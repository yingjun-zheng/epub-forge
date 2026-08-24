# -*- coding: utf-8 -*-
"""
fetch_deps.py — 不依赖 pip 的 Python 依赖安装器（可离线/受限环境使用）

原理：直接调用 PyPI JSON API 解析出与当前解释器兼容的 wheel，
用 urllib 下载、zipfile 解压到目标目录，并自动解析依赖（含环境标记）。

用法:
    python tools/fetch_deps.py [包名 ...]
    不带参数时安装项目默认依赖集。

输出:
    .deps/    —— 解压后的包目录（加入 sys.path 即可使用，如 python run.py）
    .wheels/  —— 下载的 wheel 文件缓存（再次运行时跳过已下载）
"""
import json
import os
import sys
import time
import urllib.request
import zipfile

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.tags import sys_tags
from packaging.utils import parse_wheel_filename

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPS_DIR = os.path.join(ROOT, ".deps")
WHEELS_DIR = os.path.join(ROOT, ".wheels")
PYPI_API = "https://pypi.org/pypi/{name}/json"
UA = "epub-forge-fetch-deps/1.0"

# 镜像备用源（官方 files.pythonhosted.org 在某些网络下不稳定）
# 每个条目替换 files.pythonhosted.org/packages/ 前缀
MIRRORS = [
    "https://mirrors.aliyun.com/pypi/packages/",
    "https://pypi.tuna.tsinghua.edu.cn/packages/",
]

# 解释器里已经可用的包（不再拉取）
PRESENT = {"lxml", "pillow", "ebooklib", "packaging", "pip", "setuptools", "wheel"}

# 默认依赖集（Windows x64 桌面版）
DEFAULT = [
    "markdown",
    "beautifulsoup4",
    "python-docx",
    "PyMuPDF",
    "PySide6-Essentials",   # QtCore/QtGui/QtWidgets，桌面 GUI 够用
    "shiboken6",            # PySide6 绑定层（自动解析，写在这里保底）
]


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def download_with_timeout(url: str, dest: str, timeout: int = 180,
                          stall_timeout: int = 45) -> bool:
    """流式下载到临时文件再原子改名；带超时、停滞看门狗与进度输出。返回是否成功。"""
    tmp = dest + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            last_pct = -1
            last_activity = time.time()
            with open(tmp, "wb") as fh:
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    fh.write(chunk)
                    got += len(chunk)
                    last_activity = time.time()
                    if total:
                        pct = got * 100 // total
                        if pct >= last_pct + 10 or pct == 100:
                            print(f"    {pct:3d}%  {got // (1 << 20)} MB / {total // (1 << 20)} MB")
                            last_pct = pct
                    # 停滞看门狗：长时间无数据则放弃本源
                    if time.time() - last_activity > stall_timeout:
                        raise OSError(f"下载停滞 {stall_timeout}s，切换镜像")
        if total and got != total:
            raise OSError(f"不完整: {got}/{total} 字节")
        os.replace(tmp, dest)
        return True
    except Exception as exc:
        print(f"[!] 下载失败: {exc}")
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def package_info(name: str) -> dict:
    return json.loads(http_get(PYPI_API.format(name=name)))


def best_wheel(data: dict):
    """返回 (wheel_info, parsed) 或 None。按兼容 tag 匹配，优先更具体的 tag。"""
    tags = set(sys_tags())
    candidates = []
    for f in data.get("urls", []):
        if not f["filename"].endswith(".whl"):
            continue
        try:
            parsed = parse_wheel_filename(f["filename"])
        except Exception:
            continue
        if parsed[3] & tags:  # frozenset of tags intersect environment tags
            candidates.append((f, parsed))
    if not candidates:
        return None
    # 越具体（tag 少、针对性强）的越靠前：文件名越长越具体
    candidates.sort(key=lambda c: len(c[0]["filename"]), reverse=True)
    return candidates[0]


def fetch(name: str, seen: set):
    """递归拉取并解压 name 及其依赖。"""
    key = name.lower()
    if key in seen or key in PRESENT:
        return
    seen.add(key)

    data = package_info(name)
    hit = best_wheel(data)
    if hit is None:
        print(f"[!!] {name}: 无兼容 wheel")
        return
    f, parsed = hit
    whl = os.path.join(WHEELS_DIR, f["filename"])
    os.makedirs(WHEELS_DIR, exist_ok=True)

    # 下载 + 完整性校验 + 重试（镜像优先，官方源作兜底——部分网络下官方源会停滞）
    candidates = [
        f["url"].replace("https://files.pythonhosted.org/packages/", m) for m in MIRRORS
    ] + [f["url"]]
    tries = 3
    while tries > 0 and not (os.path.exists(whl) and zipfile.is_zipfile(whl)):
        if os.path.exists(whl):
            os.remove(whl)
        print(f"[..] 下载 {f['filename']} (剩余尝试 {tries})")
        for u in candidates:
            if download_with_timeout(u, whl):
                print("    校验通过")
                break
        tries -= 1
    if not zipfile.is_zipfile(whl):
        print(f"[!!] {name}: wheel 下载多次失败，跳过")
        return

    print(f"[ok] 缓存命中 {f['filename']}")
    os.makedirs(DEPS_DIR, exist_ok=True)
    with zipfile.ZipFile(whl) as z:
        z.extractall(DEPS_DIR)
    print(f"[ok] 解压 {parsed[0]} {parsed[1]}")

    # 递归处理依赖：解析 marker，剔除不适用于本环境的
    # 注意: requires_dist 位于 PyPI JSON 的顶层 info 中（urls 条目里没有）
    env = default_environment()
    for dep_str in data.get("info", {}).get("requires_dist") or []:
        try:
            req = Requirement(dep_str)
        except Exception:
            continue
        if req.marker is not None and not req.marker.evaluate(env):
            continue
        if req.name.lower() in PRESENT:
            continue
        fetch(req.name, seen)


def main():
    names = sys.argv[1:] or DEFAULT
    seen = set()
    for n in names:
        fetch(n, seen)
    print("\n完成。依赖目录:", DEPS_DIR)
    print("运行应用: python run.py")


if __name__ == "__main__":
    main()
