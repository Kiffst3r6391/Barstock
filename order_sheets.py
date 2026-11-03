"""Recreate the paper order sheets (Booker and Tennent's) as print-ready PDFs."""
import os

from fpdf import FPDF

OUT_DIR = os.path.expanduser('~/Downloads')
TODAY = '23 October 2026'

# --- Booker -----------------------------------------------------------------
BOOKER_LEFT = [
    ('Bottle Beer', [
        'Moretti bottle', 'Moretti zero', 'Budweiser', 'Corona', 'Estrella Damm', "Inch's",
        'Magners', 'Old Mout', 'Kopparberg S/L', 'Kopparberg MF',
        'Kopparberg 0%', 'Peroni',
    ]),
    ('Minerals', [
        'Apple juice', 'Orange juice', 'Cranberry juice', 'Pineapple juice',
        'J2O O&P', 'J2O A&M', 'Fever tree', 'Fever tree SL', 'Lime cordial',
        'Blackcurrant cordial',
    ]),
    ('Whisky', [
        'Bowmore', 'Highland park', 'Jura', 'Old Pultney', 'Glenmorangie',
        'Glen Scotia',
    ]),
    ('Spirits', [
        'Bacardi', 'Capt. Morgans', 'Kraken', 'Havana 7', 'Bombay saphire',
        'Brockmans', 'Gordons', 'Gordons pink', 'Edinburgh gin', 'Tanquary',
        'Tanquary Sevilla', 'Sambuca', 'Tequila', 'Cointreau', 'Drambuie',
        'Jack Daniels', 'Jagermeister', 'Pimms', 'Sourz', 'Whitley Neill',
    ]),
]

BOOKER_RIGHT = [
    ('Soft', [
        'Coke', 'Coke Zero', 'Diet Coke', 'Irn bru', 'Diet irn bru',
        'Fanta lemon', 'Sprite', 'Ginger beer', 'Tango', 'Red bull',
    ]),
    ('Bag In Box', ['Coke', 'Diet Coke', 'Lemonade']),
    ('Snacks', ['Pringles', 'Walkers', 'Nuts']),
    ('Misc', ['Prosecco', 'Prosecco single serve', 'Lichtfelds chocolates']),
    ('Spirits', [
        'Baileys', 'Southern comfort', 'Glayva', 'Kahlua', 'malibu',
        'Disaronno', 'Smirnoff', 'Martial', 'Port', 'Aperol', 'Archers',
        'Dead mans fingers', 'Tequila rose', 'Angostura',
    ]),
]

# --- Tennent's / Abergas ----------------------------------------------------
TENNENTS_ROWS = [
    ('section', "KEGS"),
    ('item', ('Tennents', 'Joker IPA')),
    ('item', ('Caledonian Best', 'Guinness')),
    ('item', ('Innis & Gunn', 'Orchard Pig')),
    ('item', ('Poretti', '')),
    ('section', "CANS"),
    ('item', ('Guinness Surger', 'Guinness 0% Micro')),
    ('section', "WINE"),
    ('item', ('O&G Pinto grigio', 'Wicked lady pinto Grigio')),
    ('item', ('O&G sauvignon blanc', 'Cullinan view sauvignon blanc')),
    ('item', ('O&G rose', 'Whispering hills rose')),
    ('item', ('O&G merlot', 'Zarapito malbec')),
    ('item', ('O&G shiraz', 'Short mile bay merlot')),
    ('item', ('', 'Single Serve Wine')),
    ('section', "ABERGAS - (01355 234 777)"),
    ('item', ('Count Empty', '')),
    ('item', ('C02', '70/30')),
]

ITEM_W = 63
COUNT_W = 12
ORDER_W = 12
TOTAL_W = (ITEM_W + COUNT_W + ORDER_W) * 2


def sequence_rows(sections):
    rows = []
    for name, items in sections:
        rows.append(('header', name))
        rows.extend(('item', item) for item in items)
    return rows


class OrderSheet(FPDF):
    def __init__(self, heading, subtitle, row_h=4.7):
        super().__init__(orientation='P', unit='mm', format='A4')
        self.heading = heading
        self.subtitle = subtitle
        self.row_h = row_h
        self.set_auto_page_break(False)
        self.set_margins(10, 10, 10)

    def header_block(self):
        self.add_page()
        self.set_font('Helvetica', 'B', 11)
        self.cell(0, 6, self.heading, align='C', new_x='LMARGIN', new_y='NEXT')
        self.set_font('Helvetica', '', 7.5)
        self.cell(0, 4, self.subtitle, align='C', new_x='LMARGIN', new_y='NEXT')
        self.ln(2)

    def grid_row(self, left, right, left_bold=False, right_bold=False,
                 count_labels=False):
        x = (210 - TOTAL_W) / 2
        self.set_x(x)
        self.set_font('Helvetica', 'B' if left_bold else '', 8)
        self.cell(ITEM_W, self.row_h, left, border=1)
        self.set_font('Helvetica', 'B' if count_labels else '', 7.5)
        self.cell(COUNT_W, self.row_h, 'Count' if count_labels else '',
                  border=1, align='C')
        self.cell(ORDER_W, self.row_h, 'Order' if count_labels else '',
                  border=1, align='C')
        self.set_font('Helvetica', 'B' if right_bold else '', 8)
        self.cell(ITEM_W, self.row_h, right, border=1)
        self.set_font('Helvetica', 'B' if count_labels else '', 7.5)
        self.cell(COUNT_W, self.row_h, 'Count' if count_labels else '',
                  border=1, align='C')
        self.cell(ORDER_W, self.row_h, 'Order' if count_labels else '',
                  border=1, align='C')
        self.ln(self.row_h)

    def booker(self):
        self.header_block()
        left = sequence_rows(BOOKER_LEFT)
        right = sequence_rows(BOOKER_RIGHT)
        total = max(len(left), len(right))
        for i in range(total):
            l_kind, l_val = left[i] if i < len(left) else ('item', '')
            r_kind, r_val = right[i] if i < len(right) else ('item', '')
            # The first row carries the section names and the Count/Order
            # labels, exactly like the paper sheet.
            self.grid_row(l_val, r_val,
                          left_bold=(l_kind == 'header'),
                          right_bold=(r_kind == 'header'),
                          count_labels=(i == 0))

    def tennents(self):
        self.header_block()
        for index, (kind, value) in enumerate(TENNENTS_ROWS):
            if kind == 'section':
                self.grid_row(value, '', left_bold=True,
                              count_labels=(index == 0))
            else:
                left, right = value
                self.grid_row(left, right)


def main():
    booker = OrderSheet(
        'BOOKER - ACCOUNT 741938670',
        f'Prestonfield Golf Club · updated {TODAY}',
        row_h=4.7)
    booker.booker()
    path_b = os.path.join(OUT_DIR, 'Bar_Order_Sheet_Booker.pdf')
    booker.output(path_b)

    tennents = OrderSheet(
        "TENNENT'S - ACCOUNT 17595333 (0141 202 7290)",
        f'Prestonfield Golf Club · updated {TODAY}',
        row_h=8.0)
    tennents.tennents()
    path_t = os.path.join(OUT_DIR, 'Bar_Order_Sheet_Tennents.pdf')
    tennents.output(path_t)

    print(path_b)
    print(path_t)


if __name__ == '__main__':
    main()
