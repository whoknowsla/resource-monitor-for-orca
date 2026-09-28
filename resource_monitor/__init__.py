"""Resource Monitor for Orca.

Reports processor load, memory, drives, GPU, wireless network, uptime, and
operating system information on Linux. A port of the Resource Monitor add-on
for NVDA.
"""

from __future__ import annotations

import functools
import os
import time
from typing import Any

from orca import command_manager, keybindings
from orca.command import Command, KeyboardCommand
from orca.extension import Extension, ExtensionPreference

from .formatting import CELSIUS, FAHRENHEIT
from .i18n import _
from .layer import CommandLayer, EnterResult, LayerKey
from .resources import RESOURCES, ReportOptions, Resource, gather
from .wifi_monitor import WifiEvent, WifiMonitor
from .worker import Worker

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
_SOUNDS_DIR = os.path.join(_PACKAGE_DIR, "sounds")

ENTER_LAYER_COMMAND = "resource_monitor_enter_layer"
LEAVE_LAYER_COMMAND = "resource_monitor_layer_leave"

# Orca's own double-press window.
DOUBLE_PRESS_SECONDS = 0.5

SETTING_TEMPERATURE_UNIT = "gpu-temperature-unit"
SETTING_WIFI_NOTIFICATION = "wifi-notification"
SETTING_LAYER_TIMEOUT = "layer-timeout"
DEFAULT_WIFI_NOTIFICATION = "both"
DEFAULT_LAYER_TIMEOUT = 10
MAX_LAYER_TIMEOUT = 300

# (duration in seconds, frequency in Hz)
_ENTER_TONE = (0.05, 660)
_LEAVE_TONE = (0.1, 330)


class PressTracker:
    """Detects a second press of the same command within the double-press window."""

    def __init__(self, window: float = DOUBLE_PRESS_SECONDS) -> None:
        self._window = window
        self._last_name = ""
        self._last_time = float("-inf")

    def is_repeat(self, name: str, now: float) -> bool:
        """Records a press and returns True if it repeats the previous one."""

        repeat = name == self._last_name and now - self._last_time <= self._window
        self._last_name = name
        self._last_time = now
        return repeat


class ResourceMonitor(Extension):
    """Reports system resource usage, with a command layer and direct shortcuts."""

    GROUP_LABEL = _("Resource Monitor")
    DESCRIPTION = _(
        "Reports processor load, memory, drives, GPU, wireless network, uptime, "
        "and operating system information."
    )
    VERSION = "1.0.0"
    AUTHOR = "Deniz Aygun"
    COPYRIGHT = (
        "2026 Deniz Aygun. Based on Resource Monitor for NVDA by Alex Hall, Joseph Lee, "
        "Kefas Lungu, Beqa Gozalishvili, Tuukka Ojala, Ethin Probst, Kevin Derome, "
        "and other NVDA contributors."
    )

    def __init__(self) -> None:
        self._worker = Worker()
        self._presses = PressTracker()
        self._wifi_monitor = WifiMonitor(self._on_wifi_event)
        self._stopped = False
        self._layer = CommandLayer(
            self,
            self.GROUP_LABEL,
            ENTER_LAYER_COMMAND,
            self._layer_timeout,
            self._play_leave_tone,
        )
        super().__init__()

    # -- settings --------------------------------------------------------

    def get_preferences(self) -> list[ExtensionPreference]:
        return [
            ExtensionPreference.enum(
                SETTING_TEMPERATURE_UNIT,
                # Translators: Label for the setting that selects the GPU temperature unit.
                _("GPU temperature unit"),
                (
                    # Translators: An option for the GPU temperature unit.
                    (CELSIUS, _("Celsius")),
                    # Translators: An option for the GPU temperature unit.
                    (FAHRENHEIT, _("Fahrenheit")),
                ),
                CELSIUS,
            ),
            ExtensionPreference.enum(
                SETTING_WIFI_NOTIFICATION,
                # Translators: Label for the setting that selects how wi-fi connects
                # and disconnects are reported.
                _("Wi-fi connect/disconnect notification"),
                (
                    # Translators: An option for the wi-fi notification setting.
                    ("off", _("off")),
                    # Translators: An option for the wi-fi notification setting.
                    ("message", _("message")),
                    # Translators: An option for the wi-fi notification setting.
                    ("sound", _("sound")),
                    # Translators: An option for the wi-fi notification setting.
                    ("both", _("both")),
                ),
                DEFAULT_WIFI_NOTIFICATION,
            ),
            ExtensionPreference.integer(
                SETTING_LAYER_TIMEOUT,
                # Translators: Label for the setting that leaves the command layer
                # automatically when no layer key has been pressed for a while.
                _("Leave the command layer after this many idle seconds (0 = never)"),
                DEFAULT_LAYER_TIMEOUT,
                0,
                MAX_LAYER_TIMEOUT,
            ),
        ]

    def _temperature_unit(self) -> str:
        return self.settings.get(SETTING_TEMPERATURE_UNIT, default=CELSIUS)

    def _layer_timeout(self) -> int:
        return int(self.settings.get(SETTING_LAYER_TIMEOUT, default=DEFAULT_LAYER_TIMEOUT))

    # -- commands --------------------------------------------------------

    def _get_commands(self) -> list[Command]:
        entry_binding = keybindings.KeyBinding("e", keybindings.ORCA_SHIFT_MODIFIER_MASK)
        commands: list[Command] = [
            KeyboardCommand(
                ENTER_LAYER_COMMAND,
                self.enter_layer,
                self.GROUP_LABEL,
                # Translators: Description of the command that enters the command layer.
                _("Enters the Resource Monitor command layer."),
                desktop_keybinding=entry_binding,
                laptop_keybinding=entry_binding,
            )
        ]
        for resource in RESOURCES:
            binding = keybindings.KeyBinding(
                resource.shortcut,
                keybindings.ORCA_SHIFT_MODIFIER_MASK,
            )
            commands.append(
                KeyboardCommand(
                    f"resource_monitor_{resource.name}",
                    functools.partial(self._on_resource_command, resource),
                    self.GROUP_LABEL,
                    resource.description,
                    desktop_keybinding=binding,
                    laptop_keybinding=binding,
                )
            )
        return commands

    def _layer_keys(self) -> list[LayerKey]:
        keys = [
            LayerKey(
                f"resource_monitor_layer_{resource.name}",
                resource.description,
                resource.layer_key,
                resource.layer_modifiers,
                functools.partial(self._request, resource),
            )
            for resource in RESOURCES
        ]
        keys.append(
            LayerKey(
                LEAVE_LAYER_COMMAND,
                # Translators: Description of the key that leaves the command layer.
                _("Leaves the Resource Monitor command layer."),
                "Escape",
                keybindings.NO_MODIFIER_MASK,
                self.leave_layer,
            )
        )
        return keys

    def set_up_commands(self) -> None:
        super().set_up_commands()
        # The base class registers nothing for a disabled extension; follow its lead.
        if command_manager.get_manager().get_command(ENTER_LAYER_COMMAND) is not None:
            self._layer.register(self._layer_keys())

    def reset_commands(self, reason: str | None = None) -> None:
        self._layer.unregister(reason or "")
        super().reset_commands(reason)

    def enter_layer(self) -> bool:
        """Enters the command layer."""

        result = self._layer.enter()
        if result is EnterResult.ENTERED:
            if not self.controller.play_tone_internal(*_ENTER_TONE):
                self.controller.speak_message_internal(self.GROUP_LABEL)
            self.controller.display_message_internal(self.GROUP_LABEL)
        elif result is EnterResult.BLOCKED:
            self.controller.present_message_internal(
                # Translators: Reported when another Orca mode prevents entering the layer.
                _("The command layer cannot be used while another Orca mode is active.")
            )
        elif result is EnterResult.UNAVAILABLE:
            self.controller.present_message_internal(
                # Translators: Reported when this Orca version does not support the layer.
                _(
                    "The command layer is not available in this version of Orca. "
                    "Use Orca+Shift+1 through Orca+Shift+9 instead."
                )
            )
        return True

    def leave_layer(self) -> None:
        """Leaves the command layer with an audible cue."""

        if self._layer.leave():
            self._play_leave_tone()

    def _play_leave_tone(self) -> None:
        self.controller.play_tone_internal(*_LEAVE_TONE)

    # Modal input handler protocol, active only while the layer is.

    def will_handle_event(self, script: Any, event: Any, command: Any = None) -> bool:
        """Claims key presses for the command layer."""

        return self._layer.will_handle_event(script, event, command)

    def handle_event(self, script: Any, event: Any, command: Any = None) -> bool:
        """Handles a key press claimed for the command layer."""

        return self._layer.handle_event(script, event, command)

    # -- reporting -------------------------------------------------------

    def _on_resource_command(self, resource: Resource) -> bool:
        self._request(resource)
        return True

    def _request(self, resource: Resource) -> None:
        copy = self._presses.is_repeat(resource.name, time.monotonic())
        options = ReportOptions(temperature_unit=self._temperature_unit())
        self._worker.submit(
            lambda: gather(resource, options),
            lambda text: self._deliver(text, copy),
        )

    def _deliver(self, text: str, copy: bool) -> None:
        if self._stopped:
            return
        if not copy:
            self.controller.present_message_internal(text)
            return
        if self.controller.set_clipboard_text_internal(text):
            # Translators: Reported after resource information was copied to the clipboard.
            self.controller.present_message_internal(_("Copied to clipboard"))
        else:
            # Translators: Reported when resource information could not be copied.
            self.controller.present_message_internal(_("Could not copy to the clipboard"))

    # -- wi-fi notifications ---------------------------------------------

    def _on_wifi_event(self, event: WifiEvent, ssid: str) -> None:
        if self._stopped:
            return
        mode = self.settings.get(SETTING_WIFI_NOTIFICATION, default=DEFAULT_WIFI_NOTIFICATION)
        # Translators: Used when a wireless network does not broadcast its name.
        name = ssid or _("hidden network")
        if event is WifiEvent.CONNECTED:
            message, sound = _("Connected to {}").format(name), "connect.wav"
        elif event is WifiEvent.DISCONNECTED:
            message, sound = _("Disconnected from {}").format(name), "disconnect.wav"
        elif event is WifiEvent.ENABLED:
            message, sound = _("A wireless device has been enabled"), "connect.wav"
        else:
            message, sound = _("A wireless device has been disabled"), "disconnect.wav"
        if mode in ("message", "both"):
            self.controller.present_message_internal(message)
        if mode in ("sound", "both"):
            path = os.path.join(_SOUNDS_DIR, sound)
            if os.path.isfile(path):
                self.controller.play_sound_file_internal(path, interrupt=False)

    # -- lifecycle -------------------------------------------------------

    def on_ready(self) -> None:
        self._wifi_monitor.start()

    def on_enabled(self) -> None:
        self._wifi_monitor.start()

    def on_disabled(self) -> None:
        self._stopped = True
        self._layer.leave()
        self._wifi_monitor.stop()
        self._worker.stop()

    def on_shutdown(self) -> None:
        self._stopped = True
        self._wifi_monitor.stop()
        self._worker.stop()
