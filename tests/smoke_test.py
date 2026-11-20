# -*- coding: utf-8 -*-
"""端到端冒烟测试：解析 samples/ 下所有样例 → 自动分章 → 生成 EPUB → 校验。

用法: python tests/smoke_test.py
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

from epubforge.blocks import Block  # noqa: E402
from epubforge.builder import BookMeta, build_epub  # noqa: E402
from epubforge.chapter import (  # noqa: E402
    SegmentOptions, VOLUME_PATTERNS, _detect_text_headings, segment,
)
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

        # 章节 XML 良构 + 图片引用存在性
        import posixpath
        import xml.etree.ElementTree as ET
        XHTML_NS = "{http://www.w3.org/1999/xhtml}"
        nameset = set(names)
        for ch in [n for n in names if re.search(r"text/chap\d+\.xhtml$", n)]:
            try:
                root = ET.fromstring(z.read(ch))
            except Exception as exc:
                ok = False
                print(f"    !! 章节 XML 非法 {ch}: {exc}")
                continue
            # 正文 <img src> 必须能按章节文件位置解析到包内真实文件
            # （防止图片相对路径错位回归，如漏写 ../ 前缀）
            imgs = list(root.iter(f"{XHTML_NS}img")) + list(root.iter("img"))
            for img in imgs:
                src = (img.get("src") or "").strip()
                if not src:
                    continue
                target = posixpath.normpath(posixpath.join(posixpath.dirname(ch), src))
                if target not in nameset:
                    ok = False
                    print(f"    !! 图片引用失效 {ch}: {src} → {target} 不存在")
        return ok


def check_volume_toc(path: str) -> bool:
    """校验卷/部样例的嵌套目录：nav 二级列表、NCX 嵌套 navPoint、卷扉页存在且
    卷引言并入扉页、目录卷节点指向扉页。"""
    ok = True
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        nav_name = [n for n in names if n.endswith("nav.xhtml")]
        ncx_name = [n for n in names if n.endswith(".ncx")]
        if not nav_name or not ncx_name:
            print("    !! 缺少 nav/ncx")
            return False
        nav = z.read(nav_name[0]).decode("utf-8")
        if nav.count("<ol") < 2:
            ok = False
            print("    !! nav 未出现嵌套列表（卷分组缺失）")
        if "第一部" not in nav or "第二部" not in nav:
            ok = False
            print("    !! nav 中未找到卷/部标题")
        # 卷扉页: partXXXX.xhtml 存在、含大字卷名与装饰线、卷引言并入
        part_names = sorted(n for n in names if "/part" in n and n.endswith(".xhtml"))
        if len(part_names) < 2:
            ok = False
            print(f"    !! 卷扉页数量不足（样例有 3 部，应 ≥2），实际: {part_names}")
        else:
            p1 = z.read(part_names[0]).decode("utf-8")
            if 'class="part-title"' not in p1 or 'class="part-rule"' not in p1:
                ok = False
                print("    !! 扉页缺少 part-title/part-rule 结构")
            if "北境风云始于乱世" not in p1:
                ok = False
                print("    !! 卷引言未并入扉页（卷首章应合并进扉页而非独立成章）")
            # 卷首章不应再单独存在（避免目录里卷名出现两次）
            chaps = [n for n in names
                     if n.startswith("text/chap") and n.endswith(".xhtml")]
            for cn in chaps:
                body = z.read(cn).decode("utf-8")
                if ">第一部 北境风云<" in body:
                    ok = False
                    print(f"    !! 卷首章仍独立成章: {cn}")
            # 目录卷节点指向扉页
            if part_names[0].split("/")[-1] not in nav:
                ok = False
                print("    !! nav 卷节点未指向扉页文件")
        # NCX：解析 XML，确认存在嵌套 navPoint（卷 navPoint 下挂章 navPoint）
        import xml.etree.ElementTree as ET
        ncx_ns = "{http://www.daisy.org/z3986/2005/ncx/}"
        root = ET.fromstring(z.read(ncx_name[0]))
        nested = any(len(p.findall(f"{ncx_ns}navPoint")) > 0
                     for p in root.iter(f"{ncx_ns}navPoint"))
        if not nested:
            ok = False
            print("    !! NCX 未出现嵌套 navPoint（卷分组缺失）")
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
            if not check_epub(out):
                failed += 1
                continue
            print(f"  ✓ {out} ({os.path.getsize(out):,} B)")
            vols = sorted({c.volume for c in chapters if c.volume})
            if vols:
                print(f"  卷/部分组: {len(vols)} 个 —— {' | '.join(vols)}")
            if name == "volume_novel.txt":
                if check_volume_toc(out):
                    print("  ✓ 卷嵌套目录校验通过")
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

    # ---- 附加：行尾句号标题识别（网文标题排版「第一章 xxx。」） ----
    heading_cases = [
        ("第一章  杨冰、往事回忆。", True, False),   # 尾句号+顿号+双空格
        ("第二章 舞厅", True, False),
        ("番外1", True, False),
        ("第一部 风起。", False, True),
        ("第二部 舞厅风云", False, True),
        ("第一章讲的是往事。", False, False),        # "章"后跟动词 → 正文
        ("他翻开了第一章。", False, False),          # "第"不在行首 → 正文
        ("番外正文。", False, False),                # "番外"后跟正文性汉字 → 正文(防丢内容)
        ("番外篇。", True, False),                   # "番外篇"是标题性写法 → 标题
        ("番外1", True, False),                      # 已有: 数字后缀
        ("楔子。", True, False),
        ("这是正文第一段，讲到第一章的内容。", False, False),
    ]
    try:
        ch_blocks = [Block(kind="para", text=t) for t, _, _ in heading_cases]
        ch_hits = set(_detect_text_headings(ch_blocks))
        vol_hits = set(_detect_text_headings(ch_blocks, VOLUME_PATTERNS))
        for i, (t, want_ch, want_vol) in enumerate(heading_cases):
            if (i in ch_hits) != want_ch or (i in vol_hits) != want_vol:
                failed += 1
                print(f"!! 标题识别用例失败: {t!r} 章级={i in ch_hits}(期望{want_ch})"
                      f" 卷级={i in vol_hits}(期望{want_vol})")
        if failed == 0:
            print(f"\n[标题句号回归] {len(heading_cases)} 个用例全部通过")
    except Exception as exc:
        failed += 1
        print(f"!! 标题识别用例异常: {exc}")

    # ---- 附加：硬换行重排（老式 TXT：固定宽度硬切、段间无空行） ----
    try:
        import tempfile
        hw_text = (
            "第二章\n"
            "    「今天天气不错。」老王说着把茶杯放到桌\n"
            "    子上，看向窗外。\n"
            "    「是啊，难得没有下雨。」老李点了点头，\n"
            "    心里却想着别的事。\n"
            "        「那个项目的事，你听说了吗？」老王压\n"
            "    低了声音问道。\n"
        )
        fd, hw_path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(hw_text)
        try:
            hw_doc = parse_document(hw_path)
            hw_blocks = [b.text for b in hw_doc.blocks]
            # 断言: 4 块（标题独立 + 3 个自然段），词中断行已合并
            if not any("硬换行" in w for w in hw_doc.warnings):
                failed += 1
                print(f"!! 硬换行用例: 未触发重排模式，警告={hw_doc.warnings}")
            elif len(hw_blocks) != 4:
                failed += 1
                print(f"!! 硬换行用例: 段数应为 4（标题+3段），实际 {len(hw_blocks)}: {hw_blocks}")
            else:
                if "桌子上" not in hw_blocks[1] or "茶杯放到桌子上" not in hw_blocks[1]:
                    failed += 1
                    print(f"!! 硬换行用例: 「桌/子」跨行合并失败: {hw_blocks[1][:30]}")
                if not hw_blocks[3].startswith("「那个项目的事"):
                    failed += 1
                    print(f"!! 硬换行用例: 深缩进段首未独立成段: {hw_blocks[3][:30]}")
                if hw_blocks[0] != "第二章":
                    failed += 1
                    print(f"!! 硬换行用例: 标题行未独立成段: {hw_blocks[0]!r}")
                # 拼接后不得丢字
                src_chars = len(re.sub(r"\s+", "", hw_text))
                got_chars = sum(len(t) for t in hw_blocks)
                if got_chars != src_chars:
                    failed += 1
                    print(f"!! 硬换行用例: 字数不符 源{src_chars} vs 出{got_chars}")
        finally:
            os.remove(hw_path)
        if failed == 0:
            print("[硬换行重排] 用例通过（标题独立/词中合并/深缩进分段/无丢字）")
    except Exception as exc:
        failed += 1
        print(f"!! 硬换行用例异常: {exc}")

    print(f"\n{'全部通过' if failed == 0 else f'{failed} 个失败'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run())
