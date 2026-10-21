#!/usr/bin/env python3
"""Regression tests for the persistence safeguards added after the 2026-10-21
reconciliation.

These cover the failure modes that produced ~£1,539 of phantom shortfall:

* a stale in-memory inventory frame overwriting newer delivery quantities;
* inventory and log written in separate commits;
* a truncated log frame deleting recent transactions;
* partial stocktakes applied item by item;
* a baseline reset archiving the history of items that were never counted;
* deleting an item erasing its transaction history.
"""

import sqlite3

import pandas as pd
import pytest

import data_manager as dm


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point data_manager at a fresh temporary database.

    The CSV mirror is disabled because the tests must never touch the real
    stock.csv or Items.csv files.
    """
    path = tmp_path / "barstock.db"
    monkeypatch.setattr(dm, "DB_PATH", str(path))
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


def add_item(path, item_id, quantity, **overrides):
    values = {
        "item_id": item_id,
        "item_name": item_id.replace("_", " ").title(),
        "quantity": float(quantity),
        "cost_price": 1.0,
        "sell_price": 3.0,
        "measure": "Pint",
        "category": "Draught",
        "price_locked": 0,
        "allow_negative": 0,
        "reorder_level": 0.0,
        "division": "",
    }
    values.update(overrides)
    conn = connect(path)
    conn.execute(
        """
        INSERT INTO inventory
        (item_id, item_name, quantity, cost_price, sell_price, measure, category,
         price_locked, allow_negative, reorder_level, division)
        VALUES (:item_id, :item_name, :quantity, :cost_price, :sell_price,
                :measure, :category, :price_locked, :allow_negative,
                :reorder_level, :division)
        """,
        values,
    )
    conn.commit()
    conn.close()


def add_transaction(path, item_id, action, quantity, timestamp):
    conn = connect(path)
    conn.execute(
        """
        INSERT INTO transactions (item_id, action, quantity, timestamp)
        VALUES (?, ?, ?, ?)
        """,
        (item_id, action, float(quantity), timestamp),
    )
    conn.commit()
    conn.close()


def add_transactions(path, count, item_id="tennents_lager"):
    for i in range(count):
        add_transaction(
            path,
            item_id,
            "Sales",
            1.0,
            f"2026-10-{1 + i // 10:02d} {i % 10:02d}:00:00",
        )


def quantity_of(path, item_id):
    conn = connect(path)
    row = conn.execute(
        "SELECT quantity FROM inventory WHERE item_id = ?", (item_id,)
    ).fetchone()
    conn.close()
    return None if row is None else float(row["quantity"])


def count_of(path, table):
    conn = connect(path)
    n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    conn.close()
    return n


def log_frame(rows):
    return pd.DataFrame(rows, columns=dm.LOG_COLUMNS)


# ---------------------------------------------------------------------------
# Stale-frame safety
# ---------------------------------------------------------------------------

def test_unchanged_stale_frame_does_not_overwrite_newer_quantity(db):
    """The exact bug behind the reconciliation: an old window saves and wipes
    a delivery that landed after it loaded."""
    add_item(db, "tennents_lager", 100)
    baseline = dm.InventoryDataManager.load_inventory()

    # Another process records a delivery after this window loaded.
    conn = connect(db)
    conn.execute(
        "UPDATE inventory SET quantity = 250 WHERE item_id = 'tennents_lager'"
    )
    conn.commit()
    conn.close()

    stale = baseline.copy()
    assert dm.InventoryDataManager.save_inventory(stale, baseline_df=baseline)

    assert quantity_of(db, "tennents_lager") == 250


def test_stale_frame_change_is_applied_as_a_delta(db):
    add_item(db, "tennents_lager", 100)
    baseline = dm.InventoryDataManager.load_inventory()

    # This window deducts 10 pints, while a delivery of 150 lands elsewhere.
    stale = baseline.copy()
    stale.loc[stale[dm.COL_ITEM_ID] == "tennents_lager", dm.COL_QUANTITY] = 90

    conn = connect(db)
    conn.execute(
        "UPDATE inventory SET quantity = 250 WHERE item_id = 'tennents_lager'"
    )
    conn.commit()
    conn.close()

    assert dm.InventoryDataManager.save_inventory(stale, baseline_df=baseline)

    # 250 (delivery) - 10 (this window's deduction) = 240.
    assert quantity_of(db, "tennents_lager") == 240


def test_metadata_change_does_not_reset_quantity(db):
    add_item(db, "tennents_lager", 100)
    baseline = dm.InventoryDataManager.load_inventory()

    stale = baseline.copy()
    stale.loc[stale[dm.COL_ITEM_ID] == "tennents_lager", dm.COL_SELL_PRICE] = 5.25

    conn = connect(db)
    conn.execute(
        "UPDATE inventory SET quantity = 250 WHERE item_id = 'tennents_lager'"
    )
    conn.commit()
    conn.close()

    assert dm.InventoryDataManager.save_inventory(stale, baseline_df=baseline)

    assert quantity_of(db, "tennents_lager") == 250
    conn = connect(db)
    row = conn.execute(
        "SELECT sell_price FROM inventory WHERE item_id = 'tennents_lager'"
    ).fetchone()
    conn.close()
    assert float(row["sell_price"]) == 5.25


def test_inventory_save_refuses_to_empty_the_table(db):
    add_item(db, "item_a", 10)
    add_item(db, "item_b", 10)
    add_item(db, "item_c", 10)
    baseline = dm.InventoryDataManager.load_inventory()

    empty = baseline.iloc[0:0]
    assert not dm.InventoryDataManager.save_inventory(empty, baseline_df=baseline)

    assert count_of(db, "inventory") == 3


# ---------------------------------------------------------------------------
# Combined inventory + log write
# ---------------------------------------------------------------------------

def test_save_all_writes_both_tables_together(db):
    add_item(db, "tennents_lager", 100)
    baseline = dm.InventoryDataManager.load_inventory()

    inv = baseline.copy()
    inv.loc[inv[dm.COL_ITEM_ID] == "tennents_lager", dm.COL_QUANTITY] = 90
    log = log_frame([
        ["tennents_lager", "Sales", 10.0, "2026-10-21 12:00:00",
         1.0, 3.0, "", "", "", 0.0, 0.0, None],
    ])

    assert dm.InventoryDataManager.save_all(inv, log, baseline_df=baseline)

    assert quantity_of(db, "tennents_lager") == 90
    assert count_of(db, "transactions") == 1


def test_save_all_rolls_back_inventory_when_log_write_is_rejected(db):
    """Inventory must not be committed if the log half of the save fails."""
    add_item(db, "tennents_lager", 100)
    add_transactions(db, 20)
    baseline = dm.InventoryDataManager.load_inventory()

    inv = baseline.copy()
    inv.loc[inv[dm.COL_ITEM_ID] == "tennents_lager", dm.COL_QUANTITY] = 90
    truncated_log = log_frame([])  # would delete all 20 transactions

    assert not dm.InventoryDataManager.save_all(inv, truncated_log, baseline_df=baseline)

    assert quantity_of(db, "tennents_lager") == 100
    assert count_of(db, "transactions") == 20


# ---------------------------------------------------------------------------
# Log shrink guard
# ---------------------------------------------------------------------------

def test_save_log_rejects_truncated_frame(db):
    add_transactions(db, 20)

    assert not dm.InventoryDataManager.save_log(log_frame([]))
    assert count_of(db, "transactions") == 20

    # The explicit override is still available for a deliberate reset.
    assert dm.InventoryDataManager.save_log(log_frame([]), allow_shrink=True)
    assert count_of(db, "transactions") == 0


def test_save_log_allows_a_normal_small_edit(db):
    add_transactions(db, 6)  # under the allowed loss of max(5, 10%) = 5? 6-5=1
    frame = dm.InventoryDataManager.load_log()
    assert dm.InventoryDataManager.save_log(frame)
    assert count_of(db, "transactions") == 6


# ---------------------------------------------------------------------------
# Stocktake atomicity
# ---------------------------------------------------------------------------

def test_record_stocktakes_rolls_back_every_entry_on_failure(db):
    add_item(db, "item_a", 100)
    add_item(db, "item_b", 100)

    entries = [
        {"item_id": "item_a", "counted_quantity": 90,
         "expected_quantity": 100, "variance": -10},
        {"item_id": "item_b", "counted_quantity": "not-a-number",
         "expected_quantity": 100, "variance": 0},
    ]

    result = dm.record_stocktakes(entries, "2026-10-21 12:00:00", note="test")

    assert result["success"] is False
    assert quantity_of(db, "item_a") == 100
    assert quantity_of(db, "item_b") == 100
    assert count_of(db, "stocktake_snapshots") == 0
    assert count_of(db, "transactions") == 0


def test_record_stocktakes_records_all_entries(db):
    add_item(db, "item_a", 100)
    add_item(db, "item_b", 100)

    entries = [
        {"item_id": "item_a", "counted_quantity": 90,
         "expected_quantity": 100, "variance": -10},
        {"item_id": "item_b", "counted_quantity": 110,
         "expected_quantity": 100, "variance": 10},
    ]

    result = dm.record_stocktakes(entries, "2026-10-21 12:00:00", note="test")

    assert result == {"success": True, "recorded": 2}
    assert quantity_of(db, "item_a") == 90
    assert quantity_of(db, "item_b") == 110
    assert count_of(db, "stocktake_snapshots") == 2
    assert count_of(db, "transactions") == 2


# ---------------------------------------------------------------------------
# Baseline reset scope
# ---------------------------------------------------------------------------

def test_reset_baseline_archives_only_the_counted_item(db):
    add_item(db, "item_a", 100)
    add_item(db, "item_b", 200)
    add_transaction(db, "item_a", "Delivery", 10, "2026-10-01 09:00:00")
    add_transaction(db, "item_b", "Delivery", 20, "2026-10-01 09:00:00")

    result = dm.reset_baseline(
        [{"item_id": "item_a", "counted_system": 105,
          "input_value": 105, "input_unit": "unit"}],
        "2026-10-20 12:00:00",
        note="counted a only",
    )

    assert result["success"] is True
    assert result["archived_count"] == 1
    assert quantity_of(db, "item_a") == 105
    # The uncounted item keeps its stock ...
    assert quantity_of(db, "item_b") == 200
    # ... and its history.
    assert count_of(db, "transactions") == 2
    conn = connect(db)
    actions = {
        (r["item_id"], r["action"])
        for r in conn.execute("SELECT item_id, action FROM transactions")
    }
    archived = conn.execute(
        "SELECT item_id FROM transaction_archive"
    ).fetchall()
    conn.close()

    # item_a keeps only its new baseline; item_b's delivery was never archived.
    assert actions == {("item_a", "Stocktake Baseline"), ("item_b", "Delivery")}
    assert [r["item_id"] for r in archived] == ["item_a"]


# ---------------------------------------------------------------------------
# History retention
# ---------------------------------------------------------------------------

def test_load_log_keeps_history_for_items_no_longer_in_inventory(db):
    add_item(db, "still_stocked", 10)
    add_transaction(db, "still_stocked", "Delivery", 10, "2026-10-01 09:00:00")
    add_transaction(db, "deleted_item", "Sales", 4, "2026-10-02 09:00:00")

    inventory = dm.InventoryDataManager.load_inventory()
    log = dm.InventoryDataManager.load_log(inventory)

    assert len(log) == 2
    assert "deleted_item" in set(log[dm.COL_ITEM_ID])
