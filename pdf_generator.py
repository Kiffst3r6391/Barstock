"""
PDF Report Generator for Bar Stock Management.

Contains the PDFReport and PriceHistoryPDF classes extracted from BarStockApp.py.
"""

import os
from datetime import datetime
from collections import defaultdict
from fpdf import FPDF
from conversions import convert_to_input, requires_conversion, get_input_label


def _pdf_safe(text, max_len=None):
    """Return a Latin-1 safe string for fpdf core fonts.

    Replaces common Unicode punctuation with ASCII equivalents and drops any
    remaining unsupported characters.
    """
    if text is None:
        text = ''
    if not isinstance(text, str):
        text = str(text)
    replacements = {
        '’': "'",   # right single quotation mark
        '‘': "'",   # left single quotation mark
        '“': '"',   # left double quotation mark
        '”': '"',   # right double quotation mark
        '–': '-',   # en dash
        '—': '-',   # em dash
        '…': '...', # ellipsis
        'é': 'e',   # é
        'è': 'e',   # è
        'ê': 'e',   # ê
        'à': 'a',   # à
        'â': 'a',   # â
        'ô': 'o',   # ô
        'ç': 'c',   # ç
        'ñ': 'n',   # ñ
        'ü': 'u',   # ü
        'ä': 'a',   # ä
        'ö': 'o',   # ö
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = text.encode('latin-1', 'ignore').decode('latin-1')
    if max_len is not None:
        text = text[:max_len]
    return text

# Items to include in the Draught Yield Report
DRAUGHT_YIELD_ITEMS = {
    'tennents_lager',
    'birra_moretti',
    'joker_ipa',
    'belhaven_best',
    'thatchers'
}


class PDFReport(FPDF):
    """PDF Report generator with formatted sections and totals."""

    def header(self):
        """Add header to each page."""
        self.set_font('Arial', 'B', 16)
        self.set_text_color(40, 40, 40)
        self.cell(0, 10, 'Prestonfield Golf Club - Bar Stock Report', 0, 1, 'C')
        self.set_font('Arial', '', 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, f'Generated: {datetime.now().strftime("%d %B %Y at %H:%M")}', 0, 1, 'C')
        self.ln(5)
        self.set_draw_color(200, 200, 200)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def footer(self):
        """Add footer to each page."""
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    def chapter_title(self, title):
        """Add a section title."""
        self.set_font('Arial', 'B', 12)
        self.set_text_color(0, 51, 102)
        self.cell(0, 10, title, 0, 1, 'L')
        self.ln(2)

    def section_table_header(self, headers, widths, font_size=7):
        """Draw table header with styling."""
        self.set_font('Arial', 'B', font_size)
        self.set_fill_color(240, 240, 240)
        self.set_text_color(0, 0, 0)
        for header, width in zip(headers, widths):
            self.cell(width, 6, header, 1, 0, 'C', True)
        self.ln()

    def section_table_row(self, values, widths, is_total=False, font_size=7):
        """Draw table row."""
        if is_total:
            self.set_font('Arial', 'B', font_size)
            self.set_fill_color(230, 230, 230)
        else:
            self.set_font('Arial', '', font_size)
            self.set_fill_color(255, 255, 255)

        self.set_text_color(0, 0, 0)
        for value, width in zip(values, widths):
            align = 'R' if isinstance(value, (int, float)) or (isinstance(value, str) and value.startswith('£')) else 'L'
            self.cell(width, 5, str(value), 1, 0, align, True)
        self.ln()

    def generate_report(self, report_data, member_discount_pct=10, stocktake_data=None):
        """Generate the full report."""
        self.add_page()

        # Filter out equipment/capital assets from report data
        report_data = [item for item in report_data if item.get('division') != 'Equipment']

        total_wastage_value = 0
        total_line_clean_value = 0

        # Group data by division
        by_division = defaultdict(list)
        draught_items = []

        for item in report_data:
            by_division[item['division']].append(item)
            if item['is_draught']:
                draught_items.append(item)

        # SECTION 1: Stock Summary by Division
        self.chapter_title('1. Stock Summary by Division')

        headers = ['Division', 'Itm', 'Stk Val', 'Sale Val', 'GP', 'GP%', 'M Rev', 'M GP%', 'M GP', 'NM Rev', 'NM GP%', 'NM GP']
        widths = [20, 8, 15, 16, 15, 9, 16, 9, 15, 16, 9, 15]

        self.section_table_header(headers, widths, font_size=6)

        division_totals = {}
        for division, items in by_division.items():
            total_stock = sum(i['current_stock'] for i in items)
            stock_value = sum(i['stock_value'] for i in items)
            sales_qty = sum(i['total_sales_qty'] for i in items)
            sales_value = sum(i['total_sales_value'] for i in items)
            sales_cost = sum(i['sales_cost'] for i in items)
            gp = sum(i['sales_gp'] for i in items)
            gp_pct = (gp / sales_value * 100) if sales_value > 0 else 0
            member_gp = sum(i['member_gp'] for i in items)
            member_sales_value = sum(i['member_sales_value'] for i in items)
            member_gp_pct = (member_gp / member_sales_value * 100) if member_sales_value > 0 else 0
            non_member_gp = sum(i.get('non_member_gp', 0) for i in items)
            non_member_sales_value = sum(i.get('non_member_sales_value', 0) for i in items)
            non_member_gp_pct = (non_member_gp / non_member_sales_value * 100) if non_member_sales_value > 0 else 0

            division_totals[division] = {
                'stock_value': stock_value,
                'sales_value': sales_value,
                'gp': gp,
                'sales_qty': sales_qty,
                'member_gp': member_gp,
                'member_sales_value': member_sales_value,
                'member_gp_pct': member_gp_pct,
                'non_member_gp': non_member_gp,
                'non_member_sales_value': non_member_sales_value,
                'non_member_gp_pct': non_member_gp_pct
            }

            values = [
                division[:14],
                len(items),
                f"£{stock_value:.2f}",
                f"£{sales_value:.2f}",
                f"£{gp:.2f}",
                f"{gp_pct:.1f}%",
                f"£{member_sales_value:.2f}",
                f"{member_gp_pct:.1f}%",
                f"£{member_gp:.2f}",
                f"£{non_member_sales_value:.2f}",
                f"{non_member_gp_pct:.1f}%",
                f"£{non_member_gp:.2f}"
            ]
            self.section_table_row(values, widths, font_size=6)

        total_stock_value = sum(d['stock_value'] for d in division_totals.values())
        total_sales_value = sum(d['sales_value'] for d in division_totals.values())
        total_gp = sum(d['gp'] for d in division_totals.values())
        total_cost_of_sales = total_sales_value - total_gp
        total_sales_qty = sum(d['sales_qty'] for d in division_totals.values())
        total_member_gp_div = sum(d['member_gp'] for d in division_totals.values())
        total_member_rev_div = sum(d['member_sales_value'] for d in division_totals.values())
        total_member_gp_pct_div = (total_member_gp_div / total_member_rev_div * 100) if total_member_rev_div > 0 else 0
        total_non_member_gp_div = sum(d['non_member_gp'] for d in division_totals.values())
        total_non_member_rev_div = sum(d['non_member_sales_value'] for d in division_totals.values())
        total_non_member_gp_pct_div = (total_non_member_gp_div / total_non_member_rev_div * 100) if total_non_member_rev_div > 0 else 0

        values = [
            'TOTAL',
            len(report_data),
            f"£{total_stock_value:.2f}",
            f"£{total_sales_value:.2f}",
            f"£{total_gp:.2f}",
            f"{(total_gp / total_sales_value * 100) if total_sales_value > 0 else 0:.1f}%",
            f"£{total_member_rev_div:.2f}",
            f"{total_member_gp_pct_div:.1f}%",
            f"£{total_member_gp_div:.2f}",
            f"£{total_non_member_rev_div:.2f}",
            f"{total_non_member_gp_pct_div:.1f}%",
            f"£{total_non_member_gp_div:.2f}"
        ]
        self.section_table_row(values, widths, is_total=True, font_size=6)
        self.ln(5)

        # SECTION 2: Wastage Summary
        self.chapter_title('2. Wastage Summary')

        wastage_items = [i for i in report_data if i['wastage_qty'] > 0]
        if wastage_items:
            headers = ['Item', 'Division', 'Wastage Qty', 'Cost Price', 'Wastage Value']
            widths = [60, 40, 25, 30, 30]

            self.section_table_header(headers, widths)
            total_wastage = 0
            total_wastage_value = 0

            for item in wastage_items:
                wastage_value = item['wastage_qty'] * item['cost_price']
                total_wastage += item['wastage_qty']
                total_wastage_value += wastage_value

                values = [
                    item['item_name'][:25],
                    item['division'][:18],
                    f"{item['wastage_qty']:.1f}",
                    f"£{item['cost_price']:.2f}",
                    f"£{wastage_value:.2f}"
                ]
                self.section_table_row(values, widths)

            values = ['TOTAL', '', f"{total_wastage:.1f}", '', f"£{total_wastage_value:.2f}"]
            self.section_table_row(values, widths, is_total=True)
        else:
            self.set_font('Arial', 'I', 10)
            self.cell(0, 10, 'No wastage recorded in this period.', 0, 1, 'L')
        self.ln(5)

        # SECTION 2b: Line Cleaning Summary
        line_clean_items = [i for i in report_data if i.get('line_clean_qty', 0) > 0]
        if line_clean_items:
            self.chapter_title('2b. Line Cleaning Summary')

            headers = ['Item', 'Division', 'Line Clean Qty', 'Cost Price', 'Line Clean Value']
            widths = [60, 40, 25, 30, 30]

            self.section_table_header(headers, widths)
            total_line_clean = 0
            total_line_clean_value = 0

            for item in line_clean_items:
                line_clean_value = item['line_clean_qty'] * item['cost_price']
                total_line_clean += item['line_clean_qty']
                total_line_clean_value += line_clean_value

                values = [
                    item['item_name'][:25],
                    item['division'][:18],
                    f"{item['line_clean_qty']:.1f}",
                    f"£{item['cost_price']:.2f}",
                    f"£{line_clean_value:.2f}"
                ]
                self.section_table_row(values, widths)

            values = ['TOTAL', '', f"{total_line_clean:.1f}", '', f"£{total_line_clean_value:.2f}"]
            self.section_table_row(values, widths, is_total=True)
            self.ln(5)

        # Combined Wastage & Line Clean note
        if total_wastage_value > 0 or total_line_clean_value > 0:
            combined_total = total_wastage_value + total_line_clean_value
            self.set_font('Arial', 'B', 11)
            self.set_text_color(0, 0, 0)
            self.cell(0, 8, f"Total Wastage Value (excluding line clean): £{total_wastage_value:.2f}", 0, 1, 'L')
            if total_line_clean_value > 0:
                self.cell(0, 8, f"Total Line Clean Value: £{total_line_clean_value:.2f}", 0, 1, 'L')
            self.cell(0, 8, f"Combined Wastage & Line Clean Value: £{combined_total:.2f}", 0, 1, 'L')
            self.ln(5)

        # SECTION 3: Complimentary Summary
        self.chapter_title('3. Complimentary Summary')

        comp_items = [i for i in report_data if i['complimentary_qty'] > 0]
        if comp_items:
            headers = ['Item', 'Division', 'Qty', 'Retail Value']
            widths = [70, 50, 30, 35]

            self.section_table_header(headers, widths)
            total_comp = 0
            total_comp_value = 0

            for item in comp_items:
                comp_value = item['complimentary_qty'] * item['sell_price']
                total_comp += item['complimentary_qty']
                total_comp_value += comp_value

                values = [
                    item['item_name'][:30],
                    item['division'][:22],
                    f"{item['complimentary_qty']:.1f}",
                    f"£{comp_value:.2f}"
                ]
                self.section_table_row(values, widths)

            values = ['TOTAL', '', f"{total_comp:.1f}", f"£{total_comp_value:.2f}"]
            self.section_table_row(values, widths, is_total=True)
        else:
            self.set_font('Arial', 'I', 10)
            self.cell(0, 10, 'No complimentary items recorded in this period.', 0, 1, 'L')
        self.ln(5)

        # SECTION 3b: Open Tabs / Pending Sales Summary
        self.chapter_title('3b. Open Tabs / Pending Sales Summary')

        open_tab_items = [i for i in report_data if i['open_tab_qty'] > 0]
        if open_tab_items:
            headers = ['Item', 'Division', 'Qty', 'Cost Price', 'Pending Value']
            widths = [60, 40, 25, 30, 30]

            self.section_table_header(headers, widths)
            total_open_tab = 0
            total_open_tab_value = 0

            for item in open_tab_items:
                open_tab_value = item['open_tab_qty'] * item['cost_price']
                total_open_tab += item['open_tab_qty']
                total_open_tab_value += open_tab_value

                values = [
                    item['item_name'][:25],
                    item['division'][:18],
                    f"{item['open_tab_qty']:.1f}",
                    f"£{item['cost_price']:.2f}",
                    f"£{open_tab_value:.2f}"
                ]
                self.section_table_row(values, widths)

            values = ['TOTAL', '', f"{total_open_tab:.1f}", '', f"£{total_open_tab_value:.2f}"]
            self.section_table_row(values, widths, is_total=True)
        else:
            self.set_font('Arial', 'I', 10)
            self.cell(0, 10, 'No open tabs recorded in this period.', 0, 1, 'L')
        self.ln(5)

        # SECTION 3c: Parent Stock Adjustment Summary
        parent_adj_items = [i for i in report_data if i['parent_adj_qty'] > 0 and not i.get('is_hidden', False)]
        if parent_adj_items:
            self.chapter_title('3c. Parent Stock Adjustments')

            headers = ['Parent Item', 'Division', 'Qty Adjusted', 'Cost Price', 'Adj. Value']
            widths = [50, 40, 25, 30, 30]

            self.section_table_header(headers, widths)
            total_adj_qty = 0
            total_adj_value = 0

            for item in parent_adj_items:
                adj_value = item['parent_adj_qty'] * item['cost_price']
                total_adj_qty += item['parent_adj_qty']
                total_adj_value += adj_value

                values = [
                    item['item_name'][:25],
                    item['division'][:18],
                    f"{item['parent_adj_qty']:.1f}",
                    f"£{item['cost_price']:.2f}",
                    f"£{adj_value:.2f}"
                ]
                self.section_table_row(values, widths)

            values = ['TOTAL', '', f"{total_adj_qty:.1f}", '', f"£{total_adj_value:.2f}"]
            self.section_table_row(values, widths, is_total=True)
            self.ln(5)

        # SECTION 4: Draught Yield Report
        draught_items = [i for i in draught_items if i['item_id'] in DRAUGHT_YIELD_ITEMS]
        if draught_items:
            self.chapter_title('4. Draught Yield Report (pints)')

            headers = ['Item', 'Sales', 'Adj.', 'Wast', 'Comp', 'Open Tabs', 'Consumed', 'Closing', 'Yield%']
            widths = [38, 16, 14, 14, 14, 16, 18, 18, 16]

            self.section_table_header(headers, widths)

            for item in draught_items:
                yield_pct = item['yield_pct']
                yield_str = f"{yield_pct:.1f}%" if yield_pct > 0 else "N/A"
                adj_display = f"{item['parent_adj_qty']:.1f}" if item.get('parent_adj_qty', 0) > 0 else '-'

                values = [
                    item['item_name'][:18],
                    f"{item['total_sales_qty']:.1f}",
                    adj_display,
                    f"{item['wastage_qty']:.1f}" if item['wastage_qty'] > 0 else '-',
                    f"{item['complimentary_qty']:.1f}" if item['complimentary_qty'] > 0 else '-',
                    f"{item['open_tab_qty']:.1f}" if item['open_tab_qty'] > 0 else '-',
                    f"{item['expected_consumption']:.1f}",
                    f"{item['current_stock']:.1f}",
                    yield_str
                ]
                self.section_table_row(values, widths)
            self.ln(2)
            self.set_font('Arial', 'I', 8)
            self.cell(0, 5, 'All quantities in pints. Yield% = Sales / Total Consumption. Adj = pints deducted via half pints/shandies.', 0, 1, 'L')

        # SECTION 5: Financial Summary
        self.add_page()
        self.chapter_title('5. Financial Summary')

        self.set_font('Arial', '', 11)
        self.set_text_color(0, 0, 0)

        total_member_gp = sum(i['member_gp'] for i in report_data)
        total_member_revenue = sum(i['member_sales_value'] for i in report_data)
        overall_member_gp_pct = (total_member_gp / total_member_revenue * 100) if total_member_revenue > 0 else 0

        total_non_member_gp = sum(i.get('non_member_gp', 0) for i in report_data)
        total_non_member_revenue = sum(i.get('non_member_sales_value', 0) for i in report_data)
        overall_non_member_gp_pct = (total_non_member_gp / total_non_member_revenue * 100) if total_non_member_revenue > 0 else 0

        # Stock Surplus/Shortfall — only meaningful when a stocktake exists
        items_with_stocktake = [i for i in report_data if i.get('surplus_value') is not None]
        total_surplus_value = sum(i['surplus_value'] for i in items_with_stocktake) if items_with_stocktake else None
        has_stocktake = total_surplus_value is not None

        self.set_fill_color(245, 245, 245)
        self.rect(10, self.get_y(), 190, 150 if has_stocktake else 140, 'F')

        y_start = self.get_y() + 5
        self.set_xy(15, y_start)

        summary_data = [
            ('Total Stock Value', f"£{total_stock_value:.2f}"),
            ('Total Sales Revenue', f"£{total_sales_value:.2f}"),
            ('Total Cost of Sales', f"£{total_cost_of_sales:.2f}"),
            ('Total Gross Profit', f"£{total_gp:.2f}"),
            ('Overall GP Margin', f"{(total_gp / total_sales_value * 100) if total_sales_value > 0 else 0:.1f}%"),
            (f'Member Revenue ({member_discount_pct}% disc.)', f"£{total_member_revenue:.2f}"),
            ('Non-Member Revenue', f"£{total_non_member_revenue:.2f}"),
            ('Member Gross Profit', f"£{total_member_gp:.2f}"),
            ('Non-Member Gross Profit', f"£{total_non_member_gp:.2f}"),
            ('Member GP Margin', f"{overall_member_gp_pct:.1f}%"),
            ('Non-Member GP Margin', f"{overall_non_member_gp_pct:.1f}%"),
            ('Total Wastage Value (inc. line clean)', f"£{total_wastage_value + total_line_clean_value:.2f}"),
            ('Total Complimentary Value', f"£{total_comp_value:.2f}" if 'total_comp_value' in dir() else "£0.00"),
        ]
        if has_stocktake:
            summary_data.append(('Stock Surplus/Shortfall', f"£{total_surplus_value:+.2f}"))

        for label, value in summary_data:
            self.set_xy(15, self.get_y())
            self.set_font('Arial', 'B', 11)
            self.cell(80, 10, label + ':', 0, 0, 'L')
            self.set_font('Arial', '', 11)
            self.cell(50, 10, value, 0, 1, 'R')

        self.ln(10)

        # Add per-item financial breakdown with member GP
        self.chapter_title('5b. Item Financial Breakdown (incl. Member GP)')

        sales_items = [i for i in report_data if i['total_sales_qty'] > 0]
        if sales_items:
            headers = ['Item', 'Revenue', 'Cost', 'GP', 'GP%', 'Mem Qty', 'Non-Mem', 'Mem GP', 'Mem GP%']
            widths = [40, 20, 20, 20, 14, 18, 18, 20, 14]

            self.section_table_header(headers, widths)

            for item in sales_items:
                values = [
                    item['item_name'][:22],
                    f"£{item['total_sales_value']:.2f}",
                    f"£{item['sales_cost']:.2f}",
                    f"£{item['sales_gp']:.2f}",
                    f"{item['sales_gp_pct']:.1f}%",
                    f"{item.get('member_qty', 0):.1f}" if item.get('member_qty', 0) > 0 else '-',
                    f"{item.get('non_member_qty', 0):.1f}" if item.get('non_member_qty', 0) > 0 else '-',
                    f"£{item['member_gp']:.2f}",
                    f"{item['member_gp_pct']:.1f}%"
                ]
                self.section_table_row(values, widths)

            values = [
                'TOTAL',
                f"£{total_sales_value:.2f}",
                f"£{sum(i['sales_cost'] for i in sales_items):.2f}",
                f"£{sum(i['sales_gp'] for i in sales_items):.2f}",
                '',
                f"{sum(i.get('member_qty', 0) for i in sales_items):.1f}",
                f"{sum(i.get('non_member_qty', 0) for i in sales_items):.1f}",
                f"£{total_member_gp:.2f}",
                f"{overall_member_gp_pct:.1f}%"
            ]
            self.section_table_row(values, widths, is_total=True)
        else:
            self.set_font('Arial', 'I', 10)
            self.cell(0, 10, 'No sales recorded in this period.', 0, 1, 'L')
        self.ln(5)

        # Add stock movement & variance summary
        self.chapter_title('6. Stock Movement & Variance')

        variance_items = [i for i in report_data if i['expected_consumption'] > 0 and not i.get('is_hidden', False)]
        if variance_items:
            headers = ['Item', 'Opening', '+Del.', '-Sold', '-Adj', '-Wast', '-Comp', 'Closing', 'Exp.Con', 'Act.Con', 'Var%']
            widths = [34, 16, 14, 14, 14, 14, 14, 16, 16, 16, 14]

            self.section_table_header(headers, widths)

            totals = {'opening': 0, 'delivery': 0, 'sold': 0, 'adj': 0, 'wast': 0, 'comp': 0, 'closing': 0, 'exp_con': 0, 'act_con': 0}

            for item in variance_items:
                totals['opening'] += item['opening_stock']
                totals['delivery'] += item['delivery_qty']
                totals['sold'] += item['total_sales_qty']
                totals['adj'] += item['parent_adj_qty']
                totals['wast'] += item['wastage_qty']
                totals['comp'] += item['complimentary_qty']
                totals['closing'] += item['current_stock']
                totals['exp_con'] += item['expected_consumption']
                if item['actual_consumption'] is not None:
                    totals['act_con'] += item['actual_consumption']

                adj_display = f"{item['parent_adj_qty']:.1f}" if item['parent_adj_qty'] > 0 else '-'
                if item['consumption_variance_pct'] is not None:
                    var_pct_str = f"{item['consumption_variance_pct']:+.1f}%" if abs(item['consumption_variance_pct']) >= 0.1 else '-'
                else:
                    var_pct_str = '-'
                values = [
                    item['item_name'][:20],
                    f"{item['opening_stock']:.1f}",
                    f"{item['delivery_qty']:.1f}" if item['delivery_qty'] > 0 else '-',
                    f"{item['total_sales_qty']:.1f}" if item['total_sales_qty'] > 0 else '-',
                    adj_display,
                    f"{item['wastage_qty']:.1f}" if item['wastage_qty'] > 0 else '-',
                    f"{item['complimentary_qty']:.1f}" if item['complimentary_qty'] > 0 else '-',
                    f"{item['current_stock']:.1f}",
                    f"{item['expected_consumption']:.1f}",
                    f"{item['actual_consumption']:.1f}" if item['actual_consumption'] is not None else '-',
                    var_pct_str
                ]
                self.section_table_row(values, widths)

            tot_adj_display = f"{totals['adj']:.1f}" if totals['adj'] > 0 else '-'
            total_var_pct = ((totals['exp_con'] - totals['act_con']) / totals['act_con'] * 100) if totals['act_con'] > 0 else 0
            values = [
                'TOTAL',
                f"{totals['opening']:.1f}",
                f"{totals['delivery']:.1f}" if totals['delivery'] > 0 else '-',
                f"{totals['sold']:.1f}" if totals['sold'] > 0 else '-',
                tot_adj_display,
                f"{totals['wast']:.1f}" if totals['wast'] > 0 else '-',
                f"{totals['comp']:.1f}" if totals['comp'] > 0 else '-',
                f"{totals['closing']:.1f}",
                f"{totals['exp_con']:.1f}",
                f"{totals['act_con']:.1f}",
                f"{total_var_pct:+.1f}%" if abs(total_var_pct) >= 0.1 else '-'
            ]
            self.section_table_row(values, widths, is_total=True)

            self.ln(3)
            self.set_font('Arial', 'I', 8)
            self.cell(0, 5, 'Units: draught/postmix = pints, spirits = measures (35ml), bottles/cans = units. Adj = parent stock deductions from child sales.', 0, 1, 'L')
            self.cell(0, 5, 'Exp.Con = Expected consumption (Sales+Wastage+Comp+Adj). Act.Con = Actual consumption (Opening+Deliveries-Closing). Var% = difference.', 0, 1, 'L')
        else:
            self.set_font('Arial', 'I', 10)
            self.cell(0, 10, 'No stock consumption data available for variance calculation.', 0, 1, 'L')

        # SECTION 7: Stocktake Variance Report
        if stocktake_data:
            st_items = [i for i in stocktake_data if i.get('has_stocktake', False)]
            if st_items:
                self.add_page()
                self.chapter_title('7. Stocktake Variance Report')

                headers = ['Item', 'Expected', 'Counted', 'Variance', 'Var %', 'Value']
                widths = [60, 22, 22, 22, 18, 22]

                self.section_table_header(headers, widths)

                total_var_value = 0
                total_expected = 0
                total_counted = 0

                for item in st_items:
                    expected = item['expected_quantity']
                    counted = item['counted_quantity']
                    variance = item['variance']
                    var_pct = item['variance_pct']
                    var_val = item['variance_value']

                    total_expected += expected if expected is not None else 0
                    total_counted += counted if counted is not None else 0
                    total_var_value += var_val if var_val is not None else 0

                    var_str = f"{variance:+.1f}"
                    var_pct_str = f"{var_pct:+.1f}%"
                    var_val_str = f"£{var_val:+.2f}"

                    # Highlight high variance
                    if abs(var_pct) > 5:
                        self.set_fill_color(248, 215, 218)
                    elif abs(var_pct) > 2:
                        self.set_fill_color(255, 243, 205)
                    else:
                        self.set_fill_color(255, 255, 255)

                    values = [
                        item['item_name'][:28],
                        f"{expected:.1f}",
                        f"{counted:.1f}",
                        var_str,
                        var_pct_str,
                        var_val_str
                    ]
                    self.section_table_row(values, widths)

                # Total row
                total_var = total_counted - total_expected
                total_var_pct = (total_var / total_expected * 100) if total_expected > 0 else 0
                values = [
                    'TOTAL',
                    f"{total_expected:.1f}",
                    f"{total_counted:.1f}",
                    f"{total_var:+.1f}",
                    f"{total_var_pct:+.1f}%",
                    f"£{total_var_value:+.2f}"
                ]
                self.section_table_row(values, widths, is_total=True)

                self.ln(3)
                self.set_font('Arial', 'I', 8)
                self.cell(0, 5, 'Expected = system quantity at time of stocktake. Counted = physical count entered. Variance = Counted - Expected.', 0, 1, 'L')
                self.cell(0, 5, 'Red highlight = variance > 5%. Yellow highlight = variance > 2%. Value = variance × cost price.', 0, 1, 'L')
            else:
                self.ln(10)
                self.set_font('Arial', 'I', 10)
                self.cell(0, 10, 'No stocktake snapshots recorded. Use "Record Stocktake" to enter physical counts.', 0, 1, 'L')

    def generate_stock_count_sheet(self, inventory_data):
        """Generate a printable stock count sheet."""
        self.add_page()
        self.chapter_title('Stock Count Sheet')

        self.set_font('Arial', '', 10)
        self.cell(0, 8, f'Total items: {len(inventory_data)}', 0, 1, 'L')
        self.ln(2)

        headers = ['Item', 'Category', 'Expected', 'Counted', 'Variance', 'Notes']
        widths = [50, 28, 22, 22, 22, 46]

        self.set_font('Arial', 'B', 9)
        self.set_fill_color(220, 220, 220)
        self.set_text_color(0, 0, 0)
        for header, width in zip(headers, widths):
            self.cell(width, 8, header, 1, 0, 'C', True)
        self.ln()

        # Sort by category then item name
        inventory_data = sorted(inventory_data, key=lambda x: (x.get('category', ''), x.get('item_name', '')))
        current_category = None

        for item in inventory_data:
            category = item.get('category', '')
            if category != current_category:
                current_category = category
                self.set_font('Arial', 'B', 9)
                self.set_fill_color(240, 240, 240)
                self.cell(sum(widths), 8, current_category, 1, 1, 'L', True)

            self.set_font('Arial', '', 9)
            self.set_fill_color(255, 255, 255)
            self.set_text_color(0, 0, 0)
            self.cell(widths[0], 8, item.get('item_name', '')[:35], 1, 0, 'L', True)
            self.cell(widths[1], 8, item.get('category', '')[:20], 1, 0, 'L', True)

            # Convert to natural units (barrels, bottles, boxes, cartons) where applicable
            item_id = item.get('item_id', '')
            txn_expected = item.get('txn_expected', 0)
            if requires_conversion(item_id):
                expected_val = convert_to_input(item_id, txn_expected)
                unit = get_input_label(item_id) or ''
                expected_text = f"{expected_val:.1f} {unit}"
            else:
                expected_text = f"{txn_expected:.1f}"

            self.cell(widths[2], 8, expected_text, 1, 0, 'C', True)
            self.cell(widths[3], 8, '', 1, 0, 'C', True)
            self.cell(widths[4], 8, '', 1, 0, 'C', True)
            self.cell(widths[5], 8, '', 1, 1, 'L', True)

        self.ln(5)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 5, 'Expected = transaction-based expected stock. Counted = write your physical count. Variance = Counted - Expected.', 0, 1, 'L')

class PriceHistoryPDF(FPDF):
    """PDF generator for price history reports."""

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

    @staticmethod
    def generate(report_data, downloads_dir=None):
        """Generate and save a price history PDF report.

        Args:
            report_data: List of dicts with keys:
                item_name, timestamp, supplier, cost_price, prev_price, change
            downloads_dir: Directory to save the PDF. Defaults to ~/Downloads.
        """
        if downloads_dir is None:
            downloads_dir = os.path.expanduser('~/Downloads')

        pdf = PriceHistoryPDF()
        pdf.add_page()
        pdf.set_font('Arial', '', 9)

        pdf.set_fill_color(240, 240, 240)
        pdf.set_font('Arial', 'B', 9)
        headers = ['Item', 'Date', 'Supplier', 'Cost Price', 'Previous', 'Change']
        widths = [50, 30, 30, 25, 25, 25]
        for h, w in zip(headers, widths):
            pdf.cell(w, 8, h, 1, 0, 'C', True)
        pdf.ln()

        pdf.set_font('Arial', '', 9)
        for row in report_data:
            change_str = f"{'+' if row['change'] >= 0 else ''}{row['change']:.2f}"
            values = [
                str(row.get('item_name', ''))[:30],
                str(row.get('timestamp', ''))[:16],
                str(row.get('supplier', ''))[:15],
                f"£{row.get('cost_price', 0):.2f}",
                f"£{row.get('prev_price', 0):.2f}",
                change_str
            ]
            for v, w in zip(values, widths):
                pdf.cell(w, 7, v, 1, 0, 'C')
            pdf.ln()

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Price_History_Report_{timestamp}.pdf"
        filepath = os.path.join(downloads_dir, filename)
        pdf.output(filepath)
        return filepath


class StockOrderSheetPDF(FPDF):
    """PDF generator for the stock order sheet."""

    def header(self):
        """Add header to each page."""
        self.set_font('Arial', 'B', 16)
        self.set_text_color(40, 40, 40)
        self.cell(0, 10, 'Prestonfield Golf Club - Stock Order Sheet', 0, 1, 'C')
        self.set_font('Arial', '', 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, f'Generated: {datetime.now().strftime("%d %B %Y at %H:%M")}', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        """Add footer to each page."""
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    @staticmethod
    def generate(report_data, downloads_dir=None):
        """Generate and save a stock order sheet PDF.

        Args:
            report_data: List of dicts from reports.build_custom_stock_order_sheet_data().
                Expected keys: item_id, item_name, category, supplier, quantity,
                measure, reorder_level, suggested_order, is_placeholder.
            downloads_dir: Directory to save the PDF. Defaults to ~/Downloads.

        Returns:
            The full path to the saved PDF file.
        """
        if downloads_dir is None:
            downloads_dir = os.path.expanduser('~/Downloads')

        pdf = StockOrderSheetPDF()
        pdf.add_page()
        pdf.set_font('Arial', '', 9)

        if not report_data:
            pdf.set_font('Arial', 'I', 12)
            pdf.cell(0, 10, 'No items available for order sheet.', 0, 1, 'C')
        else:
            # Preserve the supplier/category order supplied by the custom builder
            grouped = []
            current_supplier = None
            current_category = None
            current_items = []
            for row in report_data:
                supplier = row.get('supplier', 'Unknown')
                category = row.get('category', '')
                if supplier != current_supplier or category != current_category:
                    if current_items:
                        grouped.append((current_supplier, current_category, current_items))
                    current_supplier = supplier
                    current_category = category
                    current_items = []
                current_items.append(row)
            if current_items:
                grouped.append((current_supplier, current_category, current_items))

            headers = ['Item', 'Current', 'Reorder']
            widths = [95, 35, 35]

            last_supplier = None
            for supplier, category, items in grouped:
                # Supplier heading
                if supplier != last_supplier:
                    if last_supplier is not None:
                        pdf.ln(4)
                    pdf.set_font('Arial', 'B', 13)
                    pdf.set_text_color(0, 51, 102)
                    pdf.cell(0, 10, _pdf_safe(supplier), 0, 1, 'L')
                    pdf.ln(1)
                    last_supplier = supplier

                # Category subheading (skip if category is blank)
                if category:
                    pdf.set_font('Arial', 'B', 10)
                    pdf.set_text_color(60, 60, 60)
                    pdf.set_fill_color(230, 230, 230)
                    pdf.cell(sum(widths), 7, _pdf_safe(category), 1, 1, 'L', True)

                # Table header
                pdf.set_font('Arial', 'B', 8)
                pdf.set_fill_color(240, 240, 240)
                pdf.set_text_color(0, 0, 0)
                for header, width in zip(headers, widths):
                    pdf.cell(width, 6, _pdf_safe(header), 1, 0, 'C', True)
                pdf.ln()

                # Rows
                pdf.set_font('Arial', '', 8)
                pdf.set_fill_color(255, 255, 255)
                for item in items:
                    reorder_level = item.get('reorder_level', 0)

                    # Current column is intentionally left blank for manual counts
                    current_str = ''
                    reorder_str = f"{reorder_level:.1f}" if reorder_level else '-'

                    values = [
                        _pdf_safe(item.get('item_name', ''), max_len=46),
                        _pdf_safe(current_str),
                        _pdf_safe(reorder_str),
                    ]
                    for value, width in zip(values, widths):
                        align = 'R' if value.replace('.', '', 1).replace('-', '', 1).isdigit() else 'L'
                        pdf.cell(width, 6, value, 1, 0, align, True)
                    pdf.ln()

                pdf.ln(2)

            pdf.set_font('Arial', 'I', 8)
            pdf.set_text_color(100, 100, 100)
            pdf.cell(0, 5, 'Order sheet. Current = blank for manual stock count. Reorder = recorded reorder level.', 0, 1, 'L')

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Stock_Order_Sheet_{timestamp}.pdf"
        filepath = os.path.join(downloads_dir, filename)
        pdf.output(filepath)
        return filepath
