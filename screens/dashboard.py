#!/usr/bin/env python3
"""Dashboard screen: the Ledger summary, attention list, top sellers and notices."""

import os
import sqlite3
from datetime import datetime, timedelta

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

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
    format_day_month, sqlite_ro_uri,
)
from actions import ACTION_DELIVERY, ACTION_STOCKTAKE_BASELINE, SALE_ACTIONS
from categories import is_delisted, should_exclude
from conversions import DATE_FORMAT_DISPLAY, parse_display_date
from data_manager import (
    InventoryDataManager, COL_REORDER_LEVEL, get_setting, get_upload_hashes,
    get_last_stocktake_summary, get_backup_health, create_backup,
)
from sales_mapping import is_hidden_from_stock_view
from money import inc_vat, round_money, sum_money
import club_profile
from reports import (
    sales_money_by_item, filter_log_by_date, build_previous_period_log,
    build_period_comparison_summary, build_upload_period_health,
    build_price_change_alerts, STOCKTAKE_DUE_DAYS, STOCKTAKE_WARN_DAYS,
    BACKUP_WARN_DAYS, BACKUP_OVERDUE_DAYS,
)


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
        self._render_setup_card(self.main_menu)

        self._render_ledger_summary(self.main_menu)
        self._render_insight_strip(self.main_menu)
        self._render_operations_strip(self.main_menu)
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

    def _render_setup_card(self, parent=None):
        """Give a completely blank install an obvious first step."""
        parent = self._dashboard_parent(parent)
        if parent is None or not self.inventory_df.empty:
            return
        card = tk.Frame(parent, bg=THEME_CARD)
        card.pack(fill='x', pady=(0, 18))
        tk.Label(card, text="SET UP YOUR STOCK LIST",
                 font=ui_theme.mono_font(9, 'bold'), fg=THEME_ACCENT,
                 bg=THEME_CARD, anchor='w').pack(fill='x', padx=16, pady=(14, 2))
        tk.Label(
            card,
            text=("No stock items yet. Import an Items.csv list, or add items "
                  "manually in Manage Stock. The import is also available under "
                  "More Actions → System → Init from Items.csv."),
            font=(ui_theme.THEME_FONT, 10), fg=THEME_TEXT, bg=THEME_CARD,
            anchor='w', justify='left', wraplength=900).pack(
                fill='x', padx=16, pady=(0, 10))
        actions = tk.Frame(card, bg=THEME_CARD)
        actions.pack(fill='x', padx=16, pady=(0, 14))
        self.styled_button(actions, "Import Items.csv",
                           self.initialize_stock_from_items_csv, width=20,
                           variant='primary').pack(side='left')
        self.styled_button(actions, "Add item manually",
                           self.manage_initial_stock, width=20,
                           variant='secondary').pack(side='left', padx=(8, 0))

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
            self._render_insight_strip(self.main_menu)
            self._render_operations_strip(self.main_menu)
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

    def _render_insight_strip(self, parent=None):
        """Render this-period-vs-previous figures beneath the KPI row."""
        parent = self._dashboard_parent(parent)
        if parent is None:
            return
        if hasattr(self, 'insight_strip_frame'):
            self.insight_strip_frame.destroy()

        snap = self._compute_dashboard_snapshot()
        comparison = snap.get('period_comparison')
        if not comparison:
            return
        current = comparison.get('current') or {}
        changes = comparison.get('changes') or {}

        outer = tk.Frame(parent, bg=THEME_BG)
        outer.pack(fill='x', pady=(0, 22))
        self.insight_strip_frame = outer
        labels = comparison.get('labels') or {}
        heading = 'Latest upload vs previous'
        if labels.get('current'):
            heading = (f"Latest upload {labels['current']} vs "
                       f"{labels.get('previous') or 'previous upload'}")
        tk.Label(outer, text=heading.upper(), font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w').pack(
            fill='x', pady=(0, 4))
        tk.Frame(outer, bg=THEME_BORDER, height=1).pack(fill='x')

        row = tk.Frame(outer, bg=THEME_BG)
        row.pack(fill='x')
        for column in (0, 2, 4, 6):
            row.grid_columnconfigure(column, weight=1, uniform='insight-kpi')
        for column in (1, 3, 5):
            tk.Frame(row, bg=THEME_BORDER, width=1).grid(
                row=0, column=column, sticky='ns', pady=12)

        def _delta(key, pp=False):
            change = changes.get(key) or {}
            if change.get('delta') is None:
                return 'No prior period', THEME_TEXT_MUTED
            if pp:
                value = change.get('pp') or 0
                text = f"{value:+.1f} pp"
            else:
                pct = change.get('pct')
                text = (f"{pct:+.1f}%" if pct is not None
                        else f"£{change.get('delta', 0):+,.2f}")
            if change.get('good') is True:
                colour = THEME_SUCCESS
            elif change.get('good') is False:
                colour = THEME_DANGER
            else:
                colour = THEME_TEXT_MUTED
            return text, colour

        waste_current = (current.get('wastage_cost', 0)
                         + current.get('complimentary_cost', 0))
        previous = comparison.get('previous') or {}
        waste_previous = (previous.get('wastage_cost', 0)
                          + previous.get('complimentary_cost', 0))
        waste_change = changes.get('wastage_cost') or {}
        if previous:
            if waste_previous:
                waste_pct = ((waste_current - waste_previous)
                             / waste_previous * 100)
                waste_text = f"{waste_pct:+.1f}%"
                waste_colour = (THEME_SUCCESS if waste_change.get('direction') == 'down'
                                else THEME_DANGER if waste_change.get('direction') == 'up'
                                else THEME_TEXT_MUTED)
            elif waste_current:
                waste_text = f"+£{waste_current:,.2f}"
                waste_colour = THEME_DANGER
            else:
                waste_text = 'No change'
                waste_colour = THEME_TEXT_MUTED
        else:
            waste_text, waste_colour = 'No prior period', THEME_TEXT_MUTED

        sales_text, sales_colour = _delta('sales_ex_vat')
        gp_text, gp_colour = _delta('gp_pct', pp=True)
        cells = [
            ('Sales ex VAT', f"£{current.get('sales_ex_vat', 0):,.2f}",
             sales_text, sales_colour,
             f"Previous £{previous.get('sales_ex_vat', 0):,.2f}"),
            ('GP margin', f"{current.get('gp_pct', 0):.1f}%",
             gp_text, gp_colour,
             f"GP £{current.get('gp', 0):,.2f}"),
            ('Wastage & comp', f"£{waste_current:,.2f}",
             waste_text, waste_colour,
             f"Previous £{waste_previous:,.2f}"),
            ('Stock holding', f"£{current.get('stock_holding', 0):,.2f}",
             'At cost, ex VAT', THEME_TEXT_MUTED,
             'Current valuation'),
        ]
        for index, (label, value, delta, colour, note) in enumerate(cells):
            cell = tk.Frame(row, bg=THEME_BG)
            cell.grid(row=0, column=index * 2, sticky='nsew',
                      padx=(0 if index == 0 else 18, 18), pady=12)
            tk.Label(cell, text=label.upper(), font=ui_theme.mono_font(8),
                     fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w').pack(fill='x')
            value_row = tk.Frame(cell, bg=THEME_BG)
            value_row.pack(fill='x', pady=(2, 0))
            tk.Label(value_row, text=value, font=ui_theme.display_font(19),
                     fg=THEME_TEXT, bg=THEME_BG, anchor='w').pack(side='left')
            tk.Label(value_row, text=delta, font=ui_theme.mono_font(9),
                     fg=colour, bg=THEME_BG, anchor='e').pack(
                side='right', padx=(8, 0))
            tk.Label(cell, text=note, font=(ui_theme.THEME_FONT, 9),
                     fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w').pack(fill='x')

        tk.Frame(outer, bg=THEME_BORDER, height=1).pack(fill='x')

    def _render_operations_strip(self, parent=None):
        """Render compact stocktake / upload / backup health cards."""
        parent = self._dashboard_parent(parent)
        if parent is None:
            return
        if hasattr(self, 'operations_strip_frame'):
            self.operations_strip_frame.destroy()

        snap = self._compute_dashboard_snapshot()
        operations = snap.get('operations') or {}
        outer = tk.Frame(parent, bg=THEME_BG)
        outer.pack(fill='x', pady=(0, 22))
        self.operations_strip_frame = outer
        tk.Frame(outer, bg=THEME_BORDER, height=1).pack(fill='x')
        row = tk.Frame(outer, bg=THEME_BG)
        row.pack(fill='x', pady=10)
        for column in range(3):
            row.grid_columnconfigure(column, weight=1, uniform='ops-card')

        def card(column, title, value, detail, colour, command=None):
            frame = tk.Frame(row, bg=THEME_BG)
            frame.grid(row=0, column=column, sticky='nsew',
                       padx=(0 if column == 0 else 18, 18))
            cursor = 'hand2' if command else ''
            label = tk.Label(frame, text=title.upper(), font=ui_theme.mono_font(8),
                             fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w',
                             cursor=cursor)
            label.pack(fill='x')
            value_label = tk.Label(frame, text=value, font=ui_theme.display_font(13),
                                   fg=colour, bg=THEME_BG, anchor='w',
                                   cursor=cursor)
            value_label.pack(fill='x', pady=(2, 0))
            detail_label = tk.Label(frame, text=detail,
                                    font=(ui_theme.THEME_FONT, 9),
                                    fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w',
                                    cursor=cursor, wraplength=260, justify='left')
            detail_label.pack(fill='x')
            if command:
                for widget in (frame, label, value_label, detail_label):
                    widget.bind('<Button-1>', lambda e: command())
            return frame

        stocktake = operations.get('stocktake')
        if stocktake is None:
            card(0, 'Stocktake', 'No count recorded',
                 'Open Stocktake to record a baseline', THEME_WARNING,
                 self.show_stocktake)
        else:
            days = stocktake.get('days_since')
            when = stocktake.get('datetime')
            when_text = format_day_month(when) if when else 'unknown'
            if days is None:
                colour, status = THEME_TEXT_MUTED, 'Date unknown'
            elif days >= STOCKTAKE_DUE_DAYS:
                colour, status = THEME_DANGER, 'Due'
            elif days >= STOCKTAKE_WARN_DAYS:
                colour, status = THEME_WARNING, 'Due soon'
            else:
                colour, status = THEME_SUCCESS, 'Up to date'
            card(0, 'Stocktake', f"Last {when_text}",
                 f"{days} days ago · {status}" if days is not None else status,
                 colour, self.show_stocktake)

        upload = operations.get('upload') or {}
        upload_end = upload.get('latest_period_end')
        if upload_end is None:
            card(1, 'Sales upload', 'No upload yet',
                 'Upload the EPOS sales file', THEME_WARNING,
                 self.show_sales_upload)
        else:
            days = upload.get('days_since_period_end')
            status = upload.get('status', '')
            colour = (THEME_DANGER if status == 'overdue'
                      else THEME_WARNING if status == 'warning'
                      else THEME_SUCCESS)
            detail = f"Coverage ends {format_day_month(upload_end)}"
            if days is not None:
                detail += f" · {days} days ago"
            if upload.get('latest_overlaps'):
                detail += f" · {len(upload['latest_overlaps'])} overlap(s)"
            elif upload.get('largest_gap_days', 0) > 8:
                detail += f" · {upload['largest_gap_days']}-day gap"
            card(1, 'Sales upload',
                 upload.get('latest_period') or 'Uploaded', detail, colour,
                 self.show_sales_upload)

        backup = operations.get('backup') or {}
        backup_latest = backup.get('latest')
        if backup_latest is None:
            card(2, 'Backup', 'No backup found',
                 'Create a backup now', THEME_DANGER)
        else:
            status = backup.get('status', '')
            colour = (THEME_DANGER if status == 'overdue'
                      else THEME_WARNING if status == 'warning'
                      else THEME_SUCCESS)
            kind = (backup.get('kind') or '').strip()
            detail = f"{backup.get('age_days')} days ago"
            if kind:
                detail += f" · {kind} backup"
            card(2, 'Backup',
                 f"{format_day_month(backup_latest)} {backup_latest.strftime('%H:%M')}",
                 detail, colour)
        button = self.styled_button(row, "Back up now", self._backup_now,
                                    width=14, variant='secondary')
        button.grid(row=1, column=2, sticky='e', padx=(18, 18), pady=(0, 6))

        tk.Frame(outer, bg=THEME_BORDER, height=1).pack(fill='x')

    def _backup_now(self):
        """Create a verified backup and refresh the dashboard."""
        if getattr(self, '_backup_in_progress', False):
            return
        self._backup_in_progress = True

        def done(path):
            self._backup_in_progress = False
            self._dashboard_snapshot_cache = None
            if path:
                name = os.path.basename(path)
                self._set_status(f"Backup created: {name}", 'success')
                self.show_dashboard()
                # The dashboard updates quietly, so make the manual action
                # unmistakable even when an auto-backup was taken minutes ago.
                messagebox.showinfo(
                    "Backup created",
                    f"Backup created successfully:\n\n{name}\n\n"
                    "The dashboard now shows this as the latest backup.")
            else:
                messagebox.showwarning(
                    "Backup failed",
                    "The backup could not be created. Check the logs before "
                    "relying on the latest copy.")

        def failed(exc):
            self._backup_in_progress = False
            messagebox.showerror("Backup failed", str(exc))

        try:
            self._run_in_background(
                "Creating backup…",
                lambda: create_backup('dashboard'),
                done, failed, title="Backup",
            )
        except Exception as exc:
            # Never leave the button permanently disabled if the progress
            # overlay cannot be created.
            self._backup_in_progress = False
            messagebox.showerror("Backup failed", str(exc))

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
            for index, item in enumerate(items[:8]):
                if index:
                    tk.Frame(parent, bg=THEME_BORDER, height=1).pack(fill='x')
                command = self._attention_command(item.get('target'))
                cursor = 'hand2' if command else ''
                row = tk.Frame(parent, bg=THEME_BG, cursor=cursor)
                row.pack(fill='x', pady=8)
                text = tk.Frame(row, bg=THEME_BG, cursor=cursor)
                text.pack(side='left', fill='x', expand=True)
                name_label = tk.Label(text, text=item['name'],
                                      font=ui_theme.display_font(11),
                                      fg=THEME_TEXT, bg=THEME_BG, anchor='w',
                                      cursor=cursor)
                name_label.pack(fill='x')
                detail_label = tk.Label(text, text=item['detail'],
                                        font=(ui_theme.THEME_FONT, 9),
                                        fg=THEME_TEXT_MUTED, bg=THEME_BG,
                                        anchor='w', cursor=cursor)
                detail_label.pack(fill='x')
                tag_label = tk.Label(row, text=item['tag'].upper(),
                                     font=ui_theme.mono_font(8),
                                     fg=THEME_WARNING, bg=THEME_BG, padx=8,
                                     pady=2, bd=1, relief='solid',
                                     cursor=cursor)
                tag_label.pack(side='right', padx=(12, 0))
                if command:
                    for widget in (row, text, name_label, detail_label, tag_label):
                        widget.bind('<Button-1>', lambda e, cmd=command: cmd())
            if len(items) > 8:
                tk.Label(parent, text=f"... and {len(items) - 8} more",
                         font=ui_theme.mono_font(8), fg=THEME_TEXT_MUTED,
                         bg=THEME_BG, anchor='w').pack(fill='x', pady=(6, 0))

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
        if hasattr(self, 'dashboard_footer_frame'):
            self.dashboard_footer_frame.destroy()
        footer = self.themed_frame(parent)
        footer.pack(fill='x', pady=(6, 0))
        self.dashboard_footer_frame = footer

        health = get_backup_health(
            warn_days=BACKUP_WARN_DAYS, overdue_days=BACKUP_OVERDUE_DAYS)
        latest_backup = "None"
        backup_colour = THEME_TEXT_MUTED
        if health.get('latest') is not None:
            age = health.get('age_days')
            latest_backup = health['latest'].strftime(DATE_FORMAT_DISPLAY)
            if age is not None:
                latest_backup += f" ({age} day{'s' if age != 1 else ''} ago)"
            backup_colour = {
                'overdue': THEME_DANGER,
                'warning': THEME_WARNING,
                'ok': THEME_TEXT_MUTED,
            }.get(health.get('status'), THEME_TEXT_MUTED)

        last_saved = "Not yet saved"
        saved_raw = get_setting('last_saved_at')
        if saved_raw:
            try:
                saved_dt = datetime.strptime(saved_raw, '%Y-%m-%d %H:%M:%S')
                last_saved = saved_dt.strftime(f'{DATE_FORMAT_DISPLAY} %H:%M')
            except (TypeError, ValueError):
                last_saved = str(saved_raw)

        self.styled_button(footer, "Back up now", self._backup_now,
                           width=13, variant='secondary').pack(side='left')
        credit = club_profile.footer_credit().strip()
        footer_parts = []
        if credit:
            footer_parts.append(credit)
        footer_parts.append(f"Latest backup {latest_backup}")
        footer_parts.append(f"Last saved {last_saved}")
        tk.Label(
            footer,
            text="   ·   ".join(footer_parts),
            font=ui_theme.mono_font(8), fg=backup_colour, bg=THEME_BG,
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
        try:
            db_mtime = os.path.getmtime(data_manager_module.DB_PATH)
        except Exception:
            db_mtime = 0
        return (log_len, latest, len(self.inventory_df),
                round(qty_sum, 4), round(value_sum, 4),
                tab_count, upload_count, db_mtime)

    def _load_dashboard_full_log(self):
        """Return active plus archived transactions for insight calculations.

        The live ``self.log_df`` is active-only; a baseline reset moves earlier
        rows to the archive, so the previous-period comparison would otherwise
        see nothing. This is called from the memoised snapshot path.
        """
        try:
            full = InventoryDataManager.load_full_log(self.inventory_df)
            if full is not None and not full.empty:
                return full
        except Exception:
            pass
        return self.log_df

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
            'period_comparison': None,
            'stock_holding': 0.0,
            'active_lines': 0,
            'lines_with_stock': 0,
            'recent_sales_uploads': [],
            'recent_deliveries': [],
            'top_sellers': [],
            'attention_items': [],
            'operations': {},
            'price_alerts': [],
            'last_stocktake': None,
            'last_upload': None,
            'backup_health': None,
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

        # Operational health is cheap SQL/globs plus the memoised full log.
        # Computing it before the empty-sales early return means the dashboard
        # still warns about a missing stocktake or a stale backup on a fresh
        # database.
        full_log = self._load_dashboard_full_log()
        upload_health = build_upload_period_health(full_log)
        last_stocktake = get_last_stocktake_summary()
        backup_health = get_backup_health(
            warn_days=BACKUP_WARN_DAYS, overdue_days=BACKUP_OVERDUE_DAYS)
        price_alerts = build_price_change_alerts(self.inventory_df, full_log)
        result['last_upload'] = upload_health
        result['last_stocktake'] = last_stocktake
        result['backup_health'] = backup_health
        result['price_alerts'] = price_alerts
        result['operations'] = {
            'upload': upload_health,
            'stocktake': last_stocktake,
            'backup': backup_health,
        }

        if self.log_df.empty or COL_ACTION not in self.log_df.columns:
            result['attention_items'] = self._compute_attention_items(
                full_log=full_log, upload_health=upload_health,
                price_alerts=price_alerts, last_stocktake=last_stocktake,
                backup_health=backup_health)
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
                result['period_label'] = (
                    "Since " + f"{baseline_ts.day} {baseline_ts.strftime('%B')}")
        result['period_sales'] = period_sales
        # The EPOS exports are inc-VAT, so the dashboard shows the same total
        # both ways and an upload can be checked against the CSV at a glance.
        result['period_sales_inc'] = inc_vat(period_sales)

        # Period-over-period insight. Prefer the last two completed upload
        # periods: the baseline-to-now window can contain an incomplete current
        # week, which would show a sales fall that is really a missing upload.
        # If there are fewer than two uploads, fall back to the baseline window.
        upload_periods = upload_health.get('periods') or []
        if len(upload_periods) >= 2:
            latest_period = upload_periods[-1]
            previous_period = upload_periods[-2]

            def _log_for_period(period):
                if full_log is None or full_log.empty:
                    return full_log
                labels = full_log[COL_DATE_RANGE].astype(str).str.strip()
                # Uploaded sales carry the trading period; manual wastage,
                # complimentary drinks and deliveries carry no date_range, so
                # include those by timestamp inside the same dates.
                selected = labels == period['period']
                timestamps = pd.to_datetime(
                    full_log[COL_TIMESTAMP], errors='coerce')
                start = pd.Timestamp(period['start'])
                end = (pd.Timestamp(period['end'])
                       + pd.Timedelta(days=1) - pd.Timedelta(seconds=1))
                manual = (labels == '') & timestamps.between(start, end)
                return full_log[selected | manual]

            result['period_comparison'] = build_period_comparison_summary(
                self.inventory_df,
                _log_for_period(latest_period),
                _log_for_period(previous_period),
                int(self.get_member_discount_pct()),
                current_label=latest_period['period'],
                previous_label=previous_period['period'])
        elif pd.notna(baseline_ts):
            current_end = datetime.now()
            current_log = filter_log_by_date(full_log, baseline_ts, current_end)
            previous_log, prev_start, prev_end = build_previous_period_log(
                full_log, baseline_ts, current_end, current_log)
            previous_label = ''
            if prev_start is not None and prev_end is not None:
                previous_label = (f"{format_day_month(prev_start)} - "
                                  f"{format_day_month(prev_end)}")
            result['period_comparison'] = build_period_comparison_summary(
                self.inventory_df, current_log, previous_log,
                int(self.get_member_discount_pct()),
                current_label=result['period_label'],
                previous_label=previous_label)

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

        result['attention_items'] = self._compute_attention_items(
            full_log=full_log, upload_health=upload_health,
            price_alerts=price_alerts, last_stocktake=last_stocktake,
            backup_health=backup_health)
        return result

    def _compute_attention_items(self, full_log=None, upload_health=None,
                                 price_alerts=None, last_stocktake=None,
                                 backup_health=None):
        """Build the actionable attention list.

        Every row carries a ``target`` the UI maps to a navigation callback, so
        a warning is not a dead end. The list covers stale tabs, sales-upload
        coverage, stocktake and backup age, delivery price increases and stock
        levels.
        """
        items = []
        if full_log is None:
            full_log = self._load_dashboard_full_log()
        if upload_health is None:
            upload_health = build_upload_period_health(full_log)
        if price_alerts is None:
            price_alerts = build_price_change_alerts(self.inventory_df, full_log)
        if last_stocktake is None:
            last_stocktake = get_last_stocktake_summary()
        if backup_health is None:
            backup_health = get_backup_health(
                warn_days=BACKUP_WARN_DAYS, overdue_days=BACKUP_OVERDUE_DAYS)

        try:
            # Query the tab table directly so each tab appears once, not once
            # per item row.
            conn = sqlite3.connect(
                sqlite_ro_uri(data_manager_module.DB_PATH), uri=True)
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
                        'target': 'open_tabs',
                    })
        except Exception:
            pass

        # Sales-upload coverage. Prefer the full log over the pruned upload
        # hashes so the warning survives the 30-day hash cleanup.
        status = upload_health.get('status')
        if status in ('overdue', 'warning'):
            detail_parts = []
            latest_end = upload_health.get('latest_period_end')
            if latest_end is not None:
                detail_parts.append(
                    f"Coverage ends {format_day_month(latest_end)} "
                    f"({upload_health.get('days_since_period_end')} days)")
            if upload_health.get('latest_overlaps'):
                detail_parts.append(
                    f"{len(upload_health['latest_overlaps'])} overlapping period(s)")
            if upload_health.get('largest_gap_days', 0) > 8:
                detail_parts.append(
                    f"{upload_health['largest_gap_days']}-day gap")
            items.append({
                'name': 'Sales upload',
                'detail': ' · '.join(detail_parts) or 'Upload due',
                'tag': 'Upload',
                'target': 'sales_upload',
            })
        elif upload_health.get('latest_period') is None:
            try:
                uploads = [h for h in get_upload_hashes()
                           if h.get('type') == 'sales']
                if uploads:
                    latest = max(uploads, key=lambda h: h.get('timestamp', ''))
                    uploaded = self._parse_timestamp(latest.get('timestamp'))
                    if uploaded and datetime.now() - uploaded > timedelta(days=8):
                        items.append({
                            'name': 'Sales upload',
                            'detail': f"Last sales file {self._short_date(uploaded)}",
                            'tag': 'Upload',
                            'target': 'sales_upload',
                        })
            except Exception:
                pass

        # Stocktake age. Monthly counts are the norm; warn at four weeks and
        # mark it due after five.
        if last_stocktake is None:
            if not self.inventory_df.empty:
                items.append({
                    'name': 'Stocktake',
                    'detail': 'No stocktake recorded',
                    'tag': 'Stocktake',
                    'target': 'stocktake',
                })
        else:
            days = last_stocktake.get('days_since')
            if days is not None and days >= STOCKTAKE_WARN_DAYS:
                label = 'due' if days >= STOCKTAKE_DUE_DAYS else 'due soon'
                when = last_stocktake.get('datetime')
                when_text = format_day_month(when) if when else 'unknown'
                items.append({
                    'name': 'Stocktake',
                    'detail': f"Last count {when_text} ({days} days) - {label}",
                    'tag': 'Stocktake',
                    'target': 'stocktake',
                })

        # Backup age: the app takes a daily auto-backup at startup, so a gap
        # of several days is worth chasing.
        backup_status = backup_health.get('status')
        if backup_status in ('none', 'warning', 'overdue'):
            latest = backup_health.get('latest')
            if latest is None:
                detail = 'No backup found'
            else:
                detail = (f"Last backup {format_day_month(latest)} "
                          f"({backup_health.get('age_days')} days)")
            items.append({
                'name': 'Backup',
                'detail': detail,
                'tag': 'Backup',
                'target': 'backup',
            })

        for alert in (price_alerts or [])[:3]:
            items.append({
                'name': alert.get('item_name', 'Price change'),
                'detail': (f"Cost £{alert['old_cost']:,.2f} → "
                           f"£{alert['new_cost']:,.2f} "
                           f"({alert['change_pct']:+.1f}%)"),
                'tag': 'Price',
                'target': 'price_history',
            })

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
                        'target': 'stock',
                    })
                elif reorder > 0 and qty <= reorder:
                    items.append({
                        'name': name,
                        'detail': f"{qty:.0f} {measure.lower()} left".replace('  ', ' '),
                        'tag': 'Low',
                        'target': 'stock',
                    })

        seen = set()
        unique = []
        for item in items:
            key = (item['name'], item['tag'])
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique

    def _attention_command(self, target):
        """Map an attention target to the screen that resolves it."""
        return {
            'open_tabs': self.show_open_tabs,
            'sales_upload': self.show_sales_upload,
            'stock': self.manage_initial_stock,
            'stocktake': self.show_stocktake,
            'backup': self._backup_now,
            'price_history': self.generate_price_history_report,
        }.get(target)

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
