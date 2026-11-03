#!/usr/bin/env python3
"""Schema migrations for databases created by earlier versions.

The 1.0 database declared ``transactions.id REAL`` with no primary key, so
every row kept a NULL id.  A log save then tried to match frame rows to
``int(None)`` and failed.  These tests pin the rebuild that gives every row a
stable integer id without losing or reordering the history.
"""

import os
import sqlite3
import tempfile

import pytest

import data_manager
from data_manager import (
    COL_ID,
    COL_SELL_PRICE,
    InventoryDataManager,
    initialize_db,
)


LEGACY_SCHEMA = """
    CREATE TABLE transactions (
        id REAL,
        item_id TEXT NOT NULL,
        action TEXT NOT NULL,
        quantity REAL NOT NULL,
        timestamp TEXT NOT NULL,
        cost_price REAL DEFAULT 0,
        sell_price REAL DEFAULT 0,
        supplier TEXT DEFAULT '',
        date_range TEXT DEFAULT '',
        reason TEXT DEFAULT '',
        user TEXT DEFAULT '',
        member_qty REAL,
        non_member_qty REAL,
        open_tab_id TEXT
    )
"""


@pytest.fixture
def legacy_db_path(monkeypatch):
    """A database with the pre-id transactions schema and NULL row ids."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(path)
    conn.execute(LEGACY_SCHEMA)
    conn.executemany(
        "INSERT INTO transactions (item_id, action, quantity, timestamp, "
        "sell_price, open_tab_id) VALUES (?, ?, ?, ?, ?, ?)",
        [
            ("tennents_lager", "Sales", 2.0, "2026-10-02 12:00:00", 4.0, None),
            ("guinness", "Sales", 1.0, "2026-10-03 12:00:00", 4.5, "7"),
        ],
    )
    conn.commit()
    conn.close()

    def mock_get_connection():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(data_manager, "_get_connection", mock_get_connection)
    monkeypatch.setattr(data_manager, "DB_PATH", path)
    monkeypatch.setattr(data_manager, "INVENTORY_FILE",
                        os.path.join(os.path.dirname(path), "stock.csv"))
    monkeypatch.setattr(data_manager, "LOG_FILE",
                        os.path.join(os.path.dirname(path), "transaction_log.csv"))

    yield path

    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def test_legacy_rows_receive_unique_integer_ids(legacy_db_path):
    initialize_db()

    conn = sqlite3.connect(legacy_db_path)
    info = {row[1]: row for row in conn.execute("PRAGMA table_info(transactions)")}
    rows = conn.execute(
        "SELECT id, item_id, timestamp, open_tab_id FROM transactions ORDER BY id"
    ).fetchall()
    conn.close()

    assert "INT" in info["id"][2].upper()
    assert info["id"][5] == 1  # primary key
    assert [row[0] for row in rows] == [1, 2]
    assert [row[1] for row in rows] == ["tennents_lager", "guinness"]
    # Values survive the rebuild, including the text open_tab_id.
    assert rows[1][3] == 7


def test_log_save_works_after_the_rebuild(legacy_db_path):
    initialize_db()
    log = InventoryDataManager.load_log()
    assert log[COL_ID].notna().all()

    log.loc[log.index[0], COL_SELL_PRICE] = 4.25
    assert InventoryDataManager.save_log(log)

    conn = sqlite3.connect(legacy_db_path)
    saved = conn.execute(
        "SELECT sell_price FROM transactions WHERE item_id = 'tennents_lager'"
    ).fetchone()[0]
    count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    conn.close()

    assert saved == pytest.approx(4.25)
    assert count == 2


def test_legacy_inventory_without_primary_key_is_rebuilt(monkeypatch, tmp_path):
    path = str(tmp_path / "legacy_inventory.db")
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE inventory (
            item_id TEXT, item_name TEXT NOT NULL, quantity REAL DEFAULT 0,
            cost_price REAL DEFAULT 0, sell_price REAL DEFAULT 0,
            measure TEXT DEFAULT '', category TEXT DEFAULT '',
            price_locked INTEGER DEFAULT 0, allow_negative INTEGER DEFAULT 0,
            reorder_level REAL DEFAULT 0
        )
    """)
    conn.execute(
        "INSERT INTO inventory (item_id, item_name, quantity) "
        "VALUES ('tennents_lager', 'Tennents Lager', 10)"
    )
    conn.commit()
    conn.close()

    def mock_get_connection():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(data_manager, "_get_connection", mock_get_connection)
    monkeypatch.setattr(data_manager, "DB_PATH", path)
    monkeypatch.setattr(data_manager, "INVENTORY_FILE", str(tmp_path / "stock.csv"))
    monkeypatch.setattr(data_manager, "LOG_FILE", str(tmp_path / "transaction_log.csv"))

    initialize_db()

    conn = sqlite3.connect(path)
    info = {row[1]: row for row in conn.execute("PRAGMA table_info(inventory)")}
    assert info["item_id"][5] == 1  # primary key
    # The upsert path that adds a new stock item now works.
    conn.execute(
        "INSERT INTO inventory (item_id, item_name, quantity) "
        "VALUES ('dash', 'Dash', 0) "
        "ON CONFLICT(item_id) DO UPDATE SET item_name = excluded.item_name"
    )
    rows = dict(conn.execute(
        "SELECT item_id, quantity FROM inventory").fetchall())
    conn.close()

    assert rows["tennents_lager"] == pytest.approx(10.0)
    assert rows["dash"] == pytest.approx(0.0)
