"""Blank-install helpers: Items.csv master creation."""

from pathlib import Path

import pandas as pd

import data_manager as dm
from data_manager import INVENTORY_COLUMNS


def test_ensure_items_csv_master_creates_file(tmp_path, monkeypatch):
    monkeypatch.setattr(dm, 'DATA_DIR', str(tmp_path))
    inventory = pd.DataFrame([
        ['lager', 'Lager', 10.0, 1.5, 4.0, 'Pint', 'Draught',
         False, False, 0.0, 'Beer - Draught'],
    ], columns=INVENTORY_COLUMNS)
    path = dm.ensure_items_csv_master(inventory)
    assert path is not None
    assert Path(path).exists()
    text = Path(path).read_text(encoding='utf-8')
    assert 'Name,Division,Unit,Total Stock,Total Value' in text
    assert 'Lager' in text


def test_ensure_items_csv_master_does_nothing_when_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(dm, 'DATA_DIR', str(tmp_path))
    empty = pd.DataFrame(columns=INVENTORY_COLUMNS)
    assert dm.ensure_items_csv_master(empty) is None
    assert not (tmp_path / 'Items.csv').exists()
