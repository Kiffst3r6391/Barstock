"""
Transaction action constants for BarStock.

These constants keep action names consistent across the UI, reports, and data layer.
The exact string values are preserved for backward compatibility with existing SQLite logs.
"""

ACTION_SALES = 'Sales'
ACTION_SALES_ONE_UNIT = 'Sales (1 unit)'
ACTION_DELIVERY = 'Delivery'
ACTION_WASTAGE = 'Wastage'
ACTION_LINE_CLEAN = 'line_clean'
ACTION_COMPLIMENTARY = 'Complimentary'
ACTION_OPEN_TAB = 'Open Tab'
ACTION_TAB_CANCELLED = 'Tab Cancelled'
ACTION_PARENT_STOCK_ADJ = 'Parent Stock Adj.'
ACTION_STOCKTAKE_BASELINE = 'Stocktake Baseline'
ACTION_STOCKTAKE_ADJUSTMENT = 'Stocktake Adjustment'
ACTION_IMPORT = 'import'
ACTION_SUPPLIER_RETURN = 'Supplier Return'
# Price-only audit row written when invoice prices are applied. It carries no
# stock movement, so reports must not treat it as a delivery.
ACTION_PRICE_UPDATE = 'Price Update'

# Stocktake rows describe corrections to expected stock rather than sales:
# Baseline rows reset the expected level, Adjustment rows carry the variance.
STOCKTAKE_ACTIONS = {ACTION_STOCKTAKE_BASELINE, ACTION_STOCKTAKE_ADJUSTMENT}

SALE_ACTIONS = {ACTION_SALES, ACTION_SALES_ONE_UNIT}
NEGATIVE_STOCK_ACTIONS = SALE_ACTIONS | {ACTION_WASTAGE, ACTION_LINE_CLEAN, ACTION_COMPLIMENTARY, ACTION_OPEN_TAB, ACTION_SUPPLIER_RETURN}
# Actions that represent actual stock consumption for reporting/reconciliation.
# Open Tab is excluded because it is only a reservation; the real consumption is
# recorded when the tab is closed (Sales/Complimentary) or cancelled (Tab Cancelled).
# Supplier Return is excluded because returned stock is expected to be credited
# back by the supplier and should not be counted as loss/consumption.
CONSUMPTION_ACTIONS = SALE_ACTIONS | {ACTION_WASTAGE, ACTION_LINE_CLEAN, ACTION_COMPLIMENTARY}
