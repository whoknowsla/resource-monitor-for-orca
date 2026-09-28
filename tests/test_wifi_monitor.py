"""Tests for the NetworkManager wireless monitor."""

import unittest

import context  # noqa: F401  pylint: disable=unused-import
from gi.repository import GLib

import resource_monitor.wifi_monitor
from resource_monitor.wifi_monitor import (
    ACCESS_POINT_INTERFACE,
    DEVICE_INTERFACE,
    DEVICE_TYPE_WIFI,
    STATE_ACTIVATED,
    STATE_DISCONNECTED,
    STATE_UNAVAILABLE,
    STATE_UNMANAGED,
    WIRELESS_INTERFACE,
    WifiEvent,
    WifiMonitor,
    classify_transition,
    decode_ssid,
)

STATE_PREPARE = 40
STATE_DEACTIVATING = 110
STATE_FAILED = 120

WIFI = "/org/freedesktop/NetworkManager/Devices/3"
ETHERNET = "/org/freedesktop/NetworkManager/Devices/2"
ACCESS_POINT = "/org/freedesktop/NetworkManager/AccessPoint/7"


class TransitionTests(unittest.TestCase):
    def test_transitions(self):
        cases = [
            (STATE_ACTIVATED, 90, WifiEvent.CONNECTED),
            (STATE_DEACTIVATING, STATE_ACTIVATED, WifiEvent.DISCONNECTED),
            (STATE_DISCONNECTED, STATE_ACTIVATED, WifiEvent.DISCONNECTED),
            (STATE_DISCONNECTED, STATE_UNAVAILABLE, WifiEvent.ENABLED),
            (STATE_DISCONNECTED, STATE_UNMANAGED, WifiEvent.ENABLED),
            (STATE_UNAVAILABLE, STATE_DEACTIVATING, WifiEvent.DISABLED),
            (STATE_UNAVAILABLE, STATE_DISCONNECTED, WifiEvent.DISABLED),
            (STATE_PREPARE, STATE_DISCONNECTED, None),
            (STATE_DISCONNECTED, STATE_FAILED, None),
            (STATE_DISCONNECTED, STATE_DEACTIVATING, None),
            (STATE_ACTIVATED, STATE_ACTIVATED, None),
        ]
        for new, old, expected in cases:
            with self.subTest(new=new, old=old):
                self.assertIs(classify_transition(new, old), expected)

    def test_decode_ssid(self):
        self.assertEqual(decode_ssid([72, 111, 109, 101]), "Home")
        self.assertEqual(decode_ssid(b"caf\xc3\xa9"), "café")
        self.assertEqual(decode_ssid(b"\xff"), "�")


class FakeNetworkManager(WifiMonitor):
    """Answers property reads from a table, synchronously."""

    PROPERTIES = {
        (WIFI, DEVICE_INTERFACE, "DeviceType"): DEVICE_TYPE_WIFI,
        (ETHERNET, DEVICE_INTERFACE, "DeviceType"): 1,
        (WIFI, WIRELESS_INTERFACE, "ActiveAccessPoint"): ACCESS_POINT,
        (ACCESS_POINT, ACCESS_POINT_INTERFACE, "Ssid"): list(b"Home"),
    }

    def __init__(self, notify):
        super().__init__(notify)
        self.reads = []

    def _get_property(self, path, interface, name, on_value):
        self.reads.append((path, name))
        on_value(self.PROPERTIES[(path, interface, name)])


def state_changed(monitor, path, new, old):
    parameters = GLib.Variant("(uuu)", (new, old, 0))
    monitor._on_state_changed(None, "", path, DEVICE_INTERFACE, "StateChanged", parameters)


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.monitor = FakeNetworkManager(lambda event, ssid: self.events.append((event, ssid)))

    def test_connect_then_disconnect_names_the_network(self):
        state_changed(self.monitor, WIFI, STATE_ACTIVATED, 90)
        state_changed(self.monitor, WIFI, STATE_DEACTIVATING, STATE_ACTIVATED)
        self.assertEqual(
            self.events,
            [(WifiEvent.CONNECTED, "Home"), (WifiEvent.DISCONNECTED, "Home")],
        )

    def test_radio_changes(self):
        state_changed(self.monitor, WIFI, STATE_UNAVAILABLE, STATE_DISCONNECTED)
        state_changed(self.monitor, WIFI, STATE_DISCONNECTED, STATE_UNAVAILABLE)
        self.assertEqual(self.events, [(WifiEvent.DISABLED, ""), (WifiEvent.ENABLED, "")])

    def test_other_devices_are_ignored_and_their_type_is_cached(self):
        state_changed(self.monitor, ETHERNET, STATE_ACTIVATED, 90)
        state_changed(self.monitor, ETHERNET, STATE_DISCONNECTED, STATE_ACTIVATED)
        self.assertEqual(self.events, [])
        self.assertEqual(self.monitor.reads.count((ETHERNET, "DeviceType")), 1)

    def test_uninteresting_transitions_do_not_query_networkmanager(self):
        state_changed(self.monitor, WIFI, STATE_PREPARE, STATE_DISCONNECTED)
        self.assertEqual(self.monitor.reads, [])

    def test_existing_connection_is_remembered_at_start(self):
        self.monitor.PROPERTIES = {
            **FakeNetworkManager.PROPERTIES,
            (WIFI, DEVICE_INTERFACE, "State"): STATE_ACTIVATED,
            (ETHERNET, DEVICE_INTERFACE, "State"): STATE_ACTIVATED,
        }
        self.monitor._on_devices(([WIFI, ETHERNET],))
        state_changed(self.monitor, WIFI, STATE_DISCONNECTED, STATE_ACTIVATED)
        self.assertEqual(self.events, [(WifiEvent.DISCONNECTED, "Home")])

    def test_removed_device_is_forgotten(self):
        state_changed(self.monitor, WIFI, STATE_ACTIVATED, 90)
        removed = GLib.Variant("(o)", (WIFI,))
        self.monitor._on_device_removed(None, "", "", "", "DeviceRemoved", removed)
        state_changed(self.monitor, WIFI, STATE_DISCONNECTED, STATE_ACTIVATED)
        self.assertEqual(self.events[-1], (WifiEvent.DISCONNECTED, ""))

    def test_stale_bus_callback_after_restart_does_not_subscribe(self):
        class FakeBus:
            def __init__(self):
                self.subscribed = 0

            def signal_subscribe(self, *_args):
                self.subscribed += 1
                return self.subscribed

            def call(self, *_args):
                pass

        bus = FakeBus()
        stale = object()
        self.monitor._running = True
        original = resource_monitor.wifi_monitor.Gio.bus_get_finish
        resource_monitor.wifi_monitor.Gio.bus_get_finish = lambda _result: bus
        try:
            self.monitor._on_bus_ready(None, None, stale)
            self.assertEqual(bus.subscribed, 0)
            self.monitor._on_bus_ready(None, None, self.monitor._cancellable)
            self.assertEqual(bus.subscribed, 2)
        finally:
            resource_monitor.wifi_monitor.Gio.bus_get_finish = original

    def test_stop_without_start_is_harmless(self):
        self.monitor.stop()
        self.monitor.stop()


if __name__ == "__main__":
    unittest.main()
