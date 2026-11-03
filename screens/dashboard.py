#!/usr/bin/env python3
"""Dashboard screen: the Ledger summary, attention list, top sellers and notices."""

import glob
import os
import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import tkinter as tk
from tkinter import ttk

import data_manager as data_manager_module
import ui_theme
from ui_theme import (
    THEME_ACCENT, THEME_BG, THEME_BORDER, THEME_CARD, THEME_DANGER,
    THEME_PANEL, THEME_SUCCESS, THEME_TEXT, THEME_TEXT_MUTED,
    THEME_WARNING, TBL_ROW_ALT,
)
from app_config import (
    COL_ACTION, COL_COST_PRICE, COL_DATE_RANGE, COL_ITEM_ID, COL_ITEM_NAME,
    COL_MEASURE, COL_QUANTITY, COL_SELL_PRICE, COL_SUPPLIER, COL_TIMESTAMP,
    DATA_DIR,
)
from actions import ACTION_DELIVERY, ACTION_STOCKTAKE_BASELINE, SALE_ACTIONS
from categories import is_delisted, should_exclude
from conversions import DATE_FORMAT_DISPLAY, parse_display_date
from data_manager import (
    InventoryDataManager, COL_REORDER_LEVEL, get_setting, get_upload_hashes,
)
from sales_mapping import is_hidden_from_stock_view
from money import inc_vat, round_money, sum_money
from reports import sales_money_by_item


MEASURE_PLURALS = {
    'pint': 'pints',
    'bottle': 'bottles',
    'can': 'cans',
    'cup': 'cups',
    'measure': 'measures',
    'keg': 'kegs',
    'glass': 'glasses',
    'unit': 'units',
}


class DashboardMixin:
    """Dashboard methods mixed into the main application class."""

    # ------------------------------------------------------------------
    # Screen
    # ------------------------------------------------------------------

    def show_dashboard(self):
        """Render the Ledger dashboard."""
        self._create_app_shell('Dashboard')

        # Notices replace the old filled banners.
        self._render_integrity_alert(self.main_menu)
        self._render_sync_alert(self.main_menu)
        self._render_price_sync_alert(self.main_menu)

        self._render_ledger_summary(self.main_menu)
        self._render_ledger_panels(self.main_menu)
        self._render_deliveries_strip(self.main_menu)
        self._render_dashboard_footer(self.main_menu)

    # ------------------------------------------------------------------
    # Alerts and notices
    # ------------------------------------------------------------------

    def _render_notice(self, parent, label, message, detail='', kind='warning',
                       on_dismiss=None):
        """Render a ruled notice with a coloured left rule and no fill."""
        colour = {
            'danger': THEME_DANGER,
            'warning': THEME_WARNING,
            'success': THEME_SUCCESS,
        }.get(kind, THEME_WARNING)

        notice = tk.Frame(parent, bg=THEME_BG)
        notice.pack(fill='x', pady=(0, 18))
        tk.Frame(notice, bg=colour, width=3).pack(side='left', fill='y')

        body = tk.Frame(notice, bg=THEME_BG)
        body.pack(side='left', fill='x', expand=True, padx=(12, 0), pady=2)

        header = tk.Frame(body, bg=THEME_BG)
        header.pack(fill='x')
        tk.Label(header, text=label.upper(), font=ui_theme.mono_font(9, 'bold'),
                 fg=colour, bg=THEME_BG, anchor='w').pack(side='left')
        if on_dismiss is not None:
            dismiss = tk.Label(header, text="Dismiss", font=(ui_theme.THEME_FONT, 9),
                               fg=THEME_TEXT_MUTED, bg=THEME_BG, cursor='hand2',
                               takefocus=1)
            dismiss.pack(side='right')
            dismiss.bind('<Button-1>', lambda e: on_dismiss())
            dismiss.bind('<Return>', lambda e: on_dismiss())

        tk.Label(body, text=message, font=(ui_theme.THEME_FONT, 10),
                 fg=THEME_TEXT, bg=THEME_BG, anchor='w', justify='left',
                 wraplength=900).pack(fill='x', pady=(4, 0))
        if detail:
            tk.Label(body, text=detail, font=ui_theme.mono_font(8),
                     fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w',
                     justify='left', wraplength=900).pack(fill='x', pady=(3, 0))
        return notice

    def _render_integrity_alert(self, parent=None):
        """Show a notice when live inventory does not reconcile with the log."""
        parent = self._dashboard_parent(parent)
        if parent is None or not getattr(self, 'startup_integrity_report', None):
            return

        def dismiss():
            self.startup_integrity_report = None
            self.show_dashboard()

        self._render_notice(
            parent,
            "Stock reconciliation check",
            "Live inventory does not agree with the transaction log. Run "
            "audit_data.py for the full list before relying on stock values.",
            self.startup_integrity_report,
            kind='danger',
            on_dismiss=dismiss,
        )

    def _render_sync_alert(self, parent=None):
        """Show a notice when tracked items are missing setup rules."""
        parent = self._dashboard_parent(parent)
        if parent is None or not getattr(self, 'startup_sync_report', None):
            return

        report_text = self.startup_sync_report.strip()
        lines = report_text.splitlines()
        if len(lines) > 12:
            report_text = "\n".join(lines[:12]) + f"\n... and {len(lines) - 12} more items"

        def dismiss():
            self.startup_sync_report = None
            self.show_dashboard()

        self._render_notice(
            parent,
            "Inventory setup check",
            "Some tracked items are missing category, conversion, or "
            "order-sheet rules.",
            report_text,
            kind='warning',
            on_dismiss=dismiss,
        )

    def _render_price_sync_alert(self, parent=None):
        """Show a notice when stock.csv cost prices were synced at startup."""
        parent = self._dashboard_parent(parent)
        if parent is None or not getattr(self, 'startup_price_sync_report', None):
            return

        report_text = self.startup_price_sync_report.strip()
        lines = report_text.splitlines()
        if len(lines) > 12:
            report_text = "\n".join(lines[:12]) + f"\n... and {len(lines) - 12} more items"

        def dismiss():
            self.startup_price_sync_report = None
            self.show_dashboard()

        self._render_notice(
            parent,
            "Price sync from stock.csv",
            "Cost prices were updated from the stock file.",
            report_text,
            kind='success',
            on_dismiss=dismiss,
        )

    # ------------------------------------------------------------------
    # Ledger summary
    # ------------------------------------------------------------------

    def update_dashboard_stats(self, parent=None):
        """Refresh the summary in place after a stock movement.

        Kept as the single post-mutation hook used across the screens.  It
        only redraws when the dashboard is the visible screen; otherwise the
        next visit recomputes the snapshot.
        """
        if getattr(self, 'active_tab', '') != 'Dashboard':
            return
        if not hasattr(self, 'main_menu') or not self.main_menu.winfo_exists():
            return
        try:
            self._render_ledger_summary(self.main_menu)
            self._render_ledger_panels(self.main_menu)
            self._render_deliveries_strip(self.main_menu)
        except tk.TclError:
            return

    def _render_ledger_summary(self, parent=None):
        """Render the four ruled headline figures."""
        parent = self._dashboard_parent(parent)
        if parent is None:
            return
        if hasattr(self, 'ledger_summary_frame'):
            self.ledger_summary_frame.destroy()

        snap = self._compute_dashboard_snapshot()
        attention = snap['attention_items']
        attention_note = self._attention_footnote(attention)

        outer = tk.Frame(parent, bg=THEME_BG)
        outer.pack(fill='x', pady=(0, 22))
        self.ledger_summary_frame = outer

        tk.Frame(outer, bg=THEME_BORDER, height=1).pack(fill='x')
        row = tk.Frame(outer, bg=THEME_BG)
        row.pack(fill='x')

        for column in (0, 2, 4, 6):
            row.grid_columnconfigure(column, weight=1, uniform='ledger-kpi')
        for column in (1, 3, 5):
            tk.Frame(row, bg=THEME_BORDER, width=1).grid(
                row=0, column=column, sticky='ns', pady=16)

        sales_note = snap['period_label']
        if snap['period_sales_inc']:
            sales_note = (f"{sales_note} · £{snap['period_sales_inc']:,.2f} "
                          "inc VAT")

        cells = [
            ("Stock holding", f"£{snap['stock_holding']:,.2f}",
             "At cost, ex VAT", THEME_TEXT),
            ("Sales this period", f"£{snap['period_sales']:,.2f}",
             sales_note, THEME_TEXT),
            ("Active lines", f"{snap['active_lines']}",
             f"{snap['lines_with_stock']} holding stock", THEME_TEXT),
            ("Needs attention", f"{len(attention)}",
             attention_note,
             THEME_WARNING if attention else THEME_TEXT),
        ]
        for index, (label, value, note, colour) in enumerate(cells):
            cell = tk.Frame(row, bg=THEME_BG)
            cell.grid(row=0, column=index * 2, sticky='nsew',
                      padx=(0 if index == 0 else 18, 18), pady=16)
            tk.Label(cell, text=label.upper(), font=ui_theme.mono_font(8),
                     fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w').pack(fill='x')
            tk.Label(cell, text=value, font=ui_theme.display_font(30),
                     fg=colour, bg=THEME_BG, anchor='w').pack(fill='x', pady=(2, 0))
            tk.Label(cell, text=note, font=(ui_theme.THEME_FONT, 9),
                     fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w').pack(fill='x')

        tk.Frame(outer, bg=THEME_BORDER, height=1).pack(fill='x')

    @staticmethod
    def _attention_footnote(items):
        tabs = sum(1 for item in items if item['tag'] == 'Tab')
        uploads = sum(1 for item in items if item['tag'] == 'Upload')
        stock = sum(1 for item in items if item['tag'] in ('Negative', 'Low'))
        parts = []
        if tabs:
            parts.append(f"{tabs} stale tab{'s' if tabs != 1 else ''}")
        if uploads:
            parts.append("upload due")
        if stock:
            parts.append(f"{stock} stock item{'s' if stock != 1 else ''}")
        return " · ".join(parts) if parts else "All clear"

    # ------------------------------------------------------------------
    # Panels
    # ------------------------------------------------------------------

    def _render_ledger_panels(self, parent=None):
        """Render the attention list and the top-seller bars side by side."""
        parent = self._dashboard_parent(parent)
        if parent is None:
            return
        if hasattr(self, 'ledger_panels_frame'):
            self.ledger_panels_frame.destroy()

        snap = self._compute_dashboard_snapshot()
        outer = tk.Frame(parent, bg=THEME_BG)
        outer.pack(fill='both', expand=True, pady=(0, 22))
        self.ledger_panels_frame = outer

        outer.grid_columnconfigure(0, weight=1, uniform='ledger-panels')
        outer.grid_columnconfigure(1, weight=1, uniform='ledger-panels')

        left = tk.Frame(outer, bg=THEME_BG)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 24))
        right = tk.Frame(outer, bg=THEME_BG)
        right.grid(row=0, column=1, sticky='nsew', padx=(24, 0))

        self._build_attention_panel(left, snap)
        self._build_top_sellers_panel(right, snap)

    def _panel_heading(self, parent, title, note='', ink_rule=True):
        heading = tk.Frame(parent, bg=THEME_BG)
        heading.pack(fill='x')
        tk.Label(heading, text=title, font=ui_theme.display_font(12),
                 fg=THEME_TEXT, bg=THEME_BG, anchor='w').pack(side='left')
        if note:
            tk.Label(heading, text=note.upper(), font=ui_theme.mono_font(8),
                     fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='e').pack(side='right')
        tk.Frame(parent, bg=THEME_TEXT if ink_rule else THEME_BORDER,
                 height=1).pack(fill='x', pady=(7, 0))

    def _build_attention_panel(self, parent, snap):
        items = snap['attention_items']
        self._panel_heading(parent, "Needs attention",
                            f"{len(items)} item{'s' if len(items) != 1 else ''}")

        if not items:
            tk.Label(parent, text="Nothing needs attention.",
                     font=(ui_theme.THEME_FONT, 10), fg=THEME_SUCCESS,
                     bg=THEME_BG, anchor='w').pack(fill='x', pady=(10, 0))
        else:
            for index, item in enumerate(items):
                if index:
                    tk.Frame(parent, bg=THEME_BORDER, height=1).pack(fill='x')
                row = tk.Frame(parent, bg=THEME_BG)
                row.pack(fill='x', pady=8)
                text = tk.Frame(row, bg=THEME_BG)
                text.pack(side='left', fill='x', expand=True)
                tk.Label(text, text=item['name'], font=ui_theme.display_font(11),
                         fg=THEME_TEXT, bg=THEME_BG, anchor='w').pack(fill='x')
                tk.Label(text, text=item['detail'], font=(ui_theme.THEME_FONT, 9),
                         fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w').pack(fill='x')
                tk.Label(row, text=item['tag'].upper(), font=ui_theme.mono_font(8),
                         fg=THEME_WARNING, bg=THEME_BG, padx=8, pady=2,
                         bd=1, relief='solid').pack(side='right', padx=(12, 0))

        uploads = snap['recent_sales_uploads']
        if not uploads:
            return

        tk.Frame(parent, bg=THEME_BORDER, height=1).pack(fill='x', pady=(16, 0))
        sub = tk.Frame(parent, bg=THEME_BG)
        sub.pack(fill='x')
        tk.Label(sub, text="Latest sales uploads", font=ui_theme.display_font(11),
                 fg=THEME_TEXT, bg=THEME_BG, anchor='w').pack(side='left', pady=(10, 0))
        tk.Label(sub, text="INC VAT", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='e').pack(
            side='right', pady=(10, 0))
        tk.Frame(parent, bg=THEME_TEXT, height=1).pack(fill='x', pady=(6, 0))

        for index, upload in enumerate(uploads):
            if index:
                tk.Frame(parent, bg=THEME_BORDER, height=1).pack(fill='x')
            row = tk.Frame(parent, bg=THEME_BG)
            row.pack(fill='x', pady=7)
            text = tk.Frame(row, bg=THEME_BG)
            text.pack(side='left', fill='x', expand=True)
            tk.Label(text, text=upload['period'], font=ui_theme.display_font(10),
                     fg=THEME_TEXT, bg=THEME_BG, anchor='w').pack(fill='x')
            tk.Label(text, text=f"{upload['lines']} lines · {upload['qty']:,.0f} units",
                     font=ui_theme.mono_font(8), fg=THEME_TEXT_MUTED,
                     bg=THEME_BG, anchor='w').pack(fill='x')
            # Inc VAT first — it is the figure the EPOS export totals — with the
            # ex-VAT revenue (what every report uses) underneath.
            value_box = tk.Frame(row, bg=THEME_BG)
            value_box.pack(side='right', padx=(12, 0))
            tk.Label(value_box, text=f"£{upload.get('value_inc', inc_vat(upload['value'])):,.2f}",
                     font=ui_theme.display_font(11, 'bold'),
                     fg=THEME_TEXT, bg=THEME_BG, anchor='e').pack(fill='x')
            tk.Label(value_box, text=f"£{upload['value']:,.2f} ex VAT",
                     font=ui_theme.mono_font(8), fg=THEME_TEXT_MUTED,
                     bg=THEME_BG, anchor='e').pack(fill='x')

    def _build_top_sellers_panel(self, parent, snap):
        sellers = snap['top_sellers']
        # The card below is "Since 1 November" after a baseline reset, so a
        # hard-coded month here goes stale the moment a new baseline is set.
        period = str(snap.get('period_label') or '')
        heading = (f"Most sold {period[0].lower() + period[1:]}"
                   if period.startswith('Since ') else "Most sold")
        self._panel_heading(parent, heading, "Inc VAT")

        if not sellers:
            tk.Label(parent, text="No sales recorded since the baseline.",
                     font=(ui_theme.THEME_FONT, 10), fg=THEME_TEXT_MUTED,
                     bg=THEME_BG, anchor='w').pack(fill='x', pady=(10, 0))
            return

        largest = max((seller['value'] for seller in sellers), default=0) or 1
        for seller in sellers:
            block = tk.Frame(parent, bg=THEME_BG)
            block.pack(fill='x', pady=(10, 0))

            top = tk.Frame(block, bg=THEME_BG)
            top.pack(fill='x')
            tk.Label(top, text=seller['name'], font=(ui_theme.THEME_FONT, 11),
                     fg=THEME_TEXT, bg=THEME_BG, anchor='w').pack(side='left')
            # Inc VAT is the figure an EPOS export totals, so it leads; the
            # ex-VAT revenue every report uses sits underneath it.
            value_box = tk.Frame(top, bg=THEME_BG)
            value_box.pack(side='right')
            tk.Label(value_box,
                     text=f"£{seller.get('value_inc', inc_vat(seller['value'])):,.2f}",
                     font=ui_theme.display_font(11, 'bold'),
                     fg=THEME_TEXT, bg=THEME_BG, anchor='e').pack(fill='x')
            tk.Label(value_box, text=f"£{seller['value']:,.2f} ex VAT",
                     font=ui_theme.mono_font(8), fg=THEME_TEXT_MUTED,
                     bg=THEME_BG, anchor='e').pack(fill='x')

            track = tk.Frame(block, bg=TBL_ROW_ALT, height=5)
            track.pack(fill='x', pady=(6, 0))
            track.pack_propagate(False)
            fill = tk.Frame(track, bg=THEME_ACCENT)
            fill.place(relx=0, rely=0, relheight=1,
                       relwidth=max(0.03, seller['value'] / largest))

            tk.Label(block, text=seller['qty_label'], font=ui_theme.mono_font(8),
                     fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w').pack(
                fill='x', pady=(4, 2))

    def _render_deliveries_strip(self, parent=None):
        """Render the one-line latest-deliveries strip."""
        parent = self._dashboard_parent(parent)
        if parent is None:
            return
        if hasattr(self, 'deliveries_strip_frame'):
            self.deliveries_strip_frame.destroy()

        snap = self._compute_dashboard_snapshot()
        deliveries = snap['recent_deliveries']
        if not deliveries:
            return

        outer = tk.Frame(parent, bg=THEME_BG)
        outer.pack(fill='x', pady=(0, 10))
        self.deliveries_strip_frame = outer
        tk.Frame(outer, bg=THEME_BORDER, height=1).pack(fill='x')

        line = tk.Frame(outer, bg=THEME_BG)
        line.pack(fill='x', pady=(10, 0))
        tk.Label(line, text="LATEST DELIVERIES", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG).pack(side='left', padx=(0, 22))
        for delivery in deliveries:
            tk.Label(line,
                     text=f"{delivery['date']} · {delivery['supplier']} · "
                          f"{delivery['lines']} line{'s' if delivery['lines'] != 1 else ''}",
                     font=ui_theme.mono_font(8), fg=THEME_TEXT_MUTED,
                     bg=THEME_BG).pack(side='left', padx=(0, 20))

    def _render_dashboard_footer(self, parent):
        footer = self.themed_frame(parent)
        footer.pack(fill='x', pady=(6, 0))

        latest_backup = "None"
        try:
            backups = sorted(
                glob.glob(os.path.join(DATA_DIR, 'backups', 'barstock_*.db')),
                key=os.path.getmtime, reverse=True)
            if backups:
                mtime = os.path.getmtime(backups[0])
                latest_backup = datetime.fromtimestamp(mtime).strftime(DATE_FORMAT_DISPLAY)
        except Exception:
            latest_backup = "Unknown"

        last_saved = "Not yet saved"
        saved_raw = get_setting('last_saved_at')
        if saved_raw:
            try:
                saved_dt = datetime.strptime(saved_raw, '%Y-%m-%d %H:%M:%S')
                last_saved = saved_dt.strftime(f'{DATE_FORMAT_DISPLAY} %H:%M')
            except (TypeError, ValueError):
                last_saved = str(saved_raw)

        tk.Label(
            footer,
            text=(f"Created by Chris Armstrong   ·   Latest backup {latest_backup}"
                  f"   ·   Last saved {last_saved}"),
            font=ui_theme.mono_font(8), fg=THEME_TEXT_MUTED, bg=THEME_BG,
            anchor='e').pack(side='right')

    # ------------------------------------------------------------------
    # Snapshot
    # ------------------------------------------------------------------

    def _dashboard_cache_key(self):
        """Cheap fingerprint of the data the dashboard aggregates."""
        log_len = len(self.log_df)
        latest = ''
        if log_len and COL_TIMESTAMP in self.log_df.columns:
            try:
                latest = str(self.log_df[COL_TIMESTAMP].max())
            except Exception:
                latest = ''
        qty_sum = 0.0
        value_sum = 0.0
        if not self.inventory_df.empty:
            try:
                qty = pd.to_numeric(self.inventory_df.get(COL_QUANTITY, 0), errors='coerce').fillna(0)
                cost = pd.to_numeric(self.inventory_df.get(COL_COST_PRICE, 0), errors='coerce').fillna(0)
                qty_sum = float(qty.sum())
                value_sum = float((qty * cost).sum())
            except Exception:
                pass
        try:
            tab_count = len(InventoryDataManager.get_open_tabs(status='open'))
        except Exception:
            tab_count = 0
        try:
            upload_count = len(get_upload_hashes())
        except Exception:
            upload_count = 0
        return (log_len, latest, len(self.inventory_df),
                round(qty_sum, 4), round(value_sum, 4),
                tab_count, upload_count)

    def _compute_dashboard_snapshot(self):
        """Return the dashboard aggregation, memoised against the data."""
        key = self._dashboard_cache_key()
        cached = getattr(self, '_dashboard_snapshot_cache', None)
        if cached is not None and cached[0] == key:
            return cached[1]
        result = self._compute_dashboard_snapshot_uncached()
        self._dashboard_snapshot_cache = (key, result)
        return result

    def _compute_dashboard_snapshot_uncached(self):
        """Return the values the Ledger dashboard draws."""
        result = {
            'period_sales': 0.0,
            'period_sales_inc': 0.0,
            'period_label': 'No sales data',
            'stock_holding': 0.0,
            'active_lines': 0,
            'lines_with_stock': 0,
            'recent_sales_uploads': [],
            'recent_deliveries': [],
            'top_sellers': [],
            'attention_items': [],
        }

        measure_by_id = {}
        name_by_id = {}
        if not self.inventory_df.empty and COL_ITEM_ID in self.inventory_df.columns:
            for _, item in self.inventory_df.iterrows():
                item_id = str(item[COL_ITEM_ID])
                if is_hidden_from_stock_view(item_id) or is_delisted(item_id):
                    continue
                measure_by_id[item_id] = str(item.get(COL_MEASURE, '') or '')
                name_by_id[item_id] = str(item.get(COL_ITEM_NAME, item_id))
            result['active_lines'] = len(measure_by_id)
            qty_series = pd.to_numeric(
                self.inventory_df.get(COL_QUANTITY, 0), errors='coerce').fillna(0)
            holding_ids = set(
                self.inventory_df.loc[qty_series > 0, COL_ITEM_ID].astype(str)
                if COL_ITEM_ID in self.inventory_df.columns else [])
            result['lines_with_stock'] = len(holding_ids & set(measure_by_id))

        # Stock holding value at cost price. Delisted lines are excluded, in
        # line with the report's Total Stock Value: they no longer hold stock.
        if not self.inventory_df.empty:
            qty = pd.to_numeric(self.inventory_df.get(COL_QUANTITY, 0), errors='coerce').fillna(0)
            cost = pd.to_numeric(self.inventory_df.get(COL_COST_PRICE, 0), errors='coerce').fillna(0)
            active_mask = ~self.inventory_df[COL_ITEM_ID].astype(str).map(is_delisted)
            result['stock_holding'] = sum_money(qty[active_mask] * cost[active_mask])

        if self.log_df.empty or COL_ACTION not in self.log_df.columns:
            result['attention_items'] = self._compute_attention_items()
            return result

        log = self.log_df.copy()
        log['_ts'] = pd.to_datetime(log[COL_TIMESTAMP], errors='coerce')

        # Period start: latest baseline reset, otherwise the first sale.
        baseline_ts = None
        baseline_rows = log[log[COL_ACTION] == ACTION_STOCKTAKE_BASELINE]
        if not baseline_rows.empty:
            baseline_ts = baseline_rows['_ts'].max()
        sales_rows = log[log[COL_ACTION].isin(SALE_ACTIONS)]
        if baseline_ts is None and not sales_rows.empty:
            baseline_ts = sales_rows['_ts'].min()

        period_sales = 0.0
        period_rows = sales_rows
        item_money = None
        if not sales_rows.empty and baseline_ts is not None:
            period_rows = sales_rows[sales_rows['_ts'] >= baseline_ts]
            # Canonical penny allocation shared with every report, so the
            # dashboard total is the same figure the GP, Division and
            # comprehensive reports show.
            item_money = sales_money_by_item(
                period_rows, int(self.get_member_discount_pct()))
            if not item_money.empty:
                period_sales = sum_money(item_money['total_revenue'])
            if baseline_rows.empty:
                result['period_label'] = 'All recorded sales'
            else:
                result['period_label'] = f"Since {baseline_ts.strftime('%-d %B')}"
        result['period_sales'] = period_sales
        # The EPOS exports are inc-VAT, so the dashboard shows the same total
        # both ways and an upload can be checked against the CSV at a glance.
        result['period_sales_inc'] = inc_vat(period_sales)

        # Recent sales uploads: period, value, lines and units.
        uploads = sales_rows[sales_rows.get(COL_DATE_RANGE, '').astype(str).str.strip() != '']
        if not uploads.empty:
            uploads = uploads.copy()
            uploads['_value'] = (
                pd.to_numeric(uploads.get(COL_QUANTITY, 0), errors='coerce').fillna(0)
                * pd.to_numeric(uploads.get(COL_SELL_PRICE, 0), errors='coerce').fillna(0))
            grouped = uploads.groupby(COL_DATE_RANGE).agg(
                _ts=('_ts', 'min'),
                qty=(COL_QUANTITY, 'sum'),
                value=('_value', 'sum'),
                lines=(COL_QUANTITY, 'size'),
            ).reset_index().sort_values('_ts', ascending=False).head(2)
            for _, row in grouped.iterrows():
                value = round_money(row['value'])
                result['recent_sales_uploads'].append({
                    'period': self._format_period_short(str(row[COL_DATE_RANGE])),
                    'qty': float(row['qty']),
                    'value': value,
                    'value_inc': inc_vat(value),
                    'lines': int(row['lines']),
                })

        # Top sellers since the baseline.
        if not period_rows.empty:
            seller_rows = period_rows.copy()
            seller_rows['_qty'] = pd.to_numeric(
                seller_rows.get(COL_QUANTITY, 0), errors='coerce').fillna(0)
            seller_rows['_price'] = pd.to_numeric(
                seller_rows.get(COL_SELL_PRICE, 0), errors='coerce').fillna(0)
            seller_rows['_value'] = seller_rows['_qty'] * seller_rows['_price']
            seller_rows['_key'] = seller_rows.get(
                COL_ITEM_ID, seller_rows.get(COL_ITEM_NAME, '')).astype(str)
            agg_kwargs = {
                'qty': ('_qty', 'sum'),
                'value': ('_value', 'sum'),
            }
            if COL_ITEM_NAME in seller_rows.columns:
                agg_kwargs['name'] = (COL_ITEM_NAME, 'last')
            grouped = seller_rows.groupby('_key').agg(
                **agg_kwargs).reset_index()
            sellers = []
            for _, seller in grouped.iterrows():
                item_id = seller['_key']
                if item_money is not None and item_id in item_money.index:
                    value = float(item_money.loc[item_id, 'total_revenue'])
                else:
                    value = round_money(seller['value'])
                sellers.append((value, item_id, float(seller['qty']),
                                str(seller.get('name', item_id))))
            sellers.sort(key=lambda entry: entry[0], reverse=True)
            for value, item_id, qty, fallback_name in sellers[:5]:
                name = name_by_id.get(item_id) or fallback_name
                measure = measure_by_id.get(item_id, '')
                result['top_sellers'].append({
                    'name': name,
                    'value': value,
                    'value_inc': inc_vat(value),
                    'qty': qty,
                    'qty_label': self._quantity_label(qty, measure),
                })

        # Recent deliveries (grouped by timestamp + supplier).
        deliveries = log[log[COL_ACTION] == ACTION_DELIVERY].copy()
        if not deliveries.empty:
            deliveries[COL_SUPPLIER] = deliveries.get(COL_SUPPLIER, '').fillna('')
            grouped = deliveries.groupby([COL_TIMESTAMP, COL_SUPPLIER]).size().reset_index(name='count')
            grouped['_ts_dt'] = pd.to_datetime(grouped[COL_TIMESTAMP], errors='coerce')
            grouped = grouped.sort_values('_ts_dt', ascending=False).head(3)
            for _, row in grouped.iterrows():
                ts = row['_ts_dt']
                date_text = self._short_day(ts) if pd.notna(ts) else str(row[COL_TIMESTAMP])[:10]
                result['recent_deliveries'].append({
                    'date': date_text,
                    'supplier': str(row[COL_SUPPLIER]) or '-',
                    'lines': int(row['count']),
                })

        result['attention_items'] = self._compute_attention_items()
        return result

    def _compute_attention_items(self):
        """Build the truthful attention list: stale tabs, upload age, stock.

        Reorder levels are zero for every live item, so the old "below reorder"
        rule contributes nothing; stale tabs and an overdue sales upload are
        what actually needs chasing.
        """
        items = []

        try:
            # Query the tab table directly so each tab appears once, not once
            # per item row.
            conn = sqlite3.connect(
                f'file:{data_manager_module.DB_PATH}?mode=ro', uri=True)
            try:
                tab_rows = conn.execute(
                    "SELECT customer_name, created_at FROM open_tabs "
                    "WHERE status = 'open' ORDER BY created_at").fetchall()
            finally:
                conn.close()
            cutoff = datetime.now() - timedelta(days=7)
            for customer_name, created_at in tab_rows:
                if not created_at:
                    continue
                try:
                    created_dt = datetime.fromisoformat(
                        str(created_at).replace('Z', '+00:00')).replace(tzinfo=None)
                except Exception:
                    continue
                if created_dt < cutoff:
                    items.append({
                        'name': str(customer_name or 'Open tab'),
                        'detail': f"Tab open since {self._short_date(created_dt)}",
                        'tag': 'Tab',
                    })
        except Exception:
            pass

        try:
            uploads = [h for h in get_upload_hashes() if h.get('type') == 'sales']
            if uploads:
                latest = max(uploads, key=lambda h: h.get('timestamp', ''))
                uploaded = self._parse_timestamp(latest.get('timestamp'))
                if uploaded and datetime.now() - uploaded > timedelta(days=8):
                    items.append({
                        'name': 'Sales upload',
                        'detail': f"Last sales file {self._short_date(uploaded)}",
                        'tag': 'Upload',
                    })
        except Exception:
            pass

        if not self.inventory_df.empty and COL_ITEM_ID in self.inventory_df.columns:
            for _, row in self.inventory_df.iterrows():
                item_id = row[COL_ITEM_ID]
                if (is_hidden_from_stock_view(item_id) or should_exclude(item_id)
                        or is_delisted(item_id)):
                    continue
                try:
                    qty = float(row[COL_QUANTITY])
                    reorder = float(row.get(COL_REORDER_LEVEL, 0) or 0)
                except (TypeError, ValueError):
                    continue
                name = str(row.get(COL_ITEM_NAME, item_id))
                measure = str(row.get(COL_MEASURE, '') or '')
                if qty < 0:
                    items.append({
                        'name': name,
                        'detail': f"{qty:.0f} {measure.lower()} on hand".replace('  ', ' '),
                        'tag': 'Negative',
                    })
                elif reorder > 0 and qty <= reorder:
                    items.append({
                        'name': name,
                        'detail': f"{qty:.0f} {measure.lower()} left".replace('  ', ' '),
                        'tag': 'Low',
                    })

        seen = set()
        unique = []
        for item in items:
            key = (item['name'], item['tag'])
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    # ------------------------------------------------------------------
    # Formatting helpers
    # ------------------------------------------------------------------

    def _dashboard_parent(self, parent):
        if parent is not None:
            return parent
        menu = getattr(self, 'main_menu', None)
        if menu is not None and menu.winfo_exists():
            return menu
        return None

    @staticmethod
    def _parse_timestamp(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(
                str(value).replace('Z', '+00:00')).replace(tzinfo=None)
        except Exception:
            return None

    @staticmethod
    def _short_date(dt):
        if dt.year == datetime.now().year:
            return f"{dt.day} {dt:%B}"
        return f"{dt.day} {dt:%B %Y}"

    @staticmethod
    def _short_day(dt):
        return f"{dt.day} {dt:%b}"

    @staticmethod
    def _quantity_label(qty, measure):
        unit = MEASURE_PLURALS.get(str(measure).lower(), str(measure).lower() or 'units')
        if qty == 1 and unit.endswith('s'):
            unit = unit[:-1]
        return f"{qty:,.0f} {unit}"

    def _format_period_short(self, period_raw):
        """Turn '05/10/2026 - 11/10/2026' into '5–11 October'."""
        if not period_raw:
            return period_raw
        for sep in (' - ', ' – ', ' to '):
            if sep in period_raw:
                parts = period_raw.split(sep)
                if len(parts) == 2:
                    try:
                        start = parse_display_date(parts[0].strip())
                        end = parse_display_date(parts[1].strip())
                    except Exception:
                        break
                    if (start.year == end.year and start.month == end.month):
                        return f"{start.day}–{end.day} {end:%B}"
                    if start.year == end.year:
                        return f"{start.day} {start:%B} – {end.day} {end:%B}"
                    return (f"{start.day} {start:%B %Y} – "
                            f"{end.day} {end:%B %Y}")
                break
        try:
            single = parse_display_date(period_raw)
            return self._short_date(single)
        except Exception:
            return period_raw

    def _format_period_display(self, period_raw):
        """Convert a raw period string to DD-MM-YYYY display format if possible."""
        if not period_raw:
            return period_raw
        for sep in (' - ', ' – ', ' to '):
            if sep in period_raw:
                parts = period_raw.split(sep)
                if len(parts) == 2:
                    return (f"{self._format_date_display(parts[0].strip())}{sep}"
                            f"{self._format_date_display(parts[1].strip())}")
                break
        return self._format_date_display(period_raw)

    def _format_date_display(self, date_str):
        """Convert any ISO/legacy display date string to DD-MM-YYYY."""
        if not date_str:
            return date_str
        try:
            return parse_display_date(date_str).strftime(DATE_FORMAT_DISPLAY)
        except Exception:
            return date_str
