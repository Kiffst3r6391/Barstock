#!/usr/bin/env python3
"""Stocktake screen: guided count, variance checks and the count sheet PDF."""

import os
from datetime import datetime

import tkinter as tk
from tkinter import messagebox, ttk

import ui_theme
from ui_theme import (
    THEME_ACCENT, THEME_BORDER, THEME_CARD, THEME_DANGER, THEME_SIDEBAR,
    THEME_SUCCESS, THEME_TEXT, THEME_TEXT_MUTED, THEME_WARNING,
)
from app_config import (
    COL_CATEGORY, COL_ITEM_ID, COL_ITEM_NAME, COL_MEASURE, COL_QUANTITY,
)
from categories import get_category, should_exclude
from conversions import convert_to_input, get_conversion, requires_conversion
from data_manager import record_stocktakes
from pdf_generator import PDFReport
from reports import calculate_expected_remaining_series
from sales_mapping import is_hidden_from_stock_view


class StocktakeMixin:
    """Stocktake methods mixed into the main application class."""

    def show_stocktake(self):
        """Show the Stocktake tab by wrapping the existing stocktake flow."""
        self._create_app_shell('Stocktake')
        self.full_stock_take()


    def full_stock_take(self):
        """Open the full stocktake screen."""
        self.record_stocktake()


    def record_stocktake(self):
        """Record a full stocktake snapshot with counted vs expected quantities."""
        self.clear_main_menu()
    
        # Header
        header_frame = self.themed_frame(self.main_menu, height=60)
        header_frame.pack(fill='x', pady=(0, 10))
        header_frame.pack_propagate(False)
        self.themed_label(header_frame, "Stocktake",
                          font=(ui_theme.THEME_FONT, 20, 'bold')).pack(expand=True)
    
        self.refresh_data()
    
        if self.inventory_df.empty:
            messagebox.showerror("Error", "No items in inventory. Please add items first.")
            self.show_dashboard()
            return
    
        # Controls card
        controls_card = self._card(self.main_menu, title='Controls')
        controls_card.pack(fill='x', padx=0, pady=(0, 10))
    
        controls_row = self._form_row(controls_card)
    
        note_col = self.themed_frame(controls_row, bg=THEME_CARD)
        note_col.grid(row=0, column=0, sticky='nsew', padx=(0, 8))
        self.themed_label(note_col, "Note", font=(ui_theme.THEME_FONT, 10), bg=THEME_CARD).pack(anchor='w')
        note_entry = tk.Entry(note_col, width=30, bg=THEME_CARD, fg=THEME_TEXT,
                              insertbackground=THEME_TEXT, relief='solid', bd=1,
                              highlightbackground=THEME_BORDER, highlightcolor=THEME_ACCENT)
        note_entry.pack(fill='x')
    
        search_col = self.themed_frame(controls_row, bg=THEME_CARD)
        search_col.grid(row=0, column=1, sticky='nsew', padx=(8, 0))
        self.themed_label(search_col, "Search", font=(ui_theme.THEME_FONT, 10), bg=THEME_CARD).pack(anchor='w')
        search_entry = tk.Entry(search_col, width=30, bg=THEME_CARD, fg=THEME_TEXT,
                                insertbackground=THEME_TEXT, relief='solid', bd=1,
                                highlightbackground=THEME_BORDER, highlightcolor=THEME_ACCENT)
        search_entry.pack(fill='x')
    
        # Progress + "uncounted only" filter.  The counter covers every
        # countable item (not just the filtered view), so it doubles as a
        # "have I finished the round?" check.
        progress_row = tk.Frame(controls_card, bg=THEME_CARD)
        progress_row.pack(fill='x', padx=14, pady=(4, 0))
        progress_var = tk.StringVar(value='')
        tk.Label(progress_row, textvariable=progress_var, font=(ui_theme.THEME_FONT, 10, 'bold'),
                 fg=THEME_TEXT_MUTED, bg=THEME_CARD).pack(side='left')
        uncounted_only = tk.BooleanVar(value=False)
        tk.Checkbutton(progress_row, text='Uncounted only', variable=uncounted_only,
                       command=lambda: build_table(), bg=THEME_CARD, fg=THEME_TEXT,
                       activebackground=THEME_CARD, activeforeground=THEME_TEXT,
                       selectcolor=THEME_SIDEBAR, highlightthickness=0, bd=0,
                       font=(ui_theme.THEME_FONT, 10), cursor='hand2').pack(side='right')
    
        progress_canvas = tk.Canvas(controls_card, height=6, bg=THEME_SIDEBAR,
                                    highlightthickness=0, bd=0)
        progress_canvas.pack(fill='x', padx=14, pady=(4, 10))
        progress_fill = progress_canvas.create_rectangle(0, 0, 0, 6,
                                                          fill=THEME_ACCENT, width=0)
    
        self.styled_button(controls_card, "Download PDF Sheet", self.download_stock_count_sheet,
                           width=20, variant='secondary').pack(anchor='w', padx=14, pady=(0, 12))
    
        # Items card
        items_card = self._card(self.main_menu, title='Items')
        items_card.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
    
        tree_frame = self.themed_frame(items_card, bg=THEME_CARD)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 14))
    
        columns = ('item_name', 'expected', 'counted', 'variance', 'unit')
        tree = ttk.Treeview(tree_frame, columns=columns, show='headings', selectmode='browse')
        tree.heading('item_name', text='ITEM')
        tree.heading('expected', text='EXPECTED')
        tree.heading('counted', text='COUNTED')
        tree.heading('variance', text='VARIANCE')
        tree.heading('unit', text='UNIT')
    
        tree.column('item_name', width=220, anchor='w')
        tree.column('expected', width=100, anchor='center')
        tree.column('counted', width=100, anchor='center')
        tree.column('variance', width=100, anchor='center')
        tree.column('unit', width=120, anchor='center')
    
        tree.tag_configure('success', foreground=THEME_SUCCESS)
        tree.tag_configure('danger', foreground=THEME_DANGER)
        tree.tag_configure('warning', foreground=THEME_WARNING)
        tree.tag_configure('muted', foreground=THEME_TEXT_MUTED)
    
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=tree.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        tree.configure(yscrollcommand=scrollbar.set)
        self._bind_treeview_mousewheel(tree)
    
        # Inline count editor, positioned over the Counted cell of the selected row
        count_editor = tk.Entry(tree_frame, width=10, justify='center', font=(ui_theme.THEME_FONT, 11),
                                bg=THEME_CARD, fg=THEME_TEXT, insertbackground=THEME_TEXT,
                                relief='solid', bd=1,
                                highlightbackground=THEME_ACCENT, highlightcolor=THEME_ACCENT)
    
        item_entries = []
        counts = {}
        iid_map = {}
    
        countable_ids = [
            row[COL_ITEM_ID] for _, row in self.inventory_df.iterrows()
            if not is_hidden_from_stock_view(row[COL_ITEM_ID])
            and not should_exclude(row[COL_ITEM_ID])
        ]
    
        def update_progress():
            done = sum(1 for item_id in countable_ids
                       if str(counts.get(item_id, '')).strip() != '')
            total = len(countable_ids)
            progress_var.set(f"{done} of {total} counted")
            width = max(progress_canvas.winfo_width(), 1)
            progress_canvas.coords(progress_fill, 0, 0,
                                   width * (done / total if total else 0), 6)
    
        def variance_info(counted_input, expected_system, factor):
            if counted_input < 0:
                return "Invalid", "danger"
            counted_system = counted_input * factor
            variance = counted_system - expected_system
            if variance > 0:
                return f"{variance:+.1f}", "success"
            elif variance < 0:
                return f"{variance:+.1f}", "danger"
            else:
                return "0.0", "muted"
    
        def update_row(iid, text):
            item_id = iid_map.get(iid)
            if item_id is None:
                return
            entry = next((e for e in item_entries if e['iid'] == iid), None)
            if entry is None:
                return
            counts[item_id] = text
            update_progress()
            if text.strip() == "":
                tree.set(iid, 'counted', "—")
                tree.set(iid, 'variance', "-")
                tree.item(iid, tags=('muted',))
                return
            try:
                counted_input = float(text)
                var_text, var_tag = variance_info(counted_input, entry['expected_system'], entry['factor'])
                tree.set(iid, 'counted', text)
                tree.set(iid, 'variance', var_text)
                tree.item(iid, tags=(var_tag,))
            except ValueError:
                tree.set(iid, 'counted', text)
                tree.set(iid, 'variance', "Invalid")
                tree.item(iid, tags=('danger',))
    
        def place_editor():
            selection = tree.selection()
            if not selection:
                count_editor.place_forget()
                return
            iid = selection[0]
    
            def _do():
                bbox = tree.bbox(iid, column='#3')
                if bbox:
                    count_editor.place(x=bbox[0], y=bbox[1], width=bbox[2], height=bbox[3])
                else:
                    count_editor.place_forget()
    
            tree.after_idle(_do)
    
        def update_editor(iid=None, focus=False):
            if iid is None:
                selection = tree.selection()
                if not selection:
                    count_editor.place_forget()
                    return
                iid = selection[0]
            if not tree.exists(iid):
                count_editor.place_forget()
                return
            item_id = iid_map.get(iid)
            count_editor.delete(0, tk.END)
            if item_id is not None:
                count_editor.insert(0, counts.get(item_id, ""))
            place_editor()
            if focus:
                count_editor.focus_set()
                count_editor.select_range(0, tk.END)
    
        def move_editor(delta):
            if not item_entries:
                count_editor.place_forget()
                return "break"
            selection = tree.selection()
            current_iid = selection[0] if selection else None
            idx = next((i for i, e in enumerate(item_entries) if e['iid'] == current_iid), -1)
            new_idx = idx + delta
            if 0 <= new_idx < len(item_entries):
                iid = item_entries[new_idx]['iid']
                tree.selection_set(iid)
                tree.see(iid)
                update_editor(iid, focus=True)
            elif new_idx >= len(item_entries):
                save_btn.focus_set()
            return "break"
    
        def on_tree_select(event=None):
            update_editor(focus=True)
    
        def on_editor_change(event=None):
            selection = tree.selection()
            if not selection:
                return
            update_row(selection[0], count_editor.get())
    
        def on_mousewheel(event):
            delta = event.delta
            if delta == 0:
                return 'break'
            if abs(delta) >= 120:
                steps = int(-delta / 120)
            else:
                steps = -1 if delta > 0 else 1
            tree.yview_scroll(steps, 'units')
            place_editor()
            return 'break'
    
        def bind_mousewheel(widget):
            widget.bind('<MouseWheel>', on_mousewheel)
            widget.bind('<Button-4>', lambda e: (tree.yview_scroll(-1, 'units'), place_editor(), 'break')[-1])
            widget.bind('<Button-5>', lambda e: (tree.yview_scroll(1, 'units'), place_editor(), 'break')[-1])
    
        tree.bind('<<TreeviewSelect>>', on_tree_select)
        tree.bind('<Configure>', lambda e: place_editor())
        for widget in (tree, tree_frame, items_card, controls_card, self.main_menu):
            bind_mousewheel(widget)
        count_editor.bind('<KeyRelease>', on_editor_change)
        count_editor.bind('<Tab>', lambda e: move_editor(1))
        count_editor.bind('<Shift-Tab>', lambda e: move_editor(-1))
        count_editor.bind('<Return>', lambda e: move_editor(1))
        count_editor.bind('<Down>', lambda e: move_editor(1))
        count_editor.bind('<Up>', lambda e: move_editor(-1))
        count_editor.bind('<MouseWheel>', on_mousewheel)
    
        def build_table():
            tree.delete(*tree.get_children())
            item_entries.clear()
            iid_map.clear()
            search_text = search_entry.get().strip().lower()
            hide_counted = uncounted_only.get()
    
            for _, row in self.inventory_df.iterrows():
                item_id = row[COL_ITEM_ID]
                item_name = row[COL_ITEM_NAME]
                current_stock = row[COL_QUANTITY]
    
                if is_hidden_from_stock_view(item_id) or should_exclude(item_id):
                    continue
    
                if hide_counted and str(counts.get(item_id, '')).strip() != '':
                    continue
    
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
    
                count_val = counts.get(item_id, "")
                if count_val == "":
                    var_text, var_tag = "-", "muted"
                else:
                    try:
                        var_text, var_tag = variance_info(float(count_val), current_stock, factor)
                    except ValueError:
                        var_text, var_tag = "Invalid", "danger"
    
                unit_text = f"Enter {input_unit}s"
                iid = tree.insert('', tk.END, values=(
                    item_name[:35], expected_text,
                    "—" if count_val == "" else count_val,
                    var_text, unit_text), tags=(var_tag,))
                item_entries.append({
                    'iid': iid,
                    'item_id': item_id,
                    'expected_system': current_stock,
                    'factor': factor,
                    'input_unit': input_unit,
                })
                iid_map[iid] = item_id
    
            tree.yview_moveto(0)
            if item_entries:
                tree.selection_set(item_entries[0]['iid'])
                update_editor(item_entries[0]['iid'], focus=False)
            else:
                count_editor.place_forget()
    
        build_table()
        update_progress()
        if item_entries:
            update_editor(item_entries[0]['iid'], focus=True)
        search_entry.bind('<KeyRelease>', lambda e: build_table())
    
        def count_map():
            """Every stock-countable item, independent of the search filter.
    
            Counts are stored in the `counts` dict keyed by item_id, so a count
            entered before the user typed a search term is still included when
            saving.  The old code iterated the filtered table, which silently
            dropped counts that were no longer on screen.
            """
            from conversions import requires_conversion, get_conversion
            mapping = {}
            for _, row in self.inventory_df.iterrows():
                item_id = str(row[COL_ITEM_ID])
                if is_hidden_from_stock_view(item_id) or should_exclude(item_id):
                    continue
                if requires_conversion(item_id):
                    conversion = get_conversion(item_id)
                    if conversion:
                        input_unit, factor = conversion[0], conversion[1]
                    else:
                        input_unit, factor = row[COL_MEASURE], 1
                else:
                    input_unit, factor = row[COL_MEASURE], 1
                mapping[item_id] = {
                    'item_id': item_id,
                    'factor': factor,
                    'input_unit': input_unit,
                    'expected_system': float(row[COL_QUANTITY]),
                }
            return mapping
    
        def save_stocktake():
            from data_manager import create_backup
            backup_path = create_backup('before_stocktake')
            if backup_path:
                print(f"Pre-stocktake backup created: {backup_path}")
    
            note = note_entry.get().strip()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            mapping = count_map()
            entries = []
            errors = 0
    
            for item_id, text in counts.items():
                val = (text or '').strip()
                if not val:
                    continue
                item = mapping.get(str(item_id))
                if item is None:
                    continue
                try:
                    counted_input = float(val)
                except ValueError:
                    errors += 1
                    continue
                if counted_input < 0:
                    errors += 1
                    continue
                counted_system = counted_input * item['factor']
                entries.append({
                    'item_id': item['item_id'],
                    'counted_quantity': counted_system,
                    'expected_quantity': item['expected_system'],
                    'variance': counted_system - item['expected_system'],
                })
    
            skipped = max(0, len(mapping) - len(entries) - errors)
    
            # Sanity checks: a mistyped count (an extra digit) is the most
            # common stocktake error and silently corrupts the running surplus.
            def _item_label(item_id):
                rows = self.inventory_df[self.inventory_df[COL_ITEM_ID] == item_id]
                return str(rows.iloc[0][COL_ITEM_NAME]) if not rows.empty else str(item_id)
    
            seen_ids = set()
            duplicates = set()
            suspicious = []
            for entry in entries:
                item_id = entry['item_id']
                if item_id in seen_ids:
                    duplicates.add(item_id)
                seen_ids.add(item_id)
                expected = float(entry['expected_quantity'])
                counted = float(entry['counted_quantity'])
                if expected > 0 and abs(counted - expected) > max(20.0, expected * 0.5):
                    suspicious.append((item_id, expected, counted))
                elif expected <= 0 and counted > 20:
                    suspicious.append((item_id, expected, counted))
    
            if duplicates:
                messagebox.showerror(
                    "Duplicate Items",
                    "The same item appears more than once in this stocktake:\n"
                    + "\n".join(f"  • {_item_label(i)}" for i in sorted(duplicates)),
                )
                return
    
            if suspicious:
                lines = [
                    f"  • {_item_label(i)}: expected {e:.1f}, counted {c:.1f}"
                    for i, e, c in suspicious[:10]
                ]
                if len(suspicious) > 10:
                    lines.append(f"  …and {len(suspicious) - 10} more")
                if not messagebox.askyesno(
                    "Unusual Counts",
                    "These counts differ substantially from expected stock:\n\n"
                    + "\n".join(lines)
                    + "\n\nThis is often a typo (for example an extra digit).\n"
                      "Save the stocktake anyway?",
                ):
                    return
    
            if not entries:
                if errors > 0:
                    messagebox.showwarning("No Valid Entries", f"No valid counted quantities entered.\nErrors: {errors} items")
                else:
                    messagebox.showwarning("No Entries", "No counted quantities entered. Please enter at least one count.")
                return
    
            # All snapshots, quantities and adjustment rows are written in one
            # transaction, so a failure cannot leave a half-recorded stocktake.
            result = record_stocktakes(entries, timestamp, note)
            if not result.get('success'):
                messagebox.showerror("Error", f"Stocktake was not saved:\n{result.get('error', 'unknown error')}")
                return
    
            msg = f"Stocktake saved: {result['recorded']} recorded, {skipped} skipped."
            if errors > 0:
                msg += f" {errors} errors."
            self._set_status(msg, 'success' if errors == 0 else 'warning')
    
            # Reload before showing the dashboard.  Without this the in-memory
            # frames still held pre-stocktake quantities, and any later save
            # (especially the old exit-time save) wrote them back over the
            # stocktake.
            self.refresh_data()
            self.show_dashboard()
    
        def collect_counted_items():
            """Return every valid count, regardless of the current search filter."""
            counted_items = []
            mapping = count_map()
            for item_id, text in counts.items():
                val = (text or '').strip()
                if not val:
                    continue
                item = mapping.get(str(item_id))
                if item is None:
                    continue
                try:
                    counted_input = float(val)
                except ValueError:
                    continue
                if counted_input < 0:
                    continue
                counted_items.append({
                    'item_id': item['item_id'],
                    'counted_system': counted_input * item['factor'],
                    'input_value': counted_input,
                    'input_unit': item['input_unit'],
                })
            return counted_items
    
        def confirm_unit_warning(counted_items):
            """Return False if user cancels because of suspicious units."""
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
                    return False
            return True
    
        def save_and_set_baseline():
            """Save stocktake and immediately set the counted quantities as the new baseline."""
            counted_items = collect_counted_items()
            if not counted_items:
                messagebox.showwarning("No Entries", "No counted quantities entered. Please enter at least one count.")
                return
    
            if not confirm_unit_warning(counted_items):
                return
    
            note = note_entry.get().strip()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
            if not messagebox.askyesno(
                "Confirm Baseline Reset",
                f"You are about to set a NEW BASELINE using today's stocktake ({len(counted_items)} of {len(count_map())} stock items).\n\n"
                f"This will:\n"
                f"  1. Save the stocktake snapshot\n"
                f"  2. Archive transactions before {timestamp} for the counted items only\n"
                f"  3. Set inventory to your counted quantities\n"
                f"  4. Log ACTION_STOCKTAKE_BASELINE transactions as the new starting point\n\n"
                f"Items you did not count keep their current stock and history.\n\n"
                f"Old transactions for counted items are preserved in an archive table for audit purposes.\n\n"
                f"Are you sure you want to proceed?"
            ):
                return
    
            from data_manager import create_backup, reset_baseline
            backup_path = create_backup('before_baseline_reset')
            if backup_path:
                print(f"Pre-baseline backup created: {backup_path}")
    
            result = reset_baseline(counted_items, timestamp, note)
            if not result['success']:
                return
    
            msg = (
                f"Stocktake saved and baseline reset complete!\n\n"
                f"Stocktake recorded: {result['saved_count']} items\n"
                f"Transactions archived: {result['archived_count']}\n"
                f"Baseline entries logged: {result['baseline_logged']}\n\n"
                f"From now on, all reports will calculate expected stock\n"
                f"using only transactions from {timestamp} onward."
            )
            messagebox.showinfo("Save & Baseline Complete", msg)
            self.refresh_data()
            self.show_dashboard()
    
        def set_baseline_from_stocktake():
            """Save stocktake and reset baseline: archive old transactions, set inventory, log baselines."""
            counted_items = collect_counted_items()
            if not counted_items:
                messagebox.showwarning("No Entries", "No counted quantities entered. Please enter at least one count.")
                return
    
            if not confirm_unit_warning(counted_items):
                return
    
            note = note_entry.get().strip()
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if not messagebox.askyesno(
                "Confirm Baseline Reset",
                f"You are about to set a NEW BASELINE using today's stocktake ({len(counted_items)} of {len(count_map())} stock items).\n\n"
                f"This will:\n"
                f"  1. Save the stocktake snapshot\n"
                f"  2. Archive transactions before {timestamp} for the counted items only\n"
                f"  3. Set inventory to your counted quantities\n"
                f"  4. Log ACTION_STOCKTAKE_BASELINE transactions as the new starting point\n\n"
                f"Items you did not count keep their current stock and history.\n\n"
                f"Old transactions for counted items are preserved in an archive table for audit purposes.\n\n"
                f"Are you sure you want to proceed?"
            ):
                return
    
            from data_manager import create_backup, reset_baseline
            backup_path = create_backup('before_baseline_reset')
            if backup_path:
                print(f"Pre-baseline backup created: {backup_path}")
    
            result = reset_baseline(counted_items, timestamp, note)
            if not result['success']:
                return
    
            msg = (
                f"Baseline reset complete!\n\n"
                f"Stocktake saved: {result['saved_count']} items\n"
                f"Transactions archived: {result['archived_count']}\n"
                f"Baseline entries logged: {result['baseline_logged']}\n\n"
                f"From now on, all reports will calculate expected stock\n"
                f"using only transactions from {timestamp} onward."
            )
            messagebox.showinfo("Baseline Reset Complete", msg)
            self.refresh_data()
            self.show_dashboard()
    
        def roll_forward_and_clean_action():
            """Clean old snapshots and audit rows once the baseline is confirmed."""
            if not messagebox.askyesno(
                "Roll Forward & Clean",
                "This will tidy up after your stocktake by removing old stocktake snapshots\n"
                "and old baseline reset records, leaving only the current baseline.\n\n"
                "Your current inventory and any deliveries/sales/wastage entered since\n"
                "the stocktake will NOT be touched.\n\n"
                "A full backup will be created first so old data can be recovered if needed.\n\n"
                "Do you want to continue?"
            ):
                return
    
            from data_manager import roll_forward_and_clean
            result = roll_forward_and_clean()
            if not result.get('success'):
                return
    
            msg = (
                f"Roll forward complete.\n\n"
                f"Old stocktake snapshots removed: {result.get('snapshots_removed', 0)}\n"
                f"Old baseline reset records removed: {result.get('resets_removed', 0)}\n\n"
                f"Backup saved to:\n{result.get('backup_path', 'Unknown')}\n\n"
                f"The app is now clean and ready for the next period."
            )
            messagebox.showinfo("Roll Forward & Clean Complete", msg)
            self.refresh_data()
            self.show_dashboard()
    
        def back():
            tree.unbind('<MouseWheel>')
            count_editor.place_forget()
            self.show_dashboard()
    
        # Bottom actions
        actions_frame = self.themed_frame(self.main_menu)
        actions_frame.pack(fill='x', pady=(0, 10))
    
        save_btn = self.styled_button(actions_frame, "Save Stocktake", save_stocktake, width=18, variant='primary')
        save_btn.pack(side=tk.LEFT, padx=(0, 10))
        baseline_btn = self.styled_button(actions_frame, "Set as New Baseline", set_baseline_from_stocktake, width=22, variant='secondary')
        baseline_btn.pack(side=tk.LEFT, padx=(0, 10))
        save_baseline_btn = self.styled_button(actions_frame, "Save & Set Baseline", save_and_set_baseline, width=22, variant='primary')
        save_baseline_btn.pack(side=tk.LEFT, padx=(0, 10))
        clean_btn = self.styled_button(actions_frame, "Roll Forward & Clean", roll_forward_and_clean_action, width=22, variant='danger')
        clean_btn.pack(side=tk.LEFT, padx=(0, 10))
        self.styled_button(actions_frame, "Back", back, width=12, variant='ghost').pack(side=tk.LEFT)
    
        self._apply_legacy_theme()


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
    
                # Expected stock on the count sheet is simply the current system stock.
                # The user physically counts against this; variance is Counted - Expected.
                txn_expected = row[COL_QUANTITY]
    
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
