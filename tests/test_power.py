"""Tests for reading the battery from sysfs."""

import os
import shutil
import tempfile
import unittest

import context  # noqa: F401  pylint: disable=unused-import

from resource_monitor.power import BatteryState, read_battery


def write(directory, **attributes):
    os.makedirs(directory, exist_ok=True)
    for name, value in attributes.items():
        with open(os.path.join(directory, name), "w", encoding="utf-8") as handle:
            handle.write(f"{value}\n")


class BatteryTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="power-supply-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def battery(self, name="BAT0", **attributes):
        write(os.path.join(self.root, name), type="Battery", **attributes)

    def mains(self, name="AC", online=1):
        write(os.path.join(self.root, name), type="Mains", online=online)

    def test_no_power_supplies_at_all(self):
        status = read_battery(self.root)
        self.assertIs(status.state, BatteryState.ABSENT)
        self.assertIsNone(status.percent)
        self.assertIsNone(status.seconds_left)
        self.assertIsNone(status.on_ac)

    def test_missing_directory_is_not_an_error(self):
        status = read_battery(os.path.join(self.root, "nothing-here"))
        self.assertIs(status.state, BatteryState.ABSENT)

    def test_desktop_with_mains_only(self):
        self.mains()
        status = read_battery(self.root)
        self.assertIs(status.state, BatteryState.ABSENT)
        self.assertTrue(status.on_ac)

    def test_energy_family_discharging(self):
        # Half of a 50 Wh battery left, drawing 10 W: two and a half hours.
        self.battery(
            status="Discharging",
            energy_now=25_000_000,
            energy_full=50_000_000,
            power_now=10_000_000,
        )
        status = read_battery(self.root)
        self.assertIs(status.state, BatteryState.DISCHARGING)
        self.assertAlmostEqual(status.percent, 50.0)
        self.assertEqual(status.seconds_left, 9000)

    def test_charge_family_discharging(self):
        self.battery(
            status="Discharging",
            charge_now=2_000_000,
            charge_full=4_000_000,
            current_now=1_000_000,
        )
        status = read_battery(self.root)
        self.assertAlmostEqual(status.percent, 50.0)
        self.assertEqual(status.seconds_left, 7200)

    def test_charging_counts_up_to_full(self):
        self.battery(
            status="Charging",
            energy_now=30_000_000,
            energy_full=50_000_000,
            power_now=20_000_000,
        )
        status = read_battery(self.root)
        self.assertIs(status.state, BatteryState.CHARGING)
        self.assertEqual(status.seconds_left, 3600)

    def test_a_negative_rate_is_a_magnitude(self):
        # Some firmware reports the draw as a negative number.
        self.battery(
            status="Discharging",
            energy_now=10_000_000,
            energy_full=50_000_000,
            power_now=-10_000_000,
        )
        self.assertEqual(read_battery(self.root).seconds_left, 3600)

    def test_full_gives_no_estimate(self):
        self.battery(
            status="Full",
            energy_now=50_000_000,
            energy_full=50_000_000,
            power_now=0,
        )
        status = read_battery(self.root)
        self.assertIs(status.state, BatteryState.FULL)
        self.assertAlmostEqual(status.percent, 100.0)
        self.assertIsNone(status.seconds_left)

    def test_not_charging_is_its_own_state(self):
        # A charge limit holds the battery below full without charging it.
        self.battery(status="Not charging", energy_now=40_000_000, energy_full=50_000_000)
        self.assertIs(read_battery(self.root).state, BatteryState.NOT_CHARGING)

    def test_unreadable_status_is_unknown_not_assumed(self):
        self.battery(energy_now=25_000_000, energy_full=50_000_000)
        self.assertIs(read_battery(self.root).state, BatteryState.UNKNOWN)

    def test_zero_rate_gives_no_estimate(self):
        # Dividing by it would raise, and a huge estimate would be a lie.
        self.battery(
            status="Discharging",
            energy_now=25_000_000,
            energy_full=50_000_000,
            power_now=0,
        )
        self.assertIsNone(read_battery(self.root).seconds_left)

    def test_capacity_is_used_when_there_is_no_energy_reading(self):
        self.battery(status="Discharging", capacity=37)
        status = read_battery(self.root)
        self.assertAlmostEqual(status.percent, 37.0)
        self.assertIsNone(status.seconds_left)

    def test_a_worn_battery_still_reaches_100_percent(self):
        # energy_full is the capacity the battery has now; energy_full_design
        # is what it had when new. Using the design figure would report a
        # charge that never reaches 100% on a worn battery.
        self.battery(
            status="Full",
            energy_now=40_000_000,
            energy_full=40_000_000,
            energy_full_design=50_000_000,
        )
        self.assertAlmostEqual(read_battery(self.root).percent, 100.0)

    def test_unparseable_values_do_not_raise(self):
        self.battery(status="Discharging", energy_now="not a number", energy_full="x")
        status = read_battery(self.root)
        self.assertIs(status.state, BatteryState.DISCHARGING)
        self.assertIsNone(status.percent)

    def test_two_batteries_are_added_together(self):
        self.battery("BAT0", status="Discharging", energy_now=10_000_000,
                     energy_full=40_000_000, power_now=5_000_000)
        self.battery("BAT1", status="Discharging", energy_now=30_000_000,
                     energy_full=40_000_000, power_now=5_000_000)
        status = read_battery(self.root)
        self.assertAlmostEqual(status.percent, 50.0)
        # 40 Wh left between them, drawing 10 W.
        self.assertEqual(status.seconds_left, 14400)

    def test_charging_wins_over_discharging(self):
        # On a two-battery machine one can feed the other, and "charging" is
        # the answer the user wants when they plug the mains in.
        self.battery("BAT0", status="Discharging", energy_now=10_000_000,
                     energy_full=40_000_000, power_now=5_000_000)
        self.battery("BAT1", status="Charging", energy_now=10_000_000,
                     energy_full=40_000_000, power_now=5_000_000)
        self.assertIs(read_battery(self.root).state, BatteryState.CHARGING)

    def test_one_full_battery_does_not_make_the_machine_full(self):
        self.battery("BAT0", status="Full", energy_now=40_000_000, energy_full=40_000_000)
        self.battery("BAT1", status="Unknown", energy_now=20_000_000, energy_full=40_000_000)
        self.assertIsNot(read_battery(self.root).state, BatteryState.FULL)

    def test_mains_offline_is_reported_as_offline(self):
        self.mains(online=0)
        self.battery(status="Discharging", capacity=50)
        self.assertFalse(read_battery(self.root).on_ac)

    def test_one_mains_online_is_enough(self):
        self.mains("AC", online=0)
        self.mains("ADP1", online=1)
        self.battery(status="Charging", capacity=50)
        self.assertTrue(read_battery(self.root).on_ac)

    def test_other_supply_types_are_ignored(self):
        # A wireless mouse reports itself here too.
        write(os.path.join(self.root, "hidpp_battery_0"), type="Battery", capacity=70,
              status="Discharging")
        write(os.path.join(self.root, "ucsi-source-psy"), type="USB", online=1)
        status = read_battery(self.root)
        self.assertAlmostEqual(status.percent, 70.0)
        self.assertIsNone(status.on_ac)


if __name__ == "__main__":
    unittest.main()
