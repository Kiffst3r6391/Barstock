"""Shared fixtures for the BarStock test suite."""

from __future__ import annotations

import pandas as pd
import pytest

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
    COL_DATE_RANGE,
    COL_REASON,
    COL_MEMBER_QTY,
    COL_NON_MEMBER_QTY,
    COL_ALLOW_NEGATIVE,
)


@pytest.fixture
def inventory_columns():
    return [
        COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE,
        COL_MEASURE, COL_CATEGORY, COL_ALLOW_NEGATIVE,
    ]


@pytest.fixture
def log_columns():
    return [
        COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE,
        COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON,
        COL_MEMBER_QTY, COL_NON_MEMBER_QTY,
    ]


@pytest.fixture
def sample_inventory(inventory_columns):
    return pd.DataFrame(
        [
            # Parent draught items
            ["tennents_lager", "Tennents Lager", 100.0, 1.50, 4.00, "Pint", "Draught", False],
            ["belhaven_best", "Belhaven Best", 80.0, 1.60, 4.20, "Pint", "Draught", False],
            ["lemonade", "Lemonade", 60.0, 0.40, 2.50, "Pint", "Soft", False],
            ["carton_juice", "Carton Juice", 50.0, 0.30, 2.00, "Pint", "Soft", False],
            # Bottled item with measure conversion
            ["whisky_70cl", "Whisky 70cl", 10.0, 18.00, 3.50, "35ml", "Spirit", False],
            # Child items
            ["tennents_lager_half", "Tennents Half", 0.0, 0.0, 2.50, "Half Pint", "Draught", False],
            ["tennants_shandy_pint", "Tennents Shandy", 0.0, 0.0, 4.50, "Pint", "Draught", False],
        ],
        columns=inventory_columns,
    )


@pytest.fixture
def empty_log(log_columns):
    return pd.DataFrame(columns=log_columns)
