"""Unit tests for the pure write-time size-limit module.

Covers the boundary behavior of ``check_write_size`` (zero-byte, one under,
exactly at, one over, far over the ceiling) and the shape of
``MemorySizeLimitError`` (US1/US2 in spec.md).
"""

from __future__ import annotations

import pytest

from mixpanel_headless._internal.memory.limits import (
    MAX_MEMORY_WRITE_BYTES,
    MemorySizeLimitError,
    check_write_size,
)


class TestConstant:
    """``MAX_MEMORY_WRITE_BYTES`` is the single locked ceiling value."""

    def test_value_is_8192(self) -> None:
        """The ceiling is exactly 8 KiB (8,192 bytes)."""
        assert MAX_MEMORY_WRITE_BYTES == 8_192


class TestCheckWriteSizeAccepts:
    """Content at or under the ceiling is accepted (returns ``None``)."""

    def test_zero_byte_returns_none(self) -> None:
        """Zero-byte content is not oversized (FR-010)."""
        check_write_size(b"")  # must not raise

    def test_one_under_ceiling_returns_none(self) -> None:
        """A payload one byte under the ceiling is accepted."""
        data = b"x" * (MAX_MEMORY_WRITE_BYTES - 1)
        check_write_size(data)  # must not raise

    def test_exactly_at_ceiling_returns_none(self) -> None:
        """A payload exactly at the ceiling is accepted (inclusive, FR-002)."""
        data = b"x" * MAX_MEMORY_WRITE_BYTES
        check_write_size(data)  # must not raise


class TestCheckWriteSizeRejects:
    """Content over the ceiling raises ``MemorySizeLimitError``."""

    def test_one_over_ceiling_raises(self) -> None:
        """A payload one byte over the ceiling raises."""
        data = b"x" * (MAX_MEMORY_WRITE_BYTES + 1)
        with pytest.raises(MemorySizeLimitError):
            check_write_size(data)

    def test_far_over_ceiling_raises(self) -> None:
        """A payload far larger than the ceiling raises."""
        data = b"x" * (MAX_MEMORY_WRITE_BYTES * 4)
        with pytest.raises(MemorySizeLimitError):
            check_write_size(data)


class TestMemorySizeLimitErrorShape:
    """``MemorySizeLimitError`` carries structured, catchable fields."""

    def test_is_value_error_subclass(self) -> None:
        """``MemorySizeLimitError`` is a ``ValueError`` subclass."""
        assert issubclass(MemorySizeLimitError, ValueError)

    def test_fields_set_from_raise(self) -> None:
        """A raised instance carries the exact ``size`` and ``limit``."""
        data = b"x" * (MAX_MEMORY_WRITE_BYTES + 1)
        with pytest.raises(MemorySizeLimitError) as exc_info:
            check_write_size(data)
        err = exc_info.value
        assert err.size == len(data)
        assert err.limit == MAX_MEMORY_WRITE_BYTES

    def test_str_names_both_numbers(self) -> None:
        """The error message names both the rejected size and the limit."""
        err = MemorySizeLimitError(size=9000, limit=8192)
        message = str(err)
        assert "9000" in message
        assert "8192" in message

    def test_direct_construction_sets_fields(self) -> None:
        """Constructing directly with keyword args sets both attributes."""
        err = MemorySizeLimitError(size=100, limit=50)
        assert err.size == 100
        assert err.limit == 50
