# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec - DualGuard-Sec 安全业务版。

用法（在仓库根目录执行）：
    pyinstaller packaging/windows/sec.spec --noconfirm --clean

产物：
    dist/DualGuard-Sec/DualGuard-Sec.exe   (主程序，控制台)
    dist/DualGuard-Sec/_internal/          (依赖与字节码)

注意：
- 使用 onedir 模式（启动更快，便于 NSIS 整体打包）。
- hiddenimports 显式列出 cryptography 关键子模块，
  避免 PyInstaller 静态分析漏掉运行期动态导入。
- 不打包业务规则正则的攻击载荷样本，仅打包规则定义本身。
"""
import os
from PyInstaller.utils.hooks import collect_submodules

# 仓库根目录（spec 文件位于 packaging/windows/）
REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, '..', '..'))

block_cipher = None

# 显式收集 cryptography 的所有子模块（避免运行期 ImportError）
crypto_subs = collect_submodules('cryptography')

a = Analysis(
    [os.path.join(REPO_ROOT, 'dualguard_sec', 'main.py')],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=crypto_subs + [
        # cryptography 常被运行期延迟加载的子模块（兜底）
        'cryptography',
        'cryptography.fernet',
        'cryptography.hazmat',
        'cryptography.hazmat.primitives.hashes',
        'cryptography.hazmat.primitives.hmac',
        'cryptography.hazmat.primitives.ciphers',
        'cryptography.hazmat.primitives.kdf.pbkdf2',
        'cryptography.hazmat.primitives.padding',
        'cryptography.hazmat.backends.openssl.backend',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['test', 'unittest', 'pydoc'],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DualGuard-Sec',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # upx 会触发部分杀软误报，关闭
    console=False,             # GUI 程序，不弹控制台黑框
    disable_windowed_traceback=False,
    icon=None,                 # 可选：放置 ico 路径以自定义图标
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='DualGuard-Sec',
)
