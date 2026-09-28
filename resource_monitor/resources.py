"""The resources the extension reports, their keys, and how each one is gathered."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from orca import keybindings

from .disks import read_drives
from .formatting import CELSIUS
from .gpu import read_gpus
from .i18n import _
from .reports import (
    cpu_report,
    drives_report,
    gpu_memory_report,
    gpu_report,
    memory_report,
    os_report,
    summary_report,
    uptime_report,
    wifi_report,
)
from .system_info import read_memory, read_os_info, read_uptime, sample_cpu_load
from .wifi import query_wifi

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReportOptions:
    """User settings a report needs, read on Orca's main thread before gathering."""

    temperature_unit: str = CELSIUS


@dataclass(frozen=True)
class Resource:
    """One kind of information, with its keys and how to gather it.

    gather blocks (it may sample the processor or run a helper program), so it
    must run off Orca's main thread. layer_key and layer_modifiers are the key
    inside the command layer; shortcut is the digit used with Orca+Shift.
    """

    name: str
    description: str
    gather: Callable[[ReportOptions], str]
    failure: str
    layer_key: str
    layer_modifiers: int
    shortcut: str


def _copy_hint(text: str) -> str:
    # Translators: Appended to every resource command description.
    return text + " " + _("If pressed twice, copies the information to the clipboard.")


RESOURCES: tuple[Resource, ...] = (
    Resource(
        name="summary",
        # Translators: Description of the overall resource usage command.
        description=_copy_hint(_("Presents used RAM and average processor load.")),
        gather=lambda _options: summary_report(read_memory(), sample_cpu_load()),
        # Translators: Reported when the overall resource usage command fails.
        failure=_("Failed to get resource usage information."),
        layer_key="space",
        layer_modifiers=keybindings.NO_MODIFIER_MASK,
        shortcut="5",
    ),
    Resource(
        name="cpu",
        # Translators: Description of the processor command.
        description=_copy_hint(_("Presents the average processor load and the load of each core.")),
        gather=lambda _options: cpu_report(sample_cpu_load()),
        # Translators: Reported when the processor command fails.
        failure=_("Failed to get processor information."),
        layer_key="c",
        layer_modifiers=keybindings.NO_MODIFIER_MASK,
        shortcut="1",
    ),
    Resource(
        name="memory",
        # Translators: Description of the memory command.
        description=_copy_hint(
            _("Presents the used and total space for both physical memory and swap.")
        ),
        gather=lambda _options: memory_report(read_memory()),
        # Translators: Reported when the memory command fails.
        failure=_("Failed to get memory information."),
        layer_key="m",
        layer_modifiers=keybindings.NO_MODIFIER_MASK,
        shortcut="2",
    ),
    Resource(
        name="drives",
        # Translators: Description of the drives command.
        description=_copy_hint(
            _("Presents the used and total space of the local and network drives.")
        ),
        gather=lambda _options: drives_report(read_drives()),
        # Translators: Reported when the drives command fails.
        failure=_("Failed to get drive information."),
        layer_key="d",
        layer_modifiers=keybindings.NO_MODIFIER_MASK,
        shortcut="3",
    ),
    Resource(
        name="wifi",
        # Translators: Description of the wireless network command.
        description=_copy_hint(
            _("Announces the wireless network name (SSID), signal strength, and security type.")
        ),
        gather=lambda _options: wifi_report(query_wifi()),
        failure=_("Unable to get wireless information"),
        layer_key="w",
        layer_modifiers=keybindings.NO_MODIFIER_MASK,
        shortcut="4",
    ),
    Resource(
        name="os",
        # Translators: Description of the operating system command.
        description=_copy_hint(
            _("Announces the Linux distribution, processor architecture, kernel, and desktop.")
        ),
        gather=lambda _options: os_report(read_os_info()),
        # Translators: Reported when the operating system command fails.
        failure=_("Failed to get operating system information."),
        layer_key="o",
        layer_modifiers=keybindings.NO_MODIFIER_MASK,
        shortcut="6",
    ),
    Resource(
        name="uptime",
        # Translators: Description of the uptime command.
        description=_copy_hint(_("Announces the system's uptime.")),
        gather=lambda _options: uptime_report(read_uptime()),
        # Translators: Obtaining uptime failed.
        failure=_("Failed to get the system's uptime."),
        layer_key="u",
        layer_modifiers=keybindings.NO_MODIFIER_MASK,
        shortcut="7",
    ),
    Resource(
        name="gpu",
        # Translators: Description of the GPU usage and temperature command.
        description=_copy_hint(_("Announces GPU usage and temperature.")),
        gather=lambda options: gpu_report(read_gpus(), options.temperature_unit),
        # Translators: Message reported when the GPU command fails unexpectedly.
        failure=_("Failed to get GPU information."),
        layer_key="g",
        layer_modifiers=keybindings.NO_MODIFIER_MASK,
        shortcut="8",
    ),
    Resource(
        name="gpu_memory",
        # Translators: Description of the GPU memory command.
        description=_copy_hint(_("Announces GPU memory usage.")),
        gather=lambda _options: gpu_memory_report(read_gpus()),
        # Translators: Message reported when the GPU memory command fails unexpectedly.
        failure=_("Failed to get GPU memory information."),
        layer_key="g",
        layer_modifiers=keybindings.SHIFT_MODIFIER_MASK,
        shortcut="9",
    ),
)


def gather(resource: Resource, options: ReportOptions) -> str:
    """Returns the resource's report, or its failure message. Never raises."""

    try:
        return resource.gather(options)
    except Exception:  # pylint: disable=broad-exception-caught
        # A command must always answer the user; the traceback goes to the log.
        _log.exception("Resource Monitor: gathering %s failed", resource.name)
        return resource.failure
