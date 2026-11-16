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
import csv
import logging
import pandas as pd
from tkinter import messagebox
from datetime import datetime

from sales_mapping import SALES_TO_PARENT, normalize_product_name
from app_config import (
    DATA_DIR, INVENTORY_FILE, LOG_FILE, get_items_csv_path,
    get_resource_path, get_script_directory, sqlite_ro_uri,
)

logger = logging.getLogger(__name__)

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
# SQLite row identifier for transactions. Loaded log frames carry it so saves
# can update/delete individual rows instead of replacing the whole table.
COL_ID = 'id'

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


DB_PATH = os.path.join(DATA_DIR, 'barstock.db')
# Bump when a migration changes the schema. The first launch after an upgrade
# takes a safety backup before any schema change is applied.
SCHEMA_VERSION = 4


def _get_connection():
    """Get a SQLite connection with proper settings."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


_TRANSACTIONS_COLUMNS_SQL = """
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
"""


_INVENTORY_COLUMNS_SQL = """
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
"""


def _ensure_inventory_primary_key(cursor):
    """Rebuild inventory if item_id is not its primary key.

    Early databases declared ``item_id TEXT`` with no constraint, so the
    upsert in ``_insert_inventory_row`` failed ("ON CONFLICT clause does not
    match any PRIMARY KEY or UNIQUE constraint") and new stock items could not
    be added. Rebuild the table with the current schema, keeping every row.
    """
    info = cursor.execute("PRAGMA table_info(inventory)").fetchall()
    id_column = next((row for row in info if row[1] == 'item_id'), None)
    if id_column is not None and int(id_column[5] or 0) == 1:
        return

    columns = {row[1] for row in info}
    cursor.execute("ALTER TABLE inventory RENAME TO inventory_legacy_pk")
    cursor.execute(f"CREATE TABLE inventory ({_INVENTORY_COLUMNS_SQL})")

    fields = []
    for name, fallback in (
            ('item_id', "''"), ('item_name', "''"), ('quantity', '0'),
            ('cost_price', '0'), ('sell_price', '0'), ('measure', "''"),
            ('category', "''"), ('price_locked', '0'),
            ('allow_negative', '0'), ('reorder_level', '0'),
            ('division', "''")):
        fields.append(name if name in columns else f"{fallback} AS {name}")

    cursor.execute(
        "INSERT OR REPLACE INTO inventory (item_id, item_name, quantity, "
        "cost_price, sell_price, measure, category, price_locked, "
        "allow_negative, reorder_level, division) "
        f"SELECT {', '.join(fields)} FROM inventory_legacy_pk ORDER BY rowid"
    )
    cursor.execute("DROP TABLE inventory_legacy_pk")
    logger.info("Rebuilt inventory table with item_id as primary key")


def _ensure_transaction_ids(cursor):
    """Rebuild transactions if its id column cannot hold row ids.

    Databases created before ids were used declared ``id REAL`` with no
    primary key, so every row kept a NULL id and a log save could not match
    a frame row back to its table row (it raised ``int(None)``). Rebuild the
    table with the current schema, carrying the rows across in insertion
    order so each one gains a stable integer id.
    """
    info = cursor.execute("PRAGMA table_info(transactions)").fetchall()
    id_column = next((row for row in info if row[1] == 'id'), None)
    if (id_column is not None
            and int(id_column[5] or 0) == 1
            and 'INT' in str(id_column[2] or '').upper()):
        return

    columns = {row[1] for row in info}
    cursor.execute("ALTER TABLE transactions RENAME TO transactions_legacy_ids")
    cursor.execute(f"CREATE TABLE transactions ({_TRANSACTIONS_COLUMNS_SQL})")

    fields = []
    for name, fallback in (
            ('item_id', "''"), ('action', "''"), ('quantity', '0'),
            ('timestamp', "''"), ('cost_price', '0'), ('sell_price', '0'),
            ('supplier', "''"), ('date_range', "''"), ('reason', "''"),
            ('member_qty', 'NULL'), ('non_member_qty', 'NULL')):
        fields.append(name if name in columns else f"{fallback} AS {name}")
    if 'open_tab_id' in columns:
        fields.append(
            "CASE WHEN open_tab_id IS NULL "
            "OR TRIM(CAST(open_tab_id AS TEXT)) IN ('', 'None') "
            "THEN NULL ELSE CAST(open_tab_id AS INTEGER) END AS open_tab_id")
    else:
        fields.append("NULL AS open_tab_id")

    cursor.execute(
        "INSERT INTO transactions (item_id, action, quantity, timestamp, "
        "cost_price, sell_price, supplier, date_range, reason, member_qty, "
        "non_member_qty, open_tab_id) "
        f"SELECT {', '.join(fields)} FROM transactions_legacy_ids ORDER BY rowid"
    )
    cursor.execute("DROP TABLE transactions_legacy_ids")
    logger.info("Rebuilt transactions table with integer row ids")


def _init_db_schema(conn):
    """Initialize the database schema."""
    cursor = conn.cursor()

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS inventory ({_INVENTORY_COLUMNS_SQL})
    """)

    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS transactions ({_TRANSACTIONS_COLUMNS_SQL})
    """)

    # Add new columns to existing tables (backward compat)
    _ensure_transaction_ids(cursor)
    cursor.execute("PRAGMA table_info(transactions)")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if 'member_qty' not in existing_cols:
        cursor.execute("ALTER TABLE transactions ADD COLUMN member_qty REAL DEFAULT 0")
    if 'non_member_qty' not in existing_cols:
        cursor.execute("ALTER TABLE transactions ADD COLUMN non_member_qty REAL DEFAULT 0")
    if 'open_tab_id' not in existing_cols:
        cursor.execute("ALTER TABLE transactions ADD COLUMN open_tab_id INTEGER DEFAULT NULL")

    _ensure_inventory_primary_key(cursor)
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

    # Dedicated audit table for baseline resets (replaces the transient settings JSON).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS baseline_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            items_count INTEGER NOT NULL,
            archived_count INTEGER NOT NULL,
            note TEXT DEFAULT '',
            snapshot_json TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_baseline_resets_timestamp ON baseline_resets(timestamp)")

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
                    # The bundled stock.csv stores quantities in system units (pints,
                    # measures, etc.), so no conversion is needed on migration.
                    system_quantity = float(row[COL_QUANTITY])
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
                    # The bundled transaction_log.csv stores quantities in system
                    # units (pints, measures, etc.), so no conversion is needed.
                    system_qty = float(row[COL_QUANTITY])
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
            os.replace(INVENTORY_FILE, INVENTORY_FILE + '.bak')
        if os.path.exists(LOG_FILE):
            os.replace(LOG_FILE, LOG_FILE + '.bak')
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


def _path_is_in_live_data_dir(path):
    """Return True when ``path`` sits beside the live database."""
    try:
        return (os.path.dirname(os.path.abspath(str(path)))
                == os.path.abspath(DATA_DIR))
    except Exception:
        return False


def initialize_db():
    """Initialize the database, migrating from CSV if needed.

    A version upgrade takes a safety backup before touching the schema. The
    backup is skipped for a brand-new database, which has nothing to lose.
    """
    conn = None
    try:
        conn = _get_connection()
        current_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if current_version < SCHEMA_VERSION:
            has_inventory = conn.execute(
                "SELECT COUNT(*) FROM sqlite_master "
                "WHERE type = 'table' AND name = 'inventory'"
            ).fetchone()[0]
            if has_inventory:
                conn.close()
                conn = None
                backup_path = create_backup(
                    f'before_schema_migration_v{SCHEMA_VERSION}'
                )
                if not backup_path:
                    raise RuntimeError(
                        "Could not create a safety backup before the database "
                        "upgrade; startup aborted."
                    )
                logger.info("Pre-migration backup: %s", backup_path)
                conn = _get_connection()

        _init_db_schema(conn)
        # A test or tool database must never consume (and rename) the live
        # CSV mirrors.  That turned a fresh temporary DB into a copy of live
        # stock and left the real stock.csv as stock.csv.bak.
        if _path_is_in_live_data_dir(INVENTORY_FILE) and not _path_is_in_live_data_dir(DB_PATH):
            logger.info("Skipping CSV migration into non-live database %s", DB_PATH)
        else:
            _migrate_from_csv(conn)
            _sync_inventory_from_csv(conn)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        conn.commit()
    except Exception as e:
        logger.exception("Failed to initialize database")
        messagebox.showerror("Initialization Error", f"Failed to initialize database: {e}")
        raise
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def get_csv_sync_changes():
    """Return cost changes that would be applied by a CSV sync without applying them."""
    try:
        conn = _get_connection()
        _init_db_schema(conn)
        changes = _sync_inventory_from_csv(conn)
        conn.rollback()
        conn.close()
        return changes
    except Exception as e:
        print(f"Warning: Could not preview CSV sync changes: {e}")
        return []


def _sync_inventory_from_csv(conn):
    """Update the SQLite inventory table from the bundled stock.csv.

    After the one-time CSV migration, the live database can drift from the
    bundled CSV (e.g. updated invoice prices or new items). This function
    reconciles CSV into the database on every startup when running as a bundled
    app (PyInstaller). Unit tests run unfrozen and use a temporary DB, so they
    are skipped to avoid polluting the test database with the real stock.csv.

      - Existing items are updated for metadata/prices (name, cost/sell,
        measure, category, division, price_locked, allow_negative,
        reorder_level). The live quantity is intentionally left untouched
        because it is transaction-driven; overwriting it from a bundled CSV
        would silently undo sales, deliveries and wastage.
      - Items present in CSV but missing from DB are inserted, using the CSV
        quantity as their starting stock.
      - Items present in DB but missing from CSV are left untouched (they may
        be historical/retired items needed for old transactions).

    Returns a list of (item_id, old_cost, new_cost) tuples for items whose
    cost_price changed, so the UI can show a startup summary.
    """
    # Only sync in the bundled app, not during unfrozen development/tests.
    if not getattr(sys, 'frozen', False):
        return []

    csv_path = INVENTORY_FILE
    if not os.path.exists(csv_path):
        # In a bundled app the CSV is copied alongside the executable; fall back
        # to the script/app directory if the app-support copy does not exist.
        script_dir = get_script_directory()
        csv_path = os.path.join(script_dir, 'stock.csv')
        if not os.path.exists(csv_path):
            return []

    try:
        df = pd.read_csv(csv_path)
        if df.empty:
            return []

        # Backwards compatibility columns
        if COL_PRICE_LOCKED not in df.columns:
            df[COL_PRICE_LOCKED] = False
        if COL_ALLOW_NEGATIVE not in df.columns:
            df[COL_ALLOW_NEGATIVE] = True
        if COL_REORDER_LEVEL not in df.columns:
            df[COL_REORDER_LEVEL] = 0
        if COL_DIVISION not in df.columns:
            df[COL_DIVISION] = ''

        df = _validate_inventory(df)

        cursor = conn.cursor()
        cursor.execute("SELECT item_id FROM inventory")
        db_item_ids = {row[0] for row in cursor.fetchall()}

        synced = 0
        cost_changes = []
        for _, row in df.iterrows():
            item_id = str(row[COL_ITEM_ID])
            # The bundled stock.csv now stores quantities in system units (pints,
            # measures, etc.) rather than input units (barrels/bottles), so no
            # conversion is needed when syncing into the live database.
            # Quantity is only used when inserting a brand-new item; existing
            # items keep their transaction-driven quantity to avoid the bundled
            # CSV silently undoing sales, deliveries and wastage.
            new_item_quantity = float(row[COL_QUANTITY])
            values = {
                'item_name': str(row[COL_ITEM_NAME]),
                'cost_price': float(row[COL_COST_PRICE]),
                'sell_price': float(row[COL_SELL_PRICE]),
                'measure': str(row.get(COL_MEASURE, '')),
                'category': str(row.get(COL_CATEGORY, '')),
                'price_locked': int(bool(row[COL_PRICE_LOCKED])),
                'allow_negative': int(bool(row.get(COL_ALLOW_NEGATIVE, True))),
                'reorder_level': float(row.get(COL_REORDER_LEVEL, 0)),
                'division': str(row.get(COL_DIVISION, '')),
            }

            if item_id in db_item_ids:
                # Update only metadata/prices; leave transaction-driven quantity alone.
                cursor.execute(
                    f"SELECT {', '.join(values.keys())} FROM inventory WHERE item_id = ?",
                    (item_id,)
                )
                db_row = cursor.fetchone()
                if db_row:
                    old_cost = float(db_row['cost_price'])
                    needs_update = any(
                        float(db_row[k]) != float(v) if isinstance(v, (int, float)) else str(db_row[k]) != str(v)
                        for k, v in values.items()
                    )
                    if needs_update:
                        set_clause = ', '.join(f"{k} = ?" for k in values.keys())
                        cursor.execute(
                            f"UPDATE inventory SET {set_clause} WHERE item_id = ?",
                            (*values.values(), item_id)
                        )
                        synced += 1
                        if abs(old_cost - values['cost_price']) > 0.0001:
                            cost_changes.append((item_id, old_cost, values['cost_price']))
            else:
                values_with_qty = {**values, 'quantity': new_item_quantity}
                columns = ['item_id'] + list(values_with_qty.keys())
                placeholders = ', '.join('?' for _ in columns)
                cursor.execute(
                    f"INSERT INTO inventory ({', '.join(columns)}) VALUES ({placeholders})",
                    (item_id, *values_with_qty.values())
                )
                synced += 1
                cost_changes.append((item_id, 0.0, values['cost_price']))

        if synced:
            conn.commit()
            print(f"Synced {synced} inventory item(s) from stock.csv")
        return cost_changes
    except Exception as e:
        print(f"Warning: Could not sync inventory from CSV: {e}")
        return []



def _normalise_name(name):
    """Normalise an item name to match item_id conventions."""
    return normalize_product_name(name)


def _write_stock_csv(csv_path, df):
    """Write the inventory DataFrame to stock.csv format."""
    def _cell(value):
        """Return a CSV-safe value, preserving booleans and empty strings."""
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ''
        if isinstance(value, bool):
            return 'True' if value else 'False'
        return value

    rows = []
    for _, row in df.iterrows():
        rows.append([
            _cell(row[COL_ITEM_ID]),
            _cell(row[COL_ITEM_NAME]),
            _cell(float(row[COL_QUANTITY])),
            _cell(float(row[COL_COST_PRICE])),
            _cell(float(row[COL_SELL_PRICE])),
            _cell(row.get(COL_MEASURE, '')),
            _cell(row.get(COL_CATEGORY, '')),
            _cell(bool(row.get(COL_PRICE_LOCKED, False))),
            _cell(bool(row.get(COL_ALLOW_NEGATIVE, False))),
            _cell(float(row.get(COL_REORDER_LEVEL, 0))),
            _cell(row.get(COL_DIVISION, ''))
        ])
    with open(csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(INVENTORY_COLUMNS)
        writer.writerows(rows)


def ensure_items_csv_master(df=None):
    """Create the live Items.csv master from inventory when it is missing.

    A frozen buyer install starts without Items.csv. After the first import or
    manual item add, this gives the app a master file to keep updated instead
    of silently writing nowhere.
    """
    if df is None:
        df = InventoryDataManager.load_inventory()
    if df is None or df.empty:
        return None
    target = os.path.join(DATA_DIR, 'Items.csv')
    if os.path.exists(target):
        return target
    header = ['Name', 'Division', 'Unit', 'Total Stock', 'Total Value',
              'Active', 'Min Alert', 'Max Alert']
    rows = []
    for _, row in df.iterrows():
        quantity = float(row.get(COL_QUANTITY, 0) or 0)
        cost = float(row.get(COL_COST_PRICE, 0) or 0)
        rows.append([
            str(row.get(COL_ITEM_NAME, '')),
            str(row.get(COL_DIVISION, '') or ''),
            str(row.get(COL_MEASURE, '') or ''),
            f"{quantity:.2f}",
            f"{quantity * cost:.2f}",
            '',
            '0.0',
            '0.0',
        ])
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(target, 'w', newline='', encoding='utf-8') as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
    return target


def _update_items_csv(items_csv_path, df):
    """Update Items.csv Total Stock/Total Value from the live inventory."""
    if not os.path.exists(items_csv_path):
        return
    header, rows = [], []
    with open(items_csv_path, 'r', newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        lines = list(reader)
        if not lines:
            return
        header = lines[0]
        rows = lines[1:]

    if 'Name' not in header or 'Total Stock' not in header or 'Total Value' not in header:
        return

    name_col = header.index('Name')
    stock_col = header.index('Total Stock')
    value_col = header.index('Total Value')

    # Map item_id -> quantity, cost, plus a name-based fallback for names
    # that don't follow the default normalisation (e.g. "Innis & Gunn").
    inv_map = {}
    name_map = {}
    for _, row in df.iterrows():
        item_id = str(row[COL_ITEM_ID]).lower()
        qty = float(row[COL_QUANTITY])
        cost = float(row[COL_COST_PRICE])
        inv_map[item_id] = (qty, cost)
        item_name = str(row[COL_ITEM_NAME]).strip().lower()
        if item_name:
            name_map[item_name] = (qty, cost)

    for row in rows:
        if not row:
            continue
        name = row[name_col] if len(row) > name_col else ''
        item_id = _normalise_name(name)
        name_key = name.strip().lower()
        if item_id in inv_map:
            qty, cost = inv_map[item_id]
        elif name_key in name_map:
            qty, cost = name_map[name_key]
        else:
            continue
        value = qty * cost
        while len(row) <= value_col:
            row.append('')
        row[stock_col] = f"{qty:.2f}"
        row[value_col] = f"{value:.2f}"

    with open(items_csv_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(header)
        writer.writerows(row for row in rows if row)


def _sync_inventory_to_csv(df):
    """Mirror the live inventory back to bundled CSV files.

    This keeps stock.csv and Items.csv in sync with the SQLite database so the
    bundled app does not overwrite live changes on its next launch.
    """
    if df.empty:
        return

    script_dir = get_script_directory()
    # The app-support copy is read first by the startup sync.
    targets = [INVENTORY_FILE]
    # In a frozen build script_dir is inside the .app bundle, which is read-only
    # (and signed), so never write there. In a dev checkout keep the repo copies
    # current for inspection and diffs.
    if not getattr(sys, 'frozen', False):
        bundled_path = os.path.join(script_dir, 'stock.csv')
        if bundled_path != INVENTORY_FILE:
            targets.append(bundled_path)
        items_csv_path = os.path.join(script_dir, 'Items.csv')
    else:
        items_csv_path = os.path.join(DATA_DIR, 'Items.csv')

    for csv_path in targets:
        try:
            _write_stock_csv(csv_path, df)
        except Exception as e:
            logger.warning("Could not write stock.csv to %s: %s", csv_path, e)

    try:
        ensure_items_csv_master(df)
        _update_items_csv(items_csv_path, df)
    except Exception as e:
        logger.warning("Could not update Items.csv: %s", e)


def _deduct_stock_in_txn(txn, item_id: str, quantity: float) -> None:
    """Deduct stock for an item and any affected parents within an AtomicTransaction.

    Mirrors sales_mapping.apply_sale_to_parent but operates directly on the
    SQLite inventory table so the log entry and stock change share one transaction.
    """
    current = txn.get_inventory_quantity(item_id)
    txn.update_inventory_quantity(item_id, current - float(quantity))

    parent_info = SALES_TO_PARENT.get(str(item_id).lower())
    if not parent_info:
        return

    parent_items, factors, _ = parent_info[:3]
    if isinstance(parent_items, list):
        for parent_id, factor in zip(parent_items, factors):
            if not parent_id:
                continue
            parent_current = txn.get_inventory_quantity(parent_id)
            txn.update_inventory_quantity(parent_id, parent_current - float(quantity) * float(factor))
    elif parent_items:
        parent_current = txn.get_inventory_quantity(parent_items)
        txn.update_inventory_quantity(parent_items, parent_current - float(quantity) * float(factors))


def _restore_stock_in_txn(txn, item_id: str, quantity: float) -> None:
    """Restore stock for an item and any affected parents within an AtomicTransaction.

    This is the inverse of _deduct_stock_in_txn and is used when a reservation
    (e.g. an open tab) is cancelled.
    """
    current = txn.get_inventory_quantity(item_id)
    txn.update_inventory_quantity(item_id, current + float(quantity))

    parent_info = SALES_TO_PARENT.get(str(item_id).lower())
    if not parent_info:
        return

    parent_items, factors, _ = parent_info[:3]
    if isinstance(parent_items, list):
        for parent_id, factor in zip(parent_items, factors):
            if not parent_id:
                continue
            parent_current = txn.get_inventory_quantity(parent_id)
            txn.update_inventory_quantity(parent_id, parent_current + float(quantity) * float(factor))
    elif parent_items:
        parent_current = txn.get_inventory_quantity(parent_items)
        txn.update_inventory_quantity(parent_items, parent_current + float(quantity) * float(factors))


INVENTORY_METADATA_COLUMNS = [
    COL_ITEM_NAME, COL_COST_PRICE, COL_SELL_PRICE, COL_MEASURE, COL_CATEGORY,
    COL_PRICE_LOCKED, COL_ALLOW_NEGATIVE, COL_REORDER_LEVEL, COL_DIVISION,
]


def _num(value, default=0.0):
    """Coerce a DataFrame cell to float, treating NaN/None as default."""
    try:
        if value is None or pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _flag(value):
    """Coerce a DataFrame cell to 0/1, treating NaN/None as False."""
    try:
        if value is None or pd.isna(value):
            return 0
        return 1 if bool(value) else 0
    except (TypeError, ValueError):
        return 0


def _text(value):
    """Coerce a DataFrame cell to a plain string, treating NaN/None as ''."""
    try:
        if value is None or pd.isna(value):
            return ''
        return str(value)
    except (TypeError, ValueError):
        return ''


def _inventory_changes(df, baseline_df):
    """Compare the in-memory inventory with the snapshot it was loaded from.

    Returns (updates, inserts, deletes).  updates is a list of
    (item_id, quantity_delta, {column: value}).

    Writing deltas rather than absolute values is what makes a stale window
    harmless: an untouched row has delta 0 and leaves whatever is in the
    database alone, so a delivery or stocktake written by another process can
    no longer be overwritten by an old in-memory frame.
    """
    current = {str(r[COL_ITEM_ID]): r for _, r in (df.iterrows() if df is not None else [])}
    baseline = (
        {str(r[COL_ITEM_ID]): r for _, r in baseline_df.iterrows()}
        if baseline_df is not None and not baseline_df.empty
        else {}
    )

    updates = []
    inserts = []
    for item_id, row in current.items():
        if item_id not in baseline:
            inserts.append(row)
            continue
        old = baseline[item_id]
        delta = round(_num(row.get(COL_QUANTITY)) - _num(old.get(COL_QUANTITY)), 6)
        fields = {}
        for col in INVENTORY_METADATA_COLUMNS:
            new_val = row.get(col)
            old_val = old.get(col)
            if col in (COL_COST_PRICE, COL_SELL_PRICE, COL_REORDER_LEVEL):
                if abs(_num(new_val) - _num(old_val)) > 1e-9:
                    fields[col] = _num(new_val)
            elif col in (COL_PRICE_LOCKED, COL_ALLOW_NEGATIVE):
                if _flag(new_val) != _flag(old_val):
                    fields[col] = _flag(new_val)
            elif _text(new_val) != _text(old_val):
                fields[col] = _text(new_val)
        if abs(delta) > 1e-9 or fields:
            updates.append((item_id, delta, fields))

    deletes = [item_id for item_id in baseline if item_id not in current]
    return updates, inserts, deletes


def _insert_inventory_row(cursor, row):
    cursor.execute("""
        INSERT INTO inventory
        (item_id, item_name, quantity, cost_price, sell_price, measure, category,
         price_locked, allow_negative, reorder_level, division)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(item_id) DO UPDATE SET
            item_name = excluded.item_name,
            cost_price = excluded.cost_price,
            sell_price = excluded.sell_price,
            measure = excluded.measure,
            category = excluded.category,
            price_locked = excluded.price_locked,
            allow_negative = excluded.allow_negative,
            reorder_level = excluded.reorder_level,
            division = excluded.division
    """, (
        str(row[COL_ITEM_ID]),
        _text(row.get(COL_ITEM_NAME)),
        _num(row.get(COL_QUANTITY)),
        _num(row.get(COL_COST_PRICE)),
        _num(row.get(COL_SELL_PRICE)),
        _text(row.get(COL_MEASURE)),
        _text(row.get(COL_CATEGORY)),
        _flag(row.get(COL_PRICE_LOCKED)),
        _flag(row.get(COL_ALLOW_NEGATIVE)),
        _num(row.get(COL_REORDER_LEVEL)),
        _text(row.get(COL_DIVISION)),
    ))


def _replace_inventory(cursor, df):
    cursor.execute("DELETE FROM inventory")
    for _, row in df.iterrows():
        _insert_inventory_row(cursor, row)


def _apply_inventory_changes(cursor, df, baseline_df):
    updates, inserts, deletes = _inventory_changes(df, baseline_df)

    # A truncated/filtered frame must never be able to empty the inventory.
    if baseline_df is not None and not baseline_df.empty:
        max_deletes = max(5, int(len(baseline_df) * 0.10))
        if len(deletes) > max_deletes:
            raise ValueError(
                f"Refusing to remove {len(deletes)} of {len(baseline_df)} inventory "
                "items in one save; the inventory frame looks incomplete."
            )

    for item_id, delta, fields in updates:
        assignments = ["quantity = ROUND(COALESCE(quantity, 0) + ?, 6)"]
        params = [delta]
        for col, value in fields.items():
            assignments.append(f"{col} = ?")
            params.append(value)
        params.append(item_id)
        cursor.execute(
            f"UPDATE inventory SET {', '.join(assignments)} WHERE item_id = ?",
            params,
        )

    for row in inserts:
        _insert_inventory_row(cursor, row)

    for item_id in deletes:
        cursor.execute("DELETE FROM inventory WHERE item_id = ?", (item_id,))


def _log_row_values(row):
    """Return the 12 mutable transaction fields for a log frame row."""
    open_tab_id = row.get(COL_OPEN_TAB_ID)
    return (
        str(row[COL_ITEM_ID]),
        str(row[COL_ACTION]),
        _num(row.get(COL_QUANTITY)),
        _text(row.get(COL_TIMESTAMP)),
        _num(row.get(COL_COST_PRICE)),
        _num(row.get(COL_SELL_PRICE)),
        _text(row.get(COL_SUPPLIER)),
        _text(row.get(COL_DATE_RANGE)),
        _text(row.get(COL_REASON)),
        _num(row.get(COL_MEMBER_QTY)),
        _num(row.get(COL_NON_MEMBER_QTY)),
        int(open_tab_id) if open_tab_id is not None and pd.notna(open_tab_id) else None,
    )


_LOG_INSERT_SQL = """
    INSERT INTO transactions
    (item_id, action, quantity, timestamp, cost_price, sell_price, supplier,
     date_range, reason, member_qty, non_member_qty, open_tab_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


def _replace_log(cursor, df, allow_shrink=False):
    current_count = cursor.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    new_count = 0 if df is None else len(df)
    if current_count and not allow_shrink:
        allowed_loss = max(5, int(current_count * 0.10))
        if new_count < current_count - allowed_loss:
            raise ValueError(
                f"Refusing to replace {current_count} transactions with {new_count}; "
                "the transaction frame looks like it was loaded before recent activity."
            )

    cursor.execute("DELETE FROM transactions")
    if df is None:
        return
    for _, row in df.iterrows():
        cursor.execute(_LOG_INSERT_SQL, _log_row_values(row))


def _apply_log_changes(cursor, df, allow_shrink=False, baseline_ids=None):
    """Write only the rows that differ from the database.

    Log frames loaded by load_log() carry their SQLite row id. Rows with no id
    are new and are inserted; rows with an id are updated in place.

    baseline_ids is the set of ids the frame was loaded with. Only those rows
    can be deleted: anything written by another process after the load is not
    in baseline_ids and is therefore left alone. Without baseline_ids the
    older behaviour (delete every id missing from the frame) is used, subject
    to the shrink guard.
    """
    if df is None or COL_ID not in getattr(df, 'columns', []):
        # Manually constructed frames (and legacy callers) have no ids, so the
        # whole-table path remains the only option.
        _replace_log(cursor, df, allow_shrink=allow_shrink)
        return

    existing_ids = {
        int(row[0]) for row in cursor.execute("SELECT id FROM transactions")
        if row[0] is not None
    }
    frame_ids = set()
    new_rows = []

    assignments = ', '.join(f'{col} = ?' for col in LOG_COLUMNS)
    for _, row in df.iterrows():
        raw_id = row.get(COL_ID)
        if raw_id is None or pd.isna(raw_id):
            new_rows.append(row)
            continue
        row_id = int(raw_id)
        frame_ids.add(row_id)
        if row_id in existing_ids:
            cursor.execute(
                f"UPDATE transactions SET {assignments} WHERE id = ?",
                _log_row_values(row) + (row_id,),
            )
        elif baseline_ids is not None and row_id in baseline_ids:
            # Deleted underneath this window (e.g. a database restore); do not
            # resurrect it under a new id.
            continue
        else:
            # The frame carries a row the database has never seen. Keep the
            # data by inserting it rather than silently dropping it.
            new_rows.append(row)

    for row in new_rows:
        cursor.execute(_LOG_INSERT_SQL, _log_row_values(row))

    if baseline_ids is not None:
        deletes = {row_id for row_id in baseline_ids if row_id not in frame_ids}
    else:
        deletes = existing_ids - frame_ids

    if deletes:
        if not allow_shrink:
            reference = len(baseline_ids) if baseline_ids is not None else len(existing_ids)
            allowed_loss = max(5, int(reference * 0.10))
            if len(deletes) > allowed_loss:
                raise ValueError(
                    f"Refusing to delete {len(deletes)} of {reference} "
                    "transactions; the transaction frame looks incomplete."
                )
        cursor.executemany(
            "DELETE FROM transactions WHERE id = ?",
            [(row_id,) for row_id in deletes],
        )


def _sync_csv_quietly(df):
    try:
        _sync_inventory_to_csv(df)
    except Exception as e:
        # The database is the source of truth; a CSV mirror failure must not
        # roll back a successful write.
        logger.warning("CSV sync failed: %s", e)


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
            logger.exception("Failed to load inventory")
            messagebox.showerror("Error", f"Failed to load inventory: {e}")
            return pd.DataFrame(columns=INVENTORY_COLUMNS)

    @staticmethod
    def load_log(inventory_df=None):
        """Load the full active transaction log from SQLite into a DataFrame.

        The inventory_df argument is accepted for backwards compatibility but
        deliberately ignored.  Filtering the log to currently stocked items
        meant that deleting an item and then saving the log silently erased
        that item's entire history.
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM transactions ORDER BY timestamp")

            rows = cursor.fetchall()
            conn.close()
            # Keep the row id: save_log writes only the rows that changed, so
            # transactions appended by another process are never overwritten.
            df = _rows_to_dataframe(rows, LOG_COLUMNS + [COL_ID])

            # Add missing columns for backward compatibility
            if COL_DATE_RANGE not in df.columns:
                df[COL_DATE_RANGE] = ""
            if COL_REASON not in df.columns:
                df[COL_REASON] = ""

            return df
        except Exception as e:
            logger.exception("Failed to load transaction log")
            messagebox.showerror("Error", f"Failed to load transaction log: {e}")
            return pd.DataFrame(columns=LOG_COLUMNS)

    @staticmethod
    def load_full_log(inventory_df=None):
        """Load active and archived transaction log for reporting.

        The inventory_df argument is accepted for backwards compatibility and
        deliberately ignored: a report for a past period must still see items
        that have since been delisted or removed from inventory.

        Old Stocktake Baseline rows are excluded from the archive because the
        current baseline supersedes them. Stocktake Adjustment rows are kept --
        they carry each stocktake's variance and are required for the expected
        stock calculation to agree with the physical count.
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM transactions ORDER BY timestamp")
            rows = list(cursor.fetchall())
            cursor.execute(
                "SELECT * FROM transaction_archive "
                "WHERE action != 'Stocktake Baseline' ORDER BY timestamp"
            )
            rows.extend(cursor.fetchall())
            conn.close()
            df = _rows_to_dataframe(rows, LOG_COLUMNS)

            # The same transaction can exist in both the active table and the
            # archive (e.g. if a baseline reset archived rows that were also
            # kept/re-imported). Drop exact duplicates so reports don't double
            # count sales, wastage, deliveries, etc.
            if not df.empty:
                dedup_cols = [COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP,
                              COL_COST_PRICE, COL_SELL_PRICE]
                # Preserve rows that have extra context (reason, supplier, etc.)
                # by keeping the last occurrence.
                df = df.drop_duplicates(subset=dedup_cols, keep='last')

            # Add missing columns for backward compatibility
            if COL_DATE_RANGE not in df.columns:
                df[COL_DATE_RANGE] = ""
            if COL_REASON not in df.columns:
                df[COL_REASON] = ""

            return df
        except Exception as e:
            logger.exception("Failed to load full transaction log")
            messagebox.showerror("Error", f"Failed to load full transaction log: {e}")
            return pd.DataFrame(columns=LOG_COLUMNS)

    @staticmethod
    def save_inventory(df, baseline_df=None):
        """Save inventory to SQLite.

        When baseline_df is supplied (the frame the UI actually loaded), only
        the difference between it and df is written.  This makes a stale
        window safe: unchanged rows contribute a delta of zero and never
        overwrite newer database values.
        """
        conn = None
        try:
            if df is None or df.empty:
                raise ValueError("Refusing to save an empty inventory frame.")
            conn = _get_connection()
            cursor = conn.cursor()
            conn.execute("BEGIN IMMEDIATE")
            if baseline_df is not None and not baseline_df.empty:
                _apply_inventory_changes(cursor, df, baseline_df)
            else:
                _replace_inventory(cursor, df)
            conn.commit()
            # Keep bundled CSVs in sync so the next app launch doesn't overwrite live data.
            _sync_csv_quietly(df)
            return True
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.exception("Failed to save inventory")
            messagebox.showerror("Error", f"Failed to save inventory: {e}")
            return False
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    @staticmethod
    def save_log(df, allow_shrink=False, baseline_ids=None):
        """Save transaction log to SQLite.

        Rows are updated/inserted/deleted individually. When baseline_ids is
        supplied, only rows that were present when the frame was loaded can be
        deleted, so transactions written by another process survive. Frames
        without ids fall back to a guarded wholesale replacement.
        """
        conn = None
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            conn.execute("BEGIN IMMEDIATE")
            _apply_log_changes(cursor, df, allow_shrink=allow_shrink,
                               baseline_ids=baseline_ids)
            conn.commit()
            return True
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.exception("Failed to save transaction log")
            messagebox.showerror("Error", f"Failed to save transaction log: {e}")
            return False
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    @staticmethod
    def save_all(inventory_df, log_df, baseline_df=None, allow_log_shrink=False,
                 baseline_log_ids=None):
        """Write inventory and transaction log in a single transaction.

        This replaces the old pattern of saving inventory and then the log in
        two separate commits, which could leave stock changed without its log
        rows (or vice versa) if the second write failed.
        """
        conn = None
        try:
            if inventory_df is None or inventory_df.empty:
                raise ValueError("Refusing to save an empty inventory frame.")
            conn = _get_connection()
            cursor = conn.cursor()
            conn.execute("BEGIN IMMEDIATE")
            if baseline_df is not None and not baseline_df.empty:
                _apply_inventory_changes(cursor, inventory_df, baseline_df)
            else:
                _replace_inventory(cursor, inventory_df)
            _apply_log_changes(cursor, log_df, allow_shrink=allow_log_shrink,
                               baseline_ids=baseline_log_ids)
            conn.commit()
            _sync_csv_quietly(inventory_df)
            return True
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception:
                    pass
            logger.exception("Failed to save inventory and log")
            messagebox.showerror("Error", f"Failed to save data: {e}")
            return False
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    @staticmethod
    def export_csv_mirrors(df=None):
        """Write the live inventory out to stock.csv and Items.csv.

        The database is authoritative; these files are mirrors for inspection
        and for the bundled app's startup sync. They used to refresh only as a
        side effect of a save, so a crash could leave them stale for days.
        """
        try:
            if df is None:
                df = InventoryDataManager.load_inventory()
            if df is None or df.empty:
                return False
            _sync_inventory_to_csv(df)
            return True
        except Exception:
            logger.exception("Failed to export CSV mirrors")
            return False

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
                    item_id = item['item_id']
                    quantity = float(item['quantity'])
                    txn.log_transaction(
                        item_id=item_id,
                        action='Open Tab',
                        quantity=quantity,
                        timestamp=timestamp,
                        cost_price=item.get('cost_price', 0),
                        sell_price=item.get('sell_price', 0),
                        reason=customer_name,
                        open_tab_id=tab_id
                    )
                    _deduct_stock_in_txn(txn, item_id, quantity)
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
                LEFT JOIN transactions t
                    ON ot.id = t.open_tab_id AND t.action = 'Open Tab'
                LEFT JOIN inventory i ON t.item_id = i.item_id
                WHERE ot.status = ?
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
    def close_open_tab_as_complimentary(tab_id, items):
        """Close an open tab as complimentary: remove stock, record no revenue.

        The stock was already deducted when the tab was opened. This method only
        reclassifies the tab as complimentary and logs Complimentary transactions
        for reporting.

        items: list of dicts with keys: item_id, quantity, cost_price, sell_price
        Returns True on success.
        """
        try:
            with AtomicTransaction() as txn:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                txn.cursor.execute(
                    "UPDATE open_tabs SET status = ?, closed_at = ? WHERE id = ?",
                    ('complimentary', timestamp, int(tab_id))
                )

                for item in items:
                    txn.log_transaction(
                        item_id=item['item_id'],
                        action='Complimentary',
                        quantity=item['quantity'],
                        timestamp=timestamp,
                        cost_price=item.get('cost_price', 0),
                        sell_price=item.get('sell_price', 0),
                        reason='Open tab closed as complimentary',
                        open_tab_id=tab_id
                    )
                return True
        except Exception as e:
            messagebox.showerror("Error", f"Failed to close tab as complimentary: {e}")
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

                # Log cancellation transactions and restore stock atomically.
                for item in items:
                    item_id = item['item_id']
                    quantity = float(item['quantity'])
                    txn.log_transaction(
                        item_id=item_id,
                        action='Tab Cancelled',
                        quantity=quantity,
                        timestamp=timestamp,
                        open_tab_id=tab_id
                    )
                    _restore_stock_in_txn(txn, item_id, quantity)

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
        # IMMEDIATE takes the write lock up front, so a deferred transaction
        # cannot fail later while trying to upgrade a read lock.
        self.conn.execute("BEGIN IMMEDIATE")
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
            # Returning False here would be ignored by the with-statement and
            # the caller would still report success.  Raise so the failure is
            # visible to the caller's except block.
            raise RuntimeError(f"Failed to commit transaction: {e}") from e

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

def record_stocktakes(entries, timestamp, note=''):
    """Record several stocktake entries in one database transaction.

    entries: list of dicts with item_id, counted_quantity, expected_quantity,
             variance.

    Recording each item in its own transaction (the old behaviour) meant a
    failure halfway through left a partially applied stocktake.  This writes
    all snapshots, quantities and adjustment rows together or not at all.
    """
    entries = list(entries or [])
    if not entries:
        return {'success': True, 'recorded': 0}
    try:
        with AtomicTransaction() as txn:
            for entry in entries:
                item_id = str(entry['item_id'])
                counted = float(entry['counted_quantity'])
                expected = float(entry['expected_quantity'])
                variance = float(entry['variance'])

                txn.cursor.execute("""
                    INSERT INTO stocktake_snapshots (item_id, counted_quantity, expected_quantity, variance, timestamp, note)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (item_id, counted, expected, variance, str(timestamp), str(note)))

                txn.update_inventory_quantity(item_id, counted)

                if variance != 0:
                    txn.log_transaction(
                        item_id=item_id,
                        action='Stocktake Adjustment',
                        quantity=variance,
                        timestamp=timestamp,
                        reason=note
                    )
        return {'success': True, 'recorded': len(entries)}
    except Exception as e:
        logger.exception("Failed to record stocktake")
        messagebox.showerror("Error", f"Failed to record stocktake: {e}")
        return {'success': False, 'recorded': 0, 'error': str(e)}


def record_stocktake(item_id, counted_quantity, expected_quantity, variance, timestamp, note=''):
    """Record a single stocktake entry. Kept for backwards compatibility."""
    result = record_stocktakes([{
        'item_id': item_id,
        'counted_quantity': counted_quantity,
        'expected_quantity': expected_quantity,
        'variance': variance,
    }], timestamp, note)
    return result['success']


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


def get_last_stocktake_summary(include_baseline=False, now=None):
    """Return the most recent stocktake and its age in days.

    The dashboard only needs one row, so this avoids loading the full history
    on every render. Baseline snapshots are bookkeeping rather than a physical
    count; they are excluded unless ``include_baseline`` is True.
    """
    now = now or datetime.now()
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        if include_baseline:
            cursor.execute(
                "SELECT timestamp, note FROM stocktake_snapshots "
                "ORDER BY timestamp DESC LIMIT 1")
        else:
            cursor.execute(
                "SELECT timestamp, note FROM stocktake_snapshots "
                "WHERE COALESCE(note, '') NOT LIKE '%Baseline%' "
                "ORDER BY timestamp DESC LIMIT 1")
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        timestamp_str, note = row[0], row[1]
        try:
            timestamp = datetime.fromisoformat(
                str(timestamp_str).replace('Z', '+00:00')).replace(tzinfo=None)
        except (TypeError, ValueError):
            timestamp = None
        return {
            'timestamp': timestamp_str,
            'datetime': timestamp,
            'note': note or '',
            'is_baseline': 'baseline' in str(note or '').lower(),
            'days_since': ((now - timestamp).days if timestamp else None),
        }
    except Exception:
        return None


def get_backup_health(warn_days=3, overdue_days=7, now=None):
    """Summarise the age of the newest backup for the dashboard."""
    now = now or datetime.now()
    backups = list_backups()
    if not backups:
        return {'latest': None, 'age_days': None, 'status': 'none'}
    try:
        latest = datetime.strptime(backups[0]['timestamp'], '%Y-%m-%d %H:%M:%S')
    except (KeyError, ValueError):
        return {'latest': None, 'age_days': None, 'status': 'unknown'}
    age_days = (now - latest).days
    if age_days >= overdue_days:
        status = 'overdue'
    elif age_days >= warn_days:
        status = 'warning'
    else:
        status = 'ok'
    return {
        'latest': latest,
        'name': backups[0].get('name', ''),
        'kind': backups[0].get('kind', ''),
        'age_days': age_days,
        'status': status,
    }


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


def get_baseline_reset_history(limit=100):
    """Get baseline reset audit history from the dedicated table."""
    import json
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, timestamp, items_count, archived_count, note, snapshot_json
            FROM baseline_resets
            ORDER BY timestamp DESC, id DESC
            LIMIT ?
        """, (int(limit),))
        rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        messagebox.showerror("Error", f"Failed to load baseline reset history: {e}")
        return []

    results = []
    for row in rows:
        snapshot = []
        if row["snapshot_json"]:
            try:
                snapshot = json.loads(row["snapshot_json"])
            except Exception:
                snapshot = []
        results.append({
            "id": row["id"],
            "timestamp": row["timestamp"],
            "items_count": row["items_count"],
            "archived_count": row["archived_count"],
            "note": row["note"],
            "snapshot": snapshot,
        })

    # One-off migration from the legacy JSON setting. Once the table has rows
    # the setting is no longer consulted, but legacy entries are imported if
    # the table is empty.
    if not results:
        raw = get_setting('baseline_resets', '[]')
        try:
            legacy = json.loads(raw)
            if isinstance(legacy, list) and legacy:
                results = [
                    {
                        "id": None,
                        "timestamp": entry.get("timestamp", ""),
                        "items_count": entry.get("items_count", 0),
                        "archived_count": entry.get("archived_count", 0),
                        "note": entry.get("note", ""),
                        "snapshot": [],
                    }
                    for entry in legacy
                ]
                results.sort(key=lambda x: x["timestamp"], reverse=True)
        except Exception:
            pass

    return results


def get_last_baseline_reset_date():
    """Return the timestamp of the most recent baseline reset, or None."""
    history = get_baseline_reset_history(limit=1)
    if not history:
        return None
    ts_str = history[0].get("timestamp", "")
    if not ts_str:
        return None
    try:
        return datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def add_baseline_reset(timestamp, items_count, archived_count, note='', snapshot=None):
    """Record a baseline reset event in the dedicated audit table.

    snapshot: optional list/dict of per-item baseline data (will be JSON-encoded).
    """
    import json
    snapshot_json = ''
    if snapshot is not None:
        try:
            snapshot_json = json.dumps(snapshot, default=str)
        except Exception:
            snapshot_json = ''

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = _get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO baseline_resets (timestamp, items_count, archived_count, note, snapshot_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            str(timestamp),
            int(items_count),
            int(archived_count),
            str(note),
            snapshot_json,
            created_at,
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        messagebox.showerror("Error", f"Failed to record baseline reset: {e}")
        return False


def reset_baseline(counted_items, timestamp, note=''):
    """Reset inventory baseline from a stocktake.

    This performs the baseline reset in one SQLite transaction:
      1. Archives transactions before the baseline timestamp for the items
         being reset.  Items that were not counted keep their history and
         their current stock.
      2. Removes any stale Stocktake Adjustment / Baseline rows at the baseline timestamp.
      3. Records the physical-count variance snapshot (so it contributes to running surplus).
      4. Records the new baseline snapshot with zero variance.
      5. Sets inventory quantities to the counted amounts.
      6. Logs new Stocktake Baseline transactions.
      7. Records the reset in the baseline_resets audit table.

    counted_items: list of dicts with keys: item_id, counted_system, input_value, input_unit
    timestamp: baseline timestamp string (YYYY-MM-DD HH:MM:SS)
    note: optional note for the snapshot/audit trail

    Returns a dict with success, archived_count, baseline_logged, saved_count, error.
    """
    if not counted_items:
        return {'success': False, 'error': 'No items were counted'}

    # A baseline reset archives history, so take a verified backup first and
    # refuse to proceed if it cannot be made.
    backup_path = create_backup('before_baseline_reset')
    if not backup_path:
        return {
            'success': False,
            'error': 'Could not create a safety backup; baseline reset cancelled.',
        }
    logger.info("Baseline reset backup: %s", backup_path)

    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()

        # 1. Archive old transactions before the baseline timestamp, but only
        #    for the items actually being reset.  The previous version archived
        #    every item while resetting only the counted ones, so counting a
        #    filtered search wiped the history of every other item.
        counted_ids = [str(item['item_id']) for item in counted_items]
        placeholders = ','.join('?' * len(counted_ids))
        archived_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(f"""
            INSERT INTO transaction_archive
            (item_id, action, quantity, timestamp, cost_price, sell_price, supplier,
             date_range, reason, user, member_qty, non_member_qty, open_tab_id, archived_at)
            SELECT item_id, action, quantity, timestamp, cost_price, sell_price, supplier,
                   date_range, reason, user, member_qty, non_member_qty, open_tab_id, ?
            FROM transactions
            WHERE timestamp < ? AND item_id IN ({placeholders})
        """, (archived_at, str(timestamp), *counted_ids))
        archived_count = cursor.rowcount
        cursor.execute(
            f"DELETE FROM transactions WHERE timestamp < ? AND item_id IN ({placeholders})",
            (str(timestamp), *counted_ids)
        )

        # 2. Clean up any stale baseline rows already stamped with this timestamp.
        cursor.execute("""
            DELETE FROM transactions
            WHERE timestamp = ? AND action IN ('Stocktake Adjustment', 'Stocktake Baseline')
        """, (str(timestamp),))

        # 3. Record snapshots, update inventory, and log baselines atomically.
        saved_count = 0
        baseline_logged = 0
        for item in counted_items:
            item_id = str(item['item_id'])
            counted = float(item['counted_system'])
            input_value = float(item['input_value'])
            input_unit = str(item['input_unit'])

            # Capture the variance BEFORE we overwrite inventory, so the running
            # surplus can still see the physical-count shortfall/surplus from this
            # stocktake. Use the current inventory quantity as the expected value.
            cursor.execute("SELECT quantity FROM inventory WHERE item_id = ?", (item_id,))
            row = cursor.fetchone()
            expected_before = float(row[0]) if row else counted
            variance = counted - expected_before

            # Variance snapshot for running surplus (non-baseline note)
            if variance != 0:
                variance_note = f"{note}: variance before baseline reset" if note else "Variance before baseline reset"
                cursor.execute("""
                    INSERT INTO stocktake_snapshots (item_id, counted_quantity, expected_quantity, variance, timestamp, note)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (item_id, counted, expected_before, variance, str(timestamp), variance_note))

            # Baseline snapshot with zero variance
            cursor.execute("""
                INSERT INTO stocktake_snapshots (item_id, counted_quantity, expected_quantity, variance, timestamp, note)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (item_id, counted, counted, 0.0, str(timestamp), str(note) + " (Baseline)"))

            cursor.execute("""
                UPDATE inventory SET quantity = ? WHERE item_id = ?
            """, (counted, item_id))

            reason = f"Baseline from physical count: {input_value:.1f} {input_unit}s"
            cursor.execute("""
                INSERT INTO transactions
                (item_id, action, quantity, timestamp, cost_price, sell_price, supplier,
                 date_range, reason, user, member_qty, non_member_qty, open_tab_id)
                VALUES (?, ?, ?, ?, 0, 0, '', '', ?, '', 0, 0, NULL)
            """, (item_id, 'Stocktake Baseline', counted, str(timestamp), reason))

            saved_count += 1
            baseline_logged += 1

        conn.commit()
        conn.close()
        conn = None

        # 4. Record audit trail.
        add_baseline_reset(timestamp, len(counted_items), archived_count, note, snapshot=counted_items)

        return {
            'success': True,
            'archived_count': archived_count,
            'baseline_logged': baseline_logged,
            'saved_count': saved_count,
        }
    except Exception as e:
        if conn:
            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass
        logger.exception("Failed to reset baseline")
        messagebox.showerror("Error", f"Failed to reset baseline: {e}")
        return {'success': False, 'error': str(e)}


def roll_forward_and_clean():
    """Clean up old snapshot/audit clutter after a baseline reset.

    This is the safe cleanup: it removes duplicate and stale baseline
    snapshots, but PRESERVES genuine variance snapshots from historical
    stocktakes so the all-time running surplus/shortfall stays intact.
    Old baseline_resets audit rows are removed, but the latest remains.
    The current inventory, current-period transactions, and the full
    transaction_archive are left untouched. A backup is created first.

    Returns a dict with success flag and counts of removed rows.
    """
    backup_path = create_backup('roll_forward_clean')
    if not backup_path:
        messagebox.showwarning("Backup Failed", "Could not create a backup before cleaning. Cleanup aborted.")
        return {'success': False, 'error': 'backup_failed'}

    conn = None
    try:
        conn = _get_connection()
        cursor = conn.cursor()

        # Find the latest baseline reset timestamp
        cursor.execute("""
            SELECT timestamp FROM baseline_resets
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
        """)
        row = cursor.fetchone()
        if not row:
            conn.close()
            messagebox.showinfo("Nothing to Clean", "No baseline reset records found.")
            return {'success': True, 'snapshots_removed': 0, 'resets_removed': 0}
        latest_ts = row["timestamp"]

        # 1. Delete baseline snapshots from any timestamp OTHER than the latest.
        #    Keep all variance snapshots (notes that do not contain 'Baseline').
        cursor.execute("""
            DELETE FROM stocktake_snapshots
            WHERE timestamp != ? AND (
                note LIKE '%Baseline%' OR note IS NULL OR note = ''
            )
        """, (latest_ts,))
        stale_baseline_removed = cursor.rowcount

        # 2. At the latest timestamp, keep only the newest baseline snapshot per item
        #    and remove exact duplicates. Variance snapshots are left alone.
        cursor.execute("""
            DELETE FROM stocktake_snapshots
            WHERE id IN (
                SELECT id FROM stocktake_snapshots s1
                WHERE s1.timestamp = ?
                  AND s1.note LIKE '%Baseline%'
                  AND s1.id NOT IN (
                      SELECT MAX(id) FROM stocktake_snapshots s2
                      WHERE s2.timestamp = s1.timestamp
                        AND s2.item_id = s1.item_id
                        AND s2.note LIKE '%Baseline%'
                  )
            )
        """, (latest_ts,))
        duplicate_baseline_removed = cursor.rowcount

        snapshots_removed = stale_baseline_removed + duplicate_baseline_removed

        # 3. Keep only the latest baseline_resets audit row
        cursor.execute("""
            DELETE FROM baseline_resets
            WHERE timestamp != ?
        """, (latest_ts,))
        resets_removed = cursor.rowcount

        conn.commit()
        conn.close()
        conn = None

        return {
            'success': True,
            'snapshots_removed': snapshots_removed,
            'resets_removed': resets_removed,
            'backup_path': backup_path,
        }
    except Exception as e:
        if conn:
            try:
                conn.rollback()
                conn.close()
            except Exception:
                pass
        messagebox.showerror("Error", f"Failed to roll forward and clean: {e}")
        return {'success': False, 'error': str(e)}


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
    """Get or create the backups directory.

    Backups sit beside the database they protect rather than beside the live
    data folder, so a test or tool pointed at a temporary database cannot
    write into -- or prune the retention of -- the real backups.
    """
    backups_dir = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), 'backups')
    os.makedirs(backups_dir, exist_ok=True)
    return backups_dir


def _copy_database(dest_path):
    """Copy the live database consistently and verify the copy."""
    source = sqlite3.connect(sqlite_ro_uri(DB_PATH), uri=True)
    target = sqlite3.connect(dest_path)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()

    check = sqlite3.connect(sqlite_ro_uri(dest_path), uri=True)
    try:
        return check.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        check.close()


def create_backup(reason=''):
    """Create a timestamped, integrity-checked backup of the database."""
    backup_path = None
    try:
        backups_dir = get_backups_dir()
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        reason_slug = reason.replace(' ', '_').replace('/', '_') if reason else 'manual'
        backup_name = f'barstock_backup_{timestamp}_{reason_slug}.db'
        backup_path = os.path.join(backups_dir, backup_name)
        status = _copy_database(backup_path)
        if status != 'ok':
            raise RuntimeError(f'backup failed integrity check: {status}')
        cleanup_old_backups()
        return backup_path
    except Exception:
        logger.exception('Backup failed')
        if backup_path and os.path.exists(backup_path):
            try:
                os.remove(backup_path)
            except Exception:
                pass
        return None


def cleanup_old_backups(max_backups=20):
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
        logger.warning("Could not prune old backups", exc_info=True)


def list_backups():
    """List available backups with metadata.

    Includes daily auto-backups as well as manual/pre-action backups, so the
    footer's "latest backup" and the restore menu agree on what exists.
    """
    try:
        backups_dir = get_backups_dir()
        paths = (glob.glob(os.path.join(backups_dir, 'barstock_backup_*.db'))
                 + glob.glob(os.path.join(backups_dir, 'barstock_auto_*.db')))
        backups = sorted(paths, key=os.path.getmtime, reverse=True)
        result = []
        for path in backups:
            name = os.path.basename(path)
            mtime = datetime.fromtimestamp(os.path.getmtime(path))
            size = os.path.getsize(path)
            result.append({
                'path': path,
                'name': name,
                'timestamp': mtime.strftime('%Y-%m-%d %H:%M:%S'),
                'size_kb': round(size / 1024, 1),
                'kind': 'auto' if name.startswith('barstock_auto_') else 'manual',
            })
        return result
    except Exception:
        return []


def verify_database(path):
    """Check that a file is a sound BarStock database.

    Returns (ok, message). Checks SQLite integrity and the presence of the two
    tables the app cannot run without, so a truncated or unrelated file can
    never replace the live database.
    """
    if not path or not os.path.exists(path):
        return False, 'file not found'
    try:
        conn = sqlite3.connect(sqlite_ro_uri(path), uri=True)
        try:
            status = conn.execute("PRAGMA integrity_check").fetchone()[0]
            if status != 'ok':
                return False, f'integrity check failed: {status}'
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        finally:
            conn.close()
    except Exception as e:
        return False, str(e)

    missing = {'inventory', 'transactions'} - tables
    if missing:
        return False, f"missing tables: {', '.join(sorted(missing))}"
    return True, 'ok'


def restore_backup(backup_path):
    """Restore the database from a backup after verifying both copies."""
    ok, message = verify_database(backup_path)
    if not ok:
        logger.error('Refusing to restore %s: %s', backup_path, message)
        return False, f'Backup is not usable: {message}'

    # The current database is copied aside first so a failed restore can be
    # undone by copying it back.
    pre_restore = create_backup('before_restore')
    if not pre_restore:
        return False, 'Could not create a pre-restore backup; restore cancelled.'

    temp_path = f'{DB_PATH}.restore.tmp'
    try:
        shutil.copy2(backup_path, temp_path)
        ok, message = verify_database(temp_path)
        if not ok:
            raise RuntimeError(f'restored copy failed verification: {message}')
        os.replace(temp_path, DB_PATH)
        logger.info('Restored database from %s (pre-restore backup: %s)',
                    backup_path, pre_restore)
        return True, pre_restore
    except Exception as e:
        logger.exception('Restore failed')
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass
        return False, f'Restore failed: {e}'


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
        status = _copy_database(backup_path)
        if status != 'ok':
            raise RuntimeError(f'auto-backup failed integrity check: {status}')
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
        logger.exception('Auto-backup failed')
        return None
