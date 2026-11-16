#!/usr/bin/env python3
"""UI smoke tests.

Two cheap checks that would have caught the broken Reports back button and
the missing reports before release:

* every ``self.<name>(...)`` call in the app class resolves to a method;
* every top-level screen builds and tears down against a withdrawn root.
"""

import ast
import sqlite3
import tkinter as tk
from pathlib import Path

import pandas as pd

import pytest

import data_manager as dm

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Static check: no calls to undefined methods
# ---------------------------------------------------------------------------

def test_every_self_method_call_is_defined():
    sources = [ROOT / "BarStockApp.py"]
    sources += sorted((ROOT / "screens").glob("*.py"))

    app_classes = []
    mixin_classes = []
    for path in sources:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                if node.name == "BarStockManagementSystem":
                    app_classes.append(node)
                elif node.name.endswith("Mixin"):
                    mixin_classes.append(node)

    assert app_classes, "BarStockManagementSystem not found"

    # Methods may live in the app class or in any mixin it inherits from.
    defined = set()
    for cls in app_classes + mixin_classes:
        defined |= {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
        # Attributes assigned at class level are callables too (rare here).
        defined |= {
            target.id
            for node in cls.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
        }

    undefined = {}

    def walk_without_nested_classes(node):
        """Walk a method, skipping classes defined inside it (e.g. PDF subclasses)."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                continue
            yield child
            yield from walk_without_nested_classes(child)

    for cls in app_classes + mixin_classes:
        called = set()
        for method in (n for n in cls.body if isinstance(n, ast.FunctionDef)):
            for node in walk_without_nested_classes(method):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "self"
                ):
                    called.add(node.func.attr)
        missing = called - defined
        if missing:
            undefined[cls.name] = sorted(missing)

    assert not undefined, f"Calls to undefined self methods: {undefined}"


# ---------------------------------------------------------------------------
# Live Tk smoke test per screen
# ---------------------------------------------------------------------------

@pytest.fixture
def app(tmp_path, monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk is not available in this environment")
    root.withdraw()

    db = tmp_path / "barstock.db"
    monkeypatch.setattr(dm, "DB_PATH", str(db))
    monkeypatch.setattr(dm, "DATA_DIR", str(tmp_path))
    # INVENTORY_FILE / LOG_FILE are computed at import time, so patching
    # DATA_DIR alone leaves them pointing at the live Application Support
    # files.  Without these the app's start-up CSV mirror export wrote the
    # one-row test inventory over the real stock.csv.
    monkeypatch.setattr(dm, "INVENTORY_FILE", str(tmp_path / "stock.csv"))
    monkeypatch.setattr(dm, "LOG_FILE", str(tmp_path / "transaction_log.csv"))
    monkeypatch.setattr(dm, "_sync_csv_quietly", lambda df: None)
    monkeypatch.setattr(dm.InventoryDataManager, "export_csv_mirrors",
                        staticmethod(lambda df=None: True))
    monkeypatch.setattr(dm, "create_auto_backup", lambda *a, **k: None)
    for name in ("showerror", "showwarning", "showinfo", "askyesno",
                 "askyesnocancel", "askokcancel"):
        monkeypatch.setattr(dm.messagebox, name, lambda *a, **k: True)

    conn = sqlite3.connect(db)
    dm._init_db_schema(conn)
    conn.execute(
        """
        INSERT INTO inventory
        (item_id, item_name, quantity, cost_price, sell_price, measure,
         category, price_locked, allow_negative, reorder_level, division)
        VALUES ('peroni', 'Peroni', 24, 1.2, 4.5, 'Bottle', 'Bottle', 0, 0, 6, 'Beer - Bottled')
        """
    )
    conn.commit()
    conn.close()

    import BarStockApp as ui
    monkeypatch.setattr(ui.messagebox, "showerror", lambda *a, **k: None)
    monkeypatch.setattr(ui.messagebox, "showwarning", lambda *a, **k: None)
    monkeypatch.setattr(ui.messagebox, "showinfo", lambda *a, **k: None)

    application = ui.BarStockManagementSystem(root)
    root.update_idletasks()
    yield application
    root.destroy()


SCREENS = [
    "show_dashboard",
    "show_reports",
    "show_more",
    "show_transactions",
    "show_delivery_history",
    "show_open_tabs",
    "show_stocktake",
    "show_sales_upload",
    "show_deliveries",
]


@pytest.mark.parametrize("screen", SCREENS)
def test_screen_builds(app, screen):
    getattr(app, screen)()
    app.root.update_idletasks()
    assert app.main_menu.winfo_exists()


def test_status_survives_navigation(app):
    app._set_status("Delivery saved.", "success")
    app.show_dashboard()
    app.root.update_idletasks()
    assert app.status_var.get() == "Delivery saved."
    app._clear_status_if("Delivery saved.")
    assert app.status_var.get() == ""


def test_dashboard_snapshot_is_cached(app):
    first = app._compute_dashboard_snapshot()
    second = app._compute_dashboard_snapshot()
    assert first is second  # same object returned while data is unchanged


def test_dashboard_reports_sales_inc_vat(app):
    """Sales are stored ex VAT but shown inc VAT as well, so the dashboard
    figure can be checked against an EPOS export."""
    from actions import ACTION_SALES
    from data_manager import LOG_COLUMNS

    sale = pd.DataFrame([[
        "peroni", ACTION_SALES, 10.0, "2026-10-20 12:00:00", 1.2, 4.5,
        "", "20-10-2026 - 20-10-2026", "", 0, 10, None,
    ]], columns=LOG_COLUMNS)
    app.log_df = pd.concat([app.log_df, sale], ignore_index=True)

    snap = app._compute_dashboard_snapshot()

    assert snap["period_sales"] == pytest.approx(45.00)
    assert snap["period_sales_inc"] == pytest.approx(54.00)
    upload = snap["recent_sales_uploads"][0]
    assert upload["value"] == pytest.approx(45.00)
    assert upload["value_inc"] == pytest.approx(54.00)
    peroni = next(s for s in snap["top_sellers"] if s["name"] == "Peroni")
    assert peroni["value"] == pytest.approx(45.00)
    assert peroni["value_inc"] == pytest.approx(54.00)


class _FakeDateRangeDialog:
    """Stand-in for the modal date picker: returns 'all time' immediately."""

    def __init__(self, *args, **kwargs):
        self.result = (None, None)


REPORT_SCREENS_TO_TEST = [
    "generate_gp_report",
    "generate_surplus_report",
    "generate_division_report",
    "generate_draught_yield_report",
    "generate_stocktake_report",
    "generate_reconciliation_report",
    "generate_price_history_report",
    "generate_sales_analytics",
    "generate_reorder_report",
    "generate_comparison_report",
]


@pytest.mark.parametrize("method", REPORT_SCREENS_TO_TEST)
def test_report_screen_builds(app, monkeypatch, method):
    """Each report screen must render against a withdrawn root.

    These live in screens/reports.py after the module split; the test keeps
    that split honest without needing a modal dialog.
    """
    import BarStockApp as ui
    import screens.reports as reports_screen

    monkeypatch.setattr(reports_screen, "DateRangeDialog", _FakeDateRangeDialog)
    # get_filtered_log still lives in the shell module and looks the dialog up
    # from its own globals.
    monkeypatch.setattr(ui, "DateRangeDialog", _FakeDateRangeDialog)
    getattr(app, method)()
    app.root.update_idletasks()
    assert app.main_menu.winfo_exists()


def test_delivery_screen_accepts_prefill(app):
    """Repeat-last-delivery injects its lines after the screen is built."""
    app.current_delivery_supplier = "Booker"
    app.process_delivery_multi_item(
        prefill=[("peroni", "Peroni", 12, 36, 1.2, 14.4)])
    app.root.update_idletasks()
    assert app.main_menu.winfo_exists()


def test_resolved_font_is_shared_with_screen_modules(app):
    import BarStockApp as ui
    import ui_theme

    assert ui_theme.THEME_FONT == ui.THEME_FONT


def test_shell_uses_ledger_paper_surfaces(app):
    """The shell, rail, content and tables all sit on Ledger tokens."""
    from tkinter import ttk

    import ui_theme

    app.show_dashboard()
    app.root.update_idletasks()

    assert app.shell_container.cget("bg") == ui_theme.THEME_BG
    assert app.sidebar.cget("bg") == ui_theme.THEME_SIDEBAR
    assert app.main_menu.cget("bg") == ui_theme.THEME_BG

    style = ttk.Style()
    assert style.lookup("Treeview", "background") == ui_theme.THEME_BG
    assert style.lookup("Treeview", "foreground") == ui_theme.THEME_TEXT
    assert style.lookup("Treeview.Heading", "background") == ui_theme.THEME_SIDEBAR


def test_retired_item_leaves_the_stock_list(app):
    """Retiring must hide an item without deleting its row."""
    import retirement

    app.manage_initial_stock()
    app.root.update_idletasks()
    assert len(app.stock_tree.get_children()) == 1

    retirement.retire_item("peroni")
    try:
        app.load_stock_into_tree()
        assert app.stock_tree.get_children() == ()
        assert "peroni" in app.inventory_df["item_id"].values
    finally:
        retirement.unretire_item("peroni")
        retirement.reset_cache()


def test_backup_now_runs_and_resets_the_button(app, monkeypatch, tmp_path):
    """The dashboard button must actually create a backup and re-enable."""
    import screens.dashboard as dashboard

    created = {}

    def fake_run(message, work, on_success=None, on_error=None, title=''):
        created['path'] = work()
        on_success(created['path'])

    monkeypatch.setattr(app, '_run_in_background', fake_run)
    monkeypatch.setattr(
        dashboard, 'create_backup',
        lambda reason='': str(tmp_path / f'barstock_backup_{reason}.db'))
    monkeypatch.setattr(dashboard.messagebox, 'showinfo', lambda *a, **k: None)

    app._backup_now()

    assert created['path'].endswith('barstock_backup_dashboard.db')
    assert getattr(app, '_backup_in_progress', False) is False
    assert 'Backup created' in app.status_var.get()
