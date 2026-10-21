#!/usr/bin/env python3
"""Shared configuration: data locations and the stock/log schema.

These values used to live at the top of ``BarStockApp``.  Screens now import
them from here so that no screen module has to import the application module
(which would be circular).
"""

import os
import sys


def get_resource_path():
    """Return the Application Support directory used for live data."""
    app_support_path = os.path.expanduser('~/Library/Application Support/BarStockManagement')
    os.makedirs(app_support_path, exist_ok=True)
    return app_support_path


def get_script_directory():
    """Return the script directory, also inside a PyInstaller bundle."""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


# Live data directory and its CSV mirrors (never bundled with the app).
DATA_DIR = get_resource_path()
INVENTORY_FILE = os.path.join(DATA_DIR, 'stock.csv')
LOG_FILE = os.path.join(DATA_DIR, 'transaction_log.csv')

# Column constants to avoid typos.
COL_ITEM_ID = 'item_id'
COL_ITEM_NAME = 'item_name'
COL_QUANTITY = 'quantity'
COL_COST_PRICE = 'cost_price'
COL_SELL_PRICE = 'sell_price'
COL_MEASURE = 'measure'
COL_CATEGORY = 'category'
COL_ACTION = 'action'
COL_TIMESTAMP = 'timestamp'
COL_SUPPLIER = 'supplier'
COL_DATE_RANGE = 'date_range'
COL_PRICE_LOCKED = 'price_locked'
COL_REASON = 'reason'

# Dropdown options.
MEASURE_OPTIONS = ['Pint', 'Half Pint', '35ml', 'Bottle', 'Can', 'Pack']
CATEGORY_OPTIONS = ['Draught', 'Bottle', 'Spirit', 'Can', 'Soft', 'Snack', 'Wine']
DIVISION_OPTIONS = ['Beer - Draught', 'Beer - Bottled', 'Spirits', 'Soft Drinks',
                    'Post Mix', 'Mineral', 'Wine', 'Snacks', 'Other']
