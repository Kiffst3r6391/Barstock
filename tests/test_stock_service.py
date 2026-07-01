"""Tests for the StockService business-logic layer."""

from __future__ import annotations

import pytest

from stock_service import StockService, StockServiceError
from actions import (
    ACTION_SALES, ACTION_DELIVERY, ACTION_WASTAGE, ACTION_COMPLIMENTARY,
    ACTION_PARENT_STOCK_ADJ, ACTION_OPEN_TAB,
)


class TestStockService:
    """Unit tests for StockService using in-memory DataFrames."""

    @pytest.fixture(autouse=True)
    def setup(self, sample_inventory, empty_log, monkeypatch):
        """Provide a StockService whose DataFrames never touch SQLite."""
        self.inventory = sample_inventory.copy()
        self.log = empty_log.copy()

        def fake_load_inventory():
            return self.inventory.copy()

        def fake_load_transaction_log():
            return self.log.copy()

        def fake_save_inventory(df):
            self.inventory = df.copy()
            return True

        def fake_save_log(df):
            self.log = df.copy()
            return True

        import stock_service
        monkeypatch.setattr(stock_service.InventoryDataManager, "load_inventory", fake_load_inventory)
        monkeypatch.setattr(stock_service.InventoryDataManager, "load_log", fake_load_transaction_log)
        monkeypatch.setattr(stock_service.InventoryDataManager, "save_inventory", fake_save_inventory)
        monkeypatch.setattr(stock_service.InventoryDataManager, "save_log", fake_save_log)

        self.service = StockService()
        self.service.inventory_df = self.inventory
        self.service.log_df = self.log

    def test_record_delivery_increases_stock(self):
        self.service.record_delivery("tennents_lager", 20.0, 1.40, supplier="Booker")
        self.service.save()

        assert self.inventory.loc[self.inventory["item_id"] == "tennents_lager", "quantity"].values[0] == 120.0
        log = self.log
        assert len(log) == 1
        assert log.iloc[0]["action"] == ACTION_DELIVERY
        assert log.iloc[0]["quantity"] == 20.0
        assert log.iloc[0]["supplier"] == "Booker"

    def test_record_delivery_rejects_negative_cost(self):
        with pytest.raises(StockServiceError):
            self.service.record_delivery("tennents_lager", 10.0, -1.0)

    def test_record_sale_decreases_stock(self):
        self.service.record_sale("tennents_lager", 10.0)
        self.service.save()

        assert self.inventory.loc[self.inventory["item_id"] == "tennents_lager", "quantity"].values[0] == 90.0
        assert len(self.log) == 1
        assert self.log.iloc[0]["action"] == ACTION_SALES

    def test_record_sale_child_deducts_parent(self):
        # Child items can go negative; only parent stock is guarded
        self.inventory.loc[self.inventory["item_id"] == "tennents_lager_half", "allow_negative"] = True
        self.service.refresh()
        self.service.record_sale("tennents_lager_half", 4.0)
        self.service.save()

        parent_qty = self.inventory.loc[self.inventory["item_id"] == "tennents_lager", "quantity"].values[0]
        child_qty = self.inventory.loc[self.inventory["item_id"] == "tennents_lager_half", "quantity"].values[0]
        assert parent_qty == 98.0
        assert child_qty == -4.0

        adj = self.log[self.log["action"] == ACTION_PARENT_STOCK_ADJ]
        assert len(adj) == 1
        assert adj.iloc[0]["item_id"] == "tennents_lager"
        assert adj.iloc[0]["quantity"] == 2.0

    def test_record_sale_blocks_negative_parent_stock(self):
        # Drain parent stock first
        self.inventory.loc[self.inventory["item_id"] == "tennents_lager", "quantity"] = 1.0
        with pytest.raises(StockServiceError):
            self.service.record_sale("tennents_lager_half", 4.0)

    def test_record_wastage_decreases_stock(self):
        self.service.record_wastage("lemonade", 5.0, reason="Broken glass")
        self.service.save()

        assert self.inventory.loc[self.inventory["item_id"] == "lemonade", "quantity"].values[0] == 55.0
        assert self.log.iloc[0]["reason"] == "Broken glass"

    def test_record_complimentary_decreases_stock(self):
        self.service.record_complimentary("belhaven_best", 3.0)
        self.service.save()

        assert self.inventory.loc[self.inventory["item_id"] == "belhaven_best", "quantity"].values[0] == 77.0
        assert self.log.iloc[0]["action"] == ACTION_COMPLIMENTARY
        assert self.log.iloc[0]["sell_price"] == 0.0

    def test_record_open_tab_creates_tab_and_deducts_stock(self):
        import stock_service
        created = {"tab_id": None}

        def fake_create_open_tab(customer_name, items):
            created["tab_id"] = 42
            return 42

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(stock_service.InventoryDataManager, "create_open_tab", fake_create_open_tab)
        try:
            tab_id = self.service.record_open_tab("Alice", [("tennents_lager", 2.0)])
            # Service mutates its own DataFrames; copy them back to the fixture-level variables
            self.inventory = self.service.inventory_df
            self.log = self.service.log_df
        finally:
            monkeypatch.undo()

        assert tab_id == 42
        assert self.inventory.loc[self.inventory["item_id"] == "tennents_lager", "quantity"].values[0] == 98.0
        open_tab_log = self.log[self.log["action"] == ACTION_OPEN_TAB]
        assert len(open_tab_log) == 1
        assert open_tab_log.iloc[0]["reason"] == "Alice"

    def test_record_open_tab_rejects_empty_customer(self):
        with pytest.raises(StockServiceError):
            self.service.record_open_tab("", [("tennents_lager", 1.0)])

    def test_record_open_tab_rejects_insufficient_stock(self):
        with pytest.raises(StockServiceError):
            self.service.record_open_tab("Bob", [("tennents_lager", 200.0)])

    def test_validate_quantity_rejects_zero(self):
        with pytest.raises(StockServiceError):
            self.service.record_sale("tennents_lager", 0.0)

    def test_validate_item_exists(self):
        with pytest.raises(StockServiceError):
            self.service.record_sale("missing_item", 1.0)
