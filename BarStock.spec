# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('stock.csv', '.'), ('transaction_log.csv', '.'), ('Items.csv', '.'), ('categories.py', '.'), ('conversions.py', '.'), ('sales_mapping.py', '.'), ('supplier_mapping.py', '.'), ('order_sheet_layout.py', '.'), ('actions.py', '.'), ('data_manager.py', '.'), ('pdf_generator.py', '.'), ('reports.py', '.'), ('stock_service.py', '.'), ('csv_upload.py', '.'), ('update_stock.py', '.')]
binaries = []
hiddenimports = ['pandas', 'numpy', 'tkinter', 'tkinter.messagebox', 'tkinter.ttk', 'ttkthemes', 'fpdf', 'fpdf.FPDF', 'defusedxml', 'PIL', 'tkcalendar', 'babel', 'babel.numbers', 'matplotlib', 'matplotlib.pyplot', 'matplotlib.backends.backend_tkagg', 'matplotlib.dates', 'categories', 'conversions', 'sales_mapping', 'supplier_mapping', 'order_sheet_layout', 'actions', 'data_manager', 'pdf_generator', 'reports', 'stock_service', 'csv_upload', 'update_stock']
tmp_ret = collect_all('tkcalendar')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('babel')
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
    codesign_identity=None,
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
)
