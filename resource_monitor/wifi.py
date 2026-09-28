"""Reports the current wireless connection.

NetworkManager's nmcli is used when available because it knows the network's
security type. Without it, iw provides the network name and signal strength.
"""

from __future__ import annotations

import enum
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

SYS_CLASS_NET = "/sys/class/net"
COMMAND_TIMEOUT_SECONDS = 5

NMCLI_ARGUMENTS = (
    "-t",
    "-e",
    "yes",
    "-f",
    "ACTIVE,SSID,SIGNAL,SECURITY",
    "device",
    "wifi",
    "list",
    "--rescan",
    "no",
)

_IW_SSID = re.compile(r"^\s*SSID:\s?(.*)$", re.MULTILINE)
_IW_SIGNAL = re.compile(r"^\s*signal:\s*(-?\d+)\s*dBm", re.MULTILINE)

_WPA_VERSIONS = {"WPA1": 1, "WPA2": 2, "WPA3": 3}
_PERSONAL_NAMES = {1: "WPA-PSK", 2: "WPA2-PSK", 3: "WPA3-SAE"}
_ENTERPRISE_NAMES = {1: "WPA-Enterprise", 2: "WPA2-Enterprise", 3: "WPA3-Enterprise"}


class WifiState(enum.Enum):
    """Overall result of a wireless query."""

    NO_DEVICE = "no-device"
    NOT_CONNECTED = "not-connected"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass(frozen=True)
class WifiConnection:
    """The network an interface is connected to.

    security is None for an open network, and UNKNOWN_SECURITY when the
    security type could not be determined.
    """

    ssid: str
    signal: int | None
    security: str | None


UNKNOWN_SECURITY = "?"


@dataclass(frozen=True)
class WifiStatus:
    """Result of query_wifi."""

    state: WifiState
    connection: WifiConnection | None = None


Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        timeout=COMMAND_TIMEOUT_SECONDS,
        check=True,
        env={**os.environ, "LC_ALL": "C"},
    )


def wireless_interfaces(root: str = SYS_CLASS_NET) -> list[str]:
    """Returns the names of network interfaces that are wireless."""

    try:
        names = sorted(os.listdir(root))
    except OSError:
        return []
    return [
        name
        for name in names
        if os.path.isdir(os.path.join(root, name, "wireless"))
        or os.path.exists(os.path.join(root, name, "phy80211"))
    ]


def split_terse_fields(line: str) -> list[str]:
    """Splits one line of nmcli terse output, honoring backslash escapes."""

    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    fields.append("".join(current))
    return fields


def describe_security(capabilities: str) -> str | None:
    """Turns nmcli's SECURITY column into names such as WPA2-PSK. None means open."""

    tokens = capabilities.split()
    if not tokens or tokens == ["--"]:
        return None
    if "OWE" in tokens:
        return "OWE"
    if "WEP" in tokens:
        return "WEP"
    versions = sorted({_WPA_VERSIONS[token] for token in tokens if token in _WPA_VERSIONS})
    if not versions:
        return capabilities.strip()
    names = _ENTERPRISE_NAMES if "802.1X" in tokens else _PERSONAL_NAMES
    return "/".join(names[version] for version in versions)


def parse_nmcli_wifi(output: str) -> WifiConnection | None:
    """Returns the active network from nmcli's wifi list, or None."""

    for line in output.splitlines():
        fields = split_terse_fields(line)
        if len(fields) < 4 or fields[0] != "yes":
            continue
        signal = int(fields[2]) if fields[2].isdigit() else None
        return WifiConnection(ssid=fields[1], signal=signal, security=describe_security(fields[3]))
    return None


def dbm_to_quality(dbm: int) -> int:
    """Converts a signal level in dBm to the 0 to 100 scale NetworkManager uses."""

    return max(0, min(100, 2 * (dbm + 100)))


def parse_iw_link(output: str) -> WifiConnection | None:
    """Parses `iw dev IFACE link` output, or returns None when not connected."""

    if not output.lstrip().startswith("Connected to"):
        return None
    ssid_match = _IW_SSID.search(output)
    signal_match = _IW_SIGNAL.search(output)
    return WifiConnection(
        ssid=ssid_match.group(1).strip() if ssid_match else "",
        signal=dbm_to_quality(int(signal_match.group(1))) if signal_match else None,
        security=UNKNOWN_SECURITY,
    )


def _query_nmcli(nmcli: str, run: Runner) -> WifiStatus | None:
    try:
        result = run([nmcli, *NMCLI_ARGUMENTS])
    except (OSError, subprocess.SubprocessError):
        # NetworkManager may not be running; let the caller try iw.
        return None
    connection = parse_nmcli_wifi(result.stdout)
    if connection is None:
        return WifiStatus(WifiState.NOT_CONNECTED)
    return WifiStatus(WifiState.CONNECTED, connection)


def _query_iw(iw: str, interfaces: Sequence[str], run: Runner) -> WifiStatus:
    failures = 0
    for interface in interfaces:
        try:
            result = run([iw, "dev", interface, "link"])
        except (OSError, subprocess.SubprocessError):
            failures += 1
            continue
        connection = parse_iw_link(result.stdout)
        if connection is not None:
            return WifiStatus(WifiState.CONNECTED, connection)
    if failures == len(interfaces):
        return WifiStatus(WifiState.ERROR)
    return WifiStatus(WifiState.NOT_CONNECTED)


def query_wifi(
    interfaces: Callable[[], list[str]] = wireless_interfaces,
    which: Callable[[str], str | None] = shutil.which,
    run: Runner = _run,
) -> WifiStatus:
    """Returns the wireless connection state. Blocks; call off the main thread."""

    found = interfaces()
    if not found:
        return WifiStatus(WifiState.NO_DEVICE)
    nmcli = which("nmcli")
    if nmcli:
        status = _query_nmcli(nmcli, run)
        if status is not None:
            return status
    iw = which("iw")
    if iw:
        return _query_iw(iw, found, run)
    return WifiStatus(WifiState.ERROR)
