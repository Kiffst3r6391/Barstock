#!/usr/bin/env python3
"""Tests for the macOS build configuration."""

from pathlib import Path

import build_app

ROOT = Path(__file__).resolve().parent.parent


def test_build_app_builds_from_the_spec():
    source = Path(build_app.__file__).read_text(encoding="utf-8")
    assert "'BarStock.spec'" in source
    # Flags belong in the spec; duplicating them here let PyInstaller
    # regenerate the spec and silently drop local edits.
    assert "--add-data" not in source
    assert "--hidden-import" not in source


def test_spec_declares_the_project_version():
    spec = (ROOT / "BarStock.spec").read_text(encoding="utf-8")
    assert "pyproject.toml" in spec
    assert "version=VERSION" in spec
    assert "info_plist={'CFBundleVersion': VERSION}" in spec
    assert build_app.project_version() != "0.0.0"


def test_spec_does_not_bundle_live_data():
    import re

    spec = (ROOT / "BarStock.spec").read_text(encoding="utf-8")
    datas = re.search(r"^datas = \[(.*?)\]$", spec, re.MULTILINE | re.DOTALL).group(1)
    for name in ("stock.csv", "Items.csv", "transaction_log.csv"):
        assert name not in datas
