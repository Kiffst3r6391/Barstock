#!/usr/bin/env python3
"""Generate a pre-stocktake variance report from raw physical counts."""

import pandas as pd
from data_manager import InventoryDataManager
from conversions import STOCK_CONVERSIONS, convert_to_system
from reports import calculate_expected_remaining_series

# Raw physical counts as provided by the user
PHYSICAL_COUNTS_RAW = {
    'A/F KOPPARBERG': 15,
    'BIRRA MORETTI ZERO': 37,
    'BUDWIESER': 46,
    'CORONA': 66,
    'FEVERTREE SL': 44,
    'FEVERTREE': 81,
    "INCH'S": 33,
    'KOPPARBERG': 44,
    'MAGNERS': 45,
    'MORETTI BOTTLE': 60,
    'PERONI': 38,
    'OLD MOUT CIDER': 13,
    'GUINNESS 0.0': 45,
    'BELHAVEN BEST': 2.2,
    'BIRRA MORETTI': 3,
    'GUINNESS CAN': 18,
    'JOKER IPA': 3,
    'TENNENTS LAGER': 3.6,
    'THATCHERS': 2.5,
    'NUTS': 42,
    'PRINGLES': 80,
    'WALKERS': 105,
    'CAN': 496,
    'CARTON JUICE': 56,
    'COKE PM': 2.1,
    'CORDIAL': 22,
    'DIET COKE PM': 3.1,
    'J20': 72,
    'LEMONADE PM': 1.6,
    'REDBULL': 25,
    'ANGOSTURA': 1,
    'APEROL': 1.8,
    'BACARDI': 1.7,
    'BAILEYS': 1.2,
    'BOMBAY SAPPHIRE': 2.8,
    'BOWMORE': 2.8,
    'BROCKMANS GIN': 1.6,
    'DEAD MANS FINGERS': 0.3,
    'DISARONNO': 1.5,
    'DRAMBUIE': 0.6,
    'EDINBURGH R&G': 2.7,
    'GLAYVA': 1.4,
    'GLEN SCOTIA': 2.3,
    'GLENMORANGIE': 3.8,
    'GORDONS GIN': 2.5,
    'GORDONS PINK GIN': 3,
    'HAVANA CLUB 7': 1.8,
    'HIGHLAND PARK': 3.9,
    'JACK DANIELS': 0.9,
    'JAGERMIESTER': 3.5,
    'JURA ORIGIN': 4.3,
    'KAHLUA': 2,
    'KRAKEN RUM': 2.4,
    'MALIBU': 2.2,
    'MARTELL': 1.9,
    'MORGANS': 1.3,
    'OLD PULTENEY': 2.9,
    'PEACH SCHNAPPS': 2.2,
    'PIMMS': 0.2,
    'PORT': 3,
    'SAMBUCCA': 1.2,
    'SMIRNOFF': 4,
    'SOURZ': 2,
    'SOUTHERN COMFORT': 1.2,
    'TANQUARAY': 3,
    'TANQUARAY SEVILLA': 2.5,
    'TEQUILA': 1.3,
    'TEQUILA ROSE': 1.6,
    'WHITLEY NEIL': 2.9,
    'CULINAN VIEW': 10,
    'PROSECCO': 20,
    'PROSECCO SINGLE SERVE': 48,
    'SHORT MILE MERLOT': 12,
    'SINGLE SERVE WINE': 240,
    'WHISPERING HILLS ZINFANDEL': 14,
    'WICKED LADY PINOT GRIGIO': 13,
    'ZARAPITO MALBEC': 15,
}

# Map raw input names to the canonical inventory item_name
NAME_CORRECTIONS = {
    'BUDWIESER': 'Budweiser',
    'FEVERTREE SL': 'Fevertree SL Tonic',
    'FEVERTREE': 'Fevertree Tonic',
    "INCH'S": 'Inchs',
    'OLD MOUT CIDER': 'old mout cider',
    'MORETTI BOTTLE': 'Moretti Bottle',
    'COKE PM': 'Coke PM',
    'DIET COKE PM': 'Diet Coke PM',
    'LEMONADE PM': 'Lemonade PM',
    'REDBULL': 'Red Bull',
    'BAILEYS': 'Baileys 50ml',
    'BOMBAY SAPPHIRE': 'Bombay Sapphire',
    'BOWMORE': 'Bowmore',
    'BROCKMANS GIN': 'Brockmans Gin',
    'DEAD MANS FINGERS': 'Dead Mans Fingers',
    'DISARONNO': 'Disaronno',
    'DRAMBUIE': 'Drambuie',
    'EDINBURGH R&G': 'Edinburgh R&G',
    'GLAYVA': 'Glayva',
    'GLEN SCOTIA': 'Glen Scotia',
    'GLENMORANGIE': 'Glenmorangie',
    'GORDONS GIN': 'Gordons Gin',
    'GORDONS PINK GIN': 'Gordons Pink Gin',
    'HAVANA CLUB 7': 'Havana Club 7',
    'HIGHLAND PARK': 'Highland Park',
    'JACK DANIELS': 'Jack Daniels',
    'JAGERMIESTER': 'Jagermeister',
    'JURA ORIGIN': 'Jura Origin',
    'KAHLUA': 'Kahlua',
    'KRAKEN RUM': 'Kraken Rum',
    'MALIBU': 'Malibu',
    'MARTELL': 'Martell',
    'MORGANS': 'Morgans',
    'OLD PULTENEY': 'Old Pulteney',
    'PEACH SCHNAPPS': 'Peach Schnapps',
    'PIMMS': 'Pimms',
    'PORT': 'Port',
    'SAMBUCCA': 'Sambuca',
    'SMIRNOFF': 'Smirnoff',
    'SOURZ': 'Sourz',
    'SOUTHERN COMFORT': 'Southern Comfort',
    'TANQUARAY': 'Tanqueray',
    'TANQUARAY SEVILLA': 'Tanqueray Sevilla',
    'TEQUILA': 'Tequila',
    'TEQUILA ROSE': 'Tequila Rose',
    'WHITLEY NEIL': 'Whitley Neill Gin',
    'CULINAN VIEW': 'Cullinan View Sauvignon Blanc',
    'PROSECCO SINGLE SERVE': 'Prosecco Single Serve',
    'SHORT MILE MERLOT': 'Short Mile Bay Merlot',
    'SINGLE SERVE WINE': 'Single Serve Wine',
    'WHISPERING HILLS ZINFANDEL': 'Whispering Hills White Zinfandel',
    'WICKED LADY PINOT GRIGIO': 'Wicked Lady Pinot Grigio',
    'ZARAPITO MALBEC': 'Zarapito Malbec',
    'A/F KOPPARBERG': 'A/F Koppaberg',
    'BIRRA MORETTI ZERO': 'Birra Moretti Zero',
    'CORONA': 'Corona',
    'KOPPARBERG': 'Kopparberg',
    'MAGNERS': 'Magners',
    'PERONI': 'Peroni',
    'GUINNESS 0.0': 'Guinness 0.0',
    'BELHAVEN BEST': 'Belhaven Best',
    'BIRRA MORETTI': 'Birra Moretti',
    'GUINNESS CAN': 'Guinness Can',
    'JOKER IPA': 'Joker IPA',
    'TENNENTS LAGER': 'Tennents Lager',
    'THATCHERS': 'Thatchers',
    'NUTS': 'Nuts',
    'PRINGLES': 'Pringles',
    'WALKERS': 'Walkers',
    'CAN': 'Can',
    'CARTON JUICE': 'Carton Juice',
    'J20': 'J2O',
    'CORDIAL': 'Cordial',
    'APEROL': 'Aperol',
    'BACARDI': 'Bacardi',
    'ANGOSTURA': 'Angostura',
}


def normalize_name(name):
    """Normalize a raw count name to an inventory item_id and canonical name."""
    corrected = NAME_CORRECTIONS.get(name, name)
    item_id = corrected.lower()
    for char in ('&', '/', '"', '.'):
        item_id = item_id.replace(char, '')
    for char in (' ', '-'):
        item_id = item_id.replace(char, '_')
    while '__' in item_id:
        item_id = item_id.replace('__', '_')
    return item_id.strip('_'), corrected


def main():
    inventory_df = InventoryDataManager.load_inventory()
    name_to_id = {str(row['item_name']).lower(): row['item_id']
                  for _, row in inventory_df.iterrows()}
    log_df = InventoryDataManager.load_log(inventory_df)
    expected_remaining = calculate_expected_remaining_series(log_df)

    results = []
    not_matched = []
    for raw_name, raw_qty in PHYSICAL_COUNTS_RAW.items():
        item_id, corrected = normalize_name(raw_name)
        key = corrected.lower()
        if key not in name_to_id:
            not_matched.append(raw_name)
            continue
        item_id = name_to_id[key]
        system_counted = convert_to_system(item_id, raw_qty)
        inv_row = inventory_df[inventory_df['item_id'] == item_id].iloc[0]
        measure = str(inv_row['measure'])
        expected_qty = float(expected_remaining.get(item_id, 0))
        variance = system_counted - expected_qty

        if item_id in STOCK_CONVERSIONS:
            raw_unit = STOCK_CONVERSIONS[item_id][0]
            plural = {'box': 'boxes', 'carton': 'cartons', 'bottle': 'bottles',
                      'barrel': 'barrels'}.get(raw_unit, f'{raw_unit}s')
            physical_display = f'{raw_qty:.2f} {plural} = {system_counted:.1f} {measure}'
        else:
            physical_display = f'{system_counted:.1f} {measure}'

        results.append({
            'item_id': item_id,
            'name': corrected,
            'measure': measure,
            'physical_raw': raw_qty,
            'physical_system': system_counted,
            'physical_display': physical_display,
            'expected': expected_qty,
            'variance': variance,
        })

    df = pd.DataFrame(results)
    df = df.sort_values('variance')

    lines = []
    lines.append('=' * 120)
    lines.append('PRE-STOCKTAKE VARIANCE REPORT')
    lines.append('Baseline: 6 Aug 2026  |  Report date: 31 Aug 2026')
    lines.append('=' * 120)
    lines.append(f'Items counted: {len(df)}')
    if not_matched:
        lines.append(f'Unmatched names: {not_matched}')
    lines.append('')
    lines.append(f'{"Item":<35} {"Physical":<28} {"Expected":>10} {"Variance":>10} {"Status":<10}')
    lines.append('-' * 120)
    for _, row in df.iterrows():
        if row['variance'] < -0.01:
            status = 'SHORT'
        elif row['variance'] > 0.01:
            status = 'OVER'
        else:
            status = 'OK'
        lines.append(
            f'{row["name"]:<35} {row["physical_display"]:<28} '
            f'{row["expected"]:>10.1f} {row["variance"]:>10.1f} {status:<10}'
        )

    lines.append('')
    lines.append('SUMMARY BY STATUS')
    lines.append('-' * 50)
    lines.append(f'OK (variance ~0): {len(df[abs(df.variance) < 0.01])}')
    lines.append(f'SHORT: {len(df[df.variance < -0.01])}')
    lines.append(f'OVER: {len(df[df.variance > 0.01])}')
    lines.append('')
    lines.append(
        'TOP 15 SHORTAGES (physical < expected - likely missing sales or over-stated baseline/deliveries)'
    )
    lines.append('-' * 95)
    for _, row in df.head(15).iterrows():
        lines.append(
            f'{row["name"]:<35} {row["physical_display"]:<28} '
            f'expected {row["expected"]:>8.1f} {row["measure"]:<8} '
            f'variance {row["variance"]:>8.1f}'
        )
    lines.append('')
    lines.append(
        'TOP 15 OVERS (physical > expected - likely missing deliveries or under-stated sales)'
    )
    lines.append('-' * 95)
    for _, row in df.tail(15).iterrows():
        lines.append(
            f'{row["name"]:<35} {row["physical_display"]:<28} '
            f'expected {row["expected"]:>8.1f} {row["measure"]:<8} '
            f'variance {row["variance"]:>8.1f}'
        )

    report = '\n'.join(lines)
    print(report)

    with open('/Users/kiffy/PGC Barstock/pre_stocktake_variance_20260831.txt', 'w') as f:
        f.write(report)
    print('\nReport saved to: /Users/kiffy/PGC Barstock/pre_stocktake_variance_20260831.txt')


if __name__ == '__main__':
    main()
