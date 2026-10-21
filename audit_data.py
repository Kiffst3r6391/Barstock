#!/usr/bin/env python3
"""Standalone data-health audit for BarStock.

Reports inconsistencies between the live data sources without modifying
anything.

Run with::

    python3 audit_data.py                 # audit the live app-support database
    python3 audit_data.py --json          # machine-readable report on stdout
    python3 audit_data.py --db PATH --csv-dir DIR

Checks:
- Negative stock in stock.csv / Items.csv / SQLite DB
- Duplicate keys in mapping dictionaries
- Missing category/conversion/order-sheet mappings
- Mismatches between stock.csv, Items.csv and the SQLite inventory
- Stock-vs-transaction-log reconciliation differences

Exit status is 1 when any issue is found, so the script can be used as a CI
or pre-build health gate.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd

# Ensure project modules are importable
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from conversions import STOCK_CONVERSIONS
from categories import CATEGORY_MAP, DELISTED_ITEMS, EXCLUDED_ITEMS, SALES_INCLUDED_EXCLUDED_ITEMS
from order_sheet_layout import get_order_sheet_layout
from sales_mapping import SALES_TO_PARENT, normalize_product_name
from actions import ACTION_SALES, ACTION_SALES_ONE_UNIT
from reports import calculate_expected_remaining_series

APP_SUPPORT_DIR = Path.home() / "Library" / "Application Support" / "BarStockManagement"
DEFAULT_DB = APP_SUPPORT_DIR / "barstock.db"


def _default_csv_dir() -> Path:
    """Prefer the live app-support mirrors; fall back to the repo."""
    if (APP_SUPPORT_DIR / "stock.csv").exists():
        return APP_SUPPORT_DIR
    return PROJECT_ROOT


def _lower_set(values) -> set[str]:
    return {str(value).lower() for value in values}


NON_STOCKED = _lower_set(SALES_INCLUDED_EXCLUDED_ITEMS)
IGNORED = _lower_set(EXCLUDED_ITEMS) | _lower_set(DELISTED_ITEMS)
CHILD_ITEMS = _lower_set(SALES_TO_PARENT.keys())


def _item_id_from_row(row) -> str:
    """Return a canonical item id for either a stock.csv or Items.csv row."""
    raw = row.get("item_id") if "item_id" in row else row.get("Name", "")
    if raw is None or (isinstance(raw, float) and pd.isna(raw)) or str(raw).strip() == "":
        raw = row.get("Name", "unknown")
    return normalize_product_name(str(raw).strip())


def _is_reconciled_item(item_id: str) -> bool:
    """True when the item holds independently reconcilable stock."""
    item_id = item_id.lower()
    return (
        item_id not in CHILD_ITEMS
        and item_id not in NON_STOCKED
        and item_id not in IGNORED
    )


def _load_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception as e:
        print(f"  WARNING: could not read {path}: {e}", file=sys.stderr)
        return None


def _find_duplicate_dict_keys(file_path: Path, var_name: str) -> list[tuple[str, int, int]]:
    """Return (key, first_line, duplicate_line) for duplicate literal dict keys."""
    text = file_path.read_text()
    tree = ast.parse(text)
    duplicates = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == var_name:
                    d = node.value
                    if not isinstance(d, ast.Dict):
                        continue
                    seen: dict[str, int] = {}
                    for k in d.keys:
                        if isinstance(k, ast.Constant) and isinstance(k.value, str):
                            key = k.value
                            if key in seen:
                                duplicates.append((key, seen[key], k.lineno))
                            else:
                                seen[key] = k.lineno
    return duplicates


def check_duplicate_keys() -> list[str]:
    """Check mapping dictionaries for duplicate literal keys."""
    issues: list[str] = []
    for file_path, var_name in [
        (PROJECT_ROOT / "sales_mapping.py", "SALES_TO_PARENT"),
        (PROJECT_ROOT / "categories.py", "CATEGORY_MAP"),
        (PROJECT_ROOT / "conversions.py", "STOCK_CONVERSIONS"),
        (PROJECT_ROOT / "supplier_mapping.py", "ITEM_SUPPLIER_MAP"),
    ]:
        dups = _find_duplicate_dict_keys(file_path, var_name)
        for key, first, second in dups:
            issues.append(
                f"Duplicate key '{key}' in {file_path.name}:{var_name} "
                f"(first at {first}, duplicate at {second})"
            )
    return issues


def check_negative_stock(stock_df: pd.DataFrame, label: str) -> list[str]:
    issues: list[str] = []
    if stock_df is None or stock_df.empty or "quantity" not in stock_df.columns:
        # Items.csv holds stock in "Total Stock"
        if stock_df is None or stock_df.empty or "Total Stock" not in stock_df.columns:
            return issues
        quantity = pd.to_numeric(stock_df["Total Stock"], errors="coerce")
    else:
        quantity = pd.to_numeric(stock_df["quantity"], errors="coerce")

    for idx, qty in quantity.items():
        if pd.isna(qty) or qty >= 0:
            continue
        row = stock_df.loc[idx]
        item = _item_id_from_row(row)
        if not _is_reconciled_item(item):
            continue
        issues.append(f"Negative stock in {label}: {item} = {qty}")
    return issues


def check_missing_mappings(stock_df: pd.DataFrame) -> list[str]:
    issues: list[str] = []
    if stock_df is None or stock_df.empty:
        return issues

    order_sheet_ids = set()
    for supplier, categories in get_order_sheet_layout():
        for cat, items in categories:
            for display_name, item_id in items:
                if item_id:
                    order_sheet_ids.add(str(item_id).lower())

    conversion_ids = {k.lower() for k in STOCK_CONVERSIONS.keys()}
    category_ids = {k.lower() for k in CATEGORY_MAP.keys()}

    for _, row in stock_df.iterrows():
        item_id = _item_id_from_row(row)
        if not _is_reconciled_item(item_id):
            continue
        measure = str(row.get("measure", "")).strip().upper()
        name = row.get("item_name", item_id)

        # Conversion check for items stored in system units
        needs_conversion = measure in {"PINT", "HALF PINT", "35ML", "SERVE", "CUP"}
        # Hot drinks are counted in cups directly; they do not have a bulk
        # packaging conversion. Cointreau has its own bottle/measure handling.
        excluded = {
            "guinness_0_0", "guinness_can", "pint", "half_pint", "cointreau",
            "barista_coffee", "cart_roll_tea_coffee", "specialist_tea", "tea",
        }
        if (
            needs_conversion
            and item_id not in conversion_ids
            and item_id not in excluded
        ):
            issues.append(f"Missing conversion mapping: {name} ({item_id}) - {measure}")

        # Category check
        if item_id not in category_ids:
            issues.append(f"Missing category mapping: {name} ({item_id})")

        # Order sheet check
        if item_id not in order_sheet_ids:
            issues.append(f"Not linked on order sheet: {name} ({item_id})")

    return issues


def check_csv_consistency(stock_df: pd.DataFrame, items_df: pd.DataFrame) -> list[str]:
    """Compare stock.csv against Items.csv."""
    issues: list[str] = []
    if stock_df is None or stock_df.empty or items_df is None or items_df.empty:
        return issues

    stock = stock_df.copy()
    stock["item_id_norm"] = stock.apply(_item_id_from_row, axis=1)
    items = items_df.copy()
    items["item_id_norm"] = items.apply(_item_id_from_row, axis=1)

    stock_ids = set(stock["item_id_norm"])
    item_ids = set(items["item_id_norm"])

    for item_id in sorted(stock_ids - item_ids):
        row = stock.loc[stock["item_id_norm"] == item_id].iloc[0]
        if _is_reconciled_item(item_id):
            issues.append(f"In stock.csv but not Items.csv: {row.get('item_name', item_id)} ({item_id})")

    for item_id in sorted(item_ids - stock_ids):
        row = items.loc[items["item_id_norm"] == item_id].iloc[0]
        if _is_reconciled_item(item_id):
            issues.append(f"In Items.csv but not stock.csv: {row.get('Name', item_id)} ({item_id})")

    if "Total Stock" not in items.columns:
        return issues

    stock_for_merge = stock[["item_id_norm", "item_name", "quantity"]].copy()
    items_for_merge = items[["item_id_norm", "Total Stock"]].copy()
    merged = stock_for_merge.merge(items_for_merge, on="item_id_norm", how="inner")
    merged["stock_qty"] = pd.to_numeric(merged["quantity"], errors="coerce")
    merged["items_qty"] = pd.to_numeric(merged["Total Stock"], errors="coerce")
    merged["diff"] = merged["stock_qty"] - merged["items_qty"]
    mismatches = merged[abs(merged["diff"]) > 0.01]
    for _, row in mismatches.iterrows():
        if not _is_reconciled_item(row["item_id_norm"]):
            continue
        issues.append(
            f"Quantity mismatch stock.csv vs Items.csv: {row['item_name']} "
            f"(stock={row['stock_qty']:.2f}, items={row['items_qty']:.2f}, diff={row['diff']:.2f})"
        )

    return issues


def check_stock_vs_log(stock_df: pd.DataFrame, log_df: pd.DataFrame) -> list[str]:
    """Compare current stock.csv against expected stock from a transaction log."""
    issues: list[str] = []
    if stock_df is None or stock_df.empty or log_df is None or log_df.empty:
        return issues

    expected = {
        str(key).lower(): float(value)
        for key, value in calculate_expected_remaining_series(log_df).items()
    }

    for _, row in stock_df.iterrows():
        item = _item_id_from_row(row)
        if not _is_reconciled_item(item):
            continue
        actual = pd.to_numeric(row.get("quantity"), errors="coerce")
        if pd.isna(actual):
            continue
        exp = expected.get(item, 0.0)
        if abs(actual - exp) > 0.01:
            issues.append(
                f"Stock vs transaction log mismatch: {row.get('item_name', item)} "
                f"(actual={actual:.2f}, expected_from_log={exp:.2f}, diff={actual - exp:.2f})"
            )

    return issues


def _load_sqlite(db_path: Path) -> tuple[pd.DataFrame, pd.DataFrame] | None:
    if not db_path.exists():
        return None
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        inv = pd.read_sql_query(
            "SELECT item_id, item_name, quantity FROM inventory ORDER BY item_id", conn
        )
        tx = pd.read_sql_query(
            "SELECT item_id, action, quantity, timestamp FROM transactions ORDER BY timestamp",
            conn,
        )
        return inv, tx
    finally:
        conn.close()


def _db_counts(db_path: Path) -> dict:
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        return {
            "inventory": conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0],
            "transactions": conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0],
            "archived_transactions": conn.execute(
                "SELECT COUNT(*) FROM transaction_archive"
            ).fetchone()[0],
        }
    except sqlite3.Error:
        return {}
    finally:
        conn.close()


def check_sqlite_negative_stock(db_path: Path) -> list[str]:
    issues: list[str] = []
    loaded = _load_sqlite(db_path)
    if loaded is None:
        return issues
    inv, _ = loaded
    quantity = pd.to_numeric(inv["quantity"], errors="coerce")
    for idx, qty in quantity.items():
        if pd.isna(qty) or qty >= 0:
            continue
        row = inv.loc[idx]
        item = str(row["item_id"]).lower()
        if not _is_reconciled_item(item):
            continue
        issues.append(
            f"Negative stock in SQLite DB: {row['item_name']} ({row['item_id']}) = {qty}"
        )
    return issues


def check_sqlite_inventory_vs_csv(db_path: Path, stock_df: pd.DataFrame) -> list[str]:
    """Compare SQLite inventory quantities to stock.csv."""
    issues: list[str] = []
    if stock_df is None or stock_df.empty:
        return issues
    loaded = _load_sqlite(db_path)
    if loaded is None:
        return issues
    inv, _ = loaded

    stock = stock_df.copy()
    stock["item_id_norm"] = stock.apply(_item_id_from_row, axis=1)
    inv = inv.copy()
    inv["item_id_norm"] = inv["item_id"].astype(str).str.lower()

    inv_ids = set(inv["item_id_norm"])
    stock_ids = set(stock["item_id_norm"])

    for iid in sorted(inv_ids - stock_ids):
        if _is_reconciled_item(iid):
            name = inv.loc[inv["item_id_norm"] == iid, "item_name"].iloc[0]
            issues.append(f"In SQLite inventory but not stock.csv: {name} ({iid})")

    for iid in sorted(stock_ids - inv_ids):
        if _is_reconciled_item(iid):
            name = stock.loc[stock["item_id_norm"] == iid, "item_name"].iloc[0]
            issues.append(f"In stock.csv but not SQLite inventory: {name} ({iid})")

    merged = inv[["item_id_norm", "item_name", "quantity"]].merge(
        stock[["item_id_norm", "quantity"]],
        on="item_id_norm",
        how="inner",
        suffixes=("_db", "_csv"),
    )
    merged["db_qty"] = pd.to_numeric(merged["quantity_db"], errors="coerce")
    merged["csv_qty"] = pd.to_numeric(merged["quantity_csv"], errors="coerce")
    merged["diff"] = merged["db_qty"] - merged["csv_qty"]
    mismatches = merged[abs(merged["diff"]) > 0.01].sort_values("diff", key=abs, ascending=False)
    for _, row in mismatches.iterrows():
        if not _is_reconciled_item(row["item_id_norm"]):
            continue
        issues.append(
            f"SQLite vs stock.csv mismatch: {row['item_name']} ({row['item_id_norm']}) "
            f"db={row['db_qty']:.2f}, csv={row['csv_qty']:.2f}, diff={row['diff']:.2f}"
        )

    return issues


def check_sqlite_transactions_reconciliation(db_path: Path) -> list[str]:
    """Reconcile SQLite inventory against its active transaction log.

    The expected level is derived with the same helper the reports use, so the
    audit and the dashboard cannot drift apart: the latest Stocktake Baseline
    anchors each item and every later movement (including adjustments, supplier
    returns and parent deductions) is applied on top of it.
    """
    issues: list[str] = []
    loaded = _load_sqlite(db_path)
    if loaded is None:
        return issues
    inv, tx = loaded
    if tx.empty:
        return issues

    expected = {
        str(key).lower(): float(value)
        for key, value in calculate_expected_remaining_series(tx).items()
    }

    for _, row in inv.iterrows():
        item = str(row["item_id"]).lower()
        if not _is_reconciled_item(item):
            continue
        actual = float(row["quantity"])
        exp = expected.get(item, 0.0)
        if abs(actual - exp) > 0.01:
            issues.append(
                f"SQLite inventory vs transactions mismatch: {row['item_name']} ({item}) "
                f"actual={actual:.2f}, expected_from_tx={exp:.2f}, diff={actual - exp:.2f}"
            )

    return issues


def run_audit(db_path: Path | None = None, csv_dir: Path | None = None) -> dict:
    """Run every check and return a structured report."""
    db_path = Path(db_path) if db_path else DEFAULT_DB
    csv_dir = Path(csv_dir) if csv_dir else _default_csv_dir()

    stock_df = _load_csv(csv_dir / "stock.csv")
    items_df = _load_csv(csv_dir / "Items.csv")
    log_df = _load_csv(csv_dir / "transaction_log.csv")

    # The live database is authoritative: when it is present, reconcile the
    # CSV mirror against the database's transaction history rather than against
    # an exported log that may be months stale.
    loaded = _load_sqlite(db_path)
    if loaded is not None and not loaded[1].empty:
        log_df = loaded[1]

    notes = [
        f"Missing CSV: {csv_dir / name}"
        for name in ("stock.csv", "Items.csv")
        if not (csv_dir / name).exists()
    ]

    sections: dict[str, list[str]] = {}
    sections["duplicate_keys"] = check_duplicate_keys()

    negative: list[str] = []
    if stock_df is not None:
        negative.extend(check_negative_stock(stock_df, "stock.csv"))
    if items_df is not None:
        negative.extend(check_negative_stock(items_df, "Items.csv"))
    negative.extend(check_sqlite_negative_stock(db_path))
    sections["negative_stock"] = negative

    sections["missing_mappings"] = (
        check_missing_mappings(stock_df) if stock_df is not None else []
    )
    sections["csv_consistency"] = (
        check_csv_consistency(stock_df, items_df)
        if stock_df is not None and items_df is not None
        else []
    )
    sections["stock_vs_log"] = (
        check_stock_vs_log(stock_df, log_df)
        if stock_df is not None and log_df is not None
        else []
    )
    sections["sqlite_vs_csv"] = check_sqlite_inventory_vs_csv(db_path, stock_df)
    sections["sqlite_reconciliation"] = check_sqlite_transactions_reconciliation(db_path)

    total = sum(len(value) for value in sections.values())
    return {
        "db": str(db_path),
        "csv_dir": str(csv_dir),
        "db_counts": _db_counts(db_path),
        "notes": notes,
        "sections": sections,
        "issue_count": total,
    }


def reconcile_inventory(db_path: Path | None = None) -> list[str]:
    """Lightweight health check for app start-up.

    Only checks that live inventory agrees with its own transaction log and
    that no stock is negative — the failures that silently corrupt every later
    report. Mapping and CSV checks stay in the full audit.
    """
    db_path = Path(db_path) if db_path else DEFAULT_DB
    issues = check_sqlite_transactions_reconciliation(db_path)
    issues.extend(check_sqlite_negative_stock(db_path))
    return issues


_SECTION_TITLES = [
    ("duplicate_keys", "Duplicate keys in mapping dictionaries"),
    ("negative_stock", "Negative stock"),
    ("missing_mappings", "Missing mappings"),
    ("csv_consistency", "stock.csv vs Items.csv consistency"),
    ("stock_vs_log", "stock.csv vs transaction_log.csv reconciliation"),
    ("sqlite_vs_csv", "SQLite inventory vs stock.csv"),
    ("sqlite_reconciliation", "SQLite inventory vs SQLite transactions reconciliation"),
]

_CAP = 50


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Audit BarStock data health.")
    parser.add_argument("--db", type=Path, default=None, help="SQLite database to audit.")
    parser.add_argument(
        "--csv-dir",
        type=Path,
        default=None,
        help="Directory holding stock.csv / Items.csv / transaction_log.csv.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the report as JSON instead of text.",
    )
    parser.add_argument(
        "--fail-on",
        type=int,
        default=1,
        metavar="N",
        help="Exit non-zero when more than N issues are found (default: 1).",
    )
    args = parser.parse_args(argv)

    report = run_audit(args.db, args.csv_dir)

    if args.json:
        print(json.dumps(report, indent=2))
        return 1 if report["issue_count"] >= args.fail_on else 0

    print("=" * 70)
    print("BarStock Data Health Audit")
    print("=" * 70)
    print(f"Database: {report['db']}")
    print(f"CSV mirror: {report['csv_dir']}")
    counts = report["db_counts"]
    if counts:
        print(
            f"SQLite: {counts.get('inventory', 0)} inventory, "
            f"{counts.get('transactions', 0)} active transactions, "
            f"{counts.get('archived_transactions', 0)} archived"
        )
    for note in report.get("notes", []):
        print(f"Note: {note}")

    for number, (key, title) in enumerate(_SECTION_TITLES, start=1):
        issues = report["sections"].get(key, [])
        print(f"\n{number}. {title}")
        if not issues:
            print("  No issues ✓")
            continue
        for issue in issues[:_CAP]:
            print(f"  {issue}")
        if len(issues) > _CAP:
            print(f"  ... and {len(issues) - _CAP} more")

    print("\n" + "=" * 70)
    print(f"Audit complete: {report['issue_count']} issue(s) found.")
    print("=" * 70)
    return 1 if report["issue_count"] >= args.fail_on else 0


if __name__ == "__main__":
    sys.exit(main())
