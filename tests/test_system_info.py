"""Tests for the /proc readers."""

import unittest

import context  # noqa: F401  pylint: disable=unused-import

from resource_monitor.system_info import (
    CpuSnapshot,
    CpuTimes,
    load_between,
    parse_cpu_snapshot,
    parse_meminfo,
    parse_uptime,
    read_os_info,
    sample_cpu_load,
)

PROC_STAT = """\
cpu  100 0 50 800 50 0 0 0 10 0
cpu0 60 0 20 400 20 0 0 0 10 0
cpu1 40 0 30 400 30 0 0 0 0 0
intr 12345 0 0
ctxt 999
"""

MEMINFO = """\
MemTotal:       16384000 kB
MemFree:         2048000 kB
MemAvailable:    8192000 kB
Buffers:          100000 kB
Cached:          4000000 kB
SwapTotal:       4096000 kB
SwapFree:        3072000 kB
HugePages_Total:       0
"""


class CpuTests(unittest.TestCase):
    def test_parse_excludes_guest_time_and_counts_iowait_as_idle(self):
        snapshot = parse_cpu_snapshot(PROC_STAT)
        # user+nice+system+idle+iowait+irq+softirq+steal; guest is inside user.
        self.assertEqual(snapshot.overall, CpuTimes(busy=150, total=1000))
        self.assertEqual(len(snapshot.per_core), 2)
        self.assertEqual(snapshot.per_core[1], CpuTimes(busy=70, total=500))

    def test_parse_requires_aggregate_line(self):
        with self.assertRaises(ValueError):
            parse_cpu_snapshot("cpu0 1 2 3 4 5 6 7 8\n")

    def test_load_between(self):
        self.assertEqual(load_between(CpuTimes(100, 1000), CpuTimes(150, 1100)), 50.0)

    def test_load_between_without_elapsed_time_is_zero(self):
        self.assertEqual(load_between(CpuTimes(100, 1000), CpuTimes(100, 1000)), 0.0)

    def test_load_is_clamped(self):
        self.assertEqual(load_between(CpuTimes(0, 0), CpuTimes(500, 100)), 100.0)
        self.assertEqual(load_between(CpuTimes(50, 0), CpuTimes(10, 100)), 0.0)

    def test_sample_uses_two_readings_and_waits(self):
        readings = iter(
            [
                CpuSnapshot(CpuTimes(0, 0), (CpuTimes(0, 0), CpuTimes(0, 0))),
                CpuSnapshot(CpuTimes(50, 200), (CpuTimes(25, 100), CpuTimes(75, 100))),
            ]
        )
        slept = []
        load = sample_cpu_load(0.3, reader=lambda: next(readings), sleep=slept.append)
        self.assertEqual(slept, [0.3])
        self.assertEqual(load.average, 25.0)
        self.assertEqual(load.per_core, (25.0, 75.0))


class MemoryTests(unittest.TestCase):
    def test_parse_meminfo(self):
        memory = parse_meminfo(MEMINFO)
        self.assertEqual(memory.total, 16384000 * 1024)
        self.assertEqual(memory.used, (16384000 - 8192000) * 1024)
        self.assertEqual(memory.swap_used, 1024000 * 1024)

    def test_old_kernels_without_mem_available(self):
        text = "\n".join(line for line in MEMINFO.splitlines() if "MemAvailable" not in line)
        memory = parse_meminfo(text)
        self.assertEqual(memory.available, (2048000 + 100000 + 4000000) * 1024)

    def test_missing_total_is_an_error(self):
        with self.assertRaises(ValueError):
            parse_meminfo("MemFree: 1 kB\n")

    def test_no_swap(self):
        memory = parse_meminfo("MemTotal: 100 kB\nMemAvailable: 50 kB\n")
        self.assertEqual(memory.swap_total, 0)
        self.assertEqual(memory.swap_used, 0)


class UptimeTests(unittest.TestCase):
    def test_parse_uptime(self):
        self.assertEqual(parse_uptime("5025.35 38000.12\n"), 5025.35)


class OsInfoTests(unittest.TestCase):
    def test_reads_desktop_and_session(self):
        info = read_os_info(
            environ={"XDG_CURRENT_DESKTOP": "ubuntu:GNOME", "XDG_SESSION_TYPE": "wayland"},
            distribution=lambda: "Ubuntu 26.04 LTS",
        )
        self.assertEqual(info.name, "Ubuntu 26.04 LTS")
        self.assertEqual(info.desktop, "ubuntu, GNOME")
        self.assertEqual(info.session_type, "Wayland")
        self.assertTrue(info.kernel)
        self.assertTrue(info.architecture)

    def test_guesses_session_from_display_variables(self):
        info = read_os_info(environ={"DISPLAY": ":0"}, distribution=lambda: "Linux")
        self.assertEqual(info.session_type, "X11")
        self.assertEqual(info.desktop, "")
        info = read_os_info(environ={"WAYLAND_DISPLAY": "wayland-0"}, distribution=lambda: "Linux")
        self.assertEqual(info.session_type, "Wayland")


if __name__ == "__main__":
    unittest.main()
