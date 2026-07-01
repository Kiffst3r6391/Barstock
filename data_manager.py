"""
Bar Stock Data Manager - SQLite-backed data persistence layer.

Provides the same interface as the original InventoryDataManager
but uses SQLite for atomic transactions and data integrity.
"""

import sqlite3
import os
import sys
import shutil
import glob
import pandas as pd
from tkinter import messagebox
from datetime import datetime

from conversions import convert_to_system

# Column constants (must match BarStockApp.py)
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
COL_ALLOW_NEGATIVE = 'allow_negative'
COL_REORDER_LEVEL = 'reorder_level'
COL_MEMBER_QTY = 'member_qty'
COL_NON_MEMBER_QTY = 'non_member_qty'
COL_OPEN_TAB_ID = 'open_tab_id'

INVENTORY_COLUMNS = [
    COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE,
    COL_MEASURE, COL_CATEGORY, COL_PRICE_LOCKED, COL_ALLOW_NEGATIVE, COL_REORDER_LEVEL,
    COL_DIVISION
]

LOG_COLUMNS = [
    COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE,
    COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON,
    COL_MEMBER_QTY, COL_NON_MEMBER_QTY, COL_OPEN_TAB_ID
]


def get_resource_path():
    """Get the correct path for data files."""
    app_support_path = os.path.expanduser('~/Library/Application Support/BarStockManagement')
    os.makedirs(app_support_path, exist_ok=True)
    return app_support_path


def get_script_directory():
    """Get the directory where the script/app is located."""
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    else:
        return os.path.dirname(os.path.abspath(__file__))


DATA_DIR = get_resource_path()
DB_PATH = os.path.join(DATA_DIR, 'barstock.db')
INVENTORY_FILE = os.path.join(DATA_DIR, 'stock.csv')
LOG_FILE = os.path.join(DATA_DIR, 'transaction_log.csv')


def _get_connection():
    """Get a SQLite connection with proper settings."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _init_db_schema(conn):
    """Initialize the database schema."""
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS inventory (
            item_id TEXT PRIMARY KEY,
            item_name TEXT NOT NULL,
            quantity REAL DEFAULT 0,
            cost_price REAL DEFAULT 0,
            sell_price REAL DEFAULT 0,
            measure TEXT DEFAULT '',
            category TEXT DEFAULT '',
            price_locked INTEGER DEFAULT 0,
            allow_negative INTEGER DEFAULT 0,
            reorder_level REAL DEFAULT 0,
            division TEXT DEFAULT ''
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id TEXT NOT NULL,
            action TEXT NOT NULL,
            quantity REAL NOT NULL,
            timestamp TEXT NOT NULL,
            cost_price REAL DEFAULT 0,
            sell_price REAL DEFAULT 0,
            supplier TEXT DEFAULT '',
            date_range TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            user TEXT DEFAULT '',
            member_qty REAL,
            non_member_qty REAL,
            open_tab_id INTEGER DEFAULT NULL
        )
    """)

    # Add new columns to existing tables (backward compat)
    cursor.execute("PRAGMA table_info(transactions)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if 'member_qty' not in existing_cols:
        cursor.execute("ALTER TABLE transactions ADD COLUMN member_qty REAL DEFAULT 0")
    if 'non_member_qty' not in existing_cols:
        cursor.execute("ALTER TABLE transactions ADD COLUMN non_member_qty REAL DEFAULT 0")
    if 'open_tab_id' not in existing_cols:
        cursor.execute("ALTER TABLE transactions ADD COLUMN open_tab_id INTEGER DEFAULT NULL")

    cursor.execute("PRAGMA table_info(inventory)")
    existing_inv_cols = {row[1] for row in cursor.fetchall()}
    if 'division' not in existing_inv_cols:
        cursor.execute("ALTER TABLE inventory ADD COLUMN division TEXT DEFAULT ''")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS open_tabs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            closed_at TEXT DEFAULT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stocktake_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id TEXT NOT NULL,
            counted_quantity REAL NOT NULL,
            expected_quantity REAL NOT NULL,
            variance REAL NOT NULL,
            timestamp TEXT NOT NULL,
            note TEXT DEFAULT ''
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocktake_item_id ON stocktake_snapshots(item_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_stocktake_timestamp ON stocktake_snapshots(timestamp)")

    # Archive table for baseline resets
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transaction_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id TEXT NOT NULL,
            action TEXT NOT NULL,
            quantity REAL NOT NULL,
            timestamp TEXT NOT NULL,
            cost_price REAL DEFAULT 0,
            sell_price REAL DEFAULT 0,
            supplier TEXT DEFAULT '',
            date_range TEXT DEFAULT '',
            reason TEXT DEFAULT '',
            user TEXT DEFAULT '',
            member_qty REAL,
            non_member_qty REAL,
            open_tab_id INTEGER DEFAULT NULL,
            archived_at TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_archive_timestamp ON transaction_archive(timestamp)")

    # Index for fast transaction queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_item_id ON transactions(item_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_timestamp ON transactions(timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_action ON transactions(action)")

    conn.commit()


def _migrate_from_csv(conn):
    """Migrate existing CSV data into SQLite on first run."""
    cursor = conn.cursor()

    # Check if we already have data
    cursor.execute("SELECT COUNT(*) FROM inventory")
    if cursor.fetchone()[0] > 0:
        return  # Already migrated

    # Migrate inventory
    if os.path.exists(INVENTORY_FILE):
        try:
            df = pd.read_csv(INVENTORY_FILE)
            if not df.empty:
                # Backwards compatibility columns
                if COL_PRICE_LOCKED not in df.columns:
                    df[COL_PRICE_LOCKED] = False
                if COL_ALLOW_NEGATIVE not in df.columns:
                    df[COL_ALLOW_NEGATIVE] = True  # Preserve existing behavior for old data
                if COL_REORDER_LEVEL not in df.columns:
                    df[COL_REORDER_LEVEL] = 0

                df = _validate_inventory(df)

                for _, row in df.iterrows():
                    item_id = str(row[COL_ITEM_ID])
                    # Convert initial stock from input units (bottles/boxes) to system units (measures/pints)
                    system_quantity = convert_to_system(item_id, float(row[COL_QUANTITY]))
                    cursor.execute("""
                        INSERT OR REPLACE INTO inventory
                        (item_id, item_name, quantity, cost_price, sell_price, measure, category, price_locked, allow_negative, reorder_level, division)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        item_id,
                        str(row[COL_ITEM_NAME]),
                        system_quantity,
                        float(row[COL_COST_PRICE]),
                        float(row[COL_SELL_PRICE]),
                        str(row.get(COL_MEASURE, '')),
                        str(row.get(COL_CATEGORY, '')),
                        int(bool(row[COL_PRICE_LOCKED])),
                        int(bool(row.get(COL_ALLOW_NEGATIVE, True))),
                        float(row.get(COL_REORDER_LEVEL, 0)),
                        str(row.get(COL_DIVISION, ''))
                    ))
                conn.commit()
                print(f"Migrated {len(df)} inventory items from CSV")
        except Exception as e:
            print(f"Warning: Could not migrate inventory CSV: {e}")

    # Migrate transaction log
    if os.path.exists(LOG_FILE):
        try:
            df = pd.read_csv(LOG_FILE)
            if not df.empty:
                if COL_DATE_RANGE not in df.columns:
                    df[COL_DATE_RANGE] = ""
                if COL_REASON not in df.columns:
                    df[COL_REASON] = ""
                if COL_MEMBER_QTY not in df.columns:
                    df[COL_MEMBER_QTY] = 0.0
                if COL_NON_MEMBER_QTY not in df.columns:
                    df[COL_NON_MEMBER_QTY] = 0.0

                for _, row in df.iterrows():
                    item_id = str(row[COL_ITEM_ID])
                    action = str(row[COL_ACTION])
                    raw_qty = float(row[COL_QUANTITY])
                    # Convert deliveries from input units to system units; sales/wastage/etc are already in system units
                    if action.lower() == 'delivery':
                        system_qty = convert_to_system(item_id, raw_qty)
                    else:
                        system_qty = raw_qty
                    cursor.execute("""
                        INSERT INTO transactions
                        (item_id, action, quantity, timestamp, cost_price, sell_price, supplier, date_range, reason, member_qty, non_member_qty)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        item_id,
                        action,
                        system_qty,
                        str(row[COL_TIMESTAMP]),
                        float(row.get(COL_COST_PRICE, 0)),
                        float(row.get(COL_SELL_PRICE, 0)),
                        str(row.get(COL_SUPPLIER, '')),
                        str(row.get(COL_DATE_RANGE, '')),
                        str(row.get(COL_REASON, '')),
                        float(row.get(COL_MEMBER_QTY, 0)),
                        float(row.get(COL_NON_MEMBER_QTY, 0))
                    ))
                conn.commit()
                print(f"Migrated {len(df)} transactions from CSV")
        except Exception as e:
            print(f"Warning: Could not migrate log CSV: {e}")

    # Rename CSVs after migration
    try:
        if os.path.exists(INVENTORY_FILE):
            os.rename(INVENTORY_FILE, INVENTORY_FILE + '.bak')
        if os.path.exists(LOG_FILE):
            os.rename(LOG_FILE, LOG_FILE + '.bak')
    except Exception as e:
        print(f"Warning: Could not rename CSV backups: {e}")


def _rows_to_dataframe(rows, columns):
    """Convert SQLite rows to a pandas DataFrame."""
    if not rows:
        return pd.DataFrame(columns=columns)
    data = [dict(row) for row in rows]
    df = pd.DataFrame(data, columns=columns)
    # Restore boolean columns
    if COL_PRICE_LOCKED in df.columns:
        df[COL_PRICE_LOCKED] = df[COL_PRICE_LOCKED].astype(bool)
    if COL_ALLOW_NEGATIVE in df.columns:
        df[COL_ALLOW_NEGATIVE] = df[COL_ALLOW_NEGATIVE].astype(bool)
    # Ensure open_tab_id is numeric (nullable)
    if COL_OPEN_TAB_ID in df.columns:
        df[COL_OPEN_TAB_ID] = pd.to_numeric(df[COL_OPEN_TAB_ID], errors='coerce')
    return df


def _validate_inventory(df):
    """Validate and fix inventory data (same as original)."""
    if df.empty:
        return df

    numeric_cols = [COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE, COL_REORDER_LEVEL]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

    bool_cols = [COL_PRICE_LOCKED, COL_ALLOW_NEGATIVE]
    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].fillna(False).astype(bool)

    if COL_MEASURE in df.columns:
        df[COL_MEASURE] = df[COL_MEASURE].fillna('')
    if COL_CATEGORY in df.columns:
        df[COL_CATEGORY] = df[COL_CATEGORY].fillna('')
    if COL_DIVISION in df.columns:
        df[COL_DIVISION] = df[COL_DIVISION].fillna('')

    if COL_ITEM_ID in df.columns:
        df = df.drop_duplicates(subset=[COL_ITEM_ID], keep='first')

    return df


def initialize_db():
    """Initialize the database, migrating from CSV if needed."""
    try:
        conn = _get_connection()
        _init_db_schema(conn)
        _migrate_from_csv(conn)
        conn.close()
    except Exception as e:
        messagebox.showerror("Initialization Error", f"Failed to initialize database: {e}")
        raise


class InventoryDataManager:
    """Handles all data persistence operations using SQLite."""

    @staticmethod
    def initialize_csv_files():
        """Backward-compatible name for initialize_db."""
        initialize_db()

    @staticmethod
    def load_inventory():
        """Load inventory from SQLite into a DataFrame."""
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM inventory ORDER BY item_id")
            rows = cursor.fetchall()
            conn.close()
            df = _rows_to_dataframe(rows, INVENTORY_COLUMNS)
            df = _validate_inventory(df)
            return df
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load inventory: {e}")
            return pd.DataFrame(columns=INVENTORY_COLUMNS)

    @staticmethod
    def load_log(inventory_df=None):
        """Load transaction log from SQLite into a DataFrame."""
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            if inventory_df is not None and not inventory_df.empty:
                valid_items = tuple(inventory_df[COL_ITEM_ID].values)
                if len(valid_items) == 1:
                    cursor.execute("SELECT * FROM transactions WHERE item_id = ? ORDER BY timestamp", (valid_items[0],))
                else:
                    cursor.execute(f"SELECT * FROM transactions WHERE item_id IN ({','.join('?' * len(valid_items))}) ORDER BY timestamp", valid_items)
            else:
                cursor.execute("SELECT * FROM transactions ORDER BY timestamp")

            rows = cursor.fetchall()
            conn.close()
            df = _rows_to_dataframe(rows, LOG_COLUMNS)

            # Add missing columns for backward compatibility
            if COL_DATE_RANGE not in df.columns:
                df[COL_DATE_RANGE] = ""
            if COL_REASON not in df.columns:
                df[COL_REASON] = ""

            return df
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load transaction log: {e}")
            return pd.DataFrame(columns=LOG_COLUMNS)

    @staticmethod
    def save_inventory(df):
        """Save inventory DataFrame to SQLite (replaces all rows atomically)."""
        conn = None
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            conn.execute("BEGIN IMMEDIATE")
            cursor.execute("DELETE FROM inventory")

            for _, row in df.iterrows():
                cursor.execute("""
                    INSERT INTO inventory
                    (item_id, item_name, quantity, cost_price, sell_price, measure, category, price_locked, allow_negative, reorder_level, division)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(row[COL_ITEM_ID]),
                    str(row[COL_ITEM_NAME]),
                    float(row[COL_QUANTITY]),
                    float(row[COL_COST_PRICE]),
                    float(row[COL_SELL_PRICE]),
                    str(row.get(COL_MEASURE, '')),
                    str(row.get(COL_CATEGORY, '')),
                    int(bool(row.get(COL_PRICE_LOCKED, False))),
                    int(bool(row.get(COL_ALLOW_NEGATIVE, False))),
                    float(row.get(COL_REORDER_LEVEL, 0)),
                    str(row.get(COL_DIVISION, ''))
                ))

            conn.commit()
            return True
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            messagebox.showerror("Error", f"Failed to save inventory: {e}")
            return False
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    @staticmethod
    def save_log(df):
        """Save transaction log DataFrame to SQLite (replaces all rows atomically)."""
        conn = None
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            conn.execute("BEGIN IMMEDIATE")
            cursor.execute("DELETE FROM transactions")

            for _, row in df.iterrows():
                cursor.execute("""
                    INSERT INTO transactions
                    (item_id, action, quantity, timestamp, cost_price, sell_price, supplier, date_range, reason, member_qty, non_member_qty, open_tab_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    str(row[COL_ITEM_ID]),
                    str(row[COL_ACTION]),
                    float(row[COL_QUANTITY]),
                    str(row[COL_TIMESTAMP]),
                    float(row.get(COL_COST_PRICE, 0)),
                    float(row.get(COL_SELL_PRICE, 0)),
                    str(row.get(COL_SUPPLIER, '')),
                    str(row.get(COL_DATE_RANGE, '')),
                    str(row.get(COL_REASON, '')),
                    float(row.get(COL_MEMBER_QTY, 0) or 0),
                    float(row.get(COL_NON_MEMBER_QTY, 0) or 0),
                    int(row.get(COL_OPEN_TAB_ID)) if pd.notna(row.get(COL_OPEN_TAB_ID)) and row.get(COL_OPEN_TAB_ID) is not None else None
                ))

            conn.commit()
            return True
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            messagebox.showerror("Error", f"Failed to save transaction log: {e}")
            return False
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    @staticmethod
    def get_item_value_safe(df, item_id, column, default=0):
        """Safely get a value from inventory DataFrame."""
        if df.empty or item_id not in df[COL_ITEM_ID].values:
            return default
        result = df.loc[df[COL_ITEM_ID] == item_id, column]
        if result.empty:
            return default
        return result.values[0]

    @staticmethod
    def item_exists(df, item_id):
        """Check if an item exists in the inventory DataFrame."""
        if df.empty:
            return False
        return item_id in df[COL_ITEM_ID].values

    @staticmethod
    def _validate_inventory(df):
        """Public wrapper for validation."""
        return _validate_inventory(df)

    @staticmethod
    def create_open_tab(customer_name, items):
        """Create a new open tab.

        items: list of dicts with keys: item_id, item_name, quantity, cost_price, sell_price
        Returns the new tab id on success, None on failure.
        """
        try:
            with AtomicTransaction() as txn:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                txn.cursor.execute(
                    "INSERT INTO open_tabs (customer_name, status, created_at) VALUES (?, ?, ?)",
                    (str(customer_name), 'open', timestamp)
                )
                tab_id = txn.cursor.lastrowid

                for item in items:
                    txn.log_transaction(
                        item_id=item['item_id'],
                        action='Open Tab',
                        quantity=item['quantity'],
                        timestamp=timestamp,
                        cost_price=item.get('cost_price', 0),
                        sell_price=item.get('sell_price', 0),
                        reason=customer_name,
                        open_tab_id=tab_id
                    )
                return tab_id
        except Exception as e:
            messagebox.showerror("Error", f"Failed to create open tab: {e}")
            return None

    @staticmethod
    def get_open_tabs(status='open'):
        """Get open tabs with their items.

        Returns a DataFrame with columns: id, customer_name, status, created_at, item_id, item_name, quantity, cost_price, sell_price
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT
                    ot.id,
                    ot.customer_name,
                    ot.status,
                    ot.created_at,
                    t.item_id,
                    i.item_name,
                    t.quantity,
                    t.cost_price,
                    t.sell_price
                FROM open_tabs ot
                JOIN transactions t ON ot.id = t.open_tab_id
                LEFT JOIN inventory i ON t.item_id = i.item_id
                WHERE ot.status = ? AND t.action = 'Open Tab'
                ORDER BY ot.created_at DESC, t.item_id
            """, (status,))
            rows = cursor.fetchall()
            conn.close()

            columns = ['id', 'customer_name', 'status', 'created_at',
                       'item_id', 'item_name', 'quantity', 'cost_price', 'sell_price']
            if not rows:
                return pd.DataFrame(columns=columns)
            data = [dict(row) for row in rows]
            return pd.DataFrame(data, columns=columns)
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load open tabs: {e}")
            return pd.DataFrame()

    @staticmethod
    def close_open_tab(tab_id, items):
        """Close an open tab and record sales transactions for revenue recognition.

        items: list of dicts with keys: item_id, quantity, cost_price, sell_price
        Returns True on success.
        """
        try:
            with AtomicTransaction() as txn:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                txn.cursor.execute(
                    "UPDATE open_tabs SET status = ?, closed_at = ? WHERE id = ?",
                    ('closed', timestamp, int(tab_id))
                )

                for item in items:
                    txn.log_transaction(
                        item_id=item['item_id'],
                        action='Sales',
                        quantity=item['quantity'],
                        timestamp=timestamp,
                        cost_price=item.get('cost_price', 0),
                        sell_price=item.get('sell_price', 0),
                        open_tab_id=tab_id
                    )
                return True
        except Exception as e:
            messagebox.showerror("Error", f"Failed to close open tab: {e}")
            return False

    @staticmethod
    def cancel_open_tab(tab_id):
        """Cancel an open tab and restore stock.

        Returns a list of dicts with item_id and quantity to restore, or None on failure.
        """
        try:
            with AtomicTransaction() as txn:
                # Get the items from the open tab
                txn.cursor.execute(
                    "SELECT item_id, quantity FROM transactions WHERE open_tab_id = ? AND action = 'Open Tab'",
                    (int(tab_id),)
                )
                rows = txn.cursor.fetchall()
                items = [{'item_id': row[0], 'quantity': row[1]} for row in rows]

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                txn.cursor.execute(
                    "UPDATE open_tabs SET status = ?, closed_at = ? WHERE id = ?",
                    ('cancelled', timestamp, int(tab_id))
                )

                # Log cancellation transactions and restore stock
                for item in items:
                    txn.log_transaction(
                        item_id=item['item_id'],
                        action='Tab Cancelled',
                        quantity=item['quantity'],
                        timestamp=timestamp,
                        open_tab_id=tab_id
                    )

                return items
        except Exception as e:
            messagebox.showerror("Error", f"Failed to cancel open tab: {e}")
            return None


# Atomic transaction helper
class AtomicTransaction:
    """Context manager for atomic database operations.

    Usage:
        with AtomicTransaction() as txn:
            txn.update_inventory(item_id, new_quantity)
            txn.log_transaction(...)
            # Both operations are committed together on exit.
    """

    def __init__(self):
        self.conn = None
        self.cursor = None

    def __enter__(self):
        self.conn = _get_connection()
        self.cursor = self.conn.cursor()
        self.conn.execute("BEGIN TRANSACTION")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.conn.rollback()
            self.conn.close()
            return False
        try:
            self.conn.commit()
            self.conn.close()
            return True
        except Exception as e:
            self.conn.rollback()
            self.conn.close()
            messagebox.showerror("Transaction Error", f"Failed to commit transaction: {e}")
            return False

    def update_inventory_quantity(self, item_id, new_quantity):
        """Update an item's quantity."""
        self.cursor.execute(
            "UPDATE inventory SET quantity = ? WHERE item_id = ?",
            (float(new_quantity), str(item_id))
        )

    def update_inventory_price(self, item_id, cost_price, sell_price):
        """Update an item's prices."""
        self.cursor.execute(
            "UPDATE inventory SET cost_price = ?, sell_price = ? WHERE item_id = ?",
            (float(cost_price), float(sell_price), str(item_id))
        )

    def insert_inventory(self, item_id, item_name, quantity, cost_price, sell_price, measure, category, price_locked=False, allow_negative=False, reorder_level=0, division=''):
        """Insert a new inventory item."""
        self.cursor.execute("""
            INSERT INTO inventory
            (item_id, item_name, quantity, cost_price, sell_price, measure, category, price_locked, allow_negative, reorder_level, division)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(item_id), str(item_name), float(quantity), float(cost_price),
            float(sell_price), str(measure), str(category),
            int(bool(price_locked)), int(bool(allow_negative)), float(reorder_level),
            str(division)
        ))

    def delete_inventory(self, item_id):
        """Delete an inventory item."""
        self.cursor.execute("DELETE FROM inventory WHERE item_id = ?", (str(item_id),))

    def log_transaction(self, item_id, action, quantity, timestamp, cost_price=0, sell_price=0, supplier='', date_range='', reason='', user='', member_qty=0, non_member_qty=0, open_tab_id=None):
        """Insert a transaction log entry."""
        self.cursor.execute("""
            INSERT INTO transactions
            (item_id, action, quantity, timestamp, cost_price, sell_price, supplier, date_range, reason, user, member_qty, non_member_qty, open_tab_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(item_id), str(action), float(quantity), str(timestamp),
            float(cost_price), float(sell_price), str(supplier),
            str(date_range), str(reason), str(user),
            float(member_qty), float(non_member_qty),
            int(open_tab_id) if open_tab_id is not None else None
        ))

    def get_inventory_quantity(self, item_id):
        """Get current quantity for an item."""
        self.cursor.execute("SELECT quantity FROM inventory WHERE item_id = ?", (str(item_id),))
        row = self.cursor.fetchone()
        return float(row[0]) if row else 0.0

    def get_inventory_row(self, item_id):
        """Get full row for an item as a dict."""
        self.cursor.execute("SELECT * FROM inventory WHERE item_id = ?", (str(item_id),))
        row = self.cursor.fetchone()
        return dict(row) if row else None


# Settings helpers
def get_setting(key, default=None):
    """Get a setting value from the database."""
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (str(key),))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else default
    except Exception:
        return default


def set_setting(key, value):
    """Set a setting value in the database."""
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (str(key), str(value)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        messagebox.showerror("Error", f"Failed to save setting: {e}")
        return False


# Stocktake snapshot helpers

def record_stocktake(item_id, counted_quantity, expected_quantity, variance, timestamp, note=''):
    """Record a stocktake snapshot entry, update inventory, and log adjustment transaction."""
    try:
        with AtomicTransaction() as txn:
            # Record snapshot
            txn.cursor.execute("""
                INSERT INTO stocktake_snapshots (item_id, counted_quantity, expected_quantity, variance, timestamp, note)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (str(item_id), float(counted_quantity), float(expected_quantity), float(variance), str(timestamp), str(note)))

            # Update inventory to counted quantity
            txn.update_inventory_quantity(item_id, float(counted_quantity))

            # Log adjustment transaction for audit trail
            if variance != 0:
                txn.log_transaction(
                    item_id=item_id,
                    action='Stocktake Adjustment',
                    quantity=float(variance),
                    timestamp=timestamp,
                    reason=note
                )

        return True
    except Exception as e:
        messagebox.showerror("Error", f"Failed to record stocktake: {e}")
        return False


def get_stocktake_history(item_id=None, limit=50):
    """Get stocktake history, optionally filtered by item_id."""
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        if item_id:
            cursor.execute("""
                SELECT * FROM stocktake_snapshots WHERE item_id = ? ORDER BY timestamp DESC LIMIT ?
            """, (str(item_id), int(limit)))
        else:
            cursor.execute("""
                SELECT * FROM stocktake_snapshots ORDER BY timestamp DESC LIMIT ?
            """, (int(limit),))
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception as e:
        messagebox.showerror("Error", f"Failed to load stocktake history: {e}")
        return []


def get_last_stocktake_date():
    """Get the timestamp of the most recent stocktake."""
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(timestamp) FROM stocktake_snapshots")
        row = cursor.fetchone()
        conn.close()
        return row[0] if row and row[0] else None
    except Exception:
        return None


def delete_stocktake(snapshot_id):
    """Delete a stocktake snapshot by ID."""
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM stocktake_snapshots WHERE id = ?", (int(snapshot_id),))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        messagebox.showerror("Error", f"Failed to delete stocktake: {e}")
        return False


def clear_stocktake_snapshots():
    """Delete all stocktake snapshots. Use with caution."""
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM stocktake_snapshots")
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        messagebox.showerror("Error", f"Failed to clear stocktake snapshots: {e}")
        return False


def clear_transaction_archive():
    """Delete all archived transactions. Use with caution."""
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM transaction_archive")
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        messagebox.showerror("Error", f"Failed to clear transaction archive: {e}")
        return False


def archive_transactions_before_date(cutoff_date):
    """Archive all transactions before cutoff_date and delete them from active log.

    Returns the number of archived transactions.
    """
    try:
        conn = _get_connection()
        cursor = conn.cursor()

        # Count what will be archived
        cursor.execute(
            "SELECT COUNT(*) FROM transactions WHERE timestamp < ?",
            (str(cutoff_date),)
        )
        count = cursor.fetchone()[0]

        if count == 0:
            conn.close()
            return 0

        # Copy to archive table
        archived_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("""
            INSERT INTO transaction_archive
            (item_id, action, quantity, timestamp, cost_price, sell_price, supplier, date_range, reason, user, member_qty, non_member_qty, open_tab_id, archived_at)
            SELECT item_id, action, quantity, timestamp, cost_price, sell_price, supplier, date_range, reason, user, member_qty, non_member_qty, open_tab_id, ?
            FROM transactions WHERE timestamp < ?
        """, (archived_at, str(cutoff_date)))

        # Delete from active transactions
        cursor.execute("DELETE FROM transactions WHERE timestamp < ?", (str(cutoff_date),))

        conn.commit()
        conn.close()
        return count
    except Exception as e:
        messagebox.showerror("Error", f"Failed to archive transactions: {e}")
        return -1


def get_archived_transaction_count():
    """Get total number of archived transactions."""
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM transaction_archive")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    except Exception:
        return 0


def restore_archived_transactions():
    """Restore all archived transactions back to the active log (emergency rollback).

    Returns the number of restored transactions.
    """
    try:
        conn = _get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM transaction_archive")
        count = cursor.fetchone()[0]

        if count == 0:
            conn.close()
            return 0

        cursor.execute("""
            INSERT INTO transactions
            (item_id, action, quantity, timestamp, cost_price, sell_price, supplier, date_range, reason, user, member_qty, non_member_qty, open_tab_id)
            SELECT item_id, action, quantity, timestamp, cost_price, sell_price, supplier, date_range, reason, user, member_qty, non_member_qty, open_tab_id
            FROM transaction_archive
        """)

        cursor.execute("DELETE FROM transaction_archive")
        conn.commit()
        conn.close()
        return count
    except Exception as e:
        messagebox.showerror("Error", f"Failed to restore archived transactions: {e}")
        return -1


def get_baseline_reset_history():
    """Get list of baseline resets from settings."""
    import json
    raw = get_setting('baseline_resets', '[]')
    try:
        return json.loads(raw)
    except Exception:
        return []


def add_baseline_reset(timestamp, items_count, archived_count, note=''):
    """Record a baseline reset event."""
    import json
    resets = get_baseline_reset_history()
    resets.append({
        'timestamp': timestamp,
        'items_count': items_count,
        'archived_count': archived_count,
        'note': note
    })
    set_setting('baseline_resets', json.dumps(resets[-10:]))  # Keep last 10


# Upload hash helpers for duplicate sales upload guard

def get_upload_hashes():
    """Get list of recent upload hashes from settings."""
    import json
    raw = get_setting('upload_hashes', '[]')
    try:
        return json.loads(raw)
    except Exception:
        return []


def add_upload_hash(file_hash, filename, timestamp, date_range, row_count, upload_type=''):
    """Add a new upload hash to the tracked list (keeps last 100, last 30 days)."""
    import json
    from datetime import datetime, timedelta
    hashes = get_upload_hashes()
    hashes.append({
        'hash': file_hash,
        'filename': filename,
        'timestamp': timestamp,
        'date_range': date_range,
        'row_count': row_count,
        'type': upload_type
    })
    # Keep only last 100 entries
    if len(hashes) > 100:
        hashes = hashes[-100:]
    # Keep only last 30 days
    cutoff = (datetime.now() - timedelta(days=30)).isoformat()
    hashes = [h for h in hashes if h.get('timestamp', '') > cutoff]
    set_setting('upload_hashes', json.dumps(hashes))
    return True


def is_duplicate_upload(file_hash, upload_type=''):
    """Check if a file hash has been uploaded recently.
    If upload_type is provided, only match against uploads of that type."""
    hashes = get_upload_hashes()
    for h in hashes:
        if h.get('hash') == file_hash:
            if upload_type and h.get('type') != upload_type:
                continue
            return h
    return None


def get_backups_dir():
    """Get or create the backups directory."""
    backups_dir = os.path.join(DATA_DIR, 'backups')
    os.makedirs(backups_dir, exist_ok=True)
    return backups_dir


def create_backup(reason=''):
    """Create a timestamped backup of the database."""
    try:
        backups_dir = get_backups_dir()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        reason_slug = reason.replace(' ', '_').replace('/', '_') if reason else 'manual'
        backup_name = f'barstock_backup_{timestamp}_{reason_slug}.db'
        backup_path = os.path.join(backups_dir, backup_name)
        shutil.copy2(DB_PATH, backup_path)
        cleanup_old_backups()
        return backup_path
    except Exception as e:
        print(f'Backup failed: {e}')
        return None


def cleanup_old_backups(max_backups=30):
    """Remove old backups keeping only the most recent max_backups."""
    try:
        backups_dir = get_backups_dir()
        backups = sorted(
            glob.glob(os.path.join(backups_dir, 'barstock_backup_*.db')),
            key=os.path.getmtime,
            reverse=True
        )
        for old in backups[max_backups:]:
            os.remove(old)
    except Exception:
        pass


def list_backups():
    """List available backups with metadata."""
    try:
        backups_dir = get_backups_dir()
        backups = sorted(
            glob.glob(os.path.join(backups_dir, 'barstock_backup_*.db')),
            key=os.path.getmtime,
            reverse=True
        )
        result = []
        for path in backups:
            name = os.path.basename(path)
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
            size = os.path.getsize(path)
            result.append({
                'path': path,
                'name': name,
                'timestamp': mtime.strftime('%Y-%m-%d %H:%M:%S'),
                'size_kb': round(size / 1024, 1)
            })
        return result
    except Exception:
        return []


def restore_backup(backup_path):
    """Restore database from a backup file."""
    try:
        if not os.path.exists(backup_path):
            return False
        create_backup('before_restore')
        shutil.copy2(backup_path, DB_PATH)
        return True
    except Exception as e:
        print(f'Restore failed: {e}')
        return False


def should_auto_backup():
    """Check if a daily auto-backup is due."""
    try:
        backups_dir = get_backups_dir()
        auto_backups = sorted(
            glob.glob(os.path.join(backups_dir, 'barstock_auto_*.db')),
            key=os.path.getmtime,
            reverse=True
        )
        if not auto_backups:
            return True
        last_mtime = os.path.getmtime(auto_backups[0])
        last_date = datetime.fromtimestamp(last_mtime).date()
        return last_date < datetime.now().date()
    except Exception:
        return True


def create_auto_backup():
    """Create a daily auto-backup if due."""
    if not should_auto_backup():
        return None
    try:
        backups_dir = get_backups_dir()
        timestamp = datetime.now().strftime('%Y%m%d')
        backup_name = f'barstock_auto_{timestamp}.db'
        backup_path = os.path.join(backups_dir, backup_name)
        shutil.copy2(DB_PATH, backup_path)
        # Keep only last 7 auto-backups
        auto_backups = sorted(
            glob.glob(os.path.join(backups_dir, 'barstock_auto_*.db')),
            key=os.path.getmtime,
            reverse=True
        )
        for old in auto_backups[7:]:
            os.remove(old)
        return backup_path
    except Exception as e:
        print(f'Auto-backup failed: {e}')
        return None
