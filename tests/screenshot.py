# -*- coding: utf-8 -*-
"""离屏渲染 GUI 截图（供 README 使用）。

用法: python tests/screenshot.py [输出.png]
需要 PySide6 就绪；无桌面环境也可用（offscreen 平台）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPS = os.path.join(ROOT, ".deps")
if os.path.isdir(DEPS):
    sys.path.insert(0, DEPS)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from epubforge.gui import MainWindow  # noqa: E402


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs", "gui.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    app = QApplication([])
    win = MainWindow()
    win.show()
    app.processEvents()
    win.grab().save(out)
    print("截图已保存:", out)


if __name__ == "__main__":
    main()
