"""
PDF Report Generator for Bar Stock Management.

Contains the PDFReport and PriceHistoryPDF classes extracted from BarStockApp.py.
"""

import os
from datetime import datetime
from collections import defaultdict
from fpdf import FPDF
from conversions import convert_to_input, requires_conversion, get_input_label, DATE_FORMAT_DISPLAY
from categories import is_delisted

# Standard UK VAT rate used to show inc-VAT equivalents on the executive summary.
VAT_RATE = 0.20
VAT_MULTIPLIER = 1.0 + VAT_RATE


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
    'thatchers',
    'poretti',
    'innis_and_gunn',
    'orchard_pig',
    'guinness',
    'caledonian_best',
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
        self.cell(0, 5, f'Generated: {datetime.now().strftime(f"{DATE_FORMAT_DISPLAY} at %H:%M")}', 0, 1, 'C')
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

    def _available_page_space(self):
        """Return remaining vertical space on the current page."""
        footer_margin = 20
        return self.h - self.get_y() - footer_margin

    def _table_height(self, headers, rows, total_rows=1, row_height=5, header_height=6, font_size=7):
        """Estimate total table height including header, rows and total row(s)."""
        return header_height + len(rows) * row_height + total_rows * row_height

    def render_table_block(self, title, headers, widths, rows, total_values=None,
                           font_size=7, header_height=6, row_height=5, repeat_header=True,
                           notes=None, notes_font_size=8, row_fill_colors=None):
        """Render a table on a single page where possible.

        If the entire table (title + header + rows + total) does not fit on the
        current page, a new page is started first. For long tables that exceed a
        single page, page breaks are handled cleanly and the header is repeated.

        Args:
            row_fill_colors: Optional list of RGB tuples, one per row. If provided
                the corresponding row is drawn with that fill colour instead of white.
        """
        total_rows_count = 1 if total_values is not None else 0
        notes_height = 0
        if notes:
            notes_height = len(notes) * notes_font_size * 0.45 + 4
        # Add a safety buffer so tables that barely fit don't start and then
        # spill over the footer mid-way.
        estimated_height = (header_height + len(rows) * row_height +
                            total_rows_count * row_height + notes_height + 15)

        def _draw_row(values, is_total=False, fill_color=None):
            if is_total:
                self.set_font('Arial', 'B', font_size)
                self.set_fill_color(230, 230, 230)
            else:
                self.set_font('Arial', '', font_size)
                if fill_color:
                    self.set_fill_color(*fill_color)
                else:
                    self.set_fill_color(255, 255, 255)
            self.set_text_color(0, 0, 0)
            for value, width in zip(values, widths):
                align = 'R' if isinstance(value, (int, float)) or (isinstance(value, str) and value.startswith('£')) else 'L'
                self.cell(width, row_height, str(value), 1, 0, align, True)
            self.ln()

        # Keep small tables together on one page
        if estimated_height <= self._available_page_space() or estimated_height <= 120:
            if estimated_height > self._available_page_space():
                self.add_page()
            if title:
                self.chapter_title(title)
            self.section_table_header(headers, widths, font_size=font_size)
            for idx, row_values in enumerate(rows):
                _draw_row(row_values, fill_color=row_fill_colors[idx] if row_fill_colors else None)
            if total_values is not None:
                _draw_row(total_values, is_total=True)
            if notes:
                self.ln(2)
                self.set_font('Arial', 'I', notes_font_size)
                self.set_text_color(0, 0, 0)
                for note in notes:
                    self.cell(0, notes_font_size * 0.5, note, 0, 1, 'L')
            return

        # Long table: start on a fresh page, repeat header after each break
        self.add_page()
        if title:
            self.chapter_title(title)
        self.section_table_header(headers, widths, font_size=font_size)

        for idx, row_values in enumerate(rows):
            if self._available_page_space() < row_height + 10:
                self.add_page()
                if repeat_header:
                    self.section_table_header(headers, widths, font_size=font_size)
            _draw_row(row_values, fill_color=row_fill_colors[idx] if row_fill_colors else None)

        if total_values is not None:
            if self._available_page_space() < row_height + 10:
                self.add_page()
                if repeat_header:
                    self.section_table_header(headers, widths, font_size=font_size)
            _draw_row(total_values, is_total=True)

        if notes:
            self.ln(2)
            self.set_font('Arial', 'I', notes_font_size)
            self.set_text_color(0, 0, 0)
            for note in notes:
                self.cell(0, notes_font_size * 0.5, note, 0, 1, 'L')

    def generate_executive_summary(self, report_data, division_totals, by_division,
                                   total_stock_value, total_sales_value, total_gp,
                                   total_cost_of_sales, total_net_profit,
                                   total_member_revenue, total_non_member_revenue,
                                   total_member_gp, total_non_member_gp,
                                   overall_member_gp_pct, overall_non_member_gp_pct,
                                   total_wastage_value, total_line_clean_value,
                                   total_supplier_return_value, total_comp_value,
                                   total_surplus_value, running_surplus_value,
                                   has_member_data, has_stocktake, member_discount_pct=10):
        """Generate a compact one-page executive summary for directors.

        All stored figures are ex-VAT. Inc-VAT equivalents are shown at the
        standard UK rate (20%) so directors can compare against EPOS/till totals.
        """
        # Inc-VAT equivalents for the headline numbers.
        total_sales_inc_vat = total_sales_value * VAT_MULTIPLIER
        total_gp_inc_vat = total_gp * VAT_MULTIPLIER
        total_net_profit_inc_vat = total_net_profit * VAT_MULTIPLIER
        vat_on_sales = total_sales_value * VAT_RATE
        overall_gp_pct = (total_gp / total_sales_value * 100) if total_sales_value > 0 else 0

        self.add_page()
        self.set_font('Arial', 'B', 15)
        self.set_text_color(0, 51, 102)
        self.cell(0, 10, 'Executive Summary', 0, 1, 'C')
        self.ln(2)

        # Key KPI boxes (2 rows of 3)
        kpis = [
            ('Total Stock Value (ex-VAT)', f"£{total_stock_value:.2f}"),
            ('Total Sales (ex-VAT)', f"£{total_sales_value:.2f}"),
            ('Total GP (ex-VAT)', f"£{total_gp:.2f}"),
            ('Overall GP Margin', f"{overall_gp_pct:.1f}%"),
            ('Total Sales (inc-VAT)', f"£{total_sales_inc_vat:.2f}"),
            ('Total GP (inc-VAT)', f"£{total_gp_inc_vat:.2f}"),
        ]

        box_width = 61
        box_height = 18
        box_spacing = 2
        start_x = 10
        y = self.get_y()
        for idx, (label, value) in enumerate(kpis):
            col = idx % 3
            row = idx // 3
            x = start_x + col * (box_width + box_spacing)
            box_y = y + row * (box_height + box_spacing)
            self.set_xy(x, box_y)
            self.set_fill_color(245, 245, 245)
            self.set_draw_color(200, 200, 200)
            self.rect(x, box_y, box_width, box_height, 'FD')
            self.set_xy(x, box_y + 2)
            self.set_font('Arial', 'B', 7)
            self.set_text_color(80, 80, 80)
            self.cell(box_width, 5, label, 0, 2, 'C')
            self.set_font('Arial', 'B', 12)
            self.set_text_color(0, 51, 102)
            self.cell(box_width, 9, value, 0, 2, 'C')

        self.ln((box_height + box_spacing) * 2 + 4)

        # Division performance (compact, with inc-VAT columns)
        self.set_font('Arial', 'B', 10)
        self.set_text_color(0, 51, 102)
        self.cell(0, 6, 'Division Performance', 0, 1, 'L')

        div_headers = ['Division', 'Items', 'Stock Value', 'Sales ex-VAT', 'Sales inc-VAT', 'GP ex-VAT', 'GP inc-VAT', 'GP%']
        div_widths = [38, 10, 22, 24, 24, 22, 22, 16]
        div_rows = []
        for division, totals in division_totals.items():
            gp_pct = (totals['gp'] / totals['sales_value'] * 100) if totals['sales_value'] > 0 else 0
            div_rows.append([
                division[:22],
                len(by_division[division]),
                f"£{totals['stock_value']:.2f}",
                f"£{totals['sales_value']:.2f}",
                f"£{totals['sales_value'] * VAT_MULTIPLIER:.2f}",
                f"£{totals['gp']:.2f}",
                f"£{totals['gp'] * VAT_MULTIPLIER:.2f}",
                f"{gp_pct:.1f}%",
            ])
        div_total = [
            'TOTAL',
            len(report_data),
            f"£{total_stock_value:.2f}",
            f"£{total_sales_value:.2f}",
            f"£{total_sales_inc_vat:.2f}",
            f"£{total_gp:.2f}",
            f"£{total_gp_inc_vat:.2f}",
            f"{overall_gp_pct:.1f}%",
        ]
        self.render_table_block(None, div_headers, div_widths, div_rows,
                                total_values=div_total, font_size=7, row_height=4)
        self.ln(2)

        # Key Metrics (compact, inline)
        self.set_font('Arial', 'B', 10)
        self.set_text_color(0, 51, 102)
        self.cell(0, 6, 'Key Metrics', 0, 1, 'L')

        metric_rows = [
            ['Cost of Sales (ex-VAT)', f"£{total_cost_of_sales:.2f}"],
            ['Net Profit (ex-VAT)', f"£{total_net_profit:.2f}"],
            ['Net Profit (inc-VAT)', f"£{total_net_profit_inc_vat:.2f}"],
            ['VAT @ 20% on Sales', f"£{vat_on_sales:.2f}"],
            ['Wastage & Line Clean (ex-VAT)', f"£{total_wastage_value + total_line_clean_value:.2f}"],
            ['Supplier Returns (ex-VAT)', f"£{total_supplier_return_value:.2f}"],
            ['Complimentary (retail, ex-VAT)', f"£{total_comp_value:.2f}"],
        ]
        if has_member_data:
            metric_rows.extend([
                [f'Member Revenue ({member_discount_pct}% disc., ex-VAT)', f"£{total_member_revenue:.2f}"],
                ['Non-Member Revenue (ex-VAT)', f"£{total_non_member_revenue:.2f}"],
            ])
        if has_stocktake and total_surplus_value is not None:
            metric_rows.append(['Stocktake Surplus/Shortfall', f"£{total_surplus_value:+.2f}"])
        if running_surplus_value is not None:
            metric_rows.append(['Running Surplus/Shortfall', f"£{running_surplus_value:+.2f}"])

        metric_headers = ['Metric', 'Value']
        metric_widths = [90, 35]
        self.render_table_block(None, metric_headers, metric_widths, metric_rows,
                                font_size=7, row_height=4)
        self.ln(2)

        # Top 5 sales items
        self.set_font('Arial', 'B', 10)
        self.set_text_color(0, 51, 102)
        self.cell(0, 6, 'Top 5 Sales Items', 0, 1, 'L')

        top_sales = sorted(
            [i for i in report_data if i['total_sales_value'] > 0],
            key=lambda x: x['total_sales_value'],
            reverse=True
        )[:5]
        top_headers = ['Item', 'Sales ex-VAT', 'Sales inc-VAT', 'Qty', 'GP%']
        top_widths = [68, 26, 26, 22, 22]
        top_rows = []
        for item in top_sales:
            top_rows.append([
                item['item_name'][:28],
                f"£{item['total_sales_value']:.2f}",
                f"£{item['total_sales_value'] * VAT_MULTIPLIER:.2f}",
                f"{item['total_sales_qty']:.1f}",
                f"{item['sales_gp_pct']:.1f}%",
            ])
        self.render_table_block(None, top_headers, top_widths, top_rows,
                                font_size=7, row_height=4)

    def generate_report(self, report_data, member_discount_pct=10, stocktake_data=None, running_surplus_value=None):
        """Generate the full report.

        Args:
            report_data: list of item dicts from build_comprehensive_report_data.
            member_discount_pct: member discount percentage.
            stocktake_data: Stocktake Variance Report data for the selected period.
            running_surplus_value: Cumulative surplus/shortfall value from all
                historical stocktakes, surviving baseline resets.
        """
        # Filter out equipment/capital assets from report data
        report_data = [item for item in report_data if item.get('division') != 'Equipment']

        # Determine whether any member split data exists
        has_member_data = any(i.get('member_sales_value', 0) > 0 for i in report_data)

        # Group data by division and classify draught items
        by_division = defaultdict(list)
        draught_items = []
        for item in report_data:
            by_division[item['division']].append(item)
            if item['is_draught']:
                draught_items.append(item)

        # Pre-compute division totals
        division_totals = {}
        for division, items in by_division.items():
            division_totals[division] = {
                'stock_value': sum(i['stock_value'] for i in items),
                'sales_value': sum(i['total_sales_value'] for i in items),
                'gp': sum(i['sales_gp'] for i in items),
                'sales_qty': sum(i['total_sales_qty'] for i in items),
                'member_gp': sum(i['member_gp'] for i in items),
                'member_sales_value': sum(i['member_sales_value'] for i in items),
                'member_gp_pct': (sum(i['member_gp'] for i in items) / sum(i['member_sales_value'] for i in items) * 100)
                    if sum(i['member_sales_value'] for i in items) > 0 else 0,
                'non_member_gp': sum(i.get('non_member_gp', 0) for i in items),
                'non_member_sales_value': sum(i.get('non_member_sales_value', 0) for i in items),
                'non_member_gp_pct': (sum(i.get('non_member_gp', 0) for i in items) /
                    sum(i.get('non_member_sales_value', 0) for i in items) * 100)
                    if sum(i.get('non_member_sales_value', 0) for i in items) > 0 else 0,
            }

        # Grand totals
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

        # Member/non-member overall totals
        total_member_gp = sum(i['member_gp'] for i in report_data)
        total_member_revenue = sum(i['member_sales_value'] for i in report_data)
        overall_member_gp_pct = (total_member_gp / total_member_revenue * 100) if total_member_revenue > 0 else 0
        total_non_member_gp = sum(i.get('non_member_gp', 0) for i in report_data)
        total_non_member_revenue = sum(i.get('non_member_sales_value', 0) for i in report_data)
        overall_non_member_gp_pct = (total_non_member_gp / total_non_member_revenue * 100) if total_non_member_revenue > 0 else 0

        # Stocktake / surplus
        items_with_stocktake = [i for i in report_data if i.get('surplus_value') is not None]
        total_surplus_value = sum(i['surplus_value'] for i in items_with_stocktake) if items_with_stocktake else None
        has_stocktake = total_surplus_value is not None

        # Cost prices, stock values and sales revenue are now stored ex-VAT.
        # Gross profit and net profit are therefore ex-VAT. Inc-VAT figures are
        # shown separately in the report where useful.
        total_net_profit = total_sales_value - total_cost_of_sales

        # Pre-compute detailed item lists and their totals
        sales_items = [i for i in report_data if i['total_sales_qty'] > 0]
        wastage_items = [i for i in report_data if i['wastage_qty'] > 0]
        line_clean_items = [i for i in report_data if i.get('line_clean_qty', 0) > 0]
        supplier_return_items = [i for i in report_data if i.get('supplier_return_qty', 0) > 0]
        comp_items = [i for i in report_data if i['complimentary_qty'] > 0]
        open_tab_items = [i for i in report_data if i['open_tab_qty'] > 0]
        parent_adj_items = [i for i in report_data if i['parent_adj_qty'] > 0 and not i.get('is_hidden', False)]
        variance_items = [i for i in report_data if i['expected_consumption'] > 0 and not i.get('is_hidden', False)]

        total_wastage_value = sum(i['wastage_qty'] * i['cost_price'] for i in wastage_items)
        total_line_clean_value = sum(i.get('line_clean_qty', 0) * i['cost_price'] for i in line_clean_items)
        total_supplier_return_value = sum(i['supplier_return_qty'] * i['cost_price'] for i in supplier_return_items)
        total_comp_value = sum(i['complimentary_qty'] * i['sell_price'] for i in comp_items)

        # ------------------------------------------------------------------
        # PAGE 1: Executive Summary (directors' view)
        # ------------------------------------------------------------------
        self.generate_executive_summary(
            report_data, division_totals, by_division,
            total_stock_value, total_sales_value, total_gp,
            total_cost_of_sales, total_net_profit,
            total_member_revenue, total_non_member_revenue,
            total_member_gp, total_non_member_gp,
            overall_member_gp_pct, overall_non_member_gp_pct,
            total_wastage_value, total_line_clean_value,
            total_supplier_return_value, total_comp_value,
            total_surplus_value, running_surplus_value,
            has_member_data, has_stocktake, member_discount_pct
        )

        # ------------------------------------------------------------------
        # SECTION 1: Item Financial Breakdown
        # ------------------------------------------------------------------
        if has_member_data:
            item_fin_headers = ['Item', 'Revenue', 'Cost', 'GP', 'GP%', 'Mem Qty', 'Non-Mem', 'Mem GP', 'Mem GP%']
            item_fin_widths = [40, 20, 20, 20, 14, 18, 18, 20, 14]
        else:
            item_fin_headers = ['Item', 'Revenue', 'Cost', 'GP', 'GP%']
            item_fin_widths = [58, 28, 28, 28, 18]

        item_fin_rows = []
        for item in sales_items:
            if has_member_data:
                item_fin_rows.append([
                    item['item_name'][:22],
                    f"£{item['total_sales_value']:.2f}",
                    f"£{item['sales_cost']:.2f}",
                    f"£{item['sales_gp']:.2f}",
                    f"{item['sales_gp_pct']:.1f}%",
                    f"{item.get('member_qty', 0):.1f}" if item.get('member_qty', 0) > 0 else '-',
                    f"{item.get('non_member_qty', 0):.1f}" if item.get('non_member_qty', 0) > 0 else '-',
                    f"£{item['member_gp']:.2f}",
                    f"{item['member_gp_pct']:.1f}%"
                ])
            else:
                item_fin_rows.append([
                    item['item_name'][:34],
                    f"£{item['total_sales_value']:.2f}",
                    f"£{item['sales_cost']:.2f}",
                    f"£{item['sales_gp']:.2f}",
                    f"{item['sales_gp_pct']:.1f}%",
                ])

        if has_member_data:
            item_fin_total = [
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
        else:
            item_fin_total = [
                'TOTAL',
                f"£{total_sales_value:.2f}",
                f"£{sum(i['sales_cost'] for i in sales_items):.2f}",
                f"£{sum(i['sales_gp'] for i in sales_items):.2f}",
                '',
            ]

        if sales_items:
            self.render_table_block(
                '1. Item Financial Breakdown' + (' (incl. Member GP)' if has_member_data else ''),
                item_fin_headers, item_fin_widths, item_fin_rows,
                total_values=item_fin_total, font_size=7
            )
        else:
            self.chapter_title('1. Item Financial Breakdown')
            self.set_font('Arial', 'I', 10)
            self.cell(0, 10, 'No sales recorded in this period.', 0, 1, 'L')
        self.ln(5)

        # ------------------------------------------------------------------
        # SECTION 2: Stock Summary by Division
        # ------------------------------------------------------------------
        self.add_page()
        if has_member_data:
            div_headers = ['Division', 'Itm', 'Stk Val', 'Sale Val', 'GP', 'GP%', 'M Rev', 'M GP%', 'M GP', 'NM Rev', 'NM GP%', 'NM GP']
            div_widths = [20, 8, 15, 16, 15, 9, 16, 9, 15, 16, 9, 15]
        else:
            div_headers = ['Division', 'Itm', 'Stk Val', 'Sale Val', 'GP', 'GP%']
            div_widths = [30, 10, 20, 20, 20, 16]

        div_rows = []
        for division, totals in division_totals.items():
            gp_pct = (totals['gp'] / totals['sales_value'] * 100) if totals['sales_value'] > 0 else 0
            if has_member_data:
                div_rows.append([
                    division[:14],
                    len(by_division[division]),
                    f"£{totals['stock_value']:.2f}",
                    f"£{totals['sales_value']:.2f}",
                    f"£{totals['gp']:.2f}",
                    f"{gp_pct:.1f}%",
                    f"£{totals['member_sales_value']:.2f}",
                    f"{totals['member_gp_pct']:.1f}%",
                    f"£{totals['member_gp']:.2f}",
                    f"£{totals['non_member_sales_value']:.2f}",
                    f"{totals['non_member_gp_pct']:.1f}%",
                    f"£{totals['non_member_gp']:.2f}"
                ])
            else:
                div_rows.append([
                    division[:24],
                    len(by_division[division]),
                    f"£{totals['stock_value']:.2f}",
                    f"£{totals['sales_value']:.2f}",
                    f"£{totals['gp']:.2f}",
                    f"{gp_pct:.1f}%",
                ])

        if has_member_data:
            div_total = [
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
        else:
            div_total = [
                'TOTAL',
                len(report_data),
                f"£{total_stock_value:.2f}",
                f"£{total_sales_value:.2f}",
                f"£{total_gp:.2f}",
                f"{(total_gp / total_sales_value * 100) if total_sales_value > 0 else 0:.1f}%",
            ]

        self.render_table_block(
            '2. Stock Summary by Division',
            div_headers, div_widths, div_rows,
            total_values=div_total, font_size=6
        )
        self.ln(5)

        # ------------------------------------------------------------------
        # SECTION 3: Stock Movement & Variance
        # ------------------------------------------------------------------
        variance_headers = ['Item', 'Opening', '+Del.', '-Sold', '-Adj', '-Wast', '-Comp', 'Closing', 'Exp.Con', 'Act.Con', 'Var%']
        variance_widths = [34, 16, 14, 14, 14, 14, 14, 16, 16, 16, 14]

        variance_rows = []
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
            variance_rows.append([
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
            ])

        tot_adj_display = f"{totals['adj']:.1f}" if totals['adj'] > 0 else '-'
        total_var_pct = ((totals['exp_con'] - totals['act_con']) / totals['act_con'] * 100) if totals['act_con'] > 0 else 0
        variance_total = [
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

        if variance_items:
            self.render_table_block(
                '3. Stock Movement & Variance',
                variance_headers, variance_widths, variance_rows,
                total_values=variance_total, font_size=7,
                notes=[
                    'Units: draught/postmix = pints, spirits = measures (35ml), bottles/cans = units. Adj = parent stock deductions from child sales.',
                    'Exp.Con = Expected consumption (Sales+Wastage+Comp+Adj). Act.Con = Actual consumption (Opening+Deliveries-Closing). Var% = difference.'
                ]
            )
        else:
            self.chapter_title('3. Stock Movement & Variance')
            self.set_font('Arial', 'I', 10)
            self.cell(0, 10, 'No stock consumption data available for variance calculation.', 0, 1, 'L')

        # ------------------------------------------------------------------
        # SECTION 4: Draught Yield Report
        # ------------------------------------------------------------------
        draught_items = [i for i in draught_items if i['item_id'] in DRAUGHT_YIELD_ITEMS]
        if draught_items:
            draught_headers = ['Item', 'Sales', 'Adj.', 'Wast', 'Comp', 'Open Tabs', 'Consumed', 'Closing', 'Yield%']
            draught_widths = [38, 16, 14, 14, 14, 16, 18, 18, 16]
            draught_rows = []
            for item in draught_items:
                yield_pct = item['yield_pct']
                yield_str = f"{yield_pct:.1f}%" if yield_pct > 0 else "N/A"
                adj_display = f"{item['parent_adj_qty']:.1f}" if item.get('parent_adj_qty', 0) > 0 else '-'
                draught_rows.append([
                    item['item_name'][:18],
                    f"{item['total_sales_qty']:.1f}",
                    adj_display,
                    f"{item['wastage_qty']:.1f}" if item['wastage_qty'] > 0 else '-',
                    f"{item['complimentary_qty']:.1f}" if item['complimentary_qty'] > 0 else '-',
                    f"{item['open_tab_qty']:.1f}" if item['open_tab_qty'] > 0 else '-',
                    f"{item['expected_consumption']:.1f}",
                    f"{item['current_stock']:.1f}",
                    yield_str
                ])
            self.render_table_block(
                '4. Draught Yield Report (pints)',
                draught_headers, draught_widths, draught_rows,
                notes=['All quantities in pints. Yield% = Sales / Total Consumption. Adj = pints deducted via half pints/shandies.']
            )

        # ------------------------------------------------------------------
        # SECTION 5: Wastage Summary
        # ------------------------------------------------------------------
        wastage_headers = ['Item', 'Division', 'Wastage Qty', 'Cost Price', 'Wastage Value']
        wastage_widths = [60, 40, 25, 30, 30]
        wastage_rows = []
        total_wastage = sum(i['wastage_qty'] for i in wastage_items)
        for item in wastage_items:
            wastage_rows.append([
                item['item_name'][:25],
                item['division'][:18],
                f"{item['wastage_qty']:.1f}",
                f"£{item['cost_price']:.2f}",
                f"£{item['wastage_qty'] * item['cost_price']:.2f}"
            ])
        wastage_total = ['TOTAL', '', f"{total_wastage:.1f}", '', f"£{total_wastage_value:.2f}"]

        if wastage_items:
            self.render_table_block('5. Wastage Summary', wastage_headers, wastage_widths,
                                    wastage_rows, total_values=wastage_total)
        else:
            self.chapter_title('5. Wastage Summary')
            self.set_font('Arial', 'I', 10)
            self.cell(0, 10, 'No wastage recorded in this period.', 0, 1, 'L')
        self.ln(5)

        # ------------------------------------------------------------------
        # SECTION 6: Line Cleaning Summary
        # ------------------------------------------------------------------
        line_clean_headers = ['Item', 'Division', 'Line Clean Qty', 'Cost Price', 'Line Clean Value']
        line_clean_widths = [60, 40, 25, 30, 30]
        line_clean_rows = []
        total_line_clean = sum(i['line_clean_qty'] for i in line_clean_items)
        for item in line_clean_items:
            line_clean_rows.append([
                item['item_name'][:25],
                item['division'][:18],
                f"{item['line_clean_qty']:.1f}",
                f"£{item['cost_price']:.2f}",
                f"£{item['line_clean_qty'] * item['cost_price']:.2f}"
            ])
        line_clean_total = ['TOTAL', '', f"{total_line_clean:.1f}", '', f"£{total_line_clean_value:.2f}"]

        if line_clean_items:
            self.render_table_block('6. Line Cleaning Summary', line_clean_headers, line_clean_widths,
                                    line_clean_rows, total_values=line_clean_total)

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

        # ------------------------------------------------------------------
        # SECTION 7: Supplier Returns Summary
        # ------------------------------------------------------------------
        supplier_return_headers = ['Item', 'Division', 'Qty', 'Cost Price', 'Supplier', 'Reason', 'Return Value']
        supplier_return_widths = [40, 25, 18, 22, 25, 30, 25]
        supplier_return_rows = []
        total_supplier_return_qty = sum(i['supplier_return_qty'] for i in supplier_return_items)
        for item in supplier_return_items:
            supplier_return_rows.append([
                item['item_name'][:20],
                item['division'][:12],
                f"{item['supplier_return_qty']:.1f}",
                f"£{item['cost_price']:.2f}",
                str(item.get('supplier_return_supplier', ''))[:12],
                str(item.get('supplier_return_reason', ''))[:18],
                f"£{item['supplier_return_qty'] * item['cost_price']:.2f}"
            ])
        supplier_return_total = ['TOTAL', '', f"{total_supplier_return_qty:.1f}", '', '', '', f"£{total_supplier_return_value:.2f}"]

        if supplier_return_items:
            self.render_table_block('7. Supplier Returns Summary', supplier_return_headers,
                                    supplier_return_widths, supplier_return_rows,
                                    total_values=supplier_return_total)
        else:
            self.chapter_title('7. Supplier Returns Summary')
            self.set_font('Arial', 'I', 10)
            self.cell(0, 10, 'No supplier returns recorded in this period.', 0, 1, 'L')
        self.ln(5)

        if total_supplier_return_value > 0:
            self.set_font('Arial', 'B', 11)
            self.set_text_color(0, 0, 0)
            self.cell(0, 8, f"Total Supplier Return Value (at cost): £{total_supplier_return_value:.2f}", 0, 1, 'L')
            self.ln(5)

        # ------------------------------------------------------------------
        # SECTION: Delisted Stock Value (separate from active stock totals)
        # ------------------------------------------------------------------
        total_delisted_value = sum(
            i.get('delisted_stock_value', 0)
            for i in report_data
            if ' (DELISTED)' in i.get('item_name', '')
        )
        if total_delisted_value != 0:
            self.chapter_title('Delisted Stock Value')
            self.set_font('Arial', '', 11)
            self.set_text_color(0, 0, 0)
            self.cell(0, 8, f"Total delisted stock value (excluded from active stock): £{total_delisted_value:.2f}", 0, 1, 'L')
            self.ln(2)
            self.set_font('Arial', 'I', 8)
            self.cell(0, 5, 'Items are delisted from active stock but still physically held. Value is excluded from Total Stock Value.', 0, 1, 'L')
            self.ln(5)

        # ------------------------------------------------------------------
        # SECTION 8: Complimentary Summary
        # ------------------------------------------------------------------
        comp_headers = ['Item', 'Division', 'Qty', 'Retail Value']
        comp_widths = [70, 50, 30, 35]
        comp_rows = []
        total_comp = sum(i['complimentary_qty'] for i in comp_items)
        for item in comp_items:
            comp_rows.append([
                item['item_name'][:30],
                item['division'][:22],
                f"{item['complimentary_qty']:.1f}",
                f"£{item['complimentary_qty'] * item['sell_price']:.2f}"
            ])
        comp_total = ['TOTAL', '', f"{total_comp:.1f}", f"£{total_comp_value:.2f}"]

        if comp_items:
            self.render_table_block('8. Complimentary Summary', comp_headers, comp_widths,
                                    comp_rows, total_values=comp_total)
        else:
            self.chapter_title('8. Complimentary Summary')
            self.set_font('Arial', 'I', 10)
            self.cell(0, 10, 'No complimentary items recorded in this period.', 0, 1, 'L')
        self.ln(5)

        # ------------------------------------------------------------------
        # SECTION 9: Open Tabs / Pending Sales Summary
        # ------------------------------------------------------------------
        open_tab_headers = ['Item', 'Division', 'Qty', 'Cost Price', 'Pending Value']
        open_tab_widths = [60, 40, 25, 30, 30]
        open_tab_rows = []
        total_open_tab = sum(i['open_tab_qty'] for i in open_tab_items)
        total_open_tab_value = sum(i['open_tab_qty'] * i['cost_price'] for i in open_tab_items)
        for item in open_tab_items:
            open_tab_rows.append([
                item['item_name'][:25],
                item['division'][:18],
                f"{item['open_tab_qty']:.1f}",
                f"£{item['cost_price']:.2f}",
                f"£{item['open_tab_qty'] * item['cost_price']:.2f}"
            ])
        open_tab_total = ['TOTAL', '', f"{total_open_tab:.1f}", '', f"£{total_open_tab_value:.2f}"]

        if open_tab_items:
            self.render_table_block('9. Open Tabs / Pending Sales Summary', open_tab_headers,
                                    open_tab_widths, open_tab_rows, total_values=open_tab_total)
        else:
            self.chapter_title('9. Open Tabs / Pending Sales Summary')
            self.set_font('Arial', 'I', 10)
            self.cell(0, 10, 'No open tabs recorded in this period.', 0, 1, 'L')
        self.ln(5)

        # ------------------------------------------------------------------
        # SECTION 10: Parent Stock Adjustment Summary
        # ------------------------------------------------------------------
        if parent_adj_items:
            parent_adj_headers = ['Parent Item', 'Division', 'Qty Adjusted', 'Cost Price', 'Adj. Value']
            parent_adj_widths = [50, 40, 25, 30, 30]
            parent_adj_rows = []
            total_adj_qty = sum(i['parent_adj_qty'] for i in parent_adj_items)
            total_adj_value = sum(i['parent_adj_qty'] * i['cost_price'] for i in parent_adj_items)
            for item in parent_adj_items:
                parent_adj_rows.append([
                    item['item_name'][:25],
                    item['division'][:18],
                    f"{item['parent_adj_qty']:.1f}",
                    f"£{item['cost_price']:.2f}",
                    f"£{item['parent_adj_qty'] * item['cost_price']:.2f}"
                ])
            parent_adj_total = ['TOTAL', '', f"{total_adj_qty:.1f}", '', f"£{total_adj_value:.2f}"]
            self.render_table_block('10. Parent Stock Adjustments', parent_adj_headers,
                                    parent_adj_widths, parent_adj_rows,
                                    total_values=parent_adj_total)

        # ------------------------------------------------------------------
        # SECTION 11: Stocktake Variance Report
        # ------------------------------------------------------------------
        if stocktake_data:
            st_items = [i for i in stocktake_data if i.get('has_stocktake', False)]
            if st_items:
                # Sort by absolute variance value so the biggest issues appear first
                st_items.sort(key=lambda i: abs(i.get('variance_value', 0) or 0), reverse=True)

                st_headers = ['Item', 'Expected', 'Counted', 'Variance', 'Var %', 'Value']
                st_widths = [60, 22, 22, 22, 18, 22]
                st_rows = []
                st_fill_colors = []
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

                    st_rows.append([
                        item['item_name'][:28],
                        f"{expected:.1f}",
                        f"{counted:.1f}",
                        f"{variance:+.1f}",
                        f"{var_pct:+.1f}%",
                        f"£{var_val:+.2f}"
                    ])
                    if abs(var_pct) > 5:
                        st_fill_colors.append((248, 215, 218))
                    elif abs(var_pct) > 2:
                        st_fill_colors.append((255, 243, 205))
                    else:
                        st_fill_colors.append((255, 255, 255))

                total_var = total_counted - total_expected
                total_var_pct = (total_var / total_expected * 100) if total_expected > 0 else 0
                st_total = [
                    'TOTAL',
                    f"{total_expected:.1f}",
                    f"{total_counted:.1f}",
                    f"{total_var:+.1f}",
                    f"{total_var_pct:+.1f}%",
                    f"£{total_var_value:+.2f}"
                ]

                self.render_table_block(
                    '11. Stocktake Variance Report',
                    st_headers, st_widths, st_rows,
                    total_values=st_total, row_fill_colors=st_fill_colors,
                    notes=[
                        'Expected = system quantity at time of stocktake. Counted = physical count entered. Variance = Counted - Expected.',
                        'Red highlight = variance > 5%. Yellow highlight = variance > 2%. Value = variance × cost price.'
                    ]
                )
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

            item_id = item.get('item_id', '')
            is_item_delisted = is_delisted(item_id)
            item_name = item.get('item_name', '')
            if is_item_delisted:
                item_name = f"{item_name} (DELISTED)"

            self.set_font('Arial', '', 9)
            self.set_fill_color(255, 255, 255)
            self.set_text_color(0, 0, 0)
            self.cell(widths[0], 8, item_name[:35], 1, 0, 'L', True)
            self.cell(widths[1], 8, item.get('category', '')[:20], 1, 0, 'L', True)

            # Convert to natural units (barrels, bottles, boxes, cartons) where applicable.
            # Delisted items show no expected quantity because stock has been removed.
            txn_expected = item.get('txn_expected', 0)
            if is_item_delisted:
                expected_text = 'DELISTED'
            elif requires_conversion(item_id):
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
        self.cell(0, 5, f'Generated: {datetime.now().strftime(f"{DATE_FORMAT_DISPLAY} at %H:%M")}', 0, 1, 'C')
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
        self.cell(0, 5, f'Generated: {datetime.now().strftime(f"{DATE_FORMAT_DISPLAY} at %H:%M")}', 0, 1, 'C')
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
            downloads_dir: Directory to save the PDF file. Defaults to ~/Downloads.

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
