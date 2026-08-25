# -*- coding: utf-8 -*-
"""验证「顶行/无空行」文件的自动分行与间距处理。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPS = os.path.join(ROOT, ".deps")
if os.path.isdir(DEPS):
    sys.path.insert(0, DEPS)

from epubforge.builder import BookMeta, build_epub  # noqa: E402
from epubforge.chapter import SegmentOptions, segment  # noqa: E402
from epubforge.sources import parse_document  # noqa: E402

OUT = os.path.join(ROOT, "test_out")
os.makedirs(OUT, exist_ok=True)


def test_wall_no_blank():
    """无空行、行尾多为逗号的长行文件 → 不应合并成一大段。"""
    lines = ["顶行测试书"]
    for ch in range(1, 11):
        lines.append(f"第{ch}章")
        for i in range(6):
            lines.append(f"这是第{ch}章第{i+1}段的内容，前后都没有空行，行尾以逗号或句号结束，"
                         f"用于验证自动分行不会把整章并成一段文字墙，编号{ch}-{i+1}。")
    path = os.path.join(OUT, "wall_no_blank.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    doc = parse_document(path)
    print(f"[无空行文件] 块数: {len(doc.blocks)}, 警告: {doc.warnings}")
    big = [b for b in doc.blocks if len(b.text) > 500]
    print(f"  超长块(>500字): {len(big)}")
    assert len(doc.blocks) >= 50, f"段落数过少({len(doc.blocks)})，疑似被合并成文字墙"
    assert not big, f"仍存在超长合并块: {big[:1]}"
    chs, notes = segment(doc, SegmentOptions(mode="auto", max_level=1))
    print(f"  分章: {len(chs)} 章")
    build_epub(chs, BookMeta(title=doc.title), os.path.join(OUT, "wall_no_blank.epub"),
               images=doc.images)
    print("  EPUB 生成 OK")


def test_long_merged_para():
    """单个 3000 字无空行段落（句号分隔）→ 自动在句末切开。"""
    sents = [f"第{i}句内容，用于凑足超长段落。这是一段完整的话，包含标点。"
             for i in range(60)]
    text = "长段测试书\n" + "".join(sents)
    path = os.path.join(OUT, "long_para.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)

    doc = parse_document(path)
    lens = [len(b.text) for b in doc.blocks]
    print(f"[超长段落文件] 块数: {len(doc.blocks)}, 最长块: {max(lens)} 字")
    assert len(doc.blocks) >= 3, "未自动切开超长段落"
    assert max(lens) <= 700, f"最长块仍 {max(lens)} 字"
    print("  超长段落已自动在句末分行 OK")


if __name__ == "__main__":
    test_wall_no_blank()
    test_long_merged_para()
    print("\n全部通过")
