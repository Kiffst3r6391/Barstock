"""Custom stock order sheet layout for BarStock.

This module defines the exact supplier/category/item structure requested by
the bar team. Items are sorted alphabetically within each category by the
report builder. Items that are not currently tracked in inventory are still
shown on the sheet (with blank stock) so the order form matches the team's
working list.

To change the layout, edit ORDER_SHEET_LAYOUT below.
"""

from __future__ import annotations

# ORDER_SHEET_LAYOUT is a list of (supplier_name, [(category_name, [(display_name, item_id_or_None)])])
# item_id_or_None: inventory item_id if the product is tracked, otherwise None.
ORDER_SHEET_LAYOUT = [
    (
        "Booker",
        [
            (
                "Bottles",
                [
                    ("Budweiser", "budweiser"),
                    ("Corona", "corona"),
                    ("Inch's", "inchs"),
                    ("Kopparberg 0%", "a_f_koppaberg"),
                    ("Kopparberg MF", None),
                    ("Kopparberg S/L", "kopparberg"),
                    ("Magners", "magners"),
                    ("Moretti bottle", "birra_moretti"),
                    ("Moretti zero", "birra_moretti_zero"),
                    ("Old Mout", "old_mout_cider"),
                ],
            ),
            (
                "Soft",
                [
                    ("Coke", "coke_pm"),
                    ("Coke Zero", None),
                    ("Diet Coke", "diet_coke_pm"),
                    ("Diet irn bru", None),
                    ("Fanta lemon", None),
                    ("Ginger beer", None),
                    ("Irn bru", None),
                    ("Red bull", "red_bull"),
                    ("Sprite", None),
                    ("Tango", None),
                ],
            ),
            (
                "Minerals",
                [
                    ("Apple juice", None),
                    ("Blackcurrant cordial", "cordial"),
                    ("Cranberry juice", None),
                    ("Fever tree", "fevertree_tonic"),
                    ("Fever tree SL", "fevertree_sl_tonic"),
                    ("J20 A&M", "j2o"),
                    ("J20 O&P", None),
                    ("Lime cordial", None),
                    ("Orange juice", None),
                    ("Pineapple juice", None),
                ],
            ),
            (
                "Bag in Box",
                [
                    ("Coke", "coke_pm"),
                    ("Diet Coke", "diet_coke_pm"),
                    ("Lemonade", "lemonade"),
                ],
            ),
            (
                "Snacks",
                [
                    ("Nuts", "nuts"),
                    ("Pringles", "pringles"),
                    ("Walkers", "walkers"),
                ],
            ),
            (
                "Whisky",
                [
                    ("Bowmore", "bowmore"),
                    ("Glen Scotia", "glen_scotia"),
                    ("Glenmorangie", "glenmorangie"),
                    ("Highland park", "highland_park"),
                    ("Jura", "jura_origin"),
                    ("Old Pultney", "old_pulteney"),
                ],
            ),
            (
                "Spirits",
                [
                    ("Aperol", "aperol"),
                    ("Archers", "peach_schnapps"),
                    ("Bacardi", "bacardi"),
                    ("Baileys", "baileys_50ml"),
                    ("Bombay saphire", "bombay_sapphire"),
                    ("Brockmans", "brockmans_gin"),
                    ("Capt. Morgans", "morgans"),
                    ("Dead mans fingers", "dead_mans_fingers"),
                    ("Disaronno", "disaronno"),
                    ("Edinburgh gin", "edinburgh_r&g"),
                    ("Glayva", "glayva"),
                    ("Gordons", "gordons_gin"),
                    ("Gordons pink", "gordons_pink_gin"),
                    ("Havana 7", "havana_club_7"),
                    ("Kahlua", "kahlua"),
                    ("Kraken", "kraken_rum"),
                    ("Martial", "martell"),
                    ("malibu", "malibu"),
                    ("Port", "port"),
                    ("Sambuca", "sambuca"),
                    ("Smirnoff", "smirnoff"),
                    ("Southern comfort", "southern_comfort"),
                    ("Tanquary", "tanqueray"),
                    ("Tanquary Sevilla", "tanqueray_sevilla"),
                    ("Tequila", "tequila"),
                    ("Tequila rose", "tequila_rose"),
                ],
            ),
            (
                "Misc",
                [
                    ("Prosecco", "prosecco"),
                    ("Prosecco single serve", "prosecco_single_serve"),
                ],
            ),
        ],
    ),
    (
        "Tennent’s",
        [
            (
                "Kegs",
                [
                    ("Joker IPA", "joker_ipa"),
                    ("Tennents", "tennents_lager"),
                ],
            ),
            (
                "Cans",
                [
                    ("Guinness micro draught 0%", "guinness_0_0"),
                    ("Guinness surger", "guinness_can"),
                ],
            ),
        ],
    ),
    (
        "Wine",
        [
            (
                "",
                [
                    ("Cullinan view sauvignon blanc", "cullinan_view_sauvignon_blanc"),
                    ("Oliver & Greg Pinto grigio", None),
                    ("Oliver & Greg merlot", None),
                    ("Oliver & Greg rose", None),
                    ("Oliver & Greg sauvignon blanc", None),
                    ("Oliver & Greg shiraz", None),
                    ("Short mile bay merlot", "short_mile_bay_merlot"),
                    ("Whispering hills rose", "whispering_hills_white_zinfandel"),
                    ("Wicked lady pinto Grigio", "wicked_lady_pinot_grigio"),
                    ("Zarapito malbec", "zarapito_malbec"),
                ],
            ),
        ],
    ),
    (
        "Belhaven",
        [
            (
                "Kegs",
                [
                    ("Belhaven best", "belhaven_best"),
                    ("Birra moretti", "birra_moretti"),
                    ("Thatchers gold", "thatchers"),
                ],
            ),
        ],
    ),
]


def get_order_sheet_layout() -> list:
    """Return the full custom order sheet layout."""
    return ORDER_SHEET_LAYOUT
