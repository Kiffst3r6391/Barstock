#!/usr/bin/env python3
"""
Unit tests for Bar Stock Management sales and parent-stock logic.

These tests use in-memory pandas DataFrames and do NOT touch the live SQLite
database or the user's data files. They can be run with pytest or directly:

    cd "/Users/kiffy/PGC Barstock"
    python3 tests/test_add_sales.py
"""

import os
import sys
import unittest

# Ensure project modules are importable when running from tests/
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from sales_mapping import (
    normalize_product_name,
    apply_sale_to_parent,
    check_apply_sale_to_parent,
    has_parent_stock,
    get_parent_for_sale,
)
from categories import get_category, should_exclude

COL_ITEM_ID = 'item_id'
COL_ITEM_NAME = 'item_name'
COL_QUANTITY = 'quantity'
COL_COST_PRICE = 'cost_price'
COL_SELL_PRICE = 'sell_price'
COL_ALLOW_NEGATIVE = 'allow_negative'


class TestProductNameNormalization(unittest.TestCase):
    def test_basic_names(self):
        self.assertEqual(normalize_product_name("Tennents Lager"), "tennents_lager")
        self.assertEqual(normalize_product_name("Birra Morettiu"), "birra_moretti")
        self.assertEqual(normalize_product_name("Orange & Lemonade"), "orange_lemonade")
        self.assertEqual(normalize_product_name("Carton Juice - Half"), "carton_juice_half")
        self.assertEqual(normalize_product_name("Inch's"), "inchs")
        self.assertEqual(normalize_product_name("Fevertree Tonic"), "fevertree_tonic")


class TestParentStockDeduction(unittest.TestCase):
    def setUp(self):
        self.inventory = pd.DataFrame([
            {
                COL_ITEM_ID: 'tennents_lager',
                COL_ITEM_NAME: 'Tennents Lager',
                COL_QUANTITY: 100.0,
                COL_COST_PRICE: 1.50,
                COL_SELL_PRICE: 3.50,
                COL_ALLOW_NEGATIVE: False,
            },
            {
                COL_ITEM_ID: 'tennents_lager_half',
                COL_ITEM_NAME: 'Tennents Lager - Half',
                COL_QUANTITY: 0.0,
                COL_COST_PRICE: 0.75,
                COL_SELL_PRICE: 1.75,
                COL_ALLOW_NEGATIVE: False,
            },
            {
                COL_ITEM_ID: 'lemonade',
                COL_ITEM_NAME: 'Lemonade',
                COL_QUANTITY: 50.0,
                COL_COST_PRICE: 0.30,
                COL_SELL_PRICE: 0.80,
                COL_ALLOW_NEGATIVE: False,
            },
            {
                COL_ITEM_ID: 'tennants_shandy_pint',
                COL_ITEM_NAME: 'Tennants Shandy Pint',
                COL_QUANTITY: 0.0,
                COL_COST_PRICE: 0.90,
                COL_SELL_PRICE: 2.00,
                COL_ALLOW_NEGATIVE: False,
            },
        ])

    def test_half_pint_deducts_from_parent(self):
        self.assertTrue(has_parent_stock('tennents_lager_half'))
        adj = apply_sale_to_parent(
            'tennents_lager_half', 4, self.inventory,
            COL_ITEM_ID, COL_QUANTITY
        )
        self.assertEqual(len(adj), 1)
        self.assertEqual(adj[0][0], 'tennents_lager')
        self.assertAlmostEqual(adj[0][1], 2.0)
        tennents_qty = self.inventory.loc[self.inventory[COL_ITEM_ID] == 'tennents_lager', COL_QUANTITY].values[0]
        self.assertAlmostEqual(tennents_qty, 98.0)

    def test_shandy_deducts_from_both_parents(self):
        self.assertTrue(has_parent_stock('tennants_shandy_pint'))
        adj = apply_sale_to_parent(
            'tennants_shandy_pint', 4, self.inventory,
            COL_ITEM_ID, COL_QUANTITY
        )
        self.assertEqual(len(adj), 2)
        parent_ids = {a[0] for a in adj}
        self.assertEqual(parent_ids, {'tennents_lager', 'lemonade'})
        for _, amount, _ in adj:
            self.assertAlmostEqual(amount, 2.0)
        tennents_qty = self.inventory.loc[self.inventory[COL_ITEM_ID] == 'tennents_lager', COL_QUANTITY].values[0]
        lemonade_qty = self.inventory.loc[self.inventory[COL_ITEM_ID] == 'lemonade', COL_QUANTITY].values[0]
        self.assertAlmostEqual(tennents_qty, 98.0)
        self.assertAlmostEqual(lemonade_qty, 48.0)

    def test_parent_negative_guard_blocks(self):
        # Empty the parent stock so half-pint sale should be blocked.
        self.inventory.loc[self.inventory[COL_ITEM_ID] == 'tennents_lager', COL_QUANTITY] = 1.0
        ok, issues = check_apply_sale_to_parent(
            'tennents_lager_half', 4, self.inventory,
            COL_ITEM_ID, COL_QUANTITY, COL_ALLOW_NEGATIVE
        )
        self.assertFalse(ok)
        self.assertTrue(any('tennents_lager' in msg for msg in issues))

    def test_parent_negative_guard_allows_if_allowed(self):
        self.inventory.loc[self.inventory[COL_ITEM_ID] == 'tennents_lager', COL_ALLOW_NEGATIVE] = True
        self.inventory.loc[self.inventory[COL_ITEM_ID] == 'tennents_lager', COL_QUANTITY] = 1.0
        ok, issues = check_apply_sale_to_parent(
            'tennents_lager_half', 4, self.inventory,
            COL_ITEM_ID, COL_QUANTITY, COL_ALLOW_NEGATIVE
        )
        self.assertTrue(ok)
        self.assertEqual(issues, [])


class TestSalesUploadSimulation(unittest.TestCase):
    def setUp(self):
        self.inventory = pd.DataFrame([
            {
                COL_ITEM_ID: 'tennents_lager',
                COL_ITEM_NAME: 'Tennents Lager',
                COL_QUANTITY: 100.0,
                COL_COST_PRICE: 1.50,
                COL_SELL_PRICE: 3.50,
                COL_ALLOW_NEGATIVE: False,
            },
            {
                COL_ITEM_ID: 'birra_moretti',
                COL_ITEM_NAME: 'Birra Moretti',
                COL_QUANTITY: 50.0,
                COL_COST_PRICE: 1.60,
                COL_SELL_PRICE: 3.80,
                COL_ALLOW_NEGATIVE: False,
            },
            {
                COL_ITEM_ID: 'tennents_lager_half',
                COL_ITEM_NAME: 'Tennents Lager - Half',
                COL_QUANTITY: 0.0,
                COL_COST_PRICE: 0.75,
                COL_SELL_PRICE: 1.75,
                COL_ALLOW_NEGATIVE: False,
            },
        ])
        self.log = pd.DataFrame(columns=[
            COL_ITEM_ID, 'action', COL_QUANTITY, 'timestamp',
            COL_COST_PRICE, COL_SELL_PRICE
        ])

    def test_upload_simulation_deducts_stock(self):
        sales = [
            ('Tennents Lager', 10),
            ('Birra Moretti', 5),
        ]
        for product_name, qty in sales:
            item_id = normalize_product_name(product_name)
            item_id = item_id  # resolve_epos_item_id would be called in real app
            self.inventory.loc[self.inventory[COL_ITEM_ID] == item_id, COL_QUANTITY] -= qty

        self.assertAlmostEqual(
            self.inventory.loc[self.inventory[COL_ITEM_ID] == 'tennents_lager', COL_QUANTITY].values[0],
            90.0
        )
        self.assertAlmostEqual(
            self.inventory.loc[self.inventory[COL_ITEM_ID] == 'birra_moretti', COL_QUANTITY].values[0],
            45.0
        )

    def test_upload_simulation_parent_negative_is_blocked(self):
        # Set parent stock too low to cover half-pint sales.
        self.inventory.loc[self.inventory[COL_ITEM_ID] == 'tennents_lager', COL_QUANTITY] = 1.0
        item_id = 'tennents_lager_half'
        qty = 4

        ok, issues = check_apply_sale_to_parent(
            item_id, qty, self.inventory,
            COL_ITEM_ID, COL_QUANTITY, COL_ALLOW_NEGATIVE
        )
        self.assertFalse(ok)

        # Because the guard blocks, no stock should be deducted.
        parent_qty = self.inventory.loc[self.inventory[COL_ITEM_ID] == 'tennents_lager', COL_QUANTITY].values[0]
        self.assertAlmostEqual(parent_qty, 1.0)

    def test_effective_sell_price_handles_none_csv_revenue(self):
        """Regression: missing/None CSV revenue must not crash with None / float."""
        preview = {'qty': 5.0, 'sell': 3.50, 'csv_revenue': None}
        quantity = preview['qty']
        sell_price = preview['sell']
        csv_revenue = preview.get('csv_revenue')
        effective_sell_price = (csv_revenue / quantity if quantity > 0 and csv_revenue is not None else sell_price)
        if not (effective_sell_price > 0 and csv_revenue is not None):
            effective_sell_price = sell_price
        self.assertAlmostEqual(effective_sell_price, sell_price)

    def test_effective_sell_price_uses_csv_revenue_when_present(self):
        preview = {'qty': 4.0, 'sell': 3.50, 'csv_revenue': 16.0}
        quantity = preview['qty']
        sell_price = preview['sell']
        csv_revenue = preview.get('csv_revenue')
        effective_sell_price = (csv_revenue / quantity if quantity > 0 and csv_revenue is not None else sell_price)
        if not (effective_sell_price > 0 and csv_revenue is not None):
            effective_sell_price = sell_price
        self.assertAlmostEqual(effective_sell_price, 4.0)


class TestFourTupleParentMapping(unittest.TestCase):
    """Regression test for mappings with an optional 4th visibility element."""

    def setUp(self):
        self.inventory = pd.DataFrame([
            {
                COL_ITEM_ID: 'aperol',
                COL_ITEM_NAME: 'Aperol',
                COL_QUANTITY: 20.0,
                COL_COST_PRICE: 0.80,
                COL_SELL_PRICE: 2.50,
                COL_ALLOW_NEGATIVE: False,
            },
            {
                COL_ITEM_ID: 'prosecco_single_serve',
                COL_ITEM_NAME: 'Prosecco Single Serve',
                COL_QUANTITY: 30.0,
                COL_COST_PRICE: 1.20,
                COL_SELL_PRICE: 4.00,
                COL_ALLOW_NEGATIVE: False,
            },
            {
                COL_ITEM_ID: 'aperol_spritz',
                COL_ITEM_NAME: 'Aperol Spritz',
                COL_QUANTITY: 0.0,
                COL_COST_PRICE: 2.00,
                COL_SELL_PRICE: 6.00,
                COL_ALLOW_NEGATIVE: False,
            },
        ])

    def test_four_tuple_mapping_deducts_from_parents(self):
        """A mapping with a 4th visibility element must still unpack safely."""
        from unittest.mock import patch
        from sales_mapping import SALES_TO_PARENT, is_hidden_from_stock_view

        four_tuple_mapping = (['aperol', 'prosecco_single_serve'], [50/35, 1.0], 'Aperol Spritz', True)
        with patch.dict(SALES_TO_PARENT, {'aperol_spritz': four_tuple_mapping}):
            self.assertTrue(has_parent_stock('aperol_spritz'))
            # 4th element True means it should remain visible in stock view
            self.assertFalse(is_hidden_from_stock_view('aperol_spritz'))

            ok, issues = check_apply_sale_to_parent(
                'aperol_spritz', 2, self.inventory,
                COL_ITEM_ID, COL_QUANTITY, COL_ALLOW_NEGATIVE
            )
            self.assertTrue(ok)
            self.assertEqual(issues, [])

            adj = apply_sale_to_parent(
                'aperol_spritz', 2, self.inventory,
                COL_ITEM_ID, COL_QUANTITY
            )
            self.assertEqual(len(adj), 2)

            aperol_qty = self.inventory.loc[self.inventory[COL_ITEM_ID] == 'aperol', COL_QUANTITY].values[0]
            prosecco_qty = self.inventory.loc[self.inventory[COL_ITEM_ID] == 'prosecco_single_serve', COL_QUANTITY].values[0]
            self.assertAlmostEqual(aperol_qty, 20.0 - (100/35))  # 2 * 50/35
            self.assertAlmostEqual(prosecco_qty, 28.0)


class TestCategoryMapping(unittest.TestCase):
    def test_known_items_have_category(self):
        self.assertIsNotNone(get_category('tennents_lager'))
        self.assertIsNotNone(get_category('smirnoff'))

    def test_excluded_items(self):
        self.assertTrue(should_exclude('pint'))
        self.assertTrue(should_exclude('half_pint'))


if __name__ == '__main__':
    unittest.main()