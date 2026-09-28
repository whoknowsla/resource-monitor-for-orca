"""Checks the compiled translations shipped with the extension."""

import gettext
import glob
import os
import string
import unittest

import context

PACKAGE_DIR = os.path.join(context.ROOT, "resource_monitor")
CATALOGS = sorted(glob.glob(os.path.join(PACKAGE_DIR, "locale", "*", "LC_MESSAGES", "*.mo")))


def placeholders(text):
    return sorted(field for _, field, _, _ in string.Formatter().parse(text) if field is not None)


class TranslationTests(unittest.TestCase):
    def test_catalogs_exist_and_use_the_package_domain(self):
        self.assertTrue(CATALOGS)
        for path in CATALOGS:
            self.assertEqual(os.path.basename(path), "resource_monitor.mo")

    def test_translations_keep_their_placeholders(self):
        for path in CATALOGS:
            with open(path, "rb") as file:
                catalog = gettext.GNUTranslations(file)._catalog  # pylint: disable=protected-access
            for key, translation in catalog.items():
                if not key:
                    continue
                source = key[0] if isinstance(key, tuple) else key
                with self.subTest(catalog=path, msgid=source):
                    self.assertTrue(translation)
                    self.assertEqual(placeholders(source), placeholders(translation))


if __name__ == "__main__":
    unittest.main()
