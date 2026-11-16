"""Windows portability helpers."""

from datetime import datetime
from pathlib import Path

import app_config
import app_runtime


def test_date_helpers_are_platform_safe():
    value = datetime(2026, 11, 8)
    assert app_config.format_day_of_month(value) == '8'
    assert app_config.format_day_month(value) == '8 Nov'
    assert app_config.format_day_month_year(value) == '8 Nov 2026'
    assert '%-' not in app_config.format_weekday_day_month(value)


def test_sqlite_ro_uri_handles_spaces(tmp_path):
    path = tmp_path / 'a b' / 'barstock.db'
    uri = app_config.sqlite_ro_uri(path)
    assert uri.startswith('file:')
    assert uri.endswith('?mode=ro')
    assert 'a%20b' in uri


def test_version_override(monkeypatch):
    monkeypatch.setenv('BARSTOCK_VERSION', '9.9.9')
    assert app_runtime.resolve_version() == '9.9.9'


def test_downloads_dir_is_writable():
    path = app_config.get_downloads_dir()
    assert path
    assert Path(path).exists()
