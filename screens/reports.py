#!/usr/bin/env python3
"""Report screens: GP, surplus, variance, price history, analytics and PDFs."""

import os
from datetime import datetime, timedelta

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

import ui_theme
from ui_theme import (
    THEME_CARD, THEME_DANGER, THEME_TEXT, THEME_TEXT_MUTED, THEME_WARNING,
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
from conversions import DATE_FORMAT_DISPLAY, parse_display_date
from data_manager import (
    InventoryDataManager, COL_REORDER_LEVEL, get_stocktake_history,
)
from pdf_generator import PDFReport, PriceHistoryPDF, StockOrderSheetPDF
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


    def generate_gp_report(self):
        """Generate and display the Gross Profit report."""
        self.clear_main_menu()
    
        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
    
        tk.Label(header_frame, text="Gross Profit Report",
                font=(ui_theme.THEME_FONT, 16, 'bold')).pack(expand=True)
    
        frame = tk.Frame(self.main_menu)
        frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=10)
    
        try:
            self.refresh_data()
    
            # Date range filter
            filtered_log, start_date, end_date = self.get_filtered_log("GP Report - Date Range")
            if filtered_log is None:
                self.generate_reports()
                return
    
            if filtered_log.empty:
                tk.Label(self.main_menu, text="No transaction data available for selected period.").pack(pady=20)
                btn_frame = tk.Frame(self.main_menu)
                btn_frame.pack(pady=10)
                tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
                return
    
            report_df = build_gp_report_data(filtered_log, member_discount_pct=int(self.get_member_discount_pct()))
    
            # Display report in treeview
            columns = ('item_id', 'total_cost', 'total_revenue', 'gp', 'gp_pct', 'member_gp', 'member_gp_pct', 'non_member_gp', 'non_member_gp_pct')
            report_tree = ttk.Treeview(frame, columns=columns, show='headings')
    
            report_tree.heading('item_id', text='Item ID')
            report_tree.heading('total_cost', text='Total Cost')
            report_tree.heading('total_revenue', text='Retail Revenue')
            report_tree.heading('gp', text='Retail GP')
            report_tree.heading('gp_pct', text='Retail GP%')
            report_tree.heading('member_gp', text='Member GP')
            report_tree.heading('member_gp_pct', text='Member GP%')
            report_tree.heading('non_member_gp', text='Non-Mem GP')
            report_tree.heading('non_member_gp_pct', text='Non-Mem GP%')
    
            report_tree.column('item_id', width=100, anchor='center')
            report_tree.column('total_cost', width=90, anchor='center')
            report_tree.column('total_revenue', width=90, anchor='center')
            report_tree.column('gp', width=80, anchor='center')
            report_tree.column('gp_pct', width=70, anchor='center')
            report_tree.column('member_gp', width=80, anchor='center')
            report_tree.column('member_gp_pct', width=70, anchor='center')
            report_tree.column('non_member_gp', width=80, anchor='center')
            report_tree.column('non_member_gp_pct', width=70, anchor='center')
    
            self._make_sortable(report_tree)
    
            report_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    
            scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=report_tree.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            report_tree.configure(yscrollcommand=scrollbar.set)
            self._bind_treeview_mousewheel(report_tree)
    
            # Configure alternating row colors
            report_tree.tag_configure('oddrow', background=TBL_ROW_ALT, foreground=THEME_TEXT)
            report_tree.tag_configure('evenrow', background=THEME_CARD, foreground=THEME_TEXT)
    
            # Insert data
            for item_id, row in report_df.iterrows():
                values = (item_id, self.format_currency(row['Total Cost']),
                         self.format_currency(row['Total Revenue']),
                         self.format_currency(row['GP']),
                         f"{row['GP%']:.1f}%",
                         self.format_currency(row['Member GP']),
                         f"{row['Member GP%']:.1f}%",
                         self.format_currency(row['Non-Member GP']),
                         f"{row['Non-Member GP%']:.1f}%")
    
                report_tree.insert('', tk.END, values=values)
    
            # Summary
            summary_frame = tk.Frame(self.main_menu, relief='solid', borderwidth=1)
            summary_frame.pack(pady=10, fill='x', padx=10)
    
            total_gp = report_df['GP'].sum()
            total_member_gp = report_df['Member GP'].sum()
            total_non_member_gp = report_df['Non-Member GP'].sum()
            total_revenue = report_df['Total Revenue'].sum()
            total_member_revenue = report_df['Member Revenue'].sum()
            total_non_member_revenue = report_df['Non-Member Revenue'].sum()
            overall_gp_pct = (total_gp / total_revenue * 100) if total_revenue > 0 else 0
            overall_member_gp_pct = (total_member_gp / total_member_revenue * 100) if total_member_revenue > 0 else 0
            overall_non_member_gp_pct = (total_non_member_gp / total_non_member_revenue * 100) if total_non_member_revenue > 0 else 0
    
            tk.Label(summary_frame, text=f"Overall Retail GP: {self.format_currency(total_gp)} ({overall_gp_pct:.1f}%)",
                    font=(ui_theme.THEME_FONT, 11, 'bold')).pack(pady=2)
            discount_pct = int(self.get_member_discount_pct())
            tk.Label(summary_frame, text=f"Overall Member GP: {self.format_currency(total_member_gp)} ({overall_member_gp_pct:.1f}%) ({discount_pct}% member discount applied)",
                    font=(ui_theme.THEME_FONT, 11, 'bold')).pack(pady=2)
            tk.Label(summary_frame, text=f"Overall Non-Member GP: {self.format_currency(total_non_member_gp)} ({overall_non_member_gp_pct:.1f}%)",
                    font=(ui_theme.THEME_FONT, 11, 'bold')).pack(pady=2)
    
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")
    
        # Back button
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=10)
    
        tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
    
        self._apply_legacy_theme()


    def generate_surplus_report(self):
        """Generate and display the Surplus/Variance Report."""
        self.clear_main_menu()
    
        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
    
        tk.Label(header_frame, text="Surplus/Variance Report",
                font=(ui_theme.THEME_FONT, 16, 'bold')).pack(expand=True)
    
        frame = tk.Frame(self.main_menu)
        frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=10)
    
        try:
            self.refresh_data()
    
            if self.inventory_df.empty:
                tk.Label(self.main_menu, text="No inventory data available.").pack(pady=20)
                btn_frame = tk.Frame(self.main_menu)
                btn_frame.pack(pady=10)
                tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
                return
    
            # Date range filter
            filtered_log, start_date, end_date = self.get_filtered_log("Surplus/Variance Report - Date Range")
            if filtered_log is None:
                self.generate_reports()
                return
    
            report_data = build_surplus_report_data(self.inventory_df, filtered_log)
            report_df = pd.DataFrame(report_data)
    
            # Display report in treeview
            columns = ('item_id', 'expected', 'actual', 'variance', 'variance_pct', 'variance_value')
            report_tree = ttk.Treeview(frame, columns=columns, show='headings')
    
            report_tree.heading('item_id', text='Item ID')
            report_tree.heading('expected', text='Expected (Sold + Wastage)')
            report_tree.heading('actual', text='Actual Stock')
            report_tree.heading('variance', text='Variance')
            report_tree.heading('variance_pct', text='Variance %')
            report_tree.heading('variance_value', text='Variance (£)')
    
            report_tree.column('item_id', width=100, anchor='center')
            report_tree.column('expected', width=150, anchor='center')
            report_tree.column('actual', width=120, anchor='center')
            report_tree.column('variance', width=100, anchor='center')
            report_tree.column('variance_pct', width=100, anchor='center')
            report_tree.column('variance_value', width=100, anchor='center')
    
            self._make_sortable(report_tree)
    
            report_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    
            scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=report_tree.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            report_tree.configure(yscrollcommand=scrollbar.set)
            self._bind_treeview_mousewheel(report_tree)
    
            # Insert data
            for _, row in report_df.iterrows():
                variance = row['Variance']
                variance_str = f"{variance:+.1f}"
                variance_pct_str = f"{row['Variance %']:+.1f}%"
                variance_value_str = f"£{row['Variance Value']:+.2f}"
    
                values = (row[COL_ITEM_ID], f"{row['Expected']:.1f}",
                         f"{row['Actual']:.1f}", variance_str, variance_pct_str, variance_value_str)
    
                report_tree.insert('', tk.END, values=values)
    
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")
    
        # Back button
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=10)
    
        tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
    
        self._apply_legacy_theme()


    def generate_division_report(self):
        """Generate and display sales by Division/Category report."""
        self.clear_main_menu()
    
        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
    
        tk.Label(header_frame, text="Division Report",
                font=(ui_theme.THEME_FONT, 16, 'bold')).pack(expand=True)
    
        frame = tk.Frame(self.main_menu)
        frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=10)
    
        try:
            self.refresh_data()
    
            # Date range filter
            filtered_log, start_date, end_date = self.get_filtered_log("Division Report - Date Range")
            if filtered_log is None:
                self.generate_reports()
                return
    
            if filtered_log.empty:
                tk.Label(self.main_menu, text="No transaction data available for selected period.", fg="gray").pack(pady=20)
                btn_frame = tk.Frame(self.main_menu)
                btn_frame.pack(pady=10)
                ttk.Button(btn_frame, text="🔙 Back", command=self.generate_reports, width=15).pack()
                return
    
            division_summary = build_division_report_data(
                self.inventory_df, filtered_log,
                member_discount_pct=int(self.get_member_discount_pct())
            )
    
            if division_summary.empty:
                tk.Label(self.main_menu, text="No sales transactions found for selected period.").pack(pady=20)
                btn_frame = tk.Frame(self.main_menu)
                btn_frame.pack(pady=10)
                tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
                return
    
            # Display in treeview
            columns = ('division', 'qty', 'revenue', 'cost', 'gp', 'gp_pct', 'member_gp', 'member_gp_pct', 'non_member_gp', 'non_member_gp_pct')
            report_tree = ttk.Treeview(frame, columns=columns, show='headings')
    
            report_tree.heading('division', text='Division')
            report_tree.heading('qty', text='Units Sold')
            report_tree.heading('revenue', text='Revenue')
            report_tree.heading('cost', text='Cost')
            report_tree.heading('gp', text='Retail GP')
            report_tree.heading('gp_pct', text='Retail GP%')
            report_tree.heading('member_gp', text='Member GP')
            report_tree.heading('member_gp_pct', text='Member GP%')
            report_tree.heading('non_member_gp', text='Non-Mem GP')
            report_tree.heading('non_member_gp_pct', text='Non-Mem GP%')
    
            report_tree.column('division', width=120, anchor='w')
            report_tree.column('qty', width=70, anchor='center')
            report_tree.column('revenue', width=80, anchor='center')
            report_tree.column('cost', width=80, anchor='center')
            report_tree.column('gp', width=70, anchor='center')
            report_tree.column('gp_pct', width=65, anchor='center')
            report_tree.column('member_gp', width=70, anchor='center')
            report_tree.column('member_gp_pct', width=65, anchor='center')
            report_tree.column('non_member_gp', width=70, anchor='center')
            report_tree.column('non_member_gp_pct', width=65, anchor='center')
    
            self._make_sortable(report_tree)
    
            report_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    
            scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=report_tree.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            report_tree.configure(yscrollcommand=scrollbar.set)
            self._bind_treeview_mousewheel(report_tree)
    
            # Insert data
            for _, row in division_summary.iterrows():
                values = (row['Division'], f"{row['Total Quantity']:.1f}",
                         self.format_currency(row['Total Revenue']),
                         self.format_currency(row['Total Cost']),
                         self.format_currency(row['GP']),
                         f"{row['GP%']:.1f}%",
                         self.format_currency(row['Member GP']),
                         f"{row['Member GP%']:.1f}%",
                         self.format_currency(row['Non-Member GP']),
                         f"{row['Non-Member GP%']:.1f}%")
    
                report_tree.insert('', tk.END, values=values)
    
            # Summary
            summary_frame = tk.Frame(self.main_menu, relief='solid', borderwidth=1)
            summary_frame.pack(pady=10, fill='x', padx=10)
    
            total_revenue = division_summary['Total Revenue'].sum()
            total_member_revenue = division_summary['Member Revenue'].sum()
            total_non_member_revenue = division_summary['Non-Member Revenue'].sum()
            total_cost = division_summary['Total Cost'].sum()
            total_gp = division_summary['GP'].sum()
            total_member_gp = division_summary['Member GP'].sum()
            total_non_member_gp = division_summary['Non-Member GP'].sum()
    
            overall_gp_pct = (total_gp / total_revenue * 100) if total_revenue > 0 else 0
            overall_member_gp_pct = (total_member_gp / total_member_revenue * 100) if total_member_revenue > 0 else 0
            overall_non_member_gp_pct = (total_non_member_gp / total_non_member_revenue * 100) if total_non_member_revenue > 0 else 0
    
            tk.Label(summary_frame, text=f"Total Revenue: {self.format_currency(total_revenue)}", font=(ui_theme.THEME_FONT, 11)).pack(pady=2)
            tk.Label(summary_frame, text=f"Overall Retail GP: {self.format_currency(total_gp)} ({overall_gp_pct:.1f}%)", font=(ui_theme.THEME_FONT, 11, 'bold')).pack(pady=2)
            tk.Label(summary_frame, text=f"Overall Member GP: {self.format_currency(total_member_gp)} ({overall_member_gp_pct:.1f}%)", font=(ui_theme.THEME_FONT, 11, 'bold')).pack(pady=2)
            tk.Label(summary_frame, text=f"Overall Non-Member GP: {self.format_currency(total_non_member_gp)} ({overall_non_member_gp_pct:.1f}%)", font=(ui_theme.THEME_FONT, 11, 'bold')).pack(pady=2)
    
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")
    
        # Back button
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=10)
    
        tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
    
        self._apply_legacy_theme()


    def generate_draught_yield_report(self):
        """Generate and display the Draught Yield Report."""
        self.clear_main_menu()
    
        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
    
        tk.Label(header_frame, text="Draught Yield Report",
                font=(ui_theme.THEME_FONT, 16, 'bold')).pack(expand=True)
    
        frame = tk.Frame(self.main_menu)
        frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=10)
    
        try:
            self.refresh_data()
    
            if self.inventory_df.empty or self.log_df.empty:
                tk.Label(self.main_menu, text="Insufficient data. Need both inventory and transaction data.").pack(pady=20)
                btn_frame = tk.Frame(self.main_menu)
                btn_frame.pack(pady=10)
                tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
                return
    
            # Date range filter
            filtered_log, start_date, end_date = self.get_filtered_log("Draught Yield Report - Date Range")
            if filtered_log is None:
                self.generate_reports()
                return
    
            report_data = build_draught_yield_data(self.inventory_df, filtered_log)
    
            if not report_data:
                tk.Label(self.main_menu, text="No draught yield data found for the selected period.",
                        wraplength=500).pack(pady=20)
                btn_frame = tk.Frame(self.main_menu)
                btn_frame.pack(pady=10)
                tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
                return
    
            report_df = pd.DataFrame(report_data)
    
            # Display report
            columns = ('item_id', 'item_name', 'opening', 'deliveries', 'sales', 'wastage', 'comp', 'consumed', 'actual', 'loss', 'closing', 'yield')
            report_tree = ttk.Treeview(frame, columns=columns, show='headings')
    
            report_tree.heading('item_id', text='Item ID')
            report_tree.heading('item_name', text='Item Name')
            report_tree.heading('opening', text='Opening')
            report_tree.heading('deliveries', text='Deliveries')
            report_tree.heading('sales', text=ACTION_SALES)
            report_tree.heading('wastage', text=ACTION_WASTAGE)
            report_tree.heading('comp', text='Comp')
            report_tree.heading('consumed', text='Exp. Consumed')
            report_tree.heading('actual', text='Actual Consumed')
            report_tree.heading('loss', text='Unrecorded Loss')
            report_tree.heading('closing', text='Closing')
            report_tree.heading('yield', text='Yield %')
    
            report_tree.column('item_id', width=70, anchor='center')
            report_tree.column('item_name', width=140, anchor='w')
            report_tree.column('opening', width=55, anchor='center')
            report_tree.column('deliveries', width=55, anchor='center')
            report_tree.column('sales', width=50, anchor='center')
            report_tree.column('wastage', width=50, anchor='center')
            report_tree.column('comp', width=45, anchor='center')
            report_tree.column('consumed', width=70, anchor='center')
            report_tree.column('actual', width=70, anchor='center')
            report_tree.column('loss', width=70, anchor='center')
            report_tree.column('closing', width=55, anchor='center')
            report_tree.column('yield', width=55, anchor='center')
    
            self._make_sortable(report_tree)
    
            report_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    
            scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=report_tree.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            report_tree.configure(yscrollcommand=scrollbar.set)
    
            for _, row in report_df.iterrows():
                yield_val = row['Yield %']
                yield_str = f"{yield_val:.1f}%"
                tag = ''
                if yield_val < 95 or yield_val > 105:
                    tag = 'yield_warning'
    
                loss_val = row['Unrecorded Loss']
                if abs(loss_val) >= 5:
                    tag = 'loss_warning'
    
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
                         yield_str)
    
                report_tree.insert('', tk.END, values=values, tags=(tag,))
    
            report_tree.tag_configure('yield_warning', background=TBL_ROW_DANGER, foreground=THEME_DANGER)
            report_tree.tag_configure('loss_warning', background=TBL_ROW_WARN, foreground=THEME_WARNING)
    
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")
    
        # Back button
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=10)
    
        tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()


    def generate_stocktake_report(self):
        """Generate and display the Stocktake Variance Report."""
        self.clear_main_menu()
    
        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
    
        tk.Label(header_frame, text="Stocktake Variance Report",
                font=(ui_theme.THEME_FONT, 16, 'bold')).pack(expand=True)
    
        frame = tk.Frame(self.main_menu)
        frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=10)
    
        try:
            self.refresh_data()
    
            if self.inventory_df.empty:
                tk.Label(self.main_menu, text="No inventory data available.").pack(pady=20)
                btn_frame = tk.Frame(self.main_menu)
                btn_frame.pack(pady=10)
                tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
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
                # Keep only the most recent non-baseline entry per item_id
                stocktake_df = stocktake_df.sort_values('timestamp', ascending=False)
                stocktake_df = stocktake_df.drop_duplicates(subset='item_id', keep='first')
    
            from reports import build_stocktake_variance_report
            report_data = build_stocktake_variance_report(self.inventory_df, self.log_df, stocktake_df)
    
            if not report_data:
                tk.Label(self.main_menu, text="No stocktake data available.").pack(pady=20)
                btn_frame = tk.Frame(self.main_menu)
                btn_frame.pack(pady=10)
                tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
                return
    
            report_df = pd.DataFrame(report_data)
    
            # Display report
            columns = ('item_id', 'item_name', 'expected', 'counted', 'variance', 'variance_pct', 'variance_value')
            report_tree = ttk.Treeview(frame, columns=columns, show='headings')
    
            report_tree.heading('item_id', text='Item ID')
            report_tree.heading('item_name', text='Item Name')
            report_tree.heading('expected', text='Expected')
            report_tree.heading('counted', text='Counted')
            report_tree.heading('variance', text='Variance')
            report_tree.heading('variance_pct', text='Var %')
            report_tree.heading('variance_value', text='Value')
    
            report_tree.column('item_id', width=80, anchor='center')
            report_tree.column('item_name', width=160, anchor='w')
            report_tree.column('expected', width=70, anchor='center')
            report_tree.column('counted', width=70, anchor='center')
            report_tree.column('variance', width=70, anchor='center')
            report_tree.column('variance_pct', width=60, anchor='center')
            report_tree.column('variance_value', width=70, anchor='center')
    
            self._make_sortable(report_tree)
    
            report_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    
            scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=report_tree.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            report_tree.configure(yscrollcommand=scrollbar.set)
    
            for _, row in report_df.iterrows():
                has_st = row.get('has_stocktake', False)
                if has_st:
                    expected = f"{row['expected_quantity']:.1f}" if row['expected_quantity'] is not None else '-'
                    counted = f"{row['counted_quantity']:.1f}" if row['counted_quantity'] is not None else '-'
                    variance = row['variance']
                    var_pct = row['variance_pct']
                    var_val = row['variance_value']
                    var_str = f"{variance:+.1f}"
                    var_pct_str = f"{var_pct:+.1f}%"
                    var_val_str = f"£{var_val:.2f}"
                    tag = ''
                    if abs(var_pct) > 5:
                        tag = 'high_variance'
                    elif abs(var_pct) > 2:
                        tag = 'med_variance'
                else:
                    expected = f"{row['expected_quantity']:.1f}" if row['expected_quantity'] is not None else '-'
                    counted = '-'
                    var_str = '-'
                    var_pct_str = '-'
                    var_val_str = '-'
                    tag = 'no_stocktake'
    
                values = (row['item_id'], row['item_name'], expected, counted, var_str, var_pct_str, var_val_str)
                report_tree.insert('', tk.END, values=values, tags=(tag,))
    
            report_tree.tag_configure('high_variance', background=TBL_ROW_DANGER, foreground=THEME_DANGER)
            report_tree.tag_configure('med_variance', background=TBL_ROW_WARN, foreground=THEME_WARNING)
            report_tree.tag_configure('no_stocktake', foreground=THEME_TEXT_MUTED)
    
            # Summary label
            st_items = report_df[report_df['has_stocktake'] == True]
            if not st_items.empty:
                total_var_val = st_items['variance_value'].sum()
                total_var_pct = (st_items['variance'].sum() / st_items['expected_quantity'].sum() * 100) if st_items['expected_quantity'].sum() > 0 else 0
                summary_text = f"Total Variance Value: £{total_var_val:+.2f}  |  Total Variance %: {total_var_pct:+.1f}%  |  Items counted: {len(st_items)} / {len(report_df)}"
                tk.Label(self.main_menu, text=summary_text, font=(ui_theme.THEME_FONT, 10, 'bold')).pack(pady=(5, 0))
    
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")
    
        # Back button
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=10)
    
        tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()


    def generate_reconciliation_report(self):
        """Generate and display the inventory reconciliation report."""
        self.clear_main_menu()
    
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
    
        tk.Label(header_frame, text="Reconciliation Report",
                font=(ui_theme.THEME_FONT, 16, 'bold')).pack(expand=True)
    
        frame = tk.Frame(self.main_menu)
        frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=10)
    
        try:
            self.refresh_data()
    
            if self.inventory_df.empty:
                tk.Label(self.main_menu, text="No inventory data available.").pack(pady=20)
                btn_frame = tk.Frame(self.main_menu)
                btn_frame.pack(pady=10)
                tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
                return
    
            from reports import build_reconciliation_report
            script_dir = get_script_directory()
            report = build_reconciliation_report(self.inventory_df, self.log_df, script_dir=script_dir)
    
            # Summary text area at top
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
                    summary_lines.append(f"{title} ({len(items)}):")
                    for item in items[:5]:
                        summary_lines.append(f"  - {fmt(item)}")
                    if len(items) > 5:
                        summary_lines.append(f"  ... and {len(items) - 5} more")
                    summary_lines.append("")
    
            if not summary_lines:
                summary_lines.append("No issues found. Inventory is fully in sync.")
    
            summary_text = tk.Text(frame, wrap=tk.WORD, height=16, font=(ui_theme.THEME_FONT, 10), bg='white', fg='black')
            summary_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            summary_text.insert(tk.END, f"Generated: {report['generated_at']}\n\n" + "\n".join(summary_lines))
            summary_text.config(state=tk.DISABLED)
    
            scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=summary_text.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            summary_text.configure(yscrollcommand=scrollbar.set)
    
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")
    
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
    
        self._apply_legacy_theme()


    def generate_price_history_report(self):
        """Generate and display price history report from delivery transactions."""
        self.clear_main_menu()
    
        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
    
        tk.Label(header_frame, text="Price History Report",
                font=(ui_theme.THEME_FONT, 16, 'bold')).pack(expand=True)
    
        try:
            self.refresh_data()
    
            if self.log_df.empty:
                tk.Label(self.main_menu, text="No transaction data available.").pack(pady=20)
                btn_frame = tk.Frame(self.main_menu)
                btn_frame.pack(pady=10)
                tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
                return
    
            # Date range filter
            filtered_log, start_date, end_date = self.get_filtered_log("Price History Report - Date Range")
            if filtered_log is None:
                self.generate_reports()
                return
    
            report_data = build_price_history_data(self.inventory_df, filtered_log)
    
            if not report_data:
                tk.Label(self.main_menu, text="No delivery transactions found for selected period.").pack(pady=20)
                btn_frame = tk.Frame(self.main_menu)
                btn_frame.pack(pady=10)
                tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
                return
    
            # Display in treeview
            frame = tk.Frame(self.main_menu)
            frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=10)
    
            columns = ('item_name', 'date', 'supplier', 'cost_price', 'prev_price', 'change')
            tree = ttk.Treeview(frame, columns=columns, show='headings')
            tree.heading('item_name', text='Item')
            tree.heading('date', text='Date')
            tree.heading('supplier', text='Supplier')
            tree.heading('cost_price', text='Cost Price')
            tree.heading('prev_price', text='Previous')
            tree.heading('change', text='Change')
    
            tree.column('item_name', width=200, anchor='w')
            tree.column('date', width=140, anchor='center')
            tree.column('supplier', width=100, anchor='center')
            tree.column('cost_price', width=80, anchor='center')
            tree.column('prev_price', width=80, anchor='center')
            tree.column('change', width=80, anchor='center')
    
            tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    
            scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            tree.configure(yscrollcommand=scrollbar.set)
            self._bind_treeview_mousewheel(tree)
    
            for row in report_data:
                change_str = f"{'+' if row['change'] >= 0 else ''}{row['change']:.2f} ({row['change_pct']:.1f}%)"
                tree.insert('', tk.END, values=(
                    row[COL_ITEM_NAME],
                    row[COL_TIMESTAMP],
                    row[COL_SUPPLIER],
                    f"£{row[COL_COST_PRICE]:.2f}",
                    f"£{row['prev_price']:.2f}",
                    change_str
                ))
    
            # Download button
            download_frame = tk.Frame(self.main_menu)
            download_frame.pack(fill='x', padx=20, pady=10)
            tk.Button(download_frame, text="Download Price History PDF",
                      command=lambda: self.download_price_history_pdf(report_data),
                      width=25).pack(pady=5)
    
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")
    
        # Back button
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()


    def download_price_history_pdf(self, report_data):
        """Generate and save a price history PDF report."""
        try:
            from fpdf import FPDF
    
            class PriceHistoryPDF(FPDF):
                def header(self):
                    self.set_font(ui_theme.THEME_FONT, 'B', 16)
                    self.set_text_color(40, 40, 40)
                    self.cell(0, 10, 'Prestonfield Golf Club - Price History Report', 0, 1, 'C')
                    self.set_font(ui_theme.THEME_FONT, '', 10)
                    self.set_text_color(100, 100, 100)
                    self.cell(0, 5, f'Generated: {datetime.now().strftime(f"{DATE_FORMAT_DISPLAY} at %H:%M")}', 0, 1, 'C')
                    self.ln(5)
    
                def footer(self):
                    self.set_y(-15)
                    self.set_font(ui_theme.THEME_FONT, 'I', 8)
                    self.set_text_color(128, 128, 128)
                    self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')
    
            pdf = PriceHistoryPDF()
            pdf.add_page()
            pdf.set_font(ui_theme.THEME_FONT, '', 9)
    
            # Table header
            pdf.set_fill_color(240, 240, 240)
            pdf.set_font(ui_theme.THEME_FONT, 'B', 9)
            headers = ['Item', 'Date', 'Supplier', 'Cost Price', 'Previous', 'Change']
            widths = [60, 35, 35, 28, 28, 28]
            for h, w in zip(headers, widths):
                pdf.cell(w, 8, h, 1, 0, 'C', True)
            pdf.ln()
    
            pdf.set_font(ui_theme.THEME_FONT, '', 9)
            for row in report_data:
                change_str = f"{'+' if row['change'] >= 0 else ''}{row['change']:.2f}"
                values = [
                    str(row[COL_ITEM_NAME])[:30],
                    str(row[COL_TIMESTAMP])[:16],
                    str(row[COL_SUPPLIER])[:15],
                    f"£{row[COL_COST_PRICE]:.2f}",
                    f"£{row['prev_price']:.2f}",
                    change_str
                ]
                for v, w in zip(values, widths):
                    pdf.cell(w, 7, v, 1, 0, 'C')
                pdf.ln()
    
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"Price_History_Report_{timestamp}.pdf"
            downloads_dir = os.path.expanduser('~/Downloads')
            filepath = os.path.join(downloads_dir, filename)
            pdf.output(filepath)
    
            messagebox.showinfo("Success", f"Price history report saved to:\n{filepath}")
    
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate PDF: {e}")


    def generate_sales_analytics(self):
        """Generate and display comprehensive sales trends and analytics."""
        self.clear_main_menu()
    
        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
    
        tk.Label(header_frame, text="Sales Trends & Analytics",
                font=(ui_theme.THEME_FONT, 16, 'bold')).pack(expand=True)
    
        try:
            self.refresh_data()
    
            if self.log_df.empty:
                tk.Label(self.main_menu, text="No transaction data available for analytics.").pack(pady=20)
                btn_frame = tk.Frame(self.main_menu)
                btn_frame.pack(pady=10)
                tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
                return
    
            # Date range filter
            filtered_log, start_date, end_date = self.get_filtered_log("Sales Analytics - Date Range")
            if filtered_log is None:
                self.generate_reports()
                return
    
            if filtered_log.empty:
                tk.Label(self.main_menu, text="No transaction data available for selected period.").pack(pady=20)
                btn_frame = tk.Frame(self.main_menu)
                btn_frame.pack(pady=10)
                tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
                return
    
            # Temporarily replace log with filtered version for tab methods
            original_log = self.log_df
            self.log_df = filtered_log
            try:
                # Create notebook for tabs
                notebook = ttk.Notebook(self.main_menu)
                notebook.pack(fill='both', expand=True, padx=10, pady=(10, 0))
    
                # Tab 1: Sales by Category
                self._create_category_sales_tab(notebook)
    
                # Tab 2: Fast & Slow Movers
                self._create_movers_tab(notebook)
    
                # Tab 3: Sales Timeline
                self._create_timeline_tab(notebook)
    
                # Tab 4: Profit Margins
                self._create_profit_margins_tab(notebook)
            finally:
                self.log_df = original_log
    
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")
    
        # Back button
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(side='bottom', fill='x', pady=10)
    
        tk.Button(btn_frame, text="Back to Menu", command=self.show_dashboard, width=15).pack()
    
        self._apply_legacy_theme()


    def _create_category_sales_tab(self, notebook):
        """Create the Sales by Category tab."""
        tab = tk.Frame(notebook)
        notebook.add(tab, text="Sales by Category")
    
        # Left frame for chart
        chart_frame = tk.Frame(tab)
        chart_frame.pack(side='left', fill='both', expand=True, padx=5, pady=5)
    
        # Right frame for data table
        table_frame = tk.Frame(tab)
        table_frame.pack(side='right', fill='both', expand=True, padx=5, pady=5)
    
        # Get sales data by category
        sales_df = self.log_df[self.log_df[COL_ACTION] == ACTION_SALES].copy()
    
        if sales_df.empty:
            tk.Label(tab, text="No sales data available.").pack(pady=20)
            return
    
        # Merge with inventory to get categories
        sales_with_cat = sales_df.merge(
            self.inventory_df[[COL_ITEM_ID, COL_ITEM_NAME, COL_CATEGORY]],
            on=COL_ITEM_ID,
            how='left'
        )
    
        # Calculate sales by category
        category_sales = sales_with_cat.groupby(COL_CATEGORY).agg({
            COL_QUANTITY: 'sum',
            COL_ITEM_ID: 'nunique'
        }).reset_index()
        category_sales.columns = [COL_CATEGORY, 'Total Quantity', 'Unique Items']
        category_sales = category_sales.sort_values('Total Quantity', ascending=False)
    
        # Create chart if matplotlib is available
        if MATPLOTLIB_AVAILABLE and not category_sales.empty:
            fig = Figure(figsize=(6, 4), dpi=100)
            ax = fig.add_subplot(111)
    
            colors = ['#2E86AB', '#A23B72', '#F18F01', '#C73E1D', '#3B1F2B', '#95C623']
            bars = ax.bar(category_sales[COL_CATEGORY], category_sales['Total Quantity'],
                         color=colors[:len(category_sales)])
    
            ax.set_xlabel('Category', fontsize=10)
            ax.set_ylabel('Sales Quantity', fontsize=10)
            ax.set_title('Sales Volume by Category', fontsize=12, fontweight='bold')
            ax.tick_params(axis='x', rotation=45)
    
            canvas = FigureCanvasTkAgg(fig, chart_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill='both', expand=True)
        else:
            tk.Label(chart_frame, text="Chart not available\n(install matplotlib for charts)").pack(pady=20)
    
        # Create data table
        tk.Label(table_frame, text="Sales by Category", font=(ui_theme.THEME_FONT, 12, 'bold')).pack(pady=5)
    
        tree = ttk.Treeview(table_frame, columns=('category', 'quantity', 'items'), show='headings', height=8)
        tree.heading('category', text='Category')
        tree.heading('quantity', text='Total Quantity')
        tree.heading('items', text='Unique Items')
        self._make_sortable(tree)
        tree.column('category', width=100, anchor='center')
        tree.column('quantity', width=100, anchor='center')
        tree.column('items', width=100, anchor='center')
    
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
    
        tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        self._bind_treeview_mousewheel(tree)
    
        for _, row in category_sales.iterrows():
            tree.insert('', tk.END, values=(
                row[COL_CATEGORY],
                f"{row['Total Quantity']:.1f}",
                int(row['Unique Items'])
            ))


    def _create_movers_tab(self, notebook):
        """Create the Fast & Slow Movers tab."""
        tab = tk.Frame(notebook)
        notebook.add(tab, text="Fast & Slow Movers")
    
        # Get sales data
        sales_df = self.log_df[self.log_df[COL_ACTION] == ACTION_SALES].copy()
    
        if sales_df.empty:
            tk.Label(tab, text="No sales data available.").pack(pady=20)
            return
    
        # Merge with inventory
        sales_with_info = sales_df.merge(
            self.inventory_df[[COL_ITEM_ID, COL_ITEM_NAME, COL_CATEGORY]],
            on=COL_ITEM_ID,
            how='left'
        )
    
        # Calculate sales by item
        item_sales = sales_with_info.groupby([COL_ITEM_ID, COL_ITEM_NAME, COL_CATEGORY]).agg({
            COL_QUANTITY: 'sum'
        }).reset_index()
        item_sales.columns = [COL_ITEM_ID, COL_ITEM_NAME, COL_CATEGORY, 'Total Sales']
        item_sales = item_sales.sort_values('Total Sales', ascending=False)
    
        # Split into fast and slow movers
        fast_movers = item_sales.head(10)
        slow_movers = item_sales.tail(10)
    
        # Create frames
        left_frame = tk.LabelFrame(tab, text="Fast Movers (Top 10)", font=(ui_theme.THEME_FONT, 10, 'bold'))
        left_frame.pack(side='left', fill='both', expand=True, padx=5, pady=5)
    
        right_frame = tk.LabelFrame(tab, text="Slow Movers (Bottom 10)", font=(ui_theme.THEME_FONT, 10, 'bold'))
        right_frame.pack(side='right', fill='both', expand=True, padx=5, pady=5)
    
        # Fast movers table
        fast_tree = ttk.Treeview(left_frame, columns=('name', 'category', 'sales'), show='headings')
        fast_tree.heading('name', text='Item Name')
        fast_tree.heading('category', text='Category')
        fast_tree.heading('sales', text='Sales Qty')
        self._make_sortable(fast_tree)
        fast_tree.column('name', width=150, anchor='w')
        fast_tree.column('category', width=80, anchor='center')
        fast_tree.column('sales', width=80, anchor='center')
    
        fast_scroll = ttk.Scrollbar(left_frame, orient='vertical', command=fast_tree.yview)
        fast_tree.configure(yscrollcommand=fast_scroll.set)
        fast_tree.pack(side='left', fill='both', expand=True)
        fast_scroll.pack(side='right', fill='y')
        self._bind_treeview_mousewheel(fast_tree)
    
        for _, row in fast_movers.iterrows():
            fast_tree.insert('', tk.END, values=(
                row[COL_ITEM_NAME],
                row[COL_CATEGORY],
                f"{row['Total Sales']:.1f}"
            ))
    
        # Slow movers table
        slow_tree = ttk.Treeview(right_frame, columns=('name', 'category', 'sales'), show='headings')
        slow_tree.heading('name', text='Item Name')
        slow_tree.heading('category', text='Category')
        slow_tree.heading('sales', text='Sales Qty')
        self._make_sortable(slow_tree)
        slow_tree.column('name', width=150, anchor='w')
        slow_tree.column('category', width=80, anchor='center')
        slow_tree.column('sales', width=80, anchor='center')
    
        slow_scroll = ttk.Scrollbar(right_frame, orient='vertical', command=slow_tree.yview)
        slow_tree.configure(yscrollcommand=slow_scroll.set)
        slow_tree.pack(side='left', fill='both', expand=True)
        slow_scroll.pack(side='right', fill='y')
        self._bind_treeview_mousewheel(slow_tree)
    
        for _, row in slow_movers.iterrows():
            slow_tree.insert('', tk.END, values=(
                row[COL_ITEM_NAME],
                row[COL_CATEGORY],
                f"{row['Total Sales']:.1f}"
            ))


    def _create_timeline_tab(self, notebook):
        """Create the Sales Timeline tab."""
        tab = tk.Frame(notebook)
        notebook.add(tab, text="Sales Timeline")
    
        # Get sales data
        sales_df = self.log_df[self.log_df[COL_ACTION] == ACTION_SALES].copy()
    
        if sales_df.empty:
            tk.Label(tab, text="No sales data available.").pack(pady=20)
            return
    
        # Parse timestamps
        sales_df['date'] = pd.to_datetime(sales_df[COL_TIMESTAMP]).dt.date
    
        # Calculate daily sales
        daily_sales = sales_df.groupby('date').agg({
            COL_QUANTITY: 'sum'
        }).reset_index()
    
        # Create chart frame
        chart_frame = tk.Frame(tab)
        chart_frame.pack(fill='both', expand=True, padx=5, pady=5)
    
        # Create chart if matplotlib is available
        if MATPLOTLIB_AVAILABLE and len(daily_sales) > 1:
            fig = Figure(figsize=(10, 5), dpi=100)
            ax = fig.add_subplot(111)
    
            ax.plot(daily_sales['date'], daily_sales[COL_QUANTITY],
                   marker='o', linestyle='-', color='#2E86AB', linewidth=2)
    
            ax.set_xlabel('Date', fontsize=10)
            ax.set_ylabel('Sales Quantity', fontsize=10)
            ax.set_title('Daily Sales Volume Over Time', fontsize=12, fontweight='bold')
            ax.grid(True, alpha=0.3)
    
            # Format x-axis dates
            fig.autofmt_xdate()
    
            canvas = FigureCanvasTkAgg(fig, chart_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill='both', expand=True)
        else:
            tk.Label(chart_frame, text="Timeline chart requires matplotlib\nand multiple days of data.").pack(pady=20)
    
        # Summary stats
        stats_frame = tk.Frame(tab)
        stats_frame.pack(fill='x', padx=5, pady=5)
    
        if not daily_sales.empty:
            avg_daily = daily_sales[COL_QUANTITY].mean()
            max_daily = daily_sales[COL_QUANTITY].max()
            min_daily = daily_sales[COL_QUANTITY].min()
    
            tk.Label(stats_frame, text=f"Average Daily Sales: {avg_daily:.1f} units",
                    font=(ui_theme.THEME_FONT, 10)).pack(anchor='w', pady=2)
            tk.Label(stats_frame, text=f"Highest Daily Sales: {max_daily:.1f} units",
                    font=(ui_theme.THEME_FONT, 10)).pack(anchor='w', pady=2)
            tk.Label(stats_frame, text=f"Lowest Daily Sales: {min_daily:.1f} units",
                    font=(ui_theme.THEME_FONT, 10)).pack(anchor='w', pady=2)


    def _create_profit_margins_tab(self, notebook):
        """Create the Profit Margins tab."""
        tab = tk.Frame(notebook)
        notebook.add(tab, text="Profit Margins")
    
        # Get sales data
        sales_df = self.log_df[self.log_df[COL_ACTION] == ACTION_SALES].copy()
    
        if sales_df.empty:
            tk.Label(tab, text="No sales data available.").pack(pady=20)
            return
    
        # Merge with inventory (avoid duplicate columns by only selecting needed columns)
        inventory_subset = self.inventory_df[[COL_ITEM_ID, COL_ITEM_NAME, COL_CATEGORY, COL_COST_PRICE, COL_SELL_PRICE]].copy()
        inventory_subset.columns = [COL_ITEM_ID, COL_ITEM_NAME, COL_CATEGORY, 'inv_cost_price', 'inv_sell_price']
    
        sales_with_info = sales_df.merge(
            inventory_subset,
            on=COL_ITEM_ID,
            how='left'
        )
    
        # Use inventory prices if log doesn't have them
        sales_with_info['cost_price'] = sales_with_info[COL_COST_PRICE].fillna(sales_with_info['inv_cost_price'])
        sales_with_info['sell_price'] = sales_with_info[COL_SELL_PRICE].fillna(sales_with_info['inv_sell_price'])
    
        # Calculate profit per sale
        sales_with_info['profit_per_unit'] = sales_with_info['sell_price'] - sales_with_info['cost_price']
        sales_with_info['total_profit'] = sales_with_info['profit_per_unit'] * sales_with_info[COL_QUANTITY]
        sales_with_info['profit_margin_pct'] = (sales_with_info['profit_per_unit'] / sales_with_info['sell_price']) * 100
    
        # Aggregate by category
        category_profit = sales_with_info.groupby(COL_CATEGORY).agg({
            'total_profit': 'sum',
            'profit_margin_pct': 'mean',
            COL_QUANTITY: 'sum'
        }).reset_index()
        category_profit.columns = [COL_CATEGORY, 'Total Profit', 'Avg Margin %', 'Quantity Sold']
        category_profit = category_profit.sort_values('Total Profit', ascending=False)
    
        # Create frames
        chart_frame = tk.Frame(tab)
        chart_frame.pack(side='top', fill='both', expand=True, padx=5, pady=5)
    
        table_frame = tk.Frame(tab)
        table_frame.pack(side='bottom', fill='x', padx=5, pady=5)
    
        # Create chart
        if MATPLOTLIB_AVAILABLE and not category_profit.empty:
            fig = Figure(figsize=(8, 4), dpi=100)
            ax = fig.add_subplot(111)
    
            colors = ['#2E86AB', '#A23B72', '#F18F01', '#C73E1D', '#3B1F2B', '#95C623']
            bars = ax.bar(category_profit[COL_CATEGORY], category_profit['Total Profit'],
                         color=colors[:len(category_profit)])
    
            ax.set_xlabel('Category', fontsize=10)
            ax.set_ylabel('Total Profit (£)', fontsize=10)
            ax.set_title('Total Profit by Category', fontsize=12, fontweight='bold')
            ax.tick_params(axis='x', rotation=45)
    
            canvas = FigureCanvasTkAgg(fig, chart_frame)
            canvas.draw()
            canvas.get_tk_widget().pack(fill='both', expand=True)
        else:
            tk.Label(chart_frame, text="Chart not available").pack(pady=10)
    
        # Create data table
        tk.Label(table_frame, text="Profit Analysis by Category", font=(ui_theme.THEME_FONT, 11, 'bold')).pack(pady=5)
    
        tree = ttk.Treeview(table_frame, columns=('category', 'profit', 'margin', 'quantity'), show='headings')
        tree.heading('category', text='Category')
        tree.heading('profit', text='Total Profit (£)')
        tree.heading('margin', text='Avg Margin (%)')
        tree.heading('quantity', text='Qty Sold')
        self._make_sortable(tree)
        tree.column('category', width=100, anchor='center')
        tree.column('profit', width=120, anchor='center')
        tree.column('margin', width=100, anchor='center')
        tree.column('quantity', width=80, anchor='center')
    
        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
    
        tree.pack(side='left', fill='x', expand=True)
        scrollbar.pack(side='right', fill='y')
        self._bind_treeview_mousewheel(tree)
    
        for _, row in category_profit.iterrows():
            tree.insert('', tk.END, values=(
                row[COL_CATEGORY],
                f"£{row['Total Profit']:.2f}",
                f"{row['Avg Margin %']:.1f}%",
                f"{row['Quantity Sold']:.1f}"
            ))


    def generate_reorder_report(self):
        """Display reorder suggestion report."""
        try:
            self.clear_main_menu()
    
            header_frame = tk.Frame(self.main_menu, height=60)
            header_frame.pack(fill='x', pady=(0, 10))
            header_frame.pack_propagate(False)
            tk.Label(header_frame, text="Reorder Suggestions", font=(ui_theme.THEME_FONT, 16, 'bold')).pack(expand=True)
    
            frame = tk.Frame(self.main_menu)
            frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=10)
    
            self.refresh_data()
            report_data = build_reorder_report_data(self.inventory_df, self.log_df)
    
            if not report_data:
                tk.Label(frame, text="No items need reordering. All stock is above reorder level.",
                        font=(ui_theme.THEME_FONT, 12)).pack(pady=20)
                btn_frame = tk.Frame(self.main_menu)
                btn_frame.pack(pady=10)
                tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
                return
    
            columns = ('item_id', 'item_name', 'current_stock', 'reorder_level', 'suggested_order', 'last_delivery', 'supplier')
            tree = ttk.Treeview(frame, columns=columns, show='headings')
            tree.heading('item_id', text='Item ID')
            tree.heading('item_name', text='Item Name')
            tree.heading('current_stock', text='Current Stock')
            tree.heading('reorder_level', text='Reorder Level')
            tree.heading('suggested_order', text='Suggested Order')
            tree.heading('last_delivery', text='Last Delivery')
            tree.heading('supplier', text='Supplier')
            self._make_sortable(tree)
    
            tree.column('item_id', width=80, anchor='center')
            tree.column('item_name', width=150, anchor='w')
            tree.column('current_stock', width=90, anchor='center')
            tree.column('reorder_level', width=90, anchor='center')
            tree.column('suggested_order', width=100, anchor='center')
            tree.column('last_delivery', width=100, anchor='center')
            tree.column('supplier', width=120, anchor='w')
    
            tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            tree.configure(yscrollcommand=scrollbar.set)
            self._bind_treeview_mousewheel(tree)
    
            for item in report_data:
                tree.insert('', tk.END, values=(
                    item[COL_ITEM_ID],
                    item[COL_ITEM_NAME],
                    f"{item[COL_QUANTITY]:.1f}",
                    f"{item[COL_REORDER_LEVEL]:.1f}",
                    f"{item['suggested_order']:.1f}",
                    item['last_delivery_date'] or '-',
                    item[COL_SUPPLIER] or '-'
                ))
    
            summary_frame = tk.Frame(self.main_menu, relief='solid', borderwidth=1)
            summary_frame.pack(pady=10, fill='x', padx=10)
            total_items = len(report_data)
            total_order = sum(i['suggested_order'] for i in report_data)
            tk.Label(summary_frame, text=f"Items to reorder: {total_items}  |  Total suggested order quantity: {total_order:.1f}",
                    font=(ui_theme.THEME_FONT, 11, 'bold')).pack(pady=5)
    
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")
    
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
    
        self._apply_legacy_theme()


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
        """Display period comparison report."""
        try:
            # Get Period A (DateRangeDialog already blocks internally via wait_window)
            dialog_a = DateRangeDialog(self.main_menu, title="Select Period A (Baseline)")
            if not dialog_a.result:
                self.generate_reports()
                return
            if dialog_a.result == 'ALL_TIME':
                start_a, end_a = None, None
            else:
                start_a, end_a = dialog_a.result
    
            # Get Period B
            dialog_b = DateRangeDialog(self.main_menu, title="Select Period B (Comparison)")
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
    
            self.clear_main_menu()
            header_frame = tk.Frame(self.main_menu, height=60)
            header_frame.pack(fill='x', pady=(0, 10))
            header_frame.pack_propagate(False)
            tk.Label(header_frame, text="Period Comparison Report", font=(ui_theme.THEME_FONT, 16, 'bold')).pack(expand=True)
    
            if start_a and end_a:
                period_a_text = f"{start_a.strftime(DATE_FORMAT_DISPLAY)} - {end_a.strftime(DATE_FORMAT_DISPLAY)}"
            else:
                period_a_text = "All Time"
            if start_b and end_b:
                period_b_text = f"{start_b.strftime(DATE_FORMAT_DISPLAY)} - {end_b.strftime(DATE_FORMAT_DISPLAY)}"
            else:
                period_b_text = "All Time"
    
            period_label = tk.Label(self.main_menu,
                    text=f"Period A: {period_a_text}  |  Period B: {period_b_text}",
                    font=(ui_theme.THEME_FONT, 10))
            period_label.pack(pady=5)
    
            frame = tk.Frame(self.main_menu)
            frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=10)
    
            if report_df.empty:
                tk.Label(frame, text="No sales data found for the selected periods.",
                        font=(ui_theme.THEME_FONT, 12)).pack(pady=20)
                btn_frame = tk.Frame(self.main_menu)
                btn_frame.pack(pady=10)
                tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()
                return
    
            columns = ('item_name', 'qty_a', 'qty_b', 'delta_qty',
                       'rev_a', 'rev_b', 'delta_rev',
                       'gp_a', 'gp_b', 'delta_gp', 'delta_gp_pct')
            tree = ttk.Treeview(frame, columns=columns, show='headings')
            tree.heading('item_name', text='Item')
            tree.heading('qty_a', text='A Qty')
            tree.heading('qty_b', text='B Qty')
            tree.heading('delta_qty', text='Δ Qty')
            tree.heading('rev_a', text='A Revenue')
            tree.heading('rev_b', text='B Revenue')
            tree.heading('delta_rev', text='Δ Revenue')
            tree.heading('gp_a', text='A GP')
            tree.heading('gp_b', text='B GP')
            tree.heading('delta_gp', text='Δ GP')
            tree.heading('delta_gp_pct', text='Δ GP%')
            self._make_sortable(tree)
    
            tree.column('item_name', width=120, anchor='w')
            for col in ['qty_a', 'qty_b', 'delta_qty']:
                tree.column(col, width=60, anchor='center')
            for col in ['rev_a', 'rev_b', 'delta_rev', 'gp_a', 'gp_b', 'delta_gp']:
                tree.column(col, width=75, anchor='center')
            tree.column('delta_gp_pct', width=60, anchor='center')
    
            tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            tree.configure(yscrollcommand=scrollbar.set)
            self._bind_treeview_mousewheel(tree)
    
            for _, row in report_df.iterrows():
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
                ))
    
            # Summary
            summary_frame = tk.Frame(self.main_menu, relief='solid', borderwidth=1)
            summary_frame.pack(pady=10, fill='x', padx=10)
            total_rev_a = report_df['total_revenue_a'].sum()
            total_rev_b = report_df['total_revenue_b'].sum()
            total_gp_a = report_df['total_gp_a'].sum()
            total_gp_b = report_df['total_gp_b'].sum()
            tk.Label(summary_frame, text=f"Period A: {self.format_currency(total_rev_a)} revenue, {self.format_currency(total_gp_a)} GP  |  "
                                          f"Period B: {self.format_currency(total_rev_b)} revenue, {self.format_currency(total_gp_b)} GP  |  "
                                          f"Δ GP: {self.format_currency(total_gp_b - total_gp_a)}",
                    font=(ui_theme.THEME_FONT, 11, 'bold')).pack(pady=5)
    
        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")
    
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()


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
                cost_by_id = dict(zip(self.inventory_df[COL_ITEM_ID], self.inventory_df[COL_COST_PRICE]))
                running_surplus_value = sum(
                    float(row['variance']) * float(cost_by_id.get(row['item_id'], 0) or 0)
                    for _, row in all_variance_st_df.iterrows()
                ) if not all_variance_st_df.empty else 0.0
            else:
                running_surplus_value = 0.0
    
            # Compute historical closing stock at end_date for date-range consistency.
            # If a stocktake exists on or before the report end date, use its counted quantities
            # as the authoritative closing stock. This avoids misclassifying CSV-uploaded
            # rows (timestamped after upload but belonging to an earlier period) as
            # post-period transactions.
            closing_stock_map = None
            if end_date is not None:
                end_ts = pd.Timestamp(end_date)
                closing_stock_map = {}
    
                if stocktake_rows:
                    # Find the latest stocktake on or before the report end date
                    st_ts = pd.to_datetime(st_df['timestamp'], errors='coerce')
                    valid_st = st_df[st_ts <= end_ts + pd.Timedelta(days=1)]
                    if not valid_st.empty:
                        latest_st = valid_st.sort_values('timestamp', ascending=False).drop_duplicates(subset='item_id', keep='first')
                        st_closing_map = dict(zip(latest_st['item_id'], latest_st['counted_quantity']))
                        for _, row in self.inventory_df.iterrows():
                            item_id = row[COL_ITEM_ID]
                            closing_stock_map[item_id] = st_closing_map.get(item_id, row[COL_QUANTITY])
    
                if not closing_stock_map:
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
                    for _, row in self.inventory_df.iterrows():
                        item_id = row[COL_ITEM_ID]
                        closing_stock_map[item_id] = row[COL_QUANTITY] - expected_after_end.get(item_id, 0)
    
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
            )
    
            # Generate timestamp for filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"Bar_Stock_Full_Report_{timestamp}.pdf"
    
            # Save to Downloads folder
            downloads_dir = os.path.expanduser('~/Downloads')
            filepath = os.path.join(downloads_dir, filename)
            pdf.output(filepath)
    
            messagebox.showinfo("Report Generated", f"Comprehensive PDF report saved to:\n{filepath}\n\nThe report includes:\n• Stock Summary by Division\n• Sales Performance\n• Wastage & Complimentary Summary\n• Draught Yield Report\n• Financial Summary with Totals\n• Stocktake Variance Report (if recorded)")
            self._apply_legacy_theme()
    
        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate report: {e}")
