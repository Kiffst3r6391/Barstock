#!/usr/bin/env python3
"""Guardrails for the Ledger theme.

The palette is the app's only look, so these checks keep two classes of
regression out: text that cannot be read on the paper it sits on, and a
stray dark-theme literal or a Tk font name reaching a PDF.
"""

import ast
import re
from pathlib import Path

import pytest

import pdf_generator
import ui_theme

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_TOKENS = (
    "THEME_BG",
    "THEME_SIDEBAR",
    "THEME_CARD",
    "THEME_PANEL",
    "THEME_BORDER",
    "THEME_TEXT",
    "THEME_TEXT_MUTED",
    "THEME_ACCENT",
    "THEME_ACCENT_HOVER",
    "THEME_ACCENT_INK",
    "THEME_SUCCESS",
    "THEME_WARNING",
    "THEME_DANGER",
    "THEME_DANGER_HOVER",
    "TBL_ROW_ALT",
    "TBL_ROW_WARN",
    "TBL_ROW_DANGER",
)

TEXT_PAIRS = (
    ("THEME_TEXT", "THEME_BG"),
    ("THEME_TEXT", "THEME_CARD"),
    ("THEME_TEXT", "THEME_SIDEBAR"),
    ("THEME_TEXT", "THEME_PANEL"),
    ("THEME_TEXT_MUTED", "THEME_BG"),
    ("THEME_TEXT_MUTED", "THEME_CARD"),
    ("THEME_TEXT_MUTED", "THEME_SIDEBAR"),
    ("THEME_ACCENT_INK", "THEME_ACCENT"),
    ("THEME_ACCENT_INK", "THEME_ACCENT_HOVER"),
    ("THEME_ACCENT_INK", "THEME_DANGER"),
    ("THEME_ACCENT_INK", "THEME_DANGER_HOVER"),
    ("THEME_ACCENT_INK", "THEME_SUCCESS"),
    ("THEME_DANGER", "THEME_BG"),
    ("THEME_DANGER", "THEME_CARD"),
    ("THEME_WARNING", "THEME_BG"),
    ("THEME_WARNING", "THEME_CARD"),
    ("THEME_SUCCESS", "THEME_BG"),
    ("THEME_SUCCESS", "THEME_CARD"),
    ("THEME_TEXT", "TBL_ROW_ALT"),
    ("THEME_TEXT", "TBL_ROW_WARN"),
    ("THEME_TEXT", "TBL_ROW_DANGER"),
)

DARK_LITERALS = re.compile(
    r"#(?:0f1419|1a2028|232b36|2c2c2c|3d1f1f|382a05|0d0d0d)\b",
    re.IGNORECASE,
)

CORE_PDF_FONTS = {"helvetica", "times", "courier"}


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

def _luminance(hex_colour):
    value = hex_colour.lstrip("#")
    channels = [int(value[i:i + 2], 16) / 255 for i in (0, 2, 4)]

    def linearise(channel):
        return (channel / 12.92 if channel <= 0.03928
                else ((channel + 0.055) / 1.055) ** 2.4)

    red, green, blue = (linearise(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(foreground, background):
    lighter, darker = sorted((_luminance(foreground), _luminance(background)),
                             reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize("token", REQUIRED_TOKENS)
def test_palette_token_is_a_hex_colour(token):
    value = getattr(ui_theme, token)
    assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), f"{token}={value!r}"


@pytest.mark.parametrize("foreground,background", TEXT_PAIRS)
def test_palette_text_contrast_is_at_least_4_5(foreground, background):
    ratio = contrast(getattr(ui_theme, foreground),
                     getattr(ui_theme, background))
    assert ratio >= 4.5, f"{foreground} on {background} is only {ratio:.2f}:1"


def test_chart_colours_are_visible_on_paper():
    """Non-text graphics need 3:1 against the surface they sit on."""
    for colour in ui_theme.CHART_COLORS:
        ratio = contrast(colour, ui_theme.THEME_BG)
        assert ratio >= 3.0, f"chart colour {colour} is only {ratio:.2f}:1"


# ---------------------------------------------------------------------------
# Source hygiene
# ---------------------------------------------------------------------------

def _source_files():
    return [ROOT / "BarStockApp.py", *sorted((ROOT / "screens").glob("*.py"))]


def _normaliser_lines(path):
    """Line numbers inside ``_apply_legacy_theme``.

    That method exists precisely to map old dark literals onto Ledger
    tokens, so its lookup tables are allowed to name them.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.FunctionDef)
                and node.name == "_apply_legacy_theme"):
            return set(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return set()


def test_no_dark_theme_literals_remain():
    offenders = []
    for path in _source_files():
        allowed = _normaliser_lines(path)
        for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            if number in allowed:
                continue
            if DARK_LITERALS.search(line):
                offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, "Dark theme literals remain:\n" + "\n".join(offenders)


# ---------------------------------------------------------------------------
# PDFs
# ---------------------------------------------------------------------------

def _pdf_modules():
    return [ROOT / "pdf_generator.py", ROOT / "screens" / "reports.py"]


def _fpdf_class_lines(path):
    """Lines occupied by classes that inherit from FPDF."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    lines = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {base.id for base in node.bases if isinstance(base, ast.Name)}
        if "FPDF" in bases:
            lines |= set(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return lines


def test_pdf_modules_never_receive_a_tk_font():
    """Screens may use Tk fonts; code inside an FPDF subclass may not."""
    offenders = []
    for path in _pdf_modules():
        pdf_lines = _fpdf_class_lines(path)
        for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            if path.name == "pdf_generator.py" or number in pdf_lines:
                if "THEME_FONT" in line or "THEME_DISPLAY_FONT" in line:
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
    assert not offenders, ("Tk font names cannot be used with FPDF's core "
                           "fonts:\n" + "\n".join(offenders))


def test_every_pdf_set_font_uses_a_core_family():
    constants = {
        "PDF_FONT": pdf_generator.PDF_FONT,
        "PDF_DISPLAY": pdf_generator.PDF_DISPLAY,
    }
    offenders = []

    for path in _pdf_modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "set_font"
                    and node.args):
                continue
            family = node.args[0]
            if isinstance(family, ast.Constant) and isinstance(family.value, str):
                name = family.value
            elif isinstance(family, ast.Name):
                name = constants.get(family.id)
                if name is None:
                    offenders.append(
                        f"{path.name}:{node.lineno}: unknown font {family.id}")
                    continue
            else:
                offenders.append(
                    f"{path.name}:{node.lineno}: computed font argument")
                continue
            if name.lower() not in CORE_PDF_FONTS:
                offenders.append(
                    f"{path.name}:{node.lineno}: {name!r} is not a core font")

    assert not offenders, "\n".join(offenders)


def test_pdf_palette_is_defined():
    for token in ("PDF_INK", "PDF_MUTED", "PDF_BOTTLE", "PDF_COPPER",
                  "PDF_RULE", "PDF_RAIL", "PDF_FONT", "PDF_DISPLAY"):
        assert hasattr(pdf_generator, token), token
    assert pdf_generator.PDF_FONT.lower() in CORE_PDF_FONTS
    assert pdf_generator.PDF_DISPLAY.lower() in CORE_PDF_FONTS


# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------

def test_font_helpers_read_module_state():
    assert ui_theme.display_font(20) == (ui_theme.THEME_DISPLAY_FONT, 20)
    assert ui_theme.display_font(20, "bold") == (
        ui_theme.THEME_DISPLAY_FONT, 20, "bold")
    assert ui_theme.mono_font(9) == (ui_theme.THEME_MONO_FONT, 9)
