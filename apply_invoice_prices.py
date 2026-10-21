"""One-off script: apply all Booker invoice prices from INVOICES/ to live stock.

This script is intentionally self-contained and produces backups before writing
anything.  It uses the same parsing, VAT, unit-conversion and can-average rules as
BarStockApp.upload_delivery_invoice_price_check().
"""
from __future__ import annotations

import csv
import os
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd
import pdfplumber

# Make sure repo modules can be imported
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from conversions import get_conversion  # noqa: E402
from inventory_sync import update_items_csv_total_value  # noqa: E402
from data_manager import (  # noqa: E402
    InventoryDataManager,
    get_resource_path,
    COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE,
    COL_SELL_PRICE, COL_MEASURE, COL_ACTION, COL_TIMESTAMP,
    COL_SUPPLIER, COL_DATE_RANGE, COL_REASON,
)


INVOICE_DIR = SCRIPT_DIR / "INVOICES"
DATA_DIR = Path(get_resource_path())
DB_PATH = DATA_DIR / "barstock.db"
STOCK_CSV = DATA_DIR / "stock.csv"
LOG_CSV = DATA_DIR / "transaction_log.csv"
ITEMS_CSV = SCRIPT_DIR / "Items.csv"
REPORT_DIR = SCRIPT_DIR / "invoice_price_reports"

# Same mapping as BarStockApp._get_invoice_to_item_mapping()
INVOICE_TO_ITEM = {
    'britvic lime cordial': 'cordial',
    'tetley tea bags 1100s': 'tea',
    'walkers crisp cheese & onion': 'walkers',
    'walkers crisps ready salted': 'walkers',
    'walkers prawn cocktail 32.5g': 'walkers',
    'walkers salt & vinegar 32.5g': 'walkers',
    'kp dry roasted peanut p card 21 50g': 'nuts',
    'kp original saltd pnut card 21 50g': 'nuts',
    'sunpride orange juice 12 1ltr': 'carton_juice',
    'apple juice': 'carton_juice',
    'orange juice': 'carton_juice',
    'cranberry juice': 'carton_juice',
    'pineapple juice': 'carton_juice',
    'pringles bbq': 'pringles',
    'pringles original': 'pringles',
    'pringles salt & vinegar': 'pringles',
    'pringles sour cream & onion': 'pringles',
    'coca cola can': 'can',
    'diet coke can': 'can',
    'sprite can': 'can',
    'tango orange can': 'can',
    'irn bru': 'can',
    'irn bru sugar free': 'can',
    'old jamaica ginger beer': 'can',
    'coke zero': 'can',
    'fanta lemon': 'can',
    'red bull': 'red_bull',
    'red bull energy drink pm175': 'red_bull',
    'corona extra nrb 4.5%': 'corona',
    'peroni nastro azzurro': 'peroni',
    'budweiser': 'budweiser',
    'magners irish cider nrb': 'magners',
    'inchs medium apple cider': 'inchs',
    'kopparberg mixed fruit cider': 'kopparberg',
    'kopparberg strbry&lime cider': 'kopparberg',
    'kopparberg 0% mixed fruit': 'a_f_koppaberg',
    'kopparberg non alcohol s/bry': 'a_f_koppaberg',
    'old mout pineapple & r/berry': 'old_mout_cider',
    'gordons gin': 'gordons_gin',
    'gordons pink gin 35%': 'gordons_pink_gin',
    'smirnoff red': 'smirnoff',
    'jack daniels': 'jack_daniels',
    'bombay sapphire': 'bombay_sapphire',
    'disaronno': 'disaronno',
    'antica sambuca classic': 'sambuca',
    'malibu 18%': 'malibu',
    'sierra tequila blanco 35%': 'tequila',
    'havana club 7 year old rum': 'havana_club_7',
    'archers peach schnapps': 'peach_schnapps',
    'old pulteney 12yo m/whisky': 'old_pulteney',
    'bowmore 12yo sgl malt': 'bowmore',
    'glenmorangie 12yo malt': 'glenmorangie',
    'martell vs cognac': 'martell',
    'brockmans gin': 'brockmans_gin',
    'kraken spiced rum 70cl': 'kraken_rum',
    'bacardi carta blanca': 'bacardi',
    'cointreau': 'cointreau',
    'dead mans fingers spiced rum': 'dead_mans_fingers',
    'fever tree prem indian tonic': 'tonic',
    'f/tree refreshingly lghttnic': 'tonic',
    'fever tree r/l ginger ale': 'tonic',
    'fever tree r/l mediterranean': 'tonic',
    'fever tree light tonic': 'fevertree_sl_tonic',
    'glen scotia dbl csk sgl malt': 'glen_scotia',
    'highland spring water stillpet': 'soda_water',
    'j20 apple & mango': 'j2o',
    'j20 orange & passionfruit': 'j2o',
    'prosecco spumante doc ex dry': 'prosecco',
    'prosecco spumante': 'prosecco',
    'schweppes lemonade bag inbox': 'lemonade',
    'schweppes lemonade bag in box': 'lemonade',
    'cockburns port spec reserve': 'port',
    'coca cola original bib': 'coke_pm',
    'diet coke bag in box': 'diet_coke_pm',
    'birra moretti 0%': 'birra_moretti_zero',
    'birra moretti nrb uk': 'moretti_bottle',
    'h/land spring water stillpet': 'soda_water',
    'aperol': 'aperol',
    'baileys irish cream': 'baileys_50ml',
    'captain morgan spiced rum': 'morgans',
    'highland park 12yo malt': 'highland_park',
    'jura 12yr': 'jura_origin',
    'kahlua coffee liqueur': 'kahlua',
    'tanqueray sevilla': 'tanqueray_sevilla',
    'magners 4x500ml': 'magners',
    # Booker draught kegs
    'poretti': 'poretti',
    'innis and gunn': 'innis_and_gunn',
    'innis & gunn': 'innis_and_gunn',
    'orchard pig': 'orchard_pig',
    'guinness keg': 'guinness',
    'guinness draught': 'guinness',
    'caledonian best': 'caledonian_best',
}

CAN_AVERAGE_GROUP = [
    'coca cola can', 'diet coke can', 'irn bru', 'irn bru sugar free',
    'coke zero', 'fanta lemon', 'sprite can', 'old jamaica ginger beer',
]

CARTON_JUICE_AVERAGE_GROUP = [
    'apple juice',
    'orange juice',
    'cranberry juice',
    'pineapple juice',
]

SKIP_KEYWORDS = [
    'refuse', 'sack', 'bleach', 'floor gel', 'sachet', 'mayonnaise',
    'hp sauce', 'clean pro', 'lichfield', 'neapolitan', 'surface',
    'surger', 'cp ', 'es citrus',
]


def parse_booker_invoice_line(line: str):
    """Mirror of BarStockApp._parse_booker_invoice_line."""
    if any(k in line for k in ['Order No:', 'Customer:', 'VAT No:', 'BOOKER', 'Page', 'Sub Total', 'Total', 'VAT']):
        return None
    tokens = line.split()
    if len(tokens) < 5:
        return None

    price_idx = None
    unit_price = None
    for i in range(2, len(tokens)):
        tok = tokens[i].replace('£', '').replace(',', '')
        if re.match(r'^-?\d+\.\d{2,}$', tok):
            price_idx = i
            unit_price = float(tok)
            break
    if price_idx is None:
        return None

    if not re.match(r'^-?\d+$', tokens[price_idx - 1]):
        return None
    invoice_qty = int(tokens[price_idx - 1])

    case_size = 1
    if price_idx - 2 >= 1:
        unit_token = tokens[price_idx - 2]
        if re.match(r'^\d+(?:\.\d+)?(?:ml|cl|ltr|l|g|s)?$', unit_token, re.I) or 'x' in unit_token.lower():
            if price_idx - 3 >= 1 and re.match(r'^\d+$', tokens[price_idx - 3]):
                case_size = int(tokens[price_idx - 3])

    full_description = ' '.join(tokens[1:price_idx - 1])
    if any(k in full_description.lower() for k in ['out of stock', 'delisted', 'substitute', 'alternative', 'credit', 'charge', 'delivery', 'refund']):
        return None

    vat_code = 'B'
    if price_idx + 3 < len(tokens):
        candidate = tokens[price_idx + 3].upper()
        if candidate in ('A', 'B'):
            vat_code = candidate

    return full_description, invoice_qty, case_size, unit_price, vat_code


def invoice_price_ex_vat(unit_price_ex: float, vat_code: str) -> float:
    """Mirror of BarStockApp._invoice_price_ex_vat.

    The system now stores prices ex-VAT, so the invoice ex-VAT price is used
    directly without adding VAT.
    """
    return unit_price_ex


def units_per_case_from_desc(desc: str, case_size: int) -> int:
    """Mirror of BarStockApp._units_per_case_from_desc."""
    d = desc.lower()
    m = re.search(r'(\d+)\s*x\s*\d+(?:ml|cl|ltr|l|g|s)\b', d)
    if m:
        return case_size * int(m.group(1))
    m = re.search(r'(\d+)\s*s\b', d)
    if m:
        return int(m.group(1))
    return case_size


def invoice_unit_matches_conversion(desc: str, input_unit: str) -> bool:
    """Mirror of BarStockApp._invoice_unit_matches_conversion."""
    d = desc.lower()
    if input_unit == 'bottle':
        return any(k in d for k in ['bottle', 'ltr', 'cl', 'ml', '75cl', '70cl', '1.5ltr'])
    if input_unit == 'box':
        return any(k in d for k in ['bag in box', 'bib', 'box', '7ltr'])
    if input_unit == 'barrel':
        return any(k in d for k in ['barrel', 'keg', 'firkin'])
    if input_unit == 'carton':
        return any(k in d for k in ['carton'])
    return False


def map_invoice_description_to_item_id(desc: str, inventory_ids: set) -> str | None:
    """Mirror of BarStockApp._map_invoice_description_to_item_id."""
    desc_lower = desc.lower().strip()
    for key in sorted(INVOICE_TO_ITEM.keys(), key=len, reverse=True):
        if desc_lower.startswith(key) or key in desc_lower:
            return INVOICE_TO_ITEM[key]
    if desc_lower in inventory_ids:
        return desc_lower
    return None


def is_can_average_description(desc: str) -> bool:
    """Mirror of BarStockApp._is_can_average_description."""
    desc_lower = desc.lower().strip()
    return any(desc_lower.startswith(key) or key in desc_lower for key in CAN_AVERAGE_GROUP)


def is_carton_juice_average_description(desc: str) -> bool:
    """Mirror of BarStockApp._is_carton_juice_average_description."""
    desc_lower = desc.lower().strip()
    return any(desc_lower.startswith(key) or key in desc_lower for key in CARTON_JUICE_AVERAGE_GROUP)


def compute_can_average_cost(invoice_lines: list) -> tuple[float, int]:
    """Mirror of BarStockApp._compute_can_average_cost."""
    total_ex_value = 0.0
    total_units = 0
    for desc, qty, case_size, price, vat_code in invoice_lines:
        if not is_can_average_description(desc):
            continue
        upc = units_per_case_from_desc(desc, case_size)
        total_units += qty * upc
        total_ex_value += qty * invoice_price_ex_vat(price, vat_code)
    if total_units == 0:
        return 0.0, 0
    return total_ex_value / total_units, total_units


def compute_carton_juice_average_cost(invoice_lines: list) -> tuple[float, int]:
    """Mirror of BarStockApp._compute_carton_juice_average_cost."""
    from conversions import PINTS_PER_LITRE
    total_ex_value = 0.0
    total_litres = 0
    for desc, qty, case_size, price, vat_code in invoice_lines:
        if not is_carton_juice_average_description(desc):
            continue
        upc = units_per_case_from_desc(desc, case_size)
        total_litres += qty * upc
        total_ex_value += qty * invoice_price_ex_vat(price, vat_code)
    if total_litres == 0:
        return 0.0, 0
    per_litre = total_ex_value / total_litres
    per_pint = per_litre / PINTS_PER_LITRE
    return per_pint, total_litres


def backup_files(timestamp: str) -> Path:
    """Backup live DB and CSVs, return backup directory path."""
    backup_dir = SCRIPT_DIR / f"Backups_pre_invoice_update_{timestamp}"
    backup_dir.mkdir(exist_ok=True)
    files_to_backup = [
        (DB_PATH, backup_dir / "barstock.db"),
        (STOCK_CSV, backup_dir / "stock.csv"),
        (LOG_CSV, backup_dir / "transaction_log.csv"),
        (ITEMS_CSV, backup_dir / "Items.csv"),
    ]
    for src, dst in files_to_backup:
        if src.exists():
            shutil.copy2(src, dst)
            print(f"Backed up: {src} -> {dst}")
    return backup_dir


def main() -> None:
    if not INVOICE_DIR.exists():
        print(f"Invoice directory not found: {INVOICE_DIR}")
        sys.exit(1)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = backup_files(timestamp)
    report_dir = REPORT_DIR
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / f"invoice_price_update_{timestamp}.txt"

    # Parse all Booker invoice PDFs
    pdf_paths = sorted(INVOICE_DIR.glob("Booker-Invoice-*.pdf"))
    if not pdf_paths:
        pdf_paths = sorted(INVOICE_DIR.glob("*.pdf"))
    if not pdf_paths:
        print("No PDF invoices found.")
        sys.exit(1)

    invoice_lines = []
    for pdf_path in pdf_paths:
        print(f"Parsing {pdf_path.name}...")
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if not text:
                    continue
                for line in text.split('\n'):
                    parsed = parse_booker_invoice_line(line)
                    if parsed:
                        invoice_lines.append(parsed)

    print(f"Parsed {len(invoice_lines)} product lines from {len(pdf_paths)} invoice(s).")

    # Aggregate duplicate descriptions
    aggregated = defaultdict(lambda: {'qty': 0, 'price': 0.0, 'case_size': 1, 'vat_code': 'B'})
    for desc, qty, case_size, price, vat_code in invoice_lines:
        key = desc.lower().strip()
        aggregated[key]['qty'] += qty
        aggregated[key]['price'] = price
        aggregated[key]['case_size'] = case_size
        aggregated[key]['vat_code'] = vat_code

    # Load current inventory
    inventory_df = InventoryDataManager.load_inventory()
    inventory_ids = {str(i).lower().strip() for i in inventory_df[COL_ITEM_ID].values}
    # Case-insensitive lookup from item_id to exact DataFrame key
    id_lookup = {str(i).lower().strip(): str(i) for i in inventory_df[COL_ITEM_ID].values}
    cost_by_id = {str(k).lower(): v for k, v in zip(inventory_df[COL_ITEM_ID], inventory_df[COL_COST_PRICE])}
    name_by_id = {str(k).lower(): v for k, v in zip(inventory_df[COL_ITEM_ID], inventory_df[COL_ITEM_NAME])}
    measure_by_id = {str(k).lower(): v for k, v in zip(inventory_df[COL_ITEM_ID], inventory_df[COL_MEASURE])}
    qty_by_id = {str(k).lower(): v for k, v in zip(inventory_df[COL_ITEM_ID], inventory_df[COL_QUANTITY])}

    comparison_rows = []
    unmatched = []
    mapped_item_ids_seen = set()

    can_avg, total_cans = compute_can_average_cost(invoice_lines)
    if total_cans > 0 and 'can' in inventory_ids:
        current = cost_by_id.get('can', 0.0)
        comparison_rows.append({
            'item_id': 'can',
            'item_name': name_by_id.get('can', 'Can'),
            'invoice_desc': f"Weighted average across {total_cans} units (Can/J20 mix)",
            'measure': measure_by_id.get('can', ''),
            'invoice_unit': 'can',
            'current_cost': current,
            'invoice_cost': can_avg,
            'diff': can_avg - current,
            'diff_pct': (can_avg - current) / current * 100 if current else 0.0,
        })
        mapped_item_ids_seen.add('can')

    carton_juice_avg, total_litres = compute_carton_juice_average_cost(invoice_lines)
    if total_litres > 0 and 'carton_juice' in inventory_ids:
        current = cost_by_id.get('carton_juice', 0.0)
        comparison_rows.append({
            'item_id': 'carton_juice',
            'item_name': name_by_id.get('carton_juice', 'Carton Juice'),
            'invoice_desc': f"Weighted average across {total_litres:.0f} litres (Apple/Orange/Cranberry/Pineapple mix, converted to £/pint)",
            'measure': measure_by_id.get('carton_juice', ''),
            'invoice_unit': 'pint',
            'current_cost': current,
            'invoice_cost': carton_juice_avg,
            'diff': carton_juice_avg - current,
            'diff_pct': (carton_juice_avg - current) / current * 100 if current else 0.0,
        })
        mapped_item_ids_seen.add('carton_juice')

    for desc, data in aggregated.items():
        item_id = map_invoice_description_to_item_id(desc, inventory_ids)

        # Skip non-stock / cleaning / refuse lines
        if item_id is None:
            if any(k in desc for k in SKIP_KEYWORDS):
                continue
            unmatched.append(desc)
            continue

        # Ignore invoice lines not in current stock list
        if item_id not in cost_by_id:
            continue

        # Ignore tea per user instruction
        if item_id == 'tea':
            continue

        # Can-average and carton-juice lines are handled once above
        if is_can_average_description(desc) or is_carton_juice_average_description(desc):
            mapped_item_ids_seen.add(item_id)  # mark as seen even if cost goes to group
            continue

        mapped_item_ids_seen.add(item_id)
        measure = measure_by_id.get(item_id, '')
        invoice_unit = measure or 'unit'
        upc = units_per_case_from_desc(desc, data['case_size'])
        case_ex = invoice_price_ex_vat(data['price'], data['vat_code'])

        conv = get_conversion(item_id)
        if conv and invoice_unit_matches_conversion(desc, conv[0]):
            invoice_per_unit = (case_ex / upc) / conv[1]
            invoice_unit = conv[2]
        else:
            invoice_per_unit = case_ex / upc
            if conv and not invoice_unit_matches_conversion(desc, conv[0]):
                invoice_unit = f"case/{upc}"

        current = cost_by_id.get(item_id, 0.0)
        diff = invoice_per_unit - current
        comparison_rows.append({
            'item_id': item_id,
            'item_name': name_by_id.get(item_id, item_id),
            'invoice_desc': desc,
            'measure': measure,
            'invoice_unit': invoice_unit,
            'current_cost': current,
            'invoice_cost': invoice_per_unit,
            'diff': diff,
            'diff_pct': diff / current * 100 if current else 0.0,
        })

    # De-duplicate: keep the highest invoice_cost per item_id to match app behaviour
    df_updates = pd.DataFrame(comparison_rows)
    if not df_updates.empty:
        df_updates = df_updates.sort_values('invoice_cost').drop_duplicates('item_id', keep='last')
        df_updates = df_updates.sort_values('item_name')

    # Apply updates
    log_entries = []
    updated_item_ids = []
    # Set this to True to update prices even when the item is marked price_locked.
    OVERRIDE_PRICE_LOCKS = True

    if not df_updates.empty:
        for _, row in df_updates.iterrows():
            item_id = row['item_id']
            actual_item_id = id_lookup.get(item_id.lower(), item_id)
            new_cost = float(row['invoice_cost'])
            item_rows = inventory_df[inventory_df[COL_ITEM_ID] == actual_item_id]
            if item_rows.empty:
                print(f"Item not found in DataFrame: {item_id} (resolved: {actual_item_id})")
                continue
            item_idx = item_rows.index[0]
            is_locked = bool(inventory_df.at[item_idx, 'price_locked'])
            if is_locked and not OVERRIDE_PRICE_LOCKS:
                print(f"Skipping locked price: {actual_item_id}")
                continue
            if is_locked and OVERRIDE_PRICE_LOCKS:
                print(f"Overriding locked price: {actual_item_id}")
            old_cost = float(inventory_df.at[item_idx, COL_COST_PRICE])
            if abs(old_cost - new_cost) < 0.0001:
                print(f"No change: {actual_item_id} (£{old_cost:.4f})")
                continue
            inventory_df.at[item_idx, COL_COST_PRICE] = new_cost
            sell_price = float(inventory_df.at[item_idx, COL_SELL_PRICE])
            log_entries.append({
                COL_ITEM_ID: actual_item_id,
                COL_ACTION: 'Delivery',
                COL_QUANTITY: 0.0,
                COL_TIMESTAMP: datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                COL_COST_PRICE: new_cost,
                COL_SELL_PRICE: sell_price,
                COL_SUPPLIER: 'Booker',
                COL_DATE_RANGE: '',
                COL_REASON: 'Invoice price update',
            })
            updated_item_ids.append(actual_item_id)

    if updated_item_ids:
        if not InventoryDataManager.save_inventory(inventory_df):
            raise RuntimeError("Failed to save inventory to database")

        log_df = InventoryDataManager.load_log(inventory_df)
        if log_entries:
            new_log_df = pd.DataFrame(log_entries, columns=log_df.columns)
            log_df = pd.concat([log_df, new_log_df], ignore_index=True)
            if not InventoryDataManager.save_log(log_df):
                raise RuntimeError("Failed to save transaction log")

        for item_id in updated_item_ids:
            item_row = inventory_df[inventory_df[COL_ITEM_ID] == item_id].iloc[0]
            quantity = float(item_row[COL_QUANTITY])
            total_value = quantity * float(item_row[COL_COST_PRICE])
            update_items_csv_total_value(
                script_dir=str(SCRIPT_DIR),
                item_id=item_id,
                item_name=str(item_row[COL_ITEM_NAME]),
                quantity=quantity,
                total_value=total_value,
            )
        print(f"\nUpdated {len(updated_item_ids)} item cost prices.")
    else:
        print("\nNo price changes to apply.")

    # Build report
    lines = []
    lines.append("BOOKER INVOICE PRICE UPDATE REPORT")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Backups:   {backup_dir}")
    lines.append(f"Invoices:  {len(pdf_paths)} file(s)")
    lines.append("")

    updated_item_ids_lower = {iid.lower() for iid in updated_item_ids}

    lines.append(f"=== APPLIED UPDATES ({len(updated_item_ids)} items) ===")
    if updated_item_ids:
        for item_id in updated_item_ids:
            lookup_key = item_id.lower()
            matches = df_updates[df_updates['item_id'] == lookup_key]
            if matches.empty:
                lines.append(f"{item_id:<22} (details unavailable)")
                continue
            row = matches.iloc[0]
            lines.append(
                f"{item_id:<22} {row['item_name']:<26} "
                f"cur £{row['current_cost']:.4f} -> new £{row['invoice_cost']:.4f} "
                f"(£{row['diff']:+.4f}, {row['diff_pct']:+.1f}%)"
            )
    else:
        lines.append("No price changes applied.")
    lines.append("")

    # Booker-supplied items currently in stock that did NOT get updated
    all_mapped_item_ids = set(INVOICE_TO_ITEM.values())
    in_stock_booker_ids = {iid for iid in all_mapped_item_ids if iid in inventory_ids}
    not_updated = sorted(in_stock_booker_ids - updated_item_ids_lower)
    lines.append(f"=== BOOKER STOCK ITEMS NOT UPDATED ({len(not_updated)} items) ===")
    if not_updated:
        for item_id in not_updated:
            actual_id = id_lookup.get(item_id, item_id)
            name = name_by_id.get(item_id, item_id)
            measure = measure_by_id.get(item_id, '')
            qty = qty_by_id.get(item_id, 0)
            current = cost_by_id.get(item_id, 0.0)
            lines.append(f"{actual_id:<22} {name:<26} qty={qty:>7.2f} {measure:<10} cur_cost=£{current:.4f}")
    else:
        lines.append("All Booker-mapped stock items were updated.")
    lines.append("")

    lines.append(f"=== UNMATCHED INVOICE LINES ({len(unmatched)} lines) ===")
    if unmatched:
        for desc in sorted(set(unmatched)):
            lines.append(f"  • {desc}")
    else:
        lines.append("No unmatched invoice lines.")
    lines.append("")

    lines.append(f"=== SKIPPED / SEEN BUT NOT APPLIED ({len(mapped_item_ids_seen - updated_item_ids_lower)} items) ===")
    skipped = sorted(mapped_item_ids_seen - updated_item_ids_lower)
    if skipped:
        for item_id in skipped:
            reason = "tea - ignored" if item_id == 'tea' else "no change or not in current stock"
            lines.append(f"{item_id:<22} {reason}")
    else:
        lines.append("None.")

    report_text = "\n".join(lines)
    report_path.write_text(report_text, encoding="utf-8")
    print(f"\nReport written to: {report_path}")
    print("\n" + report_text)


if __name__ == "__main__":
    main()
