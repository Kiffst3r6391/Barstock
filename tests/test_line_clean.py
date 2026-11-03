#!/usr/bin/env python3
"""Line clean selection tests.

Line clean used to read Items.csv from the script directory, which is empty in
the packaged app. It now works from the live inventory.
"""

import pandas as pd

from data_manager import INVENTORY_COLUMNS
from screens.transactions import draught_lines_to_clean


def inventory_frame(rows):
    return pd.DataFrame(rows, columns=INVENTORY_COLUMNS)


def ids(lines):
    return {str(row['item_id']) for row in lines}


def test_finds_a_keg_line_from_a_blank_division():
    # Tennents Lager has no division set, so it is only known as draught by
    # its barrel conversion.
    inventory = inventory_frame([
        ["tennents_lager", "Tennents Lager", 432.4, 1.0, 2.0, "Pint", "Draught", 0, 0, 0, ""],
    ])

    assert ids(draught_lines_to_clean(inventory)) == {"tennents_lager"}


def test_finds_a_keg_line_from_its_division():
    inventory = inventory_frame([
        ["tb_best", "TB Best", 40.0, 1.0, 2.0, "Pint", "Draught", 0, 0, 0, "Beers- Draught"],
    ])

    assert ids(draught_lines_to_clean(inventory)) == {"tb_best"}


def test_skips_half_pint_variants_of_a_keg_line():
    # Halves share the parent keg; cleaning the keg covers them.
    inventory = inventory_frame([
        ["guinness", "Guinness", 218.2, 1.0, 2.0, "Pint", "Draught", 0, 0, 0, "Beers- Draught"],
        ["guinness_half", "Guinness - Half", 12.0, 1.0, 2.0, "Half Pint", "Draught", 0, 0, 0, "Draught"],
    ])

    assert ids(draught_lines_to_clean(inventory)) == {"guinness"}


def test_skips_packaged_and_non_draught_lines():
    # Guinness Can is miscategorised as Draught but has no draught division
    # and no barrel conversion, so a line clean must leave it alone.
    inventory = inventory_frame([
        ["guinness", "Guinness", 218.2, 1.0, 2.0, "Pint", "Draught", 0, 0, 0, "Beers- Draught"],
        ["guinness_can", "Guinness Can", 48.0, 1.0, 2.0, "Pint", "Draught", 0, 0, 0, ""],
        ["coke_pm", "Coke Post Mix", 74.0, 1.0, 2.0, "Pint", "Soft", 0, 0, 0, "Post Mix"],
    ])

    assert ids(draught_lines_to_clean(inventory)) == {"guinness"}


def test_skips_a_delisted_keg_even_with_stock():
    inventory = inventory_frame([
        ["belhaven_best", "Belhaven Best", 2.5, 1.0, 2.0, "Pint", "Draught", 0, 0, 0, "Beers- Draught"],
        ["poretti", "Poretti", 235.2, 1.0, 2.0, "Pint", "Draught", 0, 0, 0, "Beers- Draught"],
    ])

    assert ids(draught_lines_to_clean(inventory)) == {"poretti"}


def test_skips_keg_lines_with_no_stock():
    inventory = inventory_frame([
        ["joker_ipa", "Joker IPA", 0.0, 1.0, 2.0, "Pint", "Draught", 0, 0, 0, ""],
        ["poretti", "Poretti", 235.2, 1.0, 2.0, "Pint", "Draught", 0, 0, 0, "Beers- Draught"],
    ])

    assert ids(draught_lines_to_clean(inventory)) == {"poretti"}
