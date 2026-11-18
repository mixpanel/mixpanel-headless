"""Warning helpers in their own file, for the ``skip_file_prefixes`` tests.

The provenance shim in ``conformance/record/plugin.py`` must leave a
``skip_file_prefixes`` call alone. Proving that needs a helper whose file
differs from the test's, because the prefix names the frames to pass over
by file. The matching case here names this file, not its directory: the
test file sits in the same directory, and a directory prefix would skip
the test's own frame. Underscore-prefixed so pytest does not collect it.

The keyword travels in a mapping because mypy targets Python 3.10, where
``warnings.warn`` does not take it.
"""

from __future__ import annotations

import warnings
from typing import Any

_THIS_FILE = __file__


def warn_with_matching_prefix() -> None:
    """Warn from a second frame here, with a prefix that skips this file."""
    _warn_here((_THIS_FILE,))


def warn_with_empty_prefixes() -> None:
    """Warn from a second frame here, with no prefixes at all."""
    _warn_here(())


def warn_with_nonmatching_prefix() -> None:
    """Warn from a second frame here, with a prefix that matches nothing."""
    _warn_here(("/no/such/path",))


def _warn_here(prefixes: tuple[str, ...]) -> None:
    """Raise the warning at stacklevel 2 with the given prefixes.

    Args:
        prefixes: The value for ``skip_file_prefixes``.
    """
    options: dict[str, Any] = {"skip_file_prefixes": prefixes}
    warnings.warn("probe", UserWarning, stacklevel=2, **options)
