#!/usr/bin/env python3
"""Dashboard screen: statistics, alerts, snapshot and attention table."""

import glob
import os
import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import tkinter as tk
from tkinter import ttk

import ui_theme
from ui_theme import (
    THEME_ACCENT, THEME_BORDER, THEME_CARD, THEME_DANGER, THEME_PANEL,
    THEME_SUCCESS, THEME_TEXT, THEME_TEXT_MUTED, THEME_WARNING,
    TBL_ROW_ALT, TBL_ROW_WARN, TBL_ROW_DANGER,
)
from app_config import (
    COL_ACTION, COL_COST_PRICE, COL_DATE_RANGE, COL_ITEM_ID, COL_ITEM_NAME,
    COL_MEASURE, COL_QUANTITY, COL_SELL_PRICE, COL_SUPPLIER, COL_TIMESTAMP,
    DATA_DIR, get_resource_path,
)
from actions import ACTION_DELIVERY, ACTION_STOCKTAKE_BASELINE, SALE_ACTIONS
from categories import is_delisted, should_exclude
from conversions import DATE_FORMAT_DISPLAY, parse_display_date
from data_manager import (
    InventoryDataManager, COL_REORDER_LEVEL, get_setting, get_upload_hashes,
)
from reports import build_surplus_report_data
from sales_mapping import is_hidden_from_stock_view


class DashboardMixin:
    """Dashboard methods mixed into the main application class."""

    def show_dashboard(self):
        """Render the simplified dashboard."""
        self._create_app_shell('Dashboard')

        # Header
        header = self.themed_frame(self.main_menu)
        header.pack(fill='x', pady=(0, 20))
        self.themed_label(header, "Dashboard",
                          font=(ui_theme.THEME_FONT, 24, 'bold')).pack(side='left')

        # Reconciliation banner (inventory must agree with its transaction log)
        self._render_integrity_alert(self.main_menu)

        # Sync/setup banner (non-blocking, shown only when there are real issues)
        self._render_sync_alert(self.main_menu)

        # Price-sync banner (non-blocking, shown when stock.csv changed costs)
        self._render_price_sync_alert(self.main_menu)

        # Stat cards
        self.update_dashboard_stats(self.main_menu)

        # Snapshot details
        self._render_dashboard_snapshot(self.main_menu)

        # Items needing attention
        self._section_title(self.main_menu, "Items needing attention").pack(fill='x', pady=(20, 10))
        self._render_attention_table(self.main_menu)

        # Footer
        footer = self.themed_frame(self.main_menu)
        footer.pack(fill='x', pady=(20, 0))
        self.themed_label(footer, "Created by Chris Armstrong",
                          font=(ui_theme.THEME_FONT, 9, 'italic'),
                          fg=THEME_TEXT_MUTED).pack(side='right')


    def _render_integrity_alert(self, parent=None):
        """Show a banner when live inventory does not reconcile with the log."""
        if parent is None:
            if not hasattr(self, 'main_menu') or not self.main_menu.winfo_exists():
                return
            parent = self.main_menu

        if not getattr(self, 'startup_integrity_report', None):
            return

        banner = tk.Frame(parent, bg='#3d1f1f', bd=1, relief='solid',
                          highlightbackground=THEME_DANGER, highlightthickness=1)
        banner.pack(fill='x', pady=(0, 18), padx=2)

        tk.Label(banner, text='⚠ Stock Reconciliation Check',
                 font=(ui_theme.THEME_FONT, 11, 'bold'), fg=THEME_DANGER, bg='#3d1f1f',
                 anchor='w').pack(fill='x', padx=12, pady=(10, 2))

        tk.Label(banner,
                 text=('Live inventory does not agree with the transaction log. '
                       'Run audit_data.py for the full list before relying on stock values.'),
                 font=(ui_theme.THEME_FONT, 10), fg=THEME_TEXT, bg='#3d1f1f',
                 anchor='w', justify='left', wraplength=700).pack(fill='x', padx=12, pady=(0, 4))

        tk.Label(banner, text=self.startup_integrity_report,
                 font=(ui_theme.THEME_FONT, 9), fg=THEME_TEXT_MUTED, bg='#3d1f1f',
                 anchor='w', justify='left', wraplength=700).pack(fill='x', padx=12, pady=(0, 4))

        def dismiss():
            self.startup_integrity_report = None
            banner.destroy()

        self.styled_button(banner, 'Dismiss', dismiss, width=12,
                           variant='ghost').pack(anchor='e', padx=12, pady=(0, 10))


    def _render_sync_alert(self, parent=None):
        """Show a non-blocking setup/sync banner if issues were detected at startup."""
        if parent is None:
            if not hasattr(self, 'main_menu') or not self.main_menu.winfo_exists():
                return
            parent = self.main_menu

        if not hasattr(self, 'startup_sync_report') or not self.startup_sync_report:
            return

        # Trim huge order-sheet-only reports so the banner isn't overwhelming
        report_text = self.startup_sync_report.strip()
        lines = report_text.splitlines()
        if len(lines) > 12:
            report_text = "\n".join(lines[:12]) + f"\n... and {len(lines) - 12} more items"

        banner = tk.Frame(parent, bg='#3d2e1f', bd=1, relief='solid',
                          highlightbackground=THEME_ACCENT, highlightthickness=1)
        banner.pack(fill='x', pady=(0, 18), padx=2)

        tk.Label(banner, text='⚠ Inventory Setup Check',
                 font=(ui_theme.THEME_FONT, 11, 'bold'), fg=THEME_WARNING, bg='#3d2e1f',
                 anchor='w').pack(fill='x', padx=12, pady=(10, 2))

        text = tk.Label(banner,
                        text='Some tracked items are missing category, conversion, or order-sheet rules.',
                        font=(ui_theme.THEME_FONT, 10), fg=THEME_TEXT, bg='#3d2e1f',
                        anchor='w', justify='left', wraplength=700)
        text.pack(fill='x', padx=12, pady=(0, 4))

        detail = tk.Label(banner, text=report_text,
                          font=(ui_theme.THEME_FONT, 9), fg=THEME_TEXT_MUTED, bg='#3d2e1f',
                          anchor='w', justify='left', wraplength=700)
        detail.pack(fill='x', padx=12, pady=(0, 4))

        def dismiss():
            self.startup_sync_report = None
            banner.destroy()

        self.styled_button(banner, 'Dismiss', dismiss, width=12, variant='ghost').pack(anchor='e', padx=12, pady=(0, 10))


    def _render_price_sync_alert(self, parent=None):
        """Show a non-blocking banner when stock.csv cost prices were synced at startup."""
        if parent is None:
            if not hasattr(self, 'main_menu') or not self.main_menu.winfo_exists():
                return
            parent = self.main_menu

        if not hasattr(self, 'startup_price_sync_report') or not self.startup_price_sync_report:
            return

        report_text = self.startup_price_sync_report.strip()
        lines = report_text.splitlines()
        if len(lines) > 12:
            report_text = "\n".join(lines[:12]) + f"\n... and {len(lines) - 12} more items"

        banner = tk.Frame(parent, bg='#1f3d2e', bd=1, relief='solid',
                          highlightbackground=THEME_ACCENT, highlightthickness=1)
        banner.pack(fill='x', pady=(0, 18), padx=2)

        tk.Label(banner, text='ℹ Price Sync from stock.csv',
                 font=(ui_theme.THEME_FONT, 11, 'bold'), fg=THEME_ACCENT, bg='#1f3d2e',
                 anchor='w').pack(fill='x', padx=12, pady=(10, 2))

        detail = tk.Label(banner, text=report_text,
                          font=(ui_theme.THEME_FONT, 9), fg=THEME_TEXT_MUTED, bg='#1f3d2e',
                          anchor='w', justify='left', wraplength=700)
        detail.pack(fill='x', padx=12, pady=(0, 4))

        def dismiss():
            self.startup_price_sync_report = None
            banner.destroy()

        self.styled_button(banner, 'Dismiss', dismiss, width=12, variant='ghost').pack(anchor='e', padx=12, pady=(0, 10))


    def update_dashboard_stats(self, parent=None):
        """Render simplified dashboard summary cards."""
        if parent is None:
            if not hasattr(self, 'main_menu') or not self.main_menu.winfo_exists():
                return
            parent = self.main_menu
        if hasattr(self, 'stats_frame'):
            self.stats_frame.destroy()

        self.stats_frame = self.themed_frame(parent)
        self.stats_frame._cards_grid = True
        self.stats_frame.pack(fill='x', pady=(0, 18))

        total_items = len(self.inventory_df)
        if not self.inventory_df.empty and COL_ITEM_ID in self.inventory_df.columns:
            active = self.inventory_df[COL_ITEM_ID]
            active = active[~active.apply(is_hidden_from_stock_view)]
            active = active[~active.apply(is_delisted)]
            total_items = len(active)

        # Negative stock count (excluding hidden/excluded items)
        neg_stock_count = 0
        if not self.inventory_df.empty and COL_ITEM_ID in self.inventory_df.columns:
            neg_stock_df = self.inventory_df[self.inventory_df[COL_QUANTITY] < 0]
            if not neg_stock_df.empty and COL_ITEM_ID in neg_stock_df.columns:
                neg_stock_df = neg_stock_df[~neg_stock_df[COL_ITEM_ID].apply(is_hidden_from_stock_view)]
                neg_stock_df = neg_stock_df[~neg_stock_df[COL_ITEM_ID].apply(should_exclude)]
                neg_stock_df = neg_stock_df[~neg_stock_df[COL_ITEM_ID].apply(is_delisted)]
            neg_stock_count = len(neg_stock_df)

        # Low stock count (at or below reorder level)
        low_stock_count = 0
        if (COL_REORDER_LEVEL in self.inventory_df.columns
                and COL_ITEM_ID in self.inventory_df.columns
                and not self.inventory_df.empty):
            low_stock_df = self.inventory_df[self.inventory_df[COL_QUANTITY] <= self.inventory_df[COL_REORDER_LEVEL]]
            low_stock_df = low_stock_df[low_stock_df[COL_REORDER_LEVEL] > 0]
            if not low_stock_df.empty and COL_ITEM_ID in low_stock_df.columns:
                low_stock_df = low_stock_df[~low_stock_df[COL_ITEM_ID].apply(is_hidden_from_stock_view)]
                low_stock_df = low_stock_df[~low_stock_df[COL_ITEM_ID].apply(should_exclude)]
                low_stock_df = low_stock_df[~low_stock_df[COL_ITEM_ID].apply(is_delisted)]
            low_stock_count = len(low_stock_df)

        # Last delivery timestamp
        last_delivery = "None"
        if not self.log_df.empty and COL_ACTION in self.log_df.columns:
            deliveries = self.log_df[self.log_df[COL_ACTION] == ACTION_DELIVERY]
            if not deliveries.empty and COL_TIMESTAMP in deliveries.columns:
                try:
                    latest = deliveries[COL_TIMESTAMP].max()
                    last_delivery = datetime.strptime(latest.split()[0], '%Y-%m-%d').strftime(DATE_FORMAT_DISPLAY)
                except Exception:
                    last_delivery = "Unknown"

        # Latest backup date
        latest_backup = "None"
        try:
            import glob
            backups = sorted(glob.glob(os.path.join(DATA_DIR, 'backups', 'barstock_*.db')), key=os.path.getmtime, reverse=True)
            if backups:
                mtime = os.path.getmtime(backups[0])
                latest_backup = datetime.fromtimestamp(mtime).strftime(DATE_FORMAT_DISPLAY)
        except Exception:
            latest_backup = "Unknown"

        # Last successful database write (every movement saves immediately)
        last_saved = "Not yet saved"
        saved_raw = get_setting('last_saved_at')
        if saved_raw:
            try:
                saved_dt = datetime.strptime(saved_raw, '%Y-%m-%d %H:%M:%S')
                last_saved = saved_dt.strftime(f'{DATE_FORMAT_DISPLAY} %H:%M')
            except (TypeError, ValueError):
                last_saved = str(saved_raw)

        # Reorder-level alert total
        reorder_alert_count = low_stock_count

        self.create_card(self.stats_frame, "Items in Stock", f"{total_items}",
                         f"{reorder_alert_count} below reorder level",
                         status='warning' if reorder_alert_count > 0 else 'normal')
        self.create_card(self.stats_frame, "Negative Stock", f"{neg_stock_count}",
                         "Needs attention" if neg_stock_count > 0 else "All positive",
                         status='danger' if neg_stock_count > 0 else 'normal')
        self.create_card(self.stats_frame, "Last Delivery", last_delivery,
                         "Booker/Tennent’s/Belhaven" if last_delivery != "None" else "Add a delivery")
        self.create_card(self.stats_frame, "Latest Backup", latest_backup,
                         "Auto-backup on open" if latest_backup != "None" else "Not yet backed up")
        self.create_card(self.stats_frame, "Last Saved", last_saved,
                         "Every movement saves immediately")


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
        return (log_len, latest, len(self.inventory_df),
                round(qty_sum, 4), round(value_sum, 4))


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
        """Return dict of snapshot values for the dashboard details panel."""
        result = {
            'period_sales': 0.0,
            'period_label': 'No sales data',
            'stock_holding': 0.0,
            'recent_sales_uploads': [],
            'recent_deliveries': [],
        }

        # Stock holding value at cost price
        if not self.inventory_df.empty:
            qty = pd.to_numeric(self.inventory_df.get(COL_QUANTITY, 0), errors='coerce').fillna(0)
            cost = pd.to_numeric(self.inventory_df.get(COL_COST_PRICE, 0), errors='coerce').fillna(0)
            result['stock_holding'] = (qty * cost).sum()

        if self.log_df.empty or COL_ACTION not in self.log_df.columns:
            return result

        log = self.log_df.copy()
        log['_ts'] = pd.to_datetime(log[COL_TIMESTAMP], errors='coerce')

        # Determine period start: latest baseline reset, otherwise earliest sales transaction
        baseline_ts = None
        baseline_rows = log[log[COL_ACTION] == ACTION_STOCKTAKE_BASELINE]
        if not baseline_rows.empty:
            baseline_ts = baseline_rows['_ts'].max()
        # Both sale actions count: "Sales (1 unit)" rows come from single-item
        # uploads and were previously missing from the dashboard total.
        sales_rows = log[log[COL_ACTION].isin(SALE_ACTIONS)]
        if baseline_ts is None and not sales_rows.empty:
            baseline_ts = sales_rows['_ts'].min()

        period_sales = 0.0
        if not sales_rows.empty and baseline_ts is not None:
            period_sales_rows = sales_rows[sales_rows['_ts'] >= baseline_ts]
            qty = pd.to_numeric(period_sales_rows.get(COL_QUANTITY, 0), errors='coerce').fillna(0)
            price = pd.to_numeric(period_sales_rows.get(COL_SELL_PRICE, 0), errors='coerce').fillna(0)
            period_sales = (qty * price).sum()
            if baseline_rows.empty:
                result['period_label'] = 'All recorded sales'
            else:
                result['period_label'] = f"Since {baseline_ts.strftime(DATE_FORMAT_DISPLAY)}"

        result['period_sales'] = period_sales

        # Recent sales uploads (grouped by date_range)
        uploads = sales_rows[sales_rows.get(COL_DATE_RANGE, '').astype(str).str.strip() != '']
        if not uploads.empty:
            grouped = uploads.groupby(COL_DATE_RANGE).agg({'_ts': 'min', COL_QUANTITY: 'sum'}).reset_index()
            grouped = grouped.sort_values('_ts', ascending=False).head(3)
            for _, row in grouped.iterrows():
                period_raw = str(row[COL_DATE_RANGE])
                period_fmt = self._format_period_display(period_raw)
                result['recent_sales_uploads'].append({
                    'period': period_fmt,
                    'qty': float(row[COL_QUANTITY]),
                })

        # Recent deliveries (grouped by timestamp + supplier)
        deliveries = log[log[COL_ACTION] == ACTION_DELIVERY].copy()
        if not deliveries.empty:
            deliveries[COL_SUPPLIER] = deliveries.get(COL_SUPPLIER, '').fillna('')
            grouped = deliveries.groupby([COL_TIMESTAMP, COL_SUPPLIER]).size().reset_index(name='count')
            grouped['_ts_dt'] = pd.to_datetime(grouped[COL_TIMESTAMP], errors='coerce')
            grouped = grouped.sort_values('_ts_dt', ascending=False).head(3)
            for _, row in grouped.iterrows():
                ts = row['_ts_dt']
                ts_str = ts.strftime(DATE_FORMAT_DISPLAY) if pd.notna(ts) else self._format_date_display(str(row[COL_TIMESTAMP])[:10])
                result['recent_deliveries'].append({
                    'date': ts_str,
                    'supplier': str(row[COL_SUPPLIER]) or '-',
                })

        return result


    def _format_period_display(self, period_raw):
        """Convert a raw period string to DD-MM-YYYY display format if possible."""
        if not period_raw:
            return period_raw
        # Match common patterns: 03/08/2026 - 09/08/2026, 24-05-2026 - 24-05-2026, 2026-08-03 - 2026-08-09
        for sep in (' - ', ' – ', ' to '):
            if sep in period_raw:
                parts = period_raw.split(sep)
                if len(parts) == 2:
                    return f"{self._format_date_display(parts[0].strip())}{sep}{self._format_date_display(parts[1].strip())}"
                break
        return self._format_date_display(period_raw)


    def _format_date_display(self, date_str):
        """Convert any ISO/legacy display date string to DD-MM-YYYY."""
        if not date_str:
            return date_str
        try:
            dt = parse_display_date(date_str)
            return dt.strftime(DATE_FORMAT_DISPLAY)
        except Exception:
            return date_str


    def _render_dashboard_snapshot(self, parent=None):
        """Render snapshot details panel: period sales, stock holding, recent uploads/deliveries."""
        if parent is None:
            if not hasattr(self, 'main_menu') or not self.main_menu.winfo_exists():
                return
            parent = self.main_menu
        if hasattr(self, 'snapshot_frame'):
            self.snapshot_frame.destroy()

        self.snapshot_frame = self.themed_frame(parent)
        self.snapshot_frame.pack(fill='x', pady=(0, 18))

        snap = self._compute_dashboard_snapshot()

        # Summary cards row
        cards_frame = self.themed_frame(self.snapshot_frame)
        cards_frame._cards_grid = True
        cards_frame.pack(fill='x', pady=(0, 14))

        self.create_card(cards_frame, "Period Sales (ex-VAT)", f"£{snap['period_sales']:,.2f}",
                         snap['period_label'])
        self.create_card(cards_frame, "Stock Holding", f"£{snap['stock_holding']:,.2f}",
                         "At cost price (ex VAT)")
        recent_uploads_text = "\n".join(
            [f"{u['period']}" for u in snap['recent_sales_uploads']]
        ) or "No recent uploads"
        self.create_card(cards_frame, "Last 3 Sales Uploads", f"{len(snap['recent_sales_uploads'])}",
                         recent_uploads_text)
        recent_deliveries_text = "\n".join(
            [f"{d['date']} — {d['supplier']}" for d in snap['recent_deliveries']]
        ) or "No recent deliveries"
        self.create_card(cards_frame, "Last 3 Deliveries", f"{len(snap['recent_deliveries'])}",
                         recent_deliveries_text)

        # Exit System card (clickable)
        exit_card = tk.Frame(cards_frame, bg=THEME_CARD, bd=1, relief='solid',
                             highlightbackground=THEME_BORDER, highlightthickness=1,
                             cursor='hand2')
        exit_column = len(cards_frame.grid_slaves())
        exit_card.grid(row=0, column=exit_column, sticky='nsew', padx=8, pady=5)
        cards_frame.grid_columnconfigure(exit_column, weight=1, uniform='cards')
        tk.Label(exit_card, text="EXIT SYSTEM", font=(ui_theme.THEME_FONT, 9, 'bold'),
                 fg=THEME_DANGER, bg=THEME_CARD).pack(anchor='w', padx=14, pady=(12, 4))
        exit_value = tk.Label(exit_card, text="Save & Exit", font=(ui_theme.THEME_FONT, 22, 'bold'),
                              fg=THEME_DANGER, bg=THEME_CARD)
        exit_value.pack(anchor='w', padx=14)
        tk.Label(exit_card, text="Safely close BarStock", font=(ui_theme.THEME_FONT, 10),
                 fg=THEME_TEXT_MUTED, bg=THEME_CARD).pack(anchor='w', padx=14, pady=(4, 14))

        def _fit_exit(event=None):
            width = exit_card.winfo_width()
            if width < 40 or width == getattr(exit_card, '_fitted_width', None):
                return
            exit_card._fitted_width = width
            exit_value.configure(wraplength=max(width - 28, 40),
                                 font=(ui_theme.THEME_FONT, 22 if width >= 120 else 15, 'bold'))

        exit_card.bind('<Configure>', _fit_exit)
        exit_card.bind('<Button-1>', lambda e: self.on_exit())
        for child in exit_card.winfo_children():
            child.bind('<Button-1>', lambda e: self.on_exit())


    def _render_attention_table(self, parent=None):
        """Show a simple table of items that need action: negative, low, or discrepancy."""
        if parent is None:
            if not hasattr(self, 'main_menu') or not self.main_menu.winfo_exists():
                return
            parent = self.main_menu
        if hasattr(self, 'attention_frame'):
            self.attention_frame.destroy()

        attention = []
        if not self.inventory_df.empty and COL_ITEM_ID in self.inventory_df.columns:
            for _, row in self.inventory_df.iterrows():
                item_id = row[COL_ITEM_ID]
                if is_hidden_from_stock_view(item_id) or should_exclude(item_id):
                    continue
                qty = float(row[COL_QUANTITY])
                reorder = float(row.get(COL_REORDER_LEVEL, 0) or 0)
                name = row.get(COL_ITEM_NAME, item_id)
                measure = row.get(COL_MEASURE, '')

                if qty < 0:
                    attention.append({
                        'name': name,
                        'qty': qty,
                        'measure': measure,
                        'status': 'Negative',
                        'action': 'Stocktake or delivery',
                        'tag': 'danger'
                    })
                elif reorder > 0 and qty <= reorder:
                    attention.append({
                        'name': name,
                        'qty': qty,
                        'measure': measure,
                        'status': 'Low',
                        'action': 'Order soon',
                        'tag': 'warning'
                    })

        panel = self.create_panel(parent, "Items needing attention")

        if not attention:
            self.themed_label(panel, "No issues found. All tracked stock is positive and above reorder levels.",
                              font=(ui_theme.THEME_FONT, 11), fg=THEME_SUCCESS).pack(anchor='w', padx=14, pady=(0, 14))
            return

        tree_frame = self.themed_frame(panel, bg=THEME_PANEL)
        tree_frame.pack(fill='both', expand=True, padx=14, pady=(0, 14))

        tree = ttk.Treeview(tree_frame, columns=('name', 'current', 'status', 'action'), show='headings', height=min(8, len(attention)))
        tree.heading('name', text='Item')
        tree.heading('current', text='Current Stock')
        tree.heading('status', text='Status')
        tree.heading('action', text='Action')
        tree.column('name', width=250)
        tree.column('current', width=140, anchor='e')
        tree.column('status', width=110, anchor='center')
        tree.column('action', width=200)

        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.pack(side=tk.LEFT, fill='both', expand=True)
        self._bind_treeview_mousewheel(tree)

        for item in attention:
            current_text = f"{item['qty']:.1f} {item['measure']}s" if item['measure'] else f"{item['qty']:.1f}"
            tag = 'danger' if item['tag'] == 'danger' else 'warning'
            tree.insert('', tk.END, values=(item['name'], current_text, item['status'], item['action']), tags=(tag,))

        tree.tag_configure('danger', foreground=THEME_DANGER, font=(ui_theme.THEME_FONT, 10, 'bold'))
        tree.tag_configure('warning', foreground=THEME_WARNING, font=(ui_theme.THEME_FONT, 10, 'bold'))


    def _safe_slice(self, df, required_cols):
        """Return a copy of df if it has all required columns, else an empty DataFrame with those columns."""
        if df is None or df.empty:
            return pd.DataFrame(columns=required_cols)
        missing = [c for c in required_cols if c not in df.columns]
        if missing:
            return pd.DataFrame(columns=required_cols)
        return df.copy()


    def update_critical_stock_alert(self, parent=None):
        """Display a dark-themed red alert banner if any stock item is below -10."""
        if parent is None:
            if not hasattr(self, 'main_menu') or not self.main_menu.winfo_exists():
                return
            parent = self.main_menu
        if hasattr(self, 'critical_alert_frame'):
            self.critical_alert_frame.destroy()

        df = self._safe_slice(self.inventory_df, [COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY])
        critical_items = df[df[COL_QUANTITY] < -10]
        if critical_items.empty:
            return
        critical_items = critical_items[~critical_items[COL_ITEM_ID].apply(is_hidden_from_stock_view)]
        critical_items = critical_items[~critical_items[COL_ITEM_ID].apply(should_exclude)]
        if critical_items.empty:
            return

        self.critical_alert_frame = tk.Frame(parent, bg='#3a1010', bd=1, relief='solid',
                                             highlightbackground='#7f1d1d', highlightthickness=1)
        self.critical_alert_frame.pack(fill='x', pady=(0, 12))

        alert_text = f"CRITICAL STOCK: {len(critical_items)} item(s) below -10 — "
        alert_text += ", ".join(f"{row[COL_ITEM_NAME]} ({row[COL_QUANTITY]:.1f})" for _, row in critical_items.iterrows())
        tk.Label(self.critical_alert_frame, text=alert_text,
                 font=(ui_theme.THEME_FONT, 11, 'bold'), bg='#3a1010', fg=THEME_DANGER,
                 wraplength=1100, justify='left').pack(anchor='w', padx=14, pady=10)


    def update_variance_alert(self, parent=None):
        """Display a dark-themed yellow warning banner for unexplained stock variance."""
        if parent is None:
            if not hasattr(self, 'main_menu') or not self.main_menu.winfo_exists():
                return
            parent = self.main_menu
        if hasattr(self, 'variance_alert_frame'):
            self.variance_alert_frame.destroy()

        df = self._safe_slice(self.inventory_df, [COL_ITEM_ID])
        if df.empty:
            return

        try:
            from reports import build_surplus_report_data
            from data_manager import get_resource_path
            import sqlite3
            import os
            from datetime import datetime, timedelta

            report_data = build_surplus_report_data(self.inventory_df, self.log_df)
            db_path = os.path.join(get_resource_path(), 'barstock.db')
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S')
            cursor.execute("""
                SELECT item_id, SUM(quantity) FROM transactions
                WHERE action = 'Stocktake Adjustment' AND timestamp >= ?
                GROUP BY item_id
            """, (cutoff,))
            stocktake_adjusted = {row[0]: row[1] for row in cursor.fetchall()}
            conn.close()

            unexplained = []
            for r in report_data:
                item_id = r.get(COL_ITEM_ID)
                if item_id in stocktake_adjusted:
                    continue
                if abs(r.get('Variance Value', 0)) >= 5:
                    unexplained.append(r)

            total_variance_value = sum(abs(r.get('Variance Value', 0)) for r in unexplained)
            if total_variance_value <= 200:
                return

            self.variance_alert_frame = tk.Frame(parent, bg='#382a05', bd=1, relief='solid',
                                                 highlightbackground='#856404', highlightthickness=1)
            self.variance_alert_frame.pack(fill='x', pady=(0, 12))

            alert_text = f"VARIANCE WARNING: £{total_variance_value:.2f} unexplained across {len(unexplained)} item(s). Consider a stocktake."
            tk.Label(self.variance_alert_frame, text=alert_text,
                     font=(ui_theme.THEME_FONT, 11, 'bold'), bg='#382a05', fg=THEME_WARNING,
                     wraplength=1100, justify='left').pack(anchor='w', padx=14, pady=10)
        except Exception:
            return


    def update_open_tab_alert(self, parent=None):
        """Display a dark-themed red alert banner for stale open tabs."""
        if parent is None:
            if not hasattr(self, 'main_menu') or not self.main_menu.winfo_exists():
                return
            parent = self.main_menu
        if hasattr(self, 'open_tab_alert_frame'):
            self.open_tab_alert_frame.destroy()

        try:
            from datetime import datetime, timedelta
            open_tabs = InventoryDataManager.get_open_tabs(status='open')
            if open_tabs.empty:
                return

            cutoff = datetime.now() - timedelta(days=7)
            stale_tabs = []
            for _, row in open_tabs.iterrows():
                created = row.get('created_at')
                if not created:
                    continue
                try:
                    created_dt = datetime.fromisoformat(str(created).replace('Z', '+00:00'))
                    if created_dt.replace(tzinfo=None) < cutoff:
                        stale_tabs.append(row.get('customer_name', 'Unknown'))
                except Exception:
                    continue

            stale_tabs = list(dict.fromkeys(stale_tabs))
            if not stale_tabs:
                return

            self.open_tab_alert_frame = tk.Frame(parent, bg='#3a1010', bd=1, relief='solid',
                                                 highlightbackground='#7f1d1d', highlightthickness=1)
            self.open_tab_alert_frame.pack(fill='x', pady=(0, 12))

            alert_text = f"STALE TABS: {len(stale_tabs)} tab(s) over 7 days old — {', '.join(stale_tabs[:5])}"
            if len(stale_tabs) > 5:
                alert_text += " and more..."
            alert_text += ". Consider closing or chasing."
            tk.Label(self.open_tab_alert_frame, text=alert_text,
                     font=(ui_theme.THEME_FONT, 11, 'bold'), bg='#3a1010', fg=THEME_DANGER,
                     wraplength=1100, justify='left').pack(anchor='w', padx=14, pady=10)
        except Exception:
            return


    def _render_upload_banner(self, parent=None):
        """Render dark-themed upload history banner."""
        if parent is None:
            if not hasattr(self, 'main_menu') or not self.main_menu.winfo_exists():
                return
            parent = self.main_menu
        if hasattr(self, 'upload_banner_frame'):
            self.upload_banner_frame.destroy()

        hashes = get_upload_hashes()
        sales_uploads = [h for h in hashes if h.get('type') == 'sales']
        comp_uploads = [h for h in hashes if h.get('type') == 'complimentary']
        banner_texts = []
        if sales_uploads:
            latest = max(sales_uploads, key=lambda h: h.get('timestamp', ''))
            banner_texts.append(f"Last Sales Upload: {latest.get('date_range', 'Unknown')}")
        if comp_uploads:
            latest = max(comp_uploads, key=lambda h: h.get('timestamp', ''))
            banner_texts.append(f"Last Complimentary Upload: {latest.get('date_range', 'Unknown')}")
        if not banner_texts:
            return

        self.upload_banner_frame = tk.Frame(parent, bg='#0f2e4e', bd=1, relief='solid',
                                            highlightbackground='#1e4b7a', highlightthickness=1)
        self.upload_banner_frame.pack(fill='x', pady=(0, 14))
        tk.Label(self.upload_banner_frame, text='  |  '.join(banner_texts),
                 font=(ui_theme.THEME_FONT, 10), bg='#0f2e4e', fg='#93c5fd').pack(anchor='w', padx=14, pady=8)


    def _render_stock_alerts_panel(self, parent):
        """Render a dark-themed panel listing items needing attention."""
        panel = self.create_panel(parent, "Stock Alerts")
        rows_frame = self.themed_frame(panel, bg=THEME_PANEL)
        rows_frame.pack(fill='x', padx=14, pady=(0, 14))

        header_bg = THEME_PANEL
        col_config = [("Item", 30, 'w'), ("Current", 15, 'center'),
                      ("Reorder", 15, 'center'), ("Status", 15, 'center')]
        for text, width, anchor in col_config:
            tk.Label(rows_frame, text=text, font=(ui_theme.THEME_FONT, 10, 'bold'),
                     bg=header_bg, fg=THEME_TEXT_MUTED, width=width, anchor=anchor).pack(side='left', padx=4)

        df = self._safe_slice(self.inventory_df, [COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_REORDER_LEVEL])
        if df.empty:
            tk.Label(rows_frame, text="No inventory data available.", font=(ui_theme.THEME_FONT, 11),
                     bg=THEME_PANEL, fg=THEME_TEXT_MUTED).pack(pady=10)
            return

        alert_rows = []
        for _, row in df.iterrows():
            try:
                qty = float(row[COL_QUANTITY])
                reorder = float(row[COL_REORDER_LEVEL])
                if reorder <= 0:
                    continue
                if qty > reorder:
                    continue
                item_id = str(row[COL_ITEM_ID])
                if is_hidden_from_stock_view(item_id):
                    continue
                if qty <= 0:
                    status_text = "CRITICAL"
                    status_color = THEME_DANGER
                elif qty <= reorder * 0.5:
                    status_text = "LOW"
                    status_color = THEME_WARNING
                else:
                    status_text = "BELOW REORDER"
                    status_color = THEME_TEXT
                alert_rows.append({
                    COL_ITEM_NAME: str(row[COL_ITEM_NAME]),
                    COL_QUANTITY: qty,
                    COL_REORDER_LEVEL: reorder,
                    'status_text': status_text,
                    'status_color': status_color,
                })
            except Exception:
                continue

        alert_rows = sorted(alert_rows, key=lambda r: r[COL_QUANTITY])[:10]

        if not alert_rows:
            tk.Label(rows_frame, text="No stock alerts. All items are above reorder level.",
                     font=(ui_theme.THEME_FONT, 11), bg=THEME_PANEL, fg=THEME_SUCCESS).pack(pady=10)
            return

        list_frame = self.themed_frame(panel, bg=THEME_PANEL)
        list_frame.pack(fill='x', padx=14, pady=(0, 14))
        for row in alert_rows:
            row_frame = self.themed_frame(list_frame, bg=THEME_PANEL)
            row_frame.pack(fill='x', pady=3)
            tk.Label(row_frame, text=row[COL_ITEM_NAME], font=(ui_theme.THEME_FONT, 11),
                     bg=THEME_PANEL, fg=THEME_TEXT, width=30, anchor='w').pack(side='left', padx=4)
            tk.Label(row_frame, text=f"{row[COL_QUANTITY]:.1f}", font=(ui_theme.THEME_FONT, 11),
                     bg=THEME_PANEL, fg=row['status_color'], width=15, anchor='center').pack(side='left', padx=4)
            tk.Label(row_frame, text=f"{row[COL_REORDER_LEVEL]:.1f}", font=(ui_theme.THEME_FONT, 11),
                     bg=THEME_PANEL, fg=THEME_TEXT_MUTED, width=15, anchor='center').pack(side='left', padx=4)
            tk.Label(row_frame, text=row['status_text'], font=(ui_theme.THEME_FONT, 10, 'bold'),
                     bg=THEME_PANEL, fg=row['status_color'], width=15, anchor='center').pack(side='left', padx=4)
