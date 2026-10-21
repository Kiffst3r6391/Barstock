#!/usr/bin/env python3
"""Runtime retirement (delisting) of stock items.

Items that have transaction history must never be hard-deleted: the log rows
would still point at them but every report joins through the inventory row, so
the history would silently vanish from reports.  Retiring keeps the row, marks
it delisted, and hides it from active stock views and ordering.

Static delistings live in ``categories.DELISTED_ITEMS``.  Items retired through
the UI are stored in the ``settings`` table under ``retired_items`` as a JSON
list, so they survive restarts and are available to every module that asks
``categories.is_delisted``.
"""

import json

_CACHE = {'loaded': False, 'items': set()}


def _load_from_settings():
    from data_manager import get_setting

    raw = get_setting('retired_items', '[]')
    try:
        values = json.loads(raw or '[]')
    except (TypeError, ValueError):
        values = []
    return {str(value).lower().strip() for value in values if value}


def load_retired_items(refresh=False):
    """Return the set of item IDs retired through the UI (cached)."""
    if _CACHE['loaded'] and not refresh:
        return set(_CACHE['items'])
    try:
        items = _load_from_settings()
    except Exception:
        items = set()
    _CACHE['items'] = items
    _CACHE['loaded'] = True
    return set(items)


def is_retired(item_id):
    return str(item_id).lower().strip() in load_retired_items()


def _save(items):
    from data_manager import set_setting

    payload = json.dumps(sorted(items))
    if not set_setting('retired_items', payload):
        raise RuntimeError("Could not save the retired item list")
    _CACHE['items'] = set(items)
    _CACHE['loaded'] = True


def retire_item(item_id):
    """Mark an item as retired, preserving all of its history."""
    key = str(item_id).lower().strip()
    items = load_retired_items()
    items.add(key)
    _save(items)
    return key


def unretire_item(item_id):
    """Return an item to active stock."""
    key = str(item_id).lower().strip()
    items = load_retired_items()
    items.discard(key)
    _save(items)
    return key


def reset_cache():
    """Forget the cached list (used by tests)."""
    _CACHE['loaded'] = False
    _CACHE['items'] = set()
