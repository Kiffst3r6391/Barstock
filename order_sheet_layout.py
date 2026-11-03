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
                    ("Estrella Damm", "estrella_damm"),
                    ("Inch's", "inchs"),
                    ("Kopparberg 0%", "a_f_koppaberg"),
                    ("Kopparberg MF", None),
                    ("Kopparberg S/L", "kopparberg"),
                    ("Magners", "magners"),
                    ("Moretti bottle", "birra_moretti"),
                    ("Moretti Bottle", "Moretti_Bottle"),
                    ("Moretti zero", "birra_moretti_zero"),
                    ("Old Mout", "old_mout_cider"),
                    ("Peroni", "peroni"),
                ],
            ),
            (
                "Soft",
                [
                    ("Can", "can"),
                    ("Coke", "coke_pm"),
                    ("Coke - Half", "coke_half"),
                    ("Coke Half Pint", "coke_half_pint"),
                    ("Coke Pint", "coke_pint"),
                    ("Coke Zero", None),
                    ("Diet Coke", "diet_coke_pm"),
                    ("Diet Coke - Half", "diet_coke_half"),
                    ("Diet Coke Half Pint", "diet_coke_half_pint"),
                    ("Diet Coke Pint", "diet_coke_pint"),
                    ("Diet irn bru", None),
                    ("Fanta lemon", None),
                    ("Ginger beer", None),
                    ("Irn bru", None),
                    ("Lemonade", "lemonade"),
                    ("Lemonade - Half", "lemonade_half"),
                    ("Lemonade Half Pint", "lemonade_half_pint"),
                    ("Lemonade Pint", "lemonade_pint"),
                    ("Orange & Lemonade", "orange_lemonade"),
                    ("Orange & Lemonade - Half", "orange_lemonade_half"),
                    ("Orange & Soda", "orange_soda"),
                    ("Orange & Soda - Half", "orange_soda_half"),
                    ("Red bull", "red_bull"),
                    ("Simply Fruity", "simply_fruity"),
                    ("Soda Cordial Half", "soda_cordial_half_pi"),
                    ("Soda Cordial Half Pint", "soda_cordial_half_pint"),
                    ("Soda Cordial Pint", "soda_cordial_pint"),
                    ("Soda Water", "soda_water"),
                    ("Sprite", None),
                    ("Tango", None),
                    ("Tonic", "tonic"),
                ],
            ),
            (
                "Minerals",
                [
                    ("Apple juice", None),
                    ("Blackcurrant cordial", "cordial"),
                    ("Carton Juice", "carton_juice"),
                    ("Carton Juice - Half", "carton_juice_half"),
                    ("Carton Juice Pint", "carton_juice_pint"),
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
                    ("Coke Half Pint", "coke_half_pint"),
                    ("Diet Coke", "diet_coke_pm"),
                    ("Diet Coke Half Pint", "diet_coke_half_pint"),
                    ("Lemonade", "lemonade"),
                    ("Lemonade Half Pint", "lemonade_half_pint"),
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
                    ("Angostura", "angostura"),
                    ("Aperol", "aperol"),
                    ("Archers", "peach_schnapps"),
                    ("Bacardi", "bacardi"),
                    ("Baileys", "baileys_50ml"),
                    ("Bombay saphire", "bombay_sapphire"),
                    ("Brockmans", "brockmans_gin"),
                    ("Capt. Morgans", "morgans"),
                    ("Cointreau", "Cointreau"),
                    ("Dead mans fingers", "dead_mans_fingers"),
                    ("Disaronno", "disaronno"),
                    ("Drambuie", "drambuie"),
                    ("Edinburgh gin", "edinburgh_r&g"),
                    ("Glayva", "glayva"),
                    ("Gordons", "gordons_gin"),
                    ("Gordons pink", "gordons_pink_gin"),
                    ("Havana 7", "havana_club_7"),
                    ("Jack Daniels", "jack_daniels"),
                    ("Jagermeister", "jagermeister"),
                    ("Kahlua", "kahlua"),
                    ("Kraken", "kraken_rum"),
                    ("Martial", "martell"),
                    ("malibu", "malibu"),
                    ("Pimms", "pimms"),
                    ("Port", "port"),
                    ("Sambuca", "sambuca"),
                    ("Sourz", "sours"),
                    ("Smirnoff", "smirnoff"),
                    ("Southern comfort", "southern_comfort"),
                    ("Tanquary", "tanqueray"),
                    ("Tanquary Sevilla", "tanqueray_sevilla"),
                    ("Tequila", "tequila"),
                    ("Tequila rose", "tequila_rose"),
                    ("Whitley Neill", "whitley_neill_gin"),
                ],
            ),
            (
                "Misc",
                [
                    ("Aperol Spritz", "aperol_spritz"),
                    ("Barista Coffee", "barista_coffee"),
                    ("Coffee Machine", "coffee_machine"),
                    ("Prosecco", "prosecco"),
                    ("Prosecco single serve", "prosecco_single_serve"),
                    ("Specialist Tea", "specialist_tea"),
                    ("Tea", "tea"),
                ],
            ),
            (
                "Cart Sales",
                [
                    ("CART BUD", "cart_bud"),
                    ("CART CANS", "cart_cans"),
                    ("CART CORONA", "cart_corona"),
                    ("CART INCH'S", "cart_inchs"),
                    ("CART KOPPA", "cart_koppa"),
                    ("CART MAGNERS", "cart_magners"),
                    ("CART PERONI", "cart_peroni"),
                    ("Cart Roll & Tea/Coffee", "cart_roll_tea_coffee"),
                ],
            ),
        ],
    ),
    (
        "Tennents",
        [
            (
                "Kegs",
                [
                    ("Caledonian Best", "caledonian_best"),
                    ("Caledonian Best Half", "caledonian_best_half"),
                    ("Caledonian Best Shandy", "caledonian_best_shandy"),
                    ("Guinness", "guinness"),
                    ("Guinness Half", "guinness_half"),
                    ("Guinness Shandy", "guinness_shandy"),
                    ("Innis & Gunn", "innis_and_gunn"),
                    ("Innis & Gunn Half", "innis_and_gunn_half"),
                    ("Innis & Gunn Shandy", "innis_and_gunn_shandy"),
                    ("Joker IPA", "joker_ipa"),
                    ("Joker IPA Half", "joker_ipa_half"),
                    ("Joker IPA Shandy", "joker_ipa_shandy"),
                    ("Orchard Pig", "orchard_pig"),
                    ("Orchard Pig Half", "orchard_pig_half"),
                    ("Orchard Pig Shandy", "orchard_pig_shandy"),
                    ("Poretti", "poretti"),
                    ("Poretti Half", "poretti_half"),
                    ("Poretti Shandy", "poretti_shandy"),
                    ("Tennents", "tennents_lager"),
                    ("Tennents Half", "tennents_lager_half"),
                    ("Tennents Shandy", "tennants_shandy_pint"),
                    ("Tennents Shandy Half", "tennants_shandy_half_pint"),
                    ("TG Tennents", "tg_tennents"),
                ],
            ),
            (
                "Cans",
                [
                    ("Guinness micro draught 0%", "guinness_0_0"),
                    ("Guinness surger", "guinness_can"),
                    ("TG Can", "tg_can"),
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
                    ("Merlot", "merlot"),
                    ("Oliver & Greg Pinto grigio", None),
                    ("Oliver & Greg merlot", None),
                    ("Oliver & Greg rose", None),
                    ("Oliver & Greg sauvignon blanc", None),
                    ("Oliver & Greg shiraz", None),
                    ("Short mile bay merlot", "short_mile_bay_merlot"),
                    ("Single Serve Wine", "single_serve_wine"),
                    ("TG Single Serve Wine", "tg_single_serve_wine"),
                    ("Whispering hills rose", "whispering_hills_white_zinfandel"),
                    ("Wicked lady pinto Grigio", "wicked_lady_pinot_grigio"),
                    ("Zarapito malbec", "zarapito_malbec"),
                ],
            ),
        ],
    ),
]


def get_order_sheet_layout() -> list:
    """Return the full custom order sheet layout."""
    return ORDER_SHEET_LAYOUT
