"""Tests for the GPU providers."""

import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

import context  # noqa: F401  pylint: disable=unused-import

from resource_monitor.gpu import (
    AmdSysfsProvider,
    GpuTelemetry,
    NvidiaSmiProvider,
    parse_nvidia_smi,
    read_gpus,
)

MIB = 1024 * 1024


class NvidiaTests(unittest.TestCase):
    def test_parse_values_and_not_available_markers(self):
        items = parse_nvidia_smi("12, 45, 1024, 8192\n[N/A], [N/A], 0, [N/A]\nbad line\n")
        self.assertEqual(items[0], GpuTelemetry(12.0, 45.0, 1024 * MIB, 8192 * MIB))
        self.assertEqual(items[1], GpuTelemetry(None, None, 0, None))
        self.assertEqual(len(items), 2)

    def test_absent_tool_means_no_provider(self):
        self.assertIsNone(NvidiaSmiProvider(which=lambda _name: None).collect())

    def test_failure_is_an_empty_list(self):
        def run(_command, _timeout):
            raise subprocess.CalledProcessError(9, "nvidia-smi")

        provider = NvidiaSmiProvider(which=lambda _name: "/usr/bin/nvidia-smi", run=run)
        self.assertEqual(provider.collect(), [])

    def test_runs_query_with_timeout(self):
        calls = []

        def run(command, timeout):
            calls.append((command, timeout))
            return SimpleNamespace(stdout="1, 2, 3, 4\n")

        provider = NvidiaSmiProvider(which=lambda _name: "/usr/bin/nvidia-smi", run=run)
        self.assertEqual(len(provider.collect()), 1)
        command, timeout = calls[0]
        self.assertEqual(command[0], "/usr/bin/nvidia-smi")
        self.assertIn("--format=csv,noheader,nounits", command)
        self.assertGreater(timeout, 0)


class AmdTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = self.directory.name

    def _write(self, relative, content):
        path = os.path.join(self.root, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="ascii") as file:
            file.write(content)

    def test_reads_amd_cards_only(self):
        self._write("card0/device/vendor", "0x1002\n")
        self._write("card0/device/gpu_busy_percent", "37\n")
        self._write("card0/device/mem_info_vram_used", str(512 * MIB))
        self._write("card0/device/mem_info_vram_total", str(4096 * MIB))
        self._write("card0/device/hwmon/hwmon3/temp1_input", "52000\n")
        self._write("card1/device/vendor", "0x8086\n")
        self._write("card0-DP-1/status", "connected\n")
        items = AmdSysfsProvider(drm_root=self.root).collect()
        self.assertEqual(items, [GpuTelemetry(37.0, 52.0, 512 * MIB, 4096 * MIB)])

    def test_missing_readings_become_none(self):
        self._write("card2/device/vendor", "0x1002\n")
        self._write("card2/device/gpu_busy_percent", "\n")
        items = AmdSysfsProvider(drm_root=self.root).collect()
        self.assertEqual(items, [GpuTelemetry(None, None, None, None)])

    def test_no_amd_card_means_no_provider(self):
        self._write("card1/device/vendor", "0x8086\n")
        self.assertIsNone(AmdSysfsProvider(drm_root=self.root).collect())


class FakeProvider:
    def __init__(self, result):
        self.result = result

    def collect(self):
        return self.result


class ReadGpusTests(unittest.TestCase):
    def test_no_providers(self):
        readings = read_gpus([FakeProvider(None)])
        self.assertFalse(readings.has_provider)
        self.assertEqual(readings.items, ())

    def test_combines_providers_and_notes_failures(self):
        item = GpuTelemetry(1.0, 2.0, 3, 4)
        readings = read_gpus([FakeProvider([]), FakeProvider([item])])
        self.assertTrue(readings.has_provider)
        self.assertTrue(readings.has_failure)
        self.assertEqual(readings.items, (item,))


if __name__ == "__main__":
    unittest.main()
