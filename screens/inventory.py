#!/usr/bin/env python3
"""Stock management and delivery history screens."""

import os
from datetime import datetime

import pandas as pd
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import ui_theme
from ui_theme import (
    THEME_ACCENT, THEME_BG, THEME_BORDER, THEME_CARD, THEME_DANGER,
    THEME_TEXT, THEME_TEXT_MUTED, TBL_ROW_ALT, TBL_ROW_WARN, TBL_ROW_DANGER,
)
from app_config import (
    CATEGORY_OPTIONS, DIVISION_OPTIONS, MEASURE_OPTIONS,
    COL_ACTION, COL_CATEGORY, COL_COST_PRICE, COL_ITEM_ID, COL_ITEM_NAME,
    COL_MEASURE, COL_PRICE_LOCKED, COL_QUANTITY, COL_SELL_PRICE, COL_SUPPLIER,
    COL_TIMESTAMP, get_script_directory,
)
from actions import ACTION_DELIVERY, ACTION_PRICE_UPDATE
from categories import is_delisted
from conversions import convert_to_input, convert_to_system, get_conversion, get_input_label, requires_conversion
from data_manager import (
    InventoryDataManager, COL_ALLOW_NEGATIVE, COL_DIVISION, COL_REORDER_LEVEL,
)
from inventory_sync import append_item_to_items_csv
from money import allocate_money, sum_money
from sales_mapping import is_hidden_from_stock_view


class InventoryMixin:
    """Stock management and delivery history methods mixed into the app."""

    def manage_initial_stock(self):
        """Display the initial stock management interface."""
        self._create_app_shell('Manage Stock')
        self.clear_main_menu()
    
        # Search frame
        search_frame = tk.Frame(self.main_menu, bg=THEME_BG)
        search_frame.pack(fill='x', pady=(0, 14))
    
        tk.Label(search_frame, text="SEARCH", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG).pack(side=tk.LEFT,
                                                       padx=(0, 8))
        self.search_entry = self.styled_entry(search_frame, width=60)
        self.search_entry.pack(side=tk.LEFT, fill='x', expand=True,
                               ipady=2, padx=(0, 8))
        self.search_entry.bind('<KeyRelease>', lambda e: self.search_stock())
    
        self.styled_button(search_frame, "Clear", self.clear_search,
                           width=10, variant='secondary').pack(side=tk.LEFT)
    
        # Treeview frame
        self.stock_frame = tk.Frame(self.main_menu, bg=THEME_BG)
        self.stock_frame.pack(fill='both', expand=True, pady=(0, 10))
    
        # Create treeview with scrollbar
        tree_container = tk.Frame(self.stock_frame, bg=THEME_BG)
        tree_container.pack(fill='both', expand=True)
    
        self.stock_tree = ttk.Treeview(tree_container, columns=('item_id', 'item_name', 'quantity', 'cost_price', 'sell_price', 'stock_value', 'measure', 'category'), show='headings')
    
        # Define column headings
        self.stock_tree.heading('item_id', text='Item ID', anchor='w')
        self.stock_tree.heading('item_name', text='Item Name', anchor='w')
        self.stock_tree.heading('quantity', text='Quantity', anchor='e')
        self.stock_tree.heading('cost_price', text='Cost Price', anchor='e')
        self.stock_tree.heading('sell_price', text='Sell Price', anchor='e')
        self.stock_tree.heading('stock_value', text='Stock Value', anchor='e')
        self.stock_tree.heading('measure', text='Measure', anchor='w')
        self.stock_tree.heading('category', text='Category', anchor='w')
    
        # Set column widths
        self.stock_tree.column('item_id', width=150, anchor='w')
        self.stock_tree.column('item_name', width=200, anchor='w')
        self.stock_tree.column('quantity', width=170, anchor='e')
        self.stock_tree.column('cost_price', width=90, anchor='e')
        self.stock_tree.column('sell_price', width=90, anchor='e')
        self.stock_tree.column('stock_value', width=110, anchor='e')
        self.stock_tree.column('measure', width=80, anchor='w')
        self.stock_tree.column('category', width=150, anchor='w')
        self._make_sortable(self.stock_tree)
    
        self.stock_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    
        scrollbar = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=self.stock_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.stock_tree.configure(yscrollcommand=scrollbar.set)
        self._bind_treeview_mousewheel(self.stock_tree)
    
        # Double-click to update item
        self.stock_tree.bind('<Double-1>', lambda event: self.on_stock_tree_double_click(event))
    
        self.load_stock_into_tree()
    
        # Button frame
        btn_frame = tk.Frame(self.main_menu, bg=THEME_BG)
        btn_frame.pack(fill='x', pady=(0, 4))
    
        self.styled_button(btn_frame, "Add item", self.add_stock_item,
                           width=14, variant='primary').pack(side=tk.LEFT,
                                                             padx=(0, 8))
        self.styled_button(btn_frame, "Update item",
                           self.edit_selected_stock_item, width=14,
                           variant='secondary').pack(side=tk.LEFT,
                                                     padx=(0, 8))
        self.styled_button(btn_frame, "Delete item", self.delete_stock_item,
                           width=14, variant='danger').pack(side=tk.LEFT,
                                                            padx=(0, 8))
        self.styled_button(btn_frame, "Retired items",
                           self.show_retired_items, width=14,
                           variant='secondary').pack(side=tk.LEFT,
                                                     padx=(0, 8))
        self.styled_button(btn_frame, "Back", self.show_dashboard,
                           width=12, variant='secondary').pack(side=tk.LEFT)
    
        self._apply_legacy_theme()


    def sort_treeview(self, tree, col, reverse=False):
        """Sort a Treeview by one column, numerically where the values allow."""
    
        def sort_key(iid):
            raw = str(tree.set(iid, col)).strip()
            cleaned = (raw.replace('£', '').replace(',', '')
                          .replace('%', '').replace('+', ''))
            token = cleaned.split()[0] if cleaned.split() else ''
            try:
                return (0, float(token))
            except ValueError:
                return (1, raw.lower())
    
        items = [(sort_key(iid), iid) for iid in tree.get_children('')]
        items.sort(key=lambda pair: pair[0], reverse=reverse)
        for index, (_, iid) in enumerate(items):
            tree.move(iid, '', index)


    def _make_sortable(self, tree):
        """Wire every column heading to click-to-sort (first click ascending)."""
        state = {}
        for col in tree['columns']:
            def sort(c=col):
                reverse = state.get(c, False)
                self.sort_treeview(tree, c, reverse)
                state[c] = not reverse
            tree.heading(col, command=sort)


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
        row_index = 0
        for _, row in self.inventory_df.iterrows():
            item_id = row[COL_ITEM_ID]
    
            # Skip hidden items (half pints, dash, shandies) - they deduct from parent stock
            if is_hidden_from_stock_view(item_id):
                continue
    
            # Retired and delisted items keep their history but leave the active
            # stock list (and can be restored from "Retired Items").
            if is_delisted(item_id):
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
    
                # Determine tag based on stock status; status tints win over
                # the zebra stripe so an alert row always reads as one.
                tag = 'alt' if row_index % 2 else ''
                if row[COL_QUANTITY] < 0 and not row.get(COL_ALLOW_NEGATIVE, False):
                    tag = 'negative_stock'
                elif COL_REORDER_LEVEL in row and row[COL_REORDER_LEVEL] > 0 and row[COL_QUANTITY] <= row[COL_REORDER_LEVEL]:
                    tag = 'low_stock'
    
                self.stock_tree.insert('', tk.END, values=values,
                                       tags=(tag,) if tag else ())
                row_index += 1
    
        # Configure tag styles
        self.stock_tree.tag_configure('alt', background=TBL_ROW_ALT,
                                      foreground=THEME_TEXT)
        self.stock_tree.tag_configure('low_stock', background=TBL_ROW_WARN, foreground=THEME_TEXT)
        self.stock_tree.tag_configure('negative_stock', background=TBL_ROW_DANGER, foreground=THEME_DANGER)


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
    
            if self._save_inventory():
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
                self._set_status(f"Item '{item_name}' added successfully.", 'success')
    
        top = tk.Toplevel(self.root)
        top.title("Add Stock Item")
        top.configure(bg=THEME_BG)
        top.geometry("470x640")
        self._fit_dialog(top, 470, 640)
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
        main_frame = tk.Frame(top, bg=THEME_BG, padx=22, pady=18)
        main_frame.pack(fill='both', expand=True)
    
        tk.Label(main_frame, text="NEW STOCK ITEM", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w').grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 2))
        tk.Label(main_frame, text="Add Stock Item", font=ui_theme.display_font(18),
                 fg=THEME_TEXT, bg=THEME_BG, anchor='w').grid(
            row=1, column=0, columnspan=2, sticky='w', pady=(0, 10))
    
        # Text entry fields
        fields = [
            ("ITEM ID", 'item_id'),
            ("ITEM NAME", 'item_name'),
            ("QUANTITY", 'quantity'),
            ("COST PRICE", 'cost_price'),
            ("SELL PRICE", 'sell_price'),
        ]
    
        entries = {}
        for i, (label, key) in enumerate(fields, start=2):
            tk.Label(main_frame, text=label, font=ui_theme.mono_font(8),
                     fg=THEME_TEXT_MUTED, bg=THEME_BG).grid(
                row=i, column=0, padx=(0, 12), pady=6, sticky="e")
            entry = self.styled_entry(main_frame, width=30)
            entry.grid(row=i, column=1, padx=0, pady=6, sticky="ew")
            entries[key] = entry
    
        entry_item_id = entries['item_id']
        entry_item_name = entries['item_name']
        entry_quantity = entries['quantity']
        entry_quantity.insert(0, "0")
        entry_cost_price = entries['cost_price']
        entry_sell_price = entries['sell_price']
    
        # Measure dropdown
        tk.Label(main_frame, text="MEASURE", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG).grid(
            row=7, column=0, padx=(0, 12), pady=6, sticky="e")
        measure_var = tk.StringVar(value=MEASURE_OPTIONS[0])
        measure_dropdown = ttk.Combobox(main_frame, textvariable=measure_var, values=MEASURE_OPTIONS, width=28, state="readonly")
        measure_dropdown.grid(row=7, column=1, pady=6, sticky="ew")
    
        # Category dropdown
        tk.Label(main_frame, text="CATEGORY", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG).grid(
            row=8, column=0, padx=(0, 12), pady=6, sticky="e")
        category_var = tk.StringVar(value=CATEGORY_OPTIONS[0])
        category_dropdown = ttk.Combobox(main_frame, textvariable=category_var, values=CATEGORY_OPTIONS, width=28, state="readonly")
        category_dropdown.grid(row=8, column=1, pady=6, sticky="ew")
    
        # Allow Negative Stock checkbox
        allow_negative_var = tk.BooleanVar(value=False)
        allow_negative_checkbox = tk.Checkbutton(
            main_frame, text="Allow negative stock", variable=allow_negative_var,
            bg=THEME_BG, fg=THEME_TEXT, activebackground=THEME_BG,
            activeforeground=THEME_TEXT, selectcolor=THEME_CARD,
            highlightthickness=0, bd=0, font=ui_theme.mono_font(9),
            cursor='hand2')
        allow_negative_checkbox.grid(row=9, column=1,
                                     sticky="w", pady=4)
    
        # Reorder Level
        tk.Label(main_frame, text="REORDER LEVEL", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG).grid(
            row=10, column=0, padx=(0, 12), pady=6, sticky="e")
        entry_reorder_level = self.styled_entry(main_frame, width=30)
        entry_reorder_level.insert(0, "0")
        entry_reorder_level.grid(row=10, column=1, pady=6, sticky="ew")
    
        # Division dropdown
        tk.Label(main_frame, text="DIVISION", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG).grid(
            row=11, column=0, padx=(0, 12), pady=6, sticky="e")
        division_var = tk.StringVar(value=DIVISION_OPTIONS[-1])
        division_dropdown = ttk.Combobox(main_frame, textvariable=division_var, values=DIVISION_OPTIONS, width=28, state="readonly")
        division_dropdown.grid(row=11, column=1, pady=6, sticky="ew")
    
        # Button frame
        tk.Frame(main_frame, bg=THEME_BORDER, height=1).grid(
            row=12, column=0, columnspan=2, sticky='ew', pady=(14, 0))
        btn_frame = tk.Frame(main_frame, bg=THEME_BG)
        btn_frame.grid(row=13, column=0, columnspan=2, pady=(12, 0),
                       sticky='w')
    
        self.styled_button(btn_frame, "Save Item", save_item, width=15,
                           variant='primary').pack(side=tk.LEFT, padx=(0, 10))
        self.styled_button(btn_frame, "Cancel", top.destroy, width=15,
                           variant='secondary').pack(side=tk.LEFT)
    
        main_frame.grid_columnconfigure(1, weight=1)
    
        # Force redraw so ttk.Combobox is visible immediately on macOS
        top.update_idletasks()


    def on_stock_tree_double_click(self, event):
        """Handle double-click on stock treeview item to open update dialog."""
        # Get the item under the cursor
        item = self.stock_tree.identify('item', event.x, event.y)
        if item:
            self.stock_tree.selection_set(item)
            self.edit_selected_stock_item()


    def edit_selected_stock_item(self):
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
    
            if self._save_inventory():
                self.load_stock_into_tree()
                self.update_dashboard_stats()
                top.destroy()
                self._set_status(f"Item '{item_id}' updated to {new_quantity:.1f}{conversion_msg}.", 'success')
    
        top = tk.Toplevel(self.root)
        top.title("Update Stock Item")
        top.configure(bg=THEME_BG)
        top.geometry("470x660")
        self._fit_dialog(top, 470, 660)
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
    
        main_frame = tk.Frame(top, bg=THEME_BG, padx=22, pady=18)
        main_frame.pack(fill='both', expand=True)
    
        tk.Label(main_frame, text="STOCK ITEM", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w').grid(
            row=0, column=0, columnspan=2, sticky='w', pady=(0, 2))
        tk.Label(main_frame, text=item_id, font=ui_theme.display_font(18),
                 fg=THEME_TEXT, bg=THEME_BG, anchor='w').grid(
            row=1, column=0, columnspan=2, sticky='w', pady=(0, 10))
    
        # Text entry fields
        # Use input quantity for items requiring conversion
        if requires_conv:
            quantity_label = f"QUANTITY ({input_unit.upper()}S)"
            quantity_value = f"{current_input_qty:.1f}"
        else:
            quantity_label = "QUANTITY"
            quantity_value = f"{current_system_qty:.1f}"
    
        fields = [
            ("ITEM NAME", current_name, 'item_name'),
            (quantity_label, quantity_value, 'quantity'),
            ("COST PRICE", item_values[3].replace('£', ''), 'cost_price'),
            ("SELL PRICE", item_values[4].replace('£', ''), 'sell_price'),
        ]
    
        entries = {}
        for i, (label, value, key) in enumerate(fields, 2):
            tk.Label(main_frame, text=label, font=ui_theme.mono_font(8),
                     fg=THEME_TEXT_MUTED, bg=THEME_BG).grid(
                row=i, column=0, padx=(0, 12), pady=6, sticky="e")
            entry = self.styled_entry(main_frame, width=30)
            entry.insert(0, value)
            entry.grid(row=i, column=1, pady=6, sticky="ew")
            entries[key] = entry
    
        # Show conversion info if applicable (below the quantity entry)
        if requires_conv:
            conversion_info = tk.Label(main_frame, text=f"1 {input_unit} = {conversion_factor} {output_unit}s", font=ui_theme.mono_font(9), fg=THEME_TEXT_MUTED, bg=THEME_BG)
            conversion_info.grid(row=6, column=1, sticky="w")
    
        # Measure dropdown
        tk.Label(main_frame, text="MEASURE", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG).grid(
            row=7, column=0, padx=(0, 12), pady=6, sticky="e")
        measure_var = tk.StringVar(value=current_measure if current_measure in MEASURE_OPTIONS else MEASURE_OPTIONS[0])
        measure_dropdown = ttk.Combobox(main_frame, textvariable=measure_var, values=MEASURE_OPTIONS, width=28, state="readonly")
        measure_dropdown.grid(row=7, column=1, pady=6, sticky="ew")
    
        # Category dropdown
        tk.Label(main_frame, text="CATEGORY", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG).grid(
            row=8, column=0, padx=(0, 12), pady=6, sticky="e")
        category_var = tk.StringVar(value=current_category if current_category in CATEGORY_OPTIONS else CATEGORY_OPTIONS[0])
        category_dropdown = ttk.Combobox(main_frame, textvariable=category_var, values=CATEGORY_OPTIONS, width=28, state="readonly")
        category_dropdown.grid(row=8, column=1, pady=6, sticky="ew")
    
        # Price Locked checkbox
        price_locked_var = tk.BooleanVar(value=current_price_locked)
        price_locked_checkbox = tk.Checkbutton(
            main_frame, text="Lock prices against CSV uploads",
            variable=price_locked_var, bg=THEME_BG, fg=THEME_TEXT,
            activebackground=THEME_BG, activeforeground=THEME_TEXT,
            selectcolor=THEME_CARD, highlightthickness=0, bd=0,
            font=ui_theme.mono_font(9), cursor='hand2')
        price_locked_checkbox.grid(row=9, column=1, sticky="w", pady=4)
    
        # Allow Negative Stock checkbox
        current_allow_negative = InventoryDataManager.get_item_value_safe(self.inventory_df, item_id, COL_ALLOW_NEGATIVE, default=False)
        allow_negative_var = tk.BooleanVar(value=bool(current_allow_negative))
        allow_negative_checkbox = tk.Checkbutton(
            main_frame, text="Allow negative stock",
            variable=allow_negative_var, bg=THEME_BG, fg=THEME_TEXT,
            activebackground=THEME_BG, activeforeground=THEME_TEXT,
            selectcolor=THEME_CARD, highlightthickness=0, bd=0,
            font=ui_theme.mono_font(9), cursor='hand2')
        allow_negative_checkbox.grid(row=10, column=1, sticky="w", pady=4)
    
        # Reorder Level
        current_reorder_level = InventoryDataManager.get_item_value_safe(self.inventory_df, item_id, COL_REORDER_LEVEL, default=0)
        tk.Label(main_frame, text="REORDER LEVEL", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG).grid(
            row=11, column=0, padx=(0, 12), pady=6, sticky="e")
        entry_reorder_level = self.styled_entry(main_frame, width=30)
        entry_reorder_level.insert(0, str(current_reorder_level))
        entry_reorder_level.grid(row=11, column=1, pady=6, sticky="ew")
    
        # Division dropdown
        current_division = InventoryDataManager.get_item_value_safe(self.inventory_df, item_id, COL_DIVISION, default='')
        tk.Label(main_frame, text="DIVISION", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG).grid(
            row=12, column=0, padx=(0, 12), pady=6, sticky="e")
        division_var = tk.StringVar(value=current_division if current_division in DIVISION_OPTIONS else DIVISION_OPTIONS[-1])
        division_dropdown = ttk.Combobox(main_frame, textvariable=division_var, values=DIVISION_OPTIONS, width=28, state="readonly")
        division_dropdown.grid(row=12, column=1, pady=6, sticky="ew")
    
        entry_name = entries['item_name']
        entry_quantity = entries['quantity']
        entry_cost_price = entries['cost_price']
        entry_sell_price = entries['sell_price']
    
        tk.Frame(main_frame, bg=THEME_BORDER, height=1).grid(
            row=13, column=0, columnspan=2, sticky='ew', pady=(14, 0))
        btn_frame = tk.Frame(main_frame, bg=THEME_BG)
        btn_frame.grid(row=14, column=0, columnspan=2, pady=(12, 0),
                       sticky='w')
    
        self.styled_button(btn_frame, "Save Changes", save_update, width=15,
                           variant='primary').pack(side=tk.LEFT, padx=(0, 10))
        self.styled_button(btn_frame, "Cancel", top.destroy, width=15,
                           variant='secondary').pack(side=tk.LEFT)
    
        main_frame.grid_columnconfigure(1, weight=1)
    
        # Force redraw so ttk.Combobox is visible immediately on macOS
        top.update_idletasks()


    def _item_has_history(self, item_id):
        """Return True when the transaction log references ``item_id``."""
        if self.log_df.empty or COL_ITEM_ID not in self.log_df.columns:
            return False
        return bool((self.log_df[COL_ITEM_ID].astype(str) == str(item_id)).any())


    def delete_stock_item(self):
        """Retire or delete a stock item.
    
        An item with transaction history is never deleted: removing its
        inventory row would hide every past delivery, sale and stocktake from
        the reports.  Those items are retired instead, which hides them from
        the active stock list and ordering while keeping the audit trail.
        """
        selected_item = self.stock_tree.selection()
        if not selected_item:
            messagebox.showerror("Error", "No item selected. Please select an item from the list.")
            return
    
        item_values = self.stock_tree.item(selected_item, 'values')
        item_id = item_values[0]
        item_name = item_values[1]
    
        if self._item_has_history(item_id):
            if not messagebox.askyesno(
                    "Retire Item",
                    f"'{item_name}' has transaction history, so it cannot be deleted "
                    "without losing that history from reports.\n\n"
                    "Retire it instead? It will be removed from the stock list and "
                    "order sheet, and its past transactions will be kept."):
                return
            try:
                from retirement import retire_item
                retire_item(item_id)
            except Exception as exc:
                messagebox.showerror("Error", f"Could not retire '{item_name}': {exc}")
                return
            self.load_stock_into_tree()
            self.update_dashboard_stats()
            self._set_status(
                f"Item '{item_name}' retired. History preserved; restore it from Retired Items.",
                'success')
            return
    
        typed = simpledialog.askstring(
            "Confirm Delete",
            f"'{item_name}' has no transaction history.\n\n"
            f"Type the item ID ({item_id}) to delete it permanently:",
            parent=self.root)
        if typed is None:
            return
        if typed.strip().lower() != str(item_id).strip().lower():
            messagebox.showinfo("Not Deleted", "The item ID did not match, so nothing was deleted.")
            return
    
        self.inventory_df = self.inventory_df[self.inventory_df[COL_ITEM_ID] != item_id]
        if self._save_inventory():
            self.load_stock_into_tree()
            self.update_dashboard_stats()
            self._set_status(f"Item '{item_name}' deleted successfully.", 'success')


    def show_retired_items(self):
        """List items retired from the stock list and allow restoring them."""
        from retirement import load_retired_items, unretire_item
    
        top = tk.Toplevel(self.root)
        top.title("Retired Items")
        top.geometry("620x420")
        self._fit_dialog(top, 620, 420)
        top.configure(bg=THEME_BG)
    
        tk.Label(top, text="STOCK", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w').pack(
            fill='x', padx=24, pady=(20, 2))
        tk.Label(top, text="Retired items",
                 font=ui_theme.display_font(18), fg=THEME_TEXT,
                 bg=THEME_BG, anchor='w').pack(fill='x', padx=24)
        tk.Label(top, text="They keep their transaction history but are hidden "
                           "from the stock list, order sheet and alerts.",
                 font=(ui_theme.THEME_FONT, 9), fg=THEME_TEXT_MUTED,
                 bg=THEME_BG, anchor='w').pack(fill='x', padx=24,
                                               pady=(2, 14))
        tk.Frame(top, bg=THEME_BORDER, height=1).pack(fill='x', padx=24)
    
        tree = ttk.Treeview(top, columns=('item_id', 'item_name', 'quantity'),
                            show='headings', height=10)
        tree.heading('item_id', text='Item ID', anchor='w')
        tree.heading('item_name', text='Item Name', anchor='w')
        tree.heading('quantity', text='Quantity', anchor='e')
        tree.column('item_id', width=180, anchor='w')
        tree.column('item_name', width=300, anchor='w')
        tree.column('quantity', width=90, anchor='e')
        tree.tag_configure('alt', background=TBL_ROW_ALT,
                           foreground=THEME_TEXT)
        tree.pack(fill='both', expand=True, padx=24, pady=(12, 4))
        self._bind_treeview_mousewheel(tree)

        empty_label = tk.Label(top, text="", font=(ui_theme.THEME_FONT, 10),
                               fg=THEME_TEXT_MUTED, bg=THEME_BG)
        empty_label.pack(pady=4)

        def populate():
            for child in tree.get_children():
                tree.delete(child)
            retired = load_retired_items(refresh=True)
            names = dict(zip(self.inventory_df[COL_ITEM_ID],
                             self.inventory_df[COL_ITEM_NAME]))
            quantities = dict(zip(self.inventory_df[COL_ITEM_ID],
                                  self.inventory_df[COL_QUANTITY]))
            for index, item_id in enumerate(sorted(retired)):
                if item_id not in names:
                    continue
                tree.insert('', tk.END, iid=item_id,
                            tags=('alt',) if index % 2 else (),
                            values=(item_id, names[item_id],
                                    f"{float(quantities.get(item_id) or 0):.1f}"))
            empty_label.config(text="No retired items." if not tree.get_children() else "")
    
        def restore_selected():
            selection = tree.selection()
            if not selection:
                messagebox.showinfo("Restore Item", "Select an item to restore.", parent=top)
                return
            item_id = selection[0]
            try:
                unretire_item(item_id)
            except Exception as exc:
                messagebox.showerror("Error", f"Could not restore the item: {exc}", parent=top)
                return
            populate()
            self.load_stock_into_tree()
            self.update_dashboard_stats()
            self._set_status(f"Item '{item_id}' restored to stock.", 'success')
    
        btn_frame = tk.Frame(top, bg=THEME_BG)
        btn_frame.pack(fill='x', padx=24, pady=(8, 16))
        self.styled_button(btn_frame, "Restore selected", restore_selected,
                           width=18, variant='primary').pack(side='right')
        self.styled_button(btn_frame, "Close", top.destroy,
                           width=12, variant='secondary').pack(side='right',
                                                               padx=(0, 8))
    
        populate()
        top.update_idletasks()
        self._apply_legacy_theme(top)


    def show_delivery_history(self):
        """Show delivery history inside the app shell."""
        self._create_app_shell('Delivery History')
        self.view_delivery_history()


    def view_delivery_history(self):
        """View and manage past deliveries."""
        self.clear_main_menu()
    
        self.refresh_data()
    
        # Main frame with two panes
        main_frame = tk.Frame(self.main_menu, bg=THEME_BG)
        main_frame.pack(fill=tk.BOTH, expand=True)
    
        # Left - Deliveries list
        left_frame = tk.Frame(main_frame, bg=THEME_BG,
                              highlightbackground=THEME_BORDER,
                              highlightthickness=1)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))
        tk.Label(left_frame, text="DELIVERIES", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w').pack(
            fill='x', padx=12, pady=(8, 6))
    
        del_columns = ('timestamp', 'supplier', 'items', 'total_value')
        del_tree = ttk.Treeview(left_frame, columns=del_columns, show='headings', height=12)
        del_tree.heading('timestamp', text='Date / Time')
        del_tree.heading('supplier', text='Supplier')
        del_tree.heading('items', text='Items')
        del_tree.heading('total_value', text='Total Value')
        self._make_sortable(del_tree)
        del_tree.column('timestamp', width=150, anchor='w')
        del_tree.column('supplier', width=120, anchor='w')
        del_tree.column('items', width=60, anchor='e')
        del_tree.column('total_value', width=110, anchor='e')
        del_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        del_scroll = ttk.Scrollbar(left_frame, orient=tk.VERTICAL, command=del_tree.yview)
        del_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        del_tree.configure(yscrollcommand=del_scroll.set)
        self._bind_treeview_mousewheel(del_tree)
    
        # Right - Items in selected delivery
        right_frame = tk.Frame(main_frame, bg=THEME_BG,
                               highlightbackground=THEME_BORDER,
                               highlightthickness=1)
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(6, 0))
        tk.Label(right_frame, text="ITEMS IN SELECTED DELIVERY",
                 font=ui_theme.mono_font(8), fg=THEME_TEXT_MUTED,
                 bg=THEME_BG, anchor='w').pack(fill='x', padx=12,
                                               pady=(8, 6))
    
        item_columns = ('item_id', 'item_name', 'quantity', 'cost_price', 'total')
        item_tree = ttk.Treeview(right_frame, columns=item_columns, show='headings', height=12)
        item_tree.heading('item_id', text='Item ID')
        item_tree.heading('item_name', text='Name')
        item_tree.heading('quantity', text='Qty')
        item_tree.heading('cost_price', text='Cost')
        item_tree.heading('total', text='Total')
        self._make_sortable(item_tree)
        item_tree.column('item_id', width=110, anchor='w')
        item_tree.column('item_name', width=160, anchor='w')
        item_tree.column('quantity', width=70, anchor='e')
        item_tree.column('cost_price', width=80, anchor='e')
        item_tree.column('total', width=90, anchor='e')
        item_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        item_scroll = ttk.Scrollbar(right_frame, orient=tk.VERTICAL, command=item_tree.yview)
        item_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        item_tree.configure(yscrollcommand=item_scroll.set)
        self._bind_treeview_mousewheel(item_tree)
    
        # Populate deliveries
        delivery_groups = {}
        if not self.log_df.empty and COL_ACTION in self.log_df.columns:
            deliveries = self.log_df[self.log_df[COL_ACTION] == ACTION_DELIVERY]
            for _, row in deliveries.iterrows():
                ts = row.get(COL_TIMESTAMP, '')
                if not ts:
                    continue
                supplier = row.get(COL_SUPPLIER, '') if COL_SUPPLIER in row.index else ''
                supplier = '' if pd.isna(supplier) else str(supplier)
                # Timestamp alone is not unique: two suppliers can be booked in
                # at the same second. Group on timestamp + supplier so editing
                # one never rewrites the other.
                key = f"{ts}|{supplier}"
                if key not in delivery_groups:
                    delivery_groups[key] = {
                        'timestamp': ts,
                        'supplier': supplier,
                        'items': [],
                    }
                delivery_groups[key]['items'].append(row)
    
        for key in sorted(delivery_groups.keys(), reverse=True):
            grp = delivery_groups[key]
            items_count = len(grp['items'])
            # Allocate the line values so the selected delivery's lines add up
            # exactly to the total shown for it.
            grp['line_values'] = allocate_money(
                float(i.get(COL_COST_PRICE, 0)) * float(i.get(COL_QUANTITY, 0))
                for i in grp['items'])
            total_val = sum_money(grp['line_values'])
            supplier = grp['supplier'] if grp['supplier'] else 'Unknown'
            del_tree.insert('', tk.END, values=(grp['timestamp'], supplier, items_count, self.format_currency(total_val)), tags=(key,))
    
        def on_delivery_select(event=None):
            for item in item_tree.get_children():
                item_tree.delete(item)
            selected = del_tree.selection()
            if not selected:
                return
            ts = del_tree.item(selected[0], 'tags')[0]
            if ts in delivery_groups:
                for row, line_value in zip(delivery_groups[ts]['items'],
                                           delivery_groups[ts]['line_values']):
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
                    item_tree.insert('', tk.END, values=(item_id, name, f"{qty:.1f}", self.format_currency(display_cost), self.format_currency(line_value)))
    
        del_tree.bind('<<TreeviewSelect>>', on_delivery_select)
        first_delivery = del_tree.get_children()
        if first_delivery:
            del_tree.selection_set(first_delivery[0])
            on_delivery_select()
    
        # Action buttons
        btn_frame = tk.Frame(self.main_menu, bg=THEME_BG)
        btn_frame.pack(fill='x', pady=(12, 0))
    
        def edit_selected_delivery():
            selected = del_tree.selection()
            if not selected:
                messagebox.showerror("Error", "Please select a delivery to edit.")
                return
            key = del_tree.item(selected[0], 'tags')[0]
            if key not in delivery_groups:
                return
            self.edit_delivery_dialog(key, delivery_groups[key])
    
        def delete_selected_delivery():
            selected = del_tree.selection()
            if not selected:
                messagebox.showerror("Error", "Please select a delivery to delete.")
                return
            key = del_tree.item(selected[0], 'tags')[0]
            if key not in delivery_groups:
                return
            grp = delivery_groups[key]
            items_desc = "\n".join([f"  • {i.get(COL_ITEM_ID, '')}: {float(i.get(COL_QUANTITY, 0)):.1f}" for i in grp['items']])
            if messagebox.askyesno("Confirm Delete", f"Delete this delivery?\n\nDate: {grp['timestamp']}\nSupplier: {grp['supplier']}\nItems:\n{items_desc}"):
                self.delete_delivery(grp['timestamp'], grp['items'], supplier=grp['supplier'])
                self.view_delivery_history()
    
        self.styled_button(btn_frame, "Edit selected",
                           edit_selected_delivery, width=15,
                           variant='secondary').pack(side=tk.LEFT,
                                                    padx=(0, 8))
        self.styled_button(btn_frame, "Delete selected",
                           delete_selected_delivery, width=15,
                           variant='danger').pack(side=tk.LEFT,
                                                  padx=(0, 8))
        self.styled_button(btn_frame, "Back", self.generate_reports,
                           width=15, variant='secondary').pack(side=tk.LEFT)
    
        self._apply_legacy_theme()


    def edit_delivery_dialog(self, timestamp, delivery_group):
        """Open a dialog to edit a delivery's items."""
        timestamp = delivery_group.get('timestamp', timestamp)
        supplier = delivery_group.get('supplier', '')
        top = tk.Toplevel(self.root)
        top.title(f"Edit Delivery - {timestamp}")
        top.configure(bg=THEME_BG)
        top.geometry("560x460")
        self._fit_dialog(top, 560, 460)
        top.transient(self.root)
        top.grab_set()
        top.lift()
    
        tk.Label(top, text="DELIVERY", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_BG, anchor='w').pack(
            fill='x', padx=20, pady=(18, 2))
        tk.Label(top, text=f"{delivery_group['supplier']}  ·  {timestamp}",
                 font=ui_theme.display_font(16), fg=THEME_TEXT,
                 bg=THEME_BG, anchor='w').pack(fill='x', padx=20)
    
        frame = tk.Frame(top, bg=THEME_BG)
        frame.pack(pady=12, padx=20, fill=tk.BOTH, expand=True)
    
        # Headers
        headers = ['Item', 'Quantity', 'Cost Price']
        for c, h in enumerate(headers):
            tk.Label(frame, text=h.upper(), font=ui_theme.mono_font(8),
                     fg=THEME_TEXT_MUTED, bg=THEME_BG).grid(
                row=0, column=c, padx=6, pady=4, sticky='e' if c else 'w')
    
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
    
            tk.Label(frame, text=f"{item_id} - {name}", bg=THEME_BG,
                     fg=THEME_TEXT, font=(ui_theme.THEME_FONT, 10)).grid(
                row=r, column=0, padx=6, pady=3, sticky='w')
    
            qty_var = tk.StringVar(value=f"{qty:.1f}")
            cost_var = tk.StringVar(value=f"{cost:.2f}")
            self.styled_entry(frame, textvariable=qty_var, width=10).grid(
                row=r, column=1, padx=6, pady=3, sticky='e')
            self.styled_entry(frame, textvariable=cost_var, width=10).grid(
                row=r, column=2, padx=6, pady=3, sticky='e')
    
            entries.append({'item_id': item_id, 'original_qty': qty, 'original_cost': cost,
                           'qty_var': qty_var, 'cost_var': cost_var})
    
        def save_edits():
            try:
                self.refresh_data()
                from conversions import requires_conversion, get_conversion
    
                parsed = []
                for e in entries:
                    new_qty = float(e['qty_var'].get().strip())
                    new_cost = float(e['cost_var'].get().strip())
                    if new_qty < 0:
                        messagebox.showerror("Error", "Quantity cannot be negative.", parent=top)
                        return
                    if new_cost < 0:
                        messagebox.showerror("Error", "Cost price cannot be negative.", parent=top)
                        return
                    if requires_conversion(e['item_id']):
                        conv = get_conversion(e['item_id'])
                        if conv:
                            new_cost = new_cost / conv[1]
                    parsed.append({**e, 'new_qty': new_qty, 'new_cost': new_cost})
    
                # Refuse edits that would take an item negative. Deleting the
                # stock that has already been sold would otherwise leave an
                # impossible balance behind.
                negative = []
                for p in parsed:
                    rows = self.inventory_df[self.inventory_df[COL_ITEM_ID] == p['item_id']]
                    if rows.empty:
                        continue
                    current = float(rows.iloc[0][COL_QUANTITY])
                    allowed = bool(rows.iloc[0][COL_ALLOW_NEGATIVE])
                    projected = current - p['original_qty'] + p['new_qty']
                    if projected < -0.01 and not allowed:
                        name = rows.iloc[0][COL_ITEM_NAME]
                        negative.append(f"  • {name}: {current:.1f} → {projected:.1f}")
                if negative:
                    messagebox.showerror(
                        "Stock Would Go Negative",
                        "This edit would leave stock below zero for:\n\n"
                        + "\n".join(negative)
                        + "\n\nReduce the quantity, correct the stocktake first, "
                          "or allow negative stock for the item.",
                        parent=top,
                    )
                    return
    
                # The current cost price is only meaningful for the most recent
                # priced movement. Editing an old delivery must not overwrite a
                # newer invoice price, and locked prices are never touched.
                cost_events = self.log_df[
                    self.log_df[COL_ACTION].isin([ACTION_DELIVERY, ACTION_PRICE_UPDATE])
                ].copy()
                if not cost_events.empty:
                    cost_events = cost_events[
                        pd.to_numeric(cost_events[COL_QUANTITY], errors='coerce').fillna(0) >= 0
                    ]
                latest_event = (
                    cost_events.groupby(COL_ITEM_ID)[COL_TIMESTAMP].max().to_dict()
                    if not cost_events.empty else {}
                )
    
                kept_costs = []
                for p in parsed:
                    item_id = p['item_id']
                    rows = self.inventory_df[self.inventory_df[COL_ITEM_ID] == item_id]
                    if rows.empty:
                        continue
                    idx = rows.index[0]
                    current_stock = float(self.inventory_df.at[idx, COL_QUANTITY])
                    self.inventory_df.at[idx, COL_QUANTITY] = (
                        current_stock - p['original_qty'] + p['new_qty']
                    )
    
                    is_latest = str(latest_event.get(item_id, timestamp)) <= str(timestamp)
                    is_locked = bool(self.inventory_df.at[idx, COL_PRICE_LOCKED])
                    if is_latest and not is_locked:
                        self.inventory_df.at[idx, COL_COST_PRICE] = p['new_cost']
                    elif abs(float(self.inventory_df.at[idx, COL_COST_PRICE]) - p['new_cost']) > 1e-9:
                        kept_costs.append(
                            f"{self.inventory_df.at[idx, COL_ITEM_NAME]} "
                            f"({'price locked' if is_locked else 'newer cost exists'})"
                        )
    
                # Update the historical log rows themselves (both quantity and
                # cost), regardless of whether the current cost was changed.
                mask = (
                    (self.log_df[COL_TIMESTAMP] == timestamp)
                    & (self.log_df[COL_ACTION] == ACTION_DELIVERY)
                )
                if supplier:
                    mask &= self.log_df[COL_SUPPLIER].fillna('').astype(str) == str(supplier)
                for p in parsed:
                    item_mask = mask & (self.log_df[COL_ITEM_ID] == p['item_id'])
                    if item_mask.any():
                        self.log_df.loc[item_mask, COL_QUANTITY] = p['new_qty']
                        self.log_df.loc[item_mask, COL_COST_PRICE] = p['new_cost']
    
                if kept_costs and not messagebox.askyesno(
                    "Cost Price Kept",
                    "The delivery quantity will be updated, but the current cost "
                    "price was left unchanged for:\n\n"
                    + "\n".join(f"  • {line}" for line in kept_costs)
                    + "\n\nContinue?",
                    parent=top,
                ):
                    return
    
                if self._persist():
                    self._set_status("Delivery updated successfully.", 'success')
                    top.destroy()
                    self.view_delivery_history()
                else:
                    messagebox.showerror("Error", "Failed to save changes.", parent=top)
    
            except ValueError:
                messagebox.showerror("Error", "Invalid number entered. Please check quantities and prices.", parent=top)
            except Exception as e:
                messagebox.showerror("Error", f"Update failed: {e}", parent=top)
    
        tk.Frame(top, bg=THEME_BORDER, height=1).pack(fill='x', padx=20,
                                                      pady=(14, 0))
        btn_frame = tk.Frame(top, bg=THEME_BG)
        btn_frame.pack(fill='x', padx=20, pady=12)
        self.styled_button(btn_frame, "Save Changes", save_edits, width=15,
                           variant='primary').pack(side=tk.LEFT, padx=(0, 8))
        self.styled_button(btn_frame, "Cancel", top.destroy, width=15,
                           variant='secondary').pack(side=tk.LEFT)


    def delete_delivery(self, timestamp, items, supplier=''):
        """Delete a delivery and reverse its stock changes.
    
        Refuses when reversing the delivery would take an item below zero: the
        stock it added has since been sold, so deleting it silently would leave
        a negative balance that no later report can explain.
        """
        try:
            self.refresh_data()
    
            negative = []
            for row in items:
                item_id = row.get(COL_ITEM_ID, '')
                qty = float(row.get(COL_QUANTITY, 0))
                if not item_id or self.inventory_df.empty:
                    continue
                match = self.inventory_df[COL_ITEM_ID] == item_id
                if not match.any():
                    continue
                idx = self.inventory_df.index[match][0]
                current = float(self.inventory_df.at[idx, COL_QUANTITY])
                projected = current - qty
                if projected < -0.01 and not bool(self.inventory_df.at[idx, COL_ALLOW_NEGATIVE]):
                    negative.append(
                        f"  • {self.inventory_df.at[idx, COL_ITEM_NAME]}: "
                        f"{current:.1f} → {projected:.1f}"
                    )
            if negative:
                messagebox.showerror(
                    "Cannot Delete Delivery",
                    "Deleting this delivery would leave stock below zero for:\n\n"
                    + "\n".join(negative)
                    + "\n\nThe stock has already been sold. Record a stocktake "
                      "adjustment instead, or allow negative stock for these items.",
                )
                return
    
            for row in items:
                item_id = row.get(COL_ITEM_ID, '')
                qty = float(row.get(COL_QUANTITY, 0))
                if item_id and not self.inventory_df.empty and item_id in self.inventory_df[COL_ITEM_ID].values:
                    self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] -= qty
    
            # Remove only this supplier's log entries at this timestamp.
            mask = (self.log_df[COL_TIMESTAMP] == timestamp) & (self.log_df[COL_ACTION] == ACTION_DELIVERY)
            if supplier:
                mask &= self.log_df[COL_SUPPLIER].fillna('').astype(str) == str(supplier)
            self.log_df = self.log_df[~mask].reset_index(drop=True)
    
            if self._persist():
                self._set_status("Delivery deleted successfully.", 'success')
            else:
                messagebox.showerror("Error", "Failed to save after deletion.")
    
        except Exception as e:
            messagebox.showerror("Error", f"Delete failed: {e}")
