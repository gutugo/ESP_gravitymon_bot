import openpyxl
from openpyxl.styles import Font, Alignment
from datetime import datetime, timezone
from pathlib import Path
import logging

import database
from config import TZ_UTC7

logger = logging.getLogger(__name__)

EXPORT_DIR = Path("/data/exports")

HEADERS = [
    "Timestamp (UTC+7)",
    "Temperature",
    "Unit",
    "Gravity (SG)",
    "Battery (V)",
    "RSSI",
    "Angle",
    "Interval (s)"
]


def _reading_to_row(reading: dict) -> list:
    """Convert a reading dict to a list of cell values."""
    ts = reading['timestamp']
    if isinstance(ts, str):
        ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
    if ts.tzinfo:
        ts = ts.astimezone(TZ_UTC7)
    else:
        ts = ts.replace(tzinfo=timezone.utc).astimezone(TZ_UTC7)

    return [
        ts.strftime('%Y-%m-%d %H:%M:%S'),
        reading['temperature'],
        reading.get('temp_unit', 'C'),
        reading['gravity'],
        reading['battery'],
        reading.get('rssi'),
        reading.get('angle'),
        reading.get('interval_sec'),
    ]


def _get_filepath(device_name: str) -> Path:
    """Get Excel file path for a device."""
    safe_name = device_name.replace(' ', '_').replace('/', '_')
    return EXPORT_DIR / f"{safe_name}_data.xlsx"


def _auto_width(ws):
    """Auto-fit column widths."""
    for col in ws.columns:
        max_length = max(len(str(cell.value or '')) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = max_length + 2


async def generate_device_excel(device_id: str, device_name: str) -> Path | None:
    """Generate Excel file with all device data (full rebuild)."""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    readings = await database.get_all_readings_for_device(device_id)
    if not readings:
        logger.warning(f"No readings found for device {device_name}")
        return None

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Device Data"

    for col, header in enumerate(HEADERS, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center')

    for row_idx, reading in enumerate(readings, 2):
        for col_idx, value in enumerate(_reading_to_row(reading), 1):
            ws.cell(row=row_idx, column=col_idx, value=value)

    _auto_width(ws)

    filepath = _get_filepath(device_name)
    wb.save(filepath)

    logger.info(f"Excel full export saved to {filepath} ({len(readings)} rows)")
    return filepath


async def update_device_excel(device_id: str, device_name: str, start_utc: datetime, end_utc: datetime) -> Path | None:
    """Append new readings from a period to the existing Excel file.

    If the file doesn't exist, creates it with all historical data.
    """
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = _get_filepath(device_name)

    if not filepath.exists():
        logger.info(f"No existing Excel for {device_name}, generating full export")
        return await generate_device_excel(device_id, device_name)

    new_readings = await database.get_readings_for_device_period(device_id, start_utc, end_utc)
    if not new_readings:
        logger.info(f"No new readings for {device_name} in period, Excel unchanged")
        return filepath

    wb = openpyxl.load_workbook(filepath)
    ws = wb.active

    next_row = ws.max_row + 1
    for reading in new_readings:
        for col_idx, value in enumerate(_reading_to_row(reading), 1):
            ws.cell(row=next_row, column=col_idx, value=value)
        next_row += 1

    _auto_width(ws)
    wb.save(filepath)

    logger.info(f"Excel updated for {device_name}: appended {len(new_readings)} rows (total {ws.max_row - 1})")
    return filepath


def get_device_excel_path(device_name: str) -> Path | None:
    """Get path to existing Excel file for a device."""
    filepath = _get_filepath(device_name)
    return filepath if filepath.exists() else None
