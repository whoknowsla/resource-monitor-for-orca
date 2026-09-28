"""Tests for number, size, duration, and temperature formatting."""

import unittest

import context  # noqa: F401  pylint: disable=unused-import

from resource_monitor.formatting import (
    FAHRENHEIT,
    format_duration,
    format_percent,
    format_size,
    format_temperature,
    percent_of,
    trim_number,
)


class TrimNumberTests(unittest.TestCase):
    def test_whole_float_becomes_int(self):
        self.assertEqual(trim_number(5.0), 5)
        self.assertIsInstance(trim_number(5.0), int)

    def test_fraction_is_kept(self):
        self.assertEqual(trim_number(5.5), 5.5)


class PercentTests(unittest.TestCase):
    def test_rounds_to_one_decimal_and_trims(self):
        self.assertEqual(format_percent(40.04), "40")
        self.assertEqual(format_percent(12.345), "12.3")

    def test_percent_of_zero_whole_is_zero(self):
        self.assertEqual(percent_of(5, 0), 0.0)

    def test_percent_of(self):
        self.assertEqual(percent_of(1, 4), 25.0)


class SizeTests(unittest.TestCase):
    def test_bytes_are_whole_numbers(self):
        self.assertEqual(format_size(0), "0 bytes")
        self.assertEqual(format_size(1), "1 byte")
        self.assertEqual(format_size(512), "512 bytes")

    def test_binary_multiples(self):
        self.assertEqual(format_size(1024), "1.00 KB")
        self.assertEqual(format_size(1536 * 1024**2), "1.50 GB")
        self.assertEqual(format_size(4 * 1024**4), "4.00 TB")


class DurationTests(unittest.TestCase):
    def test_all_parts_are_always_present(self):
        self.assertEqual(format_duration(0), "0 days, 0 hours, 0 minutes, 0 seconds")

    def test_singular_and_plural(self):
        seconds = 86400 + 2 * 3600 + 60 + 5
        self.assertEqual(format_duration(seconds), "1 day, 2 hours, 1 minute, 5 seconds")

    def test_fractions_and_negatives(self):
        self.assertEqual(format_duration(61.9), "0 days, 0 hours, 1 minute, 1 second")
        self.assertEqual(format_duration(-3), "0 days, 0 hours, 0 minutes, 0 seconds")


class TemperatureTests(unittest.TestCase):
    def test_celsius(self):
        self.assertEqual(format_temperature(45.0, "celsius"), "45 degrees Celsius")

    def test_fahrenheit(self):
        self.assertEqual(format_temperature(40.0, FAHRENHEIT), "104 degrees Fahrenheit")
        self.assertEqual(format_temperature(41.5, FAHRENHEIT), "106.7 degrees Fahrenheit")

    def test_unknown_unit_falls_back_to_celsius(self):
        self.assertEqual(format_temperature(30, "kelvin"), "30 degrees Celsius")


if __name__ == "__main__":
    unittest.main()
