"""Tests for the sentences Orca presents."""

import unittest

import context  # noqa: F401  pylint: disable=unused-import

from resource_monitor.disks import DiskUsage, DriveReport, Mount
from resource_monitor.gpu import GpuReadings, GpuTelemetry
from resource_monitor.reports import (
    cpu_report,
    drives_report,
    gpu_memory_report,
    gpu_report,
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


if __name__ == "__main__":
    unittest.main()
