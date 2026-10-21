#!/usr/bin/env python3
"""Tests for runtime retirement of stock items."""

import sqlite3

import pytest

import categories
import data_manager as dm
import retirement


@pytest.fixture
def db(tmp_path, monkeypatch):
    path = tmp_path / "barstock.db"
    monkeypatch.setattr(dm, "DB_PATH", str(path))
    monkeypatch.setattr(dm, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(dm.messagebox, "showerror", lambda *a, **k: None)
    conn = sqlite3.connect(path)
    dm._init_db_schema(conn)
    conn.commit()
    conn.close()
    retirement.reset_cache()
    yield path
    retirement.reset_cache()


def test_retire_round_trip(db):
    assert not categories.is_delisted("house_ale")
    retirement.retire_item("House_Ale")
    retirement.reset_cache()

    assert retirement.is_retired("house_ale")
    assert categories.is_delisted("house_ale")

    # Persisted, not just cached.
    retirement.reset_cache()
    assert retirement.load_retired_items() == {"house_ale"}

    retirement.unretire_item("house_ale")
    retirement.reset_cache()
    assert not retirement.is_retired("house_ale")
    assert not categories.is_delisted("house_ale")


def test_static_delistings_still_apply(db):
    assert categories.is_delisted("belhaven_best")
    assert not retirement.is_retired("belhaven_best")


def test_broken_setting_does_not_break_views(db):
    dm.set_setting("retired_items", "not json")
    retirement.reset_cache()
    assert retirement.load_retired_items() == set()
    assert not categories.is_delisted("anything")
