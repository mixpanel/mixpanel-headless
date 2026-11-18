"""A warning helper in its own file, for the ``skip_file_prefixes`` test.

The provenance shim in ``conformance/record/plugin.py`` must leave a
``skip_file_prefixes`` call alone. Proving that needs a helper whose file
differs from the test's, because the prefix names the frames to pass over
by file. The prefix here is this file, not its directory: the test file
sits in the same directory, and a directory prefix would skip the test's
own frame too. Underscore-prefixed so pytest does not collect it.
"""

from __future__ import annotations

import warnings
from typing import Any

_THIS_FILE = __file__


def warn_through_two_package_frames() -> None:
    """Warn from a second frame in this file, skipping both.

    ``stacklevel=2`` alone would blame this function, which is still this
    file. The prefix carries the search past every frame here, so the
    warning blames the caller in another file.
    """
    _warn_here()


def _warn_here() -> None:
    """Raise the warning, skipping every frame of this file.

    The keyword travels in a mapping because mypy targets Python 3.10,
    where ``warnings.warn`` does not take ``skip_file_prefixes``.
    """
    options: dict[str, Any] = {"skip_file_prefixes": (_THIS_FILE,)}
    warnings.warn("probe", UserWarning, stacklevel=2, **options)
