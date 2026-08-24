@echo off
rem Epub Forge 启动脚本（双击运行）
cd /d "%~dp0"

rem 使用项目自带的本地依赖（无需 pip 安装）
if exist ".deps\PySide6" (
    set "PYTHONPATH=%CD%;%CD%\.deps"
    set "PATH=%CD%\.deps\PySide6;%PATH%"
)

where python >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.9+ 并加入 PATH
    pause
    exit /b 1
)

python run.py
if errorlevel 1 pause
