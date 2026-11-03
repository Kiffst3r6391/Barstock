#!/usr/bin/env python3
"""Shared Tk dialogs used by more than one screen."""

from datetime import datetime, timedelta

import tkinter as tk
from tkinter import messagebox, ttk

import ui_theme
from conversions import DATE_FORMAT_DISPLAY, parse_display_date

try:
    from tkcalendar import Calendar
    TKCALENDAR_AVAILABLE = True
except ImportError:
    TKCALENDAR_AVAILABLE = False


class DateRangeDialog:
    """Reusable date range picker dialog with interactive calendars."""

    def __init__(self, parent, title="Select Date Range", default_start=None, default_end=None):
        self.parent = parent
        self.title = title
        self.result = None
        self.default_start = default_start
        self.default_end = default_end

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

        tk.Label(frame, text=title, font=(ui_theme.THEME_FONT, 12, 'bold')).pack(pady=(0, 5))

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
            start_frame = tk.LabelFrame(calendars_frame, text="Start Date", font=(ui_theme.THEME_FONT, 9, 'bold'))
            start_frame.pack(side='left', fill='both', expand=True, padx=(0, 10))
            self.start_cal = Calendar(start_frame, selectmode='day', date_pattern='dd-mm-y', font=(ui_theme.THEME_FONT, 16),
                                       background=ui_theme.THEME_CARD, normalbackground=ui_theme.THEME_CARD, weekendbackground=ui_theme.THEME_SIDEBAR,
                                       othermonthbackground=ui_theme.THEME_BG, othermonthwebackground=ui_theme.THEME_SIDEBAR,
                                       foreground=ui_theme.THEME_TEXT, normalforeground=ui_theme.THEME_TEXT, weekendforeground=ui_theme.THEME_TEXT,
                                       othermonthforeground=ui_theme.THEME_TEXT_MUTED, othermonthweforeground=ui_theme.THEME_TEXT_MUTED,
                                       selectbackground=ui_theme.THEME_ACCENT, selectforeground=ui_theme.THEME_ACCENT_INK, headersbackground=ui_theme.THEME_SIDEBAR, headersforeground=ui_theme.THEME_TEXT)
            self.start_cal.pack(padx=5, pady=5)

            # End calendar
            end_frame = tk.LabelFrame(calendars_frame, text="End Date", font=(ui_theme.THEME_FONT, 9, 'bold'))
            end_frame.pack(side='left', fill='both', expand=True, padx=(10, 0))
            self.end_cal = Calendar(end_frame, selectmode='day', date_pattern='dd-mm-y', font=(ui_theme.THEME_FONT, 16),
                                     background=ui_theme.THEME_CARD, normalbackground=ui_theme.THEME_CARD, weekendbackground=ui_theme.THEME_SIDEBAR,
                                     othermonthbackground=ui_theme.THEME_BG, othermonthwebackground=ui_theme.THEME_SIDEBAR,
                                     foreground=ui_theme.THEME_TEXT, normalforeground=ui_theme.THEME_TEXT, weekendforeground=ui_theme.THEME_TEXT,
                                     othermonthforeground=ui_theme.THEME_TEXT_MUTED, othermonthweforeground=ui_theme.THEME_TEXT_MUTED,
                                     selectbackground=ui_theme.THEME_ACCENT, selectforeground=ui_theme.THEME_ACCENT_INK, headersbackground=ui_theme.THEME_SIDEBAR, headersforeground=ui_theme.THEME_TEXT)
            self.end_cal.pack(padx=5, pady=5)

            # Apply caller-supplied defaults if present
            if self.default_start is not None:
                self.start_cal.selection_set(self.default_start)
            if self.default_end is not None:
                self.end_cal.selection_set(self.default_end)

            # Selected dates display
            self.dates_label = tk.Label(frame, text="", font=(ui_theme.THEME_FONT, 10))
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
            if self.default_start is not None:
                self.start_var.set(self.default_start.strftime(DATE_FORMAT_DISPLAY))
            tk.Entry(date_frame, textvariable=self.start_var, width=15).grid(row=0, column=1, padx=5, pady=5)
            tk.Label(date_frame, text="DD-MM-YYYY").grid(row=0, column=2, padx=5, pady=5, sticky='w')

            tk.Label(date_frame, text="End:").grid(row=1, column=0, padx=5, pady=5, sticky='e')
            self.end_var = tk.StringVar()
            if self.default_end is not None:
                self.end_var.set(self.default_end.strftime(DATE_FORMAT_DISPLAY))
            tk.Entry(date_frame, textvariable=self.end_var, width=15).grid(row=1, column=1, padx=5, pady=5)
            tk.Label(date_frame, text="DD-MM-YYYY").grid(row=1, column=2, padx=5, pady=5, sticky='w')

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
            self.start_var.set(start.strftime(DATE_FORMAT_DISPLAY))
            self.end_var.set(end.strftime(DATE_FORMAT_DISPLAY))

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
            start_date = parse_display_date(start_str) if start_str else None
            end_date = parse_display_date(end_str) if end_str else None
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
