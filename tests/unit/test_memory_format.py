"""Unit tests for the pure memory entry serialize/parse module.

Covers the round-trip contract (US1), body fidelity including interior ``---``
lines (US2), and loud rejection of malformed or unlabeled input (US3).
"""

from __future__ import annotations

import pytest

from mixpanel_headless._internal.memory.entry import (
    CONFIDENCE_LABELS,
    ConfidenceLabel,
    MemoryEntry,
)
from mixpanel_headless._internal.memory.format import (
    MemoryFormatError,
    parse,
    serialize,
)


class TestSerialize:
    """``serialize`` emits front-matter followed by the verbatim body."""

    def test_front_matter_shape(self) -> None:
        """Serialized text opens with the fenced confidence block."""
        text = serialize(MemoryEntry(confidence="Confirmed", body="hi"))
        assert text == "---\nconfidence: Confirmed\n---\nhi"

    def test_body_appended_verbatim(self) -> None:
        """The body follows the closing fence unchanged."""
        text = serialize(MemoryEntry(confidence="Observed", body="a\nb\n"))
        assert text.endswith("---\na\nb\n")


class TestRoundTrip:
    """``parse`` inverts ``serialize`` for every label (US1)."""

    @pytest.mark.parametrize("label", CONFIDENCE_LABELS)
    def test_round_trip_each_label(self, label: ConfidenceLabel) -> None:
        """Each label survives a serialize -> parse round-trip."""
        entry = MemoryEntry(confidence=label, body="some\nbody")
        assert parse(serialize(entry)) == entry


class TestBodyFidelity:
    """The body is preserved byte-for-byte across a round-trip (US2)."""

    @pytest.mark.parametrize(
        "body",
        [
            "before\n---\nafter",  # interior fence-like line
            "---\nstarts with a fence line",
            "",  # empty
            "unicode → ✓ 日本語   ",  # unicode + trailing whitespace
            "\n\nleading and trailing blanks\n\n",
            "---",  # body is exactly a lone fence line
        ],
    )
    def test_body_preserved(self, body: str) -> None:
        """Arbitrary bodies round-trip unchanged; interior ``---`` is not a fence."""
        entry = MemoryEntry(confidence="Inferred", body=body)
        assert parse(serialize(entry)).body == body


class TestParseRejection:
    """Malformed or unlabeled input raises ``MemoryFormatError`` (US3)."""

    def test_error_is_value_error(self) -> None:
        """``MemoryFormatError`` is a ``ValueError`` subclass."""
        assert issubclass(MemoryFormatError, ValueError)

    def test_missing_opening_fence(self) -> None:
        """Text without a leading ``---`` fence is rejected."""
        with pytest.raises(MemoryFormatError, match="front-matter"):
            parse("no front matter here")

    def test_unterminated_front_matter(self) -> None:
        """An opening fence with no closing ``---`` is rejected."""
        with pytest.raises(MemoryFormatError, match="closing|terminat"):
            parse("---\nconfidence: Confirmed\nbody with no close")

    def test_missing_confidence_key(self) -> None:
        """Front-matter without a ``confidence`` key is rejected."""
        with pytest.raises(MemoryFormatError, match="confidence"):
            parse("---\ntitle: x\n---\nbody")

    def test_empty_front_matter_missing_key(self) -> None:
        """An empty front-matter block (no keys at all) is rejected."""
        with pytest.raises(MemoryFormatError, match="missing"):
            parse("---\n---\nbody")

    def test_extra_key_rejected(self) -> None:
        """Front-matter with an unexpected extra key is rejected."""
        with pytest.raises(MemoryFormatError):
            parse("---\nconfidence: Confirmed\ntitle: x\n---\nbody")

    def test_unknown_label_value(self) -> None:
        """A confidence value outside the four labels is rejected by name."""
        with pytest.raises(MemoryFormatError, match="Certain"):
            parse("---\nconfidence: Certain\n---\nbody")

    def test_blank_label_value(self) -> None:
        """A blank confidence value is rejected."""
        with pytest.raises(MemoryFormatError):
            parse("---\nconfidence:   \n---\nbody")

    def test_duplicate_confidence_key(self) -> None:
        """A repeated ``confidence`` key is rejected rather than silently merged."""
        with pytest.raises(MemoryFormatError, match="duplicate"):
            parse("---\nconfidence: Confirmed\nconfidence: Observed\n---\nbody")

    def test_closing_fence_at_eof_empty_body(self) -> None:
        """A closing fence with no trailing newline yields an empty body."""
        entry = parse("---\nconfidence: Confirmed\n---")
        assert entry.body == ""

    def test_unterminated_at_eof_without_newline(self) -> None:
        """Front-matter whose final line is not a fence (no newline) is rejected."""
        with pytest.raises(MemoryFormatError, match="closing|terminat"):
            parse("---\nconfidence: Confirmed")

    def test_whitespace_around_label_tolerated(self) -> None:
        """Surrounding whitespace on the value is trimmed before matching."""
        assert (
            parse("---\nconfidence:  Confirmed \n---\nbody").confidence == "Confirmed"
        )
