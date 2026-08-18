"""Pure text serialization for Headless Memory entries (internal).

Serializes a :class:`~mixpanel_headless._internal.memory.entry.MemoryEntry` to a
leading ``---``-fenced front-matter block carrying only the confidence label,
followed by the verbatim markdown body, and parses that text back. The module is
deliberately I/O-free (no filesystem, no network) so it is the property- and
mutation-testing target for the slice. The reader is stdlib-only — no YAML
dependency — and rejects malformed or unlabeled input rather than defaulting.

Serialized shape::

    ---
    confidence: Confirmed
    ---
    <verbatim markdown body>

Only the leading fenced region is interpreted, so a body that itself contains
``---`` lines round-trips unchanged.
"""

from __future__ import annotations

from mixpanel_headless._internal.memory.entry import (
    CONFIDENCE_LABELS,
    ConfidenceLabel,
    MemoryEntry,
)

__all__ = ["MemoryFormatError", "parse", "serialize"]

_OPEN_FENCE = "---\n"
_FENCE = "---"


class MemoryFormatError(ValueError):
    """Raised when text cannot be parsed into a :class:`MemoryEntry`.

    Subclasses :class:`ValueError` so callers with existing ``ValueError``
    handling still catch it, while giving a precise type to match. The message
    names the specific defect (missing fence, missing/extra key, unknown label).
    """


def serialize(entry: MemoryEntry) -> str:
    """Render ``entry`` as front-matter followed by its verbatim body.

    Args:
        entry: The entry to serialize.

    Returns:
        ``"---\\nconfidence: {confidence}\\n---\\n{body}"`` — the body is
        appended unmodified.

    Example:
        ```python
        serialize(MemoryEntry(confidence="Confirmed", body="hi"))
        # "---\nconfidence: Confirmed\n---\nhi"
        ```
    """
    return f"{_OPEN_FENCE}confidence: {entry.confidence}\n{_FENCE}\n{entry.body}"


def parse(text: str) -> MemoryEntry:
    """Parse serialized text back into a :class:`MemoryEntry`.

    Reads the leading ``---``-fenced front-matter block, recovers the confidence
    label, and takes everything after the closing fence's newline as the body,
    verbatim. Only the leading fence is interpreted, so interior ``---`` lines in
    the body are preserved.

    Args:
        text: Serialized entry text, as produced by :func:`serialize`.

    Returns:
        The recovered entry, with a body byte-identical to the original.

    Raises:
        MemoryFormatError: ``text`` lacks the opening ``---`` fence, the
            front-matter is unterminated, omits ``confidence``, carries an
            unexpected extra key, or names a confidence value outside
            :data:`CONFIDENCE_LABELS`.

    Example:
        ```python
        parse("---\nconfidence: Observed\n---\nbody").body  # "body"
        ```
    """
    if not text.startswith(_OPEN_FENCE):
        raise MemoryFormatError(
            "missing opening front-matter fence (text must start with '---')"
        )

    front_matter_lines: list[str] = []
    body_start: int | None = None
    pos = len(_OPEN_FENCE)
    n = len(text)

    while True:
        newline = text.find("\n", pos)
        if newline == -1:
            line = text[pos:]
            if line == _FENCE:
                body_start = n  # closing fence at EOF -> empty body
            else:
                front_matter_lines.append(line)
            break
        line = text[pos:newline]
        if line == _FENCE:
            body_start = newline + 1
            break
        front_matter_lines.append(line)
        pos = newline + 1

    if body_start is None:
        raise MemoryFormatError(
            "unterminated front-matter (missing closing '---' fence)"
        )

    confidence = _parse_confidence(front_matter_lines)
    return MemoryEntry(confidence=confidence, body=text[body_start:])


def _parse_confidence(front_matter_lines: list[str]) -> ConfidenceLabel:
    """Extract and validate the confidence label from front-matter lines.

    Args:
        front_matter_lines: The lines between the opening and closing fences.

    Returns:
        The validated confidence label.

    Raises:
        MemoryFormatError: a line names a key other than ``confidence``, the
            ``confidence`` key is duplicated or absent, or its value is not one
            of :data:`CONFIDENCE_LABELS`.
    """
    value: str | None = None
    for line in front_matter_lines:
        key, _sep, raw_value = line.partition(":")
        if key.strip() != "confidence":
            raise MemoryFormatError(
                f"unexpected front-matter key {key.strip()!r}; "
                "only 'confidence' is allowed"
            )
        if value is not None:
            raise MemoryFormatError("duplicate 'confidence' key in front-matter")
        value = raw_value.strip()

    if value is None:
        raise MemoryFormatError("front-matter is missing the 'confidence' key")

    for label in CONFIDENCE_LABELS:
        if label == value:
            return label
    raise MemoryFormatError(
        f"invalid confidence label {value!r}; expected one of {CONFIDENCE_LABELS}"
    )
