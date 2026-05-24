# -*- mode: python ; coding: utf-8 -*-
import os
import sys

# 获取Tcl/Tk库路径
tcl_lib_path = os.path.join(sys.base_prefix, 'tcl', 'tcl8.6')
tk_lib_path = os.path.join(sys.base_prefix, 'tcl', 'tk8.6')

# 获取Python DLL和tkinter相关DLL路径
python_dir = sys.base_prefix
tkinter_dll = os.path.join(python_dir, 'DLLs', '_tkinter.pyd')
tcl_dll = os.path.join(python_dir, 'DLLs', 'tcl86t.dll')
tk_dll = os.path.join(python_dir, 'DLLs', 'tk86t.dll')

# 准备二进制文件列表
binaries = []
if os.path.exists(tkinter_dll):
    binaries.append((tkinter_dll, '.'))
if os.path.exists(tcl_dll):
    binaries.append((tcl_dll, '.'))
if os.path.exists(tk_dll):
    binaries.append((tk_dll, '.'))

a = Analysis(
    ['main.py'],
    pathex=[python_dir, '.'],
    binaries=binaries,
    datas=[
        (tcl_lib_path, 'tcl8.6'),
        (tk_lib_path, 'tk8.6'),
    ],
    hiddenimports=[
        'tkinter',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'tkinter.simpledialog',
        'customtkinter',
        'concurrent.futures',
        'logging',
        'qrcode',
        'qrcode.image.pil',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'src.crawler.dynamic_crawler',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='BilibiliCommentsCrawler',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
