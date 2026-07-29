@echo off
REM ==========================================================================
REM  DualGuard-Student 启动脚本（Windows）
REM  - 默认启动图形界面 GUI
REM  - 加 --repl 参数启动命令行模式
REM
REM  用法：
REM    双击 start_student.bat           → 启动 GUI
REM    start_student.bat --repl         → 命令行模式
REM    start_student.bat --status       → 查看状态
REM ==========================================================================
setlocal
cd /d "%~dp0"

set "PY_CMD="
where py >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=py"
    goto :found
)
where python >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=python"
    goto :found
)
echo [ERR] 未找到 Python，请安装 Python 3.10+ 并勾选 "Add to PATH"
pause
exit /b 1

:found
%PY_CMD% -c "import cryptography" >nul 2>nul
if errorlevel 1 (
    echo [INFO] 安装运行依赖 cryptography ...
    %PY_CMD% -m pip install cryptography
)

%PY_CMD% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo [WARN] 未检测到 tkinter，将使用命令行模式
    %PY_CMD% -m dualguard_student.main --repl %*
    pause
    exit /b 0
)

echo [INFO] 启动 DualGuard-Student（GUI 模式）...
%PY_CMD% -m dualguard_student.main %*
endlocal
