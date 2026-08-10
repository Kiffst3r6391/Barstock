#!/usr/bin/env python3
"""
Helper script to record a stocktake from physical counts, then reset baseline.

This does the same thing as the app's "Full Stocktake → Set as New Baseline" flow,
but can be run from the command line. It:

1. Creates a backup of the live SQLite database
2. Records a stocktake snapshot showing variance vs expected
3. Archives all transactions before the reset time
4. Sets inventory quantities to the physical counts
5. Logs new Stocktake Baseline entries

After running this, open the app and go to Reports → Stocktake Variance Report
to see the variance. A second stocktake with the same counts will show zero.

Usage:
    cd "/Users/kiffy/PGC Barstock"
    python3 apply_baseline_from_count.py

The physical counts are hardcoded below from the user's supplied list.
"""

import os
import sys
import json
import sqlite3
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_manager import DB_PATH, InventoryDataManager, create_backup
from conversions import STOCK_CONVERSIONS

# ---------------------------------------------------------------------------
# Physical counts as provided by the user (raw input units)
# ---------------------------------------------------------------------------
PHYSICAL_COUNTS_RAW = {
    'A/F kopparberg': 23,
    'Birra moretti zero': 61,
    'Budeiser': 47,
    'Corona': 115,
    'Fever tree SL': 105,
    'Fever tree': 82,
    "Inch's": 25,
    'Kopparberg': 17,
    'Magnets': 36,
    'Moretti bottle': 92,
    'Peroni': 38,
    'Old bout cider': 30,
    'Guinness 0.0': 20,
    'Belhaven best': 2.6,
    'Birra moretti': 2,
    'Guinness can': 44,
    'Joker ima': 2,
    "Tennent's": 2.6,
    'Thatchers': 1.8,
    'Nuts': 44,
    'Pringles': 69,
    'Walkers': 102,
    'Can': 498,
    'Carton juice': 55,
    'Coke PM': 3,
    'Cordial': 580,
    'Diet Coke PM': 3.5,
    'J20': 47,
    'Lemonade PM': 2.5,
    'Redbull': 37,
    'Angostura': 1,
    'Aperol': 3.7,
    'Bacardi': 1.7,
    'Baileys': 2.2,
    'Bombay saphire': 2.5,
    'Bowmore': 1.8,
    'Brockmans': 2,
    'Cointreau': 0.2,
    'Dead mans fingers': 0.8,
    'Disaronno': 1.2,
    'Drambuie': 0.6,
    'Edinburgh R&G': 2.8,
    'Glayva': 1.3,
    'Glen Scotia': 2,
    'Glenmorangie': 4.1,
    'Gordons gin': 2.8,
    'Gordons pink gin': 3.3,
    'Havana': 0.7,
    'Highland park': 4,
    'Jack daniels': 1.5,
    'Jagermeister': 3.5,
    'Jura': 2.8,
    'Kraken': 2.6,
    'Malibu': 2.3,
    'Martiell': 2.3,
    'kahlua': 2,
    'Morgans': 2,
    'Peach schnapps': 2.7,
    'Pimms': 0.2,
    'Port': 3.2,
    'Sambuca': 1.4,
    'Smirnoff': 4.3,
    'sourz': 2.1,
    'Southern comfort': 1.3,
    'Tanqueray': 2.8,
    'Tanqueray Sevilla': 4,
    'Tequila': 1.4,
    'Tequilla rose': 2.2,
    'Whitley neil': 3,
    'Culling view': 9,
    'Prosecco': 20,
    'Prosecco single serve': 24,
    'Short mile merlot': 12,
    'Single serve wine': 278,
    'Whispering hills white zinfandel': 4,
    'Wicked lady pinot Grigio': 12,
    'Zarapito malbec': 16,
}

NAME_CORRECTIONS = {
    'Budeiser': 'Budweiser',
    'Fever tree SL': 'Fevertree SL Tonic',
    'Magnets': 'Magners',
    'Old bout cider': 'old mout cider',
    'Joker ima': 'Joker IPA',
    'J20': 'J2O',
    'Bombay saphire': 'Bombay Sapphire',
    'Martiell': 'Martell',
    'Tequilla rose': 'Tequila Rose',
    'Whitley neil': 'Whitley Neill Gin',
    'Culling view': 'Cullinan View Sauvignon Blanc',
    "Tennent's": 'Tennents Lager',
    'Guinness can': 'Guinness Can',
    'Belhaven best': 'Belhaven Best',
    'Birra moretti': 'Birra Moretti',
    'Thatchers': 'Thatchers',
    'Carton juice': 'Carton Juice',
    'Coke PM': 'Coke PM',
    'Diet Coke PM': 'Diet Coke PM',
    'Lemonade PM': 'Lemonade PM',
    'Redbull': 'Red Bull',
    'Fever tree': 'Fevertree Tonic',
    'Moretti bottle': 'Moretti Bottle',
    "Inch's": 'Inchs',
    'Birra moretti zero': 'Birra Moretti Zero',
    'A/F kopparberg': 'A/F Koppaberg',
    'kahlua': 'Kahlua',
    'sourz': 'Sourz',
    'Southern comfort': 'Southern Comfort',
    'Gordons gin': 'Gordons Gin',
    'Gordons pink gin': 'Gordons Pink Gin',
    'Highland park': 'Highland Park',
    'Jack daniels': 'Jack Daniels',
    'Glen Scotia': 'Glen Scotia',
    'Dead mans fingers': 'Dead Mans Fingers',
    'Short mile merlot': 'Short Mile Bay Merlot',
    'Wicked lady pinot Grigio': 'Wicked Lady Pinot Grigio',
    'Whispering hills white zinfandel': 'Whispering Hills White Zinfandel',
    'Zarapito malbec': 'Zarapito Malbec',
    'Prosecco single serve': 'Prosecco Single Serve',
    'Single serve wine': 'Single Serve Wine',
    'Baileys': 'Baileys 50ml',
    'Brockmans': 'Brockmans Gin',
    'Havana': 'Havana Club 7',
    'Jura': 'Jura Origin',
    'Kraken': 'Kraken Rum',
}


def convert_count_to_system(name, raw_qty):
    """Convert raw physical count to system units."""
    corrected = NAME_CORRECTIONS.get(name, name)
    # Build item_id using the same rules as normalize_product_name in sales_mapping
    item_id = corrected.lower()
    for char in ('&', '/', "'", '"', '.'):
        item_id = item_id.replace(char, '')
    for char in (' ', '-'):
        item_id = item_id.replace(char, '_')
    while '__' in item_id:
        item_id = item_id.replace('__', '_')
    item_id = item_id.strip('_')

    if item_id in STOCK_CONVERSIONS:
        return item_id, raw_qty * STOCK_CONVERSIONS[item_id][1]
    return item_id, raw_qty


def main():
    print("=" * 70)
    print("Apply Baseline from Physical Count")
    print("=" * 70)

    # 1. Backup
    backup_path = create_backup('before_baseline_from_count')
    print(f"\n1. Backup created:\n   {backup_path}")

    # 2. Load data
    inventory_df = InventoryDataManager.load_inventory()
    log_df = InventoryDataManager.load_log()
    from reports import calculate_expected_remaining_series
    expected_remaining = calculate_expected_remaining_series(log_df)

    name_to_id = {str(row['item_name']).lower(): row['item_id'] for _, row in inventory_df.iterrows()}

    # 3. Convert physical counts and build baseline map
    baseline_counts = {}
    skipped = []
    for raw_name, raw_qty in PHYSICAL_COUNTS_RAW.items():
        corrected = NAME_CORRECTIONS.get(raw_name, raw_name)
        item_id = name_to_id.get(corrected.lower())
        if item_id is None:
            skipped.append(raw_name)
            continue
        _, system_qty = convert_count_to_system(raw_name, raw_qty)
        baseline_counts[item_id] = system_qty

    print(f"\n2. Matched {len(baseline_counts)} physical count items")
    if skipped:
        print(f"   Skipped {len(skipped)} unmatched names: {', '.join(skipped)}")

    # 4. Record stocktake snapshots BEFORE baseline reset (shows variance)
    snapshot_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Baseline timestamp is 1 second later so it is NOT archived/deleted
    baseline_timestamp = (datetime.now().replace(microsecond=0) + __import__('datetime').timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    recorded = 0
    for item_id, counted_qty in baseline_counts.items():
        inv_row = inventory_df[inventory_df['item_id'] == item_id]
        if inv_row.empty:
            continue
        current_stock = float(inv_row['quantity'].iloc[0])
        expected_qty = current_stock - float(expected_remaining.get(item_id, 0))
        variance = counted_qty - expected_qty
        cursor.execute(
            """INSERT INTO stocktake_snapshots
               (item_id, counted_quantity, expected_quantity, variance, timestamp, note)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (item_id, counted_qty, expected_qty, variance, snapshot_timestamp,
             'Pre-baseline stocktake from physical count list')
        )
        recorded += 1
    conn.commit()
    print(f"\n3. Recorded {recorded} stocktake snapshot entries (showing variance)")

    # 5. Archive all transactions BEFORE the baseline timestamp
    cursor.execute(
        """INSERT INTO transaction_archive
           (item_id, action, quantity, timestamp, cost_price, sell_price, supplier,
            date_range, reason, user, member_qty, non_member_qty, open_tab_id, archived_at)
           SELECT item_id, action, quantity, timestamp, cost_price, sell_price, supplier,
                  date_range, reason, user, member_qty, non_member_qty, open_tab_id, ?
           FROM transactions WHERE timestamp < ?""",
        (baseline_timestamp, baseline_timestamp)
    )
    archived_count = cursor.rowcount
    cursor.execute("DELETE FROM transactions WHERE timestamp < ?", (baseline_timestamp,))
    conn.commit()
    print(f"\n4. Archived {archived_count} transactions")

    # 6. Set inventory quantities to physical counts
    updated = 0
    for item_id, counted_qty in baseline_counts.items():
        cursor.execute("UPDATE inventory SET quantity = ? WHERE item_id = ?",
                       (counted_qty, item_id))
        if cursor.rowcount:
            updated += 1
    conn.commit()
    print(f"\n5. Updated {updated} inventory items to baseline quantities")

    # 7. Log new baseline entries at the later baseline timestamp
    placeholders = ','.join('?' * len(baseline_counts))
    cursor.execute(
        f"""INSERT INTO transactions
            (item_id, action, quantity, timestamp, cost_price, sell_price, supplier,
             date_range, reason, user, member_qty, non_member_qty, open_tab_id)
            SELECT item_id, 'Stocktake Baseline', quantity, ?, cost_price, sell_price,
                   '', '', 'Baseline reset from physical count', '', 0, 0, NULL
            FROM inventory WHERE item_id IN ({placeholders})""",
        (baseline_timestamp,) + tuple(baseline_counts.keys())
    )
    baseline_logged = cursor.rowcount
    conn.commit()
    print(f"\n6. Logged {baseline_logged} new baseline entries")

    # 8. Record reset event
    reset_record = {
        'timestamp': baseline_timestamp,
        'items_count': len(baseline_counts),
        'archived_count': archived_count,
        'note': 'Baseline from physical count list via apply_baseline_from_count.py',
    }
    cursor.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES ('baseline_resets', ?)",
        (json.dumps([reset_record]),)
    )
    conn.commit()
    conn.close()

    print("\n" + "=" * 70)
    print("DONE")
    print("=" * 70)
    print(f"Snapshot time: {snapshot_timestamp}")
    print(f"Baseline time: {baseline_timestamp}")
    print("\nNext steps:")
    print("  1. Open dist/BarStock.app")
    print("  2. Go to Reports → Stocktake Variance Report")
    print("     This will show the variance from the stocktake just recorded.")
    print("  3. Do a second Full Stocktake with the same counts")
    print("     The variance report will then show zero.")
    print(f"\nIf anything goes wrong, restore the backup:\n   {backup_path}")


if __name__ == '__main__':
    main()
