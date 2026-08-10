"""Inventory sync and reconciliation helpers for BarStock.

This module checks that every tracked inventory item is correctly configured in
conversion rules, category mapping, and the order-sheet layout. It also builds
the data for the reconciliation report.
"""

from __future__ import annotations

import csv
import os
from typing import Dict, List, Tuple, Any, Optional

import pandas as pd

from conversions import STOCK_CONVERSIONS
from categories import CATEGORY_MAP, should_exclude
from order_sheet_layout import get_order_sheet_layout
from sales_mapping import SALES_TO_PARENT, is_hidden_from_stock_view

COL_ITEM_ID = 'item_id'
COL_ITEM_NAME = 'item_name'
COL_QUANTITY = 'quantity'
COL_MEASURE = 'measure'
COL_CATEGORY = 'category'
COL_ACTION = 'action'
COL_TIMESTAMP = 'timestamp'
COL_ALLOW_NEGATIVE = 'allow_negative'


def _collect_order_sheet_item_ids() -> set:
    """Return all item_ids referenced by the order sheet layout."""
    ids = set()
    for _supplier_name, categories in get_order_sheet_layout():
        for _category_name, items in categories:
            for _display_name, item_id in items:
                if item_id is not None:
                    ids.add(item_id.lower())
    return ids


def _collect_order_sheet_none_items() -> List[Tuple[str, str, str]]:
    """Return (supplier, category, display_name) for every order-sheet row with None item_id."""
    none_items = []
    for supplier_name, categories in get_order_sheet_layout():
        for category_name, items in categories:
            for display_name, item_id in items:
                if item_id is None:
                    none_items.append((supplier_name, category_name, display_name))
    return none_items


def find_untracked_items_on_order_sheet(inventory_df: pd.DataFrame) -> List[Tuple[str, str, str]]:
    """Find order-sheet rows with None item_id that actually have live stock > 0.

    Returns list of (supplier, category, display_name) tuples.
    """
    if inventory_df.empty:
        return []
    stocked_ids = {str(i).lower() for i in inventory_df[COL_ITEM_ID].values}
    none_items = _collect_order_sheet_none_items()
    result = []
    for supplier, category, display_name in none_items:
        normalized = display_name.lower().replace(" ", "_").replace("'", "")
        # Heuristic: if a name-normalized id exists in inventory and has stock,
        # it should probably be linked.
        if normalized in stocked_ids:
            row = inventory_df[inventory_df[COL_ITEM_ID].str.lower() == normalized]
            if not row.empty and row[COL_QUANTITY].values[0] > 0:
                result.append((supplier, category, display_name))
    return result


def find_missing_mappings(inventory_df: pd.DataFrame) -> Dict[str, List[Dict[str, Any]]]:
    """Check every inventory item for missing configuration.

    Returns a dict with keys:
      - 'missing_conversion': parent stock items whose stored measure differs
        from the delivery input unit and are not in STOCK_CONVERSIONS
      - 'missing_category': items not in CATEGORY_MAP
      - 'missing_order_sheet': items not linked on the printable order sheet
    Each value is a list of dicts with item_id, item_name, quantity.
    """
    if inventory_df.empty:
        return {'missing_conversion': [], 'missing_category': [], 'missing_order_sheet': []}

    order_sheet_ids = _collect_order_sheet_item_ids()
    conversion_ids = {k.lower() for k in STOCK_CONVERSIONS.keys()}
    category_ids = {k.lower() for k in CATEGORY_MAP.keys()}

    missing_conversion = []
    missing_category = []
    missing_order_sheet = []

    for _, row in inventory_df.iterrows():
        item_id = str(row[COL_ITEM_ID])
        item_lower = item_id.lower()
        info = {
            'item_id': item_id,
            'item_name': str(row.get(COL_ITEM_NAME, item_id)),
            'quantity': float(row.get(COL_QUANTITY, 0)),
            'measure': str(row.get(COL_MEASURE, '')),
        }
        has_sales_parent = item_lower in SALES_TO_PARENT and SALES_TO_PARENT[item_lower] is not None
        is_hidden_or_excluded = is_hidden_from_stock_view(item_lower) or should_exclude(item_lower)

        # Only flag conversion issues for items that are independently stocked
        # (not child items that deduct from a parent, not hidden/excluded).
        if (not has_sales_parent
                and not is_hidden_or_excluded
                and not _is_conversion_excluded(item_lower)
                and item_lower not in conversion_ids
                and _looks_like_needs_conversion(info['measure'])):
            missing_conversion.append(info)

        # Category: child items generally don't need their own category mapping
        # because their parent provides the category.
        if item_lower not in category_ids and not has_sales_parent and not is_hidden_or_excluded:
            missing_category.append(info)

        if item_lower not in order_sheet_ids:
            missing_order_sheet.append(info)

    return {
        'missing_conversion': missing_conversion,
        'missing_category': missing_category,
        'missing_order_sheet': missing_order_sheet,
    }


def _looks_like_needs_conversion(measure: str) -> bool:
    """Return True if the stored measure suggests deliveries use a different unit.

    Measures like PINT, HALF PINT, 35ML, SERVE are system units that usually
    come from a conversion. Bottle/can/carton/pack/unit are normally input units
    and don't need a separate conversion.
    """
    m = measure.strip().upper()
    # Empty measure is ambiguous; don't flag it as a conversion issue.
    if not m:
        return False
    return m in {'PINT', 'HALF PINT', '35ML', 'SERVE', 'CUP'}


# Items that are stored in a converted system unit but intentionally have no
# STOCK_CONVERSIONS entry because they are counted/disposed differently.
_CONVERSION_EXCLUDED_ITEM_IDS = {
    'guinness_0_0',   # Guinness micro draught 0% - counted in pints, no barrel conversion
    'guinness_can',     # Guinness surger cans - counted in pints, no case conversion
}


def _is_conversion_excluded(item_id: str) -> bool:
    """Return True for items that don't need a delivery conversion rule."""
    return item_id.lower().strip() in _CONVERSION_EXCLUDED_ITEM_IDS


def format_sync_report(missing: Dict[str, List[Dict[str, Any]]]) -> str:
    """Format missing-mapping results as a human-readable string."""
    lines = []
    if missing['missing_conversion']:
        lines.append("Missing bottle/barrel/box conversion (deliveries won't convert to measures/pints):")
        for info in missing['missing_conversion']:
            lines.append(f"  - {info['item_name']} ({info['item_id']}) - stored as {info.get('measure', '')}")
    if missing['missing_category']:
        lines.append("Missing category mapping:")
        for info in missing['missing_category']:
            lines.append(f"  - {info['item_name']} ({info['item_id']})")
    if missing['missing_order_sheet']:
        lines.append("Not linked on the printable order sheet:")
        for info in missing['missing_order_sheet']:
            lines.append(f"  - {info['item_name']} ({info['item_id']})")
    return "\n".join(lines)


def has_sync_issues(missing: Dict[str, List[Dict[str, Any]]]) -> bool:
    """Return True if any sync issues were found."""
    return any(bool(v) for v in missing.values())


def _load_items_csv_ids(script_dir: str) -> set:
    """Return item_ids from Items.csv, or empty set if file missing."""
    items_csv_path = os.path.join(script_dir, 'Items.csv')
    if not os.path.exists(items_csv_path):
        return set()
    try:
        df = pd.read_csv(items_csv_path)
        if 'Name' not in df.columns:
            return set()
        names = df['Name'].dropna().astype(str).str.lower()
        return set(names.str.replace(' ', '_').str.replace("'", '').str.replace('.', '', regex=False))
    except Exception:
        return set()


def find_items_csv_inventory_mismatches(
    inventory_df: pd.DataFrame,
    script_dir: str,
) -> Dict[str, List[str]]:
    """Compare live inventory with Items.csv master list.

    Returns dict with keys:
      - 'in_inventory_not_csv': item_ids in DB but not Items.csv
      - 'in_csv_not_inventory': names in Items.csv but not DB
    """
    if inventory_df.empty:
        return {'in_inventory_not_csv': [], 'in_csv_not_inventory': []}

    inventory_ids = {str(i).lower() for i in inventory_df[COL_ITEM_ID].values}
    csv_ids = _load_items_csv_ids(script_dir)

    in_inventory_not_csv = sorted([i for i in inventory_df[COL_ITEM_ID].values if str(i).lower() not in csv_ids])
    in_csv_not_inventory = sorted(csv_ids - inventory_ids)

    return {
        'in_inventory_not_csv': in_inventory_not_csv,
        'in_csv_not_inventory': in_csv_not_inventory,
    }


def find_recent_negative_items(
    inventory_df: pd.DataFrame,
    log_df: pd.DataFrame,
    days: int = 7,
) -> List[Dict[str, Any]]:
    """Find items whose stock went negative due to transactions in the last N days.

    Returns list of dicts with item_id, item_name, current_qty, action, timestamp.
    """
    if inventory_df.empty or log_df.empty:
        return []

    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    recent = log_df[log_df[COL_TIMESTAMP] >= cutoff]
    if recent.empty:
        return []

    negative_actions = {'Sales', 'Wastage', 'Complimentary', 'Line Clean'}
    recent_negative = recent[recent[COL_ACTION].isin(negative_actions)]
    if recent_negative.empty:
        return []

    by_item = recent_negative.groupby(COL_ITEM_ID)[COL_QUANTITY].sum().reset_index()
    result = []
    for _, g in by_item.iterrows():
        item_id = g[COL_ITEM_ID]
        row = inventory_df[inventory_df[COL_ITEM_ID].str.lower() == item_id.lower()]
        if row.empty:
            continue
        current_qty = float(row[COL_QUANTITY].values[0])
        item_name = str(row[COL_ITEM_NAME].values[0])
        # Only flag if current stock is negative or would have been driven negative
        if current_qty < 0 or (current_qty == 0 and g[COL_QUANTITY] > 0):
            result.append({
                'item_id': item_id,
                'item_name': item_name,
                'current_qty': current_qty,
                'recent_qty_sold': float(g[COL_QUANTITY]),
            })
    return result


def append_item_to_items_csv(
    script_dir: str,
    item_id: str,
    item_name: str,
    division: str,
    measure: str,
    quantity: float,
    total_value: float,
    active: str = "",
    min_alert: str = "0",
    max_alert: str = "0",
) -> bool:
    """Append a new item row to Items.csv if it is not already present.

    Returns True if a row was appended, False if it already existed.
    """
    items_csv_path = os.path.join(script_dir, 'Items.csv')
    header = ["Name", "Division", "Unit", "Total Stock", "Total Value", "Active", "Min Alert", "Max Alert"]

    # If CSV exists, check for existing name (case-insensitive)
    existing_names = set()
    rows = []
    if os.path.exists(items_csv_path):
        try:
            with open(items_csv_path, 'r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                rows = list(reader)
                if rows:
                    header = rows[0]
                    for row in rows[1:]:
                        if row:
                            existing_names.add(row[0].strip().lower())
        except Exception:
            pass

    if item_name.strip().lower() in existing_names:
        return False

    new_row = [item_name, division, measure, str(quantity), f"{total_value:.2f}", active, min_alert, max_alert]

    # If file didn't exist or was empty, write header + row
    if not rows:
        with open(items_csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
            writer.writerow(header)
            writer.writerow(new_row)
        return True

    # Append row
    with open(items_csv_path, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(new_row)
    return True
