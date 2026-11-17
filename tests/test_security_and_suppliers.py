"""Password gate and supplier-list settings tests."""

import sqlite3

import club_profile
import data_manager as dm
import security


def test_password_round_trip(tmp_path, monkeypatch):
    db = tmp_path / 'barstock.db'
    monkeypatch.setattr(dm, 'DB_PATH', str(db))
    monkeypatch.setattr(dm, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(dm, 'INVENTORY_FILE', str(tmp_path / 'stock.csv'))
    monkeypatch.setattr(dm, 'LOG_FILE', str(tmp_path / 'transaction_log.csv'))
    conn = sqlite3.connect(db)
    dm._init_db_schema(conn)
    conn.commit()
    conn.close()

    assert security.password_enabled() is False
    assert security.set_password('secret', True) is True
    assert security.password_enabled() is True
    assert security.verify_password('secret') is True
    assert security.verify_password('wrong') is False
    assert security.disable_password('wrong') is False
    assert security.disable_password('secret') is True
    assert security.password_enabled() is False


def test_supplier_settings_override_the_profile():
    club_profile.reload_profile('profiles/bruntsfield.json')
    try:
        def fake_get_setting(key, default=None):
            if key == 'suppliers':
                return '["Alpha", "Beta"]'
            return default
        profile = club_profile.apply_settings_overrides(fake_get_setting)
        assert profile['suppliers'] == ['Alpha', 'Beta']
        assert profile['default_supplier'] == 'Alpha'
    finally:
        club_profile.reload_profile()
