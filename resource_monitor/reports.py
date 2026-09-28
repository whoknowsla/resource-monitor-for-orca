"""Turns resource readings into the sentences Orca presents.

Wording follows the NVDA Resource Monitor add-on so that its users hear what
they expect, with Linux terms where Windows ones would be wrong.
"""

from __future__ import annotations

from collections.abc import Sequence

from .disks import DriveReport
from .formatting import (
    format_duration,
    format_percent,
    format_size,
    format_temperature,
    percent_of,
)
from .gpu import GpuReadings, GpuTelemetry
from .i18n import _
from .system_info import CpuLoad, MemoryUsage, OsInfo
from .wifi import UNKNOWN_SECURITY, WifiState, WifiStatus


def _unknown() -> str:
    # Translators: Used in place of a value the system did not report.
    return _("unknown")


def summary_report(memory: MemoryUsage, cpu: CpuLoad) -> str:
    """Returns used RAM and average processor load."""

    # Translators: presents the overall summary of resource usage, such as CPU load and RAM usage.
    return _("{ramPercent}% RAM used, CPU at {cpuPercent}%.").format(
        ramPercent=format_percent(percent_of(memory.used, memory.total)),
        cpuPercent=format_percent(cpu.average),
    )


def cpu_report(load: CpuLoad) -> str:
    """Returns average processor load and, on multi-core systems, the load of each core."""

    average = format_percent(load.average)
    if len(load.per_core) <= 1:
        # Translators: Shows average load of the processor on single-core systems.
        return _("{avgLoad}% CPU load.").format(avgLoad=average)
    cores = ", ".join(
        # Translators: Shows the load of one CPU core (example: Core 1: 50%).
        _("Core {coreNumber}: {corePercent}%").format(
            coreNumber=number,
            corePercent=format_percent(core),
        )
        for number, core in enumerate(load.per_core, start=1)
    )
    # Translators: Shows average load of the processor and the load for each core
    # on multi-core systems.
    return _("{avgLoad}% average CPU load, {cores}.").format(avgLoad=average, cores=cores)


def memory_report(memory: MemoryUsage) -> str:
    """Returns used and total physical memory and swap."""

    # Translators: Shows RAM (physical memory) usage.
    physical = _("Physical: {physicalUsed} of {physicalTotal} used ({physicalPercent}%).").format(
        physicalUsed=format_size(memory.used),
        physicalTotal=format_size(memory.total),
        physicalPercent=format_percent(percent_of(memory.used, memory.total)),
    )
    if memory.swap_total <= 0:
        # Translators: Reported when the system has no swap space.
        swap = _("Swap: not configured.")
    else:
        # Translators: Shows swap space usage.
        swap = _("Swap: {swapUsed} of {swapTotal} used ({swapPercent}%).").format(
            swapUsed=format_size(memory.swap_used),
            swapTotal=format_size(memory.swap_total),
            swapPercent=format_percent(percent_of(memory.swap_used, memory.swap_total)),
        )
    return f"{physical} {swap}"


def _drive_line(drive: DriveReport) -> str:
    mount = drive.mount
    # Translators: word used to describe a network drive.
    drive_type = _("network") if mount.is_network else mount.fstype
    if drive.usage is None:
        # Translators: Reported when a drive cannot be reached, such as an offline network share.
        return _("{driveName} ({driveType} drive): not available.").format(
            driveName=mount.mountpoint,
            driveType=drive_type,
        )
    # Translators: Shows the mount point, file system or drive type, used capacity,
    # and total capacity of a drive (example: / (btrfs drive): 40.00 GB of 100.00 GB used (40%).).
    return _(
        "{driveName} ({driveType} drive): {usedSpace} of {totalSpace} used ({percent}%)."
    ).format(
        driveName=mount.mountpoint,
        driveType=drive_type,
        usedSpace=format_size(drive.usage.used),
        totalSpace=format_size(drive.usage.total),
        percent=format_percent(drive.usage.percent),
    )


def drives_report(drives: Sequence[DriveReport]) -> str:
    """Returns the usage of every drive."""

    if not drives:
        # Translators: Reported when no drives could be found.
        return _("No drives found.")
    return " ".join(_drive_line(drive) for drive in drives)


def wifi_report(status: WifiStatus) -> str:
    """Returns the wireless network name, signal strength, and security type."""

    if status.state is WifiState.NO_DEVICE:
        return _("No wireless devices")
    if status.state is WifiState.NOT_CONNECTED:
        return _("No wireless connections")
    connection = status.connection
    if status.state is WifiState.ERROR or connection is None:
        return _("Unable to get wireless information")
    if connection.security is None:
        security = _("No authentication (Open)")
    elif connection.security == UNKNOWN_SECURITY:
        security = _unknown()
    else:
        security = connection.security
    # Translators: Reported for a hidden network, whose name is not broadcast.
    ssid = connection.ssid or _("hidden network")
    if connection.signal is None:
        # Translators: Presents the wireless network name and security type when the
        # signal strength is not known.
        return _("Connected to {}, signal strength unknown, security type: {}").format(
            ssid, security
        )
    # Translators: Presents the wireless network name, signal strength, and security type.
    return _("Connected to {}, signal strength: {}%, security type: {}").format(
        ssid, connection.signal, security
    )


def os_report(info: OsInfo) -> str:
    """Returns the distribution, architecture, kernel, and desktop session."""

    # Translators: Presents the operating system
    # (example: Arch Linux (x86_64), kernel 6.9.1-arch1-1).
    text = _("{distribution} ({architecture}), kernel {kernel}").format(
        distribution=info.name,
        architecture=info.architecture,
        kernel=info.kernel,
    )
    if info.desktop and info.session_type:
        # Translators: Presents the desktop and display server (example: GNOME on Wayland).
        session = _("{desktop} on {sessionType}").format(
            desktop=info.desktop,
            sessionType=info.session_type,
        )
    else:
        session = info.desktop or info.session_type
    return f"{text}, {session}." if session else f"{text}."


def uptime_report(seconds: float) -> str:
    """Returns the time since boot."""

    return format_duration(seconds)


def _gpu_status_message(readings: GpuReadings, failure: str) -> str:
    if not readings.has_provider:
        return _("No GPU information available.")
    if readings.has_failure:
        return failure
    return _("No GPU data available.")


def _gpu_line(number: int, item: GpuTelemetry, unit: str) -> str:
    if item.temperature is not None:
        temperature = format_temperature(item.temperature, unit)
    else:
        temperature = _unknown()
    if item.utilization is None:
        # Translators: Shows GPU temperature when the driver does not report usage.
        return _("GPU {gpuNumber}: usage unknown, temp {temperature}.").format(
            gpuNumber=number,
            temperature=temperature,
        )
    # Translators: Shows GPU usage and temperature
    # (example: GPU 1: usage 25%, temp 45 degrees Celsius.).
    return _("GPU {gpuNumber}: usage {usage}%, temp {temperature}.").format(
        gpuNumber=number,
        usage=format_percent(item.utilization),
        temperature=temperature,
    )


def gpu_report(readings: GpuReadings, unit: str) -> str:
    """Returns the usage and temperature of every GPU."""

    if not readings.items:
        return _gpu_status_message(readings, _("Unable to get GPU information."))
    return " ".join(
        _gpu_line(number, item, unit) for number, item in enumerate(readings.items, start=1)
    )


def gpu_memory_report(readings: GpuReadings) -> str:
    """Returns the video memory usage of every GPU that reports it."""

    parts = []
    for number, item in enumerate(readings.items, start=1):
        if item.memory_used is None or not item.memory_total:
            continue
        # Translators: Shows GPU memory usage (example: 2.00 GB of 8.00 GB used (25%)).
        memory = _("{used} of {total} used ({percent}%)").format(
            used=format_size(item.memory_used),
            total=format_size(item.memory_total),
            percent=format_percent(percent_of(item.memory_used, item.memory_total)),
        )
        # Translators: Shows GPU memory usage (example: GPU 1: 2.00 GB of 8.00 GB used (25%).).
        parts.append(
            _("GPU {gpuNumber}: {memoryInfo}.").format(gpuNumber=number, memoryInfo=memory)
        )
    if parts:
        return " ".join(parts)
    if readings.items:
        return _("Unable to get GPU memory information.")
    return _gpu_status_message(readings, _("Unable to get GPU memory information."))
