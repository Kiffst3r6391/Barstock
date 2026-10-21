#!/usr/bin/env python3
"""Reporting maths regression tests.

Covers the two calculation errors fixed after the 2026-10 reconciliation:
stocktake adjustments were ignored when deriving expected stock, and GP/net
profit were being grossed up by the VAT multiplier.
"""

import pandas as pd

from actions import (
    ACTION_DELIVERY,
    ACTION_SALES,
    ACTION_STOCKTAKE_ADJUSTMENT,
    ACTION_STOCKTAKE_BASELINE,
)
from data_manager import (
    COL_ACTION,
    COL_ITEM_ID,
    COL_QUANTITY,
    COL_TIMESTAMP,
    LOG_COLUMNS,
)
from pdf_generator import calculate_vat_summary
from reports import calculate_expected_remaining_series


def log_frame(rows):
    return pd.DataFrame(rows, columns=LOG_COLUMNS)


def test_stocktake_adjustment_is_included_in_expected_stock():
    logs = log_frame([
        ["tennents_lager", ACTION_STOCKTAKE_BASELINE, 100.0,
         "2026-10-01 09:00:00", 0, 0, "", "", "", 0, 0, None],
        ["tennents_lager", ACTION_DELIVERY, 10.0,
         "2026-10-02 09:00:00", 0, 0, "", "", "", 0, 0, None],
        ["tennents_lager", ACTION_SALES, 5.0,
         "2026-10-03 09:00:00", 0, 0, "", "", "", 0, 0, None],
        ["tennents_lager", ACTION_STOCKTAKE_ADJUSTMENT, -3.0,
         "2026-10-04 09:00:00", 0, 0, "", "", "", 0, 0, None],
    ])

    expected = calculate_expected_remaining_series(logs)

    assert expected["tennents_lager"] == 102.0


def test_positive_stocktake_adjustment_increases_expected_stock():
    logs = log_frame([
        ["tennents_lager", ACTION_STOCKTAKE_BASELINE, 100.0,
         "2026-10-01 09:00:00", 0, 0, "", "", "", 0, 0, None],
        ["tennents_lager", ACTION_STOCKTAKE_ADJUSTMENT, 4.0,
         "2026-10-02 09:00:00", 0, 0, "", "", "", 0, 0, None],
    ])

    assert calculate_expected_remaining_series(logs)["tennents_lager"] == 104.0


def test_adjustment_before_the_latest_baseline_is_superseded():
    logs = log_frame([
        ["tennents_lager", ACTION_STOCKTAKE_ADJUSTMENT, -9.0,
         "2026-09-01 09:00:00", 0, 0, "", "", "", 0, 0, None],
        ["tennents_lager", ACTION_STOCKTAKE_BASELINE, 50.0,
         "2026-10-01 09:00:00", 0, 0, "", "", "", 0, 0, None],
    ])

    assert calculate_expected_remaining_series(logs)["tennents_lager"] == 50.0


def test_vat_summary_grosses_up_sales_but_not_profit():
    summary = calculate_vat_summary(sales_value=1000.0, gp=400.0, net_profit=300.0)

    assert summary["sales_ex_vat"] == 1000.0
    assert summary["sales_inc_vat"] == 1200.0
    assert summary["vat_on_sales"] == 200.0
    # GP and net profit are margins: they must be left exactly as calculated.
    assert summary["gp_ex_vat"] == 400.0
    assert summary["net_profit_ex_vat"] == 300.0
    assert "gp_inc_vat" not in summary
    assert "net_profit_inc_vat" not in summary
