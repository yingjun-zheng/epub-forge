# -*- coding: utf-8 -*-
"""端到端冒烟测试：解析 samples/ 下所有样例 → 自动分章 → 生成 EPUB → 校验。

用法: python tests/smoke_test.py
"""
import os
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

SAMPLES = os.path.join(ROOT, "samples")
OUT = os.path.join(ROOT, "test_out")


def check_epub(path: str) -> bool:
    """校验 EPUB：zip 完整性、EPUB 结构、spine idref ↔ manifest id、nav 链接、章节 XML 良构。"""
    import re
    if not os.path.isfile(path):
        print(f"    !! 文件不存在: {path}")
        return False
    ok = True
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        bad = z.testzip()
        if bad:
            print(f"    !! 损坏: {bad}")
            return False
        ok = any(n == "META-INF/container.xml" for n in names) and any(
            n.endswith(".opf") for n in names)
        if not ok:
            print(f"    !! 缺少 EPUB 结构: {names[:10]}")
            return False

        opf_name = [n for n in names if n.endswith(".opf")][0]
        opf = z.read(opf_name).decode("utf-8")
        manifest = re.search(r"<manifest.*?</manifest>", opf, re.S)
        spine = re.search(r"<spine.*?</spine>", opf, re.S)
        if manifest and spine:
            ids = set(re.findall(r'<item[^>]*\bid="([^"]+)"', manifest.group(0)))
            idrefs = re.findall(r'<itemref[^>]*\bidref="([^"]+)"', spine.group(0))
            missing = [r for r in idrefs if r not in ids]
            if missing:
                ok = False
                print(f"    !! spine 引用了不存在的 id: {missing}")

        # nav 链接存在性
        nav_name = [n for n in names if n.endswith("nav.xhtml")]
        if nav_name:
            nav = z.read(nav_name[0]).decode("utf-8")
            hrefs = re.findall(r'href="([^"]+)"', nav)
            missing = [h for h in hrefs if ("EPUB/" + h) not in names]
            if missing:
                ok = False
                print(f"    !! nav 链接指向不存在的文件: {missing}")

        # 章节 XML 良构
        import xml.etree.ElementTree as ET
        for ch in [n for n in names if re.search(r"text/chap\d+\.xhtml$", n)]:
            try:
                ET.fromstring(z.read(ch))
            except Exception as exc:
                ok = False
                print(f"    !! 章节 XML 非法 {ch}: {exc}")
        return ok


def run():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    os.makedirs(OUT, exist_ok=True)
    samples = sorted(
        f for f in os.listdir(SAMPLES)
        if f.endswith((".txt", ".md", ".html", ".docx", ".pdf")))
    if not samples:
        print("!! samples/ 为空，先运行: python tests/make_samples.py")
        return 2

    failed = 0
    for name in samples:
        src = os.path.join(SAMPLES, name)
        print(f"\n===== {name} =====")
        try:
            doc = parse_document(src)
            print(f"  解析: {len(doc.blocks)} 块, 标题={doc.title!r}, "
                  f"图片={len(doc.images)}, 警告={len(doc.warnings)}")
            for w in doc.warnings:
                print(f"    ! {w}")

            opts = SegmentOptions(mode="auto", max_level=1)
            chapters, notes = segment(doc, opts)
            for n in notes:
                print(f"    - {n}")
            total = sum(c.text_len for c in chapters)
            print(f"  分章: {len(chapters)} 章, 共 {total:,} 字")
            for i, c in enumerate(chapters[:6], 1):
                print(f"    {i}. {c.title}  ({c.block_count} 块, {c.text_len} 字)")
            if len(chapters) > 6:
                print(f"    ... 共 {len(chapters)} 章")

            out = os.path.join(OUT, f"{os.path.splitext(name)[0]}.epub")
            meta = BookMeta(title=doc.title or name, author="冒烟测试", lang="zh")
            build_epub(chapters, meta, out, images=doc.images)
            if check_epub(out):
                print(f"  ✓ {out} ({os.path.getsize(out):,} B)")
            else:
                failed += 1
        except Exception as exc:
            import traceback
            failed += 1
            print(f"  !! 失败: {exc}")
            traceback.print_exc()

    # ---- 附加：其它分章模式 ----
    txt = os.path.join(SAMPLES, "novel.txt")
    if os.path.exists(txt):
        try:
            doc = parse_document(txt)
            for mode, opts in [
                ("regex", SegmentOptions(mode="regex", custom_regex=r"^第[一二三四五六七八九十]+章")),
                ("size", SegmentOptions(mode="size", paras_per_chunk=2)),
                ("heading", SegmentOptions(mode="heading", max_level=1)),
                ("no_split", SegmentOptions(mode="auto", no_split=True)),
            ]:
                chs, notes = segment(doc, opts)
                titles = " | ".join(c.title for c in chs)
                print(f"\n[模式 {mode}] {len(chs)} 章: {titles[:100]}")
                if mode == "no_split" and len(chs) != 1:
                    failed += 1
                    print(f"!! no_split 应只有 1 章，实际 {len(chs)}")
        except Exception as exc:
            failed += 1
            print(f"!! 附加模式测试失败: {exc}")

    print(f"\n{'全部通过' if failed == 0 else f'{failed} 个失败'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
