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

import os
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
    # Keep backups (baseline resets now take one) inside the temp directory.
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


# ---------------------------------------------------------------------------
# Delta log writes
# ---------------------------------------------------------------------------

def test_log_save_preserves_rows_written_after_load(db):
    add_transactions(db, 2)  # ids 1 and 2
    frame = dm.InventoryDataManager.load_log()
    assert dm.COL_ID in frame.columns
    loaded_ids = {int(v) for v in frame[dm.COL_ID]}

    # Another window records a sale after this frame was loaded.
    add_transaction(db, "tennents_lager", "Sales", 3, "2026-10-21 13:00:00")

    assert dm.InventoryDataManager.save_log(frame, baseline_ids=loaded_ids)

    assert count_of(db, "transactions") == 3
    conn = connect(db)
    quantities = [r["quantity"] for r in conn.execute(
        "SELECT quantity FROM transactions WHERE timestamp = '2026-10-21 13:00:00'"
    )]
    conn.close()
    assert quantities == [3.0]


def test_log_save_deletes_rows_removed_from_the_frame(db):
    for n in range(3):
        add_transaction(db, "tennents_lager", "Sales", n + 1,
                        f"2026-10-0{n + 1} 09:00:00")
    frame = dm.InventoryDataManager.load_log()
    removed_id = int(frame.iloc[0][dm.COL_ID])
    frame = frame[frame[dm.COL_ID] != removed_id].reset_index(drop=True)

    assert dm.InventoryDataManager.save_log(frame)

    assert count_of(db, "transactions") == 2
    conn = connect(db)
    assert conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE id = ?", (removed_id,)
    ).fetchone()[0] == 0
    conn.close()


def test_log_save_updates_an_edited_row_in_place(db):
    add_transaction(db, "tennents_lager", "Delivery", 10, "2026-10-01 09:00:00")
    frame = dm.InventoryDataManager.load_log()
    frame.loc[:, dm.COL_QUANTITY] = 12.0

    assert dm.InventoryDataManager.save_log(frame)

    conn = connect(db)
    row = conn.execute("SELECT id, quantity FROM transactions").fetchone()
    conn.close()
    assert row["id"] == int(frame.iloc[0][dm.COL_ID])
    assert row["quantity"] == 12.0


def test_log_save_still_rejects_mass_deletion(db):
    add_transactions(db, 20)
    frame = dm.InventoryDataManager.load_log().iloc[0:0]

    assert not dm.InventoryDataManager.save_log(frame)
    assert count_of(db, "transactions") == 20


# ---------------------------------------------------------------------------
# Reporting history and backups
# ---------------------------------------------------------------------------

def test_load_full_log_includes_archived_adjustments_and_deleted_items(db):
    add_item(db, "still_stocked", 10)
    add_transaction(db, "still_stocked", "Delivery", 10, "2026-10-01 09:00:00")

    conn = connect(db)
    conn.execute(
        """
        INSERT INTO transaction_archive
        (item_id, action, quantity, timestamp, archived_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("gone_item", "Stocktake Adjustment", -4.0, "2026-09-01 09:00:00",
         "2026-10-20 09:00:00"),
    )
    conn.execute(
        """
        INSERT INTO transaction_archive
        (item_id, action, quantity, timestamp, archived_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        ("gone_item", "Stocktake Baseline", 50.0, "2026-08-01 09:00:00",
         "2026-10-20 09:00:00"),
    )
    conn.commit()
    conn.close()

    full = dm.InventoryDataManager.load_full_log(
        dm.InventoryDataManager.load_inventory()
    )

    actions = set(zip(full[dm.COL_ITEM_ID], full[dm.COL_ACTION]))
    assert ("gone_item", "Stocktake Adjustment") in actions
    # Old baselines are superseded by the current one and stay out.
    assert ("gone_item", "Stocktake Baseline") not in actions


def test_create_backup_writes_a_verified_copy(db):
    add_item(db, "tennents_lager", 100)
    add_transaction(db, "tennents_lager", "Delivery", 100, "2026-10-01 09:00:00")

    path = dm.create_backup("test")

    assert path and os.path.exists(path)
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
        assert conn.execute("SELECT quantity FROM inventory").fetchone()[0] == 100
    finally:
        conn.close()


def test_backup_retention_keeps_the_newest(db, monkeypatch):
    backups_dir = dm.get_backups_dir()
    for n in range(25):
        path = os.path.join(backups_dir, f"barstock_backup_202601{n:02d}_x.db")
        with open(path, "w") as fh:
            fh.write("x")
        # Distinct mtimes so ordering is deterministic.
        os.utime(path, (1_700_000_000 + n, 1_700_000_000 + n))

    dm.cleanup_old_backups(max_backups=20)

    remaining = sorted(os.listdir(backups_dir))
    assert len(remaining) == 20
    assert "barstock_backup_20260124_x.db" in remaining
    assert "barstock_backup_20260100_x.db" not in remaining
