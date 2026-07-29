@echo off
REM ==========================================================================
REM  DualGuard 一键部署工具启动脚本（Windows）
REM  双击或 cmd 执行：deploy.bat
REM ==========================================================================
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON=.venv\Scripts\python.exe"
) else (
    set "PYTHON=python"
)

echo [INFO] 启动 DualGuard 一键部署工具 ...
%PYTHON% -m deploy_tool
if errorlevel 1 (
    echo.
    echo [ERR] 启动失败。若提示缺少 tkinter，请安装：
    echo       Windows：通常已随 Python 自带，重新安装 Python 时勾选 "tcl/tk"
    pause
)
endlocal
