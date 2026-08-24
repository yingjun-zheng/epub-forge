# -*- coding: utf-8 -*-
"""检查生成 EPUB 的正文排版结构。"""
import re
import sys
import zipfile

path = sys.argv[1] if len(sys.argv) > 1 else "test_out/novel.epub"
with zipfile.ZipFile(path) as z:
    for n in z.namelist():
        if re.search(r"text/chap\d+\.xhtml$", n):
            html = z.read(n).decode("utf-8")
            body = re.search(r"<body>.*</body>", html, re.S).group(0)
            print(f"===== {n} =====")
            print(body[:1200])
            print()
            break
    # CSS 文件是否存在及其内容
    css_names = [n for n in z.namelist() if n.endswith(".css")]
    print("CSS 文件:", css_names)
    if css_names:
        css = z.read(css_names[0]).decode("utf-8")
        print("----- CSS 内容（前 600 字）-----")
        print(css[:600])
