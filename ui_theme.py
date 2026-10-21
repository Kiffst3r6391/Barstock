#!/usr/bin/env python3
"""Dashboard theme tokens and font resolution.

``THEME_FONT`` is deliberately module state: Tk needs one real font family,
and the family installed differs between macOS, Windows and Linux.  It is
resolved once at start-up by ``BarStockApp.setup_theme`` and read by every
screen module at draw time, so moving a screen into its own module cannot
leave it stuck on the fallback face.
"""

THEME_BG = '#0f1419'
THEME_SIDEBAR = '#1a2028'
THEME_CARD = '#232b36'
THEME_PANEL = '#232b36'
THEME_BORDER = '#2f3844'
THEME_TEXT = '#f5f2ec'
THEME_TEXT_MUTED = '#aab4bf'
THEME_ACCENT = '#c89f5e'
THEME_ACCENT_HOVER = '#e8b86d'
THEME_SUCCESS = '#5a9e6e'
THEME_WARNING = '#e0a53c'
THEME_DANGER = '#c95d5d'

# A CSS font stack is not a font name: Tk looks for a family called
# "-apple-system, ...", fails, and silently falls back to whatever the
# platform picks.  Resolve one installed family instead.
THEME_FONT_STACK = ('SF Pro Text', 'Helvetica Neue', 'Segoe UI', 'Inter',
                    'DejaVu Sans', 'Arial')
THEME_FONT = 'Helvetica'

# Table row tints.  These are deliberately dark: the Treeview foreground is
# near-white, so light tag backgrounds made the text unreadable.
TBL_ROW_ALT = '#1f2731'
TBL_ROW_WARN = '#3a3020'
TBL_ROW_DANGER = '#3d1f1f'


def resolve_font(root):
    """Return the first font family in the stack that Tk can actually use."""
    try:
        import tkinter.font as tkfont
        available = set(tkfont.families(root))
        return next((family for family in THEME_FONT_STACK if family in available),
                    'Helvetica')
    except Exception:
        return 'Helvetica'
