import matplotlib
matplotlib.use('Agg')  # Non-interactive backend

import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.ticker import MultipleLocator
from datetime import datetime, timezone
from io import BytesIO
from typing import List, Dict
from config import TZ_UTC7


PERIOD_CONFIG = {
    'hour': {
        'title': '1 час',
        'date_format': '%H:%M',
        'locator': mdates.MinuteLocator(interval=30),
    },
    'day': {
        'title': '1 день',
        'date_format': '%H:%M',
        'locator': mdates.MinuteLocator(interval=30),
    },
    'week': {
        'title': '1 неделя',
        'date_format': '%d %b',
        'locator': mdates.DayLocator(),
    },
    'month': {
        'title': '1 месяц',
        'date_format': '%d %b',
        'locator': mdates.DayLocator(interval=5),
    },
}

# Colors
COLOR_TEMP = '#FF4444'      # Red for temperature
COLOR_GRAVITY = '#FFD700'   # Yellow/gold for gravity
COLOR_BG = '#1a1a2e'        # Dark background
COLOR_GRID = '#3a3a5e'      # Grid color
COLOR_TEXT = '#ffffff'      # White text


def generate_graph(
    readings: List[Dict],
    device_name: str,
    period: str,
    show_temperature: bool = True,
    show_gravity: bool = True
) -> BytesIO:
    """
    Generate dual-axis temperature and gravity graph.
    """
    if not readings:
        return _generate_empty_graph(device_name, period)

    # Parse data
    timestamps = []
    temperatures = []
    gravities = []
    temp_unit = 'C'

    for r in readings:
        try:
            ts = r['timestamp']
            if isinstance(ts, str):
                ts = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            # Convert to UTC+7 for display (DB stores UTC)
            if ts.tzinfo:
                ts = ts.astimezone(TZ_UTC7)
            else:
                ts = ts.replace(tzinfo=timezone.utc).astimezone(TZ_UTC7)
            timestamps.append(ts)
            temperatures.append(r['temperature'])
            gravities.append(r['gravity'])
            temp_unit = r.get('temp_unit', 'C')
        except (KeyError, ValueError):
            continue

    if not timestamps:
        return _generate_empty_graph(device_name, period)

    # Check if at least one graph is enabled
    if not show_temperature and not show_gravity:
        return _generate_empty_graph(device_name, period)

    config = PERIOD_CONFIG.get(period, PERIOD_CONFIG['day'])

    # Create figure with dark background
    fig, ax1 = plt.subplots(figsize=(10, 6), facecolor=COLOR_BG)
    ax1.set_facecolor(COLOR_BG)

    # Configure grid
    ax1.grid(True, alpha=0.3, color=COLOR_GRID, linestyle='-')
    ax1.tick_params(colors=COLOR_TEXT)

    # X-axis formatting
    ax1.xaxis.set_major_formatter(mdates.DateFormatter(config['date_format']))
    ax1.xaxis.set_major_locator(config['locator'])
    ax1.tick_params(axis='x', labelsize=8, labelrotation=90)
    for label in ax1.get_xticklabels():
        label.set_color(COLOR_TEXT)

    plotted_lines = []
    labels = []

    # Temperature on left Y-axis
    if show_temperature and temperatures:
        ax1.fill_between(timestamps, temperatures, alpha=0.6, color=COLOR_TEMP)
        line1, = ax1.plot(timestamps, temperatures, color=COLOR_TEMP, linewidth=2)
        ax1.set_ylabel(f'°{temp_unit}', color=COLOR_TEMP, fontsize=12, fontweight='bold')
        ax1.tick_params(axis='y', labelcolor=COLOR_TEMP)

        # Set y-axis limits with padding
        temp_min, temp_max = min(temperatures), max(temperatures)
        temp_padding = (temp_max - temp_min) * 0.1 or 1
        ax1.set_ylim(temp_min - temp_padding, temp_max + temp_padding)

        plotted_lines.append(line1)
        labels.append('Температура')
    else:
        ax1.set_yticks([])
        ax1.set_ylabel('')

    # Gravity on right Y-axis
    if show_gravity and gravities:
        ax2 = ax1.twinx()
        ax2.set_facecolor(COLOR_BG)

        ax2.fill_between(timestamps, gravities, alpha=0.4, color=COLOR_GRAVITY)
        line2, = ax2.plot(timestamps, gravities, color=COLOR_GRAVITY, linewidth=2)
        ax2.set_ylabel('SG', color=COLOR_GRAVITY, fontsize=12, fontweight='bold')
        ax2.tick_params(axis='y', labelcolor=COLOR_GRAVITY)

        # Set y-axis limits with padding
        grav_min, grav_max = min(gravities), max(gravities)
        grav_range = grav_max - grav_min
        grav_padding = grav_range * 0.1 or 0.001
        ax2.set_ylim(grav_min - grav_padding, grav_max + grav_padding)

        # Use 0.0025 tick interval only for SG scale (range < 0.5)
        if grav_range < 0.5:
            ax2.yaxis.set_major_locator(MultipleLocator(0.0025))
            ax2.yaxis.set_major_formatter(plt.FormatStrFormatter('%.4f'))
        else:
            ax2.yaxis.set_major_formatter(plt.FormatStrFormatter('%.2f'))

        plotted_lines.append(line2)
        labels.append('Плотность')

    # Title
    fig.suptitle(
        f'{device_name} — {config["title"]}',
        fontsize=14,
        fontweight='bold',
        color=COLOR_TEXT
    )

    # Legend
    if plotted_lines:
        ax1.legend(plotted_lines, labels, loc='upper right',
                   facecolor=COLOR_BG, edgecolor=COLOR_GRID, labelcolor=COLOR_TEXT)

    # Adjust layout
    plt.tight_layout()

    # Save to buffer
    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor=COLOR_BG, edgecolor='none')
    buf.seek(0)
    plt.close(fig)

    return buf


def _generate_empty_graph(device_name: str, period: str) -> BytesIO:
    """Generate a placeholder graph when no data is available."""
    config = PERIOD_CONFIG.get(period, PERIOD_CONFIG['day'])

    fig, ax = plt.subplots(figsize=(10, 6), facecolor=COLOR_BG)
    ax.set_facecolor(COLOR_BG)

    ax.text(
        0.5, 0.5,
        'Нет данных за выбранный период',
        ha='center', va='center',
        fontsize=14,
        color=COLOR_TEXT,
        transform=ax.transAxes
    )
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    fig.suptitle(
        f'{device_name} — {config["title"]}',
        fontsize=14,
        fontweight='bold',
        color=COLOR_TEXT
    )

    buf = BytesIO()
    fig.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                facecolor=COLOR_BG, edgecolor='none')
    buf.seek(0)
    plt.close(fig)

    return buf
