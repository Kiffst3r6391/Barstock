"""
Bar Stock Management System - Basic Version

Simple tkinter-based stock management for Prestonfield Golf Club.
"""

import tkinter as tk
from tkinter import messagebox, ttk, filedialog, simpledialog
import pandas as pd
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
from app_config import DATA_DIR, INVENTORY_FILE, LOG_FILE, get_resource_path, get_script_directory
from ui_theme import *  # noqa: F401,F403
from ui_theme import THEME_FONT, THEME_FONT_STACK
import ui_theme


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
        self.root.title(f"Prestonfield Golf Club - Bar Stock Management v{APP_VERSION}")
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
                    "Use Settings → Init from Items.csv to import an item list, "
                    "or add items individually.",
                ),
            )

    def setup_theme(self):
        """Configure the application-wide dark dashboard theme."""
        global THEME_FONT
        try:
            THEME_FONT = ui_theme.resolve_font(self.root)
            # Screen modules read the family from ui_theme at draw time.
            ui_theme.THEME_FONT = THEME_FONT
        except Exception:
            pass

        self.root.configure(bg=THEME_BG)
        # Theme standard Tk widgets at creation time as well as by recolouring
        # afterwards.  Without this every legacy dialog and option menu is
        # built light and only turns dark once _apply_legacy_theme walks it,
        # which shows as a white flash when the dialog opens.
        self.root.option_add('*Background', THEME_BG)
        self.root.option_add('*Foreground', THEME_TEXT)
        self.root.option_add('*selectBackground', THEME_ACCENT)
        self.root.option_add('*selectForeground', '#0f1419')
        self.root.option_add('*highlightBackground', THEME_BORDER)
        self.root.option_add('*highlightColor', THEME_ACCENT)
        self.root.option_add('*TCombobox*Listbox.background', THEME_CARD)
        self.root.option_add('*TCombobox*Listbox.foreground', THEME_TEXT)
        self.root.option_add('*TCombobox*Listbox.selectBackground', THEME_ACCENT)
        self.root.option_add('*TCombobox*Listbox.selectForeground', '#0f1419')
        self.root.option_add('*Menu.background', THEME_CARD)
        self.root.option_add('*Menu.foreground', THEME_TEXT)
        self.root.option_add('*Menu.activeBackground', THEME_ACCENT)
        self.root.option_add('*Menu.activeForeground', '#0f1419')

        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background=THEME_BG)
        style.configure('TLabel', background=THEME_BG, foreground=THEME_TEXT, font=(THEME_FONT, 12))
        style.configure('TButton', background=THEME_ACCENT, foreground='#ffffff', font=(THEME_FONT, 12))
        style.configure('Card.TFrame', background=THEME_CARD)
        style.configure('CardTitle.TLabel', background=THEME_CARD, foreground=THEME_TEXT_MUTED, font=(THEME_FONT, 10))
        style.configure('CardValue.TLabel', background=THEME_CARD, foreground=THEME_TEXT, font=(THEME_FONT, 22, 'bold'))
        style.configure('CardSub.TLabel', background=THEME_CARD, foreground=THEME_TEXT_MUTED, font=(THEME_FONT, 10))
        style.configure('Treeview', background=THEME_CARD, foreground=THEME_TEXT, fieldbackground=THEME_CARD, rowheight=26)
        style.configure('Treeview.Heading', background=THEME_SIDEBAR, foreground=THEME_TEXT, font=(THEME_FONT, 11, 'bold'))
        style.configure('TCombobox', background=THEME_CARD, foreground=THEME_TEXT, fieldbackground=THEME_CARD, arrowcolor=THEME_ACCENT)
        style.map('TCombobox', fieldbackground=[('readonly', THEME_CARD)],
                  foreground=[('readonly', THEME_TEXT)],
                  selectbackground=[('readonly', THEME_CARD)],
                  selectforeground=[('readonly', THEME_TEXT)])
        style.configure('TEntry', background=THEME_CARD, foreground=THEME_TEXT, fieldbackground=THEME_CARD)
        style.configure('TScrollbar', background=THEME_SIDEBAR, troughcolor=THEME_BG, bordercolor=THEME_BORDER)
        style.configure('Horizontal.TProgressbar', background=THEME_ACCENT,
                        troughcolor=THEME_SIDEBAR, bordercolor=THEME_BORDER,
                        lightcolor=THEME_ACCENT, darkcolor=THEME_ACCENT)

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

    def styled_button(self, parent, text, command, width=22, variant='primary', **kwargs):
        """Create a theme-styled button matching the concept palette."""
        if variant == 'primary':
            bg, fg, hover = THEME_ACCENT, '#0f1419', THEME_ACCENT_HOVER
        elif variant == 'danger':
            bg, fg, hover = THEME_DANGER, '#ffffff', '#dc2626'
        elif variant == 'ghost':
            bg, fg, hover = THEME_SIDEBAR, THEME_TEXT, THEME_BORDER
        else:
            bg, fg, hover = THEME_CARD, THEME_TEXT, THEME_BORDER

        btn = tk.Button(
            parent, text=text, command=command, width=width,
            bg=bg, fg=fg, activebackground=hover, activeforeground=fg,
            relief='flat', font=(THEME_FONT, 12), cursor='hand2',
            padx=10, pady=6, **kwargs
        )

        def on_enter(event):
            btn.config(bg=hover)

        def on_leave(event):
            btn.config(bg=bg)

        btn.bind('<Enter>', on_enter)
        btn.bind('<Leave>', on_leave)
        return btn

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
            tile.config(bg=THEME_BORDER, fg='#ffffff')

        def on_leave(event):
            tile.config(bg=THEME_CARD, fg=THEME_TEXT)

        def on_focus_in(event):
            tile.config(bg=THEME_BORDER, highlightbackground=THEME_ACCENT)

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

    def create_card(self, parent, title, value, subtext='', status='normal'):
        """Create a simplified dashboard summary card."""
        card = tk.Frame(parent, bg=THEME_CARD, bd=1, relief='solid',
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

        title_lbl = tk.Label(card, text=title.upper(), font=(THEME_FONT, 9, 'bold'),
                             fg=THEME_TEXT_MUTED, bg=THEME_CARD)
        title_lbl.pack(anchor='w', padx=14, pady=(12, 4))

        value_color = THEME_TEXT
        if status == 'danger':
            value_color = THEME_DANGER
        elif status == 'warning':
            value_color = THEME_WARNING
        value_lbl = tk.Label(card, text=value, font=(THEME_FONT, 24, 'bold'),
                             fg=value_color, bg=THEME_CARD)
        value_lbl.pack(anchor='w', padx=14)

        sub_lbl = None
        if subtext:
            sub_lbl = tk.Label(card, text=subtext, font=(THEME_FONT, 10),
                               fg=THEME_TEXT_MUTED if status == 'normal' else value_color,
                               bg=THEME_CARD)
            sub_lbl.pack(anchor='w', padx=14, pady=(4, 14))
        else:
            tk.Label(card, text='', bg=THEME_CARD).pack(pady=(0, 8))

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
        """Create a themed panel with a title."""
        panel = tk.Frame(parent, bg=THEME_PANEL, bd=1, relief='solid',
                         highlightbackground=THEME_BORDER, highlightthickness=1)
        panel.pack(fill='x', padx=8, pady=8)
        title_lbl = tk.Label(panel, text=title.upper(), font=(THEME_FONT, 11, 'bold'),
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

        # Parse current date from the variable
        current_text = date_var.get().strip()
        try:
            current_date = parse_display_date(current_text)
        except ValueError:
            current_date = datetime.now()

        year = current_date.year
        month = current_date.month
        day = current_date.day

        header_frame = tk.Frame(top)
        header_frame.pack(pady=5)

        month_var = tk.StringVar(value=calendar.month_name[month])
        year_var = tk.StringVar(value=str(year))

        def refresh_days():
            for widget in days_frame.winfo_children():
                widget.destroy()

            y = int(year_var.get())
            m = list(calendar.month_name).index(month_var.get())

            # Weekday headers
            for i, wd in enumerate(['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']):
                tk.Label(days_frame, text=wd, font=(THEME_FONT, 10, 'bold'), width=5).grid(row=0, column=i, padx=3, pady=3)

            cal = calendar.Calendar()
            month_days = cal.monthdayscalendar(y, m)

            for r, week in enumerate(month_days, start=1):
                for c, d in enumerate(week):
                    if d == 0:
                        tk.Label(days_frame, text="", width=5).grid(row=r, column=c)
                    else:
                        btn = tk.Button(days_frame, text=str(d), width=5, font=(THEME_FONT, 10), command=lambda d=d: select_date(y, m, d))
                        if d == day and y == year and m == month:
                            btn.config(bg='#4a90d9', fg='white', font=(THEME_FONT, 10, 'bold'))
                        btn.grid(row=r, column=c, padx=2, pady=2)

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

        tk.Button(header_frame, text="<", command=prev_month, width=3, font=(THEME_FONT, 12)).pack(side=tk.LEFT, padx=10)
        tk.Label(header_frame, textvariable=month_var, font=(THEME_FONT, 12, 'bold'), width=10).pack(side=tk.LEFT)
        tk.Label(header_frame, textvariable=year_var, font=(THEME_FONT, 12, 'bold'), width=6).pack(side=tk.LEFT)
        tk.Button(header_frame, text=">", command=next_month, width=3, font=(THEME_FONT, 12)).pack(side=tk.LEFT, padx=10)

        days_frame = tk.Frame(top)
        days_frame.pack(pady=5)

        refresh_days()

        def select_today():
            now = datetime.now()
            select_date(now.year, now.month, now.day)

        tk.Button(top, text="Today", command=select_today).pack(pady=5)

    def _create_app_shell(self, active_tab):
        """Build the sidebar navigation, status bar, and scrollable content area."""
        for widget in self.shell_container.winfo_children():
            widget.destroy()

        self.shell_container.configure(bg=THEME_BG)

        # Status bar: routine feedback lands here instead of in a modal dialog.
        self.status_var = tk.StringVar(value="")
        status_bar = tk.Frame(self.shell_container, bg=THEME_SIDEBAR, height=26)
        status_bar.pack(side='bottom', fill='x')
        status_bar.pack_propagate(False)
        self.status_label = tk.Label(status_bar, textvariable=self.status_var,
                                     font=(THEME_FONT, 9), fg=THEME_TEXT_MUTED,
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

        # Left sidebar
        sidebar = tk.Frame(body, bg=THEME_SIDEBAR, width=216)
        sidebar.grid(row=0, column=0, sticky='ns')
        sidebar.grid_propagate(False)

        brand = tk.Frame(sidebar, bg=THEME_SIDEBAR)
        brand.pack(fill='x', padx=18, pady=(20, 14))
        tk.Label(brand, text="PRESTONFIELD GC", font=(THEME_FONT, 12, 'bold'),
                 fg=THEME_ACCENT, bg=THEME_SIDEBAR, anchor='w').pack(fill='x')
        tk.Label(brand, text="Bar Stock Management", font=(THEME_FONT, 9),
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
            tk.Label(sidebar, text=heading, font=(THEME_FONT, 8, 'bold'),
                     fg=THEME_TEXT_MUTED, bg=THEME_SIDEBAR, anchor='w').pack(
                fill='x', padx=18, pady=(14, 4))
            for text, command in items:
                self._nav_button(sidebar, text, command, active=(text == active_tab))

        tk.Label(sidebar, text=f"v{APP_VERSION}", font=(THEME_FONT, 8),
                 fg=THEME_TEXT_MUTED, bg=THEME_SIDEBAR, anchor='w').pack(
            side='bottom', fill='x', padx=18, pady=12)

        # Main column: page header + scrollable content
        main = tk.Frame(body, bg=THEME_BG)
        main.grid(row=0, column=1, sticky='nsew')

        topbar = tk.Frame(main, bg=THEME_BG, height=56)
        topbar.pack(fill='x', padx=20, pady=(16, 0))
        topbar.pack_propagate(False)

        title_frame = tk.Frame(topbar, bg=THEME_BG)
        title_frame.pack(side='left', fill='y')
        tk.Label(title_frame, text=active_tab, font=(THEME_FONT, 18, 'bold'),
                 fg=THEME_TEXT, bg=THEME_BG).pack(anchor='w')
        tk.Label(title_frame, text="Bar Stock Management", font=(THEME_FONT, 10),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG).pack(anchor='w')

        self.styled_button(topbar, "+ Add Delivery", self.show_deliveries,
                           width=16, variant='primary').pack(side='right', pady=8)

        # Scrollable content area
        content_outer = tk.Frame(main, bg=THEME_BG)
        content_outer.pack(fill='both', expand=True, padx=20, pady=(16, 20))
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
        """Create a sidebar navigation button.

        Built on a Label for the flat look, but focusable and operable from the
        keyboard (Tab to it, Enter/Space to activate) unlike the old tab strip.
        """
        bg = THEME_ACCENT if active else THEME_SIDEBAR
        fg = '#0f1419' if active else THEME_TEXT
        hover = THEME_ACCENT if active else THEME_CARD

        btn = tk.Label(parent, text=text, font=(THEME_FONT, 11, 'bold' if active else 'normal'),
                       bg=bg, fg=fg, cursor='hand2', anchor='w', padx=14, pady=8,
                       takefocus=1, highlightthickness=1,
                       highlightbackground=THEME_SIDEBAR, highlightcolor=THEME_ACCENT)
        btn.pack(fill='x', padx=10, pady=1)

        def activate(event=None):
            command()
            return 'break'

        btn.bind('<Button-1>', activate)
        btn.bind('<Return>', activate)
        btn.bind('<space>', activate)
        btn.bind('<Enter>', lambda e: btn.config(bg=hover))
        btn.bind('<Leave>', lambda e: btn.config(bg=bg))
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
        return tk.Label(parent, text=text.upper(), font=(THEME_FONT, 9, 'bold'),
                        fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w')

    def _pill(self, parent, text, variant='ok'):
        """Create a status pill."""
        colors = {
            'ok': ('rgba(90,158,110,0.15)', THEME_SUCCESS),
            'warn': ('rgba(201,154,70,0.15)', THEME_WARNING),
            'danger': ('rgba(201,93,93,0.15)', THEME_DANGER),
        }
        bg, fg = colors.get(variant, colors['ok'])
        # Tkinter doesn't support rgba, so use a close solid colour
        if variant == 'ok':
            bg = '#1e3a28'
        elif variant == 'warn':
            bg = '#3d2e1f'
        else:
            bg = '#3d2020'
        pill = tk.Label(parent, text=text, font=(THEME_FONT, 8, 'bold'),
                        fg=fg, bg=bg, padx=8, pady=2)
        return pill

    def _card(self, parent, title=None):
        """Create a concept-style card frame."""
        card = tk.Frame(parent, bg=THEME_CARD, bd=1, relief='solid',
                        highlightbackground=THEME_BORDER, highlightthickness=1)
        if title:
            tk.Label(card, text=title, font=(THEME_FONT, 12, 'bold'),
                     fg=THEME_ACCENT, bg=THEME_CARD, anchor='w').pack(
                fill='x', padx=14, pady=(12, 8))
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
        """Recolour a legacy screen so it matches the dark copper/navy concept.

        Preserves status colours (red/green/amber) and converts the common
        light-grey/white legacy backgrounds to the dark theme palette.
        """
        if parent is None:
            if not hasattr(self, 'main_menu') or not self.main_menu.winfo_exists():
                return
            parent = self.main_menu

        DARK_BG_MAP = {
            '#ffffff': THEME_BG, 'white': THEME_BG,
            '#f0f0f0': THEME_CARD, '#e0e0e0': THEME_CARD,
            '#d0d0d0': THEME_PANEL,
            '#333333': THEME_PANEL, '#2c2c2c': THEME_PANEL,
            'systemwindowbackgroundcolor': THEME_BG,
            'systemWindowBackgroundColor': THEME_BG,
            '': THEME_BG,
        }
        FG_MAP = {
            'black': THEME_TEXT, '#000000': THEME_TEXT,
            'white': THEME_TEXT, '#ffffff': THEME_TEXT,
            'systemtextcolor': THEME_TEXT,
            'gray': THEME_TEXT_MUTED, 'grey': THEME_TEXT_MUTED, '#808080': THEME_TEXT_MUTED,
            'red': THEME_DANGER, '#ff0000': THEME_DANGER, '#ff4444': THEME_DANGER,
            'green': THEME_SUCCESS, '#00ff00': THEME_SUCCESS, '#44cc44': THEME_SUCCESS,
            '#cc6600': THEME_WARNING,
        }

        def _theme_widget(w, depth=0):
            if depth > 30:
                return
            try:
                wtype = w.winfo_class()
                if wtype == 'Frame':
                    bg = w.cget('bg')
                    if bg.lower() in DARK_BG_MAP:
                        w.configure(bg=DARK_BG_MAP[bg.lower()])
                    else:
                        # Fallback: any light-ish default becomes page bg
                        try:
                            w.configure(bg=THEME_BG)
                        except Exception:
                            pass
                elif wtype == 'LabelFrame':
                    bg = w.cget('bg')
                    if bg.lower() in DARK_BG_MAP:
                        w.configure(bg=DARK_BG_MAP[bg.lower()])
                    else:
                        try:
                            w.configure(bg=THEME_CARD)
                        except Exception:
                            pass
                    try:
                        w.configure(fg=THEME_ACCENT)
                    except Exception:
                        pass
                elif wtype == 'Label':
                    bg = w.cget('bg')
                    if bg.lower() in DARK_BG_MAP:
                        w.configure(bg=DARK_BG_MAP[bg.lower()])
                    elif bg.lower() in ('systemwindowbackgroundcolor', 'systemdialogbackgroundcolor'):
                        w.configure(bg=THEME_BG)
                    fg = w.cget('fg')
                    if fg.lower() in FG_MAP:
                        w.configure(fg=FG_MAP[fg.lower()])
                    elif fg.lower() in ('systemtextcolor', 'black'):
                        w.configure(fg=THEME_TEXT)
                elif wtype == 'Button':
                    w.configure(
                        bg=THEME_ACCENT, fg='#0f1419',
                        activebackground=THEME_ACCENT_HOVER, activeforeground='#0f1419',
                        relief='flat', font=(THEME_FONT, 11),
                        padx=10, pady=6,
                        highlightbackground=THEME_ACCENT, highlightcolor=THEME_ACCENT
                    )
                elif wtype == 'Entry':
                    w.configure(
                        bg=THEME_CARD, fg=THEME_TEXT,
                        insertbackground=THEME_TEXT, highlightbackground=THEME_BORDER
                    )
                elif wtype == 'Canvas':
                    bg = w.cget('bg')
                    if bg.lower() in DARK_BG_MAP:
                        w.configure(bg=DARK_BG_MAP[bg.lower()])
                    elif bg.lower() in ('systemwindowbackgroundcolor',):
                        w.configure(bg=THEME_BG)
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
        self._create_app_shell('More')
        self._render_more_menu()

    def _render_more_menu(self):
        """Render the grid of secondary actions."""
        header = self.themed_frame(self.main_menu)
        header.pack(fill='x', pady=(0, 20))
        self.themed_label(header, "More actions",
                          font=(THEME_FONT, 24, 'bold')).pack(side='left')

        actions = [
            ("Manage Stock", self.manage_initial_stock),
            ("Add Wastage", self.add_wastage),
            ("Add Complimentary", self.add_complimentary),
            ("Supplier Return", self.add_supplier_return),
            ("Open Tabs", self.show_open_tabs),
            ("Line Clean", self.line_clean),
            ("Transactions", self.show_transactions),
            ("Delivery History", self.show_delivery_history),
            ("Settings", self.open_settings),
            ("Restore Backup", self.restore_from_backup_menu),
            ("Refresh CSV Mirrors", self.refresh_csv_mirrors),
            ("Init from Items.csv", self.initialize_stock_from_items_csv),
            ("Reset System", self.reset_system),
            ("Exit System", self.on_exit),
        ]

        grid = self.themed_frame(self.main_menu)
        grid.pack(fill='x')
        for i in range(3):
            grid.grid_columnconfigure(i, weight=1)

        for i, (text, command) in enumerate(actions):
            tile = self.tile_button(grid, text, command)
            tile.grid(row=i // 3, column=i % 3, padx=8, pady=8, sticky='ew')

        hint = self.themed_label(
            self.main_menu,
            "Shortcuts:  ⌘/Ctrl + 1–9 navigate  ·  ⌘/Ctrl + N new delivery  ·  "
            "⌘/Ctrl + F find stock  ·  Esc closes a dialog",
            font=(THEME_FONT, 9), fg=THEME_TEXT_MUTED, justify='left')
        hint.pack(fill='x', pady=(18, 0))

    def _render_reports_hub(self):
        """Render the single reports hub, listing every report the app offers."""
        header = self.themed_frame(self.main_menu)
        header.pack(fill='x', pady=(0, 12))
        self.themed_label(header, "Reports",
                          font=(THEME_FONT, 24, 'bold')).pack(side='left')

        groups = [
            ("Summary", [
                ("📄 Download Comprehensive PDF Report", self.download_comprehensive_report),
                ("Gross Profit Report", self.generate_gp_report),
                ("Division Report", self.generate_division_report),
                ("Period Comparison Report", self.generate_comparison_report),
            ]),
            ("Stock & orders", [
                ("Reorder Suggestions", self.generate_reorder_report),
                ("Stock Order Sheet", self.generate_stock_order_sheet),
                ("Surplus/Variance Report", self.generate_surplus_report),
                ("Reconciliation Report", self.generate_reconciliation_report),
            ]),
            ("Sales & margin", [
                ("Sales Trends & Analytics", self.generate_sales_analytics),
                ("Draught Yield Report", self.generate_draught_yield_report),
                ("Price History Report", self.generate_price_history_report),
            ]),
            ("Audit", [
                ("Stocktake Variance Report", self.generate_stocktake_report),
                ("Transaction Log", self.show_transactions),
                ("Delivery History", self.show_delivery_history),
            ]),
        ]

        for heading, items in groups:
            self._section_title(self.main_menu, heading).pack(fill='x', pady=(14, 6))
            grid = self.themed_frame(self.main_menu)
            grid.pack(fill='x')
            grid.grid_columnconfigure(0, weight=1)
            grid.grid_columnconfigure(1, weight=1)
            for i, (text, command) in enumerate(items):
                tile = self.tile_button(grid, text, command)
                tile.grid(row=i // 2, column=i % 2, sticky='ew', padx=6, pady=4)



















    def clear_main_menu(self):
        """Remove all widgets from the main menu."""
        for widget in self.main_menu.winfo_children():
            widget.destroy()

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
        """Format value as currency."""
        return f"£{value:.2f}"

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
            required_cols = ['Name', 'Division', 'Total Stock', 'Total Value']
            missing_cols = [col for col in required_cols if col not in items_df.columns]
            if missing_cols:
                messagebox.showerror("Invalid CSV", f"Items.csv is missing required columns: {', '.join(missing_cols)}")
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
                    division = str(row.get('Division', 'Uncategorized')).strip()
                    total_stock = float(row['Total Stock']) if pd.notna(row['Total Stock']) else 0
                    total_value = float(row['Total Value']) if pd.notna(row['Total Value']) else 0

                    # Skip empty items
                    if not item_name:
                        continue

                    # Create item_id using the same canonical normaliser as uploads.
                    item_id = normalize_product_name(item_name)

                    # Calculate cost price per unit (if total_value and total_stock are valid)
                    if total_stock > 0 and total_value > 0:
                        cost_price = total_value / total_stock
                    else:
                        cost_price = 0

                    # Default sell price (can be adjusted later)
                    sell_price = cost_price * 1.3  # 30% markup

                    # Determine measure and category from Division column
                    unit = str(row.get('Unit', '')).lower()
                    division = str(row.get('Division', '')).lower()

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
                                [item_name, total_stock, measure, category, division]
                        else:
                            # Update all fields for unlocked items
                            self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id,
                                                 [COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE, COL_MEASURE, COL_CATEGORY, COL_DIVISION]] = \
                                [item_name, total_stock, cost_price, sell_price, measure, category, division]
                        items_updated += 1
                    else:
                        # Add new item with every inventory column populated.
                        # Leaving allow_negative/reorder_level out produced NaN,
                        # and bool(np.nan) is True, so imported items silently
                        # became allowed to go negative.
                        new_item = pd.DataFrame([[item_id, item_name, total_stock, cost_price, sell_price, measure, category, False, False, 0, division]],
                                              columns=[COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE, COL_MEASURE, COL_CATEGORY, COL_PRICE_LOCKED, COL_ALLOW_NEGATIVE, COL_REORDER_LEVEL, COL_DIVISION])
                        self.inventory_df = pd.concat([self.inventory_df, new_item], ignore_index=True)
                        items_added += 1

                except Exception as item_error:
                    errors.append(f"Error processing '{row.get('Name', 'Unknown')}': {item_error}")

            # Save inventory
            if self._save_inventory():
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

        main_frame = tk.Frame(top, padx=20, pady=20)
        main_frame.pack(fill='both', expand=True)

        tk.Label(main_frame, text="Settings", font=(THEME_FONT, 14, 'bold')).pack(pady=(0, 15))

        # Member discount
        discount_frame = tk.Frame(main_frame)
        discount_frame.pack(fill='x', pady=5)
        tk.Label(discount_frame, text="Member Discount %:").pack(side='left')
        discount_var = tk.StringVar(value=str(int(self.get_member_discount_pct())))
        discount_entry = tk.Entry(discount_frame, textvariable=discount_var, width=10)
        discount_entry.pack(side='left', padx=5)
        tk.Label(discount_frame, text="(e.g., 10 for 10% off)").pack(side='left')

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

        btn_frame = tk.Frame(main_frame)
        btn_frame.pack(pady=20)
        tk.Button(btn_frame, text="Save", command=save_settings, width=15).pack(side='left', padx=10)
        tk.Button(btn_frame, text="Cancel", command=top.destroy, width=15).pack(side='left', padx=10)

        top.update_idletasks()
        self._apply_legacy_theme()

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

            tk.Label(dialog, text="Select a backup to restore:", font=(THEME_FONT, 12, 'bold')).pack(pady=10)

            tree = ttk.Treeview(dialog, columns=('timestamp', 'name', 'size'), show='headings', height=10)
            tree.heading('timestamp', text='Date/Time')
            tree.heading('name', text='Backup Name')
            tree.heading('size', text='Size (KB)')
            tree.column('timestamp', width=150)
            tree.column('name', width=300)
            tree.column('size', width=80, anchor='center')
            tree.pack(fill='both', expand=True, padx=10, pady=5)
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

            btn_frame = tk.Frame(dialog)
            btn_frame.pack(pady=10)
            tk.Button(btn_frame, text="Restore Selected", command=do_restore, width=15).pack(side=tk.LEFT, padx=5)
            tk.Button(btn_frame, text="Cancel", command=dialog.destroy, width=15).pack(side=tk.LEFT, padx=5)

            self._apply_legacy_theme()

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
    app = BarStockManagementSystem(root)
    root.mainloop()
