"""The packaged application self-test must pass on a blank database."""

import sqlite3

import data_manager as dm
from self_test import run_self_test


def test_self_test_passes_on_a_blank_database(tmp_path, monkeypatch):
    db = tmp_path / 'barstock.db'
    monkeypatch.setattr(dm, 'DB_PATH', str(db))
    monkeypatch.setattr(dm, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(dm, 'INVENTORY_FILE', str(tmp_path / 'stock.csv'))
    monkeypatch.setattr(dm, 'LOG_FILE', str(tmp_path / 'transaction_log.csv'))
    conn = sqlite3.connect(db)
    dm._init_db_schema(conn)
    conn.commit()
    conn.close()

    assert run_self_test() == 0
