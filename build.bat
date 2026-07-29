@echo off
chcp 65001 >nul 2>nul
REM ==========================================================================
REM  DualGuard Windows 一键构建脚本（鲁棒版）
REM
REM  修复要点：
REM  1. 用 python -m PyInstaller 代替 pyinstaller（避免 Scripts 目录不在 PATH）
REM  2. 每一步出错都 pause，不闪退
REM  3. NSIS 找不到时给出完整下载与配置指引
REM  4. 全程使用绝对路径，避免环境差异
REM
REM  双击运行或 cmd 执行：build.bat
REM ==========================================================================
setlocal EnableDelayedExpansion
title DualGuard 一键构建工具
cd /d "%~dp0"

echo.
echo ================================================================
echo   DualGuard Windows 一键构建
echo ================================================================
echo.

REM ---------- 1. 定位 Python ----------
echo [1/6] 定位 Python ...
REM 优先用 py 启动器（Windows 官方推荐），其次 python
set "PY_CMD="
where py >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=py"
    goto :found_python
)
where python >nul 2>nul
if not errorlevel 1 (
    set "PY_CMD=python"
    goto :found_python
)
echo.
echo [ERR] 未找到 Python！请安装 Python 3.10+：
echo       下载：https://www.python.org/downloads/
echo       安装时务必勾选 "Add Python to PATH"
echo.
pause
exit /b 1

:found_python
echo       使用 Python 命令：%PY_CMD%
%PY_CMD% --version
if errorlevel 1 (
    echo [ERR] Python 启动失败
    pause
    exit /b 1
)
echo.

REM ---------- 2. 检查并安装依赖 ----------
echo [2/6] 检查 Python 依赖 ...

REM 检查并安装 PyInstaller
%PY_CMD% -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo       安装 PyInstaller ...
    %PY_CMD% -m pip install --upgrade pip
    %PY_CMD% -m pip install pyinstaller
)
%PY_CMD% -c "import PyInstaller" >nul 2>nul
if errorlevel 1 (
    echo [ERR] PyInstaller 安装失败，请手动执行：
    echo       %PY_CMD% -m pip install pyinstaller
    pause
    exit /b 1
)
echo       PyInstaller 已就绪

REM 检查并安装 cryptography
%PY_CMD% -c "import cryptography" >nul 2>nul
if errorlevel 1 (
    echo       安装 cryptography ...
    %PY_CMD% -m pip install cryptography
)
%PY_CMD% -c "import cryptography" >nul 2>nul
if errorlevel 1 (
    echo [ERR] cryptography 安装失败，请手动执行：
    echo       %PY_CMD% -m pip install cryptography
    pause
    exit /b 1
)
echo       cryptography 已就绪
echo.

REM ---------- 3. 检查 NSIS ----------
echo [3/6] 检查 NSIS ...
where makensis >nul 2>nul
if errorlevel 1 (
    REM 尝试常见安装路径
    if exist "C:\Program Files\NSIS\makensis.exe" (
        set "PATH=%PATH%;C:\Program Files\NSIS"
        echo       从默认路径找到 NSIS
    ) else if exist "C:\Program Files (x86)\NSIS\makensis.exe" (
        set "PATH=%PATH%;C:\Program Files (x86)\NSIS"
        echo       从默认路径找到 NSIS
    ) else (
        echo.
        echo [ERR] 未找到 makensis！请安装 NSIS：
        echo       下载地址：https://nsis.sourceforge.io/Download
        echo       安装时勾选 "Add to PATH"，或安装后手动添加到系统 PATH
        echo       默认安装路径：C:\Program Files\NSIS\
        echo.
        echo       若暂时不想安装 NSIS，可只生成免安装版 exe：
        echo       跳过本脚本，执行：pyinstaller packaging\windows\sec.spec --noconfirm
        echo.
        pause
        exit /b 1
    )
)
echo       NSIS 已就绪
echo.

REM ---------- 4. 清理旧产物 ----------
echo [4/6] 清理旧产物 ...
if exist dist\DualGuard-Sec rmdir /s /q dist\DualGuard-Sec 2>nul
if exist dist\DualGuard-Student rmdir /s /q dist\DualGuard-Student 2>nul
if exist build rmdir /s /q build 2>nul
if exist dist\DualGuard-Sec-Setup.exe del /q dist\DualGuard-Sec-Setup.exe 2>nul
if exist dist\DualGuard-Student-Setup.exe del /q dist\DualGuard-Student-Setup.exe 2>nul
echo       清理完成
echo.

REM ---------- 5. 打包 DualGuard-Sec ----------
echo [5/6] 打包 DualGuard-Sec 安全业务版 ...
echo       --- PyInstaller ---
%PY_CMD% -m PyInstaller packaging\windows\sec.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo [ERR] DualGuard-Sec PyInstaller 打包失败
    pause
    exit /b 1
)
echo       --- NSIS ---
makensis packaging\windows\installer_sec.nsi
if errorlevel 1 (
    echo.
    echo [ERR] DualGuard-Sec NSIS 打包失败
    pause
    exit /b 1
)
echo       DualGuard-Sec 打包完成
echo.

REM ---------- 6. 打包 DualGuard-Student ----------
echo [6/6] 打包 DualGuard-Student 学生业务版 ...
echo       --- PyInstaller ---
%PY_CMD% -m PyInstaller packaging\windows\student.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo [ERR] DualGuard-Student PyInstaller 打包失败
    pause
    exit /b 1
)
echo       --- NSIS ---
makensis packaging\windows\installer_student.nsi
if errorlevel 1 (
    echo.
    echo [ERR] DualGuard-Student NSIS 打包失败
    pause
    exit /b 1
)
echo       DualGuard-Student 打包完成
echo.

REM ---------- 完成 ----------
echo ================================================================
echo   构建完成！
echo ================================================================
echo.
echo   安装包：
if exist dist\DualGuard-Sec-Setup.exe (
    echo     dist\DualGuard-Sec-Setup.exe        [OK]
) else (
    echo     dist\DualGuard-Sec-Setup.exe        [缺失]
)
if exist dist\DualGuard-Student-Setup.exe (
    echo     dist\DualGuard-Student-Setup.exe    [OK]
) else (
    echo     dist\DualGuard-Student-Setup.exe    [缺失]
)
echo.
echo   免安装版（直接双击运行）：
if exist dist\DualGuard-Sec\DualGuard-Sec.exe (
    echo     dist\DualGuard-Sec\DualGuard-Sec.exe
) else (
    echo     dist\DualGuard-Sec\DualGuard-Sec.exe    [缺失]
)
if exist dist\DualGuard-Student\DualGuard-Student.exe (
    echo     dist\DualGuard-Student\DualGuard-Student.exe
) else (
    echo     dist\DualGuard-Student\DualGuard-Student.exe    [缺失]
)
echo.
echo   部署工具（图形化）：%PY_CMD% -m deploy_tool
echo.
pause
endlocal
