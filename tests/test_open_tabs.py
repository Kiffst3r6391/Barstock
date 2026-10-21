"""Tests for open tab data-manager helpers."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from data_manager import InventoryDataManager, initialize_db


@pytest.fixture
def temp_db_path(monkeypatch):
    """Create a temporary SQLite DB and point data_manager at it."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    def mock_get_connection():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    import data_manager
    monkeypatch.setattr(data_manager, "_get_connection", mock_get_connection)
    monkeypatch.setattr(data_manager, "DB_PATH", Path(path))
    # Never let a temporary database migrate or rename the live CSV mirror.
    monkeypatch.setattr(data_manager, "INVENTORY_FILE", str(Path(path).with_name("stock.csv")))
    monkeypatch.setattr(data_manager, "LOG_FILE", str(Path(path).with_name("transaction_log.csv")))

    initialize_db()

    yield path

    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _tab_items():
    return [
        {
            "item_id": "tennents_lager",
            "item_name": "Tennents Lager",
            "quantity": 2.0,
            "cost_price": 1.50,
            "sell_price": 4.00,
        },
        {
            "item_id": "tennents_lager_half",
            "item_name": "Tennents Half",
            "quantity": 1.0,
            "cost_price": 0.75,
            "sell_price": 2.50,
        },
    ]


def _seed_inventory(conn):
    cursor = conn.cursor()
    for item_id, qty in [
        ("tennents_lager", 100.0),
        ("tennents_lager_half", 50.0),
    ]:
        cursor.execute(
            "INSERT INTO inventory (item_id, item_name, quantity, cost_price, sell_price, measure, category) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item_id, item_id.replace("_", " ").title(), qty, 1.0, 3.0, "", ""),
        )
    conn.commit()


def test_create_open_tab_logs_open_tab_transactions(temp_db_path):
    tab_id = InventoryDataManager.create_open_tab("Test Customer", _tab_items())
    assert tab_id is not None

    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM open_tabs WHERE id = ?", (tab_id,))
    assert cursor.fetchone()["status"] == "open"

    cursor.execute(
        "SELECT item_id, action, quantity FROM transactions WHERE open_tab_id = ? ORDER BY item_id",
        (tab_id,),
    )
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 2
    assert rows[0]["action"] == "Open Tab"
    assert rows[1]["action"] == "Open Tab"


def test_close_open_tab_as_sale_logs_sales(temp_db_path):
    tab_id = InventoryDataManager.create_open_tab("Test Customer", _tab_items())
    items = [
        {"item_id": "tennents_lager", "quantity": 2.0, "cost_price": 1.50, "sell_price": 4.00},
        {"item_id": "tennents_lager_half", "quantity": 1.0, "cost_price": 0.75, "sell_price": 2.50},
    ]
    assert InventoryDataManager.close_open_tab(tab_id, items)

    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM open_tabs WHERE id = ?", (tab_id,))
    assert cursor.fetchone()["status"] == "closed"

    cursor.execute(
        "SELECT action, COUNT(*) AS c FROM transactions WHERE open_tab_id = ? GROUP BY action",
        (tab_id,),
    )
    counts = {row["action"]: row["c"] for row in cursor.fetchall()}
    conn.close()

    assert counts.get("Open Tab") == 2
    assert counts.get("Sales") == 2


def test_close_open_tab_as_complimentary_logs_complimentary_and_keeps_tab_status(temp_db_path):
    tab_id = InventoryDataManager.create_open_tab("Test Customer", _tab_items())
    items = [
        {"item_id": "tennents_lager", "quantity": 2.0, "cost_price": 1.50, "sell_price": 4.00},
        {"item_id": "tennents_lager_half", "quantity": 1.0, "cost_price": 0.75, "sell_price": 2.50},
    ]
    assert InventoryDataManager.close_open_tab_as_complimentary(tab_id, items)

    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM open_tabs WHERE id = ?", (tab_id,))
    assert cursor.fetchone()["status"] == "complimentary"

    cursor.execute(
        "SELECT action, COUNT(*) AS c FROM transactions WHERE open_tab_id = ? GROUP BY action",
        (tab_id,),
    )
    counts = {row["action"]: row["c"] for row in cursor.fetchall()}
    conn.close()

    assert counts.get("Open Tab") == 2
    assert counts.get("Complimentary") == 2


def test_cancel_open_tab_returns_items_and_logs_tab_cancelled(temp_db_path):
    tab_id = InventoryDataManager.create_open_tab("Test Customer", _tab_items())
    restored = InventoryDataManager.cancel_open_tab(tab_id)

    assert restored is not None
    assert len(restored) == 2
    assert {r["item_id"] for r in restored} == {"tennents_lager", "tennents_lager_half"}

    conn = sqlite3.connect(temp_db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM open_tabs WHERE id = ?", (tab_id,))
    assert cursor.fetchone()["status"] == "cancelled"

    cursor.execute(
        "SELECT action, COUNT(*) AS c FROM transactions WHERE open_tab_id = ? GROUP BY action",
        (tab_id,),
    )
    counts = {row["action"]: row["c"] for row in cursor.fetchall()}
    conn.close()

    assert counts.get("Open Tab") == 2
    assert counts.get("Tab Cancelled") == 2


def test_get_open_tabs_filters_by_status(temp_db_path):
    open_id = InventoryDataManager.create_open_tab("Open Customer", _tab_items())
    closed_id = InventoryDataManager.create_open_tab("Closed Customer", _tab_items())
    InventoryDataManager.close_open_tab(closed_id, [
        {"item_id": "tennents_lager", "quantity": 2.0, "cost_price": 1.50, "sell_price": 4.00},
        {"item_id": "tennents_lager_half", "quantity": 1.0, "cost_price": 0.75, "sell_price": 2.50},
    ])

    open_tabs = InventoryDataManager.get_open_tabs(status="open")
    assert set(open_tabs["customer_name"]) == {"Open Customer"}

    closed_tabs = InventoryDataManager.get_open_tabs(status="closed")
    assert set(closed_tabs["customer_name"]) == {"Closed Customer"}


def test_create_open_tab_deducts_inventory_and_parent_stock(temp_db_path):
    conn = sqlite3.connect(temp_db_path)
    _seed_inventory(conn)
    conn.close()

    tab_id = InventoryDataManager.create_open_tab("Stock Test", _tab_items())
    assert tab_id is not None

    conn = sqlite3.connect(temp_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT quantity FROM inventory WHERE item_id = ?", ("tennents_lager",))
    parent_qty = cursor.fetchone()[0]
    cursor.execute("SELECT quantity FROM inventory WHERE item_id = ?", ("tennents_lager_half",))
    child_qty = cursor.fetchone()[0]
    conn.close()

    # Direct deduction: 2 from child, plus parent-side deduction for the half pint (0.5 factor)
    assert child_qty == 49.0
    assert parent_qty == 97.5


def test_cancel_open_tab_restores_inventory_and_parent_stock(temp_db_path):
    conn = sqlite3.connect(temp_db_path)
    _seed_inventory(conn)
    conn.close()

    tab_id = InventoryDataManager.create_open_tab("Stock Test", _tab_items())
    restored = InventoryDataManager.cancel_open_tab(tab_id)
    assert restored is not None

    conn = sqlite3.connect(temp_db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT quantity FROM inventory WHERE item_id = ?", ("tennents_lager",))
    parent_qty = cursor.fetchone()[0]
    cursor.execute("SELECT quantity FROM inventory WHERE item_id = ?", ("tennents_lager_half",))
    child_qty = cursor.fetchone()[0]
    conn.close()

    # Cancellation should fully restore the seeded quantities.
    assert child_qty == 50.0
    assert parent_qty == 100.0
