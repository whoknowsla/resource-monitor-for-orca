"""The Resource Monitor command layer.

After the layer is entered, single keys (C, M, D, ...) report resources until
Escape, any other Orca command, or an idle timeout leaves it.

How it works, and why it goes beyond the documented extension API:

* Orca only sees keys it has grabbed, and it refuses user-extension bindings
  that an Orca command already uses. The layer letters are Orca's structural
  navigation keys, so layer commands are registered through the command
  manager directly, suspended, and hidden from the key bindings list. They are
  grabbed only while the layer is active.
* While active, the extension instance is Orca's modal input handler. Orca
  consults it only for keys that match a command, never for other typing.
  The handler resolves layer keys in favour of the layer (browse mode binds
  the same letters) and treats any other Orca command as a request to leave
  the layer, then runs that command.
* Keys that are not Orca commands are never seen by extensions, so unlike the
  NVDA add-on, typing an unrelated key cannot end the layer. The idle timeout
  covers that case.
* When two bindings share a key, AT-SPI keeps only the first grab. After
  leaving, Orca's grabs are therefore refreshed so a browse-mode key that lost
  its grab while the layer held it gets it back.
"""

from __future__ import annotations

import enum
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import gi

gi.require_version("GLib", "2.0")
from gi.repository import GLib  # noqa: E402  pylint: disable=wrong-import-position
from orca import command_manager, keybindings  # noqa: E402
from orca.command import KeyboardCommand  # noqa: E402

_log = logging.getLogger(__name__)

LAYER_GROUP = "resource_monitor_layer"


class EnterResult(enum.Enum):
    """Outcome of CommandLayer.enter."""

    ENTERED = "entered"
    ALREADY_ACTIVE = "already-active"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class LayerKey:
    """A key inside the layer and what it does."""

    name: str
    description: str
    keysym: str
    modifiers: int
    action: Callable[[], None]


class Timer(Protocol):
    """Schedules a one-shot callback on the main loop."""

    def start(self, seconds: int, callback: Callable[[], None]) -> Any:
        """Starts the timer and returns a handle."""

    def cancel(self, handle: Any) -> None:
        """Cancels a timer that has not fired."""


class GLibTimer:
    """Timer backed by the GLib main loop."""

    def start(self, seconds: int, callback: Callable[[], None]) -> Any:
        def fire() -> bool:
            callback()
            return GLib.SOURCE_REMOVE

        return GLib.timeout_add_seconds(seconds, fire)

    def cancel(self, handle: Any) -> None:
        GLib.source_remove(handle)


def _idle(callback: Callable[[], None]) -> None:
    def run() -> bool:
        callback()
        return GLib.SOURCE_REMOVE

    GLib.idle_add(run)


class CommandLayer:  # pylint: disable=too-many-instance-attributes
    """Owns the layer's commands, grabs, modal handler, and idle timer."""

    # pylint: disable-next=too-many-arguments
    def __init__(
        self,
        handler: object,
        group_label: str,
        entry_command_name: str,
        get_timeout: Callable[[], int],
        on_timeout: Callable[[], None],
        *,
        manager: Callable[[], Any] = command_manager.get_manager,
        timer: Timer | None = None,
        idle: Callable[[Callable[[], None]], None] = _idle,
    ) -> None:
        # handler must be the extension instance: Orca only limits what a
        # modal handler sees when it is a registered user extension.
        self._handler = handler
        self._group_label = group_label
        self._entry_command_name = entry_command_name
        self._get_timeout = get_timeout
        self._on_timeout = on_timeout
        self._manager = manager
        self._timer = timer if timer is not None else GLibTimer()
        self._idle = idle
        self._keys: list[LayerKey] = []
        self._commands: list[KeyboardCommand] = []
        self._timer_handle: Any = None
        self._active = False

    @property
    def is_active(self) -> bool:
        """True while the layer keys are live."""

        return self._active

    @property
    def is_registered(self) -> bool:
        """True when the layer commands exist in Orca's command manager."""

        return bool(self._commands)

    def register(self, keys: Sequence[LayerKey]) -> bool:
        """Adds the suspended layer commands to Orca. Returns False if Orca refused them."""

        if self._commands:
            return True
        manager = self._manager()
        commands: list[KeyboardCommand] = []
        try:
            for key in keys:
                binding = keybindings.KeyBinding(key.keysym, key.modifiers)
                command = KeyboardCommand(
                    key.name,
                    self._command_function(key),
                    self._group_label,
                    key.description,
                    desktop_keybinding=binding,
                    laptop_keybinding=binding,
                    suspended=True,
                    activation_group=LAYER_GROUP,
                    user_visible=False,
                )
                manager.add_command(command)
                commands.append(command)
        except Exception:  # pylint: disable=broad-exception-caught
            # Orca internals changed; keep the direct shortcuts working without the layer.
            _log.exception("Resource Monitor: could not register the command layer")
            manager.remove_commands([command.get_name() for command in commands], "layer failed")
            return False
        self._keys = list(keys)
        self._commands = commands
        return True

    def unregister(self, reason: str = "") -> None:
        """Leaves the layer and removes its commands from Orca."""

        self.leave()
        if not self._commands:
            return
        names = [command.get_name() for command in self._commands]
        self._commands = []
        self._keys = []
        self._manager().remove_commands(names, reason or "Resource Monitor layer removed")

    def enter(self) -> EnterResult:
        """Makes the layer keys live."""

        if not self._commands:
            return EnterResult.UNAVAILABLE
        if self._active:
            return EnterResult.ALREADY_ACTIVE
        manager = self._manager()
        if not manager.set_modal_handler(self._handler):
            return EnterResult.BLOCKED
        try:
            manager.set_group_suspended(LAYER_GROUP, False)
        except Exception:  # pylint: disable=broad-exception-caught
            _log.exception("Resource Monitor: could not activate the command layer")
            manager.clear_modal_handler(self._handler)
            return EnterResult.UNAVAILABLE
        self._active = True
        self._restart_timer()
        return EnterResult.ENTERED

    def leave(self) -> bool:
        """Releases the layer keys. Returns False if the layer was not active."""

        if not self._active:
            return False
        self._active = False
        self._cancel_timer()
        manager = self._manager()
        try:
            manager.set_group_suspended(LAYER_GROUP, True)
        finally:
            manager.clear_modal_handler(self._handler)
            self._idle(lambda: manager.activate_commands("Resource Monitor layer left"))
        return True

    def will_handle_event(self, _script: Any, event: Any, _command: Any = None) -> bool:
        """Claims every key press that reaches the modal handler while active."""

        return self._active and event.is_pressed_key()

    def handle_event(self, script: Any, event: Any, command: Any = None) -> bool:
        """Runs a layer key, ignores the entry key, or leaves and passes other commands on."""

        key = self._key_for_event(event) if self._active else None
        if key is not None:
            self._run(key)
            return True
        if command is None:
            return False
        if self._active and command.get_name() == self._entry_command_name:
            return True
        self.leave()
        return bool(command.execute(script, event))

    def _key_for_event(self, event: Any) -> LayerKey | None:
        for key, command in zip(self._keys, self._commands, strict=True):
            binding = command.get_keybinding()
            if binding is not None and binding.matches(event.id, event.hw_code, event.modifiers):
                return key
        return None

    def _command_function(self, key: LayerKey) -> Callable[[Any, Any], bool]:
        # Called by Orca directly when no modal handler is consulted, for
        # instance if one of Orca's own modes replaced ours.
        def run(_script: Any, _event: Any) -> bool:
            if self._active:
                self._run(key)
            return True

        return run

    def _run(self, key: LayerKey) -> None:
        self._restart_timer()
        key.action()

    def _restart_timer(self) -> None:
        self._cancel_timer()
        seconds = self._get_timeout()
        if self._active and seconds > 0:
            self._timer_handle = self._timer.start(seconds, self._expire)

    def _cancel_timer(self) -> None:
        if self._timer_handle is not None:
            self._timer.cancel(self._timer_handle)
            self._timer_handle = None

    def _expire(self) -> None:
        self._timer_handle = None
        if self.leave():
            self._on_timeout()
