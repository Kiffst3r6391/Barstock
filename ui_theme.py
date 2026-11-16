#!/usr/bin/env python3
"""Ledger theme tokens and font resolution.

The app has one look: chalk paper, ink text, bottle-green actions and copper
for anything needing attention.  Token *names* are unchanged from the old
dark theme so the hundreds of references across the screens keep working;
only their values are new.

``THEME_FONT``, ``THEME_DISPLAY_FONT`` and ``THEME_MONO_FONT`` are module
state: Tk needs one real family and the installed faces differ between macOS,
Windows and Linux.  They are resolved once at start-up by
``BarStockApp.setup_theme`` and read by every screen module at draw time, so
moving a screen into its own module cannot leave it stuck on a fallback face.
"""

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

THEME_BG = '#F7F6F0'          # chalk paper
THEME_SIDEBAR = '#F2F1E9'     # rail, status bar, table headings
THEME_CARD = '#FCFBF6'        # fields and raised surfaces
THEME_PANEL = '#F7F6F0'       # panels carry no fill, only rules
THEME_BORDER = '#D7D9CD'      # every 1px rule
THEME_TEXT = '#1B221E'        # ink
THEME_TEXT_MUTED = '#5F685F'  # labels and footnotes (5.3:1 on chalk)
THEME_ACCENT = '#16443B'      # bottle green: actions, active nav, bars
THEME_ACCENT_HOVER = '#1D5A4D'
THEME_ACCENT_INK = '#F6F4EC'  # text on bottle
THEME_SUCCESS = '#2F6B4F'
THEME_WARNING = '#8E5A2B'     # copper: attention and low stock
THEME_DANGER = '#A33A2A'
THEME_DANGER_HOVER = '#8C3024'

# Table row tints stay pale: the Treeview foreground is ink, so the tint
# carries the warning without fighting the text.
TBL_ROW_ALT = '#F1F0E7'
TBL_ROW_WARN = '#F3E8DA'
TBL_ROW_DANGER = '#F6DFD9'

# Charts use the same three inks plus quieter tints for extra series.
CHART_COLORS = ('#16443B', '#8E5A2B', '#5B7F72', '#8A6A3E', '#A33A2A',
                '#7A8B7F')

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

# A CSS font stack is not a font name: Tk looks for a family called
# "-apple-system, ...", fails, and silently falls back.  Resolve one
# installed family per role instead.
THEME_FONT_STACK = ('SF Pro Text', 'Helvetica Neue', 'Segoe UI', 'Inter',
                    'DejaVu Sans', 'Arial')
THEME_DISPLAY_STACK = ('Georgia', 'Times New Roman', 'DejaVu Serif', 'Times')
THEME_MONO_STACK = ('Menlo', 'Consolas', 'DejaVu Sans Mono', 'Courier New',
                    'Courier')

THEME_FONT = 'Helvetica'
THEME_DISPLAY_FONT = 'Georgia'
THEME_MONO_FONT = 'Menlo'


def _resolve(root, stack, fallback):
    """Return the first font family in ``stack`` that Tk can actually use."""
    try:
        import tkinter.font as tkfont
        available = set(tkfont.families(root))
        return next((family for family in stack if family in available),
                    fallback)
    except Exception:
        return fallback


def resolve_font(root):
    """Resolve the body sans family."""
    return _resolve(root, THEME_FONT_STACK, 'Arial')


def resolve_display_font(root):
    """Resolve the serif display/figures family."""
    return _resolve(root, THEME_DISPLAY_STACK, 'Times New Roman')


def resolve_mono_font(root):
    """Resolve the monospaced label/caption family."""
    return _resolve(root, THEME_MONO_STACK, 'Courier New')


def _font_tuple(family, size, weight):
    if weight and weight != 'normal':
        return (family, size, weight)
    return (family, size)


def display_font(size, weight='normal'):
    """Serif font tuple for headings and headline figures."""
    return _font_tuple(THEME_DISPLAY_FONT, size, weight)


def mono_font(size, weight='normal'):
    """Monospaced font tuple for dates, labels and captions."""
    return _font_tuple(THEME_MONO_FONT, size, weight)
