"""
PDF Report Generator for Bar Stock Management.

Contains the PDFReport and PriceHistoryPDF classes extracted from BarStockApp.py.
"""

import os
import re
from datetime import datetime
from collections import defaultdict
from fpdf import FPDF
from conversions import convert_to_input, requires_conversion, get_input_label, DATE_FORMAT_DISPLAY
from categories import is_delisted
from money import allocate_money, inc_vat, round_money, sum_money
import app_config
import club_profile

# Standard UK VAT rate used to show inc-VAT equivalents on the executive summary.
VAT_RATE = 0.20
VAT_MULTIPLIER = 1.0 + VAT_RATE


def format_report_period(start_date=None, end_date=None):
    """Build the date-range label printed on a report.

    Dates come from the date-range picker as datetime/date/Timestamp objects.
    When no bounds were chosen the report covers everything, and the label says
    so rather than leaving the page silent about its period.
    """
    def _fmt(value):
        if hasattr(value, 'strftime'):
            return value.strftime(DATE_FORMAT_DISPLAY)
        return str(value).strip()

    if start_date is None and end_date is None:
        return 'All time'
    if start_date is None:
        return f'Up to {_fmt(end_date)}'
    if end_date is None:
        return f'From {_fmt(start_date)}'
    return f'{_fmt(start_date)} to {_fmt(end_date)}'


def allocate_division_inc_vat(division_totals):
    """Return {division: inc-VAT sales} that adds up to the inc-VAT grand total.

    Each division is first struck with the same single-rounding rule as the
    item and dashboard figures. The few pence of residual needed to match the
    grand total are then applied to the largest divisions by sales, so a small
    line such as a single function keeps its exact inc-VAT amount instead of
    absorbing the rounding.
    """
    division_names = list(division_totals)
    if not division_names:
        return {}

    values = {name: inc_vat(division_totals[name]['sales_value'])
              for name in division_names}
    target = inc_vat(sum_money(
        division_totals[name]['sales_value'] for name in division_names))
    residual = round_money(target - sum_money(values.values()))
    if residual:
        step = 0.01 if residual > 0 else -0.01
        order = sorted(
            division_names,
            key=lambda name: division_totals[name]['sales_value'],
            reverse=True)
        for position in range(int(round(abs(residual) / 0.01))):
            name = order[position % len(order)]
            values[name] = round_money(values[name] + step)
    return values


# ---------------------------------------------------------------------------
# The Ledger on paper: core fonts only (no TTF bundling)
# ---------------------------------------------------------------------------
PDF_INK = (27, 34, 30)
PDF_MUTED = (108, 117, 108)
PDF_BOTTLE = (22, 68, 59)
PDF_COPPER = (142, 90, 43)
PDF_RULE = (215, 217, 205)
PDF_RAIL = (242, 241, 233)
PDF_PAPER = (255, 255, 255)
PDF_ZEBRA = (250, 249, 244)
PDF_FONT = 'helvetica'
PDF_DISPLAY = 'times'


def calculate_vat_summary(sales_value, gp, net_profit):
    """Return the ex-VAT figures and their VAT equivalents.

    VAT is charged on sales, not on profit. GP and net profit are margins and
    must never be multiplied by the VAT factor -- doing so overstated them by
    20% on the executive summary.

    Inc-VAT sales are the ex-VAT total plus the rounded VAT, so the two figures
    add up exactly on the summary.
    """
    sales_ex_vat = round_money(sales_value)
    vat_on_sales = round_money(sales_ex_vat * VAT_RATE)
    return {
        'sales_ex_vat': sales_ex_vat,
        'sales_inc_vat': round_money(sales_ex_vat + vat_on_sales),
        'gp_ex_vat': round_money(gp),
        'net_profit_ex_vat': round_money(net_profit),
        'vat_on_sales': vat_on_sales,
    }


def calculate_vat_position(sales_ex_vat, delivery_spend_ex_vat):
    """Return estimated output VAT, input VAT and the net VAT position.

    This is a management summary, not a VAT return. It assumes every recorded
    sale and delivery is standard-rated at 20% and only counts input VAT on
    stock deliveries, not on other club purchases.
    """
    sales_ex_vat = round_money(sales_ex_vat)
    delivery_spend_ex_vat = round_money(delivery_spend_ex_vat)
    output_vat = round_money(sales_ex_vat * VAT_RATE)
    input_vat = round_money(delivery_spend_ex_vat * VAT_RATE)
    return {
        'sales_ex_vat': sales_ex_vat,
        'output_vat': output_vat,
        'deliveries_ex_vat': delivery_spend_ex_vat,
        'input_vat': input_vat,
        'net_vat': round_money(output_vat - input_vat),
    }


def _pdf_signed_money(value):
    """Format a movement as +£1,234.56 or -£1,234.56."""
    value = round_money(value)
    sign = '-' if value < 0 else '+'
    return f"{sign}£{abs(value):,.2f}"


def _is_numeric_display(value):
    """True when a table cell should be right-aligned.

    Money can arrive as £1.00, +£1.00 or -£1.00, and percentages/quantities
    should line up too. Treating only strings that start with '£' as numeric
    left signed money and percentages visually ragged.
    """
    if isinstance(value, (int, float)):
        return True
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    if text in ('-', '—'):
        return True
    if re.match(r'^[+-]?£[\d,]+(\.\d+)?$', text):
        return True
    if re.match(r'^[+-]?\d[\d,.]*%$', text):
        return True
    return bool(re.match(r'^[+-]?\d[\d,.]*$', text))


def _pdf_club_title(suffix):
    prefix = club_profile.pdf_header_prefix().strip()
    return f"{prefix} - {suffix}" if prefix else suffix


def _draw_pdf_logo(pdf):
    """Draw the club crest at the top-left when a logo is configured."""
    path = club_profile.get_logo_path()
    if not path:
        return
    try:
        pdf.image(path, x=10, y=8, w=12)
    except Exception:
        pass


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

    # Period the report covers, set by generate_report. Printed under the title
    # on every page so a saved PDF states the date range it was run for.
    report_period = None

    def header(self):
        """Add header to each page."""
        self.set_font(PDF_DISPLAY, 'B', 16)
        self.set_text_color(*PDF_INK)
        self.cell(0, 10, _pdf_club_title('Bar Stock Report'), 0, 1, 'C')
        _draw_pdf_logo(self)
        self.set_font(PDF_FONT, '', 10)
        self.set_text_color(*PDF_MUTED)
        self.cell(0, 5, f'Generated: {datetime.now().strftime(f"{DATE_FORMAT_DISPLAY} at %H:%M")}', 0, 1, 'C')
        if self.report_period:
            self.set_font(PDF_FONT, 'B', 10)
            self.set_text_color(*PDF_INK)
            self.cell(0, 5, f'Report period: {self.report_period}', 0, 1, 'C')
        self.ln(5)
        self.set_draw_color(*PDF_RULE)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def footer(self):
        """Add footer to each page."""
        self.set_y(-15)
        self.set_font(PDF_FONT, 'I', 8)
        self.set_text_color(*PDF_MUTED)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    def chapter_title(self, title):
        """Add a section title."""
        self.set_x(self.l_margin)
        self.set_font(PDF_DISPLAY, 'B', 13)
        self.set_text_color(*PDF_BOTTLE)
        self.cell(0, 10, title, 0, 1, 'L')
        self.ln(2)

    def section_table_header(self, headers, widths, font_size=7):
        """Draw table header with styling."""
        self.set_x(self.l_margin)
        self.set_font(PDF_FONT, 'B', font_size)
        self.set_fill_color(*PDF_RAIL)
        self.set_text_color(*PDF_INK)
        for header, width in zip(headers, widths):
            self.cell(width, 6, header, 1, 0, 'C', True)
        self.ln()

    def section_table_row(self, values, widths, is_total=False, font_size=7):
        """Draw table row."""
        if is_total:
            self.set_font(PDF_FONT, 'B', font_size)
            self.set_fill_color(*PDF_RAIL)
        else:
            self.set_font(PDF_FONT, '', font_size)
            self.set_fill_color(*PDF_PAPER)

        self.set_text_color(*PDF_INK)
        for value, width in zip(values, widths):
            align = 'R' if _is_numeric_display(value) else 'L'
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
        self.set_x(self.l_margin)
        total_rows_count = 1 if total_values is not None else 0
        notes_height = 0
        if notes:
            notes_height = len(notes) * notes_font_size * 0.45 + 4
        # Add a safety buffer so tables that barely fit don't start and then
        # spill over the footer mid-way.
        estimated_height = (header_height + len(rows) * row_height +
                            total_rows_count * row_height + notes_height + 15)

        def _draw_row(values, is_total=False, fill_color=None, zebra=False):
            if is_total:
                self.set_font(PDF_FONT, 'B', font_size)
                self.set_fill_color(*PDF_RAIL)
            else:
                self.set_font(PDF_FONT, '', font_size)
                if fill_color:
                    self.set_fill_color(*fill_color)
                elif zebra:
                    self.set_fill_color(*PDF_ZEBRA)
                else:
                    self.set_fill_color(*PDF_PAPER)
            self.set_text_color(*PDF_INK)
            for value, width in zip(values, widths):
                align = 'R' if _is_numeric_display(value) else 'L'
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
                _draw_row(row_values,
                          fill_color=row_fill_colors[idx] if row_fill_colors else None,
                          zebra=bool(idx % 2))
            if total_values is not None:
                _draw_row(total_values, is_total=True)
            if notes:
                self.ln(2)
                self.set_font(PDF_FONT, 'I', notes_font_size)
                self.set_text_color(*PDF_INK)
                for note in notes:
                    self.set_x(self.l_margin)
                    self.multi_cell(self.w - self.l_margin - self.r_margin,
                                    notes_font_size * 0.5, _pdf_safe(note))
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
            _draw_row(row_values,
                      fill_color=row_fill_colors[idx] if row_fill_colors else None,
                      zebra=bool(idx % 2))

        if total_values is not None:
            if self._available_page_space() < row_height + 10:
                self.add_page()
                if repeat_header:
                    self.section_table_header(headers, widths, font_size=font_size)
            _draw_row(total_values, is_total=True)

        if notes:
            self.ln(2)
            self.set_font(PDF_FONT, 'I', notes_font_size)
            self.set_text_color(*PDF_INK)
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

        All stored figures are ex-VAT. Sales are also shown inc-VAT at the
        standard UK rate (20%) so directors can compare against EPOS/till
        totals. GP and net profit are margins and are only meaningful ex-VAT.
        """
        vat = calculate_vat_summary(total_sales_value, total_gp, total_net_profit)
        total_sales_inc_vat = vat['sales_inc_vat']
        vat_on_sales = vat['vat_on_sales']
        overall_gp_pct = (total_gp / total_sales_value * 100) if total_sales_value > 0 else 0

        self.add_page()
        self.set_font(PDF_DISPLAY, 'B', 15)
        self.set_text_color(*PDF_BOTTLE)
        self.cell(0, 10, 'Executive Summary', 0, 1, 'C')
        self.ln(2)

        insights = getattr(self, 'insights', {}) or {}
        comparison_current = (insights.get('comparison') or {}).get('current') or {}
        vat_position = insights.get('vat_position') or {}
        delivery_spend = comparison_current.get('delivery_spend', 0)
        vat_due = vat_position.get('net_vat', vat_on_sales)

        # Key KPI boxes (2 rows of 4)
        kpis = [
            ('Stock value (ex-VAT)', f"£{total_stock_value:,.2f}"),
            ('Sales (ex-VAT)', f"£{total_sales_value:,.2f}"),
            ('GP (ex-VAT)', f"£{total_gp:,.2f}"),
            ('GP margin', f"{overall_gp_pct:.1f}%"),
            ('Sales (inc-VAT)', f"£{total_sales_inc_vat:,.2f}"),
            ('Wastage + line clean', f"£{total_wastage_value + total_line_clean_value:,.2f}"),
            ('Deliveries (ex-VAT)', f"£{delivery_spend:,.2f}"),
            ('VAT position', _pdf_signed_money(vat_due)),
        ]

        box_width = 45
        box_height = 18
        box_spacing = 2
        start_x = 10
        y = self.get_y()
        for idx, (label, value) in enumerate(kpis):
            col = idx % 4
            row = idx // 4
            x = start_x + col * (box_width + box_spacing)
            box_y = y + row * (box_height + box_spacing)
            self.set_xy(x, box_y)
            self.set_fill_color(*PDF_RAIL)
            self.set_draw_color(*PDF_RULE)
            self.rect(x, box_y, box_width, box_height, 'FD')
            self.set_xy(x, box_y + 2)
            self.set_font(PDF_FONT, 'B', 6.5)
            self.set_text_color(*PDF_MUTED)
            self.cell(box_width, 5, label, 0, 2, 'C')
            self.set_font(PDF_FONT, 'B', 11)
            self.set_text_color(*PDF_BOTTLE)
            self.cell(box_width, 9, value, 0, 2, 'C')

        self.set_y(y + 2 * (box_height + box_spacing) + 4)

        # Plain-language movement bullets. The detailed comparison table lives
        # in Section 1; page 1 stays readable for directors.
        narrative = insights.get('narrative') or []
        if narrative:
            self.set_font(PDF_FONT, 'B', 10)
            self.set_text_color(*PDF_BOTTLE)
            self.cell(0, 6, 'What changed', 0, 1, 'L')
            self.set_font(PDF_FONT, '', 8.5)
            self.set_text_color(*PDF_INK)
            for bullet in narrative[:6]:
                self.set_x(self.l_margin)
                self.multi_cell(self.w - self.l_margin - self.r_margin, 4.5,
                                _pdf_safe(f"- {bullet}"))
            self.ln(2)

        # A one-line contents map keeps the summary page navigable without a
        # full table-of-contents page.
        self.set_font(PDF_FONT, 'B', 8)
        self.set_text_color(*PDF_MUTED)
        self.set_x(self.l_margin)
        self.multi_cell(
            self.w - self.l_margin - self.r_margin, 4.5,
            'Contents: 1 Trading performance  |  2 Stock position  |  '
            '3 Suppliers  |  4 Costs  |  5 VAT  |  6 Reconciliation')
        self.ln(2)

        # Top 5 sales items — keep the heading with its table.
        if self._available_page_space() < 45:
            self.add_page()
        self.set_font(PDF_FONT, 'B', 10)
        self.set_text_color(*PDF_BOTTLE)
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
                f"£{item['total_sales_value']:,.2f}",
                f"£{item['total_sales_value'] * VAT_MULTIPLIER:,.2f}",
                f"{item['total_sales_qty']:.1f}",
                f"{item['sales_gp_pct']:.1f}%",
            ])
        self.render_table_block(None, top_headers, top_widths, top_rows,
                                font_size=7, row_height=4)

    def _render_comparison_summary(self):
        """Render the headline current-vs-previous table for Section 1."""
        comparison = self.insights.get('comparison') or {}
        current = comparison.get('current') or {}
        previous = comparison.get('previous')
        changes = comparison.get('changes') or {}
        if not current:
            self.set_font(PDF_FONT, 'I', 9)
            self.cell(0, 6, 'No period comparison available.', 0, 1, 'L')
            return

        metrics = [
            ('Sales ex-VAT', 'sales_ex_vat', 'money'),
            ('Sales inc-VAT', 'sales_inc_vat', 'money'),
            ('Cost of sales', 'cost_of_sales', 'money'),
            ('Gross profit', 'gp', 'money'),
            ('GP margin', 'gp_pct', 'pct'),
            ('Wastage', 'wastage_cost', 'money'),
            ('Line cleaning', 'line_clean_cost', 'money'),
            ('Complimentary (retail)', 'complimentary_retail', 'money'),
            ('Supplier returns', 'supplier_returns_cost', 'money'),
            ('Deliveries', 'delivery_spend', 'money'),
        ]
        rows = []
        for label, key, kind in metrics:
            current_value = current.get(key, 0) or 0
            previous_value = previous.get(key) if previous else None
            change = changes.get(key) or {}
            if kind == 'pct':
                current_text = f"{current_value:.1f}%"
                previous_text = (f"{previous_value:.1f}%"
                                 if previous_value is not None else '-')
                delta = change.get('pp')
                delta_text = f"{delta:+.1f} pp" if delta is not None else '-'
            else:
                current_text = f"£{current_value:,.2f}"
                previous_text = (f"£{previous_value:,.2f}"
                                 if previous_value is not None else '-')
                delta = change.get('delta')
                delta_text = _pdf_signed_money(delta) if delta is not None else '-'
            pct = change.get('pct')
            pct_text = f"{pct:+.1f}%" if pct is not None else '-'
            rows.append([_pdf_safe(label, 26), current_text, previous_text,
                         delta_text, pct_text])

        headers = ['Metric', 'Current', 'Previous', 'Change', 'Change %']
        widths = [58, 32, 32, 32, 26]
        self.render_table_block('1.1 Headline comparison', headers, widths, rows,
                                font_size=7, row_height=4)

    def generate_report(self, report_data, member_discount_pct=10, stocktake_data=None, running_surplus_value=None,
                        report_period=None, insights=None):
        """Generate the full report.

        Args:
            report_data: list of item dicts from build_comprehensive_report_data.
            member_discount_pct: member discount percentage.
            stocktake_data: Stocktake Variance Report data for the selected period.
            running_surplus_value: Cumulative surplus/shortfall value from all
                historical stocktakes, surviving baseline resets.
            report_period: Date-range label for the period the report covers,
                printed in the header of every page.
            insights: optional dict of summary data built in screens/reports.py
                (comparison, supplier spend, VAT, reasons, value bridge, notes).
        """
        # Set before the first add_page() so every page header carries the range.
        self.report_period = report_period
        self.insights = insights or {}
        # Every item with a value in the dashboard's stock holding is reported,
        # including equipment, so the committee pack and the app agree.
        # Determine whether any member split data exists
        has_member_data = any(i.get('member_sales_value', 0) > 0 for i in report_data)

        # Group data by division and classify draught items
        by_division = defaultdict(list)
        draught_items = []
        for item in report_data:
            by_division[item['division']].append(item)
            if item['is_draught']:
                draught_items.append(item)

        # Pre-compute division totals. Item values are already struck to the
        # penny, so the division rows add up exactly to the grand totals.
        division_totals = {}
        for division, items in by_division.items():
            member_revenue = sum_money(i['member_sales_value'] for i in items)
            non_member_revenue = sum_money(i.get('non_member_sales_value', 0) for i in items)
            member_gp = sum_money(i['member_gp'] for i in items)
            non_member_gp = sum_money(i.get('non_member_gp', 0) for i in items)
            division_totals[division] = {
                'stock_value': sum_money(i['stock_value'] for i in items),
                'sales_value': round_money(member_revenue + non_member_revenue),
                'gp': round_money(member_gp + non_member_gp),
                'sales_qty': sum(i['total_sales_qty'] for i in items),
                'member_gp': member_gp,
                'member_sales_value': member_revenue,
                'member_gp_pct': (member_gp / member_revenue * 100) if member_revenue > 0 else 0,
                'non_member_gp': non_member_gp,
                'non_member_sales_value': non_member_revenue,
                'non_member_gp_pct': (non_member_gp / non_member_revenue * 100) if non_member_revenue > 0 else 0,
            }

        # Inc-VAT sales per division, allocated so the rows add up to the total.
        division_inc_vat = allocate_division_inc_vat(division_totals)
        for name, value in division_inc_vat.items():
            division_totals[name]['sales_inc_vat'] = value

        # Grand totals
        total_stock_value = sum_money(d['stock_value'] for d in division_totals.values())
        total_sales_value = sum_money(d['sales_value'] for d in division_totals.values())
        total_gp = sum_money(d['gp'] for d in division_totals.values())
        total_sales_inc_vat = sum_money(d['sales_inc_vat'] for d in division_totals.values())
        total_cost_of_sales = round_money(total_sales_value - total_gp)
        total_sales_qty = sum(d['sales_qty'] for d in division_totals.values())
        total_member_gp_div = sum_money(d['member_gp'] for d in division_totals.values())
        total_member_rev_div = sum_money(d['member_sales_value'] for d in division_totals.values())
        total_member_gp_pct_div = (total_member_gp_div / total_member_rev_div * 100) if total_member_rev_div > 0 else 0
        total_non_member_gp_div = sum_money(d['non_member_gp'] for d in division_totals.values())
        total_non_member_rev_div = sum_money(d['non_member_sales_value'] for d in division_totals.values())
        total_non_member_gp_pct_div = (total_non_member_gp_div / total_non_member_rev_div * 100) if total_non_member_rev_div > 0 else 0

        # Member/non-member overall totals
        total_member_gp = sum_money(i['member_gp'] for i in report_data)
        total_member_revenue = sum_money(i['member_sales_value'] for i in report_data)
        overall_member_gp_pct = (total_member_gp / total_member_revenue * 100) if total_member_revenue > 0 else 0
        total_non_member_gp = sum_money(i.get('non_member_gp', 0) for i in report_data)
        total_non_member_revenue = sum_money(i.get('non_member_sales_value', 0) for i in report_data)
        overall_non_member_gp_pct = (total_non_member_gp / total_non_member_revenue * 100) if total_non_member_revenue > 0 else 0

        # Stocktake / surplus
        items_with_stocktake = [i for i in report_data if i.get('surplus_value') is not None]
        total_surplus_value = sum_money(i['surplus_value'] for i in items_with_stocktake) if items_with_stocktake else None
        has_stocktake = total_surplus_value is not None

        # Cost prices, stock values and sales revenue are now stored ex-VAT.
        # Gross profit and net profit are therefore ex-VAT. Inc-VAT figures are
        # shown separately in the report where useful.
        total_net_profit = round_money(total_sales_value - total_cost_of_sales)

        # Pre-compute detailed item lists and their totals
        sales_items = [i for i in report_data if i['total_sales_qty'] > 0]
        wastage_items = [i for i in report_data if i['wastage_qty'] > 0]
        line_clean_items = [i for i in report_data if i.get('line_clean_qty', 0) > 0]
        supplier_return_items = [i for i in report_data if i.get('supplier_return_qty', 0) > 0]
        comp_items = [i for i in report_data if i['complimentary_qty'] > 0]
        open_tab_items = [i for i in report_data if i['open_tab_qty'] > 0]
        parent_adj_items = [i for i in report_data if i['parent_adj_qty'] > 0
                            and not i.get('is_hidden', False)
                            and not i.get('is_delisted', False)]
        variance_items = [i for i in report_data if i['expected_consumption'] > 0
                          and not i.get('is_hidden', False)
                          and not i.get('is_delisted', False)]

        # Value each item column once, allocated to the penny, so the rows in
        # each summary add up exactly to the total printed beneath them.
        wastage_values = allocate_money(
            [i['wastage_qty'] * i['cost_price'] for i in wastage_items])
        line_clean_values = allocate_money(
            [i.get('line_clean_qty', 0) * i['cost_price'] for i in line_clean_items])
        supplier_return_values = allocate_money(
            [i['supplier_return_qty'] * i['cost_price'] for i in supplier_return_items])
        comp_values = allocate_money(
            [i['complimentary_qty'] * i['sell_price'] for i in comp_items])
        open_tab_values = allocate_money(
            [i['open_tab_qty'] * i['cost_price'] for i in open_tab_items])
        parent_adj_values = allocate_money(
            [i['parent_adj_qty'] * i['cost_price'] for i in parent_adj_items])

        total_wastage_value = sum_money(wastage_values)
        total_line_clean_value = sum_money(line_clean_values)
        total_supplier_return_value = sum_money(supplier_return_values)
        total_comp_value = sum_money(comp_values)
        total_open_tab_value = sum_money(open_tab_values)
        total_adj_value = sum_money(parent_adj_values)

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
        # The full item table is deferred to Appendix B so the report opens
        # with the summary sections. It is rendered at the end of this method.
        # ------------------------------------------------------------------

        # ------------------------------------------------------------------
        # SECTION 1: Trading Performance vs Previous Period
        # ------------------------------------------------------------------
        self.add_page()
        self.chapter_title('1. Trading Performance vs Previous Period')
        self._render_comparison_summary()
        self.ln(2)
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
                    f"£{totals['stock_value']:,.2f}",
                    f"£{totals['sales_value']:,.2f}",
                    f"£{totals['gp']:,.2f}",
                    f"{gp_pct:.1f}%",
                    f"£{totals['member_sales_value']:,.2f}",
                    f"{totals['member_gp_pct']:.1f}%",
                    f"£{totals['member_gp']:,.2f}",
                    f"£{totals['non_member_sales_value']:,.2f}",
                    f"{totals['non_member_gp_pct']:.1f}%",
                    f"£{totals['non_member_gp']:,.2f}"
                ])
            else:
                div_rows.append([
                    division[:24],
                    len(by_division[division]),
                    f"£{totals['stock_value']:,.2f}",
                    f"£{totals['sales_value']:,.2f}",
                    f"£{totals['gp']:,.2f}",
                    f"{gp_pct:.1f}%",
                ])

        if has_member_data:
            div_total = [
                'TOTAL',
                len(report_data),
                f"£{total_stock_value:,.2f}",
                f"£{total_sales_value:,.2f}",
                f"£{total_gp:,.2f}",
                f"{(total_gp / total_sales_value * 100) if total_sales_value > 0 else 0:.1f}%",
                f"£{total_member_rev_div:,.2f}",
                f"{total_member_gp_pct_div:.1f}%",
                f"£{total_member_gp_div:,.2f}",
                f"£{total_non_member_rev_div:,.2f}",
                f"{total_non_member_gp_pct_div:.1f}%",
                f"£{total_non_member_gp_div:,.2f}"
            ]
        else:
            div_total = [
                'TOTAL',
                len(report_data),
                f"£{total_stock_value:,.2f}",
                f"£{total_sales_value:,.2f}",
                f"£{total_gp:,.2f}",
                f"{(total_gp / total_sales_value * 100) if total_sales_value > 0 else 0:.1f}%",
            ]

        self.render_table_block(
            '1.2 Sales by Division',
            div_headers, div_widths, div_rows,
            total_values=div_total, font_size=6
        )
        self.ln(5)

        # ------------------------------------------------------------------
        # SECTION 2: Stock Position & Movement
        # ------------------------------------------------------------------
        self.add_page()
        self.chapter_title('2. Stock Position & Movement')
        self._render_value_bridge()
        self.ln(4)
        self._render_division_stock_movement(report_data)
        self.ln(4)
        self._render_stock_exceptions(stocktake_data, report_data)

        # ------------------------------------------------------------------
        # SECTION 3: Supplier Spend and Price Changes
        # ------------------------------------------------------------------
        self._render_supplier_spend()

        # ------------------------------------------------------------------
        # SECTION 4: Wastage, Line Cleaning and Complimentary
        # ------------------------------------------------------------------
        self.chapter_title('4. Costs & Exceptions')
        self._render_reason_summary(
            '4.1 Wastage by reason',
            self.insights.get('wastage_reasons'),
            'Value at cost. Line cleaning is reported separately.')
        wastage_headers = ['Item', 'Division', 'Wastage Qty', 'Cost Price', 'Wastage Value']
        wastage_widths = [60, 40, 25, 30, 30]
        wastage_rows = []
        total_wastage = sum(i['wastage_qty'] for i in wastage_items)
        for item, value in zip(wastage_items, wastage_values):
            wastage_rows.append([
                item['item_name'][:25],
                item['division'][:18],
                f"{item['wastage_qty']:.1f}",
                f"£{item['cost_price']:.2f}",
                f"£{value:.2f}"
            ])
        wastage_total = ['TOTAL', '', f"{total_wastage:.1f}", '', f"£{total_wastage_value:.2f}"]

        if wastage_items:
            self.render_table_block('4.1 Wastage by item', wastage_headers, wastage_widths,
                                    wastage_rows, total_values=wastage_total)
        else:
            self.chapter_title('4.1 Wastage by item')
            self.set_font(PDF_FONT, 'I', 10)
            self.cell(0, 10, 'No wastage recorded in this period.', 0, 1, 'L')
        self.ln(5)

        # ------------------------------------------------------------------
        # SECTION 6: Line Cleaning Summary
        # ------------------------------------------------------------------
        line_clean_headers = ['Item', 'Division', 'Line Clean Qty', 'Cost Price', 'Line Clean Value']
        line_clean_widths = [60, 40, 25, 30, 30]
        line_clean_rows = []
        total_line_clean = sum(i['line_clean_qty'] for i in line_clean_items)
        for item, value in zip(line_clean_items, line_clean_values):
            line_clean_rows.append([
                item['item_name'][:25],
                item['division'][:18],
                f"{item['line_clean_qty']:.1f}",
                f"£{item['cost_price']:.2f}",
                f"£{value:.2f}"
            ])
        line_clean_total = ['TOTAL', '', f"{total_line_clean:.1f}", '', f"£{total_line_clean_value:.2f}"]

        self._render_reason_summary(
            '4.2 Line cleaning by reason',
            self.insights.get('line_clean_reasons'),
            'Value at cost.')
        if line_clean_items:
            self.render_table_block('4.2 Line cleaning by item', line_clean_headers, line_clean_widths,
                                    line_clean_rows, total_values=line_clean_total)

        # Combined Wastage & Line Clean note
        if total_wastage_value > 0 or total_line_clean_value > 0:
            combined_total = total_wastage_value + total_line_clean_value
            self.set_font(PDF_FONT, 'B', 11)
            self.set_text_color(*PDF_INK)
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
        for item, value in zip(supplier_return_items, supplier_return_values):
            supplier_return_rows.append([
                item['item_name'][:20],
                item['division'][:12],
                f"{item['supplier_return_qty']:.1f}",
                f"£{item['cost_price']:.2f}",
                str(item.get('supplier_return_supplier', ''))[:12],
                str(item.get('supplier_return_reason', ''))[:18],
                f"£{value:.2f}"
            ])
        supplier_return_total = ['TOTAL', '', f"{total_supplier_return_qty:.1f}", '', '', '', f"£{total_supplier_return_value:.2f}"]

        if supplier_return_items:
            self.render_table_block('4.3 Supplier Returns Summary', supplier_return_headers,
                                    supplier_return_widths, supplier_return_rows,
                                    total_values=supplier_return_total)
        else:
            self.chapter_title('4.3 Supplier Returns Summary')
            self.set_font(PDF_FONT, 'I', 10)
            self.cell(0, 10, 'No supplier returns recorded in this period.', 0, 1, 'L')
        self.ln(5)

        if total_supplier_return_value > 0:
            self.set_font(PDF_FONT, 'B', 11)
            self.set_text_color(*PDF_INK)
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
            self.chapter_title('4.3a Delisted Stock Value')
            self.set_font(PDF_FONT, '', 11)
            self.set_text_color(*PDF_INK)
            self.cell(0, 8, f"Total delisted stock value (excluded from active stock): £{total_delisted_value:.2f}", 0, 1, 'L')
            self.ln(2)
            self.set_font(PDF_FONT, 'I', 8)
            self.cell(0, 5, 'Items are delisted from active stock but still physically held. Value is excluded from Total Stock Value.', 0, 1, 'L')
            self.ln(5)

        # ------------------------------------------------------------------
        # SECTION 8: Complimentary Summary
        # ------------------------------------------------------------------
        comp_headers = ['Item', 'Division', 'Qty', 'Retail Value']
        comp_widths = [70, 50, 30, 35]
        comp_rows = []
        total_comp = sum(i['complimentary_qty'] for i in comp_items)
        for item, value in zip(comp_items, comp_values):
            comp_rows.append([
                item['item_name'][:30],
                item['division'][:22],
                f"{item['complimentary_qty']:.1f}",
                f"£{value:.2f}"
            ])
        comp_total = ['TOTAL', '', f"{total_comp:.1f}", f"£{total_comp_value:.2f}"]

        self._render_reason_summary(
            '4.4 Complimentary by reason',
            self.insights.get('comp_reasons'),
            'Value at retail (ex VAT).')
        if comp_items:
            self.render_table_block('4.4 Complimentary by item', comp_headers, comp_widths,
                                    comp_rows, total_values=comp_total)
        else:
            self.chapter_title('4.4 Complimentary by item')
            self.set_font(PDF_FONT, 'I', 10)
            self.cell(0, 10, 'No complimentary items recorded in this period.', 0, 1, 'L')
        self.ln(5)

        # ------------------------------------------------------------------
        # SECTION 9: Open Tabs / Pending Sales Summary
        # ------------------------------------------------------------------
        open_tab_headers = ['Item', 'Division', 'Qty', 'Cost Price', 'Pending Value']
        open_tab_widths = [60, 40, 25, 30, 30]
        open_tab_rows = []
        total_open_tab = sum(i['open_tab_qty'] for i in open_tab_items)
        for item, value in zip(open_tab_items, open_tab_values):
            open_tab_rows.append([
                item['item_name'][:25],
                item['division'][:18],
                f"{item['open_tab_qty']:.1f}",
                f"£{item['cost_price']:.2f}",
                f"£{value:.2f}"
            ])
        open_tab_total = ['TOTAL', '', f"{total_open_tab:.1f}", '', f"£{total_open_tab_value:.2f}"]

        if open_tab_items:
            self.render_table_block('4.5 Open Tabs / Pending Sales', open_tab_headers,
                                    open_tab_widths, open_tab_rows, total_values=open_tab_total)
        else:
            self.chapter_title('4.5 Open Tabs / Pending Sales')
            self.set_font(PDF_FONT, 'I', 10)
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
            for item, value in zip(parent_adj_items, parent_adj_values):
                parent_adj_rows.append([
                    item['item_name'][:25],
                    item['division'][:18],
                    f"{item['parent_adj_qty']:.1f}",
                    f"£{item['cost_price']:.2f}",
                    f"£{value:.2f}"
                ])
            parent_adj_total = ['TOTAL', '', f"{total_adj_qty:.1f}", '', f"£{total_adj_value:.2f}"]
            self.render_table_block('4.6 Parent Stock Adjustments', parent_adj_headers,
                                    parent_adj_widths, parent_adj_rows,
                                    total_values=parent_adj_total)

        # ------------------------------------------------------------------
        # SECTION 5: VAT Summary
        # ------------------------------------------------------------------
        self._render_vat_summary()

        # ------------------------------------------------------------------
        # SECTION 6: Reconciliation Notes
        # ------------------------------------------------------------------
        self._render_reconciliation_notes()


    # ------------------------------------------------------------------
    # New summary / appendix sections
    # ------------------------------------------------------------------

    def _render_value_bridge(self):
        bridge = self.insights.get('value_bridge') or {}
        rows = bridge.get('rows') or []
        if not rows:
            return
        table_rows = [[_pdf_safe(row['label'], 40),
                       _pdf_signed_money(row['value'])] for row in rows]
        self.set_font(PDF_FONT, 'B', 10)
        self.set_text_color(*PDF_BOTTLE)
        self.cell(0, 6, '2.1 Stock value movement', 0, 1, 'L')
        notes = ['Closing stock is valued at current cost. The difference line '
                 'exposes cost revaluation; it is not a missing transaction.']
        closing = bridge.get('closing') or 0
        difference = bridge.get('difference') or 0
        if self.insights.get('has_baseline'):
            notes.append('This period includes a stocktake baseline, so the '
                         'opening stock is derived from the current count and '
                         'the bridge is indicative.')
        if (closing and abs(difference) > abs(closing) * 0.05
                and not self.insights.get('has_baseline')):
            notes.append('The difference is over 5% of closing stock: the opening '
                         'figure is indicative, especially if the period includes '
                         'a stocktake baseline.')
        self.render_table_block(
            None, ['Movement', 'Value'], [110, 45], table_rows, font_size=7,
            row_height=4, notes=notes)

    def _render_supplier_spend(self):
        suppliers = self.insights.get('supplier_spend') or []
        price_changes = self.insights.get('price_changes') or []
        self.chapter_title('3. Supplier Spend and Price Changes')
        if suppliers:
            rows = [[_pdf_safe(row['supplier'], 30), row['lines'],
                     f"{row['units']:,.1f}", f"£{row['spend_ex_vat']:,.2f}",
                     f"{row['share_pct']:.1f}%"] for row in suppliers]
            self.render_table_block(
                '3.1 Spend by supplier',
                ['Supplier', 'Lines', 'Units', 'Spend ex-VAT', 'Share'],
                [58, 20, 24, 34, 24], rows, font_size=7, row_height=4,
                notes=['Delivery spend only. Supplier returns are reported '
                       'separately in Section 4.'])
        else:
            self.set_font(PDF_FONT, 'I', 9)
            self.cell(0, 6, 'No deliveries recorded in this period.', 0, 1, 'L')

        if price_changes:
            rows = []
            for change in price_changes[:20]:
                when = change.get('date')
                when_text = when.strftime('%d-%m-%Y') if hasattr(when, 'strftime') else ''
                rows.append([
                    _pdf_safe(change.get('item_name', ''), 30),
                    _pdf_safe(change.get('supplier', ''), 20),
                    when_text,
                    f"£{change.get('old_cost', 0):,.2f}",
                    f"£{change.get('new_cost', 0):,.2f}",
                    f"{change.get('change_pct', 0):+.1f}%",
                ])
            self.render_table_block(
                '3.2 Price changes',
                ['Item', 'Supplier', 'Date', 'Old', 'New', 'Change'],
                [52, 34, 24, 22, 22, 20], rows, font_size=7, row_height=4,
                notes=['Only increases of 5% or more are listed. Compare with '
                       'invoice prices before changing sell prices.'])

    def _render_reason_summary(self, title, reasons, basis_note):
        if not reasons:
            return
        rows = [[_pdf_safe(row['reason'], 40), f"{row['quantity']:,.1f}",
                 f"£{row['value']:,.2f}", f"{row['share_pct']:.1f}%"]
                for row in reasons]
        self.render_table_block(
            title, ['Reason', 'Qty', 'Value', 'Share'],
            [70, 30, 32, 24], rows, font_size=7, row_height=4,
            notes=[basis_note])

    def _render_vat_summary(self):
        vat = self.insights.get('vat_position') or {}
        if not vat:
            return
        self.chapter_title('5. VAT Summary (estimate)')
        rows = [
            ['Sales ex-VAT', f"£{vat.get('sales_ex_vat', 0):,.2f}"],
            ['Output VAT at 20%', f"£{vat.get('output_vat', 0):,.2f}"],
            ['Deliveries ex-VAT', f"£{vat.get('deliveries_ex_vat', 0):,.2f}"],
            ['Input VAT at 20%', f"£{vat.get('input_vat', 0):,.2f}"],
            ['Net VAT position', _pdf_signed_money(vat.get('net_vat', 0))],
        ]
        self.render_table_block(
            None, ['VAT item', 'Value'], [95, 45], rows, font_size=7,
            row_height=4,
            notes=['Management estimate only, not a VAT return. Assumes all '
                   'recorded bar sales and deliveries are standard-rated at 20%. '
                   'Input VAT is based on stock deliveries only.'])

    def _render_reconciliation_notes(self):
        notes = self.insights.get('reconciliation_notes') or []
        self.chapter_title('6. Reconciliation Notes')
        if not notes:
            self.set_font(PDF_FONT, 'I', 9)
            self.cell(0, 6, 'Nothing to reconcile for this period.', 0, 1, 'L')
            return
        for note in notes:
            self.set_font(PDF_FONT, 'B', 9)
            self.set_text_color(*PDF_BOTTLE)
            self.set_x(self.l_margin)
            self.multi_cell(self.w - self.l_margin - self.r_margin, 5,
                            _pdf_safe(note.get('title', '')))
            self.set_font(PDF_FONT, '', 8.5)
            self.set_text_color(*PDF_INK)
            self.set_x(self.l_margin)
            self.multi_cell(self.w - self.l_margin - self.r_margin, 4.5,
                            _pdf_safe(note.get('detail', '')))
            self.ln(2)

    def _render_item_financial_breakdown(self, sales_items, has_member_data,
                                         total_member_gp,
                                         overall_member_gp_pct):
        """Render the full item table as Appendix B."""
        if has_member_data:
            headers = ['Item', 'Revenue', 'Cost', 'GP', 'GP%', 'Mem Qty',
                       'Non-Mem', 'Mem GP', 'Mem GP%']
            widths = [50, 17, 17, 17, 11, 15, 15, 17, 11]
        else:
            headers = ['Item', 'Revenue', 'Cost', 'GP', 'GP%']
            widths = [58, 28, 28, 28, 18]

        rows = []
        for item in sales_items:
            if has_member_data:
                rows.append([
                    item['item_name'][:30],
                    f"£{item['total_sales_value']:,.2f}",
                    f"£{item['sales_cost']:,.2f}",
                    f"£{item['sales_gp']:,.2f}",
                    f"{item['sales_gp_pct']:.1f}%",
                    f"{item.get('member_qty', 0):.1f}" if item.get('member_qty', 0) > 0 else '-',
                    f"{item.get('non_member_qty', 0):.1f}" if item.get('non_member_qty', 0) > 0 else '-',
                    f"£{item['member_gp']:,.2f}",
                    f"{item['member_gp_pct']:.1f}%",
                ])
            else:
                rows.append([
                    item['item_name'][:34],
                    f"£{item['total_sales_value']:,.2f}",
                    f"£{item['sales_cost']:,.2f}",
                    f"£{item['sales_gp']:,.2f}",
                    f"{item['sales_gp_pct']:.1f}%",
                ])

        total_revenue = sum_money(i['total_sales_value'] for i in sales_items)
        total_cost = sum_money(i['sales_cost'] for i in sales_items)
        total_gp = sum_money(i['sales_gp'] for i in sales_items)
        total_gp_pct = (total_gp / total_revenue * 100) if total_revenue else 0
        if has_member_data:
            total = [
                'TOTAL',
                f"£{total_revenue:,.2f}",
                f"£{total_cost:,.2f}",
                f"£{total_gp:,.2f}",
                f"{total_gp_pct:.1f}%",
                f"{sum(i.get('member_qty', 0) for i in sales_items):.1f}",
                f"{sum(i.get('non_member_qty', 0) for i in sales_items):.1f}",
                f"£{total_member_gp:,.2f}",
                f"{overall_member_gp_pct:.1f}%",
            ]
        else:
            total = [
                'TOTAL',
                f"£{total_revenue:,.2f}",
                f"£{total_cost:,.2f}",
                f"£{total_gp:,.2f}",
                f"{total_gp_pct:.1f}%",
            ]

        if sales_items:
            self.render_table_block(
                'Appendix B. Item Financial Breakdown'
                + (' (incl. Member GP)' if has_member_data else ''),
                headers, widths, rows, total_values=total, font_size=7)
        else:
            self.chapter_title('Appendix B. Item Financial Breakdown')
            self.set_font(PDF_FONT, 'I', 10)
            self.cell(0, 10, 'No sales recorded in this period.', 0, 1, 'L')

    def _render_division_stock_movement(self, report_data):
        """Render the directors' division-level stock movement summary."""
        from reports import build_division_stock_movement
        movement = build_division_stock_movement(
            report_data,
            target_revaluation=(self.insights.get('value_bridge') or {}).get('difference'))
        rows_data = movement.get('rows') or []
        if not rows_data:
            return
        headers = ['Division', 'Opening', 'Deliveries', 'Cost of Sales',
                   'Wastage & Comp', 'Returns', 'Closing', 'Revaluation']
        widths = [30, 20, 20, 20, 22, 16, 20, 20]
        rows = []
        for row in rows_data:
            rows.append([
                _pdf_safe(row['division'], 20),
                f"£{row['opening']:,.2f}",
                f"£{row['deliveries']:,.2f}",
                f"£{row['cogs']:,.2f}",
                f"£{row['shrinkage']:,.2f}",
                f"£{row['returns']:,.2f}",
                f"£{row['closing']:,.2f}",
                _pdf_signed_money(row['revaluation']),
            ])
        total = movement.get('total') or {}
        total_row = [
            'TOTAL',
            f"£{total.get('opening', 0):,.2f}",
            f"£{total.get('deliveries', 0):,.2f}",
            f"£{total.get('cogs', 0):,.2f}",
            f"£{total.get('shrinkage', 0):,.2f}",
            f"£{total.get('returns', 0):,.2f}",
            f"£{total.get('closing', 0):,.2f}",
            _pdf_signed_money(total.get('revaluation', 0)),
        ]
        self.render_table_block(
            '2.2 Stock movement by division', headers, widths, rows,
            total_values=total_row, font_size=7, row_height=4,
            notes=['Opening, deliveries, wastage and closing are valued at '
                   'current cost; cost of sales uses transaction cost. '
                   'Revaluation = Closing - (Opening + Deliveries - Cost of '
                   'Sales - Wastage - Returns); it reconciles to the value '
                   'bridge difference.'])

    def _render_stock_exceptions(self, stocktake_data, report_data):
        """Render the largest stocktake variances and negative-stock items."""
        from reports import build_stock_exceptions
        exceptions = build_stock_exceptions(stocktake_data, report_data)
        variances = exceptions.get('variances') or []
        negative = exceptions.get('negative') or []

        if self._available_page_space() < 60:
            self.add_page()
        self.chapter_title('2.3 Exceptions')
        if variances:
            headers = ['Item', 'Division', 'Expected', 'Counted', 'Variance', 'Value']
            widths = [50, 30, 22, 22, 22, 24]
            rows = []
            for row in variances:
                rows.append([
                    _pdf_safe(row['item_name'], 28),
                    _pdf_safe(row['division'], 18),
                    f"{row['expected']:.1f}",
                    f"{row['counted']:.1f}",
                    f"{row['variance']:+.1f}",
                    _pdf_signed_money(row['variance_value']),
                ])
            self.render_table_block(
                '2.3.1 Largest stocktake variances', headers, widths, rows,
                font_size=7, row_height=4,
                notes=['Top 10 by absolute variance value.'])
        else:
            self.set_font(PDF_FONT, 'I', 9)
            self.cell(0, 6, 'No stocktake variance recorded for this period.',
                      0, 1, 'L')
            self.ln(2)

        if negative:
            headers = ['Item', 'Division', 'Current Stock', 'Value']
            widths = [62, 40, 30, 28]
            rows = []
            for row in negative:
                rows.append([
                    _pdf_safe(row['item_name'], 30),
                    _pdf_safe(row['division'], 20),
                    f"{row['current_stock']:.1f}",
                    _pdf_signed_money(row['stock_value']),
                ])
            self.render_table_block(
                '2.3.2 Negative stock', headers, widths, rows,
                font_size=7, row_height=4,
                notes=['Negative stock usually means sales or wastage were '
                       'recorded without a matching delivery.'])

    def _render_full_stock_movement(self, variance_items):
        """Render the full item-level quantity movement as Appendix C."""
        headers = ['Item', 'Opening', '+Del.', '-Sold', '-Adj', '-Wast',
                   '-Comp', 'Closing', 'Exp.Con', 'Act.Con', 'Var%']
        widths = [34, 16, 14, 14, 14, 14, 14, 16, 16, 16, 14]
        rows = []
        totals = {'opening': 0, 'delivery': 0, 'sold': 0, 'adj': 0,
                  'wast': 0, 'comp': 0, 'closing': 0, 'exp_con': 0,
                  'act_con': 0}
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
            if item['consumption_variance_pct'] is not None:
                var_pct = (f"{item['consumption_variance_pct']:+.1f}%"
                           if abs(item['consumption_variance_pct']) >= 0.1
                           else '-')
            else:
                var_pct = '-'
            rows.append([
                item['item_name'][:20],
                f"{item['opening_stock']:.1f}",
                f"{item['delivery_qty']:.1f}" if item['delivery_qty'] > 0 else '-',
                f"{item['total_sales_qty']:.1f}" if item['total_sales_qty'] > 0 else '-',
                f"{item['parent_adj_qty']:.1f}" if item['parent_adj_qty'] > 0 else '-',
                f"{item['wastage_qty']:.1f}" if item['wastage_qty'] > 0 else '-',
                f"{item['complimentary_qty']:.1f}" if item['complimentary_qty'] > 0 else '-',
                f"{item['current_stock']:.1f}",
                f"{item['expected_consumption']:.1f}",
                f"{item['actual_consumption']:.1f}" if item['actual_consumption'] is not None else '-',
                var_pct,
            ])
        total_var_pct = (
            (totals['exp_con'] - totals['act_con']) / totals['act_con'] * 100
            if totals['act_con'] > 0 else 0)
        total = [
            'TOTAL',
            f"{totals['opening']:.1f}",
            f"{totals['delivery']:.1f}" if totals['delivery'] > 0 else '-',
            f"{totals['sold']:.1f}" if totals['sold'] > 0 else '-',
            f"{totals['adj']:.1f}" if totals['adj'] > 0 else '-',
            f"{totals['wast']:.1f}" if totals['wast'] > 0 else '-',
            f"{totals['comp']:.1f}" if totals['comp'] > 0 else '-',
            f"{totals['closing']:.1f}",
            f"{totals['exp_con']:.1f}",
            f"{totals['act_con']:.1f}",
            f"{total_var_pct:+.1f}%" if abs(total_var_pct) >= 0.1 else '-',
        ]
        if variance_items:
            self.render_table_block(
                'Appendix C. Full quantity movement & variance', headers, widths, rows,
                total_values=total, font_size=7, row_height=4,
                notes=['Units: draught/postmix = pints, spirits = measures '
                       '(35ml), bottles/cans = units. Adj = parent stock '
                       'deductions from child sales.',
                       'Exp.Con = Expected consumption '
                       '(Sales+Wastage+Comp+Adj). Act.Con = Actual consumption '
                       '(Opening+Deliveries-Closing). Var% = difference.'])
        else:
            self.set_font(PDF_FONT, 'I', 10)
            self.cell(0, 10, 'No stock consumption data available for variance '
                      'calculation.', 0, 1, 'L')

    def _render_draught_yield(self, draught_items):
        """Render the operational draught-yield table as Appendix C."""
        draught_items = [i for i in draught_items
                         if i['item_id'] in DRAUGHT_YIELD_ITEMS
                         and not i.get('is_delisted', False)]
        if not draught_items:
            return
        headers = ['Item', 'Sales', 'Adj.', 'Wast', 'Comp', 'Open Tabs',
                   'Consumed', 'Closing', 'Yield%']
        widths = [38, 16, 14, 14, 14, 16, 18, 18, 16]
        rows = []
        for item in draught_items:
            yield_pct = item['yield_pct']
            rows.append([
                item['item_name'][:18],
                f"{item['total_sales_qty']:.1f}",
                f"{item['parent_adj_qty']:.1f}" if item.get('parent_adj_qty', 0) > 0 else '-',
                f"{item['wastage_qty']:.1f}" if item['wastage_qty'] > 0 else '-',
                f"{item['complimentary_qty']:.1f}" if item['complimentary_qty'] > 0 else '-',
                f"{item['open_tab_qty']:.1f}" if item['open_tab_qty'] > 0 else '-',
                f"{item['expected_consumption']:.1f}",
                f"{item['current_stock']:.1f}",
                f"{yield_pct:.1f}%" if yield_pct > 0 else 'N/A',
            ])
        self.render_table_block(
            'C.2 Draught Yield (pints)', headers, widths, rows,
            font_size=7, row_height=4,
            notes=['All quantities in pints. Yield% = Sales / Total '
                   'Consumption. Adj = pints deducted via half '
                   'pints/shandies.'])

    def generate_stock_count_sheet(self, inventory_data):
        """Generate a printable stock count sheet."""
        self.add_page()
        self.chapter_title('Stock Count Sheet')

        self.set_font(PDF_FONT, '', 10)
        self.cell(0, 8, f'Total items: {len(inventory_data)}', 0, 1, 'L')
        self.ln(2)

        headers = ['Item', 'Category', 'Expected', 'Counted', 'Variance', 'Notes']
        widths = [50, 28, 22, 22, 22, 46]

        self.set_font(PDF_FONT, 'B', 9)
        self.set_fill_color(*PDF_RAIL)
        self.set_text_color(*PDF_INK)
        for header, width in zip(headers, widths):
            self.cell(width, 8, header, 1, 0, 'C', True)
        self.ln()

        # Sort by category then item name
        inventory_data = sorted(inventory_data, key=lambda x: (x.get('category', ''), x.get('item_name', '')))
        current_category = None

        for index, item in enumerate(inventory_data):
            item_id = item.get('item_id', '')
            # Delisted lines hold no stock and are never counted.
            if is_delisted(item_id):
                continue

            category = item.get('category', '')
            if category != current_category:
                current_category = category
                self.set_font(PDF_FONT, 'B', 9)
                self.set_fill_color(*PDF_RAIL)
                self.set_text_color(*PDF_INK)
                self.cell(sum(widths), 8, current_category, 1, 1, 'L', True)

            item_name = item.get('item_name', '')

            self.set_font(PDF_FONT, '', 9)
            self.set_fill_color(*(PDF_ZEBRA if index % 2 else PDF_PAPER))
            self.set_text_color(*PDF_INK)
            self.cell(widths[0], 8, item_name[:35], 1, 0, 'L', True)
            self.cell(widths[1], 8, item.get('category', '')[:20], 1, 0, 'L', True)

            # Convert to natural units (barrels, bottles, boxes, cartons) where applicable.
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
        self.set_font(PDF_FONT, 'I', 8)
        self.cell(0, 5, 'Expected = transaction-based expected stock. Counted = write your physical count. Variance = Counted - Expected.', 0, 1, 'L')

class PriceHistoryPDF(FPDF):
    """PDF generator for price history reports."""

    # Date range the report was run for; printed under the title on every page.
    report_period = None

    def header(self):
        self.set_font(PDF_DISPLAY, 'B', 16)
        self.set_text_color(*PDF_INK)
        self.cell(0, 10, _pdf_club_title('Price History Report'), 0, 1, 'C')
        _draw_pdf_logo(self)
        self.set_font(PDF_FONT, '', 10)
        self.set_text_color(*PDF_MUTED)
        self.cell(0, 5, f'Generated: {datetime.now().strftime(f"{DATE_FORMAT_DISPLAY} at %H:%M")}', 0, 1, 'C')
        if self.report_period:
            self.set_font(PDF_FONT, 'B', 10)
            self.set_text_color(*PDF_INK)
            self.cell(0, 5, f'Report period: {self.report_period}', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font(PDF_FONT, 'I', 8)
        self.set_text_color(*PDF_MUTED)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    @staticmethod
    def generate(report_data, downloads_dir=None, report_period=None):
        """Generate and save a price history PDF report.

        Args:
            report_data: List of dicts with keys:
                item_name, timestamp, supplier, cost_price, prev_price, change
            downloads_dir: Directory to save the PDF. Defaults to ~/Downloads.
            report_period: Date-range label printed in the page header.
        """
        if downloads_dir is None:
            downloads_dir = app_config.get_downloads_dir()

        pdf = PriceHistoryPDF()
        pdf.report_period = report_period
        pdf.add_page()
        pdf.set_font(PDF_FONT, '', 9)

        pdf.set_fill_color(*PDF_RAIL)
        pdf.set_text_color(*PDF_INK)
        pdf.set_font(PDF_FONT, 'B', 9)
        headers = ['Item', 'Date', 'Supplier', 'Cost Price', 'Previous', 'Change']
        widths = [50, 30, 30, 25, 25, 25]
        for h, w in zip(headers, widths):
            pdf.cell(w, 8, h, 1, 0, 'C', True)
        pdf.ln()

        pdf.set_font(PDF_FONT, '', 9)
        pdf.set_text_color(*PDF_INK)
        for index, row in enumerate(report_data):
            pdf.set_fill_color(*(PDF_ZEBRA if index % 2 else PDF_PAPER))
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
                pdf.cell(w, 7, v, 1, 0, 'C', True)
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
        self.set_font(PDF_DISPLAY, 'B', 16)
        self.set_text_color(*PDF_INK)
        self.cell(0, 10, _pdf_club_title('Stock Order Sheet'), 0, 1, 'C')
        _draw_pdf_logo(self)
        self.set_font(PDF_FONT, '', 10)
        self.set_text_color(*PDF_MUTED)
        self.cell(0, 5, f'Generated: {datetime.now().strftime(f"{DATE_FORMAT_DISPLAY} at %H:%M")}', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        """Add footer to each page."""
        self.set_y(-15)
        self.set_font(PDF_FONT, 'I', 8)
        self.set_text_color(*PDF_MUTED)
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
            downloads_dir = app_config.get_downloads_dir()

        pdf = StockOrderSheetPDF()
        pdf.add_page()
        pdf.set_font(PDF_FONT, '', 9)

        if not report_data:
            pdf.set_font(PDF_FONT, 'I', 12)
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
                    pdf.set_font(PDF_FONT, 'B', 13)
                    pdf.set_text_color(*PDF_BOTTLE)
                    pdf.cell(0, 10, _pdf_safe(supplier), 0, 1, 'L')
                    pdf.ln(1)
                    last_supplier = supplier

                # Category subheading (skip if category is blank)
                if category:
                    pdf.set_font(PDF_FONT, 'B', 10)
                    pdf.set_text_color(*PDF_INK)
                    pdf.set_fill_color(*PDF_RAIL)
                    pdf.cell(sum(widths), 7, _pdf_safe(category), 1, 1, 'L', True)

                # Table header
                pdf.set_font(PDF_FONT, 'B', 8)
                pdf.set_fill_color(*PDF_RAIL)
                pdf.set_text_color(*PDF_INK)
                for header, width in zip(headers, widths):
                    pdf.cell(width, 6, _pdf_safe(header), 1, 0, 'C', True)
                pdf.ln()

                # Rows
                pdf.set_font(PDF_FONT, '', 8)
                pdf.set_text_color(*PDF_INK)
                for index, item in enumerate(items):
                    pdf.set_fill_color(*(PDF_ZEBRA if index % 2 else PDF_PAPER))
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

            pdf.set_font(PDF_FONT, 'I', 8)
            pdf.set_text_color(*PDF_MUTED)
            pdf.cell(0, 5, 'Order sheet. Current = blank for manual stock count. Reorder = recorded reorder level.', 0, 1, 'L')

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"Stock_Order_Sheet_{timestamp}.pdf"
        filepath = os.path.join(downloads_dir, filename)
        pdf.output(filepath)
        return filepath
