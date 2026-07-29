@echo off
REM ==========================================================================
REM  DualGuard-Student Windows 一键构建脚本
REM  与 build_sec.bat 完全对称，仅产物名不同。
REM
REM  前置依赖：pip install pyinstaller cryptography；系统安装 NSIS。
REM  用法（在仓库根目录执行）：packaging\windows\build_student.bat
REM  产物：
REM    dist\DualGuard-Student\                PyInstaller onedir 输出
REM    dist\DualGuard-Student-Setup.exe       NSIS 安装包
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
if exist dist\DualGuard-Student rmdir /s /q dist\DualGuard-Student
if exist build rmdir /s /q build
if exist dist\DualGuard-Student-Setup.exe del /q dist\DualGuard-Student-Setup.exe

echo [3/4] 运行 PyInstaller...
pyinstaller packaging\windows\student.spec --noconfirm --clean
if errorlevel 1 (
    echo [ERR] PyInstaller 打包失败。
    exit /b 1
)

echo [4/4] 运行 NSIS 生成安装包...
makensis packaging\windows\installer_student.nsi
if errorlevel 1 (
    echo [ERR] NSIS 打包失败。
    exit /b 1
)

echo.
echo [OK] 构建完成：
echo     安装包: dist\DualGuard-Student-Setup.exe
echo     免安装: dist\DualGuard-Student\DualGuard-Student.exe
endlocal
