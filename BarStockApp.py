"""
Bar Stock Management System - Basic Version

Simple tkinter-based stock management for Prestonfield Golf Club.
"""

import tkinter as tk
from tkinter import messagebox, ttk, filedialog
import pandas as pd
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict
import calendar
from fpdf import FPDF
from categories import get_category, should_exclude, CATEGORY_ORDER, EXCLUDED_ITEMS
from conversions import (
    get_conversion, convert_to_system, convert_to_input,
    get_input_label, format_stock_display, format_quantity_display, requires_conversion
)
from sales_mapping import (
    has_parent_stock, get_parent_for_sale, apply_sale_to_parent,
    check_apply_sale_to_parent, normalize_product_name,
    get_affected_parents_description, is_hidden_from_stock_view, get_hidden_items,
    get_effective_cost_price, resolve_epos_item_id
)
from inventory_sync import (
    find_missing_mappings, has_sync_issues, format_sync_report,
    append_item_to_items_csv, find_items_csv_inventory_mismatches,
    find_untracked_items_on_order_sheet, find_recent_negative_items,
)
from actions import (
    ACTION_SALES, ACTION_SALES_ONE_UNIT, ACTION_DELIVERY,
    ACTION_WASTAGE, ACTION_LINE_CLEAN, ACTION_COMPLIMENTARY,
    ACTION_OPEN_TAB, ACTION_TAB_CANCELLED, ACTION_PARENT_STOCK_ADJ,
    ACTION_STOCKTAKE_BASELINE, ACTION_IMPORT,
)

# Calendar picker
try:
    from tkcalendar import Calendar
    TKCALENDAR_AVAILABLE = True
except ImportError:
    TKCALENDAR_AVAILABLE = False

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


def get_resource_path():
    """
    Get the correct path for data files.
    Data is stored in Application Support folder for proper macOS sandboxing.
    """
    # Use Application Support folder (appropriate for sandboxed apps)
    app_support_path = os.path.expanduser('~/Library/Application Support/BarStockManagement')
    os.makedirs(app_support_path, exist_ok=True)
    return app_support_path


def get_script_directory():
    """
    Get the directory where the script/app is located.
    Works for both regular Python and bundled apps (onefile and onedir).
    """
    if getattr(sys, 'frozen', False):
        # Running as bundled app
        # PyInstaller sets sys._MEIPASS to the extraction folder in onefile mode
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    else:
        # Running as regular Python script
        return os.path.dirname(os.path.abspath(__file__))


# Set up data directory
DATA_DIR = get_resource_path()

# Constants for file paths
INVENTORY_FILE = os.path.join(DATA_DIR, 'stock.csv')
LOG_FILE = os.path.join(DATA_DIR, 'transaction_log.csv')

# Column constants to avoid typos
COL_ITEM_ID = 'item_id'
COL_ITEM_NAME = 'item_name'
COL_QUANTITY = 'quantity'
COL_COST_PRICE = 'cost_price'
COL_SELL_PRICE = 'sell_price'
COL_MEASURE = 'measure'
COL_CATEGORY = 'category'
COL_ACTION = 'action'
COL_TIMESTAMP = 'timestamp'
COL_SUPPLIER = 'supplier'
COL_DATE_RANGE = 'date_range'
COL_PRICE_LOCKED = 'price_locked'
COL_REASON = 'reason'

# Constants for dropdown options
MEASURE_OPTIONS = ['Pint', 'Half Pint', '35ml', 'Bottle', 'Can', 'Pack']
CATEGORY_OPTIONS = ['Draught', 'Bottle', 'Spirit', 'Can', 'Soft', 'Snack', 'Wine']
DIVISION_OPTIONS = ['Beer - Draught', 'Beer - Bottled', 'Spirits', 'Soft Drinks', 'Post Mix', 'Mineral', 'Wine', 'Snacks', 'Other']

# Dark dashboard theme constants
THEME_BG = '#121212'
THEME_SIDEBAR = '#1a1a1a'
THEME_CARD = '#1e1e1e'
THEME_PANEL = '#1e1e1e'
THEME_BORDER = '#2a2a2a'
THEME_TEXT = '#eeeeee'
THEME_TEXT_MUTED = '#888888'
THEME_ACCENT = '#2563eb'
THEME_ACCENT_HOVER = '#1d4ed8'
THEME_SUCCESS = '#4ade80'
THEME_WARNING = '#facc15'
THEME_DANGER = '#f87171'
THEME_FONT = '-apple-system, BlinkMacSystemFont, SF Pro, Segoe UI, Arial'


from data_manager import (
    InventoryDataManager, get_setting, set_setting, AtomicTransaction,
    COL_ALLOW_NEGATIVE, COL_REORDER_LEVEL, COL_MEMBER_QTY, COL_NON_MEMBER_QTY, COL_DIVISION,
    record_stocktake, get_stocktake_history,
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

# Initialize database (migrates from CSV on first run)
InventoryDataManager.initialize_csv_files()

# Settings cache
MEMBER_DISCOUNT_PCT = 10


class DateRangeDialog:
    """Reusable date range picker dialog with interactive calendars."""

    def __init__(self, parent, title="Select Date Range"):
        self.parent = parent
        self.title = title
        self.result = None

        self.top = tk.Toplevel(parent)
        self.top.title(title)
        self.top.transient(parent)
        self.top.grab_set()
        self.top.lift()
        self.top.attributes('-topmost', True)
        self.top.after_idle(self.top.attributes, '-topmost', False)

        # Center and set size explicitly
        self.top.update_idletasks()
        if TKCALENDAR_AVAILABLE:
            width, height = 1050, 680
        else:
            width, height = 450, 320
        x = (self.top.winfo_screenwidth() - width) // 2
        y = (self.top.winfo_screenheight() - height) // 2
        self.top.geometry(f"{width}x{height}+{x}+{y}")
        self.top.minsize(width, height)

        frame = tk.Frame(self.top, padx=20, pady=15)
        frame.pack(fill='both', expand=True)

        tk.Label(frame, text=title, font=('Arial', 12, 'bold')).pack(pady=(0, 5))

        # Preset buttons
        preset_frame = tk.Frame(frame)
        preset_frame.pack(fill='x', pady=5)

        tk.Button(preset_frame, text="Last 7 Days",
                  command=lambda: self._set_preset(7), width=10).pack(side='left', padx=2)
        tk.Button(preset_frame, text="Last 30 Days",
                  command=lambda: self._set_preset(30), width=10).pack(side='left', padx=2)
        tk.Button(preset_frame, text="This Year",
                  command=lambda: self._set_preset(365), width=10).pack(side='left', padx=2)

        if TKCALENDAR_AVAILABLE:
            # Switch to clam theme so calendar custom colors work on macOS dark mode
            style = ttk.Style()
            self._original_theme = style.theme_use()
            style.theme_use('clam')

            # Calendar pickers side by side
            calendars_frame = tk.Frame(frame)
            calendars_frame.pack(fill='both', expand=True, pady=10)

            # Start calendar
            start_frame = tk.LabelFrame(calendars_frame, text="Start Date", font=('Arial', 9, 'bold'))
            start_frame.pack(side='left', fill='both', expand=True, padx=(0, 10))
            self.start_cal = Calendar(start_frame, selectmode='day', date_pattern='y-mm-dd', font=('Arial', 16),
                                       background='#2b2b2b', normalbackground='#2b2b2b', weekendbackground='#333333',
                                       othermonthbackground='#1e1e1e', othermonthwebackground='#262626',
                                       foreground='white', normalforeground='white', weekendforeground='white',
                                       othermonthforeground='white', othermonthweforeground='white',
                                       selectbackground='#0078d7', selectforeground='white', headersbackground='#444444', headersforeground='white')
            self.start_cal.pack(padx=5, pady=5)

            # End calendar
            end_frame = tk.LabelFrame(calendars_frame, text="End Date", font=('Arial', 9, 'bold'))
            end_frame.pack(side='left', fill='both', expand=True, padx=(10, 0))
            self.end_cal = Calendar(end_frame, selectmode='day', date_pattern='y-mm-dd', font=('Arial', 16),
                                     background='#2b2b2b', normalbackground='#2b2b2b', weekendbackground='#333333',
                                     othermonthbackground='#1e1e1e', othermonthwebackground='#262626',
                                     foreground='white', normalforeground='white', weekendforeground='white',
                                     othermonthforeground='white', othermonthweforeground='white',
                                     selectbackground='#0078d7', selectforeground='white', headersbackground='#444444', headersforeground='white')
            self.end_cal.pack(padx=5, pady=5)

            # Selected dates display
            self.dates_label = tk.Label(frame, text="", font=('Arial', 10))
            self.dates_label.pack(pady=5)
            self._update_dates_label()

            # Bind calendar clicks to update label
            self.start_cal.bind('<<CalendarSelected>>', lambda e: self._update_dates_label())
            self.end_cal.bind('<<CalendarSelected>>', lambda e: self._update_dates_label())
        else:
            # Fallback text entries
            date_frame = tk.Frame(frame)
            date_frame.pack(fill='x', pady=10)

            tk.Label(date_frame, text="Start:").grid(row=0, column=0, padx=5, pady=5, sticky='e')
            self.start_var = tk.StringVar()
            tk.Entry(date_frame, textvariable=self.start_var, width=15).grid(row=0, column=1, padx=5, pady=5)
            tk.Label(date_frame, text="YYYY-MM-DD").grid(row=0, column=2, padx=5, pady=5, sticky='w')

            tk.Label(date_frame, text="End:").grid(row=1, column=0, padx=5, pady=5, sticky='e')
            self.end_var = tk.StringVar()
            tk.Entry(date_frame, textvariable=self.end_var, width=15).grid(row=1, column=1, padx=5, pady=5)
            tk.Label(date_frame, text="YYYY-MM-DD").grid(row=1, column=2, padx=5, pady=5, sticky='w')

        # Buttons
        btn_frame = tk.Frame(frame)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Apply", command=self._on_apply, width=12).pack(side='left', padx=5)
        tk.Button(btn_frame, text="All Time", command=self._on_all_time, width=12).pack(side='left', padx=5)
        tk.Button(btn_frame, text="Cancel", command=self._on_cancel, width=12).pack(side='left', padx=5)

        self.top.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.top.wait_window(self.top)

    def _update_dates_label(self):
        if TKCALENDAR_AVAILABLE:
            start = self.start_cal.get_date()
            end = self.end_cal.get_date()
            self.dates_label.config(text=f"Selected: {start}  to  {end}")

    def _set_preset(self, days):
        end = datetime.now()
        start = end - timedelta(days=days)
        if TKCALENDAR_AVAILABLE:
            self.start_cal.selection_set(start)
            self.end_cal.selection_set(end)
            self._update_dates_label()
        else:
            self.start_var.set(start.strftime('%Y-%m-%d'))
            self.end_var.set(end.strftime('%Y-%m-%d'))

    def _restore_theme(self):
        """Restore original ttk theme before closing dialog."""
        if TKCALENDAR_AVAILABLE and hasattr(self, '_original_theme'):
            ttk.Style().theme_use(self._original_theme)

    def _on_apply(self):
        if TKCALENDAR_AVAILABLE:
            start_str = self.start_cal.get_date()
            end_str = self.end_cal.get_date()
        else:
            start_str = self.start_var.get().strip()
            end_str = self.end_var.get().strip()
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d') if start_str else None
            end_date = datetime.strptime(end_str, '%Y-%m-%d') if end_str else None
            if end_date:
                end_date = end_date.replace(hour=23, minute=59, second=59)
            self.result = (start_date, end_date)
            self._restore_theme()
            self.top.destroy()
        except ValueError:
            messagebox.showerror("Invalid Date", "Please select valid dates.")

    def _on_all_time(self):
        self.result = 'ALL_TIME'
        self._restore_theme()
        self.top.destroy()

    def _on_cancel(self):
        self.result = None
        self._restore_theme()
        self.top.destroy()


class BarStockManagementSystem:
    """Main application class for the Bar Stock Management System."""

    def __init__(self, root):
        """Initialize the application window and UI elements."""
        self.root = root
        self.root.title("Prestonfield Golf Club - Bar Stock Management")
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

        # Daily auto-backup check
        try:
            from data_manager import create_auto_backup
            auto_path = create_auto_backup()
            if auto_path:
                print(f"Auto-backup created: {auto_path}")
        except Exception:
            pass

        # Sync check: warn if any inventory item lacks conversion/category/order-sheet mapping
        try:
            missing = find_missing_mappings(self.inventory_df)
            if has_sync_issues(missing):
                report = format_sync_report(missing)
                self.root.after(500, lambda: messagebox.showwarning(
                    "Inventory Setup Check",
                    "Some tracked items are not fully configured:\n\n" + report +
                    "\n\nPlease add the missing rules to conversions.py, categories.py, or the order sheet."
                ))
        except Exception as e:
            print(f"Startup sync check failed: {e}")

        self.create_widgets()

    def setup_theme(self):
        """Configure the application-wide dark dashboard theme."""
        self.root.configure(bg=THEME_BG)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background=THEME_BG)
        style.configure('TLabel', background=THEME_BG, foreground=THEME_TEXT, font=(THEME_FONT, 12))
        style.configure('TButton', background=THEME_ACCENT, foreground='#ffffff', font=(THEME_FONT, 12))
        style.configure('Card.TFrame', background=THEME_CARD)
        style.configure('CardTitle.TLabel', background=THEME_CARD, foreground=THEME_TEXT_MUTED, font=(THEME_FONT, 10))
        style.configure('CardValue.TLabel', background=THEME_CARD, foreground=THEME_TEXT, font=(THEME_FONT, 22, 'bold'))
        style.configure('CardSub.TLabel', background=THEME_CARD, foreground=THEME_SUCCESS, font=(THEME_FONT, 10))
        style.configure('Treeview', background=THEME_CARD, foreground=THEME_TEXT, fieldbackground=THEME_CARD, rowheight=24)
        style.configure('Treeview.Heading', background=THEME_SIDEBAR, foreground=THEME_TEXT, font=(THEME_FONT, 11, 'bold'))

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
        """Create a theme-styled button."""
        if variant == 'primary':
            bg, fg, hover = THEME_ACCENT, '#ffffff', THEME_ACCENT_HOVER
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
        """Create a clickable tile button that renders reliably on macOS dark mode."""
        tile = tk.Label(
            parent, text=text, font=(THEME_FONT, 12, 'bold'),
            bg=THEME_CARD, fg=THEME_TEXT, cursor='hand2',
            padx=12, pady=14, anchor='center',
            highlightbackground=THEME_BORDER, highlightthickness=1,
        )
        tile.bind('<Button-1>', lambda event: command())

        def on_enter(event):
            tile.config(bg=THEME_BORDER, fg='#ffffff')

        def on_leave(event):
            tile.config(bg=THEME_CARD, fg=THEME_TEXT)

        tile.bind('<Enter>', on_enter)
        tile.bind('<Leave>', on_leave)
        return tile

    def create_card(self, parent, title, value, subtext='', status='normal'):
        """Create a dashboard summary card."""
        card = tk.Frame(parent, bg=THEME_CARD, bd=1, relief='solid',
                         highlightbackground=THEME_BORDER, highlightthickness=1)
        card.pack(side='left', fill='both', expand=True, padx=8, pady=5)

        title_lbl = tk.Label(card, text=title.upper(), font=(THEME_FONT, 9),
                             fg=THEME_TEXT_MUTED, bg=THEME_CARD)
        title_lbl.pack(anchor='w', padx=14, pady=(12, 2))

        value_color = THEME_TEXT
        if status == 'danger':
            value_color = THEME_DANGER
        elif status == 'warning':
            value_color = THEME_WARNING
        value_lbl = tk.Label(card, text=value, font=(THEME_FONT, 24, 'bold'),
                             fg=value_color, bg=THEME_CARD)
        value_lbl.pack(anchor='w', padx=14)

        if subtext:
            sub_lbl = tk.Label(card, text=subtext, font=(THEME_FONT, 10),
                               fg=THEME_SUCCESS if status == 'normal' else value_color,
                               bg=THEME_CARD)
            sub_lbl.pack(anchor='w', padx=14, pady=(2, 12))
        else:
            tk.Label(card, text='', bg=THEME_CARD).pack(pady=(0, 6))
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
        """Save data and confirm before exiting the application."""
        # Save all data before exiting
        if not self.inventory_df.empty:
            InventoryDataManager.save_inventory(self.inventory_df)
        if not self.log_df.empty:
            InventoryDataManager.save_log(self.log_df)

        if messagebox.askyesno("Confirm Exit", "Are you sure you want to exit?\n\nAll data has been saved."):
            self.root.quit()

    def create_widgets(self):
        """Create and arrange all UI widgets in the application window."""
        self.main_menu = tk.Frame(self.root)
        self.main_menu.pack(fill="both", expand=True)

        self.create_main_menu()

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
        top.minsize(400, 420)
        top.transient(parent_widget)
        top.grab_set()
        top.lift()

        # Parse current date from the variable
        current_text = date_var.get().strip()
        try:
            current_date = datetime.strptime(current_text, "%d/%m/%Y")
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
                tk.Label(days_frame, text=wd, font=('Arial', 10, 'bold'), width=5).grid(row=0, column=i, padx=3, pady=3)

            cal = calendar.Calendar()
            month_days = cal.monthdayscalendar(y, m)

            for r, week in enumerate(month_days, start=1):
                for c, d in enumerate(week):
                    if d == 0:
                        tk.Label(days_frame, text="", width=5).grid(row=r, column=c)
                    else:
                        btn = tk.Button(days_frame, text=str(d), width=5, font=('Arial', 10), command=lambda d=d: select_date(y, m, d))
                        if d == day and y == year and m == month:
                            btn.config(bg='#4a90d9', fg='white', font=('Arial', 10, 'bold'))
                        btn.grid(row=r, column=c, padx=2, pady=2)

        def select_date(y, m, d):
            date_var.set(f"{d:02d}/{m:02d}/{y}")
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

        tk.Button(header_frame, text="<", command=prev_month, width=3, font=('Arial', 12)).pack(side=tk.LEFT, padx=10)
        tk.Label(header_frame, textvariable=month_var, font=('Arial', 12, 'bold'), width=10).pack(side=tk.LEFT)
        tk.Label(header_frame, textvariable=year_var, font=('Arial', 12, 'bold'), width=6).pack(side=tk.LEFT)
        tk.Button(header_frame, text=">", command=next_month, width=3, font=('Arial', 12)).pack(side=tk.LEFT, padx=10)

        days_frame = tk.Frame(top)
        days_frame.pack(pady=5)

        refresh_days()

        def select_today():
            now = datetime.now()
            select_date(now.year, now.month, now.day)

        tk.Button(top, text="Today", command=select_today).pack(pady=5)

    def create_main_menu(self):
        """Create the modern dark dashboard with sidebar navigation."""
        # Clear existing widgets
        for widget in self.main_menu.winfo_children():
            widget.destroy()

        # Root container with sidebar + main area
        container = tk.Frame(self.main_menu, bg=THEME_BG)
        container.pack(fill='both', expand=True)

        # Sidebar
        sidebar = self.themed_frame(container, bg=THEME_SIDEBAR, width=220)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)

        logo_frame = self.themed_frame(sidebar, bg=THEME_SIDEBAR, height=70)
        logo_frame.pack(fill='x', padx=18, pady=(24, 8))
        logo_frame.pack_propagate(False)
        self.themed_label(logo_frame, "Prestonfield GC",
                          font=(THEME_FONT, 17, 'bold'), fg=THEME_TEXT).pack(anchor='w')
        self.themed_label(logo_frame, "Bar Stock Management",
                          font=(THEME_FONT, 10), fg=THEME_TEXT_MUTED).pack(anchor='w')

        # Navigation groups
        nav = [
            ("Dashboard", self.create_main_menu, True),
            ("Manage Stock", self.manage_initial_stock, False),
            ("Add Delivery", self.add_delivery, False),
            ("Add Sales", self.add_sales, False),
            ("Add Wastage", self.add_wastage, False),
            ("Add Complimentary", self.add_complimentary, False),
            ("Open Tabs", self.open_tabs_menu, False),
            ("Full Stocktake", self.full_stock_take, False),
            ("Line Clean", self.line_clean, False),
        ]
        nav_frame = self.themed_frame(sidebar, bg=THEME_SIDEBAR)
        nav_frame.pack(fill='x', padx=12, pady=10)
        for text, command, active in nav:
            self._nav_button(nav_frame, text, command, active)

        tools_frame = self.themed_frame(sidebar, bg=THEME_SIDEBAR)
        tools_frame.pack(fill='x', padx=12, pady=(20, 10))
        self.themed_label(tools_frame, "TOOLS",
                          font=(THEME_FONT, 9, 'bold'), fg=THEME_TEXT_MUTED).pack(anchor='w', pady=(0, 8))
        self._nav_button(tools_frame, "Reports", self.generate_reports, False)
        self._nav_button(tools_frame, "Transactions", self.view_transaction_log, False)
        self._nav_button(tools_frame, "Delivery History", self.view_delivery_history, False)
        self._nav_button(tools_frame, "Settings", self.open_settings, False)
        self._nav_button(tools_frame, "Restore Backup", self.restore_from_backup_menu, False)
        self._nav_button(tools_frame, "Init from Items.csv", self.initialize_stock_from_items_csv, False)
        self._nav_button(tools_frame, "Reset System", self.reset_system, False, danger=True)

        # System actions at bottom of sidebar
        system_frame = self.themed_frame(sidebar, bg=THEME_SIDEBAR)
        system_frame.pack(fill='x', padx=12, pady=(20, 10), side='bottom')
        self.themed_label(system_frame, "SYSTEM",
                          font=(THEME_FONT, 9, 'bold'), fg=THEME_TEXT_MUTED).pack(anchor='w', pady=(0, 8))
        self._nav_button(system_frame, "Exit System", self.on_exit, False, danger=True)

        # Main content area
        self.dashboard_area = self.themed_frame(container)
        self.dashboard_area.pack(side='left', fill='both', expand=True, padx=24, pady=24)

        # Header with primary action
        header = self.themed_frame(self.dashboard_area)
        header.pack(fill='x', pady=(0, 20))
        self.themed_label(header, "Dashboard",
                          font=(THEME_FONT, 24, 'bold')).pack(side='left')
        self.tile_button(header, "+ Add Delivery", self.add_delivery).pack(side='right')

        # Alert banners
        self.update_critical_stock_alert(self.dashboard_area)
        self.update_variance_alert(self.dashboard_area)
        self.update_open_tab_alert(self.dashboard_area)

        # Dashboard cards
        self.update_dashboard_stats(self.dashboard_area)

        # Upload banner
        self._render_upload_banner(self.dashboard_area)

        # Items needing attention
        self._render_attention_table(self.dashboard_area)

        # Quick actions panel
        quick_panel = self.create_panel(self.dashboard_area, "Quick Actions")
        quick_grid = self.themed_frame(quick_panel, bg=THEME_PANEL)
        quick_grid.pack(fill='x', padx=14, pady=(0, 14))
        quick_grid.grid_columnconfigure(0, weight=1)
        quick_grid.grid_columnconfigure(1, weight=1)
        quick_grid.grid_columnconfigure(2, weight=1)
        quick_actions = [
            ("Manage Stock", self.manage_initial_stock),
            ("Add Sales", self.add_sales),
            ("Add Wastage", self.add_wastage),
            ("Open Tabs", self.open_tabs_menu),
            ("Full Stocktake", self.full_stock_take),
            ("Line Clean", self.line_clean),
        ]
        for i, (text, command) in enumerate(quick_actions):
            self.tile_button(quick_grid, text, command).grid(
                row=i // 3, column=i % 3, padx=8, pady=8, sticky='ew'
            )

        # Report shortcuts panel
        reports_panel = self.create_panel(self.dashboard_area, "Report Shortcuts")
        reports_grid = self.themed_frame(reports_panel, bg=THEME_PANEL)
        reports_grid.pack(fill='x', padx=14, pady=(0, 14))
        reports_grid.grid_columnconfigure(0, weight=1)
        reports_grid.grid_columnconfigure(1, weight=1)
        reports_grid.grid_columnconfigure(2, weight=1)
        report_actions = [
            ("Gross Profit", self.generate_gp_report),
            ("Division Report", self.generate_division_report),
            ("Reorder Suggestions", self.generate_reorder_report),
            ("Sales Trends", self.generate_sales_analytics),
            ("Surplus / Variance", self.generate_surplus_report),
            ("Transaction Log", self.view_transaction_log),
            ("Delivery History", self.view_delivery_history),
        ]
        for i, (text, command) in enumerate(report_actions):
            self.tile_button(reports_grid, text, command).grid(
                row=i // 3, column=i % 3, padx=8, pady=8, sticky='ew'
            )

        # Footer
        footer = self.themed_frame(self.dashboard_area)
        footer.pack(fill='x', pady=(20, 0))
        self.themed_label(footer, "Created by Chris Armstrong",
                          font=(THEME_FONT, 9, 'italic'),
                          fg=THEME_TEXT_MUTED).pack(side='right')

    def _nav_button(self, parent, text, command, active, danger=False):
        """Create a sidebar navigation button."""
        bg = THEME_ACCENT if active else THEME_SIDEBAR
        fg = '#ffffff' if active else (THEME_DANGER if danger else THEME_TEXT)
        hover = THEME_ACCENT_HOVER if active else THEME_BORDER

        btn = tk.Label(parent, text=text, font=(THEME_FONT, 12, 'bold' if active else 'normal'),
                       bg=bg, fg=fg, cursor='hand2', anchor='w',
                       padx=12, pady=8)
        btn.pack(fill='x', pady=3)

        def on_enter(event):
            if not active:
                btn.config(bg=hover)

        def on_leave(event):
            if not active:
                btn.config(bg=bg)

        def on_click(event):
            command()

        btn.bind('<Enter>', on_enter)
        btn.bind('<Leave>', on_leave)
        btn.bind('<Button-1>', on_click)
        return btn

    def update_dashboard_stats(self, parent=None):
        """Render simplified dashboard summary cards."""
        if parent is None:
            if not hasattr(self, 'dashboard_area') or not self.dashboard_area.winfo_exists():
                return
            parent = self.dashboard_area
        if hasattr(self, 'stats_frame'):
            self.stats_frame.destroy()

        self.stats_frame = self.themed_frame(parent)
        self.stats_frame.pack(fill='x', pady=(0, 18))

        total_items = len(self.inventory_df)

        # Negative stock count (excluding hidden/excluded items)
        neg_stock_count = 0
        if not self.inventory_df.empty and COL_ITEM_ID in self.inventory_df.columns:
            neg_stock_df = self.inventory_df[self.inventory_df[COL_QUANTITY] < 0]
            neg_stock_df = neg_stock_df[~neg_stock_df[COL_ITEM_ID].apply(is_hidden_from_stock_view)]
            neg_stock_df = neg_stock_df[~neg_stock_df[COL_ITEM_ID].apply(should_exclude)]
            neg_stock_count = len(neg_stock_df)

        # Low stock count (at or below reorder level)
        low_stock_count = 0
        if COL_REORDER_LEVEL in self.inventory_df.columns and not self.inventory_df.empty:
            low_stock_df = self.inventory_df[self.inventory_df[COL_QUANTITY] <= self.inventory_df[COL_REORDER_LEVEL]]
            low_stock_df = low_stock_df[low_stock_df[COL_REORDER_LEVEL] > 0]
            low_stock_df = low_stock_df[~low_stock_df[COL_ITEM_ID].apply(is_hidden_from_stock_view)]
            low_stock_df = low_stock_df[~low_stock_df[COL_ITEM_ID].apply(should_exclude)]
            low_stock_count = len(low_stock_df)

        # Last delivery timestamp
        last_delivery = "None"
        if not self.log_df.empty and COL_ACTION in self.log_df.columns:
            deliveries = self.log_df[self.log_df[COL_ACTION] == ACTION_DELIVERY]
            if not deliveries.empty and COL_TIMESTAMP in deliveries.columns:
                try:
                    latest = deliveries[COL_TIMESTAMP].max()
                    last_delivery = latest.split()[0]
                except Exception:
                    last_delivery = "Unknown"

        # Latest backup date
        latest_backup = "None"
        try:
            import glob
            backups = sorted(glob.glob(os.path.join(DATA_DIR, 'backups', 'barstock_*.db')), key=os.path.getmtime, reverse=True)
            if backups:
                mtime = os.path.getmtime(backups[0])
                latest_backup = datetime.fromtimestamp(mtime).strftime('%d/%m/%Y')
        except Exception:
            latest_backup = "Unknown"

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

    def _render_attention_table(self, parent=None):
        """Show a simple table of items that need action: negative, low, or discrepancy."""
        if parent is None:
            if not hasattr(self, 'dashboard_area') or not self.dashboard_area.winfo_exists():
                return
            parent = self.dashboard_area
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
                              font=(THEME_FONT, 11), fg=THEME_SUCCESS).pack(anchor='w', padx=14, pady=(0, 14))
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

        for item in attention:
            current_text = f"{item['qty']:.1f} {item['measure']}s" if item['measure'] else f"{item['qty']:.1f}"
            tag = 'danger' if item['tag'] == 'danger' else 'warning'
            tree.insert('', tk.END, values=(item['name'], current_text, item['status'], item['action']), tags=(tag,))

        tree.tag_configure('danger', foreground=THEME_DANGER, font=(THEME_FONT, 10, 'bold'))
        tree.tag_configure('warning', foreground=THEME_WARNING, font=(THEME_FONT, 10, 'bold'))

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
            if not hasattr(self, 'dashboard_area') or not self.dashboard_area.winfo_exists():
                return
            parent = self.dashboard_area
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
                 font=(THEME_FONT, 11, 'bold'), bg='#3a1010', fg=THEME_DANGER,
                 wraplength=1100, justify='left').pack(anchor='w', padx=14, pady=10)

    def update_variance_alert(self, parent=None):
        """Display a dark-themed yellow warning banner for unexplained stock variance."""
        if parent is None:
            if not hasattr(self, 'dashboard_area') or not self.dashboard_area.winfo_exists():
                return
            parent = self.dashboard_area
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
                     font=(THEME_FONT, 11, 'bold'), bg='#382a05', fg=THEME_WARNING,
                     wraplength=1100, justify='left').pack(anchor='w', padx=14, pady=10)
        except Exception:
            return

    def update_open_tab_alert(self, parent=None):
        """Display a dark-themed red alert banner for stale open tabs."""
        if parent is None:
            if not hasattr(self, 'dashboard_area') or not self.dashboard_area.winfo_exists():
                return
            parent = self.dashboard_area
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
                     font=(THEME_FONT, 11, 'bold'), bg='#3a1010', fg=THEME_DANGER,
                     wraplength=1100, justify='left').pack(anchor='w', padx=14, pady=10)
        except Exception:
            return

    def _render_upload_banner(self, parent=None):
        """Render dark-themed upload history banner."""
        if parent is None:
            if not hasattr(self, 'dashboard_area') or not self.dashboard_area.winfo_exists():
                return
            parent = self.dashboard_area
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
                 font=(THEME_FONT, 10), bg='#0f2e4e', fg='#93c5fd').pack(anchor='w', padx=14, pady=8)

    def _render_stock_alerts_panel(self, parent):
        """Render a dark-themed panel listing items needing attention."""
        panel = self.create_panel(parent, "Stock Alerts")
        rows_frame = self.themed_frame(panel, bg=THEME_PANEL)
        rows_frame.pack(fill='x', padx=14, pady=(0, 14))

        header_bg = THEME_PANEL
        col_config = [("Item", 30, 'w'), ("Current", 15, 'center'),
                      ("Reorder", 15, 'center'), ("Status", 15, 'center')]
        for text, width, anchor in col_config:
            tk.Label(rows_frame, text=text, font=(THEME_FONT, 10, 'bold'),
                     bg=header_bg, fg=THEME_TEXT_MUTED, width=width, anchor=anchor).pack(side='left', padx=4)

        df = self._safe_slice(self.inventory_df, [COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_REORDER_LEVEL])
        if df.empty:
            tk.Label(rows_frame, text="No inventory data available.", font=(THEME_FONT, 11),
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
                     font=(THEME_FONT, 11), bg=THEME_PANEL, fg=THEME_SUCCESS).pack(pady=10)
            return

        list_frame = self.themed_frame(panel, bg=THEME_PANEL)
        list_frame.pack(fill='x', padx=14, pady=(0, 14))
        for row in alert_rows:
            row_frame = self.themed_frame(list_frame, bg=THEME_PANEL)
            row_frame.pack(fill='x', pady=3)
            tk.Label(row_frame, text=row[COL_ITEM_NAME], font=(THEME_FONT, 11),
                     bg=THEME_PANEL, fg=THEME_TEXT, width=30, anchor='w').pack(side='left', padx=4)
            tk.Label(row_frame, text=f"{row[COL_QUANTITY]:.1f}", font=(THEME_FONT, 11),
                     bg=THEME_PANEL, fg=row['status_color'], width=15, anchor='center').pack(side='left', padx=4)
            tk.Label(row_frame, text=f"{row[COL_REORDER_LEVEL]:.1f}", font=(THEME_FONT, 11),
                     bg=THEME_PANEL, fg=THEME_TEXT_MUTED, width=15, anchor='center').pack(side='left', padx=4)
            tk.Label(row_frame, text=row['status_text'], font=(THEME_FONT, 10, 'bold'),
                     bg=THEME_PANEL, fg=row['status_color'], width=15, anchor='center').pack(side='left', padx=4)

    def clear_main_menu(self):
        """Remove all widgets from the main menu."""
        for widget in self.main_menu.winfo_children():
            widget.destroy()

    def refresh_data(self):
        """Reload data from CSV files."""
        self.inventory_df = InventoryDataManager.load_inventory()
        self.log_df = InventoryDataManager.load_log(self.inventory_df)

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

    def manage_initial_stock(self):
        """Display the initial stock management interface."""
        self.clear_main_menu()

        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)

        tk.Label(header_frame, text="Stock Management",
                font=('Arial', 16, 'bold')).pack(expand=True)

        # Search frame
        search_frame = tk.Frame(self.main_menu)
        search_frame.pack(fill='x', padx=10, pady=5)

        tk.Label(search_frame, text="Search:").pack(side=tk.LEFT, padx=5)
        self.search_entry = tk.Entry(search_frame)
        self.search_entry.pack(side=tk.LEFT, fill='x', expand=True, padx=5)
        self.search_entry.bind('<KeyRelease>', lambda e: self.search_stock())

        tk.Button(search_frame, text="Search", command=self.search_stock).pack(side=tk.LEFT, padx=5)
        tk.Button(search_frame, text="Clear", command=self.clear_search).pack(side=tk.LEFT, padx=5)

        # Treeview frame
        self.stock_frame = tk.Frame(self.main_menu)
        self.stock_frame.pack(fill='both', expand=True, padx=10, pady=10)

        # Create treeview with scrollbar
        tree_container = tk.Frame(self.stock_frame)
        tree_container.pack(fill='both', expand=True)

        self.stock_tree = ttk.Treeview(tree_container, columns=('item_id', 'item_name', 'quantity', 'cost_price', 'sell_price', 'stock_value', 'measure', 'category'), show='headings')

        # Define column headings
        self.stock_tree.heading('item_id', text='Item ID')
        self.stock_tree.heading('item_name', text='Item Name')
        self.stock_tree.heading('quantity', text='Quantity')
        self.stock_tree.heading('cost_price', text='Cost Price')
        self.stock_tree.heading('sell_price', text='Sell Price')
        self.stock_tree.heading('stock_value', text='Stock Value')
        self.stock_tree.heading('measure', text='Measure')
        self.stock_tree.heading('category', text='Category')

        # Set column widths
        self.stock_tree.column('item_id', width=100, anchor='center')
        self.stock_tree.column('item_name', width=150)
        self.stock_tree.column('quantity', width=80, anchor='center')
        self.stock_tree.column('cost_price', width=80, anchor='center')
        self.stock_tree.column('sell_price', width=80, anchor='center')
        self.stock_tree.column('stock_value', width=80, anchor='center')
        self.stock_tree.column('measure', width=80, anchor='center')
        self.stock_tree.column('category', width=100, anchor='center')

        self.stock_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.stock_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.stock_tree.configure(yscrollcommand=scrollbar.set)

        # Double-click to update item
        self.stock_tree.bind('<Double-1>', lambda event: self.on_stock_tree_double_click(event))

        self.load_stock_into_tree()

        # Button frame
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="Add Item", command=self.add_stock_item).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Update Item", command=self.update_stock_item).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Delete Item", command=self.delete_stock_item).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Back", command=self.create_main_menu).pack(side=tk.LEFT, padx=5)

    def sort_treeview(self, tree, col, reverse):
        """Sort treeview contents when a column header is clicked."""
        l = [(tree.set(k, col), k) for k in tree.get_children('')]
        try:
            # Try numeric sort first
            l.sort(key=lambda t: float(t[0].replace('£', '')), reverse=reverse)
        except:
            # Fall back to string sort
            l.sort(reverse=reverse)

        for index, (val, k) in enumerate(l):
            tree.move(k, '', index)

        tree.heading(col, command=lambda: self.sort_treeview(tree, col, not reverse))

    def search_stock(self):
        """Filter stock based on search term."""
        search_term = self.search_entry.get().lower()
        self.load_stock_into_tree(search_term)

    def clear_search(self):
        """Clear search and show all items."""
        self.search_entry.delete(0, tk.END)
        self.load_stock_into_tree()

    def load_stock_into_tree(self, search_term=None):
        """Load current stock data into the treeview."""
        self.refresh_data()

        # Clear existing items
        for item in self.stock_tree.get_children():
            self.stock_tree.delete(item)

        # Filter and insert data
        for _, row in self.inventory_df.iterrows():
            item_id = row[COL_ITEM_ID]

            # Skip hidden items (half pints, dash, shandies) - they deduct from parent stock
            if is_hidden_from_stock_view(item_id):
                continue

            if search_term is None or search_term in str(row[COL_ITEM_ID]).lower() or search_term in str(row[COL_ITEM_NAME]).lower():
                stock_value = row[COL_QUANTITY] * row[COL_COST_PRICE]
                measure = row.get(COL_MEASURE, '-')
                category = row.get(COL_CATEGORY, '-')

                # Check if item requires conversion and show both values
                quantity_display = f"{row[COL_QUANTITY]:.1f}"
                if requires_conversion(item_id):
                    from conversions import get_conversion
                    input_qty = convert_to_input(item_id, row[COL_QUANTITY])
                    input_unit = get_input_label(item_id)
                    _, _, output_unit = get_conversion(item_id)
                    quantity_display = f"{input_qty:.1f} {input_unit}s ({row[COL_QUANTITY]:.1f} {output_unit}s)"

                values = (row[COL_ITEM_ID], row[COL_ITEM_NAME], quantity_display,
                         self.format_currency(row[COL_COST_PRICE]), self.format_currency(row[COL_SELL_PRICE]),
                         self.format_currency(stock_value), measure, category)

                # Determine tag based on stock status
                tag = ''
                if row[COL_QUANTITY] < 0 and not row.get(COL_ALLOW_NEGATIVE, False):
                    tag = 'negative_stock'
                elif COL_REORDER_LEVEL in row and row[COL_REORDER_LEVEL] > 0 and row[COL_QUANTITY] <= row[COL_REORDER_LEVEL]:
                    tag = 'low_stock'

                self.stock_tree.insert('', tk.END, values=values, tags=(tag,))

        # Configure tag styles
        self.stock_tree.tag_configure('low_stock', background='#fff3cd')
        self.stock_tree.tag_configure('negative_stock', background='#f8d7da')

    def validate_number(self, value, field_name, allow_zero=False, allow_negative=False):
        """Validate that a value is a valid number."""
        try:
            num = float(value)
            if not allow_negative and num < 0:
                messagebox.showerror("Error", f"{field_name} cannot be negative.")
                return None
            if not allow_zero and num == 0:
                messagebox.showerror("Error", f"{field_name} cannot be zero.")
                return None
            return num
        except ValueError:
            messagebox.showerror("Error", f"{field_name} must be a valid number.")
            return None

    def add_stock_item(self):
        """Add a new item to the stock inventory."""
        def save_item():
            item_id = entry_item_id.get().strip()
            item_name = entry_item_name.get().strip()
            quantity = entry_quantity.get().strip()
            cost_price = entry_cost_price.get().strip()
            sell_price = entry_sell_price.get().strip()
            measure = measure_var.get()
            category = category_var.get()

            # Validation
            if not all([item_id, item_name, quantity, cost_price, sell_price]):
                messagebox.showerror("Error", "All fields are required.")
                return

            # Check for duplicate item_id
            if item_id in self.inventory_df[COL_ITEM_ID].values:
                messagebox.showerror("Error", f"Item ID '{item_id}' already exists. Use a unique ID.")
                return

            # Validate numbers
            input_quantity = self.validate_number(quantity, "Quantity", allow_zero=True)
            if input_quantity is None:
                return

            # Convert quantity to system units if this item has a conversion defined
            from conversions import requires_conversion as conv_requires, convert_to_system as conv_convert
            if conv_requires(item_id):
                quantity = conv_convert(item_id, input_quantity)
            else:
                quantity = input_quantity

            cost_price = self.validate_number(cost_price, "Cost price", allow_zero=True)
            if cost_price is None:
                return

            sell_price = self.validate_number(sell_price, "Sell price", allow_zero=True)
            if sell_price is None:
                return

            # Validate that sell price >= cost price (only if both are non-zero)
            if sell_price < cost_price and (sell_price > 0 or cost_price > 0):
                if not messagebox.askyesno("Warning", "Sell price is less than cost price. Continue anyway?"):
                    return

            # Get allow_negative, reorder_level, and division
            allow_negative = allow_negative_var.get()
            reorder_level = self.validate_number(entry_reorder_level.get().strip(), "Reorder Level", allow_zero=True)
            if reorder_level is None:
                reorder_level = 0
            division = division_var.get()

            # Create and save new item
            new_item = pd.DataFrame([[item_id, item_name, quantity, cost_price, sell_price, measure, category, False, allow_negative, reorder_level, division]],
                                    columns=[COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE, COL_MEASURE, COL_CATEGORY, COL_PRICE_LOCKED, COL_ALLOW_NEGATIVE, COL_REORDER_LEVEL, COL_DIVISION])
            self.inventory_df = pd.concat([self.inventory_df, new_item], ignore_index=True)

            if InventoryDataManager.save_inventory(self.inventory_df):
                # Keep master Items.csv in sync so new items survive database rebuilds
                try:
                    script_dir = get_script_directory()
                    total_value = float(quantity) * float(cost_price)
                    append_item_to_items_csv(
                        script_dir=script_dir,
                        item_id=item_id,
                        item_name=item_name,
                        division=division,
                        measure=measure,
                        quantity=input_quantity,
                        total_value=total_value,
                    )
                except Exception as csv_err:
                    print(f"Could not update Items.csv: {csv_err}")

                self.load_stock_into_tree()
                self.update_dashboard_stats()
                top.destroy()
                messagebox.showinfo("Success", f"Item '{item_name}' added successfully.")

        top = tk.Toplevel(self.root)
        top.title("Add Stock Item")
        top.geometry("450x550")
        top.transient(self.root)
        top.grab_set()

        # macOS-specific: Bring dialog to front
        top.lift()
        top.attributes('-topmost', True)
        top.after_idle(top.attributes, '-topmost', False)

        # Center the window
        top.update_idletasks()
        x = (top.winfo_screenwidth() - top.winfo_width()) // 2
        y = (top.winfo_screenheight() - top.winfo_height()) // 2
        top.geometry(f'+{x}+{y}')

        # Create form
        main_frame = tk.Frame(top, padx=20, pady=20)
        main_frame.pack(fill='both', expand=True)

        # Text entry fields
        fields = [
            ("Item ID:", 'item_id'),
            ("Item Name:", 'item_name'),
            ("Quantity:", 'quantity'),
            ("Cost Price:", 'cost_price'),
            ("Sell Price:", 'sell_price'),
        ]

        entries = {}
        for i, (label, key) in enumerate(fields):
            tk.Label(main_frame, text=label).grid(row=i, column=0, padx=5, pady=8, sticky="e")
            entry = tk.Entry(main_frame, width=30)
            entry.grid(row=i, column=1, padx=5, pady=8, sticky="ew")
            entries[key] = entry

        entry_item_id = entries['item_id']
        entry_item_name = entries['item_name']
        entry_quantity = entries['quantity']
        entry_quantity.insert(0, "0")
        entry_cost_price = entries['cost_price']
        entry_sell_price = entries['sell_price']

        # Measure dropdown
        tk.Label(main_frame, text="Measure:").grid(row=5, column=0, padx=5, pady=8, sticky="e")
        measure_var = tk.StringVar(value=MEASURE_OPTIONS[0])
        measure_dropdown = ttk.Combobox(main_frame, textvariable=measure_var, values=MEASURE_OPTIONS, width=28, state="readonly")
        measure_dropdown.grid(row=5, column=1, padx=5, pady=8, sticky="ew")

        # Category dropdown
        tk.Label(main_frame, text="Category:").grid(row=6, column=0, padx=5, pady=8, sticky="e")
        category_var = tk.StringVar(value=CATEGORY_OPTIONS[0])
        category_dropdown = ttk.Combobox(main_frame, textvariable=category_var, values=CATEGORY_OPTIONS, width=28, state="readonly")
        category_dropdown.grid(row=6, column=1, padx=5, pady=8, sticky="ew")

        # Allow Negative Stock checkbox
        allow_negative_var = tk.BooleanVar(value=False)
        allow_negative_checkbox = tk.Checkbutton(main_frame, text="Allow Negative Stock",
                                                   variable=allow_negative_var, wraplength=300, justify='left')
        allow_negative_checkbox.grid(row=7, column=0, columnspan=2, padx=5, pady=4, sticky="w")

        # Reorder Level
        tk.Label(main_frame, text="Reorder Level:").grid(row=8, column=0, padx=5, pady=8, sticky="e")
        entry_reorder_level = tk.Entry(main_frame, width=30)
        entry_reorder_level.insert(0, "0")
        entry_reorder_level.grid(row=8, column=1, padx=5, pady=8, sticky="ew")

        # Division dropdown
        tk.Label(main_frame, text="Division:").grid(row=9, column=0, padx=5, pady=8, sticky="e")
        division_var = tk.StringVar(value=DIVISION_OPTIONS[-1])
        division_dropdown = ttk.Combobox(main_frame, textvariable=division_var, values=DIVISION_OPTIONS, width=28, state="readonly")
        division_dropdown.grid(row=9, column=1, padx=5, pady=8, sticky="ew")

        # Button frame
        btn_frame = tk.Frame(main_frame)
        btn_frame.grid(row=10, column=0, columnspan=2, pady=20)

        tk.Button(btn_frame, text="Save Item", command=save_item, width=15).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Cancel", command=top.destroy, width=15).pack(side=tk.LEFT, padx=10)

        main_frame.grid_columnconfigure(1, weight=1)

        # Force redraw so ttk.Combobox is visible immediately on macOS
        top.update_idletasks()

    def on_stock_tree_double_click(self, event):
        """Handle double-click on stock treeview item to open update dialog."""
        # Get the item under the cursor
        item = self.stock_tree.identify('item', event.x, event.y)
        if item:
            self.stock_tree.selection_set(item)
            self.update_stock_item()

    def update_stock_item(self):
        """Update an existing stock item based on selected item in treeview."""
        selected_item = self.stock_tree.selection()
        if not selected_item:
            messagebox.showerror("Error", "No item selected. Please select an item from the list.")
            return

        item_values = self.stock_tree.item(selected_item, 'values')
        item_id = item_values[0]
        current_name = item_values[1]

        # Get current measure and category from inventory
        current_measure = item_values[6] if len(item_values) > 6 else MEASURE_OPTIONS[0]
        current_category = item_values[7] if len(item_values) > 7 else CATEGORY_OPTIONS[0]

        # Get current price_locked value from inventory
        current_price_locked = False
        if item_id in self.inventory_df[COL_ITEM_ID].values:
            locked_val = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_PRICE_LOCKED].values[0]
            if pd.notna(locked_val) and locked_val:
                current_price_locked = True

        # Check if item requires conversion and get current values
        requires_conv = requires_conversion(item_id)
        current_system_qty = InventoryDataManager.get_item_value_safe(
            self.inventory_df, item_id, COL_QUANTITY, default=0)
        if requires_conv:
            current_input_qty = convert_to_input(item_id, current_system_qty)
            input_unit = get_input_label(item_id)
            conversion = get_conversion(item_id)
            conversion_factor = conversion[1] if conversion else 1
            output_unit = conversion[2] if conversion else "pints"
        else:
            current_input_qty = current_system_qty
            input_unit = ""

        def save_update():
            new_name = entry_name.get().strip()
            new_quantity_str = entry_quantity.get().strip()
            new_cost_price = entry_cost_price.get().strip()
            new_sell_price = entry_sell_price.get().strip()
            new_measure = measure_var.get()
            new_category = category_var.get()

            if not new_name:
                messagebox.showerror("Error", "Item name is required.")
                return

            # Validate quantity
            input_quantity = self.validate_number(new_quantity_str, "Quantity", allow_zero=True, allow_negative=False)
            if input_quantity is None:
                return

            # Convert quantity if needed
            if requires_conv:
                new_quantity = convert_to_system(item_id, input_quantity)
                conversion_msg = f" ({input_quantity:.1f} {input_unit}s = {new_quantity:.1f} {output_unit}s)"
            else:
                new_quantity = input_quantity
                conversion_msg = ""

            new_cost_price = self.validate_number(new_cost_price, "Cost price", allow_zero=True)
            if new_cost_price is None:
                return

            new_sell_price = self.validate_number(new_sell_price, "Sell price", allow_zero=True)
            if new_sell_price is None:
                return

            # Get price_locked, allow_negative, reorder_level, division values
            new_price_locked = price_locked_var.get()
            new_allow_negative = allow_negative_var.get()
            new_reorder_level = self.validate_number(entry_reorder_level.get().strip(), "Reorder Level", allow_zero=True)
            if new_reorder_level is None:
                new_reorder_level = 0
            new_division = division_var.get()

            # Update the item
            self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id,
                                  [COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE, COL_MEASURE, COL_CATEGORY, COL_PRICE_LOCKED, COL_ALLOW_NEGATIVE, COL_REORDER_LEVEL, COL_DIVISION]] = \
                [new_name, new_quantity, new_cost_price, new_sell_price, new_measure, new_category, new_price_locked, new_allow_negative, new_reorder_level, new_division]

            if InventoryDataManager.save_inventory(self.inventory_df):
                self.load_stock_into_tree()
                self.update_dashboard_stats()
                top.destroy()
                messagebox.showinfo("Success", f"Item '{item_id}' updated to {new_quantity:.1f}{conversion_msg}.")

        top = tk.Toplevel(self.root)
        top.title("Update Stock Item")
        top.geometry("450x560")
        top.transient(self.root)
        top.grab_set()

        # macOS-specific: Bring dialog to front
        top.lift()
        top.attributes('-topmost', True)
        top.after_idle(top.attributes, '-topmost', False)

        # Center the window
        top.update_idletasks()
        x = (top.winfo_screenwidth() - top.winfo_width()) // 2
        y = (top.winfo_screenheight() - top.winfo_height()) // 2
        top.geometry(f'+{x}+{y}')

        main_frame = tk.Frame(top, padx=20, pady=20)
        main_frame.pack(fill='both', expand=True)

        tk.Label(main_frame, text=f"Item ID: {item_id}", font=('Arial', 10, 'bold')).grid(row=0, column=0, columnspan=2, pady=10)

        # Text entry fields
        # Use input quantity for items requiring conversion
        if requires_conv:
            quantity_label = f"Quantity ({input_unit}s):"
            quantity_value = f"{current_input_qty:.1f}"
        else:
            quantity_label = "Quantity:"
            quantity_value = f"{current_system_qty:.1f}"

        fields = [
            ("Item Name:", current_name, 'item_name'),
            (quantity_label, quantity_value, 'quantity'),
            ("Cost Price:", item_values[3].replace('£', ''), 'cost_price'),
            ("Sell Price:", item_values[4].replace('£', ''), 'sell_price'),
        ]

        entries = {}
        for i, (label, value, key) in enumerate(fields, 1):
            tk.Label(main_frame, text=label).grid(row=i, column=0, padx=5, pady=8, sticky="e")
            entry = tk.Entry(main_frame, width=30)
            entry.insert(0, value)
            entry.grid(row=i, column=1, padx=5, pady=8, sticky="ew")
            entries[key] = entry

        # Show conversion info if applicable (below the quantity entry)
        if requires_conv:
            conversion_info = tk.Label(main_frame, text=f"1 {input_unit} = {conversion_factor} {output_unit}s", font=('Arial', 9, 'italic'), fg='gray')
            conversion_info.grid(row=3, column=1, padx=5, pady=2, sticky="w")

        # Measure dropdown
        tk.Label(main_frame, text="Measure:").grid(row=5, column=0, padx=5, pady=8, sticky="e")
        measure_var = tk.StringVar(value=current_measure if current_measure in MEASURE_OPTIONS else MEASURE_OPTIONS[0])
        measure_dropdown = ttk.Combobox(main_frame, textvariable=measure_var, values=MEASURE_OPTIONS, width=28, state="readonly")
        measure_dropdown.grid(row=5, column=1, padx=5, pady=8, sticky="ew")

        # Category dropdown
        tk.Label(main_frame, text="Category:").grid(row=6, column=0, padx=5, pady=8, sticky="e")
        category_var = tk.StringVar(value=current_category if current_category in CATEGORY_OPTIONS else CATEGORY_OPTIONS[0])
        category_dropdown = ttk.Combobox(main_frame, textvariable=category_var, values=CATEGORY_OPTIONS, width=28, state="readonly")
        category_dropdown.grid(row=6, column=1, padx=5, pady=8, sticky="ew")

        # Price Locked checkbox
        price_locked_var = tk.BooleanVar(value=current_price_locked)
        price_locked_checkbox = tk.Checkbutton(main_frame, text="Lock Price (prevent CSV uploads from changing buy/cost prices)",
                                               variable=price_locked_var, wraplength=300, justify='left')
        price_locked_checkbox.grid(row=7, column=0, columnspan=2, padx=5, pady=4, sticky="w")

        # Allow Negative Stock checkbox
        current_allow_negative = InventoryDataManager.get_item_value_safe(self.inventory_df, item_id, COL_ALLOW_NEGATIVE, default=False)
        allow_negative_var = tk.BooleanVar(value=bool(current_allow_negative))
        allow_negative_checkbox = tk.Checkbutton(main_frame, text="Allow Negative Stock",
                                                   variable=allow_negative_var, wraplength=300, justify='left')
        allow_negative_checkbox.grid(row=8, column=0, columnspan=2, padx=5, pady=4, sticky="w")

        # Reorder Level
        current_reorder_level = InventoryDataManager.get_item_value_safe(self.inventory_df, item_id, COL_REORDER_LEVEL, default=0)
        tk.Label(main_frame, text="Reorder Level:").grid(row=9, column=0, padx=5, pady=8, sticky="e")
        entry_reorder_level = tk.Entry(main_frame, width=30)
        entry_reorder_level.insert(0, str(current_reorder_level))
        entry_reorder_level.grid(row=9, column=1, padx=5, pady=8, sticky="ew")

        # Division dropdown
        current_division = InventoryDataManager.get_item_value_safe(self.inventory_df, item_id, COL_DIVISION, default='')
        tk.Label(main_frame, text="Division:").grid(row=10, column=0, padx=5, pady=8, sticky="e")
        division_var = tk.StringVar(value=current_division if current_division in DIVISION_OPTIONS else DIVISION_OPTIONS[-1])
        division_dropdown = ttk.Combobox(main_frame, textvariable=division_var, values=DIVISION_OPTIONS, width=28, state="readonly")
        division_dropdown.grid(row=10, column=1, padx=5, pady=8, sticky="ew")

        entry_name = entries['item_name']
        entry_quantity = entries['quantity']
        entry_cost_price = entries['cost_price']
        entry_sell_price = entries['sell_price']

        btn_frame = tk.Frame(main_frame)
        btn_frame.grid(row=11, column=0, columnspan=2, pady=20)

        tk.Button(btn_frame, text="Save Changes", command=save_update, width=15).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Cancel", command=top.destroy, width=15).pack(side=tk.LEFT, padx=10)

        main_frame.grid_columnconfigure(1, weight=1)

        # Force redraw so ttk.Combobox is visible immediately on macOS
        top.update_idletasks()

    def delete_stock_item(self):
        """Delete a stock item from the inventory based on selection."""
        selected_item = self.stock_tree.selection()
        if not selected_item:
            messagebox.showerror("Error", "No item selected. Please select an item from the list.")
            return

        item_values = self.stock_tree.item(selected_item, 'values')
        item_id = item_values[0]
        item_name = item_values[1]

        if messagebox.askyesno("Confirm Delete", f"Are you sure you want to delete item '{item_name}' (ID: {item_id})?\n\nThis action cannot be undone."):
            self.inventory_df = self.inventory_df[self.inventory_df[COL_ITEM_ID] != item_id]
            if InventoryDataManager.save_inventory(self.inventory_df):
                self.load_stock_into_tree()
                self.update_dashboard_stats()
                messagebox.showinfo("Success", f"Item '{item_name}' deleted successfully.")

    def add_delivery(self):
        """Add a delivery transaction with supplier selection."""
        self.clear_main_menu()

        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)

        tk.Label(header_frame, text="Add Delivery", font=('Arial', 16, 'bold')).pack(expand=True)

        frame = tk.Frame(self.main_menu)
        frame.pack(pady=10, padx=20)

        # Supplier selection
        tk.Label(frame, text="Supplier:").grid(row=0, column=0, padx=5, pady=8, sticky="e")
        supplier_var = tk.StringVar(value="Booker")
        supplier_dropdown = ttk.Combobox(frame, textvariable=supplier_var,
                                          values=["Booker", "Tennents", "Belhaven"],
                                          width=40, state="readonly")
        supplier_dropdown.grid(row=0, column=1, padx=5, pady=8)
        supplier_dropdown.set("Select supplier...")

        def proceed_with_delivery():
            selected_supplier = supplier_var.get()
            if selected_supplier == "Select supplier...":
                messagebox.showerror("Error", "Please select a supplier.")
                return
            # Store supplier and proceed to multi-item delivery
            self.current_delivery_supplier = selected_supplier
            self.process_delivery_multi_item()

        # Recent Deliveries
        history_frame = tk.LabelFrame(self.main_menu, text="Recent Deliveries", font=('Arial', 10, 'bold'))
        history_frame.pack(fill='x', padx=20, pady=(10, 0))

        try:
            self.refresh_data()
            if not self.log_df.empty:
                delivery_log = self.log_df[self.log_df[COL_ACTION] == ACTION_DELIVERY].copy()
                if not delivery_log.empty:
                    # Group by timestamp (first 16 chars for minute-level) and supplier
                    delivery_log['ts_group'] = delivery_log[COL_TIMESTAMP].str[:16]
                    grouped = delivery_log.groupby(['ts_group', COL_SUPPLIER]).agg({
                        COL_ITEM_ID: 'nunique',
                        COL_QUANTITY: 'sum'
                    }).reset_index()
                    grouped.columns = ['timestamp', 'supplier', 'items', 'total_qty']
                    grouped = grouped.sort_values('timestamp', ascending=False).head(10)

                    history_container = tk.Frame(history_frame)
                    history_container.pack(fill='x', padx=10, pady=5)

                    for _, row in grouped.iterrows():
                        ts = row['timestamp'] if pd.notna(row['timestamp']) else 'N/A'
                        supplier = row['supplier'] if pd.notna(row['supplier']) else 'Unknown'
                        items = int(row['items'])
                        total_qty = row['total_qty']
                        tk.Label(history_container,
                                 text=f"  {ts}  — {supplier}: {items} items, +{total_qty:.1f} units",
                                 font=('Arial', 9), anchor='w').pack(fill='x', padx=5)
                else:
                    tk.Label(history_frame, text="  No deliveries yet", font=('Arial', 9), fg='gray').pack(padx=5, pady=5)
            else:
                tk.Label(history_frame, text="  No deliveries yet", font=('Arial', 9), fg='gray').pack(padx=5, pady=5)
        except Exception:
            tk.Label(history_frame, text="  Unable to load recent deliveries", font=('Arial', 9), fg='gray').pack(padx=5, pady=5)

        # Buttons
        btn_frame = tk.Frame(frame)
        btn_frame.grid(row=1, column=0, columnspan=2, pady=20)

        tk.Button(btn_frame, text="Proceed", command=proceed_with_delivery, width=15).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Back", command=self.create_main_menu, width=15).pack(side=tk.LEFT, padx=10)

        # Force redraw so ttk.Combobox is visible immediately on macOS
        self.root.update_idletasks()

    def process_delivery_multi_item(self):
        """Process a delivery with multiple items."""
        self.clear_main_menu()

        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)

        supplier_name = getattr(self, 'current_delivery_supplier', 'Unknown')
        tk.Label(header_frame, text=f"Add Delivery - {supplier_name}", font=('Arial', 16, 'bold')).pack(expand=True)

        # Delivery date
        date_frame = tk.Frame(header_frame)
        date_frame.pack(pady=5)
        tk.Label(date_frame, text="Delivery Date:", font=('Arial', 10, 'bold')).pack(side=tk.LEFT, padx=5)
        delivery_date_var = tk.StringVar(value=datetime.now().strftime("%d/%m/%Y"))
        delivery_date_entry = tk.Entry(date_frame, textvariable=delivery_date_var, width=12, font=('Arial', 10))
        delivery_date_entry.pack(side=tk.LEFT, padx=5)
        tk.Button(date_frame, text="📅", command=lambda: self.show_calendar(delivery_date_var, self.root), font=('Arial', 10)).pack(side=tk.LEFT, padx=2)

        # Main container
        main_frame = tk.Frame(self.main_menu)
        main_frame.pack(pady=10, padx=20, fill='both', expand=True)

        # Left side - Item entry
        entry_frame = tk.LabelFrame(main_frame, text="Add Items to Delivery", font=('Arial', 10, 'bold'))
        entry_frame.pack(side=tk.LEFT, fill='both', expand=True, padx=(0, 10))

        # Item selection
        tk.Label(entry_frame, text="Item:").grid(row=0, column=0, padx=5, pady=8, sticky="e")

        # Create list of items for dropdown
        self.refresh_data()
        full_item_list = [f"{row[COL_ITEM_ID]} - {row[COL_ITEM_NAME]}" for _, row in self.inventory_df.iterrows()]

        if not full_item_list:
            messagebox.showerror("Error", "No items in inventory. Please add items first.")
            self.create_main_menu()
            return

        # Search bar to filter items
        search_var = tk.StringVar()
        search_entry = tk.Entry(entry_frame, textvariable=search_var, width=15, bg='#2c2c2c', fg='white')
        search_entry.grid(row=0, column=1, padx=(5, 0), pady=8, sticky="w")
        search_entry.insert(0, "Type to search...")
        search_entry.config(fg='gray')

        def on_search_focus_in(event):
            if search_var.get() == "Type to search...":
                search_entry.delete(0, tk.END)
                search_entry.config(fg='white')

        def on_search_focus_out(event):
            if not search_var.get().strip():
                search_entry.insert(0, "Type to search...")
                search_entry.config(fg='gray')

        def on_search_change(*args):
            query = search_var.get().lower()
            if query == "type to search..." or not query:
                filtered = full_item_list
            else:
                filtered = [item for item in full_item_list if query in item.lower()]
            item_dropdown['values'] = filtered

        search_entry.bind('<FocusIn>', on_search_focus_in)
        search_entry.bind('<FocusOut>', on_search_focus_out)
        search_var.trace_add('write', on_search_change)

        item_var = tk.StringVar()
        item_dropdown = ttk.Combobox(entry_frame, textvariable=item_var, values=full_item_list, width=35, state="readonly")
        item_dropdown.grid(row=1, column=0, columnspan=2, padx=5, pady=8)
        item_dropdown.set("Select an item...")

        # Quantity entry (label updated dynamically based on selected item)
        qty_label = tk.Label(entry_frame, text="Quantity:")
        qty_label.grid(row=2, column=0, padx=5, pady=8, sticky="e")
        entry_quantity = tk.Entry(entry_frame, width=15)
        entry_quantity.grid(row=2, column=1, padx=5, pady=8, sticky="w")

        # Cost Price entry
        cost_label = tk.Label(entry_frame, text="Cost Price (£):")
        cost_label.grid(row=3, column=0, padx=5, pady=8, sticky="e")
        entry_cost_price = tk.Entry(entry_frame, width=15)
        entry_cost_price.grid(row=3, column=1, padx=5, pady=8, sticky="w")

        # GP% label
        gp_label = tk.Label(entry_frame, text="GP: -", font=('Arial', 9, 'bold'))
        gp_label.grid(row=4, column=1, padx=5, pady=2, sticky="w")

        # Current stock label
        stock_label = tk.Label(entry_frame, text="Current stock: -", font=('Arial', 9), fg='gray')
        stock_label.grid(row=5, column=1, padx=5, pady=2, sticky="w")

        # Conversion info label
        conversion_label = tk.Label(entry_frame, text="", font=('Arial', 9), fg='gray')
        conversion_label.grid(row=7, column=1, padx=5, pady=0, sticky="w")

        # Track currently selected item for conversion
        selected_item_id = [None]
        selected_sell_price = [0.0]
        selected_factor = [1.0]
        selected_has_conversion = [False]
        last_delivery_cost_per_unit = [0.0]  # Per-unit cost for deviation warning

        def update_gp_label(event=None):
            """Recalculate GP% when cost price changes."""
            try:
                cost = float(entry_cost_price.get().strip())
                # Convert pack cost to per-unit cost for GP calculation
                if selected_has_conversion[0] and selected_factor[0] > 0:
                    cost = cost / selected_factor[0]
                sell = selected_sell_price[0]
                if sell > 0:
                    gp_pct = ((sell - cost) / sell) * 100
                    color = '#ff4444' if gp_pct < 60 else '#44cc44'
                    gp_label.config(text=f"GP: {gp_pct:.1f}%", fg=color)
                else:
                    gp_label.config(text="GP: -", fg='gray')
            except:
                gp_label.config(text="GP: -", fg='gray')

        def on_cost_change(event=None):
            """Warn if cost price deviates >10% from last delivery cost."""
            if last_delivery_cost_per_unit[0] <= 0:
                return
            try:
                entered_cost = float(entry_cost_price.get().strip())
                if selected_has_conversion[0] and selected_factor[0] > 0:
                    # User enters pack cost; compare to per-unit cost * factor
                    comparison_cost = last_delivery_cost_per_unit[0] * selected_factor[0]
                    label = "pack"
                else:
                    # User enters per-unit cost directly
                    comparison_cost = last_delivery_cost_per_unit[0]
                    label = "per-unit"
                deviation = abs(entered_cost - comparison_cost) / comparison_cost
                if deviation > 0.10:
                    messagebox.showwarning("Cost Deviation Warning",
                        f"Entered {label} cost (£{entered_cost:.2f}) differs by {deviation*100:.0f}% from the last delivery {label} cost (£{comparison_cost:.2f}).\nPlease confirm this is correct.")
            except ValueError:
                pass

        entry_cost_price.bind('<KeyRelease>', update_gp_label)
        entry_cost_price.bind('<FocusOut>', on_cost_change)

        def on_item_select(event=None):
            """Update stock label and quantity label when item is selected."""
            selected = item_var.get()
            if selected and selected != "Select an item...":
                item_id = selected.split(" - ")[0]
                selected_item_id[0] = item_id
                try:
                    from conversions import requires_conversion, convert_to_input, get_input_label, format_stock_display, get_conversion
                    qty = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY].values[0]
                    cost_price = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_COST_PRICE].values[0]
                    sell_price = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_SELL_PRICE].values[0]
                    selected_sell_price[0] = sell_price

                    # Look up most recent delivery cost for this item
                    item_deliveries = self.log_df[(self.log_df[COL_ITEM_ID] == item_id) & (self.log_df[COL_ACTION] == ACTION_DELIVERY)]
                    if not item_deliveries.empty:
                        recent = item_deliveries.sort_values(COL_TIMESTAMP, ascending=False).iloc[0]
                        last_delivery_cost_per_unit[0] = recent[COL_COST_PRICE]
                    else:
                        last_delivery_cost_per_unit[0] = cost_price

                    if requires_conversion(item_id):
                        display = format_stock_display(item_id, qty)
                        input_unit = get_input_label(item_id)
                        conversion = get_conversion(item_id)
                        factor = conversion[1] if conversion else 1
                        output_unit = conversion[2] if conversion else "units"
                        stock_label.config(text=f"Current stock: {display}")
                        qty_label.config(text=f"Quantity ({input_unit}s):")
                        conversion_label.config(text=f"1 {input_unit} = {factor} {output_unit}s")
                        # Show pack cost
                        selected_factor[0] = factor
                        selected_has_conversion[0] = True
                        cost_label.config(text=f"Pack Cost Price (£):")
                        entry_cost_price.delete(0, tk.END)
                        entry_cost_price.insert(0, f"{last_delivery_cost_per_unit[0] * factor:.2f}")
                    else:
                        stock_label.config(text=f"Current stock: {qty:.1f}")
                        qty_label.config(text="Quantity:")
                        conversion_label.config(text="")
                        selected_factor[0] = 1.0
                        selected_has_conversion[0] = False
                        cost_label.config(text="Cost Price (£):")
                        entry_cost_price.delete(0, tk.END)
                        entry_cost_price.insert(0, f"{last_delivery_cost_per_unit[0]:.2f}")
                    update_gp_label()
                except:
                    stock_label.config(text="Current stock: -")
                    qty_label.config(text="Quantity:")
                    conversion_label.config(text="")
                    gp_label.config(text="GP: -", fg='gray')
                    entry_cost_price.delete(0, tk.END)
            else:
                selected_item_id[0] = None
                selected_sell_price[0] = 0.0
                selected_factor[0] = 1.0
                selected_has_conversion[0] = False
                last_delivery_cost_per_unit[0] = 0.0
                stock_label.config(text="Current stock: -")
                qty_label.config(text="Quantity:")
                conversion_label.config(text="")
                gp_label.config(text="GP: -", fg='gray')
                entry_cost_price.delete(0, tk.END)

        item_dropdown.bind("<<ComboboxSelected>>", on_item_select)

        # List to store delivery items
        delivery_items = []

        # Right side - Items list
        list_frame = tk.LabelFrame(main_frame, text="Items in this Delivery", font=('Arial', 10, 'bold'))
        list_frame.pack(side=tk.RIGHT, fill='both', expand=True)

        # Treeview for items
        columns = ('item_id', 'item_name', 'quantity', 'new_stock', 'cost_price')
        items_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=10)
        items_tree.heading('item_id', text='Item ID')
        items_tree.heading('item_name', text='Name')
        items_tree.heading('quantity', text='Qty Added')
        items_tree.heading('new_stock', text='New Stock Level')
        items_tree.heading('cost_price', text='Cost Price')
        items_tree.column('item_id', width=80)
        items_tree.column('item_name', width=120)
        items_tree.column('quantity', width=70)
        items_tree.column('new_stock', width=90)
        items_tree.column('cost_price', width=80)
        items_tree.pack(fill='both', expand=True, padx=5, pady=5)

        # Scrollbar for treeview
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=items_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        items_tree.configure(yscrollcommand=scrollbar.set)

        # Total delivery cost at cost
        total_frame = tk.Frame(list_frame)
        total_frame.pack(fill='x', padx=5, pady=(0, 8))
        tk.Label(total_frame, text="Total Delivery Cost:", font=('Arial', 14, 'bold'), fg='white').pack(side=tk.LEFT)
        total_cost_label = tk.Label(total_frame, text="£0.00", font=('Arial', 14, 'bold'), fg='white')
        total_cost_label.pack(side=tk.RIGHT)

        def add_item_to_delivery():
            """Add an item to the delivery list."""
            selected = item_var.get()
            if selected == "Select an item..." or not selected:
                messagebox.showerror("Error", "Please select an item.")
                return

            item_id = selected.split(" - ")[0]
            quantity_str = entry_quantity.get().strip()

            if not quantity_str:
                messagebox.showerror("Error", "Quantity is required.")
                return

            # Validate quantity
            try:
                input_quantity = float(quantity_str)
                if input_quantity <= 0:
                    messagebox.showerror("Error", "Quantity must be greater than zero.")
                    return
            except ValueError:
                messagebox.showerror("Error", "Quantity must be a valid number.")
                return

            # Convert input quantity to system units if needed (e.g. bottles -> measures)
            from conversions import requires_conversion, convert_to_system, get_conversion, get_input_label, format_stock_display
            if requires_conversion(item_id):
                quantity = convert_to_system(item_id, input_quantity)
                conversion = get_conversion(item_id)
                input_unit = conversion[0] if conversion else "units"
                output_unit = conversion[2] if conversion else "units"
                conversion_msg = f" ({input_quantity:.1f} {input_unit}s = {quantity:.1f} {output_unit}s)"
            else:
                quantity = input_quantity
                conversion_msg = ""

            # Get cost price (entered as pack cost if conversion applies)
            cost_price_str = entry_cost_price.get().strip()
            if not cost_price_str:
                messagebox.showerror("Error", "Cost price is required.")
                return
            try:
                pack_cost = float(cost_price_str)
                if pack_cost < 0:
                    messagebox.showerror("Error", "Cost price cannot be negative.")
                    return
            except ValueError:
                messagebox.showerror("Error", "Cost price must be a valid number.")
                return

            # Convert pack cost to per-unit cost for storage
            from conversions import requires_conversion, get_conversion
            conv_factor = 1.0
            if requires_conversion(item_id):
                conv = get_conversion(item_id)
                if conv:
                    conv_factor = conv[1]
            cost_price = pack_cost / conv_factor if conv_factor > 0 else pack_cost

            # Get item details
            item_row = self.inventory_df[self.inventory_df[COL_ITEM_ID] == item_id].iloc[0]
            item_name = item_row[COL_ITEM_NAME]
            current_qty = item_row[COL_QUANTITY]
            new_qty = current_qty + quantity
            sell_price = item_row[COL_SELL_PRICE]

            # GP warning (using per-unit cost)
            gp_pct = ((sell_price - cost_price) / sell_price * 100) if sell_price > 0 else 0
            if gp_pct < 60:
                if not messagebox.askyesno("Low GP Warning", f"The GP for {item_name} is {gp_pct:.1f}% (below 60%).\nAre you sure you want to add this item?"):
                    return

            # Line total cost = cost entered × quantity entered by user
            line_total_cost = pack_cost * input_quantity

            # Check if item already in delivery
            for i, (existing_id, _, existing_qty, _, existing_price, existing_line_total) in enumerate(delivery_items):
                if existing_id == item_id:
                    new_total_qty = existing_qty + quantity
                    new_total_line_cost = existing_line_total + line_total_cost
                    new_new_qty = current_qty + new_total_qty
                    if messagebox.askyesno("Item Already Added", f"'{item_name}' is already in this delivery.\nDo you want to add {quantity:.1f} more to the existing {existing_qty:.1f}?{conversion_msg}"):
                        delivery_items[i] = (item_id, item_name, new_total_qty, new_new_qty, cost_price, new_total_line_cost)
                        refresh_items_list()
                        # Clear inputs
                        item_dropdown.set("Select an item...")
                        entry_quantity.delete(0, tk.END)
                        entry_cost_price.delete(0, tk.END)
                        gp_label.config(text="GP: -", fg='gray')
                        stock_label.config(text="Current stock: -")
                        conversion_label.config(text="")
                    return

            # Add to delivery items (include line total cost for total)
            delivery_items.append((item_id, item_name, quantity, new_qty, cost_price, line_total_cost))

            # Refresh treeview and total cost
            refresh_items_list()

            # Clear inputs
            item_dropdown.set("Select an item...")
            entry_quantity.delete(0, tk.END)
            entry_cost_price.delete(0, tk.END)
            gp_label.config(text="GP: -", fg='gray')
            stock_label.config(text="Current stock: -")
            conversion_label.config(text="")

        def refresh_items_list():
            """Refresh the items treeview and total cost."""
            from conversions import requires_conversion, format_stock_display, get_conversion
            for item in items_tree.get_children():
                items_tree.delete(item)
            total_cost = 0.0
            for item_id, item_name, quantity, new_qty, cost_price, line_total_cost in delivery_items:
                new_qty_display = format_stock_display(item_id, new_qty) if requires_conversion(item_id) else f"{new_qty:.1f}"
                # Show pack cost if applicable
                display_cost = cost_price
                if requires_conversion(item_id):
                    conv = get_conversion(item_id)
                    if conv:
                        display_cost = cost_price * conv[1]
                items_tree.insert('', tk.END, values=(item_id, item_name, f"{quantity:.1f}", new_qty_display, f"£{display_cost:.2f}"))
                total_cost += line_total_cost
            total_cost_label.config(text=f"£{total_cost:.2f}")

        def remove_selected_item():
            """Remove the selected item from the delivery."""
            selected = items_tree.selection()
            if not selected:
                messagebox.showerror("Error", "Please select an item to remove.")
                return

            item_values = items_tree.item(selected[0], 'values')
            item_id = item_values[0]

            # Remove from delivery_items
            for i, (del_id, _, _, _, _, _) in enumerate(delivery_items):
                if del_id == item_id:
                    delivery_items.pop(i)
                    break

            items_tree.delete(selected[0])
            refresh_items_list()

        def save_delivery():
            """Save all items in the delivery."""
            if not delivery_items:
                messagebox.showerror("Error", "No items to save. Please add at least one item.")
                return

            try:
                # Reload inventory to ensure we have latest data
                self.refresh_data()

                delivery_date = delivery_date_var.get().strip()
                try:
                    parsed_date = datetime.strptime(delivery_date, "%d/%m/%Y")
                except ValueError:
                    messagebox.showerror("Error", "Invalid date format. Use DD/MM/YYYY.")
                    return

                timestamp = f"{parsed_date.strftime('%Y-%m-%d')} {datetime.now().strftime('%H:%M:%S')}"
                supplier = getattr(self, 'current_delivery_supplier', '')

                log_entries = []

                for item_id, item_name, quantity, _, cost_price, pack_cost in delivery_items:
                    # Update inventory quantity and cost price
                    self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] += quantity
                    self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_COST_PRICE] = cost_price

                    sell_price = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_SELL_PRICE].values[0]

                    # Create log entry
                    log_entries.append([item_id, ACTION_DELIVERY, quantity, timestamp, cost_price, sell_price, supplier, "", ""])

                # Add all log entries
                if log_entries:
                    new_log_df = pd.DataFrame(log_entries, columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON])
                    self.log_df = pd.concat([self.log_df, new_log_df], ignore_index=True)

                # Save both files
                if InventoryDataManager.save_inventory(self.inventory_df) and InventoryDataManager.save_log(self.log_df):
                    from conversions import requires_conversion, get_conversion
                    success_msg = f"Delivery from {supplier} saved successfully!\n\n"
                    success_msg += f"Items added: {len(delivery_items)}\n"
                    lines = []
                    delivery_total = 0.0
                    for item_id, name, qty, _, price, line_total_cost in delivery_items:
                        display_price = price
                        if requires_conversion(item_id):
                            conv = get_conversion(item_id)
                            if conv:
                                display_price = price * conv[1]
                        lines.append(f"  • {name}: +{qty:.1f} @ £{display_price:.2f}")
                        delivery_total += line_total_cost
                    lines.append(f"\nTotal delivery cost: £{delivery_total:.2f}")
                    success_msg += "\n".join(lines)

                    messagebox.showinfo("Success", success_msg)

                    # Clear supplier
                    if hasattr(self, 'current_delivery_supplier'):
                        delattr(self, 'current_delivery_supplier')

                    self.update_dashboard_stats()
                    self.create_main_menu()
                else:
                    messagebox.showerror("Error", "Failed to save delivery. Data may be inconsistent.")

            except Exception as e:
                messagebox.showerror("Error", f"Delivery failed: {e}")

        def cancel_delivery():
            """Cancel the delivery and return to main menu."""
            if delivery_items:
                if not messagebox.askyesno("Cancel Delivery", f"You have {len(delivery_items)} items in this delivery.\nAre you sure you want to cancel?"):
                    return

            if hasattr(self, 'current_delivery_supplier'):
                delattr(self, 'current_delivery_supplier')
            self.create_main_menu()

        # Buttons for entry frame
        btn_frame = tk.Frame(entry_frame)
        btn_frame.grid(row=8, column=0, columnspan=2, pady=15)

        tk.Button(btn_frame, text="Add to Delivery", command=add_item_to_delivery, width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Remove Selected", command=remove_selected_item, width=15).pack(side=tk.LEFT, padx=5)

        # Bottom buttons
        bottom_frame = tk.Frame(self.main_menu)
        bottom_frame.pack(fill='x', padx=20, pady=20)

        tk.Button(bottom_frame, text="Save Delivery", command=save_delivery, width=20).pack(side=tk.LEFT, padx=5)
        tk.Button(bottom_frame, text="Cancel", command=cancel_delivery, width=15).pack(side=tk.LEFT, padx=20)

        # Force redraw so ttk.Combobox is visible immediately on macOS
        self.root.update_idletasks()

    def add_sales(self):
        """Add sales with option to upload weekly report."""
        self.clear_main_menu()

        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)

        tk.Label(header_frame, text="Add Sales", font=('Arial', 16, 'bold')).pack(expand=True)

        # Main frame
        main_frame = tk.Frame(self.main_menu)
        main_frame.pack(pady=10, padx=20, fill='both', expand=True)

        # Upload Sales Report Section
        upload_frame = tk.LabelFrame(main_frame, text="Upload Weekly Sales Report", font=('Arial', 10, 'bold'))
        upload_frame.pack(fill='x', pady=10)

        tk.Label(upload_frame, text="Upload CSV file with sales data to auto-populate transactions.",
                wraplength=500, justify='left').pack(pady=5)
        tk.Label(upload_frame, text="Expected format: Rank, Product, Member Qty, Member Sales, Non Member Qty, Non Member Sales, Qty, Sales",
                wraplength=500, justify='left', font=('Arial', 8)).pack(pady=2)

        btn_frame = tk.Frame(upload_frame)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="Select Sales Report CSV", command=self.upload_sales_report, width=25).pack()

        # Upload history
        history_frame = tk.LabelFrame(upload_frame, text="Recent Uploads", font=('Arial', 9, 'bold'))
        history_frame.pack(fill='x', padx=10, pady=5)
        if not self.log_df.empty and 'date_range' in self.log_df.columns:
            sales_uploads = self.log_df[self.log_df[COL_ACTION] == ACTION_SALES]
            if not sales_uploads.empty:
                # Aggregate per upload batch
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
                    for _, row in recent.iterrows():
                        date_range = row['date_range'] if pd.notna(row['date_range']) else 'N/A'
                        ts = row['timestamp'][:16] if pd.notna(row['timestamp']) else 'N/A'
                        qty = row['total_qty']
                        rev = row['total_revenue']

                        line1 = f"{date_range}  (uploaded {ts}, {int(row['items'])} items)"
                        line2_parts = [f"Qty: {qty:.1f}", f"Revenue: £{rev:.2f}"]
                        if has_member:
                            mem_qty = row.get(COL_MEMBER_QTY, 0)
                            non_mem_qty = row.get(COL_NON_MEMBER_QTY, 0)
                            if mem_qty > 0 or non_mem_qty > 0:
                                line2_parts.append(f"Member: {mem_qty:.1f}  Non-Member: {non_mem_qty:.1f}")
                        line2 = "  " + "  |  ".join(line2_parts)

                        tk.Label(history_frame, text=line1, font=('Arial', 9, 'bold'), anchor='w').pack(fill='x', padx=5)
                        tk.Label(history_frame, text=line2, font=('Arial', 8), anchor='w', fg='gray').pack(fill='x', padx=5)
                else:
                    tk.Label(history_frame, text="  No uploads yet", font=('Arial', 9), fg='gray').pack(padx=5, pady=2)
            else:
                tk.Label(history_frame, text="  No uploads yet", font=('Arial', 9), fg='gray').pack(padx=5, pady=2)
        else:
            tk.Label(history_frame, text="  No uploads yet", font=('Arial', 9), fg='gray').pack(padx=5, pady=2)

        # Manual Entry Section
        manual_frame = tk.LabelFrame(main_frame, text="Manual Entry", font=('Arial', 10, 'bold'))
        manual_frame.pack(fill='both', expand=True, pady=10)

        tk.Label(manual_frame, text="Or add individual sales transaction:",
                wraplength=500, justify='left').pack(pady=5)

        tk.Button(manual_frame, text="Add Single Sale", command=lambda: self.process_transaction(ACTION_SALES), width=25).pack(pady=10)

        # Back button
        back_frame = tk.Frame(self.main_menu)
        back_frame.pack(fill='x', padx=20, pady=20)

        tk.Button(back_frame, text="Back", command=self.create_main_menu, width=25).pack()

    def add_wastage(self):
        """Add wastage transactions (multi-item like delivery)."""
        self.process_multi_transaction(ACTION_WASTAGE)

    def add_complimentary(self):
        """Add complimentary transactions (multi-item like delivery)."""
        self.process_multi_transaction(ACTION_COMPLIMENTARY)

    def open_tabs_menu(self):
        """Display the Open Tabs menu with options to create or view tabs."""
        self.clear_main_menu()

        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
        tk.Label(header_frame, text="Open Tabs", font=('Arial', 16, 'bold')).pack(expand=True)

        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=20)

        tk.Button(btn_frame, text="Create New Tab", command=self.create_open_tab_dialog, width=25).pack(pady=5)
        tk.Button(btn_frame, text="View / Close Tabs", command=self.view_open_tabs, width=25).pack(pady=5)
        tk.Button(btn_frame, text="Back", command=self.create_main_menu, width=25).pack(pady=5)

    def create_open_tab_dialog(self):
        """Dialog to create a new open tab (multi-item, customer name)."""
        self.clear_main_menu()

        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
        tk.Label(header_frame, text="Create Open Tab", font=('Arial', 16, 'bold')).pack(expand=True)

        main_frame = tk.Frame(self.main_menu)
        main_frame.pack(pady=10, padx=20, fill='both', expand=True)

        # Left side - Item entry
        entry_frame = tk.LabelFrame(main_frame, text="Add Items", font=('Arial', 10, 'bold'))
        entry_frame.pack(side=tk.LEFT, fill='both', expand=True, padx=(0, 10))

        # Customer name
        tk.Label(entry_frame, text="Customer Name:").grid(row=0, column=0, padx=5, pady=8, sticky="e")
        customer_entry = tk.Entry(entry_frame, width=35)
        customer_entry.grid(row=0, column=1, padx=5, pady=8, sticky="w")

        # Search bar
        self.refresh_data()
        full_item_list = [f"{row[COL_ITEM_ID]} - {row[COL_ITEM_NAME]}" for _, row in self.inventory_df.iterrows()]
        if not full_item_list:
            messagebox.showerror("Error", "No items in inventory. Please add items first.")
            self.create_main_menu()
            return

        tk.Label(entry_frame, text="Search:").grid(row=1, column=0, padx=5, pady=8, sticky="e")
        search_var = tk.StringVar()
        search_entry = tk.Entry(entry_frame, textvariable=search_var, width=15, bg='#2c2c2c', fg='white')
        search_entry.grid(row=1, column=1, padx=(5, 0), pady=8, sticky="w")
        search_entry.insert(0, "Type to search...")
        search_entry.config(fg='gray')

        def on_search_focus_in(event):
            if search_var.get() == "Type to search...":
                search_entry.delete(0, tk.END)
                search_entry.config(fg='white')

        def on_search_focus_out(event):
            if not search_var.get().strip():
                search_entry.insert(0, "Type to search...")
                search_entry.config(fg='gray')

        def on_search_change(*args):
            query = search_var.get().lower()
            if query == "type to search..." or not query:
                filtered = full_item_list
            else:
                filtered = [item for item in full_item_list if query in item.lower()]
            item_dropdown['values'] = filtered

        search_entry.bind('<FocusIn>', on_search_focus_in)
        search_entry.bind('<FocusOut>', on_search_focus_out)
        search_var.trace_add('write', on_search_change)

        item_var = tk.StringVar()
        item_dropdown = ttk.Combobox(entry_frame, textvariable=item_var, values=full_item_list, width=35, state="readonly")
        item_dropdown.grid(row=2, column=0, columnspan=2, padx=5, pady=8)
        item_dropdown.set("Select an item...")

        qty_label = tk.Label(entry_frame, text="Quantity:")
        qty_label.grid(row=3, column=0, padx=5, pady=8, sticky="e")
        entry_quantity = tk.Entry(entry_frame, width=15)
        entry_quantity.grid(row=3, column=1, padx=5, pady=8, sticky="w")

        stock_label = tk.Label(entry_frame, text="Current stock: -", font=('Arial', 9), fg='gray')
        stock_label.grid(row=4, column=1, padx=5, pady=2, sticky="w")

        conversion_label = tk.Label(entry_frame, text="", font=('Arial', 9), fg='gray')
        conversion_label.grid(row=5, column=1, padx=5, pady=0, sticky="w")

        def on_item_select(event=None):
            selected = item_var.get()
            if selected and selected != "Select an item...":
                item_id = selected.split(" - ")[0]
                try:
                    from conversions import requires_conversion, format_stock_display, get_conversion
                    qty = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY].values[0]
                    if requires_conversion(item_id):
                        display = format_stock_display(item_id, qty)
                        conversion = get_conversion(item_id)
                        output_unit = conversion[2] if conversion else "units"
                        stock_label.config(text=f"Current stock: {display}")
                        qty_label.config(text=f"Quantity ({output_unit}s):")
                        conversion_label.config(text="Enter quantity in consumption units")
                    else:
                        stock_label.config(text=f"Current stock: {qty:.1f}")
                        qty_label.config(text="Quantity:")
                        conversion_label.config(text="")
                except:
                    stock_label.config(text="Current stock: -")
                    qty_label.config(text="Quantity:")
                    conversion_label.config(text="")
            else:
                stock_label.config(text="Current stock: -")
                qty_label.config(text="Quantity:")
                conversion_label.config(text="")

        item_dropdown.bind("<<ComboboxSelected>>", on_item_select)

        # Items list
        transaction_items = []

        list_frame = tk.LabelFrame(main_frame, text="Items in this Tab", font=('Arial', 10, 'bold'))
        list_frame.pack(side=tk.RIGHT, fill='both', expand=True)

        columns = ('item_id', 'item_name', 'quantity')
        items_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=10)
        items_tree.heading('item_id', text='Item ID')
        items_tree.heading('item_name', text='Name')
        items_tree.heading('quantity', text='Qty')
        items_tree.column('item_id', width=80)
        items_tree.column('item_name', width=120)
        items_tree.column('quantity', width=60)
        items_tree.pack(fill='both', expand=True, padx=5, pady=5)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=items_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        items_tree.configure(yscrollcommand=scrollbar.set)

        def add_item():
            selected = item_var.get()
            if selected == "Select an item..." or not selected:
                messagebox.showerror("Error", "Please select an item.")
                return
            item_id = selected.split(" - ")[0]
            quantity_str = entry_quantity.get().strip()
            if not quantity_str:
                messagebox.showerror("Error", "Quantity is required.")
                return
            try:
                quantity = float(quantity_str)
                if quantity <= 0:
                    messagebox.showerror("Error", "Quantity must be greater than zero.")
                    return
            except ValueError:
                messagebox.showerror("Error", "Quantity must be a valid number.")
                return

            item_row = self.inventory_df[self.inventory_df[COL_ITEM_ID] == item_id].iloc[0]
            item_name = item_row[COL_ITEM_NAME]

            for i, (eid, _, eqty) in enumerate(transaction_items):
                if eid == item_id:
                    transaction_items[i] = (eid, item_name, eqty + quantity)
                    refresh_list()
                    item_dropdown.set("Select an item...")
                    entry_quantity.delete(0, tk.END)
                    stock_label.config(text="Current stock: -")
                    conversion_label.config(text="")
                    return

            transaction_items.append((item_id, item_name, quantity))
            refresh_list()
            item_dropdown.set("Select an item...")
            entry_quantity.delete(0, tk.END)
            stock_label.config(text="Current stock: -")
            conversion_label.config(text="")

        def remove_selected():
            sel = items_tree.selection()
            if not sel:
                messagebox.showerror("Error", "Please select an item to remove.")
                return
            item_values = items_tree.item(sel[0], 'values')
            item_id = item_values[0]
            for i, (eid, _, _) in enumerate(transaction_items):
                if eid == item_id:
                    transaction_items.pop(i)
                    break
            items_tree.delete(sel[0])

        def refresh_list():
            for item in items_tree.get_children():
                items_tree.delete(item)
            for item_id, item_name, qty in transaction_items:
                items_tree.insert('', tk.END, values=(item_id, item_name, f"{qty:.1f}"))

        def save_tab():
            customer_name = customer_entry.get().strip()
            if not customer_name:
                messagebox.showerror("Error", "Customer name is required.")
                return
            if not transaction_items:
                messagebox.showerror("Error", "No items to save.")
                return
            try:
                self.refresh_data()

                # Negative stock guard
                for item_id, item_name, quantity in transaction_items:
                    ok, current_qty, _ = self.check_negative_stock(item_id, quantity)
                    if not ok:
                        messagebox.showerror("Negative Stock", f"Cannot tab {quantity} of '{item_id}': only {current_qty} in stock.")
                        return
                    if has_parent_stock(item_id):
                        parent_ok, parent_issues = check_apply_sale_to_parent(
                            item_id, quantity, self.inventory_df,
                            COL_ITEM_ID, COL_QUANTITY, COL_ALLOW_NEGATIVE
                        )
                        if not parent_ok:
                            messagebox.showerror(
                                "Negative Parent Stock",
                                f"Cannot tab {quantity} of '{item_id}':\n" + "\n".join(parent_issues)
                            )
                            return

                # Prepare items with prices for the data manager
                items_for_db = []
                for item_id, item_name, quantity in transaction_items:
                    cost_price = get_effective_cost_price(item_id, self.inventory_df, COL_ITEM_ID, COL_COST_PRICE)
                    sell_price = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_SELL_PRICE].values[0]
                    items_for_db.append({
                        'item_id': item_id,
                        'item_name': item_name,
                        'quantity': quantity,
                        'cost_price': cost_price,
                        'sell_price': sell_price
                    })

                tab_id = InventoryDataManager.create_open_tab(customer_name, items_for_db)
                if not tab_id:
                    messagebox.showerror("Error", "Failed to create open tab.")
                    return

                # Deduct stock
                for item_id, item_name, quantity in transaction_items:
                    self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] -= quantity
                    if has_parent_stock(item_id):
                        apply_sale_to_parent(item_id, quantity, self.inventory_df, COL_ITEM_ID, COL_QUANTITY)

                if InventoryDataManager.save_inventory(self.inventory_df):
                    msg = f"Tab saved for '{customer_name}'!\n\n{len(transaction_items)} items:\n"
                    msg += "\n".join([f"  {name}: {qty:.1f}" for _, name, qty in transaction_items])
                    messagebox.showinfo("Success", msg)
                    self.update_dashboard_stats()
                    self.open_tabs_menu()
                else:
                    messagebox.showerror("Error", "Failed to save inventory.")
            except Exception as e:
                messagebox.showerror("Error", f"Tab failed: {e}")

        btn_frame = tk.Frame(entry_frame)
        btn_frame.grid(row=6, column=0, columnspan=2, pady=15)
        tk.Button(btn_frame, text="Add Item", command=add_item, width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Remove Selected", command=remove_selected, width=12).pack(side=tk.LEFT, padx=5)

        bottom_frame = tk.Frame(self.main_menu)
        bottom_frame.pack(fill='x', padx=20, pady=20)
        tk.Button(bottom_frame, text="Save Tab", command=save_tab, width=15).pack(side=tk.LEFT, padx=10)
        tk.Button(bottom_frame, text="Back", command=self.open_tabs_menu, width=15).pack(side=tk.LEFT, padx=10)

        self.root.update_idletasks()

    def view_open_tabs(self):
        """Display all open tabs with options to close or cancel."""
        self.clear_main_menu()

        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
        tk.Label(header_frame, text="View Open Tabs", font=('Arial', 16, 'bold')).pack(expand=True)

        # Load open tabs
        tabs_df = InventoryDataManager.get_open_tabs(status='open')

        if tabs_df.empty:
            tk.Label(self.main_menu, text="No open tabs.", font=('Arial', 12)).pack(pady=20)
            tk.Button(self.main_menu, text="Back", command=self.open_tabs_menu, width=15).pack(pady=10)
            return

        # Group by tab id
        tab_groups = tabs_df.groupby('id')

        # Treeview for tabs
        tree_container = tk.Frame(self.main_menu)
        tree_container.pack(fill='both', expand=True, padx=20, pady=10)

        columns = ('tab_id', 'customer', 'items', 'total_qty', 'created_at')
        tabs_tree = ttk.Treeview(tree_container, columns=columns, show='headings', height=12)
        tabs_tree.heading('tab_id', text='Tab ID')
        tabs_tree.heading('customer', text='Customer')
        tabs_tree.heading('items', text='Items')
        tabs_tree.heading('total_qty', text='Total Qty')
        tabs_tree.heading('created_at', text='Created')
        tabs_tree.column('tab_id', width=60, anchor='center')
        tabs_tree.column('customer', width=150)
        tabs_tree.column('items', width=250)
        tabs_tree.column('total_qty', width=80, anchor='center')
        tabs_tree.column('created_at', width=150, anchor='center')
        tabs_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=tabs_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tabs_tree.configure(yscrollcommand=scrollbar.set)

        # Populate tree
        for tab_id, group in tab_groups:
            customer = group['customer_name'].iloc[0]
            created_at = group['created_at'].iloc[0]
            items_list = [f"{row['item_name']} ({row['quantity']:.1f})" for _, row in group.iterrows()]
            total_qty = group['quantity'].sum()
            tabs_tree.insert('', tk.END, values=(tab_id, customer, ", ".join(items_list), f"{total_qty:.1f}", created_at))

        def close_as_sale():
            selected = tabs_tree.selection()
            if not selected:
                messagebox.showerror("Error", "Please select a tab to close.")
                return
            item_values = tabs_tree.item(selected[0], 'values')
            tab_id = int(item_values[0])

            if not messagebox.askyesno("Confirm", "Close this tab and record as sale?"):
                return

            self.refresh_data()
            tab_items = tabs_df[tabs_df['id'] == tab_id]
            items_for_db = []
            for _, row in tab_items.iterrows():
                items_for_db.append({
                    'item_id': row['item_id'],
                    'quantity': row['quantity'],
                    'cost_price': row['cost_price'],
                    'sell_price': row['sell_price']
                })

            if InventoryDataManager.close_open_tab(tab_id, items_for_db):
                # Reload log to include new sales
                self.log_df = InventoryDataManager.load_log(self.inventory_df)
                messagebox.showinfo("Success", f"Tab {tab_id} closed as sale.")
                self.update_dashboard_stats()
                self.view_open_tabs()
            else:
                messagebox.showerror("Error", "Failed to close tab.")

        def cancel_tab():
            selected = tabs_tree.selection()
            if not selected:
                messagebox.showerror("Error", "Please select a tab to cancel.")
                return
            item_values = tabs_tree.item(selected[0], 'values')
            tab_id = int(item_values[0])

            if not messagebox.askyesno("Confirm", "Cancel this tab and restore stock?"):
                return

            self.refresh_data()
            items_to_restore = InventoryDataManager.cancel_open_tab(tab_id)
            if items_to_restore is None:
                messagebox.showerror("Error", "Failed to cancel tab.")
                return

            # Restore stock
            for item in items_to_restore:
                item_id = item['item_id']
                quantity = item['quantity']
                self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] += quantity
                if has_parent_stock(item_id):
                    # Reverse parent stock adjustment by adding back
                    parent_info = get_parent_for_sale(item_id)
                    if parent_info:
                        parent_ids, factors, _ = parent_info
                        if isinstance(parent_ids, list):
                            for pid, factor in zip(parent_ids, factors):
                                if pid:
                                    self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == pid, COL_QUANTITY] += quantity * factor
                        elif parent_ids:
                            self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == parent_ids, COL_QUANTITY] += quantity * factors

            if InventoryDataManager.save_inventory(self.inventory_df):
                # Reload log to include cancellation
                self.log_df = InventoryDataManager.load_log(self.inventory_df)
                messagebox.showinfo("Success", f"Tab {tab_id} cancelled and stock restored.")
                self.update_dashboard_stats()
                self.view_open_tabs()
            else:
                messagebox.showerror("Error", "Failed to save restored stock.")

        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Close as Sale", command=close_as_sale, width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel Tab", command=cancel_tab, width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Back", command=self.open_tabs_menu, width=15).pack(side=tk.LEFT, padx=5)

        self.root.update_idletasks()

    def process_multi_transaction(self, action):
        """Process wastage or complimentary transactions with multiple items."""
        self.clear_main_menu()

        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)

        tk.Label(header_frame, text=f"Add {action}", font=('Arial', 16, 'bold')).pack(expand=True)

        # Main container
        main_frame = tk.Frame(self.main_menu)
        main_frame.pack(pady=10, padx=20, fill='both', expand=True)

        # Left side - Item entry
        entry_frame = tk.LabelFrame(main_frame, text=f"Add Items ({action})", font=('Arial', 10, 'bold'))
        entry_frame.pack(side=tk.LEFT, fill='both', expand=True, padx=(0, 10))

        # Search bar
        tk.Label(entry_frame, text="Search:").grid(row=0, column=0, padx=5, pady=8, sticky="e")
        self.refresh_data()
        full_item_list = [f"{row[COL_ITEM_ID]} - {row[COL_ITEM_NAME]}" for _, row in self.inventory_df.iterrows()]

        if not full_item_list:
            messagebox.showerror("Error", "No items in inventory. Please add items first.")
            self.create_main_menu()
            return

        search_var = tk.StringVar()
        search_entry = tk.Entry(entry_frame, textvariable=search_var, width=15, bg='#2c2c2c', fg='white')
        search_entry.grid(row=0, column=1, padx=(5, 0), pady=8, sticky="w")
        search_entry.insert(0, "Type to search...")
        search_entry.config(fg='gray')

        def on_search_focus_in(event):
            if search_var.get() == "Type to search...":
                search_entry.delete(0, tk.END)
                search_entry.config(fg='white')

        def on_search_focus_out(event):
            if not search_var.get().strip():
                search_entry.insert(0, "Type to search...")
                search_entry.config(fg='gray')

        def on_search_change(*args):
            query = search_var.get().lower()
            if query == "type to search..." or not query:
                filtered = full_item_list
            else:
                filtered = [item for item in full_item_list if query in item.lower()]
            item_dropdown['values'] = filtered

        search_entry.bind('<FocusIn>', on_search_focus_in)
        search_entry.bind('<FocusOut>', on_search_focus_out)
        search_var.trace_add('write', on_search_change)

        item_var = tk.StringVar()
        item_dropdown = ttk.Combobox(entry_frame, textvariable=item_var, values=full_item_list, width=35, state="readonly")
        item_dropdown.grid(row=1, column=0, columnspan=2, padx=5, pady=8)
        item_dropdown.set("Select an item...")

        qty_label = tk.Label(entry_frame, text="Quantity:")
        qty_label.grid(row=2, column=0, padx=5, pady=8, sticky="e")
        entry_quantity = tk.Entry(entry_frame, width=15)
        entry_quantity.grid(row=2, column=1, padx=5, pady=8, sticky="w")

        # Reason dropdown for Wastage and Complimentary
        if action == ACTION_WASTAGE:
            tk.Label(entry_frame, text="Reason:").grid(row=3, column=0, padx=5, pady=8, sticky="e")
            reason_var = tk.StringVar(value="Broken/Damaged")
            reason_dropdown = ttk.Combobox(entry_frame, textvariable=reason_var,
                                           values=["Broken/Damaged", "Out of Date", "Overpour", "Returned", "Line Clean", "Drip Trays", "Other"],
                                           width=33, state="readonly")
            reason_dropdown.grid(row=3, column=1, padx=5, pady=8, sticky="w")
            stock_row = 4
            conv_row = 5
            btn_row = 6
        elif action == ACTION_COMPLIMENTARY:
            tk.Label(entry_frame, text="Reason:").grid(row=3, column=0, padx=5, pady=8, sticky="e")
            reason_var = tk.StringVar(value="Complaint")
            reason_dropdown = ttk.Combobox(entry_frame, textvariable=reason_var,
                                           values=["Complaint", "Chris", "Tour Group", "Hospitality"],
                                           width=33, state="readonly")
            reason_dropdown.grid(row=3, column=1, padx=5, pady=8, sticky="w")
            stock_row = 4
            conv_row = 5
            btn_row = 6
        else:
            stock_row = 3
            conv_row = 4
            btn_row = 5

        stock_label = tk.Label(entry_frame, text="Current stock: -", font=('Arial', 9), fg='gray')
        stock_label.grid(row=stock_row, column=1, padx=5, pady=2, sticky="w")

        conversion_label = tk.Label(entry_frame, text="", font=('Arial', 9), fg='gray')
        conversion_label.grid(row=conv_row, column=1, padx=5, pady=0, sticky="w")

        def on_item_select(event=None):
            selected = item_var.get()
            if selected and selected != "Select an item...":
                item_id = selected.split(" - ")[0]
                try:
                    from conversions import requires_conversion, format_stock_display, get_conversion
                    qty = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY].values[0]
                    if requires_conversion(item_id):
                        display = format_stock_display(item_id, qty)
                        conversion = get_conversion(item_id)
                        output_unit = conversion[2] if conversion else "units"
                        stock_label.config(text=f"Current stock: {display}")
                        qty_label.config(text=f"Quantity ({output_unit}s):")
                        conversion_label.config(text="Enter quantity in consumption units")
                    else:
                        stock_label.config(text=f"Current stock: {qty:.1f}")
                        qty_label.config(text="Quantity:")
                        conversion_label.config(text="")
                except:
                    stock_label.config(text="Current stock: -")
            else:
                stock_label.config(text="Current stock: -")
                qty_label.config(text="Quantity:")
                conversion_label.config(text="")

        item_dropdown.bind("<<ComboboxSelected>>", on_item_select)

        # Items list for this transaction
        transaction_items = []

        # Right side - Items list
        list_frame = tk.LabelFrame(main_frame, text=f"Items in this {action}", font=('Arial', 10, 'bold'))
        list_frame.pack(side=tk.RIGHT, fill='both', expand=True)

        columns = ('item_id', 'item_name', 'quantity', 'reason')
        items_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=10)
        items_tree.heading('item_id', text='Item ID')
        items_tree.heading('item_name', text='Name')
        items_tree.heading('quantity', text='Qty')
        items_tree.heading('reason', text='Reason')
        items_tree.column('item_id', width=80)
        items_tree.column('item_name', width=120)
        items_tree.column('quantity', width=60)
        items_tree.column('reason', width=120)
        items_tree.pack(fill='both', expand=True, padx=5, pady=5)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=items_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        items_tree.configure(yscrollcommand=scrollbar.set)

        def add_item():
            selected = item_var.get()
            if selected == "Select an item..." or not selected:
                messagebox.showerror("Error", "Please select an item.")
                return
            item_id = selected.split(" - ")[0]
            quantity_str = entry_quantity.get().strip()
            if not quantity_str:
                messagebox.showerror("Error", "Quantity is required.")
                return
            try:
                quantity = float(quantity_str)
                if quantity <= 0:
                    messagebox.showerror("Error", "Quantity must be greater than zero.")
                    return
            except ValueError:
                messagebox.showerror("Error", "Quantity must be a valid number.")
                return

            item_row = self.inventory_df[self.inventory_df[COL_ITEM_ID] == item_id].iloc[0]
            item_name = item_row[COL_ITEM_NAME]
            reason = reason_var.get() if action in (ACTION_WASTAGE, ACTION_COMPLIMENTARY) else ""

            # Check if already added
            for i, (eid, _, eqty, _) in enumerate(transaction_items):
                if eid == item_id:
                    transaction_items[i] = (eid, item_name, eqty + quantity, reason)
                    refresh_list()
                    item_dropdown.set("Select an item...")
                    entry_quantity.delete(0, tk.END)
                    stock_label.config(text="Current stock: -")
                    conversion_label.config(text="")
                    return

            transaction_items.append((item_id, item_name, quantity, reason))
            refresh_list()
            item_dropdown.set("Select an item...")
            entry_quantity.delete(0, tk.END)
            stock_label.config(text="Current stock: -")
            conversion_label.config(text="")

        def remove_selected():
            sel = items_tree.selection()
            if not sel:
                messagebox.showerror("Error", "Please select an item to remove.")
                return
            item_values = items_tree.item(sel[0], 'values')
            item_id = item_values[0]
            for i, (eid, _, _, _) in enumerate(transaction_items):
                if eid == item_id:
                    transaction_items.pop(i)
                    break
            items_tree.delete(sel[0])

        def refresh_list():
            for item in items_tree.get_children():
                items_tree.delete(item)
            for item_id, item_name, qty, reason in transaction_items:
                items_tree.insert('', tk.END, values=(item_id, item_name, f"{qty:.1f}", reason))

        def save_all():
            if not transaction_items:
                messagebox.showerror("Error", "No items to save.")
                return
            try:
                self.refresh_data()
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log_entries = []

                for item_id, item_name, quantity, reason in transaction_items:
                    # Negative stock guard for the item itself
                    ok, current_qty, _ = self.check_negative_stock(item_id, quantity)
                    if not ok:
                        messagebox.showerror("Negative Stock", f"Cannot {action.lower()} {quantity} of '{item_id}': only {current_qty} in stock.")
                        continue

                    # Negative parent stock guard
                    if has_parent_stock(item_id):
                        parent_ok, parent_issues = check_apply_sale_to_parent(
                            item_id, quantity, self.inventory_df,
                            COL_ITEM_ID, COL_QUANTITY, COL_ALLOW_NEGATIVE
                        )
                        if not parent_ok:
                            messagebox.showerror(
                                "Negative Parent Stock",
                                f"Cannot {action.lower()} {quantity} of '{item_id}':\n" + "\n".join(parent_issues)
                            )
                            continue

                    if action == ACTION_WASTAGE:
                        self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] -= quantity
                    else:  # Complimentary
                        self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] -= quantity

                    if has_parent_stock(item_id):
                        apply_sale_to_parent(item_id, quantity, self.inventory_df, COL_ITEM_ID, COL_QUANTITY)

                    cost_price = get_effective_cost_price(item_id, self.inventory_df, COL_ITEM_ID, COL_COST_PRICE)
                    sell_price = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_SELL_PRICE].values[0]
                    log_entries.append([item_id, action, quantity, timestamp, cost_price, sell_price, "", "", reason])

                if log_entries:
                    new_log_df = pd.DataFrame(log_entries, columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON])
                    self.log_df = pd.concat([self.log_df, new_log_df], ignore_index=True)

                if InventoryDataManager.save_inventory(self.inventory_df) and InventoryDataManager.save_log(self.log_df):
                    msg = f"{action} saved!\n\n{len(transaction_items)} items:\n"
                    msg += "\n".join([f"  {name}: {qty:.1f}" for _, name, qty, _ in transaction_items])
                    messagebox.showinfo("Success", msg)
                    self.update_dashboard_stats()
                    self.create_main_menu()
                else:
                    messagebox.showerror("Error", "Failed to save. Data may be inconsistent.")
            except Exception as e:
                messagebox.showerror("Error", f"{action} failed: {e}")

        # Buttons
        btn_frame = tk.Frame(entry_frame)
        btn_frame.grid(row=btn_row, column=0, columnspan=2, pady=15)
        tk.Button(btn_frame, text="Add Item", command=add_item, width=12).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Remove Selected", command=remove_selected, width=12).pack(side=tk.LEFT, padx=5)

        # Bottom buttons
        bottom_frame = tk.Frame(self.main_menu)
        bottom_frame.pack(fill='x', padx=20, pady=20)
        tk.Button(bottom_frame, text="Save All", command=save_all, width=15).pack(side=tk.LEFT, padx=10)
        if action == ACTION_COMPLIMENTARY:
            tk.Button(bottom_frame, text="Upload CSV", command=self.upload_complimentary_report, width=15).pack(side=tk.LEFT, padx=10)
        tk.Button(bottom_frame, text="Back", command=self.create_main_menu, width=15).pack(side=tk.LEFT, padx=10)

        self.root.update_idletasks()

    def line_clean(self):
        """Record a line clean by deducting 5 pints from each draught item's current stock and logging it as wastage."""
        self.refresh_data()

        if self.inventory_df.empty:
            messagebox.showwarning("No Data", "No inventory data available.")
            return

        # Load Items.csv to identify draught items by their Division
        script_dir = get_script_directory()
        items_csv_path = os.path.join(script_dir, 'Items.csv')
        draught_item_names = set()

        if os.path.exists(items_csv_path):
            try:
                items_df = pd.read_csv(items_csv_path, compression=None)
                if 'Name' in items_df.columns and 'Division' in items_df.columns:
                    for _, row in items_df.iterrows():
                        if 'draught' in str(row['Division']).lower():
                            draught_item_names.add(str(row['Name']).lower().strip())
            except Exception as e:
                messagebox.showerror("Error", f"Failed to read Items.csv: {e}")
                return

        if not draught_item_names:
            messagebox.showwarning("No Data", "Could not find draught items in Items.csv.\n\nPlease ensure Items.csv exists with 'Name' and 'Division' columns,\nand some items have 'Draught' in their Division.")
            return

        # Find matching items in inventory
        draught_items = []
        for _, row in self.inventory_df.iterrows():
            item_name = str(row[COL_ITEM_NAME]).lower().strip()
            # Check if item name matches any draught item from Items.csv
            if item_name in draught_item_names and row[COL_QUANTITY] > 0:
                draught_items.append(row)

        if not draught_items:
            messagebox.showinfo("Line Clean", "No draught items with positive stock found in inventory.")
            return

        # Build confirmation message
        confirm_msg = "Line Clean will record 5 pints wastage for the following items:\n\n"
        total_pints = 0
        for item in draught_items:
            confirm_msg += f"  {item[COL_ITEM_NAME]} (Current: {item[COL_QUANTITY]:.1f})\n"
            total_pints += 5

        confirm_msg += f"\nTotal pints to record as wastage: {total_pints}\n"
        confirm_msg += "\nThis will deduct 5 pints from each item's current stock and log it as wastage.\n\nProceed with line clean?"

        if not messagebox.askyesno("Confirm Line Clean", confirm_msg):
            return

        # Perform the line clean - deduct from stock AND log wastage
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        items_recorded = []
        errors = []

        for item in draught_items:
            item_id = item[COL_ITEM_ID]
            item_name = item[COL_ITEM_NAME]
            cost_price = item[COL_COST_PRICE]
            sell_price = item[COL_SELL_PRICE]

            try:
                # Deduct 5 pints from current stock
                self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] -= 5

                # Log the transaction as wastage
                new_log_entry = pd.DataFrame([[item_id, ACTION_WASTAGE, 5, timestamp, cost_price, sell_price, "Line Clean", "", "Line Clean"]],
                                              columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON])
                self.log_df = pd.concat([self.log_df, new_log_entry], ignore_index=True)

                items_recorded.append(f"{item_name}: -5 pints")

            except Exception as e:
                errors.append(f"{item_name}: {e}")

        # Save changes (both inventory and log)
        if InventoryDataManager.save_inventory(self.inventory_df) and InventoryDataManager.save_log(self.log_df):
            success_msg = f"Line Clean recorded successfully!\n\n{len(items_recorded)} items:\n"
            success_msg += "\n".join(items_recorded[:10])  # Show first 10
            if len(items_recorded) > 10:
                success_msg += f"\n... and {len(items_recorded) - 10} more"
            if errors:
                success_msg += f"\n\nErrors ({len(errors)}):\n" + "\n".join(errors[:5])
            success_msg += "\n\nCurrent stock levels have been updated."
            messagebox.showinfo("Line Clean Complete", success_msg)
        else:
            messagebox.showerror("Error", "Failed to save line clean data. Please try again.")

    def process_transaction(self, action):
        """Process a transaction of the specified type."""
        self.clear_main_menu()

        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)

        tk.Label(header_frame, text=f"Add {action}", font=('Arial', 16, 'bold')).pack(expand=True)

        frame = tk.Frame(self.main_menu)
        frame.pack(pady=10, padx=20)

        # Item selection via dropdown
        tk.Label(frame, text="Item:").grid(row=0, column=0, padx=5, pady=8, sticky="e")

        # Create list of items for dropdown
        self.refresh_data()
        item_list = [f"{row[COL_ITEM_ID]} - {row[COL_ITEM_NAME]}" for _, row in self.inventory_df.iterrows()]

        if not item_list:
            messagebox.showerror("Error", "No items in inventory. Please add items first.")
            self.create_main_menu()
            return

        item_var = tk.StringVar()
        item_dropdown = ttk.Combobox(frame, textvariable=item_var, values=item_list, width=40, state="readonly")
        item_dropdown.grid(row=0, column=1, padx=5, pady=8)
        item_dropdown.set("Select an item...")

        # Quantity label updated dynamically based on selected item
        qty_label = tk.Label(frame, text="Quantity:")
        qty_label.grid(row=1, column=0, padx=5, pady=8, sticky="e")
        entry_quantity = tk.Entry(frame, width=20)
        entry_quantity.grid(row=1, column=1, padx=5, pady=8, sticky="w")

        # Show current stock label
        stock_label = tk.Label(frame, text="Current stock: -", font=('Arial', 10, 'bold'))
        stock_label.grid(row=2, column=1, padx=5, pady=5, sticky="w")

        # Conversion info label
        conversion_label = tk.Label(frame, text="", font=('Arial', 9), fg='gray')
        conversion_label.grid(row=3, column=1, padx=5, pady=0, sticky="w")

        # Track currently selected item for conversion
        selected_item_id = [None]

        def on_item_select(event=None):
            """Update stock label and quantity label when item is selected."""
            selected = item_var.get()
            if selected and selected != "Select an item...":
                item_id = selected.split(" - ")[0]
                selected_item_id[0] = item_id
                try:
                    from conversions import requires_conversion, convert_to_input, get_input_label, format_stock_display, get_conversion
                    qty = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY].values[0]
                    if requires_conversion(item_id):
                        display = format_stock_display(item_id, qty)
                        input_unit = get_input_label(item_id)
                        conversion = get_conversion(item_id)
                        factor = conversion[1] if conversion else 1
                        output_unit = conversion[2] if conversion else "units"
                        stock_label.config(text=f"Current stock: {display}")
                        qty_label.config(text=f"Quantity ({input_unit}s):")
                        conversion_label.config(text=f"1 {input_unit} = {factor} {output_unit}s")
                    else:
                        stock_label.config(text=f"Current stock: {qty:.1f}")
                        qty_label.config(text="Quantity:")
                        conversion_label.config(text="")
                except:
                    stock_label.config(text="Current stock: -")
                    qty_label.config(text="Quantity:")
                    conversion_label.config(text="")
            else:
                selected_item_id[0] = None
                stock_label.config(text="Current stock: -")
                qty_label.config(text="Quantity:")
                conversion_label.config(text="")

        item_dropdown.bind("<<ComboboxSelected>>", on_item_select)

        def save_transaction():
            """Save the transaction to the log and update inventory."""
            selected = item_var.get()
            if selected == "Select an item..." or not selected:
                messagebox.showerror("Error", "Please select an item.")
                return

            item_id = selected.split(" - ")[0]
            quantity_str = entry_quantity.get().strip()

            if not quantity_str:
                messagebox.showerror("Error", "Quantity is required.")
                return

            # Validate quantity
            try:
                input_quantity = float(quantity_str)
                if input_quantity <= 0:
                    messagebox.showerror("Error", "Quantity must be greater than zero.")
                    return
            except ValueError:
                messagebox.showerror("Error", "Quantity must be a valid number.")
                return

            # Convert input quantity to system units if needed (e.g. bottles -> measures)
            from conversions import requires_conversion, convert_to_system, get_conversion, get_input_label
            if requires_conversion(item_id):
                quantity = convert_to_system(item_id, input_quantity)
                conversion = get_conversion(item_id)
                input_unit = conversion[0] if conversion else "units"
                output_unit = conversion[2] if conversion else "units"
                conversion_msg = f"\n({input_quantity:.1f} {input_unit}s = {quantity:.1f} {output_unit}s)"
            else:
                quantity = input_quantity
                conversion_msg = ""

            # Reload inventory to ensure we have latest data
            self.refresh_data()

            if item_id not in self.inventory_df[COL_ITEM_ID].values:
                messagebox.showerror("Error", "Item not found in inventory.")
                return

            # Get current quantity and prices
            current_qty = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY].values[0]
            if action == ACTION_DELIVERY:
                cost_price = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_COST_PRICE].values[0]
            else:
                cost_price = get_effective_cost_price(item_id, self.inventory_df, COL_ITEM_ID, COL_COST_PRICE)
            sell_price = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_SELL_PRICE].values[0]

            # Perform transaction (atomic operation)
            try:
                parent_adjustments = []

                # Update inventory
                if action == ACTION_DELIVERY:
                    self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] += quantity
                else:
                    # For sales/wastage/complimentary, deduct from the item
                    # Check negative stock guard for the item itself
                    ok, current_qty, _ = self.check_negative_stock(item_id, quantity)
                    if not ok:
                        messagebox.showerror("Negative Stock", f"Cannot {action.lower()} {quantity} of '{item_id}': only {current_qty} in stock.")
                        return

                    # Check parent stock guard for items that deduct from parent stock
                    if has_parent_stock(item_id):
                        parent_ok, parent_issues = check_apply_sale_to_parent(
                            item_id, quantity, self.inventory_df,
                            COL_ITEM_ID, COL_QUANTITY, COL_ALLOW_NEGATIVE
                        )
                        if not parent_ok:
                            messagebox.showerror(
                                "Negative Parent Stock",
                                f"Cannot {action.lower()} {quantity} of '{item_id}':\n" + "\n".join(parent_issues)
                            )
                            return

                    self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] -= quantity

                    # Apply parent stock deductions (e.g., half pint affects full pint)
                    if has_parent_stock(item_id):
                        parent_adjustments = apply_sale_to_parent(
                            item_id, quantity, self.inventory_df,
                            COL_ITEM_ID, COL_QUANTITY
                        )

                # Log the transaction with ISO format timestamp
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # Include supplier for Delivery transactions
                if action == ACTION_DELIVERY and hasattr(self, 'current_delivery_supplier'):
                    new_log_entry = pd.DataFrame([[item_id, action, quantity, timestamp, cost_price, sell_price, self.current_delivery_supplier, "", ""]],
                                                  columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON])
                    # Clear the supplier after use
                    delattr(self, 'current_delivery_supplier')
                else:
                    new_log_entry = pd.DataFrame([[item_id, action, quantity, timestamp, cost_price, sell_price, "", "", ""]],
                                                  columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON])
                self.log_df = pd.concat([self.log_df, new_log_entry], ignore_index=True)

                # Save both files
                if InventoryDataManager.save_inventory(self.inventory_df) and InventoryDataManager.save_log(self.log_df):
                    success_msg = f"{quantity:.1f} units of item '{item_id}' recorded as {action}.{conversion_msg}"

                    # Add parent adjustment info if applicable
                    if parent_adjustments:
                        success_msg += "\n\nParent stock adjusted:\n"
                        for parent_id, deduction, desc in parent_adjustments:
                            success_msg += f"  • {desc}\n"

                    messagebox.showinfo("Success", success_msg)
                    self.update_dashboard_stats()
                    self.create_main_menu()
                else:
                    messagebox.showerror("Error", "Failed to save transaction. Data may be inconsistent.")

            except Exception as e:
                messagebox.showerror("Error", f"Transaction failed: {e}")

        btn_frame = tk.Frame(frame)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=20)

        tk.Button(btn_frame, text="Save Transaction", command=save_transaction, width=15).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Back", command=self.create_main_menu, width=15).pack(side=tk.LEFT, padx=10)

        # Force redraw so ttk.Combobox is visible immediately on macOS
        self.root.update_idletasks()

    def full_stock_take(self):
        """Open the full stocktake screen."""
        self.record_stocktake()

    def record_stocktake(self):
        """Record a full stocktake snapshot with counted vs expected quantities."""
        self.clear_main_menu()

        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)

        tk.Label(header_frame, text="Full Stocktake", font=('Arial', 16, 'bold')).pack(expand=True)

        self.refresh_data()

        if self.inventory_df.empty:
            messagebox.showerror("Error", "No items in inventory. Please add items first.")
            self.create_main_menu()
            return

        # Compact top controls frame (note + search on one row)
        controls_frame = tk.Frame(self.main_menu, bg='#333333')
        controls_frame.pack(fill='x', padx=10, pady=5)

        tk.Label(controls_frame, text="Note:", font=('Arial', 10, 'bold'), bg='#333333', fg='white').pack(side=tk.LEFT, padx=5)
        note_entry = tk.Entry(controls_frame, width=25, bg='white', fg='black')
        note_entry.pack(side=tk.LEFT, padx=5)

        tk.Button(controls_frame, text="Download PDF Sheet", command=self.download_stock_count_sheet,
                  width=16, font=('Arial', 9, 'bold')).pack(side=tk.LEFT, padx=(15, 5))

        tk.Label(controls_frame, text="Search:", font=('Arial', 10, 'bold'), bg='#333333', fg='white').pack(side=tk.LEFT, padx=(20, 5))
        search_entry = tk.Entry(controls_frame, width=20, bg='white', fg='black')
        search_entry.pack(side=tk.LEFT, padx=5)

        # Table container
        table_container = tk.Frame(self.main_menu, bg='#d0d0d0', bd=2, relief='solid')
        table_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)

        # Column header
        header_bg = '#d0d0d0'
        col_config = [
            ("Item", 35, 'w'),
            ("Expected", 12, 'center'),
            ("Counted", 12, 'center'),
            ("Variance", 12, 'center')
        ]
        header_frame = tk.Frame(table_container, bg=header_bg)
        header_frame.pack(fill='x')
        for text, width, anchor in col_config:
            tk.Label(header_frame, text=text, font=('Arial', 10, 'bold'),
                     bg=header_bg, fg='black', width=width, anchor=anchor).pack(side=tk.LEFT, padx=(4, 0), pady=4)

        # Scrollable body
        canvas = tk.Canvas(table_container, bg='#d0d0d0', highlightthickness=0)
        scrollbar = ttk.Scrollbar(table_container, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg='white')

        def on_canvas_configure(event):
            canvas.itemconfig(canvas_window, width=event.width)
            canvas.coords(canvas_window, event.width / 2, 0)
        canvas.bind("<Configure>", on_canvas_configure)

        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas_window = canvas.create_window((0, 0), window=scroll_frame, anchor="n")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Mouse wheel scrolling
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", on_mousewheel)

        # Row styling
        row_bg_even = '#ffffff'
        row_bg_odd = '#f0f0f0'

        # Store widgets for saving
        item_entries = []
        expected_system = {}  # item_id -> expected quantity in system units

        def build_table():
            # Clear existing rows
            for widget in scroll_frame.winfo_children():
                widget.destroy()
            item_entries.clear()

            search_text = search_entry.get().strip().lower()

            row_idx = 0
            for _, row in self.inventory_df.iterrows():
                item_id = row[COL_ITEM_ID]
                item_name = row[COL_ITEM_NAME]
                current_stock = row[COL_QUANTITY]

                # Skip excluded/hidden items
                if is_hidden_from_stock_view(item_id):
                    continue

                # Apply search filter
                if search_text and search_text not in item_name.lower() and search_text not in item_id.lower():
                    continue

                if requires_conversion(item_id):
                    conversion = get_conversion(item_id)
                    input_unit, factor, output_unit = conversion
                    expected_input = convert_to_input(item_id, current_stock)
                    expected_text = f"{expected_input:.1f} {input_unit}s"
                else:
                    expected_text = f"{current_stock:.1f} {row[COL_MEASURE]}s"
                    factor = 1
                    input_unit = row[COL_MEASURE]
                    expected_input = current_stock

                expected_system[item_id] = current_stock
                bg_color = row_bg_even if row_idx % 2 == 0 else row_bg_odd

                # Row container
                row_frame = tk.Frame(scroll_frame, bg=bg_color, bd=1, relief='solid')
                row_frame.pack(fill='x')

                # Item name
                tk.Label(row_frame, text=item_name[:35], font=('Arial', 10),
                         bg=bg_color, fg='black', width=35, anchor='w').pack(side=tk.LEFT, padx=(6, 0), pady=4)

                # Expected
                tk.Label(row_frame, text=expected_text, font=('Arial', 10),
                         bg=bg_color, fg='black', width=12, anchor='center').pack(side=tk.LEFT, padx=(4, 0), pady=4)

                # Counted entry
                count_entry = tk.Entry(row_frame, font=('Arial', 10), width=12, justify='center',
                                       relief='solid', bd=1, bg='white', fg='black')
                count_entry.pack(side=tk.LEFT, padx=(4, 0), pady=4)

                # Variance
                var_lbl = tk.Label(row_frame, text="-", font=('Arial', 10, 'bold'),
                                   bg=bg_color, fg='black', width=12, anchor='center')
                var_lbl.pack(side=tk.LEFT, padx=(4, 0), pady=4)

                # Unit hint for converted items
                if requires_conversion(item_id):
                    unit_hint = tk.Label(row_frame, text=f"Enter {input_unit}s",
                                         font=('Arial', 8), bg=bg_color, fg='gray', width=12, anchor='center')
                else:
                    unit_hint = tk.Label(row_frame, text=f"Enter {input_unit}s",
                                         font=('Arial', 8), bg=bg_color, fg='gray', width=12, anchor='center')
                unit_hint.pack(side=tk.LEFT, padx=(4, 0), pady=4)

                def make_update(var_lbl, exp_sys, conv_factor, ent):
                    def update_variance(*args):
                        val = ent.get().strip()
                        if not val:
                            var_lbl.config(text="-", fg='black')
                            return
                        try:
                            counted_input = float(val)
                            if counted_input < 0:
                                var_lbl.config(text="Invalid", fg='red')
                                return
                            counted_system = counted_input * conv_factor if conv_factor != 1 else counted_input
                            variance = counted_system - exp_sys
                            var_text = f"{variance:+.1f}"
                            if variance > 0:
                                var_lbl.config(text=var_text, fg='green')
                            elif variance < 0:
                                var_lbl.config(text=var_text, fg='red')
                            else:
                                var_lbl.config(text="0.0", fg='black')
                        except ValueError:
                            var_lbl.config(text="Invalid", fg='red')
                    return update_variance

                update_fn = make_update(var_lbl, current_stock, factor if requires_conversion(item_id) else 1, count_entry)
                count_entry.bind("<KeyRelease>", update_fn)

                item_entries.append({
                    'item_id': item_id,
                    'entry': count_entry,
                    'var_label': var_lbl,
                    'expected_system': current_stock,
                    'factor': factor if requires_conversion(item_id) else 1,
                    'input_unit': input_unit
                })
                row_idx += 1

            # Tab/Enter navigation
            for i, item in enumerate(item_entries):
                def make_tab_handler(next_entry):
                    def on_tab(event):
                        next_entry.focus_set()
                        next_entry.select_range(0, tk.END)
                        return "break"
                    return on_tab
                if i < len(item_entries) - 1:
                    item['entry'].bind("<Return>", make_tab_handler(item_entries[i + 1]['entry']))
                    item['entry'].bind("<Tab>", make_tab_handler(item_entries[i + 1]['entry']))
                else:
                    def on_last_tab(event):
                        save_btn.focus_set()
                        return "break"
                    item['entry'].bind("<Return>", on_last_tab)
                    item['entry'].bind("<Tab>", on_last_tab)

            scroll_frame.update_idletasks()
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.yview_moveto(0)

        build_table()
        canvas.yview_moveto(0)
        search_entry.bind("<KeyRelease>", lambda e: build_table())

        def save_stocktake():
            # Pre-stocktake backup
            from data_manager import create_backup
            backup_path = create_backup('before_stocktake')
            if backup_path:
                print(f"Pre-stocktake backup created: {backup_path}")

            note = note_entry.get().strip()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            recorded = 0
            skipped = 0
            errors = 0

            for item in item_entries:
                val = item['entry'].get().strip()
                if not val:
                    skipped += 1
                    continue
                try:
                    counted_input = float(val)
                    if counted_input < 0:
                        errors += 1
                        continue
                    counted_system = counted_input * item['factor']
                    variance = counted_system - item['expected_system']
                    success = record_stocktake(
                        item['item_id'], counted_system, item['expected_system'],
                        variance, timestamp, note
                    )
                    if success:
                        recorded += 1
                    else:
                        errors += 1
                except ValueError:
                    errors += 1

            if recorded > 0:
                msg = f"Stocktake saved successfully!\n\nRecorded: {recorded} items\nSkipped (blank): {skipped} items"
                if errors > 0:
                    msg += f"\nErrors: {errors} items"
                messagebox.showinfo("Success", msg)
                self.create_main_menu()
            else:
                if errors > 0:
                    messagebox.showwarning("No Valid Entries", f"No valid counted quantities entered.\nErrors: {errors} items")
                else:
                    messagebox.showwarning("No Entries", "No counted quantities entered. Please enter at least one count.")

        def set_baseline_from_stocktake():
            """Save stocktake and reset baseline: archive old transactions, log baselines."""
            # Collect counted items first
            counted_items = []
            for item in item_entries:
                val = item['entry'].get().strip()
                if not val:
                    continue
                try:
                    counted_input = float(val)
                    if counted_input < 0:
                        continue
                    counted_system = counted_input * item['factor']
                    counted_items.append({
                        'item_id': item['item_id'],
                        'counted_system': counted_system,
                        'input_value': counted_input,
                        'input_unit': item['input_unit']
                    })
                except ValueError:
                    continue

            if not counted_items:
                messagebox.showwarning("No Entries", "No counted quantities entered. Please enter at least one count.")
                return

            # Unit warning: if any converted item count is suspiciously small, confirm unit
            suspicious = []
            for item in counted_items:
                if requires_conversion(item['item_id']) and item['input_value'] < 0.5:
                    suspicious.append(f"{item['item_id']}: {item['input_value']:.2f} {item['input_unit']}s")
            if suspicious:
                warn_msg = (
                    "The following counts are very small for items that are normally counted in bottles/boxes/barrels:\n\n" +
                    "\n".join(suspicious) +
                    "\n\nPlease confirm you entered the counts in the correct input unit (not measures/pints)."
                )
                if not messagebox.askyesno("Unit Check", warn_msg + "\n\nDo you want to continue anyway?"):
                    return

            # Confirm with user
            note = note_entry.get().strip()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            confirm_msg = (
                f"You are about to set a NEW BASELINE using today's stocktake ({len(counted_items)} items).\n\n"
                f"This will:\n"
                f"  1. Save the stocktake snapshot\n"
                f"  2. Archive ALL transactions before {timestamp}\n"
                f"  3. Set inventory to your counted quantities\n"
                f"  4. Log ACTION_STOCKTAKE_BASELINE transactions as the new starting point\n\n"
                f"Old transactions will be preserved in an archive table for audit purposes.\n\n"
                f"Reports from now on will only consider transactions from today onward.\n\n"
                f"Are you sure you want to proceed?"
            )
            if not messagebox.askyesno("Confirm Baseline Reset", confirm_msg):
                return

            # Step 1: Pre-reset backup
            from data_manager import create_backup
            backup_path = create_backup('before_baseline_reset')
            if backup_path:
                print(f"Pre-baseline backup created: {backup_path}")

            # Step 2: Save stocktake normally
            saved_count = 0
            for item in counted_items:
                success = record_stocktake(
                    item['item_id'], item['counted_system'], 0,
                    item['counted_system'], timestamp, note + " (Baseline)"
                )
                if success:
                    saved_count += 1

            # Step 3: Archive old transactions
            from data_manager import archive_transactions_before_date, add_baseline_reset
            archived_count = archive_transactions_before_date(timestamp)
            if archived_count < 0:
                messagebox.showerror("Error", "Failed to archive transactions. Baseline reset aborted.")
                return

            # Step 4: Log baseline transactions
            baseline_logged = 0
            try:
                with AtomicTransaction() as txn:
                    for item in counted_items:
                        txn.log_transaction(
                            item_id=item['item_id'],
                            action=ACTION_STOCKTAKE_BASELINE,
                            quantity=item['counted_system'],
                            timestamp=timestamp,
                            reason=f"Baseline from physical count: {item['input_value']:.1f} {item['input_unit']}s"
                        )
                        baseline_logged += 1
            except Exception as e:
                messagebox.showerror("Error", f"Failed to log baseline transactions: {e}")
                return

            # Step 5: Record the reset event
            add_baseline_reset(timestamp, saved_count, archived_count, note)

            msg = (
                f"Baseline reset complete!\n\n"
                f"Stocktake saved: {saved_count} items\n"
                f"Transactions archived: {archived_count}\n"
                f"Baseline entries logged: {baseline_logged}\n\n"
                f"From now on, all reports will calculate expected stock\n"
                f"using only transactions from {timestamp} onward."
            )
            messagebox.showinfo("Baseline Reset Complete", msg)
            self.create_main_menu()

        def back():
            canvas.unbind_all("<MouseWheel>")
            self.create_main_menu()

        # Buttons at bottom
        btn_frame = tk.Frame(self.main_menu, bg='#333333')
        btn_frame.pack(pady=10, fill='x')

        save_btn = tk.Button(btn_frame, text="Save Stocktake", command=save_stocktake, width=18, font=('Arial', 10, 'bold'))
        save_btn.pack(side=tk.LEFT, padx=10)
        baseline_btn = tk.Button(btn_frame, text="Set as New Baseline", command=set_baseline_from_stocktake, width=20, font=('Arial', 10, 'bold'), fg='#cc6600')
        baseline_btn.pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Back", command=back, width=15, font=('Arial', 10)).pack(side=tk.LEFT, padx=10)

    def download_stock_count_sheet(self):
        """Generate and download a printable stock count sheet PDF."""
        try:
            self.refresh_data()

            if self.inventory_df.empty:
                messagebox.showwarning("No Data", "No inventory data available to generate stock count sheet.")
                return

            # Calculate transaction-based expected stock for the count sheet
            from reports import calculate_expected_remaining_series
            expected_remaining = calculate_expected_remaining_series(self.log_df)

            # Prepare inventory data for the count sheet
            inventory_data = []
            excluded_count = 0
            for _, row in self.inventory_df.iterrows():
                item_id = row[COL_ITEM_ID]

                # Skip excluded items (half pint, dash, coffee machine, etc.)
                if should_exclude(item_id):
                    excluded_count += 1
                    continue

                # Get category from data or use mapping
                category = row.get(COL_CATEGORY, '')
                if not category or category == 'Unknown':
                    category = get_category(item_id)

                # Transaction-based expected = current stock - expected remaining
                # (this is the opening stock / what stock should be before any new transactions)
                txn_expected = row[COL_QUANTITY] - expected_remaining.get(item_id, 0)

                inventory_data.append({
                    'item_id': item_id,
                    'item_name': row[COL_ITEM_NAME],
                    'current_stock': row[COL_QUANTITY],
                    'txn_expected': txn_expected,
                    'category': category
                })

            if not inventory_data:
                messagebox.showwarning("No Data", "No inventory items remain after filtering.")
                return

            # Create PDF
            pdf = PDFReport()
            pdf.generate_stock_count_sheet(inventory_data)

            # Generate timestamp for filename
            timestamp = datetime.now().strftime("%d%m%Y_%H%M%S")
            filename = f"Stock_Count_Sheet_{timestamp}.pdf"

            # Save to Downloads folder
            downloads_dir = os.path.expanduser('~/Downloads')
            filepath = os.path.join(downloads_dir, filename)
            pdf.output(filepath)

            messagebox.showinfo("Stock Count Sheet Generated",
                f"Stock count sheet saved to:\n{filepath}\n\n"
                f"This PDF contains:\n"
                f"• {len(inventory_data)} stock items organized by category\n"
                f"• {excluded_count} items excluded (half pints, dash, coffee, etc.)\n"
                f"• Items sorted alphabetically within each category\n"
                f"• Expected stock levels from the system\n"
                f"• Space to write your actual counts\n"
                f"• Space for notes\n\n"
                f"Print this sheet and use it to record your physical stock count, "
                f"then enter the results in the system.")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate stock count sheet: {e}")

    def view_delivery_history(self):
        """View and manage past deliveries."""
        self.clear_main_menu()

        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
        tk.Label(header_frame, text="Delivery History", font=('Arial', 16, 'bold')).pack(expand=True)

        self.refresh_data()

        # Main frame with two panes
        main_frame = tk.Frame(self.main_menu)
        main_frame.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

        # Left - Deliveries list
        left_frame = tk.LabelFrame(main_frame, text="Deliveries", font=('Arial', 10, 'bold'))
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 5))

        del_columns = ('timestamp', 'supplier', 'items', 'total_value')
        del_tree = ttk.Treeview(left_frame, columns=del_columns, show='headings', height=12)
        del_tree.heading('timestamp', text='Date / Time')
        del_tree.heading('supplier', text='Supplier')
        del_tree.heading('items', text='Items')
        del_tree.heading('total_value', text='Total Value')
        del_tree.column('timestamp', width=140, anchor='center')
        del_tree.column('supplier', width=120, anchor='center')
        del_tree.column('items', width=50, anchor='center')
        del_tree.column('total_value', width=100, anchor='center')
        del_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        del_scroll = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=del_tree.yview)
        del_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        del_tree.configure(yscrollcommand=del_scroll.set)

        # Right - Items in selected delivery
        right_frame = tk.LabelFrame(main_frame, text="Items in Selected Delivery", font=('Arial', 10, 'bold'))
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(5, 0))

        item_columns = ('item_id', 'item_name', 'quantity', 'cost_price', 'total')
        item_tree = ttk.Treeview(right_frame, columns=item_columns, show='headings', height=12)
        item_tree.heading('item_id', text='Item ID')
        item_tree.heading('item_name', text='Name')
        item_tree.heading('quantity', text='Qty')
        item_tree.heading('cost_price', text='Cost')
        item_tree.heading('total', text='Total')
        item_tree.column('item_id', width=80, anchor='center')
        item_tree.column('item_name', width=120, anchor='w')
        item_tree.column('quantity', width=60, anchor='center')
        item_tree.column('cost_price', width=70, anchor='center')
        item_tree.column('total', width=80, anchor='center')
        item_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        item_scroll = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=item_tree.yview)
        item_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        item_tree.configure(yscrollcommand=item_scroll.set)

        # Populate deliveries
        delivery_groups = {}
        if not self.log_df.empty and COL_ACTION in self.log_df.columns:
            deliveries = self.log_df[self.log_df[COL_ACTION] == ACTION_DELIVERY]
            for _, row in deliveries.iterrows():
                ts = row.get(COL_TIMESTAMP, '')
                if not ts:
                    continue
                if ts not in delivery_groups:
                    delivery_groups[ts] = {
                        'supplier': row.get(COL_SUPPLIER, '') if COL_SUPPLIER in row.index else '',
                        'items': [],
                    }
                delivery_groups[ts]['items'].append(row)

        for ts in sorted(delivery_groups.keys(), reverse=True):
            grp = delivery_groups[ts]
            items_count = len(grp['items'])
            total_val = sum(float(i.get(COL_COST_PRICE, 0)) * float(i.get(COL_QUANTITY, 0)) for i in grp['items'])
            supplier = grp['supplier'] if grp['supplier'] else 'Unknown'
            del_tree.insert('', tk.END, values=(ts, supplier, items_count, self.format_currency(total_val)), tags=(ts,))

        def on_delivery_select(event=None):
            for item in item_tree.get_children():
                item_tree.delete(item)
            selected = del_tree.selection()
            if not selected:
                return
            ts = del_tree.item(selected[0], 'tags')[0]
            if ts in delivery_groups:
                for row in delivery_groups[ts]['items']:
                    item_id = row.get(COL_ITEM_ID, '')
                    qty = float(row.get(COL_QUANTITY, 0))
                    cost = float(row.get(COL_COST_PRICE, 0))
                    # Convert per-unit cost to pack cost for display
                    from conversions import requires_conversion, get_conversion
                    display_cost = cost
                    if requires_conversion(item_id):
                        conv = get_conversion(item_id)
                        if conv:
                            display_cost = cost * conv[1]
                    name = ''
                    if not self.inventory_df.empty and item_id in self.inventory_df[COL_ITEM_ID].values:
                        name = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_ITEM_NAME].values[0]
                    item_tree.insert('', tk.END, values=(item_id, name, f"{qty:.1f}", self.format_currency(display_cost), self.format_currency(cost * qty)))

        del_tree.bind('<<TreeviewSelect>>', on_delivery_select)

        # Action buttons
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=10)

        def edit_selected_delivery():
            selected = del_tree.selection()
            if not selected:
                messagebox.showerror("Error", "Please select a delivery to edit.")
                return
            ts = del_tree.item(selected[0], 'tags')[0]
            if ts not in delivery_groups:
                return
            self.edit_delivery_dialog(ts, delivery_groups[ts])

        def delete_selected_delivery():
            selected = del_tree.selection()
            if not selected:
                messagebox.showerror("Error", "Please select a delivery to delete.")
                return
            ts = del_tree.item(selected[0], 'tags')[0]
            if ts not in delivery_groups:
                return
            grp = delivery_groups[ts]
            items_desc = "\n".join([f"  • {i.get(COL_ITEM_ID, '')}: {float(i.get(COL_QUANTITY, 0)):.1f}" for i in grp['items']])
            if messagebox.askyesno("Confirm Delete", f"Delete this delivery?\n\nDate: {ts}\nSupplier: {grp['supplier']}\nItems:\n{items_desc}"):
                self.delete_delivery(ts, grp['items'])
                self.view_delivery_history()

        tk.Button(btn_frame, text="Edit Selected", command=edit_selected_delivery, width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Delete Selected", command=delete_selected_delivery, width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack(side=tk.LEFT, padx=20)

    def edit_delivery_dialog(self, timestamp, delivery_group):
        """Open a dialog to edit a delivery's items."""
        top = tk.Toplevel(self.root)
        top.title(f"Edit Delivery - {timestamp}")
        top.geometry("500x400")
        top.transient(self.root)
        top.grab_set()
        top.lift()

        tk.Label(top, text=f"Editing Delivery: {timestamp}", font=('Arial', 12, 'bold')).pack(pady=10)
        tk.Label(top, text=f"Supplier: {delivery_group['supplier']}", font=('Arial', 10)).pack(pady=2)

        frame = tk.Frame(top)
        frame.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

        # Headers
        headers = ['Item', 'Quantity', 'Cost Price']
        for c, h in enumerate(headers):
            tk.Label(frame, text=h, font=('Arial', 9, 'bold')).grid(row=0, column=c, padx=5, pady=2)

        entries = []
        for r, row in enumerate(delivery_group['items'], start=1):
            item_id = row.get(COL_ITEM_ID, '')
            qty = float(row.get(COL_QUANTITY, 0))
            cost = float(row.get(COL_COST_PRICE, 0))

            # Convert per-unit cost to pack cost for display
            from conversions import requires_conversion, get_conversion
            if requires_conversion(item_id):
                conv = get_conversion(item_id)
                if conv:
                    cost = cost * conv[1]

            name = item_id
            if not self.inventory_df.empty and item_id in self.inventory_df[COL_ITEM_ID].values:
                name = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_ITEM_NAME].values[0]

            tk.Label(frame, text=f"{item_id} - {name}").grid(row=r, column=0, padx=5, pady=2, sticky='w')

            qty_var = tk.StringVar(value=f"{qty:.1f}")
            cost_var = tk.StringVar(value=f"{cost:.2f}")
            tk.Entry(frame, textvariable=qty_var, width=10).grid(row=r, column=1, padx=5, pady=2)
            tk.Entry(frame, textvariable=cost_var, width=10).grid(row=r, column=2, padx=5, pady=2)

            entries.append({'item_id': item_id, 'original_qty': qty, 'original_cost': cost,
                           'qty_var': qty_var, 'cost_var': cost_var})

        def save_edits():
            try:
                self.refresh_data()

                for e in entries:
                    new_qty = float(e['qty_var'].get().strip())
                    new_cost = float(e['cost_var'].get().strip())
                    if new_qty < 0:
                        messagebox.showerror("Error", "Quantity cannot be negative.", parent=top)
                        return
                    if new_cost < 0:
                        messagebox.showerror("Error", "Cost price cannot be negative.", parent=top)
                        return

                # Reverse original stock changes
                for e in entries:
                    item_id = e['item_id']
                    old_qty = e['original_qty']
                    self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] -= old_qty

                # Apply new values
                for e in entries:
                    item_id = e['item_id']
                    new_qty = float(e['qty_var'].get().strip())
                    new_cost = float(e['cost_var'].get().strip())
                    # Convert pack cost to per-unit cost if applicable
                    from conversions import requires_conversion, get_conversion
                    if requires_conversion(item_id):
                        conv = get_conversion(item_id)
                        if conv:
                            new_cost = new_cost / conv[1]
                    self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] += new_qty
                    self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_COST_PRICE] = new_cost

                # Update log entries
                mask = (self.log_df[COL_TIMESTAMP] == timestamp) & (self.log_df[COL_ACTION] == ACTION_DELIVERY)
                for e in entries:
                    item_id = e['item_id']
                    new_qty = float(e['qty_var'].get().strip())
                    new_cost = float(e['cost_var'].get().strip())
                    # Convert pack cost to per-unit cost if applicable
                    if requires_conversion(item_id):
                        conv = get_conversion(item_id)
                        if conv:
                            new_cost = new_cost / conv[1]
                    item_mask = mask & (self.log_df[COL_ITEM_ID] == item_id)
                    if item_mask.any():
                        self.log_df.loc[item_mask, COL_QUANTITY] = new_qty
                        self.log_df.loc[item_mask, COL_COST_PRICE] = new_cost

                if InventoryDataManager.save_inventory(self.inventory_df) and InventoryDataManager.save_log(self.log_df):
                    messagebox.showinfo("Success", "Delivery updated successfully.", parent=top)
                    top.destroy()
                    self.view_delivery_history()
                else:
                    messagebox.showerror("Error", "Failed to save changes.", parent=top)

            except ValueError:
                messagebox.showerror("Error", "Invalid number entered. Please check quantities and prices.", parent=top)
            except Exception as e:
                messagebox.showerror("Error", f"Update failed: {e}", parent=top)

        btn_frame = tk.Frame(top)
        btn_frame.pack(pady=15)
        tk.Button(btn_frame, text="Save Changes", command=save_edits, width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", command=top.destroy, width=15).pack(side=tk.LEFT, padx=5)

    def delete_delivery(self, timestamp, items):
        """Delete a delivery and reverse its stock changes."""
        try:
            self.refresh_data()

            for row in items:
                item_id = row.get(COL_ITEM_ID, '')
                qty = float(row.get(COL_QUANTITY, 0))
                if item_id and not self.inventory_df.empty and item_id in self.inventory_df[COL_ITEM_ID].values:
                    self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] -= qty

            # Remove log entries
            mask = (self.log_df[COL_TIMESTAMP] == timestamp) & (self.log_df[COL_ACTION] == ACTION_DELIVERY)
            self.log_df = self.log_df[~mask].reset_index(drop=True)

            if InventoryDataManager.save_inventory(self.inventory_df) and InventoryDataManager.save_log(self.log_df):
                messagebox.showinfo("Success", "Delivery deleted successfully.")
            else:
                messagebox.showerror("Error", "Failed to save after deletion.")

        except Exception as e:
            messagebox.showerror("Error", f"Delete failed: {e}")

    def generate_reports(self):
        """Generate and display various reports (GP%, surplus, draught yield)."""
        self.clear_main_menu()

        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)

        tk.Label(header_frame, text="Reports & Analytics",
                font=('Arial', 16, 'bold')).pack(expand=True)

        frame = tk.Frame(self.main_menu)
        frame.pack(pady=10, padx=20, fill='both', expand=True)

        buttons = [
            ("Gross Profit Report", self.generate_gp_report),
            ("Division Report", self.generate_division_report),
            ("Period Comparison Report", self.generate_comparison_report),
            ("Reorder Suggestions", self.generate_reorder_report),
            ("Stock Order Sheet", self.generate_stock_order_sheet),
            ("Surplus/Variance Report", self.generate_surplus_report),
            ("Draught Yield Report", self.generate_draught_yield_report),
            ("Stocktake Variance Report", self.generate_stocktake_report),
            ("Sales Trends & Analytics", self.generate_sales_analytics),
            ("Price History Report", self.generate_price_history_report),
            ("Transaction Log", self.view_transaction_log),
            ("Delivery History", self.view_delivery_history),
            ("Reconciliation Report", self.generate_reconciliation_report),
        ]

        for text, command in buttons:
            tk.Button(frame, text=text, command=command, width=30).pack(pady=5)

        # Download full report button
        download_frame = tk.Frame(self.main_menu)
        download_frame.pack(fill='x', padx=20, pady=20)

        tk.Label(download_frame, text="Download Comprehensive PDF Report",
                font=('Arial', 12, 'bold')).pack(pady=5)
        tk.Label(download_frame, text="Generate a formatted PDF report with sections, totals, and summary data").pack()

        tk.Button(download_frame, text="Download PDF Report", command=self.download_comprehensive_report,
                  width=25).pack(pady=10)

        # Back button
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=20)

        tk.Button(btn_frame, text="Back to Main Menu", command=self.create_main_menu, width=25).pack()

    def view_transaction_log(self):
        """View the complete transaction log."""
        self.clear_main_menu()

        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)

        tk.Label(header_frame, text="Transaction Log",
                font=('Arial', 16, 'bold')).pack(expand=True)

        frame = tk.Frame(self.main_menu)
        frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=10)

        try:
            self.refresh_data()

            # Create treeview
            columns = ('timestamp', 'item_id', 'action', 'quantity', 'cost_price', 'sell_price', 'total_value', 'date_range', 'reason')
            log_tree = ttk.Treeview(frame, columns=columns, show='headings')

            log_tree.heading('timestamp', text='Timestamp')
            log_tree.heading('item_id', text='Item ID')
            log_tree.heading('action', text='Action')
            log_tree.heading('quantity', text='Quantity')
            log_tree.heading('cost_price', text='Cost Price')
            log_tree.heading('sell_price', text='Sell Price')
            log_tree.heading('total_value', text='Total Value')
            log_tree.heading('date_range', text='Period')
            log_tree.heading('reason', text='Reason')

            log_tree.column('timestamp', width=120, anchor='center')
            log_tree.column('item_id', width=80, anchor='center')
            log_tree.column('action', width=100, anchor='center')
            log_tree.column('quantity', width=60, anchor='center')
            log_tree.column('cost_price', width=60, anchor='center')
            log_tree.column('sell_price', width=60, anchor='center')
            log_tree.column('total_value', width=60, anchor='center')
            log_tree.column('date_range', width=120, anchor='center')
            log_tree.column('reason', width=100, anchor='center')

            log_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=log_tree.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            log_tree.configure(yscrollcommand=scrollbar.set)

            # Sort by timestamp descending
            if not self.log_df.empty and COL_TIMESTAMP in self.log_df.columns:
                sorted_log = self.log_df.sort_values(by=COL_TIMESTAMP, ascending=False)
                for _, row in sorted_log.iterrows():
                    cost_price = row.get(COL_COST_PRICE, 0)
                    quantity = row.get(COL_QUANTITY, 0)
                    total_value = cost_price * quantity

                    values = (row.get(COL_TIMESTAMP, ''), row.get(COL_ITEM_ID, ''),
                             row.get(COL_ACTION, ''), f"{quantity:.1f}",
                             self.format_currency(cost_price), self.format_currency(row.get(COL_SELL_PRICE, 0)),
                             self.format_currency(total_value),
                             row.get(COL_DATE_RANGE, '') if COL_DATE_RANGE in row.index else '',
                             row.get(COL_REASON, '') if COL_REASON in row.index else '')

                    log_tree.insert('', tk.END, values=values)

                if self.log_df.empty:
                    tk.Label(self.main_menu, text="No transactions recorded yet.").pack(pady=20)

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")

        # Back button
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()

    def generate_gp_report(self):
        """Generate and display the Gross Profit report."""
        self.clear_main_menu()

        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)

        tk.Label(header_frame, text="Gross Profit Report",
                font=('Arial', 16, 'bold')).pack(expand=True)

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

            report_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=report_tree.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            report_tree.configure(yscrollcommand=scrollbar.set)

            # Configure alternating row colors
            report_tree.tag_configure('oddrow', background='#f9f9f9')
            report_tree.tag_configure('evenrow', background='#ffffff')

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
                    font=('Arial', 11, 'bold')).pack(pady=2)
            discount_pct = int(self.get_member_discount_pct())
            tk.Label(summary_frame, text=f"Overall Member GP: {self.format_currency(total_member_gp)} ({overall_member_gp_pct:.1f}%) ({discount_pct}% member discount applied)",
                    font=('Arial', 11, 'bold')).pack(pady=2)
            tk.Label(summary_frame, text=f"Overall Non-Member GP: {self.format_currency(total_non_member_gp)} ({overall_non_member_gp_pct:.1f}%)",
                    font=('Arial', 11, 'bold')).pack(pady=2)

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")

        # Back button
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()

    def generate_surplus_report(self):
        """Generate and display the Surplus/Variance Report."""
        self.clear_main_menu()

        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)

        tk.Label(header_frame, text="Surplus/Variance Report",
                font=('Arial', 16, 'bold')).pack(expand=True)

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

            report_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=report_tree.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            report_tree.configure(yscrollcommand=scrollbar.set)

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

    def generate_division_report(self):
        """Generate and display sales by Division/Category report."""
        self.clear_main_menu()

        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)

        tk.Label(header_frame, text="Division Report",
                font=('Arial', 16, 'bold')).pack(expand=True)

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

            report_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

            scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=report_tree.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            report_tree.configure(yscrollcommand=scrollbar.set)

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

            tk.Label(summary_frame, text=f"Total Revenue: {self.format_currency(total_revenue)}", font=('Arial', 11)).pack(pady=2)
            tk.Label(summary_frame, text=f"Overall Retail GP: {self.format_currency(total_gp)} ({overall_gp_pct:.1f}%)", font=('Arial', 11, 'bold')).pack(pady=2)
            tk.Label(summary_frame, text=f"Overall Member GP: {self.format_currency(total_member_gp)} ({overall_member_gp_pct:.1f}%)", font=('Arial', 11, 'bold')).pack(pady=2)
            tk.Label(summary_frame, text=f"Overall Non-Member GP: {self.format_currency(total_non_member_gp)} ({overall_non_member_gp_pct:.1f}%)", font=('Arial', 11, 'bold')).pack(pady=2)

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")

        # Back button
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=10)

        tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()

    def generate_draught_yield_report(self):
        """Generate and display the Draught Yield Report."""
        self.clear_main_menu()

        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)

        tk.Label(header_frame, text="Draught Yield Report",
                font=('Arial', 16, 'bold')).pack(expand=True)

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

            report_tree.tag_configure('yield_warning', background='#f8d7da')
            report_tree.tag_configure('loss_warning', background='#fff3cd')

            report_tree.tag_configure('yield_warning', background='#f8d7da')

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
                font=('Arial', 16, 'bold')).pack(expand=True)

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
                # Keep only the most recent entry per item_id
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

            report_tree.tag_configure('high_variance', background='#f8d7da')
            report_tree.tag_configure('med_variance', background='#fff3cd')
            report_tree.tag_configure('no_stocktake', foreground='#999999')

            # Summary label
            st_items = report_df[report_df['has_stocktake'] == True]
            if not st_items.empty:
                total_var_val = st_items['variance_value'].sum()
                total_var_pct = (st_items['variance'].sum() / st_items['expected_quantity'].sum() * 100) if st_items['expected_quantity'].sum() > 0 else 0
                summary_text = f"Total Variance Value: £{total_var_val:+.2f}  |  Total Variance %: {total_var_pct:+.1f}%  |  Items counted: {len(st_items)} / {len(report_df)}"
                tk.Label(self.main_menu, text=summary_text, font=('Arial', 10, 'bold')).pack(pady=(5, 0))

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
                font=('Arial', 16, 'bold')).pack(expand=True)

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

            summary_text = tk.Text(frame, wrap=tk.WORD, height=16, font=('Arial', 10), bg='white', fg='black')
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

    def generate_price_history_report(self):
        """Generate and display price history report from delivery transactions."""
        self.clear_main_menu()

        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)

        tk.Label(header_frame, text="Price History Report",
                font=('Arial', 16, 'bold')).pack(expand=True)

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
                    self.set_font('Arial', 'B', 16)
                    self.set_text_color(40, 40, 40)
                    self.cell(0, 10, 'Prestonfield Golf Club - Price History Report', 0, 1, 'C')
                    self.set_font('Arial', '', 10)
                    self.set_text_color(100, 100, 100)
                    self.cell(0, 5, f'Generated: {datetime.now().strftime("%d %B %Y at %H:%M")}', 0, 1, 'C')
                    self.ln(5)

                def footer(self):
                    self.set_y(-15)
                    self.set_font('Arial', 'I', 8)
                    self.set_text_color(128, 128, 128)
                    self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

            pdf = PriceHistoryPDF()
            pdf.add_page()
            pdf.set_font('Arial', '', 9)

            # Table header
            pdf.set_fill_color(240, 240, 240)
            pdf.set_font('Arial', 'B', 9)
            headers = ['Item', 'Date', 'Supplier', 'Cost Price', 'Previous', 'Change']
            widths = [60, 35, 35, 28, 28, 28]
            for h, w in zip(headers, widths):
                pdf.cell(w, 8, h, 1, 0, 'C', True)
            pdf.ln()

            pdf.set_font('Arial', '', 9)
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
                font=('Arial', 16, 'bold')).pack(expand=True)

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

        tk.Button(btn_frame, text="Back to Menu", command=self.create_main_menu, width=15).pack()

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
        tk.Label(table_frame, text="Sales by Category", font=('Arial', 12, 'bold')).pack(pady=5)

        tree = ttk.Treeview(table_frame, columns=('category', 'quantity', 'items'), show='headings', height=8)
        tree.heading('category', text='Category')
        tree.heading('quantity', text='Total Quantity')
        tree.heading('items', text='Unique Items')
        tree.column('category', width=100, anchor='center')
        tree.column('quantity', width=100, anchor='center')
        tree.column('items', width=100, anchor='center')

        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')

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
        left_frame = tk.LabelFrame(tab, text="Fast Movers (Top 10)", font=('Arial', 10, 'bold'))
        left_frame.pack(side='left', fill='both', expand=True, padx=5, pady=5)

        right_frame = tk.LabelFrame(tab, text="Slow Movers (Bottom 10)", font=('Arial', 10, 'bold'))
        right_frame.pack(side='right', fill='both', expand=True, padx=5, pady=5)

        # Fast movers table
        fast_tree = ttk.Treeview(left_frame, columns=('name', 'category', 'sales'), show='headings')
        fast_tree.heading('name', text='Item Name')
        fast_tree.heading('category', text='Category')
        fast_tree.heading('sales', text='Sales Qty')
        fast_tree.column('name', width=150, anchor='w')
        fast_tree.column('category', width=80, anchor='center')
        fast_tree.column('sales', width=80, anchor='center')

        fast_scroll = ttk.Scrollbar(left_frame, orient='vertical', command=fast_tree.yview)
        fast_tree.configure(yscrollcommand=fast_scroll.set)
        fast_tree.pack(side='left', fill='both', expand=True)
        fast_scroll.pack(side='right', fill='y')

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
        slow_tree.column('name', width=150, anchor='w')
        slow_tree.column('category', width=80, anchor='center')
        slow_tree.column('sales', width=80, anchor='center')

        slow_scroll = ttk.Scrollbar(right_frame, orient='vertical', command=slow_tree.yview)
        slow_tree.configure(yscrollcommand=slow_scroll.set)
        slow_tree.pack(side='left', fill='both', expand=True)
        slow_scroll.pack(side='right', fill='y')

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
                    font=('Arial', 10)).pack(anchor='w', pady=2)
            tk.Label(stats_frame, text=f"Highest Daily Sales: {max_daily:.1f} units",
                    font=('Arial', 10)).pack(anchor='w', pady=2)
            tk.Label(stats_frame, text=f"Lowest Daily Sales: {min_daily:.1f} units",
                    font=('Arial', 10)).pack(anchor='w', pady=2)

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
        tk.Label(table_frame, text="Profit Analysis by Category", font=('Arial', 11, 'bold')).pack(pady=5)

        tree = ttk.Treeview(table_frame, columns=('category', 'profit', 'margin', 'quantity'), show='headings')
        tree.heading('category', text='Category')
        tree.heading('profit', text='Total Profit (£)')
        tree.heading('margin', text='Avg Margin (%)')
        tree.heading('quantity', text='Qty Sold')
        tree.column('category', width=100, anchor='center')
        tree.column('profit', width=120, anchor='center')
        tree.column('margin', width=100, anchor='center')
        tree.column('quantity', width=80, anchor='center')

        scrollbar = ttk.Scrollbar(table_frame, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)

        tree.pack(side='left', fill='x', expand=True)
        scrollbar.pack(side='right', fill='y')

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
            tk.Label(header_frame, text="Reorder Suggestions", font=('Arial', 16, 'bold')).pack(expand=True)

            frame = tk.Frame(self.main_menu)
            frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=10)

            self.refresh_data()
            report_data = build_reorder_report_data(self.inventory_df, self.log_df)

            if not report_data:
                tk.Label(frame, text="No items need reordering. All stock is above reorder level.",
                        font=('Arial', 12)).pack(pady=20)
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
                    font=('Arial', 11, 'bold')).pack(pady=5)

        except Exception as e:
            messagebox.showerror("Error", f"An error occurred: {e}")

        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Back", command=self.generate_reports, width=15).pack()

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
            tk.Label(header_frame, text="Period Comparison Report", font=('Arial', 16, 'bold')).pack(expand=True)

            if start_a and end_a:
                period_a_text = f"{start_a.strftime('%d/%m/%Y')} - {end_a.strftime('%d/%m/%Y')}"
            else:
                period_a_text = "All Time"
            if start_b and end_b:
                period_b_text = f"{start_b.strftime('%d/%m/%Y')} - {end_b.strftime('%d/%m/%Y')}"
            else:
                period_b_text = "All Time"

            period_label = tk.Label(self.main_menu,
                    text=f"Period A: {period_a_text}  |  Period B: {period_b_text}",
                    font=('Arial', 10))
            period_label.pack(pady=5)

            frame = tk.Frame(self.main_menu)
            frame.pack(pady=10, fill=tk.BOTH, expand=True, padx=10)

            if report_df.empty:
                tk.Label(frame, text="No sales data found for the selected periods.",
                        font=('Arial', 12)).pack(pady=20)
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
                    font=('Arial', 11, 'bold')).pack(pady=5)

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

            # Date range filter
            dialog = DateRangeDialog(self.root, title="Comprehensive PDF Report - Date Range")
            if dialog.result is None:
                return
            if dialog.result == 'ALL_TIME':
                filtered_log = full_log_df.copy()
                start_date, end_date = None, None
            else:
                start_date, end_date = dialog.result
                filtered_log = filter_log_by_date(full_log_df, start_date, end_date)

            # Load latest stocktake data for meaningful variance calculation
            stocktake_rows = get_stocktake_history(limit=1000)
            stocktake_map = {}
            stocktake_data = None
            if stocktake_rows:
                st_df = pd.DataFrame([dict(row) for row in stocktake_rows])
                st_df = st_df.sort_values('timestamp', ascending=False)
                st_df = st_df.drop_duplicates(subset='item_id', keep='first')
                stocktake_map = {
                    row['item_id']: {
                        'counted_quantity': row['counted_quantity'],
                        'expected_quantity': row['expected_quantity'],
                        'variance': row['variance'],
                    }
                    for _, row in st_df.iterrows()
                }
                from reports import build_stocktake_variance_report
                stocktake_data = build_stocktake_variance_report(self.inventory_df, full_log_df, st_df)

            # Compute historical closing stock at end_date for date-range consistency.
            # If a stocktake exists on or before the end date, use its counted quantities
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
                                p_end = datetime.strptime(parts[1].strip(), '%d/%m/%Y').replace(hour=23, minute=59, second=59)
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
            pdf.generate_report(report_data, member_discount_pct=int(self.get_member_discount_pct()), stocktake_data=stocktake_data)

            # Generate timestamp for filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"Bar_Stock_Full_Report_{timestamp}.pdf"

            # Save to Downloads folder
            downloads_dir = os.path.expanduser('~/Downloads')
            filepath = os.path.join(downloads_dir, filename)
            pdf.output(filepath)

            messagebox.showinfo("Report Generated", f"Comprehensive PDF report saved to:\n{filepath}\n\nThe report includes:\n• Stock Summary by Division\n• Sales Performance\n• Wastage & Complimentary Summary\n• Draught Yield Report\n• Financial Summary with Totals\n• Stocktake Variance Report (if recorded)")

        except Exception as e:
            messagebox.showerror("Error", f"Failed to generate report: {e}")

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

                    # Create item_id from name (lowercase, no spaces)
                    item_id = item_name.lower().replace(' ', '_').replace('-', '_')

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
                        # Add new item (price_locked defaults to False)
                        new_item = pd.DataFrame([[item_id, item_name, total_stock, cost_price, sell_price, measure, category, False, division]],
                                              columns=[COL_ITEM_ID, COL_ITEM_NAME, COL_QUANTITY, COL_COST_PRICE, COL_SELL_PRICE, COL_MEASURE, COL_CATEGORY, COL_PRICE_LOCKED, COL_DIVISION])
                        self.inventory_df = pd.concat([self.inventory_df, new_item], ignore_index=True)
                        items_added += 1

                except Exception as item_error:
                    errors.append(f"Error processing '{row.get('Name', 'Unknown')}': {item_error}")

            # Save inventory
            if InventoryDataManager.save_inventory(self.inventory_df):
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

        except Exception as e:
            messagebox.showerror("Error", f"Failed to initialize stock: {e}")

    def open_settings(self):
        """Open the settings dialog."""
        top = tk.Toplevel(self.root)
        top.title("Settings")
        top.geometry("400x250")
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

        tk.Label(main_frame, text="Settings", font=('Arial', 14, 'bold')).pack(pady=(0, 15))

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
                    messagebox.showinfo("Success", "Settings saved successfully.")
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
            # Confirm again for safety
            if not messagebox.askyesno("Final Confirmation",
                "This action cannot be undone.\n\n"
                "All transaction data, stocktake snapshots, and archived transactions will be permanently deleted.\n\n"
                "Do you want to proceed?"):
                return

            # Clear the transaction log - keep only the column structure
            self.log_df = pd.DataFrame(columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY,
                                                COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON, COL_MEMBER_QTY, COL_NON_MEMBER_QTY])

            # Save the empty log and clear historical data
            log_saved = InventoryDataManager.save_log(self.log_df)
            snapshots_cleared = clear_stocktake_snapshots()
            archive_cleared = clear_transaction_archive()

            if log_saved and snapshots_cleared and archive_cleared:
                messagebox.showinfo("Reset Complete",
                    "System has been reset successfully.\n\n"
                    "All transaction history, stocktake snapshots, and archived transactions have been cleared.\n"
                    "Stock items have been preserved.")
            else:
                messagebox.showerror("Error", "Failed to complete reset. Some historical data may remain.")

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

            tk.Label(dialog, text="Select a backup to restore:", font=('Arial', 12, 'bold')).pack(pady=10)

            tree = ttk.Treeview(dialog, columns=('timestamp', 'name', 'size'), show='headings', height=10)
            tree.heading('timestamp', text='Date/Time')
            tree.heading('name', text='Backup Name')
            tree.heading('size', text='Size (KB)')
            tree.column('timestamp', width=150)
            tree.column('name', width=300)
            tree.column('size', width=80, anchor='center')
            tree.pack(fill='both', expand=True, padx=10, pady=5)

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

                if restore_backup(backup_path):
                    self.inventory_df = InventoryDataManager.load_inventory()
                    self.log_df = InventoryDataManager.load_log()
                    self.update_dashboard_stats()
                    messagebox.showinfo("Success", "Database restored successfully!")
                    dialog.destroy()
                else:
                    messagebox.showerror("Error", "Restore failed.")

            btn_frame = tk.Frame(dialog)
            btn_frame.pack(pady=10)
            tk.Button(btn_frame, text="Restore Selected", command=do_restore, width=15).pack(side=tk.LEFT, padx=5)
            tk.Button(btn_frame, text="Cancel", command=dialog.destroy, width=15).pack(side=tk.LEFT, padx=5)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to open restore dialog: {e}")

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
                date_range_str = f"{start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}"

            # Duplicate guard
            with open(filepath, 'rb') as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
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

            # Detect and strip composite EPOS files that append a second report
            with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                raw_lines = f.readlines()

            clean_lines = []
            for i, line in enumerate(raw_lines):
                # Check for the start of the second report section (different column format)
                if line.strip().startswith('"Name') or line.strip().startswith('Name\n'):
                    # Look ahead to verify it's the detailed transaction header
                    remaining = ''.join(raw_lines[i:i+5])
                    if 'Payment Method' in remaining or 'Date\n' in remaining or 'Subtotal' in remaining:
                        break
                clean_lines.append(line)

            if len(clean_lines) < len(raw_lines):
                print(f"Stripped {len(raw_lines) - len(clean_lines)} lines from composite report (detailed section removed).")

            from io import StringIO
            sales_df = pd.read_csv(StringIO(''.join(clean_lines)), compression=None)
            sales_df.columns = [col.strip() for col in sales_df.columns]

            if 'Product' not in sales_df.columns:
                messagebox.showerror("Invalid CSV", "Sales report must have a 'Product' column.")
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
                if 'member' in col_lower and 'qty' in col_lower:
                    if 'non' in col_lower:
                        non_member_qty_col = col
                    else:
                        member_qty_col = col

            # Parse CSV into preview data without modifying inventory
            self.refresh_data()
            preview_items = []
            skipped_items = []
            total_revenue = 0
            total_cost = 0

            for _, row in sales_df.iterrows():
                try:
                    product_name = str(row['Product']).strip()
                    if not product_name or product_name.lower() == 'nan' or product_name.lower() == 'total':
                        continue
                    try:
                        quantity = float(row[qty_col]) if pd.notna(row[qty_col]) else 0
                    except:
                        quantity = 0
                    if quantity <= 0:
                        continue

                    try:
                        member_qty = float(row[member_qty_col]) if member_qty_col and pd.notna(row[member_qty_col]) else None
                    except:
                        member_qty = None
                    try:
                        non_member_qty = float(row[non_member_qty_col]) if non_member_qty_col and pd.notna(row[non_member_qty_col]) else None
                    except:
                        non_member_qty = None

                    item_id = normalize_product_name(product_name)
                    item_id = resolve_epos_item_id(item_id)

                    if item_id not in self.inventory_df[COL_ITEM_ID].values:
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

                    if should_exclude(item_id) and not has_parent_stock(item_id):
                        skipped_items.append(f"{product_name} (excluded)")
                        continue

                    item_row = self.inventory_df[self.inventory_df[COL_ITEM_ID] == item_id].iloc[0]
                    cost_price = get_effective_cost_price(item_id, self.inventory_df, COL_ITEM_ID, COL_COST_PRICE)
                    sell_price = item_row[COL_SELL_PRICE]
                    current_qty = item_row[COL_QUANTITY]
                    projected = current_qty - quantity

                    # Use the CSV's own gross total (after discount, incl. VAT) for revenue.
                    # This matches the EPOS 'Totals' column the user expects.
                    csv_total = row.get('Totals')
                    try:
                        csv_revenue = float(csv_total) if pd.notna(csv_total) else None
                    except Exception:
                        csv_revenue = None
                    line_revenue = csv_revenue if csv_revenue is not None and csv_revenue >= 0 else quantity * sell_price

                    preview_items.append({
                        'item_id': item_id,
                        'name': item_row[COL_ITEM_NAME],
                        'qty': quantity,
                        'current': current_qty,
                        'projected': projected,
                        'cost': cost_price,
                        'sell': sell_price,
                        'csv_revenue': csv_revenue,
                        'revenue': line_revenue,
                        'cost_total': quantity * cost_price,
                        'member_qty': member_qty,
                        'non_member_qty': non_member_qty,
                        'has_parent': has_parent_stock(item_id)
                    })
                    total_revenue += line_revenue
                    total_cost += quantity * cost_price

                except Exception as item_error:
                    skipped_items.append(f"{row.get('Product', 'Unknown')}: {item_error}")

            if not preview_items:
                messagebox.showwarning("No Transactions", "No valid transactions found in the CSV file.")
                return

            # Negative stock guard: block unless allow_negative is True
            blocking_negative = []
            warning_negative = []
            for p in preview_items:
                if p['projected'] < 0 and not p['has_parent']:
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

            tk.Label(dialog, text=f"Sales Upload Preview  |  Period: {date_range_str}",
                    font=('Arial', 12, 'bold')).pack(pady=10)

            summary_frame = tk.Frame(dialog)
            summary_frame.pack(fill='x', padx=10, pady=5)
            tk.Label(summary_frame, text=f"Items: {len(preview_items)}  |  Revenue: £{total_revenue:,.2f}  |  GP: £{total_revenue - total_cost:,.2f}  |  Skipped: {len(skipped_items)}",
                    font=('Arial', 10)).pack()

            tree_frame = tk.Frame(dialog)
            tree_frame.pack(fill='both', expand=True, padx=10, pady=5)

            tree = ttk.Treeview(tree_frame, columns=('name', 'qty', 'current', 'projected', 'revenue'), show='headings', height=15)
            tree.heading('name', text='Item')
            tree.heading('qty', text='Qty Sold')
            tree.heading('current', text='Current Stock')
            tree.heading('projected', text='After Upload')
            tree.heading('revenue', text='Revenue')
            tree.column('name', width=220)
            tree.column('qty', width=100, anchor='center')
            tree.column('current', width=110, anchor='center')
            tree.column('projected', width=110, anchor='center')
            tree.column('revenue', width=90, anchor='e')
            tree.pack(side=tk.LEFT, fill='both', expand=True)

            sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
            sb.pack(side=tk.RIGHT, fill=tk.Y)
            tree.configure(yscrollcommand=sb.set)

            for p in preview_items:
                tag = 'negative' if p['projected'] < 0 and not p['has_parent'] else ''
                current_display = format_quantity_display(p['item_id'], p['current'])
                projected_display = format_quantity_display(p['item_id'], p['projected'])
                qty_display = format_quantity_display(p['item_id'], p['qty'])
                tree.insert('', tk.END, values=(p['name'], qty_display, current_display,
                                               projected_display, f"£{p['revenue']:.2f}"), tags=(tag,))
            tree.tag_configure('negative', foreground='red', font=('Arial', 9, 'bold'))

            def confirm_upload():
                dialog.destroy()
                self._apply_sales_upload(preview_items, skipped_items, file_hash, filepath, date_range_str, len(sales_df))

            def cancel_upload():
                dialog.destroy()
                messagebox.showinfo("Cancelled", "Upload cancelled. No changes were made.")

            btn_frame = tk.Frame(dialog)
            btn_frame.pack(pady=15)
            tk.Button(btn_frame, text="Confirm Upload", command=confirm_upload, width=15, bg='green', fg='white').pack(side=tk.LEFT, padx=10)
            tk.Button(btn_frame, text="Cancel", command=cancel_upload, width=15).pack(side=tk.LEFT, padx=10)

        except Exception as e:
            messagebox.showerror("Error", f"Failed to upload sales report: {e}")

    def _apply_sales_upload(self, preview_items, skipped_items, file_hash, filepath, date_range_str, total_row_count):
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

            for p in preview_items:
                item_id = p['item_id']
                quantity = p['qty']
                cost_price = p['cost']
                sell_price = p['sell']
                member_qty = p['member_qty']
                non_member_qty = p['non_member_qty']

                parent_adjustments = []
                if has_parent_stock(item_id):
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

                # Store the CSV's actual gross line revenue as the effective sell price,
                # so reports match the source CSV 'Totals' column.
                effective_sell_price = p.get('csv_revenue', quantity * sell_price) / quantity if quantity > 0 else sell_price
                if not (effective_sell_price > 0 and p.get('csv_revenue') is not None):
                    effective_sell_price = sell_price

                new_log_entry = pd.DataFrame([[item_id, ACTION_SALES, quantity, timestamp, cost_price, effective_sell_price, "", date_range_str, "", member_qty, non_member_qty]],
                                              columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON, COL_MEMBER_QTY, COL_NON_MEMBER_QTY])
                self.log_df = pd.concat([self.log_df, new_log_entry], ignore_index=True)

                for parent_id, deduction, desc in parent_adjustments:
                    parent_row = self.inventory_df[self.inventory_df[COL_ITEM_ID] == parent_id].iloc[0]
                    parent_cost = parent_row[COL_COST_PRICE]
                    parent_sell = parent_row[COL_SELL_PRICE]
                    parent_log_entry = pd.DataFrame([[parent_id, ACTION_PARENT_STOCK_ADJ, deduction, timestamp, parent_cost, parent_sell, f"From {item_id}", date_range_str, "", 0, 0]],
                                                      columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON, COL_MEMBER_QTY, COL_NON_MEMBER_QTY])
                    self.log_df = pd.concat([self.log_df, parent_log_entry], ignore_index=True)

                transactions.append(f"{p['name']}: {quantity:.1f} units")

            if InventoryDataManager.save_inventory(self.inventory_df) and InventoryDataManager.save_log(self.log_df):
                self.update_dashboard_stats()
                add_upload_hash(file_hash, os.path.basename(filepath), datetime.now().isoformat(), date_range_str, total_row_count, 'sales')

                success_msg = f"Sales report uploaded successfully!\n\nBackup created before upload.\n\n"
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
            else:
                messagebox.showerror("Error", "Failed to save transactions.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to apply sales upload: {e}")

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
                date_range_str = f"{start_date.strftime('%d/%m/%Y')} - {end_date.strftime('%d/%m/%Y')}"

            # Duplicate guard
            with open(filepath, 'rb') as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
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

            comp_df = pd.read_csv(filepath, compression=None)
            comp_df.columns = [col.strip() for col in comp_df.columns]

            if 'Product' not in comp_df.columns:
                messagebox.showerror("Invalid CSV", "Complimentary report must have a 'Product' column.")
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

                    try:
                        quantity = float(row[qty_col]) if pd.notna(row[qty_col]) else 0
                    except:
                        quantity = 0
                    if quantity <= 0:
                        continue

                    item_id = normalize_product_name(product_name)
                    item_id = resolve_epos_item_id(item_id)

                    if item_id not in self.inventory_df[COL_ITEM_ID].values:
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

                    if should_exclude(item_id) and not has_parent_stock(item_id):
                        skipped_items.append(f"{product_name} (excluded)")
                        continue

                    item_row = self.inventory_df[self.inventory_df[COL_ITEM_ID] == item_id].iloc[0]
                    cost_price = get_effective_cost_price(item_id, self.inventory_df, COL_ITEM_ID, COL_COST_PRICE)
                    current_qty = item_row[COL_QUANTITY]
                    projected = current_qty - quantity

                    preview_items.append({
                        'item_id': item_id,
                        'name': item_row[COL_ITEM_NAME],
                        'qty': quantity,
                        'current': current_qty,
                        'projected': projected,
                        'cost': cost_price,
                        'cost_total': quantity * cost_price,
                        'has_parent': has_parent_stock(item_id)
                    })
                    total_cost += quantity * cost_price

                except Exception as item_error:
                    skipped_items.append(f"{row.get('Product', 'Unknown')}: {item_error}")

            if not preview_items:
                messagebox.showwarning("No Transactions", "No valid transactions found in the CSV file.")
                return

            # Negative stock warning
            negative_count = sum(1 for p in preview_items if p['projected'] < 0 and not p['has_parent'])
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

            tk.Label(dialog, text=f"Complimentary Upload Preview  |  Period: {date_range_str}",
                     font=('Arial', 12, 'bold')).pack(pady=10)

            summary_frame = tk.Frame(dialog)
            summary_frame.pack(fill='x', padx=10, pady=5)
            tk.Label(summary_frame, text=f"Items: {len(preview_items)}  |  Total Cost: £{total_cost:,.2f}  |  Skipped: {len(skipped_items)}",
                     font=('Arial', 10)).pack()

            tree_frame = tk.Frame(dialog)
            tree_frame.pack(fill='both', expand=True, padx=10, pady=5)

            tree = ttk.Treeview(tree_frame, columns=('name', 'qty', 'current', 'projected', 'cost'), show='headings', height=15)
            tree.heading('name', text='Item')
            tree.heading('qty', text='Qty')
            tree.heading('current', text='Current Stock')
            tree.heading('projected', text='After Upload')
            tree.heading('cost', text='Cost Impact')
            tree.column('name', width=250)
            tree.column('qty', width=80, anchor='center')
            tree.column('current', width=100, anchor='center')
            tree.column('projected', width=100, anchor='center')
            tree.column('cost', width=100, anchor='e')
            tree.pack(side=tk.LEFT, fill='both', expand=True)

            sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
            sb.pack(side=tk.RIGHT, fill=tk.Y)
            tree.configure(yscrollcommand=sb.set)

            for p in preview_items:
                tag = 'negative' if p['projected'] < 0 and not p['has_parent'] else ''
                tree.insert('', tk.END, values=(p['name'], f"{p['qty']:.1f}", f"{p['current']:.1f}",
                                               f"{p['projected']:.1f}", f"£{p['cost_total']:.2f}"), tags=(tag,))
            tree.tag_configure('negative', foreground='red', font=('Arial', 9, 'bold'))

            def confirm_upload():
                dialog.destroy()
                self._apply_complimentary_upload(preview_items, skipped_items, file_hash, filepath, date_range_str, len(comp_df))

            def cancel_upload():
                dialog.destroy()
                messagebox.showinfo("Cancelled", "Upload cancelled. No changes were made.")

            btn_frame = tk.Frame(dialog)
            btn_frame.pack(pady=15)
            tk.Button(btn_frame, text="Confirm Upload", command=confirm_upload, width=15, bg='green', fg='white').pack(side=tk.LEFT, padx=10)
            tk.Button(btn_frame, text="Cancel", command=cancel_upload, width=15).pack(side=tk.LEFT, padx=10)

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
                if has_parent_stock(item_id):
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

            if InventoryDataManager.save_inventory(self.inventory_df) and InventoryDataManager.save_log(self.log_df):
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
                self.create_main_menu()
            else:
                messagebox.showerror("Error", "Failed to save transactions.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to apply complimentary upload: {e}")


if __name__ == "__main__":
    root = tk.Tk()
    app = BarStockManagementSystem(root)
    root.mainloop()
