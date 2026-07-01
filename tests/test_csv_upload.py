"""Tests for CSV upload parsing and application."""

from __future__ import annotations

import os
import tempfile

import pytest

from csv_upload import parse_sales_csv, parse_complimentary_csv, apply_sales_upload, apply_complimentary_upload, CSVUploadError
from actions import ACTION_SALES, ACTION_COMPLIMENTARY, ACTION_PARENT_STOCK_ADJ


class TestCSVUpload:
    """Unit tests for csv_upload helpers."""

    @pytest.fixture
    def sales_csv(self):
        content = "Rank,Product,Member Qty,Member Sales,Non Member Qty,Non Member Sales,Qty,Sales\n"
        content += "1,Tennents Lager,2,8.00,3,12.00,5,20.00\n"
        content += "2,Belhaven Best,1,4.20,1,4.20,2,8.40\n"
        content += "3,Unknown Product,1,1.00,0,0.00,1,1.00\n"
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        yield path
        os.unlink(path)

    @pytest.fixture
    def complimentary_csv(self):
        content = "Product,Qty\n"
        content += "Tennents Lager,2\n"
        content += "Tennents Half,4\n"
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        yield path
        os.unlink(path)

    def test_parse_sales_csv(self, sales_csv, sample_inventory):
        result = parse_sales_csv(sales_csv, sample_inventory)
        assert result["total_revenue"] > 0
        assert result["total_cost"] > 0
        assert len(result["preview_items"]) == 2
        assert "Unknown Product" in result["skipped_items"]

    def test_parse_complimentary_csv(self, complimentary_csv, sample_inventory):
        result = parse_complimentary_csv(complimentary_csv, sample_inventory)
        assert len(result["preview_items"]) == 2
        assert result["total_cost"] > 0

    def test_apply_sales_upload(self, sales_csv, sample_inventory, empty_log):
        parsed = parse_sales_csv(sales_csv, sample_inventory)
        inv, log, tx, skipped = apply_sales_upload(
            parsed["preview_items"], sample_inventory, empty_log, parsed["date_range_str"]
        )
        assert len(log[log["action"] == ACTION_SALES]) == 2
        assert inv.loc[inv["item_id"] == "tennents_lager", "quantity"].values[0] == 95.0

    def test_apply_complimentary_upload_parent_deduction(self, complimentary_csv, sample_inventory, empty_log):
        parsed = parse_complimentary_csv(complimentary_csv, sample_inventory)
        inv, log, tx, skipped = apply_complimentary_upload(
            parsed["preview_items"], sample_inventory, empty_log, parsed["date_range_str"]
        )
        parent_qty = inv.loc[inv["item_id"] == "tennents_lager", "quantity"].values[0]
        assert parent_qty == 96.0  # 2 full pints + 4 half-pints = 4 pints deducted
        adj = log[log["action"] == ACTION_PARENT_STOCK_ADJ]
        assert len(adj) == 1
        assert adj.iloc[0]["quantity"] == 2.0  # 4 half-pints

    def test_missing_product_column_raises(self, sample_inventory):
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.write(fd, b"Foo,Qty\n1,2\n")
        os.close(fd)
        try:
            with pytest.raises(CSVUploadError):
                parse_sales_csv(path, sample_inventory)
        finally:
            os.unlink(path)
