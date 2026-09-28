"""Reads processor, memory, uptime, and operating system data from the kernel.

Everything here is plain file parsing, so the extension needs no third-party
Python packages. Readers take the file path as a parameter for testing.
"""

from __future__ import annotations

import os
import platform
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

PROC_STAT = "/proc/stat"
PROC_MEMINFO = "/proc/meminfo"
PROC_UPTIME = "/proc/uptime"

# Long enough for a stable reading at the kernel's 100 Hz tick, short enough
# that the answer still feels immediate.
CPU_SAMPLE_SECONDS = 0.3

_KIB = 1024

# /proc/stat columns: user nice system idle iowait irq softirq steal guest guest_nice.
# guest and guest_nice are already included in user and nice.
_IDLE_COLUMN = 3
_IOWAIT_COLUMN = 4
_COUNTED_COLUMNS = 8


@dataclass(frozen=True)
class CpuTimes:
    """Cumulative busy and total jiffies for one processor or for all of them."""

    busy: int
    total: int


@dataclass(frozen=True)
class CpuSnapshot:
    """Processor times at one moment: the aggregate plus each logical processor."""

    overall: CpuTimes
    per_core: tuple[CpuTimes, ...]


@dataclass(frozen=True)
class CpuLoad:
    """Processor load in percent over a sampling interval."""

    average: float
    per_core: tuple[float, ...]


@dataclass(frozen=True)
class MemoryUsage:
    """Physical memory and swap, in bytes."""

    total: int
    available: int
    swap_total: int
    swap_free: int

    @property
    def used(self) -> int:
        """Memory applications cannot get back without swapping."""

        return max(0, self.total - self.available)

    @property
    def swap_used(self) -> int:
        """Swap in use."""

        return max(0, self.swap_total - self.swap_free)


@dataclass(frozen=True)
class OsInfo:
    """Distribution, architecture, kernel, and graphical session."""

    name: str
    architecture: str
    kernel: str
    desktop: str
    session_type: str


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as file:
        return file.read()


def _parse_cpu_line(fields: list[str]) -> CpuTimes:
    values = [int(value) for value in fields[:_COUNTED_COLUMNS]]
    total = sum(values)
    idle = values[_IDLE_COLUMN] + (values[_IOWAIT_COLUMN] if len(values) > _IOWAIT_COLUMN else 0)
    return CpuTimes(busy=total - idle, total=total)


def parse_cpu_snapshot(text: str) -> CpuSnapshot:
    """Parses /proc/stat content."""

    overall: CpuTimes | None = None
    per_core: list[CpuTimes] = []
    for line in text.splitlines():
        if not line.startswith("cpu"):
            continue
        label, *fields = line.split()
        if label == "cpu":
            overall = _parse_cpu_line(fields)
        else:
            per_core.append(_parse_cpu_line(fields))
    if overall is None:
        raise ValueError("No aggregate cpu line in /proc/stat")
    return CpuSnapshot(overall=overall, per_core=tuple(per_core))


def read_cpu_snapshot(path: str = PROC_STAT) -> CpuSnapshot:
    """Reads the current processor times."""

    return parse_cpu_snapshot(_read_text(path))


def load_between(before: CpuTimes, after: CpuTimes) -> float:
    """Returns the busy percentage between two readings."""

    total = after.total - before.total
    if total <= 0:
        return 0.0
    busy = max(0, after.busy - before.busy)
    return min(100.0, busy / total * 100.0)


def sample_cpu_load(
    interval: float = CPU_SAMPLE_SECONDS,
    reader: Callable[[], CpuSnapshot] = read_cpu_snapshot,
    sleep: Callable[[float], None] = time.sleep,
) -> CpuLoad:
    """Measures processor load over interval seconds. Blocks; call off the main thread."""

    before = reader()
    sleep(interval)
    after = reader()
    cores = tuple(
        load_between(old, new) for old, new in zip(before.per_core, after.per_core, strict=False)
    )
    return CpuLoad(average=load_between(before.overall, after.overall), per_core=cores)


def parse_meminfo(text: str) -> MemoryUsage:
    """Parses /proc/meminfo content."""

    values: dict[str, int] = {}
    for line in text.splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            values[key.strip()] = int(parts[0]) * _KIB
    if "MemTotal" not in values:
        raise ValueError("No MemTotal in /proc/meminfo")
    available = values.get("MemAvailable")
    if available is None:
        # Kernels before 3.14 lack MemAvailable; this is the classic estimate.
        available = values.get("MemFree", 0) + values.get("Buffers", 0) + values.get("Cached", 0)
    return MemoryUsage(
        total=values["MemTotal"],
        available=available,
        swap_total=values.get("SwapTotal", 0),
        swap_free=values.get("SwapFree", 0),
    )


def read_memory(path: str = PROC_MEMINFO) -> MemoryUsage:
    """Reads current memory usage."""

    return parse_meminfo(_read_text(path))


def parse_uptime(text: str) -> float:
    """Parses /proc/uptime content into seconds since boot."""

    return float(text.split(maxsplit=1)[0])


def read_uptime(path: str = PROC_UPTIME) -> float:
    """Reads the number of seconds since boot, including time spent suspended."""

    return parse_uptime(_read_text(path))


def _distribution_name() -> str:
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        return "Linux"
    return release.get("PRETTY_NAME") or release.get("NAME") or "Linux"


def _session_type(environ: Mapping[str, str]) -> str:
    session = environ.get("XDG_SESSION_TYPE", "")
    if not session:
        session = "wayland" if environ.get("WAYLAND_DISPLAY") else ""
    if not session and environ.get("DISPLAY"):
        session = "x11"
    names = {"x11": "X11", "wayland": "Wayland", "tty": "TTY"}
    return names.get(session.lower(), session)


def read_os_info(
    environ: Mapping[str, str] = os.environ,
    distribution: Callable[[], str] = _distribution_name,
) -> OsInfo:
    """Returns operating system details."""

    desktop = environ.get("XDG_CURRENT_DESKTOP") or environ.get("DESKTOP_SESSION") or ""
    return OsInfo(
        name=distribution(),
        architecture=platform.machine(),
        kernel=platform.release(),
        desktop=desktop.replace(":", ", "),
        session_type=_session_type(environ),
    )
