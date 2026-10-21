"""ARCHIVED one-off script (31 Aug 2026 counts, live database).

It is kept for history only. It writes directly to the live database with
hardcoded counts and no backup, so running it accidentally would corrupt the
live baseline. To run it deliberately, set BARSTOCK_ALLOW_LIVE_SCRIPT=1.
"""

import os
import sys

if os.environ.get("BARSTOCK_ALLOW_LIVE_SCRIPT") != "1":
    raise SystemExit(
        "This archived script writes hardcoded counts to the live database. "
        "Use apply_baseline_from_count.py --counts FILE --run instead."
    )

import sqlite3, os
from conversions import STOCK_CONVERSIONS

DB = os.path.expanduser('~/Library/Application Support/BarStockManagement/barstock.db')
conn = sqlite3.connect(DB)
cur = conn.cursor()

counts_text = """A/F KOPPARBERG 20
BIRRA MORETTI ZERO 37
BUDWIESER 68
CORONA 85
FEVERTREE SL 69
FEVERTREE 99
INCH’S 10
KOPPARBERG 41
MAGNERS 45
MORETTI BOTTLE 51
PERONI 0
OLD MOUT CIDER 25
GUINNESS 0.0 88
BELHAVEN BEST 21.8
BIRRA MORETTI 2.2
CALIDONIAN BEST 1.9
GUINNESS 1.9
GUINNESS CAN 48
INNIS & GUNN 0.9
JOKER IPA 2.2
ORCHARD PIG 0.9
PORETTI 1.9
TENNENTS LAGER 3.3
THATCHERS 1.4
NUTS 29
PRINGLES 55
WALKERS 80
CAN 708
CARTON JUICE 55
COKE PM 2
CORDIAL 18
DIET COKE PM 3
J20 66
LEMONADE PM 2
REDBULL 33
ANGOSTURA 0.5
APEROL 1.7
BACARDI 2.2
BAILEYS 2.2
BOMBAY SAPPHIRE 2.2
BOWMORE 2.1
BROCKMANS GIN 2.1
COINTREAU 1
DEAD MANS FINGERS 1.1
DISARONNO 2.5
DRAMBUIE 0.7
EDINBURGH R&G 2.5
GLAYVA 1.3
GLEN SCOTIA 2.2
GLENMORANGIE 3.3
GORDONS GIN 3.9
GORDONS PINK GIN 2.9
HAVANA CLUB 7 2.8
HIGHLAND PARK 2.3
JACK DANIELS 0.4
JAGERMIESTER 3.5
JURA ORIGIN 5
KAHLUA 2.9
KRAKEN RUM 3
MALIBU 2.2
MARTELL 1.5
MORGANS 1.1
OLD PULTENEY 2.8
PEACH SCHNAPPS 2.6
PIMMS 0.2
PORT 3
SAMBUCCA 1.2
SMIRNOFF 5.8
SOURZ 2.1
SOUTHERN COMFORT 0.9
TANQUARAY 3
TANQUARAY SEVILLA 2.6
TEQUILA 1.3
TEQUILA ROSE 2
WHITLEY NEIL 2.8
CULINAN VIEW 17
PROSECCO 42
PROSECCO SINGLE SERVE 37
SHORT MILE MERLOT 24
SINGLE SERVE WINE 72
WHISPERING HILLS ZINFANDEL 23
WICKED LADY PINOT GRIGIO 19
ZARAPITO MALBEC 20"""

name_to_count = {}
for line in counts_text.strip().split('\n'):
    parts = line.rsplit(' ', 1)
    if len(parts) == 2:
        name, qty = parts
        name_to_count[name.strip().upper()] = float(qty)

name_map = {
    'A/F KOPPARBERG': 'a_f_koppaberg',
    'BIRRA MORETTI ZERO': 'birra_moretti_zero',
    'BUDWIESER': 'budweiser',
    'CORONA': 'corona',
    'FEVERTREE SL': 'fevertree_sl_tonic',
    'FEVERTREE': 'fevertree_tonic',
    'INCH’S': 'inchs',
    'KOPPARBERG': 'kopparberg',
    'MAGNERS': 'magners',
    'MORETTI BOTTLE': 'Moretti_Bottle',
    'PERONI': 'peroni',
    'OLD MOUT CIDER': 'old_mout_cider',
    'GUINNESS 0.0': 'guinness_0_0',
    'BELHAVEN BEST': 'belhaven_best',
    'BIRRA MORETTI': 'birra_moretti',
    'CALIDONIAN BEST': 'caledonian_best',
    'GUINNESS': 'guinness',
    'GUINNESS CAN': 'guinness_can',
    'INNIS & GUNN': 'innis_and_gunn',
    'JOKER IPA': 'joker_ipa',
    'ORCHARD PIG': 'orchard_pig',
    'PORETTI': 'poretti',
    'TENNENTS LAGER': 'tennents_lager',
    'THATCHERS': 'thatchers',
    'NUTS': 'nuts',
    'PRINGLES': 'pringles',
    'WALKERS': 'walkers',
    'CAN': 'can',
    'CARTON JUICE': 'carton_juice',
    'COKE PM': 'coke_pm',
    'CORDIAL': 'cordial',
    'DIET COKE PM': 'diet_coke_pm',
    'J20': 'j2o',
    'LEMONADE PM': 'lemonade',
    'REDBULL': 'red_bull',
    'ANGOSTURA': 'angostura',
    'APEROL': 'aperol',
    'BACARDI': 'bacardi',
    'BAILEYS': 'baileys_50ml',
    'BOMBAY SAPPHIRE': 'bombay_sapphire',
    'BOWMORE': 'bowmore',
    'BROCKMANS GIN': 'brockmans_gin',
    'COINTREAU': 'Cointreau',
    'DEAD MANS FINGERS': 'dead_mans_fingers',
    'DISARONNO': 'disaronno',
    'DRAMBUIE': 'drambuie',
    'EDINBURGH R&G': 'edinburgh_r&g',
    'GLAYVA': 'glayva',
    'GLEN SCOTIA': 'glen_scotia',
    'GLENMORANGIE': 'glenmorangie',
    'GORDONS GIN': 'gordons_gin',
    'GORDONS PINK GIN': 'gordons_pink_gin',
    'HAVANA CLUB 7': 'havana_club_7',
    'HIGHLAND PARK': 'highland_park',
    'JACK DANIELS': 'jack_daniels',
    'JAGERMIESTER': 'jagermeister',
    'JURA ORIGIN': 'jura_origin',
    'KAHLUA': 'kahlua',
    'KRAKEN RUM': 'kraken_rum',
    'MALIBU': 'malibu',
    'MARTELL': 'martell',
    'MORGANS': 'morgans',
    'OLD PULTENEY': 'old_pulteney',
    'PEACH SCHNAPPS': 'peach_schnapps',
    'PIMMS': 'pimms',
    'PORT': 'port',
    'SAMBUCCA': 'sambuca',
    'SMIRNOFF': 'smirnoff',
    'SOURZ': 'sours',
    'SOUTHERN COMFORT': 'southern_comfort',
    'TANQUARAY': 'tanqueray',
    'TANQUARAY SEVILLA': 'tanqueray_sevilla',
    'TEQUILA': 'tequila',
    'TEQUILA ROSE': 'tequila_rose',
    'WHITLEY NEIL': 'whitley_neill_gin',
    'CULINAN VIEW': 'cullinan_view_sauvignon_blanc',
    'PROSECCO': 'prosecco',
    'PROSECCO SINGLE SERVE': 'prosecco_single_serve',
    'SHORT MILE MERLOT': 'short_mile_bay_merlot',
    'SINGLE SERVE WINE': 'single_serve_wine',
    'WHISPERING HILLS ZINFANDEL': 'whispering_hills_white_zinfandel',
    'WICKED LADY PINOT GRIGIO': 'wicked_lady_pinot_grigio',
    'ZARAPITO MALBEC': 'zarapito_malbec',
}

def convert_to_system(item_id, input_value):
    item_id = item_id.lower()
    if item_id in STOCK_CONVERSIONS:
        return input_value * STOCK_CONVERSIONS[item_id][1]
    return input_value

def get_input_unit(item_id):
    item_id = item_id.lower()
    if item_id in STOCK_CONVERSIONS:
        return STOCK_CONVERSIONS[item_id][0]
    cur.execute('SELECT measure FROM inventory WHERE item_id=?', (item_id,))
    row = cur.fetchone()
    return row[0] if row else 'unit'

variances = []
unmatched = []
for pasted_name, count in name_to_count.items():
    item_id = name_map.get(pasted_name)
    if not item_id:
        unmatched.append(pasted_name)
        continue
    cur.execute('SELECT item_id, item_name, quantity, measure FROM inventory WHERE item_id=?', (item_id,))
    row = cur.fetchone()
    if not row:
        unmatched.append(f'{pasted_name} ({item_id})')
        continue
    db_id, db_name, system_qty, measure = row
    system_qty = float(system_qty)
    system_count = convert_to_system(item_id, count)
    variance = system_count - system_qty
    unit = get_input_unit(item_id)
    variances.append((db_id, db_name, count, unit, system_qty, system_count, variance))

print('=== TEST STOCKTAKE VARIANCES ===')
print(f'{"Item":35} {"Input":>10} {"Unit":>10} {"System":>10} {"Variance":>10}')
print('=' * 80)
for db_id, db_name, count, unit, system_qty, system_count, variance in variances:
    print(f'{db_name[:35]:35} {count:>10.2f} {unit:>10} {system_qty:>10.2f} {variance:>+10.2f}')

print('\n=== SUMMARY ===')
total_var = sum(v[6] for v in variances)
print(f'Items counted: {len(variances)}')
print(f'Total variance (sum): {total_var:+.2f}')
print(f'Items with variance > 5: {sum(1 for v in variances if abs(v[6]) > 5)}')
print(f'Items with variance > 10: {sum(1 for v in variances if abs(v[6]) > 10)}')

print('\n=== LARGEST VARIANCES ===')
variances.sort(key=lambda x: abs(x[6]), reverse=True)
for db_id, db_name, count, unit, system_qty, system_count, variance in variances[:15]:
    print(f'{db_name:35} sys={system_qty:8.2f} count={system_count:8.2f} var={variance:+8.2f}')

if unmatched:
    print('\n=== UNMATCHED ===')
    for u in unmatched:
        print(u)

conn.close()
