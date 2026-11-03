#!/usr/bin/env python3
"""Reporting maths regression tests.

Covers the two calculation errors fixed after the 2026-10 reconciliation:
stocktake adjustments were ignored when deriving expected stock, and GP/net
profit were being grossed up by the VAT multiplier.
"""

import pandas as pd
from datetime import datetime

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
    INVENTORY_COLUMNS,
    LOG_COLUMNS,
)
from pdf_generator import (
    allocate_division_inc_vat,
    calculate_vat_summary,
    format_report_period,
)
import reports
from reports import (
    build_comprehensive_report_data,
    build_stocktake_variance_report,
    calculate_expected_remaining_series,
)


def log_frame(rows):
    return pd.DataFrame(rows, columns=LOG_COLUMNS)


def inventory_frame(rows):
    return pd.DataFrame(rows, columns=INVENTORY_COLUMNS)


def _isolate_report_db(monkeypatch):
    """Keep report tests away from the live baseline/open-tab tables."""
    monkeypatch.setattr(reports, "_get_latest_baseline_snapshot", lambda: (None, {}))
    monkeypatch.setattr(reports, "_get_currently_open_tab_ids", lambda: set())


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


def test_division_inc_vat_keeps_a_small_exact_line_and_still_adds_up():
    # The wedding transfer is exactly £1,400.00 inc VAT; the column total must
    # still match inc VAT of the grand total, so the rounding pennies belong to
    # the largest divisions rather than the small function line.
    totals = {
        'Beer - Draught': {'sales_value': 4080.52},
        'Hot Drinks': {'sales_value': 1526.12},
        'Functions': {'sales_value': 1166.67},
        'Wine': {'sales_value': 716.42},
    }

    values = allocate_division_inc_vat(totals)

    assert values['Functions'] == 1400.00
    assert values['Wine'] == 859.70
    assert round(sum(values.values()), 2) == 8987.68
    assert values['Beer - Draught'] == 4896.63  # absorbs a residual penny


def test_expected_stock_clamps_an_oversold_line_for_reports():
    # Reports clamp an oversold line to its baseline so the variance report
    # never invents a negative opening stock; reconciliation asks for the
    # unclamped balance instead.
    logs = log_frame([
        ["jack_daniels", ACTION_STOCKTAKE_BASELINE, 17.2,
         "2026-10-01 09:00:00", 0, 0, "", "", "", 0, 0, None],
        ["jack_daniels", ACTION_SALES, 18.0,
         "2026-10-02 09:00:00", 0, 0, "", "", "", 0, 0, None],
    ])

    assert calculate_expected_remaining_series(logs)["jack_daniels"] == 17.2
    assert round(calculate_expected_remaining_series(
        logs, clamp_negative=False)["jack_daniels"], 2) == -0.8


def test_child_sales_before_the_parent_baseline_are_not_deducted_again():
    # Children (mixers) are never counted, so they keep their whole history.
    # Once the parent is re-baselined, a shandy sold before that count is
    # already inside the physical figure; deducting it again understates
    # expected stock and shows up as a phantom surplus at the next count.
    logs = log_frame([
        ["lemonade", ACTION_STOCKTAKE_BASELINE, 200.0,
         "2026-11-01 08:00:00", 0, 0, "", "", "", 0, 0, None],
        ["tennants_shandy_pint", ACTION_SALES, 20.0,
         "2026-10-15 21:00:00", 0, 0, "", "", "", 10, 10, None],
        ["tennants_shandy_pint", ACTION_SALES, 4.0,
         "2026-11-02 21:00:00", 0, 0, "", "", "", 2, 2, None],
    ])

    expected = calculate_expected_remaining_series(logs)

    # Only the four post-baseline halves come off the 200-pint count.
    assert expected["lemonade"] == 198.0


def test_report_period_label_uses_the_picked_dates():
    # The date picker returns datetimes, the end one at 23:59:59.
    start = datetime(2026, 10, 1, 0, 0, 0)
    end = datetime(2026, 10, 25, 23, 59, 59)

    assert format_report_period(start, end) == '01-10-2026 to 25-10-2026'


def test_report_period_label_says_all_time_when_unbounded():
    assert format_report_period(None, None) == 'All time'


def test_report_period_label_handles_an_open_ended_range():
    assert format_report_period(datetime(2026, 10, 1), None) == 'From 01-10-2026'
    assert format_report_period(None, datetime(2026, 10, 25)) == 'Up to 25-10-2026'


def test_comprehensive_report_drops_delisted_items_without_activity(monkeypatch):
    _isolate_report_db(monkeypatch)
    inventory = inventory_frame([
        ["tennents_lager", "Tennents Lager", 10.0, 1.0, 2.0, "Pint", "Draught", 0, 0, 0, "Beer - Draught"],
        ["belhaven_best", "Belhaven Best", 0.0, 1.0, 2.0, "Pint", "Draught", 0, 0, 0, "Beer - Draught"],
        ["thatchers", "Thatchers", 0.0, 1.0, 2.0, "Pint", "Draught", 0, 0, 0, "Beer - Draught"],
    ])
    logs = log_frame([
        ["tennents_lager", ACTION_SALES, 2.0, "2026-10-03 09:00:00",
         1.0, 2.0, "", "", "", 1, 1, None],
        # A delisted reset is bookkeeping, not activity: it must not keep the
        # line alive in the report.
        ["belhaven_best", ACTION_STOCKTAKE_ADJUSTMENT, 1.0, "2026-10-04 09:00:00",
         0, 0, "", "", "", 0, 0, None],
    ])

    ids = {row["item_id"] for row in build_comprehensive_report_data(inventory, logs)}

    assert ids == {"tennents_lager"}


def test_comprehensive_report_keeps_a_delisted_line_that_sold(monkeypatch):
    _isolate_report_db(monkeypatch)
    inventory = inventory_frame([
        ["birra_moretti", "Birra Moretti", 0.0, 1.4, 3.4, "Pint", "Draught", 0, 0, 0, "Beer - Draught"],
    ])
    logs = log_frame([
        ["birra_moretti", ACTION_SALES, 21.0, "2026-10-10 21:00:00",
         1.4, 3.3, "", "", "", 10, 11, None],
    ])

    rows = build_comprehensive_report_data(inventory, logs)

    # The final sell-off before delisting is real revenue: keeping the line
    # keeps the sales total reconciling with EPOS. Stock is zero, though.
    assert len(rows) == 1
    assert rows[0]["is_delisted"] is True
    assert rows[0]["current_stock"] == 0
    assert rows[0]["total_sales_qty"] == 21
    assert rows[0]["total_sales_value"] > 0


def test_stocktake_variance_report_omits_delisted_items():
    inventory = inventory_frame([
        ["tennents_lager", "Tennents Lager", 10.0, 1.0, 2.0, "Pint", "Draught", 0, 0, 0, "Beer - Draught"],
        ["belhaven_best", "Belhaven Best", 0.0, 1.0, 2.0, "Pint", "Draught", 0, 0, 0, "Beer - Draught"],
    ])
    logs = log_frame([
        ["tennents_lager", ACTION_STOCKTAKE_BASELINE, 10.0, "2026-10-01 09:00:00",
         0, 0, "", "", "", 0, 0, None],
    ])

    ids = {row["item_id"] for row in build_stocktake_variance_report(inventory, logs)}

    assert ids == {"tennents_lager"}
