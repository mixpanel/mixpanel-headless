"""Property-based tests for the pure write-time size-limit module.

The I/O-free ``limits`` module carries the mutation-kill weight, so these
properties stress the boundary invariant across randomized byte-lengths
spanning zero, under, at, and over the ceiling:

- ``check_write_size`` returns ``None`` iff ``len(data) <= MAX_MEMORY_WRITE_BYTES``.
- Every raised ``MemorySizeLimitError`` satisfies ``size == len(data)`` and
  ``limit == MAX_MEMORY_WRITE_BYTES`` and ``size > limit``.

Byte-length-based strategies build payloads from a length only (``b"x" * n``)
rather than materializing arbitrary byte content, and "far over" cases are
capped at a modest size above the ceiling so tests stay fast.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mixpanel_headless._internal.memory.limits import (
    MAX_MEMORY_WRITE_BYTES,
    MemorySizeLimitError,
    check_write_size,
)

# Lengths spanning zero, arbitrary-under, exactly-at, and over-the-ceiling
# (capped a few KiB past the ceiling so payloads stay small and tests fast).
lengths = st.integers(min_value=0, max_value=MAX_MEMORY_WRITE_BYTES + 4_096)


class TestCheckWriteSizeProperties:
    """``check_write_size`` accepts iff within the ceiling, else raises."""

    @given(length=lengths)
    def test_returns_none_iff_within_ceiling(self, length: int) -> None:
        """Accept iff length <= ceiling; otherwise raise ``MemorySizeLimitError``."""
        data = b"x" * length
        if length <= MAX_MEMORY_WRITE_BYTES:
            check_write_size(data)  # must not raise
        else:
            with pytest.raises(MemorySizeLimitError):
                check_write_size(data)

    @given(
        length=st.integers(
            min_value=MAX_MEMORY_WRITE_BYTES + 1,
            max_value=MAX_MEMORY_WRITE_BYTES + 4_096,
        )
    )
    def test_raised_error_fields_match_input(self, length: int) -> None:
        """A raised error's ``size``/``limit`` reflect the actual input and ceiling."""
        data = b"x" * length
        with pytest.raises(MemorySizeLimitError) as exc_info:
            check_write_size(data)
        err = exc_info.value
        assert err.size == length
        assert err.limit == MAX_MEMORY_WRITE_BYTES
        assert err.size > err.limit
