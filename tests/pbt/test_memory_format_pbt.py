"""Property-based tests for the pure memory serialize/parse module.

The I/O-free ``format`` module carries the mutation-kill weight, so these
properties stress the round-trip and rejection invariants across randomized
inputs:

- Any label + arbitrary body -> ``parse(serialize(e)) == e`` (body byte-identical).
- A successful ``parse`` always yields a label in ``CONFIDENCE_LABELS``.
- ``serialize`` is deterministic for fixed inputs.
- Any ``confidence`` value outside the labels -> always raises.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

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

labels = st.sampled_from(CONFIDENCE_LABELS)
# Bodies that deliberately include fence-like lines, newlines, and unicode.
bodies = st.text(
    alphabet=st.characters(min_codepoint=1, max_codepoint=0x2FFF),
    max_size=200,
) | st.lists(
    st.sampled_from(["---", "text", "", "a: b", "  ", "→✓", "# h"]),
    max_size=8,
).map("\n".join)


class TestRoundTripProperties:
    """Serialize -> parse is a stable, body-preserving round-trip."""

    @given(label=labels, body=bodies)
    def test_round_trip(self, label: ConfidenceLabel, body: str) -> None:
        """Any valid entry survives a round-trip byte-for-byte."""
        entry = MemoryEntry(confidence=label, body=body)
        parsed = parse(serialize(entry))
        assert parsed == entry
        assert parsed.body == body

    @given(label=labels, body=bodies)
    def test_parse_yields_known_label(self, label: ConfidenceLabel, body: str) -> None:
        """A successful parse never produces a label outside the set."""
        parsed = parse(serialize(MemoryEntry(confidence=label, body=body)))
        assert parsed.confidence in CONFIDENCE_LABELS

    @given(label=labels, body=bodies)
    def test_serialize_deterministic(self, label: ConfidenceLabel, body: str) -> None:
        """``serialize`` returns the same text for the same entry."""
        entry = MemoryEntry(confidence=label, body=body)
        assert serialize(entry) == serialize(entry)


class TestRejectionProperties:
    """Unknown labels are always rejected, never defaulted."""

    @given(
        bad=st.text(max_size=20).filter(lambda s: s.strip() not in CONFIDENCE_LABELS),
        body=st.text(max_size=50).filter(lambda s: "\n" not in s and "---" not in s),
    )
    def test_unknown_label_always_raises(self, bad: str, body: str) -> None:
        """A confidence value outside the labels always raises."""
        text = f"---\nconfidence: {bad}\n---\n{body}"
        with pytest.raises(MemoryFormatError):
            parse(text)
