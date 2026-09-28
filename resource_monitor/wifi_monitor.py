"""Watches NetworkManager for wireless connects, disconnects, and radio changes.

Signals arrive on Orca's GLib main loop, so the notify callback may present
messages directly. Every D-Bus call is asynchronous; a stalled
NetworkManager cannot freeze Orca. Without NetworkManager the monitor stays
silent.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402  pylint: disable=wrong-import-position

NM_BUS = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
NM_INTERFACE = "org.freedesktop.NetworkManager"
DEVICE_INTERFACE = "org.freedesktop.NetworkManager.Device"
WIRELESS_INTERFACE = "org.freedesktop.NetworkManager.Device.Wireless"
ACCESS_POINT_INTERFACE = "org.freedesktop.NetworkManager.AccessPoint"
PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"
CALL_TIMEOUT_MS = 2000

DEVICE_TYPE_WIFI = 2
STATE_UNMANAGED = 10
STATE_UNAVAILABLE = 20
STATE_DISCONNECTED = 30
STATE_ACTIVATED = 100
_RADIO_OFF_STATES = (STATE_UNMANAGED, STATE_UNAVAILABLE)
_NO_ACCESS_POINT = "/"


class WifiEvent(enum.Enum):
    """Something worth telling the user about a wireless device."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ENABLED = "enabled"
    DISABLED = "disabled"


def classify_transition(new_state: int, old_state: int) -> WifiEvent | None:
    """Maps a NetworkManager device state change to a user-facing event."""

    if new_state == old_state:
        return None
    if new_state == STATE_ACTIVATED:
        return WifiEvent.CONNECTED
    if old_state == STATE_ACTIVATED:
        return WifiEvent.DISCONNECTED
    if new_state == STATE_DISCONNECTED and old_state in _RADIO_OFF_STATES:
        return WifiEvent.ENABLED
    if new_state in _RADIO_OFF_STATES and old_state >= STATE_DISCONNECTED:
        return WifiEvent.DISABLED
    return None


def decode_ssid(raw: Any) -> str:
    """Decodes an SSID byte array; SSIDs are usually, but not always, UTF-8."""

    return bytes(raw).decode("utf-8", errors="replace")


class WifiMonitor:
    """Subscribes to NetworkManager device signals and reports wireless events."""

    def __init__(self, notify: Callable[[WifiEvent, str], None]) -> None:
        self._notify = notify
        self._connection: Gio.DBusConnection | None = None
        self._cancellable = Gio.Cancellable()
        self._subscriptions: list[int] = []
        self._wifi_devices: set[str] = set()
        self._other_devices: set[str] = set()
        self._ssids: dict[str, str] = {}
        self._running = False

    def start(self) -> None:
        """Connects to the system bus. Safe to call more than once."""

        if self._running:
            return
        self._running = True
        self._cancellable = Gio.Cancellable()
        Gio.bus_get(Gio.BusType.SYSTEM, self._cancellable, self._on_bus_ready, self._cancellable)

    def stop(self) -> None:
        """Unsubscribes and forgets all state. Safe to call more than once."""

        if not self._running:
            return
        self._running = False
        self._cancellable.cancel()
        if self._connection is not None:
            for subscription in self._subscriptions:
                self._connection.signal_unsubscribe(subscription)
        self._subscriptions.clear()
        self._wifi_devices.clear()
        self._other_devices.clear()
        self._ssids.clear()
        self._connection = None

    def _on_bus_ready(
        self,
        _source: Any,
        result: Gio.AsyncResult,
        cancellable: Gio.Cancellable,
    ) -> None:
        try:
            connection = Gio.bus_get_finish(result)
        except GLib.Error:
            return
        # A stop() and start() may have happened while this request was in
        # flight; only the latest start may subscribe.
        if not self._running or cancellable is not self._cancellable:
            return
        self._connection = connection
        self._subscriptions = [
            connection.signal_subscribe(
                NM_BUS,
                DEVICE_INTERFACE,
                "StateChanged",
                None,
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_state_changed,
            ),
            connection.signal_subscribe(
                NM_BUS,
                NM_INTERFACE,
                "DeviceRemoved",
                NM_PATH,
                None,
                Gio.DBusSignalFlags.NONE,
                self._on_device_removed,
            ),
        ]
        self._call(NM_PATH, NM_INTERFACE, "GetDevices", None, "(ao)", self._on_devices)

    def _call(
        self,
        path: str,
        interface: str,
        method: str,
        parameters: GLib.Variant | None,
        reply_type: str,
        on_reply: Callable[[tuple[Any, ...]], None],
    ) -> None:
        if self._connection is None:
            return
        self._connection.call(
            NM_BUS,
            path,
            interface,
            method,
            parameters,
            GLib.VariantType.new(reply_type),
            Gio.DBusCallFlags.NONE,
            CALL_TIMEOUT_MS,
            self._cancellable,
            self._on_call_done,
            on_reply,
        )

    def _on_call_done(
        self,
        connection: Gio.DBusConnection,
        result: Gio.AsyncResult,
        on_reply: Callable[[tuple[Any, ...]], None],
    ) -> None:
        try:
            reply = connection.call_finish(result)
        except GLib.Error:
            # Cancelled on stop, or NetworkManager went away; nothing to report.
            return
        if self._running:
            on_reply(reply.unpack())

    def _get_property(
        self,
        path: str,
        interface: str,
        name: str,
        on_value: Callable[[Any], None],
    ) -> None:
        self._call(
            path,
            PROPERTIES_INTERFACE,
            "Get",
            GLib.Variant("(ss)", (interface, name)),
            "(v)",
            lambda values: on_value(values[0]),
        )

    def _on_devices(self, values: tuple[Any, ...]) -> None:
        for path in values[0]:
            self._with_device_type(
                path, lambda is_wifi, path=path: self._on_initial_device(path, is_wifi)
            )

    def _on_initial_device(self, path: str, is_wifi: bool) -> None:
        if not is_wifi:
            return
        # Remember the current network so a later disconnect can name it.
        self._get_property(
            path,
            DEVICE_INTERFACE,
            "State",
            lambda state: state == STATE_ACTIVATED and self._remember_ssid(path),
        )

    def _with_device_type(self, path: str, done: Callable[[bool], None]) -> None:
        if path in self._wifi_devices:
            done(True)
            return
        if path in self._other_devices:
            done(False)
            return

        def on_type(device_type: int) -> None:
            is_wifi = device_type == DEVICE_TYPE_WIFI
            (self._wifi_devices if is_wifi else self._other_devices).add(path)
            done(is_wifi)

        self._get_property(path, DEVICE_INTERFACE, "DeviceType", on_type)

    def _fetch_ssid(self, path: str, done: Callable[[str], None]) -> None:
        def on_access_point(access_point: str) -> None:
            if not access_point or access_point == _NO_ACCESS_POINT:
                done("")
                return
            self._get_property(
                access_point,
                ACCESS_POINT_INTERFACE,
                "Ssid",
                lambda raw: done(decode_ssid(raw)),
            )

        self._get_property(path, WIRELESS_INTERFACE, "ActiveAccessPoint", on_access_point)

    def _remember_ssid(self, path: str, then: Callable[[str], None] | None = None) -> None:
        def store(ssid: str) -> None:
            self._ssids[path] = ssid
            if then is not None:
                then(ssid)

        self._fetch_ssid(path, store)

    def _on_state_changed(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        path: str,
        _interface: str,
        _signal: str,
        parameters: GLib.Variant,
    ) -> None:
        new_state, old_state, _reason = parameters.unpack()
        event = classify_transition(new_state, old_state)
        if event is None:
            return
        self._with_device_type(
            path,
            lambda is_wifi: is_wifi and self._handle_event(path, event),
        )

    def _handle_event(self, path: str, event: WifiEvent) -> None:
        if event is WifiEvent.CONNECTED:
            self._remember_ssid(path, lambda ssid: self._notify(WifiEvent.CONNECTED, ssid))
        elif event is WifiEvent.DISCONNECTED:
            self._notify(WifiEvent.DISCONNECTED, self._ssids.pop(path, ""))
        else:
            self._notify(event, "")

    def _on_device_removed(
        self,
        _connection: Gio.DBusConnection,
        _sender: str,
        _path: str,
        _interface: str,
        _signal: str,
        parameters: GLib.Variant,
    ) -> None:
        (removed,) = parameters.unpack()
        self._wifi_devices.discard(removed)
        self._other_devices.discard(removed)
        self._ssids.pop(removed, None)
