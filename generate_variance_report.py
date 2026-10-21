#!/usr/bin/env python3
"""Generate a pre-stocktake variance report from physical counts.

The counts file is supplied on the command line (CSV with ``name,quantity`` or
a JSON object); nothing is hardcoded. Run this before a stocktake to see which
items are short or over relative to the expected level from the transaction
log.

Usage::

    python3 generate_variance_report.py --counts counts.csv
    python3 generate_variance_report.py --counts counts.csv --output report.txt
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from apply_baseline_from_count import load_counts, resolve_counts
from conversions import STOCK_CONVERSIONS
from data_manager import InventoryDataManager
from reports import calculate_expected_remaining_series


def build_report(entries, expected_by_id, inventory_df, unmatched, generated_at):
    """Build the printable variance report text."""
    results = []
    for entry in entries:
        item_id = entry["item_id"]
        row = inventory_df[inventory_df["item_id"] == item_id].iloc[0]
        measure = str(row.get("measure", ""))
        expected_qty = float(expected_by_id.get(item_id.lower(), 0.0))
        variance = entry["counted_system"] - expected_qty

        if item_id in STOCK_CONVERSIONS:
            raw_unit = STOCK_CONVERSIONS[item_id][0]
            plural = {"box": "boxes", "carton": "cartons", "bottle": "bottles",
                      "barrel": "barrels"}.get(raw_unit, f"{raw_unit}s")
            physical_display = (
                f'{entry["input_value"]:.2f} {plural} = '
                f'{entry["counted_system"]:.1f} {measure}'
            )
        else:
            physical_display = f'{entry["counted_system"]:.1f} {measure}'

        results.append({
            "item_id": item_id,
            "name": str(row.get("item_name", item_id)),
            "measure": measure,
            "physical_display": physical_display,
            "expected": expected_qty,
            "variance": variance,
        })

    df = pd.DataFrame(results)
    if df.empty:
        return "No matched counts.\n", df

    df = df.sort_values("variance")

    lines = [
        "=" * 120,
        "PRE-STOCKTAKE VARIANCE REPORT",
        f"Generated: {generated_at}",
        "=" * 120,
        f"Items counted: {len(df)}",
    ]
    if unmatched:
        lines.append(f"Unmatched names: {unmatched}")
    lines.append("")
    lines.append(
        f'{"Item":<35} {"Physical":<28} {"Expected":>10} {"Variance":>10} {"Status":<10}'
    )
    lines.append("-" * 120)
    for _, row in df.iterrows():
        if row["variance"] < -0.01:
            status = "SHORT"
        elif row["variance"] > 0.01:
            status = "OVER"
        else:
            status = "OK"
        lines.append(
            f'{row["name"]:<35} {row["physical_display"]:<28} '
            f'{row["expected"]:>10.1f} {row["variance"]:>10.1f} {status:<10}'
        )

    lines.extend([
        "",
        "SUMMARY BY STATUS",
        "-" * 50,
        f"OK (variance ~0): {len(df[abs(df.variance) < 0.01])}",
        f"SHORT: {len(df[df.variance < -0.01])}",
        f"OVER: {len(df[df.variance > 0.01])}",
        "",
        "TOP 15 SHORTAGES (physical < expected - likely missing sales or over-stated baseline/deliveries)",
        "-" * 95,
    ])
    shortages = df[df.variance < -0.01].head(15)
    overs = df[df.variance > 0.01].sort_values("variance", ascending=False).head(15)

    if shortages.empty:
        lines.append("  None")
    for _, row in shortages.iterrows():
        lines.append(
            f'{row["name"]:<35} {row["physical_display"]:<28} '
            f'expected {row["expected"]:>8.1f} {row["measure"]:<8} '
            f'variance {row["variance"]:>8.1f}'
        )
    lines.extend([
        "",
        "TOP 15 OVERS (physical > expected - likely missing deliveries or under-stated sales)",
        "-" * 95,
    ])
    if overs.empty:
        lines.append("  None")
    for _, row in overs.iterrows():
        lines.append(
            f'{row["name"]:<35} {row["physical_display"]:<28} '
            f'expected {row["expected"]:>8.1f} {row["measure"]:<8} '
            f'variance {row["variance"]:>8.1f}'
        )

    return "\n".join(lines) + "\n", df


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-stocktake variance report.")
    parser.add_argument(
        "--counts", type=Path, required=True,
        help="CSV (name,quantity) or JSON object of physical counts.",
    )
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Write the report to this file instead of only printing it.",
    )
    args = parser.parse_args(argv)

    inventory_df = InventoryDataManager.load_inventory()
    if inventory_df.empty:
        print("Inventory is empty; nothing to report.")
        return 1

    try:
        raw_counts = load_counts(args.counts)
    except (OSError, ValueError) as exc:
        print(f"Could not read counts file: {exc}")
        return 2
    entries, unmatched = resolve_counts(raw_counts, inventory_df)
    expected = {
        str(key).lower(): float(value)
        for key, value in calculate_expected_remaining_series(
            InventoryDataManager.load_log(inventory_df)
        ).items()
    }

    report, df = build_report(
        entries, expected, inventory_df, unmatched,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    print(report)

    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(f"Report saved to: {args.output}")

    return 0 if not df.empty else 1


if __name__ == "__main__":
    sys.exit(main())
