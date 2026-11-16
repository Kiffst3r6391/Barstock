#!/usr/bin/env python3
"""One-off migration: convert stored cost prices from ex-VAT to inc-VAT.

This script is intentionally separate from the app. It must be run once before
starting the app after the inc-VAT code changes are deployed.

Behaviour:
  - Backs up stock.csv, Items.csv, transaction_log.csv, and the SQLite DB.
  - Multiplies every cost_price and value field by 1.2.
  - Leaves quantities untouched.
  - Default mode is dry-run; pass --run to apply changes.

Run:
    python3 migrate_to_inc_vat.py --dry-run
    python3 migrate_to_inc_vat.py --run
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

VAT_MULTIPLIER = 1.2

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
    backup_dir = SCRIPT_DIR / "Backups" / f"migrate_to_inc_vat_{_timestamp()}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir / label


def _copy_with_backup(src: Path, backup_label: str) -> Path | None:
    if not src.exists():
        return None
    backup = _backup_path(backup_label)
    shutil.copy2(src, backup)
    return backup


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
        result["preview"] = _preview_cost_changes(df, "cost_price", "Total Value")
        return result

    result["backup"] = str(_copy_with_backup(STOCK_CSV, "stock.csv.bak"))
    df["cost_price"] = pd.to_numeric(df["cost_price"], errors="coerce").fillna(0) * VAT_MULTIPLIER
    if "Total Value" in df.columns:
        df["Total Value"] = pd.to_numeric(df["Total Value"], errors="coerce").fillna(0) * VAT_MULTIPLIER
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
        result["preview"] = _preview_cost_changes(df, value_col="Total Value")
        return result

    result["backup"] = str(_copy_with_backup(ITEMS_CSV, "Items.csv.bak"))
    if "Total Value" in df.columns:
        df["Total Value"] = pd.to_numeric(df["Total Value"], errors="coerce").fillna(0) * VAT_MULTIPLIER
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
        result["preview"] = _preview_cost_changes(df, "cost_price")
        return result

    result["backup"] = str(_copy_with_backup(LOG_CSV, "transaction_log.csv.bak"))
    df["cost_price"] = pd.to_numeric(df["cost_price"], errors="coerce").fillna(0) * VAT_MULTIPLIER
    df.to_csv(LOG_CSV, index=False)
    result["rows_changed"] = len(df)
    return result


def _preview_cost_changes(df: pd.DataFrame, cost_col: str | None = None, value_col: str | None = None) -> list[dict]:
    """Return a short preview of the largest cost/value changes."""
    previews: list[dict] = []
    if cost_col and cost_col in df.columns:
        numeric = pd.to_numeric(df[cost_col], errors="coerce").fillna(0)
        nonzero = numeric[numeric > 0]
        if not nonzero.empty:
            sample = nonzero.nlargest(min(5, len(nonzero)))
            for idx, val in sample.items():
                previews.append({
                    "item": str(df.iloc[idx].get(df.columns[0], idx)),
                    "field": cost_col,
                    "old": round(val, 4),
                    "new": round(val * VAT_MULTIPLIER, 4),
                })
    if value_col and value_col in df.columns:
        numeric = pd.to_numeric(df[value_col], errors="coerce").fillna(0)
        nonzero = numeric[numeric > 0]
        if not nonzero.empty:
            sample = nonzero.nlargest(min(5, len(nonzero)))
            for idx, val in sample.items():
                previews.append({
                    "item": str(df.iloc[idx].get(df.columns[0], idx)),
                    "field": value_col,
                    "old": round(val, 4),
                    "new": round(val * VAT_MULTIPLIER, 4),
                })
    return previews


def _update_sqlite(dry_run: bool) -> dict:
    result = {"path": str(DB_PATH), "tables": {}, "backup": None}
    if not DB_PATH.exists():
        result["skipped"] = "database not found"
        return result

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Tables/columns to update
    targets = [
        ("inventory", "cost_price"),
        ("transactions", "cost_price"),
        ("transaction_archive", "cost_price"),
    ]

    previews: list[dict] = []
    for table, col in targets:
        try:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            cursor.execute(f"SELECT {col} FROM {table} WHERE {col} > 0 LIMIT 5")
            sample_old = [r[0] for r in cursor.fetchall()]
            previews.append({
                "table": table,
                "column": col,
                "rows_with_positive_cost": count,
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
            cursor.execute(f"UPDATE {table} SET {col} = {col} * ? WHERE {col} IS NOT NULL", (VAT_MULTIPLIER,))
        except sqlite3.OperationalError:
            pass  # Table/column may not exist
    conn.commit()
    conn.close()
    return result


def _write_restore_script(backup_dir: Path) -> None:
    script = backup_dir / "restore.sh"
    script.write_text(
        f"#!/bin/sh\n"
        f"# Auto-generated restore script created by migrate_to_inc_vat.py\n"
        f"cd \"{SCRIPT_DIR}\" || exit 1\n"
        f"cp \"{backup_dir / 'stock.csv.bak'}\" stock.csv\n"
        f"cp \"{backup_dir / 'Items.csv.bak'}\" Items.csv\n"
        f"cp \"{backup_dir / 'transaction_log.csv.bak'}\" transaction_log.csv\n"
        f"cp \"{backup_dir / 'barstock.db.bak'}\" \"$HOME/Library/Application Support/BarStockManagement/barstock.db\"\n"
        f"echo 'Restored from {backup_dir.name}'\n"
    )
    script.chmod(0o755)


PRICE_BASIS = "inc_vat"
OPPOSITE_BASIS = "ex_vat"


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
    parser = argparse.ArgumentParser(description="Migrate BarStock cost prices from ex-VAT to inc-VAT.")
    parser.add_argument("--run", action="store_true", help="Apply the migration (default is dry-run)")
    parser.add_argument("--force", action="store_true",
                        help="Run even if the database already records a price basis.")
    args = parser.parse_args()

    current_basis = _read_price_basis()
    if current_basis == PRICE_BASIS and not args.force:
        print("Database is already marked inc-VAT; nothing to do. Use --force to multiply again.")
        return 0
    if current_basis == OPPOSITE_BASIS and not args.force:
        print(
            "Database is marked ex-VAT. Running this script would multiply prices a second "
            "time.\nRe-run with --force only if you are certain."
        )
        return 1

    dry_run = not args.run
    mode_label = "DRY RUN" if dry_run else "APPLY"
    print(f"migrate_to_inc_vat.py — {mode_label}")
    print(f"VAT multiplier: {VAT_MULTIPLIER}")
    print()

    results = {
        "stock.csv": _update_stock_csv(dry_run),
        "Items.csv": _update_items_csv(dry_run),
        "transaction_log.csv": _update_transaction_log_csv(dry_run),
        "sqlite": _update_sqlite(dry_run),
    }

    for name, res in results.items():
        print(f"[{name}]")
        print(f"  path: {res.get('path') or res.get('skipped', 'n/a')}")
        if "skipped" in res:
            print(f"  skipped: {res['skipped']}")
        if "rows_changed" in res and res["rows_changed"]:
            print(f"  rows changed: {res['rows_changed']}")
        if "backup" in res and res["backup"]:
            print(f"  backup: {res['backup']}")
        if "preview" in res:
            print("  preview (largest positive values):")
            for p in res["preview"]:
                print(f"    {p['item']} [{p['field']}] {p['old']} -> {p['new']}")
        if "tables" in res:
            print("  tables:")
            for t in res["tables"]:
                if "error" in t:
                    print(f"    {t['table']}.{t['column']}: error - {t['error']}")
                else:
                    print(f"    {t['table']}.{t['column']}: {t.get('rows_with_positive_cost', 0)} rows, sample old={t.get('sample_old_values', [])}")
        print()

    if not dry_run:
        _write_price_basis(PRICE_BASIS)
        backup_dir = Path(results["stock.csv"]["backup"]).parent
        _write_restore_script(backup_dir)
        print(f"Restore script written to: {backup_dir / 'restore.sh'}")
        print("\nMigration applied. You can now start BarStock with inc-VAT cost prices.")
    else:
        print("Dry run complete. Pass --run to apply these changes.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
