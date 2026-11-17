"""Local app password protection.

This is an access gate for the desktop window, not database encryption: the
SQLite database and CSV mirrors remain readable by anyone with file access.
Passwords are stored as a PBKDF2-SHA256 hash with a random salt in the normal
settings table.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets

SETTING_KEY = 'app_password'
ITERATIONS = 200_000


def _make_hash(password: str, salt_hex: str, iterations: int = ITERATIONS) -> str:
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), salt, int(iterations))
    return digest.hex()


def _record():
    from data_manager import get_setting
    raw = get_setting(SETTING_KEY, '')
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def password_enabled() -> bool:
    record = _record()
    return bool(record and record.get('enabled')
                and record.get('salt') and record.get('hash'))


def verify_password(password: str) -> bool:
    record = _record()
    if not record or not record.get('enabled'):
        return True
    if not record.get('salt') or not record.get('hash'):
        return False
    try:
        candidate = _make_hash(
            password or '', record['salt'],
            int(record.get('iterations', ITERATIONS)))
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(candidate, str(record['hash']))


def set_password(password: str, enabled: bool = True) -> bool:
    """Set or replace the password. Requires a non-empty password to enable."""
    if enabled and not (password or '').strip():
        return False
    salt = secrets.token_hex(16)
    record = {
        'enabled': bool(enabled),
        'salt': salt,
        'hash': _make_hash(password or '', salt),
        'iterations': ITERATIONS,
    }
    from data_manager import set_setting
    return set_setting(SETTING_KEY, json.dumps(record))


def disable_password(current_password: str) -> bool:
    if not password_enabled():
        return True
    if not verify_password(current_password):
        return False
    record = _record() or {}
    record['enabled'] = False
    from data_manager import set_setting
    return set_setting(SETTING_KEY, json.dumps(record))


def prompt_for_password(root) -> bool:
    """Ask for the startup password. Returns False when access is refused."""
    from tkinter import simpledialog, messagebox
    for attempt in range(3):
        value = simpledialog.askstring(
            "Password required",
            "Enter the BarStock password:",
            show='*', parent=root)
        if value is None:
            return False
        if verify_password(value):
            return True
        messagebox.showerror("Password", "Incorrect password.", parent=root)
    return False
