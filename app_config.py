#!/usr/bin/env python3
"""Shared configuration: data locations and the stock/log schema.

These values used to live at the top of ``BarStockApp``.  Screens now import
them from here so that no screen module has to import the application module
(which would be circular).
"""

import os
import sys
from pathlib import Path

import club_profile


def get_resource_path():
    """Return the per-user data directory for the active club profile."""
    profile = club_profile.get_profile()
    data_dir = club_profile.resolve_data_dir(profile)
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def get_script_directory():
    """Return the script directory, also inside a PyInstaller bundle."""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


# Live data directory and its CSV mirrors (never bundled with the app).
DATA_DIR = get_resource_path()
INVENTORY_FILE = os.path.join(DATA_DIR, 'stock.csv')
LOG_FILE = os.path.join(DATA_DIR, 'transaction_log.csv')
ITEMS_FILE = os.path.join(DATA_DIR, 'Items.csv')


def get_items_csv_path():
    """Return the Items.csv master path.

    The live master belongs in the data directory. In a source checkout the
    repository file is still accepted when no data-dir master exists yet.
    """
    if os.path.exists(ITEMS_FILE):
        return ITEMS_FILE
    if not getattr(sys, 'frozen', False):
        checkout = os.path.join(get_script_directory(), 'Items.csv')
        if os.path.exists(checkout):
            return checkout
    return ITEMS_FILE


def get_downloads_dir():
    """Return a writable export directory, preferring the user's Downloads."""
    downloads = os.path.expanduser('~/Downloads')
    try:
        os.makedirs(downloads, exist_ok=True)
        if os.access(downloads, os.W_OK):
            return downloads
    except OSError:
        pass
    fallback = os.path.join(DATA_DIR, 'exports')
    os.makedirs(fallback, exist_ok=True)
    return fallback


def sqlite_ro_uri(path):
    """Build a read-only SQLite URI that works with Windows paths and spaces."""
    return Path(path).resolve().as_uri() + '?mode=ro'


def format_day_of_month(value):
    """Return the day without a leading zero (Windows-safe %-d replacement)."""
    return str(value.day)


def format_day_month(value):
    return f"{value.day} {value.strftime('%b')}"


def format_day_month_year(value):
    return f"{value.day} {value.strftime('%b %Y')}"


def format_weekday_day_month(value):
    return f"{value.strftime('%A')} {value.day} {value.strftime('%B')}"

# Column constants to avoid typos.
COL_ITEM_ID = 'item_id'
COL_ITEM_NAME = 'item_name'
COL_QUANTITY = 'quantity'
COL_COST_PRICE = 'cost_price'
COL_SELL_PRICE = 'sell_price'
COL_MEASURE = 'measure'
COL_CATEGORY = 'category'
COL_DIVISION = 'division'
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
