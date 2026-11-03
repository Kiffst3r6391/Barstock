#!/usr/bin/env python3
"""Report screens: GP, surplus, variance, price history, analytics and PDFs."""

import os
from datetime import datetime, timedelta

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

import ui_theme
from ui_theme import (
    THEME_ACCENT, THEME_BG, THEME_BORDER, THEME_CARD, THEME_DANGER,
    THEME_TEXT, THEME_TEXT_MUTED, THEME_WARNING,
    TBL_ROW_ALT, TBL_ROW_WARN, TBL_ROW_DANGER,
)

try:
    import matplotlib
    matplotlib.use('TkAgg')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

from fpdf import FPDF

from app_config import (
    COL_ACTION, COL_CATEGORY, COL_COST_PRICE, COL_ITEM_ID, COL_ITEM_NAME,
    COL_QUANTITY, COL_SELL_PRICE, COL_SUPPLIER, COL_TIMESTAMP,
    get_script_directory,
)
from actions import ACTION_COMPLIMENTARY, ACTION_SALES, ACTION_WASTAGE
from categories import is_delisted
from conversions import DATE_FORMAT_DISPLAY, parse_display_date
from data_manager import (
    InventoryDataManager, COL_REORDER_LEVEL, get_stocktake_history,
)
from pdf_generator import PDFReport, PriceHistoryPDF, StockOrderSheetPDF, format_report_period
from reports import (
    filter_log_by_date,
    build_gp_report_data,
    build_surplus_report_data,
    build_division_report_data,
    build_draught_yield_data,
    build_price_history_data,
    build_sales_analytics_data,
    build_comprehensive_report_data,
    build_reorder_report_data,
    build_comparison_report_data,
    build_stock_order_sheet_data,
    build_custom_stock_order_sheet_data,
)
from screens.widgets import DateRangeDialog


class ReportsMixin:
    """Report screens mixed into the main application class."""

    def generate_reports(self):
        """Legacy entry point for the report screens; the hub is the single list.

        Report screens still use this for their Back button, so it forwards to
        the hub rather than rendering a second, divergent menu.
        """
        self.show_reports()

    # Shared Ledger furniture -------------------------------------------

    def _begin_report(self, title, subtitle):
        """Clear the content and put the report's name in the page heading."""
        self.clear_main_menu()
        self._set_page_heading(title, subtitle)
        body = tk.Frame(self.main_menu, bg=THEME_BG)
        body.pack(fill='both', expand=True)
        return body

    def _report_table(self, parent, columns, headings, widths, anchors=None):
        """Build a ruled, sortable table sized to the report content."""
        wrap = tk.Frame(parent, bg=THEME_BG)
        wrap.pack(fill='both', expand=True)
        tree = ttk.Treeview(wrap, columns=columns, show='headings')
        anchors = anchors or {}
        for column, heading in zip(columns, headings):
            anchor = anchors.get(column, 'e')
            tree.heading(column, text=heading, anchor=anchor)
        for column, width in zip(columns, widths):
            tree.column(column, width=width, minwidth=60,
                        anchor=anchors.get(column, 'e'), stretch=True)
        self._make_sortable(tree)
        tree.tag_configure('alt', background=TBL_ROW_ALT, foreground=THEME_TEXT)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(wrap, orient=tk.VERTICAL, command=tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=scrollbar.set)
        self._bind_treeview_mousewheel(tree)
        return tree

    def _report_totals(self, parent, rows):
        """Ruled totals band: muted labels left, serif figures right."""
        tk.Frame(parent, bg=THEME_BORDER, height=1).pack(fill='x', pady=(18, 0))
        band = tk.Frame(parent, bg=THEME_BG)
        band.pack(fill='x')
        for index, (label, value) in enumerate(rows):
            line = tk.Frame(band, bg=THEME_BG)
            line.pack(fill='x', pady=(10 if index == 0 else 5, 0))
            tk.Label(line, text=label.upper(), font=ui_theme.mono_font(9),
                     fg=THEME_TEXT_MUTED, bg=THEME_BG,
                     anchor='w').pack(side='left')
            tk.Label(line, text=value, font=ui_theme.display_font(13),
                     fg=THEME_TEXT, bg=THEME_BG,
                     anchor='e').pack(side='right')
        tk.Frame(parent, bg=THEME_BORDER, height=1).pack(fill='x', pady=(10, 0))

    def _report_empty(self, parent, message):
        """Replace a table with a quiet empty state."""
        box = tk.Frame(parent, bg=THEME_BG)
        box.pack(fill='both', expand=True, pady=(48, 48))
        tk.Label(box, text=message, font=ui_theme.display_font(14),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG).pack()

    def _report_footer(self, actions=()):
        """A ruled footer with Back on the left and any extras on the right.

        ``actions`` is a sequence of ``(text, command, variant)`` tuples.
        """
        tk.Frame(self.main_menu, bg=THEME_BORDER, height=1).pack(
            fill='x', pady=(22, 0))
        footer = tk.Frame(self.main_menu, bg=THEME_BG)
        footer.pack(fill='x', pady=(12, 0))
        self.styled_button(footer, "Back", self.generate_reports,
                           width=8, variant='secondary').pack(side='left')
        for text, command, variant in reversed(tuple(actions)):
            self.styled_button(footer, text, command, width=22,
                               variant=variant).pack(side='right', padx=(8, 0))


    def generate_gp_report(self):
        """Display the Gross Profit report."""
        body = self._begin_report(
            "Gross Profit",
            "Retail, member and non-member margin for the period")

        try:
            self.refresh_data()

            filtered_log, start_date, end_date = self.get_filtered_log(
                "GP Report - Date Range")
            if filtered_log is None:
                self.generate_reports()
                return

            if filtered_log.empty:
                self._report_empty(
                    body, "No transactions fall inside the selected period.")
                self._report_footer()
                return

            report_df = build_gp_report_data(
                filtered_log,
                member_discount_pct=int(self.get_member_discount_pct()))

            # Show the stocked name rather than the key, so a committee reader
            # sees "Tennents Lager", not "tennents_lager".
            name_by_id = {}
            if not self.inventory_df.empty:
                name_by_id = {
                    str(item_id): str(name)
                    for item_id, name in zip(
                        self.inventory_df[COL_ITEM_ID],
                        self.inventory_df[COL_ITEM_NAME])
                }

            columns = ('item_id', 'total_cost', 'total_revenue', 'gp', 'gp_pct',
                       'member_gp', 'member_gp_pct', 'non_member_gp',
                       'non_member_gp_pct')
            tree = self._report_table(
                body, columns,
                ('Item', 'Cost', 'Retail revenue', 'Retail GP', 'GP %',
                 'Member GP', 'Member %', 'Non-member GP', 'Non-member %'),
                (200, 95, 115, 100, 75, 100, 80, 120, 100),
                anchors={'item_id': 'w'})

            for index, (item_id, row) in enumerate(report_df.iterrows()):
                values = (name_by_id.get(str(item_id), item_id),
                          self.format_currency(row['Total Cost']),
                          self.format_currency(row['Total Revenue']),
                          self.format_currency(row['GP']),
                          f"{row['GP%']:.1f}%",
                          self.format_currency(row['Member GP']),
                          f"{row['Member GP%']:.1f}%",
                          self.format_currency(row['Non-Member GP']),
                          f"{row['Non-Member GP%']:.1f}%")
                tree.insert('', tk.END, values=values,
                            tags=('alt',) if index % 2 else ())

            total_gp = report_df['GP'].sum()
            total_member_gp = report_df['Member GP'].sum()
            total_non_member_gp = report_df['Non-Member GP'].sum()
            total_revenue = report_df['Total Revenue'].sum()
            total_member_revenue = report_df['Member Revenue'].sum()
            total_non_member_revenue = report_df['Non-Member Revenue'].sum()
            overall_gp_pct = (total_gp / total_revenue * 100) if total_revenue > 0 else 0
            overall_member_gp_pct = (total_member_gp / total_member_revenue * 100) if total_member_revenue > 0 else 0
            overall_non_member_gp_pct = (total_non_member_gp / total_non_member_revenue * 100) if total_non_member_revenue > 0 else 0

            discount_pct = int(self.get_member_discount_pct())
            self._report_totals(body, [
                ("Retail GP",
                 f"{self.format_currency(total_gp)}  ·  {overall_gp_pct:.1f}%"),
                (f"Member GP · {discount_pct}% discount applied",
                 f"{self.format_currency(total_member_gp)}  ·  {overall_member_gp_pct:.1f}%"),
                ("Non-member GP",
                 f"{self.format_currency(total_non_member_gp)}  ·  {overall_non_member_gp_pct:.1f}%"),
            ])

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")

        self._report_footer()


    def generate_surplus_report(self):
        """Display the Surplus/Variance report."""
        body = self._begin_report(
            "Surplus & Variance",
            "Actual stock against what sales and wastage predict")

        try:
            self.refresh_data()

            if self.inventory_df.empty:
                self._report_empty(body, "No inventory data available.")
                self._report_footer()
                return

            filtered_log, start_date, end_date = self.get_filtered_log(
                "Surplus/Variance Report - Date Range")
            if filtered_log is None:
                self.generate_reports()
                return

            report_data = build_surplus_report_data(self.inventory_df, filtered_log)
            report_df = pd.DataFrame(report_data)

            columns = ('item_id', 'expected', 'actual', 'variance',
                       'variance_pct', 'variance_value')
            tree = self._report_table(
                body, columns,
                ('Item', 'Expected (sold + wastage)', 'Actual stock',
                 'Variance', 'Variance %', 'Variance £'),
                (200, 180, 130, 110, 100, 110),
                anchors={'item_id': 'w'})

            for index, (_, row) in enumerate(report_df.iterrows()):
                variance = row['Variance']
                values = (row[COL_ITEM_ID], f"{row['Expected']:.1f}",
                          f"{row['Actual']:.1f}", f"{variance:+.1f}",
                          f"{row['Variance %']:+.1f}%",
                          f"£{row['Variance Value']:+.2f}")
                tags = ('alt',) if index % 2 else ()
                tree.insert('', tk.END, values=values, tags=tags)

            if not report_df.empty:
                self._report_totals(body, [
                    ("Net variance",
                     f"£{report_df['Variance Value'].sum():+.2f}"),
                    ("Lines in variance",
                     f"{int((report_df['Variance'].abs() >= 1).sum())} of {len(report_df)}"),
                ])

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")

        self._report_footer()


    def generate_division_report(self):
        """Display sales by division/category."""
        body = self._begin_report(
            "Sales by Division",
            "Revenue and margin grouped by product category")

        try:
            self.refresh_data()

            filtered_log, start_date, end_date = self.get_filtered_log(
                "Division Report - Date Range")
            if filtered_log is None:
                self.generate_reports()
                return

            if filtered_log.empty:
                self._report_empty(
                    body, "No transactions fall inside the selected period.")
                self._report_footer()
                return

            division_summary = build_division_report_data(
                self.inventory_df, filtered_log,
                member_discount_pct=int(self.get_member_discount_pct())
            )

            if division_summary.empty:
                self._report_empty(
                    body, "No sales transactions found for the selected period.")
                self._report_footer()
                return

            columns = ('division', 'qty', 'revenue', 'cost', 'gp', 'gp_pct',
                       'member_gp', 'member_gp_pct', 'non_member_gp',
                       'non_member_gp_pct')
            tree = self._report_table(
                body, columns,
                ('Division', 'Units', 'Revenue', 'Cost', 'Retail GP', 'GP %',
                 'Member GP', 'Member %', 'Non-member GP', 'Non-member %'),
                (170, 80, 100, 90, 100, 75, 100, 80, 120, 100),
                anchors={'division': 'w'})

            for index, (_, row) in enumerate(division_summary.iterrows()):
                values = (row['Division'], f"{row['Total Quantity']:.1f}",
                          self.format_currency(row['Total Revenue']),
                          self.format_currency(row['Total Cost']),
                          self.format_currency(row['GP']),
                          f"{row['GP%']:.1f}%",
                          self.format_currency(row['Member GP']),
                          f"{row['Member GP%']:.1f}%",
                          self.format_currency(row['Non-Member GP']),
                          f"{row['Non-Member GP%']:.1f}%")
                tree.insert('', tk.END, values=values,
                            tags=('alt',) if index % 2 else ())

            total_revenue = division_summary['Total Revenue'].sum()
            total_member_revenue = division_summary['Member Revenue'].sum()
            total_non_member_revenue = division_summary['Non-Member Revenue'].sum()
            total_gp = division_summary['GP'].sum()
            total_member_gp = division_summary['Member GP'].sum()
            total_non_member_gp = division_summary['Non-Member GP'].sum()

            overall_gp_pct = (total_gp / total_revenue * 100) if total_revenue > 0 else 0
            overall_member_gp_pct = (total_member_gp / total_member_revenue * 100) if total_member_revenue > 0 else 0
            overall_non_member_gp_pct = (total_non_member_gp / total_non_member_revenue * 100) if total_non_member_revenue > 0 else 0

            self._report_totals(body, [
                ("Revenue", self.format_currency(total_revenue)),
                ("Retail GP",
                 f"{self.format_currency(total_gp)}  ·  {overall_gp_pct:.1f}%"),
                ("Member GP",
                 f"{self.format_currency(total_member_gp)}  ·  {overall_member_gp_pct:.1f}%"),
                ("Non-member GP",
                 f"{self.format_currency(total_non_member_gp)}  ·  {overall_non_member_gp_pct:.1f}%"),
            ])

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")

        self._report_footer()


    def generate_draught_yield_report(self):
        """Display the draught yield report."""
        body = self._begin_report(
            "Draught Yield",
            "What the kegs say went out, against sales, wastage and returns")

        try:
            self.refresh_data()

            if self.inventory_df.empty or self.log_df.empty:
                self._report_empty(
                    body, "This report needs both inventory and transactions.")
                self._report_footer()
                return

            filtered_log, start_date, end_date = self.get_filtered_log(
                "Draught Yield Report - Date Range")
            if filtered_log is None:
                self.generate_reports()
                return

            report_data = build_draught_yield_data(self.inventory_df, filtered_log)

            if not report_data:
                self._report_empty(
                    body, "No draught yield data found for the selected period.")
                self._report_footer()
                return

            report_df = pd.DataFrame(report_data)

            columns = ('item_id', 'item_name', 'opening', 'deliveries', 'sales',
                       'wastage', 'comp', 'consumed', 'actual', 'loss',
                       'closing', 'yield')
            tree = self._report_table(
                body, columns,
                ('Item', 'Name', 'Opening', 'Deliveries', ACTION_SALES,
                 ACTION_WASTAGE, 'Comp', 'Expected used', 'Actual used',
                 'Unrecorded loss', 'Closing', 'Yield %'),
                (90, 180, 75, 85, 70, 80, 60, 105, 100, 115, 75, 70),
                anchors={'item_id': 'w', 'item_name': 'w'})

            for index, (_, row) in enumerate(report_df.iterrows()):
                yield_val = row['Yield %']
                loss_val = row['Unrecorded Loss']
                moved = any(abs(float(row[column])) > 0.001 for column in (
                    'Opening Stock', 'Deliveries', ACTION_SALES,
                    ACTION_WASTAGE, ACTION_COMPLIMENTARY, 'Current Stock',
                    'Actual Consumption'))
                tags = ('alt',) if index % 2 else ()
                if is_delisted(str(row[COL_ITEM_ID])) or not moved:
                    # Delisted or untouched lines have no yield to judge.
                    tags = ('no_activity',)
                elif yield_val < 90 or yield_val > 110 or abs(loss_val) >= 10:
                    tags = ('yield_warning',)
                elif yield_val < 95 or yield_val > 105 or abs(loss_val) >= 5:
                    tags = ('loss_warning',)

                values = (row[COL_ITEM_ID], row[COL_ITEM_NAME],
                          f"{row['Opening Stock']:.1f}",
                          f"{row['Deliveries']:.1f}",
                          f"{row[ACTION_SALES]:.1f}",
                          f"{row[ACTION_WASTAGE]:.1f}",
                          f"{row[ACTION_COMPLIMENTARY]:.1f}",
                          f"{row['Expected Consumption']:.1f}",
                          f"{row['Actual Consumption']:.1f}",
                          f"{loss_val:.1f}",
                          f"{row['Current Stock']:.1f}",
                          f"{yield_val:.1f}%")

                tree.insert('', tk.END, values=values, tags=tags)

            tree.tag_configure('yield_warning', background=TBL_ROW_DANGER,
                               foreground=THEME_DANGER)
            tree.tag_configure('loss_warning', background=TBL_ROW_WARN,
                               foreground=THEME_WARNING)
            tree.tag_configure('no_activity', foreground=THEME_TEXT_MUTED)

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")

        self._report_footer()


    def generate_stocktake_report(self):
        """Display the stocktake variance report."""
        body = self._begin_report(
            "Stocktake Variance",
            "The last physical count against the expected figure")

        try:
            self.refresh_data()

            if self.inventory_df.empty:
                self._report_empty(body, "No inventory data available.")
                self._report_footer()
                return

            # Load latest stocktake data
            stocktake_rows = get_stocktake_history(limit=1000)
            stocktake_df = None
            if stocktake_rows:
                data = [dict(row) for row in stocktake_rows]
                stocktake_df = pd.DataFrame(data)
                # Baseline-reset snapshots represent the new starting point, not a
                # physical variance, so exclude them before picking the latest
                # meaningful stocktake per item.
                stocktake_df = stocktake_df[
                    ~stocktake_df['note'].astype(str).str.contains('Baseline', case=False, na=False)
                ]
                stocktake_df = stocktake_df.sort_values('timestamp', ascending=False)
                stocktake_df = stocktake_df.drop_duplicates(subset='item_id', keep='first')

            from reports import build_stocktake_variance_report
            report_data = build_stocktake_variance_report(self.inventory_df, self.log_df, stocktake_df)

            if not report_data:
                self._report_empty(body, "No stocktakes have been recorded yet.")
                self._report_footer()
                return

            report_df = pd.DataFrame(report_data)

            columns = ('item_id', 'item_name', 'expected', 'counted',
                       'variance', 'variance_pct', 'variance_value')
            tree = self._report_table(
                body, columns,
                ('Item', 'Name', 'Expected', 'Counted', 'Variance',
                 'Variance %', 'Value'),
                (130, 220, 100, 100, 100, 100, 100),
                anchors={'item_id': 'w', 'item_name': 'w'})

            def _qty(value):
                return f"{value:.1f}" if pd.notna(value) else '-'

            for index, (_, row) in enumerate(report_df.iterrows()):
                has_st = row.get('has_stocktake', False)
                if has_st:
                    expected = _qty(row['expected_quantity'])
                    counted = _qty(row['counted_quantity'])
                    variance = row['variance']
                    var_pct = row['variance_pct']
                    var_val = row['variance_value']
                    var_str = f"{variance:+.1f}"
                    var_pct_str = f"{var_pct:+.1f}%"
                    var_val_str = f"£{var_val:.2f}"
                    tags = ('alt',) if index % 2 else ()
                    if abs(var_pct) > 5:
                        tags = ('high_variance',)
                    elif abs(var_pct) > 2:
                        tags = ('med_variance',)
                else:
                    expected = _qty(row['expected_quantity'])
                    counted = '-'
                    var_str = '-'
                    var_pct_str = '-'
                    var_val_str = '-'
                    tags = ('no_stocktake',)

                values = (row['item_id'], row['item_name'], expected, counted,
                          var_str, var_pct_str, var_val_str)
                tree.insert('', tk.END, values=values, tags=tags)

            tree.tag_configure('high_variance', background=TBL_ROW_DANGER,
                               foreground=THEME_DANGER)
            tree.tag_configure('med_variance', background=TBL_ROW_WARN,
                               foreground=THEME_WARNING)
            tree.tag_configure('no_stocktake', foreground=THEME_TEXT_MUTED)

            st_items = report_df[report_df['has_stocktake'] == True]
            if not st_items.empty:
                total_var_val = st_items['variance_value'].sum()
                expected_total = st_items['expected_quantity'].sum()
                total_var_pct = (st_items['variance'].sum() / abs(expected_total) * 100) if abs(expected_total) > 0 else 0
                self._report_totals(body, [
                    ("Net variance",
                     f"£{total_var_val:+.2f}  ·  {total_var_pct:+.1f}%"),
                    ("Items counted", f"{len(st_items)} of {len(report_df)}"),
                ])

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")

        self._report_footer()


    def generate_reconciliation_report(self):
        """Display the inventory reconciliation report."""
        body = self._begin_report(
            "Reconciliation",
            "Where the inventory, transaction log and reference files disagree")

        try:
            self.refresh_data()

            if self.inventory_df.empty:
                self._report_empty(body, "No inventory data available.")
                self._report_footer()
                return

            from reports import build_reconciliation_report
            script_dir = get_script_directory()
            report = build_reconciliation_report(self.inventory_df, self.log_df, script_dir=script_dir)

            summary_lines = []
            sections = [
                ("Missing conversion rules", report['missing_conversion'], lambda x: f"{x['item_name']} ({x['item_id']})"),
                ("Missing category mapping", report['missing_category'], lambda x: f"{x['item_name']} ({x['item_id']})"),
                ("Not on order sheet", report['missing_order_sheet'], lambda x: f"{x['item_name']} ({x['item_id']})"),
                ("Order-sheet orphans with stock", report['order_sheet_orphans'], lambda x: f"{x['display_name']} ({x['supplier']} / {x['category']})"),
                ("In inventory but not Items.csv", report['csv_mismatches']['in_inventory_not_csv'], lambda x: str(x)),
                ("In Items.csv but not inventory", report['csv_mismatches']['in_csv_not_inventory'], lambda x: str(x)),
                ("Recently negative items", report['recent_negative'], lambda x: f"{x['item_name']} ({x['item_id']}): {x['current_qty']:.1f}"),
            ]

            for title, items, fmt in sections:
                if items:
                    summary_lines.append(f"{title} ({len(items)})")
                    for item in items[:5]:
                        summary_lines.append(f"    {fmt(item)}")
                    if len(items) > 5:
                        summary_lines.append(f"    ... and {len(items) - 5} more")
                    summary_lines.append("")

            if not summary_lines:
                summary_lines.append("No issues found. Inventory is fully in sync.")

            text = tk.Text(body, wrap=tk.WORD, height=18,
                           font=ui_theme.mono_font(10), bg=THEME_CARD,
                           fg=THEME_TEXT, relief='flat', padx=14, pady=12,
                           highlightthickness=1,
                           highlightbackground=THEME_BORDER,
                           highlightcolor=THEME_BORDER,
                           insertbackground=THEME_TEXT)
            text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            text.insert(tk.END, f"Generated {report['generated_at']}\n\n"
                                 + "\n".join(summary_lines))
            text.config(state=tk.DISABLED)

            scrollbar = ttk.Scrollbar(body, orient=tk.VERTICAL,
                                      command=text.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            text.configure(yscrollcommand=scrollbar.set)

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")

        self._report_footer()


    def generate_price_history_report(self):
        """Display price history from delivery transactions."""
        body = self._begin_report(
            "Price History",
            "What each supplier charged, and when it changed")

        try:
            self.refresh_data()

            if self.log_df.empty:
                self._report_empty(body, "No transaction data available.")
                self._report_footer()
                return

            filtered_log, start_date, end_date = self.get_filtered_log(
                "Price History Report - Date Range")
            if filtered_log is None:
                self.generate_reports()
                return

            report_data = build_price_history_data(self.inventory_df, filtered_log)

            if not report_data:
                self._report_empty(
                    body, "No delivery transactions fall inside the selected period.")
                self._report_footer()
                return

            columns = ('item_name', 'date', 'supplier', 'cost_price',
                       'prev_price', 'change')
            tree = self._report_table(
                body, columns,
                ('Item', 'Date', 'Supplier', 'Cost price', 'Previous', 'Change'),
                (260, 160, 160, 110, 110, 160),
                anchors={'item_name': 'w', 'date': 'w', 'supplier': 'w'})

            for index, row in enumerate(report_data):
                change_str = f"{'+' if row['change'] >= 0 else ''}{row['change']:.2f} ({row['change_pct']:.1f}%)"
                stamp = pd.to_datetime(row[COL_TIMESTAMP], errors='coerce')
                date_text = (stamp.strftime('%d %b %Y')
                             if pd.notna(stamp) else str(row[COL_TIMESTAMP]))
                tree.insert('', tk.END, values=(
                    row[COL_ITEM_NAME],
                    date_text,
                    row[COL_SUPPLIER],
                    f"£{row[COL_COST_PRICE]:.2f}",
                    f"£{row['prev_price']:.2f}",
                    change_str
                ), tags=('alt',) if index % 2 else ())

            self._report_footer([
                ("Download price history PDF",
                 lambda: self.download_price_history_pdf(
                     report_data, format_report_period(start_date, end_date)),
                 'secondary'),
            ])
            return

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")

        self._report_footer()


    def download_price_history_pdf(self, report_data, report_period=None):
        """Generate and save a price history PDF report."""
        try:
            filepath = PriceHistoryPDF.generate(
                report_data, report_period=report_period)
            messagebox.showinfo("Success", f"Price history report saved to:\n{filepath}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate PDF: {e}")


    def generate_sales_analytics(self):
        """Display sales trends and analytics."""
        body = self._begin_report(
            "Sales Analytics",
            "Category volume, movers, daily rhythm and margin")

        try:
            self.refresh_data()

            if self.log_df.empty:
                self._report_empty(body, "No transaction data available for analytics.")
                self._report_footer()
                return

            filtered_log, start_date, end_date = self.get_filtered_log(
                "Sales Analytics - Date Range")
            if filtered_log is None:
                self.generate_reports()
                return

            if filtered_log.empty:
                self._report_empty(
                    body, "No transactions fall inside the selected period.")
                self._report_footer()
                return

            # Temporarily replace log with filtered version for tab methods
            original_log = self.log_df
            self.log_df = filtered_log
            try:
                notebook = ttk.Notebook(body)
                notebook.pack(fill='both', expand=True)

                self._create_category_sales_tab(notebook)
                self._create_movers_tab(notebook)
                self._create_timeline_tab(notebook)
                self._create_profit_margins_tab(notebook)
            finally:
                self.log_df = original_log

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")

        self._report_footer()


    def _create_category_sales_tab(self, notebook):
        """Create the Sales by Category tab."""
        tab = tk.Frame(notebook, bg=THEME_BG)
        notebook.add(tab, text="Sales by Category")

        sales_df = self.log_df[self.log_df[COL_ACTION] == ACTION_SALES].copy()

        if sales_df.empty:
            self._report_empty(tab, "No sales data available.")
            return

        sales_with_cat = sales_df.merge(
            self.inventory_df[[COL_ITEM_ID, COL_ITEM_NAME, COL_CATEGORY]],
            on=COL_ITEM_ID,
            how='left'
        )

        category_sales = sales_with_cat.groupby(COL_CATEGORY).agg({
            COL_QUANTITY: 'sum',
            COL_ITEM_ID: 'nunique'
        }).reset_index()
        category_sales.columns = [COL_CATEGORY, 'Total Quantity', 'Unique Items']
        category_sales = category_sales.sort_values('Total Quantity', ascending=False)

        chart_frame = tk.Frame(tab, bg=THEME_BG)
        chart_frame.pack(side='left', fill='both', expand=True, pady=14)
        table_frame = tk.Frame(tab, bg=THEME_BG)
        table_frame.pack(side='right', fill='y', padx=(24, 0), pady=14)

        tk.Label(chart_frame, text="VOLUME BY CATEGORY",
                 font=ui_theme.mono_font(9), fg=THEME_TEXT_MUTED,
                 bg=THEME_BG, anchor='w').pack(fill='x', pady=(0, 8))
        tk.Label(table_frame, text="CATEGORY BREAKDOWN",
                 font=ui_theme.mono_font(9), fg=THEME_TEXT_MUTED,
                 bg=THEME_BG, anchor='w').pack(fill='x', pady=(0, 8))

        if MATPLOTLIB_AVAILABLE and not category_sales.empty:
            fig = Figure(figsize=(6, 4), dpi=100)
            ax = fig.add_subplot(111)
            colors = list(ui_theme.CHART_COLORS)
            ax.bar(category_sales[COL_CATEGORY], category_sales['Total Quantity'],
                   color=colors[:len(category_sales)], width=0.62)
            ax.set_ylabel('Units sold', fontsize=10)
            ax.tick_params(axis='x', rotation=30)
            self._style_chart(fig, ax)
            fig.subplots_adjust(bottom=0.26, left=0.1, right=0.98, top=0.94)

            canvas = FigureCanvasTkAgg(fig, chart_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill='both', expand=True)
        else:
            tk.Label(chart_frame, text="Charts need matplotlib installed.",
                     font=(ui_theme.THEME_FONT, 10), fg=THEME_TEXT_MUTED,
                     bg=THEME_BG).pack(pady=20)

        tree = self._report_table(
            table_frame,
            ('category', 'quantity', 'items'),
            ('Category', 'Units', 'Items'),
            (150, 95, 70),
            anchors={'category': 'w'})
        for index, (_, row) in enumerate(category_sales.iterrows()):
            tree.insert('', tk.END, values=(
                row[COL_CATEGORY],
                f"{row['Total Quantity']:.1f}",
                int(row['Unique Items'])
            ), tags=('alt',) if index % 2 else ())


    def _create_movers_tab(self, notebook):
        """Create the Fast & Slow Movers tab."""
        tab = tk.Frame(notebook, bg=THEME_BG)
        notebook.add(tab, text="Fast & Slow Movers")

        sales_df = self.log_df[self.log_df[COL_ACTION] == ACTION_SALES].copy()

        if sales_df.empty:
            self._report_empty(tab, "No sales data available.")
            return

        sales_with_info = sales_df.merge(
            self.inventory_df[[COL_ITEM_ID, COL_ITEM_NAME, COL_CATEGORY]],
            on=COL_ITEM_ID,
            how='left'
        )

        item_sales = sales_with_info.groupby([COL_ITEM_ID, COL_ITEM_NAME, COL_CATEGORY]).agg({
            COL_QUANTITY: 'sum'
        }).reset_index()
        item_sales.columns = [COL_ITEM_ID, COL_ITEM_NAME, COL_CATEGORY, 'Total Sales']
        item_sales = item_sales.sort_values('Total Sales', ascending=False)

        fast_movers = item_sales.head(10)
        slow_movers = item_sales.tail(10)

        left_frame = tk.Frame(tab, bg=THEME_BG)
        left_frame.pack(side='left', fill='both', expand=True, pady=14)
        right_frame = tk.Frame(tab, bg=THEME_BG)
        right_frame.pack(side='right', fill='both', expand=True, padx=(24, 0), pady=14)

        for pane, heading in ((left_frame, "FAST MOVERS · TOP 10"),
                              (right_frame, "SLOW MOVERS · BOTTOM 10")):
            tk.Label(pane, text=heading, font=ui_theme.mono_font(9),
                     fg=THEME_TEXT_MUTED, bg=THEME_BG,
                     anchor='w').pack(fill='x', pady=(0, 8))
            tk.Frame(pane, bg=THEME_BORDER, height=1).pack(fill='x', pady=(0, 8))

        fast_tree = self._report_table(
            left_frame, ('name', 'category', 'sales'),
            ('Item', 'Category', 'Units'), (220, 110, 80),
            anchors={'name': 'w', 'category': 'w'})
        for index, (_, row) in enumerate(fast_movers.iterrows()):
            fast_tree.insert('', tk.END, values=(
                row[COL_ITEM_NAME], row[COL_CATEGORY],
                f"{row['Total Sales']:.1f}"
            ), tags=('alt',) if index % 2 else ())

        slow_tree = self._report_table(
            right_frame, ('name', 'category', 'sales'),
            ('Item', 'Category', 'Units'), (220, 110, 80),
            anchors={'name': 'w', 'category': 'w'})
        for index, (_, row) in enumerate(slow_movers.iterrows()):
            slow_tree.insert('', tk.END, values=(
                row[COL_ITEM_NAME], row[COL_CATEGORY],
                f"{row['Total Sales']:.1f}"
            ), tags=('alt',) if index % 2 else ())


    def _create_timeline_tab(self, notebook):
        """Create the Sales Timeline tab."""
        tab = tk.Frame(notebook, bg=THEME_BG)
        notebook.add(tab, text="Sales Timeline")

        sales_df = self.log_df[self.log_df[COL_ACTION] == ACTION_SALES].copy()

        if sales_df.empty:
            self._report_empty(tab, "No sales data available.")
            return

        sales_df['date'] = pd.to_datetime(sales_df[COL_TIMESTAMP]).dt.date

        daily_sales = sales_df.groupby('date').agg({
            COL_QUANTITY: 'sum'
        }).reset_index()

        tk.Label(tab, text="DAILY SALES VOLUME", font=ui_theme.mono_font(9),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG,
                 anchor='w').pack(fill='x', pady=(14, 8))

        chart_frame = tk.Frame(tab, bg=THEME_BG)
        chart_frame.pack(fill='both', expand=True)

        if MATPLOTLIB_AVAILABLE and len(daily_sales) > 1:
            fig = Figure(figsize=(10, 5), dpi=100)
            ax = fig.add_subplot(111)

            ax.plot(daily_sales['date'], daily_sales[COL_QUANTITY],
                    marker='o', markersize=3, linestyle='-',
                    color=THEME_ACCENT, linewidth=2)

            ax.set_ylabel('Units sold', fontsize=10)
            self._style_chart(fig, ax)

            fig.autofmt_xdate()
            fig.subplots_adjust(bottom=0.22, left=0.08, right=0.98, top=0.96)

            canvas = FigureCanvasTkAgg(fig, chart_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill='both', expand=True)
        else:
            tk.Label(chart_frame,
                     text="The timeline needs matplotlib and more than one day of sales.",
                     font=(ui_theme.THEME_FONT, 10), fg=THEME_TEXT_MUTED,
                     bg=THEME_BG).pack(pady=20)

        if not daily_sales.empty:
            stats = tk.Frame(tab, bg=THEME_BG)
            stats.pack(fill='x', pady=(14, 0))
            tk.Frame(stats, bg=THEME_BORDER, height=1).pack(
                fill='x', pady=(0, 10))
            figures = [
                ("Average day", f"{daily_sales[COL_QUANTITY].mean():.1f} units"),
                ("Busiest day", f"{daily_sales[COL_QUANTITY].max():.1f} units"),
                ("Quietest day", f"{daily_sales[COL_QUANTITY].min():.1f} units"),
            ]
            for label, value in figures:
                cell = tk.Frame(stats, bg=THEME_BG)
                cell.pack(side='left', padx=(0, 48))
                tk.Label(cell, text=label.upper(), font=ui_theme.mono_font(9),
                         fg=THEME_TEXT_MUTED, bg=THEME_BG,
                         anchor='w').pack(fill='x')
                tk.Label(cell, text=value, font=ui_theme.display_font(14),
                         fg=THEME_TEXT, bg=THEME_BG,
                         anchor='w').pack(fill='x')


    def _create_profit_margins_tab(self, notebook):
        """Create the Profit Margins tab."""
        tab = tk.Frame(notebook, bg=THEME_BG)
        notebook.add(tab, text="Profit Margins")

        sales_df = self.log_df[self.log_df[COL_ACTION] == ACTION_SALES].copy()

        if sales_df.empty:
            self._report_empty(tab, "No sales data available.")
            return

        inventory_subset = self.inventory_df[[COL_ITEM_ID, COL_ITEM_NAME, COL_CATEGORY, COL_COST_PRICE, COL_SELL_PRICE]].copy()
        inventory_subset.columns = [COL_ITEM_ID, COL_ITEM_NAME, COL_CATEGORY, 'inv_cost_price', 'inv_sell_price']

        sales_with_info = sales_df.merge(
            inventory_subset,
            on=COL_ITEM_ID,
            how='left'
        )

        sales_with_info['cost_price'] = sales_with_info[COL_COST_PRICE].fillna(sales_with_info['inv_cost_price'])
        sales_with_info['sell_price'] = sales_with_info[COL_SELL_PRICE].fillna(sales_with_info['inv_sell_price'])

        sales_with_info['profit_per_unit'] = sales_with_info['sell_price'] - sales_with_info['cost_price']
        sales_with_info['total_profit'] = sales_with_info['profit_per_unit'] * sales_with_info[COL_QUANTITY]
        sales_with_info['profit_margin_pct'] = (sales_with_info['profit_per_unit'] / sales_with_info['sell_price']) * 100

        category_profit = sales_with_info.groupby(COL_CATEGORY).agg({
            'total_profit': 'sum',
            'profit_margin_pct': 'mean',
            COL_QUANTITY: 'sum'
        }).reset_index()
        category_profit.columns = [COL_CATEGORY, 'Total Profit', 'Avg Margin %', 'Quantity Sold']
        category_profit = category_profit.sort_values('Total Profit', ascending=False)

        tk.Label(tab, text="PROFIT BY CATEGORY", font=ui_theme.mono_font(9),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG,
                 anchor='w').pack(fill='x', pady=(14, 8))

        chart_frame = tk.Frame(tab, bg=THEME_BG)
        chart_frame.pack(fill='both', expand=True)

        if MATPLOTLIB_AVAILABLE and not category_profit.empty:
            fig = Figure(figsize=(8, 3.6), dpi=100)
            ax = fig.add_subplot(111)

            colors = list(ui_theme.CHART_COLORS)
            ax.bar(category_profit[COL_CATEGORY], category_profit['Total Profit'],
                   color=colors[:len(category_profit)], width=0.62)

            ax.set_ylabel('Gross profit (£)', fontsize=10)
            ax.tick_params(axis='x', rotation=30)
            self._style_chart(fig, ax)
            fig.subplots_adjust(bottom=0.3, left=0.1, right=0.98, top=0.94)

            canvas = FigureCanvasTkAgg(fig, chart_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill='both', expand=True)
        else:
            tk.Label(chart_frame, text="Charts need matplotlib installed.",
                     font=(ui_theme.THEME_FONT, 10), fg=THEME_TEXT_MUTED,
                     bg=THEME_BG).pack(pady=20)

        tk.Frame(tab, bg=THEME_BORDER, height=1).pack(fill='x', pady=(14, 0))
        tk.Label(tab, text="MARGIN BY CATEGORY", font=ui_theme.mono_font(9),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG,
                 anchor='w').pack(fill='x', pady=(10, 8))

        tree = self._report_table(
            tab, ('category', 'profit', 'margin', 'quantity'),
            ('Category', 'Gross profit', 'Average margin', 'Units'),
            (220, 150, 150, 110), anchors={'category': 'w'})
        for index, (_, row) in enumerate(category_profit.iterrows()):
            tree.insert('', tk.END, values=(
                row[COL_CATEGORY],
                f"£{row['Total Profit']:.2f}",
                f"{row['Avg Margin %']:.1f}%",
                f"{row['Quantity Sold']:.1f}"
            ), tags=('alt',) if index % 2 else ())


    def generate_reorder_report(self):
        """Display reorder suggestions."""
        body = self._begin_report(
            "Reorder Suggestions",
            "Lines at or below their reorder level")

        try:
            self.refresh_data()
            report_data = build_reorder_report_data(self.inventory_df, self.log_df)

            if not report_data:
                self._report_empty(
                    body, "Nothing to reorder. Every line is above its reorder level.")
                self._report_footer()
                return

            columns = ('item_id', 'item_name', 'current_stock', 'reorder_level',
                       'suggested_order', 'last_delivery', 'supplier')
            tree = self._report_table(
                body, columns,
                ('Item', 'Name', 'On hand', 'Reorder at', 'Suggested order',
                 'Last delivery', 'Supplier'),
                (140, 220, 90, 100, 130, 130, 170),
                anchors={'item_id': 'w', 'item_name': 'w',
                         'last_delivery': 'w', 'supplier': 'w'})

            for index, item in enumerate(report_data):
                tree.insert('', tk.END, values=(
                    item[COL_ITEM_ID],
                    item[COL_ITEM_NAME],
                    f"{item[COL_QUANTITY]:.1f}",
                    f"{item[COL_REORDER_LEVEL]:.1f}",
                    f"{item['suggested_order']:.1f}",
                    item['last_delivery_date'] or '-',
                    item[COL_SUPPLIER] or '-'
                ), tags=('alt',) if index % 2 else ())

            total_order = sum(i['suggested_order'] for i in report_data)
            self._report_totals(body, [
                ("Lines to reorder", f"{len(report_data)}"),
                ("Total suggested quantity", f"{total_order:.1f}"),
            ])

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")

        self._report_footer()


    def generate_stock_order_sheet(self):
        """Generate the custom printable stock order sheet PDF."""
        try:
            self.refresh_data()
            report_data = build_custom_stock_order_sheet_data(self.inventory_df, self.log_df)
    
            if not report_data:
                messagebox.showwarning("No Items", "No orderable items found.")
                return
    
            filepath = StockOrderSheetPDF.generate(report_data)
            messagebox.showinfo("Order Sheet Generated",
                                f"Stock order sheet saved to:\n{filepath}\n\n"
                                f"Items included: {len(report_data)}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate stock order sheet: {e}")


    def generate_comparison_report(self):
        """Display the period comparison report."""
        try:
            # Get Period A (DateRangeDialog already blocks internally via wait_window)
            dialog_a = DateRangeDialog(self.root, title="Select Period A (Baseline)")
            if not dialog_a.result:
                self.generate_reports()
                return
            if dialog_a.result == 'ALL_TIME':
                start_a, end_a = None, None
            else:
                start_a, end_a = dialog_a.result

            dialog_b = DateRangeDialog(self.root, title="Select Period B (Comparison)")
            if not dialog_b.result:
                self.generate_reports()
                return
            if dialog_b.result == 'ALL_TIME':
                start_b, end_b = None, None
            else:
                start_b, end_b = dialog_b.result

            self.refresh_data()
            log_a = filter_log_by_date(self.log_df, start_a, end_a)
            log_b = filter_log_by_date(self.log_df, start_b, end_b)

            report_df = build_comparison_report_data(self.inventory_df, log_a, log_b,
                                                      member_discount_pct=int(self.get_member_discount_pct()))

            if start_a and end_a:
                period_a_text = f"{start_a.strftime(DATE_FORMAT_DISPLAY)} – {end_a.strftime(DATE_FORMAT_DISPLAY)}"
            else:
                period_a_text = "All time"
            if start_b and end_b:
                period_b_text = f"{start_b.strftime(DATE_FORMAT_DISPLAY)} – {end_b.strftime(DATE_FORMAT_DISPLAY)}"
            else:
                period_b_text = "All time"

            body = self._begin_report(
                "Period Comparison",
                f"A: {period_a_text}   ·   B: {period_b_text}")

            if report_df.empty:
                self._report_empty(
                    body, "No sales data found for the selected periods.")
                self._report_footer()
                return

            columns = ('item_name', 'qty_a', 'qty_b', 'delta_qty',
                       'rev_a', 'rev_b', 'delta_rev',
                       'gp_a', 'gp_b', 'delta_gp', 'delta_gp_pct')
            tree = self._report_table(
                body, columns,
                ('Item', 'A units', 'B units', 'Δ units',
                 'A revenue', 'B revenue', 'Δ revenue',
                 'A GP', 'B GP', 'Δ GP', 'Δ GP %'),
                (190, 70, 70, 75, 95, 95, 95, 85, 85, 85, 75),
                anchors={'item_name': 'w'})

            for index, (_, row) in enumerate(report_df.iterrows()):
                delta_gp_pct_str = f"{row['delta_gp_pct']:+.1f}%" if row['total_revenue_a'] != 0 else '-'
                tree.insert('', tk.END, values=(
                    row[COL_ITEM_NAME],
                    f"{row['total_qty_a']:.1f}",
                    f"{row['total_qty_b']:.1f}",
                    f"{row['delta_qty']:+.1f}",
                    self.format_currency(row['total_revenue_a']),
                    self.format_currency(row['total_revenue_b']),
                    self.format_currency(row['delta_revenue']),
                    self.format_currency(row['total_gp_a']),
                    self.format_currency(row['total_gp_b']),
                    self.format_currency(row['delta_gp']),
                    delta_gp_pct_str
                ), tags=('alt',) if index % 2 else ())

            total_rev_a = report_df['total_revenue_a'].sum()
            total_rev_b = report_df['total_revenue_b'].sum()
            total_gp_a = report_df['total_gp_a'].sum()
            total_gp_b = report_df['total_gp_b'].sum()
            self._report_totals(body, [
                ("Period A", f"{self.format_currency(total_rev_a)} revenue  ·  {self.format_currency(total_gp_a)} GP"),
                ("Period B", f"{self.format_currency(total_rev_b)} revenue  ·  {self.format_currency(total_gp_b)} GP"),
                ("GP movement", self.format_currency(total_gp_b - total_gp_a)),
            ])

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")

        self._report_footer()


    def download_comprehensive_report(self):
        """Generate and download a comprehensive PDF report with all data."""
        try:
            self.refresh_data()
    
            if self.inventory_df.empty:
                messagebox.showwarning("No Data", "No inventory data available to generate report.")
                return
    
            # Load full transaction history (active + archive) so the report can
            # show sales/complimentary/wastage/deliveries from before a baseline
            # reset while still using the current inventory state.
            full_log_df = InventoryDataManager.load_full_log(self.inventory_df)
    
            # Date range filter — default from last baseline reset to today
            from data_manager import get_last_baseline_reset_date
            default_start = get_last_baseline_reset_date()
            default_end = datetime.now()
            dialog = DateRangeDialog(
                self.root,
                title="Comprehensive PDF Report - Date Range",
                default_start=default_start,
                default_end=default_end
            )
            if dialog.result is None:
                return
            if dialog.result == 'ALL_TIME':
                filtered_log = full_log_df.copy()
                start_date, end_date = None, None
            else:
                start_date, end_date = dialog.result
                filtered_log = filter_log_by_date(full_log_df, start_date, end_date)

            # Printed in the PDF header and the confirmation dialog so the saved
            # file states the period it was run for.
            period_text = format_report_period(start_date, end_date)
    
            # Load latest stocktake data for meaningful variance calculation.
            # Baseline-reset snapshots are excluded from surplus/shortfall calculations
            # because their variance represents the new baseline, not a physical over/short.
            stocktake_rows = get_stocktake_history(limit=1000)
            stocktake_map = {}
            stocktake_data = None
            if stocktake_rows:
                st_df = pd.DataFrame([dict(row) for row in stocktake_rows])
                # Variance/surplus should only reflect true stocktake counts, not baselines
                variance_st_df = st_df[~st_df['note'].astype(str).str.contains('Baseline', case=False, na=False)]
                # Delisted items are reset to zero when they are retired. That reset is
                # bookkeeping, not a physical count, so it must not be reported as a
                # surplus (and the item carries no value in this report either).
                variance_st_df = variance_st_df[
                    ~variance_st_df['item_id'].map(lambda x: is_delisted(str(x)))
                ]
                # Then keep the latest meaningful (non-baseline) snapshot per item
                variance_st_df = variance_st_df.sort_values('timestamp', ascending=False)
                variance_st_df = variance_st_df.drop_duplicates(subset='item_id', keep='first')
                # Bound stocktakes to the selected report date range. A stocktake taken before
                # the period is not a surplus/shortfall for this report; one taken after the
                # period belongs to a later report.
                if start_date is not None and end_date is not None:
                    st_ts = pd.to_datetime(variance_st_df['timestamp'], errors='coerce')
                    variance_st_df = variance_st_df[
                        (st_ts >= pd.Timestamp(start_date)) &
                        (st_ts <= pd.Timestamp(end_date) + pd.Timedelta(days=1))
                    ]
                stocktake_map = {
                    row['item_id']: {
                        'counted_quantity': row['counted_quantity'],
                        'expected_quantity': row['expected_quantity'],
                        'variance': row['variance'],
                    }
                    for _, row in variance_st_df.iterrows()
                }
                if not variance_st_df.empty:
                    from reports import build_stocktake_variance_report
                    stocktake_data = build_stocktake_variance_report(self.inventory_df, full_log_df, variance_st_df)
    
                # Running surplus/shortfall: cumulative value of every non-baseline stocktake
                # variance across all time, surviving monthly baseline resets.
                # Use the full history (not the per-item latest snapshot) so each physical
                # stocktake's variance contributes to the year-end figure.
                all_variance_st_df = pd.DataFrame([dict(row) for row in stocktake_rows])
                all_variance_st_df = all_variance_st_df[
                    ~all_variance_st_df['note'].astype(str).str.contains('Baseline', case=False, na=False)
                ]
                # Same rule for the cumulative figure: a delisting reset is not a
                # physical surplus or shortfall.
                all_variance_st_df = all_variance_st_df[
                    ~all_variance_st_df['item_id'].map(lambda x: is_delisted(str(x)))
                ]
                cost_by_id = dict(zip(self.inventory_df[COL_ITEM_ID], self.inventory_df[COL_COST_PRICE]))
                running_surplus_value = sum(
                    float(row['variance']) * float(cost_by_id.get(row['item_id'], 0) or 0)
                    for _, row in all_variance_st_df.iterrows()
                ) if not all_variance_st_df.empty else 0.0
            else:
                running_surplus_value = 0.0
    
            # Compute closing stock at end_date for date-range consistency.
            # Closing stock is always derived from the live inventory by backing out
            # movements that happened after the period end. Stocktake snapshots are
            # not used here: a baseline reset sits at the *start* of the period, so
            # treating the latest snapshot as closing stock would report the opening
            # value as the closing one (and disagree with the dashboard).
            closing_stock_map = None
            if end_date is not None:
                end_ts = pd.Timestamp(end_date)
                from reports import calculate_expected_remaining_series
                # Filter out CSV-uploaded rows whose sales period is actually inside
                # the selected range, so their upload timestamp doesn't fake a post-period
                # transaction.
                def _is_after_period(row):
                    period = row.get('date_range')
                    if isinstance(period, str) and ' - ' in period:
                        try:
                            parts = period.split(' - ')
                            p_end = parse_display_date(parts[1].strip()).replace(hour=23, minute=59, second=59)
                            return p_end > end_date
                        except Exception:
                            pass
                    ts = pd.to_datetime(row.get('timestamp'), errors='coerce')
                    return pd.notna(ts) and ts > end_ts

                after_end_mask = full_log_df.apply(_is_after_period, axis=1)
                after_end_log = full_log_df[after_end_mask].copy()
                expected_after_end = calculate_expected_remaining_series(after_end_log)
                closing_stock_map = {
                    row[COL_ITEM_ID]: row[COL_QUANTITY] - expected_after_end.get(row[COL_ITEM_ID], 0)
                    for _, row in self.inventory_df.iterrows()
                }
    
            report_data = build_comprehensive_report_data(
                self.inventory_df, filtered_log,
                member_discount_pct=int(self.get_member_discount_pct()),
                stocktake_map=stocktake_map,
                closing_stock_map=closing_stock_map
            )
    
            if not report_data:
                messagebox.showwarning("No Data", "No data available for the selected period.")
                return
    
            # Create PDF
            pdf = PDFReport()
            pdf.generate_report(
                report_data,
                member_discount_pct=int(self.get_member_discount_pct()),
                stocktake_data=stocktake_data,
                running_surplus_value=running_surplus_value,
                report_period=period_text,
            )
    
            # Generate timestamp for filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"Bar_Stock_Full_Report_{timestamp}.pdf"
    
            # Save to Downloads folder
            downloads_dir = os.path.expanduser('~/Downloads')
            filepath = os.path.join(downloads_dir, filename)
            pdf.output(filepath)
    
            messagebox.showinfo("Report Generated", f"Comprehensive PDF report saved to:\n{filepath}\n\nReport period: {period_text}\n\nThe report includes:\n• Stock Summary by Division\n• Sales Performance\n• Wastage & Complimentary Summary\n• Draught Yield Report\n• Financial Summary with Totals\n• Stocktake Variance Report (if recorded)")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate report: {e}")
