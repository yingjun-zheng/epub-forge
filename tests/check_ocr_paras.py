# -*- coding: utf-8 -*-
"""检查 OCR 子集 EPUB 的段落分隔情况。"""
import re
import sys
import zipfile

path = sys.argv[1] if len(sys.argv) > 1 else "test_out/scan_subset.epub"
with zipfile.ZipFile(path) as z:
    for n in sorted(z.namelist()):
        if re.search(r"text/chap\d+\.xhtml$", n):
            h = z.read(n).decode("utf-8")
            ps = re.findall(r'<p class="para"[^>]*>(.*?)</p>', h, re.S)
            print(f"章节 {n}: {len(ps)} 个段落")
            for p in ps[:8]:
                t = re.sub(r"<[^>]+>", "", p).strip()
                print("   ", t[:44])
            if len(ps) >= 3:
                break
