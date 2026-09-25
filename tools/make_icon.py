# -*- coding: utf-8 -*-
"""make_icon.py — 从生成的 PNG 图标制作 assets/app.ico。

处理步骤:
  1. 修补右下角 AI 生成水印: 水印区是纯渐变背景, 对每列取上方干净行
     做最小二乘线性拟合, 沿渐变方向外推重建;
  2. 四角转透明: 生成图是白角不透明画布, 按检测到的圆角半径把角外
     区域置 alpha=0 (含 2px 羽化);
  3. 输出多尺寸 ICO (256/128/64/48/32/24/16)。

用法:
    python tools/make_icon.py <src.png> [dst.ico]
"""
import math
import os
import sys

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_white(px, x, y, thr=235):
    r, g, b = px[x, y][:3]
    return r >= thr and g >= thr and b >= thr


def detect_corner_radius(px, W):
    """用顶部若干行的首个非白像素 x_left 反解圆角半径。

    顶行 y 处圆角内背景起点 x_left = R - sqrt(2*R*y - y^2)，
    解二次方程取大根: R = (x_left + y) + sqrt(2 * x_left * y)。
    """
    rs = []
    for y in (12, 20, 30, 40):
        xl = None
        for x in range(0, W // 2):
            if not is_white(px, x, y):
                xl = x
                break
        if xl is None or xl <= y + 2:   # 无白角或太贴近边缘, 不可靠
            continue
        rs.append((xl + y) + math.sqrt(2 * xl * y))
    if not rs:
        return 145  # 检测失败用保守默认
    return max(60, min(int(round(sum(rs) / len(rs))), 260))


def fix_watermark(img, x0, y0, fit_y0, fit_y1):
    """对 [x0..W, y0..H] 区域按列做背景渐变外推 (拟合区 [fit_y0, fit_y1])。"""
    px = img.load()
    W, H = img.size
    for x in range(x0, W):
        # 拟合该列干净行的颜色线性走向: c(y) = a + b*y
        pts = [(y, px[x, y]) for y in range(fit_y0, fit_y1 + 1)
               if not is_white(px, x, y)]
        if len(pts) < 6:
            continue
        n = len(pts)
        sy = sum(p[0] for p in pts)
        sr = sum(p[1][0] for p in pts)
        sg = sum(p[1][1] for p in pts)
        sb = sum(p[1][2] for p in pts)
        syy = sum(p[0] * p[0] for p in pts)
        syr = sum(p[0] * p[1][0] for p in pts)
        syg = sum(p[0] * p[1][1] for p in pts)
        syb = sum(p[0] * p[1][2] for p in pts)
        den = n * syy - sy * sy
        if abs(den) < 1e-6:
            continue
        for ch, s_ch, s_ych in ((0, sr, syr), (1, sg, syg), (2, sb, syb)):
            pass  # 占位, 循环体内直接算
        def extrap(y):
            out = []
            for s_ch, s_ych in ((sr, syr), (sg, syg), (sb, syb)):
                b = (n * s_ych - sy * s_ch) / den
                a = (s_ch - b * sy) / n
                out.append(max(0, min(255, int(round(a + b * y)))))
            return tuple(out)
        for y in range(y0, H):
            px[x, y] = extrap(y)


def round_alpha(img, R):
    """四角按圆角半径转透明, 边缘 3px 线性羽化。返回 RGBA 图。

    只处理每个角的 (R+FE)^2 角部小方块: 方块内圆外透明, 方块外
    (边缘中段) 一律保留 —— 不能按大正方形里距角部圆心的距离切,
    否则四边中段会被误切出弧形缺口。
    """
    W, H = img.size
    rgba = img.convert("RGBA")
    alpha = Image.new("L", (W, H), 255)
    ap = alpha.load()
    FE = 3  # 羽化宽度
    # (角点x, 角点y, x方向向内, y方向向内)
    corners = [(0, 0, 1, 1), (W - 1, 0, -1, 1),
               (0, H - 1, 1, -1), (W - 1, H - 1, -1, -1)]
    for cx, cy, sx, sy in corners:
        for y in range(0, R + FE + 1):
            for x in range(0, R + FE + 1):
                d = math.hypot(x - R, y - R)   # 小方块坐标系, 圆心 (R, R)
                if d > R + FE:
                    a = 0
                elif d > R:                     # 羽化带
                    a = int(255 * (R + FE - d) / FE)
                else:
                    continue
                px_x, px_y = cx + sx * x, cy + sy * y
                if a < ap[px_x, px_y]:
                    ap[px_x, px_y] = a
    rgba.putalpha(alpha)
    return rgba


def main():
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "assets", "app.ico")
    img = Image.open(src).convert("RGB")
    W, H = img.size

    px = img.load()
    R = detect_corner_radius(px, W)
    print(f"圆角半径检测: R={R}")

    # 水印区(右下角): 修补 x>=810, y>=936; 拟合区 y 896..930 (干净背景)
    fix_watermark(img, 810, 936, 896, 930)

    rgba = round_alpha(img, R)

    os.makedirs(os.path.dirname(dst), exist_ok=True)
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (24, 24), (16, 16)]
    # bitmap_format="bmp": Pillow 12+ 默认把所有尺寸存成 PNG 压缩条目,
    # Qt 的 qico 插件解析全 PNG 条目 ico 时会直接崩溃(进程无输出退出),
    # 传统 BMP 条目全平台兼容。
    rgba.save(dst, format="ICO", sizes=sizes, bitmap_format="bmp")
    preview = os.path.join(ROOT, "docs", "icon_preview.png")
    os.makedirs(os.path.dirname(preview), exist_ok=True)
    rgba.save(preview)
    print(f"已生成: {dst}")
    print(f"预览:   {preview}")


if __name__ == "__main__":
    main()
