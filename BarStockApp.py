"""
Bar Stock Management System - Basic Version

Simple tkinter-based bar stock management.
"""

import tkinter as tk
from tkinter import messagebox, ttk, filedialog, simpledialog
import pandas as pd
import json
import os
import sys
import logging
from datetime import datetime, timedelta
from collections import defaultdict
import calendar
import re
from fpdf import FPDF
try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    pdfplumber = None
    PDFPLUMBER_AVAILABLE = False
from categories import get_category, should_exclude, is_delisted, CATEGORY_ORDER, EXCLUDED_ITEMS, SALES_INCLUDED_EXCLUDED_ITEMS
from conversions import (
    get_conversion, convert_to_system, convert_to_input,
    get_input_label, format_stock_display, format_quantity_display, requires_conversion,
    DATE_FORMAT_DISPLAY, DATE_FORMAT_DISPLAY_LEGACY, parse_display_date,
)
from sales_mapping import (
    has_parent_stock, get_parent_for_sale, apply_sale_to_parent,
    check_apply_sale_to_parent, normalize_product_name,
    get_affected_parents_description, is_hidden_from_stock_view, get_hidden_items,
    get_effective_cost_price, resolve_epos_item_id
)
from supplier_mapping import get_supplier, get_supplier_order
from inventory_sync import (
    find_missing_mappings, has_sync_issues, format_sync_report,
    append_item_to_items_csv, update_items_csv_total_value,
    find_items_csv_inventory_mismatches,
    find_untracked_items_on_order_sheet, find_recent_negative_items,
)
from actions import (
    ACTION_SALES, ACTION_SALES_ONE_UNIT, ACTION_DELIVERY,
    ACTION_WASTAGE, ACTION_LINE_CLEAN, ACTION_COMPLIMENTARY,
    ACTION_OPEN_TAB, ACTION_TAB_CANCELLED, ACTION_PARENT_STOCK_ADJ,
    ACTION_STOCKTAKE_BASELINE, ACTION_IMPORT, ACTION_SUPPLIER_RETURN,
    ACTION_PRICE_UPDATE, SALE_ACTIONS,
)

# Analytics imports
try:
    import matplotlib
    matplotlib.use('TkAgg')
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib import dates as mdates
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False


# Data locations, schema column names and dropdown options live in
# app_config, and the colour tokens in ui_theme, so screen modules can import
# them without importing this module (which would be circular).
from app_config import *  # noqa: F401,F403
from app_config import (
    DATA_DIR, INVENTORY_FILE, LOG_FILE, get_downloads_dir,
    get_items_csv_path, get_resource_path, get_script_directory,
)
from ui_theme import *  # noqa: F401,F403
from ui_theme import THEME_FONT, THEME_FONT_STACK
import ui_theme
import club_profile
import security


from data_manager import (
    InventoryDataManager, get_setting, set_setting, AtomicTransaction,
    COL_ALLOW_NEGATIVE, COL_REORDER_LEVEL, COL_MEMBER_QTY, COL_NON_MEMBER_QTY,
    COL_DIVISION, COL_ID,
    record_stocktake, record_stocktakes, get_stocktake_history,
    clear_stocktake_snapshots, clear_transaction_archive,
    get_upload_hashes, add_upload_hash, is_duplicate_upload
)
import hashlib
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
    build_custom_stock_order_sheet_data
)

from app_runtime import (
    APP_VERSION,
    setup_logging,
    acquire_single_instance_lock,
    install_exception_hooks,
    get_log_path,
)

logger = logging.getLogger(__name__)

# Configure logging and take the single-instance lock before touching the
# database, so two copies cannot migrate or save at the same time.
setup_logging()
INSTANCE_LOCK = acquire_single_instance_lock()

# Initialize database (migrates from CSV on first run)
InventoryDataManager.initialize_csv_files()

# Settings cache
MEMBER_DISCOUNT_PCT = 10




# Screen groups live in their own modules; the mixins share the shell helpers
# and application state defined below.
from screens.dashboard import DashboardMixin
from screens.deliveries import DeliveriesMixin
from screens.inventory import InventoryMixin
from screens.reports import ReportsMixin
from screens.stocktake import StocktakeMixin
from screens.transactions import TransactionsMixin
from screens.uploads import UploadsMixin
from screens.widgets import DateRangeDialog


class BarStockManagementSystem(DashboardMixin, DeliveriesMixin, InventoryMixin,
                               ReportsMixin, StocktakeMixin, TransactionsMixin,
                               UploadsMixin):
    """Main application class for the Bar Stock Management System."""

    def __init__(self, root):
        """Initialize the application window and UI elements."""
        self.root = root
        # Apply profile item rules once, before any screen reads the maps.
        try:
            club_profile.apply_item_rules()
        except Exception:
            logger.warning("Could not apply club item rules", exc_info=True)
        try:
            club_profile.apply_settings_overrides(get_setting)
        except Exception:
            logger.warning("Could not apply club profile settings", exc_info=True)

        self.root.title(
            f"{club_profile.club_name()} - "
            f"{club_profile.app_display_name()} v{APP_VERSION}")
        self._logo_image = None
        logo_path = club_profile.get_logo_path()
        if logo_path:
            try:
                self._logo_image = tk.PhotoImage(file=logo_path)
                self.root.iconphoto(True, self._logo_image)
            except tk.TclError:
                self._logo_image = None
        # Maximize window on launch
        self.root.update_idletasks()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        self.root.geometry(f"{screen_width}x{screen_height}+0+0")
        try:
            self.root.state('zoomed')
        except tk.TclError:
            pass

        # macOS-specific: Bring window to front
        self.root.lift()
        self.root.attributes('-topmost', True)
        self.root.after_idle(self.root.attributes, '-topmost', False)

        # Configure dark dashboard theme
        self.setup_theme()

        # Set up exit confirmation
        self.root.protocol("WM_DELETE_WINDOW", self.on_exit)

        # Load data
        self.inventory_df = InventoryDataManager.load_inventory()
        self.log_df = InventoryDataManager.load_log()
        # Snapshot of what was loaded. Saves write the difference between this
        # and the current frame, so a window that is left open cannot clobber
        # newer stock movements written by another process.
        self._inventory_snapshot = self.inventory_df.copy()
        self._log_snapshot_ids = self._current_log_ids()

        # Keep the bundled CSV mirrors current even if the previous session
        # ended without a save.
        InventoryDataManager.export_csv_mirrors(self.inventory_df)

        # Daily auto-backup check
        try:
            from data_manager import create_auto_backup
            auto_path = create_auto_backup()
            if auto_path:
                logger.info("Auto-backup created: %s", auto_path)
        except Exception:
            logger.warning("Auto-backup check failed", exc_info=True)

        # Sync check: collect any missing conversion/category/order-sheet mappings
        # so they can be shown in a non-blocking dashboard banner instead of a modal dialog.
        self.startup_sync_report = None
        if club_profile.feature_enabled('mapping_warnings'):
            try:
                missing = find_missing_mappings(self.inventory_df)
                if has_sync_issues(missing):
                    self.startup_sync_report = format_sync_report(missing)
            except Exception as e:
                print(f"Startup sync check failed: {e}")

        # Reconcile inventory against its own transaction log. A failure here
        # means every balance and report below it is wrong, so surface it on
        # the dashboard instead of waiting for someone to run audit_data.py.
        self.startup_integrity_report = None
        try:
            from audit_data import reconcile_inventory
            integrity_issues = reconcile_inventory()
            if integrity_issues:
                shown = integrity_issues[:8]
                if len(integrity_issues) > len(shown):
                    shown.append(f"...and {len(integrity_issues) - len(shown)} more")
                self.startup_integrity_report = "\n".join(shown)
                logger.warning(
                    "Startup reconciliation found %d issue(s)", len(integrity_issues)
                )
        except Exception:
            logger.warning("Startup reconciliation check failed", exc_info=True)

        # Capture any cost-price changes applied from the bundled stock.csv so the
        # dashboard banner can report them on startup.
        self.startup_price_sync_report = None
        try:
            from data_manager import get_csv_sync_changes
            csv_changes = get_csv_sync_changes()
            if csv_changes:
                lines = ["Prices updated from stock.csv:"]
                for item_id, old_cost, new_cost in csv_changes:
                    diff = new_cost - old_cost
                    pct = (diff / old_cost * 100) if old_cost > 0 else 0.0
                    lines.append(
                        f"  • {item_id}: £{old_cost:.4f} → £{new_cost:.4f} "
                        f"({diff:+.4f}, {pct:+.1f}%)"
                    )
                self.startup_price_sync_report = "\n".join(lines)
        except Exception as e:
            print(f"Startup price sync check failed: {e}")

        self.create_widgets()
        self._install_shortcuts()

        # First run: the database starts empty by design (no client data is
        # bundled), so point the user at the import path rather than showing a
        # bare dashboard.
        if self.inventory_df.empty:
            self.root.after(
                300,
                lambda: messagebox.showinfo(
                    "Welcome to BarStock",
                    "No stock items have been set up yet.\n\n"
                    "Use More Actions → System → Init from Items.csv to import "
                    "an item list, or add items individually in Manage Stock.",
                ),
            )

    def setup_theme(self):
        """Configure the application-wide Ledger theme."""
        global THEME_FONT
        try:
            THEME_FONT = ui_theme.resolve_font(self.root)
            # Screen modules read the families from ui_theme at draw time.
            ui_theme.THEME_FONT = THEME_FONT
            ui_theme.THEME_DISPLAY_FONT = ui_theme.resolve_display_font(self.root)
            ui_theme.THEME_MONO_FONT = ui_theme.resolve_mono_font(self.root)
        except Exception:
            pass

        self.root.configure(bg=THEME_BG)
        # Theme standard Tk widgets at creation time as well as by recolouring
        # afterwards.  Without this every legacy dialog and option menu is
        # built with platform defaults and only turns light once
        # _apply_legacy_theme walks it, which shows as a flash when it opens.
        self.root.option_add('*Background', THEME_BG)
        self.root.option_add('*Foreground', THEME_TEXT)
        self.root.option_add('*selectBackground', THEME_ACCENT)
        self.root.option_add('*selectForeground', THEME_ACCENT_INK)
        self.root.option_add('*highlightBackground', THEME_BORDER)
        self.root.option_add('*highlightColor', THEME_ACCENT)
        self.root.option_add('*TCombobox*Listbox.background', THEME_CARD)
        self.root.option_add('*TCombobox*Listbox.foreground', THEME_TEXT)
        self.root.option_add('*TCombobox*Listbox.selectBackground', THEME_ACCENT)
        self.root.option_add('*TCombobox*Listbox.selectForeground', THEME_ACCENT_INK)
        self.root.option_add('*Menu.background', THEME_CARD)
        self.root.option_add('*Menu.foreground', THEME_TEXT)
        self.root.option_add('*Menu.activeBackground', THEME_ACCENT)
        self.root.option_add('*Menu.activeForeground', THEME_ACCENT_INK)

        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background=THEME_BG)
        style.configure('TLabel', background=THEME_BG, foreground=THEME_TEXT,
                        font=(THEME_FONT, 12))
        style.configure('TButton', background=THEME_ACCENT,
                        foreground=THEME_ACCENT_INK, font=(THEME_FONT, 11),
                        bordercolor=THEME_ACCENT, relief='flat')
        style.map('TButton',
                  background=[('pressed', THEME_ACCENT_HOVER),
                              ('active', THEME_ACCENT_HOVER)],
                  foreground=[('disabled', THEME_TEXT_MUTED)])
        style.configure('Primary.TButton', background=THEME_ACCENT,
                        foreground=THEME_ACCENT_INK,
                        font=(THEME_FONT, 11), padding=(12, 7),
                        borderwidth=0, focusthickness=1,
                        focuscolor=THEME_ACCENT)
        style.map('Primary.TButton',
                  background=[('pressed', THEME_ACCENT_HOVER),
                              ('active', THEME_ACCENT_HOVER)],
                  foreground=[('disabled', THEME_TEXT_MUTED)])
        style.configure('Secondary.TButton', background=THEME_CARD,
                        foreground=THEME_TEXT, font=(THEME_FONT, 11),
                        padding=(12, 6), borderwidth=1,
                        bordercolor=THEME_BORDER, lightcolor=THEME_CARD,
                        darkcolor=THEME_BORDER, relief='solid',
                        focusthickness=1, focuscolor=THEME_ACCENT)
        style.map('Secondary.TButton',
                  background=[('pressed', TBL_ROW_ALT),
                              ('active', TBL_ROW_ALT)],
                  bordercolor=[('focus', THEME_ACCENT)])
        style.configure('Ghost.TButton', background=THEME_SIDEBAR,
                        foreground=THEME_TEXT, font=(THEME_FONT, 11),
                        padding=(12, 7), borderwidth=0,
                        focusthickness=1, focuscolor=THEME_ACCENT)
        style.map('Ghost.TButton',
                  background=[('pressed', TBL_ROW_ALT),
                              ('active', TBL_ROW_ALT)])
        style.configure('Danger.TButton', background=THEME_DANGER,
                        foreground=THEME_ACCENT_INK,
                        font=(THEME_FONT, 11), padding=(12, 7),
                        borderwidth=0, focusthickness=1,
                        focuscolor=THEME_DANGER)
        style.map('Danger.TButton',
                  background=[('pressed', THEME_DANGER_HOVER),
                              ('active', THEME_DANGER_HOVER)],
                  foreground=[('disabled', THEME_TEXT_MUTED)])
        style.configure('Card.TFrame', background=THEME_CARD)
        style.configure('CardTitle.TLabel', background=THEME_CARD,
                        foreground=THEME_TEXT_MUTED, font=(THEME_FONT, 10))
        style.configure('CardValue.TLabel', background=THEME_CARD,
                        foreground=THEME_TEXT, font=(THEME_FONT, 22, 'bold'))
        style.configure('CardSub.TLabel', background=THEME_CARD,
                        foreground=THEME_TEXT_MUTED, font=(THEME_FONT, 10))
        style.configure('Treeview', background=THEME_BG, foreground=THEME_TEXT,
                        fieldbackground=THEME_BG, rowheight=28,
                        bordercolor=THEME_BORDER, lightcolor=THEME_BORDER,
                        darkcolor=THEME_BORDER)
        # A pale selection keeps per-row tag colours (warning, danger, muted)
        # readable; a bottle fill would swallow their ink.
        style.map('Treeview',
                  background=[('selected', TBL_ROW_ALT)],
                  foreground=[('selected', THEME_TEXT)])
        style.configure('Treeview.Heading', background=THEME_SIDEBAR,
                        foreground=THEME_TEXT, font=(THEME_FONT, 10, 'bold'),
                        relief='flat', bordercolor=THEME_BORDER,
                        lightcolor=THEME_SIDEBAR, darkcolor=THEME_BORDER)
        style.map('Treeview.Heading',
                  background=[('active', THEME_BORDER)])
        style.configure('TCombobox', background=THEME_CARD, foreground=THEME_TEXT,
                        fieldbackground=THEME_CARD, arrowcolor=THEME_ACCENT,
                        bordercolor=THEME_BORDER, lightcolor=THEME_BORDER,
                        darkcolor=THEME_BORDER)
        style.map('TCombobox', fieldbackground=[('readonly', THEME_CARD)],
                  foreground=[('readonly', THEME_TEXT)],
                  selectbackground=[('readonly', THEME_CARD)],
                  selectforeground=[('readonly', THEME_TEXT)],
                  bordercolor=[('focus', THEME_ACCENT)])
        style.configure('TEntry', background=THEME_CARD, foreground=THEME_TEXT,
                        fieldbackground=THEME_CARD, insertcolor=THEME_TEXT,
                        bordercolor=THEME_BORDER, lightcolor=THEME_BORDER,
                        darkcolor=THEME_BORDER)
        style.map('TEntry', bordercolor=[('focus', THEME_ACCENT)])
        style.configure('TScrollbar', background=THEME_SIDEBAR,
                        troughcolor=THEME_BG, bordercolor=THEME_BORDER,
                        arrowcolor=THEME_TEXT_MUTED)
        style.map('TScrollbar', background=[('active', THEME_BORDER)])
        style.configure('Horizontal.TProgressbar', background=THEME_ACCENT,
                        troughcolor=THEME_SIDEBAR, bordercolor=THEME_BORDER,
                        lightcolor=THEME_ACCENT, darkcolor=THEME_ACCENT)
        style.configure('TNotebook', background=THEME_BG,
                        borderwidth=0, tabmargins=(0, 4, 0, 0))
        style.configure('TNotebook.Tab', background=THEME_BG,
                        foreground=THEME_TEXT_MUTED, font=(THEME_FONT, 10),
                        padding=(16, 7), borderwidth=0,
                        bordercolor=THEME_BG, lightcolor=THEME_BG,
                        darkcolor=THEME_BG)
        style.map('TNotebook.Tab',
                  background=[('selected', THEME_BG)],
                  foreground=[('selected', THEME_TEXT)],
                  font=[('selected', (THEME_FONT, 10, 'bold'))],
                  lightcolor=[('selected', THEME_ACCENT)])
        style.configure('TCheckbutton', background=THEME_BG,
                        foreground=THEME_TEXT, font=(THEME_FONT, 11),
                        indicatorcolor=THEME_CARD,
                        indicatorbackground=THEME_CARD)
        style.map('TCheckbutton',
                  background=[('active', THEME_BG)],
                  indicatorcolor=[('selected', THEME_ACCENT),
                                  ('active', THEME_CARD)])
        style.configure('TRadiobutton', background=THEME_BG,
                        foreground=THEME_TEXT, font=(THEME_FONT, 11),
                        indicatorcolor=THEME_CARD)
        style.map('TRadiobutton',
                  background=[('active', THEME_BG)],
                  indicatorcolor=[('selected', THEME_ACCENT),
                                  ('active', THEME_CARD)])
        style.configure('TSeparator', background=THEME_BORDER)
        style.configure('TLabelFrame', background=THEME_BG,
                        bordercolor=THEME_BORDER, relief='solid',
                        labelmargins=6)
        style.configure('TLabelFrame.Label', background=THEME_BG,
                        foreground=THEME_TEXT_MUTED,
                        font=(THEME_FONT, 9, 'bold'))

    def themed_frame(self, parent=None, bg=None, **kwargs):
        """Create a Frame with theme background."""
        parent = parent or self.main_menu
        return tk.Frame(parent, bg=bg or THEME_BG, **kwargs)

    def themed_label(self, parent, text, font=None, fg=None, bg=None, **kwargs):
        """Create a Label using theme colors."""
        return tk.Label(
            parent, text=text, font=font or (THEME_FONT, 12),
            fg=fg or THEME_TEXT, bg=bg or THEME_BG, **kwargs
        )

    def styled_entry(self, parent, **kwargs):
        """Create an Entry with a ruled paper field and visible focus ring."""
        kwargs.setdefault('bg', THEME_CARD)
        kwargs.setdefault('fg', THEME_TEXT)
        kwargs.setdefault('insertbackground', THEME_TEXT)
        kwargs.setdefault('relief', 'flat')
        kwargs.setdefault('highlightthickness', 1)
        kwargs.setdefault('highlightbackground', THEME_BORDER)
        kwargs.setdefault('highlightcolor', THEME_ACCENT)
        return tk.Entry(parent, **kwargs)

    def styled_button(self, parent, text, command, width=22, variant='primary', **kwargs):
        """Create a Ledger button.

        ttk buttons are used because macOS ignores the background colour of a
        classic ``tk.Button``; the clam theme honours these styles exactly.
        """
        style_name = {
            'primary': 'Primary.TButton',
            'danger': 'Danger.TButton',
            'ghost': 'Ghost.TButton',
            'secondary': 'Secondary.TButton',
        }.get(variant, 'Secondary.TButton')
        font = kwargs.pop('font', None)
        if font:
            # A caller-supplied font needs its own derived style.
            derived = f"{style_name.split('.')[0]}{abs(hash(str(font))) % 10000}.TButton"
            ttk.Style().configure(derived, font=font)
            style_name = derived
        return ttk.Button(parent, text=text, command=command, width=width,
                          style=style_name, cursor='hand2', **kwargs)

    def tile_button(self, parent, text, command):
        """Create a clickable tile that also works from the keyboard.

        Tk labels are not focusable by default, so the tile opts into the tab
        order explicitly and activates on Return/Space.  The focus ring is a
        highlight border in the accent colour.
        """
        tile = tk.Label(
            parent, text=text, font=(THEME_FONT, 12, 'bold'),
            bg=THEME_CARD, fg=THEME_TEXT, cursor='hand2',
            padx=12, pady=14, anchor='center',
            takefocus=1, highlightthickness=2,
            highlightbackground=THEME_CARD, highlightcolor=THEME_ACCENT,
        )
        tile.bind('<Button-1>', lambda event: (command(), 'break')[1])

        def activate(event=None):
            command()
            return 'break'

        def on_enter(event):
            tile.config(bg=TBL_ROW_ALT)

        def on_leave(event):
            tile.config(bg=THEME_CARD, fg=THEME_TEXT)

        def on_focus_in(event):
            tile.config(bg=TBL_ROW_ALT, highlightbackground=THEME_ACCENT)

        def on_focus_out(event):
            tile.config(bg=THEME_CARD, fg=THEME_TEXT,
                        highlightbackground=THEME_CARD)

        tile.bind('<Enter>', on_enter)
        tile.bind('<Leave>', on_leave)
        tile.bind('<Return>', activate)
        tile.bind('<space>', activate)
        tile.bind('<FocusIn>', on_focus_in)
        tile.bind('<FocusOut>', on_focus_out)
        return tile

    def report_row(self, parent, title, description, command, badge=None):
        """Create a compact report row with a description and an open affordance.

        The whole row is the target: click, Return or Space runs the report.
        Hover and focus share one highlight so the row behaves like a native
        list item rather than a flat label.
        """
        row = tk.Frame(parent, bg=THEME_BG, cursor='hand2', takefocus=1,
                       highlightthickness=1, highlightbackground=THEME_BG,
                       highlightcolor=THEME_ACCENT)
        body = tk.Frame(row, bg=THEME_BG)
        body.pack(side='left', fill='x', expand=True, padx=(14, 8), pady=9)
        body.grid_columnconfigure(0, minsize=280)
        body.grid_columnconfigure(1, weight=1)

        title_label = tk.Label(body, text=title, font=ui_theme.display_font(12),
                               fg=THEME_TEXT, bg=THEME_BG, anchor='w')
        title_label.grid(row=0, column=0, sticky='w')
        description_label = tk.Label(body, text=description,
                                     font=(THEME_FONT, 10),
                                     fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w')
        description_label.grid(row=0, column=1, sticky='w', padx=(16, 0))

        right = tk.Frame(row, bg=THEME_BG)
        right.pack(side='right', padx=(0, 14))
        arrow = tk.Label(right, text='→', font=(THEME_FONT, 13),
                         fg=THEME_WARNING, bg=THEME_BG)
        arrow.pack(side='right')
        badge_label = None
        if badge:
            badge_label = tk.Label(right, text=badge.upper(),
                                   font=ui_theme.mono_font(8),
                                   fg=THEME_WARNING, bg=THEME_BG, padx=6,
                                   bd=1, relief='solid')
            badge_label.pack(side='right', padx=(0, 10))

        widgets = [row, body, title_label, description_label, right, arrow]
        if badge_label:
            widgets.append(badge_label)

        state = {'hover': False, 'focus': False}
        pending = [None]

        def refresh():
            active = state['hover'] or state['focus']
            bg = TBL_ROW_ALT if active else THEME_BG
            for widget in widgets:
                widget.configure(bg=bg)
            title_label.configure(fg=THEME_TEXT)
            arrow.configure(fg=THEME_WARNING if active else THEME_TEXT_MUTED)

        def set_hover(active):
            state['hover'] = active
            refresh()

        def on_enter(event=None):
            if pending[0] is not None:
                row.after_cancel(pending[0])
                pending[0] = None
            set_hover(True)

        def clear_hover():
            pending[0] = None
            if row.winfo_exists():
                set_hover(False)

        def on_leave(event=None):
            # Moving onto a child fires Leave on the parent; wait one tick so
            # the child's Enter can cancel the reset.
            if pending[0] is not None:
                row.after_cancel(pending[0])
            pending[0] = row.after(40, clear_hover)

        def on_focus_in(event=None):
            state['focus'] = True
            row.configure(highlightbackground=THEME_ACCENT)
            refresh()

        def on_focus_out(event=None):
            state['focus'] = False
            row.configure(highlightbackground=THEME_BG)
            refresh()

        def activate(event=None):
            command()
            return 'break'

        def on_click(event=None):
            command()
            return 'break'

        row.bind('<Enter>', on_enter)
        row.bind('<Leave>', on_leave)
        for widget in widgets:
            widget.bind('<Enter>', on_enter, add='+')
            widget.bind('<Leave>', on_leave, add='+')
            widget.bind('<Button-1>', on_click)
        row.bind('<Return>', activate)
        row.bind('<space>', activate)
        row.bind('<FocusIn>', on_focus_in)
        row.bind('<FocusOut>', on_focus_out)
        return row

    def create_card(self, parent, title, value, subtext='', status='normal'):
        """Create a ruled summary block (no fill, one hairline border)."""
        card = tk.Frame(parent, bg=THEME_BG, bd=0,
                         highlightbackground=THEME_BORDER, highlightthickness=1)
        if getattr(parent, '_cards_grid', False):
            # Grid keeps every card the same width; pack sized cards by their
            # longest subtext, which made some cards tiny next to others.
            column = len(parent.grid_slaves())
            card.grid(row=0, column=column, sticky='nsew', padx=8, pady=5)
            parent.grid_columnconfigure(column, weight=1, uniform='cards')
            parent.grid_rowconfigure(0, weight=1)
        else:
            card.pack(side='left', fill='both', expand=True, padx=8, pady=5)

        title_lbl = tk.Label(card, text=title.upper(), font=ui_theme.mono_font(8),
                             fg=THEME_TEXT_MUTED, bg=THEME_BG)
        title_lbl.pack(anchor='w', padx=14, pady=(12, 4))

        value_color = THEME_TEXT
        if status == 'danger':
            value_color = THEME_DANGER
        elif status == 'warning':
            value_color = THEME_WARNING
        value_lbl = tk.Label(card, text=value, font=ui_theme.display_font(24),
                             fg=value_color, bg=THEME_BG)
        value_lbl.pack(anchor='w', padx=14)

        sub_lbl = None
        if subtext:
            sub_lbl = tk.Label(card, text=subtext, font=(THEME_FONT, 9),
                               fg=THEME_TEXT_MUTED if status == 'normal' else value_color,
                               bg=THEME_BG)
            sub_lbl.pack(anchor='w', padx=14, pady=(4, 14))
        else:
            tk.Label(card, text='', bg=THEME_BG).pack(pady=(0, 8))

        # Cards share the row width equally, so on a narrower window the value
        # label (e.g. a full timestamp) used to be clipped by the card edge.
        # Wrap the text to the available width and step the value font down
        # before resorting to wrapping.
        def _fit_labels(event=None):
            width = card.winfo_width()
            if width < 40 or width == getattr(card, '_fitted_width', None):
                return
            card._fitted_width = width
            available = max(width - 28, 40)
            title_lbl.configure(wraplength=available)
            value_lbl.configure(wraplength=available)
            if sub_lbl is not None:
                sub_lbl.configure(wraplength=available)
            if width < 120:
                size = 14
            elif width < 160:
                size = 18
            else:
                size = 24
            value_lbl.configure(font=(THEME_FONT, size, 'bold'))

        card.bind('<Configure>', _fit_labels)
        return card

    def create_panel(self, parent, title):
        """Create a ruled panel with a mono heading."""
        panel = tk.Frame(parent, bg=THEME_PANEL, bd=0,
                         highlightbackground=THEME_BORDER, highlightthickness=1)
        panel.pack(fill='x', padx=8, pady=8)
        title_lbl = tk.Label(panel, text=title.upper(),
                             font=ui_theme.mono_font(9, 'bold'),
                             fg=THEME_TEXT_MUTED, bg=THEME_PANEL)
        title_lbl.pack(anchor='w', padx=14, pady=(12, 8))
        return panel

    def on_exit(self):
        """Confirm before exiting the application.

        Nothing is saved here.  Every stock movement is written to SQLite at
        the moment it is recorded, so an exit-time save could only ever write
        stale in-memory frames over newer data (this is what silently undid a
        stocktake, and could revert deliveries made while the window was open).
        """
        if messagebox.askyesno("Confirm Exit", "Are you sure you want to exit?"):
            self.root.quit()

    def create_widgets(self):
        """Create and arrange all UI widgets in the application window."""
        # Shell container holds the top bar, tabs, and the scrollable content area.
        self.shell_container = tk.Frame(self.root, bg=THEME_BG)
        self.shell_container.pack(fill="both", expand=True)

        self.show_dashboard()

    def get_member_discount_pct(self):
        """Get configured member discount percentage (default 10)."""
        try:
            val = get_setting('member_discount_pct', '10')
            return float(val)
        except Exception:
            return 10.0

    def get_member_multiplier(self):
        """Return multiplier for member pricing (e.g., 0.9 for 10% off)."""
        return (100 - self.get_member_discount_pct()) / 100

    def check_negative_stock(self, item_id, deduction_qty):
        """Check if deducting quantity would cause negative stock. Returns (ok, current_qty, allow_negative)."""
        if self.inventory_df.empty or item_id not in self.inventory_df[COL_ITEM_ID].values:
            return False, 0, False
        current_qty = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY].values[0]
        allow_negative = InventoryDataManager.get_item_value_safe(
            self.inventory_df, item_id, COL_ALLOW_NEGATIVE, default=False)
        if not allow_negative and current_qty < deduction_qty:
            return False, current_qty, allow_negative
        return True, current_qty, allow_negative

    def show_calendar(self, date_var, parent_widget):
        """Open a popup calendar to pick a delivery date."""
        top = tk.Toplevel(self.root)
        top.title("Select Date")
        top.geometry("400x420")
        self._fit_dialog(top, 400, 420)
        top.minsize(400, 420)
        top.transient(parent_widget)
        top.grab_set()
        top.lift()
        top.configure(bg=THEME_BG)

        # Parse current date from the variable
        current_text = date_var.get().strip()
        try:
            current_date = parse_display_date(current_text)
        except ValueError:
            current_date = datetime.now()

        year = current_date.year
        month = current_date.month
        day = current_date.day

        month_var = tk.StringVar(value=calendar.month_name[month])
        year_var = tk.StringVar(value=str(year))

        shell = tk.Frame(top, bg=THEME_BG, padx=20, pady=18)
        shell.pack(fill='both', expand=True)

        header_frame = tk.Frame(shell, bg=THEME_BG)
        header_frame.pack(fill='x', pady=(0, 12))

        days_frame = tk.Frame(shell, bg=THEME_BG)
        days_frame.pack(fill='x')

        def refresh_days():
            for widget in days_frame.winfo_children():
                widget.destroy()

            y = int(year_var.get())
            m = list(calendar.month_name).index(month_var.get())

            # Weekday headers
            for i, wd in enumerate(['Mon', 'Tue', 'Wed', 'Thu',
                                    'Fri', 'Sat', 'Sun']):
                tk.Label(days_frame, text=wd, font=ui_theme.mono_font(8),
                         fg=THEME_TEXT_MUTED, bg=THEME_BG, width=5).grid(
                    row=0, column=i, padx=2, pady=(0, 6))

            cal = calendar.Calendar()
            month_days = cal.monthdayscalendar(y, m)

            for r, week in enumerate(month_days, start=1):
                for c, d in enumerate(week):
                    if d == 0:
                        tk.Label(days_frame, text="", width=5,
                                 bg=THEME_BG).grid(row=r, column=c)
                        continue
                    selected = d == day and y == year and m == month
                    cell = tk.Label(
                        days_frame, text=str(d), width=5, pady=5,
                        font=(THEME_FONT, 10, 'bold' if selected else 'normal'),
                        fg=THEME_ACCENT_INK if selected else THEME_TEXT,
                        bg=THEME_ACCENT if selected else THEME_BG,
                        cursor='hand2', takefocus=1,
                        highlightthickness=1,
                        highlightbackground=THEME_BG,
                        highlightcolor=THEME_ACCENT)
                    cell.grid(row=r, column=c, padx=2, pady=2)
                    cell.bind('<Button-1>',
                              lambda e, y=y, m=m, d=d: select_date(y, m, d))
                    cell.bind('<Return>',
                              lambda e, y=y, m=m, d=d: select_date(y, m, d))
                    cell.bind('<space>',
                              lambda e, y=y, m=m, d=d: select_date(y, m, d))

                    def hover_on(event, cell=cell, selected=selected):
                        if not selected:
                            cell.config(bg=TBL_ROW_ALT)

                    def hover_off(event, cell=cell, selected=selected):
                        if not selected:
                            cell.config(bg=THEME_BG)

                    cell.bind('<Enter>', hover_on)
                    cell.bind('<Leave>', hover_off)

        def select_date(y, m, d):
            date_var.set(f"{d:02d}-{m:02d}-{y}")
            top.destroy()

        def prev_month():
            m = list(calendar.month_name).index(month_var.get())
            y = int(year_var.get())
            m -= 1
            if m < 1:
                m = 12
                y -= 1
            month_var.set(calendar.month_name[m])
            year_var.set(str(y))
            refresh_days()

        def next_month():
            m = list(calendar.month_name).index(month_var.get())
            y = int(year_var.get())
            m += 1
            if m > 12:
                m = 1
                y += 1
            month_var.set(calendar.month_name[m])
            year_var.set(str(y))
            refresh_days()

        self.styled_button(header_frame, "‹", prev_month, width=3,
                           variant='secondary').pack(side='left')
        tk.Label(header_frame, textvariable=month_var,
                 font=ui_theme.display_font(15), fg=THEME_TEXT,
                 bg=THEME_BG, width=10).pack(side='left', padx=(10, 2))
        tk.Label(header_frame, textvariable=year_var,
                 font=ui_theme.mono_font(10), fg=THEME_TEXT_MUTED,
                 bg=THEME_BG).pack(side='left')
        self.styled_button(header_frame, "›", next_month, width=3,
                           variant='secondary').pack(side='right')

        refresh_days()

        def select_today():
            now = datetime.now()
            select_date(now.year, now.month, now.day)

        footer = tk.Frame(shell, bg=THEME_BG)
        footer.pack(fill='x', pady=(14, 0))
        tk.Frame(footer, bg=THEME_BORDER, height=1).pack(fill='x',
                                                          pady=(0, 12))
        self.styled_button(footer, "Today", select_today, width=12,
                           variant='secondary').pack(side='left')
        self.styled_button(footer, "Cancel", top.destroy, width=12,
                           variant='secondary').pack(side='right')

    def _create_app_shell(self, active_tab):
        """Build the Ledger rail, topbar, status bar and scrollable content."""
        for widget in self.shell_container.winfo_children():
            widget.destroy()

        self.active_tab = active_tab
        self.shell_container.configure(bg=THEME_BG)

        # Status bar: routine feedback lands here instead of in a modal dialog.
        self.status_var = tk.StringVar(value="")
        tk.Frame(self.shell_container, bg=THEME_BORDER, height=1).pack(
            side='bottom', fill='x')
        status_bar = tk.Frame(self.shell_container, bg=THEME_SIDEBAR, height=26)
        status_bar.pack(side='bottom', fill='x')
        status_bar.pack_propagate(False)
        self.status_label = tk.Label(status_bar, textvariable=self.status_var,
                                     font=ui_theme.mono_font(9), fg=THEME_TEXT_MUTED,
                                     bg=THEME_SIDEBAR, anchor='w')
        self.status_label.pack(side='left', fill='x', padx=16)
        # A save usually navigates to another screen, which rebuilds this shell.
        # Carry the last message over so it is still visible after the rebuild.
        carried = getattr(self, '_status_message', '')
        if carried:
            self.status_var.set(carried)
            self.status_label.config(fg=self._status_colour(getattr(self, '_status_kind', 'info')))
            self.root.after(8000, lambda: self._clear_status_if(carried))

        body = tk.Frame(self.shell_container, bg=THEME_BG)
        body.pack(fill='both', expand=True)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        # Left rail ---------------------------------------------------------
        rail_outer = tk.Frame(body, bg=THEME_BORDER, width=207)
        rail_outer.grid(row=0, column=0, sticky='ns')
        rail_outer.grid_propagate(False)
        sidebar = tk.Frame(rail_outer, bg=THEME_SIDEBAR)
        sidebar.pack(fill='both', expand=True, padx=(0, 1))
        self.sidebar = sidebar

        brand = tk.Frame(sidebar, bg=THEME_SIDEBAR)
        brand.pack(fill='x', padx=18, pady=(22, 16))
        crest = tk.Frame(brand, bg=THEME_SIDEBAR, width=40, height=40,
                         highlightbackground=THEME_TEXT, highlightthickness=1)
        crest.pack(side='left')
        crest.pack_propagate(False)
        logo_shown = False
        if self._logo_image is not None:
            try:
                # The bundled crest is 160px; 40px keeps the rail proportions.
                self._sidebar_logo = self._logo_image.subsample(4)
                tk.Label(crest, image=self._sidebar_logo,
                         bg=THEME_SIDEBAR).pack(expand=True)
                logo_shown = True
            except tk.TclError:
                self._sidebar_logo = None
        if not logo_shown:
            tk.Label(crest, text=club_profile.crest_text(),
                     font=ui_theme.display_font(13),
                     fg=THEME_TEXT, bg=THEME_SIDEBAR).pack(expand=True)
        names = tk.Frame(brand, bg=THEME_SIDEBAR)
        names.pack(side='left', padx=(10, 0))
        tk.Label(names, text=club_profile.club_short_name(),
                 font=ui_theme.display_font(14),
                 fg=THEME_TEXT, bg=THEME_SIDEBAR, anchor='w').pack(fill='x')
        tk.Label(names, text=club_profile.strap_line(),
                 font=(THEME_FONT, 9),
                 fg=THEME_TEXT_MUTED, bg=THEME_SIDEBAR, anchor='w').pack(fill='x')

        groups = [
            ("OPERATIONS", [
                ("Dashboard", self.show_dashboard),
                ("Deliveries", self.show_deliveries),
                ("Stocktake", self.show_stocktake),
                ("Sales Upload", self.show_sales_upload),
            ]),
            ("RECORDS", [
                ("Reports", self.show_reports),
                ("Transactions", self.show_transactions),
                ("Delivery History", self.show_delivery_history),
                ("Open Tabs", self.show_open_tabs),
            ]),
            ("SYSTEM", [
                ("Settings", self.open_settings),
                ("More Actions", self.show_more),
            ]),
        ]
        for heading, items in groups:
            tk.Label(sidebar, text=heading, font=ui_theme.mono_font(8),
                     fg=THEME_TEXT_MUTED, bg=THEME_SIDEBAR, anchor='w').pack(
                fill='x', padx=18, pady=(16, 4))
            for text, command in items:
                self._nav_button(sidebar, text, command, active=(text == active_tab))

        footer = tk.Frame(sidebar, bg=THEME_SIDEBAR)
        footer.pack(side='bottom', fill='x', padx=18, pady=14)
        exit_link = tk.Label(footer, text="Save & exit",
                             font=(THEME_FONT, 10), fg=THEME_TEXT_MUTED,
                             bg=THEME_SIDEBAR, anchor='w', cursor='hand2',
                             takefocus=1)
        exit_link.pack(fill='x', pady=(0, 8))
        exit_link.bind('<Button-1>', lambda e: (self.on_exit(), 'break')[1])
        exit_link.bind('<Return>', lambda e: (self.on_exit(), 'break')[1])
        tk.Label(footer, text=f"Stock control  ·  {APP_VERSION}",
                 font=ui_theme.mono_font(8), fg=THEME_TEXT_MUTED,
                 bg=THEME_SIDEBAR, anchor='w').pack(fill='x')

        # Main column -------------------------------------------------------
        main = tk.Frame(body, bg=THEME_BG)
        main.grid(row=0, column=1, sticky='nsew')

        topbar = tk.Frame(main, bg=THEME_BG)
        topbar.pack(fill='x', padx=28, pady=(22, 0))

        title_frame = tk.Frame(topbar, bg=THEME_BG)
        title_frame.pack(side='left', fill='y')
        now = datetime.now()
        tk.Label(title_frame, text=format_weekday_day_month(now).upper(),
                 font=ui_theme.mono_font(9), fg=THEME_TEXT_MUTED,
                 bg=THEME_BG, anchor='w').pack(fill='x', pady=(0, 4))
        if active_tab == "Dashboard":
            hour = now.hour
            part = "morning" if hour < 12 else ("afternoon" if hour < 18 else "evening")
            name = club_profile.greeting_name().strip()
            heading = f"Good {part}, {name}" if name else f"Good {part}"
            subtitle = f"Bar stock at {club_profile.club_name()}"
        else:
            heading = active_tab
            subtitle = {
                "Deliveries": "Record what arrived and what it cost",
                "Stocktake": "Count the bar against the system",
                "Sales Upload": "Bring in the EPOS sales file",
                "Reports": "Fourteen views, one skin",
                "Transactions": "Every movement, newest first",
                "Delivery History": "What came in, and when",
                "Open Tabs": "Tabs still running at the bar",
                "More Actions": "Everything else, grouped",
                "Manage Stock": "Add, edit, retire and restore products",
                "Wastage": "Record broken, out-of-date or overpoured stock",
                "Complimentary": "Drinks given away, with a reason",
                "Supplier Return": "Send damaged or credited stock back",
                "Single Sale": "Record one sale by hand",
                "New Tab": "Start a tab and add items",
                "Settings": "System preferences and data tools",
            }.get(active_tab, "Bar Stock Management")
        self._topbar_title = tk.Label(
            title_frame, text=heading, font=ui_theme.display_font(20),
            fg=THEME_TEXT, bg=THEME_BG)
        self._topbar_title.pack(anchor='w')
        self._topbar_subtitle = tk.Label(
            title_frame, text=subtitle, font=(THEME_FONT, 9),
            fg=THEME_TEXT_MUTED, bg=THEME_BG)
        self._topbar_subtitle.pack(anchor='w', pady=(2, 0))

        actions = tk.Frame(topbar, bg=THEME_BG)
        actions.pack(side='right', pady=(2, 0))
        self.styled_button(actions, "New delivery", self.show_deliveries,
                           width=12, variant='primary').pack(side='right')
        if active_tab == "Dashboard":
            self.styled_button(actions, "Upload sales", self.show_sales_upload,
                               width=12, variant='secondary').pack(
                side='right', padx=(0, 8))

        tk.Frame(main, bg=THEME_BORDER, height=1).pack(
            fill='x', padx=28, pady=(16, 0))

        # Scrollable content area
        content_outer = tk.Frame(main, bg=THEME_BG)
        content_outer.pack(fill='both', expand=True, padx=28, pady=(20, 24))
        content_outer.grid_rowconfigure(0, weight=1)
        content_outer.grid_columnconfigure(0, weight=1)

        canvas = tk.Canvas(content_outer, bg=THEME_BG, highlightthickness=0)
        canvas.grid(row=0, column=0, sticky='nsew')

        scrollbar = ttk.Scrollbar(content_outer, orient='vertical', command=canvas.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        canvas.configure(yscrollcommand=scrollbar.set)

        self.main_menu = tk.Frame(canvas, bg=THEME_BG)
        canvas_window = canvas.create_window((0, 0), window=self.main_menu, anchor='nw')

        def _configure_canvas(event):
            canvas.itemconfig(canvas_window, width=event.width)

        def _configure_frame(event):
            canvas.configure(scrollregion=canvas.bbox('all'))

        canvas.bind('<Configure>', _configure_canvas)
        self.main_menu.bind('<Configure>', _configure_frame)

        # Universal mouse wheel scrolling for the content canvas and any nested scrollable widgets
        def _on_mousewheel(event):
            delta = event.delta
            if delta == 0:
                return 'break'
            if abs(delta) >= 120:
                steps = int(-delta / 120)
            else:
                steps = -1 if delta > 0 else 1
            canvas.yview_scroll(steps, 'units')
            return 'break'

        def _on_mousewheel_linux(event, direction):
            canvas.yview_scroll(direction, 'units')
            return 'break'

        canvas.bind_all('<MouseWheel>', _on_mousewheel)
        canvas.bind_all('<Button-4>', lambda e: _on_mousewheel_linux(e, -1))
        canvas.bind_all('<Button-5>', lambda e: _on_mousewheel_linux(e, 1))

        # Store helper so tab-specific scrollable widgets can reuse the same scrolling logic
        self._shell_canvas = canvas

    def _style_chart(self, fig, ax):
        """Paint a matplotlib chart in the Ledger palette."""
        fig.patch.set_facecolor(THEME_BG)
        ax.set_facecolor(THEME_BG)
        ax.tick_params(colors=THEME_TEXT_MUTED, labelsize=9, length=0)
        ax.xaxis.label.set_color(THEME_TEXT)
        ax.yaxis.label.set_color(THEME_TEXT)
        ax.title.set_color(THEME_TEXT)
        # Rules, not boxes: keep the baseline and left scale, drop the frame.
        for name, spine in ax.spines.items():
            spine.set_color(THEME_BORDER)
            spine.set_visible(name in ('left', 'bottom'))
        ax.grid(True, axis='y', color=THEME_BORDER, linewidth=0.6, alpha=0.9)
        ax.set_axisbelow(True)

    def _bind_treeview_mousewheel(self, tree):
        """Make a Treeview scroll with the mouse wheel on macOS and Linux."""

        def _tree_wheel(event):
            delta = event.delta
            if delta == 0:
                return 'break'
            if abs(delta) >= 120:
                steps = int(-delta / 120)
            else:
                steps = -1 if delta > 0 else 1
            tree.yview_scroll(steps, 'units')
            return 'break'

        tree.bind('<MouseWheel>', _tree_wheel)
        tree.bind('<Button-4>', lambda e: (tree.yview_scroll(-1, 'units'), 'break')[-1])
        tree.bind('<Button-5>', lambda e: (tree.yview_scroll(1, 'units'), 'break')[-1])

    def _nav_button(self, parent, text, command, active=False):
        """Create a Ledger rail item.

        The active item is ink and bold with a 2px bottle underline rather
        than a filled block.  Built on a Label for the flat look, but
        focusable and operable from the keyboard.
        """
        wrap = tk.Frame(parent, bg=THEME_SIDEBAR)
        wrap.pack(fill='x', padx=10, pady=1)

        btn = tk.Label(wrap, text=text,
                       font=(THEME_FONT, 11, 'bold' if active else 'normal'),
                       bg=THEME_SIDEBAR, fg=THEME_TEXT if active else THEME_TEXT_MUTED,
                       cursor='hand2', anchor='w', padx=8, pady=6,
                       takefocus=1, highlightthickness=1,
                       highlightbackground=THEME_SIDEBAR,
                       highlightcolor=THEME_ACCENT)
        btn.pack(fill='x')
        underline = tk.Frame(wrap, bg=THEME_ACCENT if active else THEME_SIDEBAR,
                             height=2)
        underline.pack(fill='x', pady=(2, 0))

        def activate(event=None):
            command()
            return 'break'

        def on_enter(event=None):
            if not active:
                btn.config(bg=TBL_ROW_ALT)

        def on_leave(event=None):
            if not active:
                btn.config(bg=THEME_SIDEBAR)

        btn.bind('<Button-1>', activate)
        btn.bind('<Return>', activate)
        btn.bind('<space>', activate)
        btn.bind('<Enter>', on_enter)
        btn.bind('<Leave>', on_leave)
        btn.bind('<FocusIn>', lambda e: btn.config(highlightbackground=THEME_ACCENT))
        btn.bind('<FocusOut>', lambda e: btn.config(highlightbackground=THEME_SIDEBAR))
        return btn

    def _set_status(self, message, kind='info', timeout=8000):
        """Show a short-lived message in the status bar instead of a modal dialog."""
        var = getattr(self, 'status_var', None)
        if var is None:
            return
        colour = self._status_colour(kind)
        # Remember it: most save flows navigate to another screen, which rebuilds
        # the shell (and the status bar) immediately afterwards.
        self._status_message = message
        self._status_kind = kind
        try:
            var.set(message)
            if hasattr(self, 'status_label'):
                self.status_label.config(fg=colour)
        except tk.TclError:
            return

        def clear():
            self._clear_status_if(message)

        if timeout:
            self.root.after(timeout, clear)

    def _clear_status_if(self, message):
        """Clear the status bar, but only if it still shows ``message``."""
        if getattr(self, '_status_message', None) != message:
            return
        self._status_message = ''
        var = getattr(self, 'status_var', None)
        if var is None:
            return
        try:
            var.set("")
        except tk.TclError:
            pass

    def _status_colour(self, kind):
        return {
            'success': THEME_SUCCESS,
            'warning': THEME_WARNING,
            'danger': THEME_DANGER,
        }.get(kind, THEME_TEXT_MUTED)

    def _run_in_background(self, message, work, on_success=None, on_error=None,
                           title="Working…"):
        """Run ``work`` on a worker thread with a small progress dialog.

        Tk widgets must only be touched from the main thread, so ``work`` is
        expected to be a pure function (file reading, parsing, PDF extraction).
        ``on_success``/``on_error`` run back on the main thread.  The dialog
        cannot be closed and grabs input while the work runs, so the same
        action cannot be started twice.
        """
        import queue
        import threading

        overlay = tk.Toplevel(self.root)
        overlay.title(title)
        overlay._keep_open = True  # Escape must not close work in progress
        overlay.transient(self.root)
        overlay.resizable(False, False)
        overlay.configure(bg=THEME_CARD)
        overlay.protocol('WM_DELETE_WINDOW', lambda: None)
        tk.Label(overlay, text=message, font=(THEME_FONT, 11),
                 fg=THEME_TEXT, bg=THEME_CARD, wraplength=320,
                 justify='left').pack(padx=24, pady=(20, 10))
        bar = ttk.Progressbar(overlay, mode='indeterminate', length=280)
        bar.pack(padx=24, pady=(0, 20))
        bar.start(12)

        try:
            overlay.update_idletasks()
            x = self.root.winfo_rootx() + (self.root.winfo_width() - overlay.winfo_width()) // 2
            y = self.root.winfo_rooty() + (self.root.winfo_height() - overlay.winfo_height()) // 3
            overlay.geometry(f"+{max(x, 0)}+{max(y, 0)}")
            overlay.grab_set()
        except tk.TclError:
            pass

        results = queue.Queue()

        def worker():
            try:
                results.put((True, work()))
            except Exception as exc:  # surfaced on the main thread below
                results.put((False, exc))

        def poll():
            try:
                ok, payload = results.get_nowait()
            except queue.Empty:
                self.root.after(75, poll)
                return
            try:
                bar.stop()
                overlay.grab_release()
            except tk.TclError:
                pass
            overlay.destroy()
            if ok:
                try:
                    if on_success is not None:
                        on_success(payload)
                except Exception as exc:  # the continuation runs on the UI thread
                    if on_error is not None:
                        on_error(exc)
                    else:
                        messagebox.showerror(title, f"{message}\n\n{exc}")
            elif on_error is not None:
                on_error(payload)
            else:
                messagebox.showerror(title, f"{message}\n\n{payload}")

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(75, poll)

    def _install_shortcuts(self):
        """Install global keyboard shortcuts.

        Modifier is Command on macOS and Control elsewhere.  Number keys map
        to the sidebar sections in order; F focuses the stock search when the
        Manage Stock screen is open, N starts a delivery, and Escape closes
        the top-most dialog (dialogs can veto by returning "break").
        """
        actions = {
            '1': self.show_dashboard,
            '2': self.show_deliveries,
            '3': self.show_stocktake,
            '4': self.show_sales_upload,
            '5': self.show_reports,
            '6': self.show_transactions,
            '7': self.show_delivery_history,
            '8': self.show_open_tabs,
            '9': self.show_more,
        }
        for key, command in actions.items():
            for mod in ('Command', 'Control'):
                self.root.bind_all(
                    f'<{mod}-Key-{key}>',
                    lambda event, c=command: (c(), 'break')[1],
                )
        for mod in ('Command', 'Control'):
            self.root.bind_all(f'<{mod}-Key-f>', self._focus_search)
            self.root.bind_all(
                f'<{mod}-Key-n>',
                lambda event: (self.show_deliveries(), 'break')[1],
            )
        self.root.bind_all('<Escape>', self._close_top_dialog)

    def _focus_search(self, event=None):
        """Focus the stock search box, or open Manage Stock if it is closed."""
        entry = getattr(self, 'search_entry', None)
        try:
            visible = entry is not None and entry.winfo_exists() and entry.winfo_viewable()
        except tk.TclError:
            visible = False
        if visible:
            entry.focus_set()
            entry.select_range(0, tk.END)
        else:
            self.manage_initial_stock()
        return 'break'

    def _close_top_dialog(self, event=None):
        """Escape closes the active dialog, never the main window."""
        widget = getattr(event, 'widget', None)
        if widget is None:
            try:
                widget = self.root.focus_get()
            except Exception:
                widget = self.root
        try:
            top = widget.winfo_toplevel()
        except Exception:
            return None
        if top is self.root or getattr(top, '_keep_open', False):
            return None
        top.destroy()
        return 'break'

    @staticmethod
    def _fit_dialog(top, min_width=0, min_height=0):
        """Let a dialog resize and grow it to fit its content.

        Dialogs were given a fixed pixel size and no minimum, so a larger
        system font (or accessibility text size) clipped labels with no way
        to recover.  This expands to the requested size once the widget tree
        is laid out and refuses to shrink below the design size.
        """
        top.resizable(True, True)

        def fit():
            if not top.winfo_exists():
                return
            top.update_idletasks()
            width = max(min_width, top.winfo_reqwidth())
            height = max(min_height, top.winfo_reqheight())
            if top.winfo_width() < width or top.winfo_height() < height:
                top.geometry(f"{width}x{height}")
            top.minsize(min(width, 320), min(height, 240))

        top.after_idle(fit)

    def _section_title(self, parent, text):
        """Create a muted uppercase section title."""
        return tk.Label(parent, text=text.upper(), font=ui_theme.mono_font(9),
                        fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w')

    def _pill(self, parent, text, variant='ok'):
        """Create an outlined status tag (no filled pill)."""
        fg = {
            'ok': THEME_SUCCESS,
            'warn': THEME_WARNING,
            'danger': THEME_DANGER,
        }.get(variant, THEME_SUCCESS)
        return tk.Label(parent, text=text.upper(), font=ui_theme.mono_font(8),
                        fg=fg, bg=THEME_BG, padx=7, pady=2,
                        bd=1, relief='solid')

    def _card(self, parent, title=None):
        """Create a ruled paper block with a mono section label."""
        card = tk.Frame(parent, bg=THEME_CARD, bd=0,
                        highlightbackground=THEME_BORDER, highlightthickness=1)
        if title:
            tk.Label(card, text=title.upper(), font=ui_theme.mono_font(9),
                     fg=THEME_TEXT_MUTED, bg=THEME_CARD, anchor='w').pack(
                fill='x', padx=14, pady=(12, 6))
        return card

    def _form_row(self, parent):
        """Create a two-column form row frame."""
        row = tk.Frame(parent, bg=THEME_CARD)
        row.pack(fill='x', padx=14, pady=6)
        row.grid_columnconfigure(0, weight=1)
        row.grid_columnconfigure(1, weight=1)
        return row

    def _data_table(self, parent, columns, rows, row_height=28):
        """Create a simple themed data table using a Treeview."""
        tree = ttk.Treeview(parent, columns=columns, show='headings', height=min(max(4, len(rows)), 12))
        tree.tag_configure('danger', foreground=THEME_DANGER)
        tree.tag_configure('warning', foreground=THEME_WARNING)
        tree.tag_configure('success', foreground=THEME_SUCCESS)

        for col in columns:
            tree.heading(col, text=col)
            tree.column(col, anchor='w', width=120)
        self._make_sortable(tree)

        for row_data in rows:
            tags = row_data.get('tags', ())
            values = row_data['values']
            tree.insert('', 'end', values=values, tags=tags)

        self._bind_treeview_mousewheel(tree)
        return tree

    def _apply_legacy_theme(self, parent=None):
        """Normalise leftover legacy colours to the Ledger palette.

        This is a light-theme normaliser, not a restyler: it maps old white,
        grey and dark-mode literals but leaves widgets already painted with
        Ledger tokens alone.  Buttons built before the shared helper are given
        the ruled paper treatment rather than being forced to accent green.
        """
        if parent is None:
            if not hasattr(self, 'main_menu') or not self.main_menu.winfo_exists():
                return
            parent = self.main_menu

        BG_MAP = {
            '#ffffff': THEME_CARD, 'white': THEME_CARD,
            '#fcfbf6': THEME_CARD,
            '#f0f0f0': THEME_SIDEBAR, '#ececec': THEME_SIDEBAR,
            '#e0e0e0': THEME_SIDEBAR, '#f5f5f5': THEME_SIDEBAR,
            '#d0d0d0': THEME_BORDER,
            '#333333': THEME_BG, '#2c2c2c': THEME_BG,
            '#1e1e1e': THEME_BG, '#262626': THEME_BG,
            '#0f1419': THEME_BG, '#1a2028': THEME_SIDEBAR,
            '#232b36': THEME_CARD, '#2f3844': THEME_BORDER,
            'systemwindowbackgroundcolor': THEME_BG,
            'systemdialogbackgroundcolor': THEME_BG,
            'systembuttonface': THEME_CARD,
            '': THEME_BG,
        }
        FG_MAP = {
            'black': THEME_TEXT, '#000000': THEME_TEXT,
            'white': THEME_TEXT, '#ffffff': THEME_TEXT,
            'systemtextcolor': THEME_TEXT,
            'gray': THEME_TEXT_MUTED, 'grey': THEME_TEXT_MUTED,
            '#808080': THEME_TEXT_MUTED,
            '#aab4bf': THEME_TEXT_MUTED,
            '#f5f2ec': THEME_TEXT,
            '#c89f5e': THEME_TEXT, '#e8b86d': THEME_TEXT,
            'red': THEME_DANGER, '#ff0000': THEME_DANGER,
            '#ff4444': THEME_DANGER,
            'green': THEME_SUCCESS, '#00ff00': THEME_SUCCESS,
            '#44cc44': THEME_SUCCESS,
            '#cc6600': THEME_WARNING,
        }

        def _map_bg(widget):
            try:
                bg = str(widget.cget('bg')).lower()
            except Exception:
                return
            if bg in BG_MAP:
                try:
                    widget.configure(bg=BG_MAP[bg])
                except Exception:
                    pass

        def _map_fg(widget):
            try:
                fg = str(widget.cget('fg')).lower()
            except Exception:
                return
            if fg in FG_MAP:
                try:
                    widget.configure(fg=FG_MAP[fg])
                except Exception:
                    pass

        def _theme_widget(w, depth=0):
            if depth > 30:
                return
            try:
                wtype = w.winfo_class()
                if wtype in ('Frame', 'Toplevel', 'Canvas', 'Listbox'):
                    _map_bg(w)
                elif wtype == 'LabelFrame':
                    _map_bg(w)
                    _map_fg(w)
                elif wtype == 'Label':
                    _map_bg(w)
                    _map_fg(w)
                elif wtype == 'Button':
                    bg = str(w.cget('bg')).lower()
                    if bg in BG_MAP:
                        w.configure(
                            bg=THEME_CARD, fg=THEME_TEXT,
                            activebackground=TBL_ROW_ALT,
                            activeforeground=THEME_TEXT,
                            relief='solid', bd=1,
                            highlightthickness=1,
                            highlightbackground=THEME_BORDER,
                        )
                elif wtype == 'Entry':
                    bg = str(w.cget('bg')).lower()
                    if bg in BG_MAP:
                        w.configure(bg=THEME_CARD)
                    w.configure(fg=THEME_TEXT, insertbackground=THEME_TEXT,
                                highlightbackground=THEME_BORDER,
                                highlightcolor=THEME_ACCENT)
                elif wtype == 'Text':
                    bg = str(w.cget('bg')).lower()
                    if bg in BG_MAP:
                        w.configure(bg=THEME_CARD)
                    w.configure(fg=THEME_TEXT, insertbackground=THEME_TEXT)
                elif wtype in ('Checkbutton', 'Radiobutton'):
                    _map_bg(w)
                    _map_fg(w)
                    try:
                        w.configure(activebackground=THEME_BG,
                                    selectcolor=THEME_CARD,
                                    highlightbackground=THEME_BORDER,
                                    highlightcolor=THEME_ACCENT)
                    except Exception:
                        pass
            except Exception:
                pass

            try:
                for child in w.winfo_children():
                    _theme_widget(child, depth + 1)
            except Exception:
                pass

        _theme_widget(parent)





    def show_reports(self):
        """Show the Reports hub."""
        self._create_app_shell('Reports')
        self._render_reports_hub()




    def show_more(self):
        """Show secondary actions that don't fit the primary tabs."""
        self._create_app_shell('More Actions')
        self._render_more_menu()

    def _render_more_menu(self):
        """Render secondary actions as the same ruled list used by Reports."""
        groups = [
            ("Stock", [
                ("Manage Stock", "Add, edit, retire and restore products.",
                 self.manage_initial_stock),
                ("Add Wastage", "Record broken, out-of-date or overpoured stock.",
                 self.add_wastage),
                ("Add Complimentary", "Record drinks given away, with a reason.",
                 self.add_complimentary),
                ("Supplier Return", "Send damaged or credited stock back.",
                 self.add_supplier_return),
                ("Line Clean", "Record line-cleaning usage against a product.",
                 self.line_clean),
            ]),
            ("Records", [
                ("Transactions", "Every movement, newest first.",
                 self.show_transactions),
                ("Delivery History", "Deliveries and supplier returns by date.",
                 self.show_delivery_history),
                ("Open Tabs", "Tabs still running at the bar.",
                 self.show_open_tabs),
            ]),
            ("System", [
                ("Suppliers", "Add, rename or remove suppliers.",
                 self.open_supplier_manager),
                ("Password Protection", "Require a password at startup.",
                 self.open_password_settings),
                ("Settings", "Member discount and system preferences.",
                 self.open_settings),
                ("Restore Backup", "Roll the database back to an earlier copy.",
                 self.restore_from_backup_menu),
                ("Refresh CSV Mirrors", "Rewrite stock.csv and the transaction log.",
                 self.refresh_csv_mirrors),
                ("Init from Items.csv", "Import the item list on a fresh system.",
                 self.initialize_stock_from_items_csv),
                ("Reset System", "Clear all data and start again.",
                 self.reset_system),
                ("Exit System", "Close BarStock safely.",
                 self.on_exit),
            ]),
        ]

        for heading, items in groups:
            head = self.themed_frame(self.main_menu)
            head.pack(fill='x', pady=(16, 2))
            self.themed_label(head, heading.upper(),
                              font=ui_theme.mono_font(9),
                              fg=THEME_TEXT_MUTED, anchor='w').pack(side='left')
            self.themed_label(head, f"{len(items)} actions",
                              font=ui_theme.mono_font(8), fg=THEME_TEXT_MUTED,
                              anchor='e').pack(side='right')
            tk.Frame(self.main_menu, bg=THEME_TEXT, height=1).pack(fill='x')

            for index, (title, description, command) in enumerate(items):
                row = self.report_row(self.main_menu, title, description, command)
                row.pack(fill='x')
                if index < len(items) - 1:
                    tk.Frame(self.main_menu, bg=THEME_BORDER,
                             height=1).pack(fill='x')

        hint = self.themed_label(
            self.main_menu,
            "Shortcuts:  ⌘/Ctrl + 1–9 navigate  ·  ⌘/Ctrl + N new delivery  ·  "
            "⌘/Ctrl + F find stock  ·  Esc closes a dialog",
            font=ui_theme.mono_font(8), fg=THEME_TEXT_MUTED, justify='left')
        hint.pack(fill='x', pady=(22, 0))

    def _render_reports_hub(self):
        """Render the single reports hub, listing every report the app offers."""
        intro = self.themed_label(
            self.main_menu,
            "Reports open in this window. PDF reports are saved to your "
            "Downloads folder.",
            font=(THEME_FONT, 10), fg=THEME_TEXT_MUTED,
            justify='left', anchor='w')
        intro.pack(fill='x', pady=(0, 4))

        groups = [
            ("Summary", [
                ("Comprehensive PDF Report",
                 "Stock, sales, wastage, draught yield and variance in one PDF.",
                 self.download_comprehensive_report, "PDF"),
                ("Gross Profit Report",
                 "Margin by product, with member and non-member splits.",
                 self.generate_gp_report, None),
                ("Division Report",
                 "Sales and gross profit by bar division.",
                 self.generate_division_report, None),
                ("Period Comparison Report",
                 "Two date ranges side by side.",
                 self.generate_comparison_report, None),
            ]),
            ("Stock & orders", [
                ("Reorder Suggestions",
                 "Items below reorder level, with suggested quantities.",
                 self.generate_reorder_report, None),
                ("Stock Order Sheet",
                 "Printable order sheet grouped by supplier.",
                 self.generate_stock_order_sheet, "PDF"),
                ("Surplus & Variance Report",
                 "Running surplus or shortfall by product.",
                 self.generate_surplus_report, None),
                ("Reconciliation Report",
                 "Stock, conversion and Items.csv checks in one place.",
                 self.generate_reconciliation_report, None),
            ]),
            ("Sales & margin", [
                ("Sales Trends & Analytics",
                 "Category sales, fast and slow movers, timeline and margins.",
                 self.generate_sales_analytics, None),
                ("Draught Yield Report",
                 "Pints poured against kegs opened, by product.",
                 self.generate_draught_yield_report, None),
                ("Price History Report",
                 "Delivery cost changes over time, by product.",
                 self.generate_price_history_report, None),
            ]),
            ("Audit", [
                ("Stocktake Variance Report",
                 "Counted against expected stock, for each stocktake.",
                 self.generate_stocktake_report, None),
                ("Transaction Log",
                 "Every stock movement, filterable by date and type.",
                 self.show_transactions, None),
                ("Delivery History",
                 "Deliveries and supplier returns by date.",
                 self.show_delivery_history, None),
            ]),
        ]

        for heading, items in groups:
            if not club_profile.feature_enabled('stock_order_sheet'):
                items = [item for item in items
                         if item[0] != 'Stock Order Sheet']
            head = self.themed_frame(self.main_menu)
            head.pack(fill='x', pady=(16, 2))
            self.themed_label(head, heading.upper(),
                              font=ui_theme.mono_font(9),
                              fg=THEME_TEXT_MUTED, anchor='w').pack(side='left')
            self.themed_label(head, f"{len(items)} reports",
                              font=ui_theme.mono_font(8), fg=THEME_TEXT_MUTED,
                              anchor='e').pack(side='right')
            tk.Frame(self.main_menu, bg=THEME_TEXT, height=1).pack(fill='x')

            for index, (title, description, command, badge) in enumerate(items):
                row = self.report_row(self.main_menu, title, description,
                                      command, badge)
                row.pack(fill='x')
                if index < len(items) - 1:
                    tk.Frame(self.main_menu, bg=THEME_BORDER,
                             height=1).pack(fill='x')



















    def clear_main_menu(self):
        """Remove all widgets from the main menu."""
        for widget in self.main_menu.winfo_children():
            widget.destroy()

    def _set_page_heading(self, title, subtitle=None):
        """Retitle the topbar without rebuilding the shell.

        Report screens open inside the Reports shell, so the page heading is
        the report's name rather than a second, centred title in the content.
        """
        title_label = getattr(self, '_topbar_title', None)
        if title_label is None:
            return
        try:
            title_label.config(text=title)
            if subtitle is not None:
                self._topbar_subtitle.config(text=subtitle)
        except tk.TclError:
            pass

    def refresh_data(self):
        """Reload data from SQLite and reset the save baselines."""
        self.inventory_df = InventoryDataManager.load_inventory()
        self.log_df = InventoryDataManager.load_log()
        self._inventory_snapshot = self.inventory_df.copy()
        self._log_snapshot_ids = self._current_log_ids()

    def _current_log_ids(self):
        """Return the transaction row ids currently loaded in this window."""
        if self.log_df is None or self.log_df.empty or COL_ID not in self.log_df.columns:
            return set()
        return {int(value) for value in self.log_df[COL_ID].dropna()}

    def _persist(self):
        """Write inventory deltas and the log in one transaction, then reload.

        Returns True on success.  On success the in-memory frames are reloaded
        from SQLite so the next save's baseline is accurate.
        """
        ok = InventoryDataManager.save_all(
            self.inventory_df,
            self.log_df,
            baseline_df=self._inventory_snapshot,
            baseline_log_ids=self._log_snapshot_ids,
        )
        if ok:
            set_setting('last_saved_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            self.refresh_data()
        return ok

    def _save_inventory(self):
        """Write inventory-only deltas (item add/edit/delete), then reload."""
        ok = InventoryDataManager.save_inventory(
            self.inventory_df,
            baseline_df=self._inventory_snapshot,
        )
        if ok:
            set_setting('last_saved_at', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            self.refresh_data()
        return ok

    def format_currency(self, value):
        """Format value as currency, with thousands separators for reports."""
        return f"£{value:,.2f}"

    def get_filtered_log(self, title="Select Date Range"):
        """Show date range dialog and return filtered log DataFrame.

        Returns (log_df, start_date, end_date) or (None, None, None) if cancelled.
        """
        self.refresh_data()
        dialog = DateRangeDialog(self.root, title=title)
        if dialog.result is None:
            return None, None, None
        if dialog.result == 'ALL_TIME':
            return self.log_df.copy(), None, None
        start_date, end_date = dialog.result
        filtered = filter_log_by_date(self.log_df, start_date, end_date)
        return filtered, start_date, end_date



















































    def refresh_csv_mirrors(self):
        """Write the current inventory to stock.csv and Items.csv on demand."""
        if self.inventory_df.empty:
            messagebox.showinfo(
                "CSV Mirrors",
                "There are no stock items yet. Add or import items first.",
            )
            return
        if InventoryDataManager.export_csv_mirrors(self.inventory_df):
            messagebox.showinfo(
                "CSV Mirrors",
                "stock.csv and Items.csv have been refreshed from the live database.",
            )
        else:
            messagebox.showerror(
                "CSV Mirrors",
                f"Could not refresh the CSV mirrors.\n\nSee the log for details:\n{get_log_path()}",
            )

    def initialize_stock_from_items_csv(self):
        """Initialize stock inventory from Items.csv file."""
        try:
            # Open file dialog to select Items.csv
            filepath = filedialog.askopenfilename(
                title="Select Items.csv File",
                filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
                defaultextension=".csv"
            )

            if not filepath:
                return  # User cancelled

            # Read Items.csv
            items_df = pd.read_csv(filepath, compression=None)

            # Check required columns
            if 'Name' not in items_df.columns:
                messagebox.showerror("Invalid CSV", "Items.csv is missing the required 'Name' column.")
                return

            # Confirm before overwriting
            if not self.inventory_df.empty:
                if not messagebox.askyesno("Confirm Initialize",
                    "This will add items from Items.csv to your inventory.\n\n"
                    "Existing items with the same name will be updated.\n\n"
                    "Do you want to continue?"):
                    return

            # Process items
            items_added = 0
            items_updated = 0
            errors = []

            for _, row in items_df.iterrows():
                try:
                    item_name = str(row['Name']).strip()
                    division_value = row.get('Division', 'Uncategorized')
                    division_raw = (str(division_value).strip()
                                    if pd.notna(division_value) else 'Uncategorized')
                    total_stock = float(row['Total Stock']) if 'Total Stock' in row and pd.notna(row['Total Stock']) else 0
                    total_value = float(row['Total Value']) if 'Total Value' in row and pd.notna(row['Total Value']) else 0

                    # Skip empty items
                    if not item_name:
                        continue

                    # Create item_id using the same canonical normaliser as uploads.
                    item_id = normalize_product_name(item_name)

                    # Explicit Cost Price / Sell Price columns win; otherwise
                    # derive cost from Total Value / Total Stock and use a 30%
                    # markup as a starting sell price.
                    explicit_cost = (
                        float(row['Cost Price'])
                        if 'Cost Price' in row and pd.notna(row['Cost Price'])
                        else None)
                    explicit_sell = (
                        float(row['Sell Price'])
                        if 'Sell Price' in row and pd.notna(row['Sell Price'])
                        else None)
                    if explicit_cost is not None:
                        cost_price = explicit_cost
                    elif total_stock > 0 and total_value > 0:
                        cost_price = total_value / total_stock
                    else:
                        cost_price = 0
                    sell_price = (explicit_sell if explicit_sell is not None
                                  else cost_price * 1.3)

                    # Determine measure and category from Unit/Division.
                    unit_value = row.get('Unit', '')
                    unit = str(unit_value).lower() if pd.notna(unit_value) else ''
                    division = division_raw.lower()

                    # Determine measure
                    if 'pint' in unit or 'draught' in division:
                        measure = 'Pint'
                    elif '50ml' in unit or '25ml' in unit or 'spirit' in division:
                        measure = '35ml'
                    else:
                        measure = 'Bottle'

                    # Determine category
                    if 'draught' in division:
                        category = 'Draught'
                    elif 'spirit' in division or 'liqueurs' in division or 'whisky' in division or 'gin' in division:
                        category = 'Spirit'
                    elif 'mineral' in division or 'post mix' in division or 'soft' in division:
                        category = 'Soft'
                    else:
                        category = 'Bottle'

                    # Check if item exists
                    if item_id in self.inventory_df[COL_ITEM_ID].values:
                        # Check if price is locked for this item
                        is_locked = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_PRICE_LOCKED].values[0]
                        if pd.isna(is_locked):
                            is_locked = False

                        if is_locked:
                            # Only update non-price fields for locked items
                            self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id,
                                                 [COL_ITEM_NAME, COL_QUANTITY, COL_MEASURE, COL_CATEGORY, COL_DIVISION]] = \
                                [item_name, total_stock, measure, category, division_raw]
                        else:
                            # Update all fields for unlocked items
                            self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id,
                                                 [COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE, COL_MEASURE, COL_CATEGORY, COL_DIVISION]] = \
                                [item_name, total_stock, cost_price, sell_price, measure, category, division_raw]
                        items_updated += 1
                    else:
                        # Add new item with every inventory column populated.
                        # Leaving allow_negative/reorder_level out produced NaN,
                        # and bool(np.nan) is True, so imported items silently
                        # became allowed to go negative.
                        new_item = pd.DataFrame([[item_id, item_name, total_stock, cost_price, sell_price, measure, category, False, False, 0, division_raw]],
                                              columns=[COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE, COL_MEASURE, COL_CATEGORY, COL_PRICE_LOCKED, COL_ALLOW_NEGATIVE, COL_REORDER_LEVEL, COL_DIVISION])
                        self.inventory_df = pd.concat([self.inventory_df, new_item], ignore_index=True)
                        items_added += 1

                except Exception as item_error:
                    errors.append(f"Error processing '{row.get('Name', 'Unknown')}': {item_error}")

            # Save inventory
            if self._save_inventory():
                # Keep the selected file as the live Items.csv master in the
                # data folder (never in the read-only bundle).
                try:
                    import shutil
                    master = os.path.join(DATA_DIR, 'Items.csv')
                    temp_copy = master + '.tmp'
                    shutil.copy2(filepath, temp_copy)
                    if os.path.exists(master):
                        os.replace(master, master + '.bak')
                    os.replace(temp_copy, master)
                except Exception as csv_err:
                    logger.warning("Could not install Items.csv master: %s", csv_err)
                self.update_dashboard_stats()
                success_msg = f"Stock initialization complete!\n\n"
                success_msg += f"Items added: {items_added}\n"
                success_msg += f"Items updated: {items_updated}\n"
                if errors:
                    success_msg += f"Errors: {len(errors)}\n"
                    success_msg += "\nSome items had errors. Check details below."
                messagebox.showinfo("Success", success_msg)
            else:
                messagebox.showerror("Error", "Failed to save inventory.")

            self._apply_legacy_theme()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to initialize stock: {e}")

    def open_supplier_manager(self):
        """Add, rename and remove the suppliers offered by the app."""
        top = tk.Toplevel(self.root)
        top.title("Suppliers")
        top.geometry("560x560")
        self._fit_dialog(top, 560, 560)
        top.transient(self.root)
        top.grab_set()
        top.configure(bg=THEME_BG)

        frame = tk.Frame(top, padx=24, pady=20, bg=THEME_BG)
        frame.pack(fill='both', expand=True)
        tk.Label(frame, text="Suppliers", font=ui_theme.display_font(18),
                 fg=THEME_TEXT, bg=THEME_BG, anchor='w').pack(fill='x')
        tk.Label(frame,
                 text=("These names appear in Deliveries and Supplier Return. "
                       "You can still type a new supplier directly into the "
                       "delivery screen."),
                 font=(THEME_FONT, 9), fg=THEME_TEXT_MUTED, bg=THEME_BG,
                 anchor='w', justify='left', wraplength=500).pack(
                     fill='x', pady=(2, 12))

        raw = get_setting('suppliers')
        suppliers = []
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    suppliers = [str(v).strip() for v in parsed
                                 if str(v).strip()]
            except Exception:
                suppliers = []
        if not suppliers:
            suppliers = list(club_profile.suppliers())

        list_frame = tk.Frame(frame, bg=THEME_BG)
        list_frame.pack(fill='both', expand=True)
        listbox = tk.Listbox(
            list_frame, font=(THEME_FONT, 11), bg=THEME_CARD,
            fg=THEME_TEXT, selectbackground=THEME_ACCENT,
            selectforeground=THEME_TEXT, exportselection=False, bd=1,
            relief='solid', highlightthickness=0)
        listbox.pack(side='left', fill='both', expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient='vertical',
                                  command=listbox.yview)
        scrollbar.pack(side='right', fill='y')
        listbox.configure(yscrollcommand=scrollbar.set)

        def refresh():
            listbox.delete(0, tk.END)
            for value in suppliers:
                listbox.insert(tk.END, value)

        entry_var = tk.StringVar()
        entry_row = tk.Frame(frame, bg=THEME_BG)
        entry_row.pack(fill='x', pady=(10, 0))
        entry = ttk.Entry(entry_row, textvariable=entry_var,
                          font=(THEME_FONT, 11))
        entry.pack(side='left', fill='x', expand=True, ipady=3)

        def add_supplier():
            value = entry_var.get().strip()
            if not value:
                return
            if any(value.lower() == existing.lower() for existing in suppliers):
                messagebox.showinfo("Suppliers", "That supplier is already listed.")
                return
            suppliers.append(value)
            suppliers.sort(key=str.lower)
            entry_var.set('')
            refresh()

        def selected_index():
            selection = listbox.curselection()
            return selection[0] if selection else None

        def rename_supplier():
            index = selected_index()
            if index is None:
                messagebox.showinfo("Suppliers", "Select a supplier first.")
                return
            new_name = simpledialog.askstring(
                "Rename supplier", "New supplier name:",
                initialvalue=suppliers[index], parent=top)
            if not new_name or not new_name.strip():
                return
            new_name = new_name.strip()
            if any(new_name.lower() == existing.lower()
                   for position, existing in enumerate(suppliers)
                   if position != index):
                messagebox.showinfo("Suppliers", "That supplier is already listed.")
                return
            suppliers[index] = new_name
            suppliers.sort(key=str.lower)
            refresh()

        def remove_supplier():
            index = selected_index()
            if index is None:
                messagebox.showinfo("Suppliers", "Select a supplier first.")
                return
            if not messagebox.askyesno(
                    "Remove supplier",
                    f"Remove '{suppliers[index]}' from the supplier list?\n\n"
                    "Existing delivery records keep the name."):
                return
            del suppliers[index]
            refresh()

        buttons = tk.Frame(frame, bg=THEME_BG)
        buttons.pack(fill='x', pady=(8, 0))
        self.styled_button(buttons, "Add", add_supplier, width=10,
                           variant='primary').pack(side='left')
        self.styled_button(buttons, "Rename", rename_supplier, width=10,
                           variant='secondary').pack(side='left', padx=(6, 0))
        self.styled_button(buttons, "Remove", remove_supplier, width=10,
                           variant='secondary').pack(side='left', padx=(6, 0))

        def save_and_close():
            if set_setting('suppliers', json.dumps(suppliers)):
                club_profile.apply_settings_overrides(get_setting)
                self._set_status("Supplier list saved.", 'success')
                top.destroy()
            else:
                messagebox.showerror("Suppliers", "Could not save the supplier list.")

        footer = tk.Frame(frame, bg=THEME_BG)
        footer.pack(fill='x', pady=(14, 0))
        self.styled_button(footer, "Save", save_and_close, width=14,
                           variant='primary').pack(side='right')
        self.styled_button(footer, "Cancel", top.destroy, width=14,
                           variant='secondary').pack(side='right', padx=(0, 8))

        entry.bind('<Return>', lambda event: add_supplier())
        refresh()
        top.update_idletasks()
        self._apply_legacy_theme(top)

    def open_password_settings(self):
        """Enable, change or disable the startup password."""
        enabled = security.password_enabled()
        top = tk.Toplevel(self.root)
        top.title("Password Protection")
        top.geometry("520x440")
        self._fit_dialog(top, 520, 440)
        top.transient(self.root)
        top.grab_set()
        top.configure(bg=THEME_BG)

        frame = tk.Frame(top, padx=24, pady=20, bg=THEME_BG)
        frame.pack(fill='both', expand=True)
        tk.Label(frame, text="Password Protection",
                 font=ui_theme.display_font(18), fg=THEME_TEXT, bg=THEME_BG,
                 anchor='w').pack(fill='x')
        tk.Label(frame,
                 text=("Locks the app window at startup. This does not encrypt "
                       "the database or CSV files."),
                 font=(THEME_FONT, 9), fg=THEME_TEXT_MUTED, bg=THEME_BG,
                 anchor='w', justify='left', wraplength=460).pack(
                     fill='x', pady=(2, 12))

        status_var = tk.BooleanVar(value=enabled)
        tk.Checkbutton(
            frame, text="Enable password protection",
            variable=status_var, font=(THEME_FONT, 11), fg=THEME_TEXT,
            bg=THEME_BG, activebackground=THEME_BG,
            selectcolor=THEME_CARD).pack(anchor='w', pady=(0, 12))

        def field(label, show=None):
            row = tk.Frame(frame, bg=THEME_BG)
            row.pack(fill='x', pady=(0, 8))
            tk.Label(row, text=label, font=(THEME_FONT, 10, 'bold'),
                     fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w',
                     width=20).pack(side='left')
            var = tk.StringVar()
            ttk.Entry(row, textvariable=var, show=show or '',
                      font=(THEME_FONT, 11)).pack(
                          side='left', fill='x', expand=True, ipady=3)
            return var

        current_var = field("Current password", '*') if enabled else None
        new_var = field("New password", '*')
        confirm_var = field("Confirm new password", '*')

        tk.Label(frame,
                 text=("If the password is lost, the app can only be opened by "
                       "removing the app_password setting from the database."),
                 font=(THEME_FONT, 8), fg=THEME_TEXT_MUTED, bg=THEME_BG,
                 anchor='w', justify='left', wraplength=460).pack(
                     fill='x', pady=(4, 0))

        def save():
            want = bool(status_var.get())
            current = current_var.get() if current_var is not None else ''
            new_password = new_var.get()
            confirm = confirm_var.get()

            if enabled and not security.verify_password(current):
                messagebox.showerror("Password", "Current password is incorrect.")
                return

            if not want:
                if enabled and not security.disable_password(current):
                    messagebox.showerror("Password", "Could not disable the password.")
                    return
                self._set_status("Password protection disabled.", 'success')
                top.destroy()
                return

            if not new_password:
                if enabled:
                    top.destroy()  # keep the existing password unchanged
                else:
                    messagebox.showerror("Password", "Enter a new password.")
                return
            if new_password != confirm:
                messagebox.showerror("Password", "The new passwords do not match.")
                return
            if new_password.strip() == '':
                messagebox.showerror("Password", "Password cannot be blank.")
                return
            if security.set_password(new_password, True):
                self._set_status("Password protection enabled.", 'success')
                top.destroy()
            else:
                messagebox.showerror("Password", "Could not save the password.")

        footer = tk.Frame(frame, bg=THEME_BG)
        footer.pack(fill='x', pady=(18, 0))
        self.styled_button(footer, "Save", save, width=14,
                           variant='primary').pack(side='right')
        self.styled_button(footer, "Cancel", top.destroy, width=14,
                           variant='secondary').pack(side='right', padx=(0, 8))

        top.update_idletasks()
        self._apply_legacy_theme(top)

    def open_settings(self):
        """Open the settings dialog."""
        top = tk.Toplevel(self.root)
        top.title("Settings")
        top.geometry("480x320")
        self._fit_dialog(top, 480, 320)
        top.transient(self.root)
        top.grab_set()

        top.lift()
        top.attributes('-topmost', True)
        top.after_idle(top.attributes, '-topmost', False)

        top.update_idletasks()
        x = (top.winfo_screenwidth() - top.winfo_width()) // 2
        y = (top.winfo_screenheight() - top.winfo_height()) // 2
        top.geometry(f'+{x}+{y}')

        top.configure(bg=THEME_BG)
        main_frame = tk.Frame(top, padx=24, pady=20, bg=THEME_BG)
        main_frame.pack(fill='both', expand=True)

        tk.Label(main_frame, text="Settings", font=ui_theme.display_font(18),
                 fg=THEME_TEXT, bg=THEME_BG, anchor='w').pack(fill='x')
        tk.Label(main_frame, text="Member discount and system preferences.",
                 font=(THEME_FONT, 9), fg=THEME_TEXT_MUTED, bg=THEME_BG,
                 anchor='w').pack(fill='x', pady=(2, 16))
        tk.Frame(main_frame, bg=THEME_BORDER, height=1).pack(fill='x')

        # Member discount
        discount_frame = tk.Frame(main_frame, bg=THEME_BG)
        discount_frame.pack(fill='x', pady=(16, 4))
        tk.Label(discount_frame, text="Member discount %",
                 font=(THEME_FONT, 10, 'bold'), fg=THEME_TEXT_MUTED,
                 bg=THEME_BG).pack(anchor='w')
        entry_row = tk.Frame(main_frame, bg=THEME_BG)
        entry_row.pack(fill='x')
        discount_var = tk.StringVar(value=str(int(self.get_member_discount_pct())))
        discount_entry = ttk.Entry(entry_row, textvariable=discount_var,
                                   width=10, font=(THEME_FONT, 12))
        discount_entry.pack(side='left', ipady=3)
        tk.Label(entry_row, text="e.g. 10 for 10% off", font=(THEME_FONT, 9),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG).pack(side='left', padx=(10, 0))

        def save_settings():
            try:
                discount = float(discount_var.get())
                if discount < 0 or discount > 100:
                    messagebox.showerror("Error", "Discount must be between 0 and 100.")
                    return
                if set_setting('member_discount_pct', str(int(discount))):
                    self._set_status("Settings saved successfully.", 'success')
                    top.destroy()
                else:
                    messagebox.showerror("Error", "Failed to save settings.")
            except ValueError:
                messagebox.showerror("Error", "Discount must be a valid number.")

        btn_frame = tk.Frame(main_frame, bg=THEME_BG)
        btn_frame.pack(fill='x', pady=(24, 0))
        self.styled_button(btn_frame, "Save", save_settings, width=15,
                           variant='primary').pack(side='right')
        self.styled_button(btn_frame, "Cancel", top.destroy, width=15,
                           variant='secondary').pack(side='right', padx=(0, 8))

        top.update_idletasks()
        self._apply_legacy_theme(top)

    def reset_system(self):
        """Reset all system data while preserving stock items.

        This clears the transaction log, stocktake snapshots, and archived transactions,
        but keeps the stock item definitions intact.
        """
        if not messagebox.askyesno("Confirm Reset",
            "This will reset all system data:\n\n"
            "• All transaction history will be deleted\n"
            "• All stocktake snapshots will be deleted\n"
            "• All archived transactions will be deleted\n"
            "• Stock items and their definitions will be preserved\n\n"
            "Are you sure you want to reset the system?"):
            return

        try:
            # A second, typed confirmation: this wipes all history and cannot
            # be undone from inside the app (only from a database backup).
            typed = simpledialog.askstring(
                "Final Confirmation",
                "This action cannot be undone.\n\n"
                "All transaction data, stocktake snapshots and archived transactions "
                "will be permanently deleted.\n\n"
                "Type RESET to confirm:",
                parent=self.root)
            if typed is None:
                return
            if typed.strip() != 'RESET':
                messagebox.showinfo("Not Reset", "The confirmation text did not match, so nothing was reset.")
                return

            # Clear the transaction log - keep only the column structure
            self.log_df = pd.DataFrame(columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY,
                                                COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON, COL_MEMBER_QTY, COL_NON_MEMBER_QTY])

            # Save the empty log and clear historical data
            log_saved = InventoryDataManager.save_log(self.log_df, allow_shrink=True)
            snapshots_cleared = clear_stocktake_snapshots()
            archive_cleared = clear_transaction_archive()

            if log_saved and snapshots_cleared and archive_cleared:
                messagebox.showinfo("Reset Complete",
                    "System has been reset successfully.\n\n"
                    "All transaction history, stocktake snapshots, and archived transactions have been cleared.\n"
                    "Stock items have been preserved.")
            else:
                messagebox.showerror("Error", "Failed to complete reset. Some historical data may remain.")

            self._apply_legacy_theme()

        except Exception as e:
            messagebox.showerror("Error", f"Failed to reset system: {e}")

    def restore_from_backup_menu(self):
        """Show dialog to restore from a previous backup."""
        try:
            from data_manager import list_backups, restore_backup
            backups = list_backups()
            if not backups:
                messagebox.showinfo("No Backups", "No backups found.")
                return

            dialog = tk.Toplevel(self.root)
            dialog.title("Restore from Backup")
            dialog.geometry("600x400")
            self._fit_dialog(dialog, 600, 400)
            dialog.configure(bg=THEME_BG)

            tk.Label(dialog, text="Restore from backup",
                     font=ui_theme.display_font(18), fg=THEME_TEXT,
                     bg=THEME_BG, anchor='w').pack(fill='x', padx=24,
                                                   pady=(20, 0))
            tk.Label(dialog,
                     text="Choose a copy to roll back to. The current database is kept first.",
                     font=(THEME_FONT, 9), fg=THEME_TEXT_MUTED, bg=THEME_BG,
                     anchor='w').pack(fill='x', padx=24, pady=(2, 14))
            tk.Frame(dialog, bg=THEME_BORDER, height=1).pack(fill='x', padx=24)

            tree = ttk.Treeview(dialog, columns=('timestamp', 'name', 'size'), show='headings', height=10)
            tree.heading('timestamp', text='Date/Time')
            tree.heading('name', text='Backup Name')
            tree.heading('size', text='Size (KB)')
            tree.column('timestamp', width=170, anchor='w')
            tree.column('name', width=300, anchor='w')
            tree.column('size', width=90, anchor='e')
            tree.pack(fill='both', expand=True, padx=24, pady=(12, 5))
            self._bind_treeview_mousewheel(tree)

            for b in backups:
                tree.insert('', tk.END, values=(b['timestamp'], b['name'], b['size_kb']))

            def do_restore():
                sel = tree.selection()
                if not sel:
                    messagebox.showerror("Error", "Please select a backup.")
                    return
                item = tree.item(sel[0], 'values')
                backup_name = item[1]
                from data_manager import get_backups_dir
                backup_path = os.path.join(get_backups_dir(), backup_name)

                if not messagebox.askyesno("Confirm Restore",
                    f"Restore from backup:\n{backup_name}\n\n"
                    "Current data will be backed up first. Continue?"):
                    return

                ok, detail = restore_backup(backup_path)
                if ok:
                    # Reload both frames and their snapshots, otherwise the next
                    # save would write the pre-restore state straight back.
                    self.refresh_data()
                    self.update_dashboard_stats()
                    messagebox.showinfo(
                        "Success",
                        "Database restored and verified.\n\n"
                        f"A copy of the previous database was kept at:\n{detail}",
                    )
                    dialog.destroy()
                else:
                    messagebox.showerror("Restore Failed", str(detail))

            btn_frame = tk.Frame(dialog, bg=THEME_BG)
            btn_frame.pack(fill='x', padx=24, pady=(8, 16))
            self.styled_button(btn_frame, "Restore selected", do_restore,
                               width=16, variant='primary').pack(side='right')
            self.styled_button(btn_frame, "Cancel", dialog.destroy,
                               width=15, variant='secondary').pack(
                side='right', padx=(0, 8))

            self._apply_legacy_theme(dialog)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to open restore dialog: {e}")














    CAN_AVERAGE_GROUP = [
        'coca cola can',
        'diet coke can',
        'irn bru',
        'irn bru sugar free',
        'coke zero',
        'fanta lemon',
        'sprite can',
        'old jamaica ginger beer',
    ]

    CARTON_JUICE_AVERAGE_GROUP = [
        'apple juice',
        'orange juice',
        'cranberry juice',
        'pineapple juice',
    ]









if __name__ == "__main__":
    root = tk.Tk()
    if INSTANCE_LOCK is None:
        root.withdraw()
        messagebox.showerror(
            "BarStock is already running",
            "Another copy of BarStock is already open.\n\n"
            "Close it before starting a second copy, so both cannot write "
            "to the same stock database.",
        )
        root.destroy()
        raise SystemExit(0)
    install_exception_hooks(root)
    if security.password_enabled():
        root.withdraw()
        if not security.prompt_for_password(root):
            root.destroy()
            raise SystemExit(0)
        root.deiconify()
    app = BarStockManagementSystem(root)
    root.mainloop()
