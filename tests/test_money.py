#!/usr/bin/env python3
"""Penny-exactness tests for the shared money helpers and the reports that use them.

Every money figure in the app must be identical to the penny across the
dashboard, the report screens and the PDF. These tests pin the arithmetic that
makes that true: components add back to totals, and a column of allocated
amounts always sums to its rounded total.
"""

import pandas as pd
import pytest

from actions import ACTION_SALES
from data_manager import (
    COL_ACTION,
    COL_ITEM_ID,
    COL_QUANTITY,
    COL_SELL_PRICE,
    COL_TIMESTAMP,
    LOG_COLUMNS,
)
from money import (
    VAT_MULTIPLIER,
    VAT_RATE,
    allocate_money,
    ex_vat,
    inc_vat,
    round_money,
    sum_money,
)
from reports import build_division_report_data, build_gp_report_data, sales_money_by_item


def log_frame(rows):
    return pd.DataFrame(rows, columns=LOG_COLUMNS)


def sales_log():
    return log_frame([
        ["tennents_lager", ACTION_SALES, 10.0, "2026-10-02 12:00:00",
         1.11, 3.33, "", "", "", 4, 6, None],
        ["guinness", ACTION_SALES, 7.0, "2026-10-02 12:05:00",
         0.97, 3.11, "", "", "", 0, 7, None],
        ["poretti", ACTION_SALES, 5.0, "2026-10-03 12:00:00",
         1.03, 3.37, "", "", "", 5, 0, None],
        ["barista_coffee", ACTION_SALES, 11.0, "2026-10-03 12:10:00",
         0.29, 2.99, "", "", "", 3, 8, None],
    ])


def test_round_money_is_half_up_and_stable():
    assert round_money(1.005) == 1.01
    assert round_money(2.675) == 2.68
    assert round_money(-1.005) == -1.01
    assert round_money("nonsense") == 0.0


def test_sum_money_rounds_only_once():
    assert sum_money([0.005, 0.005, 0.005]) == 0.02
    assert sum_money([]) == 0.0


def test_vat_rate_is_the_standard_twenty_percent():
    assert VAT_RATE == pytest.approx(0.20)
    assert VAT_MULTIPLIER == pytest.approx(1.20)


def test_inc_vat_matches_the_epos_export_total():
    # The 1-18 October upload: the exporter totals £11,022.89 inc VAT and the
    # system records £9,180.92 ex VAT for the lines it can hold.
    assert inc_vat(9180.92) == pytest.approx(11017.10)
    assert ex_vat(11022.89) == pytest.approx(9185.74)
    assert ex_vat(inc_vat(9180.92)) == pytest.approx(9180.92)


def test_vat_helpers_round_once_at_the_penny():
    assert inc_vat(0) == 0.0
    assert inc_vat("nonsense") == 0.0
    assert inc_vat(1.004) == pytest.approx(1.20)
    # One rounding on the column, not one per line: 3 x 0.005 ex VAT is 0.02
    # inc VAT, not the 3 x 0.01 a per-line uplift would produce.
    assert inc_vat(sum_money([0.005, 0.005, 0.005])) == pytest.approx(0.02)


def test_allocate_money_parts_add_up_to_the_rounded_total():
    values = [1.005, 1.005, 1.005, 1.005]
    allocated = allocate_money(values)
    assert sum(allocated) == pytest.approx(round_money(sum(values)), abs=1e-9)
    assert sum(allocated) == pytest.approx(4.02, abs=1e-9)


def test_allocate_money_is_deterministic():
    values = [0.1, 0.2, 0.3, 0.4, 0.5]
    assert allocate_money(values) == allocate_money(list(values))


def test_allocate_money_handles_negative_values():
    values = [0.004, -0.004, 0.006]
    allocated = allocate_money(values)
    assert sum(allocated) == pytest.approx(round_money(sum(values)), abs=1e-9)


def test_sales_money_components_add_back_per_row():
    money = sales_money_by_item(sales_log(), member_discount_pct=10)

    for _, row in money.iterrows():
        assert row["total_revenue"] == pytest.approx(
            row["member_revenue"] + row["non_member_revenue"], abs=1e-9)
        assert row["total_cost"] == pytest.approx(
            row["member_cost"] + row["non_member_cost"], abs=1e-9)
        assert row["gp"] == pytest.approx(row["total_revenue"] - row["total_cost"],
                                          abs=1e-9)
        assert row["member_gp"] == pytest.approx(
            row["member_revenue"] - row["member_cost"], abs=1e-9)


def test_member_split_survives_an_object_dtype_log():
    # A fresh session concatenates log frames, which stores every column as
    # object; the member split must not crash or lose the member discount.
    object_log = sales_log().astype(object)
    numeric = sales_money_by_item(sales_log(), member_discount_pct=10)
    object_money = sales_money_by_item(object_log, member_discount_pct=10)

    for column in ("member_revenue", "non_member_revenue", "member_cost",
                   "non_member_cost", "total_revenue", "gp"):
        assert sum_money(object_money[column]) == pytest.approx(
            sum_money(numeric[column]), abs=1e-9)
    assert sum_money(numeric["member_revenue"]) > 0


def test_member_split_handles_a_fully_non_member_sale():
    log = log_frame([
        ["tennents_lager", ACTION_SALES, 10.0, "2026-10-02 12:00:00",
         1.11, 3.33, "", "", "", 0, 10, None],
    ]).astype(object)
    money = sales_money_by_item(log, member_discount_pct=10)

    assert sum_money(money["member_revenue"]) == pytest.approx(0.0)
    assert sum_money(money["non_member_revenue"]) == pytest.approx(33.30)


def test_gp_and_division_reports_show_identical_money():
    log = sales_log()
    inventory = pd.DataFrame([
        {"item_id": "tennents_lager", "division": "Beer-Draught"},
        {"item_id": "guinness", "division": "Beer-Draught"},
        {"item_id": "poretti", "division": "Beer-Draught"},
        {"item_id": "barista_coffee", "division": "Hot Drinks"},
    ])

    gp = build_gp_report_data(log, member_discount_pct=10)
    division = build_division_report_data(inventory, log, member_discount_pct=10)

    for column in ("Total Revenue", "Total Cost", "GP", "Member Revenue",
                   "Non-Member Revenue", "Member GP", "Non-Member GP"):
        assert sum_money(gp[column]) == pytest.approx(
            sum_money(division[column]), abs=1e-9)

    # Division rows must add up to the GP report column totals exactly.
    for column in ("Total Revenue", "Total Cost", "GP"):
        assert sum_money(division[column]) == pytest.approx(
            sum_money(gp[column]), abs=1e-9)


def test_division_row_components_add_back():
    inventory = pd.DataFrame([
        {"item_id": "tennents_lager", "division": "Beer-Draught"},
        {"item_id": "guinness", "division": "Beer-Draught"},
        {"item_id": "poretti", "division": "Beer-Draught"},
        {"item_id": "barista_coffee", "division": "Hot Drinks"},
    ])
    division = build_division_report_data(inventory, sales_log())

    for _, row in division.iterrows():
        assert row["Total Revenue"] == pytest.approx(
            row["Member Revenue"] + row["Non-Member Revenue"], abs=1e-9)
        assert row["GP"] == pytest.approx(row["Total Revenue"] - row["Total Cost"],
                                          abs=1e-9)
