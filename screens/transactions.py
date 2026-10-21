#!/usr/bin/env python3
"""Transaction log, open tabs, wastage, complimentary and supplier returns."""

import os
from datetime import datetime

import pandas as pd
import tkinter as tk
from tkinter import messagebox, ttk

import ui_theme
from app_config import (
    COL_ACTION, COL_COST_PRICE, COL_DATE_RANGE, COL_ITEM_ID, COL_ITEM_NAME,
    COL_QUANTITY, COL_REASON, COL_SELL_PRICE, COL_SUPPLIER, COL_TIMESTAMP,
    get_script_directory,
)
from actions import (
    ACTION_COMPLIMENTARY, ACTION_DELIVERY, ACTION_SUPPLIER_RETURN, ACTION_WASTAGE,
)
from conversions import (
    convert_to_system, format_stock_display, get_conversion, get_input_label,
    requires_conversion,
)
from data_manager import InventoryDataManager, COL_ALLOW_NEGATIVE
from sales_mapping import (
    apply_sale_to_parent, check_apply_sale_to_parent, get_effective_cost_price,
    has_parent_stock,
)
from supplier_mapping import get_supplier, get_supplier_order


class TransactionsMixin:
    """Transaction and open-tab methods mixed into the main application class."""

    def show_transactions(self):
        """Show the transaction log inside the app shell."""
        self._create_app_shell('Transactions')
        self.view_transaction_log()


    def view_transaction_log(self):
        """View the complete transaction log."""
        self.clear_main_menu()
    
        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
    
        tk.Label(header_frame, text="Transaction Log",
                font=(ui_theme.THEME_FONT, 16, 'bold')).pack(expand=True)
    
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
    
            self._make_sortable(log_tree)
    
            log_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    
            scrollbar = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=log_tree.yview)
            scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
            log_tree.configure(yscrollcommand=scrollbar.set)
            self._bind_treeview_mousewheel(log_tree)
    
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
    
        self._apply_legacy_theme()


    def show_open_tabs(self):
        """Show the open tabs menu inside the app shell."""
        self._create_app_shell('Open Tabs')
        self.open_tabs_menu()


    def open_tabs_menu(self):
        """Display the Open Tabs menu with options to create or view tabs."""
        self.clear_main_menu()
    
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
        tk.Label(header_frame, text="Open Tabs", font=(ui_theme.THEME_FONT, 16, 'bold')).pack(expand=True)
    
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=20)
    
        tk.Button(btn_frame, text="Create New Tab", command=self.create_open_tab_dialog, width=25).pack(pady=5)
        tk.Button(btn_frame, text="View / Close Tabs", command=self.view_open_tabs, width=25).pack(pady=5)
        tk.Button(btn_frame, text="Back", command=self.show_dashboard, width=25).pack(pady=5)


    def create_open_tab_dialog(self):
        """Dialog to create a new open tab (multi-item, customer name)."""
        self.clear_main_menu()
    
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
        tk.Label(header_frame, text="Create Open Tab", font=(ui_theme.THEME_FONT, 16, 'bold')).pack(expand=True)
    
        main_frame = tk.Frame(self.main_menu)
        main_frame.pack(pady=10, padx=20, fill='both', expand=True)
    
        # Left side - Item entry
        entry_frame = tk.LabelFrame(main_frame, text="Add Items", font=(ui_theme.THEME_FONT, 10, 'bold'))
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
            self.show_dashboard()
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
    
        stock_label = tk.Label(entry_frame, text="Current stock: -", font=(ui_theme.THEME_FONT, 9), fg='gray')
        stock_label.grid(row=4, column=1, padx=5, pady=2, sticky="w")
    
        conversion_label = tk.Label(entry_frame, text="", font=(ui_theme.THEME_FONT, 9), fg='gray')
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
    
        list_frame = tk.LabelFrame(main_frame, text="Items in this Tab", font=(ui_theme.THEME_FONT, 10, 'bold'))
        list_frame.pack(side=tk.RIGHT, fill='both', expand=True)
    
        columns = ('item_id', 'item_name', 'quantity')
        items_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=10)
        items_tree.heading('item_id', text='Item ID')
        items_tree.heading('item_name', text='Name')
        items_tree.heading('quantity', text='Qty')
        self._make_sortable(items_tree)
        items_tree.column('item_id', width=80)
        items_tree.column('item_name', width=120)
        items_tree.column('quantity', width=60)
        items_tree.pack(fill='both', expand=True, padx=5, pady=5)
    
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=items_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        items_tree.configure(yscrollcommand=scrollbar.set)
        self._bind_treeview_mousewheel(items_tree)
    
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
    
                # Stock was deducted atomically inside create_open_tab; refresh
                # the in-memory DataFrame from the database so the UI stays in sync.
                self.refresh_data()
                self._set_status(
                    f"Tab saved for '{customer_name}' ({len(transaction_items)} items).",
                    'success')
                self.update_dashboard_stats()
                self.open_tabs_menu()
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
        tk.Label(header_frame, text="View Open Tabs", font=(ui_theme.THEME_FONT, 16, 'bold')).pack(expand=True)
    
        # Load open tabs
        tabs_df = InventoryDataManager.get_open_tabs(status='open')
    
        if tabs_df.empty:
            tk.Label(self.main_menu, text="No open tabs.", font=(ui_theme.THEME_FONT, 12)).pack(pady=20)
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
        self._make_sortable(tabs_tree)
        tabs_tree.column('tab_id', width=60, anchor='center')
        tabs_tree.column('customer', width=150)
        tabs_tree.column('items', width=250)
        tabs_tree.column('total_qty', width=80, anchor='center')
        tabs_tree.column('created_at', width=150, anchor='center')
        tabs_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    
        scrollbar = ttk.Scrollbar(tree_container, orient=tk.VERTICAL, command=tabs_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tabs_tree.configure(yscrollcommand=scrollbar.set)
        self._bind_treeview_mousewheel(tabs_tree)
    
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
                self._set_status(f"Tab {tab_id} closed as sale; stock updated.", 'success')
                self.update_dashboard_stats()
                self.view_open_tabs()
            else:
                messagebox.showerror("Error", "Failed to close tab.")
    
        def close_as_complimentary():
            selected = tabs_tree.selection()
            if not selected:
                messagebox.showerror("Error", "Please select a tab to close as complimentary.")
                return
            item_values = tabs_tree.item(selected[0], 'values')
            tab_id = int(item_values[0])
    
            if not messagebox.askyesno("Confirm", "Close this tab as complimentary? Stock will remain deducted and no sale will be recorded."):
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
    
            if InventoryDataManager.close_open_tab_as_complimentary(tab_id, items_for_db):
                # Reload log to include complimentary transactions
                self.log_df = InventoryDataManager.load_log(self.inventory_df)
                self._set_status(f"Tab {tab_id} closed as complimentary; stock updated.", 'success')
                self.update_dashboard_stats()
                self.view_open_tabs()
            else:
                messagebox.showerror("Error", "Failed to close tab as complimentary.")
    
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
    
            # Stock was restored atomically inside cancel_open_tab; refresh the
            # in-memory DataFrame from the database so the UI stays in sync.
            self.refresh_data()
            self.log_df = InventoryDataManager.load_log(self.inventory_df)
            self._set_status(f"Tab {tab_id} cancelled and stock restored.", 'success')
            self.update_dashboard_stats()
            self.view_open_tabs()
    
        btn_frame = tk.Frame(self.main_menu)
        btn_frame.pack(pady=10)
        tk.Button(btn_frame, text="Close as Sale", command=close_as_sale, width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Close as Complimentary", command=close_as_complimentary, width=20).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel Tab", command=cancel_tab, width=15).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Back", command=self.open_tabs_menu, width=15).pack(side=tk.LEFT, padx=5)
    
        self.root.update_idletasks()


    def add_wastage(self):
        """Add wastage transactions (multi-item like delivery)."""
        self.process_multi_transaction(ACTION_WASTAGE)


    def add_complimentary(self):
        """Add complimentary transactions (multi-item like delivery)."""
        self.process_multi_transaction(ACTION_COMPLIMENTARY)


    def add_supplier_return(self):
        """Add supplier return transactions (multi-item)."""
        self.process_multi_transaction(ACTION_SUPPLIER_RETURN)


    def process_multi_transaction(self, action):
        """Process wastage, complimentary or supplier return transactions with multiple items."""
        self.clear_main_menu()
    
        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
    
        tk.Label(header_frame, text=f"Add {action}", font=(ui_theme.THEME_FONT, 16, 'bold')).pack(expand=True)
    
        # Main container
        main_frame = tk.Frame(self.main_menu)
        main_frame.pack(pady=10, padx=20, fill='both', expand=True)
    
        # Left side - Item entry
        entry_frame = tk.LabelFrame(main_frame, text=f"Add Items ({action})", font=(ui_theme.THEME_FONT, 10, 'bold'))
        entry_frame.pack(side=tk.LEFT, fill='both', expand=True, padx=(0, 10))
    
        # Search bar
        tk.Label(entry_frame, text="Search:").grid(row=0, column=0, padx=5, pady=8, sticky="e")
        self.refresh_data()
        full_item_list = [f"{row[COL_ITEM_ID]} - {row[COL_ITEM_NAME]}" for _, row in self.inventory_df.iterrows()]
    
        if not full_item_list:
            messagebox.showerror("Error", "No items in inventory. Please add items first.")
            self.show_dashboard()
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
    
        # Reason dropdown for Wastage, Complimentary and Supplier Return
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
        elif action == ACTION_SUPPLIER_RETURN:
            tk.Label(entry_frame, text="Reason:").grid(row=3, column=0, padx=5, pady=8, sticky="e")
            reason_var = tk.StringVar(value="Faulty Keg")
            reason_dropdown = ttk.Combobox(entry_frame, textvariable=reason_var,
                                           values=["Faulty Keg", "Out of Date", "Damaged", "Wrong Product", "Other"],
                                           width=33, state="readonly")
            reason_dropdown.grid(row=3, column=1, padx=5, pady=8, sticky="w")
    
            tk.Label(entry_frame, text="Supplier:").grid(row=4, column=0, padx=5, pady=8, sticky="e")
            supplier_var = tk.StringVar(value="Tennents")
            supplier_dropdown = ttk.Combobox(entry_frame, textvariable=supplier_var,
                                             values=get_supplier_order() + ["Other"],
                                             width=33, state="readonly")
            supplier_dropdown.grid(row=4, column=1, padx=5, pady=8, sticky="w")
            stock_row = 5
            conv_row = 6
            btn_row = 7
        else:
            stock_row = 3
            conv_row = 4
            btn_row = 5
    
        stock_label = tk.Label(entry_frame, text="Current stock: -", font=(ui_theme.THEME_FONT, 9), fg='gray')
        stock_label.grid(row=stock_row, column=1, padx=5, pady=2, sticky="w")
    
        conversion_label = tk.Label(entry_frame, text="", font=(ui_theme.THEME_FONT, 9), fg='gray')
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
                    if action == ACTION_SUPPLIER_RETURN:
                        mapped_supplier = get_supplier(item_id)
                        supplier_var.set(mapped_supplier)
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
        list_frame = tk.LabelFrame(main_frame, text=f"Items in this {action}", font=(ui_theme.THEME_FONT, 10, 'bold'))
        list_frame.pack(side=tk.RIGHT, fill='both', expand=True)
    
        if action == ACTION_SUPPLIER_RETURN:
            columns = ('item_id', 'item_name', 'quantity', 'reason', 'supplier')
        else:
            columns = ('item_id', 'item_name', 'quantity', 'reason')
        items_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=10)
        items_tree.heading('item_id', text='Item ID')
        items_tree.heading('item_name', text='Name')
        items_tree.heading('quantity', text='Qty')
        items_tree.heading('reason', text='Reason')
        self._make_sortable(items_tree)
        items_tree.column('item_id', width=80)
        items_tree.column('item_name', width=120)
        items_tree.column('quantity', width=60)
        items_tree.column('reason', width=120)
        if action == ACTION_SUPPLIER_RETURN:
            items_tree.heading('supplier', text='Supplier')
            items_tree.column('supplier', width=100)
        items_tree.pack(fill='both', expand=True, padx=5, pady=5)
    
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=items_tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        items_tree.configure(yscrollcommand=scrollbar.set)
        self._bind_treeview_mousewheel(items_tree)
    
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
            reason = reason_var.get() if action in (ACTION_WASTAGE, ACTION_COMPLIMENTARY, ACTION_SUPPLIER_RETURN) else ""
            supplier = supplier_var.get() if action == ACTION_SUPPLIER_RETURN else ""
    
            # Check if already added
            for i, (eid, _, eqty, _, _) in enumerate(transaction_items):
                if eid == item_id:
                    transaction_items[i] = (eid, item_name, eqty + quantity, reason, supplier)
                    refresh_list()
                    item_dropdown.set("Select an item...")
                    entry_quantity.delete(0, tk.END)
                    stock_label.config(text="Current stock: -")
                    conversion_label.config(text="")
                    return
    
            transaction_items.append((item_id, item_name, quantity, reason, supplier))
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
            for i, (eid, _, _, _, _) in enumerate(transaction_items):
                if eid == item_id:
                    transaction_items.pop(i)
                    break
            items_tree.delete(sel[0])
    
        def refresh_list():
            for item in items_tree.get_children():
                items_tree.delete(item)
            for item_id, item_name, qty, reason, supplier in transaction_items:
                if action == ACTION_SUPPLIER_RETURN:
                    items_tree.insert('', tk.END, values=(item_id, item_name, f"{qty:.1f}", reason, supplier))
                else:
                    items_tree.insert('', tk.END, values=(item_id, item_name, f"{qty:.1f}", reason))
    
        def save_all():
            if not transaction_items:
                messagebox.showerror("Error", "No items to save.")
                return
            try:
                self.refresh_data()
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                log_entries = []
    
                for item_id, item_name, quantity, reason, supplier in transaction_items:
                    # Negative stock guard for the item itself
                    ok, current_qty, _ = self.check_negative_stock(item_id, quantity)
                    if not ok:
                        messagebox.showerror("Negative Stock", f"Cannot {action.lower()} {quantity} of '{item_id}': only {current_qty} in stock.")
                        continue
    
                    # Negative parent stock guard (not applicable to supplier returns)
                    if action != ACTION_SUPPLIER_RETURN and has_parent_stock(item_id):
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
                    elif action == ACTION_SUPPLIER_RETURN:
                        self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] -= quantity
                    else:  # Complimentary
                        self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_QUANTITY] -= quantity
    
                    if action != ACTION_SUPPLIER_RETURN and has_parent_stock(item_id):
                        apply_sale_to_parent(item_id, quantity, self.inventory_df, COL_ITEM_ID, COL_QUANTITY)
    
                    cost_price = get_effective_cost_price(item_id, self.inventory_df, COL_ITEM_ID, COL_COST_PRICE)
                    sell_price = self.inventory_df.loc[self.inventory_df[COL_ITEM_ID] == item_id, COL_SELL_PRICE].values[0]
                    log_entries.append([item_id, action, quantity, timestamp, cost_price, sell_price, supplier, "", reason])
    
                if log_entries:
                    new_log_df = pd.DataFrame(log_entries, columns=[COL_ITEM_ID, COL_ACTION, COL_QUANTITY, COL_TIMESTAMP, COL_COST_PRICE, COL_SELL_PRICE, COL_SUPPLIER, COL_DATE_RANGE, COL_REASON])
                    self.log_df = pd.concat([self.log_df, new_log_df], ignore_index=True)
    
                if self._persist():
                    self._set_status(
                        f"{action} saved ({len(transaction_items)} items).",
                        'success')
                    self.update_dashboard_stats()
                    self.show_dashboard()
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
        tk.Button(bottom_frame, text="Back", command=self.show_dashboard, width=15).pack(side=tk.LEFT, padx=10)
    
        self.root.update_idletasks()


    def process_transaction(self, action):
        """Process a transaction of the specified type."""
        self.clear_main_menu()
    
        # Header
        header_frame = tk.Frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
    
        tk.Label(header_frame, text=f"Add {action}", font=(ui_theme.THEME_FONT, 16, 'bold')).pack(expand=True)
    
        frame = tk.Frame(self.main_menu)
        frame.pack(pady=10, padx=20)
    
        # Item selection via dropdown
        tk.Label(frame, text="Item:").grid(row=0, column=0, padx=5, pady=8, sticky="e")
    
        # Create list of items for dropdown
        self.refresh_data()
        item_list = [f"{row[COL_ITEM_ID]} - {row[COL_ITEM_NAME]}" for _, row in self.inventory_df.iterrows()]
    
        if not item_list:
            messagebox.showerror("Error", "No items in inventory. Please add items first.")
            self.show_dashboard()
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
        stock_label = tk.Label(frame, text="Current stock: -", font=(ui_theme.THEME_FONT, 10, 'bold'))
        stock_label.grid(row=2, column=1, padx=5, pady=5, sticky="w")
    
        # Conversion info label
        conversion_label = tk.Label(frame, text="", font=(ui_theme.THEME_FONT, 9), fg='gray')
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
                if self._persist():
                    success_msg = f"{quantity:.1f} units of item '{item_id}' recorded as {action}.{conversion_msg}"
                    if parent_adjustments:
                        names = ", ".join(desc for _, _, desc in parent_adjustments)
                        success_msg += f" Parent stock adjusted: {names}"
                    self._set_status(success_msg, 'success')
                    self.update_dashboard_stats()
                    self.show_dashboard()
                else:
                    messagebox.showerror("Error", "Failed to save transaction. Data may be inconsistent.")
    
            except Exception as e:
                messagebox.showerror("Error", f"Transaction failed: {e}")
    
        btn_frame = tk.Frame(frame)
        btn_frame.grid(row=3, column=0, columnspan=2, pady=20)
    
        tk.Button(btn_frame, text="Save Transaction", command=save_transaction, width=15).pack(side=tk.LEFT, padx=10)
        tk.Button(btn_frame, text="Back", command=self.show_dashboard, width=15).pack(side=tk.LEFT, padx=10)
    
        # Force redraw so ttk.Combobox is visible immediately on macOS
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
        if self._persist():
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
    
        self._apply_legacy_theme()
