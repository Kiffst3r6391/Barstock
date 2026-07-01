"""
StockService - Business logic layer for BarStock operations.

This module encapsulates recording deliveries, sales, wastage, complimentary
items, stocktakes, and parent-stock adjustments. It reads from and writes to
the SQLite database via InventoryDataManager.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Tuple, Optional

import pandas as pd

from actions import (
    ACTION_SALES, ACTION_DELIVERY, ACTION_WASTAGE, ACTION_COMPLIMENTARY,
    ACTION_OPEN_TAB, ACTION_PARENT_STOCK_ADJ
)
from data_manager import (
    InventoryDataManager,
    COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE,
    COL_ACTION, COL_TIMESTAMP, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON,
    COL_MEMBER_QTY, COL_NON_MEMBER_QTY, COL_ALLOW_NEGATIVE,
)
from sales_mapping import (
    has_parent_stock, apply_sale_to_parent, check_apply_sale_to_parent,
    get_effective_cost_price,
)


class StockServiceError(Exception):
    """Raised when a stock operation cannot be completed."""
    pass


def _validate_quantity(quantity: float, field_name: str = "Quantity") -> float:
    if quantity is None:
        raise StockServiceError(f"{field_name} is required.")
    try:
        quantity = float(quantity)
    except (ValueError, TypeError):
        raise StockServiceError(f"{field_name} must be a valid number.")
    if quantity <= 0:
        raise StockServiceError(f"{field_name} must be greater than zero.")
    return quantity


def _validate_item_exists(inventory_df: pd.DataFrame, item_id: str) -> None:
    if inventory_df.empty or item_id not in inventory_df[COL_ITEM_ID].values:
        raise StockServiceError(f"Item '{item_id}' not found in inventory.")


def _check_negative_stock(inventory_df: pd.DataFrame, item_id: str, deduction_qty: float) -> None:
    row = inventory_df[inventory_df[COL_ITEM_ID] == item_id]
    if row.empty:
        raise StockServiceError(f"Item '{item_id}' not found in inventory.")
    current_qty = row[COL_QUANTITY].values[0]
    allow_negative = bool(row[COL_ALLOW_NEGATIVE].values[0]) if COL_ALLOW_NEGATIVE in row.columns else False
    if not allow_negative and current_qty < deduction_qty:
        raise StockServiceError(
            f"Cannot deduct {deduction_qty:.1f} of '{item_id}': only {current_qty:.1f} in stock."
        )


def _check_parent_stock(inventory_df: pd.DataFrame, item_id: str, quantity: float) -> None:
    if not has_parent_stock(item_id):
        return
    ok, issues = check_apply_sale_to_parent(
        item_id, quantity, inventory_df,
        COL_ITEM_ID, COL_QUANTITY, COL_ALLOW_NEGATIVE
    )
    if not ok:
        raise StockServiceError("\n".join(issues))


def _record_parent_adjustments(
    log_df: pd.DataFrame,
    item_id: str,
    quantity: float,
    inventory_df: pd.DataFrame,
    timestamp: str,
    date_range: str,
    reason: str,
) -> pd.DataFrame:
    """Log parent-stock adjustments for a child sale and return the updated log."""
    if not has_parent_stock(item_id):
        return log_df

    parent_adjustments = apply_sale_to_parent(
        item_id, quantity, inventory_df, COL_ITEM_ID, COL_QUANTITY
    )
    if not parent_adjustments:
        return log_df

    entries = []
    for parent_id, deduction, _desc in parent_adjustments:
        parent_row = inventory_df[inventory_df[COL_ITEM_ID] == parent_id]
        if parent_row.empty:
            continue
        parent_cost = parent_row[COL_COST_PRICE].values[0]
        parent_sell = parent_row[COL_SELL_PRICE].values[0]
        entries.append([
            parent_id, ACTION_PARENT_STOCK_ADJ, deduction, timestamp,
            parent_cost, parent_sell, f"From {item_id}", date_range, reason,
            0.0, 0.0,
        ])

    if entries:
        new_log = pd.DataFrame(
            entries,
            columns=[
                COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP,
                COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE,
                COL_REASON, COL_MEMBER_QTY, COL_NON_MEMBER_QTY,
            ],
        )
        log_df = pd.concat([log_df, new_log], ignore_index=True)
    return log_df


class StockService:
    """High-level service for stock operations backed by SQLite."""

    def __init__(self) -> None:
        self.inventory_df = InventoryDataManager.load_inventory()
        self.log_df = InventoryDataManager.load_log()

    def refresh(self) -> None:
        """Reload the in-memory DataFrames from the database."""
        self.inventory_df = InventoryDataManager.load_inventory()
        self.log_df = InventoryDataManager.load_log()

    def save(self) -> None:
        """Persist the current in-memory DataFrames to the database."""
        if not InventoryDataManager.save_inventory(self.inventory_df):
            raise StockServiceError("Failed to save inventory.")
        if not InventoryDataManager.save_log(self.log_df):
            raise StockServiceError("Failed to save transaction log.")

    def record_delivery(
        self,
        item_id: str,
        quantity: float,
        cost_price: float,
        supplier: str = "",
        timestamp: Optional[str] = None,
    ) -> None:
        """Record a delivery, increasing stock."""
        _validate_item_exists(self.inventory_df, item_id)
        quantity = _validate_quantity(quantity, "Delivery quantity")
        if cost_price is None or cost_price < 0:
            raise StockServiceError("Cost price cannot be negative.")

        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        sell_price = self.inventory_df.loc[
            self.inventory_df[COL_ITEM_ID] == item_id, COL_SELL_PRICE
        ].values[0]

        self.inventory_df.loc[
            self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY
        ] += quantity

        new_entry = pd.DataFrame(
            [[item_id, ACTION_DELIVERY, quantity, timestamp, cost_price, sell_price, supplier, "", ""]],
            columns=[
                COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP,
                COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON,
            ],
        )
        self.log_df = pd.concat([self.log_df, new_entry], ignore_index=True)

    def record_sale(
        self,
        item_id: str,
        quantity: float,
        member_qty: Optional[float] = None,
        non_member_qty: Optional[float] = None,
        timestamp: Optional[str] = None,
        date_range: str = "",
    ) -> None:
        """Record a sale, decreasing stock and applying parent deductions."""
        _validate_item_exists(self.inventory_df, item_id)
        quantity = _validate_quantity(quantity, "Sale quantity")
        _check_negative_stock(self.inventory_df, item_id, quantity)
        _check_parent_stock(self.inventory_df, item_id, quantity)

        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cost_price = get_effective_cost_price(item_id, self.inventory_df, COL_ITEM_ID, COL_COST_PRICE)
        sell_price = self.inventory_df.loc[
            self.inventory_df[COL_ITEM_ID] == item_id, COL_SELL_PRICE
        ].values[0]

        self.inventory_df.loc[
            self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY
        ] -= quantity

        member_qty = member_qty if member_qty is not None else 0.0
        non_member_qty = non_member_qty if non_member_qty is not None else 0.0

        new_entry = pd.DataFrame(
            [[
                item_id, ACTION_SALES, quantity, timestamp, cost_price, sell_price,
                "", date_range, "", member_qty, non_member_qty,
            ]],
            columns=[
                COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP,
                COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE,
                COL_REASON, COL_MEMBER_QTY, COL_NON_MEMBER_QTY,
            ],
        )
        self.log_df = pd.concat([self.log_df, new_entry], ignore_index=True)

        self.log_df = _record_parent_adjustments(
            self.log_df, item_id, quantity, self.inventory_df,
            timestamp, date_range, "",
        )

    def record_wastage(
        self,
        item_id: str,
        quantity: float,
        reason: str = "",
        timestamp: Optional[str] = None,
        date_range: str = "",
    ) -> None:
        """Record wastage, decreasing stock and applying parent deductions."""
        _validate_item_exists(self.inventory_df, item_id)
        quantity = _validate_quantity(quantity, "Wastage quantity")
        _check_negative_stock(self.inventory_df, item_id, quantity)
        _check_parent_stock(self.inventory_df, item_id, quantity)

        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cost_price = get_effective_cost_price(item_id, self.inventory_df, COL_ITEM_ID, COL_COST_PRICE)
        sell_price = self.inventory_df.loc[
            self.inventory_df[COL_ITEM_ID] == item_id, COL_SELL_PRICE
        ].values[0]

        self.inventory_df.loc[
            self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY
        ] -= quantity

        new_entry = pd.DataFrame(
            [[
                item_id, ACTION_WASTAGE, quantity, timestamp, cost_price, sell_price,
                "", date_range, reason,
            ]],
            columns=[
                COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP,
                COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON,
            ],
        )
        self.log_df = pd.concat([self.log_df, new_entry], ignore_index=True)

        self.log_df = _record_parent_adjustments(
            self.log_df, item_id, quantity, self.inventory_df,
            timestamp, date_range, reason,
        )

    def record_complimentary(
        self,
        item_id: str,
        quantity: float,
        timestamp: Optional[str] = None,
        date_range: str = "",
        reason: str = "CSV Upload",
    ) -> None:
        """Record a complimentary item, decreasing stock and applying parent deductions."""
        _validate_item_exists(self.inventory_df, item_id)
        quantity = _validate_quantity(quantity, "Complimentary quantity")
        _check_negative_stock(self.inventory_df, item_id, quantity)
        _check_parent_stock(self.inventory_df, item_id, quantity)

        if timestamp is None:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        cost_price = get_effective_cost_price(item_id, self.inventory_df, COL_ITEM_ID, COL_COST_PRICE)

        self.inventory_df.loc[
            self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY
        ] -= quantity

        new_entry = pd.DataFrame(
            [[
                item_id, ACTION_COMPLIMENTARY, quantity, timestamp, cost_price, 0.0,
                "", date_range, reason,
            ]],
            columns=[
                COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP,
                COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON,
            ],
        )
        self.log_df = pd.concat([self.log_df, new_entry], ignore_index=True)

        self.log_df = _record_parent_adjustments(
            self.log_df, item_id, quantity, self.inventory_df,
            timestamp, date_range, reason,
        )

    def record_open_tab(
        self,
        customer_name: str,
        items: List[Tuple[str, float]],
    ) -> int:
        """Record an open tab and deduct stock.

        items: list of (item_id, quantity) tuples.
        Returns the open_tab_id from the data manager.
        """
        if not customer_name:
            raise StockServiceError("Customer name is required.")
        if not items:
            raise StockServiceError("No items to save.")

        for item_id, quantity in items:
            _validate_item_exists(self.inventory_df, item_id)
            _validate_quantity(quantity)
            _check_negative_stock(self.inventory_df, item_id, quantity)
            _check_parent_stock(self.inventory_df, item_id, quantity)

        items_for_db = []
        for item_id, quantity in items:
            cost_price = get_effective_cost_price(item_id, self.inventory_df, COL_ITEM_ID, COL_COST_PRICE)
            sell_price = self.inventory_df.loc[
                self.inventory_df[COL_ITEM_ID] == item_id, COL_SELL_PRICE
            ].values[0]
            items_for_db.append({
                COL_ITEM_ID: item_id,
                COL_ITEM_NAME: "",
                COL_QUANTITY: quantity,
                COL_COST_PRICE: cost_price,
                COL_SELL_PRICE: sell_price,
            })

        tab_id = InventoryDataManager.create_open_tab(customer_name, items_for_db)
        if not tab_id:
            raise StockServiceError("Failed to create open tab.")

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for item_id, quantity in items:
            self.inventory_df.loc[
                self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY
            ] -= quantity

            cost_price = get_effective_cost_price(item_id, self.inventory_df, COL_ITEM_ID, COL_COST_PRICE)
            sell_price = self.inventory_df.loc[
                self.inventory_df[COL_ITEM_ID] == item_id, COL_SELL_PRICE
            ].values[0]
            new_entry = pd.DataFrame(
                [[
                    item_id, ACTION_OPEN_TAB, quantity, timestamp, cost_price, sell_price,
                    "", "", customer_name,
                ]],
                columns=[
                    COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP,
                    COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON,
                ],
            )
            self.log_df = pd.concat([self.log_df, new_entry], ignore_index=True)

            self.log_df = _record_parent_adjustments(
                self.log_df, item_id, quantity, self.inventory_df,
                timestamp, "", customer_name,
            )

        return tab_id

    def apply_child_parent_deductions(
        self,
        item_id: str,
        quantity: float,
    ) -> List[Tuple[str, float, str]]:
        """Apply parent-stock deductions for a child sale. Returns adjustment details."""
        if not has_parent_stock(item_id):
            return []
        _check_parent_stock(self.inventory_df, item_id, quantity)
        return apply_sale_to_parent(item_id, quantity, self.inventory_df, COL_ITEM_ID, COL_QUANTITY)
