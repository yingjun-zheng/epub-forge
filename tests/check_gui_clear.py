# -*- coding: utf-8 -*-
"""GUI 表单清除逻辑测试。"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPS = os.path.join(ROOT, ".deps")
if os.path.isdir(DEPS):
    sys.path.insert(0, DEPS)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from epubforge.chapter import SegmentOptions  # noqa: E402
from epubforge.gui import MainWindow, _analyze_task  # noqa: E402

# 打桩所有模态弹窗，避免阻塞（含静态方法 information/warning/critical）
QMessageBox.exec = lambda self: 0  # noqa: E731
QMessageBox.information = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.warning = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)
QMessageBox.critical = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Ok)

SAMPLES = os.path.join(ROOT, "samples")


def ok(cond, msg):
    print(("  ✓ " if cond else "  ✗ ") + msg)
    return bool(cond)


def main():
    app = QApplication([])
    w = MainWindow()
    fails = 0

    # 1) 分析 novel.txt → 自动填充书名
    doc, chs, notes = _analyze_task(os.path.join(SAMPLES, "novel.txt"),
                                    SegmentOptions(mode="auto", max_level=1), "auto",
                                    lambda p, m: None)
    w.source_path = os.path.join(SAMPLES, "novel.txt")  # 模拟真实流程中 _set_source 已设置
    w._on_analyzed((doc, chs, notes))
    fails += 0 if ok(w.title_edit.text() == "雾隐山庄",
                     f"分析后自动填充书名 {w.title_edit.text()!r}") else 1
    w.author_edit.setText("旧作者")
    w.publisher_edit.setText("旧出版社")
    w.desc_edit.setPlainText("旧简介")
    w.cover_edit.setText("C:/old/cover.png")
    fails += 0 if ok(bool(w.chapter_list.count()), "章节列表非空") else 1

    # 2) 选择新文件 guide.md → 上次填写的内容被清空
    w._set_source(os.path.join(SAMPLES, "guide.md"))
    fails += 0 if ok(w.title_edit.text() == "", "新文件清空旧书名") else 1
    fails += 0 if ok(w.author_edit.text() == "", "新文件清空旧作者") else 1
    fails += 0 if ok(w.publisher_edit.text() == "", "新文件清空旧出版社") else 1
    fails += 0 if ok(w.desc_edit.toPlainText() == "", "新文件清空旧简介") else 1
    fails += 0 if ok(w.cover_edit.text() == "", "新文件清空旧封面") else 1
    fails += 0 if ok(w.chapter_list.count() == 0, "新文件清空章节列表") else 1
    fails += 0 if ok(w.source_path == os.path.join(SAMPLES, "guide.md"), "源文件已切换") else 1
    # 等后台分析线程结束，避免影响后续断言
    if w.worker:
        w.worker.wait(10000)
    app.processEvents()

    # 3) 重新选择同一个文件 → 不清空（保留用户编辑）
    w.title_edit.setText("用户手填书名")
    w._set_source(os.path.join(SAMPLES, "guide.md"))
    fails += 0 if ok(w.title_edit.text() == "用户手填书名", "同一文件不清空用户输入") else 1

    # 4) 生成成功后 → 全部清空（含源文件）
    w.title_edit.setText("测试")
    w._on_built(os.path.join(ROOT, "test_out", "novel.epub"))
    fails += 0 if ok(w.source_path == "", "生成后清空源文件") else 1
    fails += 0 if ok(w.title_edit.text() == "", "生成后清空书名") else 1
    fails += 0 if ok(w.chapter_list.count() == 0, "生成后清空章节") else 1
    fails += 0 if ok(not w.gen_btn.isEnabled(), "生成按钮禁用") else 1

    if w.worker and w.worker.isRunning():
        w.worker.wait(5000)

    print(f"\n结果: {'全部通过' if fails == 0 else f'{fails} 项失败'}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
