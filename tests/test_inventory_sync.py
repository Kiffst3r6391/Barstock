#!/usr/bin/env python3
"""
Unit tests for inventory_sync helpers.
"""

import os
import sys
import unittest
import tempfile
import csv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
from inventory_sync import (
    find_missing_mappings,
    has_sync_issues,
    find_untracked_items_on_order_sheet,
    append_item_to_items_csv,
    find_items_csv_inventory_mismatches,
)

COL_ITEM_ID = 'item_id'
COL_ITEM_NAME = 'item_name'
COL_QUANTITY = 'quantity'
COL_MEASURE = 'measure'
COL_CATEGORY = 'category'


class TestFindMissingMappings(unittest.TestCase):
    def setUp(self):
        self.inventory = pd.DataFrame([
            ['glen_scotia', 'Glen Scotia', 30.0, '35ml', 'Spirits'],
            ['unknown_item', 'Unknown Item', 10.0, 'PINT', 'Spirits'],
            ['tennents_lager', 'Tennents Lager', 100.0, 'PINT', 'Beers'],
        ], columns=[COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_MEASURE, COL_CATEGORY])

    def test_known_item_has_no_missing_mappings(self):
        missing = find_missing_mappings(self.inventory)
        glen = [m for m in missing['missing_conversion'] if m['item_id'] == 'glen_scotia']
        self.assertEqual(len(glen), 0)

    def test_unknown_item_flagged_everywhere(self):
        missing = find_missing_mappings(self.inventory)
        self.assertTrue(any(m['item_id'] == 'unknown_item' for m in missing['missing_conversion']))
        self.assertTrue(any(m['item_id'] == 'unknown_item' for m in missing['missing_category']))
        self.assertTrue(any(m['item_id'] == 'unknown_item' for m in missing['missing_order_sheet']))

    def test_has_sync_issues_true_when_missing(self):
        missing = find_missing_mappings(self.inventory)
        self.assertTrue(has_sync_issues(missing))


class TestUntrackedOrderSheetItems(unittest.TestCase):
    def setUp(self):
        self.inventory = pd.DataFrame([
            ['glen_scotia', 'Glen Scotia', 30.0, '35ml', 'Spirits'],
        ], columns=[COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_MEASURE, COL_CATEGORY])

    def test_glen_scotia_no_longer_orphan(self):
        orphans = find_untracked_items_on_order_sheet(self.inventory)
        self.assertFalse(any(d == 'Glen Scotia' for _s, _c, d in orphans))


class TestAppendItemToItemsCsv(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        path = os.path.join(self.tmpdir, 'Items.csv')
        if os.path.exists(path):
            os.remove(path)
        os.rmdir(self.tmpdir)

    def test_appends_new_item(self):
        result = append_item_to_items_csv(
            script_dir=self.tmpdir,
            item_id='new_item',
            item_name='New Item',
            division='Spirits',
            measure='BOTTLE',
            quantity=5.0,
            total_value=50.0,
        )
        self.assertTrue(result)
        path = os.path.join(self.tmpdir, 'Items.csv')
        self.assertTrue(os.path.exists(path))
        with open(path, 'r') as f:
            reader = csv.reader(f)
            rows = list(reader)
        self.assertEqual(rows[0], ["Name", "Division", "Unit", "Total Stock", "Total Value", "Active", "Min Alert", "Max Alert"])
        self.assertEqual(rows[1][0], "New Item")
        self.assertEqual(rows[1][2], "BOTTLE")

    def test_does_not_duplicate(self):
        append_item_to_items_csv(
            script_dir=self.tmpdir,
            item_id='new_item',
            item_name='New Item',
            division='Spirits',
            measure='BOTTLE',
            quantity=5.0,
            total_value=50.0,
        )
        result = append_item_to_items_csv(
            script_dir=self.tmpdir,
            item_id='new_item',
            item_name='New Item',
            division='Spirits',
            measure='BOTTLE',
            quantity=5.0,
            total_value=50.0,
        )
        self.assertFalse(result)


class TestCsvInventoryMismatches(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        path = os.path.join(self.tmpdir, 'Items.csv')
        with open(path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Name", "Division", "Unit", "Total Stock", "Total Value", "Active", "Min Alert", "Max Alert"])
            writer.writerow(["Glen Scotia", "Malt Whisky", "BOTTLE", "1.5", "30.60", "", "0", "0"])
            writer.writerow(["Missing From DB", "Spirits", "BOTTLE", "0", "0.00", "", "0", "0"])

    def tearDown(self):
        path = os.path.join(self.tmpdir, 'Items.csv')
        if os.path.exists(path):
            os.remove(path)
        os.rmdir(self.tmpdir)

    def test_detects_mismatches(self):
        inventory = pd.DataFrame([
            ['glen_scotia', 'Glen Scotia', 30.0, '35ml', 'Spirits'],
            ['not_in_csv', 'Not In CSV', 10.0, 'BOTTLE', 'Spirits'],
        ], columns=[COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_MEASURE, COL_CATEGORY])
        result = find_items_csv_inventory_mismatches(inventory, self.tmpdir)
        self.assertIn('not_in_csv', result['in_inventory_not_csv'])
        self.assertIn('missing_from_db', result['in_csv_not_inventory'])


if __name__ == '__main__':
    unittest.main()
