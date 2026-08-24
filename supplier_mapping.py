"""Supplier mapping for BarStock order sheets and reports.

Provides a simple, editable lookup from item_id (or product type) to the
supplier that normally delivers it. The default mapping reflects the three
suppliers already used in the delivery dialog: Booker, Tennents, Belhaven.

To change a supplier assignment, edit ITEM_SUPPLIER_MAP or
CATEGORY_SUPPLIER_OVERRIDES below.
"""

from __future__ import annotations

# Suppliers are displayed in this order on the order sheet.
SUPPLIER_ORDER = [
    'Booker',
    'Tennents',
    'Belhaven',
    'Unknown',
]

# Per-item supplier overrides. Use this for items whose supplier is not the
# same as the default for their product type.
ITEM_SUPPLIER_MAP = {
    # Tennents products
    'tennents_lager': 'Tennents',
    'tennents_lager_half': 'Tennents',
    'tennants_shandy_pint': 'Tennents',
    'tennants_shandy_half_pint': 'Tennents',
    'tg_tennents': 'Tennents',

    # Belhaven products
    'belhaven_best': 'Belhaven',
    'belhaven_best_half_pint': 'Belhaven',
    'belhaven_best_shandy': 'Belhaven',
    'best_shandy': 'Belhaven',
    'tb_best': 'Belhaven',
}

# Default supplier for whole product types. Anything not listed here and not
# in ITEM_SUPPLIER_MAP falls back to 'Booker'.
CATEGORY_SUPPLIER_OVERRIDES = {
    # Currently all non-Tennents/Belhaven types come from Booker.
    # Add entries here if a whole category changes supplier in the future.
}


def get_supplier(item_id: str, category: str | None = None) -> str:
    """Return the supplier for the given item.

    Resolution order:
      1. Explicit per-item mapping in ITEM_SUPPLIER_MAP.
      2. Category-level override in CATEGORY_SUPPLIER_OVERRIDES.
      3. Default to 'Booker'.

    Args:
        item_id: The inventory item_id.
        category: Optional product type/category from categories.py.

    Returns:
        One of the supplier names in SUPPLIER_ORDER (usually 'Booker',
        'Tennents', or 'Belhaven').
    """
    if not isinstance(item_id, str):
        item_id = str(item_id)
    item_id_lower = item_id.lower()

    if item_id_lower in ITEM_SUPPLIER_MAP:
        return ITEM_SUPPLIER_MAP[item_id_lower]

    if category is not None:
        category_supplier = CATEGORY_SUPPLIER_OVERRIDES.get(str(category))
        if category_supplier:
            return category_supplier

    return 'Booker'


def get_supplier_order() -> list[str]:
    """Return the display order for suppliers."""
    return list(SUPPLIER_ORDER)
