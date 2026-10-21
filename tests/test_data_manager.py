#!/usr/bin/env python3
"""
Unit tests for data_manager CSV / DB sync behaviour.
"""

import os
import sys
import unittest
import tempfile
import sqlite3
import csv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

import pandas as pd
import data_manager as dm


class TestCsvToDbSyncPreservesQuantity(unittest.TestCase):
    """The bundled stock.csv must update metadata/prices but never overwrite
    the transaction-driven quantity of an existing DB item."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, 'test.db')
        # _get_connection() reads the module-level DB_PATH, not a _DB_PATH.
        self.original_db_path = getattr(dm, 'DB_PATH', None)
        self.original_inventory_file = getattr(dm, 'INVENTORY_FILE', None)
        # Point data_manager at our temp DB.
        dm.DB_PATH = self.db_path
        dm.INVENTORY_FILE = os.path.join(self.tmpdir, 'stock.csv')

    def tearDown(self):
        if self.original_db_path is not None:
            dm.DB_PATH = self.original_db_path
        if self.original_inventory_file is not None:
            dm.INVENTORY_FILE = self.original_inventory_file

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self):
        conn = self._connect()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS inventory (
                item_id TEXT PRIMARY KEY,
                item_name TEXT,
                quantity REAL DEFAULT 0,
                cost_price REAL DEFAULT 0,
                sell_price REAL DEFAULT 0,
                measure TEXT,
                category TEXT,
                price_locked INTEGER DEFAULT 0,
                allow_negative INTEGER DEFAULT 1,
                reorder_level REAL DEFAULT 0,
                division TEXT
            )
        ''')
        conn.commit()
        conn.close()

    def _write_stock_csv(self, rows):
        path = dm.INVENTORY_FILE
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(dm.INVENTORY_COLUMNS)
            for r in rows:
                writer.writerow(r)

    def test_existing_item_quantity_is_not_overwritten(self):
        """A stale bundled CSV must not erase sales/delivery-driven quantity."""
        self._init_schema()
        conn = self._connect()
        conn.execute('''
            INSERT INTO inventory (item_id, item_name, quantity, cost_price, sell_price,
                                   measure, category, price_locked, allow_negative)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', ('tennents_lager', 'Tennents Lager', 519.4, 1.27, 4.33, 'Pint', 'Draught', 1, 1))
        conn.commit()
        conn.close()

        # Simulate a stale bundled CSV that still says 290.4.
        self._write_stock_csv([
            ['tennents_lager', 'Tennents Lager', 290.4, 1.50, 4.33, 'Pint', 'Draught', 'True', 'True', 0.0, '']
        ])

        # Force bundled-app path.
        original_frozen = getattr(sys, 'frozen', False)
        sys.frozen = True
        try:
            conn = self._connect()
            dm._sync_inventory_from_csv(conn)
            conn.close()
        finally:
            sys.frozen = original_frozen

        conn = self._connect()
        cur = conn.cursor()
        cur.execute("SELECT quantity, cost_price FROM inventory WHERE item_id='tennents_lager'")
        row = cur.fetchone()
        conn.close()

        self.assertAlmostEqual(row[0], 519.4, places=2,
                               msg="Transaction-driven quantity must survive CSV sync")
        self.assertAlmostEqual(row[1], 1.50, places=2,
                               msg="Cost price should still be updated from CSV")

    def test_new_item_gets_csv_quantity(self):
        """A brand-new item seeded from CSV should get its starting quantity."""
        self._init_schema()
        self._write_stock_csv([
            ['new_keg', 'New Keg', 88.0, 2.00, 5.00, 'Pint', 'Draught', 'True', 'True', 0.0, '']
        ])

        original_frozen = getattr(sys, 'frozen', False)
        sys.frozen = True
        try:
            conn = self._connect()
            dm._sync_inventory_from_csv(conn)
            conn.close()
        finally:
            sys.frozen = original_frozen

        conn = self._connect()
        cur = conn.cursor()
        cur.execute("SELECT quantity FROM inventory WHERE item_id='new_keg'")
        row = cur.fetchone()
        conn.close()

        self.assertAlmostEqual(row[0], 88.0, places=2,
                               msg="New item should inherit quantity from bundled CSV")


if __name__ == '__main__':
    unittest.main()
