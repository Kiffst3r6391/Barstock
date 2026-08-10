# BarStock upgrade plan

## Goal
Prevent future mismatches between physical stock and system stock by adding guards, previews, automatic master-list updates, and a reconciliation report.

## Upgrades to implement

### 1. Startup sync check
- Add `validate_inventory_sync(inventory_df)` in a new helper module (or `categories.py`/`conversions.py` pair) that returns items missing from:
  - `conversions.py` `STOCK_CONVERSIONS`
  - `categories.py` `CATEGORY_MAP`
  - `order_sheet_layout.py` `ORDER_SHEET_LAYOUT`
- Call it from `BarStockApp.py` after `self.inventory_df = InventoryDataManager.load_inventory()` in `__init__`.
- Show a `messagebox.showwarning` listing any problems with a one-click suggestion.

### 2. Audit/order-sheet `None` links
- Add a helper `find_order_sheet_items_without_id(inventory_df)` that detects tracked items that appear on the order sheet with `None`.
- Include the result in the startup sync check and the reconciliation report.
- Also run a manual audit now and fix any obvious cases (Glen Scotia already fixed).

### 3. Delivery unit selector / label
- In `process_delivery_multi_item()` / `add_item_to_delivery()`, update the quantity label so it always shows the input unit for converted items:
  - `Quantity (bottles):` for spirits
  - `Quantity (barrels):` for draught
  - `Quantity (cartons):` for carton juice
  - `Quantity (boxes):` for postmix
- Keep the existing conversion message so the user sees e.g. `1.0 bottles = 20.0 measures`.

### 4. Stocktake unit warning
- In `record_stocktake()`, when the user enters a counted quantity for an item that requires conversion, show a small note next to the field:
  - `Enter count in bottles (1 bottle = 20 measures)`
- If the counted value is suspiciously small (e.g. < 0.5 input units for a converted item), show a confirmation `askyesno` asking whether they meant measures instead of bottles.

### 5. Sales upload preview (before/after in display units)
- Extend `csv_upload.py` `build_preview_item()` or the preview DataFrame in `upload_sales_report()` to show:
  - Current stock in display units (`1.5 bottles`)
  - Sales quantity in display units (`8 measures`)
  - Projected stock in display units (`1.1 bottles`)
- Use `conversions.format_stock_display()` and `convert_to_input()` helpers.

### 6. Block/warn on negative stock during sales upload
- In `upload_sales_report()`, change the negative-stock flow:
  - If any item would go negative and `allow_negative` is False, **block** the upload with `messagebox.showerror` listing the items.
  - If `allow_negative` is True, show a warning `askyesno` confirmation.
- Currently it only warns when >10% go negative; this is too loose.

### 7. Add Glen Scotia to `Items.csv` + auto-add new items to master CSV
- Add a row to `Items.csv` for Glen Scotia with sensible defaults.
- Add a helper `append_item_to_master_csv(item_row_dict, csv_path)` in `data_manager.py`.
- Call it from `BarStockApp.py` `save_item()` inside `add_stock_item()` whenever a new item is successfully created.
- The helper must match the `Items.csv` header and append only if the `item_id` is not already present.

### 8. Reconciliation report
- Add `build_reconciliation_report_data(inventory_df, log_df, layout)` to `reports.py` that finds:
  - Items in inventory missing from `conversions.py`/`categories.py`
  - Items on order sheet with `None` that have stock > 0
  - Items that went negative in the last 7/30 days
  - Items in `Items.csv` but not in live inventory (and vice versa)
- Wire it into `BarStockApp.py` `generate_reports()` as a new button.
- Generate the report as a simple treeview dialog or PDF via `pdf_generator.py`.

## Files to touch
- `conversions.py` — add `format_input_unit_label()` helper if needed
- `categories.py` — add sync helpers
- `order_sheet_layout.py` — already fixed Glen Scotia; add audit helper
- `data_manager.py` — `append_item_to_master_csv()`
- `BarStockApp.py` — startup check, delivery labels, stocktake warning, sales upload blocking, auto-add to CSV, report button
- `csv_upload.py` — preview enhancements
- `reports.py` — reconciliation report builder
- `Items.csv` — add Glen Scotia row
- `tests/` — add regression tests for sync check, auto-add-to-CSV, and negative-stock upload guard

## Out of scope / optional future
- Reversing the historical Glen Scotia delivery of `2.0` measures entered on 6 Aug — this is a one-off data cleanup that the user can handle via stocktake if needed.
- Changing the database schema; all work stays at the app/reporting layer.

## Testing plan
1. Run existing unit tests (`test_add_sales.py`, `test_delivery_edit.py`).
2. Add new tests:
   - `test_sync_check.py` — inventory item missing from conversions/categories is flagged.
   - `test_auto_csv_append.py` — creating an item appends to `Items.csv`.
   - `test_sales_upload_negative_block.py` — upload that would drive stock negative is blocked.
3. Manual smoke test:
   - Open app; confirm no sync warning for Glen Scotia.
   - Add a dummy item; confirm it appears in `Items.csv`.
   - Attempt sales upload that would drive dummy item negative; confirm blocked.
