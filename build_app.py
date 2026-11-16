#!/usr/bin/env python3
"""
Build script to create a launchable macOS app from the Bar Stock Management System.

The bundle configuration lives in BarStock.spec (datas, hidden imports, icon,
entitlements, version); this script just drives the build and verifies the
result.

Usage:
    python3 build_app.py

Requirements:
    pip3 install pyinstaller pandas
"""

import os
import re
import sys
import time
import subprocess
import shutil


INSTALL_DIR = '/Applications'
APP_NAME = 'BarStock.app'


def project_version():
    """Read the version from pyproject.toml so the bundle matches the code."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pyproject.toml')
    try:
        with open(path, encoding='utf-8') as fh:
            match = re.search(r'^version\s*=\s*"([^"]+)"', fh.read(), re.MULTILINE)
        if match:
            return match.group(1)
    except OSError:
        pass
    return '0.0.0'


def verify_bundle(app_dir, expected_version):
    """Check the built bundle: version, signature, and no bundled live data."""
    plist = os.path.join(app_dir, 'Contents', 'Info.plist')
    ok = True

    if not os.path.exists(plist):
        print(f"✗ {plist} not found")
        return False

    result = subprocess.run(
        ['/usr/libexec/PlistBuddy', '-c', 'Print :CFBundleShortVersionString', plist],
        capture_output=True, text=True,
    )
    version = result.stdout.strip()
    if version == expected_version:
        print(f"✓ Bundle version {version}")
    else:
        print(f"✗ Bundle version is {version!r}, expected {expected_version!r}")
        ok = False

    sign = subprocess.run(
        ['codesign', '--verify', '--deep', '--strict', app_dir],
        capture_output=True, text=True,
    )
    if sign.returncode == 0:
        print("✓ Code signature valid")
    else:
        print(f"✗ Code signature invalid: {sign.stderr.strip()}")
        ok = False

    live_data = {'stock.csv', 'Items.csv', 'transaction_log.csv'}
    leaked = [
        os.path.relpath(os.path.join(root, name), app_dir)
        for root, _dirs, files in os.walk(app_dir)
        for name in files
        if name in live_data
    ]
    if leaked:
        print(f"✗ Live data bundled into the app: {', '.join(leaked)}")
        ok = False
    else:
        print("✓ No live data files in the bundle")

    return ok


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


def stage_club_profile():
    """Bundle the seller profile explicitly so its branding is not a fallback."""
    os.makedirs('build_support', exist_ok=True)
    shutil.copyfile('profiles/prestonfield.json',
                    'build_support/club_profile.json')


def build_with_pyinstaller():
    """Build the app from BarStock.spec, the single source of truth for the bundle."""
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

    # Building from the spec keeps every flag in one place and stops PyInstaller
    # regenerating the spec (which used to overwrite local edits).
    cmd = ['pyinstaller', '--noconfirm', '--clean', 'BarStock.spec']

    print(f"Running: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, capture_output=False)

    if result.returncode == 0:
        print("\n" + "=" * 60)
        print("✓ Build successful!")
        print("=" * 60)
        print("\nYour app is available at:")
        print("  dist/BarStock.app")
        print("\nThe previous copy in /Applications will be replaced automatically.")
        print("\nNote: On first launch, you may need to right-click and select 'Open'")
        print("      to bypass Gatekeeper warnings.")
        return True
    else:
        print("\n✗ Build failed!")
        return False


def app_is_running():
    """True when a BarStock process is live (it holds the old bundle open)."""
    return subprocess.run(
        ['pgrep', '-x', 'BarStock'], capture_output=True
    ).returncode == 0


def install_app(app_dir, install_dir=INSTALL_DIR):
    """Replace the previously installed copy so /Applications always matches dist.

    The new bundle is staged first and only swapped in once it is complete, so a
    failed copy never leaves Applications without a working app.
    """
    print("\n" + "=" * 60)
    print("Installing to Applications (replacing previous build)...")
    print("=" * 60)

    target = os.path.join(install_dir, APP_NAME)
    if not os.path.exists(target):
        print(f"No existing {target}; copying new build into place.")

    if app_is_running():
        print("BarStock is running - asking it to quit so the old copy can be replaced...")
        subprocess.run(
            ['osascript', '-e', 'tell application "BarStock" to quit'],
            capture_output=True,
        )
        for _ in range(20):
            time.sleep(0.25)
            if not app_is_running():
                break
        if app_is_running():
            print(f"✗ BarStock is still running; {target} was left untouched.")
            print("  Quit BarStock and re-run the build, or copy dist/BarStock.app manually.")
            return False

    if not os.access(install_dir, os.W_OK):
        print(f"✗ {install_dir} is not writable; skipping install.")
        print("  Copy dist/BarStock.app to Applications manually.")
        return False

    staging = os.path.join(install_dir, f'.{APP_NAME}.new')
    if os.path.exists(staging):
        shutil.rmtree(staging)

    print(f"Copying new build to staging: {staging}")
    shutil.copytree(app_dir, staging, symlinks=True)

    if os.path.exists(target):
        print(f"Deleting previous build: {target}")
        shutil.rmtree(target)
    os.rename(staging, target)

    print(f"✓ Installed {target}")
    return True


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
    # Relative paths in the spec and entitlements assume the project root.
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print("=" * 60)
    print("Bar Stock Management - App Builder")
    print("=" * 60)

    if not check_dependencies():
        print("\nPlease install missing dependencies and try again.")
        sys.exit(1)

    app_dir = os.path.join('dist', 'BarStock.app')
    version = project_version()
    stage_club_profile()

    if not build_with_pyinstaller():
        print("\n✗ Build failed. Check the output above for errors.")
        print("Creating simple launcher script as fallback...")
        create_launch_script()
        print("\nYou can run the app with: ./launch.sh")
        sys.exit(1)

    if not verify_bundle(app_dir, version):
        print("\n✗ The built app failed verification; no archive was created.")
        sys.exit(1)

    # Replace the installed copy so no stale build is ever left running from
    # Applications. A failure here does not invalidate the build itself.
    install_app(app_dir)

    # Create a ZIP for distribution
    print("\n" + "=" * 60)
    print("Creating distribution archive...")
    print("=" * 60)

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
  - /Applications/BarStock.app (previous build replaced)
  - {zip_name}.zip (distribution archive)

To use:
  1. Launch BarStock from Applications
  2. Or extract {zip_name}.zip on another Mac and drag 'BarStock.app' to Applications

Your database will be created automatically in
~/Library/Application Support/BarStockManagement/barstock.db on first run.
""")


if __name__ == "__main__":
    main()
