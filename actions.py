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
ACTION_IMPORT = 'import'

SALE_ACTIONS = {ACTION_SALES, ACTION_SALES_ONE_UNIT}
NEGATIVE_STOCK_ACTIONS = SALE_ACTIONS | {ACTION_WASTAGE, ACTION_LINE_CLEAN, ACTION_COMPLIMENTARY, ACTION_OPEN_TAB}
