#!/usr/bin/env python3
"""
Unit tests for delivery editing/deletion logic in BarStockApp.

These tests use in-memory pandas DataFrames and do NOT touch the live SQLite
database or the user's data files.
"""

import os
import sys
import unittest

# Ensure project modules are importable when running from tests/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from conversions import convert_to_system, get_conversion, requires_conversion

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
ACTION_DELIVERY = 'Delivery'


def _reverse_and_apply_delivery_edit(
    inventory_df,
    log_df,
    timestamp,
    entries,
):
    """
    Replicate the core logic from BarStockApp.edit_delivery_dialog save_edits().

    entries: list of dicts with keys:
        item_id, original_qty, new_qty, original_cost, new_cost
    """
    df = inventory_df.copy()
    log = log_df.copy()

    # Reverse original stock changes
    for e in entries:
        df.loc[df[COL_ITEM_ID] == e['item_id'], COL_QUANTITY] -= e['original_qty']

    # Apply new values
    for e in entries:
        new_qty = e['new_qty']
        new_cost = e['new_cost']
        item_id = e['item_id']
        if requires_conversion(item_id):
            conv = get_conversion(item_id)
            if conv:
                new_cost = new_cost / conv[1]
        df.loc[df[COL_ITEM_ID] == item_id, COL_QUANTITY] += new_qty
        df.loc[df[COL_ITEM_ID] == item_id, COL_COST_PRICE] = new_cost

    # Update log entries
    mask = (log[COL_TIMESTAMP] == timestamp) & (log[COL_ACTION] == ACTION_DELIVERY)
    for e in entries:
        item_id = e['item_id']
        new_qty = e['new_qty']
        new_cost = e['new_cost']
        if requires_conversion(item_id):
            conv = get_conversion(item_id)
            if conv:
                new_cost = new_cost / conv[1]
        item_mask = mask & (log[COL_ITEM_ID] == item_id)
        if item_mask.any():
            log.loc[item_mask, COL_QUANTITY] = new_qty
            log.loc[item_mask, COL_COST_PRICE] = new_cost

    return df, log


def _delete_delivery(inventory_df, log_df, timestamp, items):
    """Replicate BarStockApp.delete_delivery logic."""
    df = inventory_df.copy()
    log = log_df.copy()

    for row in items:
        item_id = row.get(COL_ITEM_ID, '')
        qty = float(row.get(COL_QUANTITY, 0))
        if item_id and item_id in df[COL_ITEM_ID].values:
            df.loc[df[COL_ITEM_ID] == item_id, COL_QUANTITY] -= qty

    mask = (log[COL_TIMESTAMP] == timestamp) & (log[COL_ACTION] == ACTION_DELIVERY)
    log = log[~mask].reset_index(drop=True)
    return df, log


class TestDeliveryEditQuantity(unittest.TestCase):
    """Editing a delivery's quantity updates stock and log correctly."""

    def setUp(self):
        self.inventory = pd.DataFrame([
            ['tennents_lager', 'Tennents Lager', 100.0, 1.50, 4.00, 'Pint', 'Draught'],
            ['moretti_bottle', 'Moretti Bottle', 50.0, 1.70, 3.80, 'Bottle', 'Beer - Bottled'],
        ], columns=[COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE, 'measure', 'category'])

        self.timestamp = '2026-08-06 12:00:00'
        self.log = pd.DataFrame([
            ['tennents_lager', ACTION_DELIVERY, 20.0, self.timestamp, 1.50, 4.00, 'Supplier A', '', ''],
            ['moretti_bottle', ACTION_DELIVERY, 12.0, self.timestamp, 1.70, 3.80, 'Supplier A', '', ''],
        ], columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON])

    def test_edit_quantity_updates_stock(self):
        entries = [
            {'item_id': 'tennents_lager', 'original_qty': 20.0, 'new_qty': 35.0, 'original_cost': 1.50, 'new_cost': 1.50},
            {'item_id': 'moretti_bottle', 'original_qty': 12.0, 'new_qty': 6.0, 'original_cost': 1.70, 'new_cost': 1.70},
        ]
        new_inv, new_log = _reverse_and_apply_delivery_edit(self.inventory, self.log, self.timestamp, entries)

        # Tennents: 100 - 20 + 35 = 115
        self.assertAlmostEqual(
            new_inv.loc[new_inv[COL_ITEM_ID] == 'tennents_lager', COL_QUANTITY].values[0],
            115.0
        )
        # Moretti: 50 - 12 + 6 = 44
        self.assertAlmostEqual(
            new_inv.loc[new_inv[COL_ITEM_ID] == 'moretti_bottle', COL_QUANTITY].values[0],
            44.0
        )

        # Log updated
        tennent_log = new_log[(new_log[COL_TIMESTAMP] == self.timestamp) & (new_log[COL_ITEM_ID] == 'tennents_lager')]
        self.assertAlmostEqual(tennent_log[COL_QUANTITY].values[0], 35.0)
        moretti_log = new_log[(new_log[COL_TIMESTAMP] == self.timestamp) & (new_log[COL_ITEM_ID] == 'moretti_bottle')]
        self.assertAlmostEqual(moretti_log[COL_QUANTITY].values[0], 6.0)


class TestDeliveryEditCostPrice(unittest.TestCase):
    """Editing a delivery's cost price updates the item's stored cost."""

    def setUp(self):
        # Use a non-converted item so cost is stored exactly as entered
        self.inventory = pd.DataFrame([
            ['moretti_bottle', 'Moretti Bottle', 50.0, 1.70, 3.80, 'Bottle', 'Beer - Bottled'],
        ], columns=[COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE, 'measure', 'category'])

        self.timestamp = '2026-08-06 12:00:00'
        self.log = pd.DataFrame([
            ['moretti_bottle', ACTION_DELIVERY, 12.0, self.timestamp, 1.70, 3.80, 'Supplier A', '', ''],
        ], columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON])

    def test_edit_cost_price_updates_inventory(self):
        entries = [
            {'item_id': 'moretti_bottle', 'original_qty': 12.0, 'new_qty': 12.0, 'original_cost': 1.70, 'new_cost': 1.85},
        ]
        new_inv, new_log = _reverse_and_apply_delivery_edit(self.inventory, self.log, self.timestamp, entries)

        # Moretti Bottle is not a converted item, so new_cost is stored as-is
        self.assertAlmostEqual(
            new_inv.loc[new_inv[COL_ITEM_ID] == 'moretti_bottle', COL_COST_PRICE].values[0],
            1.85
        )
        # Quantity unchanged
        self.assertAlmostEqual(
            new_inv.loc[new_inv[COL_ITEM_ID] == 'moretti_bottle', COL_QUANTITY].values[0],
            50.0
        )


class TestDeliveryEditConvertedItems(unittest.TestCase):
    """Editing converted items (barrels/bottles) handles per-unit cost conversion."""

    def setUp(self):
        self.inventory = pd.DataFrame([
            ['birra_moretti', 'Birra Moretti', 176.0, 1.66, 3.80, 'Pint', 'Draught'],
            ['smirnoff', 'Smirnoff', 86.0, 0.65, 2.50, '35ml', 'Spirit'],
        ], columns=[COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE, 'measure', 'category'])

        self.timestamp = '2026-08-06 12:00:00'
        # Stored as system quantities: 2 barrels = 176 pints, cost per pint = 1.66
        self.log = pd.DataFrame([
            ['birra_moretti', ACTION_DELIVERY, 176.0, self.timestamp, 1.66, 3.80, 'Supplier A', '', ''],
            ['smirnoff', ACTION_DELIVERY, 43.0, self.timestamp, 0.65, 2.50, 'Supplier A', '', ''],
        ], columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON])

    def test_edit_draught_barrel_quantity(self):
        # User edits from 2 barrels to 3 barrels; display cost was per barrel
        entries = [
            {
                'item_id': 'birra_moretti',
                'original_qty': 176.0,  # 2 barrels * 88
                'new_qty': 264.0,  # 3 barrels * 88
                'original_cost': 1.66 * 88,  # displayed as pack cost
                'new_cost': 1.66 * 88,
            },
        ]
        new_inv, _ = _reverse_and_apply_delivery_edit(self.inventory, self.log, self.timestamp, entries)

        # Birra Moretti: 176 - 176 + 264 = 264
        self.assertAlmostEqual(
            new_inv.loc[new_inv[COL_ITEM_ID] == 'birra_moretti', COL_QUANTITY].values[0],
            264.0
        )
        # Per-unit cost unchanged
        self.assertAlmostEqual(
            new_inv.loc[new_inv[COL_ITEM_ID] == 'birra_moretti', COL_COST_PRICE].values[0],
            1.66,
            places=2
        )

    def test_edit_spirit_bottle_quantity(self):
        # User edits from 1 bottle to 2 bottles; display cost per bottle
        entries = [
            {
                'item_id': 'smirnoff',
                'original_qty': 43.0,  # 1 bottle * 43
                'new_qty': 86.0,  # 2 bottles * 43
                'original_cost': 0.65 * 43,  # displayed as pack cost
                'new_cost': 0.65 * 43,
            },
        ]
        new_inv, _ = _reverse_and_apply_delivery_edit(self.inventory, self.log, self.timestamp, entries)

        # Smirnoff: 86 - 43 + 86 = 129
        self.assertAlmostEqual(
            new_inv.loc[new_inv[COL_ITEM_ID] == 'smirnoff', COL_QUANTITY].values[0],
            129.0
        )

    def test_edit_converted_cost_price(self):
        # User changes barrel cost from £146.08 to £160.00 per barrel
        entries = [
            {
                'item_id': 'birra_moretti',
                'original_qty': 176.0,
                'new_qty': 176.0,
                'original_cost': 1.66 * 88,
                'new_cost': 160.0,
            },
        ]
        new_inv, _ = _reverse_and_apply_delivery_edit(self.inventory, self.log, self.timestamp, entries)

        # Per-unit cost should be 160 / 88 = 1.8181...
        expected_per_pint = 160.0 / 88.0
        self.assertAlmostEqual(
            new_inv.loc[new_inv[COL_ITEM_ID] == 'birra_moretti', COL_COST_PRICE].values[0],
            expected_per_pint,
            places=4
        )


class TestDeliveryDelete(unittest.TestCase):
    """Deleting a delivery fully reverses its stock impact."""

    def setUp(self):
        self.inventory = pd.DataFrame([
            ['tennents_lager', 'Tennents Lager', 120.0, 1.50, 4.00, 'Pint', 'Draught'],
            ['moretti_bottle', 'Moretti Bottle', 62.0, 1.70, 3.80, 'Bottle', 'Beer - Bottled'],
        ], columns=[COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE, 'measure', 'category'])

        self.timestamp = '2026-08-06 12:00:00'
        self.log = pd.DataFrame([
            ['tennents_lager', ACTION_DELIVERY, 20.0, self.timestamp, 1.50, 4.00, 'Supplier A', '', ''],
            ['moretti_bottle', ACTION_DELIVERY, 12.0, self.timestamp, 1.70, 3.80, 'Supplier A', '', ''],
            ['tennents_lager', 'Sales', 5.0, '2026-08-06 13:00:00', 1.50, 4.00, '', '', ''],
        ], columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON])

    def test_delete_delivery_reverses_stock(self):
        items = [
            {COL_ITEM_ID: 'tennents_lager', COL_QUANTITY: 20.0},
            {COL_ITEM_ID: 'moretti_bottle', COL_QUANTITY: 12.0},
        ]
        new_inv, new_log = _delete_delivery(self.inventory, self.log, self.timestamp, items)

        # Tennents: 120 - 20 = 100
        self.assertAlmostEqual(
            new_inv.loc[new_inv[COL_ITEM_ID] == 'tennents_lager', COL_QUANTITY].values[0],
            100.0
        )
        # Moretti: 62 - 12 = 50
        self.assertAlmostEqual(
            new_inv.loc[new_inv[COL_ITEM_ID] == 'moretti_bottle', COL_QUANTITY].values[0],
            50.0
        )

        # Delivery log entries removed, sales entry remains
        delivery_count = len(new_log[(new_log[COL_TIMESTAMP] == self.timestamp) & (new_log[COL_ACTION] == ACTION_DELIVERY)])
        self.assertEqual(delivery_count, 0)
        sales_count = len(new_log[new_log[COL_ACTION] == 'Sales'])
        self.assertEqual(sales_count, 1)


class TestDeliveryEditMultiItem(unittest.TestCase):
    """Editing multiple items in one delivery updates all items correctly."""

    def setUp(self):
        self.inventory = pd.DataFrame([
            ['tennents_lager', 'Tennents Lager', 100.0, 1.50, 4.00, 'Pint', 'Draught'],
            ['belhaven_best', 'Belhaven Best', 80.0, 1.60, 4.20, 'Pint', 'Draught'],
            ['lemonade', 'Lemonade', 60.0, 0.40, 2.50, 'Pint', 'Soft'],
        ], columns=[COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE, 'measure', 'category'])

        self.timestamp = '2026-08-06 12:00:00'
        self.log = pd.DataFrame([
            ['tennents_lager', ACTION_DELIVERY, 20.0, self.timestamp, 1.50, 4.00, 'Supplier A', '', ''],
            ['belhaven_best', ACTION_DELIVERY, 10.0, self.timestamp, 1.60, 4.20, 'Supplier A', '', ''],
            ['lemonade', ACTION_DELIVERY, 5.0, self.timestamp, 0.40, 2.50, 'Supplier A', '', ''],
        ], columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON])

    def test_multi_item_edit(self):
        entries = [
            {'item_id': 'tennents_lager', 'original_qty': 20.0, 'new_qty': 25.0, 'original_cost': 1.50, 'new_cost': 1.50},
            {'item_id': 'belhaven_best', 'original_qty': 10.0, 'new_qty': 8.0, 'original_cost': 1.60, 'new_cost': 1.60},
            {'item_id': 'lemonade', 'original_qty': 5.0, 'new_qty': 12.0, 'original_cost': 0.40, 'new_cost': 0.40},
        ]
        new_inv, new_log = _reverse_and_apply_delivery_edit(self.inventory, self.log, self.timestamp, entries)

        self.assertAlmostEqual(
            new_inv.loc[new_inv[COL_ITEM_ID] == 'tennents_lager', COL_QUANTITY].values[0],
            105.0  # 100 - 20 + 25
        )
        self.assertAlmostEqual(
            new_inv.loc[new_inv[COL_ITEM_ID] == 'belhaven_best', COL_QUANTITY].values[0],
            78.0  # 80 - 10 + 8
        )
        self.assertAlmostEqual(
            new_inv.loc[new_inv[COL_ITEM_ID] == 'lemonade', COL_QUANTITY].values[0],
            67.0  # 60 - 5 + 12
        )

        for item_id, expected_qty in [('tennents_lager', 25.0), ('belhaven_best', 8.0), ('lemonade', 12.0)]:
            item_log = new_log[(new_log[COL_TIMESTAMP] == self.timestamp) & (new_log[COL_ITEM_ID] == item_id)]
            self.assertAlmostEqual(item_log[COL_QUANTITY].values[0], expected_qty)


if __name__ == '__main__':
    unittest.main()
