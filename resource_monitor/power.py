"""Battery charge, state, and estimated time remaining.

Read straight from sysfs, so this needs no helper program and no third-party
module, like the processor, memory, and uptime readers.

Two families of attributes exist and a battery exposes one or the other:
``energy_*`` with ``power_now`` (microwatt hours and microwatts), or
``charge_*`` with ``current_now`` (microamp hours and microamps). Within one
family the units cancel, so the time remaining is a division either way; the
families are never mixed, because that would need the voltage and would turn
a reading into a guess.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

POWER_SUPPLY_ROOT = "/sys/class/power_supply"

# Values of the sysfs "status" attribute we recognise. Anything else, and the
# attribute's absence, is reported as unknown rather than assumed.
_STATUS_CHARGING = "charging"
_STATUS_DISCHARGING = "discharging"
_STATUS_FULL = "full"
_STATUS_NOT_CHARGING = "not charging"


class BatteryState(Enum):
    """What the battery is doing."""

    ABSENT = "absent"
    CHARGING = "charging"
    DISCHARGING = "discharging"
    FULL = "full"
    NOT_CHARGING = "not charging"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BatteryStatus:
    """A reading of every battery in the machine, taken together."""

    state: BatteryState
    percent: float | None
    seconds_left: int | None
    on_ac: bool | None


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


def _supply_type(directory: str) -> str:
    return _read_text(os.path.join(directory, "type")).lower()


def _entries(root: str) -> list[str]:
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [os.path.join(root, name) for name in names]


def _reserve(directory: str) -> tuple[float | None, float | None, float | None]:
    """Returns (now, full, rate) in one unit family, or Nones.

    ``energy_full_design`` is deliberately not used as a fallback for
    ``energy_full``: it describes the battery when it was new, so on a worn
    battery it reports a percentage that never reaches 100 and a time
    remaining that never arrives.
    """

    for now_name, full_name, rate_name in (
        ("energy_now", "energy_full", "power_now"),
        ("charge_now", "charge_full", "current_now"),
    ):
        now = _read_number(os.path.join(directory, now_name))
        full = _read_number(os.path.join(directory, full_name))
        if now is None or full is None:
            continue
        rate = _read_number(os.path.join(directory, rate_name))
        return now, full, abs(rate) if rate is not None else None
    return None, None, None


def _state_from(statuses: list[str]) -> BatteryState:
    """Decides one state for the machine from each battery's status.

    Charging wins over discharging: on a machine with two batteries one can
    feed the other, and "charging" is the answer the user is really asking
    for when they plug the mains in.
    """

    if any(status == _STATUS_CHARGING for status in statuses):
        return BatteryState.CHARGING
    if any(status == _STATUS_DISCHARGING for status in statuses):
        return BatteryState.DISCHARGING
    if statuses and all(status == _STATUS_FULL for status in statuses):
        return BatteryState.FULL
    if any(status == _STATUS_NOT_CHARGING for status in statuses):
        return BatteryState.NOT_CHARGING
    return BatteryState.UNKNOWN


def read_battery(root: str = POWER_SUPPLY_ROOT) -> BatteryStatus:
    """Returns the state of the machine's batteries, or that there are none."""

    batteries: list[str] = []
    on_ac: bool | None = None

    for directory in _entries(root):
        kind = _supply_type(directory)
        if kind == "battery":
            batteries.append(directory)
        elif kind == "mains":
            online = _read_number(os.path.join(directory, "online"))
            if online is not None:
                on_ac = bool(online) or bool(on_ac)

    if not batteries:
        return BatteryStatus(BatteryState.ABSENT, None, None, on_ac)

    statuses = [_read_text(os.path.join(d, "status")).lower() for d in batteries]
    state = _state_from(statuses)

    total_now = total_full = total_rate = 0.0
    have_reserve = have_rate = False
    capacities: list[float] = []

    for directory in batteries:
        now, full, rate = _reserve(directory)
        if now is not None and full is not None and full > 0:
            total_now += now
            total_full += full
            have_reserve = True
            if rate is not None and rate > 0:
                total_rate += rate
                have_rate = True
        capacity = _read_number(os.path.join(directory, "capacity"))
        if capacity is not None:
            capacities.append(capacity)

    if have_reserve:
        percent: float | None = total_now / total_full * 100.0
    elif capacities:
        # No energy or charge attributes: fall back to the kernel's own
        # percentage, averaged over the batteries present.
        percent = sum(capacities) / len(capacities)
    else:
        percent = None

    seconds_left: int | None = None
    if have_reserve and have_rate and total_rate > 0:
        if state is BatteryState.DISCHARGING:
            seconds_left = int(total_now / total_rate * 3600)
        elif state is BatteryState.CHARGING:
            seconds_left = int(max(0.0, total_full - total_now) / total_rate * 3600)

    return BatteryStatus(state, percent, seconds_left, on_ac)
