#!/usr/bin/env python3
"""One-off migration: convert stored cost/sell prices from inc-VAT to ex-VAT.

This script is intentionally separate from the app. It must be run once before
starting the app after the ex-VAT code changes are deployed.

Behaviour:
  - Backs up stock.csv, Items.csv, transaction_log.csv, and the SQLite DB.
  - Divides every cost_price, sell_price and value field by 1.2.
  - Leaves quantities untouched.
  - Default mode is dry-run; pass --run to apply changes.

Run:
    python3 migrate_to_ex_vat.py --dry-run
    python3 migrate_to_ex_vat.py --run
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from app_config import DATA_DIR, sqlite_ro_uri

VAT_DIVISOR = 1.2

SCRIPT_DIR = Path(__file__).resolve().parent
APP_SUPPORT_DIR = Path(DATA_DIR)

# Files we may mutate
STOCK_CSV = APP_SUPPORT_DIR / "stock.csv"
ITEMS_CSV = APP_SUPPORT_DIR / "Items.csv"
LOG_CSV = APP_SUPPORT_DIR / "transaction_log.csv"
DB_PATH = APP_SUPPORT_DIR / "barstock.db"


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _backup_path(label: str) -> Path:
    backup_dir = SCRIPT_DIR / "Backups" / f"migrate_to_ex_vat_{_timestamp()}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir / label


def _copy_with_backup(src: Path, backup_label: str) -> Path | None:
    if not src.exists():
        return None
    backup = _backup_path(backup_label)
    shutil.copy2(src, backup)
    return backup


def _divide_or_passthrough(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for col in columns:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0) / VAT_DIVISOR
    return df


def _update_stock_csv(dry_run: bool) -> dict:
    result = {"path": str(STOCK_CSV), "rows_changed": 0, "backup": None}
    if not STOCK_CSV.exists():
        result["skipped"] = "file not found"
        return result

    df = pd.read_csv(STOCK_CSV)
    if df.empty:
        result["skipped"] = "empty file"
        return result

    if dry_run:
        result["preview"] = _preview_price_changes(df, ["cost_price", "sell_price", "Total Value"])
        return result

    result["backup"] = str(_copy_with_backup(STOCK_CSV, "stock.csv.bak"))
    df = _divide_or_passthrough(df, ["cost_price", "sell_price", "Total Value"])
    df.to_csv(STOCK_CSV, index=False)
    result["rows_changed"] = len(df)
    return result


def _update_items_csv(dry_run: bool) -> dict:
    result = {"path": str(ITEMS_CSV), "rows_changed": 0, "backup": None}
    if not ITEMS_CSV.exists():
        result["skipped"] = "file not found"
        return result

    df = pd.read_csv(ITEMS_CSV)
    if df.empty:
        result["skipped"] = "empty file"
        return result

    if dry_run:
        result["preview"] = _preview_price_changes(df, ["Total Value"])
        return result

    result["backup"] = str(_copy_with_backup(ITEMS_CSV, "Items.csv.bak"))
    df = _divide_or_passthrough(df, ["Total Value"])
    df.to_csv(ITEMS_CSV, index=False)
    result["rows_changed"] = len(df)
    return result


def _update_transaction_log_csv(dry_run: bool) -> dict:
    result = {"path": str(LOG_CSV), "rows_changed": 0, "backup": None}
    if not LOG_CSV.exists():
        result["skipped"] = "file not found"
        return result

    df = pd.read_csv(LOG_CSV)
    if df.empty:
        result["skipped"] = "empty file"
        return result

    if dry_run:
        result["preview"] = _preview_price_changes(df, ["cost_price", "sell_price"])
        return result

    result["backup"] = str(_copy_with_backup(LOG_CSV, "transaction_log.csv.bak"))
    df = _divide_or_passthrough(df, ["cost_price", "sell_price"])
    df.to_csv(LOG_CSV, index=False)
    result["rows_changed"] = len(df)
    return result


def _preview_price_changes(df: pd.DataFrame, cols: list[str]) -> list[dict]:
    previews: list[dict] = []
    for col in cols:
        if col not in df.columns:
            continue
        numeric = pd.to_numeric(df[col], errors="coerce").fillna(0)
        nonzero = numeric[numeric > 0]
        if nonzero.empty:
            continue
        sample = nonzero.nlargest(min(5, len(nonzero)))
        for idx, val in sample.items():
            previews.append({
                "item": str(df.iloc[idx].get(df.columns[0], idx)),
                "field": col,
                "old": round(val, 4),
                "new": round(val / VAT_DIVISOR, 4),
            })
    return previews


def _update_sqlite(dry_run: bool) -> dict:
    result = {"path": str(DB_PATH), "tables": {}, "backup": None}
    if not DB_PATH.exists():
        result["skipped"] = "database not found"
        return result

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    targets = [
        ("inventory", "cost_price"),
        ("inventory", "sell_price"),
        ("transactions", "cost_price"),
        ("transactions", "sell_price"),
        ("transaction_archive", "cost_price"),
        ("transaction_archive", "sell_price"),
    ]

    previews: list[dict] = []
    for table, col in targets:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table} WHERE {col} > 0")
            count = cursor.fetchone()[0]
            cursor.execute(f"SELECT {col} FROM {table} WHERE {col} > 0 LIMIT 5")
            sample_old = [r[0] for r in cursor.fetchall()]
            previews.append({
                "table": table,
                "column": col,
                "rows_with_positive_price": count,
                "sample_old_values": [round(v, 4) for v in sample_old],
            })
        except sqlite3.OperationalError as e:
            previews.append({"table": table, "column": col, "error": str(e)})

    result["tables"] = previews

    if dry_run:
        conn.close()
        return result

    result["backup"] = str(_copy_with_backup(DB_PATH, "barstock.db.bak"))
    for table, col in targets:
        try:
            cursor.execute(f"UPDATE {table} SET {col} = {col} / ? WHERE {col} IS NOT NULL", (VAT_DIVISOR,))
        except sqlite3.OperationalError as e:
            print(f"Warning: could not update {table}.{col}: {e}")
    conn.commit()
    conn.close()
    return result


def _print_result(label: str, result: dict) -> None:
    print(f"\n{label}")
    print(f"  Path: {result.get('path', 'N/A')}")
    if "skipped" in result:
        print(f"  Skipped: {result['skipped']}")
        return
    if "rows_changed" in result:
        print(f"  Rows changed: {result['rows_changed']}")
    if result.get("backup"):
        print(f"  Backup: {result['backup']}")
    previews = result.get("preview") or result.get("tables")
    if previews:
        print("  Preview:")
        for p in previews:
            print(f"    {p}")


PRICE_BASIS = "ex_vat"
OPPOSITE_BASIS = "inc_vat"


def _read_price_basis() -> str | None:
    """Return the stored price basis marker, if the database has one."""
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(sqlite_ro_uri(DB_PATH), uri=True)
        try:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = 'price_basis'"
            ).fetchone()
        finally:
            conn.close()
        return row[0] if row else None
    except sqlite3.Error:
        return None


def _write_price_basis(value: str) -> None:
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('price_basis', ?)",
            (value,),
        )
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate BarStock prices from inc-VAT to ex-VAT.")
    parser.add_argument("--run", action="store_true", help="Apply changes (default is dry-run).")
    parser.add_argument("--force", action="store_true",
                        help="Run even if the database already records a price basis.")
    args = parser.parse_args()

    current_basis = _read_price_basis()
    if current_basis == PRICE_BASIS and not args.force:
        print("Database is already marked ex-VAT; nothing to do. Use --force to divide again.")
        return 0
    if current_basis == OPPOSITE_BASIS and not args.force:
        print(
            "Database is marked inc-VAT. Running this script would divide prices a second "
            "time.\nRe-run with --force only if you are certain."
        )
        return 1

    dry_run = not args.run
    print(f"Mode: {'DRY-RUN' if dry_run else 'APPLY'}")
    print(f"All prices and values will be divided by {VAT_DIVISOR}.")

    _print_result("Stock CSV", _update_stock_csv(dry_run))
    _print_result("Items CSV", _update_items_csv(dry_run))
    _print_result("Transaction Log CSV", _update_transaction_log_csv(dry_run))
    _print_result("SQLite DB", _update_sqlite(dry_run))

    if dry_run:
        print("\nDry-run complete. Pass --run to apply changes.")
    else:
        _write_price_basis(PRICE_BASIS)
        print("\nMigration complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
