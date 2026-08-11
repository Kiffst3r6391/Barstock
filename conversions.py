# Stock conversion factors for input vs display
# Format: item_id: (input_unit, conversion_factor, output_unit)
# conversion_factor = how many output_units per 1 input_unit

STOCK_CONVERSIONS = {
    # Carton Juice: 1 carton = 1.76 pints
    'carton_juice': ('carton', 1.76, 'pint'),

    # Postmix: 1 box = 74 pints (at 5:1 ratio)
    'coke_pm': ('box', 74.0, 'pint'),
    'diet_coke_pm': ('box', 74.0, 'pint'),
    'lemonade': ('box', 74.0, 'pint'),  # Lemonade PM

    # SPIRITS - 1.5L bottles (43 x 35ml measures per bottle)
    # These 7 spirits are 1.5L bottles
    'southern_comfort': ('bottle', 43.0, 'measure'),
    'bacardi': ('bottle', 43.0, 'measure'),
    'jack_daniels': ('bottle', 43.0, 'measure'),
    'morgans': ('bottle', 43.0, 'measure'),
    'gordons_gin': ('bottle', 43.0, 'measure'),
    'gordons_pink_gin': ('bottle', 43.0, 'measure'),
    'smirnoff': ('bottle', 43.0, 'measure'),

    # SPIRITS - Standard 70cl bottles (20 x 35ml measures per bottle)
    'baileys_50ml': ('bottle', 20.0, 'measure'),
    'aperol': ('bottle', 20.0, 'measure'),
    'disaronno': ('bottle', 20.0, 'measure'),
    'drambuie': ('bottle', 20.0, 'measure'),
    'glayva': ('bottle', 20.0, 'measure'),
    'kahlua': ('bottle', 20.0, 'measure'),
    'malibu': ('bottle', 20.0, 'measure'),
    'mexcal': ('bottle', 20.0, 'measure'),
    'peach_schnapps': ('bottle', 20.0, 'measure'),
    'sours': ('bottle', 20.0, 'measure'),
    'tequila_rose': ('bottle', 20.0, 'measure'),
    'bowmore': ('bottle', 20.0, 'measure'),
    'glen_scotia': ('bottle', 20.0, 'measure'),
    'glenlivet': ('bottle', 20.0, 'measure'),
    'glenmorangie': ('bottle', 20.0, 'measure'),
    'highland_park': ('bottle', 20.0, 'measure'),
    'jura_origin': ('bottle', 20.0, 'measure'),
    'loch_lomond': ('bottle', 20.0, 'measure'),
    'monkey_shoulder': ('bottle', 20.0, 'measure'),
    'old_pulteney': ('bottle', 20.0, 'measure'),
    'absolut_vodka': ('bottle', 20.0, 'measure'),
    'angostura': ('bottle', 20.0, 'measure'),
    'bombay_sapphire': ('bottle', 20.0, 'measure'),
    'brockmans_gin': ('bottle', 20.0, 'measure'),
    'dead_mans_fingers': ('bottle', 20.0, 'measure'),
    'edinburgh_r&g': ('bottle', 20.0, 'measure'),
    'gordons_lemon_gin': ('bottle', 20.0, 'measure'),
    'grey_goose': ('bottle', 20.0, 'measure'),
    'havana_club_7': ('bottle', 20.0, 'measure'),
    'jagermeister': ('bottle', 20.0, 'measure'),
    'kraken_rum': ('bottle', 20.0, 'measure'),
    'martell': ('bottle', 20.0, 'measure'),
    'sailor_jerry': ('bottle', 20.0, 'measure'),
    'sambuca': ('bottle', 20.0, 'measure'),
    'tanqueray': ('bottle', 20.0, 'measure'),
    'tanqueray_sevilla': ('bottle', 20.0, 'measure'),
    'tequila': ('bottle', 20.0, 'measure'),
    'whitley_neill_gin': ('bottle', 20.0, 'measure'),
    'zubrowka': ('bottle', 20.0, 'measure'),
    'pimms': ('bottle', 20.0, 'measure'),
    'port': ('bottle', 20.0, 'measure'),
    'cointreau': ('bottle', 20.0, 'measure'),

    # SOFT DRINKS - delivered in bottles, counted in measures
    'cordial': ('bottle', 20.0, 'measure'),

    # DRAUGHT BEERS - 1 barrel = 88 pints
    'tennents_lager': ('barrel', 88.0, 'pint'),
    'belhaven_best': ('barrel', 88.0, 'pint'),
    'birra_moretti': ('barrel', 88.0, 'pint'),
    'joker_ipa': ('barrel', 88.0, 'pint'),
    'thatchers': ('barrel', 88.0, 'pint'),
}


from datetime import datetime

# User-facing date format used throughout the UI.
DATE_FORMAT_DISPLAY = '%d-%m-%Y'
# Legacy display format kept for parsing older date_range strings.
DATE_FORMAT_DISPLAY_LEGACY = '%d/%m/%Y'


def parse_display_date(date_str):
    """Parse a user-facing date string (DD-MM-YYYY or legacy DD/MM/YYYY).

    Returns a datetime object, or raises ValueError if neither format matches.
    """
    for fmt in (DATE_FORMAT_DISPLAY, DATE_FORMAT_DISPLAY_LEGACY):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid date format: {date_str!r}")


def get_conversion(item_id):
    """Get conversion details for an item.

    Returns: (input_unit, conversion_factor, output_unit) or None if no conversion
    """
    return STOCK_CONVERSIONS.get(item_id.lower())


def convert_to_system(item_id, input_quantity):
    """Convert user input (cartons/boxes) to system quantity (pints).

    Args:
        item_id: The item ID
        input_quantity: Quantity in input units (cartons/boxes)

    Returns:
        float: Quantity in output units (pints)
    """
    conversion = get_conversion(item_id)
    if conversion:
        input_unit, factor, output_unit = conversion
        return input_quantity * factor
    return input_quantity


def convert_to_input(item_id, system_quantity):
    """Convert system quantity (pints) to input units (cartons/boxes).

    Args:
        item_id: The item ID
        system_quantity: Quantity in output units (pints)

    Returns:
        float: Quantity in input units (cartons/boxes)
    """
    conversion = get_conversion(item_id)
    if conversion:
        input_unit, factor, output_unit = conversion
        return system_quantity / factor
    return system_quantity


def get_input_label(item_id):
    """Get the label for input unit (e.g., 'cartons', 'boxes')."""
    conversion = get_conversion(item_id)
    if conversion:
        input_unit, _, _ = conversion
        return input_unit
    return None


def format_stock_display(item_id, system_quantity):
    """Format stock for display showing both input and output units.

    Returns: string like "2.5 cartons (4.4 pints)" or just "4.4 pints" if no conversion
    """
    conversion = get_conversion(item_id)
    if conversion:
        input_unit, factor, output_unit = conversion
        input_qty = system_quantity / factor
        # Handle irregular plurals
        input_plural = {'box': 'boxes', 'carton': 'cartons', 'bottle': 'bottles'}.get(input_unit, f"{input_unit}s")
        output_plural = f"{output_unit}s"
        return f"{input_qty:.1f} {input_plural} ({system_quantity:.1f} {output_plural})"
    return f"{system_quantity:.2f}"


def format_quantity_display(item_id, system_quantity):
    """Format a quantity in the most natural display unit for the item.

    For converted items this returns the input-unit equivalent (e.g. bottles).
    For non-converted items it returns the raw system quantity with measure.
    """
    conversion = get_conversion(item_id)
    if conversion:
        input_unit, factor, _output_unit = conversion
        input_qty = system_quantity / factor
        input_plural = {'box': 'boxes', 'carton': 'cartons', 'bottle': 'bottles'}.get(input_unit, f"{input_unit}s")
        return f"{input_qty:.2f} {input_plural}"
    return f"{system_quantity:.1f}"


def requires_conversion(item_id):
    """Check if an item requires input conversion."""
    return item_id.lower() in STOCK_CONVERSIONS
