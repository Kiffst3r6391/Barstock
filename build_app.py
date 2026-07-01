#!/usr/bin/,nv python3
"""
Build script to create a launchable macOS app from the Bar Stock Management System.

This script will attempt multiple methods to build the app:
1. PyInstaller (recommended - most reliable)
2. py2app (alternative - more native macOS feel)

Usage:
    python3 build_app.py

Requirements:
    pip3 install pyinstaller pandas
    or
    pip3 install py2app pandas
"""

import os
import sys
import subprocess
import shutil


def check_dependencies():
    """Check if required packages are installed."""
    missing = []

    try:
        import pandas
        print("✓ pandas is installed")
    except ImportError:
        missing.append("pandas")

    try:
        import PyInstaller
        print("✓ PyInstaller is installed")
    except ImportError:
        missing.append("pyinstaller")

    if missing:
        print(f"\n⚠ Missing dependencies: {', '.join(missing)}")
        print("\nInstall with:")
        print(f"  pip3 install {' '.join(missing)}")
        return False
    return True


def create_entitlements_file():
    """Ensure entitlements file exists and targets the correct data directory."""
    if os.path.exists('entitlements.plist'):
        return
    entitlements_content = '''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.app-sandbox</key>
    <false/>
    <key>com.apple.security.files.user-selected.read-write</key>
    <true/>
    <key>com.apple.security.files.downloads.read-write</key>
    <true/>
    <key>com.apple.security.temporary-exception.files.home-relative-path.read-write</key>
    <array>
        <string>/Library/Application Support/BarStockManagement/</string>
    </array>
</dict>
</plist>
'''
    with open('entitlements.plist', 'w') as f:
        f.write(entitlements_content)
    print("Created entitlements.plist for Application Support access")


def build_with_pyinstaller():
    """Build the app using PyInstaller (most reliable method)."""
    print("\n" + "=" * 60)
    print("Building with PyInstaller...")
    print("=" * 60 + "\n")

    # Clean previous builds
    for folder in ['build', 'dist']:
        if os.path.exists(folder):
            print(f"Cleaning {folder}/...")
            shutil.rmtree(folder)

    # Ensure entitlements file exists and targets the correct directory
    create_entitlements_file()

    # Signing identity from environment, if provided
    codesign_identity = os.environ.get('CODESIGN_IDENTITY', None)

    # Create the PyInstaller command
    cmd = [
        'pyinstaller',
        '--name', 'BarStock',
        '--windowed',  # macOS GUI app (no console)
        '--onedir',    # Directory mode (better for macOS .app bundles)
        '--noconfirm', # Overwrite existing
        '--clean',
        # Data files
        '--add-data', 'stock.csv:.',
        '--add-data', 'transaction_log.csv:.',
        '--add-data', 'Items.csv:.',
        '--add-data', 'categories.py:.',
        '--add-data', 'conversions.py:.',
        '--add-data', 'sales_mapping.py:.',
        '--add-data', 'supplier_mapping.py:.',
        '--add-data', 'order_sheet_layout.py:.',
        '--add-data', 'actions.py:.',
        '--add-data', 'data_manager.py:.',
        '--add-data', 'pdf_generator.py:.',
        '--add-data', 'reports.py:.',
        '--add-data', 'stock_service.py:.',
        '--add-data', 'csv_upload.py:.',
        '--add-data', 'update_stock.py:.',
        # Hidden imports
        '--hidden-import', 'pandas',
        '--hidden-import', 'numpy',
        '--hidden-import', 'tkinter',
        '--hidden-import', 'tkinter.messagebox',
        '--hidden-import', 'tkinter.ttk',
        '--hidden-import', 'ttkthemes',
        '--hidden-import', 'fpdf',
        '--hidden-import', 'fpdf.FPDF',
        '--hidden-import', 'defusedxml',
        '--hidden-import', 'PIL',
        '--hidden-import', 'tkcalendar',
        '--collect-all', 'tkcalendar',
        '--hidden-import', 'babel',
        '--hidden-import', 'babel.numbers',
        '--collect-all', 'babel',
        '--hidden-import', 'matplotlib',
        '--hidden-import', 'matplotlib.pyplot',
        '--hidden-import', 'matplotlib.backends.backend_tkagg',
        '--hidden-import', 'matplotlib.dates',
        '--hidden-import', 'categories',
        '--hidden-import', 'conversions',
        '--hidden-import', 'sales_mapping',
        '--hidden-import', 'supplier_mapping',
        '--hidden-import', 'order_sheet_layout',
        '--hidden-import', 'actions',
        '--hidden-import', 'data_manager',
        '--hidden-import', 'pdf_generator',
        '--hidden-import', 'reports',
        '--hidden-import', 'stock_service',
        '--hidden-import', 'csv_upload',
        '--hidden-import', 'update_stock',
        # Exclude unnecessary packages
        '--exclude-module', 'scipy',
        '--exclude-module', 'sphinx',
        '--exclude-module', 'PyQt5',
        '--exclude-module', 'PyQt6',
        '--exclude-module', 'wx',
        # macOS app bundle
        '--osx-bundle-identifier', 'com.prestonfield.barstock',
        '--osx-entitlements-file', 'entitlements.plist',
        # Icon
        '--icon', 'assets/icon.icns',
        'BarStockApp.py'
    ]

    if codesign_identity:
        cmd.extend(['--codesign-identity', codesign_identity])

    print(f"Running: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, capture_output=False)

    if result.returncode == 0:
        print("\n" + "=" * 60)
        print("✓ Build successful!")
        print("=" * 60)
        print("\nYour app is available at:")
        print("  dist/BarStock.app")
        print("\nTo install:")
        print("  1. Drag 'BarStock.app' to your Applications folder")
        print("  2. Double-click to launch")
        print("\nNote: On first launch, you may need to right-click and select 'Open'")
        print("      to bypass Gatekeeper warnings.")
        return True
    else:
        print("\n✗ Build failed!")
        return False


def build_with_py2app():
    """Build the app using py2app (alternative method)."""
    print("\n" + "=" * 60)
    print("Building with py2app...")
    print("=" * 60 + "\n")

    try:
        import py2app
    except ImportError:
        print("py2app is not installed. Install with:")
        print("  pip3 install py2app")
        return False

    # Clean previous builds
    for folder in ['build', 'dist']:
        if os.path.exists(folder):
            print(f"Cleaning {folder}/...")
            shutil.rmtree(folder)

    cmd = ['python3', 'setup.py', 'py2app']
    print(f"Running: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, capture_output=False)

    if result.returncode == 0:
        print("\n" + "=" * 60)
        print("✓ Build successful!")
        print("=" * 60)
        print("\nYour app is available at:")
        print("  dist/BarStock.app")
        return True
    else:
        print("\n✗ Build failed!")
        return False


def create_launch_script():
    """Create a simple launcher script as a fallback."""
    script_content = '''#!/bin/bash
# Bar Stock Management Launcher
cd "$(dirname "$0")"
python3 BarStockApp.py
'''
    with open('launch.sh', 'w') as f:
        f.write(script_content)
    os.chmod('launch.sh', 0o755)
    print("Created launch.sh as a fallback launcher")


def main():
    """Main build process."""
    print("=" * 60)
    print("Bar Stock Management - App Builder")
    print("=" * 60)

    if not check_dependencies():
        print("\nPlease install missing dependencies and try again.")
        sys.exit(1)

    # Try PyInstaller first (most reliable)
    if build_with_pyinstaller():
        # Create a DMG or ZIP for distribution
        print("\n" + "=" * 60)
        print("Creating distribution archive...")
        print("=" * 60)

        # Create ZIP
        zip_name = "BarStockManagement-macOS"
        if os.path.exists(f"{zip_name}.zip"):
            os.remove(f"{zip_name}.zip")

        shutil.make_archive(zip_name, 'zip', root_dir='dist', base_dir='BarStock.app')
        print(f"\n✓ Created {zip_name}.zip for distribution")

        print("\n" + "=" * 60)
        print("BUILD COMPLETE!")
        print("=" * 60)
        print(f"""
Files created:
  - dist/BarStock.app (launchable app)
  - {zip_name}.zip (distribution archive)

To use:
  1. Extract {zip_name}.zip
  2. Drag 'BarStock.app' to Applications
  3. Double-click to run

Your database will be created automatically in
~/Library/Application Support/BarStockManagement/barstock.db on first run.
        """)
    else:
        print("\n⚠ PyInstaller build failed.")
        print("Attempting py2app as fallback...")
        if build_with_py2app():
            print("\n✓ Build successful with py2app!")
        else:
            print("\n✗ All build methods failed.")
            print("Creating simple launcher script as fallback...")
            create_launch_script()
            print("\nYou can run the app with: ./launch.sh")


if __name__ == "__main__":
    main()
