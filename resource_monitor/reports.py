"""Turns resource readings into the sentences Orca presents.

Wording follows the NVDA Resource Monitor add-on so that its users hear what
they expect, with Linux terms where Windows ones would be wrong.
"""

from __future__ import annotations

from collections.abc import Sequence

from .audio import AudioDevice, AudioRole
from .disks import DriveReport
from .formatting import (
    format_duration,
    format_percent,
    format_size,
    format_temperature,
    format_time_remaining,
    percent_of,
)
from .gpu import GpuReadings, GpuTelemetry
from .i18n import _
from .load import SystemLoad
from .power import BatteryState, BatteryStatus
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


def battery_report(status: BatteryStatus) -> str:
    """Returns the battery charge, what it is doing, and how long is left."""

    if status.state is BatteryState.ABSENT:
        if status.on_ac:
            # Translators: Reported on a machine with no battery, running on mains power.
            return _("No battery. Running on AC power.")
        # Translators: Reported on a machine with no battery.
        return _("No battery.")

    if status.percent is None:
        # Translators: Reported when a battery is present but its charge is unreadable.
        return _("Battery present, charge unknown.")

    charge = format_percent(status.percent)
    if status.state is BatteryState.CHARGING:
        # Translators: Shows battery charge while charging (example: Battery: 42%, charging.).
        head = _("Battery: {percent}%, charging.").format(percent=charge)
    elif status.state is BatteryState.DISCHARGING:
        # Translators: Shows battery charge while running on the battery.
        head = _("Battery: {percent}%, on battery power.").format(percent=charge)
    elif status.state is BatteryState.FULL:
        # Translators: Shows battery charge when the battery is full.
        head = _("Battery: {percent}%, fully charged.").format(percent=charge)
    elif status.state is BatteryState.NOT_CHARGING:
        # Translators: Shows battery charge when plugged in but deliberately not
        # charging, as when a charge limit is set.
        head = _("Battery: {percent}%, plugged in, not charging.").format(percent=charge)
    else:
        # Translators: Shows battery charge when the state is not reported.
        head = _("Battery: {percent}%.").format(percent=charge)

    if status.seconds_left is None:
        return head
    remaining = format_time_remaining(status.seconds_left)
    if status.state is BatteryState.CHARGING:
        # Translators: Shows the estimated time until the battery is full.
        return _("{batteryInfo} {time} until full.").format(
            batteryInfo=head, time=remaining
        )
    # Translators: Shows the estimated time until the battery runs out.
    return _("{batteryInfo} {time} remaining.").format(batteryInfo=head, time=remaining)


def audio_report(role: AudioRole, device: AudioDevice) -> str:
    """Returns the default audio device for `role`, its volume, and mute state."""

    if device.is_empty:
        if role is AudioRole.INPUT:
            # Translators: Reported when the audio input device cannot be read.
            return _("Unable to get audio input information.")
        # Translators: Reported when the audio output device cannot be read.
        return _("Unable to get audio output information.")

    if role is AudioRole.INPUT:
        # Translators: Names the audio input device, the microphone.
        label = _("Input")
    else:
        # Translators: Names the audio output device, the speakers or headphones.
        label = _("Output")

    # Translators: Used in place of an audio device whose name is not reported.
    name = device.name or _unknown()

    if device.volume is None:
        # Translators: Shows the audio device when its volume is not reported.
        text = _("{audioRole}: {deviceName}, volume unknown.").format(
            audioRole=label, deviceName=name
        )
    else:
        # Translators: Shows the audio device and its volume
        # (example: Output: Built-in Speakers, volume 42%.).
        text = _("{audioRole}: {deviceName}, volume {volumePercent}%.").format(
            audioRole=label,
            deviceName=name,
            volumePercent=format_percent(device.volume * 100.0),
        )
    if device.muted:
        # Translators: Appended when the audio device is muted.
        return _("{audioInfo} Muted.").format(audioInfo=text)
    return text


def load_report(load: SystemLoad, unit: str) -> str:
    """Returns the load averages and the temperatures that could be read."""

    parts: list[str] = []
    averages = load.averages
    if averages is None:
        # Translators: Reported when the load averages cannot be read.
        parts.append(_("Load average unavailable."))
    else:
        # Translators: Shows how many tasks have been waiting, averaged over one,
        # five, and fifteen minutes (example: Load average: 0.5, 0.8, 0.8.).
        parts.append(
            _("Load average: {oneMinute}, {fiveMinutes}, {fifteenMinutes}.").format(
                oneMinute=format_percent(averages.one),
                fiveMinutes=format_percent(averages.five),
                fifteenMinutes=format_percent(averages.fifteen),
            )
        )

    if load.temperatures:
        readings = ", ".join(
            # Translators: Shows one temperature sensor and its reading
            # (example: coretemp Package id 0: 45 degrees Celsius).
            _("{sensorName}: {temperature}").format(
                sensorName=reading.label,
                temperature=format_temperature(reading.celsius, unit),
            )
            for reading in load.temperatures
        )
        # Translators: Introduces the list of temperature readings.
        parts.append(_("Temperatures: {temperatureList}.").format(temperatureList=readings))
    else:
        # Translators: Reported when no temperature sensors could be read.
        parts.append(_("No temperature sensors available."))

    return " ".join(parts)
