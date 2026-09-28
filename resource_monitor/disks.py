"""Finds mounted drives and measures their space.

Local and network drives are reported; pseudo file systems (proc, tmpfs,
cgroup, overlay, and the like) and read-only package images are skipped. The
same device mounted more than once, such as btrfs subvolumes, is reported
once. Every size query has a time limit, because a stale network mount can
block forever.
"""

from __future__ import annotations

import contextlib
import os
import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass

PROC_MOUNTS = "/proc/self/mounts"
PROC_FILESYSTEMS = "/proc/filesystems"
QUERY_TIMEOUT_SECONDS = 2.0

NETWORK_FS_TYPES = frozenset(
    {
        "9p",
        "afs",
        "ceph",
        "cifs",
        "davfs",
        "fuse.davfs2",
        "fuse.glusterfs",
        "fuse.rclone",
        "fuse.s3fs",
        "fuse.sshfs",
        "glusterfs",
        "ncpfs",
        "nfs",
        "nfs4",
        "smb3",
        "smbfs",
        "sshfs",
    }
)

# Device-backed but not interesting: snap and flatpak-style package images are
# always full.
IGNORED_FS_TYPES = frozenset({"squashfs", "erofs"})

# ZFS registers as nodev yet stores real data.
EXTRA_LOCAL_FS_TYPES = frozenset({"zfs"})

_OCTAL_ESCAPE = re.compile(r"\\([0-7]{3})")


@dataclass(frozen=True)
class Mount:
    """One line of the mount table."""

    device: str
    mountpoint: str
    fstype: str

    @property
    def is_network(self) -> bool:
        """True for network file systems."""

        return self.fstype in NETWORK_FS_TYPES


@dataclass(frozen=True)
class DiskUsage:
    """Space on one drive, in bytes, computed the same way as df."""

    total: int
    used: int
    available: int

    @property
    def percent(self) -> float:
        """Used space as a percentage of the space ordinary users can fill."""

        usable = self.used + self.available
        if usable <= 0:
            return 0.0
        return self.used / usable * 100.0


@dataclass(frozen=True)
class DriveReport:
    """A drive and its usage, or None when the drive could not be queried."""

    mount: Mount
    usage: DiskUsage | None


def _unescape(field: str) -> str:
    return _OCTAL_ESCAPE.sub(lambda match: chr(int(match.group(1), 8)), field)


def parse_mounts(text: str) -> list[Mount]:
    """Parses /proc/self/mounts content, decoding escaped spaces and tabs."""

    mounts = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        device, mountpoint, fstype = (_unescape(field) for field in fields[:3])
        mounts.append(Mount(device=device, mountpoint=mountpoint, fstype=fstype))
    return mounts


def parse_local_fs_types(text: str) -> frozenset[str]:
    """Returns file system types from /proc/filesystems that need a block device."""

    types = set(EXTRA_LOCAL_FS_TYPES)
    for line in text.splitlines():
        fields = line.split()
        if len(fields) == 1:
            types.add(fields[0])
    return frozenset(types)


def select_drives(mounts: Iterable[Mount], local_fs_types: frozenset[str]) -> list[Mount]:
    """Returns the mounts worth reporting, one per device, in mount order."""

    selected: list[Mount] = []
    seen_devices: set[str] = set()
    for mount in mounts:
        if mount.fstype in IGNORED_FS_TYPES:
            continue
        if not (mount.is_network or mount.fstype in local_fs_types):
            continue
        if not mount.device or mount.device in seen_devices:
            continue
        seen_devices.add(mount.device)
        selected.append(mount)
    return selected


def statvfs_usage(path: str, statvfs: Callable[[str], os.statvfs_result] = os.statvfs) -> DiskUsage:
    """Returns the usage of the file system containing path."""

    info = statvfs(path)
    total = info.f_blocks * info.f_frsize
    used = (info.f_blocks - info.f_bfree) * info.f_frsize
    available = info.f_bavail * info.f_frsize
    return DiskUsage(total=total, used=used, available=available)


def query_with_timeout(
    query: Callable[[], DiskUsage],
    timeout: float = QUERY_TIMEOUT_SECONDS,
) -> DiskUsage | None:
    """Runs query in a daemon thread; returns None on error or timeout."""

    result: list[DiskUsage] = []

    def run() -> None:
        # An unreachable drive is reported as not available by the caller.
        with contextlib.suppress(OSError):
            result.append(query())

    thread = threading.Thread(target=run, name="resource-monitor-statvfs", daemon=True)
    thread.start()
    thread.join(timeout)
    return result[0] if result else None


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8", errors="replace") as file:
        return file.read()


def read_drives(
    mounts_path: str = PROC_MOUNTS,
    filesystems_path: str = PROC_FILESYSTEMS,
    usage_of: Callable[[str], DiskUsage] = statvfs_usage,
    timeout: float = QUERY_TIMEOUT_SECONDS,
) -> list[DriveReport]:
    """Returns every reportable drive with its usage. Blocks; call off the main thread."""

    drives = select_drives(
        parse_mounts(_read_text(mounts_path)),
        parse_local_fs_types(_read_text(filesystems_path)),
    )
    reports = []
    for mount in drives:
        usage = query_with_timeout(lambda path=mount.mountpoint: usage_of(path), timeout)
        if usage is not None and usage.total <= 0:
            continue
        reports.append(DriveReport(mount=mount, usage=usage))
    return reports
