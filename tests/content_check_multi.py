# -*- coding: utf-8 -*-
"""多格式内容完整性测试：PDF / DOCX / GBK-TXT。"""
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
os.makedirs(OUT, exist_ok=True)


def extract_epub_text(path: str) -> str:
    chunks = []
    with zipfile.ZipFile(path) as z:
        for n in sorted(z.namelist()):
            if re.search(r"text/chap\d+\.xhtml$", n):
                html = z.read(n).decode("utf-8")
                body = re.search(r"<body>(.*)</body>", html, re.S)
                if body:
                    chunks.append(re.sub(r"<[^>]+>", "", body.group(1)))
    return "".join(chunks)


def run_check(label, src_path, markers, tail_marker, expected_chars):
    print(f"\n===== {label} =====")
    try:
        doc = parse_document(src_path)
        chs, notes = segment(doc, SegmentOptions(mode="auto", max_level=1))
        epub_path = os.path.join(OUT, f"big_{label}.epub")
        build_epub(chs, BookMeta(title=doc.title), epub_path, images=doc.images)
        text = extract_epub_text(epub_path)
        missing = [m for m in markers if m not in text]
        print(f"  标记总数: {len(markers)}, 缺失: {len(missing)}")
        if missing:
            print(f"    !! 缺失样例: {missing[:8]}")
        print(f"  末尾标记 {tail_marker}: {'存在' if tail_marker in text else '丢失!!'}")
        print(f"  期望字符数≈{expected_chars}, EPUB 字符数: {len(re.sub(chr(92)+'s', '', text))}")
        return 1 if (missing or tail_marker not in text) else 0
    except Exception as exc:
        print(f"  !! 失败: {exc}")
        return 1


def main():
    import docx
    import pymupdf as fitz

    failed = 0

    # ---- 1) 长 DOCX：15 章 × 4 段 ----
    d = docx.Document()
    markers = []
    for ch in range(1, 16):
        d.add_heading(f"第{ch}章 章节{ch}", level=1)
        for para in range(1, 5):
            m = f"【标记】章{ch}-段{para}"
            markers.append(m)
            d.add_paragraph(f"{m}：这是第{ch}章第{para}段的内容，用于验证转换完整性。")
    docx_path = os.path.join(OUT, "big_source.docx")
    d.save(docx_path)
    failed += run_check("DOCX15", docx_path, markers, "【标记】章15-段4", 5000)

    # ---- 2) 长 PDF：15 页，每页一段 + 书签 ----
    pdf = fitz.open()
    toc = []
    pdf_markers = []
    for ch in range(1, 16):
        page = pdf.new_page()
        page.insert_textbox(fitz.Rect(72, 72, 540, 120), f"第{ch}章",
                            fontsize=22, fontname="china-s")
        m = f"【标记】PDF章{ch}-段1"
        pdf_markers.append(m)
        page.insert_textbox(fitz.Rect(72, 150, 540, 500),
                            f"{m}：这是 PDF 第{ch}章的内容，用于验证转换完整性。",
                            fontsize=12, fontname="china-s")
        toc.append([1, f"第{ch}章", ch])
    pdf.set_toc(toc)
    pdf_path = os.path.join(OUT, "big_source.pdf")
    pdf.save(pdf_path)
    pdf.close()
    failed += run_check("PDF15", pdf_path, pdf_markers, "【标记】PDF章15-段1", 4000)

    # ---- 3) GBK 编码 TXT：30 章 ----
    gbk_markers = []
    lines = ["GBK测试书"]
    for ch in range(1, 31):
        lines.append(f"第{ch}章 章节{ch}")
        for para in range(1, 4):
            m = f"【标记】GBK章{ch}-段{para}"
            gbk_markers.append(m)
            lines.append(f"{m}：这是 GBK 编码第{ch}章第{para}段的内容。")
    gbk_path = os.path.join(OUT, "big_source_gbk.txt")
    with open(gbk_path, "w", encoding="gb18030") as f:
        f.write("\n\n".join(lines))
    failed += run_check("GBK_TXT30", gbk_path, gbk_markers, "【标记】GBK章30-段3", 6000)

    # ---- 4) 结尾是「全文完」的 TXT（无空行，逐行排布） ----
    tail_markers = []
    tlines = ["结尾测试书"]
    for ch in range(1, 21):
        tlines.append(f"第{ch}章")
        for para in range(1, 4):
            m = f"【标记】尾章{ch}-段{para}"
            tail_markers.append(m)
            tlines.append(f"{m}：这是第{ch}章第{para}段。")
    tlines.append("（全文完）")
    tail_path = os.path.join(OUT, "big_source_tail.txt")
    with open(tail_path, "w", encoding="utf-8") as f:
        f.write("\n".join(tlines))  # 无空行！
    failed += run_check("TAIL_TXT20", tail_path, tail_markers, "（全文完）", 4000)

    print(f"\n结果: {'全部通过' if failed == 0 else f'{failed} 项失败'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
