"""Tests for the Booker invoice price-check parser helpers."""

import sqlite3

import pytest

from BarStockApp import BarStockManagementSystem


@pytest.fixture
def app(tmp_path, monkeypatch):
    import tkinter as tk

    import data_manager as dm
    import BarStockApp as ui

    # Never let a test window load or mirror the live data: constructing the
    # app exports the CSV mirrors at start-up.
    monkeypatch.setattr(dm, "DB_PATH", str(tmp_path / "barstock.db"))
    monkeypatch.setattr(dm, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(dm, "INVENTORY_FILE", str(tmp_path / "stock.csv"))
    monkeypatch.setattr(dm, "LOG_FILE", str(tmp_path / "transaction_log.csv"))
    monkeypatch.setattr(dm, "_sync_csv_quietly", lambda df: None)
    monkeypatch.setattr(dm.InventoryDataManager, "export_csv_mirrors",
                        staticmethod(lambda df=None: True))
    monkeypatch.setattr(dm, "create_auto_backup", lambda *a, **k: None)
    for name in ("showerror", "showwarning", "showinfo", "askyesno"):
        monkeypatch.setattr(dm.messagebox, name, lambda *a, **k: True)
        monkeypatch.setattr(ui.messagebox, name, lambda *a, **k: None)

    conn = sqlite3.connect(tmp_path / "barstock.db")
    dm._init_db_schema(conn)
    conn.commit()
    conn.close()

    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk is not available in this environment")
    root.withdraw()
    app = BarStockManagementSystem(root)
    root.destroy()
    return app


class TestParseBookerInvoiceLine:
    def test_parses_simple_product_line(self, app):
        line = "282574 Coca Cola Can 24 330ml 1 10.50 TC 21.00 B 1.49 64.8%"
        desc, qty, case_size, price, vat_code = app._parse_booker_invoice_line(line)
        assert desc == "Coca Cola Can 24 330ml"
        assert qty == 1
        assert case_size == 24
        assert price == 10.50
        assert vat_code == "B"

    def test_parses_vat_exempt_line(self, app):
        line = "123456 Test Water 24 500ml 1 5.00 TC 5.00 A 0.99 50.0%"
        *_, vat_code = app._parse_booker_invoice_line(line)
        assert vat_code == "A"

    def test_parses_spirit_line(self, app):
        line = "473959 Gordons Gin 1 1.5ltr 2 30.48 MUP 60.96 B"
        desc, qty, case_size, price, vat_code = app._parse_booker_invoice_line(line)
        assert desc == "Gordons Gin 1 1.5ltr"
        assert qty == 2
        assert case_size == 1
        assert price == 30.48
        assert vat_code == "B"

    def test_parses_multipack_line(self, app):
        line = "294482 Birra Moretti 0% 6 4x330ml 1 18.49 TC 18.49 B 6.39 42.2%"
        desc, qty, case_size, price, vat_code = app._parse_booker_invoice_line(line)
        assert desc == "Birra Moretti 0% 6 4x330ml"
        assert qty == 1
        assert case_size == 6
        assert price == 18.49
        assert vat_code == "B"

    def test_ignores_header_and_total_lines(self, app):
        assert app._parse_booker_invoice_line("CODE DESCRIPTION PACK SIZE QTY PRICE VALUE VAT RRP POR") is None
        assert app._parse_booker_invoice_line("TOTAL ITEMS: 3") is None
        assert app._parse_booker_invoice_line("INVOICE NUMBER 3533591 PAGE 01") is None

    def test_ignores_out_of_stock_lines(self, app):
        line = "123456 Substitute Out of Stock 12 40g 1 5.00 5.00 B"
        assert app._parse_booker_invoice_line(line) is None


class TestInvoicePriceExVat:
    def test_vat_code_b_returns_ex_vat_price(self, app):
        assert app._invoice_price_ex_vat(10.00, "B") == 10.00

    def test_vat_code_a_returns_ex_vat_price(self, app):
        assert app._invoice_price_ex_vat(10.00, "A") == 10.00

    def test_missing_vat_code_returns_ex_vat_price(self, app):
        assert app._invoice_price_ex_vat(10.00, "") == 10.00


class TestUnitsPerCaseFromDesc:
    def test_simple_case_size(self, app):
        assert app._units_per_case_from_desc("Coca Cola Can 24 330ml", 24) == 24

    def test_multipack(self, app):
        assert app._units_per_case_from_desc("Birra Moretti 0% 6 4x330ml", 6) == 24

    def test_single_bottle(self, app):
        assert app._units_per_case_from_desc("Gordons Gin 1 1.5ltr", 1) == 1


class TestInvoiceUnitMatchesConversion:
    def test_bottle_conversion_matches_volume(self, app):
        assert app._invoice_unit_matches_conversion("Gordons Gin 1 1.5ltr", "bottle")
        assert app._invoice_unit_matches_conversion("Antica Sambuca Classic 1 70cl", "bottle")

    def test_box_conversion_matches_bib(self, app):
        assert app._invoice_unit_matches_conversion("Coca Cola Original BIB 1 7Ltr", "box")
        assert app._invoice_unit_matches_conversion("Schweppes Lemonade Bag inBox 1 7ltr", "box")

    def test_barrel_conversion_does_not_match_bottle_invoice(self, app):
        assert not app._invoice_unit_matches_conversion("Birra Moretti NRB UK 24 330ml", "barrel")


class TestMapInvoiceDescription:
    def test_maps_known_descriptions(self, app):
        inventory_ids = {"gordons_gin", "smirnoff", "coke_pm"}
        assert app._map_invoice_description_to_item_id("Gordons Gin 1 1.5ltr", inventory_ids) == "gordons_gin"
        assert app._map_invoice_description_to_item_id("Smirnoff Red 1 1.5ltr", inventory_ids) == "smirnoff"
        assert app._map_invoice_description_to_item_id("Coca Cola Original BIB 1 7Ltr", inventory_ids) == "coke_pm"

    def test_returns_none_for_unmapped(self, app):
        assert app._map_invoice_description_to_item_id("Unknown Widget 12 1ltr", {"gordons_gin"}) is None


class TestCanAveragePricing:
    def test_detects_can_group_descriptions(self, app):
        assert app._is_can_average_description("Coca Cola Can 24 330ml")
        assert app._is_can_average_description("Diet Coke Can 24 330ml")
        assert app._is_can_average_description("Irn Bru 24 330ml")
        assert app._is_can_average_description("Irn Bru Sugar Free 24 330ml")
        assert app._is_can_average_description("Coke Zero 24 330ml")
        assert app._is_can_average_description("Fanta Lemon 24 330ml")
        assert app._is_can_average_description("Sprite Can 24 330ml")
        assert app._is_can_average_description("Old Jamaica Ginger Beer 24 330ml")
        assert not app._is_can_average_description("Red Bull 24 250ml")

    def test_weighted_average_per_can(self, app):
        lines = [
            ("Coca Cola Can 24 330ml", 2, 24, 10.50, "B"),
            ("Diet Coke Can 24 330ml", 1, 24, 8.50, "B"),
        ]
        avg, total_cans = app._compute_can_average_cost({}, lines)
        expected_total_cans = 2 * 24 + 1 * 24
        expected_ex_value = 2 * 10.50 + 1 * 8.50
        assert total_cans == expected_total_cans
        assert round(avg, 4) == round(expected_ex_value / expected_total_cans, 4)

    def test_non_can_items_ignored_in_average(self, app):
        lines = [
            ("Coca Cola Can 24 330ml", 1, 24, 10.50, "B"),
            ("Red Bull 24 250ml", 1, 24, 24.00, "B"),
        ]
        avg, total_cans = app._compute_can_average_cost({}, lines)
        assert total_cans == 24
        assert round(avg, 4) == round(10.50 / 24, 4)

    def test_no_can_lines_returns_zero(self, app):
        lines = [
            ("Red Bull 24 250ml", 1, 24, 24.00, "B"),
        ]
        avg, total_cans = app._compute_can_average_cost({}, lines)
        assert total_cans == 0
        assert avg == 0.0


class TestInvoiceCostStorageIsExVat:
    def test_invoice_parser_returns_ex_vat_price(self, app):
        line = "282574 Coca Cola Can 24 330ml 1 10.50 TC 21.00 B 1.49 64.8%"
        _, _, _, price, vat_code = app._parse_booker_invoice_line(line)
        assert price == 10.50  # raw case price is ex VAT
        assert vat_code == "B"
