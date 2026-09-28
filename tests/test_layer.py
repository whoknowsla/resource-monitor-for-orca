"""Tests for the command layer, against a stand-in for Orca's command manager."""

import unittest

import context  # noqa: F401  pylint: disable=unused-import
from orca import keybindings

from resource_monitor.layer import LAYER_GROUP, CommandLayer, EnterResult, LayerKey

SHIFT = keybindings.SHIFT_MODIFIER_MASK
ORCA_SHIFT = keybindings.ORCA_SHIFT_MODIFIER_MASK

# keysym: (keyval, keycode), so bindings never need a display to resolve keys.
KEYS = {"c": (0x63, 54), "g": (0x67, 42), "Escape": (0xFF1B, 9), "e": (0x65, 26)}
ENTRY = "resource_monitor_enter_layer"


class FakeManager:
    """Records what the layer asks of Orca's command manager."""

    def __init__(self):
        self.commands = {}
        self.modal_handler = None
        self.accept_modal_handler = True
        self.activations = []
        self.removed = []
        self.fail_on_add = False

    def add_command(self, command):
        if self.fail_on_add and self.commands:
            raise RuntimeError("Orca changed")
        binding = command.get_default_keybinding(True)
        binding.keyval, binding.keycode = KEYS[binding.keysymstring]
        command.set_keybinding(binding)
        self.commands[command.get_name()] = command

    def remove_commands(self, names, _reason=""):
        self.removed.extend(names)
        for name in names:
            self.commands.pop(name, None)

    def set_modal_handler(self, handler):
        if not self.accept_modal_handler:
            return False
        self.modal_handler = handler
        return True

    def clear_modal_handler(self, handler):
        if self.modal_handler is handler:
            self.modal_handler = None

    def set_group_suspended(self, group, suspended):
        for command in self.commands.values():
            if command.get_activation_group() == group:
                command.set_suspended(suspended)

    def activate_commands(self, reason=""):
        self.activations.append(reason)


class FakeTimer:
    def __init__(self):
        self.running = {}
        self.next_handle = 1

    def start(self, seconds, callback):
        handle = self.next_handle
        self.next_handle += 1
        self.running[handle] = (seconds, callback)
        return handle

    def cancel(self, handle):
        del self.running[handle]

    def fire(self):
        (handle,) = self.running
        _seconds, callback = self.running.pop(handle)
        callback()


class FakeEvent:
    def __init__(self, keysym, modifiers=0, pressed=True, keyval=None):
        default_keyval, self.hw_code = KEYS[keysym]
        self.id = keyval if keyval is not None else default_keyval
        self.modifiers = modifiers
        self._pressed = pressed

    def is_pressed_key(self):
        return self._pressed


class FakeCommand:
    def __init__(self, name):
        self.name = name
        self.executed = []

    def get_name(self):
        return self.name

    def execute(self, script, event):
        self.executed.append((script, event))
        return True


class LayerTests(unittest.TestCase):
    def setUp(self):
        self.manager = FakeManager()
        self.timer = FakeTimer()
        self.handler = object()
        self.actions = []
        self.timeouts = 0
        self.timeout_seconds = 10
        self.idle_calls = []
        self.layer = CommandLayer(
            self.handler,
            "Resource Monitor",
            ENTRY,
            lambda: self.timeout_seconds,
            self._on_timeout,
            manager=lambda: self.manager,
            timer=self.timer,
            idle=lambda callback: (self.idle_calls.append(callback), callback()),
        )
        self.keys = [
            LayerKey("layer_cpu", "CPU", "c", 0, lambda: self.actions.append("cpu")),
            LayerKey("layer_gpu", "GPU", "g", 0, lambda: self.actions.append("gpu")),
            LayerKey("layer_gpu_memory", "VRAM", "g", SHIFT, lambda: self.actions.append("vram")),
            LayerKey("layer_leave", "Leave", "Escape", 0, self.layer.leave),
        ]

    def _on_timeout(self):
        self.timeouts += 1

    def _enter(self):
        self.assertTrue(self.layer.register(self.keys))
        self.assertIs(self.layer.enter(), EnterResult.ENTERED)

    def test_register_adds_hidden_suspended_commands(self):
        self.assertTrue(self.layer.register(self.keys))
        self.assertTrue(self.layer.register(self.keys))  # idempotent
        self.assertEqual(len(self.manager.commands), 4)
        for command in self.manager.commands.values():
            self.assertTrue(command.is_suspended())
            self.assertFalse(command.is_user_visible())
            self.assertEqual(command.get_activation_group(), LAYER_GROUP)

    def test_register_failure_cleans_up(self):
        self.manager.fail_on_add = True
        with self.assertLogs("resource_monitor.layer", level="ERROR"):
            self.assertFalse(self.layer.register(self.keys))
        self.assertEqual(self.manager.commands, {})
        self.assertIs(self.layer.enter(), EnterResult.UNAVAILABLE)

    def test_enter_activates_keys_modal_handler_and_timer(self):
        self._enter()
        self.assertTrue(self.layer.is_active)
        self.assertIs(self.manager.modal_handler, self.handler)
        self.assertFalse(any(command.is_suspended() for command in self.manager.commands.values()))
        self.assertEqual([seconds for seconds, _ in self.timer.running.values()], [10])
        self.assertIs(self.layer.enter(), EnterResult.ALREADY_ACTIVE)

    def test_enter_is_blocked_by_another_modal_handler(self):
        self.layer.register(self.keys)
        self.manager.accept_modal_handler = False
        self.assertIs(self.layer.enter(), EnterResult.BLOCKED)
        self.assertFalse(self.layer.is_active)
        self.assertTrue(all(command.is_suspended() for command in self.manager.commands.values()))

    def test_layer_keys_run_and_keep_the_layer(self):
        self._enter()
        for event in (FakeEvent("c"), FakeEvent("g"), FakeEvent("g", SHIFT, keyval=0x47)):
            self.assertTrue(self.layer.will_handle_event(None, event, FakeCommand("next_image")))
            self.assertTrue(self.layer.handle_event(None, event, FakeCommand("next_image")))
        self.assertEqual(self.actions, ["cpu", "gpu", "vram"])
        self.assertTrue(self.layer.is_active)

    def test_releases_are_not_claimed(self):
        self._enter()
        self.assertFalse(self.layer.will_handle_event(None, FakeEvent("c", pressed=False)))

    def test_nothing_is_claimed_when_inactive(self):
        self.layer.register(self.keys)
        self.assertFalse(self.layer.will_handle_event(None, FakeEvent("c")))

    def test_entry_key_is_ignored_inside_the_layer(self):
        self._enter()
        entry = FakeCommand(ENTRY)
        self.assertTrue(self.layer.handle_event(None, FakeEvent("e", ORCA_SHIFT), entry))
        self.assertTrue(self.layer.is_active)
        self.assertEqual(entry.executed, [])

    def test_other_commands_leave_and_pass_through(self):
        self._enter()
        other = FakeCommand("toggle_speech")
        event = FakeEvent("e", ORCA_SHIFT)
        self.assertTrue(self.layer.handle_event("script", event, other))
        self.assertFalse(self.layer.is_active)
        self.assertEqual(other.executed, [("script", event)])
        self.assertIsNone(self.manager.modal_handler)

    def test_leave_suspends_keys_and_refreshes_grabs(self):
        self._enter()
        self.assertTrue(
            self.layer.handle_event(None, FakeEvent("Escape"), FakeCommand("layer_leave"))
        )
        self.assertFalse(self.layer.is_active)
        self.assertTrue(all(command.is_suspended() for command in self.manager.commands.values()))
        self.assertEqual(len(self.manager.activations), 1)
        self.assertEqual(self.timer.running, {})
        self.assertFalse(self.layer.leave())

    def test_idle_timeout_leaves_and_reports(self):
        self._enter()
        self.timer.fire()
        self.assertFalse(self.layer.is_active)
        self.assertEqual(self.timeouts, 1)

    def test_keys_restart_the_timer(self):
        self._enter()
        (first,) = self.timer.running
        self.layer.handle_event(None, FakeEvent("c"), None)
        (second,) = self.timer.running
        self.assertNotEqual(first, second)

    def test_zero_timeout_disables_the_timer(self):
        self.timeout_seconds = 0
        self._enter()
        self.assertEqual(self.timer.running, {})

    def test_command_functions_work_without_the_modal_handler(self):
        self._enter()
        command = self.manager.commands["layer_cpu"]
        self.assertTrue(command.execute(None, None))
        self.assertEqual(self.actions, ["cpu"])

    def test_unregister_leaves_and_removes_commands(self):
        self._enter()
        self.layer.unregister("test")
        self.assertFalse(self.layer.is_active)
        self.assertFalse(self.layer.is_registered)
        self.assertEqual(self.manager.commands, {})
        self.assertEqual(len(self.manager.removed), 4)


if __name__ == "__main__":
    unittest.main()
