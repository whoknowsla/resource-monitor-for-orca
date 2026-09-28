"""Tests for mount parsing, drive selection, and usage queries."""

import os
import tempfile
import threading
import unittest
from types import SimpleNamespace

import context  # noqa: F401  pylint: disable=unused-import

from resource_monitor.disks import (
    DiskUsage,
    Mount,
    parse_local_fs_types,
    parse_mounts,
    query_with_timeout,
    read_drives,
    select_drives,
    statvfs_usage,
)

MOUNTS = """\
proc /proc proc rw 0 0
/dev/mapper/root / btrfs rw,subvol=/@ 0 0
tmpfs /tmp tmpfs rw 0 0
/dev/mapper/root /home btrfs rw,subvol=/@home 0 0
/dev/nvme0n1p1 /boot vfat rw 0 0
/dev/loop3 /snap/core/1 squashfs ro 0 0
server:/export /mnt/my\\040share nfs4 rw 0 0
overlay /var/lib/docker/overlay2/x/merged overlay rw 0 0
"""

FILESYSTEMS = """\
nodev\tsysfs
nodev\ttmpfs
nodev\tproc
\tbtrfs
\tvfat
\tsquashfs
nodev\tnfs4
nodev\toverlay
\text4
"""


class ParseTests(unittest.TestCase):
    def test_parse_mounts_decodes_escapes(self):
        mounts = parse_mounts(MOUNTS)
        self.assertEqual(len(mounts), 8)
        self.assertEqual(mounts[6].mountpoint, "/mnt/my share")
        self.assertTrue(mounts[6].is_network)

    def test_parse_mounts_skips_short_lines(self):
        self.assertEqual(parse_mounts("broken line\n"), [])

    def test_local_types_exclude_nodev_and_include_zfs(self):
        types = parse_local_fs_types(FILESYSTEMS)
        self.assertIn("btrfs", types)
        self.assertIn("zfs", types)
        self.assertNotIn("tmpfs", types)
        self.assertNotIn("nfs4", types)


class SelectTests(unittest.TestCase):
    def test_selects_one_entry_per_device_and_keeps_network_drives(self):
        selected = select_drives(parse_mounts(MOUNTS), parse_local_fs_types(FILESYSTEMS))
        self.assertEqual([mount.mountpoint for mount in selected], ["/", "/boot", "/mnt/my share"])


class UsageTests(unittest.TestCase):
    def test_statvfs_usage_matches_df(self):
        fake = SimpleNamespace(f_blocks=1000, f_bfree=300, f_bavail=250, f_frsize=4096)
        usage = statvfs_usage("/", statvfs=lambda _path: fake)
        self.assertEqual(usage.total, 1000 * 4096)
        self.assertEqual(usage.used, 700 * 4096)
        self.assertEqual(usage.available, 250 * 4096)
        # Reserved blocks are excluded from the percentage, as df does.
        self.assertAlmostEqual(usage.percent, 700 / 950 * 100)

    def test_percent_of_empty_file_system(self):
        self.assertEqual(DiskUsage(total=0, used=0, available=0).percent, 0.0)

    def test_query_with_timeout_returns_result(self):
        usage = DiskUsage(1, 1, 0)
        self.assertIs(query_with_timeout(lambda: usage), usage)

    def test_query_with_timeout_handles_errors(self):
        def fail():
            raise OSError("stale file handle")

        self.assertIsNone(query_with_timeout(fail))

    def test_query_with_timeout_gives_up_on_hangs(self):
        release = threading.Event()
        try:
            self.assertIsNone(query_with_timeout(lambda: release.wait(5), timeout=0.05))
        finally:
            release.set()


class ReadDrivesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.mounts = os.path.join(self.directory.name, "mounts")
        self.filesystems = os.path.join(self.directory.name, "filesystems")
        with open(self.mounts, "w", encoding="utf-8") as file:
            file.write(MOUNTS)
        with open(self.filesystems, "w", encoding="utf-8") as file:
            file.write(FILESYSTEMS)

    def test_reports_usage_and_unreachable_network_drives(self):
        def usage_of(path):
            if path == "/mnt/my share":
                raise OSError("host is down")
            if path == "/boot":
                return DiskUsage(total=0, used=0, available=0)
            return DiskUsage(total=100, used=40, available=60)

        reports = read_drives(self.mounts, self.filesystems, usage_of=usage_of)
        self.assertEqual(
            [(report.mount.mountpoint, report.usage) for report in reports],
            [("/", DiskUsage(100, 40, 60)), ("/mnt/my share", None)],
        )

    def test_mount_is_immutable(self):
        mount = Mount("/dev/sda1", "/", "ext4")
        with self.assertRaises(AttributeError):
            mount.fstype = "xfs"  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
