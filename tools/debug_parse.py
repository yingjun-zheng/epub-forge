# -*- coding: utf-8 -*-
"""调试工具：分析源文件解析结果，定位内容丢失问题。

用法:
    python tools/debug_parse.py 你的文件.txt [--txt-paras auto|blank|line]

输出: 编码、行数、块数、字数、完整性警告、开头/末尾块、章节列表。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPS = os.path.join(ROOT, ".deps")
if os.path.isdir(DEPS):
    sys.path.insert(0, DEPS)

from epubforge.chapter import SegmentOptions, segment  # noqa: E402
from epubforge.sources import parse_document  # noqa: E402
from epubforge.utils import read_text_with_fallback  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print("用法: python tools/debug_parse.py <文件> [--txt-paras auto|blank|line]")
        return 1
    path = sys.argv[1]
    txt_mode = "auto"
    if "--txt-paras" in sys.argv:
        i = sys.argv.index("--txt-paras")
        if i + 1 < len(sys.argv):
            txt_mode = sys.argv[i + 1]

    print(f"文件: {path}  ({os.path.getsize(path):,} 字节)")
    enc = ""
    if path.lower().endswith((".txt", ".md", ".markdown", ".html", ".htm", ".xhtml")):
        try:
            _, enc = read_text_with_fallback(path)
            print(f"检测编码: {enc}")
        except Exception as e:
            print(f"编码探测失败: {e}")

    doc = parse_document(path, txt_para_mode=txt_mode)
    print(f"\n标题: {doc.title!r}")
    print(f"格式: {doc.fmt} | 块数: {len(doc.blocks)} | 解析字数: {doc.total_text_len}")
    print(f"警告({len(doc.warnings)}):")
    for w in doc.warnings:
        print(f"  ! {w}")

    print("\n开头 3 块:")
    for b in doc.blocks[:3]:
        print(f"  [{b.kind}] {b.text[:50]!r}")
    print("\n末尾 5 块（重点检查这里！）:")
    for b in doc.blocks[-5:]:
        print(f"  [{b.kind}] {b.text[:60]!r}")

    chs, notes = segment(doc, SegmentOptions(mode="auto", max_level=1))
    print(f"\n分章: {len(chs)} 章")
    for n in notes:
        print(f"  - {n}")
    print("章节列表（首 3 + 末 3）:")
    show = chs[:3] + (["..."] if len(chs) > 6 else []) + chs[-3:]
    for c in show:
        if isinstance(c, str):
            print("  ...")
        else:
            print(f"  {c.title!r}  ({c.block_count} 块, {c.text_len} 字)")
    if chs:
        last = chs[-1]
        print(f"\n末章「{last.title}」的末尾 2 块:")
        for b in last.blocks[-2:]:
            print(f"  [{b.kind}] {b.text[:60]!r}")
    print("\n如果上面末尾块能看到（全书完）等内容，说明解析完整——问题在阅读器；")
    print("如果末尾块缺失，把本输出贴给作者以便定位。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
