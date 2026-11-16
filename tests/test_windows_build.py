"""Static checks for the Windows portable build configuration."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_windows_spec_has_no_macos_only_pieces():
    text = (ROOT / 'BarStockWindows.spec').read_text(encoding='utf-8')
    for forbidden in ('BUNDLE(', 'codesign_identity=', 'entitlements_file=',
                      'argv_emulation=', 'upx=True', '.icns'):
        assert forbidden not in text
    assert 'bruntsfield_logo.png' in text
    assert 'build_support/club_profile.json' in text
    assert 'BarStockManagement' in text


def test_windows_build_script_and_workflow():
    build = (ROOT / 'build_windows.py').read_text(encoding='utf-8')
    assert "os.name != 'nt'" in build
    assert 'BarStockManagement-Windows-x64' in build
    workflow = (ROOT / '.github/workflows/build-windows.yml').read_text(
        encoding='utf-8')
    assert 'windows-latest' in workflow
    assert 'workflow_dispatch' in workflow
    assert 'upload-artifact' in workflow


def test_requirements_use_fpdf2():
    text = (ROOT / 'requirements.txt').read_text(encoding='utf-8')
    assert 'fpdf2' in text
    assert 'Pillow' in text
