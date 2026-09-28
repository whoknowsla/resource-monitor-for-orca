"""Graphics processor usage, temperature, and memory.

NVIDIA cards are read through nvidia-smi. AMD cards are read from the amdgpu
driver's files in sysfs. Other GPUs do not publish usage without root access,
so they are not reported.
"""

from __future__ import annotations

import glob
import os
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

NVIDIA_SMI_TIMEOUT_SECONDS = 5
AMD_VENDOR_ID = "0x1002"
DRM_ROOT = "/sys/class/drm"
_MIB = 1024 * 1024
_MILLIDEGREES = 1000.0
_NOT_AVAILABLE_MARKERS = ("[N/A]", "N/A", "[Not Supported]", "")


@dataclass(frozen=True)
class GpuTelemetry:
    """One GPU's readings. Any value may be None when the driver does not report it."""

    utilization: float | None
    temperature: float | None
    memory_used: int | None
    memory_total: int | None


class GpuProvider(Protocol):
    """Collects telemetry for one kind of GPU."""

    def collect(self) -> list[GpuTelemetry] | None:
        """Returns None when no such GPU exists, or an empty list when reading failed."""


def _number(text: str) -> float | None:
    text = text.strip()
    if text in _NOT_AVAILABLE_MARKERS:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_nvidia_smi(output: str) -> list[GpuTelemetry]:
    """Parses csv,noheader,nounits output for utilization, temperature, and memory in MiB."""

    items = []
    for line in output.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) < 4:
            continue
        used, total = _number(fields[2]), _number(fields[3])
        items.append(
            GpuTelemetry(
                utilization=_number(fields[0]),
                temperature=_number(fields[1]),
                memory_used=int(used * _MIB) if used is not None else None,
                memory_total=int(total * _MIB) if total is not None else None,
            )
        )
    return items


def _run(command: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
        env={**os.environ, "LC_ALL": "C"},
    )


class NvidiaSmiProvider:
    """Reads NVIDIA GPUs through nvidia-smi."""

    QUERY = "--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total"

    def __init__(
        self,
        which: Callable[[str], str | None] = shutil.which,
        run: Callable[[Sequence[str], float], subprocess.CompletedProcess[str]] = _run,
    ) -> None:
        self._which = which
        self._run = run

    def collect(self) -> list[GpuTelemetry] | None:
        path = self._which("nvidia-smi")
        if not path:
            return None
        try:
            result = self._run(
                [path, self.QUERY, "--format=csv,noheader,nounits"],
                NVIDIA_SMI_TIMEOUT_SECONDS,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        return parse_nvidia_smi(result.stdout)


def _read_number(path: str) -> float | None:
    try:
        with open(path, encoding="ascii") as file:
            return _number(file.read())
    except (OSError, UnicodeDecodeError):
        return None


class AmdSysfsProvider:
    """Reads AMD GPUs from the amdgpu driver's sysfs files."""

    def __init__(self, drm_root: str = DRM_ROOT) -> None:
        self._drm_root = drm_root

    def _devices(self) -> list[str]:
        devices = []
        for card in sorted(glob.glob(os.path.join(self._drm_root, "card[0-9]*"))):
            if not os.path.basename(card)[len("card") :].isdigit():
                continue
            device = os.path.join(card, "device")
            try:
                with open(os.path.join(device, "vendor"), encoding="ascii") as file:
                    vendor = file.read().strip()
            except OSError:
                continue
            if vendor == AMD_VENDOR_ID and os.path.exists(os.path.join(device, "gpu_busy_percent")):
                devices.append(device)
        return devices

    @staticmethod
    def _temperature(device: str) -> float | None:
        for sensor in sorted(glob.glob(os.path.join(device, "hwmon", "hwmon*", "temp1_input"))):
            value = _read_number(sensor)
            if value is not None:
                return value / _MILLIDEGREES
        return None

    def collect(self) -> list[GpuTelemetry] | None:
        devices = self._devices()
        if not devices:
            return None
        items = []
        for device in devices:
            used = _read_number(os.path.join(device, "mem_info_vram_used"))
            total = _read_number(os.path.join(device, "mem_info_vram_total"))
            items.append(
                GpuTelemetry(
                    utilization=_read_number(os.path.join(device, "gpu_busy_percent")),
                    temperature=self._temperature(device),
                    memory_used=int(used) if used is not None else None,
                    memory_total=int(total) if total is not None else None,
                )
            )
        return items


@dataclass(frozen=True)
class GpuReadings:
    """Telemetry from every provider, plus whether any provider was present or failed."""

    items: tuple[GpuTelemetry, ...]
    has_provider: bool
    has_failure: bool


def default_providers() -> list[GpuProvider]:
    """Returns the providers tried, in order."""

    return [NvidiaSmiProvider(), AmdSysfsProvider()]


def read_gpus(providers: Sequence[GpuProvider] | None = None) -> GpuReadings:
    """Collects telemetry from all providers. Blocks; call off the main thread."""

    items: list[GpuTelemetry] = []
    has_provider = False
    has_failure = False
    for provider in providers if providers is not None else default_providers():
        telemetry = provider.collect()
        if telemetry is None:
            continue
        has_provider = True
        if not telemetry:
            has_failure = True
        items.extend(telemetry)
    return GpuReadings(items=tuple(items), has_provider=has_provider, has_failure=has_failure)
