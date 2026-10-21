#!/usr/bin/env python3
"""Tests for the reconciliation audit and verified restore."""

import os
import sqlite3

import pandas as pd
import pytest

import data_manager as dm
from audit_data import reconcile_inventory


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "barstock.db"
    monkeypatch.setattr(dm, "DB_PATH", str(path))
    monkeypatch.setattr(dm, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(dm, "_sync_csv_quietly", lambda df: None)
    monkeypatch.setattr(dm.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(dm.messagebox, "showwarning", lambda *a, **k: None)
    monkeypatch.setattr(dm.messagebox, "showinfo", lambda *a, **k: None)

    conn = sqlite3.connect(path)
    dm._init_db_schema(conn)
    conn.close()
    return path


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def add_item(path, item_id, quantity):
    conn = connect(path)
    conn.execute(
        """
        INSERT INTO inventory
        (item_id, item_name, quantity, cost_price, sell_price, measure, category,
         price_locked, allow_negative, reorder_level, division)
        VALUES (?, ?, ?, 1, 3, 'Pint', 'Draught', 0, 0, 0, '')
        """,
        (item_id, item_id.replace("_", " ").title(), float(quantity)),
    )
    conn.commit()
    conn.close()


def add_tx(path, item_id, action, quantity, timestamp):
    conn = connect(path)
    conn.execute(
        "INSERT INTO transactions (item_id, action, quantity, timestamp) VALUES (?, ?, ?, ?)",
        (item_id, action, float(quantity), timestamp),
    )
    conn.commit()
    conn.close()


def set_quantity(path, item_id, quantity):
    conn = connect(path)
    conn.execute("UPDATE inventory SET quantity = ? WHERE item_id = ?", (quantity, item_id))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def test_reconciliation_accepts_a_consistent_log(db):
    add_item(db, "tennents_lager", 90)
    add_tx(db, "tennents_lager", "Stocktake Baseline", 100, "2026-10-01 09:00:00")
    add_tx(db, "tennents_lager", "Sales", 10, "2026-10-02 09:00:00")

    assert reconcile_inventory(db) == []


def test_reconciliation_treats_supplier_returns_as_a_deduction(db):
    add_item(db, "tennents_lager", 105)
    add_tx(db, "tennents_lager", "Stocktake Baseline", 100, "2026-10-01 09:00:00")
    add_tx(db, "tennents_lager", "Delivery", 10, "2026-10-02 09:00:00")
    add_tx(db, "tennents_lager", "Supplier Return", 5, "2026-10-03 09:00:00")

    assert reconcile_inventory(db) == []


def test_reconciliation_includes_stocktake_adjustments(db):
    add_item(db, "tennents_lager", 97)
    add_tx(db, "tennents_lager", "Stocktake Baseline", 100, "2026-10-01 09:00:00")
    add_tx(db, "tennents_lager", "Sales", 10, "2026-10-02 09:00:00")
    add_tx(db, "tennents_lager", "Stocktake Adjustment", 7, "2026-10-03 09:00:00")

    assert reconcile_inventory(db) == []


def test_reconciliation_reports_a_genuine_mismatch(db):
    add_item(db, "tennents_lager", 95)
    add_tx(db, "tennents_lager", "Stocktake Baseline", 100, "2026-10-01 09:00:00")
    add_tx(db, "tennents_lager", "Sales", 10, "2026-10-02 09:00:00")

    issues = reconcile_inventory(db)

    assert len(issues) == 1
    assert "tennents_lager" in issues[0]
    assert "actual=95.00" in issues[0]
    assert "expected_from_tx=90.00" in issues[0]


def test_reconciliation_skips_child_and_non_stocked_items(db):
    add_item(db, "tennents_lager", 90)
    add_tx(db, "tennents_lager", "Stocktake Baseline", 100, "2026-10-01 09:00:00")
    add_tx(db, "tennents_lager", "Sales", 10, "2026-10-02 09:00:00")
    # A child item that deducts from its parent; its own quantity is not
    # expected to reconcile with the parent's movements.
    add_item(db, "coffee_machine", 0)
    # A revenue-only item with no stock.
    add_item(db, "tea", 0)

    assert reconcile_inventory(db) == []


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------

def test_restore_refuses_a_non_database_file(db):
    add_item(db, "tennents_lager", 10)
    bad = db.parent / "not_a_database.db"
    bad.write_bytes(b"this is not sqlite")

    ok, message = dm.restore_backup(str(bad))

    assert ok is False
    assert "not usable" in message.lower()
    # The live database is untouched.
    conn = connect(db)
    assert conn.execute("SELECT quantity FROM inventory").fetchone()[0] == 10
    conn.close()


def test_restore_round_trips_and_keeps_a_pre_restore_copy(db):
    add_item(db, "tennents_lager", 10)
    backup = dm.create_backup("test_snapshot")
    assert backup

    add_item(db, "added_after_backup", 5)

    ok, detail = dm.restore_backup(backup)

    assert ok is True
    assert os.path.exists(detail), "pre-restore backup should exist"
    conn = connect(db)
    ids = {row[0] for row in conn.execute("SELECT item_id FROM inventory")}
    conn.close()
    assert ids == {"tennents_lager"}


def test_restore_reports_missing_file(db):
    ok, message = dm.restore_backup(str(db.parent / "missing.db"))
    assert ok is False
    assert "not found" in message.lower()


# ---------------------------------------------------------------------------
# Migration guard and variance report
# ---------------------------------------------------------------------------

def test_price_basis_marker_round_trips(db, monkeypatch):
    import migrate_to_ex_vat as ex
    import migrate_to_inc_vat as inc

    monkeypatch.setattr(ex, "DB_PATH", db)
    monkeypatch.setattr(inc, "DB_PATH", db)

    assert ex._read_price_basis() is None
    ex._write_price_basis(ex.PRICE_BASIS)
    assert inc._read_price_basis() == "ex_vat"
    inc._write_price_basis(inc.PRICE_BASIS)
    assert ex._read_price_basis() == "inc_vat"


def test_variance_report_separates_shortages_from_overs():
    from generate_variance_report import build_report

    inventory_df = pd.DataFrame([
        {"item_id": "a", "item_name": "Short Item", "measure": "Pint"},
        {"item_id": "b", "item_name": "Over Item", "measure": "Pint"},
    ])
    entries = [
        {"item_id": "a", "counted_system": 8.0, "input_value": 8.0},
        {"item_id": "b", "counted_system": 20.0, "input_value": 20.0},
    ]
    expected = {"a": 10.0, "b": 10.0}

    text, df = build_report(entries, expected, inventory_df, [], "2026-10-21")

    shortages, overs = text.split("TOP 15 SHORTAGES")[1].split("TOP 15 OVERS")
    assert "Short Item" in shortages and "Over Item" not in shortages
    assert "Over Item" in overs and "Short Item" not in overs
    assert len(df) == 2
