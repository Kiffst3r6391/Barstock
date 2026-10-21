#!/usr/bin/env python3
"""Record a physical stocktake and reset the baseline from the command line.

This performs the same operation as the app's
"Full Stocktake -> Set as New Baseline" flow, using the same audited code path
(``data_manager.reset_baseline``): it takes a verified backup, records the
variance snapshot, archives the pre-baseline history for the counted items,
sets inventory to the physical counts, logs new baseline rows, and writes the
reset to the ``baseline_resets`` audit table.

Counts are never hardcoded. Supply a CSV with ``name,quantity`` columns (or a
JSON object mapping name to quantity). Names are matched with the same
normaliser the uploads use, so shorthand from the count sheet is accepted.

Usage::

    python3 apply_baseline_from_count.py --counts counts.csv          # dry run
    python3 apply_baseline_from_count.py --counts counts.csv --run    # apply

The script is a dry run unless ``--run`` is passed.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conversions import STOCK_CONVERSIONS
from data_manager import InventoryDataManager, reset_baseline
from sales_mapping import normalize_product_name

# Legacy spelling corrections from the printed count sheets. These only map
# names the user actually wrote to the canonical inventory name; they do not
# carry quantities.
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


def load_counts(path: Path) -> dict[str, float]:
    """Read counts from a CSV (name,quantity) or JSON object file."""
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON counts file must be an object of name -> quantity")
        return {str(k): float(v) for k, v in data.items()}

    counts: dict[str, float] = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError("CSV counts file is empty")
        name_field = next(
            (f for f in reader.fieldnames if f.strip().lower() in ("name", "item", "item_name")),
            reader.fieldnames[0],
        )
        qty_field = next(
            (f for f in reader.fieldnames if f.strip().lower() in ("quantity", "qty", "count")),
            reader.fieldnames[-1],
        )
        for row in reader:
            name = str(row.get(name_field, "")).strip()
            raw_qty = str(row.get(qty_field, "")).strip()
            if not name or not raw_qty:
                continue
            counts[name] = float(raw_qty)
    return counts


def resolve_counts(raw_counts: dict[str, float], inventory_df) -> tuple[list[dict], list[str]]:
    """Map printed names to inventory items and convert to system units."""
    by_name = {}
    by_id = {}
    for _, row in inventory_df.iterrows():
        item_id = str(row["item_id"])
        by_name[str(row["item_name"]).strip().lower()] = item_id
        by_id[normalize_product_name(item_id)] = item_id
        by_id[normalize_product_name(str(row["item_name"]))] = item_id

    entries: list[dict] = []
    unmatched: list[str] = []
    for raw_name, raw_qty in raw_counts.items():
        corrected = NAME_CORRECTIONS.get(raw_name, raw_name)
        item_id = by_name.get(corrected.strip().lower())
        if item_id is None:
            item_id = by_id.get(normalize_product_name(corrected))
        if item_id is None:
            unmatched.append(raw_name)
            continue

        if item_id in STOCK_CONVERSIONS:
            unit_label, factor = STOCK_CONVERSIONS[item_id][:2]
            counted_system = float(raw_qty) * float(factor)
            input_unit = str(unit_label)
        else:
            counted_system = float(raw_qty)
            row = inventory_df[inventory_df["item_id"] == item_id].iloc[0]
            input_unit = str(row.get("measure", "unit")).lower()

        entries.append({
            "item_id": item_id,
            "counted_system": counted_system,
            "input_value": float(raw_qty),
            "input_unit": input_unit,
        })
    return entries, unmatched


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record a physical stocktake and reset the baseline."
    )
    parser.add_argument(
        "--counts", type=Path, required=True,
        help="CSV (name,quantity) or JSON object of physical counts.",
    )
    parser.add_argument(
        "--run", action="store_true",
        help="Apply the reset. Without this flag the script only previews.",
    )
    parser.add_argument("--note", default="", help="Note stored with the reset.")
    args = parser.parse_args(argv)

    print("=" * 70)
    print("Apply Baseline from Physical Count")
    print("=" * 70)

    try:
        raw_counts = load_counts(args.counts)
    except (OSError, ValueError) as exc:
        print(f"\nCould not read counts file: {exc}")
        return 2
    inventory_df = InventoryDataManager.load_inventory()
    entries, unmatched = resolve_counts(raw_counts, inventory_df)

    print(f"\nCounts file: {args.counts}")
    print(f"Matched: {len(entries)} of {len(raw_counts)} lines")
    if unmatched:
        print("Unmatched names (will be skipped):")
        for name in unmatched:
            print(f"  • {name}")

    print("\nPreview (counted vs current stock):")
    for entry in entries:
        row = inventory_df[inventory_df["item_id"] == entry["item_id"]].iloc[0]
        current = float(row["quantity"])
        variance = entry["counted_system"] - current
        print(
            f"  {entry['item_id']:<28} {current:>9.2f} -> {entry['counted_system']:>9.2f} "
            f"({variance:+.2f})"
        )

    if not entries:
        print("\nNothing to apply.")
        return 1

    if not args.run:
        print("\nDry run only. Pass --run to take a backup and apply the reset.")
        return 0

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    result = reset_baseline(entries, timestamp, note=args.note or "CLI baseline reset")

    if not result.get("success"):
        print(f"\nBaseline reset failed: {result.get('error', 'unknown error')}")
        return 1

    print("\nBaseline reset complete.")
    print(f"  Timestamp: {timestamp}")
    print(f"  Items reset: {result.get('saved_count', len(entries))}")
    print(f"  Transactions archived: {result.get('archived_count', 0)}")
    print(f"  Baseline rows written: {result.get('baseline_logged', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
