# -*- coding: utf-8 -*-
"""Epub Forge 启动器（GUI / CLI 双模式）。

自动把本地依赖目录 .deps 加入 sys.path（无需 pip 安装），再启动。
用法:
    python run.py                  # 图形界面
    python run.py in.docx -o out.epub --author 张三   # 命令行转换
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
DEPS = os.path.join(ROOT, ".deps")

if os.path.isdir(DEPS) and DEPS not in sys.path:
    sys.path.insert(0, DEPS)
    pyside_pkg = os.path.join(DEPS, "PySide6")
    if os.path.isdir(pyside_pkg):
        os.environ.setdefault("PATH", pyside_pkg + os.pathsep + os.environ.get("PATH", ""))


def _cli_progress(pct: float, msg: str):
    print(f"    {pct:3.0f}%  {msg}")


def _cli_main(argv):
    # Windows 默认 GBK 控制台：强制 UTF-8 输出避免中文乱码
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    from epubforge import logutil
    from epubforge.builder import BookMeta, build_epub
    from epubforge.chapter import SegmentOptions, segment
    from epubforge.sources import parse_document
    from epubforge.utils import human_size

    p = argparse.ArgumentParser(prog="epubforge", description="多格式文档转 EPUB3")
    p.add_argument("input", help="源文档 (.txt/.md/.html/.docx/.pdf)")
    p.add_argument("-o", "--output", help="输出 .epub 路径（默认源文件同目录）")
    p.add_argument("-t", "--title", help="书名（默认自动推断）")
    p.add_argument("-a", "--author", default="", help="作者")
    p.add_argument("-p", "--publisher", default="", help="出版社")
    p.add_argument("-l", "--lang", default="zh", help="语言代码（默认 zh）")
    p.add_argument("--desc", default="", help="简介")
    p.add_argument("--cover", default="", help="封面图片路径")
    p.add_argument("--mode", default="auto", choices=["auto", "heading", "regex", "size"],
                   help="分章模式（默认 auto）")
    p.add_argument("--max-level", type=int, default=1, help="标题级别上限，0=不限（默认 1）")
    p.add_argument("--regex", default="", help="自定义章节正则（--mode regex 时生效）")
    p.add_argument("--paras", type=int, default=8, help="按篇幅时每章段落数（默认 8）")
    p.add_argument("--min-chars", type=int, default=500, help="少于该字数不分章（默认 500）")
    p.add_argument("--txt-paras", default="auto", choices=["auto", "blank", "line"],
                   help="TXT 分段方式：auto 自动 / blank 空行分段 / line 每行一段（默认 auto）")
    p.add_argument("--ocr", action="store_true",
                   help="扫描版 PDF 启用 OCR 识别（无文字层时，速度较慢）")
    p.add_argument("--no-split", action="store_true",
                   help="不分章：整本作为一章")
    args = p.parse_args(argv)

    print(f"[1/3] 解析 {args.input} …")
    logutil.log(f"CLI 转换开始: {args.input} (mode={args.mode}, ocr={args.ocr})")
    doc = parse_document(args.input, txt_para_mode=args.txt_paras,
                         ocr=args.ocr, progress_cb=_cli_progress)
    opts = SegmentOptions(mode=args.mode, max_level=args.max_level,
                          custom_regex=args.regex, paras_per_chunk=args.paras,
                          min_chars=args.min_chars, no_split=args.no_split)
    print(f"[2/3] 分章（{opts.mode}）…")
    chapters, notes = segment(doc, opts)
    for n in notes:
        print("    -", n)
    volumes = list(dict.fromkeys(c.volume for c in chapters if c.volume))
    if volumes:
        head = " / ".join(volumes[:5]) + ("…" if len(volumes) > 5 else "")
        print(f"    识别到 {len(volumes)} 个卷/部（目录将按卷分组）：{head}")
    for w in doc.warnings:
        print("    !", w)
    if not chapters:
        print("错误: 没有可转换的内容。")
        return 2

    if args.output:
        out_path = args.output
    else:
        stem = os.path.splitext(os.path.basename(args.input))[0]
        out_path = os.path.join(os.path.dirname(os.path.abspath(args.input)), f"{stem}.epub")
    if not out_path.lower().endswith(".epub"):
        out_path += ".epub"

    cover_bytes, cover_name = None, "cover.jpg"
    if args.cover and os.path.isfile(args.cover):
        with open(args.cover, "rb") as f:
            cover_bytes = f.read()
        cover_name = f"cover.{os.path.splitext(args.cover)[1].lstrip('.').lower() or 'jpg'}"

    meta = BookMeta(title=args.title or doc.title, author=args.author, lang=args.lang,
                    publisher=args.publisher, description=args.desc)
    print(f"[3/3] 生成 EPUB（{len(chapters)} 章）…")
    last = {"v": 0}

    def cb(pct, msg):
        if pct - last["v"] >= 10 or pct == 100:
            print(f"    {pct:3.0f}%  {msg}")
            last["v"] = pct

    build_epub(chapters, meta, out_path, images=doc.images,
               cover_bytes=cover_bytes, cover_name=cover_name, progress_cb=cb)
    logutil.log(f"CLI 转换完成: {out_path}（{human_size(os.path.getsize(out_path))}，{len(chapters)} 章）")
    print(f"完成: {out_path}（{human_size(os.path.getsize(out_path))}）")
    return 0


def main():
    if len(sys.argv) > 1:
        sys.exit(_cli_main(sys.argv[1:]))
    from epubforge.gui import main as gui_main
    gui_main()


if __name__ == "__main__":
    main()
