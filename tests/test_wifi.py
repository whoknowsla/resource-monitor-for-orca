"""Tests for the wireless query."""

import os
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

import context  # noqa: F401  pylint: disable=unused-import

from resource_monitor.wifi import (
    UNKNOWN_SECURITY,
    WifiConnection,
    WifiState,
    dbm_to_quality,
    describe_security,
    parse_iw_link,
    parse_nmcli_wifi,
    query_wifi,
    split_terse_fields,
    wireless_interfaces,
)

NMCLI = """\
no:Neighbour:45:WPA2
yes:Home\\: 5G:89:WPA2 WPA3
no:Cafe::
"""

IW_CONNECTED = """\
Connected to aa:bb:cc:dd:ee:ff (on wlan0)
\tSSID: Office
\tfreq: 5180
\tsignal: -58 dBm
\ttx bitrate: 866.7 MBit/s
"""


class ParsingTests(unittest.TestCase):
    def test_split_terse_fields_honors_escapes(self):
        self.assertEqual(split_terse_fields("yes:a\\:b:c\\\\d:"), ["yes", "a:b", "c\\d", ""])

    def test_describe_security(self):
        cases = {
            "": None,
            "--": None,
            "WPA2": "WPA2-PSK",
            "WPA1 WPA2": "WPA-PSK/WPA2-PSK",
            "WPA3": "WPA3-SAE",
            "WPA2 802.1X": "WPA2-Enterprise",
            "WEP": "WEP",
            "OWE": "OWE",
            "Something": "Something",
        }
        for capabilities, expected in cases.items():
            with self.subTest(capabilities=capabilities):
                self.assertEqual(describe_security(capabilities), expected)

    def test_parse_nmcli_finds_active_network(self):
        self.assertEqual(
            parse_nmcli_wifi(NMCLI),
            WifiConnection(ssid="Home: 5G", signal=89, security="WPA2-PSK/WPA3-SAE"),
        )

    def test_parse_nmcli_without_active_network(self):
        self.assertIsNone(parse_nmcli_wifi("no:Neighbour:45:WPA2\n"))

    def test_parse_iw_link(self):
        self.assertEqual(
            parse_iw_link(IW_CONNECTED),
            WifiConnection(ssid="Office", signal=84, security=UNKNOWN_SECURITY),
        )
        self.assertIsNone(parse_iw_link("Not connected.\n"))

    def test_dbm_to_quality_is_clamped(self):
        self.assertEqual(dbm_to_quality(-50), 100)
        self.assertEqual(dbm_to_quality(-75), 50)
        self.assertEqual(dbm_to_quality(-120), 0)


class InterfaceTests(unittest.TestCase):
    def test_finds_wireless_interfaces(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "wlan0", "wireless"))
            os.makedirs(os.path.join(root, "wlan1", "phy80211"))
            os.makedirs(os.path.join(root, "eth0"))
            self.assertEqual(wireless_interfaces(root), ["wlan0", "wlan1"])

    def test_missing_directory(self):
        self.assertEqual(wireless_interfaces("/nonexistent/path"), [])


def _which(available):
    return lambda name: f"/usr/bin/{name}" if name in available else None


class QueryTests(unittest.TestCase):
    def test_no_wireless_device(self):
        status = query_wifi(interfaces=lambda: [], which=_which({"nmcli"}))
        self.assertIs(status.state, WifiState.NO_DEVICE)

    def test_nmcli_connected(self):
        def run(command):
            self.assertEqual(command[0], "/usr/bin/nmcli")
            return SimpleNamespace(stdout=NMCLI)

        status = query_wifi(interfaces=lambda: ["wlan0"], which=_which({"nmcli"}), run=run)
        self.assertIs(status.state, WifiState.CONNECTED)
        self.assertEqual(status.connection.ssid, "Home: 5G")

    def test_nmcli_not_connected(self):
        status = query_wifi(
            interfaces=lambda: ["wlan0"],
            which=_which({"nmcli"}),
            run=lambda _command: SimpleNamespace(stdout=""),
        )
        self.assertIs(status.state, WifiState.NOT_CONNECTED)

    def test_falls_back_to_iw_when_networkmanager_is_not_running(self):
        def run(command):
            if command[0].endswith("nmcli"):
                raise subprocess.CalledProcessError(8, command)
            self.assertEqual(command[1:], ["dev", "wlan0", "link"])
            return SimpleNamespace(stdout=IW_CONNECTED)

        status = query_wifi(interfaces=lambda: ["wlan0"], which=_which({"nmcli", "iw"}), run=run)
        self.assertIs(status.state, WifiState.CONNECTED)
        self.assertEqual(status.connection.security, UNKNOWN_SECURITY)

    def test_iw_not_connected_and_failures(self):
        status = query_wifi(
            interfaces=lambda: ["wlan0"],
            which=_which({"iw"}),
            run=lambda _command: SimpleNamespace(stdout="Not connected.\n"),
        )
        self.assertIs(status.state, WifiState.NOT_CONNECTED)

        def fail(command):
            raise subprocess.TimeoutExpired(command, 5)

        status = query_wifi(interfaces=lambda: ["wlan0"], which=_which({"iw"}), run=fail)
        self.assertIs(status.state, WifiState.ERROR)

    def test_no_tools(self):
        status = query_wifi(interfaces=lambda: ["wlan0"], which=_which(set()))
        self.assertIs(status.state, WifiState.ERROR)


if __name__ == "__main__":
    unittest.main()
