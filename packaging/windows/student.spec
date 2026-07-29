# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec - DualGuard-Student 学生业务版。

用法（在仓库根目录执行）：
    pyinstaller packaging/windows/student.spec --noconfirm --clean

产物：
    dist/DualGuard-Student/DualGuard-Student.exe
    dist/DualGuard-Student/_internal/

与 sec.spec 结构完全对称，仅入口模块与产物名不同，
确保两套版本完全独立、可同机并存。
"""
import os
from PyInstaller.utils.hooks import collect_submodules

REPO_ROOT = os.path.abspath(os.path.join(SPECPATH, '..', '..'))

block_cipher = None
crypto_subs = collect_submodules('cryptography')

a = Analysis(
    [os.path.join(REPO_ROOT, 'dualguard_student', 'main.py')],
    pathex=[REPO_ROOT],
    binaries=[],
    datas=[],
    hiddenimports=crypto_subs + [
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
    name='DualGuard-Student',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,             # GUI 程序，不弹控制台黑框
    disable_windowed_traceback=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='DualGuard-Student',
)
