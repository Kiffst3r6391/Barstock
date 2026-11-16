# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller configuration for the bruntsfield Windows portable build.

Built by ``build_windows.py --profile bruntsfield`` on Windows (or GitHub
Actions). It is deliberately separate from ``BarStock.spec`` because that spec
contains macOS-only BUNDLE/codesigning/entitlements pieces.
"""
import os

from PyInstaller.utils.hooks import collect_all

datas = [
    ('categories.py', '.'),
    ('conversions.py', '.'),
    ('sales_mapping.py', '.'),
    ('supplier_mapping.py', '.'),
    ('order_sheet_layout.py', '.'),
    ('actions.py', '.'),
    ('app_runtime.py', '.'),
    ('app_config.py', '.'),
    ('club_profile.py', '.'),
    ('ui_theme.py', '.'),
    ('retirement.py', '.'),
    ('data_manager.py', '.'),
    ('pdf_generator.py', '.'),
    ('reports.py', '.'),
    ('inventory_sync.py', '.'),
    ('assets/bruntsfield_logo.png', 'assets'),
    ('assets/bruntsfield_logo_40.png', 'assets'),
    ('assets/bruntsfield_logo_64.png', 'assets'),
    ('assets/bruntsfield.ico', 'assets'),
    ('build_support/club_profile.json', '.'),
    ('build_support/version.txt', '.'),
    ('README-BUYER.txt', '.'),
    ('Items_template.csv', '.'),
]
binaries = []
hiddenimports = [
    'pandas', 'numpy', 'tkinter', 'tkinter.messagebox', 'tkinter.ttk',
    'fpdf', 'defusedxml', 'PIL', 'tkcalendar', 'babel',
    'babel.numbers', 'matplotlib', 'matplotlib.pyplot',
    'matplotlib.backends.backend_tkagg', 'matplotlib.dates',
    'categories', 'conversions', 'sales_mapping', 'supplier_mapping',
    'order_sheet_layout', 'actions', 'app_runtime', 'app_config',
    'club_profile', 'ui_theme', 'retirement', 'data_manager',
    'pdf_generator', 'reports', 'inventory_sync', 'pdfplumber', 'screens',
    'screens.dashboard', 'screens.deliveries', 'screens.inventory',
    'screens.reports', 'screens.stocktake', 'screens.transactions',
    'screens.uploads', 'screens.widgets',
]
for package in ('tkcalendar', 'babel', 'pdfplumber', 'fpdf'):
    try:
        extra = collect_all(package)
        datas += extra[0]
        binaries += extra[1]
        hiddenimports += extra[2]
    except Exception:
        pass

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
    name='BarStockManagement',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=['assets/bruntsfield.ico'],
    version='build_support/windows_version_info.txt',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BarStockManagement',
)
