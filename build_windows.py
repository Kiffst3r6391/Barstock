#!/usr/bin/env python3
"""Build the standalone Windows portable ZIP for a club profile.

PyInstaller cannot cross-compile, so this script refuses to run on macOS/Linux.
Run it on Windows, or let .github/workflows/build-windows.yml run it on a
windows-latest runner. The destination PC does not need Python.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BUILD_SUPPORT = ROOT / 'build_support'
DIST = ROOT / 'dist'
APP_NAME = 'BarStockManagement'
ZIP_NAME = 'BarStockManagement-Windows-x64'
LIVE_NAMES = {'barstock.db', 'stock.csv', 'Items.csv', 'transaction_log.csv'}
FORBIDDEN_TEXT = ('Prestonfield', 'Chris Armstrong')


def project_version() -> str:
    text = (ROOT / 'pyproject.toml').read_text(encoding='utf-8')
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else '0.0.0'


def stage(profile_name: str, version: str) -> Path:
    profile_path = ROOT / 'profiles' / f'{profile_name}.json'
    if not profile_path.exists():
        raise SystemExit(f'Profile not found: {profile_path}')
    BUILD_SUPPORT.mkdir(exist_ok=True)
    shutil.copy2(profile_path, BUILD_SUPPORT / 'club_profile.json')
    (BUILD_SUPPORT / 'version.txt').write_text(version + '\n', encoding='utf-8')

    parts = [int(part) for part in version.split('.') if part.isdigit()]
    parts += [0] * (4 - len(parts))
    version_tuple = tuple(parts[:4])
    (BUILD_SUPPORT / 'windows_version_info.txt').write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={version_tuple}, prodvers={version_tuple},
                    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1,
                    subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
        StringStruct('CompanyName', 'Bruntsfield Links'),
        StringStruct('FileDescription', 'Bar Stock Management'),
        StringStruct('FileVersion', '{version}'),
        StringStruct('InternalName', 'BarStockManagement'),
        StringStruct('OriginalFilename', 'BarStockManagement.exe'),
        StringStruct('ProductName', 'Bruntsfield Links Bar Stock'),
        StringStruct('ProductVersion', '{version}')
    ])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""",
        encoding='utf-8')
    return BUILD_SUPPORT / 'club_profile.json'


def verify(app_dir: Path) -> None:
    exe = app_dir / 'BarStockManagement.exe'
    if not exe.exists():
        raise SystemExit(f'Missing executable: {exe}')
    profile_path = app_dir / 'club_profile.json'
    if not profile_path.exists():
        profile_path = app_dir / '_internal' / 'club_profile.json'
    if not profile_path.exists():
        raise SystemExit(f'Missing bundled profile: {profile_path}')
    profile = json.loads(profile_path.read_text(encoding='utf-8'))
    if profile.get('profile_id') != 'bruntsfield':
        raise SystemExit('Bundled profile is not bruntsfield')

    for root, _dirs, files in os.walk(app_dir):
        for name in files:
            if name in LIVE_NAMES:
                raise SystemExit(f'Live data file leaked into build: {root}/{name}')
            if name.lower().endswith(('.json', '.txt', '.py', '.pyc')):
                try:
                    text = Path(root, name).read_text(encoding='utf-8',
                                                       errors='ignore')
                except OSError:
                    continue
                for forbidden in FORBIDDEN_TEXT:
                    if forbidden in text:
                        raise SystemExit(
                            f'Forbidden branding {forbidden!r} in {root}/{name}')


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', default='bruntsfield')
    parser.add_argument('--no-zip', action='store_true')
    args = parser.parse_args()

    if os.name != 'nt':
        print('ERROR: PyInstaller cannot cross-compile.')
        print('Run this on Windows, or use the GitHub Actions build workflow.')
        return 2

    version = project_version()
    stage(args.profile, version)
    for folder in (ROOT / 'build', DIST):
        if folder.exists():
            print(f'Cleaning {folder.name}/...')
            shutil.rmtree(folder)

    cmd = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
           'BarStockWindows.spec']
    print('Running:', ' '.join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        print('ERROR: PyInstaller failed.')
        return result.returncode

    app_dir = DIST / APP_NAME
    for name in ('README-BUYER.txt', 'Items_template.csv'):
        source = ROOT / name
        if source.exists():
            shutil.copy2(source, app_dir / name)
    verify(app_dir)
    print(f'Verified {app_dir}')

    if not args.no_zip:
        zip_path = ROOT / ZIP_NAME
        if zip_path.with_suffix('.zip').exists():
            zip_path.with_suffix('.zip').unlink()
        shutil.make_archive(str(zip_path), 'zip', root_dir=str(DIST),
                            base_dir=APP_NAME)
        print(f'Created {zip_path}.zip')

    print('\nPortable build complete.')
    print('Extract the ZIP and run BarStockManagement.exe.')
    print('Data will live in %LOCALAPPDATA%\\BruntsfieldBarStock.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
