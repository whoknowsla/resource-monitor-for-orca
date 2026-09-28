"""Makes the extension package importable from the tests.

Orca's modules have an import cycle that only shows up when orca.extension is
imported first. Importing the command manager first mirrors Orca's own startup
order. Orca itself is fully imported before it loads extensions.
"""

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Tests compare English output.
os.environ["LANGUAGE"] = "C"

import orca.command_manager  # noqa: E402,F401  pylint: disable=unused-import,wrong-import-position
