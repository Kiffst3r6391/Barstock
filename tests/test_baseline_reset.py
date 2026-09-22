"""Tests for baseline reset audit trail helpers."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from data_manager import (
    InventoryDataManager,
    add_baseline_reset,
    get_baseline_reset_history,
    initialize_db,
)


@pytest.fixture
def temp_db_path(monkeypatch):
    """Create a temporary SQLite DB and point data_manager at it."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    def mock_get_connection():
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        return conn

    import data_manager
    monkeypatch.setattr(data_manager, "_get_connection", mock_get_connection)
    monkeypatch.setattr(data_manager, "DB_PATH", Path(path))

    initialize_db()

    yield path

    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def test_add_baseline_reset_stores_full_audit_record(temp_db_path):
    snapshot = [
        {"item_id": "tennents_lager", "counted_system": 100.0, "input_value": 100.0, "input_unit": "pint"},
        {"item_id": "guinness", "counted_system": 80.0, "input_value": 80.0, "input_unit": "pint"},
    ]
    ts = datetime.now().isoformat()
    assert add_baseline_reset(ts, 2, 150, "weekly reset", snapshot=snapshot) is True

    history = get_baseline_reset_history(limit=10)
    assert len(history) == 1
    entry = history[0]
    assert entry["timestamp"] == ts
    assert entry["items_count"] == 2
    assert entry["archived_count"] == 150
    assert entry["note"] == "weekly reset"
    assert entry["snapshot"] == snapshot


def test_baseline_reset_history_returns_most_recent_first(temp_db_path):
    for i in range(3):
        add_baseline_reset(f"2026-08-{10 + i:02d} 12:00:00", i + 1, 0, f"reset {i}")

    history = get_baseline_reset_history(limit=10)
    assert len(history) == 3
    assert [h["note"] for h in history] == ["reset 2", "reset 1", "reset 0"]


def test_baseline_reset_history_respects_limit(temp_db_path):
    for i in range(5):
        add_baseline_reset(f"2026-08-{10 + i:02d} 12:00:00", 1, 0, "r")

    history = get_baseline_reset_history(limit=2)
    assert len(history) == 2
