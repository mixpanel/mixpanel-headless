"""Write-time size-limit enforcement for Headless Memory (internal).

Holds the single per-file byte ceiling every memory write primitive enforces,
and the pure, I/O-free check that raises a typed error when content exceeds
it. Kept separate from ``backend.py`` so the size comparison is an isolated
unit-, property-, and mutation-testable target, matching ``format.py``'s
discipline.
"""

from __future__ import annotations

from typing import Final

__all__ = ["MAX_MEMORY_WRITE_BYTES", "MemorySizeLimitError", "check_write_size"]

MAX_MEMORY_WRITE_BYTES: Final[int] = 8_192
"""The per-file byte ceiling every memory write primitive enforces.

8 KiB (8 x 1024 bytes). Locked — a memory note is a single concise fact, not
a pasted document. Inclusive: a payload of exactly this many bytes is
accepted. Scoped to a single file's content in one write; never summed
across files, scopes, or an entire ``memory/`` tree.
"""


class MemorySizeLimitError(ValueError):
    """Raised when write content exceeds :data:`MAX_MEMORY_WRITE_BYTES`.

    Subclasses :class:`ValueError` so callers with existing ``ValueError``
    handling still catch it, while giving a precise type to match without
    string-matching a message, matching the ``MemoryFormatError`` precedent
    in ``format.py``.

    Attributes:
        size: The rejected content's length in bytes.
        limit: The ceiling it exceeded (:data:`MAX_MEMORY_WRITE_BYTES` at the
            time of the raise).

    Example:
        ```python
        try:
            check_write_size(b"x" * 8_193)
        except MemorySizeLimitError as err:
            err.size, err.limit  # (8193, 8192)
        ```
    """

    def __init__(self, size: int, limit: int) -> None:
        """Initialize the error with the rejected size and the ceiling.

        Args:
            size: The rejected content's length in bytes.
            limit: The ceiling that was exceeded.
        """
        self.size = size
        self.limit = limit
        super().__init__(
            f"Memory write of {size} bytes exceeds the {limit}-byte per-file limit."
        )


def check_write_size(data: bytes) -> None:
    """Raise if ``data`` exceeds :data:`MAX_MEMORY_WRITE_BYTES`.

    A pure, I/O-free comparison of ``len(data)`` against the locked ceiling.
    Intended to run before any filesystem syscall in a write path, so a raise
    is a strict no-op with respect to disk state.

    Args:
        data: The raw bytes a caller wants to persist.

    Returns:
        ``None`` when ``len(data) <= MAX_MEMORY_WRITE_BYTES`` (the ceiling is
        inclusive; zero-byte content is always accepted).

    Raises:
        MemorySizeLimitError: ``len(data) > MAX_MEMORY_WRITE_BYTES``.

    Example:
        ```python
        check_write_size(b"short note")  # None
        check_write_size(b"x" * 8_193)  # raises MemorySizeLimitError
        ```
    """
    size = len(data)
    if size > MAX_MEMORY_WRITE_BYTES:
        raise MemorySizeLimitError(size=size, limit=MAX_MEMORY_WRITE_BYTES)
