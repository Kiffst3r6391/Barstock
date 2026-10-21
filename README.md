# BarStock Management

Desktop stock control for Prestonfield Golf Club's bar: deliveries, sales,
wastage, stocktakes, GP reporting, order sheets and invoice price checks.

## Running

```bash
pip3 install -r requirements.txt
python3 BarStockApp.py
```

The live database and CSV mirrors are stored in
`~/Library/Application Support/BarStockManagement/`, not in the repository or
the application bundle. A daily backup is taken on start-up and retained in
`backups/` (newest 20 kept).

## Tests

```bash
python3 -m pytest -q
```

CI runs the same suite on macOS via `.github/workflows/tests.yml`.

## Project layout

`BarStockApp.py` is the application shell: window setup, theme, navigation,
status bar and the Manage Stock screen. Individual screens live in
`screens/` as mixins over that shell:

- `screens/dashboard.py` — stat cards, alerts and snapshot
- `screens/deliveries.py` — delivery entry, repeat last delivery
- `screens/inventory.py` — stock management and delivery history
- `screens/reports.py` — GP, surplus, variance, analytics and PDFs
- `screens/stocktake.py` — guided count and count sheet
- `screens/transactions.py` — transaction log, open tabs, wastage
- `screens/uploads.py` — EPOS sales, complimentary and invoice checks
- `screens/widgets.py` — shared dialogs (date range picker)

Shared data locations and schema names are in `app_config.py`, colour and
font tokens in `ui_theme.py`, and runtime delistings in `retirement.py`.

Items with transaction history are retired rather than deleted, so reports
keep their history; they can be restored from Stock Management → Retired
Items. Resetting the system requires typing `RESET`.

## Data health

```bash
python3 audit_data.py            # human-readable report
python3 audit_data.py --json     # machine-readable
```

Exits non-zero when issues are found, so it can gate a release. The app also
runs the inventory-vs-transaction-log check at start-up and shows a banner if
the two disagree.

## One-off tools

These default to a dry run and must be given an explicit flag to write:

- `apply_baseline_from_count.py --counts counts.csv [--run]`
- `generate_variance_report.py --counts counts.csv [--output FILE]`
- `apply_invoice_prices.py [--apply] [--allow-locked]`
- `migrate_to_ex_vat.py` / `migrate_to_inc_vat.py` (`--run`, guarded by a
  `price_basis` marker so a migration cannot be applied twice)

## Building the macOS app

```bash
python3 build_app.py
```

Requires PyInstaller. `BarStock.spec` is the single source of truth for the
bundle (modules, hidden imports, icon, entitlements, version pulled from
`pyproject.toml`); the script builds from it and then verifies the version,
code signature and that no live data files were bundled. The bundle no longer
contains stock data files.
