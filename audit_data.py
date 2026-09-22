#!/usr/bin/env python3
"""
Standalone data-health audit for BarStock.

Reports inconsistencies between the live data sources without modifying anything.
Run with:

    cd "/Users/kiffy/PGC Barstock"
    python3 audit_data.py

Checks:
- Negative stock in stock.csv / Items.csv / SQLite DB
- Duplicate keys in mapping dictionaries
- Missing category/conversion/order-sheet mappings
- Mismatches between stock.csv, Items.csv, SQLite inventory, and transaction_log.csv
- Stock-vs-transaction-log reconciliation differences
"""

from __future__ import annotations

import ast
import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd

# Ensure project modules are importable
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from conversions import STOCK_CONVERSIONS
from categories import CATEGORY_MAP
from order_sheet_layout import get_order_sheet_layout
from sales_mapping import SALES_TO_PARENT
from actions import (
    ACTION_SALES,
    ACTION_SALES_ONE_UNIT,
    ACTION_DELIVERY,
    ACTION_WASTAGE,
    ACTION_LINE_CLEAN,
    ACTION_COMPLIMENTARY,
    ACTION_OPEN_TAB,
    ACTION_TAB_CANCELLED,
    ACTION_PARENT_STOCK_ADJ,
    ACTION_STOCKTAKE_BASELINE,
    ACTION_IMPORT,
    CONSUMPTION_ACTIONS,
)
from categories import SALES_INCLUDED_EXCLUDED_ITEMS


def _load_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception as e:
        print(f"  WARNING: could not read {path}: {e}")
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
    if stock_df.empty or "quantity" not in stock_df.columns:
        return issues
    non_stocked = {str(i).lower() for i in SALES_INCLUDED_EXCLUDED_ITEMS}
    neg = stock_df[pd.to_numeric(stock_df["quantity"], errors="coerce") < 0]
    for _, row in neg.iterrows():
        item = str(row.get("item_id", row.get("Name", "unknown"))).lower()
        if item in non_stocked:
            # These items generate revenue but stock is not held/tracked.
            continue
        qty = row["quantity"]
        issues.append(f"Negative stock in {label}: {item} = {qty}")
    return issues


def check_missing_mappings(stock_df: pd.DataFrame) -> list[str]:
    issues: list[str] = []
    if stock_df.empty:
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
        item_id = str(row["item_id"]).lower()
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
            and item_id not in SALES_TO_PARENT
        ):
            issues.append(f"Missing conversion mapping: {name} ({item_id}) - {measure}")

        # Category check
        if item_id not in category_ids and item_id not in SALES_TO_PARENT:
            issues.append(f"Missing category mapping: {name} ({item_id})")

        # Order sheet check
        if item_id not in order_sheet_ids and item_id not in SALES_TO_PARENT:
            issues.append(f"Not linked on order sheet: {name} ({item_id})")

    return issues


def check_csv_consistency(stock_df: pd.DataFrame, items_df: pd.DataFrame) -> list[str]:
    """Compare stock.csv against Items.csv."""
    issues: list[str] = []
    if stock_df.empty or items_df.empty:
        return issues

    # Build item_id columns consistently with sales_mapping.normalize_product_name
    items_df = items_df.copy()
    items_df["item_id"] = (
        items_df["Name"]
        .astype(str)
        .str.lower()
        .str.replace(" ", "_", regex=False)
        .str.replace("'", "", regex=False)
        .str.replace(".", "", regex=False)
        .str.replace("/", "_", regex=False)
    )

    stock_ids = set(stock_df["item_id"].astype(str).str.lower())
    item_ids = set(items_df["item_id"])

    for item_id in sorted(stock_ids - item_ids):
        name = stock_df.loc[stock_df["item_id"].str.lower() == item_id, "item_name"].iloc[0]
        issues.append(f"In stock.csv but not Items.csv: {name} ({item_id})")

    for item_id in sorted(item_ids - stock_ids):
        name = items_df.loc[items_df["item_id"] == item_id, "Name"].iloc[0]
        issues.append(f"In Items.csv but not stock.csv: {name} ({item_id})")

    # Quantity mismatches
    stock_for_merge = stock_df[["item_id", "item_name", "quantity"]].copy()
    stock_for_merge["item_id_lower"] = stock_for_merge["item_id"].astype(str).str.lower()
    items_for_merge = items_df[["item_id", "Total Stock"]].copy()
    merged = stock_for_merge.merge(
        items_for_merge,
        left_on="item_id_lower",
        right_on="item_id",
        how="inner",
        suffixes=("_stock", "_items"),
    )
    merged["stock_qty"] = pd.to_numeric(merged["quantity"], errors="coerce")
    merged["items_qty"] = pd.to_numeric(merged["Total Stock"], errors="coerce")
    merged["diff"] = merged["stock_qty"] - merged["items_qty"]
    mismatches = merged[abs(merged["diff"]) > 0.01]
    for _, row in mismatches.iterrows():
        issues.append(
            f"Quantity mismatch stock.csv vs Items.csv: {row['item_name']} "
            f"(stock={row['stock_qty']:.2f}, items={row['items_qty']:.2f}, diff={row['diff']:.2f})"
        )

    return issues


def check_stock_vs_log(stock_df: pd.DataFrame, log_df: pd.DataFrame) -> list[str]:
    """Compare current stock against expected from transaction log."""
    issues: list[str] = []
    if stock_df.empty or log_df.empty:
        return issues

    log_df = log_df.copy()
    log_df["quantity"] = pd.to_numeric(log_df["quantity"], errors="coerce").fillna(0)

    expected: dict[str, float] = {}
    for _, row in log_df.iterrows():
        item = str(row["item_id"]).lower()
        action = str(row["action"]).strip()
        action_lower = action.lower()
        qty = float(row["quantity"])
        additive_actions = {
            ACTION_IMPORT.lower(),
            ACTION_DELIVERY.lower(),
            ACTION_TAB_CANCELLED.lower(),
            "stocktake adjustment",
        }
        # Stocktake Baseline is an audit marker; the Stocktake Adjustment carries
        # the actual variance delta. This mirrors the SQLite reconciliation.
        # Parent stock adjustments record the parent-side stock movement caused
        # by a child sale/complimentary transaction. They are always reductions,
        # so they must be treated as consumption for reconciliation.
        consumption_actions = {a.lower() for a in CONSUMPTION_ACTIONS} | {ACTION_OPEN_TAB.lower(), ACTION_PARENT_STOCK_ADJ.lower()}
        if action_lower == ACTION_STOCKTAKE_BASELINE.lower():
            # Marker only; the matching Stocktake Adjustment records the delta.
            continue
        elif action_lower in additive_actions:
            expected[item] = expected.get(item, 0.0) + qty
        elif action_lower in consumption_actions:
            expected[item] = expected.get(item, 0.0) - qty
        else:
            # Unrecognised action: report it
            issues.append(f"Unrecognised transaction action '{action}' for {item}")

    child_ids = {k.lower() for k in SALES_TO_PARENT.keys()}
    non_stocked = {str(i).lower() for i in SALES_INCLUDED_EXCLUDED_ITEMS}
    for _, row in stock_df.iterrows():
        item = str(row["item_id"]).lower()
        if item in child_ids:
            # Child items deduct from parent stock; their own inventory in
            # stock.csv is maintained independently and should not be
            # reconciled against parent/child combined movements here.
            continue
        if item in non_stocked:
            # Revenue-only items do not hold stock; their quantity is kept at 0
            # and should not be reconciled against transaction volume.
            continue
        actual = float(row["quantity"])
        exp = expected.get(item, 0.0)
        if abs(actual - exp) > 0.01:
            issues.append(
                f"Stock vs transaction log mismatch: {row.get('item_name', item)} "
                f"(actual={actual:.2f}, expected_from_log={exp:.2f}, diff={actual - exp:.2f})"
            )

    return issues


def check_sqlite_if_present() -> list[str]:
    """Check the migrated SQLite database if it exists."""
    issues: list[str] = []
    db_path = Path.home() / "Library" / "Application Support" / "BarStockManagement" / "barstock.db"
    if not db_path.exists():
        return issues

    try:
        conn = sqlite3.connect(db_path)
        inv = pd.read_sql_query("SELECT item_id, item_name, quantity FROM inventory", conn)
        non_stocked = {str(i).lower() for i in SALES_INCLUDED_EXCLUDED_ITEMS}
        neg = inv[pd.to_numeric(inv["quantity"], errors="coerce") < 0]
        for _, row in neg.iterrows():
            item = str(row["item_id"]).lower()
            if item in non_stocked:
                continue
            issues.append(
                f"Negative stock in SQLite DB: {row['item_name']} ({row['item_id']}) = {row['quantity']}"
            )

        # Count transactions
        tx_count = pd.read_sql_query("SELECT COUNT(*) AS c FROM transactions", conn).iloc[0]["c"]
        archived = pd.read_sql_query("SELECT COUNT(*) AS c FROM transaction_archive", conn).iloc[0]["c"]
        print(f"  SQLite DB found: {db_path}")
        print(f"    Active transactions: {tx_count}")
        print(f"    Archived transactions: {archived}")
        conn.close()
    except Exception as e:
        issues.append(f"Could not audit SQLite DB: {e}")

    return issues


def check_sqlite_inventory_vs_csv(stock_df: pd.DataFrame) -> list[str]:
    """Compare SQLite inventory quantities to stock.csv."""
    issues: list[str] = []
    db_path = Path.home() / "Library" / "Application Support" / "BarStockManagement" / "barstock.db"
    if not db_path.exists() or stock_df is None or stock_df.empty:
        return issues

    try:
        conn = sqlite3.connect(db_path)
        inv = pd.read_sql_query("SELECT item_id, item_name, quantity FROM inventory", conn)
        conn.close()

        inv["item_id_lower"] = inv["item_id"].astype(str).str.lower()
        stock_df = stock_df.copy()
        stock_df["item_id_lower"] = stock_df["item_id"].astype(str).str.lower()

        inv_ids = set(inv["item_id_lower"])
        stock_ids = set(stock_df["item_id_lower"])

        for iid in sorted(inv_ids - stock_ids):
            name = inv.loc[inv["item_id_lower"] == iid, "item_name"].iloc[0]
            issues.append(f"In SQLite inventory but not stock.csv: {name} ({iid})")

        for iid in sorted(stock_ids - inv_ids):
            name = stock_df.loc[stock_df["item_id_lower"] == iid, "item_name"].iloc[0]
            issues.append(f"In stock.csv but not SQLite inventory: {name} ({iid})")

        merged = inv[["item_id_lower", "item_name", "quantity"]].merge(
            stock_df[["item_id_lower", "quantity"]],
            on="item_id_lower",
            how="inner",
            suffixes=("_db", "_csv"),
        )
        merged["db_qty"] = pd.to_numeric(merged["quantity_db"], errors="coerce")
        merged["csv_qty"] = pd.to_numeric(merged["quantity_csv"], errors="coerce")
        merged["diff"] = merged["db_qty"] - merged["csv_qty"]
        mismatches = merged[abs(merged["diff"]) > 0.01].sort_values("diff", key=abs, ascending=False)
        for _, row in mismatches.iterrows():
            issues.append(
                f"SQLite vs stock.csv mismatch: {row['item_name']} ({row['item_id_lower']}) "
                f"db={row['db_qty']:.2f}, csv={row['csv_qty']:.2f}, diff={row['diff']:.2f}"
            )
    except Exception as e:
        issues.append(f"Could not compare SQLite inventory to stock.csv: {e}")

    return issues


def check_sqlite_transactions_reconciliation() -> list[str]:
    """Reconcile SQLite inventory against active SQLite transactions.

    Only active transactions are replayed because archived transactions are
    superseded by the current Stocktake Baseline. Child/deduction items that
    map to a parent in SALES_TO_PARENT are skipped; they do not hold
    independent stock.
    """
    issues: list[str] = []
    db_path = Path.home() / "Library" / "Application Support" / "BarStockManagement" / "barstock.db"
    if not db_path.exists():
        return issues

    additive_actions = {
        ACTION_IMPORT.lower(),
        ACTION_DELIVERY.lower(),
        ACTION_TAB_CANCELLED.lower(),
        "stocktake adjustment",
    }
    # Parent stock adjustments record the parent-side stock movement caused by
    # a child sale/complimentary transaction. They are always reductions, so they
    # must be treated as consumption for stock reconciliation.
    consumption_actions = {a.lower() for a in CONSUMPTION_ACTIONS} | {ACTION_OPEN_TAB.lower(), ACTION_PARENT_STOCK_ADJ.lower()}

    try:
        conn = sqlite3.connect(db_path)
        tx = pd.read_sql_query(
            "SELECT item_id, action, quantity, timestamp FROM transactions ORDER BY timestamp",
            conn,
        )
        inv = pd.read_sql_query("SELECT item_id, item_name, quantity FROM inventory", conn)
        conn.close()

        expected: dict[str, float] = {}
        for _, row in tx.iterrows():
            item = str(row["item_id"]).lower()
            action = str(row["action"]).strip()
            action_lower = action.lower()
            qty = float(row["quantity"])

            if action == ACTION_STOCKTAKE_BASELINE:
                # Baseline is an audit marker only; the Stocktake Adjustment
                # transaction carries the actual variance delta.
                continue
            elif action_lower in additive_actions:
                expected[item] = expected.get(item, 0.0) + qty
            elif action_lower in consumption_actions:
                expected[item] = expected.get(item, 0.0) - qty
            else:
                issues.append(f"Unrecognised SQLite action '{action}' for {item}")

        child_ids = {k.lower() for k in SALES_TO_PARENT.keys()}
        non_stocked = {str(i).lower() for i in SALES_INCLUDED_EXCLUDED_ITEMS}
        for _, row in inv.iterrows():
            item = str(row["item_id"]).lower()
            if item in child_ids:
                # Child items deduct from parent stock; their own inventory
                # is maintained at 0 and should not be reconciled here.
                continue
            if item in non_stocked:
                # Revenue-only items do not hold stock.
                continue
            actual = float(row["quantity"])
            exp = expected.get(item, 0.0)
            if abs(actual - exp) > 0.01:
                issues.append(
                    f"SQLite inventory vs transactions mismatch: {row['item_name']} ({item}) "
                    f"actual={actual:.2f}, expected_from_tx={exp:.2f}, diff={actual - exp:.2f}"
                )
    except Exception as e:
        issues.append(f"Could not reconcile SQLite transactions: {e}")

    return issues


def main() -> int:
    print("=" * 70)
    print("BarStock Data Health Audit")
    print("=" * 70)

    stock_path = PROJECT_ROOT / "stock.csv"
    items_path = PROJECT_ROOT / "Items.csv"
    log_path = PROJECT_ROOT / "transaction_log.csv"

    stock_df = _load_csv(stock_path)
    items_df = _load_csv(items_path)
    log_df = _load_csv(log_path)

    all_issues: list[str] = []

    print("\n1. Duplicate keys in mapping dictionaries")
    dup_issues = check_duplicate_keys()
    all_issues.extend(dup_issues)
    if dup_issues:
        for issue in dup_issues:
            print(f"  {issue}")
    else:
        print("  No duplicate keys found ✓")

    print("\n2. Negative stock")
    neg_issues: list[str] = []
    if stock_df is not None:
        neg_issues.extend(check_negative_stock(stock_df, "stock.csv"))
    if items_df is not None:
        neg_issues.extend(check_negative_stock(items_df, "Items.csv"))
    neg_issues.extend(check_sqlite_if_present())
    all_issues.extend(neg_issues)
    if neg_issues:
        for issue in neg_issues:
            print(f"  {issue}")
    else:
        print("  No negative stock found ✓")

    print("\n3. Missing mappings")
    if stock_df is not None:
        map_issues = check_missing_mappings(stock_df)
        all_issues.extend(map_issues)
        if map_issues:
            for issue in map_issues:
                print(f"  {issue}")
        else:
            print("  No missing mappings ✓")
    else:
        print("  stock.csv not found; skipping")

    print("\n4. stock.csv vs Items.csv consistency")
    if stock_df is not None and items_df is not None:
        csv_issues = check_csv_consistency(stock_df, items_df)
        all_issues.extend(csv_issues)
        if csv_issues:
            for issue in csv_issues[:50]:  # cap output
                print(f"  {issue}")
            if len(csv_issues) > 50:
                print(f"  ... and {len(csv_issues) - 50} more")
        else:
            print("  CSVs are consistent ✓")
    else:
        print("  stock.csv or Items.csv not found; skipping")

    print("\n5. stock.csv vs transaction_log.csv reconciliation")
    if stock_df is not None and log_df is not None:
        log_issues = check_stock_vs_log(stock_df, log_df)
        all_issues.extend(log_issues)
        if log_issues:
            for issue in log_issues[:50]:
                print(f"  {issue}")
            if len(log_issues) > 50:
                print(f"  ... and {len(log_issues) - 50} more")
        else:
            print("  Stock and transaction log reconcile ✓")
    else:
        print("  stock.csv or transaction_log.csv not found; skipping")

    print("\n6. SQLite inventory vs stock.csv")
    sqlite_csv_issues = check_sqlite_inventory_vs_csv(stock_df)
    all_issues.extend(sqlite_csv_issues)
    if sqlite_csv_issues:
        for issue in sqlite_csv_issues[:50]:
            print(f"  {issue}")
        if len(sqlite_csv_issues) > 50:
            print(f"  ... and {len(sqlite_csv_issues) - 50} more")
    else:
        print("  SQLite inventory matches stock.csv ✓")

    print("\n7. SQLite inventory vs SQLite transactions reconciliation")
    sqlite_tx_issues = check_sqlite_transactions_reconciliation()
    all_issues.extend(sqlite_tx_issues)
    if sqlite_tx_issues:
        for issue in sqlite_tx_issues[:50]:
            print(f"  {issue}")
        if len(sqlite_tx_issues) > 50:
            print(f"  ... and {len(sqlite_tx_issues) - 50} more")
    else:
        print("  SQLite inventory reconciles with transactions ✓")

    print("\n" + "=" * 70)
    print(f"Audit complete: {len(all_issues)} issue(s) found.")
    print("=" * 70)

    return 1 if all_issues else 0


if __name__ == "__main__":
    sys.exit(main())
