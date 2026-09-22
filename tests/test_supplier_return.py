#!/usr/bin/env python3
"""
Unit tests for the Supplier Return action and reporting logic.

These tests use in-memory pandas DataFrames and do NOT touch the live SQLite
database or the user's data files.
"""

import os
import sys

# Ensure project modules are importable when running from tests/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import pytest

from actions import (
    ACTION_SALES,
    ACTION_WASTAGE,
    ACTION_COMPLIMENTARY,
    ACTION_SUPPLIER_RETURN,
    CONSUMPTION_ACTIONS,
    NEGATIVE_STOCK_ACTIONS,
)
from reports import (
    calculate_expected_remaining_series,
    build_comprehensive_report_data,
    build_draught_yield_data,
)


COL_ITEM_ID = 'item_id'
COL_ITEM_NAME = 'item_name'
COL_QUANTITY = 'quantity'
COL_COST_PRICE = 'cost_price'
COL_SELL_PRICE = 'sell_price'
COL_ACTION = 'action'
COL_TIMESTAMP = 'timestamp'
COL_SUPPLIER = 'supplier'
COL_DATE_RANGE = 'date_range'
COL_REASON = 'reason'
COL_CATEGORY = 'category'
COL_MEASURE = 'measure'


def _make_inventory():
    return pd.DataFrame([
        ['tennents_lager', 'Tennents Lager', 200.0, 1.50, 4.00, 'Pint', 'Draught'],
        ['belhaven_best', 'Belhaven Best', 160.0, 1.60, 4.20, 'Pint', 'Draught'],
        ['whisky_70cl', 'Whisky 70cl', 10.0, 18.00, 3.50, '35ml', 'Spirit'],
    ], columns=[COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE, COL_MEASURE, COL_CATEGORY])


def _make_log(rows):
    columns = [COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON]
    return pd.DataFrame(rows, columns=columns)


def test_supplier_return_action_sets():
    """Supplier return should trigger negative-stock guard but not be treated as consumption."""
    assert ACTION_SUPPLIER_RETURN in NEGATIVE_STOCK_ACTIONS
    assert ACTION_SUPPLIER_RETURN not in CONSUMPTION_ACTIONS
    assert ACTION_WASTAGE in CONSUMPTION_ACTIONS
    assert ACTION_COMPLIMENTARY in CONSUMPTION_ACTIONS


def test_expected_remaining_subtracts_supplier_return():
    """Returning stock should reduce the expected remaining quantity."""
    inventory = _make_inventory()
    log = _make_log([
        ['tennents_lager', ACTION_SUPPLIER_RETURN, 88.0, '2026-09-01 10:00:00', 1.50, 4.00, 'Tennents', '', 'Faulty Keg'],
    ])
    expected = calculate_expected_remaining_series(log)
    assert expected['tennents_lager'] == -88.0


def test_expected_remaining_excludes_supplier_return_from_consumption():
    """Supplier returns should not be mixed with sales/wastage when computing expected stock."""
    inventory = _make_inventory()
    log = _make_log([
        ['tennents_lager', ACTION_SALES, 50.0, '2026-09-01 09:00:00', 1.50, 4.00, '', '', ''],
        ['tennents_lager', ACTION_SUPPLIER_RETURN, 88.0, '2026-09-01 10:00:00', 1.50, 4.00, 'Tennents', '', 'Faulty Keg'],
    ])
    expected = calculate_expected_remaining_series(log)
    # Expected = -sales - returns = -50 - 88
    assert expected['tennents_lager'] == -138.0


def test_comprehensive_report_separates_supplier_return():
    """Supplier returns should be reported separately and excluded from wastage/consumption."""
    inventory = _make_inventory()
    log = _make_log([
        ['tennents_lager', ACTION_SALES, 50.0, '2026-09-01 09:00:00', 1.50, 4.00, '', '', ''],
        ['tennents_lager', ACTION_WASTAGE, 10.0, '2026-09-01 09:00:00', 1.50, 4.00, '', '', 'Overpour'],
        ['tennents_lager', ACTION_SUPPLIER_RETURN, 88.0, '2026-09-01 10:00:00', 1.50, 4.00, 'Tennents', '', 'Faulty Keg'],
    ])
    report = build_comprehensive_report_data(inventory, log)
    tennents = next(r for r in report if r['item_id'] == 'tennents_lager')

    assert tennents['total_sales_qty'] == 50.0
    assert tennents['wastage_qty'] == 10.0
    assert tennents['supplier_return_qty'] == 88.0
    assert tennents['supplier_return_supplier'] == 'Tennents'
    assert tennents['supplier_return_reason'] == 'Faulty Keg'

    # Expected consumption should only include sales/wastage/complimentary, not returns.
    assert tennents['expected_consumption'] == 60.0


def test_comprehensive_report_supplier_return_does_not_affect_gp():
    """Supplier returns should not appear in sales GP calculations."""
    inventory = _make_inventory()
    log = _make_log([
        ['tennents_lager', ACTION_SALES, 50.0, '2026-09-01 09:00:00', 1.50, 4.00, '', '', ''],
        ['tennents_lager', ACTION_SUPPLIER_RETURN, 88.0, '2026-09-01 10:00:00', 1.50, 4.00, 'Tennents', '', 'Faulty Keg'],
    ])
    report = build_comprehensive_report_data(inventory, log)
    tennents = next(r for r in report if r['item_id'] == 'tennents_lager')

    expected_revenue = 50.0 * 4.00
    expected_cost = 50.0 * 1.50
    assert tennents['total_sales_value'] == expected_revenue
    assert tennents['sales_cost'] == expected_cost
    assert tennents['sales_gp'] == expected_revenue - expected_cost


def test_draught_yield_excludes_supplier_return_from_consumption():
    """Supplier returns should not be counted as draught consumption/yield loss."""
    inventory = _make_inventory()
    # During the period: 88 pints returned, 50 sold, 10 wasted.
    log = _make_log([
        ['tennents_lager', ACTION_SALES, 50.0, '2026-09-01 09:00:00', 1.50, 4.00, '', '', ''],
        ['tennents_lager', ACTION_WASTAGE, 10.0, '2026-09-01 09:30:00', 1.50, 4.00, '', '', 'Overpour'],
        ['tennents_lager', ACTION_SUPPLIER_RETURN, 88.0, '2026-09-01 10:00:00', 1.50, 4.00, 'Tennents', '', 'Faulty Keg'],
    ])
    report = build_draught_yield_data(inventory, log)
    tennents = next(r for r in report if r[COL_ITEM_ID] == 'tennents_lager')

    # Expected consumption should only include sales/wastage, not returns.
    assert tennents['Expected Consumption'] == 60.0
    assert tennents[ACTION_SALES] == 50.0
    assert tennents[ACTION_WASTAGE] == 10.0


def test_multiple_returns_aggregate_reasons_and_suppliers():
    """Multiple return rows should be aggregated with distinct reasons/suppliers joined."""
    inventory = _make_inventory()
    log = _make_log([
        ['tennents_lager', ACTION_SUPPLIER_RETURN, 88.0, '2026-09-01 10:00:00', 1.50, 4.00, 'Tennents', '', 'Faulty Keg'],
        ['tennents_lager', ACTION_SUPPLIER_RETURN, 88.0, '2026-09-02 10:00:00', 1.50, 4.00, 'Tennents', '', 'Out of Date'],
    ])
    report = build_comprehensive_report_data(inventory, log)
    tennents = next(r for r in report if r['item_id'] == 'tennents_lager')

    assert tennents['supplier_return_qty'] == 176.0
    assert 'Faulty Keg' in tennents['supplier_return_reason']
    assert 'Out of Date' in tennents['supplier_return_reason']
    assert tennents['supplier_return_supplier'] == 'Tennents'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
