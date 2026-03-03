from datetime import datetime, timedelta, timezone
from pathlib import Path

import openpyxl

import database
import excel_export


async def test_generate_device_excel(sample_reading, tmp_path, monkeypatch):
    monkeypatch.setattr(excel_export, "EXPORT_DIR", tmp_path)
    path = await excel_export.generate_device_excel("abc123", "TestDevice")
    assert path is not None
    assert path.exists()
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    assert ws.max_row == 2  # header + 1 reading


async def test_generate_device_excel_no_readings(sample_device, tmp_path, monkeypatch):
    monkeypatch.setattr(excel_export, "EXPORT_DIR", tmp_path)
    path = await excel_export.generate_device_excel("abc123", "TestDevice")
    assert path is None


async def test_update_device_excel_creates_if_missing(sample_reading, tmp_path, monkeypatch):
    monkeypatch.setattr(excel_export, "EXPORT_DIR", tmp_path)
    now = datetime.now(timezone.utc)
    path = await excel_export.update_device_excel(
        "abc123", "TestDevice",
        now - timedelta(days=1), now + timedelta(days=1),
    )
    assert path is not None
    wb = openpyxl.load_workbook(path)
    assert wb.active.max_row == 2


async def test_update_device_excel_appends(sample_reading, tmp_path, monkeypatch):
    monkeypatch.setattr(excel_export, "EXPORT_DIR", tmp_path)

    # First: full build (1 reading)
    path = await excel_export.generate_device_excel("abc123", "TestDevice")
    wb = openpyxl.load_workbook(path)
    initial_rows = wb.active.max_row  # header + 1

    # Insert another reading
    await database.insert_reading(
        device_id="abc123", temperature=22.0, temp_unit="C",
        gravity=1.045, gravity_unit="G", battery=3.8,
    )

    now = datetime.now(timezone.utc)
    path = await excel_export.update_device_excel(
        "abc123", "TestDevice",
        now - timedelta(hours=1), now + timedelta(hours=1),
    )
    wb = openpyxl.load_workbook(path)
    # update appends all readings in the period to the existing file
    assert wb.active.max_row > initial_rows


async def test_get_device_excel_path_none(tmp_path, monkeypatch):
    monkeypatch.setattr(excel_export, "EXPORT_DIR", tmp_path)
    assert excel_export.get_device_excel_path("NoDevice") is None
