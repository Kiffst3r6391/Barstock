#!/usr/bin/env python3
"""
Script to update 1.5L spirit stock quantities in the live SQLite database.

This script operates on barstock.db via InventoryDataManager instead of the legacy
stock.csv file. It creates a backup before making any changes.
"""

import os
import sys

# Ensure project modules are importable when run from anywhere
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_ROOT)

from data_manager import InventoryDataManager, create_backup, COL_QUANTITY, COL_ITEM_ID

# 1.5L spirits: their system quantity is stored in measures; 1 bottle = 43 measures.
PRODUCTS_1_5L = {
    'southern_comfort': 'Southern Comfort',
    'bacardi': 'Bacardi',
    'jack_daniels': 'Jack Daniels',
    'morgans': 'Morgans',
    'gordons_gin': 'Gordons Gin',
    'gordons_pink_gin': 'Gordons Pink Gin',
    'smirnoff': 'Smirnoff',
}


def main():
    print("=" * 60)
    print("BarStock 1.5L Spirit Stock Updater")
    print("=" * 60)

    inventory_df = InventoryDataManager.load_inventory()
    if inventory_df.empty:
        print("No inventory found in database.")
        return

    backup_path = create_backup('before_1.5L_update')
    if backup_path:
        print(f"\n✓ Backup created: {backup_path}")

    print("\n=== CHECKING 1.5L PRODUCTS ===")
    print("=" * 60)

    updated_count = 0
    for item_id, display_name in PRODUCTS_1_5L.items():
        if item_id not in inventory_df[COL_ITEM_ID].values:
            print(f"✗ {display_name:20} | NOT FOUND")
            continue

        current_qty = inventory_df.loc[inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY].iloc[0]
        # 1.5L bottle → measures conversion factor is 43.0, matching conversions.py.
        new_qty = current_qty * 43.0
        inventory_df.loc[inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] = round(new_qty, 3)

        print(f"✓ {display_name:20} | {current_qty:8.3f} measures → {new_qty:8.3f} measures")
        updated_count += 1

    print("=" * 60)
    print(f"Updated {updated_count} of {len(PRODUCTS_1_5L)} items\n")

    if InventoryDataManager.save_inventory(inventory_df):
        print("✓ Inventory saved to database successfully.")
    else:
        print("✗ Failed to save inventory. Restoring from backup may be required.")
        sys.exit(1)


if __name__ == "__main__":
    main()
