import openpyxl
from openpyxl.styles import Font, Alignment
from datetime import datetime, timezone
from pathlib import Path
import logging

import database
from config import TZ_UTC7

logger = logging.getLogger(__name__)

EXPORT_DIR = Path("/data/exports")


async def generate_device_excel(device_id: str, device_name: str) -> Path | None:
    """Generate Excel file with all device data."""
    # Ensure export directory exists
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    # Get all readings for the device
    readings = await database.get_all_readings_for_device(device_id)

    if not readings:
        logger.warning(f"No readings found for device {device_name}")
        return None

    # Create workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Device Data"

    # Headers
    headers = [
        "Timestamp (UTC+7)",
        "Temperature",
        "Unit",
        "Gravity (SG)",
        "Battery (V)",
        "RSSI",
        "Angle",
        "Interval (s)"
    ]
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)
        cell.alignment = Alignment(horizontal='center')

    # Data rows
    for row_idx, reading in enumerate(readings, 2):
        ts = reading['timestamp']
        if isinstance(ts, str):
            ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        if ts.tzinfo:
            ts = ts.astimezone(TZ_UTC7)
        else:
            ts = ts.replace(tzinfo=timezone.utc).astimezone(TZ_UTC7)

        ws.cell(row=row_idx, column=1, value=ts.strftime('%Y-%m-%d %H:%M:%S'))
        ws.cell(row=row_idx, column=2, value=reading['temperature'])
        ws.cell(row=row_idx, column=3, value=reading.get('temp_unit', 'C'))
        ws.cell(row=row_idx, column=4, value=reading['gravity'])
        ws.cell(row=row_idx, column=5, value=reading['battery'])
        ws.cell(row=row_idx, column=6, value=reading.get('rssi'))
        ws.cell(row=row_idx, column=7, value=reading.get('angle'))
        ws.cell(row=row_idx, column=8, value=reading.get('interval_sec'))

    # Auto-width columns
    for col in ws.columns:
        max_length = max(len(str(cell.value or '')) for cell in col)
        ws.column_dimensions[col[0].column_letter].width = max_length + 2

    # Save file
    safe_name = device_name.replace(' ', '_').replace('/', '_')
    filename = f"{safe_name}_data.xlsx"
    filepath = EXPORT_DIR / filename
    wb.save(filepath)

    logger.info(f"Excel export saved to {filepath}")
    return filepath


def get_device_excel_path(device_name: str) -> Path | None:
    """Get path to existing Excel file for a device."""
    safe_name = device_name.replace(' ', '_').replace('/', '_')
    filepath = EXPORT_DIR / f"{safe_name}_data.xlsx"
    return filepath if filepath.exists() else None
