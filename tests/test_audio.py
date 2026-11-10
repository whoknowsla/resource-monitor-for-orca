"""Tests for reading the default audio devices."""

import subprocess
import unittest

import context  # noqa: F401  pylint: disable=unused-import

from resource_monitor.audio import (
    AudioDevice,
    AudioRole,
    PactlProvider,
    WpctlProvider,
    parse_device_name,
    parse_pactl_mute,
    parse_pactl_volume,
    parse_wpctl_volume,
    read_audio,
)

WPCTL_INSPECT = """id 54, type PipeWire:Interface:Node
    * node.description = "CalDigit TS5 Plus Audio - Rear Analog Stereo"
    * node.nick = "CalDigit TS5 Plus Audio - Rear"
      node.name = "alsa_output.usb-CalDigit"
"""

PACTL_VOLUME = (
    "Volume: front-left: 27524 /  42% / -22.61 dB,   "
    "front-right: 27524 /  42% / -22.61 dB\n        balance 0.00\n"
)


def completed(stdout):
    return subprocess.CompletedProcess([], 0, stdout, "")


class ParsingTests(unittest.TestCase):
    def test_wpctl_volume(self):
        self.assertEqual(parse_wpctl_volume("Volume: 0.42\n"), (0.42, False))

    def test_wpctl_volume_muted(self):
        self.assertEqual(parse_wpctl_volume("Volume: 0.42 [MUTED]\n"), (0.42, True))

    def test_wpctl_volume_above_one_is_a_real_state(self):
        # The sound server allows it, so it is reported rather than clamped.
        self.assertEqual(parse_wpctl_volume("Volume: 1.40\n"), (1.4, False))

    def test_wpctl_volume_integer(self):
        self.assertEqual(parse_wpctl_volume("Volume: 1\n"), (1.0, False))

    def test_wpctl_volume_empty(self):
        self.assertEqual(parse_wpctl_volume(""), (None, None))

    def test_wpctl_volume_unexpected_output(self):
        self.assertEqual(parse_wpctl_volume("Node not found\n"), (None, False))

    def test_pactl_volume_takes_the_first_channel(self):
        self.assertAlmostEqual(parse_pactl_volume(PACTL_VOLUME), 0.42)

    def test_pactl_volume_missing(self):
        self.assertIsNone(parse_pactl_volume("Failure: No such entity\n"))

    def test_pactl_mute(self):
        self.assertTrue(parse_pactl_mute("Mute: yes\n"))
        self.assertFalse(parse_pactl_mute("Mute: no\n"))
        self.assertIsNone(parse_pactl_mute("Failure\n"))

    def test_device_name_prefers_the_description(self):
        self.assertEqual(
            parse_device_name(WPCTL_INSPECT),
            "CalDigit TS5 Plus Audio - Rear Analog Stereo",
        )

    def test_device_name_falls_back_to_the_nick(self):
        self.assertEqual(
            parse_device_name('      node.nick = "Headphones"\n'), "Headphones"
        )

    def test_an_empty_description_is_not_a_name(self):
        self.assertEqual(
            parse_device_name('* node.description = ""\n* node.nick = "Dock"\n'), "Dock"
        )

    def test_no_name_at_all(self):
        self.assertIsNone(parse_device_name("id 54\n"))


class WpctlProviderTests(unittest.TestCase):
    def provider(self, outputs, present=True):
        self.commands = []

        def run(command, _timeout):
            self.commands.append(list(command))
            return completed(outputs.get(command[1], ""))

        return WpctlProvider(which=lambda _name: "/usr/bin/wpctl" if present else None, run=run)

    def test_absent_tool_declines(self):
        self.assertIsNone(self.provider({}, present=False).collect(AudioRole.OUTPUT))

    def test_reads_volume_and_name(self):
        device = self.provider(
            {"get-volume": "Volume: 0.42\n", "inspect": WPCTL_INSPECT}
        ).collect(AudioRole.OUTPUT)
        self.assertAlmostEqual(device.volume, 0.42)
        self.assertEqual(device.name, "CalDigit TS5 Plus Audio - Rear Analog Stereo")
        self.assertFalse(device.muted)

    def test_the_input_role_asks_for_the_source(self):
        self.provider({"get-volume": "Volume: 0.5\n"}).collect(AudioRole.INPUT)
        self.assertIn("@DEFAULT_AUDIO_SOURCE@", self.commands[0])

    def test_a_failed_inspect_does_not_lose_the_volume(self):
        # The volume is the more important half of the answer.
        def run(command, _timeout):
            if command[1] == "inspect":
                raise subprocess.SubprocessError("boom")
            return completed("Volume: 0.42\n")

        provider = WpctlProvider(which=lambda _name: "/usr/bin/wpctl", run=run)
        device = provider.collect(AudioRole.OUTPUT)
        self.assertAlmostEqual(device.volume, 0.42)
        self.assertIsNone(device.name)

    def test_a_failed_volume_declines_entirely(self):
        def run(_command, _timeout):
            raise subprocess.SubprocessError("boom")

        provider = WpctlProvider(which=lambda _name: "/usr/bin/wpctl", run=run)
        self.assertIsNone(provider.collect(AudioRole.OUTPUT))

    def test_an_empty_reading_declines_so_the_next_provider_runs(self):
        self.assertIsNone(self.provider({}).collect(AudioRole.OUTPUT))


class PactlProviderTests(unittest.TestCase):
    def provider(self, outputs, present=True):
        def run(command, _timeout):
            return completed(outputs.get(command[1], ""))

        return PactlProvider(which=lambda _name: "/usr/bin/pactl" if present else None, run=run)

    def test_absent_tool_declines(self):
        self.assertIsNone(self.provider({}, present=False).collect(AudioRole.OUTPUT))

    def test_reads_the_sink(self):
        device = self.provider(
            {
                "get-default-sink": "alsa_output.usb-CalDigit\n",
                "get-sink-volume": PACTL_VOLUME,
                "get-sink-mute": "Mute: yes\n",
            }
        ).collect(AudioRole.OUTPUT)
        self.assertEqual(device.name, "alsa_output.usb-CalDigit")
        self.assertAlmostEqual(device.volume, 0.42)
        self.assertTrue(device.muted)

    def test_reads_the_source(self):
        device = self.provider(
            {"get-default-source": "alsa_input.pci\n", "get-source-mute": "Mute: no\n"}
        ).collect(AudioRole.INPUT)
        self.assertEqual(device.name, "alsa_input.pci")
        self.assertFalse(device.muted)


class ReadAudioTests(unittest.TestCase):
    def test_the_first_provider_that_answers_wins(self):
        class Answers:
            def collect(self, _role):
                return AudioDevice("Speakers", 0.5, False)

        class Declines:
            def collect(self, _role):
                return None

        self.assertEqual(
            read_audio(AudioRole.OUTPUT, [Declines(), Answers()]).name, "Speakers"
        )

    def test_nothing_answering_gives_an_empty_device(self):
        class Declines:
            def collect(self, _role):
                return None

        device = read_audio(AudioRole.OUTPUT, [Declines()])
        self.assertTrue(device.is_empty)

    def test_a_device_with_any_field_is_not_empty(self):
        self.assertFalse(AudioDevice(volume=0.5).is_empty)
        self.assertFalse(AudioDevice(muted=False).is_empty)
        self.assertTrue(AudioDevice().is_empty)


if __name__ == "__main__":
    unittest.main()
