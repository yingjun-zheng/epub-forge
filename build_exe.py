# -*- coding: utf-8 -*-
"""PyInstaller 打包脚本：生成独立 exe。

用法:
    python build_exe.py
产物: dist/EpubForge.exe（单文件模式，需先安装 PyInstaller）

注意: PySide6 应用建议用 onedir 模式（--onedir）以获得更快的启动速度；
本脚本默认单文件，可通过 --onedir 切换。
"""
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

HERE = os.path.abspath(os.path.dirname(__file__))


def main():
    try:
        import PyInstaller.__main__  # noqa: F401
    except ImportError:
        print("未安装 PyInstaller。请先执行: pip install pyinstaller")
        sys.exit(1)

    onedir = "--onedir" in sys.argv
    args = [
        os.path.join(HERE, "run.py"),
        "--name", "EpubForge",
        "--noconfirm",
        "--clean",
        "--windowed",                 # 不弹出控制台窗口
        "--icon", os.path.join(HERE, "assets", "app.ico") if os.path.exists(
            os.path.join(HERE, "assets", "app.ico")) else "NONE",
        "--collect-submodules", "ebooklib",
    ]
    # .deps 依赖目录加入 PyInstaller 模块搜索路径：PySide6 等依赖由 .deps
    # 提供（run.py 的 sys.path.insert 只在运行时生效，Analysis 静态扫描看
    # 不到），不加会导致 exe 启动报 ModuleNotFoundError: No module named
    # 'PySide6'。
    deps_dir = os.path.join(HERE, ".deps")
    if os.path.isdir(deps_dir):
        args += ["--paths", deps_dir]
    if onedir:
        args.append("--onedir")
    else:
        args.append("--onefile")

    # 隐藏不必要的 Qt 模块可减小体积（按需增删）
    excludes = [
        "PySide6.QtQml", "PySide6.QtQuick", "PySide6.Qt3DCore",
        "PySide6.QtMultimedia", "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick",
        "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtBluetooth",
    ]
    for e in excludes:
        args += ["--exclude-module", e]

    print("PyInstaller 参数:", " ".join(args))
    from PyInstaller.__main__ import run
    run(args)
    print("打包完成:", os.path.join(HERE, "dist", "EpubForge.exe"))


if __name__ == "__main__":
    main()
