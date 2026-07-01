"""
CSV upload helpers for BarStock.

This module isolates parsing and preview logic for the weekly sales and
complimentary reports. It works with in-memory pandas DataFrames so that it can
be tested without a live SQLite database.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from io import StringIO
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from actions import ACTION_SALES, ACTION_COMPLIMENTARY, ACTION_PARENT_STOCK_ADJ
from categories import should_exclude
from sales_mapping import (
    has_parent_stock, check_apply_sale_to_parent, apply_sale_to_parent,
    normalize_product_name, resolve_epos_item_id, get_effective_cost_price,
)
from data_manager import COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE
from data_manager import COL_ACTION, COL_TIMESTAMP, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON
from data_manager import COL_MEMBER_QTY, COL_NON_MEMBER_QTY


class CSVUploadError(Exception):
    """Raised when a CSV upload cannot be parsed or applied."""
    pass


def parse_date_range_from_filename(filepath: str) -> Tuple[Optional[datetime], Optional[datetime]]:
    """Extract a date range from a sales/complimentary CSV filename.

    Expected pattern: ...DD-MM-YYYY-DD-MM-YYYY...
    Returns (start_date, end_date) or (None, None) on failure.
    """
    basename = os.path.basename(filepath)
    match = re.search(r'(\d{2})-(\d{2})-(\d{4})-(\d{2})-(\d{2})-(\d{4})', basename)
    if not match:
        return None, None
    d1, m1, y1, d2, m2, y2 = match.groups()
    try:
        return datetime(int(y1), int(m1), int(d1)), datetime(int(y2), int(m2), int(d2))
    except ValueError:
        return None, None


def file_hash(filepath: str) -> str:
    """Return SHA-256 hex digest of a file's bytes."""
    with open(filepath, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def _strip_composite_report(raw_lines: List[str]) -> List[str]:
    """Remove the trailing detailed-transaction section from composite EPOS files."""
    clean_lines: List[str] = []
    for i, line in enumerate(raw_lines):
        if line.strip().startswith('"Name') or line.strip().startswith('Name\n'):
            remaining = ''.join(raw_lines[i:i + 5])
            if 'Payment Method' in remaining or 'Date\n' in remaining or 'Subtotal' in remaining:
                break
        clean_lines.append(line)
    return clean_lines


def _find_qty_column(df: pd.DataFrame, require_member: bool = False, require_non_member: bool = False) -> Optional[str]:
    for col in df.columns:
        col_lower = col.lower()
        if 'qty' not in col_lower:
            continue
        if require_member and 'non' in col_lower:
            continue
        if require_member and 'member' not in col_lower:
            continue
        if require_non_member and 'non' not in col_lower:
            continue
        if not require_member and not require_non_member and 'member' in col_lower:
            continue
        return col
    return None


def _resolve_item_id(item_id: str, product_name: str, inventory_df: pd.DataFrame) -> Optional[str]:
    """Resolve a normalized product name to a known inventory item_id."""
    if item_id in inventory_df[COL_ITEM_ID].values:
        return item_id

    name_lower = product_name.lower()
    for inv_id in inventory_df[COL_ITEM_ID].values:
        inv_name = str(
            inventory_df.loc[inventory_df[COL_ITEM_ID] == inv_id, COL_ITEM_NAME].values[0]
        ).lower()
        if name_lower in inv_name or inv_name in name_lower:
            return inv_id
    return None


def _build_preview_item(
    item_id: str,
    quantity: float,
    member_qty: Optional[float],
    non_member_qty: Optional[float],
    inventory_df: pd.DataFrame,
    action: str,
) -> Optional[Dict[str, Any]]:
    if item_id not in inventory_df[COL_ITEM_ID].values:
        return None

    item_row = inventory_df[inventory_df[COL_ITEM_ID] == item_id].iloc[0]
    cost_price = get_effective_cost_price(item_id, inventory_df, COL_ITEM_ID, COL_COST_PRICE)
    sell_price = item_row[COL_SELL_PRICE]
    current_qty = item_row[COL_QUANTITY]

    preview: Dict[str, Any] = {
        'item_id': item_id,
        'name': item_row[COL_ITEM_NAME],
        'qty': quantity,
        'current': current_qty,
        'projected': current_qty - quantity,
        'cost': cost_price,
        'sell': sell_price,
        'cost_total': quantity * cost_price,
        'has_parent': has_parent_stock(item_id),
        'member_qty': member_qty,
        'non_member_qty': non_member_qty,
    }
    if action == ACTION_SALES:
        preview['revenue'] = quantity * sell_price
    return preview


def parse_sales_csv(
    filepath: str,
    inventory_df: pd.DataFrame,
) -> Dict[str, Any]:
    """Parse a weekly sales report CSV and return preview data.

    Returns a dict with:
      - preview_items: list of preview dicts
      - skipped_items: list of skipped product names / reasons
      - total_revenue, total_cost
      - date_range_str, raw_row_count
    """
    if not os.path.exists(filepath):
        raise CSVUploadError("File not found.")

    start_date, end_date = parse_date_range_from_filename(filepath)
    date_range_str = ""
    if start_date and end_date:
        date_range_str = f"{start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}"

    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        raw_lines = f.readlines()

    clean_lines = _strip_composite_report(raw_lines)
    sales_df = pd.read_csv(StringIO(''.join(clean_lines)), compression=None)
    sales_df.columns = [col.strip() for col in sales_df.columns]

    if 'Product' not in sales_df.columns:
        raise CSVUploadError("Sales report must have a 'Product' column.")

    qty_col = _find_qty_column(sales_df) or 'Qty'
    member_qty_col = _find_qty_column(sales_df, require_member=True)
    non_member_qty_col = _find_qty_column(sales_df, require_non_member=True)

    preview_items: List[Dict[str, Any]] = []
    skipped_items: List[str] = []
    total_revenue = 0.0
    total_cost = 0.0

    for _, row in sales_df.iterrows():
        try:
            product_name = str(row['Product']).strip()
            if not product_name or product_name.lower() == 'nan':
                continue

            try:
                quantity = float(row[qty_col]) if pd.notna(row[qty_col]) else 0.0
            except Exception:
                quantity = 0.0
            if quantity <= 0:
                continue

            try:
                member_qty = float(row[member_qty_col]) if member_qty_col and pd.notna(row[member_qty_col]) else None
            except Exception:
                member_qty = None
            try:
                non_member_qty = float(row[non_member_qty_col]) if non_member_qty_col and pd.notna(row[non_member_qty_col]) else None
            except Exception:
                non_member_qty = None

            item_id = normalize_product_name(product_name)
            item_id = resolve_epos_item_id(item_id)
            resolved = _resolve_item_id(item_id, product_name, inventory_df)
            if not resolved:
                skipped_items.append(product_name)
                continue
            item_id = resolved

            if should_exclude(item_id) and not has_parent_stock(item_id):
                skipped_items.append(f"{product_name} (excluded)")
                continue

            preview = _build_preview_item(item_id, quantity, member_qty, non_member_qty, inventory_df, ACTION_SALES)
            if not preview:
                skipped_items.append(product_name)
                continue

            preview_items.append(preview)
            total_revenue += preview['revenue']
            total_cost += preview['cost_total']
        except Exception as item_error:
            skipped_items.append(f"{row.get('Product', 'Unknown')}: {item_error}")

    return {
        'preview_items': preview_items,
        'skipped_items': skipped_items,
        'total_revenue': total_revenue,
        'total_cost': total_cost,
        'date_range_str': date_range_str,
        'raw_row_count': len(sales_df),
    }


def parse_complimentary_csv(
    filepath: str,
    inventory_df: pd.DataFrame,
) -> Dict[str, Any]:
    """Parse a complimentary report CSV and return preview data.

    Returns a dict with:
      - preview_items, skipped_items, total_cost
      - date_range_str, raw_row_count
    """
    if not os.path.exists(filepath):
        raise CSVUploadError("File not found.")

    start_date, end_date = parse_date_range_from_filename(filepath)
    date_range_str = ""
    if start_date and end_date:
        date_range_str = f"{start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}"

    comp_df = pd.read_csv(filepath, compression=None)
    comp_df.columns = [col.strip() for col in comp_df.columns]

    if 'Product' not in comp_df.columns:
        raise CSVUploadError("Complimentary report must have a 'Product' column.")

    qty_col = None
    for col in comp_df.columns:
        if col.lower() == 'qty':
            qty_col = col
            break
    if not qty_col:
        qty_col = 'Qty'

    preview_items: List[Dict[str, Any]] = []
    skipped_items: List[str] = []
    total_cost = 0.0

    for _, row in comp_df.iterrows():
        try:
            product_name = str(row['Product']).strip()
            if not product_name or product_name.lower() == 'nan' or product_name.lower() == 'total':
                continue

            try:
                quantity = float(row[qty_col]) if pd.notna(row[qty_col]) else 0.0
            except Exception:
                quantity = 0.0
            if quantity <= 0:
                continue

            item_id = normalize_product_name(product_name)
            item_id = resolve_epos_item_id(item_id)
            resolved = _resolve_item_id(item_id, product_name, inventory_df)
            if not resolved:
                skipped_items.append(product_name)
                continue
            item_id = resolved

            if should_exclude(item_id) and not has_parent_stock(item_id):
                skipped_items.append(f"{product_name} (excluded)")
                continue

            preview = _build_preview_item(item_id, quantity, None, None, inventory_df, ACTION_COMPLIMENTARY)
            if not preview:
                skipped_items.append(product_name)
                continue

            preview_items.append(preview)
            total_cost += preview['cost_total']
        except Exception as item_error:
            skipped_items.append(f"{row.get('Product', 'Unknown')}: {item_error}")

    return {
        'preview_items': preview_items,
        'skipped_items': skipped_items,
        'total_cost': total_cost,
        'date_range_str': date_range_str,
        'raw_row_count': len(comp_df),
    }


def parent_stock_issues(preview_items: List[Dict[str, Any]], inventory_df: pd.DataFrame) -> List[str]:
    """Return human-readable parent-stock issues for a list of preview items."""
    issues: List[str] = []
    for p in preview_items:
        if p['has_parent']:
            ok, item_issues = check_apply_sale_to_parent(
                p['item_id'], p['qty'], inventory_df,
                COL_ITEM_ID, COL_QUANTITY, 'allow_negative'
            )
            if not ok:
                issues.extend(item_issues)
    return issues


def apply_sales_upload(
    preview_items: List[Dict[str, Any]],
    inventory_df: pd.DataFrame,
    log_df: pd.DataFrame,
    date_range_str: str,
    timestamp: Optional[str] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, List[str], List[str]]:
    """Apply a confirmed sales upload to inventory and log DataFrames.

    Returns (inventory_df, log_df, transactions, skipped_items).
    """
    if timestamp is None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    transactions: List[str] = []
    skipped_items: List[str] = []

    for p in preview_items:
        item_id = p['item_id']
        quantity = p['qty']
        cost_price = p['cost']
        sell_price = p['sell']
        member_qty = p.get('member_qty')
        non_member_qty = p.get('non_member_qty')

        parent_adjustments = []
        if has_parent_stock(item_id):
            ok, issues = check_apply_sale_to_parent(
                item_id, quantity, inventory_df,
                COL_ITEM_ID, COL_QUANTITY, 'allow_negative'
            )
            if not ok:
                skipped_items.append(f"{p['name']} (parent stock: {'; '.join(issues)})")
                continue
            parent_adjustments = apply_sale_to_parent(item_id, quantity, inventory_df, COL_ITEM_ID, COL_QUANTITY)
        else:
            inventory_df.loc[inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] -= quantity

        new_log_entry = pd.DataFrame(
            [[item_id, ACTION_SALES, quantity, timestamp, cost_price, sell_price, "", date_range_str, "", member_qty, non_member_qty]],
            columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON, COL_MEMBER_QTY, COL_NON_MEMBER_QTY]
        )
        log_df = pd.concat([log_df, new_log_entry], ignore_index=True)

        for parent_id, deduction, _desc in parent_adjustments:
            parent_row = inventory_df[inventory_df[COL_ITEM_ID] == parent_id].iloc[0]
            parent_cost = parent_row[COL_COST_PRICE]
            parent_sell = parent_row[COL_SELL_PRICE]
            parent_log_entry = pd.DataFrame(
                [[parent_id, ACTION_PARENT_STOCK_ADJ, deduction, timestamp, parent_cost, parent_sell, f"From {item_id}", date_range_str, "", 0, 0]],
                columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON, COL_MEMBER_QTY, COL_NON_MEMBER_QTY]
            )
            log_df = pd.concat([log_df, parent_log_entry], ignore_index=True)

        transactions.append(f"{p['name']}: {quantity:.1f} units")

    return inventory_df, log_df, transactions, skipped_items


def apply_complimentary_upload(
    preview_items: List[Dict[str, Any]],
    inventory_df: pd.DataFrame,
    log_df: pd.DataFrame,
    date_range_str: str,
    timestamp: Optional[str] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, List[str], List[str]]:
    """Apply a confirmed complimentary upload to inventory and log DataFrames.

    Returns (inventory_df, log_df, transactions, skipped_items).
    """
    if timestamp is None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    transactions: List[str] = []
    skipped_items: List[str] = []

    for p in preview_items:
        item_id = p['item_id']
        quantity = p['qty']
        cost_price = p['cost']

        parent_adjustments = []
        if has_parent_stock(item_id):
            ok, issues = check_apply_sale_to_parent(
                item_id, quantity, inventory_df,
                COL_ITEM_ID, COL_QUANTITY, 'allow_negative'
            )
            if not ok:
                skipped_items.append(f"{p['name']} (parent stock: {'; '.join(issues)})")
                continue
            parent_adjustments = apply_sale_to_parent(item_id, quantity, inventory_df, COL_ITEM_ID, COL_QUANTITY)
        else:
            inventory_df.loc[inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] -= quantity

        new_log_entry = pd.DataFrame(
            [[item_id, ACTION_COMPLIMENTARY, quantity, timestamp, cost_price, 0.0, "", date_range_str, "CSV Upload"]],
            columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON]
        )
        log_df = pd.concat([log_df, new_log_entry], ignore_index=True)

        for parent_id, deduction, _desc in parent_adjustments:
            parent_row = inventory_df[inventory_df[COL_ITEM_ID] == parent_id].iloc[0]
            parent_cost = parent_row[COL_COST_PRICE]
            parent_log_entry = pd.DataFrame(
                [[parent_id, ACTION_PARENT_STOCK_ADJ, deduction, timestamp, parent_cost, 0.0, f"From {item_id}", date_range_str, "CSV Upload", 0, 0]],
                columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON, COL_MEMBER_QTY, COL_NON_MEMBER_QTY]
            )
            log_df = pd.concat([log_df, parent_log_entry], ignore_index=True)

        transactions.append(f"{p['name']}: {quantity:.1f} units")

    return inventory_df, log_df, transactions, skipped_items
