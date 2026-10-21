"""Tests for the stock order sheet report builder."""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from reports import build_stock_order_sheet_data
from actions import ACTION_DELIVERY
from conversions import DATE_FORMAT_DISPLAY
from data_manager import (
    COL_ITEM_ID,
    COL_ITEM_NAME,
    COL_QUANTITY,
    COL_COST_PRICE,
    COL_SELL_PRICE,
    COL_MEASURE,
    COL_CATEGORY,
    COL_ACTION,
    COL_TIMESTAMP,
    COL_SUPPLIER,
    COL_REORDER_LEVEL,
)


@pytest.fixture
def order_inventory():
    """Inventory with parents, children, excluded items, and reorder levels."""
    return pd.DataFrame(
        [
            # Parents - Booker
            ["budweiser", "Budweiser", 10.0, 0.83, 3.95, "Bottle", "Bottle", 20.0],
            ["corona", "Corona", 5.0, 0.95, 4.3, "Bottle", "Bottle", 15.0],
            # Parents - Tennents
            ["tennents_lager", "Tennents Lager", 50.0, 1.52, 5.2, "Pint", "Draught", 100.0],
            # Parents - Delisted (no longer reordered; mapped to Booker for reports)
            ["belhaven_best", "Belhaven Best", 0.0, 1.15, 5.1, "Pint", "Draught", 80.0],
            # Child items (should be excluded)
            ["tennents_lager_half", "Tennents Lager - Half", 0.0, 0.76, 3.26, "Half Pint", "Draught", 0.0],
            ["belhaven_best_half_pint", "Belhaven Best - Half", 0.0, 0.8, 2.0, "Half Pint", "Draught", 0.0],
            # Excluded items (should be excluded)
            ["tea", "Tea", 5.0, 0.5, 2.0, "Cup", "Hot Drinks", 10.0],
            ["dash", "Dash", 20.0, 0.05, 0.64, "35ml", "Soft", 0.0],
            # Item with no reorder level
            ["nuts", "Nuts", 40.0, 0.55, 1.0, "Pack", "Snack", 0.0],
        ],
        columns=[
            COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE,
            COL_SELL_PRICE, COL_MEASURE, COL_CATEGORY, COL_REORDER_LEVEL,
        ],
    )


@pytest.fixture
def empty_log():
    return pd.DataFrame(
        columns=[
            COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP,
            COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER,
        ]
    )


@pytest.fixture
def delivery_log():
    """Delivery history used to populate last-delivery metadata."""
    base = datetime.now() - timedelta(days=7)
    return pd.DataFrame(
        [
            ["budweiser", ACTION_DELIVERY, 24.0, (base + timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S"), 0.83, 3.95, "Booker"],
            ["tennents_lager", ACTION_DELIVERY, 88.0, (base + timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"), 1.52, 5.2, "Tennents"],
            ["belhaven_best", ACTION_DELIVERY, 88.0, base.strftime("%Y-%m-%d %H:%M:%S"), 1.15, 5.1, "Belhaven"],
            ["budweiser", ACTION_DELIVERY, 12.0, base.strftime("%Y-%m-%d %H:%M:%S"), 0.83, 3.95, "Booker"],
        ],
        columns=[
            COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP,
            COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER,
        ]
    )


class TestStockOrderSheetData:
    """Unit tests for build_stock_order_sheet_data."""

    def test_excludes_child_and_hidden_items(self, order_inventory, empty_log):
        report_data = build_stock_order_sheet_data(order_inventory, empty_log)
        item_ids = {row[COL_ITEM_ID] for row in report_data}

        assert "tennents_lager_half" not in item_ids
        assert "belhaven_best_half_pint" not in item_ids
        assert "dash" not in item_ids

    def test_excludes_ignored_items(self, order_inventory, empty_log):
        report_data = build_stock_order_sheet_data(order_inventory, empty_log)
        item_ids = {row[COL_ITEM_ID] for row in report_data}

        assert "tea" not in item_ids

    def test_includes_parent_items(self, order_inventory, empty_log):
        report_data = build_stock_order_sheet_data(order_inventory, empty_log)
        item_ids = {row[COL_ITEM_ID] for row in report_data}

        assert "budweiser" in item_ids
        assert "corona" in item_ids
        assert "tennents_lager" in item_ids
        assert "belhaven_best" in item_ids
        assert "nuts" in item_ids

    def test_supplier_mapping_defaults(self, order_inventory, empty_log):
        report_data = build_stock_order_sheet_data(order_inventory, empty_log)
        by_id = {row[COL_ITEM_ID]: row for row in report_data}

        assert by_id["budweiser"][COL_SUPPLIER] == "Booker"
        assert by_id["corona"][COL_SUPPLIER] == "Booker"
        assert by_id["tennents_lager"][COL_SUPPLIER] == "Tennents"
        assert by_id["belhaven_best"][COL_SUPPLIER] == "Booker"
        assert by_id["nuts"][COL_SUPPLIER] == "Booker"

    def test_sort_order_supplier_then_category_then_name(self, order_inventory, empty_log):
        report_data = build_stock_order_sheet_data(order_inventory, empty_log)
        suppliers = [row[COL_SUPPLIER] for row in report_data]

        assert suppliers == sorted(suppliers, key=lambda s: ("Booker", "Tennents", "Unknown").index(s))

    def test_suggested_order_calculation(self, order_inventory, empty_log):
        report_data = build_stock_order_sheet_data(order_inventory, empty_log)
        by_id = {row[COL_ITEM_ID]: row for row in report_data}

        # Budweiser: reorder 20, current 10 -> suggested 30
        assert by_id["budweiser"]["suggested_order"] == pytest.approx(30.0)
        # Corona: reorder 15, current 5 -> suggested 25
        assert by_id["corona"]["suggested_order"] == pytest.approx(25.0)
        # Nuts: no reorder level -> suggested 0
        assert by_id["nuts"]["suggested_order"] == pytest.approx(0.0)

    def test_last_delivery_metadata(self, order_inventory, delivery_log):
        report_data = build_stock_order_sheet_data(order_inventory, delivery_log)
        by_id = {row[COL_ITEM_ID]: row for row in report_data}

        # Budweiser has two deliveries - should use the most recent one
        assert by_id["budweiser"]["last_delivery_supplier"] == "Booker"
        expected_date = datetime.strptime(delivery_log.iloc[0][COL_TIMESTAMP][:10], '%Y-%m-%d').strftime(DATE_FORMAT_DISPLAY)
        assert by_id["budweiser"]["last_delivery_date"] == expected_date

        assert by_id["tennents_lager"]["last_delivery_supplier"] == "Tennents"
        assert by_id["belhaven_best"]["last_delivery_supplier"] == "Belhaven"

    def test_empty_inventory_returns_empty_list(self):
        assert build_stock_order_sheet_data(pd.DataFrame(), pd.DataFrame()) == []
