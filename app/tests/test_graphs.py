from datetime import datetime, timedelta, timezone

from graphs import generate_graph


def _make_readings(n=10, start_gravity=1.050, start_temp=20.0):
    """Generate n sample readings spread over the last day."""
    now = datetime.now(timezone.utc)
    readings = []
    for i in range(n):
        readings.append({
            "timestamp": (now - timedelta(hours=n - i)).isoformat(),
            "temperature": start_temp + i * 0.1,
            "temp_unit": "C",
            "gravity": start_gravity - i * 0.001,
            "gravity_unit": "G",
            "battery": 3.9,
        })
    return readings


def test_generate_graph_returns_png():
    buf = generate_graph(_make_readings(), "TestDevice", "day")
    data = buf.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_generate_graph_empty():
    buf = generate_graph([], "TestDevice", "day")
    data = buf.read()
    # Empty graph is still a valid PNG
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_generate_graph_custom_range():
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=5)
    buf = generate_graph(
        _make_readings(),
        "TestDevice",
        "custom",
        start_date=start,
        end_date=now,
    )
    assert buf.read()[:8] == b"\x89PNG\r\n\x1a\n"


def test_generate_graph_toggle_flags():
    readings = _make_readings()
    # Only gravity
    buf = generate_graph(readings, "D", "day", show_temperature=False, show_gravity=True)
    assert buf.read()[:8] == b"\x89PNG\r\n\x1a\n"

    # Only temperature
    buf = generate_graph(readings, "D", "day", show_temperature=True, show_gravity=False)
    assert buf.read()[:8] == b"\x89PNG\r\n\x1a\n"

    # Neither → empty graph
    buf = generate_graph(readings, "D", "day", show_temperature=False, show_gravity=False)
    assert buf.read()[:8] == b"\x89PNG\r\n\x1a\n"
