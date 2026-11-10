"""Load averages and component temperatures.

Both come from sysfs and procfs, so this needs no helper program and no
third-party module.

Load average is not the same reading as processor load, and both are worth
having. Processor load is how busy the cores are right now; the load average
is how many tasks have been waiting over the last minute, five minutes, and
fifteen. A machine can sit at a low processor load with a high load average
when tasks are blocked on disk or network, which is exactly the state where a
screen reader user wants to know why everything feels slow.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

PROC_LOADAVG = "/proc/loadavg"
THERMAL_ROOT = "/sys/class/thermal"
HWMON_ROOT = "/sys/class/hwmon"

# Readings outside this range are sensors reporting a sentinel rather than a
# temperature: disconnected probes commonly read -274 or 0, and some report a
# fixed critical value in the thousands.
_MIN_PLAUSIBLE_CELSIUS = -40.0
_MAX_PLAUSIBLE_CELSIUS = 150.0

# How many temperatures to report. A desktop can expose dozens of near
# identical sensors, and reading them all aloud is worse than reading none.
MAX_TEMPERATURES = 4

# hwmon chips worth naming first: these are the processor and GPU packages,
# which is what the question is usually about.
_PREFERRED_CHIPS = ("coretemp", "k10temp", "zenpower", "cpu_thermal", "amdgpu", "nouveau")


@dataclass(frozen=True)
class LoadAverages:
    """Tasks waiting, averaged over one, five, and fifteen minutes."""

    one: float
    five: float
    fifteen: float


@dataclass(frozen=True)
class Temperature:
    """One sensor reading, in degrees Celsius."""

    label: str
    celsius: float


@dataclass(frozen=True)
class SystemLoad:
    """Load averages and whatever temperatures could be read."""

    averages: LoadAverages | None
    temperatures: tuple[Temperature, ...]


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _read_number(path: str) -> float | None:
    text = _read_text(path)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_loadavg(text: str) -> LoadAverages | None:
    """Returns the three load averages from the contents of /proc/loadavg."""

    fields = text.split()
    if len(fields) < 3:
        return None
    try:
        one, five, fifteen = (float(field) for field in fields[:3])
    except ValueError:
        return None
    return LoadAverages(one, five, fifteen)


def read_load_averages(path: str = PROC_LOADAVG) -> LoadAverages | None:
    """Returns the load averages, or None if they cannot be read."""

    return parse_loadavg(_read_text(path))


def _plausible(celsius: float) -> bool:
    return _MIN_PLAUSIBLE_CELSIUS <= celsius <= _MAX_PLAUSIBLE_CELSIUS


def _hwmon_temperatures(root: str) -> list[Temperature]:
    readings: list[Temperature] = []
    try:
        chips = sorted(os.listdir(root))
    except OSError:
        return readings

    for chip in chips:
        directory = os.path.join(root, chip)
        chip_name = _read_text(os.path.join(directory, "name")) or chip
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for name in names:
            if not (name.startswith("temp") and name.endswith("_input")):
                continue
            millidegrees = _read_number(os.path.join(directory, name))
            if millidegrees is None:
                continue
            celsius = millidegrees / 1000.0
            if not _plausible(celsius):
                continue
            label = _read_text(
                os.path.join(directory, name.replace("_input", "_label"))
            )
            readings.append(
                Temperature(f"{chip_name} {label}".strip() if label else chip_name, celsius)
            )
    return readings


def _thermal_zone_temperatures(root: str) -> list[Temperature]:
    readings: list[Temperature] = []
    try:
        zones = sorted(os.listdir(root))
    except OSError:
        return readings

    for zone in zones:
        if not zone.startswith("thermal_zone"):
            continue
        directory = os.path.join(root, zone)
        millidegrees = _read_number(os.path.join(directory, "temp"))
        if millidegrees is None:
            continue
        celsius = millidegrees / 1000.0
        if not _plausible(celsius):
            continue
        readings.append(
            Temperature(_read_text(os.path.join(directory, "type")) or zone, celsius)
        )
    return readings


def _is_preferred(reading: Temperature) -> bool:
    """Returns whether this sensor is a processor or graphics sensor."""

    label = reading.label.lower()
    return any(label.startswith(chip) for chip in _PREFERRED_CHIPS)


def _rank(reading: Temperature) -> tuple[int, float]:
    """Sorts preferred chips first, then hottest first."""

    label = reading.label.lower()
    for position, chip in enumerate(_PREFERRED_CHIPS):
        if label.startswith(chip):
            return position, -reading.celsius
    return len(_PREFERRED_CHIPS), -reading.celsius


def read_temperatures(
    hwmon_root: str = HWMON_ROOT,
    thermal_root: str = THERMAL_ROOT,
    limit: int = MAX_TEMPERATURES,
) -> tuple[Temperature, ...]:
    """Returns the most useful temperatures, hottest first within each chip.

    hwmon is preferred because its sensors carry labels, so a reading can be
    attributed to the processor package rather than to "thermal_zone3". The
    thermal zones are a fallback for machines that expose nothing else.
    """

    readings = _hwmon_temperatures(hwmon_root)
    if not readings:
        readings = _thermal_zone_temperatures(thermal_root)

    # When a processor or graphics sensor is present, report only those. A
    # desktop exposes temperatures for network cards, drives and chipsets,
    # and padding the list out with them buries the two readings the question
    # was actually about -- which matters more when the list is spoken than
    # when it is seen.
    preferred = [reading for reading in readings if _is_preferred(reading)]
    if preferred:
        readings = preferred

    seen: set[str] = set()
    unique: list[Temperature] = []
    for reading in sorted(readings, key=_rank):
        key = reading.label.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(reading)
    return tuple(unique[:limit]) if limit > 0 else tuple(unique)


def read_system_load(
    loadavg_path: str = PROC_LOADAVG,
    hwmon_root: str = HWMON_ROOT,
    thermal_root: str = THERMAL_ROOT,
) -> SystemLoad:
    """Returns the load averages and the temperatures worth reporting."""

    return SystemLoad(
        read_load_averages(loadavg_path),
        read_temperatures(hwmon_root, thermal_root),
    )
