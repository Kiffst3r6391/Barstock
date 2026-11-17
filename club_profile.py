"""Club profile: branding, data-directory and feature configuration.

The app is sold as a white-labelled product, so the club name, logo, data
folder and club-specific feature flags must not be hard-coded in the UI. A
profile is a small JSON document; this module loads the right one for the
running build and exposes simple accessors.

It deliberately uses only the standard library so ``app_config`` can import it
before the database exists without an import cycle.
"""

from __future__ import annotations

import copy
import json
import ntpath
import os
import posixpath
import sys
from typing import Any, Mapping

DEFAULT_PROFILE: dict[str, Any] = {
    'profile_id': 'default',
    'club_name': 'BarStock',
    'club_short_name': 'BarStock',
    'strap_line': 'Stock Control',
    'crest_text': 'BS',
    'logo_path': '',
    'footer_credit': '',
    'greeting_name': '',
    'data_dir_name': 'BarStockManagement',
    'app_display_name': 'Bar Stock Management',
    'pdf_header_prefix': 'Bar Stock',
    'complimentary_reasons': ['Hospitality', 'Manager', 'Other'],
    'suppliers': [],
    'default_supplier': '',
    'features': {
        'stock_order_sheet': False,
        'booker_invoice_price_check': False,
        'mapping_warnings': False,
    },
    'item_rules': {},
}

_PROFILE_CACHE: dict[str, Any] | None = None


def _script_directory() -> str:
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _deep_merge(base: dict[str, Any], overlay: Mapping[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if (isinstance(value, Mapping)
                and isinstance(result.get(key), Mapping)):
            result[key] = _deep_merge(dict(result[key]), value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _read_json(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def _candidate_paths() -> list[str]:
    candidates: list[str] = []
    explicit = os.environ.get('BARSTOCK_CLUB_PROFILE', '').strip()
    if explicit:
        candidates.append(explicit)

    name = os.environ.get('BARSTOCK_PROFILE', '').strip()
    if name:
        if name.lower().endswith('.json'):
            candidates.append(name)
        else:
            candidates.append(os.path.join(
                _script_directory(), 'profiles', f'{name}.json'))

    script_dir = _script_directory()
    if getattr(sys, 'frozen', False):
        candidates.append(os.path.join(script_dir, 'club_profile.json'))
        candidates.append(os.path.join(
            os.path.dirname(sys.executable), 'club_profile.json'))
    else:
        candidates.append(os.path.join(
            script_dir, 'profiles', 'prestonfield.json'))
        candidates.append(os.path.join(script_dir, 'club_profile.json'))
    return candidates


def resolve_data_dir(profile: Mapping[str, Any],
                     os_name: str | None = None,
                     environ: Mapping[str, str] | None = None) -> str:
    """Return the per-user data directory for a profile.

    This is pure apart from reading the supplied environment; it does not
    create the directory. ``BARSTOCK_DATA_DIR`` is an explicit override used
    by tests and portable/developer runs.
    """
    environ = os.environ if environ is None else environ
    override = str(environ.get('BARSTOCK_DATA_DIR', '') or '').strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))

    folder = str(profile.get('data_dir_name') or 'BarStockManagement').strip()
    if os_name is None:
        if sys.platform.startswith('win'):
            os_name = 'nt'
        elif sys.platform == 'darwin':
            os_name = 'darwin'
        else:
            os_name = 'posix'

    if os_name == 'nt':
        base = (environ.get('LOCALAPPDATA')
                or environ.get('APPDATA')
                or ntpath.join(os.path.expanduser('~'), 'AppData', 'Local'))
        return ntpath.join(base, folder)
    home = environ.get('HOME') or os.path.expanduser('~')
    if os_name == 'darwin':
        return posixpath.join(home, 'Library', 'Application Support', folder)
    base = environ.get('XDG_DATA_HOME') or posixpath.join(
        home, '.local', 'share')
    return posixpath.join(base, folder)


def load_profile(path: str | None = None, force: bool = False) -> dict[str, Any]:
    """Load and merge the club profile.

    Order: explicit path, environment candidates, bundled profile, source
    seller profile, neutral defaults. A local overlay in the data folder
    can add branding/item rules on the destination machine without a rebuild.
    """
    global _PROFILE_CACHE
    if _PROFILE_CACHE is not None and not force and path is None:
        return _PROFILE_CACHE

    profile = copy.deepcopy(DEFAULT_PROFILE)
    chosen = path
    if chosen:
        data = _read_json(chosen)
        if data:
            profile = _deep_merge(profile, data)
    else:
        for candidate in _candidate_paths():
            data = _read_json(candidate)
            if data:
                profile = _deep_merge(profile, data)
                break

    data_dir = resolve_data_dir(profile)
    local_path = os.path.join(data_dir, 'club_profile.local.json')
    local = _read_json(local_path)
    if local:
        # The data folder cannot be moved by a local overlay: it has already
        # been used to locate this file. Branding and item rules are fine.
        local = {key: value for key, value in local.items()
                 if key != 'data_dir_name'}
        profile = _deep_merge(profile, local)

    _PROFILE_CACHE = profile
    return profile


def reload_profile(path: str | None = None) -> dict[str, Any]:
    global _PROFILE_CACHE
    _PROFILE_CACHE = None
    return load_profile(path, force=True)


def get_profile() -> dict[str, Any]:
    return load_profile()


def profile_value(key: str, default: Any = None) -> Any:
    return get_profile().get(key, default)


def club_name() -> str:
    return str(profile_value('club_name', DEFAULT_PROFILE['club_name']))


def club_short_name() -> str:
    return str(profile_value('club_short_name', club_name()))


def strap_line() -> str:
    return str(profile_value('strap_line', ''))


def crest_text() -> str:
    return str(profile_value('crest_text', ''))


def footer_credit() -> str:
    return str(profile_value('footer_credit', ''))


def greeting_name() -> str:
    return str(profile_value('greeting_name', ''))


def app_display_name() -> str:
    return str(profile_value('app_display_name', 'Bar Stock Management'))


def pdf_header_prefix() -> str:
    return str(profile_value('pdf_header_prefix', club_name()))


def complimentary_reasons() -> list[str]:
    reasons = profile_value('complimentary_reasons')
    if isinstance(reasons, list) and reasons:
        return [str(reason) for reason in reasons]
    return list(DEFAULT_PROFILE['complimentary_reasons'])


def suppliers() -> list[str]:
    values = profile_value('suppliers')
    if not isinstance(values, list):
        return []
    return [str(value).strip() for value in values if str(value).strip()]


def default_supplier() -> str:
    return str(profile_value('default_supplier', '') or '')


def feature_enabled(name: str) -> bool:
    features = profile_value('features', {}) or {}
    return bool(features.get(name, DEFAULT_PROFILE['features'].get(name, False)))


def get_logo_path() -> str | None:
    """Return an existing logo path from the bundle, source tree or data dir."""
    raw = str(profile_value('logo_path', '') or '').strip()
    if not raw:
        return None
    if os.path.isabs(raw) and os.path.exists(raw):
        return raw

    candidates = [
        os.path.join(_script_directory(), raw),
        os.path.join(_script_directory(), 'assets', os.path.basename(raw)),
    ]
    try:
        data_dir = resolve_data_dir(get_profile())
        candidates.append(os.path.join(data_dir, raw))
        candidates.append(os.path.join(data_dir, 'assets',
                                     os.path.basename(raw)))
    except Exception:
        pass
    for candidate in candidates:
        if os.path.exists(candidate):
            return candidate
    return None


def apply_settings_overrides(get_setting) -> dict[str, Any]:
    """Apply DB settings over profile branding after the database exists."""
    profile = get_profile()
    for key in ('club_name', 'club_short_name', 'footer_credit',
                'greeting_name', 'pdf_header_prefix', 'logo_path'):
        try:
            value = get_setting(key)
        except Exception:
            value = None
        if value not in (None, ''):
            profile[key] = str(value)

    try:
        raw_suppliers = get_setting('suppliers')
        if raw_suppliers:
            parsed = json.loads(raw_suppliers)
            if isinstance(parsed, list):
                profile['suppliers'] = [str(v).strip() for v in parsed
                                        if str(v).strip()]
    except Exception:
        pass
    current_default = str(profile.get('default_supplier', '') or '')
    values = profile.get('suppliers') or []
    if values and current_default not in values:
        profile['default_supplier'] = values[0]
    if not values:
        profile['default_supplier'] = ''
    return profile


def apply_item_rules(profile: Mapping[str, Any] | None = None) -> None:
    """Merge optional per-club item rules into the existing module maps.

    Kept lazy so importing this module never imports pandas/reporting code.
    Phase E populates the profile sections; empty sections are ignored.
    """
    profile = dict(profile or get_profile())
    rules = profile.get('item_rules') or {}
    if not isinstance(rules, Mapping) or not rules:
        return

    def _items(value):
        if not isinstance(value, Mapping):
            return {}
        return {str(key).strip().lower(): val for key, val in value.items()}

    conversions = _items(rules.get('conversions'))
    if conversions:
        import conversions as conversions_module
        conversions_module.STOCK_CONVERSIONS.update(conversions)

    sales_to_parent = _items(rules.get('sales_to_parent'))
    if sales_to_parent:
        import sales_mapping
        sales_mapping.SALES_TO_PARENT.update(sales_to_parent)

    aliases = _items(rules.get('epos_aliases'))
    if aliases:
        import sales_mapping
        sales_mapping.EPOS_NAME_TO_ITEM_ID.update(aliases)

    ignored = rules.get('ignored_epos_items')
    if isinstance(ignored, list) and ignored:
        import sales_mapping
        sales_mapping.IGNORED_EPOS_ITEMS.update(
            str(value).strip().lower() for value in ignored if str(value).strip())

    category_map = _items(rules.get('category_map'))
    if category_map:
        import categories
        categories.CATEGORY_MAP.update(category_map)

    excluded = rules.get('excluded_items')
    if isinstance(excluded, list) and excluded:
        import categories
        categories.EXCLUDED_ITEMS.update(
            str(value).strip().lower() for value in excluded if str(value).strip())

    delisted = rules.get('delisted_items')
    if isinstance(delisted, list) and delisted:
        import categories
        categories.DELISTED_ITEMS.update(
            str(value).strip().lower() for value in delisted if str(value).strip())
