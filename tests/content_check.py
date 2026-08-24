# -*- coding: utf-8 -*-
"""内容完整性测试：大文档转换后，逐条核对源文档中的标记是否全部出现在 EPUB 里。

用法: python tests/content_check.py
"""
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPS = os.path.join(ROOT, ".deps")
if os.path.isdir(DEPS):
    sys.path.insert(0, DEPS)

from epubforge.builder import BookMeta, build_epub  # noqa: E402
from epubforge.chapter import SegmentOptions, segment  # noqa: E402
from epubforge.sources import parse_document  # noqa: E402

OUT = os.path.join(ROOT, "test_out")


def make_big_txt(path: str):
    """40 章 × 4 段，每段带唯一标记。"""
    parts = ["大测试文档"]
    for ch in range(1, 41):
        parts.append(f"第{ch}章 章节{ch}")
        for para in range(1, 5):
            parts.append(f"【标记】章{ch}-段{para}：这是第{ch}章第{para}段的内容，"
                         f"用于验证转换过程中没有内容丢失。编号为{ch:02d}{para:02d}。")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(parts) + "\n\n（全书完）\n")


def extract_epub_text(path: str) -> str:
    """把 EPUB 所有章节 XHTML 的正文拼出来。"""
    chunks = []
    with zipfile.ZipFile(path) as z:
        for n in sorted(z.namelist()):
            if re.search(r"text/chap\d+\.xhtml$", n):
                html = z.read(n).decode("utf-8")
                body = re.search(r"<body>(.*)</body>", html, re.S)
                if body:
                    # 剥掉标签，保留文本
                    text = re.sub(r"<[^>]+>", "", body.group(1))
                    chunks.append(text)
    return "".join(chunks)


def check(source_path: str, epub_path: str, label: str) -> int:
    doc = parse_document(source_path)
    chs, notes = segment(doc, SegmentOptions(mode="auto", max_level=1))
    meta = BookMeta(title=doc.title or label)
    build_epub(chs, meta, epub_path, images=doc.images)

    src_text = open(source_path, encoding="utf-8").read()
    epub_text = extract_epub_text(epub_path)

    # 1) 全部标记必须出现在 EPUB 中
    markers = re.findall(r"【标记】章\d+-段\d+", src_text)
    missing = [m for m in markers if m not in epub_text]
    # 2) 末尾标记必须出现
    last = markers[-1] if markers else None
    # 3) 字符量对比（忽略空白差异）
    src_chars = len(re.sub(r"\s", "", src_text))
    epub_chars = len(re.sub(r"\s", "", epub_text))

    print(f"\n===== {label} =====")
    print(f"  源文件标记数: {len(markers)}, EPUB 缺失: {len(missing)}")
    if missing:
        print(f"    !! 缺失标记样例: {missing[:10]}")
    print(f"  末尾标记 {last}: {'存在' if last and last in epub_text else '丢失!!'}")
    print(f"  源字符数: {src_chars}, EPUB 字符数: {epub_chars}, 差: {epub_chars - src_chars}")
    return 1 if (missing or (last and last not in epub_text)) else 0


def main():
    os.makedirs(OUT, exist_ok=True)
    txt = os.path.join(OUT, "big_source.txt")
    make_big_txt(txt)
    failed = check(txt, os.path.join(OUT, "big_novel.epub"), "大 TXT（40 章）")
    print("\n结果:", "通过" if failed == 0 else "存在内容丢失！")
    return failed


if __name__ == "__main__":
    sys.exit(main())
