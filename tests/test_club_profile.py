"""Club-profile and platform-path tests."""

import json
from pathlib import Path

import club_profile


def test_neutral_defaults():
    profile = club_profile.DEFAULT_PROFILE
    assert profile['club_name'] == 'BarStock'
    assert 'Prestonfield' not in json.dumps(profile)
    assert 'Chris Armstrong' not in json.dumps(profile)


def test_resolve_data_dir_by_platform(tmp_path):
    profile = {'data_dir_name': 'BruntsfieldBarStock'}
    assert club_profile.resolve_data_dir(
        profile, os_name='darwin', environ={}
    ).endswith('Library/Application Support/BruntsfieldBarStock')
    assert club_profile.resolve_data_dir(
        profile, os_name='nt',
        environ={'LOCALAPPDATA': r'C:\Users\Test\AppData\Local'}
    ) == r'C:\Users\Test\AppData\Local\BruntsfieldBarStock'
    override = str(tmp_path / 'x')
    assert club_profile.resolve_data_dir(
        profile, os_name='nt', environ={'BARSTOCK_DATA_DIR': override}
    ) == override


def test_bruntsfield_profile_fields():
    profile = club_profile.reload_profile('profiles/bruntsfield.json')
    try:
        assert profile['profile_id'] == 'bruntsfield'
        assert profile['club_name'] == 'Bruntsfield Links'
        assert profile['data_dir_name'] == 'BruntsfieldBarStock'
        assert profile['footer_credit'] == ''
        assert profile['greeting_name'] == ''
        assert profile['features']['stock_order_sheet'] is False
        assert profile['features']['booker_invoice_price_check'] is False
        assert 'Prestonfield' not in json.dumps(profile)
        assert 'Chris Armstrong' not in json.dumps(profile)
    finally:
        club_profile.reload_profile()


def test_prestonfield_profile_fields():
    profile = club_profile.reload_profile('profiles/prestonfield.json')
    try:
        assert profile['club_name'] == 'Prestonfield Golf Club'
        assert profile['data_dir_name'] == 'BarStockManagement'
        assert profile['features']['stock_order_sheet'] is True
    finally:
        club_profile.reload_profile()


def test_bruntsfield_logo_resolves():
    club_profile.reload_profile('profiles/bruntsfield.json')
    try:
        path = club_profile.get_logo_path()
        assert path is not None
        assert Path(path).exists()
    finally:
        club_profile.reload_profile()
