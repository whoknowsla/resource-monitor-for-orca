"""Tests for the sentences Orca presents."""

import unittest

import context  # noqa: F401  pylint: disable=unused-import

from resource_monitor.audio import AudioDevice, AudioRole
from resource_monitor.disks import DiskUsage, DriveReport, Mount
from resource_monitor.gpu import GpuReadings, GpuTelemetry
from resource_monitor.load import LoadAverages, SystemLoad, Temperature
from resource_monitor.power import BatteryState, BatteryStatus
from resource_monitor.reports import (
    audio_report,
    battery_report,
    cpu_report,
    drives_report,
    gpu_memory_report,
    gpu_report,
    load_report,
    memory_report,
    os_report,
    summary_report,
    uptime_report,
    wifi_report,
)
from resource_monitor.system_info import CpuLoad, MemoryUsage, OsInfo
from resource_monitor.wifi import (
    UNKNOWN_SECURITY,
    WifiConnection,
    WifiState,
    WifiStatus,
)

GIB = 1024**3


def memory(total=16, available=12, swap_total=4, swap_free=4):
    return MemoryUsage(total * GIB, available * GIB, swap_total * GIB, swap_free * GIB)


class CpuAndMemoryTests(unittest.TestCase):
    def test_summary(self):
        self.assertEqual(
            summary_report(memory(), CpuLoad(12.34, (10.0, 14.0))),
            "25% RAM used, CPU at 12.3%.",
        )

    def test_cpu_multi_core(self):
        self.assertEqual(
            cpu_report(CpuLoad(20.0, (10.0, 30.55))),
            "20% average CPU load, Core 1: 10%, Core 2: 30.6%.",
        )

    def test_cpu_single_core(self):
        self.assertEqual(cpu_report(CpuLoad(7.0, (7.0,))), "7% CPU load.")

    def test_memory_with_swap(self):
        self.assertEqual(
            memory_report(memory(swap_free=3)),
            "Physical: 4.00 GB of 16.00 GB used (25%). Swap: 1.00 GB of 4.00 GB used (25%).",
        )

    def test_memory_without_swap(self):
        self.assertEqual(
            memory_report(memory(swap_total=0, swap_free=0)),
            "Physical: 4.00 GB of 16.00 GB used (25%). Swap: not configured.",
        )


class DriveTests(unittest.TestCase):
    def test_local_and_unreachable_network_drives(self):
        drives = [
            DriveReport(Mount("/dev/sda2", "/", "ext4"), DiskUsage(100 * GIB, 40 * GIB, 60 * GIB)),
            DriveReport(Mount("nas:/share", "/mnt/nas", "nfs4"), None),
        ]
        self.assertEqual(
            drives_report(drives),
            "/ (ext4 drive): 40.00 GB of 100.00 GB used (40%). "
            "/mnt/nas (network drive): not available.",
        )

    def test_reachable_network_drive(self):
        drives = [
            DriveReport(Mount("//nas/x", "/mnt/x", "cifs"), DiskUsage(GIB, GIB // 2, GIB // 2))
        ]
        self.assertEqual(
            drives_report(drives),
            "/mnt/x (network drive): 512.00 MB of 1.00 GB used (50%).",
        )

    def test_no_drives(self):
        self.assertEqual(drives_report([]), "No drives found.")


class WifiTests(unittest.TestCase):
    def test_connected(self):
        status = WifiStatus(WifiState.CONNECTED, WifiConnection("Home", 80, "WPA2-PSK"))
        self.assertEqual(
            wifi_report(status),
            "Connected to Home, signal strength: 80%, security type: WPA2-PSK",
        )

    def test_open_hidden_and_unknown_values(self):
        status = WifiStatus(WifiState.CONNECTED, WifiConnection("", None, None))
        self.assertEqual(
            wifi_report(status),
            "Connected to hidden network, signal strength unknown, "
            "security type: No authentication (Open)",
        )
        status = WifiStatus(WifiState.CONNECTED, WifiConnection("Lab", 50, UNKNOWN_SECURITY))
        self.assertTrue(wifi_report(status).endswith("security type: unknown"))

    def test_states_without_connection(self):
        self.assertEqual(wifi_report(WifiStatus(WifiState.NO_DEVICE)), "No wireless devices")
        self.assertEqual(
            wifi_report(WifiStatus(WifiState.NOT_CONNECTED)), "No wireless connections"
        )
        self.assertEqual(
            wifi_report(WifiStatus(WifiState.ERROR)),
            "Unable to get wireless information",
        )


class SystemTests(unittest.TestCase):
    def test_os_with_desktop_and_session(self):
        info = OsInfo("Fedora Linux 44", "aarch64", "6.20.1", "GNOME", "Wayland")
        self.assertEqual(
            os_report(info), "Fedora Linux 44 (aarch64), kernel 6.20.1, GNOME on Wayland."
        )

    def test_os_with_partial_session_information(self):
        self.assertEqual(
            os_report(OsInfo("Debian", "x86_64", "6.1", "", "TTY")),
            "Debian (x86_64), kernel 6.1, TTY.",
        )
        self.assertEqual(
            os_report(OsInfo("Debian", "x86_64", "6.1", "", "")), "Debian (x86_64), kernel 6.1."
        )

    def test_uptime(self):
        self.assertEqual(uptime_report(3661), "0 days, 1 hour, 1 minute, 1 second")


class GpuTests(unittest.TestCase):
    ITEM = GpuTelemetry(
        utilization=25.0, temperature=45.0, memory_used=2 * GIB, memory_total=8 * GIB
    )

    def test_usage_and_temperature(self):
        readings = GpuReadings((self.ITEM, GpuTelemetry(None, None, None, None)), True, False)
        self.assertEqual(
            gpu_report(readings, "celsius"),
            "GPU 1: usage 25%, temp 45 degrees Celsius. GPU 2: usage unknown, temp unknown.",
        )
        self.assertIn("113 degrees Fahrenheit", gpu_report(readings, "fahrenheit"))

    def test_status_messages(self):
        self.assertEqual(
            gpu_report(GpuReadings((), False, False), "celsius"), "No GPU information available."
        )
        self.assertEqual(
            gpu_report(GpuReadings((), True, True), "celsius"), "Unable to get GPU information."
        )
        self.assertEqual(
            gpu_report(GpuReadings((), True, False), "celsius"), "No GPU data available."
        )

    def test_memory(self):
        readings = GpuReadings((self.ITEM,), True, False)
        self.assertEqual(gpu_memory_report(readings), "GPU 1: 2.00 GB of 8.00 GB used (25%).")

    def test_memory_not_reported(self):
        readings = GpuReadings((GpuTelemetry(1.0, 1.0, None, None),), True, False)
        self.assertEqual(gpu_memory_report(readings), "Unable to get GPU memory information.")
        self.assertEqual(
            gpu_memory_report(GpuReadings((), True, True)),
            "Unable to get GPU memory information.",
        )
        self.assertEqual(
            gpu_memory_report(GpuReadings((), False, False)), "No GPU information available."
        )



class BatteryReportTests(unittest.TestCase):
    def test_discharging_with_an_estimate(self):
        self.assertEqual(
            battery_report(BatteryStatus(BatteryState.DISCHARGING, 42.0, 4800, False)),
            "Battery: 42%, on battery power. 1 hour, 20 minutes remaining.",
        )

    def test_charging_counts_towards_full(self):
        self.assertEqual(
            battery_report(BatteryStatus(BatteryState.CHARGING, 67.5, 3900, True)),
            "Battery: 67.5%, charging. 1 hour, 5 minutes until full.",
        )

    def test_under_an_hour_names_only_minutes(self):
        self.assertEqual(
            battery_report(BatteryStatus(BatteryState.DISCHARGING, 5.0, 540, False)),
            "Battery: 5%, on battery power. 9 minutes remaining.",
        )

    def test_one_minute_is_singular(self):
        self.assertEqual(
            battery_report(BatteryStatus(BatteryState.CHARGING, 99.0, 60, True)),
            "Battery: 99%, charging. 1 minute until full.",
        )

    def test_full_has_no_estimate(self):
        self.assertEqual(
            battery_report(BatteryStatus(BatteryState.FULL, 100.0, None, True)),
            "Battery: 100%, fully charged.",
        )

    def test_plugged_in_but_not_charging(self):
        self.assertEqual(
            battery_report(BatteryStatus(BatteryState.NOT_CHARGING, 80.0, None, True)),
            "Battery: 80%, plugged in, not charging.",
        )

    def test_an_unknown_state_still_gives_the_charge(self):
        self.assertEqual(
            battery_report(BatteryStatus(BatteryState.UNKNOWN, 55.0, None, None)),
            "Battery: 55%.",
        )

    def test_no_battery_on_mains(self):
        self.assertEqual(
            battery_report(BatteryStatus(BatteryState.ABSENT, None, None, True)),
            "No battery. Running on AC power.",
        )

    def test_no_battery_and_no_mains_reading(self):
        self.assertEqual(
            battery_report(BatteryStatus(BatteryState.ABSENT, None, None, None)),
            "No battery.",
        )

    def test_a_battery_whose_charge_cannot_be_read(self):
        self.assertEqual(
            battery_report(BatteryStatus(BatteryState.DISCHARGING, None, None, False)),
            "Battery present, charge unknown.",
        )


class AudioReportTests(unittest.TestCase):
    def test_output_device_and_volume(self):
        self.assertEqual(
            audio_report(AudioRole.OUTPUT, AudioDevice("Built-in Speakers", 0.42, False)),
            "Output: Built-in Speakers, volume 42%.",
        )

    def test_input_is_named_as_input(self):
        self.assertEqual(
            audio_report(AudioRole.INPUT, AudioDevice("Internal Microphone", 0.5, False)),
            "Input: Internal Microphone, volume 50%.",
        )

    def test_muted_is_said_last(self):
        self.assertEqual(
            audio_report(AudioRole.OUTPUT, AudioDevice("Headphones", 1.0, True)),
            "Output: Headphones, volume 100%. Muted.",
        )

    def test_a_volume_above_full_is_reported_as_it_is(self):
        self.assertEqual(
            audio_report(AudioRole.OUTPUT, AudioDevice("Speakers", 1.4, False)),
            "Output: Speakers, volume 140%.",
        )

    def test_an_unreadable_volume(self):
        self.assertEqual(
            audio_report(AudioRole.OUTPUT, AudioDevice("Dock", None, False)),
            "Output: Dock, volume unknown.",
        )

    def test_an_unnamed_device(self):
        self.assertEqual(
            audio_report(AudioRole.OUTPUT, AudioDevice(None, 0.5, False)),
            "Output: unknown, volume 50%.",
        )

    def test_nothing_readable_at_all(self):
        self.assertEqual(
            audio_report(AudioRole.OUTPUT, AudioDevice()),
            "Unable to get audio output information.",
        )
        self.assertEqual(
            audio_report(AudioRole.INPUT, AudioDevice()),
            "Unable to get audio input information.",
        )


class LoadReportTests(unittest.TestCase):
    def test_averages_and_temperatures(self):
        load = SystemLoad(
            LoadAverages(0.48, 0.77, 0.78),
            (Temperature("k10temp Tctl", 49.1), Temperature("amdgpu edge", 44.0)),
        )
        self.assertEqual(
            load_report(load, "celsius"),
            "Load average: 0.5, 0.8, 0.8. Temperatures: k10temp Tctl: 49.1 degrees "
            "Celsius, amdgpu edge: 44 degrees Celsius.",
        )

    def test_the_temperature_unit_is_honoured(self):
        load = SystemLoad(LoadAverages(1.0, 1.0, 1.0), (Temperature("coretemp", 100.0),))
        self.assertIn("212 degrees Fahrenheit", load_report(load, "fahrenheit"))

    def test_no_sensors(self):
        load = SystemLoad(LoadAverages(1.0, 2.0, 3.0), ())
        self.assertEqual(
            load_report(load, "celsius"),
            "Load average: 1, 2, 3. No temperature sensors available.",
        )

    def test_no_averages(self):
        load = SystemLoad(None, (Temperature("coretemp", 45.0),))
        self.assertEqual(
            load_report(load, "celsius"),
            "Load average unavailable. Temperatures: coretemp: 45 degrees Celsius.",
        )

    def test_nothing_at_all(self):
        self.assertEqual(
            load_report(SystemLoad(None, ()), "celsius"),
            "Load average unavailable. No temperature sensors available.",
        )


if __name__ == "__main__":
    unittest.main()
