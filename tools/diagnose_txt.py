# -*- coding: utf-8 -*-
"""diagnose_txt.py — TXT 分章诊断（脱敏：不输出任何正文内容）。

复用 epubforge 真实解析链，输出：
  * 段落模式、块数、书名推断是否吞了首行
  * 章级 / 卷级正则各命中多少、位于哪些块序号
  * 疑似漏网的卷标题行：只打印特征（长度 / 首"第" / 前缀括号 / 尾标点）与未命中原因

用法:
    python tools/diagnose_txt.py <txt路径> [auto|blank|line]

所有输出均为布尔特征与计数，无原文，可放心粘贴给他人分析。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, ".deps"))
sys.path.insert(0, ROOT)

from epubforge.chapter import (  # noqa: E402
    MAX_TITLE_LEN, TEXT_HEADING_PATTERNS, VOLUME_PATTERNS, _detect_text_headings,
    _SENT_END,
)
from epubforge.sources import parse_document  # noqa: E402

_BRACKET_PREFIX = re.compile(r"^[【\[（(「『“\"']")
_VOL_WORDS = ("卷", "部", "册")


def mask_features(line: str) -> str:
    """行 → 脱敏特征串（不包含任何原文）。"""
    return (f"len={len(line)}"
            f' 首"第"={"是" if line.startswith("第") else "否"}'
            f' 前缀括号={"是" if _BRACKET_PREFIX.match(line) else "否"}'
            f' 尾标点={"是" if line.endswith(_SENT_END) else "否"}'
            f' 多行={"是" if "\\n" in line else "否"}')


def miss_reason(line: str) -> str:
    """疑似卷标题但未命中的原因分类。"""
    if len(line) > MAX_TITLE_LEN:
        return f"超过 {MAX_TITLE_LEN} 字上限 —— 疑似标题与正文粘连在同一行"
    if line.endswith(_SENT_END):
        return "行尾是标点 —— 被当作正文句子跳过"
    if _BRACKET_PREFIX.match(line):
        return '前缀括号/书名号挡住"第"字 —— 卷正则要求"第"必须行首（章级序章条目支持前缀，卷级不支持）'
    if any(w in line and "第" not in line for w in _VOL_WORDS):
        return "含卷/部/册字样但无\"第\"字（如「卷一」「上册」），部分写法未被正则覆盖"
    return "写法未被卷正则覆盖（需看特征或用自定义正则）"


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    path = sys.argv[1]
    para_mode = sys.argv[2] if len(sys.argv) > 2 else "auto"

    doc = parse_document(path, txt_para_mode=para_mode)
    blocks = doc.blocks
    print(f"[解析] 模式={para_mode} 块数={len(blocks)} 图片={len(doc.images)}")
    for w in doc.warnings:
        print(f"[警告] {w}")

    vol_hits = _detect_text_headings(blocks, VOLUME_PATTERNS)
    ch_hits = _detect_text_headings(blocks)
    print(f"[卷探测] 命中 {len(vol_hits)} 个 → 块序号 {vol_hits[:20]}"
          f"{' ...(截断)' if len(vol_hits) > 20 else ''}")
    print(f"[章探测] 命中 {len(ch_hits)} 个 → 块序号 {ch_hits[:20]}"
          f"{' ...(截断)' if len(ch_hits) > 20 else ''}")
    if len(vol_hits) >= 2:
        print("[结构] 卷数 ≥2，将启用两级目录（卷分组）。")
    elif len(vol_hits) == 1:
        print("[结构] 仅 1 个卷标题 → 不启用卷分组，该卷并入章平铺（这可能就是『另一部没分组』的直接原因）。")

    # 疑似漏网的卷标题行：单行、含卷/部/册、且行较短
    print("\n[漏网筛查] 含卷/部/册字样的短单行（未命中卷正则的）:")
    found = False
    for i, b in enumerate(blocks):
        line = b.text.strip()
        if b.kind not in ("para", "heading") or "\n" in line:
            continue
        if len(line) > MAX_TITLE_LEN + 40 or not any(w in line for w in _VOL_WORDS):
            continue
        if any(p.search(line) for p in VOLUME_PATTERNS):
            continue  # 已命中的不用报
        # 排除明显是正文的长句（以句末标点结尾且很长）
        if len(line) > 60 and line.endswith(_SENT_END):
            continue
        found = True
        hit_ch = "【会被当章标题】" if any(p.search(line) for p in TEXT_HEADING_PATTERNS) else ""
        print(f"  块#{i} {mask_features(line)} → {miss_reason(line)} {hit_ch}")
    if not found:
        print("  （无）—— 所有含卷部字样的短行都已命中或不存在")

    # 番外/楔子等特殊标题的命中情况（只报计数与序号）
    special = re.compile(r"番外|楔子|序章|尾声|终章|后记")
    sp_blocks = [i for i, b in enumerate(blocks)
                 if b.kind in ("para", "heading") and special.search(b.text)]
    if sp_blocks:
        ok = [i for i in sp_blocks if i in ch_hits]
        miss = [i for i in sp_blocks if i not in ch_hits]
        print(f"\n[特殊标题] 含番外/楔子/序章等字样的块: {sp_blocks}")
        print(f"  被章正则命中: {ok if ok else '无'}")
        if miss:
            for i in miss[:10]:
                line = blocks[i].text.strip()
                print(f"  未命中 块#{i} {mask_features(line)} → {miss_reason(line)}")


if __name__ == "__main__":
    main()
