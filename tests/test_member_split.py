"""Tests for member/non-member revenue split logic in reports."""

from __future__ import annotations

import pandas as pd
import pytest

from reports import (
    _split_sales_revenue_and_cost,
    build_gp_report_data,
    build_division_report_data,
    build_comprehensive_report_data,
    COL_ITEM_ID,
    COL_ITEM_NAME,
    COL_ACTION,
    COL_QUANTITY,
    COL_COST_PRICE,
    COL_SELL_PRICE,
    COL_MEMBER_QTY,
    COL_NON_MEMBER_QTY,
    COL_CATEGORY,
    COL_MEASURE,
    COL_REASON,
)


@pytest.fixture
def sample_sales_log():
    return pd.DataFrame(
        [
            # All non-member (no split columns provided)
            ["whisky", "Sales", 10.0, 18.0, 3.50],
            # Split 6 member / 4 non-member
            ["gin", "Sales", 10.0, 15.0, 4.00, 6.0, 4.0],
            # Split data present but only sums to 8 (2 missing -> treated non-member)
            ["rum", "Sales", 10.0, 12.0, 3.50, 5.0, 3.0],
        ],
        columns=[
            COL_ITEM_ID,
            COL_ACTION,
            COL_QUANTITY,
            COL_COST_PRICE,
            COL_SELL_PRICE,
            COL_MEMBER_QTY,
            COL_NON_MEMBER_QTY,
        ],
    )


def test_split_sales_revenue_and_cost_no_split_defaults_to_non_member():
    df = pd.DataFrame(
        [["whisky", 10.0, 18.0, 3.50]],
        columns=[COL_ITEM_ID, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE],
    )
    result = _split_sales_revenue_and_cost(df, member_discount_pct=10)
    assert result["member_revenue"].iloc[0] == 0.0
    assert result["non_member_revenue"].iloc[0] == pytest.approx(35.0)
    assert result["member_cost"].iloc[0] == 0.0
    assert result["non_member_cost"].iloc[0] == pytest.approx(180.0)


def test_split_sales_revenue_and_cost_actual_split():
    df = pd.DataFrame(
        [["gin", 10.0, 15.0, 4.00, 6.0, 4.0]],
        columns=[
            COL_ITEM_ID,
            COL_QUANTITY,
            COL_COST_PRICE,
            COL_SELL_PRICE,
            COL_MEMBER_QTY,
            COL_NON_MEMBER_QTY,
        ],
    )
    result = _split_sales_revenue_and_cost(df, member_discount_pct=10)
    # Before scaling: member = 6*4*0.9 = 21.6, non-member = 4*4 = 16, total = 37.6
    # Total revenue = 10*4 = 40, scale = 40/37.6
    assert (result["member_revenue"] + result["non_member_revenue"]).iloc[0] == pytest.approx(40.0)
    assert result["member_revenue"].iloc[0] == pytest.approx(21.6 * 40.0 / 37.6)
    assert result["non_member_revenue"].iloc[0] == pytest.approx(16.0 * 40.0 / 37.6)
    assert (result["member_cost"] + result["non_member_cost"]).iloc[0] == pytest.approx(150.0)


def test_gp_report_matches_split_totals():
    log = pd.DataFrame(
        [
            ["gin", "Sales", 10.0, 15.0, 4.00, 6.0, 4.0],
        ],
        columns=[
            COL_ITEM_ID,
            COL_ACTION,
            COL_QUANTITY,
            COL_COST_PRICE,
            COL_SELL_PRICE,
            COL_MEMBER_QTY,
            COL_NON_MEMBER_QTY,
        ],
    )
    result = build_gp_report_data(log, member_discount_pct=10)
    assert len(result) == 1
    assert result["Total Revenue"].iloc[0] == pytest.approx(40.0)
    assert result["Member Revenue"].iloc[0] + result["Non-Member Revenue"].iloc[0] == pytest.approx(40.0)
    assert result["Total Cost"].iloc[0] == pytest.approx(150.0)


def test_division_report_matches_split_totals():
    log = pd.DataFrame(
        [
            ["gin", "Sales", 10.0, 15.0, 4.00, 6.0, 4.0],
        ],
        columns=[
            COL_ITEM_ID,
            COL_ACTION,
            COL_QUANTITY,
            COL_COST_PRICE,
            COL_SELL_PRICE,
            COL_MEMBER_QTY,
            COL_NON_MEMBER_QTY,
        ],
    )
    inv = pd.DataFrame(
        [["gin", "Gin", 100.0, 15.0, 4.00, "Spirit", "Spirits"]],
        columns=[COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE, COL_MEASURE, COL_CATEGORY],
    )
    result = build_division_report_data(inv, log, member_discount_pct=10)
    assert len(result) == 1
    assert result["Total Revenue"].iloc[0] == pytest.approx(40.0)
    assert result["Member Revenue"].iloc[0] + result["Non-Member Revenue"].iloc[0] == pytest.approx(40.0)


def test_comprehensive_report_no_double_member_discount():
    log = pd.DataFrame(
        [
            ["gin", "Sales", 10.0, 15.0, 4.00, "", 6.0, 4.0],
        ],
        columns=[
            COL_ITEM_ID,
            COL_ACTION,
            COL_QUANTITY,
            COL_COST_PRICE,
            COL_SELL_PRICE,
            COL_REASON,
            COL_MEMBER_QTY,
            COL_NON_MEMBER_QTY,
        ],
    )
    inv = pd.DataFrame(
        [["gin", "Gin", 100.0, 15.0, 4.00, "35ml", "Spirit"]],
        columns=[COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE, COL_MEASURE, COL_CATEGORY],
    )
    result = build_comprehensive_report_data(inv, log, member_discount_pct=10)
    assert len(result) == 1
    row = result[0]
    assert row["total_sales_value"] == pytest.approx(40.0)
    assert row["member_sales_value"] + row["non_member_sales_value"] == pytest.approx(40.0)
