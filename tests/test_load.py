"""Tests for load averages and temperature sensors."""

import os
import shutil
import tempfile
import unittest

import context  # noqa: F401  pylint: disable=unused-import

from resource_monitor.load import (
    parse_loadavg,
    read_load_averages,
    read_system_load,
    read_temperatures,
)


class LoadAverageTests(unittest.TestCase):
    def test_parses_the_three_averages(self):
        averages = parse_loadavg("0.48 0.77 0.78 2/1870 2321461")
        self.assertEqual((averages.one, averages.five, averages.fifteen), (0.48, 0.77, 0.78))

    def test_trailing_fields_are_not_required(self):
        averages = parse_loadavg("1.00 2.00 3.00")
        self.assertEqual(averages.fifteen, 3.0)

    def test_too_few_fields_is_none(self):
        self.assertIsNone(parse_loadavg("0.48 0.77"))

    def test_empty_is_none(self):
        self.assertIsNone(parse_loadavg(""))

    def test_non_numeric_is_none(self):
        self.assertIsNone(parse_loadavg("a b c 2/1870 1"))

    def test_a_missing_file_is_none_not_an_error(self):
        self.assertIsNone(read_load_averages("/nonexistent/loadavg"))


class TemperatureTests(unittest.TestCase):
    def setUp(self):
        self.hwmon = tempfile.mkdtemp(prefix="hwmon-")
        self.thermal = tempfile.mkdtemp(prefix="thermal-")
        self.addCleanup(shutil.rmtree, self.hwmon, ignore_errors=True)
        self.addCleanup(shutil.rmtree, self.thermal, ignore_errors=True)

    def chip(self, name, chip_name, **attributes):
        directory = os.path.join(self.hwmon, name)
        os.makedirs(directory, exist_ok=True)
        attributes["name"] = chip_name
        for key, value in attributes.items():
            with open(os.path.join(directory, key), "w", encoding="utf-8") as handle:
                handle.write(f"{value}\n")

    def zone(self, name, kind, millidegrees):
        directory = os.path.join(self.thermal, name)
        os.makedirs(directory, exist_ok=True)
        for key, value in (("type", kind), ("temp", millidegrees)):
            with open(os.path.join(directory, key), "w", encoding="utf-8") as handle:
                handle.write(f"{value}\n")

    def read(self, limit=4):
        return read_temperatures(self.hwmon, self.thermal, limit)

    def test_nothing_at_all(self):
        self.assertEqual(self.read(), ())

    def test_missing_roots_are_not_an_error(self):
        self.assertEqual(read_temperatures("/nonexistent", "/also-nonexistent"), ())

    def test_a_labelled_sensor_is_named_chip_then_label(self):
        self.chip("hwmon0", "coretemp", temp1_input=45000, temp1_label="Package id 0")
        readings = self.read()
        self.assertEqual(readings[0].label, "coretemp Package id 0")
        self.assertAlmostEqual(readings[0].celsius, 45.0)

    def test_an_unlabelled_sensor_falls_back_to_the_chip_name(self):
        self.chip("hwmon0", "k10temp", temp1_input=50000)
        self.assertEqual(self.read()[0].label, "k10temp")

    def test_implausible_readings_are_dropped(self):
        # A disconnected probe commonly reports -274 degrees, and some
        # sensors report a fixed critical value in the thousands.
        self.chip("hwmon0", "coretemp", temp1_input=45000)
        self.chip("hwmon1", "nonsense", temp1_input=-274000)
        self.chip("hwmon2", "alsononsense", temp1_input=9999000)
        readings = self.read()
        self.assertEqual([reading.label for reading in readings], ["coretemp"])

    def test_cpu_and_gpu_sensors_crowd_out_the_rest(self):
        # A desktop exposes temperatures for network cards and chipsets, and
        # padding the list with them buries the readings that were asked for.
        self.chip("hwmon0", "k10temp", temp1_input=49000, temp1_label="Tctl")
        self.chip("hwmon1", "amdgpu", temp1_input=44000, temp1_label="edge")
        self.chip("hwmon2", "enp100s0", temp1_input=48000, temp1_label="PHY Temperature")
        self.chip("hwmon3", "acpitz", temp1_input=49000)
        readings = self.read()
        self.assertEqual(
            [reading.label for reading in readings],
            ["k10temp Tctl", "amdgpu edge"],
        )

    def test_everything_is_reported_when_no_cpu_or_gpu_sensor_exists(self):
        self.chip("hwmon0", "enp100s0", temp1_input=48000)
        self.chip("hwmon1", "nvme", temp1_input=40000)
        self.assertEqual(len(self.read()), 2)

    def test_the_processor_is_named_before_the_graphics(self):
        self.chip("hwmon0", "amdgpu", temp1_input=70000)
        self.chip("hwmon1", "coretemp", temp1_input=40000)
        self.assertEqual(
            [reading.label for reading in self.read()], ["coretemp", "amdgpu"]
        )

    def test_the_hottest_sensor_of_a_chip_comes_first(self):
        self.chip(
            "hwmon0",
            "coretemp",
            temp1_input=40000,
            temp1_label="Core 0",
            temp2_input=60000,
            temp2_label="Core 1",
        )
        self.assertEqual(self.read()[0].label, "coretemp Core 1")

    def test_duplicate_labels_are_reported_once(self):
        self.chip("hwmon0", "coretemp", temp1_input=45000)
        self.chip("hwmon1", "coretemp", temp1_input=46000)
        self.assertEqual(len(self.read()), 1)

    def test_the_limit_is_honoured(self):
        for index in range(6):
            self.chip(f"hwmon{index}", f"chip{index}", temp1_input=40000 + index * 1000)
        self.assertEqual(len(self.read(limit=3)), 3)

    def test_a_limit_of_zero_means_no_limit(self):
        for index in range(6):
            self.chip(f"hwmon{index}", f"chip{index}", temp1_input=40000 + index * 1000)
        self.assertEqual(len(self.read(limit=0)), 6)

    def test_thermal_zones_are_the_fallback(self):
        self.zone("thermal_zone0", "acpitz", 42000)
        readings = self.read()
        self.assertEqual(readings[0].label, "acpitz")
        self.assertAlmostEqual(readings[0].celsius, 42.0)

    def test_hwmon_is_preferred_over_thermal_zones(self):
        # hwmon sensors carry labels, so a reading can be attributed to the
        # processor rather than to "thermal_zone3".
        self.chip("hwmon0", "coretemp", temp1_input=45000)
        self.zone("thermal_zone0", "acpitz", 42000)
        self.assertEqual([reading.label for reading in self.read()], ["coretemp"])

    def test_unparseable_values_do_not_raise(self):
        self.chip("hwmon0", "coretemp", temp1_input="warm")
        self.assertEqual(self.read(), ())


class SystemLoadTests(unittest.TestCase):
    def test_both_halves_are_gathered(self):
        handle = tempfile.NamedTemporaryFile("w", suffix="-loadavg", delete=False)
        handle.write("1.50 2.50 3.50 1/100 1\n")
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        load = read_system_load(handle.name, "/nonexistent", "/nonexistent")
        self.assertEqual(load.averages.one, 1.5)
        self.assertEqual(load.temperatures, ())


if __name__ == "__main__":
    unittest.main()
