# -*- coding: utf-8 -*-
"""检查用户 PDF 的结构：页数、文字层、书签大纲、每页文本量。"""
import pymupdf as fitz

path = r"C:\Users\zhengyingjun\Documents\deepseek\epub-forge\军事地形学.pdf"
doc = fitz.open(path)
print("页数:", doc.page_count)
print("元数据:", {k: v for k, v in (doc.metadata or {}).items() if v})

toc = doc.get_toc()
print(f"书签条数: {len(toc)}")
from collections import Counter
lvl_cnt = Counter(t[0] for t in toc)
print("书签级别分布:", dict(lvl_cnt))
print("书签样例(前12):", toc[:12])
print("书签样例(后6):", toc[-6:])

# 每页文本量统计
empty_pages = 0
total_chars = 0
sample = []
for pno in range(doc.page_count):
    t = doc[pno].get_text("text")
    n = len(t.strip())
    total_chars += n
    if n == 0:
        empty_pages += 1
    if pno < 5 or pno >= doc.page_count - 3:
        sample.append((pno + 1, n, t.strip()[:60].replace("\n", " ")))
print(f"\n总文本字符: {total_chars}, 空页: {empty_pages}/{doc.page_count}")
for pno, n, head in sample:
    print(f"  第{pno}页: {n} 字 | {head!r}")

# 图片数量
img_count = 0
for pno in range(min(doc.page_count, 20)):
    img_count += len(doc[pno].get_images())
print(f"\n前20页图片对象数: {img_count} (扫描版特征)")

# 页面尺寸
p0 = doc[0]
print("页面尺寸:", p0.rect)
doc.close()
