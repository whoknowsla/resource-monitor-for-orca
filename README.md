# Resource Monitor for Orca

A Linux port of the [Resource Monitor add-on for NVDA](https://github.com/kefaslungu/resourceMonitor),
built as an Orca user extension. It reports processor load, memory, drives, GPU,
wireless network, battery, audio devices, load averages, temperatures, uptime,
and operating system information, through a command layer or through direct
shortcuts.

- Version: 1.0.0
- Author: Deniz Aygun
- Targets: Orca 51 (user extension API), Linux
- License: GNU GPL version 2 (see `COPYING`)

## Requirements

- Orca with user-extension support (`~/.local/share/orca/extensions/`).
- Nothing else is required. Processor, memory, uptime, drive, battery, load
  average, temperature, and operating system information come straight from
  the kernel (`/proc`, `/sys`, `statvfs`), so no third-party Python packages
  are needed.
- Optional helpers, each used only if present:

| Tool | Package (most distributions) | Used for |
| --- | --- | --- |
| `nmcli` | NetworkManager | Wi-Fi name, signal, and security type |
| `iw` | iw | Wi-Fi name and signal when NetworkManager is not running |
| `nvidia-smi` | NVIDIA driver utilities | NVIDIA GPU usage, temperature, and memory |
| `wpctl` | WirePlumber (PipeWire) | Audio device name, volume, and mute state |
| `pactl` | PulseAudio utilities | Audio device, volume, and mute state when `wpctl` is absent |

AMD GPUs are read from the `amdgpu` driver's sysfs files and need no tool.
Wi-Fi connect and disconnect notifications need NetworkManager. `wpctl` is
preferred for audio and gives the readable device name; `pactl` also works
against PipeWire through its PulseAudio interface, and reports the device's
internal name.

## Installation

```sh
./install.sh
```

Then restart Orca (`orca --replace &`). `install.sh` copies the
`resource_monitor` package into `~/.local/share/orca/extensions/`, recompiles
its translations when GNU gettext's `msgfmt` is available, and approves it with
`orca --approve-extension resource_monitor`. Pass `--yes` to replace an
existing copy without being asked.

To remove it, run `./install.sh --uninstall`: it revokes the approval and
deletes the installed copy.

You can copy the folder yourself instead, then approve it:

```sh
mkdir -p ~/.local/share/orca/extensions
cp -r resource_monitor ~/.local/share/orca/extensions/
orca --approve-extension resource_monitor
```

Approval is required for security: Orca records the extension's SHA256 hash.
Any change to the package contents changes that hash, so run `install.sh`
again (or re-approve) after updating. You can also approve, disable, or delete
the extension on the **User Extensions** page of Orca's preferences.

## The command layer

Press **Orca+Shift+E** to enter the layer. Orca plays a short high tone and
brailles "Resource Monitor". Then press:

| Key | Reports |
| --- | --- |
| Space | Overall usage: used RAM and average processor load |
| C | Processor: average load and, on multi-core systems, the load of each core |
| M | Memory: used and total physical memory and swap |
| D | Drives: used and total space of local and network drives |
| G | GPU usage and temperature |
| Shift+G | GPU memory usage |
| O | Operating system: distribution, architecture, kernel, desktop and session |
| U | System uptime |
| W | Wi-Fi: network name (SSID), signal strength, security type |
| B | Battery: charge, whether it is charging, and the time remaining |
| A | Audio output: device and volume |
| Shift+A | Audio input: device and volume |
| L | Load averages and component temperatures |
| Escape | Leaves the layer (low tone) |

Resource keys keep the layer active so they can be repeated. **Pressing a
resource key twice quickly copies the information to the clipboard.**

The layer also ends when you press any other Orca command (the command then
runs normally), or after 10 seconds without a layer key. The timeout is
adjustable and can be turned off.

## Direct shortcuts

Every report also has a direct shortcut, so the layer is optional. As in the
layer, pressing a shortcut twice copies the information to the clipboard.

| Shortcut | Reports |
| --- | --- |
| Orca+Shift+1 | Processor |
| Orca+Shift+2 | Memory |
| Orca+Shift+3 | Drives |
| Orca+Shift+4 | Wi-Fi |
| Orca+Shift+5 | Overall usage |
| Orca+Shift+6 | Operating system |
| Orca+Shift+7 | Uptime |
| Orca+Shift+8 | GPU usage and temperature |
| Orca+Shift+9 | GPU memory |
| Orca+Shift+0 | Battery |

Audio output, audio input, and load averages have no default shortcut, because
the digits run out at nine. They are still registered as commands, so they
appear unbound in Orca's key bindings preferences and can be given a key
there, and they always have a layer key.

Orca+Shift+1, 2, 3, 4, 6, and 7 match the NVDA add-on's legacy shortcuts. The
entry key and the direct shortcuts can be changed in Orca's key bindings
preferences, under **Resource Monitor**. Layer keys are fixed, as in the NVDA
add-on.

## Settings

Open Orca's preferences, go to **User Extensions**, select **Resource
Monitor**, and press the settings button.

| Setting | Default | Purpose |
| --- | --- | --- |
| GPU temperature unit | Celsius | Celsius or Fahrenheit |
| Wi-fi connect/disconnect notification | both | off, message, sound, or both |
| Leave the command layer after this many idle seconds | 10 | 0 keeps the layer until Escape or another Orca command |

## What each report measures

- **Processor**: sampled from `/proc/stat` over 0.3 seconds, so the answer
  reflects the current load. Loads are for logical processors, so processors
  with simultaneous multithreading show two per core.
- **Memory**: used memory is total minus *available*, the same figure desktop
  system monitors show; file cache that the kernel can reclaim does not count
  as used. Swap includes zram.
- **Drives**: local block-device file systems and network shares (NFS, SMB,
  SSHFS, and similar). Pseudo file systems, snap and other read-only package
  images are skipped, and a device mounted several times, such as btrfs
  subvolumes, is reported once under its first mount point. Sizes match `df`.
  Each drive has a two-second limit, so an unreachable network share is
  reported as "not available" instead of freezing.
- **GPU**: NVIDIA through `nvidia-smi`, AMD through sysfs. Intel GPUs do not
  publish usage without root access and are not reported. On laptops with a
  sleeping NVIDIA GPU, `nvidia-smi` wakes it briefly.
- **Wi-Fi**: security types are named like the NVDA add-on (WPA2-PSK,
  WPA3-SAE, WPA2-Enterprise, ...). They describe what the access point
  offers; mixed networks are reported as, for example, WPA2-PSK/WPA3-SAE.
- **Uptime**: includes time spent suspended, like `/proc/uptime`.
- **Battery**: read from `/sys/class/power_supply`. A battery exposes either
  `energy_*` with `power_now` or `charge_*` with `current_now`; within one
  family the units cancel, so the time remaining is a division either way,
  and the families are never mixed because that would need the voltage and
  would turn a reading into a guess. The charge is measured against
  `energy_full`, the capacity the battery has now, not `energy_full_design`,
  which it had when new -- on a worn battery the design figure reports a
  charge that never reaches 100%. Two batteries are added together, and
  charging takes precedence over discharging, because on such a machine one
  battery can feed the other. No estimate is given when the rate is zero,
  which is also why a full battery reports no time remaining.
- **Audio**: the default output and input device, its volume, and whether it
  is muted, through `wpctl` or `pactl`. A volume above 100% is a state the
  sound server allows, so it is reported rather than clamped. `pactl` reports
  a percentage per channel and the first is used, because one figure spoken
  aloud is clearer than several.
- **Load averages**: from `/proc/loadavg`, over one, five, and fifteen
  minutes. This is not the same reading as processor load, and both are worth
  having: processor load is how busy the cores are now, while the load average
  is how many tasks have been waiting. A machine can sit at a low processor
  load with a high load average when tasks are blocked on disk or network,
  which is exactly the state where it is useful to know why everything feels
  slow.
- **Temperatures**: from `hwmon`, which labels its sensors, falling back to
  the thermal zones where there is nothing else. When a processor or graphics
  sensor is present only those are reported: a desktop also exposes
  temperatures for network cards, drives and chipsets, and padding the list
  with them buries the readings the question was about -- which matters more
  when the list is spoken than when it is seen. Readings outside -40 to 150
  degrees Celsius are discarded, because a disconnected probe commonly reports
  -274 and some sensors report a fixed critical value in the thousands.

Wi-Fi notifications follow NetworkManager: connecting, disconnecting, and
turning the wireless radio on or off. They use the NVDA add-on's sounds.

## Differences from the NVDA add-on

- Battery, audio devices, load averages, and temperatures are reported, none
  of which the NVDA add-on covers. Battery and load average come from the
  kernel and need no helper; audio needs `wpctl` or `pactl`.
- Linux terms replace Windows ones: swap instead of virtual memory, mount
  points instead of drive letters, distribution and kernel instead of Windows
  build.
- The operating system report adds the desktop and display server (for
  example "GNOME on Wayland"), which matters for accessibility on Linux.
- AMD GPUs are supported in addition to NVIDIA.
- Overall usage, GPU, and GPU memory have direct shortcuts (Orca+Shift+5, 8,
  and 9). The NVDA add-on's alternative memory shortcut (NVDA+Shift+5) is not
  needed and is used for overall usage instead.
- Orca+Shift+E is the entry key, like NVDA+Shift+E.
- In NVDA, pressing an unrelated key ends the layer and types the key. Orca
  does not let extensions see ordinary typing, so here unrelated keys are
  typed without ending the layer. Escape, any Orca command, or the idle
  timeout ends it.

## How the layer works, and a caveat

Orca's documented extension API lets an extension grab only keys that no Orca
command uses. The layer letters are Orca's browse-mode (structural navigation)
keys, so a layer built only on that API could not use them.

The layer therefore uses Orca's command manager more directly, in the same way
Orca's own math navigation mode does: the layer commands are registered
suspended and hidden from the key bindings list, and are grabbed only while
the layer is active. While active, the extension is Orca's modal input
handler, so a browse-mode letter such as C reports the processor instead of
moving to the next combo box. When the layer ends, the keys are released and
Orca refreshes its key grabs.

The extension never sees keys that are not Orca commands, so it cannot read
what you type.

This part relies on Orca internals that may change between Orca releases. If
a future Orca refuses the layer, the entry key says so and the direct
shortcuts, which use only the documented API, keep working.

## Translations

A Turkish translation is included. To add a language, copy
`resource_monitor/po/resource_monitor.pot` to `resource_monitor/po/<language>.po`,
translate it, and run `./update-translations.sh` (GNU gettext required), which
also regenerates the template and recompiles every catalog. Re-approve the
extension afterwards. To try a language, start Orca with, for example,
`LANGUAGE=tr orca --replace`.

## Tests

```sh
python3 -m unittest discover -s tests
```

The tests need Orca installed (they import its modules) but not running. They
cover parsing of every data source, report wording, the worker thread, the
NetworkManager monitor, the command layer against a stand-in command manager,
the extension's commands and notifications, and the placeholders in every
translation. They do not grab keys or change system state.

## Structure

```text
resource_monitor/
├── __init__.py       Extension class: commands, settings, presentation, lifecycle
├── layer.py          Command layer: suspended commands, modal handler, idle timer
├── resources.py      The reports, their keys, and how each is gathered
├── reports.py        User-facing sentences
├── system_info.py    Processor, memory, uptime, and operating system readers
├── disks.py          Mount table parsing and drive usage
├── gpu.py            NVIDIA (nvidia-smi) and AMD (sysfs) GPU readers
├── wifi.py           Current wireless connection (nmcli, iw)
├── wifi_monitor.py   NetworkManager connect and disconnect notifications
├── worker.py         Background thread for blocking queries
├── formatting.py     Sizes, percentages, durations, temperatures
├── i18n.py           Gettext setup shared by the modules
├── sounds/           Wi-Fi notification sounds from the NVDA add-on
├── po/               Translation template and translations
└── locale/           Compiled translations loaded by Orca
```

Nothing that can block (processor sampling, helper programs, network drives)
runs on Orca's main thread. Queries run in order on one background thread and
their results are presented through the GLib main loop.

## Credits

Based on Resource Monitor for NVDA by Alex Hall, Joseph Lee, Kefas Lungu, Beqa
Gozalishvili, Tuukka Ojala, Ethin Probst, Kevin Derome, and other NVDA
contributors, released under the GNU GPL. The report wording, the Wi-Fi
notification sounds, and parts of the Turkish translation come from that
add-on. The Linux implementation is new.
