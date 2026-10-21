"""
Bar Stock Reports - Data processing functions for report generation.

All functions accept inventory_df, log_df, and optional date filtering.
Returns raw data structures (dicts, DataFrames) for UI rendering.
"""

import json
import os
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
from sales_mapping import is_hidden_from_stock_view
from supplier_mapping import get_supplier, get_supplier_order, supplier_rank
from order_sheet_layout import get_order_sheet_layout
from conversions import parse_display_date, DATE_FORMAT_DISPLAY


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
            qty = df.loc[has_actual, COL_QUANTITY]
            member_qty = df.loc[has_actual, COL_MEMBER_QTY].fillna(0)
            non_member_qty = df.loc[has_actual, COL_NON_MEMBER_QTY].fillna(0)
            known_total = member_qty + non_member_qty

            # Any quantity not explicitly split is treated as non-member.
            remaining = np.maximum(qty - known_total, 0)
            member_qty_est = member_qty
            non_member_qty_est = non_member_qty + remaining

            df.loc[has_actual, "member_revenue"] = (
                member_qty_est * df.loc[has_actual, COL_SELL_PRICE] * member_mult
            )
            df.loc[has_actual, "non_member_revenue"] = (
                non_member_qty_est * df.loc[has_actual, COL_SELL_PRICE]
            )

            # Scale so member + non-member revenue equals total revenue for every transaction.
            actual_total = df.loc[has_actual, COL_QUANTITY] * df.loc[has_actual, COL_SELL_PRICE]
            split_total = df.loc[has_actual, "member_revenue"] + df.loc[has_actual, "non_member_revenue"]
            revenue_scale = np.where(split_total > 0, actual_total / split_total, 1.0)
            df.loc[has_actual, "member_revenue"] *= revenue_scale
            df.loc[has_actual, "non_member_revenue"] *= revenue_scale

            cost = df.loc[has_actual, "total_cost"]
            df.loc[has_actual, "member_cost"] = np.where(
                qty > 0,
                cost * (member_qty_est / qty),
                0.0,
            )
            df.loc[has_actual, "non_member_cost"] = cost - df.loc[has_actual, "member_cost"]

    return df


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


def calculate_expected_remaining_series(log_df):
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

    # Compute parent adjustments dynamically from child sales instead of relying on log entries
    from sales_mapping import SALES_TO_PARENT
    computed_parent_adj = {}
    for child_id, mapping in SALES_TO_PARENT.items():
        if not mapping:
            continue
        parent_items, factors, _ = mapping[:3]
        child_log = effective_log[effective_log[COL_ITEM_ID].str.lower() == child_id]
        sales_qty = child_log[child_log[COL_ACTION].isin([ACTION_SALES, ACTION_SALES_ONE_UNIT])][COL_QUANTITY].sum()
        comp_qty = child_log[child_log[COL_ACTION] == ACTION_COMPLIMENTARY][COL_QUANTITY].sum()
        total = sales_qty + comp_qty
        if isinstance(parent_items, list):
            for p_id, factor in zip(parent_items, factors):
                computed_parent_adj[p_id.lower()] = computed_parent_adj.get(p_id.lower(), 0) + total * factor
        else:
            computed_parent_adj[parent_items.lower()] = computed_parent_adj.get(parent_items.lower(), 0) + total * factors

    # Build a parent_adj Series aligned with the pivot index (case-insensitive)
    all_item_ids = list(pivot.index)
    parent_adj = pd.Series({item_id: computed_parent_adj.get(item_id.lower(), 0) for item_id in all_item_ids})
    parent_adj.index.name = COL_ITEM_ID

    result = (import_qty + delivery + baseline + tab_cancelled + stocktake_adjustment
              - sales - wastage - comp - open_tab - supplier_return - parent_adj)

    # Replace any remaining negative expected remaining with the baseline anchor
    # when a baseline exists, so current_stock - expected_remaining never invents
    # a negative opening stock.
    if not baseline_quantities.empty:
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
    """Load division mapping from Items.csv."""
    division_mapping = {}
    items_csv_path = os.path.join(script_dir, 'Items.csv')
    if os.path.exists(items_csv_path):
        try:
            items_df = pd.read_csv(items_csv_path, compression=None)
            if 'Name' in items_df.columns and 'Division' in items_df.columns:
                raw_mapping = dict(zip(items_df['Name'].str.lower(), items_df['Division']))
                division_mapping = {k: normalize_division_name(v) for k, v in raw_mapping.items()}
        except Exception:
            pass
    return division_mapping


def build_gp_report_data(log_df, member_discount_pct=10):
    """Build data for Gross Profit Report.

    Returns DataFrame with columns:
    Total Cost, Total Revenue, GP, GP%, Member Revenue, Non-Member Revenue,
    Member GP, Member GP%, Non-Member GP, Non-Member GP%
    """
    if log_df.empty:
        return pd.DataFrame(columns=['Total Cost', 'Total Revenue', 'GP', 'GP%',
                                     'Member Revenue', 'Non-Member Revenue',
                                     'Member GP', 'Member GP%',
                                     'Non-Member GP', 'Non-Member GP%'])

    # Gross Profit Report should only consider Sales data
    sales_df = log_df[log_df[COL_ACTION] .isin([ACTION_SALES, ACTION_SALES_ONE_UNIT])].copy()
    if sales_df.empty:
        return pd.DataFrame(columns=['Total Cost', 'Total Revenue', 'GP', 'GP%',
                                     'Member Revenue', 'Non-Member Revenue',
                                     'Member GP', 'Member GP%',
                                     'Non-Member GP', 'Non-Member GP%'])

    sales_df = _split_sales_revenue_and_cost(sales_df, member_discount_pct)

    # Aggregate per item
    item_summary = sales_df.groupby(COL_ITEM_ID).agg({
        COL_QUANTITY: 'sum',
        'total_cost': 'sum',
        'total_revenue': 'sum',
        COL_COST_PRICE: 'mean',
        COL_SELL_PRICE: 'mean',
        'member_revenue': 'sum',
        'non_member_revenue': 'sum',
        'member_cost': 'sum',
        'non_member_cost': 'sum'
    }).rename(columns={COL_QUANTITY: 'sales_qty', 'total_cost': 'sales_cost', 'total_revenue': 'sales_revenue'})

    item_summary['member_gp'] = item_summary['member_revenue'] - item_summary['member_cost']
    item_summary['non_member_gp'] = item_summary['non_member_revenue'] - item_summary['non_member_cost']
    item_summary['total_revenue'] = item_summary['member_revenue'] + item_summary['non_member_revenue']
    item_summary['gp'] = item_summary['member_gp'] + item_summary['non_member_gp']

    item_summary['member_gp_pct'] = np.where(
        item_summary['member_revenue'] > 0,
        item_summary['member_gp'] / item_summary['member_revenue'] * 100,
        0.0
    )
    item_summary['non_member_gp_pct'] = np.where(
        item_summary['non_member_revenue'] > 0,
        item_summary['non_member_gp'] / item_summary['non_member_revenue'] * 100,
        0.0
    )
    item_summary['gp_pct'] = np.where(
        item_summary['total_revenue'] > 0,
        item_summary['gp'] / item_summary['total_revenue'] * 100,
        0.0
    )

    result = item_summary[['sales_cost', 'total_revenue', 'gp', 'gp_pct',
                           'member_revenue', 'non_member_revenue',
                           'member_gp', 'member_gp_pct',
                           'non_member_gp', 'non_member_gp_pct']].copy()
    result.columns = ['Total Cost', 'Total Revenue', 'GP', 'GP%',
                      'Member Revenue', 'Non-Member Revenue',
                      'Member GP', 'Member GP%',
                      'Non-Member GP', 'Non-Member GP%']
    return result.round(2)


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

    return report_data


def build_division_report_data(inventory_df, log_df, member_discount_pct=10):
    """Build data for Division Report.

    Returns DataFrame with columns: Division, Total Quantity, Total Revenue,
    Total Cost, GP, GP%, Member Revenue, Member GP, Member GP%
    """
    if log_df.empty:
        return pd.DataFrame(columns=['Division', 'Total Quantity', 'Total Revenue',
                                     'Total Cost', 'GP', 'GP%', 'Member Revenue',
                                     'Member GP', 'Member GP%'])

    division_mapping = get_division_mapping(os.path.dirname(os.path.abspath(__file__)))

    sales_log = log_df[log_df[COL_ACTION].str.contains(ACTION_SALES, na=False)]
    if sales_log.empty:
        return pd.DataFrame(columns=['Division', 'Total Quantity', 'Total Revenue',
                                     'Total Cost', 'GP', 'GP%', 'Member Revenue',
                                     'Member GP', 'Member GP%'])

    # Prefer the inventory division column; fall back to Items.csv name mapping only when empty.
    if COL_DIVISION in inventory_df.columns:
        sales_with_names = sales_log.merge(
            inventory_df[[COL_ITEM_ID, COL_ITEM_NAME, COL_DIVISION]], on=COL_ITEM_ID, how='left'
        )

        def _resolve_division(row):
            div = row[COL_DIVISION]
            if pd.notna(div) and str(div).strip():
                return normalize_division_name(str(div))
            return normalize_division_name(division_mapping.get(str(row[COL_ITEM_NAME]).lower(), 'Unknown'))

        sales_with_names['Division'] = sales_with_names.apply(_resolve_division, axis=1)
    else:
        sales_with_names = sales_log.merge(
            inventory_df[[COL_ITEM_ID, COL_ITEM_NAME]], on=COL_ITEM_ID, how='left'
        )
        sales_with_names['Division'] = sales_with_names[COL_ITEM_NAME].apply(
            lambda x: normalize_division_name(division_mapping.get(str(x).lower(), 'Unknown'))
        )

    sales_with_names = _split_sales_revenue_and_cost(sales_with_names, member_discount_pct)

    division_summary = sales_with_names.groupby('Division').agg({
        COL_QUANTITY: 'sum',
        'member_revenue': 'sum',
        'non_member_revenue': 'sum',
        'member_cost': 'sum',
        'non_member_cost': 'sum',
        'total_cost': 'sum'
    }).reset_index()
    division_summary.columns = ['Division', 'Total Quantity', 'Member Revenue', 'Non-Member Revenue',
                                'Member Cost', 'Non-Member Cost', 'Total Cost']
    division_summary['Total Revenue'] = division_summary['Member Revenue'] + division_summary['Non-Member Revenue']

    division_summary['GP'] = division_summary['Total Revenue'] - division_summary['Total Cost']
    division_summary['Member GP'] = division_summary['Member Revenue'] - division_summary['Member Cost']
    division_summary['Non-Member GP'] = division_summary['Non-Member Revenue'] - division_summary['Non-Member Cost']

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
    result = division_summary[['Division', 'Total Quantity', 'Total Revenue', 'Total Cost', 'GP', 'GP%',
                               'Member Revenue', 'Member GP', 'Member GP%',
                               'Non-Member Revenue', 'Non-Member GP', 'Non-Member GP%']].copy()
    return result.round(2)


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
    db_path = os.path.expanduser('~/Library/Application Support/BarStockManagement/barstock.db')
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
    """
    db_path = os.path.expanduser('~/Library/Application Support/BarStockManagement/barstock.db')
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, snapshot_json FROM baseline_resets
            ORDER BY timestamp DESC, id DESC LIMIT 1
        """)
        row = cursor.fetchone()
        conn.close()
        if not row or not row['snapshot_json']:
            return None, {}
        snapshot_list = json.loads(row['snapshot_json'])
        snapshot = {item['item_id']: float(item.get('counted_system', 0)) for item in snapshot_list}
        return str(row['timestamp']), snapshot
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

    division_mapping = get_division_mapping(os.path.dirname(os.path.abspath(__file__)))

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

    for _, inv_row in inventory_df.iterrows():
        item_id = inv_row[COL_ITEM_ID]
        item_name = inv_row[COL_ITEM_NAME]
        # Use historical closing stock when a date-range map is provided; fall back to live stock
        current_stock = closing_stock_map.get(item_id, inv_row[COL_QUANTITY]) if closing_stock_map else inv_row[COL_QUANTITY]
        cost_price = inv_row[COL_COST_PRICE]
        sell_price = inv_row[COL_SELL_PRICE]

        division = normalize_division_name(division_mapping.get(item_name.lower(), 'Unknown'))

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

        # Compute member/non-member breakdown per-transaction to match GP/Division reports
        actual_sales = log_df[(log_df[COL_ACTION].isin([ACTION_SALES, ACTION_SALES_ONE_UNIT])) & (log_df[COL_ITEM_ID] == item_id)].copy()
        member_sales_value = 0.0
        non_member_sales_value = 0.0
        member_cost = 0.0
        non_member_cost = 0.0
        member_qty = 0.0
        non_member_qty = 0.0

        if not actual_sales.empty:
            actual_sales = _split_sales_revenue_and_cost(actual_sales, member_discount_pct)

            member_sales_value = actual_sales['member_revenue'].sum()
            non_member_sales_value = actual_sales['non_member_revenue'].sum()
            member_cost = actual_sales['member_cost'].sum()
            non_member_cost = actual_sales['non_member_cost'].sum()

            if COL_MEMBER_QTY in actual_sales.columns:
                split_sum = actual_sales[COL_MEMBER_QTY].fillna(0) + actual_sales[COL_NON_MEMBER_QTY].fillna(0)
                has_actual = split_sum > 0
                if has_actual.any():
                    qty = actual_sales.loc[has_actual, COL_QUANTITY]
                    member_qty_col = actual_sales.loc[has_actual, COL_MEMBER_QTY].fillna(0)
                    non_member_qty_col = actual_sales.loc[has_actual, COL_NON_MEMBER_QTY].fillna(0)
                    remaining = np.maximum(qty - member_qty_col - non_member_qty_col, 0)
                    member_qty = (member_qty_col + remaining * 0).sum()
                    non_member_qty = (non_member_qty_col + remaining).sum()
                else:
                    non_member_qty = actual_sales[COL_QUANTITY].sum()
            else:
                non_member_qty = actual_sales[COL_QUANTITY].sum()

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

            # Delisted items report zero stock but keep their sales history.
            if is_delisted(item_id):
                current_stock = 0.0
                item_name = f"{item_name} (DELISTED)"

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

            # Delisted items report zero stock but keep their sales history.
            if is_delisted(item_id):
                current_stock = 0.0
                item_name = f"{item_name} (DELISTED)"

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
