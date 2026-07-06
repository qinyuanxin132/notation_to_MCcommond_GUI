# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['notation_to_MCcommond_GUI_0.01.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['tkinterdnd2', 'pydirectinput', 'pynput', 'pyperclip', 'mido'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyd = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyd,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='MidiToRedstoneMusic',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # 改为 False 可隐藏控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',  # 如果有图标文件
)