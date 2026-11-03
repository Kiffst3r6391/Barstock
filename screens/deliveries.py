#!/usr/bin/env python3
"""Delivery entry screen, including repeat-last-delivery and quick picks."""

from datetime import datetime

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

import ui_theme
from ui_theme import (THEME_BORDER, THEME_CARD, THEME_DANGER,
                      THEME_SUCCESS, THEME_TEXT, THEME_TEXT_MUTED,
                      TBL_ROW_ALT)
from app_config import (
    COL_ACTION, COL_COST_PRICE, COL_DATE_RANGE, COL_ITEM_ID, COL_ITEM_NAME,
    COL_QUANTITY, COL_REASON, COL_SELL_PRICE, COL_SUPPLIER, COL_TIMESTAMP,
)
from actions import ACTION_DELIVERY
from categories import EXCLUDED_ITEMS, is_delisted
from conversions import (
    DATE_FORMAT_DISPLAY, convert_to_system, format_stock_display,
    get_conversion, get_input_label, parse_display_date, requires_conversion,
)
from sales_mapping import get_hidden_items


class DeliveriesMixin:
    """Delivery methods mixed into the main application class."""

    def show_deliveries(self):
        """Show the Deliveries tab by wrapping the existing delivery flow."""
        self._create_app_shell('Deliveries')
        self.add_delivery()


    def add_delivery(self):
        """Add a delivery transaction with supplier selection."""
        self.clear_main_menu()
    
        # Supplier card
        supplier_card = self._card(self.main_menu, title="Supplier")
        supplier_card.pack(fill='x', pady=(0, 20))

        row = self._form_row(supplier_card)
        field_frame = tk.Frame(row, bg=THEME_CARD)
        field_frame.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
        tk.Label(field_frame, text="SUPPLIER", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_CARD, anchor='w').pack(fill='x')
        supplier_var = tk.StringVar(value="Booker")
        supplier_dropdown = ttk.Combobox(field_frame, textvariable=supplier_var,
                                          values=["Booker", "Tennents"],
                                          width=40, state="readonly")
        supplier_dropdown.pack(fill='x', pady=(4, 0))
        supplier_dropdown.set("Select supplier...")
    
        def proceed_with_delivery():
            selected_supplier = supplier_var.get()
            if selected_supplier == "Select supplier...":
                messagebox.showerror("Error", "Please select a supplier.")
                return
            self.current_delivery_supplier = selected_supplier
            self.process_delivery_multi_item()
    
        def upload_invoice_for_price_check():
            selected_supplier = supplier_var.get()
            if selected_supplier == "Select supplier...":
                messagebox.showerror("Error", "Please select a supplier first.")
                return
            if selected_supplier != "Booker":
                messagebox.showerror("Error", "Invoice price check is currently only available for Booker invoices.")
                return
            self.current_delivery_supplier = selected_supplier
            self.upload_delivery_invoice_price_check()
    
        btn_frame = self.themed_frame(self.main_menu)
        btn_frame.pack(fill='x', pady=(10, 0))
    
        def repeat_last():
            selected = supplier_var.get()
            if selected == "Select supplier...":
                selected = None
            self.repeat_last_delivery(selected)
    
        self.styled_button(btn_frame, "Proceed", proceed_with_delivery, width=16, variant='primary').pack(side='left', padx=(0, 10))
        self.styled_button(btn_frame, "Repeat Last Delivery", repeat_last,
                           width=20, variant='secondary').pack(side='left', padx=(0, 10))
        self.styled_button(btn_frame, "Upload Invoice to Price Check", upload_invoice_for_price_check,
                           width=26, variant='secondary').pack(side='left', padx=(0, 10))
        self.styled_button(btn_frame, "Back", self.show_dashboard, width=16, variant='secondary').pack(side='left')
    
        # Recent deliveries
        history_card = self._card(self.main_menu, title="Recent deliveries")
        history_card.pack(fill='x', pady=(20, 20))
    
        try:
            self.refresh_data()
            if not self.log_df.empty:
                delivery_log = self.log_df[self.log_df[COL_ACTION] == ACTION_DELIVERY].copy()
                if not delivery_log.empty:
                    delivery_log['ts_group'] = delivery_log[COL_TIMESTAMP].str[:16]
                    grouped = delivery_log.groupby(['ts_group', COL_SUPPLIER]).agg({
                        COL_ITEM_ID: 'nunique',
                        COL_QUANTITY: 'sum'
                    }).reset_index()
                    grouped.columns = ['timestamp', 'supplier', 'items', 'total_qty']
                    grouped = grouped.sort_values('timestamp', ascending=False).head(10)
    
                    history_container = tk.Frame(history_card, bg=THEME_CARD)
                    history_container.pack(fill='x', padx=14, pady=(0, 12))
                    for index, (_, entry) in enumerate(grouped.iterrows()):
                        ts = entry['timestamp'] if pd.notna(entry['timestamp']) else 'N/A'
                        supplier = entry['supplier'] if pd.notna(entry['supplier']) else 'Unknown'
                        items = int(entry['items'])
                        total_qty = entry['total_qty']
                        if index:
                            tk.Frame(history_container, bg=THEME_BORDER,
                                     height=1).pack(fill='x')
                        history_row = tk.Frame(history_container, bg=THEME_CARD)
                        history_row.pack(fill='x', pady=7)
                        tk.Label(history_row, text=ts, font=ui_theme.mono_font(9),
                                 fg=THEME_TEXT_MUTED, bg=THEME_CARD,
                                 anchor='w', width=18).pack(side='left')
                        tk.Label(history_row, text=supplier,
                                 font=ui_theme.display_font(12), fg=THEME_TEXT,
                                 bg=THEME_CARD, anchor='w').pack(side='left')
                        tk.Label(history_row,
                                 text=f"{items} items  ·  +{total_qty:.1f} units",
                                 font=ui_theme.mono_font(9),
                                 fg=THEME_TEXT_MUTED, bg=THEME_CARD,
                                 anchor='e').pack(side='right')
                else:
                    self.themed_label(history_card, "No deliveries yet", font=(ui_theme.THEME_FONT, 9),
                                      fg=THEME_TEXT_MUTED).pack(padx=14, pady=10)
            else:
                self.themed_label(history_card, "No deliveries yet", font=(ui_theme.THEME_FONT, 9),
                                  fg=THEME_TEXT_MUTED).pack(padx=14, pady=10)
        except Exception:
            self.themed_label(history_card, "Unable to load recent deliveries", font=(ui_theme.THEME_FONT, 9),
                              fg=THEME_TEXT_MUTED).pack(padx=14, pady=10)
    
        self.root.update_idletasks()
        self._apply_legacy_theme()


    def repeat_last_delivery(self, supplier=None):
        """Open delivery entry pre-filled with the most recent delivery's lines.
    
        Weekly deliveries from the same supplier are usually close to
        identical, so this turns the common case into "check quantities and
        save" instead of re-entering every item.
        """
        self.refresh_data()
        if self.log_df.empty:
            self._set_status("No previous deliveries to repeat.", 'warning')
            return
    
        deliveries = self.log_df[self.log_df[COL_ACTION] == ACTION_DELIVERY]
        if supplier and supplier != "Select supplier...":
            deliveries = deliveries[deliveries[COL_SUPPLIER] == supplier]
        if deliveries.empty:
            self._set_status("No previous delivery from that supplier.", 'warning')
            return
    
        latest = deliveries[COL_TIMESTAMP].max()
        lines = deliveries[deliveries[COL_TIMESTAMP] == latest]
        prefill = []
        for _, line in lines.iterrows():
            item_id = line[COL_ITEM_ID]
            rows = self.inventory_df[self.inventory_df[COL_ITEM_ID] == item_id]
            if rows.empty:
                continue
            qty = float(line[COL_QUANTITY] or 0)
            cost = float(line[COL_COST_PRICE] or 0)
            current = float(rows.iloc[0][COL_QUANTITY] or 0)
            prefill.append((item_id, rows.iloc[0][COL_ITEM_NAME], qty,
                            current + qty, cost, qty * cost))
    
        if not prefill:
            self._set_status("The last delivery's items are no longer in stock.", 'warning')
            return
    
        resolved_supplier = str(lines.iloc[0].get(COL_SUPPLIER) or supplier or 'Unknown')
        self.current_delivery_supplier = resolved_supplier
        self.process_delivery_multi_item(prefill=prefill)


    def process_delivery_multi_item(self, prefill=None):
        """Process a delivery with multiple items."""
        self.clear_main_menu()
    
        supplier_name = getattr(self, 'current_delivery_supplier', 'Unknown')

        self.refresh_data()
        from sales_mapping import get_hidden_items
        excluded_ids = set(get_hidden_items()) | {i.lower() for i in EXCLUDED_ITEMS}
        # Delisted lines are out of stock and cannot be delivered again, so they
        # stay out of both the item list and the frequently-delivered shortcuts.
        excluded_ids |= {
            str(row[COL_ITEM_ID]).lower()
            for _, row in self.inventory_df.iterrows()
            if is_delisted(row[COL_ITEM_ID])
        }
        full_item_list = [
            f"{row[COL_ITEM_ID]} - {row[COL_ITEM_NAME]}"
            for _, row in self.inventory_df.iterrows()
            if row[COL_ITEM_ID].lower() not in excluded_ids
        ]
        if not full_item_list:
            messagebox.showerror("Error", "No parent items available for delivery. Please add stock first.")
            self.show_dashboard()
            return
    
        # Delivery details card
        details_card = self._card(self.main_menu, title="Delivery Details")
        details_card.pack(fill='x', pady=(0, 20))
    
        details_row = self._form_row(details_card)
        sup_frame = tk.Frame(details_row, bg=THEME_CARD)
        sup_frame.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
        tk.Label(sup_frame, text="SUPPLIER", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_CARD, anchor='w').pack(fill='x')
        tk.Label(sup_frame, text=supplier_name, font=ui_theme.display_font(14),
                 fg=THEME_TEXT, bg=THEME_CARD, anchor='w').pack(fill='x', pady=(4, 0))
    
        date_frame = tk.Frame(details_row, bg=THEME_CARD)
        date_frame.grid(row=0, column=1, sticky='nsew', padx=5, pady=5)
        tk.Label(date_frame, text="DELIVERY DATE", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_CARD, anchor='w').pack(fill='x')
        date_entry_frame = tk.Frame(date_frame, bg=THEME_CARD)
        date_entry_frame.pack(fill='x', pady=(4, 0))
        delivery_date_var = tk.StringVar(value=datetime.now().strftime(DATE_FORMAT_DISPLAY))
        delivery_date_entry = self.styled_entry(
            date_entry_frame, textvariable=delivery_date_var, width=12,
            font=(ui_theme.THEME_FONT, 12))
        delivery_date_entry.pack(side='left')
        self.styled_button(date_entry_frame, "Pick date",
                           lambda: self.show_calendar(delivery_date_var, self.root),
                           width=9, variant='secondary').pack(
            side='left', padx=(6, 0))
    
        # Add item card
        item_card = self._card(self.main_menu, title="Add Item")
        item_card.pack(fill='x', pady=(0, 20))
    
        search_frame = tk.Frame(item_card, bg=THEME_CARD)
        search_frame.pack(fill='x', padx=14, pady=(8, 6))
        tk.Label(search_frame, text="SEARCH", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_CARD, anchor='w').pack(fill='x')
        search_var = tk.StringVar()
        search_entry = self.styled_entry(
            search_frame, textvariable=search_var, width=15,
            font=(ui_theme.THEME_FONT, 12))
        search_entry.pack(fill='x', pady=(4, 0))
        search_entry.insert(0, "Type to search...")
        search_entry.config(fg=THEME_TEXT_MUTED)
    
        def on_search_focus_in(event):
            if search_var.get() == "Type to search...":
                search_entry.delete(0, tk.END)
                search_entry.config(fg=THEME_TEXT)
    
        def on_search_focus_out(event):
            if not search_var.get().strip():
                search_entry.insert(0, "Type to search...")
                search_entry.config(fg=THEME_TEXT_MUTED)
    
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
    
        item_frame = tk.Frame(item_card, bg=THEME_CARD)
        item_frame.pack(fill='x', padx=14, pady=6)
        tk.Label(item_frame, text="ITEM", font=ui_theme.mono_font(8),
                 fg=THEME_TEXT_MUTED, bg=THEME_CARD, anchor='w').pack(fill='x')
        item_var = tk.StringVar()
        item_dropdown = ttk.Combobox(item_frame, textvariable=item_var,
                                       values=full_item_list, width=35, state="readonly")
        item_dropdown.pack(fill='x', pady=(4, 0))
        item_dropdown.set("Select an item...")
    
        # Quick pick: most frequently delivered items, so repeat business does
        # not begin with a scroll through the whole inventory.
        quick_ids = []
        try:
            delivery_log = self.log_df[self.log_df[COL_ACTION] == ACTION_DELIVERY]
            if not delivery_log.empty:
                quick_ids = (delivery_log.groupby(COL_ITEM_ID).size()
                             .sort_values(ascending=False).head(8).index.tolist())
        except Exception:
            quick_ids = []
    
        if quick_ids:
            quick_frame = tk.Frame(item_card, bg=THEME_CARD)
            quick_frame.pack(fill='x', padx=14, pady=(0, 2))
            tk.Label(quick_frame, text="FREQUENTLY DELIVERED", font=ui_theme.mono_font(8),
                     fg=THEME_TEXT_MUTED, bg=THEME_CARD, anchor='w').pack(fill='x')
            quick_row = tk.Frame(quick_frame, bg=THEME_CARD)
            quick_row.pack(fill='x', pady=(4, 0))
            names_by_id = dict(zip(self.inventory_df[COL_ITEM_ID],
                                   self.inventory_df[COL_ITEM_NAME]))
            for quick_id in quick_ids:
                if quick_id.lower() in excluded_ids:
                    continue
                label = str(names_by_id.get(quick_id, quick_id))[:16]
                self.styled_button(
                    quick_row, label,
                    lambda i=quick_id: quick_select(i),
                    width=14, variant='secondary',
                ).pack(side='left', padx=(0, 6))
    
        qty_cost_row = self._form_row(item_card)
        qty_frame = tk.Frame(qty_cost_row, bg=THEME_CARD)
        qty_frame.grid(row=0, column=0, sticky='nsew', padx=5, pady=5)
        qty_label = tk.Label(qty_frame, text="QUANTITY", font=ui_theme.mono_font(8),
                             fg=THEME_TEXT_MUTED, bg=THEME_CARD, anchor='w')
        qty_label.pack(fill='x')
        entry_quantity = self.styled_entry(qty_frame, width=15,
                                           font=(ui_theme.THEME_FONT, 12))
        entry_quantity.pack(fill='x', pady=(4, 0))
        stock_label = tk.Label(qty_frame, text="Current stock: -", font=ui_theme.mono_font(9),
                               fg=THEME_TEXT_MUTED, bg=THEME_CARD, anchor='w')
        stock_label.pack(fill='x', pady=(2, 0))
    
        cost_frame = tk.Frame(qty_cost_row, bg=THEME_CARD)
        cost_frame.grid(row=0, column=1, sticky='nsew', padx=5, pady=5)
        cost_label = tk.Label(cost_frame, text="COST PRICE (EX VAT) (£)", font=ui_theme.mono_font(8),
                              fg=THEME_TEXT_MUTED, bg=THEME_CARD, anchor='w')
        cost_label.pack(fill='x')
        entry_cost_price = self.styled_entry(cost_frame, width=15,
                                             font=(ui_theme.THEME_FONT, 12))
        entry_cost_price.pack(fill='x', pady=(4, 0))
        gp_label = tk.Label(cost_frame, text="GP: -", font=ui_theme.mono_font(9),
                            fg=THEME_TEXT_MUTED, bg=THEME_CARD, anchor='w')
        gp_label.pack(fill='x', pady=(2, 0))
        conversion_label = tk.Label(cost_frame, text="", font=ui_theme.mono_font(9),
                                    fg=THEME_TEXT_MUTED, bg=THEME_CARD, anchor='w')
        conversion_label.pack(fill='x', pady=(0, 0))
    
        # Track currently selected item for conversion
        selected_item_id = [None]
        selected_sell_price = [0.0]
        selected_factor = [1.0]
        selected_has_conversion = [False]
        last_delivery_cost_per_unit = [0.0]
    
        def update_gp_label(event=None):
            try:
                cost = float(entry_cost_price.get().strip())
                if selected_has_conversion[0] and selected_factor[0] > 0:
                    cost = cost / selected_factor[0]
                sell = selected_sell_price[0]
                if sell > 0:
                    gp_pct = ((sell - cost) / sell) * 100
                    color = THEME_DANGER if gp_pct < 60 else THEME_SUCCESS
                    gp_label.config(text=f"GP: {gp_pct:.1f}%", fg=color)
                else:
                    gp_label.config(text="GP: -", fg=THEME_TEXT_MUTED)
            except:
                gp_label.config(text="GP: -", fg=THEME_TEXT_MUTED)
    
        def on_cost_change(event=None):
            if last_delivery_cost_per_unit[0] <= 0:
                return
            try:
                entered_cost = float(entry_cost_price.get().strip())
                if selected_has_conversion[0] and selected_factor[0] > 0:
                    comparison_cost = last_delivery_cost_per_unit[0] * selected_factor[0]
                    label = "pack"
                else:
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
            selected = item_var.get()
            if selected and selected != "Select an item...":
                item_id = selected.split(" - ")[0]
                selected_item_id[0] = item_id
                try:
                    from conversions import requires_conversion, get_input_label, format_stock_display, get_conversion
                    qty = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY].values[0]
                    cost_price = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_COST_PRICE].values[0]
                    sell_price = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_SELL_PRICE].values[0]
                    selected_sell_price[0] = sell_price
    
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
                        qty_label.config(text=f"QUANTITY ({input_unit.upper()}S)")
                        conversion_label.config(text=f"1 {input_unit} = {factor} {output_unit}s")
                        selected_factor[0] = factor
                        selected_has_conversion[0] = True
                        cost_label.config(text="PACK COST (EX VAT) (£)")
                        entry_cost_price.delete(0, tk.END)
                        entry_cost_price.insert(0, f"{last_delivery_cost_per_unit[0] * factor:.2f}")
                    else:
                        stock_label.config(text=f"Current stock: {qty:.1f}")
                        qty_label.config(text="QUANTITY")
                        conversion_label.config(text="")
                        selected_factor[0] = 1.0
                        selected_has_conversion[0] = False
                        cost_label.config(text="COST PRICE (EX VAT) (£)")
                        entry_cost_price.delete(0, tk.END)
                        entry_cost_price.insert(0, f"{last_delivery_cost_per_unit[0]:.2f}")
                    update_gp_label()
                except:
                    stock_label.config(text="Current stock: -")
                    qty_label.config(text="QUANTITY")
                    conversion_label.config(text="")
                    gp_label.config(text="GP: -", fg=THEME_TEXT_MUTED)
                    entry_cost_price.delete(0, tk.END)
            else:
                selected_item_id[0] = None
                selected_sell_price[0] = 0.0
                selected_factor[0] = 1.0
                selected_has_conversion[0] = False
                last_delivery_cost_per_unit[0] = 0.0
                stock_label.config(text="Current stock: -")
                qty_label.config(text="QUANTITY")
                conversion_label.config(text="")
                gp_label.config(text="GP: -", fg=THEME_TEXT_MUTED)
                entry_cost_price.delete(0, tk.END)
    
        item_dropdown.bind("<<ComboboxSelected>>", on_item_select)
    
        def quick_select(item_id):
            match = next((entry for entry in full_item_list
                          if entry.startswith(f"{item_id} - ")), None)
            if match is None:
                return
            item_var.set(match)
            on_item_select()
            entry_quantity.focus_set()
    
        delivery_items = []
    
        def add_item_to_delivery():
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
                input_quantity = float(quantity_str)
                if input_quantity <= 0:
                    messagebox.showerror("Error", "Quantity must be greater than zero.")
                    return
            except ValueError:
                messagebox.showerror("Error", "Quantity must be a valid number.")
                return
    
            from conversions import requires_conversion, convert_to_system, get_conversion, get_input_label
            if requires_conversion(item_id):
                quantity = convert_to_system(item_id, input_quantity)
                conversion = get_conversion(item_id)
                input_unit = conversion[0] if conversion else "units"
                output_unit = conversion[2] if conversion else "units"
                conversion_msg = f" ({input_quantity:.1f} {input_unit}s = {quantity:.1f} {output_unit}s)"
            else:
                quantity = input_quantity
                conversion_msg = ""
    
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
    
            conv_factor = 1.0
            if requires_conversion(item_id):
                conv = get_conversion(item_id)
                if conv:
                    conv_factor = conv[1]
            cost_price = pack_cost / conv_factor if conv_factor > 0 else pack_cost
    
            item_row = self.inventory_df[self.inventory_df[COL_ITEM_ID] == item_id].iloc[0]
            item_name = item_row[COL_ITEM_NAME]
            current_qty = item_row[COL_QUANTITY]
            new_qty = current_qty + quantity
            sell_price = item_row[COL_SELL_PRICE]
    
            gp_pct = ((sell_price - cost_price) / sell_price * 100) if sell_price > 0 else 0
            if gp_pct < 60:
                if not messagebox.askyesno("Low GP Warning", f"The GP for {item_name} is {gp_pct:.1f}% (below 60%).\nAre you sure you want to add this item?"):
                    return
    
            line_total_cost = pack_cost * input_quantity
    
            for i, (existing_id, _, existing_qty, _, existing_price, existing_line_total) in enumerate(delivery_items):
                if existing_id == item_id:
                    new_total_qty = existing_qty + quantity
                    new_total_line_cost = existing_line_total + line_total_cost
                    new_new_qty = current_qty + new_total_qty
                    if messagebox.askyesno("Item Already Added", f"'{item_name}' is already in this delivery.\nDo you want to add {quantity:.1f} more to the existing {existing_qty:.1f}?{conversion_msg}"):
                        delivery_items[i] = (item_id, item_name, new_total_qty, new_new_qty, cost_price, new_total_line_cost)
                        refresh_items_list()
                        item_dropdown.set("Select an item...")
                        entry_quantity.delete(0, tk.END)
                        entry_cost_price.delete(0, tk.END)
                        gp_label.config(text="GP: -", fg=THEME_TEXT_MUTED)
                        stock_label.config(text="Current stock: -")
                        conversion_label.config(text="")
                    return
    
            delivery_items.append((item_id, item_name, quantity, new_qty, cost_price, line_total_cost))
            refresh_items_list()
    
            item_dropdown.set("Select an item...")
            entry_quantity.delete(0, tk.END)
            entry_cost_price.delete(0, tk.END)
            gp_label.config(text="GP: -", fg=THEME_TEXT_MUTED)
            stock_label.config(text="Current stock: -")
            conversion_label.config(text="")
    
        def refresh_items_list():
            from conversions import requires_conversion, format_stock_display, get_conversion
            for item in items_tree.get_children():
                items_tree.delete(item)
            total_cost = 0.0
            for index, (item_id, item_name, quantity, new_qty, cost_price, line_total_cost) in enumerate(delivery_items):
                new_qty_display = format_stock_display(item_id, new_qty) if requires_conversion(item_id) else f"{new_qty:.1f}"
                display_cost = cost_price
                if requires_conversion(item_id):
                    conv = get_conversion(item_id)
                    if conv:
                        display_cost = cost_price * conv[1]
                items_tree.insert('', tk.END, tags=('alt',) if index % 2 else (),
                                  values=(item_id, item_name, f"{quantity:.1f}", new_qty_display, f"£{display_cost:.2f}"))
                total_cost += line_total_cost
            total_cost_label.config(text=f"£{total_cost:.2f}")
    
        def remove_selected_item():
            selected = items_tree.selection()
            if not selected:
                messagebox.showerror("Error", "Please select an item to remove.")
                return
    
            item_values = items_tree.item(selected[0], 'values')
            item_id = item_values[0]
    
            for i, (del_id, _, _, _, _, _) in enumerate(delivery_items):
                if del_id == item_id:
                    delivery_items.pop(i)
                    break
    
            items_tree.delete(selected[0])
            refresh_items_list()
    
        def save_delivery():
            if not delivery_items:
                messagebox.showerror("Error", "No items to save. Please add at least one item.")
                return
    
            try:
                self.refresh_data()
    
                delivery_date = delivery_date_var.get().strip()
                try:
                    parsed_date = parse_display_date(delivery_date)
                except ValueError:
                    messagebox.showerror("Error", "Invalid date format. Use DD-MM-YYYY.")
                    return
    
                timestamp = f"{parsed_date.strftime('%Y-%m-%d')} {datetime.now().strftime('%H:%M:%S')}"
                supplier = getattr(self, 'current_delivery_supplier', '')
    
                log_entries = []
    
                for item_id, item_name, quantity, _, cost_price, pack_cost in delivery_items:
                    self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] += quantity
                    self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_COST_PRICE] = cost_price
    
                    sell_price = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_SELL_PRICE].values[0]
    
                    log_entries.append([item_id, ACTION_DELIVERY, quantity, timestamp, cost_price, sell_price, supplier, "", ""])
    
                if log_entries:
                    new_log_df = pd.DataFrame(log_entries, columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON])
                    self.log_df = pd.concat([self.log_df, new_log_df], ignore_index=True)
    
                if self._persist():
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
    
                    if hasattr(self, 'current_delivery_supplier'):
                        delattr(self, 'current_delivery_supplier')
    
                    self.update_dashboard_stats()
                    self.show_dashboard()
                else:
                    messagebox.showerror("Error", "Failed to save delivery. Data may be inconsistent.")
    
            except Exception as e:
                messagebox.showerror("Error", f"Delivery failed: {e}")
    
        def cancel_delivery():
            if delivery_items:
                if not messagebox.askyesno("Cancel Delivery", f"You have {len(delivery_items)} items in this delivery.\nAre you sure you want to cancel?"):
                    return
    
            if hasattr(self, 'current_delivery_supplier'):
                delattr(self, 'current_delivery_supplier')
            self.show_dashboard()
    
        # Add/remove item buttons
        add_remove_frame = self.themed_frame(item_card, bg=THEME_CARD)
        add_remove_frame.pack(fill='x', padx=14, pady=(8, 12))
        self.styled_button(add_remove_frame, "Add to Delivery", add_item_to_delivery,
                           width=18, variant='primary').pack(side='left', padx=(0, 10))
        self.styled_button(add_remove_frame, "Remove Selected", remove_selected_item,
                           width=18, variant='secondary').pack(side='left')
    
        # Items in this delivery card
        list_card = self._card(self.main_menu, title="Items in this Delivery")
        list_card.pack(fill='both', expand=True, pady=(0, 20))
    
        columns = ('item_id', 'item_name', 'quantity', 'new_stock', 'cost_price')
        items_tree = ttk.Treeview(list_card, columns=columns, show='headings', height=10)
        items_tree.heading('item_id', text='Item ID', anchor='w')
        items_tree.heading('item_name', text='Name', anchor='w')
        items_tree.heading('quantity', text='Qty Added', anchor='e')
        items_tree.heading('new_stock', text='New Stock Level', anchor='e')
        items_tree.heading('cost_price', text='Cost Price', anchor='e')
        self._make_sortable(items_tree)
        items_tree.column('item_id', width=80, anchor='w')
        items_tree.column('item_name', width=120, anchor='w')
        items_tree.column('quantity', width=70, anchor='e')
        items_tree.column('new_stock', width=90, anchor='e')
        items_tree.column('cost_price', width=80, anchor='e')
        items_tree.tag_configure('alt', background=TBL_ROW_ALT,
                                 foreground=THEME_TEXT)
        items_tree.pack(fill='both', expand=True, padx=14, pady=5)
    
        scrollbar = ttk.Scrollbar(list_card, orient=tk.VERTICAL, command=items_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        items_tree.configure(yscrollcommand=scrollbar.set)
        self._bind_treeview_mousewheel(items_tree)
    
        total_frame = self.themed_frame(list_card, bg=THEME_CARD)
        total_frame.pack(fill='x', padx=14, pady=(0, 10))
        tk.Label(total_frame, text="TOTAL DELIVERY COST", font=ui_theme.mono_font(9),
                 fg=THEME_TEXT, bg=THEME_CARD).pack(side='left')
        total_cost_label = tk.Label(total_frame, text="£0.00", font=ui_theme.display_font(16),
                                    fg=THEME_TEXT, bg=THEME_CARD)
        total_cost_label.pack(side='right')
    
        # Bottom actions
        bottom_frame = self.themed_frame(self.main_menu)
        bottom_frame.pack(fill='x', pady=(0, 20))
        self.styled_button(bottom_frame, "Save Delivery", save_delivery,
                           width=18, variant='primary').pack(side='left', padx=(0, 10))
        self.styled_button(bottom_frame, "Cancel", cancel_delivery,
                           width=16, variant='secondary').pack(side='left')
    
        if prefill:
            delivery_items.extend(prefill)
            refresh_items_list()
    
        self.root.update_idletasks()
        self._apply_legacy_theme()
