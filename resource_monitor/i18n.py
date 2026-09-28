"""Gettext helpers shared by every module of the package."""

from __future__ import annotations

import os

from orca.extension import get_translation

# Orca derives the gettext domain and locale folder from the package's
# __init__.py, so submodules resolve their catalog through that file too.
_translation = get_translation(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "__init__.py")
)
_ = _translation.gettext
ngettext = _translation.ngettext
pgettext = _translation.pgettext
