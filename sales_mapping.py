# Sales to Parent Stock Mapping
# When these items are sold, deduct from parent stock instead/as well
# Format: child_item_id: (parent_item_id, quantity_factor, description)
# quantity_factor = how much to deduct from parent per 1 unit sold

SALES_TO_PARENT = {
    # HALF PINTS -> deduct from full pint
    'tennents_lager_half': ('tennents_lager', 0.5, 'Tennents Half Pint'),
    'belhaven_best_half_pint': ('belhaven_best', 0.5, 'Belhaven Best Half Pint'),
    'birra_moretti_half': ('birra_moretti', 0.5, 'Birra Moretti Half Pint'),
    'joker_ipa_half': ('joker_ipa', 0.5, 'Joker IPA Half Pint'),
    'thatchers_half': ('thatchers', 0.5, 'Thatchers Half Pint'),
    'carton_juice_half': ('carton_juice', 0.5, 'Carton Juice Half'),

    # DASH -> deduct from soft drinks
    'dash': ('lemonade', 0.1, 'Dash (10% of pint)'),

    # SHANDIES -> deduct from beer + lemonade
    'tennants_shandy_pint': (['tennents_lager', 'lemonade'], [0.5, 0.5], 'Tennents Shandy'),
    'tennants_shandy_half_pint': (['tennents_lager', 'lemonade'], [0.25, 0.25], 'Tennents Shandy Half'),
    'best_shandy': (['belhaven_best', 'lemonade'], [0.5, 0.5], 'Best Shandy'),
    'belhaven_best_shandy': (['belhaven_best', 'lemonade'], [0.5, 0.5], 'Belhaven Best Shandy'),
    'birra_moretti_shandy': (['birra_moretti', 'lemonade'], [0.5, 0.5], 'Birra Moretti Shandy'),
    'joker_ipa_shandy': (['joker_ipa', 'lemonade'], [0.5, 0.5], 'Joker IPA Shandy'),
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
    'cart_koppa': ('kopparberg', 1.0, 'Cart Koppa (Kopparberg)'),

    # TG (Table/Golf) ITEMS -> deduct from parent stock at 1:1 ratio
    # Premium cart sales that deduct from standard parent stock
    'tg_can': ('can', 1.0, 'TG Can'),
    'tg_tennents': ('tennents_lager', 1.0, 'TG Tennents'),
    'tb_best': ('belhaven_best', 1.0, 'TB Best'),
    'tg_single_serve_wine': ('single_serve_wine', 1.0, 'TG Single Serve Wine'),
}


# EPOS report product names -> inventory item_id overrides
# Fixes fuzzy-match issues where EPOS names don't convert cleanly to item IDs
EPOS_NAME_TO_ITEM_ID = {
    # Case fixes
    'cointreau': 'Cointreau',

    # Guinness draught in EPOS means Guinness Can (per user request)
    'guinness': 'guinness_can',

    # Thatchers PINT/HALF should match Thatchers, not generic pint
    'thatchers_pint': 'thatchers',
    'thatchers_half_pint': 'thatchers_half',

    # Birra Moretti Shandy (typo in EPOS: missing space before dash)
    'birra_moretti_shandy_pint': 'birra_moretti_shandy',

    # Tennants Shandy Half Pint (double space in EPOS name)
    'tennants_shandy_half_pint': 'tennants_shandy_half_pint',

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
}


def normalize_product_name(name):
    """Normalize a product name from a CSV report to an item_id-style string.

    Matches the conversion used in the sales/complimentary upload logic.
    """
    if not isinstance(name, str):
        name = str(name)
    name = name.replace('Morettiu', 'Moretti')
    item_id = name.lower()
    for char in ('&', '/', "'", '"', '.'):
        item_id = item_id.replace(char, '')
    for char in (' ', '-'):
        item_id = item_id.replace(char, '_')
    while '__' in item_id:
        item_id = item_id.replace('__', '_')
    return item_id.strip('_')


def resolve_epos_item_id(raw_item_id):
    """Resolve an EPOS-generated item ID to the correct inventory item ID.

    Checks explicit overrides first, then falls back to the raw ID.
    """
    return EPOS_NAME_TO_ITEM_ID.get(raw_item_id.lower(), raw_item_id)


def get_parent_for_sale(item_id):
    """Get parent item(s) that should be affected when this item is sold.

    Returns: tuple of (parent_item_id(s), quantity_factor(s), description)
             parent_item_id can be a single ID or list of IDs
             quantity_factor can be a single value or list of values
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

    parent_items, factors, _ = mapping
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

    parent_items, factors, description = mapping
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

    parent_items, factors, description = mapping
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

    parent_items, factors, description = mapping

    if isinstance(parent_items, list):
        details = [f"{factor} from {parent}" for parent, factor in zip(parent_items, factors)]
        return f"{description} affects: {', '.join(details)}"
    else:
        return f"{description} affects: {factors} from {parent_items}"


def is_hidden_from_stock_view(item_id):
    """Check if this item should be hidden from the Manage Stock view.

    These are child items (half pints, dash, shandies) that deduct from parent stock.
    They should still appear in sales transactions.
    """
    mapping = SALES_TO_PARENT.get(item_id.lower())
    return mapping is not None


def get_hidden_items():
    """Get list of all item IDs that should be hidden from stock view."""
    return [k for k, v in SALES_TO_PARENT.items() if v is not None]


def get_children_for_parent(parent_id):
    """Get all child items that deduct from a given parent stock.

    Returns: list of tuples (child_item_id, quantity_factor)
    """
    parent_id = parent_id.lower()
    children = []
    for child_id, mapping in SALES_TO_PARENT.items():
        if not mapping:
            continue
        parent_items, factors, _ = mapping
        if isinstance(parent_items, list):
            for idx, p_id in enumerate(parent_items):
                if p_id.lower() == parent_id:
                    children.append((child_id, factors[idx]))
        else:
            if parent_items.lower() == parent_id:
                children.append((child_id, factors))
    return children
