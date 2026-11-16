#!/usr/bin/env python3
"""Upload screens: EPOS sales, complimentary drinks and Booker invoice checks."""

import hashlib
import os
import re
from collections import defaultdict
from datetime import datetime
from io import StringIO

import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import ui_theme
from ui_theme import (
    THEME_BG, THEME_BORDER, THEME_CARD, THEME_DANGER, THEME_SUCCESS,
    THEME_TEXT, THEME_TEXT_MUTED, THEME_WARNING, TBL_ROW_ALT,
)

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    pdfplumber = None
    PDFPLUMBER_AVAILABLE = False

from app_config import (
    COL_ACTION, COL_COST_PRICE, COL_DATE_RANGE, COL_ITEM_ID, COL_ITEM_NAME,
    COL_MEASURE, COL_PRICE_LOCKED, COL_QUANTITY, COL_REASON, COL_SELL_PRICE,
    COL_SUPPLIER, COL_TIMESTAMP, get_script_directory,
)
from actions import (
    ACTION_COMPLIMENTARY, ACTION_PARENT_STOCK_ADJ, ACTION_PRICE_UPDATE,
    ACTION_SALES,
)
from categories import (SALES_INCLUDED_EXCLUDED_ITEMS, should_exclude,
                        is_delisted, UNTRACKED_SALES_ITEMS)
from conversions import DATE_FORMAT_DISPLAY, format_quantity_display, get_conversion
import data_manager as data_manager_module
from data_manager import (
    COL_ALLOW_NEGATIVE, COL_MEMBER_QTY, COL_NON_MEMBER_QTY,
    InventoryDataManager, add_upload_hash, is_duplicate_upload,
)
from inventory_sync import update_items_csv_total_value
from money import allocate_money, inc_vat, round_money, sum_money
from reports import (
    build_upload_period_health, find_overlapping_upload_periods,
)
from sales_mapping import (
    apply_sale_to_parent, check_apply_sale_to_parent, get_effective_cost_price,
    has_parent_stock, is_ignored_epos_product, normalize_product_name,
    resolve_epos_item_id,
)


class UploadsMixin:
    """Sales, complimentary and invoice upload methods mixed into the app."""

    def show_sales_upload(self):
        """Show the Sales Upload tab by wrapping the existing sales flow."""
        self._create_app_shell('Sales Upload')
        self.add_sales()


    def add_sales(self):
        """Add sales with option to upload weekly report."""
        self.clear_main_menu()
    
        # Upload card
        upload_card = self._card(self.main_menu, title="Upload weekly sales report")
        upload_card.pack(fill='x', pady=(0, 20))
    
        self.themed_label(upload_card,
                          "Upload CSV file with sales data to auto-populate transactions.",
                          font=(ui_theme.THEME_FONT, 11), fg=THEME_TEXT, wraplength=700).pack(anchor='w', padx=14, pady=(8, 0))
        self.themed_label(upload_card,
                          "Expected format: Rank, Product, Member Qty, Member Sales, Non Member Qty, Non Member Sales, Qty, Sales",
                          font=(ui_theme.THEME_FONT, 9), fg=THEME_TEXT_MUTED, wraplength=700).pack(anchor='w', padx=14, pady=(4, 8))
        self.styled_button(upload_card, "Select Sales Report CSV", self.upload_sales_report,
                           width=26, variant='primary').pack(anchor='w', padx=14, pady=(0, 12))
    
        # Recent uploads
        history_card = self._card(self.main_menu, title="Recent uploads")
        history_card.pack(fill='x', pady=(0, 20))
    
        if not self.log_df.empty and 'date_range' in self.log_df.columns:
            sales_uploads = self.log_df[self.log_df[COL_ACTION] == ACTION_SALES]
            if not sales_uploads.empty:
                has_member = COL_MEMBER_QTY in sales_uploads.columns
                agg = {'quantity': 'sum', 'cost_price': 'count'}
                if has_member:
                    agg[COL_MEMBER_QTY] = 'sum'
                    agg[COL_NON_MEMBER_QTY] = 'sum'
                upload_batches = sales_uploads.groupby(['timestamp', 'date_range']).agg(agg).reset_index()
                upload_batches.columns = ['timestamp', 'date_range', 'total_qty', 'items'] + ([COL_MEMBER_QTY, COL_NON_MEMBER_QTY] if has_member else [])
                upload_batches['total_revenue'] = sales_uploads.groupby(['timestamp', 'date_range']).apply(
                    lambda g: (g[COL_QUANTITY] * g[COL_SELL_PRICE]).sum()
                ).reset_index(drop=True)
                recent = upload_batches.sort_values('timestamp', ascending=False).head(10)
                if not recent.empty:
                    for index, (_, entry) in enumerate(recent.iterrows()):
                        date_range = entry['date_range'] if pd.notna(entry['date_range']) else 'N/A'
                        ts = entry['timestamp'][:16] if pd.notna(entry['timestamp']) else 'N/A'
                        qty = entry['total_qty']
                        rev = entry['total_revenue']
    
                        line1 = str(date_range)
                        meta = f"UPLOADED {ts}  ·  {int(entry['items'])} ITEMS"
                        # Inc VAT first so an upload can be checked against the
                        # EPOS export, which totals sales inc VAT.
                        line2_parts = [f"Qty {qty:.1f}",
                                       f"Revenue £{inc_vat(rev):,.2f} inc VAT",
                                       f"£{rev:,.2f} ex"]
                        if has_member:
                            mem_qty = entry.get(COL_MEMBER_QTY, 0)
                            non_mem_qty = entry.get(COL_NON_MEMBER_QTY, 0)
                            if mem_qty > 0 or non_mem_qty > 0:
                                line2_parts.append(f"Member {mem_qty:.1f}  ·  Non-member {non_mem_qty:.1f}")
                        line2 = "   ·   ".join(line2_parts)
    
                        if index:
                            tk.Frame(history_card, bg=THEME_BORDER,
                                     height=1).pack(fill='x', padx=14)
                        row_frame = self.themed_frame(history_card, bg=THEME_CARD)
                        row_frame.pack(fill='x', padx=14, pady=7)
                        self.themed_label(row_frame, line1,
                                          font=ui_theme.display_font(13),
                                          fg=THEME_TEXT,
                                          bg=THEME_CARD).pack(anchor='w')
                        self.themed_label(row_frame, meta,
                                          font=ui_theme.mono_font(8),
                                          fg=THEME_TEXT_MUTED,
                                          bg=THEME_CARD).pack(anchor='w',
                                                              pady=(1, 0))
                        self.themed_label(row_frame, line2,
                                          font=ui_theme.mono_font(9),
                                          fg=THEME_TEXT_MUTED,
                                          bg=THEME_CARD).pack(anchor='w',
                                                              pady=(3, 0))
                else:
                    self.themed_label(history_card, "No uploads yet", font=(ui_theme.THEME_FONT, 9),
                                      fg=THEME_TEXT_MUTED).pack(padx=14, pady=10)
            else:
                self.themed_label(history_card, "No uploads yet", font=(ui_theme.THEME_FONT, 9),
                                  fg=THEME_TEXT_MUTED).pack(padx=14, pady=10)
        else:
            self.themed_label(history_card, "No uploads yet", font=(ui_theme.THEME_FONT, 9),
                              fg=THEME_TEXT_MUTED).pack(padx=14, pady=10)
    
        # Manual entry card
        manual_card = self._card(self.main_menu, title="Manual entry")
        manual_card.pack(fill='x', pady=(0, 20))
    
        self.themed_label(manual_card, "Or add individual sales transaction:",
                          font=(ui_theme.THEME_FONT, 11), fg=THEME_TEXT).pack(anchor='w', padx=14, pady=(8, 0))
        self.styled_button(manual_card, "Add Single Sale",
                           lambda: self.process_transaction(ACTION_SALES),
                           width=26, variant='secondary').pack(anchor='w', padx=14, pady=(8, 12))
    
        # Back button
        back_frame = self.themed_frame(self.main_menu)
        back_frame.pack(fill='x', pady=(0, 20))
        self.styled_button(back_frame, "Back", self.show_dashboard, width=20, variant='secondary').pack(side='left')
    
        self._apply_legacy_theme()


    @staticmethod
    def parse_date_range_from_filename(filepath):
        """Extract date range from sales CSV filename.
        Expected format: ...transactions-DD-MM-YYYY-DD-MM-YYYY-generated-...
        Returns (start_date, end_date) as datetime objects, or (None, None).
        """
        import re
        basename = os.path.basename(filepath)
        # Match DD-MM-YYYY-DD-MM-YYYY pattern
        match = re.search(r'(\d{2})-(\d{2})-(\d{4})-(\d{2})-(\d{2})-(\d{4})', basename)
        if match:
            d1, m1, y1, d2, m2, y2 = match.groups()
            try:
                start_date = datetime(int(y1), int(m1), int(d1))
                end_date = datetime(int(y2), int(m2), int(d2))
                return start_date, end_date
            except ValueError:
                pass
        return None, None


    @staticmethod
    def _read_sales_file(filepath):
        """Read and parse an EPOS sales CSV. Runs off the UI thread.
    
        Returns ``(file_hash, sales_df)``. Raises ``ValueError`` with a
        user-facing message when the file is not a usable sales report.
        """
        with open(filepath, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
    
        # Detect and strip composite EPOS files that append a second report.
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            raw_lines = f.readlines()
    
        clean_lines = []
        for i, line in enumerate(raw_lines):
            # Check for the start of the second report section (different column format)
            if line.strip().startswith('"Name') or line.strip().startswith('Name\n'):
                remaining = ''.join(raw_lines[i:i + 5])
                if 'Payment Method' in remaining or 'Date\n' in remaining or 'Subtotal' in remaining:
                    break
            clean_lines.append(line)
    
        if len(clean_lines) < len(raw_lines):
            print(f"Stripped {len(raw_lines) - len(clean_lines)} lines from composite report (detailed section removed).")
    
        from io import StringIO
        try:
            sales_df = pd.read_csv(StringIO(''.join(clean_lines)), compression=None)
        except Exception as exc:
            raise ValueError(f"Could not read the report as a CSV: {exc}") from exc
        if sales_df.empty:
            raise ValueError("The report contains no rows.")
        sales_df.columns = [col.strip() for col in sales_df.columns]
    
        if 'Product' not in sales_df.columns:
            raise ValueError("Sales report must have a 'Product' column.")
        return file_hash, sales_df

    @staticmethod
    def _epos_line_total(row):
        """Return an EPOS line total in pence-inclusive pounds, if present.

        EPOS product-transaction exports carry the line total in a column named
        'Sales'; some older exports call it 'Totals'. Reports that only split
        the sale carry 'Member Sales' and 'Non Member Sales' instead.
        """
        for column in ('Totals', 'Sales', 'Total Sales'):
            if column in row.index:
                value = pd.to_numeric(
                    str(row.get(column)).replace(',', ''), errors='coerce')
                if pd.notna(value):
                    return float(value)

        parts = []
        for column in ('Member Sales', 'Non Member Sales'):
            if column in row.index:
                value = pd.to_numeric(
                    str(row.get(column)).replace(',', ''), errors='coerce')
                if pd.notna(value):
                    parts.append(float(value))
        return sum(parts) if parts else None


    @staticmethod
    def _effective_sell_price(csv_revenue, quantity, sell_price):
        """Return the per-unit price implied by the EPOS line revenue.

        A zero total is a real figure (a comped line) and must stay zero; only
        a missing total falls back to the shelf price.
        """
        if csv_revenue is not None and quantity > 0:
            return csv_revenue / quantity
        return sell_price

    @staticmethod
    def _tracks_stock(item_id, current_qty):
        """Whether a sale of this item should move stock.

        Mixed-in soft drinks are sold without club stock, and a delisted item
        holds no stock, but both still earn revenue; recording them without a
        movement avoids a negative-stock block.
        """
        if str(item_id).lower() in UNTRACKED_SALES_ITEMS:
            return False
        return not (is_delisted(item_id) and current_qty <= 0)

    @staticmethod
    def _build_reconciliation(file_total_inc, preview_items, unrecorded_lines):
        """Summarise the gap between the EPOS file total and recorded revenue.

        ``unrecorded_lines`` carries one entry per product line left out of
        the ledger, with the reason. Anything still unexplained after those
        lines (a line with no EPOS total, or rounding) is returned as
        ``residual_inc`` rather than being hidden.
        """
        reported_inc = sum_money(p['revenue_inc'] for p in preview_items)
        unrecorded_inc = round_money(file_total_inc - reported_inc)
        explained_inc = sum_money(line['revenue_inc'] for line in unrecorded_lines)
        residual_inc = round_money(unrecorded_inc - explained_inc)
        return {
            'file_total_inc': round_money(file_total_inc),
            'reported_inc': reported_inc,
            'unrecorded_inc': unrecorded_inc,
            'explained_inc': explained_inc,
            'residual_inc': residual_inc,
            'lines': unrecorded_lines,
        }

    def upload_sales_report(self):
        """Upload and process weekly sales report CSV with preview and backup."""
        try:
            filepath = filedialog.askopenfilename(
                title="Select Sales Report CSV",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
            )
            if not filepath:
                return
    
            start_date, end_date = self.parse_date_range_from_filename(filepath)
            date_range_str = ""
            if start_date and end_date:
                date_range_str = f"{start_date.strftime(DATE_FORMAT_DISPLAY)} - {end_date.strftime(DATE_FORMAT_DISPLAY)}"
    
            def continue_upload(loaded):
                file_hash, sales_df = loaded
                # Duplicate guard
                dup = is_duplicate_upload(file_hash, 'sales')
                if dup:
                    dup_info = f"Previously uploaded on {dup.get('timestamp', 'unknown')}\nFilename: {dup.get('filename', 'unknown')}"
                    response = messagebox.askyesnocancel(
                        "Duplicate Upload Detected",
                        f"This file appears to have been uploaded before.\n\n{dup_info}\n\n"
                        "Do you want to proceed?\n\n"
                        "Yes = Continue anyway\nNo = Skip (do not upload)\nCancel = Go back"
                    )
                    if response is None or response is False:
                        return

                # Period guard: a re-exported file has a different hash but can
                # still cover the same trading week. Warn before the preview.
                try:
                    full_log = InventoryDataManager.load_full_log(self.inventory_df)
                except Exception:
                    full_log = self.log_df
                if start_date and end_date:
                    overlaps = find_overlapping_upload_periods(
                        start_date, end_date, full_log)
                    if overlaps:
                        preview = "\n".join(f"• {period}" for period in overlaps[:10])
                        more = (f"\n... and {len(overlaps) - 10} more"
                                if len(overlaps) > 10 else "")
                        if not messagebox.askyesno(
                            "Overlapping Sales Period",
                            "This file's period overlaps sales already in the "
                            "ledger:\n\n" + preview + more +
                            "\n\nUploading it again may double-count those sales."
                            "\n\nContinue anyway?"
                        ):
                            return
                elif build_upload_period_health(full_log).get('periods'):
                    if not messagebox.askyesno(
                        "No Sales Period Detected",
                        "The filename does not contain a recognisable date "
                        "range, so this upload cannot be checked against "
                        "existing sales periods.\n\nContinue anyway?"
                    ):
                        return

                qty_col = None
                for col in sales_df.columns:
                    if 'qty' in col.lower() and 'member' not in col.lower():
                        qty_col = col
                        break
                if not qty_col:
                    qty_col = 'Qty'
    
                member_qty_col = None
                non_member_qty_col = None
                for col in sales_df.columns:
                    col_lower = col.lower()
                    # Match "Member Qty", "Member Quantity", "Member Count", etc.
                    if 'member' in col_lower and ('qty' in col_lower or 'quantity' in col_lower or 'count' in col_lower):
                        if 'non' in col_lower:
                            non_member_qty_col = col
                        else:
                            member_qty_col = col
    
                # The export's own inc-VAT total across every product line,
                # including lines this upload does not record (till-only
                # in/out lines, unmatched products, refunds). Prefer the
                # export's stated Total row when it has one; otherwise sum the
                # product lines. Any gap is itemised in the reconciliation.
                line_total_sum = 0.0
                stated_total_inc = None
                unrecorded_lines = []
                for _, file_row in sales_df.iterrows():
                    first_cell = (str(file_row.iloc[0]).strip().lower()
                                  if len(file_row) else '')
                    product = str(file_row.get('Product', '')).strip()
                    if first_cell == 'total':
                        stated_total_inc = self._epos_line_total(file_row)
                        continue
                    if not product or product.lower() in ('nan', 'total'):
                        continue
                    line_total = self._epos_line_total(file_row)
                    if line_total is None:
                        continue
                    line_total_sum += line_total
                    if is_ignored_epos_product(product):
                        try:
                            line_qty = float(file_row[qty_col]) if pd.notna(file_row[qty_col]) else 0
                        except (TypeError, ValueError):
                            line_qty = 0
                        unrecorded_lines.append({
                            'product': product,
                            'qty': line_qty,
                            'revenue_inc': line_total,
                            'reason': ('Staff drink in/out line: charged on the '
                                       'till, then refunded back to staff. It holds '
                                       'no stock and nets to zero, so it is not '
                                       'counted as revenue.'),
                        })
                line_total_sum = round_money(line_total_sum)
                if stated_total_inc is not None:
                    file_total_inc = round_money(stated_total_inc)
                    if abs(file_total_inc - line_total_sum) >= 0.005:
                        # The export's Total row disagrees with its own product
                        # lines (a discount or rounding in the export). Keep the
                        # difference visible rather than hiding it.
                        unrecorded_lines.append({
                            'product': 'EPOS Total row vs product lines',
                            'qty': 0,
                            'revenue_inc': round_money(file_total_inc - line_total_sum),
                            'reason': ('The CSV Total row does not equal the sum of '
                                       'its product lines (discount or rounding in '
                                       'the export).'),
                        })
                else:
                    file_total_inc = line_total_sum

                # Parse CSV into preview data without modifying inventory
                self.refresh_data()
                preview_items = []
                skipped_items = []
                total_revenue = 0
                total_cost = 0
    
                for _, row in sales_df.iterrows():
                    preview_count = len(preview_items)
                    try:
                        product_name = str(row['Product']).strip()
                        if not product_name or product_name.lower() == 'nan' or product_name.lower() == 'total':
                            continue
                        # Till-only in/out lines (e.g. the Blue WKD staff-tip
                        # button) are not sales. They are kept out of revenue
                        # but itemised in the reconciliation popup so the
                        # difference from the EPOS file total is explained.
                        if is_ignored_epos_product(product_name):
                            continue
                        line_revenue_inc = self._epos_line_total(row)
                        try:
                            quantity = float(row[qty_col]) if pd.notna(row[qty_col]) else 0
                        except:
                            quantity = 0
                        if quantity <= 0:
                            if line_revenue_inc:
                                unrecorded_lines.append({
                                    'product': product_name,
                                    'qty': quantity,
                                    'revenue_inc': line_revenue_inc,
                                    'reason': 'Zero or negative quantity (refund/void line).',
                                })
                            continue


                        try:
                            member_qty = float(row[member_qty_col]) if member_qty_col and pd.notna(row[member_qty_col]) else None
                        except:
                            member_qty = None
                        try:
                            non_member_qty = float(row[non_member_qty_col]) if non_member_qty_col and pd.notna(row[non_member_qty_col]) else None
                        except:
                            non_member_qty = None

                        normalized_id = normalize_product_name(product_name)
                        item_id = resolve_epos_item_id(normalized_id)
                        explicit_override = item_id != normalized_id

                        if item_id not in self.inventory_df[COL_ITEM_ID].values:
                            if explicit_override:
                                # Explicit EPOS mapping points to an item not in inventory; skip rather than guess.
                                skipped_items.append(product_name)
                                unrecorded_lines.append({
                                    'product': product_name,
                                    'qty': quantity,
                                    'revenue_inc': line_revenue_inc or 0.0,
                                    'reason': f"Maps to '{item_id}', which is not in the stock list.",
                                })
                                continue
                            match_found = False
                            for inv_id in self.inventory_df[COL_ITEM_ID].values:
                                inv_name = str(self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == inv_id, COL_ITEM_NAME].values[0]).lower()
                                if product_name.lower() in inv_name or inv_name in product_name.lower():
                                    item_id = inv_id
                                    match_found = True
                                    break
                            if not match_found:
                                skipped_items.append(product_name)
                                unrecorded_lines.append({
                                    'product': product_name,
                                    'qty': quantity,
                                    'revenue_inc': line_revenue_inc or 0.0,
                                    'reason': 'No matching item in the stock list.',
                                })
                                continue

                        if should_exclude(item_id) and not has_parent_stock(item_id) and item_id not in SALES_INCLUDED_EXCLUDED_ITEMS:
                            skipped_items.append(f"{product_name} (excluded)")
                            unrecorded_lines.append({
                                'product': product_name,
                                'qty': quantity,
                                'revenue_inc': line_revenue_inc or 0.0,
                                'reason': 'Excluded from sales tracking by a category rule.',
                            })
                            continue
    
                        item_row = self.inventory_df[self.inventory_df[COL_ITEM_ID] == item_id].iloc[0]
                        cost_price = get_effective_cost_price(item_id, self.inventory_df, COL_ITEM_ID, COL_COST_PRICE)
                        sell_price = item_row[COL_SELL_PRICE]
                        current_qty = item_row[COL_QUANTITY]
                        # A delisted item holds no stock, but its EPOS sales are
                        # still revenue; record them without driving stock
                        # negative or blocking the upload.
                        track_stock = self._tracks_stock(item_id, current_qty)
                        has_parent = has_parent_stock(item_id)
                        # Only an item that deducts its own stock changes here.
                        # Child items (half pints, shandies, TG items) deduct
                        # from their parent and untracked mixes never move
                        # stock, so showing a negative "after upload" for them
                        # would be a false alarm.
                        if has_parent or not track_stock:
                            projected = current_qty
                        else:
                            projected = current_qty - quantity
    
                        # The EPOS line total is inc-VAT. The system records revenue
                        # ex-VAT, so divide by 1.2 before recording. EPOS exports
                        # name the column 'Sales'; older ones use 'Totals'.
                        csv_revenue_inc = self._epos_line_total(row)
                        csv_revenue = csv_revenue_inc / 1.2 if csv_revenue_inc is not None and csv_revenue_inc >= 0 else None
                        line_revenue = csv_revenue if csv_revenue is not None else quantity * sell_price
    
                        preview_items.append({
                            'item_id': item_id,
                            'name': item_row[COL_ITEM_NAME],
                            'qty': quantity,
                            'current': current_qty,
                            'projected': projected,
                            'cost': cost_price,
                            'sell': sell_price,
                            'csv_revenue': csv_revenue,
                            # Kept as the export stated it (not re-derived from
                            # the ex-VAT price) so the preview's inc-VAT total
                            # matches the CSV to the penny.
                            'revenue_inc': (csv_revenue_inc if csv_revenue_inc is not None
                                            else inc_vat(line_revenue)),
                            'revenue': line_revenue,
                            'cost_total': quantity * cost_price,
                            'member_qty': member_qty,
                            'non_member_qty': non_member_qty,
                            'has_parent': has_parent,
                            'track_stock': track_stock
                        })
                        total_revenue += line_revenue
                        total_cost += quantity * cost_price

                    except Exception as item_error:
                        skipped_items.append(f"{row.get('Product', 'Unknown')}: {item_error}")
                        # Only explain the line if it never reached the
                        # preview; an error after the append still counts as
                        # recorded and is covered by the residual row.
                        if len(preview_items) == preview_count:
                            error_product = str(row.get('Product', 'Unknown')).strip() or 'Unknown'
                            try:
                                error_amount = self._epos_line_total(row) or 0.0
                            except Exception:
                                error_amount = 0.0
                            unrecorded_lines.append({
                                'product': error_product,
                                'qty': 0,
                                'revenue_inc': error_amount,
                                'reason': f'Could not process this line: {item_error}',
                            })
    
                if not preview_items:
                    messagebox.showwarning("No Transactions", "No valid transactions found in the CSV file.")
                    return
    
                # Round each line to the penny so the previewed rows add up
                # exactly to the revenue and GP shown above them.
                for item, revenue, cost_total in zip(
                        preview_items,
                        allocate_money([p['revenue'] for p in preview_items]),
                        allocate_money([p['cost_total'] for p in preview_items])):
                    item['revenue'] = revenue
                    item['cost_total'] = cost_total
                total_revenue = sum_money(p['revenue'] for p in preview_items)
                total_cost = sum_money(p['cost_total'] for p in preview_items)
                reported_inc = sum_money(p['revenue_inc'] for p in preview_items)
                reconciliation = self._build_reconciliation(
                    file_total_inc, preview_items, unrecorded_lines)
                unrecorded_inc = reconciliation['unrecorded_inc']
                residual_inc = reconciliation['residual_inc']

                # Negative stock guard: block unless allow_negative is True
                blocking_negative = []
                warning_negative = []
                for p in preview_items:
                    if p['projected'] < 0 and not p['has_parent'] and p.get('track_stock', True):
                        allow_neg = bool(self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == p['item_id'], COL_ALLOW_NEGATIVE].values[0])
                        if allow_neg:
                            warning_negative.append(p)
                        else:
                            blocking_negative.append(p)
    
                if blocking_negative:
                    lines = []
                    for p in blocking_negative:
                        current_display = format_quantity_display(p['item_id'], p['current'])
                        projected_display = format_quantity_display(p['item_id'], p['projected'])
                        lines.append(f"{p['name']}: {current_display} → {projected_display} after {p['qty']:.1f} sales")
                    messagebox.showerror(
                        "Upload Blocked: Negative Stock",
                        "This upload would drive the following items negative:\n\n" +
                        "\n".join(lines) +
                        "\n\nTo allow negative stock for an item, edit it and enable 'Allow Negative Stock'."
                    )
                    return
    
                if warning_negative:
                    lines = []
                    for p in warning_negative:
                        current_display = format_quantity_display(p['item_id'], p['current'])
                        projected_display = format_quantity_display(p['item_id'], p['projected'])
                        lines.append(f"{p['name']}: {current_display} → {projected_display}")
                    if not messagebox.askyesno(
                        "WARNING: Negative Stock",
                        "This upload would drive the following items negative (they are set to allow negative stock):\n\n" +
                        "\n".join(lines) +
                        "\n\nAre you sure you want to continue?"
                    ):
                        return
    
                # Parent stock negative warning
                parent_issues = []
                for p in preview_items:
                    if p['has_parent']:
                        parent_ok, item_issues = check_apply_sale_to_parent(
                            p['item_id'], p['qty'], self.inventory_df,
                            COL_ITEM_ID, COL_QUANTITY, COL_ALLOW_NEGATIVE
                        )
                        if not parent_ok:
                            parent_issues.extend(item_issues)
                if parent_issues:
                    if not messagebox.askyesno(
                        "WARNING: Parent Stock Negative",
                        "This upload would cause parent stock to go negative:\n\n" +
                        "\n".join(parent_issues[:10]) +
                        (f"\n... and {len(parent_issues) - 10} more" if len(parent_issues) > 10 else "") +
                        "\n\nAre you sure you want to continue?"
                    ):
                        return
    
                # Show preview dialog
                dialog = tk.Toplevel(self.root)
                dialog.title("Upload Preview - Confirm Before Applying")
                dialog.geometry("900x600")
                self._fit_dialog(dialog, 900, 600)
    
                dialog.configure(bg=THEME_BG)
                tk.Label(dialog, text="SALES UPLOAD PREVIEW",
                         font=ui_theme.mono_font(8), fg=THEME_TEXT_MUTED,
                         bg=THEME_BG).pack(anchor='w', padx=18, pady=(16, 2))
                tk.Label(dialog, text=f"Period {date_range_str}",
                         font=ui_theme.display_font(16), fg=THEME_TEXT,
                         bg=THEME_BG).pack(anchor='w', padx=18)
    
                summary_frame = tk.Frame(dialog, bg=THEME_BG)
                summary_frame.pack(fill='x', padx=18, pady=(6, 12))
                tk.Label(summary_frame, text=f"{len(preview_items)} items  ·  GP £{total_revenue - total_cost:,.2f}  ·  {len(skipped_items)} skipped",
                        font=ui_theme.mono_font(9), fg=THEME_TEXT_MUTED,
                        bg=THEME_BG).pack(anchor='w')
                if abs(unrecorded_inc) < 0.005:
                    match_text = "matches the EPOS file total"
                else:
                    match_text = (f"£{unrecorded_inc:,.2f} in the file not "
                                  "recorded — see Mismatch Details")
                tk.Label(summary_frame,
                         text=(f"Recorded £{reported_inc:,.2f} inc VAT "
                               f"(£{total_revenue:,.2f} ex)  ·  "
                               f"EPOS file £{file_total_inc:,.2f} inc  ·  "
                               f"{match_text}"),
                         font=ui_theme.mono_font(9), fg=THEME_TEXT,
                         bg=THEME_BG).pack(anchor='w', pady=(3, 0))
                tree_frame = tk.Frame(dialog, bg=THEME_BG)
                tree_frame.pack(fill='both', expand=True, padx=18)
    
                tree = ttk.Treeview(tree_frame, columns=('name', 'qty', 'current', 'projected', 'revenue'), show='headings', height=15)
                tree.heading('name', text='Item', anchor='w')
                tree.heading('qty', text='Qty Sold', anchor='e')
                tree.heading('current', text='Current Stock', anchor='e')
                tree.heading('projected', text='After Upload', anchor='e')
                tree.heading('revenue', text='Revenue', anchor='e')
                tree.column('name', width=220, anchor='w')
                tree.column('qty', width=100, anchor='e')
                tree.column('current', width=110, anchor='e')
                tree.column('projected', width=110, anchor='e')
                tree.column('revenue', width=90, anchor='e')
                tree.tag_configure('alt', background=TBL_ROW_ALT,
                                   foreground=THEME_TEXT)
                tree.pack(side=tk.LEFT, fill='both', expand=True)
    
                sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
                sb.pack(side=tk.RIGHT, fill=tk.Y)
                tree.configure(yscrollcommand=sb.set)
                self._bind_treeview_mousewheel(tree)
    
                for index, p in enumerate(preview_items):
                    tag = ('negative' if (p['projected'] < 0
                                         and not p['has_parent']
                                         and p.get('track_stock', True))
                           else ('alt' if index % 2 else ''))
                    current_display = format_quantity_display(p['item_id'], p['current'])
                    projected_display = format_quantity_display(p['item_id'], p['projected'])
                    qty_display = format_quantity_display(p['item_id'], p['qty'])
                    tree.insert('', tk.END, tags=(tag,) if tag else (),
                                values=(p['name'], qty_display, current_display,
                                        projected_display, f"£{p['revenue']:.2f}"))
                tree.tag_configure('negative', foreground=ui_theme.THEME_DANGER)
    
                def confirm_upload():
                    dialog.destroy()
                    self._apply_sales_upload(preview_items, skipped_items, file_hash,
                                            filepath, date_range_str, len(sales_df),
                                            reconciliation)

                def cancel_upload():
                    dialog.destroy()
                    self._set_status("Upload cancelled. No changes were made.", 'info')

                tk.Frame(dialog, bg=THEME_BORDER, height=1).pack(
                    fill='x', padx=18, pady=(14, 0))
                btn_frame = tk.Frame(dialog, bg=THEME_BG)
                btn_frame.pack(fill='x', padx=18, pady=12)
                self.styled_button(btn_frame, "Confirm Upload", confirm_upload, width=15, variant='primary').pack(side=tk.LEFT, padx=10)
                self.styled_button(btn_frame, "Cancel", cancel_upload, width=15, variant='secondary').pack(side=tk.LEFT, padx=10)
                if unrecorded_lines or abs(residual_inc) >= 0.005:
                    self.styled_button(
                        btn_frame, "Mismatch Details",
                        lambda: self._show_sales_reconciliation(reconciliation),
                        width=18, variant='secondary').pack(side=tk.LEFT, padx=10)
    
            self._run_in_background(
                "Reading sales report…",
                lambda: self._read_sales_file(filepath),
                continue_upload,
                lambda exc: messagebox.showerror("Invalid CSV", str(exc)),
                title="Sales Upload",
            )
    
        except Exception as e:
            messagebox.showerror("Error", f"Failed to upload sales report: {e}")


    def _apply_sales_upload(self, preview_items, skipped_items, file_hash, filepath, date_range_str, total_row_count, reconciliation=None):
        """Apply the confirmed sales upload after preview."""
        try:
            # Create backup before applying
            from data_manager import create_backup
            backup_path = create_backup('before_sales_upload')
            if backup_path:
                print(f"Pre-upload backup created: {backup_path}")

            self.refresh_data()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            transactions = []
            recorded_revenue = 0.0
            applied_revenue_inc = []

            for p in preview_items:
                item_id = p['item_id']
                quantity = p['qty']
                cost_price = p['cost']
                sell_price = p['sell']
                member_qty = p['member_qty']
                non_member_qty = p['non_member_qty']

                parent_adjustments = []
                if not p.get('track_stock', True):
                    # Delisted item with no stock: revenue only, no movement.
                    pass
                elif has_parent_stock(item_id):
                    parent_ok, parent_issues = check_apply_sale_to_parent(
                        item_id, quantity, self.inventory_df,
                        COL_ITEM_ID, COL_QUANTITY, COL_ALLOW_NEGATIVE
                    )
                    if not parent_ok:
                        skipped_items.append(f"{p['name']} (parent stock: {'; '.join(parent_issues)})")
                        if reconciliation is not None:
                            reconciliation['lines'].append({
                                'product': p['name'],
                                'qty': quantity,
                                'revenue_inc': p.get('revenue_inc') or 0.0,
                                'reason': f"Not recorded because parent stock would go negative: {'; '.join(parent_issues)}",
                            })
                        continue
                    parent_adjustments = apply_sale_to_parent(
                        item_id, quantity, self.inventory_df,
                        COL_ITEM_ID, COL_QUANTITY
                    )
                else:
                    self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] -= quantity
    
                # Store the line's actual EPOS revenue as the effective sell price,
                # so reports match the source CSV (already ex-VAT and struck to
                # the penny when the preview was built). A line the EPOS exported
                # at zero (a comped drink) keeps that zero; only a line with no
                # revenue figure at all falls back to the shelf price.
                csv_revenue = p.get('revenue')
                effective_sell_price = self._effective_sell_price(
                    csv_revenue, quantity, sell_price)
    
                new_log_entry = pd.DataFrame([[item_id, ACTION_SALES, quantity, timestamp, cost_price, effective_sell_price, "", date_range_str, "", member_qty, non_member_qty]],
                                              columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON, COL_MEMBER_QTY, COL_NON_MEMBER_QTY])
                self.log_df = pd.concat([self.log_df, new_log_entry], ignore_index=True)
                recorded_revenue += float(csv_revenue or 0.0)
                applied_revenue_inc.append(float(p.get('revenue_inc') or inc_vat(csv_revenue or 0.0)))
    
                for parent_id, deduction, desc in parent_adjustments:
                    parent_row = self.inventory_df[self.inventory_df[COL_ITEM_ID] == parent_id].iloc[0]
                    parent_cost = parent_row[COL_COST_PRICE]
                    parent_sell = parent_row[COL_SELL_PRICE]
                    parent_log_entry = pd.DataFrame([[parent_id, ACTION_PARENT_STOCK_ADJ, deduction, timestamp, parent_cost, parent_sell, f"From {item_id}", date_range_str, "", 0, 0]],
                                                      columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON, COL_MEMBER_QTY, COL_NON_MEMBER_QTY])
                    self.log_df = pd.concat([self.log_df, parent_log_entry], ignore_index=True)

                transactions.append(f"{p['name']}: {quantity:.1f} units")

            # Recompute the reconciliation after the apply pass: a line can
            # still be dropped here if its parent stock check fails.
            if reconciliation is not None:
                reconciliation['reported_inc'] = sum_money(applied_revenue_inc)
                reconciliation['unrecorded_inc'] = round_money(
                    reconciliation['file_total_inc'] - reconciliation['reported_inc'])
                reconciliation['explained_inc'] = sum_money(
                    line['revenue_inc'] for line in reconciliation['lines'])
                reconciliation['residual_inc'] = round_money(
                    reconciliation['unrecorded_inc'] - reconciliation['explained_inc'])

            if self._persist():
                self.update_dashboard_stats()
                add_upload_hash(file_hash, os.path.basename(filepath), datetime.now().isoformat(), date_range_str, total_row_count, 'sales')
    
                success_msg = f"Sales report uploaded successfully!\n\nBackup created before upload.\n\n"
                if date_range_str:
                    success_msg += f"Period: {date_range_str}\n\n"
                success_msg += f"Transactions recorded: {len(transactions)}\n"
                success_msg += (f"Revenue: £{inc_vat(recorded_revenue):,.2f} inc VAT "
                                f"(£{round_money(recorded_revenue):,.2f} ex)\n\n")
                has_mismatch = (
                    reconciliation is not None
                    and abs(reconciliation['unrecorded_inc']) >= 0.005
                )
                if has_mismatch:
                    success_msg += (
                        f"EPOS file: £{reconciliation['file_total_inc']:,.2f} inc VAT  ·  "
                        f"£{reconciliation['unrecorded_inc']:,.2f} not recorded\n"
                        "A breakdown of every unrecorded line and why follows in the next window.\n\n"
                    )
                if skipped_items:
                    success_msg += f"Skipped items: {len(skipped_items)}\n"
                    if len(skipped_items) <= 10:
                        success_msg += "\n" + "\n".join(skipped_items)
                    else:
                        success_msg += "\n" + "\n".join(skipped_items[:10]) + f"\n... and {len(skipped_items) - 10} more"
                messagebox.showinfo("Success", success_msg)
                if has_mismatch:
                    self._show_sales_reconciliation(reconciliation)
            else:
                messagebox.showerror("Error", "Failed to save transactions.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to apply sales upload: {e}")


    def _show_sales_reconciliation(self, reconciliation):
        """Popup explaining any gap between the EPOS file total and revenue.

        Every line left out of the ledger is listed with its value and the
        reason it was left out, so a mismatch is never silent.
        """
        file_total = reconciliation['file_total_inc']
        recorded = reconciliation['reported_inc']
        unrecorded = reconciliation['unrecorded_inc']
        residual = reconciliation['residual_inc']
        lines = reconciliation['lines']

        dialog = tk.Toplevel(self.root)
        dialog.title("Revenue Reconciliation")
        dialog.geometry("880x480")
        self._fit_dialog(dialog, 880, 480)
        dialog.configure(bg=THEME_BG)

        tk.Label(dialog, text="REVENUE RECONCILIATION",
                 font=ui_theme.mono_font(8), fg=THEME_TEXT_MUTED,
                 bg=THEME_BG).pack(anchor='w', padx=18, pady=(16, 2))
        tk.Label(dialog, text="What the EPOS file shows vs what was recorded",
                 font=ui_theme.display_font(15), fg=THEME_TEXT,
                 bg=THEME_BG).pack(anchor='w', padx=18)
        tk.Label(dialog,
                 text=(f"EPOS file £{file_total:,.2f} inc VAT   ·   "
                       f"Recorded £{recorded:,.2f} inc VAT   ·   "
                       f"Not recorded £{unrecorded:,.2f}"),
                 font=ui_theme.mono_font(9), fg=THEME_TEXT,
                 bg=THEME_BG).pack(anchor='w', padx=18, pady=(6, 10))

        tree_frame = tk.Frame(dialog, bg=THEME_BG)
        tree_frame.pack(fill='both', expand=True, padx=18)

        tree = ttk.Treeview(tree_frame,
                            columns=('product', 'qty', 'amount', 'reason'),
                            show='headings', height=12)
        tree.heading('product', text='Line', anchor='w')
        tree.heading('qty', text='Qty', anchor='e')
        tree.heading('amount', text='Not recorded', anchor='e')
        tree.heading('reason', text='Why it is not revenue', anchor='w')
        tree.column('product', width=190, anchor='w')
        tree.column('qty', width=60, anchor='e')
        tree.column('amount', width=110, anchor='e')
        tree.column('reason', width=440, anchor='w')
        tree.tag_configure('alt', background=TBL_ROW_ALT, foreground=THEME_TEXT)
        tree.pack(side=tk.LEFT, fill='both', expand=True)

        sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=sb.set)
        self._bind_treeview_mousewheel(tree)

        shown = 0
        for line in lines:
            if abs(line['revenue_inc']) < 0.005:
                continue
            tree.insert('', tk.END,
                        tags=('alt',) if shown % 2 else (),
                        values=(line['product'],
                                f"{line['qty']:.1f}",
                                f"£{line['revenue_inc']:,.2f}",
                                line['reason']))
            shown += 1

        if abs(residual) >= 0.005:
            tree.insert('', tk.END,
                        values=('Unaccounted', '', f"£{residual:,.2f}",
                                'Rounding, or a line with no EPOS line total. '
                                'Check the upload log.'))
            shown += 1

        if shown == 0:
            tree.insert('', tk.END, values=(
                'None', '', '£0.00',
                'Every line in the EPOS file was recorded. The totals match.'))

        tk.Frame(dialog, bg=THEME_BORDER, height=1).pack(fill='x', padx=18,
                                                        pady=(12, 0))
        btn_frame = tk.Frame(dialog, bg=THEME_BG)
        btn_frame.pack(fill='x', padx=18, pady=12)
        self.styled_button(btn_frame, "Close", dialog.destroy, width=14,
                           variant='primary').pack(side=tk.RIGHT, padx=10)


    @staticmethod
    def _read_complimentary_file(filepath):
        """Read and validate a complimentary-sales CSV. Runs off the UI thread."""
        with open(filepath, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        try:
            comp_df = pd.read_csv(filepath, compression=None)
        except Exception as exc:
            raise ValueError(f"Could not read the report as a CSV: {exc}") from exc
        if comp_df.empty:
            raise ValueError("The report contains no rows.")
        comp_df.columns = [col.strip() for col in comp_df.columns]
        if 'Product' not in comp_df.columns:
            raise ValueError("Complimentary report must have a 'Product' column.")
        return file_hash, comp_df


    def upload_complimentary_report(self):
        """Upload and process complimentary transactions CSV with preview and backup."""
        try:
            filepath = filedialog.askopenfilename(
                title="Select Complimentary Report CSV",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")]
            )
            if not filepath:
                return
    
            start_date, end_date = self.parse_date_range_from_filename(filepath)
            date_range_str = ""
            if start_date and end_date:
                date_range_str = f"{start_date.strftime(DATE_FORMAT_DISPLAY)} - {end_date.strftime(DATE_FORMAT_DISPLAY)}"
    
            def continue_upload(loaded):
                file_hash, comp_df = loaded
                # Duplicate guard
                dup = is_duplicate_upload(file_hash, 'complimentary')
                if dup:
                    dup_info = f"Previously uploaded on {dup.get('timestamp', 'unknown')}\nFilename: {dup.get('filename', 'unknown')}"
                    response = messagebox.askyesnocancel(
                        "Duplicate Upload Detected",
                        f"This file appears to have been uploaded before.\n\n{dup_info}\n\n"
                        "Do you want to proceed?\n\n"
                        "Yes = Continue anyway\nNo = Skip (do not upload)\nCancel = Go back"
                    )
                    if response is None or response is False:
                        return
    
                qty_col = None
                for col in comp_df.columns:
                    if col.lower() == 'qty':
                        qty_col = col
                        break
                if not qty_col:
                    qty_col = 'Qty'
    
                self.refresh_data()
                preview_items = []
                skipped_items = []
                total_cost = 0
    
                for _, row in comp_df.iterrows():
                    try:
                        product_name = str(row['Product']).strip()
                        if not product_name or product_name.lower() == 'nan' or product_name.lower() == 'total':
                            continue
                        # Till-only in/out lines hold no stock and are ignored.
                        if is_ignored_epos_product(product_name):
                            continue

                        try:
                            quantity = float(row[qty_col]) if pd.notna(row[qty_col]) else 0
                        except:
                            quantity = 0
                        if quantity <= 0:
                            continue
    
                        normalized_id = normalize_product_name(product_name)
                        item_id = resolve_epos_item_id(normalized_id)
                        explicit_override = item_id != normalized_id
    
                        if item_id not in self.inventory_df[COL_ITEM_ID].values:
                            if explicit_override:
                                # Explicit EPOS mapping points to an item not in inventory; skip rather than guess.
                                skipped_items.append(product_name)
                                continue
                            match_found = False
                            for inv_id in self.inventory_df[COL_ITEM_ID].values:
                                inv_name = str(self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == inv_id, COL_ITEM_NAME].values[0]).lower()
                                if product_name.lower() in inv_name or inv_name in product_name.lower():
                                    item_id = inv_id
                                    match_found = True
                                    break
                            if not match_found:
                                skipped_items.append(product_name)
                                continue
    
                        if should_exclude(item_id) and not has_parent_stock(item_id) and item_id not in SALES_INCLUDED_EXCLUDED_ITEMS:
                            skipped_items.append(f"{product_name} (excluded)")
                            continue
    
                        item_row = self.inventory_df[self.inventory_df[COL_ITEM_ID] == item_id].iloc[0]
                        cost_price = get_effective_cost_price(item_id, self.inventory_df, COL_ITEM_ID, COL_COST_PRICE)
                        current_qty = item_row[COL_QUANTITY]
                        has_parent = has_parent_stock(item_id)
                        # A child item deducts from its parent, so its own
                        # stock does not move.
                        projected = current_qty if has_parent else current_qty - quantity

                        preview_items.append({
                            'item_id': item_id,
                            'name': item_row[COL_ITEM_NAME],
                            'qty': quantity,
                            'current': current_qty,
                            'projected': projected,
                            'cost': cost_price,
                            'cost_total': quantity * cost_price,
                            'has_parent': has_parent
                        })
                        total_cost += quantity * cost_price
    
                    except Exception as item_error:
                        skipped_items.append(f"{row.get('Product', 'Unknown')}: {item_error}")
    
                if not preview_items:
                    messagebox.showwarning("No Transactions", "No valid transactions found in the CSV file.")
                    return
    
                # Round each line so the previewed costs add up exactly to
                # the total cost shown above them.
                for item, cost_total in zip(
                        preview_items,
                        allocate_money([p['cost_total'] for p in preview_items])):
                    item['cost_total'] = cost_total
                total_cost = sum_money(p['cost_total'] for p in preview_items)

                # Negative stock warning
                negative_count = sum(
                    1 for p in preview_items
                    if p['projected'] < 0 and not p['has_parent']
                    and p.get('track_stock', True))
                pct_negative = (negative_count / len(preview_items)) * 100
                if pct_negative > 10:
                    if not messagebox.askyesno(
                        "WARNING: High Negative Stock",
                        f"This upload would cause {negative_count} items ({pct_negative:.0f}%) to go negative.\n\n"
                        "This usually means these complimentary items are already reflected in your stock counts.\n\n"
                        "Are you sure you want to continue?"
                    ):
                        return
    
                # Parent stock negative warning
                parent_issues = []
                for p in preview_items:
                    if p['has_parent']:
                        parent_ok, item_issues = check_apply_sale_to_parent(
                            p['item_id'], p['qty'], self.inventory_df,
                            COL_ITEM_ID, COL_QUANTITY, COL_ALLOW_NEGATIVE
                        )
                        if not parent_ok:
                            parent_issues.extend(item_issues)
                if parent_issues:
                    if not messagebox.askyesno(
                        "WARNING: Parent Stock Negative",
                        "This upload would cause parent stock to go negative:\n\n" +
                        "\n".join(parent_issues[:10]) +
                        (f"\n... and {len(parent_issues) - 10} more" if len(parent_issues) > 10 else "") +
                        "\n\nAre you sure you want to continue?"
                    ):
                        return
    
                # Show preview dialog
                dialog = tk.Toplevel(self.root)
                dialog.title("Upload Preview - Complimentary")
                dialog.geometry("900x600")
                self._fit_dialog(dialog, 900, 600)
    
                dialog.configure(bg=THEME_BG)
                tk.Label(dialog, text="COMPLIMENTARY UPLOAD PREVIEW",
                         font=ui_theme.mono_font(8), fg=THEME_TEXT_MUTED,
                         bg=THEME_BG).pack(anchor='w', padx=18, pady=(16, 2))
                tk.Label(dialog, text=f"Period {date_range_str}",
                         font=ui_theme.display_font(16), fg=THEME_TEXT,
                         bg=THEME_BG).pack(anchor='w', padx=18)
    
                summary_frame = tk.Frame(dialog, bg=THEME_BG)
                summary_frame.pack(fill='x', padx=18, pady=(6, 12))
                tk.Label(summary_frame, text=f"{len(preview_items)} items  ·  Total cost £{total_cost:,.2f}  ·  {len(skipped_items)} skipped",
                         font=ui_theme.mono_font(9), fg=THEME_TEXT_MUTED,
                         bg=THEME_BG).pack(anchor='w')
    
                tree_frame = tk.Frame(dialog, bg=THEME_BG)
                tree_frame.pack(fill='both', expand=True, padx=18)
    
                tree = ttk.Treeview(tree_frame, columns=('name', 'qty', 'current', 'projected', 'cost'), show='headings', height=15)
                tree.heading('name', text='Item', anchor='w')
                tree.heading('qty', text='Qty', anchor='e')
                tree.heading('current', text='Current Stock', anchor='e')
                tree.heading('projected', text='After Upload', anchor='e')
                tree.heading('cost', text='Cost Impact', anchor='e')
                tree.column('name', width=250, anchor='w')
                tree.column('qty', width=80, anchor='e')
                tree.column('current', width=100, anchor='e')
                tree.column('projected', width=100, anchor='e')
                tree.column('cost', width=100, anchor='e')
                tree.tag_configure('alt', background=TBL_ROW_ALT,
                                   foreground=THEME_TEXT)
                tree.pack(side=tk.LEFT, fill='both', expand=True)
    
                sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
                sb.pack(side=tk.RIGHT, fill=tk.Y)
                tree.configure(yscrollcommand=sb.set)
                self._bind_treeview_mousewheel(tree)
    
                for index, p in enumerate(preview_items):
                    tag = ('negative' if (p['projected'] < 0
                                         and not p['has_parent']
                                         and p.get('track_stock', True))
                           else ('alt' if index % 2 else ''))
                    tree.insert('', tk.END, tags=(tag,) if tag else (),
                                values=(p['name'], f"{p['qty']:.1f}", f"{p['current']:.1f}",
                                        f"{p['projected']:.1f}", f"£{p['cost_total']:.2f}"))
                tree.tag_configure('negative', foreground=ui_theme.THEME_DANGER)
    
                def confirm_upload():
                    dialog.destroy()
                    self._apply_complimentary_upload(preview_items, skipped_items, file_hash, filepath, date_range_str, len(comp_df))
    
                def cancel_upload():
                    dialog.destroy()
                    self._set_status("Upload cancelled. No changes were made.", 'info')
    
                tk.Frame(dialog, bg=THEME_BORDER, height=1).pack(
                    fill='x', padx=18, pady=(14, 0))
                btn_frame = tk.Frame(dialog, bg=THEME_BG)
                btn_frame.pack(fill='x', padx=18, pady=12)
                self.styled_button(btn_frame, "Confirm Upload", confirm_upload, width=15, variant='primary').pack(side=tk.LEFT, padx=10)
                self.styled_button(btn_frame, "Cancel", cancel_upload, width=15, variant='secondary').pack(side=tk.LEFT, padx=10)
            self._run_in_background(
                "Reading complimentary report…",
                lambda: self._read_complimentary_file(filepath),
                continue_upload,
                lambda exc: messagebox.showerror("Invalid CSV", str(exc)),
                title="Complimentary Upload",
            )
    
        except Exception as e:
            messagebox.showerror("Error", f"Failed to upload complimentary report: {e}")


    def _apply_complimentary_upload(self, preview_items, skipped_items, file_hash, filepath, date_range_str, total_row_count):
        """Apply the confirmed complimentary upload after preview."""
        try:
            from data_manager import create_backup
            backup_path = create_backup('before_complimentary_upload')
            if backup_path:
                print(f"Pre-upload backup created: {backup_path}")
    
            self.refresh_data()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            transactions = []
    
            for p in preview_items:
                item_id = p['item_id']
                quantity = p['qty']
                cost_price = p['cost']
    
                parent_adjustments = []
                if not p.get('track_stock', True):
                    # Delisted item with no stock: revenue only, no movement.
                    pass
                elif has_parent_stock(item_id):
                    parent_ok, parent_issues = check_apply_sale_to_parent(
                        item_id, quantity, self.inventory_df,
                        COL_ITEM_ID, COL_QUANTITY, COL_ALLOW_NEGATIVE
                    )
                    if not parent_ok:
                        skipped_items.append(f"{p['name']} (parent stock: {'; '.join(parent_issues)})")
                        continue
                    parent_adjustments = apply_sale_to_parent(
                        item_id, quantity, self.inventory_df,
                        COL_ITEM_ID, COL_QUANTITY
                    )
                else:
                    self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] -= quantity
    
                new_log_entry = pd.DataFrame([[item_id, ACTION_COMPLIMENTARY, quantity, timestamp, cost_price, 0.0, "", date_range_str, "CSV Upload"]],
                                              columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON])
                self.log_df = pd.concat([self.log_df, new_log_entry], ignore_index=True)
    
                for parent_id, deduction, desc in parent_adjustments:
                    parent_row = self.inventory_df[self.inventory_df[COL_ITEM_ID] == parent_id].iloc[0]
                    parent_cost = parent_row[COL_COST_PRICE]
                    parent_log_entry = pd.DataFrame([[parent_id, ACTION_PARENT_STOCK_ADJ, deduction, timestamp, parent_cost, 0.0, f"From {item_id}", date_range_str, "CSV Upload", 0, 0]],
                                                      columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON, COL_MEMBER_QTY, COL_NON_MEMBER_QTY])
                    self.log_df = pd.concat([self.log_df, parent_log_entry], ignore_index=True)
    
                transactions.append(f"{p['name']}: {quantity:.1f} units")
    
            if self._persist():
                self.update_dashboard_stats()
                add_upload_hash(file_hash, os.path.basename(filepath), datetime.now().isoformat(), date_range_str, total_row_count, 'complimentary')
    
                success_msg = f"Complimentary report uploaded successfully!\n\nBackup created before upload.\n\n"
                if date_range_str:
                    success_msg += f"Period: {date_range_str}\n\n"
                success_msg += f"Transactions recorded: {len(transactions)}\n\n"
                if skipped_items:
                    success_msg += f"Skipped items: {len(skipped_items)}\n"
                    if len(skipped_items) <= 10:
                        success_msg += "\n" + "\n".join(skipped_items)
                    else:
                        success_msg += "\n" + "\n".join(skipped_items[:10]) + f"\n... and {len(skipped_items) - 10} more"
    
                messagebox.showinfo("Success", success_msg)
                self.show_dashboard()
            else:
                messagebox.showerror("Error", "Failed to save transactions.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to apply complimentary upload: {e}")


    def _parse_booker_invoice_line(self, line):
        """Parse a single Booker invoice line into (description, invoice_qty, case_size, unit_price_ex, vat_code).
    
        The unit price token is the case/unit price **excluding VAT**.
        The VAT code is normally three tokens after the unit price (A = VAT exempt, B = 20% VAT).
        Returns None if the line does not look like a product row.
        """
        if any(k in line for k in ['Order No:', 'Customer:', 'VAT No:', 'BOOKER', 'Page', 'Sub Total', 'Total', 'VAT']):
            return None
        tokens = line.split()
        if len(tokens) < 5:
            return None
    
        # First price-like decimal after the product code is the case/unit price (ex VAT)
        price_idx = None
        unit_price = None
        for i in range(2, len(tokens)):
            tok = tokens[i].replace('£', '').replace(',', '')
            if re.match(r'^-?\d+\.\d{2,}$', tok):
                price_idx = i
                unit_price = float(tok)
                break
        if price_idx is None:
            return None
    
        if not re.match(r'^-?\d+$', tokens[price_idx - 1]):
            return None
        invoice_qty = int(tokens[price_idx - 1])
    
        case_size = 1
        product_end = price_idx - 1
        if price_idx - 2 >= 1:
            unit_token = tokens[price_idx - 2]
            if re.match(r'^\d+(?:\.\d+)?(?:ml|cl|ltr|l|g|s)?$', unit_token, re.I) or 'x' in unit_token.lower():
                product_end = price_idx - 2
                if price_idx - 3 >= 1 and re.match(r'^\d+$', tokens[price_idx - 3]):
                    case_size = int(tokens[price_idx - 3])
                    product_end = price_idx - 3
    
        # Keep the case/unit info in the description so downstream unit matching works
        full_description = ' '.join(tokens[1:price_idx - 1])
        if any(k in full_description.lower() for k in ['out of stock', 'delisted', 'substitute', 'alternative', 'credit', 'charge', 'delivery', 'refund']):
            return None
    
        # VAT code is typically the token after total-value and a marker, e.g. "... 10.50 TC 21.00 B 1.49 64.8%"
        vat_code = 'B'
        if price_idx + 3 < len(tokens):
            candidate = tokens[price_idx + 3].upper()
            if candidate in ('A', 'B'):
                vat_code = candidate
    
        return full_description, invoice_qty, case_size, unit_price, vat_code


    @staticmethod
    def _invoice_price_ex_vat(unit_price_ex: float, vat_code: str) -> float:
        """Return the ex-VAT invoice price.
    
        The system now stores all prices ex-VAT, so no VAT multiplier is applied.
        VAT-exempt items (code A) are returned unchanged; standard items (code B)
        are already excluding VAT in the invoice extract.
        """
        return unit_price_ex


    def _units_per_case_from_desc(self, desc, case_size):
        """Infer actual stock units in a case from a Booker description."""
        d = desc.lower()
        # e.g. "6 4x330ml" -> 6 packs of 4 bottles = 24 units
        m = re.search(r'(\d+)\s*x\s*\d+(?:ml|cl|ltr|l|g|s)\b', d)
        if m:
            return case_size * int(m.group(1))
        # e.g. "32 s" (singles) - usually case_size already equals units
        m = re.search(r'(\d+)\s*s\b', d)
        if m:
            return int(m.group(1))
        return case_size


    def _get_invoice_to_item_mapping(self):
        """Return mapping from Booker invoice description to stock item_id."""
        return {
            'britvic lime cordial': 'cordial',
            'tetley tea bags 1100s': 'tea',
            'walkers crisp cheese & onion': 'walkers',
            'walkers crisps ready salted': 'walkers',
            'walkers prawn cocktail 32.5g': 'walkers',
            'walkers salt & vinegar 32.5g': 'walkers',
            'kp dry roasted peanut p card 21 50g': 'nuts',
            'kp original saltd pnut card 21 50g': 'nuts',
            'sunpride orange juice 12 1ltr': 'carton_juice',
            'apple juice': 'carton_juice',
            'orange juice': 'carton_juice',
            'cranberry juice': 'carton_juice',
            'pineapple juice': 'carton_juice',
            'pringles bbq': 'pringles',
            'pringles original': 'pringles',
            'pringles salt & vinegar': 'pringles',
            'pringles sour cream & onion': 'pringles',
            'coca cola can': 'can',
            'diet coke can': 'can',
            'sprite can': 'can',
            'tango orange can': 'can',
            'irn bru': 'can',
            'irn bru sugar free': 'can',
            'old jamaica ginger beer': 'can',
            'coke zero': 'can',
            'fanta lemon': 'can',
            'red bull': 'red_bull',
            'red bull energy drink pm175': 'red_bull',
            'corona extra nrb 4.5%': 'corona',
            'peroni nastro azzurro': 'peroni',
            'budweiser': 'budweiser',
            'magners irish cider nrb': 'magners',
            'inchs medium apple cider': 'inchs',
            'kopparberg mixed fruit cider': 'kopparberg',
            'kopparberg strbry&lime cider': 'kopparberg',
            'kopparberg 0% mixed fruit': 'a_f_koppaberg',
            'kopparberg non alcohol s/bry': 'a_f_koppaberg',
            'old mout pineapple & r/berry': 'old_mout_cider',
            'gordons gin': 'gordons_gin',
            'gordons pink gin 35%': 'gordons_pink_gin',
            'smirnoff red': 'smirnoff',
            'jack daniels': 'jack_daniels',
            'bombay sapphire': 'bombay_sapphire',
            'disaronno': 'disaronno',
            'antica sambuca classic': 'sambuca',
            'malibu 18%': 'malibu',
            'sierra tequila blanco 35%': 'tequila',
            'havana club 7 year old rum': 'havana_club_7',
            'archers peach schnapps': 'peach_schnapps',
            'old pulteney 12yo m/whisky': 'old_pulteney',
            'bowmore 12yo sgl malt': 'bowmore',
            'glenmorangie 12yo malt': 'glenmorangie',
            'martell vs cognac': 'martell',
            'brockmans gin': 'brockmans_gin',
            'kraken spiced rum 70cl': 'kraken_rum',
            'bacardi carta blanca': 'bacardi',
            'cointreau': 'Cointreau',
            'dead mans fingers spiced rum': 'dead_mans_fingers',
            'fever tree prem indian tonic': 'tonic',
            'f/tree refreshingly lghttnic': 'tonic',
            'fever tree r/l ginger ale': 'tonic',
            'fever tree r/l mediterranean': 'tonic',
            'fever tree light tonic': 'fevertree_sl_tonic',
            'glen scotia dbl csk sgl malt': 'glen_scotia',
            'highland spring water stillpet': 'soda_water',
            'h/land spring water stillpet': 'soda_water',
            'j20 apple & mango': 'j2o',
            'j20 orange & passionfruit': 'j2o',
            'prosecco spumante doc ex dry': 'prosecco',
            'prosecco spumante': 'prosecco',
            'schweppes lemonade bag inbox': 'lemonade',
            'schweppes lemonade bag in box': 'lemonade',
            'cockburns port spec reserve': 'port',
            'coca cola original bib': 'coke_pm',
            'diet coke bag in box': 'diet_coke_pm',
            'birra moretti 0%': 'birra_moretti_zero',
            'birra moretti nrb uk': 'Moretti_Bottle',
            'estrella damm': 'estrella_damm',
            'aperol': 'aperol',
            'baileys irish cream': 'baileys_50ml',
            'captain morgan spiced rum': 'morgans',
            'highland park 12yo malt': 'highland_park',
            'jura 12yr': 'jura_origin',
            'kahlua coffee liqueur': 'kahlua',
            'tanqueray sevilla': 'tanqueray_sevilla',
            'magners 4x500ml': 'magners',
            # Booker draught kegs
            'poretti': 'poretti',
            'innis and gunn': 'innis_and_gunn',
            'innis & gunn': 'innis_and_gunn',
            'innis gunn': 'innis_and_gunn',
            'orchard pig': 'orchard_pig',
            'guinness keg': 'guinness',
            'guinness draught': 'guinness',
            'caledonian best': 'caledonian_best',
    
            # Cart/snack aliases where Booker descriptions omit punctuation.
            'cart roll tea coffee': 'cart_roll_tea_coffee',
        }


    def _invoice_unit_matches_conversion(self, desc, input_unit):
        """Heuristic: does the invoice description use the conversion input unit?"""
        d = desc.lower()
        if input_unit == 'bottle':
            return any(k in d for k in ['bottle', 'ltr', 'cl', 'ml', '75cl', '70cl', '1.5ltr'])
        if input_unit == 'box':
            return any(k in d for k in ['bag in box', 'bib', 'box', '7ltr'])
        if input_unit == 'barrel':
            return any(k in d for k in ['barrel', 'keg', 'firkin'])
        if input_unit == 'carton':
            return any(k in d for k in ['carton'])
        return False


    def _map_invoice_description_to_item_id(self, desc, inventory_ids):
        """Map an invoice description to a stock item_id, or None if unmapped."""
        desc_lower = desc.lower().strip()
        mapping = self._get_invoice_to_item_mapping()
        for key in sorted(mapping.keys(), key=len, reverse=True):
            if desc_lower.startswith(key) or key in desc_lower:
                return mapping[key]
        if desc_lower in inventory_ids:
            return desc_lower
        return None


    def _is_can_average_description(self, desc: str) -> bool:
        """Return True if this invoice description is part of the mixed can/bottle average group."""
        desc_lower = desc.lower().strip()
        return any(desc_lower.startswith(key) or key in desc_lower for key in self.CAN_AVERAGE_GROUP)


    def _is_carton_juice_average_description(self, desc: str) -> bool:
        """Return True if this invoice description is part of the carton juice average group."""
        desc_lower = desc.lower().strip()
        return any(desc_lower.startswith(key) or key in desc_lower for key in self.CARTON_JUICE_AVERAGE_GROUP)


    def _compute_can_average_cost(self, aggregated: dict, invoice_lines: list) -> tuple[float, int]:
        """Compute weighted-average ex-VAT per-unit cost from the mixed can/bottle group.
    
        Returns (average_cost_per_unit, total_units).
        """
        total_ex_value = 0.0
        total_units = 0
        for desc, qty, case_size, price, vat_code in invoice_lines:
            if not self._is_can_average_description(desc):
                continue
            upc = self._units_per_case_from_desc(desc, case_size)
            total_units += qty * upc
            total_ex_value += qty * self._invoice_price_ex_vat(price, vat_code)
        if total_units == 0:
            return 0.0, 0
        return total_ex_value / total_units, total_units


    def _compute_carton_juice_average_cost(self, aggregated: dict, invoice_lines: list) -> tuple[float, int]:
        """Compute weighted-average ex-VAT per-pint cost from mixed carton juices.
    
        Invoice lines are priced per litre; the stock system tracks carton_juice in
        pints, so the result is converted from £/litre to £/pint.
    
        Returns (average_cost_per_pint, total_litres).
        """
        from conversions import PINTS_PER_LITRE
        total_ex_value = 0.0
        total_litres = 0
        for desc, qty, case_size, price, vat_code in invoice_lines:
            if not self._is_carton_juice_average_description(desc):
                continue
            upc = self._units_per_case_from_desc(desc, case_size)
            total_litres += qty * upc
            total_ex_value += qty * self._invoice_price_ex_vat(price, vat_code)
        if total_litres == 0:
            return 0.0, 0
        per_litre = total_ex_value / total_litres
        per_pint = per_litre / PINTS_PER_LITRE
        return per_pint, total_litres


    def upload_delivery_invoice_price_check(self):
        """Upload Booker invoice PDFs and compare prices to current system costs."""
        if not PDFPLUMBER_AVAILABLE:
            messagebox.showerror("Error", "pdfplumber is not installed. Cannot read invoice PDFs.")
            return
    
        filepaths = filedialog.askopenfilenames(
            title="Select Booker Invoice PDFs (multi-select supported)",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")]
        )
        if not filepaths:
            return
    
        try:
            self.refresh_data()
    
            def extract_invoice_lines():
                extracted = []
                for path in filepaths:
                    with pdfplumber.open(path) as pdf:
                        for page in pdf.pages:
                            text = page.extract_text()
                            if not text:
                                continue
                            for line in text.split('\n'):
                                parsed = self._parse_booker_invoice_line(line)
                                if parsed:
                                    extracted.append(parsed)
                return extracted
    
            def continue_check(invoice_lines):
                if not invoice_lines:
                    messagebox.showinfo("No Products Found", "Could not extract any product lines from the PDFs.")
                    return
                # Aggregate duplicate descriptions by quantity, keep latest price and case size
                aggregated = defaultdict(lambda: {'qty': 0, 'price': 0.0, 'case_size': 1, 'vat_code': 'B'})
                for desc, qty, case_size, price, vat_code in invoice_lines:
                    key = desc.lower().strip()
                    aggregated[key]['qty'] += qty
                    aggregated[key]['price'] = price  # latest ex-VAT price wins
                    aggregated[key]['case_size'] = case_size
                    aggregated[key]['vat_code'] = vat_code
    
                inventory_ids = {str(i).lower().strip() for i in self.inventory_df[COL_ITEM_ID].values}
                # Case-insensitive lookups so legacy IDs like Cointreau/Moretti_Bottle resolve correctly.
                cost_by_id = {str(k).lower(): v for k, v in zip(self.inventory_df[COL_ITEM_ID], self.inventory_df[COL_COST_PRICE])}
                name_by_id = {str(k).lower(): v for k, v in zip(self.inventory_df[COL_ITEM_ID], self.inventory_df[COL_ITEM_NAME])}
                measure_by_id = {str(k).lower(): v for k, v in zip(self.inventory_df[COL_ITEM_ID], self.inventory_df[COL_MEASURE])}
    
                comparison_rows = []
                unmatched = []
                can_group_seen = False
                carton_juice_group_seen = False
                for desc, data in aggregated.items():
                    item_id = self._map_invoice_description_to_item_id(desc, inventory_ids)
                    if item_id is None:
                        # Skip non-beverage/cleaning/refuse lines
                        skip_keywords = ['refuse', 'sack', 'bleach', 'floor gel', 'sachet', 'mayonnaise',
                                         'hp sauce', 'clean pro', 'lichfield', 'neapolitan', 'surface',
                                         'surger', 'cp ', 'es citrus']
                        if any(k in desc for k in skip_keywords):
                            continue
                        unmatched.append(desc)
                        continue
    
                    # Fold all can-group lines into a single synthetic Can row
                    if self._is_can_average_description(desc):
                        if can_group_seen:
                            continue
                        can_group_seen = True
                        invoice_per_unit, total_cans = self._compute_can_average_cost(aggregated, invoice_lines)
                        if total_cans == 0:
                            continue
                        item_id = 'can'
                        invoice_unit = 'can'
                        invoice_desc = (
                            f"Weighted average across {total_cans} units "
                            "(Can/J20 mix)"
                        )
                    # Fold all carton-juice lines into a single synthetic Carton Juice row
                    elif self._is_carton_juice_average_description(desc):
                        if carton_juice_group_seen:
                            continue
                        carton_juice_group_seen = True
                        invoice_per_unit, total_litres = self._compute_carton_juice_average_cost(aggregated, invoice_lines)
                        if total_litres == 0:
                            continue
                        item_id = 'carton_juice'
                        invoice_unit = 'pint'
                        invoice_desc = (
                            f"Weighted average across {total_litres:.0f} litres "
                            "(Apple/Orange/Cranberry/Pineapple mix, converted to £/pint)"
                        )
                    else:
                        measure = measure_by_id.get(item_id.lower(), '')
                        invoice_unit = measure or 'unit'
                        upc = self._units_per_case_from_desc(desc, data['case_size'])
                        case_ex = self._invoice_price_ex_vat(data['price'], data['vat_code'])
    
                        conv = get_conversion(item_id)
                        if conv and self._invoice_unit_matches_conversion(desc, conv[0]):
                            input_unit, factor, output_unit = conv
                            invoice_per_unit = (case_ex / upc) / factor
                            invoice_unit = output_unit
                        else:
                            invoice_per_unit = case_ex / upc
                            if conv and not self._invoice_unit_matches_conversion(desc, conv[0]):
                                invoice_unit = f"case/{upc}"
                        invoice_desc = desc
    
                    current_cost = cost_by_id.get(item_id.lower(), 0.0)
                    diff = invoice_per_unit - current_cost
                    diff_pct = (diff / current_cost * 100) if current_cost > 0 else 0.0
    
                    comparison_rows.append({
                        'item_id': item_id,
                        'item_name': name_by_id.get(item_id.lower(), item_id),
                        'invoice_desc': invoice_desc,
                        'measure': measure_by_id.get(item_id.lower(), ''),
                        'invoice_unit': invoice_unit,
                        'current_cost': current_cost,
                        'invoice_cost': invoice_per_unit,
                        'diff': diff,
                        'diff_pct': diff_pct,
                    })
    
                if not comparison_rows and not unmatched:
                    messagebox.showinfo("No Products Found", "No recognisable Booker products found in the invoices.")
                    return
    
                filename_summary = f"{len(filepaths)} invoice(s): " + ", ".join(os.path.basename(f) for f in filepaths[:3])
                if len(filepaths) > 3:
                    filename_summary += "..."
                self._show_invoice_price_check_results(comparison_rows, unmatched, filename_summary)
    
            def handle(invoice_lines):
                try:
                    continue_check(invoice_lines)
                except Exception as exc:
                    messagebox.showerror("Error", f"Failed to process invoice PDF: {exc}")
    
            self._run_in_background(
                "Reading invoice PDFs…",
                extract_invoice_lines,
                handle,
                lambda exc: messagebox.showerror("Error", f"Failed to process invoice PDF: {exc}"),
                title="Invoice Price Check",
            )
    
        except Exception as e:
            messagebox.showerror("Error", f"Failed to process invoice PDF: {e}")


    def _show_invoice_price_check_results(self, comparison_rows, unmatched, filename):
        """Show the invoice price-check comparison in a modal dialog."""
        top = tk.Toplevel(self.root)
        top.title(f"Invoice Price Check - {filename}")
        top.transient(self.root)
        top.grab_set()
        top.lift()
        top.attributes('-topmost', True)
        top.after_idle(lambda: top.attributes('-topmost', False))
    
        top.update_idletasks()
        width, height = 1050, 650
        x = (top.winfo_screenwidth() - width) // 2
        y = (top.winfo_screenheight() - height) // 2
        top.geometry(f"{width}x{height}+{x}+{y}")
        top.minsize(width, height)
    
        frame = tk.Frame(top, bg=THEME_BG)
        frame.pack(fill='both', expand=True, padx=15, pady=15)
    
        tk.Label(frame, text="INVOICE PRICE CHECK", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w').pack(fill='x')
        tk.Label(frame, text=filename, font=ui_theme.display_font(17),
                 fg=THEME_TEXT, bg=THEME_BG, anchor='w').pack(fill='x', pady=(2, 4))
    
        summary_text = (f"{len(comparison_rows)} matched items  ·  "
                        f"{len(unmatched)} unmatched lines")
        tk.Label(frame, text=summary_text,
                 font=ui_theme.mono_font(9), fg=THEME_TEXT_MUTED, bg=THEME_BG,
                 anchor='w').pack(fill='x', pady=(0, 12))
    
        tree_frame = tk.Frame(frame, bg=THEME_BG)
        tree_frame.pack(fill='both', expand=True)
    
        columns = ('invoice_desc', 'item_id', 'item_name', 'measure', 'invoice_unit', 'current_cost', 'invoice_cost', 'diff', 'diff_pct')
        tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=16)
        tree.heading('invoice_desc', text='Invoice Product', anchor='w')
        tree.heading('item_id', text='Item ID', anchor='w')
        tree.heading('item_name', text='Name', anchor='w')
        tree.heading('measure', text='System Unit', anchor='w')
        tree.heading('invoice_unit', text='Invoice Unit', anchor='w')
        tree.heading('current_cost', text='Current Cost', anchor='e')
        tree.heading('invoice_cost', text='Invoice Cost', anchor='e')
        tree.heading('diff', text='Difference', anchor='e')
        tree.heading('diff_pct', text='Diff %', anchor='e')
        self._make_sortable(tree)
    
        tree.column('invoice_desc', width=180, anchor='w')
        tree.column('item_id', width=90, anchor='w')
        tree.column('item_name', width=110, anchor='w')
        tree.column('measure', width=70, anchor='w')
        tree.column('invoice_unit', width=80, anchor='w')
        tree.column('current_cost', width=100, anchor='e')
        tree.column('invoice_cost', width=100, anchor='e')
        tree.column('diff', width=90, anchor='e')
        tree.column('diff_pct', width=70, anchor='e')
        tree.tag_configure('alt', background=TBL_ROW_ALT,
                           foreground=THEME_TEXT)
    
        tree.tag_configure('higher', foreground=THEME_DANGER)
        tree.tag_configure('lower', foreground=THEME_SUCCESS)
        tree.tag_configure('neutral', foreground=THEME_TEXT)
    
        for index, row in enumerate(sorted(comparison_rows, key=lambda r: abs(r['diff_pct']), reverse=True)):
            if row['diff_pct'] > 10:
                tag = 'higher'
            elif row['diff_pct'] < -10:
                tag = 'lower'
            else:
                tag = 'alt' if index % 2 else 'neutral'
            values = (
                row['invoice_desc'] or '-',
                row['item_id'],
                row['item_name'],
                row['measure'] or '-',
                row['invoice_unit'] or '-',
                f"£{row['current_cost']:.4f}",
                f"£{row['invoice_cost']:.4f}",
                f"£{row['diff']:+.4f}",
                f"{row['diff_pct']:+.1f}%",
            )
            tree.insert('', tk.END, values=values, tags=(tag,))
    
        tree.pack(side=tk.LEFT, fill='both', expand=True)
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill='y')
        tree.configure(yscrollcommand=scrollbar.set)
    
        if unmatched:
            tk.Label(frame, text="UNMATCHED INVOICE LINES", font=ui_theme.mono_font(8),
                     fg=THEME_WARNING, bg=THEME_BG, anchor='w').pack(fill='x', pady=(12, 4))
            unmatched_text = tk.Text(frame, height=4, wrap='word', bg=THEME_CARD, fg=THEME_TEXT,
                                     font=ui_theme.mono_font(9), relief='flat',
                                     highlightbackground=THEME_BORDER,
                                     highlightthickness=1, padx=10, pady=8)
            unmatched_text.pack(fill='x')
            unmatched_text.insert('1.0', "\n".join(f"  • {u}" for u in sorted(unmatched)))
            unmatched_text.config(state='disabled')
    
        btn_frame = tk.Frame(frame, bg=THEME_BG)
        btn_frame.pack(fill='x', pady=(15, 0))
    
        def apply_invoice_prices():
            if not comparison_rows:
                return
            if not messagebox.askyesno(
                "Confirm Apply",
                f"Update {len(comparison_rows)} item cost prices from these invoices?\n\n"
                "This will overwrite current costs and update Items.csv total values.",
                parent=top,
            ):
                return
            try:
                result = self._apply_invoice_cost_updates(comparison_rows)
                msg = f"Invoice prices applied to {result['updated']} item(s)."
                if result['unchanged']:
                    msg += f"\nAlready up to date: {result['unchanged']} item(s)."
                if result['locked']:
                    msg += (f"\n\nSkipped {len(result['locked'])} price-locked item(s); "
                            "their costs were left unchanged:")
                    for locked in result['locked'][:10]:
                        msg += (f"\n  • {locked['item_name']} "
                                f"(£{locked['current_cost']:.4f} → £{locked['invoice_cost']:.4f})")
                    if len(result['locked']) > 10:
                        msg += f"\n  …and {len(result['locked']) - 10} more"
                    msg += "\n\nUnlock the item to accept invoice prices for it."
                messagebox.showinfo("Invoice Prices", msg, parent=top)
                top.destroy()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to apply invoice prices: {e}", parent=top)
    
        self.styled_button(btn_frame, "Apply Invoice Prices to Stock", apply_invoice_prices,
                           width=26, variant='secondary').pack(side='left')
        self.styled_button(btn_frame, "Close", top.destroy, width=16, variant='primary').pack(side='right')


    def _apply_invoice_cost_updates(self, comparison_rows):
        """Persist invoice-derived cost prices into SQLite, CSVs, and log history."""
        from inventory_sync import update_items_csv_total_value
        from datetime import datetime
    
        self.refresh_data()
        timestamp = datetime.now().strftime(f"%Y-%m-%d %H:%M:%S")
        supplier = getattr(self, 'current_delivery_supplier', 'Booker')
    
        # Case-insensitive lookup because invoice mappings may return lowercase
        # item_ids while the database stores the original casing (e.g. 'Cointreau').
        id_lookup = {str(i).lower(): str(i) for i in self.inventory_df[COL_ITEM_ID].values}
    
        log_entries = []
        updated_items = []
        locked_skipped = []
        unchanged_count = 0
    
        for row in comparison_rows:
            item_id = id_lookup.get(str(row['item_id']).lower(), row['item_id'])
            new_cost = row['invoice_cost']
            item_rows = self.inventory_df[self.inventory_df[COL_ITEM_ID] == item_id]
            if item_rows.empty:
                continue
            item_idx = item_rows.index[0]
            old_cost = float(self.inventory_df.at[item_idx, COL_COST_PRICE])
            is_locked = bool(self.inventory_df.at[item_idx, COL_PRICE_LOCKED])
            if is_locked:
                # Respect locked prices, same as manual deliveries, but report
                # the skip instead of quietly treating the upload as complete.
                locked_skipped.append({
                    'item_id': item_id,
                    'item_name': str(self.inventory_df.at[item_idx, COL_ITEM_NAME]),
                    'current_cost': old_cost,
                    'invoice_cost': float(new_cost),
                })
                continue
    
            if abs(old_cost - new_cost) < 0.0001:
                unchanged_count += 1
                continue
    
            self.inventory_df.at[item_idx, COL_COST_PRICE] = new_cost
            sell_price = float(self.inventory_df.at[item_idx, COL_SELL_PRICE])
            # A price update is not a delivery: a zero-quantity Delivery row
            # polluted delivery history and any report that groups by action,
            # so give it its own action.
            log_entries.append([item_id, ACTION_PRICE_UPDATE, 0.0, timestamp, new_cost, sell_price, supplier, "", "Invoice price update"])
            updated_items.append(item_id)
    
        if log_entries:
            new_log_df = pd.DataFrame(
                log_entries,
                columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON]
            )
            self.log_df = pd.concat([self.log_df, new_log_df], ignore_index=True)
    
        if updated_items:
            # Costs and their audit rows must land together: a cost change with
            # no log row is exactly what made earlier invoice runs unrepeatable.
            if not self._persist():
                raise RuntimeError("Failed to save invoice price updates")
    
            script_dir = data_manager_module.DATA_DIR
            for item_id in updated_items:
                item_row = self.inventory_df[self.inventory_df[COL_ITEM_ID] == item_id].iloc[0]
                quantity = float(item_row[COL_QUANTITY])
                total_value = quantity * float(item_row[COL_COST_PRICE])
                update_items_csv_total_value(
                    script_dir=script_dir,
                    item_id=item_id,
                    item_name=str(item_row[COL_ITEM_NAME]),
                    quantity=quantity,
                    total_value=total_value,
                )
    
        return {
            'updated': len(updated_items),
            'unchanged': unchanged_count,
            'locked': locked_skipped,
        }
