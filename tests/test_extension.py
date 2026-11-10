"""Tests for the extension class: commands, presentation, and notifications."""

import os
import unittest

import context  # noqa: F401  pylint: disable=unused-import
from orca import keybindings

import resource_monitor
from resource_monitor import ENTER_LAYER_COMMAND, PressTracker, ResourceMonitor
from resource_monitor.layer import EnterResult
from resource_monitor.resources import RESOURCES, Resource
from resource_monitor.wifi_monitor import WifiEvent


class FakeController:
    def __init__(self, tones_work=True, clipboard_works=True):
        self.presented = []
        self.spoken = []
        self.brailled = []
        self.tones = []
        self.sounds = []
        self.clipboard = None
        self.tones_work = tones_work
        self.clipboard_works = clipboard_works

    def present_message_internal(self, message):
        self.presented.append(message)
        return True

    def speak_message_internal(self, message):
        self.spoken.append(message)
        return True

    def display_message_internal(self, message, persistent=False):
        self.brailled.append(message)
        return True

    def play_tone_internal(self, duration, frequency, volume=1.0, wave="sine", interrupt=True):
        self.tones.append((duration, frequency))
        return self.tones_work

    def play_sound_file_internal(self, path, interrupt=True):
        self.sounds.append(os.path.basename(path))
        return True

    def set_clipboard_text_internal(self, text):
        self.clipboard = text
        return self.clipboard_works


class FakeSettings:
    def __init__(self, **values):
        self.values = values

    def get(self, key, default=None):
        return self.values.get(key, default)


class ImmediateWorker:
    def submit(self, job, on_result):
        on_result(job())
        return True

    def stop(self):
        pass


class FakeLayer:
    def __init__(self, result):
        self.result = result

    def enter(self):
        return self.result


def make_extension(**settings):
    extension = ResourceMonitor()
    extension.controller = FakeController()
    extension.settings = FakeSettings(**settings)
    extension._worker = ImmediateWorker()
    return extension


class MetadataTests(unittest.TestCase):
    def test_author_and_labels(self):
        self.assertEqual(ResourceMonitor.AUTHOR, "Deniz Aygun")
        self.assertEqual(ResourceMonitor.GROUP_LABEL, "Resource Monitor")
        self.assertTrue(ResourceMonitor.VERSION)


class CommandTests(unittest.TestCase):
    def setUp(self):
        self.extension = make_extension()

    def test_entry_and_direct_shortcuts(self):
        commands = self.extension._get_commands()
        names = [command.get_name() for command in commands]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(names[0], ENTER_LAYER_COMMAND)
        bindings = [command.get_default_keybinding(True) for command in commands]
        self.assertEqual(bindings[0].keysymstring, "e")
        # Some resources have no default shortcut, because the digits run out
        # at nine; those commands are registered unbound so they can be given
        # a key in Orca's preferences.
        bound = [binding for binding in bindings if binding is not None]
        digits = sorted(binding.keysymstring for binding in bound[1:])
        self.assertEqual(digits, [str(digit) for digit in range(0, 10)])
        self.assertTrue(
            all(binding.modifiers == keybindings.ORCA_SHIFT_MODIFIER_MASK for binding in bound)
        )
        self.assertEqual(
            [
                command.get_default_keybinding(False).keysymstring
                if command.get_default_keybinding(False) is not None
                else None
                for command in commands
            ],
            [
                binding.keysymstring if binding is not None else None
                for binding in bindings
            ],
        )

    def test_a_resource_without_a_shortcut_is_still_a_command(self):
        commands = {
            command.get_name(): command for command in self.extension._get_commands()
        }
        for resource in RESOURCES:
            command = commands[f"resource_monitor_{resource.name}"]
            if resource.shortcut:
                self.assertIsNotNone(command.get_default_keybinding(True))
            else:
                self.assertIsNone(command.get_default_keybinding(True))
                self.assertIsNone(command.get_default_keybinding(False))

    def test_layer_keys_match_the_nvda_add_on(self):
        keys = {(key.keysym, key.modifiers) for key in self.extension._layer_keys()}
        no_modifier = keybindings.NO_MODIFIER_MASK
        expected = {
            (letter, no_modifier) for letter in ("space", "c", "m", "d", "w", "o", "u", "g")
        }
        expected |= {("g", keybindings.SHIFT_MODIFIER_MASK), ("Escape", no_modifier)}
        # A subset, not an equality: the keys below report things the NVDA
        # add-on does not have, so they cannot match it.
        self.assertTrue(expected <= keys)

    def test_layer_keys_for_the_reports_nvda_does_not_have(self):
        keys = {(key.keysym, key.modifiers) for key in self.extension._layer_keys()}
        no_modifier = keybindings.NO_MODIFIER_MASK
        expected = {(letter, no_modifier) for letter in ("b", "a", "l")}
        expected |= {("a", keybindings.SHIFT_MODIFIER_MASK)}
        self.assertTrue(expected <= keys)

    def test_every_layer_key_is_unique(self):
        keys = [(key.keysym, key.modifiers) for key in self.extension._layer_keys()]
        self.assertEqual(len(keys), len(set(keys)))

    def test_every_resource_has_a_layer_key(self):
        keys = {(key.keysym, key.modifiers) for key in self.extension._layer_keys()}
        for resource in RESOURCES:
            self.assertIn((resource.layer_key, resource.layer_modifiers), keys)

    def test_every_resource_has_a_description(self):
        for resource in RESOURCES:
            self.assertIn("If pressed twice", resource.description)


class PressTrackerTests(unittest.TestCase):
    def test_second_press_within_window_is_a_repeat(self):
        tracker = PressTracker(window=0.5)
        self.assertFalse(tracker.is_repeat("cpu", 10.0))
        self.assertTrue(tracker.is_repeat("cpu", 10.4))
        self.assertFalse(tracker.is_repeat("cpu", 11.0))
        self.assertFalse(tracker.is_repeat("memory", 11.1))


def fake_resource(text):
    return Resource("fake", "Fake.", lambda _options: text, "Failed.", "x", 0, "0")


class PresentationTests(unittest.TestCase):
    def test_single_press_presents_and_double_press_copies(self):
        extension = make_extension()
        extension._presses = PressTracker(window=60)
        resource = fake_resource("CPU at 5%.")
        extension._request(resource)
        extension._request(resource)
        self.assertEqual(extension.controller.presented, ["CPU at 5%.", "Copied to clipboard"])
        self.assertEqual(extension.controller.clipboard, "CPU at 5%.")

    def test_clipboard_failure_is_reported(self):
        extension = make_extension()
        extension.controller.clipboard_works = False
        extension._deliver("text", copy=True)
        self.assertEqual(extension.controller.presented, ["Could not copy to the clipboard"])

    def test_nothing_is_presented_after_shutdown(self):
        extension = make_extension()
        extension.on_shutdown()
        extension._deliver("late", copy=False)
        self.assertEqual(extension.controller.presented, [])

    def test_failing_gather_presents_the_failure_message(self):
        extension = make_extension()

        def explode(_options):
            raise OSError("no /proc")

        resource = Resource("broken", "Broken.", explode, "Failed to read.", "x", 0, "0")
        with self.assertLogs("resource_monitor.resources", level="ERROR"):
            extension._request(resource)
        self.assertEqual(extension.controller.presented, ["Failed to read."])


class LayerFeedbackTests(unittest.TestCase):
    def test_entering_plays_a_tone_and_brailles_the_name(self):
        extension = make_extension()
        extension._layer = FakeLayer(EnterResult.ENTERED)
        self.assertTrue(extension.enter_layer())
        self.assertEqual(len(extension.controller.tones), 1)
        self.assertEqual(extension.controller.brailled, ["Resource Monitor"])
        self.assertEqual(extension.controller.spoken, [])

    def test_speech_replaces_the_tone_when_tones_fail(self):
        extension = make_extension()
        extension.controller.tones_work = False
        extension._layer = FakeLayer(EnterResult.ENTERED)
        extension.enter_layer()
        self.assertEqual(extension.controller.spoken, ["Resource Monitor"])

    def test_blocked_and_unavailable_are_explained(self):
        for result in (EnterResult.BLOCKED, EnterResult.UNAVAILABLE):
            with self.subTest(result=result):
                extension = make_extension()
                extension._layer = FakeLayer(result)
                extension.enter_layer()
                self.assertEqual(len(extension.controller.presented), 1)

    def test_already_active_is_silent(self):
        extension = make_extension()
        extension._layer = FakeLayer(EnterResult.ALREADY_ACTIVE)
        extension.enter_layer()
        self.assertEqual(extension.controller.presented, [])
        self.assertEqual(extension.controller.tones, [])


class WifiNotificationTests(unittest.TestCase):
    def test_default_is_message_and_sound(self):
        extension = make_extension()
        extension._on_wifi_event(WifiEvent.CONNECTED, "Home")
        self.assertEqual(extension.controller.presented, ["Connected to Home"])
        self.assertEqual(extension.controller.sounds, ["connect.wav"])

    def test_modes(self):
        cases = {
            "off": ([], []),
            "message": (["Disconnected from Home"], []),
            "sound": ([], ["disconnect.wav"]),
        }
        for mode, (messages, sounds) in cases.items():
            with self.subTest(mode=mode):
                extension = make_extension(**{"wifi-notification": mode})
                extension._on_wifi_event(WifiEvent.DISCONNECTED, "Home")
                self.assertEqual(extension.controller.presented, messages)
                self.assertEqual(extension.controller.sounds, sounds)

    def test_device_events_and_hidden_networks(self):
        extension = make_extension(**{"wifi-notification": "message"})
        extension._on_wifi_event(WifiEvent.ENABLED, "")
        extension._on_wifi_event(WifiEvent.DISABLED, "")
        extension._on_wifi_event(WifiEvent.CONNECTED, "")
        self.assertEqual(
            extension.controller.presented,
            [
                "A wireless device has been enabled",
                "A wireless device has been disabled",
                "Connected to hidden network",
            ],
        )

    def test_sound_files_are_packaged(self):
        sounds = os.path.join(os.path.dirname(resource_monitor.__file__), "sounds")
        for name in ("connect.wav", "disconnect.wav"):
            self.assertTrue(os.path.isfile(os.path.join(sounds, name)))


if __name__ == "__main__":
    unittest.main()
