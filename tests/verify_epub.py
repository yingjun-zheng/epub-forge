# -*- coding: utf-8 -*-
"""验证 EPUB 内部结构：spine idref 与 manifest id 一一对应、nav 链接、CSS 注入。"""
import re
import sys
import zipfile

path = sys.argv[1] if len(sys.argv) > 1 else "test_out/novel.epub"
with zipfile.ZipFile(path) as z:
    opf_name = [n for n in z.namelist() if n.endswith(".opf")][0]
    opf = z.read(opf_name).decode("utf-8")

    manifest = re.search(r"<manifest.*?</manifest>", opf, re.S).group(0)
    ids = re.findall(r'<item[^>]*\bid="([^"]+)"', manifest)
    spine = re.search(r"<spine.*?</spine>", opf, re.S).group(0)
    idrefs = re.findall(r'<itemref[^>]*\bidref="([^"]+)"', spine)

    print("MANIFEST ids :", ids)
    print("SPINE idrefs :", idrefs)
    ok = all(r in ids for r in idrefs)
    print("spine 引用全部合法:", ok)
    print("spine 顺序:", idrefs)

    # nav 链接
    nav_name = [n for n in z.namelist() if n.endswith("nav.xhtml")][0]
    nav = z.read(nav_name).decode("utf-8")
    hrefs = re.findall(r'href="([^"]+)"', nav)
    print("NAV hrefs    :", hrefs)
    files = set(z.namelist())
    ok2 = all(("EPUB/" + h) in files for h in hrefs)
    print("nav 链接全部存在:", ok2)

    # 章节 CSS 注入
    ch_name = [n for n in z.namelist() if re.search(r"text/chap0001", n)][0]
    ch = z.read(ch_name).decode("utf-8")
    head = re.search(r"<head>.*?</head>", ch, re.S).group(0)
    print("章节 head:", head[:220])
    print("CSS 已注入:", "main.css" in head)

    # 元数据里不应再有 ns0:generator
    print("无 ns0 命名空间污染:", "ns0:" not in opf)
    sys.exit(0 if (ok and ok2) else 1)
