"""Smoke tests for xlsx_service — local file I/O, no Google API calls."""
from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path

import pytest

# Point xlsx_service at a temp file so tests don't touch the real ERP bot.xlsx
@pytest.fixture(autouse=True)
def tmp_xlsx(monkeypatch, tmp_path):
    xlsx_file = str(tmp_path / "test.xlsx")
    monkeypatch.setenv("XLSX_PATH", xlsx_file)
    # Reload settings and xlsx_service so the patched env is picked up
    import importlib
    import app.config as cfg_mod
    import app.services.xlsx_service as svc_mod

    # Re-instantiate settings with the new env var
    monkeypatch.setattr(cfg_mod, "settings", cfg_mod.Settings())  # type: ignore[call-arg]
    importlib.reload(svc_mod)
    yield xlsx_file


@pytest.fixture
def svc():
    from app.services import xlsx_service
    return xlsx_service


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_append_and_read(svc):
    row_num = run(svc.append_row("收據記錄", ["2026-07-05", "12:00", "Alice", "發票", "全聯", "水", 100, 5, "INV-001", "", "高", "G1", ""]))
    assert row_num == 2  # row 1 = header, row 2 = first data row

    rows = run(svc.read_all_rows("收據記錄"))
    assert len(rows) == 1
    assert rows[0][8] == "INV-001"  # col I = 單號


def test_append_multiple(svc):
    run(svc.append_row("庫存台帳", ["青蔥", "", "把", "10", "50", "2026-07-05", "", ""]))
    run(svc.append_row("庫存台帳", ["豬肉", "", "斤", "5", "20", "2026-07-05", "", ""]))
    rows = run(svc.read_all_rows("庫存台帳"))
    assert len(rows) == 2
    assert rows[0][0] == "青蔥"
    assert rows[1][0] == "豬肉"


def test_update_cells(svc):
    run(svc.append_row("庫存台帳", ["青蔥", "", "把", "10", "50", "2026-07-01", "", ""]))
    # Update 目前庫存 (col 4) and 最後更新 (col 5), row 2
    run(svc.update_cells("庫存台帳", 2, {4: 35, 5: "2026-07-05 10:00"}))
    rows = run(svc.read_all_rows("庫存台帳"))
    assert rows[0][4] == "35"
    assert rows[0][5] == "2026-07-05 10:00"


def test_find_row_by_col(svc):
    run(svc.append_row("收據記錄", ["2026-07-05", "", "", "", "", "", "", "", "INV-999", "", "", "", ""]))
    row_num = run(svc.find_row_by_col("收據記錄", 8, "INV-999"))
    assert row_num == 2


def test_find_row_by_col_not_found(svc):
    result = run(svc.find_row_by_col("收據記錄", 8, "DOES-NOT-EXIST"))
    assert result is None


def test_missing_sheet_auto_created(svc):
    """Reading a sheet that exists in SHEET_HEADERS but not yet in file should return []."""
    rows = run(svc.read_all_rows("庫存異動"))
    assert rows == []
