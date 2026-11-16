# Sales to Parent Stock Mapping
# When these items are sold, deduct from parent stock instead/as well
# Format: child_item_id: (parent_item_id, quantity_factor, description, visible_in_stock)
# quantity_factor = how much to deduct from parent per 1 unit sold
# visible_in_stock = optional bool; if True the item still appears in Manage Stock
#                    (defaults to False for half pints, shandies, dashes, etc.)

SALES_TO_PARENT = {
    # HALF PINTS -> deduct from full pint
    'tennents_lager_half': ('tennents_lager', 0.5, 'Tennents Half Pint'),
    'belhaven_best_half_pint': ('belhaven_best', 0.5, 'Belhaven Best Half Pint'),
    'birra_moretti_half': ('birra_moretti', 0.5, 'Birra Moretti Half Pint'),
    'joker_ipa_half': ('joker_ipa', 0.5, 'Joker IPA Half Pint'),
    'thatchers_half': ('thatchers', 0.5, 'Thatchers Half Pint'),
    'poretti_half': ('poretti', 0.5, 'Poretti Half Pint'),
    'innis_and_gunn_half': ('innis_and_gunn', 0.5, 'Innis & Gunn Half Pint'),
    'orchard_pig_half': ('orchard_pig', 0.5, 'Orchard Pig Half Pint'),
    'guinness_half': ('guinness', 0.5, 'Guinness Half Pint'),
    'caledonian_best_half': ('caledonian_best', 0.5, 'Caledonian Best Half Pint'),
    'carton_juice_half': ('carton_juice', 0.5, 'Carton Juice Half'),

    # DASH is sold without club stock (see categories.UNTRACKED_SALES_ITEMS),
    # so it has no parent stock to deduct from.

    # SHANDIES -> deduct from beer + lemonade
    'tennants_shandy_pint': (['tennents_lager', 'lemonade'], [0.5, 0.5], 'Tennents Shandy'),
    'tennants_shandy_half_pint': (['tennents_lager', 'lemonade'], [0.25, 0.25], 'Tennents Shandy Half'),
    'best_shandy': (['belhaven_best', 'lemonade'], [0.5, 0.5], 'Best Shandy'),
    'belhaven_best_shandy': (['belhaven_best', 'lemonade'], [0.5, 0.5], 'Belhaven Best Shandy'),
    'birra_moretti_shandy': (['birra_moretti', 'lemonade'], [0.5, 0.5], 'Birra Moretti Shandy'),
    'joker_ipa_shandy': (['joker_ipa', 'lemonade'], [0.5, 0.5], 'Joker IPA Shandy'),
    'poretti_shandy': (['poretti', 'lemonade'], [0.5, 0.5], 'Poretti Shandy'),
    'innis_and_gunn_shandy': (['innis_and_gunn', 'lemonade'], [0.5, 0.5], 'Innis & Gunn Shandy'),
    'orchard_pig_shandy': (['orchard_pig', 'lemonade'], [0.5, 0.5], 'Orchard Pig Shandy'),
    'guinness_shandy': (['guinness', 'lemonade'], [0.5, 0.5], 'Guinness Shandy'),
    'caledonian_best_shandy': (['caledonian_best', 'lemonade'], [0.5, 0.5], 'Caledonian Best Shandy'),
    'thatchers_shandy': (['thatchers', 'lemonade'], [0.5, 0.5], 'Thatchers Shandy'),

    # ORANGE & LEMONADE -> 50/50 from carton juice + lemonade
    'orange_lemonade': (['carton_juice', 'lemonade'], [0.5, 0.5], 'Orange & Lemonade'),
    'orange_lemonade_half': (['carton_juice', 'lemonade'], [0.25, 0.25], 'Orange & Lemonade Half'),

    # ORANGE & SODA -> half pint from carton juice
    'orange_soda': ('carton_juice', 0.5, 'Orange & Soda (half pint from carton)'),
    'orange_soda_half': ('carton_juice', 0.25, 'Orange & Soda Half'),

    # SODA CORDIAL -> deduct from cordial stock
    'soda_cordial_half_pi': ('cordial', 0.5, 'Soda Cordial Half Pint'),
    'soda_cordial_half_pint': ('cordial', 0.5, 'Soda Cordial Half Pint'),
    'soda_cordial_pint': ('cordial', 1.0, 'Soda Cordial Pint'),

    # PINT as generic draught -> no parent (user records manually)
    'pint': None,
    'half_pint': None,

    # POSTMIX FULL PINTS -> deduct 1.0 from respective postmix stock
    'coke_pint': ('coke_pm', 1.0, 'Coke Pint', True),
    'diet_coke_pint': ('diet_coke_pm', 1.0, 'Diet Coke Pint', True),
    'lemonade_pint': ('lemonade', 1.0, 'Lemonade Pint', True),

    # TG (Table/Golf) PREMIUM ITEMS -> deduct from parent stock at 1:1, visible in Manage Stock
    'tg_tennents': ('tennents_lager', 1.0, 'TG Tennents', True),
    'tg_best': ('caledonian_best', 1.0, 'TG Best', True),
    'tb_best': ('belhaven_best', 1.0, 'TB Best', True),
    'tg_can': ('can', 1.0, 'TG Can', True),
    'tg_single_serve_wine': ('single_serve_wine', 1.0, 'TG Single Serve Wine', True),

    # CART KOPPARBERG -> deduct from kopparberg stock, visible in Manage Stock
    'cart_koppa': ('kopparberg', 1.0, 'Cart Koppa (Kopparberg)', True),


    # POSTMIX HALF PINTS -> deduct 0.5 from respective postmix stock
    'coke_half': ('coke_pm', 0.5, 'Coke Half Pint'),
    'coke_half_pint': ('coke_pm', 0.5, 'Coke Half Pint'),
    'diet_coke_half': ('diet_coke_pm', 0.5, 'Diet Coke Half Pint'),
    'diet_coke_half_pint': ('diet_coke_pm', 0.5, 'Diet Coke Half Pint'),
    'lemonade_half': ('lemonade', 0.5, 'Lemonade Half Pint'),
    'lemonade_half_pint': ('lemonade', 0.5, 'Lemonade Half Pint'),

    # CARTON JUICE PINT -> deduct from carton_juice stock
    'carton_juice_pint': ('carton_juice', 1.0, 'Carton Juice Pint'),

    # CART ITEMS -> deduct from parent stock at 1:1 ratio
    # Sale price is higher (cart premium) but stock comes from the parent item
    'cart_bud': ('budweiser', 1.0, 'Cart Bud (Budweiser)'),
    'cart_corona': ('corona', 1.0, 'Cart Corona'),
    'cart_magners': ('magners', 1.0, 'Cart Magners'),
    'cart_cans': ('can', 1.0, 'Cart Cans'),
    'cart_inchs': ('inchs', 1.0, 'Cart Inch\'s'),
    'cart_peroni': ('peroni', 1.0, 'Cart Peroni'),

    # COCKTAILS / MIXED DRINKS -> deduct multiple ingredients
    # Aperol Spritz: 50ml Aperol + 1 single-serve Prosecco
    # Aperol system quantity is in 35ml measures, so 50ml = 50/35 measures.
    # Marked visible_in_stock=True so it still appears in Manage Stock.
    'aperol_spritz': (['aperol', 'prosecco_single_serve'], [50/35, 1.0], 'Aperol Spritz', True),
}


# EPOS report product names -> inventory item_id overrides
# Fixes fuzzy-match issues where EPOS names don't convert cleanly to item IDs
EPOS_NAME_TO_ITEM_ID = {
    # Case fixes: these two legacy item_ids keep their original casing.
    'cointreau': 'Cointreau',
    'moretti_bottle': 'Moretti_Bottle',

    # Draught Guinness and Guinness Can are now separate EPOS products.
    # "Guinness" goes to the draught keg; "Guinness Can" stays on cans.
    'guinness': 'guinness',
    'guinness_can': 'guinness_can',

    # New draught kegs are not auto-matched from EPOS names; use explicit item IDs
    # when adding their sales if needed.
    'poretti': 'poretti',
    'innis_and_gunn': 'innis_and_gunn',
    'innis_gunn': 'innis_and_gunn',
    'orchard_pig': 'orchard_pig',
    'caledonian_best': 'caledonian_best',
    # EPOS typo: Calidonian -> Caledonian (missing 'e' before 'd')
    'calidonian_best': 'caledonian_best',
    'calidonian_best_half_pint': 'caledonian_best_half',
    'calidonian_best_shandy': 'caledonian_best_shandy',

    # Thatchers PINT/HALF should match Thatchers, not generic pint
    'thatchers_pint': 'thatchers',
    'thatchers_half_pint': 'thatchers_half',

    # Birra Moretti Shandy (typo in EPOS: missing space before dash)
    'birra_moretti_shandy_pint': 'birra_moretti_shandy',

    # Tennants Shandy Half Pint (double space in EPOS name)
    'tennants_shandy_half_pint': 'tennants_shandy_half_pint',

    # TG and cart item name normalisation helpers
    'tg_tennents': 'tg_tennents',
    'tg_best': 'tg_best',
    'tb_best': 'tb_best',
    'cart_koppa': 'cart_koppa',

    # Postmix half pints (EPOS name variations)
    'coke': 'coke_pm',
    'diet_coke': 'diet_coke_pm',
    'lemonade': 'lemonade',
    'coke_half_pint': 'coke_half',
    'diet_coke_half_pint': 'diet_coke_half',
    'lemonade_half_pint': 'lemonade_half',

    # Port 50ml in EPOS maps to plain Port in inventory
    'port_50ml': 'port',

    # Tea/Coffee Urn maps to Tea
    'teacoffee_urn': 'tea',
    # EPOS "Nuts small pack" is the tracked Nuts item
    'nuts_small_pack': 'nuts',
    # EPOS "Archers" is Peach Schnapps
    'archers': 'peach_schnapps',

    # Ampersand normalisation fallbacks. The canonical normaliser converts
    # "X & Y" to "X_and_Y", but several stock item_ids omit the _and_.
    'orange_and_lemonade': 'orange_lemonade',
    'orange_and_lemonade_half': 'orange_lemonade_half',
    'orange_and_soda': 'orange_soda',
    'orange_and_soda_half': 'orange_soda_half',
    'cart_roll_and_tea_coffee': 'cart_roll_tea_coffee',

    # Slash/ampersand edge cases where the old normaliser stripped characters.
    # These aliases protect legacy CSV uploads and third-party EPOS reports.
    'edinburgh_rg': 'edinburgh_r&g',
    'af_koppaberg': 'a_f_koppaberg',

    # Short/common EPOS names that don't normalise to the stock item_id.
    'baileys': 'baileys_50ml',
    'gordons': 'gordons_gin',
    'bombay': 'bombay_sapphire',
    'kraken': 'kraken_rum',
    'old_mout': 'old_mout_cider',
    'j2o_apple_mango': 'j2o',
    'j2o_orange_passion': 'j2o',
    'prosecco_doc': 'prosecco',
    'single_serve_red': 'single_serve_wine',
    'single_serve_white': 'single_serve_wine',
    'single_serve_rose': 'single_serve_wine',

    # Item_name normalisation fallbacks where the display name diverges from item_id.
    'belhaven_best_half': 'belhaven_best_half_pint',
    'guinness_00': 'guinness_0_0',
    'sourz': 'sours',
}


def normalize_product_name(name):
    """Normalize a product name from a CSV report to an item_id-style string.

    Matches the convention used for item_ids in stock.csv and Items.csv:
      - "Innis & Gunn"        -> "innis_and_gunn"
      - "Edinburgh R&G"        -> "edinburgh_r&g"
      - "A/F Koppaberg"       -> "a_f_koppaberg"
      - "Orange & Lemonade"    -> "orange_and_lemonade"
      - "Cart Roll & Tea/Coffee" -> "cart_roll_and_tea_coffee"
    """
    if not isinstance(name, str):
        name = str(name)
    # Common Booker/EPOS typo
    name = name.replace('Morettiu', 'Moretti')
    item_id = name.lower()
    # Convert spaced ampersands to _and_ so "Innis & Gunn" becomes innis_and_gunn.
    # Standalone ampersands (e.g. "R&G") are preserved.
    item_id = item_id.replace(' & ', '_and_')
    for char in ("'", '"', '.'):
        item_id = item_id.replace(char, '')
    for char in ('/', ' ', '-'):
        item_id = item_id.replace(char, '_')
    while '__' in item_id:
        item_id = item_id.replace('__', '_')
    return item_id.strip('_')


def resolve_epos_item_id(raw_item_id):
    """Resolve an EPOS-generated item ID to the correct inventory item ID.

    Checks explicit overrides first, then falls back to the raw ID.
    """
    return EPOS_NAME_TO_ITEM_ID.get(raw_item_id.lower(), raw_item_id)


# Till-only products that must never be recorded by an upload. They are used as
# in/out mechanisms (for example the Blue WKD staff-drink button: charged on
# the till then refunded back to staff) and hold no stock, so any revenue they
# show is a pass-through rather than a sale.
IGNORED_EPOS_ITEMS = {
    'blue_wkd',
}


def is_ignored_epos_product(product_name):
    """True when an EPOS product line should be ignored entirely."""
    return resolve_epos_item_id(
        normalize_product_name(product_name)) in IGNORED_EPOS_ITEMS


def get_parent_for_sale(item_id):
    """Get parent item(s) that should be affected when this item is sold.

    Returns: tuple of (parent_item_id(s), quantity_factor(s), description[, visible_in_stock])
             parent_item_id can be a single ID or list of IDs
             quantity_factor can be a single value or list of values
             An optional fourth element controls stock-view visibility (True = visible)
             Returns None if no parent mapping exists
    """
    return SALES_TO_PARENT.get(item_id.lower())


def get_effective_cost_price(item_id, inventory_df, col_item_id='item_id', col_cost_price='cost_price'):
    """Get the effective cost price for an item.

    For items with a single parent mapping, returns the parent's cost price
    multiplied by the quantity factor. For items with multiple parents or
    no parent mapping, returns the item's own cost price.
    """
    mapping = get_parent_for_sale(item_id)
    if not mapping:
        return inventory_df.loc[inventory_df[col_item_id] == item_id, col_cost_price].values[0]

    parent_items, factors, _ = mapping[:3]
    if isinstance(parent_items, list):
        # Multiple parents - return own cost (blending would be complex)
        return inventory_df.loc[inventory_df[col_item_id] == item_id, col_cost_price].values[0]

    # Single parent
    if parent_items in inventory_df[col_item_id].values:
        parent_cost = inventory_df.loc[inventory_df[col_item_id] == parent_items, col_cost_price].values[0]
        return parent_cost * factors

    return inventory_df.loc[inventory_df[col_item_id] == item_id, col_cost_price].values[0]


def has_parent_stock(item_id):
    """Check if this item affects parent stock when sold."""
    mapping = SALES_TO_PARENT.get(item_id.lower())
    return mapping is not None


def check_apply_sale_to_parent(item_id, quantity_sold, inventory_df, col_item_id, col_quantity, col_allow_negative=None):
    """Check whether applying a child sale would drive any parent stock negative.

    Returns:
        (ok, messages): ok is True if no parent would go negative (or all parents
        allow negative stock). messages is a list of human-readable issue strings.
    """
    mapping = get_parent_for_sale(item_id)
    if not mapping:
        return True, []

    parent_items, factors, description = mapping[:3]
    messages = []

    def _check_parent(parent_id, factor):
        if parent_id in inventory_df[col_item_id].values:
            current_qty = inventory_df.loc[inventory_df[col_item_id] == parent_id, col_quantity].values[0]
            deduction = quantity_sold * factor
            allow_negative = False
            if col_allow_negative and col_allow_negative in inventory_df.columns:
                allow_negative = bool(
                    inventory_df.loc[inventory_df[col_item_id] == parent_id, col_allow_negative].values[0]
                )
            if not allow_negative and current_qty < deduction:
                messages.append(
                    f"{description}: needs {deduction:.2f} from '{parent_id}' but only {current_qty:.2f} available"
                )

    if isinstance(parent_items, list):
        for parent_id, factor in zip(parent_items, factors):
            _check_parent(parent_id, factor)
    else:
        _check_parent(parent_items, factors)

    return len(messages) == 0, messages


def apply_sale_to_parent(item_id, quantity_sold, inventory_df, col_item_id, col_quantity):
    """Apply a sale of a child item to parent stock.

    Args:
        item_id: The child item being sold
        quantity_sold: Quantity being sold
        inventory_df: DataFrame containing inventory
        col_item_id: Column name for item ID
        col_quantity: Column name for quantity

    Returns:
        list of tuples: [(parent_id, amount_deducted, description), ...]
    """
    mapping = get_parent_for_sale(item_id)
    if not mapping:
        return []

    parent_items, factors, description = mapping[:3]
    adjustments = []

    # Handle single or multiple parents
    if isinstance(parent_items, list):
        # Multiple parents (e.g., shandy affects beer AND lemonade)
        for parent_id, factor in zip(parent_items, factors):
            deduction = quantity_sold * factor
            if parent_id in inventory_df[col_item_id].values:
                current_qty = inventory_df.loc[inventory_df[col_item_id] == parent_id, col_quantity].values[0]
                new_qty = current_qty - deduction
                inventory_df.loc[inventory_df[col_item_id] == parent_id, col_quantity] = new_qty
                adjustments.append((parent_id, deduction, f"{description}: -{deduction:.2f} from {parent_id}"))
    else:
        # Single parent
        deduction = quantity_sold * factors
        if parent_items in inventory_df[col_item_id].values:
            current_qty = inventory_df.loc[inventory_df[col_item_id] == parent_items, col_quantity].values[0]
            new_qty = current_qty - deduction
            inventory_df.loc[inventory_df[col_item_id] == parent_items, col_quantity] = new_qty
            adjustments.append((parent_items, deduction, f"{description}: -{deduction:.2f} from {parent_items}"))

    return adjustments


def get_affected_parents_description(item_id):
    """Get a human-readable description of what stock is affected by this sale."""
    mapping = get_parent_for_sale(item_id)
    if not mapping:
        return None

    parent_items, factors, description = mapping[:3]

    if isinstance(parent_items, list):
        details = [f"{factor} from {parent}" for parent, factor in zip(parent_items, factors)]
        return f"{description} affects: {', '.join(details)}"
    else:
        return f"{description} affects: {factors} from {parent_items}"


def is_hidden_from_stock_view(item_id):
    """Check if this item should be hidden from the Manage Stock view.

    These are child items (half pints, dash, shandies) that deduct from parent stock.
    They should still appear in sales transactions.

    Items with a SALES_TO_PARENT mapping can opt out of hiding by setting the
    optional fourth tuple element to True.
    """
    mapping = SALES_TO_PARENT.get(item_id.lower())
    if not mapping:
        return False
    # Optional fourth element controls visibility (default hidden)
    return not (len(mapping) > 3 and mapping[3])


def get_hidden_items():
    """Get list of all item IDs that should be hidden from stock view."""
    return [k for k, v in SALES_TO_PARENT.items() if v is not None and not (len(v) > 3 and v[3])]


def get_children_for_parent(parent_id):
    """Get all child items that deduct from a given parent stock.

    Returns: list of tuples (child_item_id, quantity_factor)
    """
    parent_id = parent_id.lower()
    children = []
    for child_id, mapping in SALES_TO_PARENT.items():
        if not mapping:
            continue
        parent_items, factors, _ = mapping[:3]
        if isinstance(parent_items, list):
            for idx, p_id in enumerate(parent_items):
                if p_id.lower() == parent_id:
                    children.append((child_id, factors[idx]))
        else:
            if parent_items.lower() == parent_id:
                children.append((child_id, factors))
    return children
