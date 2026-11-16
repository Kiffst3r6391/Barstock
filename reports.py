"""
Bar Stock Reports - Data processing functions for report generation.

All functions accept inventory_df, log_df, and optional date filtering.
Returns raw data structures (dicts, DataFrames) for UI rendering.
"""

import json
import os
import re
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

from actions import (
    ACTION_SALES, ACTION_SALES_ONE_UNIT, ACTION_DELIVERY,
    ACTION_WASTAGE, ACTION_LINE_CLEAN, ACTION_COMPLIMENTARY,
    ACTION_OPEN_TAB, ACTION_TAB_CANCELLED, ACTION_PARENT_STOCK_ADJ,
    ACTION_STOCKTAKE_BASELINE, ACTION_STOCKTAKE_ADJUSTMENT,
    ACTION_IMPORT, ACTION_SUPPLIER_RETURN,
)
from categories import get_category, should_exclude, is_delisted, CATEGORY_ORDER
from sales_mapping import is_hidden_from_stock_view, get_parent_for_sale
from supplier_mapping import get_supplier, get_supplier_order, supplier_rank
from order_sheet_layout import get_order_sheet_layout
from conversions import parse_display_date, DATE_FORMAT_DISPLAY
from money import allocate_money, round_money, sum_money, inc_vat


def _format_delivery_date(timestamp_str):
    """Format an ISO timestamp/date string as DD-MM-YYYY for display."""
    if not isinstance(timestamp_str, str) or not timestamp_str.strip():
        return ''
    date_part = timestamp_str[:10]
    try:
        return datetime.strptime(date_part, '%Y-%m-%d').strftime(DATE_FORMAT_DISPLAY)
    except ValueError:
        return date_part


# Column constants
COL_ITEM_ID = 'item_id'
COL_ITEM_NAME = 'item_name'
COL_QUANTITY = 'quantity'
COL_COST_PRICE = 'cost_price'
COL_SELL_PRICE = 'sell_price'
COL_MEASURE = 'measure'
COL_CATEGORY = 'category'
COL_ACTION = 'action'
COL_TIMESTAMP = 'timestamp'
COL_SUPPLIER = 'supplier'
COL_DATE_RANGE = 'date_range'
COL_PRICE_LOCKED = 'price_locked'
COL_REASON = 'reason'
COL_MEMBER_QTY = 'member_qty'
COL_NON_MEMBER_QTY = 'non_member_qty'
COL_OPEN_TAB_ID = 'open_tab_id'
COL_REORDER_LEVEL = 'reorder_level'
COL_DIVISION = 'division'


def _split_sales_revenue_and_cost(sales_df: pd.DataFrame, member_discount_pct: float = 10.0) -> pd.DataFrame:
    """Split sales revenue and cost into member and non-member portions.

    Uses actual member_qty / non_member_qty columns when they are present and
    sum to a positive value. Any quantity not explicitly split is treated as
    non-member (conservative default that avoids inventing a discount).

    Returns the input DataFrame with added columns:
      total_cost, total_revenue, member_revenue, non_member_revenue,
      member_cost, non_member_cost
    """
    df = sales_df.copy()
    df["total_cost"] = df[COL_QUANTITY] * df[COL_COST_PRICE]
    df["total_revenue"] = df[COL_QUANTITY] * df[COL_SELL_PRICE]

    member_mult = (100 - member_discount_pct) / 100

    df["member_revenue"] = 0.0
    df["non_member_revenue"] = df["total_revenue"]
    df["member_cost"] = 0.0
    df["non_member_cost"] = df["total_cost"]

    if COL_MEMBER_QTY in df.columns:
        split_sum = df[COL_MEMBER_QTY].fillna(0) + df[COL_NON_MEMBER_QTY].fillna(0)
        has_actual = split_sum > 0

        if has_actual.any():
            def _floats(series):
                """Plain float array, so an object-dtype log cannot leak into
                the arithmetic (a fresh session concatenates frames and every
                column becomes object)."""
                return pd.to_numeric(series, errors='coerce').fillna(0.0).to_numpy(dtype=float)

            qty = _floats(df.loc[has_actual, COL_QUANTITY])
            member_qty = _floats(df.loc[has_actual, COL_MEMBER_QTY])
            non_member_qty = _floats(df.loc[has_actual, COL_NON_MEMBER_QTY])
            sell = _floats(df.loc[has_actual, COL_SELL_PRICE])
            cost = _floats(df.loc[has_actual, "total_cost"])

            known_total = member_qty + non_member_qty

            # Any quantity not explicitly split is treated as non-member.
            remaining = np.maximum(qty - known_total, 0.0)
            member_qty_est = member_qty
            non_member_qty_est = non_member_qty + remaining

            actual_total = qty * sell
            member_revenue = member_qty_est * sell * member_mult
            non_member_revenue = non_member_qty_est * sell

            # Scale so member + non-member revenue equals total revenue for every transaction.
            split_total = member_revenue + non_member_revenue
            revenue_scale = np.divide(
                actual_total, split_total,
                out=np.ones_like(actual_total), where=split_total > 0)
            member_revenue = member_revenue * revenue_scale
            non_member_revenue = non_member_revenue * revenue_scale

            member_cost = np.where(
                qty > 0,
                cost * np.divide(member_qty_est, qty,
                                 out=np.zeros_like(qty), where=qty > 0),
                0.0,
            )
            non_member_cost = cost - member_cost

            df.loc[has_actual, "member_revenue"] = member_revenue
            df.loc[has_actual, "non_member_revenue"] = non_member_revenue
            df.loc[has_actual, "member_cost"] = member_cost
            df.loc[has_actual, "non_member_cost"] = non_member_cost

    return df


SALES_MONEY_COLUMNS = [
    'sales_qty', 'member_revenue', 'non_member_revenue', 'member_cost',
    'non_member_cost', 'total_revenue', 'total_cost', 'member_gp',
    'non_member_gp', 'gp',
]


def sales_money_by_item(log_df, member_discount_pct=10):
    """Canonical per-item sales money, used by every report and the dashboard.

    Total revenue, member revenue, total cost and member cost are each
    allocated to the penny across the selling items, so their rows add up
    exactly to the period totals. Non-member revenue/cost and every GP figure
    are derived by subtraction, so each row's components add up too.
    """
    if log_df is None or log_df.empty:
        return pd.DataFrame(columns=SALES_MONEY_COLUMNS)

    sales_df = log_df[log_df[COL_ACTION].isin([ACTION_SALES, ACTION_SALES_ONE_UNIT])].copy()
    if sales_df.empty:
        return pd.DataFrame(columns=SALES_MONEY_COLUMNS)

    sales_df = _split_sales_revenue_and_cost(sales_df, member_discount_pct)
    grouped = sales_df.groupby(COL_ITEM_ID).agg({
        COL_QUANTITY: 'sum',
        'total_revenue': 'sum',
        'member_revenue': 'sum',
        'total_cost': 'sum',
        'member_cost': 'sum',
    }).sort_index()

    grouped['total_revenue'] = allocate_money(grouped['total_revenue'].tolist())
    grouped['member_revenue'] = allocate_money(grouped['member_revenue'].tolist())
    grouped['total_cost'] = allocate_money(grouped['total_cost'].tolist())
    grouped['member_cost'] = allocate_money(grouped['member_cost'].tolist())

    grouped['non_member_revenue'] = grouped['total_revenue'] - grouped['member_revenue']
    grouped['non_member_cost'] = grouped['total_cost'] - grouped['member_cost']
    grouped['member_gp'] = grouped['member_revenue'] - grouped['member_cost']
    grouped['non_member_gp'] = grouped['non_member_revenue'] - grouped['non_member_cost']
    grouped['gp'] = grouped['total_revenue'] - grouped['total_cost']

    grouped = grouped.rename(columns={COL_QUANTITY: 'sales_qty'})
    return grouped[SALES_MONEY_COLUMNS]


def item_division_lookup(inventory_df):
    """Map item_id -> division from the live inventory, then sensible fallbacks.

    The Division report and the comprehensive PDF both use this lookup, so a
    sale lands in the same division in both. Child/mixer items (half pints,
    shandies, orange & lemonade) often have no division of their own, so they
    inherit the division of their parent stock item rather than defaulting to
    "Unknown".
    """
    division_mapping = get_division_mapping(os.path.dirname(os.path.abspath(__file__)))
    lookup = {}
    if inventory_df is None or inventory_df.empty:
        return lookup

    rows = list(inventory_df.iterrows())

    # First pass: explicit divisions from the live inventory.
    for _, row in rows:
        item_id = str(row[COL_ITEM_ID])
        live = row.get(COL_DIVISION, '')
        if pd.notna(live) and str(live).strip():
            lookup[item_id] = normalize_division_name(str(live))

    # Items whose display name / item_id does not map cleanly.
    explicit = {
        'guinness_0_0': 'Beer - Bottled',
        'sours': 'Spirits',
        'cart_roll_tea_coffee': 'Hot Drinks',
        'coke_half': 'Post Mix',
        'diet_coke_half': 'Post Mix',
        'coke_pm': 'Post Mix',
        'diet_coke_pm': 'Post Mix',
    }

    # Second pass: Items.csv, then the parent's division, then explicit.
    for _, row in rows:
        item_id = str(row[COL_ITEM_ID])
        if item_id in lookup:
            continue
        mapped = division_mapping.get(str(row[COL_ITEM_NAME]).lower(), '')
        if not mapped or mapped == 'Unknown':
            parent = get_parent_for_sale(item_id)
            if parent:
                parent_ids = (parent[0] if isinstance(parent[0], list)
                              else [parent[0]])
                for parent_id in parent_ids:
                    parent_id = str(parent_id)
                    if parent_id in lookup and lookup[parent_id] != 'Unknown':
                        mapped = lookup[parent_id]
                        break
        if not mapped or mapped == 'Unknown':
            mapped = explicit.get(item_id, 'Unknown')
        lookup[item_id] = normalize_division_name(str(mapped))
    return lookup


def filter_log_by_date(log_df, start_date=None, end_date=None):
    """Filter transaction log by date range.

    Sales/complimentary/wastage transactions uploaded from CSV reports store
    their sales period in the date_range column (e.g. "01/08/2026 - 07/08/2026").
    When filtering by date, include those rows if their date_range overlaps the
    selected period; otherwise fall back to the transaction timestamp.
    """
    if log_df.empty or start_date is None:
        return log_df
    filtered = log_df.copy()

    if COL_TIMESTAMP in filtered.columns:
        filtered['__timestamp_dt__'] = pd.to_datetime(filtered[COL_TIMESTAMP], errors='coerce')
        timestamp_mask = pd.Series(True, index=filtered.index)
        if start_date is not None:
            timestamp_mask &= filtered['__timestamp_dt__'] >= pd.Timestamp(start_date)
        if end_date is not None:
            timestamp_mask &= filtered['__timestamp_dt__'] <= pd.Timestamp(end_date)
    else:
        timestamp_mask = pd.Series(True, index=filtered.index)

    if COL_DATE_RANGE in filtered.columns:
        def _date_range_in_range(date_range_str):
            if not isinstance(date_range_str, str) or not date_range_str.strip():
                return None  # signal: fall back to timestamp
            try:
                parts = date_range_str.split(' - ')
                if len(parts) != 2:
                    return None
                dr_start = parse_display_date(parts[0].strip())
                dr_end = parse_display_date(parts[1].strip())
                # For CSV-uploaded periods, include the row if the CSV period
                # overlaps the report range at all. Previously the whole CSV
                # period had to fall inside the report range, which excluded
                # weekly CSVs that straddled a month boundary (e.g. 31 Aug -
                # 6 Sept when reporting on September).
                if start_date is not None and dr_end < start_date:
                    return False
                if end_date is not None and dr_start > end_date:
                    return False
                return True
            except Exception:
                return None

        daterange_decision = filtered[COL_DATE_RANGE].apply(_date_range_in_range)
        # Rows with a valid date_range are decided by full containment;
        # rows without one fall back to the timestamp mask.
        from_period = daterange_decision == True
        fallback_to_timestamp = daterange_decision.isna()
        filtered = filtered[from_period | (fallback_to_timestamp & timestamp_mask)]
    else:
        filtered = filtered[timestamp_mask]

    filtered = filtered.drop(columns=['__timestamp_dt__'], errors='ignore')
    return filtered


def calculate_expected_remaining_series(log_df, clamp_negative=True):
    """Calculate expected remaining stock for all items from transaction log.

    A Stocktake Baseline row acts as a reset: expected stock at the baseline
    timestamp equals the baseline quantity, and only transactions at or after
    that baseline are applied. This prevents pre-baseline archive history from
    producing negative opening-stock figures when the current inventory has
    been reset to a physical count.

    Formula (post-baseline): baseline + import + delivery + tab_cancelled
                             + stocktake_adjustment
                             - sales - wastage - line_clean - complimentary
                             - open_tab - supplier_return - parent_adj

    Stocktake Adjustment rows carry the variance (counted - expected) recorded
    when a stocktake is saved, so including them keeps the expected level in
    step with the physical count. Omitting them made the variance report and
    the running surplus disagree with live inventory after every stocktake.
    Returns pd.Series indexed by item_id.

    Note: this is a stock-level expected remaining calculation. Open Tab rows are
    included because stock is deducted when a tab is opened. Consumption
    reporting should use CONSUMPTION_ACTIONS (which excludes Open Tab) so that
    tabs are not counted as sold/wasted before they are closed.

    ``clamp_negative`` keeps reports from inventing a negative opening stock
    when more was sold than the baseline held. Reconciliation passes False so
    the ledger's true balance is compared (an oversold line really is negative).
    """
    if log_df.empty:
        return pd.Series(dtype=float)

    # Find the latest baseline timestamp per item. Rows before that timestamp
    # are ignored because the baseline supersedes earlier history.
    baseline_rows = log_df[log_df[COL_ACTION] == ACTION_STOCKTAKE_BASELINE]
    latest_baseline_ts = None
    baseline_quantities = pd.Series(dtype=float)
    if not baseline_rows.empty:
        latest_baseline_ts = baseline_rows.groupby(COL_ITEM_ID)[COL_TIMESTAMP].max()
        baseline_quantities = baseline_rows.groupby(COL_ITEM_ID)[COL_QUANTITY].last()

    if latest_baseline_ts is not None and not latest_baseline_ts.empty:
        def _after_baseline(row):
            item_id = row[COL_ITEM_ID]
            if item_id not in latest_baseline_ts.index:
                return True
            return str(row[COL_TIMESTAMP]) >= str(latest_baseline_ts[item_id])
        effective_log = log_df[log_df.apply(_after_baseline, axis=1)].copy()
    else:
        effective_log = log_df.copy()

    grouped = effective_log.groupby([COL_ITEM_ID, COL_ACTION]).agg({COL_QUANTITY: 'sum'}).reset_index()
    pivot = grouped.pivot(index=COL_ITEM_ID, columns=COL_ACTION, values=COL_QUANTITY).fillna(0)

    sales = pivot.get(ACTION_SALES, 0) + pivot.get(ACTION_SALES_ONE_UNIT, 0)
    wastage = pivot.get(ACTION_WASTAGE, 0) + pivot.get(ACTION_LINE_CLEAN, 0)
    comp = pivot.get(ACTION_COMPLIMENTARY, 0)
    open_tab = pivot.get(ACTION_OPEN_TAB, 0)
    tab_cancelled = pivot.get(ACTION_TAB_CANCELLED, 0)
    import_qty = pivot.get(ACTION_IMPORT, 0)
    delivery = pivot.get(ACTION_DELIVERY, 0)
    baseline = pivot.get(ACTION_STOCKTAKE_BASELINE, 0)
    stocktake_adjustment = pivot.get(ACTION_STOCKTAKE_ADJUSTMENT, 0)
    supplier_return = pivot.get(ACTION_SUPPLIER_RETURN, 0)

    # Compute parent adjustments dynamically from child sales instead of relying on log entries.
    # A parent's baseline also resets its children's deductions: a child sale that
    # happened before the parent was counted is already inside the physical count,
    # so deducting it again would understate the parent's expected stock. Children
    # are not on the count sheet and keep their whole history, so the child's own
    # baseline cannot do this job.
    from sales_mapping import SALES_TO_PARENT
    baseline_ts_lower = {}
    if latest_baseline_ts is not None and not latest_baseline_ts.empty:
        baseline_ts_lower = {str(k).lower(): str(v) for k, v in latest_baseline_ts.items()}

    computed_parent_adj = {}
    for child_id, mapping in SALES_TO_PARENT.items():
        if not mapping:
            continue
        parent_items, factors, _ = mapping[:3]
        if isinstance(parent_items, list):
            pairs = list(zip(parent_items, factors))
        else:
            pairs = [(parent_items, factors)]
        child_log = effective_log[effective_log[COL_ITEM_ID].str.lower() == child_id]
        sales_rows = child_log[child_log[COL_ACTION].isin([ACTION_SALES, ACTION_SALES_ONE_UNIT])]
        comp_rows = child_log[child_log[COL_ACTION] == ACTION_COMPLIMENTARY]
        for p_id, factor in pairs:
            parent_key = p_id.lower()
            parent_ts = baseline_ts_lower.get(parent_key)
            if parent_ts is None:
                total = sales_rows[COL_QUANTITY].sum() + comp_rows[COL_QUANTITY].sum()
            else:
                parent_sales = sales_rows[sales_rows[COL_TIMESTAMP].astype(str) >= parent_ts]
                parent_comp = comp_rows[comp_rows[COL_TIMESTAMP].astype(str) >= parent_ts]
                total = parent_sales[COL_QUANTITY].sum() + parent_comp[COL_QUANTITY].sum()
            computed_parent_adj[parent_key] = computed_parent_adj.get(parent_key, 0) + total * factor

    # Build a parent_adj Series aligned with the pivot index (case-insensitive)
    all_item_ids = list(pivot.index)
    parent_adj = pd.Series({item_id: computed_parent_adj.get(item_id.lower(), 0) for item_id in all_item_ids})
    parent_adj.index.name = COL_ITEM_ID

    result = (import_qty + delivery + baseline + tab_cancelled + stocktake_adjustment
              - sales - wastage - comp - open_tab - supplier_return - parent_adj)

    # Replace any remaining negative expected remaining with the baseline anchor
    # when a baseline exists, so current_stock - expected_remaining never invents
    # a negative opening stock.
    if clamp_negative and not baseline_quantities.empty:
        for item_id in result.index:
            if item_id in baseline_quantities.index and result[item_id] < 0:
                result[item_id] = float(baseline_quantities[item_id])

    return result


def normalize_division_name(name):
    """Normalize a division name to group similar spellings together.

    Handles cases like:
      'Beers- Draught' -> 'Beer - Draught'
      'Beer - Draught' -> 'Beer - Draught'
      '  Soft  Drinks ' -> 'Soft Drinks'
    """
    if pd.isna(name) or not isinstance(name, str):
        return 'Unknown'

    name = name.strip()
    # Collapse multiple spaces
    while '  ' in name:
        name = name.replace('  ', ' ')
    # Fix spacing around hyphens: ensure space before and after
    name = name.replace('- ', '-').replace(' -', '-')
    name = name.replace('-', ' - ')
    # Collapse any double spaces introduced
    while '  ' in name:
        name = name.replace('  ', ' ')
    # Singularize common plurals
    if name.lower().startswith('beers'):
        name = 'Beer' + name[5:]
    # Title case consistency
    name = name.title()
    # Re-apply spacing fix after title case (Title Case may re-add spaces)
    name = name.replace(' - ', '-')
    name = name.replace('-', ' - ')
    while '  ' in name:
        name = name.replace('  ', ' ')
    return name.strip()


def get_division_mapping(script_dir):
    """Load the division mapping from Items.csv.

    In the packaged app the bundle no longer carries Items.csv (it is live
    data), so fall back to the Application Support copy before giving up.
    """
    candidates = [os.path.join(script_dir, 'Items.csv')]
    try:
        from app_config import DATA_DIR
        candidates.append(os.path.join(DATA_DIR, 'Items.csv'))
    except Exception:
        pass
    candidates.append(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), 'Items.csv'))

    for items_csv_path in candidates:
        if not os.path.exists(items_csv_path):
            continue
        try:
            items_df = pd.read_csv(items_csv_path, compression=None)
            if 'Name' in items_df.columns and 'Division' in items_df.columns:
                raw_mapping = dict(zip(items_df['Name'].str.lower(),
                                       items_df['Division']))
                division_mapping = {
                    key: normalize_division_name(value)
                    for key, value in raw_mapping.items()}
                if division_mapping:
                    return division_mapping
        except Exception:
            continue
    return {}


def build_gp_report_data(log_df, member_discount_pct=10):
    """Build data for Gross Profit Report.

    Returns DataFrame with columns:
    Total Cost, Total Revenue, GP, GP%, Member Revenue, Non-Member Revenue,
    Member GP, Member GP%, Non-Member GP, Non-Member GP%
    """
    columns = ['Total Cost', 'Total Revenue', 'GP', 'GP%',
               'Member Revenue', 'Non-Member Revenue',
               'Member GP', 'Member GP%',
               'Non-Member GP', 'Non-Member GP%']
    if log_df is None or log_df.empty:
        return pd.DataFrame(columns=columns)

    # Gross Profit Report should only consider Sales data
    item_money = sales_money_by_item(log_df, member_discount_pct)
    if item_money.empty:
        return pd.DataFrame(columns=columns)

    item_summary = item_money.rename(columns={
        'total_cost': 'Total Cost',
        'total_revenue': 'Total Revenue',
        'gp': 'GP',
        'member_revenue': 'Member Revenue',
        'non_member_revenue': 'Non-Member Revenue',
        'member_gp': 'Member GP',
        'non_member_gp': 'Non-Member GP',
    })

    item_summary['GP%'] = np.where(
        item_summary['Total Revenue'] > 0,
        item_summary['GP'] / item_summary['Total Revenue'] * 100,
        0.0
    )
    item_summary['Member GP%'] = np.where(
        item_summary['Member Revenue'] > 0,
        item_summary['Member GP'] / item_summary['Member Revenue'] * 100,
        0.0
    )
    item_summary['Non-Member GP%'] = np.where(
        item_summary['Non-Member Revenue'] > 0,
        item_summary['Non-Member GP'] / item_summary['Non-Member Revenue'] * 100,
        0.0
    )

    return item_summary[columns].round(2)


def build_surplus_report_data(inventory_df, log_df):
    """Build data for Surplus/Variance Report.

    Returns list of dicts with keys: item_id, item_name, cost_price, Expected, Actual,
    Variance, Variance %, Variance Value (£)

    Excludes hidden child items (half pints, shandies, dash) whose stock is managed
    through parent stock deductions.
    """
    report_data = []
    if inventory_df.empty:
        return report_data

    # Exclude hidden child items whose stock is managed through parents
    try:
        from sales_mapping import is_hidden_from_stock_view
        hidden_filter = inventory_df[COL_ITEM_ID].apply(lambda x: not is_hidden_from_stock_view(x))
        inventory_df = inventory_df[hidden_filter]
    except ImportError:
        pass

    try:
        from categories import EXCLUDED_ITEMS
        excluded_set = set(EXCLUDED_ITEMS)
        inventory_df = inventory_df[~inventory_df[COL_ITEM_ID].isin(excluded_set)]
    except ImportError:
        pass

    # Calculate expected remaining stock from transaction log
    expected_remaining = calculate_expected_remaining_series(log_df)

    actual_quantity = inventory_df.set_index(COL_ITEM_ID)[COL_QUANTITY]
    cost_map = inventory_df.set_index(COL_ITEM_ID)[COL_COST_PRICE]
    name_map = inventory_df.set_index(COL_ITEM_ID)[COL_ITEM_NAME]

    for item_id in inventory_df[COL_ITEM_ID]:
        expected = expected_remaining.get(item_id, 0)
        actual = actual_quantity.get(item_id, 0)
        variance = actual - expected
        variance_pct = (variance / expected * 100) if expected != 0 else 0
        cost = cost_map.get(item_id, 0)
        variance_value = variance * cost

        report_data.append({
            COL_ITEM_ID: item_id,
            COL_ITEM_NAME: name_map.get(item_id, item_id),
            COL_COST_PRICE: cost,
            'Expected': expected,
            'Actual': actual,
            'Variance': variance,
            'Variance %': variance_pct,
            'Variance Value': variance_value
        })

    # Allocate variance values so the item rows add up to the net variance shown.
    variance_values = allocate_money([row['Variance Value'] for row in report_data])
    for row, value in zip(report_data, variance_values):
        row['Variance Value'] = value

    return report_data


def build_division_report_data(inventory_df, log_df, member_discount_pct=10):
    """Build data for Division Report.

    Returns DataFrame with columns: Division, Total Quantity, Total Revenue,
    Total Cost, GP, GP%, Member Revenue, Member GP, Member GP%
    """
    columns = ['Division', 'Total Quantity', 'Total Revenue',
               'Total Cost', 'GP', 'GP%', 'Member Revenue',
               'Member GP', 'Member GP%',
               'Non-Member Revenue', 'Non-Member GP', 'Non-Member GP%']
    if log_df is None or log_df.empty:
        return pd.DataFrame(columns=columns)

    item_money = sales_money_by_item(log_df, member_discount_pct)
    if item_money.empty:
        return pd.DataFrame(columns=columns)

    # Same division source as the comprehensive report: the live inventory
    # column first, Items.csv only where that column is blank.
    lookup = item_division_lookup(inventory_df)
    sales_with_names = item_money.copy()
    sales_with_names['Division'] = [
        lookup.get(item_id, 'Unknown') for item_id in sales_with_names.index
    ]

    division_summary = sales_with_names.groupby('Division').agg({
        'sales_qty': 'sum',
        'member_revenue': 'sum',
        'non_member_revenue': 'sum',
        'total_revenue': 'sum',
        'total_cost': 'sum',
        'member_cost': 'sum',
        'member_gp': 'sum',
        'non_member_gp': 'sum',
        'non_member_cost': 'sum',
        'gp': 'sum',
    }).reset_index()
    division_summary.columns = [
        'Division', 'Total Quantity', 'Member Revenue', 'Non-Member Revenue',
        'Total Revenue', 'Total Cost', 'Member Cost', 'Member GP',
        'Non-Member GP', 'Non-Member Cost', 'GP',
    ]

    money_columns = ['Member Revenue', 'Non-Member Revenue', 'Total Revenue',
                     'Total Cost', 'Member GP', 'Non-Member GP', 'GP']
    for column in money_columns:
        division_summary[column] = [round_money(v) for v in division_summary[column]]

    division_summary['GP%'] = np.where(
        division_summary['Total Revenue'] > 0,
        division_summary['GP'] / division_summary['Total Revenue'] * 100,
        0.0
    )
    division_summary['Member GP%'] = np.where(
        division_summary['Member Revenue'] > 0,
        division_summary['Member GP'] / division_summary['Member Revenue'] * 100,
        0.0
    )
    division_summary['Non-Member GP%'] = np.where(
        division_summary['Non-Member Revenue'] > 0,
        division_summary['Non-Member GP'] / division_summary['Non-Member Revenue'] * 100,
        0.0
    )

    division_summary = division_summary.sort_values('Total Revenue', ascending=False)
    return division_summary[columns].round(2)


def build_draught_yield_data(inventory_df, log_df):
    """Build data for Draught Yield Report.

    Returns list of dicts with yield calculations for draught items.
    Dynamically detects all items with barrel conversion.
    """
    report_data = []
    if inventory_df.empty:
        return report_data

    # Dynamically detect draught items (barrel conversion)
    try:
        from conversions import STOCK_CONVERSIONS
        DRAUGHT_YIELD_ITEMS = {k for k, v in STOCK_CONVERSIONS.items() if v[0] == 'barrel'}
    except ImportError:
        DRAUGHT_YIELD_ITEMS = set()

    expected_remaining = calculate_expected_remaining_series(log_df)

    sales_df = log_df[log_df[COL_ACTION] .isin([ACTION_SALES, ACTION_SALES_ONE_UNIT])].groupby(COL_ITEM_ID)[COL_QUANTITY].sum()
    delivery_df = log_df[log_df[COL_ACTION] == ACTION_DELIVERY].groupby(COL_ITEM_ID)[COL_QUANTITY].sum()
    wastage_df = log_df[log_df[COL_ACTION].isin([ACTION_WASTAGE, ACTION_LINE_CLEAN])].groupby(COL_ITEM_ID)[COL_QUANTITY].sum()
    comp_df = log_df[log_df[COL_ACTION] == ACTION_COMPLIMENTARY].groupby(COL_ITEM_ID)[COL_QUANTITY].sum()
    supplier_return_df = log_df[log_df[COL_ACTION] == ACTION_SUPPLIER_RETURN].groupby(COL_ITEM_ID)[COL_QUANTITY].sum()
    open_tab_df = log_df[log_df[COL_ACTION] == ACTION_OPEN_TAB].groupby(COL_ITEM_ID)[COL_QUANTITY].sum()
    parent_adj_df = log_df[log_df[COL_ACTION] == ACTION_PARENT_STOCK_ADJ].groupby(COL_ITEM_ID)[COL_QUANTITY].sum()

    for item_id in inventory_df[COL_ITEM_ID]:
        item_row = inventory_df[inventory_df[COL_ITEM_ID] == item_id].iloc[0]
        item_name = item_row[COL_ITEM_NAME]

        if item_id in DRAUGHT_YIELD_ITEMS:
            sales_qty = sales_df.get(item_id, 0)
            delivery_qty = delivery_df.get(item_id, 0)
            wastage_qty = wastage_df.get(item_id, 0)
            comp_qty = comp_df.get(item_id, 0)
            supplier_return_qty = supplier_return_df.get(item_id, 0)
            current_stock = item_row[COL_QUANTITY]

            # Recorded consumption is actual usage (sales/wastage/complimentary
            # plus parent-side deductions from child sales). Open Tab and supplier
            # returns are not consumption, so they are excluded here.
            expected_consumption = (sales_qty + wastage_qty + comp_qty +
                                    parent_adj_df.get(item_id, 0))

            # Variance between transaction-expected stock and counted stock.
            # Positive unrecorded_loss means physical stock is lower than expected (shrinkage).
            unrecorded_loss = expected_remaining.get(item_id, 0) - current_stock

            # Actual consumption includes recorded usage plus any unrecorded shrinkage.
            actual_consumption = expected_consumption + unrecorded_loss

            # Derive opening stock from the other values so the report balances.
            # Supplier returns already reduce expected_remaining, so no extra term is needed here.
            opening_stock = current_stock + actual_consumption - delivery_qty
            yield_pct = (sales_qty / expected_consumption * 100) if expected_consumption > 0 else 0

            report_data.append({
                COL_ITEM_ID: item_id,
                COL_ITEM_NAME: item_name,
                'Opening Stock': opening_stock,
                'Deliveries': delivery_qty,
                ACTION_SALES: sales_qty,
                ACTION_WASTAGE: wastage_qty,
                ACTION_COMPLIMENTARY: comp_qty,
                'Expected Consumption': expected_consumption,
                'Actual Consumption': actual_consumption,
                'Unrecorded Loss': unrecorded_loss,
                'Current Stock': current_stock,
                'Yield %': yield_pct
            })

    return report_data


def build_price_history_data(inventory_df, log_df):
    """Build data for Price History Report.

    Returns list of dicts with delivery price history.
    """
    report_data = []
    if log_df.empty:
        return report_data

    delivery_log = log_df[log_df[COL_ACTION] == ACTION_DELIVERY].copy()
    if delivery_log.empty:
        return report_data

    if not inventory_df.empty and COL_ITEM_ID in inventory_df.columns:
        delivery_log = delivery_log.merge(
            inventory_df[[COL_ITEM_ID, COL_ITEM_NAME]], on=COL_ITEM_ID, how='left'
        )
    else:
        delivery_log[COL_ITEM_NAME] = delivery_log[COL_ITEM_ID]

    delivery_log = delivery_log.sort_values(by=[COL_ITEM_ID, COL_TIMESTAMP])

    prev_prices = {}
    for _, row in delivery_log.iterrows():
        item_id = row[COL_ITEM_ID]
        item_name = row.get(COL_ITEM_NAME, item_id)
        timestamp = row[COL_TIMESTAMP]
        supplier = row.get(COL_SUPPLIER, "")
        cost_price = row.get(COL_COST_PRICE, 0)

        prev_price = prev_prices.get(item_id, cost_price)
        change = cost_price - prev_price
        change_pct = ((change / prev_price) * 100) if prev_price else 0
        prev_prices[item_id] = cost_price

        report_data.append({
            COL_ITEM_ID: item_id,
            COL_ITEM_NAME: item_name,
            COL_TIMESTAMP: timestamp,
            COL_SUPPLIER: supplier,
            COL_COST_PRICE: cost_price,
            'prev_price': prev_price,
            'change': change,
            'change_pct': change_pct
        })

    return report_data


def build_sales_analytics_data(inventory_df, log_df):
    """Build data for Sales Trends & Analytics tabs.

    Returns dict with keys: category_sales, fast_movers, slow_movers,
    timeline_data, profit_margins
    """
    result = {
        'category_sales': pd.DataFrame(),
        'fast_movers': pd.DataFrame(),
        'slow_movers': pd.DataFrame(),
        'timeline_data': pd.DataFrame(),
        'profit_margins': pd.DataFrame()
    }

    if log_df.empty:
        return result

    sales_df = log_df[log_df[COL_ACTION] .isin([ACTION_SALES, ACTION_SALES_ONE_UNIT])].copy()
    if sales_df.empty:
        return result

    # Category sales
    sales_with_cat = sales_df.merge(
        inventory_df[[COL_ITEM_ID, COL_ITEM_NAME, COL_CATEGORY]],
        on=COL_ITEM_ID, how='left'
    )
    result['category_sales'] = sales_with_cat.groupby(COL_CATEGORY).agg({
        COL_QUANTITY: 'sum',
        COL_ITEM_ID: 'nunique'
    }).reset_index()
    result['category_sales'].columns = [COL_CATEGORY, 'Total Quantity', 'Unique Items']
    result['category_sales'] = result['category_sales'].sort_values('Total Quantity', ascending=False)

    # Fast / slow movers
    sales_with_info = sales_df.merge(
        inventory_df[[COL_ITEM_ID, COL_ITEM_NAME, COL_CATEGORY]],
        on=COL_ITEM_ID, how='left'
    )
    item_sales = sales_with_info.groupby([COL_ITEM_ID, COL_ITEM_NAME, COL_CATEGORY]).agg({
        COL_QUANTITY: 'sum'
    }).reset_index()
    item_sales.columns = [COL_ITEM_ID, COL_ITEM_NAME, COL_CATEGORY, 'Total Sales']
    item_sales = item_sales.sort_values('Total Sales', ascending=False)
    result['fast_movers'] = item_sales.head(10)
    result['slow_movers'] = item_sales.tail(10)

    # Timeline data
    sales_timeline = sales_df.copy()
    sales_timeline['date'] = pd.to_datetime(sales_timeline[COL_TIMESTAMP], errors='coerce').dt.date
    timeline = sales_timeline.groupby('date')[COL_QUANTITY].sum().reset_index()
    timeline.columns = ['date', 'daily_sales']
    result['timeline_data'] = timeline.sort_values('date')

    # Profit margins by category
    sales_with_cat['total_revenue'] = sales_with_cat[COL_QUANTITY] * sales_with_cat[COL_SELL_PRICE]
    sales_with_cat['total_cost'] = sales_with_cat[COL_QUANTITY] * sales_with_cat[COL_COST_PRICE]
    profit_data = sales_with_cat.groupby(COL_CATEGORY).agg({
        'total_revenue': 'sum',
        'total_cost': 'sum',
        COL_QUANTITY: 'sum'
    }).reset_index()
    profit_data['profit'] = profit_data['total_revenue'] - profit_data['total_cost']
    profit_data['avg_margin_pct'] = profit_data.apply(
        lambda row: (row['profit'] / row['total_revenue'] * 100) if row['total_revenue'] != 0 else 0,
        axis=1
    )
    profit_data.columns = [COL_CATEGORY, 'Total Revenue', 'Total Cost', 'Quantity', 'Profit', 'Avg Margin %']
    profit_data = profit_data.sort_values('Profit', ascending=False)
    result['profit_margins'] = profit_data

    return result


def _get_currently_open_tab_ids():
    """Return the set of open_tab_id values that are still status='open'.

    Only currently pending (open) tabs should appear in the comprehensive report.
    Cancelled or closed tabs are excluded because their stock has already been
    restored or recognised as sales.
    """
    try:
        import data_manager
        db_path = data_manager.DB_PATH
    except Exception:
        return set()
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM open_tabs WHERE status = 'open'")
        rows = cursor.fetchall()
        conn.close()
        return {row[0] for row in rows}
    except Exception:
        return set()


def _get_latest_baseline_snapshot():
    """Load the most recent baseline reset snapshot from the audit table.

    Returns (timestamp_str, snapshot_dict) where snapshot_dict maps item_id to
    the counted system quantity at baseline. Returns (None, {}) if no baseline
    reset audit record exists.

    Older resets recorded an empty payload in the audit table, so the physical
    Baseline rows in ``stocktake_snapshots`` are used as a fallback. Without
    the snapshot, reports cannot anchor opening stock and every item starts
    from zero.
    """
    try:
        import data_manager
        db_path = getattr(data_manager, 'DB_PATH', None)
    except Exception:
        db_path = None
    if not db_path:
        from app_config import DATA_DIR
        db_path = os.path.join(DATA_DIR, 'barstock.db')
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, snapshot_json FROM baseline_resets
            ORDER BY timestamp DESC, id DESC LIMIT 1
        """)
        row = cursor.fetchone()
        timestamp = str(row['timestamp']) if row else None

        snapshot = {}
        if row and row['snapshot_json']:
            try:
                snapshot = {
                    item['item_id']: float(item.get('counted_system', 0))
                    for item in json.loads(row['snapshot_json'])
                }
            except Exception:
                snapshot = {}

        if not snapshot:
            if timestamp is None:
                cursor.execute("""
                    SELECT MAX(timestamp) AS ts FROM stocktake_snapshots
                    WHERE note LIKE '%Baseline%'
                """)
                ts_row = cursor.fetchone()
                timestamp = str(ts_row['ts']) if ts_row and ts_row['ts'] else None
            if timestamp is not None:
                cursor.execute("""
                    SELECT item_id, counted_quantity FROM stocktake_snapshots
                    WHERE note LIKE '%Baseline%' AND timestamp = ?
                """, (timestamp,))
                snapshot = {
                    r['item_id']: float(r['counted_quantity'])
                    for r in cursor.fetchall()
                }
        conn.close()
        if not snapshot:
            return timestamp, {}
        return timestamp, snapshot
    except Exception:
        return None, {}


def build_comprehensive_report_data(inventory_df, log_df, member_discount_pct=10, stocktake_map=None, closing_stock_map=None, use_current_cost_for_gp=False):
    """Build data for Comprehensive PDF Report.

    Returns list of dicts, one per inventory item.

    Args:
        stocktake_map: Optional dict mapping item_id -> counted quantity (legacy), or
                       item_id -> dict with 'counted_quantity', 'expected_quantity', 'variance'.
                       When the richer dict is provided, surplus is computed from the actual
                       stocktake variance rather than derived period consumption, which avoids
                       misinterpreting a closing stocktake as opening stock.
        closing_stock_map: Optional dict mapping item_id -> stock quantity at the end of the
                           report period. When provided, overrides live current_stock for
                           historical date-range consistency.
        use_current_cost_for_gp: When True, GP is calculated using the current inventory
                                 cost_price for every sold unit, ignoring historical
                                 transaction costs. This gives a trading GP% based on
                                 latest delivered costs rather than the cost at the
                                 time each sale was recorded.
    """
    report_data = []
    if inventory_df.empty:
        return report_data

    # Normalize stocktake_map to info dicts.
    stocktake_info = {}
    if stocktake_map:
        for k, v in stocktake_map.items():
            if isinstance(v, dict):
                stocktake_info[k] = v
            else:
                # Legacy scalar counted-quantity map
                stocktake_info[k] = {
                    'counted_quantity': float(v),
                    'expected_quantity': 0.0,
                    'variance': float(v),
                }

    # Aggregated log data
    if not log_df.empty:
        sales_data = log_df[log_df[COL_ACTION] .isin([ACTION_SALES, ACTION_SALES_ONE_UNIT])].groupby(COL_ITEM_ID).agg({
            COL_QUANTITY: 'sum',
            COL_COST_PRICE: 'mean',
            COL_SELL_PRICE: 'mean'
        }).reset_index()
        sales_data.columns = [COL_ITEM_ID, 'total_sales_qty', 'avg_cost_price', 'avg_sell_price']
        sales_data['total_sales_value'] = sales_data['total_sales_qty'] * sales_data['avg_sell_price']
        sales_data['total_sales_cost'] = sales_data['total_sales_qty'] * sales_data['avg_cost_price']
        sales_data['sales_gp'] = sales_data['total_sales_value'] - sales_data['total_sales_cost']

        # Wastage excludes line-clean entries; those are reported separately.
        wastage_data = log_df[
            (log_df[COL_ACTION] == ACTION_WASTAGE) &
            (log_df[COL_REASON] != 'Line Clean')
        ].groupby(COL_ITEM_ID).agg({
            COL_QUANTITY: 'sum'
        }).reset_index()
        wastage_data.columns = [COL_ITEM_ID, 'total_wastage_qty']

        # De-duplicate identical line-clean rows logged repeatedly at the same
        # timestamp (e.g. 5 pints per tap should only count once per event).
        line_clean_log = log_df[(log_df[COL_ACTION] == ACTION_WASTAGE) & (log_df[COL_REASON] == 'Line Clean')].copy()
        line_clean_log = line_clean_log.drop_duplicates(subset=[COL_ITEM_ID, COL_TIMESTAMP, COL_QUANTITY])
        line_clean_data = line_clean_log.groupby(COL_ITEM_ID).agg({
            COL_QUANTITY: 'sum'
        }).reset_index()
        line_clean_data.columns = [COL_ITEM_ID, 'total_line_clean_qty']

        comp_data = log_df[log_df[COL_ACTION] == ACTION_COMPLIMENTARY].groupby(COL_ITEM_ID).agg({
            COL_QUANTITY: 'sum'
        }).reset_index()
        comp_data.columns = [COL_ITEM_ID, 'total_complimentary_qty']

        supplier_return_agg = {COL_QUANTITY: 'sum'}
        if COL_SUPPLIER in log_df.columns:
            supplier_return_agg[COL_SUPPLIER] = lambda s: ', '.join(sorted(set(s.dropna().astype(str).str.strip()))) if not s.empty else ''
        if COL_REASON in log_df.columns:
            supplier_return_agg[COL_REASON] = lambda r: ', '.join(sorted(set(r.dropna().astype(str).str.strip()))) if not r.empty else ''
        supplier_return_data = log_df[log_df[COL_ACTION] == ACTION_SUPPLIER_RETURN].groupby(COL_ITEM_ID).agg(supplier_return_agg).reset_index()
        supplier_return_columns = [COL_ITEM_ID, 'total_supplier_return_qty']
        if COL_SUPPLIER in log_df.columns:
            supplier_return_columns.append('supplier_return_supplier')
        if COL_REASON in log_df.columns:
            supplier_return_columns.append('supplier_return_reason')
        supplier_return_data.columns = supplier_return_columns

        # Only include tabs that are still open (status='open'). Cancelled/closed tabs have
        # already been accounted for by Tab Cancelled or Sales transactions.
        open_tab_ids = _get_currently_open_tab_ids()
        if open_tab_ids and COL_OPEN_TAB_ID in log_df.columns:
            open_tab_mask = (
                (log_df[COL_ACTION] == ACTION_OPEN_TAB) &
                (log_df[COL_OPEN_TAB_ID].isin(open_tab_ids))
            )
            open_tab_data = log_df[open_tab_mask].groupby(COL_ITEM_ID).agg({
                COL_QUANTITY: 'sum'
            }).reset_index()
            open_tab_data.columns = [COL_ITEM_ID, 'total_open_tab_qty']
        else:
            open_tab_data = pd.DataFrame(columns=[COL_ITEM_ID, 'total_open_tab_qty'])

        delivery_data = log_df[log_df[COL_ACTION] == ACTION_DELIVERY].groupby(COL_ITEM_ID).agg({
            COL_QUANTITY: 'sum'
        }).reset_index()
        delivery_data.columns = [COL_ITEM_ID, 'total_delivery_qty']

        parent_adj_data = log_df[log_df[COL_ACTION] == ACTION_PARENT_STOCK_ADJ].groupby(COL_ITEM_ID).agg({
            COL_QUANTITY: 'sum'
        }).reset_index()
        parent_adj_data.columns = [COL_ITEM_ID, 'total_parent_adj_qty']
    else:
        sales_data = pd.DataFrame(columns=[COL_ITEM_ID, 'total_sales_qty', 'avg_cost_price',
                                          'avg_sell_price', 'total_sales_value', 'total_sales_cost', 'sales_gp'])
        wastage_data = pd.DataFrame(columns=[COL_ITEM_ID, 'total_wastage_qty'])
        line_clean_data = pd.DataFrame(columns=[COL_ITEM_ID, 'total_line_clean_qty'])
        comp_data = pd.DataFrame(columns=[COL_ITEM_ID, 'total_complimentary_qty'])
        supplier_return_columns = [COL_ITEM_ID, 'total_supplier_return_qty']
        if COL_SUPPLIER in log_df.columns:
            supplier_return_columns.append('supplier_return_supplier')
        if COL_REASON in log_df.columns:
            supplier_return_columns.append('supplier_return_reason')
        supplier_return_data = pd.DataFrame(columns=supplier_return_columns)
        open_tab_data = pd.DataFrame(columns=[COL_ITEM_ID, 'total_open_tab_qty'])
        delivery_data = pd.DataFrame(columns=[COL_ITEM_ID, 'total_delivery_qty'])
        parent_adj_data = pd.DataFrame(columns=[COL_ITEM_ID, 'total_parent_adj_qty'])

    # Hidden / excluded items
    try:
        from categories import EXCLUDED_ITEMS
        excluded_items = set(EXCLUDED_ITEMS)
    except ImportError:
        excluded_items = set()

    try:
        from sales_mapping import get_hidden_items
        hidden_item_ids = set(get_hidden_items())
    except ImportError:
        hidden_item_ids = set()

    excluded_item_ids = {k for k in excluded_items if k not in hidden_item_ids}

    # Load the latest baseline reset snapshot. When a baseline reset exists,
    # use it as the authoritative opening stock anchor so the report never
    # invents negative opening stock from pre-baseline archive history.
    latest_baseline_ts, baseline_snapshot = _get_latest_baseline_snapshot()
    has_baseline_snapshot = bool(latest_baseline_ts) and baseline_snapshot

    # If a baseline reset exists, ignore any transactions that pre-date it.
    # The full history is still preserved in transaction_archive for all-time
    # reports; the comprehensive report shows the current period from baseline.
    # Only apply the baseline cut-off when the selected log period starts at or
    # after the baseline. If the period includes pre-baseline history (e.g. an
    # all-time report, or an older date range), keep the full log so sales/GP
    # history is preserved. Also skip the cut-off for purely synthetic unit tests.
    if (has_baseline_snapshot and not log_df.empty and COL_TIMESTAMP in log_df.columns):
        log_timestamps = log_df[COL_TIMESTAMP].astype(str)
        if (log_timestamps.max() >= str(latest_baseline_ts) and
                log_timestamps.min() >= str(latest_baseline_ts)):
            log_df = log_df[log_timestamps >= str(latest_baseline_ts)].copy()

    # Pre-compute unified expected remaining for opening stock derivation
    expected_remaining_series = calculate_expected_remaining_series(log_df)

    # Canonical sales money and division assignment, shared with the GP and
    # Division reports so every figure is struck at the same penny.
    item_money = sales_money_by_item(log_df, member_discount_pct)
    division_lookup = item_division_lookup(inventory_df)

    # Delisted lines carry no stock, so they are dropped from the report
    # entirely unless they still appear in the selected period - typically the
    # final sell-off before delisting. Those sales stay in the item breakdown
    # (with zero stock) so the revenue and GP totals keep reconciling with EPOS.
    delisted_activity_actions = {
        ACTION_SALES, ACTION_SALES_ONE_UNIT, ACTION_DELIVERY,
        ACTION_WASTAGE, ACTION_LINE_CLEAN, ACTION_COMPLIMENTARY,
        ACTION_OPEN_TAB, ACTION_SUPPLIER_RETURN,
    }
    if not log_df.empty and COL_ITEM_ID in log_df.columns:
        delisted_activity_ids = set(
            log_df.loc[log_df[COL_ACTION].isin(delisted_activity_actions), COL_ITEM_ID].astype(str))
    else:
        delisted_activity_ids = set()

    for _, inv_row in inventory_df.iterrows():
        item_id = inv_row[COL_ITEM_ID]
        item_name = inv_row[COL_ITEM_NAME]

        if is_delisted(item_id) and str(item_id) not in delisted_activity_ids:
            continue

        # Use historical closing stock when a date-range map is provided; fall back to live stock
        current_stock = closing_stock_map.get(item_id, inv_row[COL_QUANTITY]) if closing_stock_map else inv_row[COL_QUANTITY]
        cost_price = inv_row[COL_COST_PRICE]
        sell_price = inv_row[COL_SELL_PRICE]

        division = division_lookup.get(item_id, 'Unknown')

        sales_row = sales_data[sales_data[COL_ITEM_ID] == item_id]
        if not sales_row.empty:
            total_sales_qty = sales_row['total_sales_qty'].iloc[0]
            total_sales_value = sales_row['total_sales_value'].iloc[0]
            total_sales_cost = sales_row['total_sales_cost'].iloc[0]
            sales_gp = sales_row['sales_gp'].iloc[0]
            sales_gp_pct = (sales_gp / total_sales_value * 100) if total_sales_value > 0 else 0
        else:
            total_sales_qty = 0
            total_sales_value = 0
            total_sales_cost = 0
            sales_gp = 0
            sales_gp_pct = 0

        wastage_row = wastage_data[wastage_data[COL_ITEM_ID] == item_id]
        total_wastage_qty = wastage_row['total_wastage_qty'].iloc[0] if not wastage_row.empty else 0

        line_clean_row = line_clean_data[line_clean_data[COL_ITEM_ID] == item_id]
        total_line_clean_qty = line_clean_row['total_line_clean_qty'].iloc[0] if not line_clean_row.empty else 0

        comp_row = comp_data[comp_data[COL_ITEM_ID] == item_id]
        total_complimentary_qty = comp_row['total_complimentary_qty'].iloc[0] if not comp_row.empty else 0

        supplier_return_row = supplier_return_data[supplier_return_data[COL_ITEM_ID] == item_id]
        total_supplier_return_qty = supplier_return_row['total_supplier_return_qty'].iloc[0] if not supplier_return_row.empty else 0
        supplier_return_supplier = supplier_return_row['supplier_return_supplier'].iloc[0] if not supplier_return_row.empty and 'supplier_return_supplier' in supplier_return_data.columns else ''
        supplier_return_reason = supplier_return_row['supplier_return_reason'].iloc[0] if not supplier_return_row.empty and 'supplier_return_reason' in supplier_return_data.columns else ''

        open_tab_row = open_tab_data[open_tab_data[COL_ITEM_ID] == item_id]
        total_open_tab_qty = open_tab_row['total_open_tab_qty'].iloc[0] if not open_tab_row.empty else 0

        delivery_row = delivery_data[delivery_data[COL_ITEM_ID] == item_id]
        total_delivery_qty = delivery_row['total_delivery_qty'].iloc[0] if not delivery_row.empty else 0

        parent_adj_row = parent_adj_data[parent_adj_data[COL_ITEM_ID] == item_id]
        total_parent_adj_qty = parent_adj_row['total_parent_adj_qty'].iloc[0] if not parent_adj_row.empty else 0

        # Consumption excludes open-tab reservations and supplier returns; those are
        # tracked separately. Supplier returns reduce stock but are not treated as loss.
        expected_consumption = (total_sales_qty + total_parent_adj_qty + total_wastage_qty +
                                total_line_clean_qty + total_complimentary_qty)

        # Use stocktake snapshot data when available. The stocktake variance
        # (counted - expected) is the authoritative surplus/shortfall figure and
        # matches the Stocktake Variance Report. Period consumption metrics are
        # adjusted so they are consistent with that variance.
        if stocktake_info and item_id in stocktake_info:
            st = stocktake_info[item_id]
            counted_quantity = float(st.get('counted_quantity', 0))
            expected_quantity = float(st.get('expected_quantity', 0))
            variance = float(st.get('variance', counted_quantity - expected_quantity))
            opening_stock = counted_quantity
            # Adjust actual consumption so the implied variance equals the stocktake variance
            actual_consumption = expected_consumption - variance
            consumption_variance = variance
            consumption_variance_pct = (variance / actual_consumption * 100) if actual_consumption > 0 else 0
            expected_closing = expected_quantity
            # Surplus = counted - system expected at stocktake, valued at cost price
            surplus_value = variance * cost_price
        else:
            # Derive opening stock. Prefer the latest baseline snapshot when one
            # exists, so post-baseline reports never invent negative opening stock
            # from pre-baseline archive history.
            if has_baseline_snapshot and item_id in baseline_snapshot:
                opening_stock = baseline_snapshot[item_id]
            else:
                opening_stock = current_stock - expected_remaining_series.get(item_id, 0)
                # Guard against negative opening stock when archive history
                # predates the current inventory state.
                if opening_stock < 0:
                    opening_stock = 0.0
            expected_closing = opening_stock + total_delivery_qty - expected_consumption
            actual_consumption = None
            consumption_variance = None
            consumption_variance_pct = None
            surplus_value = None

        is_hidden = item_id in hidden_item_ids or item_id in excluded_item_ids
        is_draught = (inv_row.get(COL_CATEGORY, '') == 'Draught')
        yield_pct = (total_sales_qty / expected_consumption * 100) if expected_consumption > 0 and is_draught else 0

        # Money comes from the canonical per-item allocation shared with the
        # GP and Division reports; only the quantity split is computed here.
        actual_sales = log_df[(log_df[COL_ACTION].isin([ACTION_SALES, ACTION_SALES_ONE_UNIT])) & (log_df[COL_ITEM_ID] == item_id)].copy()
        member_qty = 0.0
        non_member_qty = 0.0

        if not actual_sales.empty and COL_MEMBER_QTY in actual_sales.columns:
            split_sum = actual_sales[COL_MEMBER_QTY].fillna(0) + actual_sales[COL_NON_MEMBER_QTY].fillna(0)
            has_actual = split_sum > 0
            if has_actual.any():
                qty = actual_sales.loc[has_actual, COL_QUANTITY]
                member_qty_col = actual_sales.loc[has_actual, COL_MEMBER_QTY].fillna(0)
                non_member_qty_col = actual_sales.loc[has_actual, COL_NON_MEMBER_QTY].fillna(0)
                remaining = np.maximum(qty - member_qty_col - non_member_qty_col, 0)
                member_qty = member_qty_col.sum()
                non_member_qty = (non_member_qty_col + remaining).sum()
            else:
                non_member_qty = actual_sales[COL_QUANTITY].sum()
        elif not actual_sales.empty:
            non_member_qty = actual_sales[COL_QUANTITY].sum()

        if item_id in item_money.index:
            money_row = item_money.loc[item_id]
            member_sales_value = float(money_row['member_revenue'])
            non_member_sales_value = float(money_row['non_member_revenue'])
            member_cost = float(money_row['member_cost'])
            non_member_cost = float(money_row['non_member_cost'])
        else:
            member_sales_value = 0.0
            non_member_sales_value = 0.0
            member_cost = 0.0
            non_member_cost = 0.0

        member_gp = member_sales_value - member_cost
        member_gp_pct = (member_gp / member_sales_value * 100) if member_sales_value > 0 else 0
        non_member_gp = non_member_sales_value - non_member_cost
        non_member_gp_pct = (non_member_gp / non_member_sales_value * 100) if non_member_sales_value > 0 else 0

        current_stock_value = current_stock * cost_price

        # Capture physical (live DB) stock value for delisted items before zeroing
        # it out, so it can be reported separately without affecting totals.
        delisted_stock_value = 0.0
        if is_delisted(item_id):
            delisted_stock_value = current_stock * cost_price
            current_stock = 0.0
            current_stock_value = 0.0
            opening_stock = 0.0
            expected_closing = 0.0
            item_name = f"{item_name} (DELISTED)"

        # Use actual transaction-level sums for totals
        actual_total_revenue = member_sales_value + non_member_sales_value
        actual_total_cost = member_cost + non_member_cost
        actual_total_gp = member_gp + non_member_gp
        actual_gp_pct = (actual_total_gp / actual_total_revenue * 100) if actual_total_revenue > 0 else 0

        report_data.append({
            'item_id': item_id,
            'item_name': item_name,
            'division': division,
            'is_delisted': is_delisted(item_id),
            'cost_price': cost_price,
            'sell_price': sell_price,
            'current_stock': current_stock,
            'stock_value': current_stock_value,
            'total_sales_qty': total_sales_qty,
            'total_sales_value': actual_total_revenue,
            'sales_cost': actual_total_cost,
            'sales_gp': actual_total_gp,
            'sales_gp_pct': actual_gp_pct,
            'member_sales_value': member_sales_value,
            'member_gp': member_gp,
            'member_gp_pct': member_gp_pct,
            'non_member_sales_value': non_member_sales_value,
            'non_member_gp': non_member_gp,
            'non_member_gp_pct': non_member_gp_pct,
            'member_qty': member_qty if 'member_qty' in dir() else 0,
            'non_member_qty': non_member_qty if 'non_member_qty' in dir() else 0,
            'wastage_qty': total_wastage_qty,
            'line_clean_qty': total_line_clean_qty,
            'complimentary_qty': total_complimentary_qty,
            'supplier_return_qty': total_supplier_return_qty,
            'supplier_return_supplier': supplier_return_supplier,
            'supplier_return_reason': supplier_return_reason,
            'open_tab_qty': total_open_tab_qty,
            'expected_consumption': expected_consumption,
            'opening_stock': opening_stock,
            'delivery_qty': total_delivery_qty,
            'parent_adj_qty': total_parent_adj_qty,
            'expected_closing': expected_closing,
            'actual_consumption': actual_consumption,
            'consumption_variance': consumption_variance,
            'consumption_variance_pct': consumption_variance_pct,
            'surplus_value': surplus_value,
            'is_draught': is_draught,
            'yield_pct': yield_pct,
            'is_hidden': is_hidden,
            'delisted_stock_value': delisted_stock_value,
        })

    # Allocate stock values to the penny so the division stock rows in the
    # PDF add up exactly to the Total Stock Value shown on the summary.
    stock_values = allocate_money([row['stock_value'] for row in report_data])
    for row, value in zip(report_data, stock_values):
        row['stock_value'] = value

    return report_data


def build_reorder_report_data(inventory_df, log_df):
    """Build data for Reorder Suggestion Report.

    Returns list of dicts with keys: item_id, item_name, current_stock,
    reorder_level, suggested_order, last_delivery_date, supplier
    """
    report_data = []
    if inventory_df.empty:
        return report_data

    # Get last delivery info per item
    last_delivery = {}
    if not log_df.empty:
        delivery_log = log_df[log_df[COL_ACTION] == ACTION_DELIVERY].copy()
        if not delivery_log.empty:
            delivery_log['dt'] = pd.to_datetime(delivery_log[COL_TIMESTAMP], errors='coerce')
            delivery_log = delivery_log.sort_values('dt', ascending=False)
            for _, row in delivery_log.iterrows():
                item_id = row[COL_ITEM_ID]
                if item_id not in last_delivery:
                    last_delivery[item_id] = {
                        'date': _format_delivery_date(row[COL_TIMESTAMP]) if pd.notna(row[COL_TIMESTAMP]) else '',
                        'supplier': str(row.get(COL_SUPPLIER, ''))
                    }

    for _, inv_row in inventory_df.iterrows():
        item_id = inv_row[COL_ITEM_ID]
        item_name = inv_row[COL_ITEM_NAME]
        current_stock = inv_row[COL_QUANTITY]
        reorder_level = inv_row.get(COL_REORDER_LEVEL, 0)

        if reorder_level <= 0:
            continue

        if current_stock > reorder_level:
            continue

        suggested_order = max(reorder_level * 2 - current_stock, reorder_level)

        ld = last_delivery.get(item_id, {'date': '', 'supplier': ''})

        report_data.append({
            COL_ITEM_ID: item_id,
            COL_ITEM_NAME: item_name,
            COL_QUANTITY: current_stock,
            COL_REORDER_LEVEL: reorder_level,
            'suggested_order': suggested_order,
            'last_delivery_date': ld['date'],
            COL_SUPPLIER: ld['supplier']
        })

    # Sort by suggested_order descending (most urgent first)
    report_data.sort(key=lambda x: x['suggested_order'], reverse=True)
    return report_data


def build_stock_order_sheet_data(inventory_df, log_df):
    """Build data for the printable Stock Order Sheet.

    Returns a list of dicts ready for grouping by supplier and product type.
    Excludes ignored items (categories.EXCLUDED_ITEMS) and child products
    that deduct from parent stock (sales_mapping.is_hidden_from_stock_view).

    Each dict contains: item_id, item_name, product_type, supplier,
    current_stock, measure, reorder_level, suggested_order,
    last_delivery_date, last_delivery_supplier.
    """
    report_data = []
    if inventory_df.empty:
        return report_data

    # Get last delivery info per item (date + supplier)
    last_delivery = {}
    if not log_df.empty and COL_ACTION in log_df.columns and COL_SUPPLIER in log_df.columns:
        delivery_log = log_df[log_df[COL_ACTION] == ACTION_DELIVERY].copy()
        if not delivery_log.empty:
            delivery_log['dt'] = pd.to_datetime(delivery_log[COL_TIMESTAMP], errors='coerce')
            delivery_log = delivery_log.sort_values('dt', ascending=False)
            for _, row in delivery_log.iterrows():
                item_id = row[COL_ITEM_ID]
                if item_id not in last_delivery:
                    last_delivery[item_id] = {
                        'date': _format_delivery_date(row[COL_TIMESTAMP]) if pd.notna(row[COL_TIMESTAMP]) else '',
                        'supplier': str(row.get(COL_SUPPLIER, ''))
                    }

    for _, inv_row in inventory_df.iterrows():
        item_id = inv_row[COL_ITEM_ID]

        # Skip ignored items
        if should_exclude(item_id):
            continue

        # Skip child/hidden items that deduct from parent stock
        if is_hidden_from_stock_view(item_id):
            continue

        item_name = inv_row[COL_ITEM_NAME]
        current_stock = inv_row[COL_QUANTITY]
        measure = inv_row.get(COL_MEASURE, '')
        reorder_level = inv_row.get(COL_REORDER_LEVEL, 0) if COL_REORDER_LEVEL in inv_row.index else 0
        product_type = get_category(item_id)
        supplier = get_supplier(item_id, product_type)

        if reorder_level and reorder_level > 0:
            suggested_order = max(0.0, reorder_level * 2 - current_stock)
        else:
            suggested_order = 0.0

        ld = last_delivery.get(item_id, {'date': '', 'supplier': ''})

        report_data.append({
            COL_ITEM_ID: item_id,
            COL_ITEM_NAME: item_name,
            COL_CATEGORY: product_type,
            COL_SUPPLIER: supplier,
            COL_QUANTITY: current_stock,
            COL_MEASURE: measure,
            COL_REORDER_LEVEL: reorder_level,
            'suggested_order': suggested_order,
            'last_delivery_date': ld['date'],
            'last_delivery_supplier': ld['supplier'],
        })

    # Sort by supplier order, then product type order, then item name
    category_rank = {c: i for i, c in enumerate(CATEGORY_ORDER)}

    report_data.sort(key=lambda x: (
        supplier_rank(x[COL_SUPPLIER]),
        category_rank.get(x[COL_CATEGORY], 999),
        str(x[COL_ITEM_NAME]).lower(),
    ))
    return report_data


def build_custom_stock_order_sheet_data(inventory_df, _log_df=None):
    """Build the custom stock order sheet from order_sheet_layout.py.

    Returns a list of dicts with keys: item_id, item_name, supplier, category,
    current_stock, measure, reorder_level, suggested_order. Items are sorted
    alphabetically by display name within each category, and categories are
    returned in the order defined in ORDER_SHEET_LAYOUT.

    Items that are not tracked in inventory (item_id is None) are still
    included so the order form matches the user's requested layout.

    Delisted items are omitted from the order sheet so they are not reordered.
    """
    from categories import is_delisted

    report_data = []
    if inventory_df.empty:
        inventory_by_id = {}
    else:
        inventory_by_id = {
            str(row[COL_ITEM_ID]).lower(): row
            for _, row in inventory_df.iterrows()
        }

    layout = get_order_sheet_layout()

    for supplier, categories in layout:
        for category, items in categories:
            # Sort items alphabetically by display name
            sorted_items = sorted(items, key=lambda x: str(x[0]).lower())

            for display_name, item_id in sorted_items:
                if item_id is not None and is_delisted(str(item_id)):
                    continue

                if item_id is None:
                    report_data.append({
                        COL_ITEM_ID: '',
                        COL_ITEM_NAME: display_name,
                        COL_SUPPLIER: supplier,
                        COL_CATEGORY: category,
                        COL_QUANTITY: None,
                        COL_MEASURE: '',
                        COL_REORDER_LEVEL: 0,
                        'suggested_order': 0,
                        'is_placeholder': True,
                    })
                    continue

                row = inventory_by_id.get(str(item_id).lower())
                if row is None:
                    # Item listed in layout but not in current inventory
                    report_data.append({
                        COL_ITEM_ID: item_id,
                        COL_ITEM_NAME: display_name,
                        COL_SUPPLIER: supplier,
                        COL_CATEGORY: category,
                        COL_QUANTITY: None,
                        COL_MEASURE: '',
                        COL_REORDER_LEVEL: 0,
                        'suggested_order': 0,
                        'is_placeholder': True,
                    })
                    continue

                current_stock = row[COL_QUANTITY]
                measure = row.get(COL_MEASURE, '')
                reorder_level = row.get(COL_REORDER_LEVEL, 0) if COL_REORDER_LEVEL in row.index else 0

                if reorder_level and reorder_level > 0:
                    suggested_order = max(0.0, reorder_level * 2 - current_stock)
                else:
                    suggested_order = 0.0

                report_data.append({
                    COL_ITEM_ID: item_id,
                    COL_ITEM_NAME: display_name,
                    COL_SUPPLIER: supplier,
                    COL_CATEGORY: category,
                    COL_QUANTITY: current_stock,
                    COL_MEASURE: measure,
                    COL_REORDER_LEVEL: reorder_level,
                    'suggested_order': suggested_order,
                    'is_placeholder': False,
                })

    return report_data


def build_comparison_report_data(inventory_df, log_a, log_b, member_discount_pct=10):
    """Build data for Period Comparison Report.

    Args:
        inventory_df: Inventory DataFrame
        log_a: Transaction log DataFrame for Period A
        log_b: Transaction log DataFrame for Period B
        member_discount_pct: Member discount percentage

    Returns DataFrame with comparison data per item.
    """
    member_mult = (100 - member_discount_pct) / 100

    def aggregate_sales(log_df):
        if log_df.empty:
            return pd.DataFrame(columns=[COL_ITEM_ID, 'total_qty', 'total_revenue', 'total_cost', 'total_gp'])
        sales = log_df[log_df[COL_ACTION].isin([ACTION_SALES, ACTION_SALES_ONE_UNIT])].copy()
        if sales.empty:
            return pd.DataFrame(columns=[COL_ITEM_ID, 'total_qty', 'total_revenue', 'total_cost', 'total_gp'])
        sales['line_revenue'] = sales[COL_QUANTITY] * sales[COL_SELL_PRICE]
        sales['line_cost'] = sales[COL_QUANTITY] * sales[COL_COST_PRICE]
        grouped = sales.groupby(COL_ITEM_ID).agg({
            COL_QUANTITY: 'sum',
            'line_revenue': 'sum',
            'line_cost': 'sum'
        }).reset_index()
        grouped['total_gp'] = grouped['line_revenue'] - grouped['line_cost']
        grouped.columns = [COL_ITEM_ID, 'total_qty', 'total_revenue', 'total_cost', 'total_gp']
        return grouped

    a_data = aggregate_sales(log_a)
    b_data = aggregate_sales(log_b)

    # Merge with inventory names
    names = inventory_df[[COL_ITEM_ID, COL_ITEM_NAME]].copy()
    a_data = a_data.merge(names, on=COL_ITEM_ID, how='left')
    b_data = b_data.merge(names, on=COL_ITEM_ID, how='left')

    # Outer merge A and B
    merged = a_data.merge(b_data, on=COL_ITEM_ID, how='outer', suffixes=('_a', '_b'))
    merged[COL_ITEM_NAME] = merged['item_name_a'].fillna(merged['item_name_b'])
    merged = merged.fillna(0)

    # Allocate each money column so the rows add up to the period totals.
    for column in ('total_revenue_a', 'total_revenue_b',
                   'total_cost_a', 'total_cost_b',
                   'total_gp_a', 'total_gp_b'):
        merged[column] = allocate_money(merged[column].tolist())

    # Calculate deltas
    merged['delta_qty'] = merged['total_qty_b'] - merged['total_qty_a']
    merged['delta_revenue'] = merged['total_revenue_b'] - merged['total_revenue_a']
    merged['delta_cost'] = merged['total_cost_b'] - merged['total_cost_a']
    merged['delta_gp'] = merged['total_gp_b'] - merged['total_gp_a']
    merged['delta_gp_pct'] = merged.apply(
        lambda row: (row['delta_gp'] / row['total_revenue_a'] * 100) if row['total_revenue_a'] != 0 else 0,
        axis=1
    )

    merged = merged.sort_values('delta_gp', ascending=False, key=abs)
    return merged[[COL_ITEM_ID, COL_ITEM_NAME,
                   'total_qty_a', 'total_qty_b', 'delta_qty',
                   'total_revenue_a', 'total_revenue_b', 'delta_revenue',
                   'total_cost_a', 'total_cost_b', 'delta_cost',
                   'total_gp_a', 'total_gp_b', 'delta_gp', 'delta_gp_pct']]


def build_stocktake_variance_report(inventory_df, log_df, stocktake_df=None):
    """Build data for Stocktake Variance Report.

    Args:
        inventory_df: Inventory DataFrame
        log_df: Transaction log DataFrame
        stocktake_df: DataFrame with columns item_id, counted_quantity, expected_quantity, variance
                      If None, computes expected from current stock and all transactions.

    Returns list of dicts with variance data per item.
    """
    report_data = []
    if inventory_df.empty:
        return report_data

    # If no stocktake provided, compute opening stock from current stock and transaction log
    if stocktake_df is None or stocktake_df.empty:
        expected_remaining = calculate_expected_remaining_series(log_df)

        for _, inv_row in inventory_df.iterrows():
            item_id = inv_row[COL_ITEM_ID]
            item_name = inv_row[COL_ITEM_NAME]
            current_stock = inv_row[COL_QUANTITY]
            cost_price = inv_row[COL_COST_PRICE]

            # Delisted lines hold no stock and are outside the physical count,
            # so they have no variance to report.
            if is_delisted(item_id):
                continue

            # Opening stock = current stock - expected remaining (from transactions)
            expected = current_stock - expected_remaining.get(item_id, 0)
            # Variance is unknown without a stocktake count
            report_data.append({
                'item_id': item_id,
                'item_name': item_name,
                'current_stock': current_stock,
                'expected_quantity': expected,
                'counted_quantity': None,
                'variance': None,
                'variance_pct': None,
                'cost_price': cost_price,
                'variance_value': None,
                'has_stocktake': False
            })
    else:
        # Use provided stocktake data
        stocktake_by_item = stocktake_df.set_index(COL_ITEM_ID).to_dict('index')
        for _, inv_row in inventory_df.iterrows():
            item_id = inv_row[COL_ITEM_ID]
            item_name = inv_row[COL_ITEM_NAME]
            cost_price = inv_row[COL_COST_PRICE]
            current_stock = inv_row[COL_QUANTITY]

            # Delisted lines hold no stock and are outside the physical count,
            # so they have no variance to report.
            if is_delisted(item_id):
                continue

            st = stocktake_by_item.get(item_id)
            if st:
                expected = st.get('expected_quantity', 0)
                counted = st.get('counted_quantity', 0)
                variance = counted - expected
                variance_pct = (variance / expected * 100) if expected != 0 else 0
                variance_value = variance * cost_price
                report_data.append({
                    'item_id': item_id,
                    'item_name': item_name,
                    'current_stock': current_stock,
                    'expected_quantity': expected,
                    'counted_quantity': counted,
                    'variance': variance,
                    'variance_pct': variance_pct,
                    'cost_price': cost_price,
                    'variance_value': variance_value,
                    'has_stocktake': True
                })
            else:
                report_data.append({
                    'item_id': item_id,
                    'item_name': item_name,
                    'current_stock': current_stock,
                    'expected_quantity': None,
                    'counted_quantity': None,
                    'variance': None,
                    'variance_pct': None,
                    'cost_price': cost_price,
                    'variance_value': None,
                    'has_stocktake': False
                })

    # Allocate the counted variances so the item rows add up to the total.
    counted = [row for row in report_data if row['variance_value'] is not None]
    allocated = allocate_money([row['variance_value'] for row in counted])
    for row, value in zip(counted, allocated):
        row['variance_value'] = value

    return report_data


def build_reconciliation_report(
    inventory_df,
    log_df,
    script_dir=None,
    negative_days=7,
):
    """Build data for the inventory reconciliation report.

    Returns a dict with sections:
      - missing_conversion: items without STOCK_CONVERSIONS entry
      - missing_category: items without CATEGORY_MAP entry
      - missing_order_sheet: items not linked on order sheet
      - order_sheet_orphans: order-sheet rows with None that have live stock > 0
      - csv_mismatches: items in inventory not in Items.csv, and vice versa
      - recent_negative: items driven negative in the last N days
    """
    from inventory_sync import (
        find_missing_mappings,
        find_untracked_items_on_order_sheet,
        find_items_csv_inventory_mismatches,
        find_recent_negative_items,
    )

    report = {
        'generated_at': datetime.now().strftime(f'{DATE_FORMAT_DISPLAY} %H:%M:%S'),
        'missing_conversion': [],
        'missing_category': [],
        'missing_order_sheet': [],
        'order_sheet_orphans': [],
        'csv_mismatches': {'in_inventory_not_csv': [], 'in_csv_not_inventory': []},
        'recent_negative': [],
    }

    if inventory_df.empty:
        return report

    missing = find_missing_mappings(inventory_df)
    report['missing_conversion'] = missing['missing_conversion']
    report['missing_category'] = missing['missing_category']
    report['missing_order_sheet'] = missing['missing_order_sheet']
    report['order_sheet_orphans'] = [
        {'supplier': s, 'category': c, 'display_name': d}
        for s, c, d in find_untracked_items_on_order_sheet(inventory_df)
    ]

    if script_dir:
        report['csv_mismatches'] = find_items_csv_inventory_mismatches(inventory_df, script_dir)

    report['recent_negative'] = find_recent_negative_items(inventory_df, log_df, days=negative_days)

    return report


# ---------------------------------------------------------------------------
# Dashboard / PDF insight builders
#
# These are pure functions over DataFrames so the dashboard and the PDF share
# one set of money rules. Every figure is allocated or summed through money.py.
# ---------------------------------------------------------------------------

UPLOAD_OVERDUE_DAYS = 8
UPLOAD_GAP_DAYS = 8
PRICE_ALERT_DAYS = 30
PRICE_ALERT_PCT = 10.0
STOCKTAKE_WARN_DAYS = 28
STOCKTAKE_DUE_DAYS = 35
BACKUP_WARN_DAYS = 3
BACKUP_OVERDUE_DAYS = 7


def _safe_float(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if np.isfinite(number) else default


def _inventory_price_lookups(inventory_df):
    """Return (cost_by_id, sell_by_id, name_by_id) from the inventory."""
    costs, sells, names = {}, {}, {}
    if inventory_df is None or inventory_df.empty or COL_ITEM_ID not in inventory_df.columns:
        return costs, sells, names
    for _, row in inventory_df.iterrows():
        item_id = str(row.get(COL_ITEM_ID, '')).strip()
        if not item_id:
            continue
        costs[item_id] = _safe_float(row.get(COL_COST_PRICE, 0))
        sells[item_id] = _safe_float(row.get(COL_SELL_PRICE, 0))
        names[item_id] = str(row.get(COL_ITEM_NAME, item_id))
    return costs, sells, names


def _activity_value(log_df, actions, price_by_id, price_column=COL_COST_PRICE,
                    exclude_reason=None, only_reason=None,
                    prefer_inventory=False):
    """Value matching log rows at a price, falling back to inventory prices.

    ``prefer_inventory`` values the rows at the current inventory price, which
    is the basis the report's item tables use; leave it False for
    transaction-cost views. Returns an exact penny total via ``sum_money``.
    """
    if log_df is None or log_df.empty or COL_ACTION not in log_df.columns:
        return 0.0
    rows = log_df[log_df[COL_ACTION].isin(actions)]
    if rows.empty:
        return 0.0
    if COL_REASON in rows.columns:
        reasons = rows[COL_REASON].astype(str).str.strip().str.lower()
        if exclude_reason:
            rows = rows[reasons != exclude_reason.strip().lower()]
        if only_reason:
            rows = rows[reasons == only_reason.strip().lower()]
    if rows.empty:
        return 0.0
    values = []
    for _, row in rows.iterrows():
        item_id = str(row.get(COL_ITEM_ID, '')).strip()
        quantity = _safe_float(row.get(COL_QUANTITY, 0))
        inventory_price = _safe_float(price_by_id.get(item_id, 0))
        price = _safe_float(row.get(price_column, 0))
        if prefer_inventory and inventory_price:
            price = inventory_price
        elif price == 0:
            price = inventory_price
        values.append(quantity * price)
    return sum_money(values)


def _period_totals(log_df, inventory_df, member_discount_pct=10):
    """Return the dashboard/PDF figures for one trading period."""
    cost_by_id, sell_by_id, _ = _inventory_price_lookups(inventory_df)
    money = sales_money_by_item(log_df, member_discount_pct)
    if money.empty:
        sales_ex = cost = gp = 0.0
        sales_qty = 0.0
    else:
        sales_ex = sum_money(money['total_revenue'])
        cost = sum_money(money['total_cost'])
        gp = sum_money(money['gp'])
        sales_qty = _safe_float(money['sales_qty'].sum())
    gp_pct = (gp / sales_ex * 100) if sales_ex else 0.0

    wastage_cost = _activity_value(
        log_df, {ACTION_WASTAGE}, cost_by_id, COL_COST_PRICE,
        exclude_reason='Line Clean', prefer_inventory=True)
    line_clean_cost = _activity_value(
        log_df, {ACTION_WASTAGE}, cost_by_id, COL_COST_PRICE,
        only_reason='Line Clean', prefer_inventory=True)
    line_clean_cost = round_money(line_clean_cost + _activity_value(
        log_df, {ACTION_LINE_CLEAN}, cost_by_id, COL_COST_PRICE,
        prefer_inventory=True))
    comp_retail = _activity_value(
        log_df, {ACTION_COMPLIMENTARY}, sell_by_id, COL_SELL_PRICE,
        prefer_inventory=True)
    comp_cost = _activity_value(
        log_df, {ACTION_COMPLIMENTARY}, cost_by_id, COL_COST_PRICE,
        prefer_inventory=True)
    supplier_returns_cost = _activity_value(
        log_df, {ACTION_SUPPLIER_RETURN}, cost_by_id, COL_COST_PRICE,
        prefer_inventory=True)
    delivery_spend = _activity_value(
        log_df, {ACTION_DELIVERY}, cost_by_id, COL_COST_PRICE)

    return {
        'sales_ex_vat': round_money(sales_ex),
        'sales_inc_vat': inc_vat(sales_ex),
        'cost_of_sales': round_money(cost),
        'gp': round_money(gp),
        'gp_pct': gp_pct,
        'sales_qty': sales_qty,
        'wastage_cost': round_money(wastage_cost),
        'line_clean_cost': line_clean_cost,
        'complimentary_retail': round_money(comp_retail),
        'complimentary_cost': round_money(comp_cost),
        'supplier_returns_cost': round_money(supplier_returns_cost),
        'delivery_spend': round_money(delivery_spend),
    }


def _change(current, previous, key, higher_is_good=True):
    """Describe the movement of one metric."""
    if previous is None or current is None:
        return {'delta': None, 'pct': None, 'pp': None,
                'direction': 'flat', 'good': None}
    delta = round_money(current - previous)
    if key == 'gp_pct':
        pct = None
        pp = delta
    else:
        pct = (delta / abs(previous) * 100) if previous else None
        pp = None
    if abs(delta) < 0.005:
        direction = 'flat'
    else:
        direction = 'up' if delta > 0 else 'down'
    good = None
    if direction != 'flat':
        good = (delta > 0) == higher_is_good
    return {'delta': delta, 'pct': pct, 'pp': pp,
            'direction': direction, 'good': good}


def _filter_fully_within(log_df, start, end):
    """Keep rows whose trading period (or timestamp) sits inside the window.

    A catch-up upload can span several weeks. Counting the whole upload in a
    comparison window that only touches one of its days would distort the
    previous-period figures, so partial overlaps are excluded rather than
    silently prorated.
    """
    if log_df is None or log_df.empty:
        return log_df
    start_ts = pd.Timestamp(start).normalize()
    end_ts = (pd.Timestamp(end).normalize()
              + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
    keep = []
    for index, row in log_df.iterrows():
        period = _parse_period_range(row.get(COL_DATE_RANGE))
        if period:
            period_start, period_end = period
            if (pd.Timestamp(period_start).normalize() >= start_ts
                    and pd.Timestamp(period_end).normalize() <= end_ts.normalize()):
                keep.append(index)
            continue
        timestamp = pd.to_datetime(row.get(COL_TIMESTAMP), errors='coerce')
        if pd.notna(timestamp) and start_ts <= timestamp <= end_ts:
            keep.append(index)
    return log_df.loc[keep]


def build_previous_period_log(full_log_df, start_date, end_date, current_log=None):
    """Return the equal-length period immediately before ``start_date``.

    Weekly uploads can straddle a boundary because ``filter_log_by_date``
    includes any row whose ``date_range`` overlaps. Rows already present in
    ``current_log`` are removed from the previous period so the same sale is
    never counted twice.
    """
    if full_log_df is None or start_date is None or end_date is None:
        return None, None, None
    start = pd.Timestamp(start_date).normalize()
    end = pd.Timestamp(end_date).normalize()
    if end < start:
        start, end = end, start
    span_days = (end - start).days + 1
    previous_end = start - pd.Timedelta(days=1)
    previous_start = previous_end - pd.Timedelta(days=span_days - 1)
    previous_log = filter_log_by_date(
        full_log_df, previous_start.to_pydatetime(),
        previous_end.to_pydatetime())
    # Exclude upload periods that only partly fall inside the window. A
    # multi-week catch-up upload otherwise lands wholly in one comparison.
    previous_log = _filter_fully_within(
        previous_log, previous_start, previous_end)
    if current_log is not None and not current_log.empty:
        previous_log = previous_log.drop(index=current_log.index, errors='ignore')
    return (previous_log, previous_start.to_pydatetime(),
            previous_end.to_pydatetime())


def build_period_comparison_summary(inventory_df, current_log, previous_log,
                                    member_discount_pct=10,
                                    current_label='', previous_label=''):
    """Return current/previous/delta figures for the dashboard and PDF."""
    current = _period_totals(current_log, inventory_df, member_discount_pct)
    previous = (_period_totals(previous_log, inventory_df, member_discount_pct)
                if previous_log is not None else None)

    # Stock holding is inherently current-only; no invented prior valuation.
    stock_holding = 0.0
    if inventory_df is not None and not inventory_df.empty:
        qty = pd.to_numeric(
            inventory_df.get(COL_QUANTITY, 0), errors='coerce').fillna(0)
        cost = pd.to_numeric(
            inventory_df.get(COL_COST_PRICE, 0), errors='coerce').fillna(0)
        active = ~inventory_df[COL_ITEM_ID].astype(str).map(is_delisted)
        stock_holding = sum_money(qty[active] * cost[active])
    current['stock_holding'] = round_money(stock_holding)

    higher_is_good = {
        'sales_ex_vat': True,
        'sales_inc_vat': True,
        'cost_of_sales': False,
        'gp': True,
        'gp_pct': True,
        'sales_qty': True,
        'wastage_cost': False,
        'line_clean_cost': False,
        'complimentary_retail': False,
        'complimentary_cost': False,
        'supplier_returns_cost': False,
        'delivery_spend': True,
        'stock_holding': True,
    }
    changes = {}
    for key, good_when_up in higher_is_good.items():
        prev_value = previous.get(key) if previous is not None else None
        changes[key] = _change(current.get(key, 0.0), prev_value, key,
                               higher_is_good=good_when_up)

    return {
        'current': current,
        'previous': previous,
        'changes': changes,
        'labels': {'current': current_label, 'previous': previous_label},
    }


def _parse_period_range(value):
    """Parse a date_range string into (start, end) datetimes, or None."""
    if not isinstance(value, str):
        return None
    match = re.search(
        r'(\d{2}[/-]\d{2}[/-]\d{4})\s+-\s+(\d{2}[/-]\d{2}[/-]\d{4})', value)
    if not match:
        return None
    try:
        return parse_display_date(match.group(1)), parse_display_date(match.group(2))
    except ValueError:
        return None


def build_upload_period_health(log_df, today=None):
    """Summarise sales-upload coverage: latest period, gaps and overlaps."""
    today = today or datetime.now()
    result = {
        'periods': [],
        'latest_period': None,
        'latest_period_end': None,
        'days_since_period_end': None,
        'last_upload_timestamp': None,
        'overlaps': [],
        'latest_overlaps': [],
        'largest_gap_days': 0,
        'status': 'none',
    }
    if log_df is None or log_df.empty:
        return result
    sales = log_df[log_df[COL_ACTION].isin([ACTION_SALES, ACTION_SALES_ONE_UNIT])]
    if sales.empty:
        return result

    raw_periods = set()
    if COL_DATE_RANGE in sales.columns:
        for value in sales[COL_DATE_RANGE].dropna().astype(str):
            parsed = _parse_period_range(value)
            if parsed:
                raw_periods.add((parsed[0], parsed[1], value.strip()))
    periods = sorted(raw_periods, key=lambda item: (item[0], item[1]))
    result['periods'] = [
        {'period': label, 'start': start, 'end': end}
        for start, end, label in periods
    ]

    if periods:
        latest = periods[-1]
        result['latest_period'] = latest[2]
        result['latest_period_end'] = latest[1]
        result['days_since_period_end'] = (today.date() - latest[1].date()).days
        for earlier in periods[:-1]:
            if latest[0] <= earlier[1] and latest[1] >= earlier[0]:
                result['latest_overlaps'].append({
                    'first': earlier[2],
                    'second': latest[2],
                })

    for index in range(1, len(periods)):
        previous_end = periods[index - 1][1]
        current_start = periods[index][0]
        if current_start <= previous_end:
            result['overlaps'].append({
                'first': periods[index - 1][2],
                'second': periods[index][2],
            })
        else:
            gap = (current_start.date() - previous_end.date()).days - 1
            result['largest_gap_days'] = max(result['largest_gap_days'], gap)

    if COL_TIMESTAMP in sales.columns and not sales.empty:
        timestamps = pd.to_datetime(sales[COL_TIMESTAMP], errors='coerce').dropna()
        if not timestamps.empty:
            result['last_upload_timestamp'] = timestamps.max().to_pydatetime()

    if result['days_since_period_end'] is not None and \
            result['days_since_period_end'] > UPLOAD_OVERDUE_DAYS:
        result['status'] = 'overdue'
    elif result['latest_overlaps'] or result['largest_gap_days'] > UPLOAD_GAP_DAYS:
        result['status'] = 'warning'
    elif periods:
        result['status'] = 'ok'
    return result


def build_price_change_alerts(inventory_df, log_df, days=PRICE_ALERT_DAYS,
                              threshold_pct=PRICE_ALERT_PCT, today=None,
                              limit=3):
    """Find recent delivery cost increases above ``threshold_pct``.

    Each item's deliveries are compared with its previous distinct unit cost,
    so a split delivery at the same price does not create a false alert.
    """
    if log_df is None or log_df.empty or COL_ACTION not in log_df.columns:
        return []
    today = today or datetime.now()
    deliveries = log_df[log_df[COL_ACTION] == ACTION_DELIVERY].copy()
    if deliveries.empty:
        return []
    deliveries['_ts'] = pd.to_datetime(deliveries[COL_TIMESTAMP], errors='coerce')
    deliveries = deliveries.dropna(subset=['_ts'])
    if days is not None:
        cutoff = pd.Timestamp(today) - pd.Timedelta(days=days)
        deliveries = deliveries[deliveries['_ts'] >= cutoff]
    if deliveries.empty:
        return []

    _, _, name_by_id = _inventory_price_lookups(inventory_df)
    alerts = []
    for item_id, rows in deliveries.sort_values('_ts').groupby(COL_ITEM_ID):
        rows = rows.drop_duplicates(subset=['_ts', COL_COST_PRICE])
        previous_cost = None
        for _, row in rows.iterrows():
            cost = _safe_float(row.get(COL_COST_PRICE, 0))
            if cost <= 0:
                continue
            if previous_cost is not None and previous_cost > 0:
                change_pct = (cost - previous_cost) / previous_cost * 100
                if change_pct >= threshold_pct:
                    alerts.append({
                        'item_id': str(item_id),
                        'item_name': name_by_id.get(str(item_id), str(item_id)),
                        'supplier': str(row.get(COL_SUPPLIER, '') or 'Unassigned'),
                        'date': row['_ts'].to_pydatetime(),
                        'old_cost': round_money(previous_cost),
                        'new_cost': round_money(cost),
                        'change_pct': change_pct,
                        'target': 'price_history',
                    })
            previous_cost = cost

    alerts.sort(key=lambda alert: (alert['change_pct'], alert['date']),
                reverse=True)
    return alerts[:limit] if limit is not None else alerts


def build_supplier_spend_summary(log_df):
    """Return delivery spend by supplier, ex VAT, with exact shares."""
    rows = []
    if log_df is None or log_df.empty or COL_ACTION not in log_df.columns:
        return rows
    deliveries = log_df[log_df[COL_ACTION] == ACTION_DELIVERY].copy()
    if deliveries.empty:
        return rows
    deliveries[COL_SUPPLIER] = deliveries.get(
        COL_SUPPLIER, '').fillna('').astype(str).str.strip()
    deliveries.loc[deliveries[COL_SUPPLIER] == '', COL_SUPPLIER] = 'Unassigned'
    values = []
    grouped = []
    for supplier, group in deliveries.groupby(COL_SUPPLIER):
        spend = sum_money(
            _safe_float(row.get(COL_QUANTITY, 0)) *
            _safe_float(row.get(COL_COST_PRICE, 0))
            for _, row in group.iterrows())
        values.append(spend)
        grouped.append((supplier, group, spend))
    allocated = allocate_money(values)
    total = sum_money(allocated)
    for (supplier, group, _), spend in zip(grouped, allocated):
        rows.append({
            'supplier': supplier,
            'lines': int(len(group)),
            'units': _safe_float(group[COL_QUANTITY].sum()),
            'spend_ex_vat': spend,
            'share_pct': (spend / total * 100) if total else 0.0,
        })
    rows.sort(key=lambda row: row['spend_ex_vat'], reverse=True)
    return rows


def build_reason_value_summary(log_df, inventory_df, kind='wastage',
                               value_basis='cost'):
    """Group wastage, line-clean or complimentary activity by reason.

    ``kind`` is ``wastage``, ``line_clean`` or ``comp``. Values are allocated
    to the penny so the reason rows add up to the section total.
    """
    cost_by_id, sell_by_id, _ = _inventory_price_lookups(inventory_df)
    if kind == 'comp':
        actions = {ACTION_COMPLIMENTARY}
        price_map = sell_by_id if value_basis == 'retail' else cost_by_id
        price_column = COL_SELL_PRICE if value_basis == 'retail' else COL_COST_PRICE
        exclude_reason = None
        only_reason = None
    elif kind == 'line_clean':
        actions = {ACTION_LINE_CLEAN}
        price_map = cost_by_id
        price_column = COL_COST_PRICE
        exclude_reason = None
        only_reason = None
    else:
        actions = {ACTION_WASTAGE}
        price_map = cost_by_id
        price_column = COL_COST_PRICE
        exclude_reason = 'Line Clean'
        only_reason = None

    if log_df is None or log_df.empty or COL_ACTION not in log_df.columns:
        return []
    rows = log_df[log_df[COL_ACTION].isin(actions)]
    if kind == 'wastage' and COL_REASON in rows.columns:
        # Line cleaning is reported separately, never as wastage.
        rows = rows[rows[COL_REASON].astype(str).str.strip().str.lower()
                    != 'line clean']
    if kind == 'line_clean':
        # Legacy line-clean rows may be recorded as Wastage/Line Clean.
        legacy = log_df[log_df[COL_ACTION] == ACTION_WASTAGE]
        if COL_REASON in legacy.columns:
            legacy = legacy[legacy[COL_REASON].astype(str).str.strip().str.lower()
                            == 'line clean']
        rows = pd.concat([rows, legacy], ignore_index=True)
    if rows.empty:
        return []
    reasons = rows.get(COL_REASON, pd.Series([''] * len(rows), index=rows.index))
    rows = rows.copy()
    rows['_reason'] = reasons.fillna('').astype(str).str.strip()
    rows.loc[rows['_reason'] == '', '_reason'] = 'Unspecified'

    grouped = []
    values = []
    for reason, group in rows.groupby('_reason'):
        value = _activity_value(
            group, set(group[COL_ACTION].unique()), price_map, price_column,
            exclude_reason=exclude_reason if kind == 'wastage' else None,
            only_reason=only_reason, prefer_inventory=True)
        values.append(value)
        grouped.append((reason, group, value))
    allocated = allocate_money(values)
    total = sum_money(allocated)
    result = []
    for (reason, group, _), value in zip(grouped, allocated):
        result.append({
            'reason': reason,
            'quantity': _safe_float(group[COL_QUANTITY].sum()),
            'value': value,
            'share_pct': (value / total * 100) if total else 0.0,
        })
    result.sort(key=lambda row: row['value'], reverse=True)
    return result


def build_value_movement_bridge(report_data, total_stock_value=None):
    """Build the value bridge from opening stock to closing stock.

    The bridge deliberately exposes a balancing line: GP uses transaction cost
    while stock is valued at current cost, so the two can differ by a cost
    revaluation. Hiding that difference would make the report lie.
    """
    if not report_data:
        return {'rows': [], 'closing': 0.0, 'difference': 0.0}
    opening = sum_money(
        _safe_float(item.get('opening_stock', 0)) *
        _safe_float(item.get('cost_price', 0)) for item in report_data)
    deliveries = sum_money(
        _safe_float(item.get('delivery_qty', 0)) *
        _safe_float(item.get('cost_price', 0)) for item in report_data)
    cost_of_sales = sum_money(
        _safe_float(item.get('sales_cost', 0)) for item in report_data)
    wastage = sum_money(
        _safe_float(item.get('wastage_qty', 0)) *
        _safe_float(item.get('cost_price', 0)) for item in report_data)
    line_clean = sum_money(
        _safe_float(item.get('line_clean_qty', 0)) *
        _safe_float(item.get('cost_price', 0)) for item in report_data)
    complimentary = sum_money(
        _safe_float(item.get('complimentary_qty', 0)) *
        _safe_float(item.get('cost_price', 0)) for item in report_data)
    supplier_returns = sum_money(
        _safe_float(item.get('supplier_return_qty', 0)) *
        _safe_float(item.get('cost_price', 0)) for item in report_data)
    variance_values = [
        _safe_float(item.get('surplus_value'))
        for item in report_data if item.get('surplus_value') is not None]
    variance = sum_money(variance_values) if variance_values else 0.0
    closing = round_money(
        total_stock_value if total_stock_value is not None
        else sum_money(_safe_float(item.get('stock_value', 0))
                       for item in report_data))
    expected_closing = round_money(
        opening + deliveries - cost_of_sales - wastage - line_clean
        - complimentary - supplier_returns + variance)
    difference = round_money(closing - expected_closing)
    rows = [
        ('Opening stock at cost', opening),
        ('Plus deliveries at cost', deliveries),
        ('Less cost of sales', -cost_of_sales),
        ('Less wastage at cost', -wastage),
        ('Less line cleaning at cost', -line_clean),
        ('Less complimentary at cost', -complimentary),
        ('Less supplier returns at cost', -supplier_returns),
        ('Stocktake variance', variance),
        ('Expected closing stock', expected_closing),
        ('Closing stock at current cost', closing),
        ('Difference (cost revaluation)', difference),
    ]
    return {
        'rows': [{'label': label, 'value': round_money(value)}
                 for label, value in rows],
        'closing': closing,
        'expected_closing': expected_closing,
        'difference': difference,
    }


def build_report_reconciliation_notes(inventory_df, log_df, report_data,
                                      upload_health=None):
    """Build data-driven notes explaining non-sales and reconciliation lines."""
    notes = []
    if report_data:
        zero_cost = [
            item for item in report_data
            if _safe_float(item.get('total_sales_value', 0)) > 0
            and _safe_float(item.get('sales_cost', 0)) == 0]
        if zero_cost:
            notes.append({
                'title': 'Zero-cost sales lines',
                'detail': (f"{len(zero_cost)} item{'s' if len(zero_cost) != 1 else ''} {'carry' if len(zero_cost) != 1 else 'carries'} revenue with no "
                           "recorded cost, so their GP is 100%."),
            })

        delisted = [item for item in report_data
                    if item.get('is_delisted') or item.get('delisted_stock_value')]
        if delisted:
            value = sum_money(_safe_float(item.get('delisted_stock_value', 0))
                              for item in delisted)
            notes.append({
                'title': 'Delisted items',
                'detail': (f"{len(delisted)} delisted line{'s' if len(delisted) != 1 else ''} {'are' if len(delisted) != 1 else 'is'} excluded from "
                           f"active stock value (£{value:,.2f} held separately)."),
            })

        negative = [item for item in report_data
                    if _safe_float(item.get('current_stock', 0)) < 0]
        if negative:
            notes.append({
                'title': 'Negative stock',
                'detail': (f"{len(negative)} item{'s' if len(negative) != 1 else ''} {'are' if len(negative) != 1 else 'is'} negative at the report "
                           "date; check recent deliveries and sales."),
            })

    if log_df is not None and not log_df.empty and COL_ACTION in log_df.columns:
        deliveries = log_df[log_df[COL_ACTION] == ACTION_DELIVERY]
        if COL_SUPPLIER in deliveries.columns:
            unnamed = deliveries[
                deliveries[COL_SUPPLIER].fillna('').astype(str).str.strip() == '']
            if not unnamed.empty:
                spend = sum_money(
                    _safe_float(row.get(COL_QUANTITY, 0)) *
                    _safe_float(row.get(COL_COST_PRICE, 0))
                    for _, row in unnamed.iterrows())
                notes.append({
                    'title': 'Unassigned deliveries',
                    'detail': (f"{len(unnamed)} delivery line{'s' if len(unnamed) != 1 else ''} {'have' if len(unnamed) != 1 else 'has'} no supplier "
                               f"(£{spend:,.2f} ex VAT)."),
                })

    if upload_health:
        if upload_health.get('overlaps'):
            notes.append({
                'title': 'Overlapping sales uploads',
                'detail': (f"{len(upload_health['overlaps'])} overlapping sales "
                           "period(s) were found. Check the upload history before "
                           "relying on the period total."),
            })
        if upload_health.get('largest_gap_days', 0) > UPLOAD_GAP_DAYS:
            notes.append({
                'title': 'Sales coverage gap',
                'detail': (f"The largest gap between sales upload periods is "
                           f"{upload_health['largest_gap_days']} days."),
            })

    notes.append({
        'title': 'Cost basis',
        'detail': ('Sales, costs and stock are reported ex VAT at 20%. GP uses '
                   'transaction cost; closing stock uses current cost, so the '
                   'value bridge may show a cost-revaluation difference.'),
    })
    return notes


def build_executive_narrative(comparison, division_totals=None,
                              supplier_spend=None, vat_position=None):
    """Create short, plain-language bullets for the PDF summary page."""
    bullets = []
    if comparison:
        current = comparison.get('current') or {}
        changes = comparison.get('changes') or {}
        sales_change = changes.get('sales_ex_vat') or {}
        if sales_change.get('pct') is not None:
            direction = 'up' if sales_change['direction'] == 'up' else 'down'
            bullets.append(
                f"Sales are {direction} {abs(sales_change['pct']):.1f}% "
                f"against the previous period (£{current.get('sales_ex_vat', 0):,.2f} ex VAT).")
        gp_change = changes.get('gp_pct') or {}
        if gp_change.get('pp') is not None:
            direction = 'up' if gp_change['direction'] == 'up' else 'down'
            bullets.append(
                f"GP margin is {direction} {abs(gp_change['pp']):.1f} percentage "
                f"points at {current.get('gp_pct', 0):.1f}%.")
        waste_change = changes.get('wastage_cost') or {}
        if waste_change.get('delta') is not None:
            direction = 'higher' if waste_change['direction'] == 'up' else 'lower'
            bullets.append(
                f"Wastage is £{current.get('wastage_cost', 0):,.2f}, "
                f"{direction} than the previous period.")
    if division_totals:
        top_division = max(
            division_totals.items(),
            key=lambda item: item[1].get('sales_value', 0) or 0,
            default=(None, None))
        if top_division[0]:
            bullets.append(
                f"{top_division[0]} is the largest division at "
                f"£{top_division[1].get('sales_value', 0):,.2f} ex VAT.")
    if supplier_spend:
        top = supplier_spend[0]
        bullets.append(
            f"{top['supplier']} is the largest supplier at "
            f"£{top['spend_ex_vat']:,.2f} ex VAT.")
    if vat_position:
        net = vat_position.get('net_vat', 0)
        position = 'payable' if net >= 0 else 'repayable'
        bullets.append(
            f"Net VAT is £{abs(net):,.2f} {position} for the period (estimate only).")
    return bullets[:6]


def find_overlapping_upload_periods(start_date, end_date, log_df):
    """Return existing sales periods that overlap a proposed upload period.

    Used by the sales-upload guard: a re-exported file has a different hash but
    can still double-count the same trading week.
    """
    if start_date is None or end_date is None:
        return []
    new_start = pd.Timestamp(start_date).normalize()
    new_end = pd.Timestamp(end_date).normalize()
    if new_end < new_start:
        new_start, new_end = new_end, new_start
    overlaps = []
    for period in build_upload_period_health(log_df).get('periods', []):
        if new_start <= pd.Timestamp(period['end']).normalize() and \
                new_end >= pd.Timestamp(period['start']).normalize():
            overlaps.append(period['period'])
    return overlaps


def build_division_stock_movement(report_data, target_revaluation=None):
    """Aggregate stock movement by division for the directors' PDF.

    Values use current cost for opening/closing/wastage and transaction cost
    for cost of sales, the same basis as the value bridge. Each money column is
    allocated to the penny so the division rows add up to the total row.
    """
    if not report_data:
        return {'rows': [], 'total': {}}
    grouped = defaultdict(lambda: {
        'opening': 0.0, 'deliveries': 0.0, 'cogs': 0.0,
        'shrinkage': 0.0, 'returns': 0.0, 'closing': 0.0,
    })
    for item in report_data:
        division = str(item.get('division', 'Unknown') or 'Unknown')
        cost = _safe_float(item.get('cost_price', 0))
        bucket = grouped[division]
        bucket['opening'] += _safe_float(item.get('opening_stock', 0)) * cost
        bucket['deliveries'] += _safe_float(item.get('delivery_qty', 0)) * cost
        bucket['cogs'] += _safe_float(item.get('sales_cost', 0))
        bucket['shrinkage'] += (
            _safe_float(item.get('wastage_qty', 0))
            + _safe_float(item.get('line_clean_qty', 0))
            + _safe_float(item.get('complimentary_qty', 0))) * cost
        bucket['returns'] += _safe_float(item.get('supplier_return_qty', 0)) * cost
        bucket['closing'] += _safe_float(item.get('stock_value', 0))

    divisions = list(grouped)
    for key in ('opening', 'deliveries', 'cogs', 'shrinkage', 'returns', 'closing'):
        allocated = allocate_money([grouped[d][key] for d in divisions])
        for division, value in zip(divisions, allocated):
            grouped[division][key] = value

    rows = []
    for division in divisions:
        bucket = grouped[division]
        rows.append({
            'division': division,
            'opening': round_money(bucket['opening']),
            'deliveries': round_money(bucket['deliveries']),
            'cogs': round_money(bucket['cogs']),
            'shrinkage': round_money(bucket['shrinkage']),
            'returns': round_money(bucket['returns']),
            'closing': round_money(bucket['closing']),
            'revaluation': round_money(
                bucket['closing']
                - (bucket['opening'] + bucket['deliveries']
                   - bucket['cogs'] - bucket['shrinkage']
                   - bucket['returns'])),
        })
    rows.sort(key=lambda row: row['closing'], reverse=True)
    if target_revaluation is not None and rows:
        current_total = sum_money(row['revaluation'] for row in rows)
        residual = round_money(target_revaluation - current_total)
        if residual:
            index = max(range(len(rows)),
                        key=lambda i: abs(rows[i]['revaluation']))
            rows[index]['revaluation'] = round_money(
                rows[index]['revaluation'] + residual)
    total = {
        key: sum_money(row[key] for row in rows)
        for key in ('opening', 'deliveries', 'cogs', 'shrinkage',
                    'returns', 'closing', 'revaluation')
    }
    return {'rows': rows, 'total': total}


def build_stock_exceptions(stocktake_data, report_data, limit=10):
    """Return the largest stocktake variances and negative-stock items."""
    division_by_id = {
        str(item.get('item_id', '')): item.get('division', 'Unknown')
        for item in (report_data or [])
    }
    variances = []
    for row in (stocktake_data or []):
        if not row.get('has_stocktake', False):
            continue
        variances.append({
            'item_id': row.get('item_id', ''),
            'item_name': row.get('item_name', ''),
            'division': division_by_id.get(str(row.get('item_id', '')), 'Unknown'),
            'expected': _safe_float(row.get('expected_quantity', 0)),
            'counted': _safe_float(row.get('counted_quantity', 0)),
            'variance': _safe_float(row.get('variance', 0)),
            'variance_value': _safe_float(row.get('variance_value', 0)),
        })
    variances.sort(key=lambda row: abs(row['variance_value']), reverse=True)

    negative = []
    for item in (report_data or []):
        current_stock = _safe_float(item.get('current_stock', 0))
        if current_stock < 0:
            negative.append({
                'item_id': item.get('item_id', ''),
                'item_name': item.get('item_name', ''),
                'division': item.get('division', 'Unknown'),
                'current_stock': current_stock,
                'stock_value': _safe_float(item.get('stock_value', 0)),
            })
    negative.sort(key=lambda row: row['current_stock'])
    return {
        'variances': variances[:limit],
        'negative': negative[:limit],
    }
