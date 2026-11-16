#!/usr/bin/env python3
"""EPOS report parsing tests.

The EPOS product-transaction export carries the line total in a column named
'Sales' (some exports call it 'Totals', and split reports carry 'Member Sales'
and 'Non Member Sales'). Uploads must use that figure rather than recomputing
quantity x shelf price, otherwise member-discounted sales are overstated.
"""

import pandas as pd

from screens.uploads import UploadsMixin
from sales_mapping import is_ignored_epos_product


def row(**values):
    return pd.Series(values)


def test_sales_column_is_the_line_total():
    assert UploadsMixin._epos_line_total(
        row(Product='Tennents Lager', Qty=182, Sales=839.76)) == 839.76


def test_totals_column_is_accepted_for_older_exports():
    assert UploadsMixin._epos_line_total(
        row(Product='Tennents Lager', Qty=182, Totals=839.76)) == 839.76


def test_member_and_non_member_sales_are_summed_when_there_is_no_total():
    assert UploadsMixin._epos_line_total(
        row(Product='Tennents Lager', **{'Member Sales': 787.76,
                                         'Non Member Sales': 52.00})) == 839.76


def test_thousands_separators_are_tolerated():
    assert UploadsMixin._epos_line_total(
        row(Product='Big Week', Sales='1,234.50')) == 1234.50


def test_missing_total_returns_none():
    assert UploadsMixin._epos_line_total(row(Product='Unknown', Qty=3)) is None


def test_sales_total_is_ex_vat_when_recorded():
    # The uploader records 1/1.2 of the EPOS line total.
    total_inc = UploadsMixin._epos_line_total(
        row(Product='Tennents Lager', Sales=839.76))
    assert round(total_inc / 1.2, 2) == 699.80


def test_effective_sell_price_keeps_a_comped_zero():
    # A line the EPOS exported at 0.00 must stay at zero revenue, not fall
    # back to the shelf price.
    assert UploadsMixin._effective_sell_price(0.0, 1, 16.25) == 0.0


def test_effective_sell_price_falls_back_only_when_revenue_is_missing():
    assert UploadsMixin._effective_sell_price(None, 2, 4.0) == 4.0
    assert UploadsMixin._effective_sell_price(9.0, 2, 4.0) == 4.5


def test_delisted_item_with_no_stock_does_not_move_stock():
    # Birra Moretti is delisted with zero stock; its sales still count as
    # revenue, so the upload must not block on a negative projection.
    assert UploadsMixin._tracks_stock('birra_moretti', 0.0) is False
    # Stock left over on a delisted line is still deducted.
    assert UploadsMixin._tracks_stock('birra_moretti', 4.0) is True
    assert UploadsMixin._tracks_stock('tennents_lager', 0.0) is True


def test_untracked_post_mix_items_never_move_stock():
    # Dash and Soda Water are sold by the EPOS but the club holds no stock.
    assert UploadsMixin._tracks_stock('dash', 0.0) is False
    assert UploadsMixin._tracks_stock('soda_water', 0.0) is False


def test_blue_wkd_till_item_is_ignored():
    # Blue WKD is the staff-tip in/out button: no stock is held and the
    # charge/refund pair is not a sale, so uploads must ignore it entirely.
    assert is_ignored_epos_product('Blue WKD') is True
    assert is_ignored_epos_product('blue wkd') is True


def test_ordinary_products_are_not_ignored():
    assert is_ignored_epos_product('Tennents Lager') is False
    assert is_ignored_epos_product('Can') is False


def test_reconciliation_explains_ignored_blue_wkd():
    # The real 1-8 Nov export: every line records except the £3.47 Blue WKD
    # in/out line. The gap must be attributed to that line, not left as an
    # unexplained difference.
    preview = [{'revenue_inc': 2271.85}]
    unrecorded = [{
        'product': 'Blue WKD',
        'qty': 1,
        'revenue_inc': 3.47,
        'reason': 'Till-only staff-tip/refund in-out line.',
    }]
    rec = UploadsMixin._build_reconciliation(2275.32, preview, unrecorded)
    assert rec['reported_inc'] == 2271.85
    assert rec['unrecorded_inc'] == 3.47
    assert rec['explained_inc'] == 3.47
    assert rec['residual_inc'] == 0.0
    assert rec['lines'] == unrecorded


def test_reconciliation_keeps_unexplained_money_visible():
    rec = UploadsMixin._build_reconciliation(
        10.00, [{'revenue_inc': 9.00}], [])
    assert rec['unrecorded_inc'] == 1.00
    assert rec['explained_inc'] == 0.00
    assert rec['residual_inc'] == 1.00


def test_reconciliation_is_zero_when_every_line_records():
    rec = UploadsMixin._build_reconciliation(
        12.34, [{'revenue_inc': 12.34}], [])
    assert rec['unrecorded_inc'] == 0.0
    assert rec['residual_inc'] == 0.0
