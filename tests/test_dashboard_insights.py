"""Tests for the dashboard/PDF insight builders.

These are pure DataFrame tests; they never touch the live database.
"""

import pandas as pd

from actions import (
    ACTION_COMPLIMENTARY, ACTION_DELIVERY, ACTION_LINE_CLEAN,
    ACTION_SALES, ACTION_WASTAGE,
)
from data_manager import INVENTORY_COLUMNS, LOG_COLUMNS
from pdf_generator import calculate_vat_position, PDFReport
from reports import (
    build_previous_period_log, build_period_comparison_summary,
    build_upload_period_health, find_overlapping_upload_periods,
    build_price_change_alerts, build_supplier_spend_summary,
    build_reason_value_summary, build_value_movement_bridge,
    build_report_reconciliation_notes, item_division_lookup,
)


def inventory_frame(rows):
    return pd.DataFrame(rows, columns=INVENTORY_COLUMNS)


def log_frame(rows):
    return pd.DataFrame(rows, columns=LOG_COLUMNS)


def sample_inventory():
    return inventory_frame([
        ['tennents_lager', 'Tennents Lager', 40.0, 1.5, 5.2,
         'Pint', 'Draught', False, False, 100.0, 'Beer - Draught'],
        ['can', 'Can', 80.0, 0.8, 1.5,
         'Can', 'Beer', False, False, 0.0, 'Beer - Bottled'],
    ])


def sample_log():
    return log_frame([
        ['tennents_lager', ACTION_SALES, 20, '2026-11-02 10:00:00', 1.5, 5.2,
         '', '01-11-2026 - 08-11-2026', '', 12, 8, None],
        ['can', ACTION_SALES, 10, '2026-11-03 10:00:00', 0.8, 1.5,
         '', '01-11-2026 - 08-11-2026', '', 6, 4, None],
        ['tennents_lager', ACTION_DELIVERY, 88, '2026-11-02 09:00:00',
         1.6, 5.2, 'Tennents', '', '', 0, 0, None],
        ['tennents_lager', ACTION_WASTAGE, 2, '2026-11-04 09:00:00',
         1.6, 5.2, '', '', 'Spillage', 0, 0, None],
        ['tennents_lager', ACTION_WASTAGE, 5, '2026-11-05 09:00:00',
         1.6, 5.2, '', '', 'Line Clean', 0, 0, None],
        ['can', ACTION_COMPLIMENTARY, 1, '2026-11-06 09:00:00',
         0.8, 1.5, '', '', 'Goodwill', 0, 0, None],
    ])


def test_previous_period_excludes_rows_already_in_current_period():
    full = sample_log()
    current = full.iloc[[0]]
    previous_log, start, end = build_previous_period_log(
        full, pd.Timestamp('2026-11-01'), pd.Timestamp('2026-11-08'), current)
    assert previous_log is not None
    assert 0 not in previous_log.index
    assert start < end


def test_comparison_summary_is_penny_exact():
    inventory = sample_inventory()
    current = sample_log()
    comparison = build_period_comparison_summary(inventory, current, None, 10)
    figures = comparison['current']
    assert figures['sales_ex_vat'] == 119.0
    assert figures['sales_inc_vat'] == 142.8
    assert figures['cost_of_sales'] == 38.0
    assert figures['gp'] == 81.0
    assert figures['wastage_cost'] == 3.0
    assert figures['line_clean_cost'] == 7.5
    assert figures['complimentary_retail'] == 1.5
    assert figures['delivery_spend'] == 140.8
    assert comparison['previous'] is None


def test_comparison_reports_direction_and_goodness():
    inventory = sample_inventory()
    current = sample_log()
    previous = sample_log()
    # Make the previous period larger so sales are down.
    previous.loc[0, 'quantity'] = 40
    comparison = build_period_comparison_summary(
        inventory, current, previous, 10)
    sales_change = comparison['changes']['sales_ex_vat']
    assert sales_change['direction'] == 'down'
    assert sales_change['good'] is False
    assert sales_change['pct'] is not None


def test_upload_health_detects_gap_and_overlap():
    log = log_frame([
        ['can', ACTION_SALES, 1, '2026-10-03 10:00:00', 0.8, 1.5,
         '', '01-10-2026 - 07-10-2026', '', 1, 0, None],
        ['can', ACTION_SALES, 1, '2026-10-10 10:00:00', 0.8, 1.5,
         '', '08-10-2026 - 14-10-2026', '', 1, 0, None],
        ['can', ACTION_SALES, 1, '2026-10-12 10:00:00', 0.8, 1.5,
         '', '08-10-2026 - 14-10-2026', '', 1, 0, None],
        ['can', ACTION_SALES, 1, '2026-10-20 10:00:00', 0.8, 1.5,
         '', '15-10-2026 - 21-10-2026', '', 1, 0, None],
    ])
    health = build_upload_period_health(log, today=pd.Timestamp('2026-10-30'))
    assert health['latest_period'] == '15-10-2026 - 21-10-2026'
    assert health['largest_gap_days'] == 0
    assert health['days_since_period_end'] == 9
    assert health['status'] == 'overdue'

    overlapping = log_frame([
        ['can', ACTION_SALES, 1, '2026-10-03 10:00:00', 0.8, 1.5,
         '', '01-10-2026 - 07-10-2026', '', 1, 0, None],
        ['can', ACTION_SALES, 1, '2026-10-05 10:00:00', 0.8, 1.5,
         '', '04-10-2026 - 10-10-2026', '', 1, 0, None],
    ])
    health = build_upload_period_health(
        overlapping, today=pd.Timestamp('2026-10-12'))
    assert health['overlaps']
    assert health['status'] == 'warning'


def test_find_overlapping_upload_periods_lists_existing_periods():
    log = log_frame([
        ['can', ACTION_SALES, 1, '2026-10-03 10:00:00', 0.8, 1.5,
         '', '01-10-2026 - 07-10-2026', '', 1, 0, None],
    ])
    assert find_overlapping_upload_periods(
        pd.Timestamp('2026-10-05'), pd.Timestamp('2026-10-12'), log
    ) == ['01-10-2026 - 07-10-2026']
    assert find_overlapping_upload_periods(
        pd.Timestamp('2026-10-08'), pd.Timestamp('2026-10-12'), log
    ) == []


def test_price_alerts_only_fire_above_threshold_and_ignore_same_price():
    inventory = sample_inventory()
    log = log_frame([
        ['tennents_lager', ACTION_DELIVERY, 10, '2026-10-01 09:00:00',
         1.0, 5.2, 'Tennents', '', '', 0, 0, None],
        ['tennents_lager', ACTION_DELIVERY, 10, '2026-10-02 09:00:00',
         1.0, 5.2, 'Tennents', '', '', 0, 0, None],
        ['tennents_lager', ACTION_DELIVERY, 10, '2026-10-10 09:00:00',
         1.2, 5.2, 'Tennents', '', '', 0, 0, None],
        ['tennents_lager', ACTION_DELIVERY, 10, '2026-10-11 09:00:00',
         1.21, 5.2, 'Tennents', '', '', 0, 0, None],
    ])
    alerts = build_price_change_alerts(
        inventory, log, days=None, threshold_pct=10)
    # 1.00 -> 1.20 is +20%; 1.20 -> 1.21 is +0.8% and must not fire.
    assert len(alerts) == 1
    assert alerts[0]['old_cost'] == 1.0
    assert alerts[0]['new_cost'] == 1.2


def test_supplier_spend_is_allocated_and_shares_sum_to_100():
    log = sample_log()
    rows = build_supplier_spend_summary(log)
    assert rows[0]['supplier'] == 'Tennents'
    assert rows[0]['spend_ex_vat'] == 140.8
    assert sum(row['share_pct'] for row in rows) == 100.0


def test_reason_summary_keeps_line_clean_out_of_wastage():
    inventory = sample_inventory()
    log = sample_log()
    wastage = build_reason_value_summary(log, inventory, 'wastage')
    line_clean = build_reason_value_summary(log, inventory, 'line_clean')
    assert [row['reason'] for row in wastage] == ['Spillage']
    # The reason summary uses the current inventory cost, the same basis as
    # the report's item tables, so the two totals reconcile.
    assert wastage[0]['value'] == 3.0
    assert line_clean[0]['reason'] == 'Line Clean'
    assert line_clean[0]['value'] == 7.5


def test_value_bridge_exposes_the_difference():
    report_data = [{
        'opening_stock': 10, 'cost_price': 1.5, 'delivery_qty': 88,
        'sales_cost': 30, 'wastage_qty': 2, 'line_clean_qty': 5,
        'complimentary_qty': 1, 'supplier_return_qty': 0,
        'surplus_value': 0, 'stock_value': 60,
    }]
    bridge = build_value_movement_bridge(report_data, 60)
    assert bridge['closing'] == 60.0
    assert bridge['expected_closing'] == 105.0
    assert bridge['difference'] == -45.0
    labels = [row['label'] for row in bridge['rows']]
    assert 'Difference (cost revaluation)' in labels


def test_vat_position_output_input_net():
    vat = calculate_vat_position(1000.0, 400.0)
    assert vat['output_vat'] == 200.0
    assert vat['input_vat'] == 80.0
    assert vat['net_vat'] == 120.0


def test_reconciliation_notes_flag_zero_cost_and_unassigned_deliveries():
    inventory = sample_inventory()
    log = log_frame([
        ['can', ACTION_SALES, 10, '2026-11-03 10:00:00',
         0, 1.5, '', '01-11-2026 - 08-11-2026', '', 0, 10, None],
        ['can', ACTION_DELIVERY, 10, '2026-11-02 09:00:00',
         0.8, 1.5, '', '', '', 0, 0, None],
    ])
    report_data = [{'item_id': 'can', 'total_sales_value': 15.0,
                    'sales_cost': 0, 'stock_value': 64.0}]
    notes = build_report_reconciliation_notes(inventory, log, report_data)
    titles = {note['title'] for note in notes}
    assert 'Zero-cost sales lines' in titles
    assert 'Unassigned deliveries' in titles


def test_pdf_generates_with_new_sections(tmp_path):
    inventory = sample_inventory()
    log = sample_log()
    from reports import (
        build_comprehensive_report_data, build_executive_narrative,
        build_upload_period_health,
    )
    report_data = build_comprehensive_report_data(inventory, log)
    comparison = build_period_comparison_summary(inventory, log, None, 10)
    vat = calculate_vat_position(
        comparison['current']['sales_ex_vat'],
        comparison['current']['delivery_spend'])
    insights = {
        'comparison': comparison,
        'narrative': build_executive_narrative(
            comparison, supplier_spend=build_supplier_spend_summary(log),
            vat_position=vat),
        'vat_position': vat,
        'supplier_spend': build_supplier_spend_summary(log),
        'price_changes': [],
        'wastage_reasons': build_reason_value_summary(log, inventory, 'wastage'),
        'line_clean_reasons': build_reason_value_summary(log, inventory, 'line_clean'),
        'comp_reasons': build_reason_value_summary(log, inventory, 'comp', 'retail'),
        'upload_health': build_upload_period_health(log),
        'value_bridge': build_value_movement_bridge(report_data),
        'reconciliation_notes': build_reconciliation_notes_for_pdf(
            inventory, log, report_data),
    }
    pdf = PDFReport()
    pdf.generate_report(report_data, report_period='01-11-2026 to 08-11-2026',
                        insights=insights)
    output = tmp_path / 'report.pdf'
    pdf.output(str(output))
    assert output.exists()
    assert output.stat().st_size > 1000


def build_reconciliation_notes_for_pdf(inventory, log, report_data):
    return build_report_reconciliation_notes(inventory, log, report_data)


def test_division_lookup_inherits_parent_for_child_items():
    inventory = inventory_frame([
        ['tennents_lager', 'Tennents Lager', 10, 1.5, 5.2,
         'Pint', 'Draught', False, False, 0, 'Beer - Draught'],
        ['tennents_lager_half', 'Tennents Lager - Half', 0, 0.75, 1.75,
         'Half Pint', 'Draught', False, False, 0, ''],
        ['guinness_0_0', 'Guinness 0.0', 0, 1.0, 2.0,
         'Bottle', 'Bottle', False, False, 0, ''],
    ])
    lookup = item_division_lookup(inventory)
    assert lookup['tennents_lager_half'] == 'Beer - Draught'
    assert lookup['guinness_0_0'] == 'Beer - Bottled'
