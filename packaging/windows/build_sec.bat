@echo off
REM ==========================================================================
REM  DualGuard-Sec Windows 一键构建脚本
REM  作用：调用 PyInstaller 生成 exe 目录，再调用 NSIS 打包成安装包
REM
REM  前置依赖：
REM    pip install pyinstaller cryptography
REM    系统安装 NSIS (https://nsis.sourceforge.io/)，makensis 在 PATH 中
REM
REM  用法（在仓库根目录执行）：
REM    packaging\windows\build_sec.bat
REM  产物：
REM    dist\DualGuard-Sec\               PyInstaller onedir 输出
REM    dist\DualGuard-Sec-Setup.exe      NSIS 安装包
REM ==========================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0\..\.."

echo [1/4] 检查依赖...
python -c "import PyInstaller; import cryptography" 2>nul
if errorlevel 1 (
    echo [ERR] 缺少 PyInstaller 或 cryptography，执行: pip install pyinstaller cryptography
    exit /b 1
)
where makensis >nul 2>nul
if errorlevel 1 (
    echo [ERR] 未找到 makensis，请安装 NSIS 并加入 PATH。
    exit /b 1
)

echo [2/4] 清理旧产物...
if exist dist\DualGuard-Sec rmdir /s /q dist\DualGuard-Sec
if exist build rmdir /s /q build
if exist dist\DualGuard-Sec-Setup.exe del /q dist\DualGuard-Sec-Setup.exe

echo [3/4] 运行 PyInstaller...
pyinstaller packaging\windows\sec.spec --noconfirm --clean
if errorlevel 1 (
    echo [ERR] PyInstaller 打包失败。
    exit /b 1
)

echo [4/4] 运行 NSIS 生成安装包...
makensis packaging\windows\installer_sec.nsi
if errorlevel 1 (
    echo [ERR] NSIS 打包失败。
    exit /b 1
)

echo.
echo [OK] 构建完成：
echo     安装包: dist\DualGuard-Sec-Setup.exe
echo     免安装: dist\DualGuard-Sec\DualGuard-Sec.exe
endlocal
