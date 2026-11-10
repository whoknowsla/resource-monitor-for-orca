"""The default audio output and input device, its volume, and whether it is muted.

Unlike the processor, memory, and battery readers, this one needs a helper
program, because the volume lives in the sound server rather than in the
kernel. PipeWire's ``wpctl`` is preferred and PulseAudio's ``pactl`` is the
fallback; ``pactl`` also works against PipeWire through its PulseAudio
interface, so between them they cover current desktops.

Why a screen reader user wants this: the volume and the chosen device are
exactly what you cannot see when speech suddenly goes somewhere else, and
checking them in a settings dialog means navigating a dialog with the speech
you are trying to diagnose.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum

_log = logging.getLogger(__name__)

COMMAND_TIMEOUT_SECONDS = 2.0

_WPCTL_VOLUME = re.compile(r"Volume:\s*([0-9]*\.?[0-9]+)")
_PACTL_PERCENT = re.compile(r"/\s*(\d+)%")
_NODE_DESCRIPTION = re.compile(r'node\.description\s*=\s*"(.*)"')
_NODE_NICK = re.compile(r'node\.nick\s*=\s*"(.*)"')


class AudioRole(Enum):
    """Which end of the sound system to report."""

    OUTPUT = "output"
    INPUT = "input"


@dataclass(frozen=True)
class AudioDevice:
    """A reading of one default device. Any field may be unknown."""

    name: str | None = None
    volume: float | None = None
    muted: bool | None = None

    @property
    def is_empty(self) -> bool:
        """Returns True when nothing at all could be read."""

        return self.name is None and self.volume is None and self.muted is None


def _run(command: Sequence[str], timeout: float) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
        env={**os.environ, "LC_ALL": "C"},
    )


def parse_wpctl_volume(output: str) -> tuple[float | None, bool | None]:
    """Returns (volume as a fraction, muted) from `wpctl get-volume`.

    wpctl prints "Volume: 0.42", and appends "[MUTED]" when muted. A volume
    above 1.0 is a real state, not an error -- the sound server allows it --
    so it is reported rather than clamped.
    """

    match = _WPCTL_VOLUME.search(output)
    volume = float(match.group(1)) if match else None
    muted = "[MUTED]" in output.upper() if output.strip() else None
    return volume, muted


def parse_pactl_volume(output: str) -> float | None:
    """Returns the volume as a fraction from `pactl get-sink-volume`.

    pactl prints a percentage per channel. The channels are normally equal
    and the first is taken; where they differ, one figure spoken aloud is
    better than several, and the first is the one a balance control moves
    away from.
    """

    match = _PACTL_PERCENT.search(output)
    if match is None:
        return None
    return int(match.group(1)) / 100.0


def parse_pactl_mute(output: str) -> bool | None:
    """Returns whether the device is muted, from `pactl get-sink-mute`."""

    lowered = output.lower()
    if "mute: yes" in lowered:
        return True
    if "mute: no" in lowered:
        return False
    return None


def parse_device_name(output: str) -> str | None:
    """Returns a readable device name from `wpctl inspect`.

    node.description is the name the desktop shows. node.nick is shorter and
    is used when there is no description.
    """

    for pattern in (_NODE_DESCRIPTION, _NODE_NICK):
        match = pattern.search(output)
        if match and match.group(1).strip():
            return match.group(1).strip()
    return None


class WpctlProvider:
    """Reads the default device through PipeWire's wpctl."""

    TARGETS = {
        AudioRole.OUTPUT: "@DEFAULT_AUDIO_SINK@",
        AudioRole.INPUT: "@DEFAULT_AUDIO_SOURCE@",
    }

    def __init__(
        self,
        which: Callable[[str], str | None] = shutil.which,
        run: Callable[[Sequence[str], float], subprocess.CompletedProcess[str]] = _run,
    ) -> None:
        self._which = which
        self._run = run

    def collect(self, role: AudioRole) -> AudioDevice | None:
        """Returns a reading, or None when wpctl is absent or fails."""

        if self._which("wpctl") is None:
            return None
        target = self.TARGETS[role]
        try:
            volume_output = self._run(
                ["wpctl", "get-volume", target], COMMAND_TIMEOUT_SECONDS
            ).stdout
        except (OSError, subprocess.SubprocessError):
            return None

        volume, muted = parse_wpctl_volume(volume_output)
        name: str | None = None
        try:
            name = parse_device_name(
                self._run(["wpctl", "inspect", target], COMMAND_TIMEOUT_SECONDS).stdout
            )
        except (OSError, subprocess.SubprocessError):
            # The volume is the more important half, so a failure to name the
            # device must not lose it.
            _log.debug("wpctl inspect failed for %s", target)

        device = AudioDevice(name, volume, muted)
        return None if device.is_empty else device


class PactlProvider:
    """Reads the default device through PulseAudio's pactl."""

    DEFAULTS = {
        AudioRole.OUTPUT: ("get-default-sink", "get-sink-volume", "get-sink-mute", "@DEFAULT_SINK@"),
        AudioRole.INPUT: (
            "get-default-source",
            "get-source-volume",
            "get-source-mute",
            "@DEFAULT_SOURCE@",
        ),
    }

    def __init__(
        self,
        which: Callable[[str], str | None] = shutil.which,
        run: Callable[[Sequence[str], float], subprocess.CompletedProcess[str]] = _run,
    ) -> None:
        self._which = which
        self._run = run

    def _read(self, arguments: Sequence[str]) -> str | None:
        try:
            return self._run(["pactl", *arguments], COMMAND_TIMEOUT_SECONDS).stdout
        except (OSError, subprocess.SubprocessError):
            return None

    def collect(self, role: AudioRole) -> AudioDevice | None:
        """Returns a reading, or None when pactl is absent or fails."""

        if self._which("pactl") is None:
            return None
        default_command, volume_command, mute_command, target = self.DEFAULTS[role]

        name_output = self._read([default_command])
        # pactl gives the sink's internal name rather than a readable one. It
        # is long, but it is what the user would see in a mixer, and it is
        # better than reporting no device at all.
        name = name_output.strip() if name_output and name_output.strip() else None

        volume_output = self._read([volume_command, target])
        volume = parse_pactl_volume(volume_output) if volume_output else None

        mute_output = self._read([mute_command, target])
        muted = parse_pactl_mute(mute_output) if mute_output else None

        device = AudioDevice(name, volume, muted)
        return None if device.is_empty else device


def default_providers() -> list[WpctlProvider | PactlProvider]:
    """Returns the providers to try, in order of preference."""

    return [WpctlProvider(), PactlProvider()]


def read_audio(
    role: AudioRole,
    providers: Sequence[WpctlProvider | PactlProvider] | None = None,
) -> AudioDevice:
    """Returns the default device for `role`, from the first provider that answers."""

    for provider in default_providers() if providers is None else providers:
        device = provider.collect(role)
        if device is not None:
            return device
    return AudioDevice()
