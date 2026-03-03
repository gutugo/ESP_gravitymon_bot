from unittest.mock import AsyncMock, patch

from daily_report import (
    calculate_abv,
    get_battery_status,
    get_fermentation_status,
    get_signal_quality,
    generate_daily_report,
)


# ── Pure functions ──────────────────────────────────────────────────

def test_calculate_abv_normal():
    abv = calculate_abv(1.050, 1.010)
    assert abs(abv - 5.25) < 0.01


def test_calculate_abv_og_le_fg():
    assert calculate_abv(1.010, 1.050) == 0.0


def test_calculate_abv_og_le_one():
    assert calculate_abv(0.999, 0.998) == 0.0


def test_fermentation_active():
    label, code = get_fermentation_status(-0.015)
    assert code == "active"


def test_fermentation_slowing():
    label, code = get_fermentation_status(-0.005)
    assert code == "slowing"


def test_fermentation_complete():
    label, code = get_fermentation_status(-0.001)
    assert code == "complete"


def test_fermentation_stable():
    label, code = get_fermentation_status(0.002)
    assert code == "stable"


def test_battery_critical():
    _, code = get_battery_status(3.0)
    assert code == "critical"


def test_battery_low():
    _, code = get_battery_status(3.2)
    assert code == "low"


def test_battery_medium():
    _, code = get_battery_status(3.5)
    assert code == "medium"


def test_battery_good():
    _, code = get_battery_status(3.9)
    assert code == "good"


def test_signal_quality_excellent():
    assert get_signal_quality(-40) == "Отличный"


def test_signal_quality_good():
    assert get_signal_quality(-55) == "Хороший"


def test_signal_quality_medium():
    assert get_signal_quality(-65) == "Средний"


def test_signal_quality_weak():
    assert get_signal_quality(-80) == "Слабый"


def test_signal_quality_none():
    assert get_signal_quality(None) == "н/д"


# ── generate_daily_report (async, mocked DB) ───────────────────────

async def test_generate_daily_report_happy_path():
    stats = {
        "temp_min": 18.0,
        "temp_max": 22.0,
        "temp_avg": 20.0,
        "grav_min": 1.040,
        "grav_max": 1.050,
        "grav_avg": 1.045,
        "batt_min": 3.7,
        "batt_max": 3.9,
        "batt_avg": 3.8,
        "rssi_avg": -55.0,
        "reading_count": 90,
    }
    first = {"gravity": 1.050, "temperature": 20, "battery": 3.9, "timestamp": "2026-03-01 00:00:00", "interval_sec": 900}
    last = {"gravity": 1.040, "temperature": 21, "battery": 3.8, "timestamp": "2026-03-01 23:00:00"}

    with (
        patch("daily_report.database.get_24h_stats", AsyncMock(return_value=stats)),
        patch("daily_report.database.get_first_reading_24h", AsyncMock(return_value=first)),
        patch("daily_report.database.get_last_reading_in_period", AsyncMock(return_value=last)),
        patch("daily_report.database.get_alerts_24h", AsyncMock(return_value=[])),
        patch("daily_report.database.get_avg_interval", AsyncMock(return_value=900.0)),
        patch("daily_report.database.get_device_interval", AsyncMock(return_value=900)),
    ):
        report = await generate_daily_report("abc123", "TestDevice")

    assert report is not None
    assert "ЕЖЕДНЕВНЫЙ ОТЧЁТ" in report
    assert "TestDevice" in report
    assert "18.0°C" in report
    assert "1.0500" in report


async def test_generate_daily_report_no_stats():
    with patch("daily_report.database.get_24h_stats", AsyncMock(return_value=None)):
        report = await generate_daily_report("abc123", "TestDevice")
    assert report is None
