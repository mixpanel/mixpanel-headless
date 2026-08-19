"""Unit tests for the memory entry record and confidence labels.

Covers the foundational ``MemoryEntry`` invariants (label set, immutability,
label validation, verbatim body) and the ``to_dict`` structured-output contract.
"""

from __future__ import annotations

import dataclasses
import json
from typing import get_args

import pytest

from mixpanel_headless._internal.memory.entry import (
    CONFIDENCE_LABELS,
    ConfidenceLabel,
    MemoryEntry,
)


class TestConfidenceLabels:
    """The label set is the four canonical values in descending trust order."""

    def test_label_set_and_order(self) -> None:
        """``CONFIDENCE_LABELS`` is exactly the four labels, highest trust first."""
        assert CONFIDENCE_LABELS == (
            "Confirmed",
            "Inferred",
            "Observed",
            "Predicted",
        )

    def test_tuple_matches_literal(self) -> None:
        """The runtime tuple and the ``ConfidenceLabel`` Literal cannot drift."""
        assert set(CONFIDENCE_LABELS) == set(get_args(ConfidenceLabel))


class TestMemoryEntryConstruction:
    """A ``MemoryEntry`` stores a valid label and a verbatim body."""

    @pytest.mark.parametrize("label", CONFIDENCE_LABELS)
    def test_constructs_for_each_label(self, label: ConfidenceLabel) -> None:
        """Each of the four labels constructs and round-trips its fields."""
        entry = MemoryEntry(confidence=label, body="content")
        assert entry.confidence == label
        assert entry.body == "content"

    def test_body_stored_verbatim(self) -> None:
        """The body is stored exactly, including markdown and whitespace."""
        body = "# Heading\n\n- item\n\ntrailing   "
        assert MemoryEntry(confidence="Observed", body=body).body == body

    def test_empty_body_is_valid(self) -> None:
        """An empty body is accepted."""
        assert MemoryEntry(confidence="Confirmed", body="").body == ""

    def test_is_frozen(self) -> None:
        """Entries are immutable — attribute assignment raises."""
        entry = MemoryEntry(confidence="Confirmed", body="x")
        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.body = "y"  # type: ignore[misc]

    def test_unknown_label_raises(self) -> None:
        """A confidence value outside the four labels raises ``ValueError``."""
        with pytest.raises(ValueError, match="Bogus"):
            MemoryEntry(confidence="Bogus", body="x")  # type: ignore[arg-type]

    def test_case_variant_label_raises(self) -> None:
        """Label matching is case-sensitive — ``confirmed`` is rejected."""
        with pytest.raises(ValueError):
            MemoryEntry(confidence="confirmed", body="x")  # type: ignore[arg-type]


class TestMemoryEntryToDict:
    """``to_dict`` yields JSON-serializable structured output."""

    def test_to_dict_shape(self) -> None:
        """The dict carries exactly the confidence and body values."""
        entry = MemoryEntry(confidence="Inferred", body="text")
        assert entry.to_dict() == {"confidence": "Inferred", "body": "text"}

    def test_to_dict_keys(self) -> None:
        """The dict has exactly the two documented keys."""
        entry = MemoryEntry(confidence="Predicted", body="")
        assert set(entry.to_dict()) == {"confidence", "body"}

    def test_to_dict_json_serializable(self) -> None:
        """The dict serializes to JSON with no custom encoder."""
        entry = MemoryEntry(confidence="Confirmed", body="a\nb\n---\nc")
        loaded = json.loads(json.dumps(entry.to_dict()))
        assert loaded == {"confidence": "Confirmed", "body": "a\nb\n---\nc"}
