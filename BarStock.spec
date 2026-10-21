# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build configuration - the single source of truth for the bundle.

Build with ``python3 build_app.py`` (which wraps this spec and verifies the
result), or directly::

    pyinstaller --noconfirm --clean BarStock.spec

Live data (stock.csv, Items.csv, transaction_log.csv) is deliberately not
bundled: client data lives in ~/Library/Application Support/BarStockManagement.
"""
import os
import re

from PyInstaller.utils.hooks import collect_all

# SPECPATH is provided by PyInstaller and is the directory holding this file.
with open(os.path.join(SPECPATH, 'pyproject.toml'), encoding='utf-8') as _fh:  # noqa: F821
    _match = re.search(r'^version\s*=\s*"([^"]+)"', _fh.read(), re.MULTILINE)
VERSION = _match.group(1) if _match else '0.0.0'

datas = [('categories.py', '.'), ('conversions.py', '.'), ('sales_mapping.py', '.'), ('supplier_mapping.py', '.'), ('order_sheet_layout.py', '.'), ('actions.py', '.'), ('app_runtime.py', '.'), ('app_config.py', '.'), ('ui_theme.py', '.'), ('retirement.py', '.'), ('data_manager.py', '.'), ('pdf_generator.py', '.'), ('reports.py', '.'), ('inventory_sync.py', '.')]
binaries = []
hiddenimports = ['pandas', 'numpy', 'tkinter', 'tkinter.messagebox', 'tkinter.ttk', 'ttkthemes', 'fpdf', 'fpdf.FPDF', 'defusedxml', 'PIL', 'tkcalendar', 'babel', 'babel.numbers', 'matplotlib', 'matplotlib.pyplot', 'matplotlib.backends.backend_tkagg', 'matplotlib.dates', 'categories', 'conversions', 'sales_mapping', 'supplier_mapping', 'order_sheet_layout', 'actions', 'app_runtime', 'app_config', 'ui_theme', 'retirement', 'data_manager', 'pdf_generator', 'reports', 'inventory_sync', 'pdfplumber', 'screens', 'screens.dashboard', 'screens.deliveries', 'screens.inventory', 'screens.reports', 'screens.stocktake', 'screens.transactions', 'screens.uploads', 'screens.widgets']
tmp_ret = collect_all('tkcalendar')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('babel')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pdfplumber')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['BarStockApp.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['scipy', 'sphinx', 'PyQt5', 'PyQt6', 'wx'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='BarStock',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=os.environ.get('CODESIGN_IDENTITY'),
    entitlements_file='entitlements.plist',
    icon=['assets/icon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BarStock',
)
app = BUNDLE(
    coll,
    name='BarStock.app',
    icon='assets/icon.icns',
    bundle_identifier='com.prestonfield.barstock',
    version=VERSION,
    info_plist={'CFBundleVersion': VERSION},
)
