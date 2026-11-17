"""Headless self-test for the packaged desktop app.

Run with ``BarStockManagement.exe --self-test`` (or
``python3 BarStockApp.py --self-test``). It uses an isolated temporary data
folder, so it never touches live club data, and writes a short report to the
system temp directory.
"""
from __future__ import annotations

import os
import tempfile
import traceback
from datetime import datetime


def run_self_test() -> int:
    lines: list[str] = []
    ok = True
    try:
        import pandas as pd
        import club_profile
        import data_manager
        import security
        from app_runtime import APP_VERSION
        from pdf_generator import PDFReport
        from reports import build_comprehensive_report_data

        profile = club_profile.get_profile()
        lines.append(f"Version: {APP_VERSION}")
        lines.append(f"Profile: {profile.get('profile_id')} / "
                     f"{profile.get('club_name')}")
        lines.append(f"Data directory: {data_manager.DATA_DIR}")

        logo = club_profile.get_logo_path()
        lines.append(f"Logo: {logo or '(none configured)'}")

        inventory = data_manager.InventoryDataManager.load_inventory()
        log = data_manager.InventoryDataManager.load_log()
        lines.append(f"Database: inventory={len(inventory)} rows, "
                     f"log={len(log)} rows")

        sample = pd.DataFrame([[
            'self_test_item', 'Self Test Item', 10.0, 1.5, 4.0,
            'Pint', 'Draught', False, False, 0.0, 'Beer - Draught',
        ]], columns=data_manager.INVENTORY_COLUMNS)
        items_path = data_manager.ensure_items_csv_master(sample)
        lines.append(f"Items.csv master: {items_path or '(not created)'}")

        empty_log = pd.DataFrame(columns=data_manager.LOG_COLUMNS)
        report_data = build_comprehensive_report_data(sample, empty_log)
        pdf = PDFReport()
        pdf.generate_report(report_data, report_period='Self-test')
        pdf_path = os.path.join(tempfile.gettempdir(), 'barstock_self_test.pdf')
        pdf.output(pdf_path)
        lines.append(f"PDF: {pdf_path} "
                     f"({os.path.getsize(pdf_path)} bytes)")

        backup = data_manager.create_backup('self_test')
        if not backup:
            raise RuntimeError('backup was not created')
        verified, message = data_manager.verify_database(backup)
        if not verified:
            raise RuntimeError(f'backup verification failed: {message}')
        lines.append(f"Backup: {os.path.basename(backup)} (verified)")

        if not security.set_password('self-test-password', True):
            raise RuntimeError('could not set the self-test password')
        if not security.verify_password('self-test-password'):
            raise RuntimeError('password verification failed')
        if security.verify_password('wrong-password'):
            raise RuntimeError('wrong password was accepted')
        if not security.disable_password('self-test-password'):
            raise RuntimeError('could not disable the self-test password')
        lines.append('Password gate: set / verify / disable (ok)')

        lines.append(f"Result: PASS ({datetime.now():%Y-%m-%d %H:%M:%S})")
    except Exception:
        ok = False
        lines.append('Result: FAIL')
        lines.append(traceback.format_exc())

    report_path = os.path.join(tempfile.gettempdir(),
                               'barstock_self_test.txt')
    try:
        with open(report_path, 'w', encoding='utf-8') as handle:
            handle.write('\n'.join(lines) + '\n')
    except OSError:
        pass
    for line in lines:
        print(line)
    print(f"Report: {report_path}")
    return 0 if ok else 1
