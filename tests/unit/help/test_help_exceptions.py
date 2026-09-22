"""Unit tests for ``HelpLookupError``.

Covers the hierarchy, the structured attributes ``query`` / ``suggestions`` /
``hits``, the message format with and without suggestions, ``to_dict()``
shape, and the package-level export.
"""

from __future__ import annotations

import json

import pytest

import mixpanel_headless as mp
from mixpanel_headless._internal.help.models import SearchHit
from mixpanel_headless.exceptions import HelpLookupError, MixpanelHeadlessError


def _hit(name: str) -> SearchHit:
    """Build a minimal ``SearchHit`` for a type export.

    Args:
        name: Export name to place in the hit.

    Returns:
        A ``SearchHit`` in the ``type`` category matched on its name.
    """
    return SearchHit(category="type", name=name, summary="", matched_on="name")


class TestHierarchy:
    """``HelpLookupError`` sits under ``MixpanelHeadlessError`` and is exported."""

    def test_subclasses_base(self) -> None:
        """``HelpLookupError`` is a ``MixpanelHeadlessError``."""
        assert issubclass(HelpLookupError, MixpanelHeadlessError)

    def test_catchable_as_base(self) -> None:
        """A raise is caught by ``except MixpanelHeadlessError``."""
        with pytest.raises(MixpanelHeadlessError):
            raise HelpLookupError("Nope")

    def test_exported_from_package(self) -> None:
        """The class is reachable as ``mixpanel_headless.HelpLookupError``."""
        assert mp.HelpLookupError is HelpLookupError
        assert "HelpLookupError" in mp.__all__


class TestAttributes:
    """The structured attributes are stored as given and default to empty tuples."""

    def test_query_is_stored(self) -> None:
        """``query`` echoes the constructor argument."""
        exc = HelpLookupError("Nope")
        assert exc.query == "Nope"

    def test_defaults_are_empty_tuples(self) -> None:
        """``suggestions`` and ``hits`` default to ``()``."""
        exc = HelpLookupError("Nope")
        assert exc.suggestions == ()
        assert exc.hits == ()
        assert isinstance(exc.suggestions, tuple)
        assert isinstance(exc.hits, tuple)

    def test_suggestions_are_stored_as_tuple(self) -> None:
        """A list of suggestions is normalized to a tuple in the given order."""
        exc = HelpLookupError("Filtr", suggestions=["Filter", "FilterOperator"])
        assert exc.suggestions == ("Filter", "FilterOperator")

    def test_hits_are_stored_as_tuple(self) -> None:
        """Search hits are kept as a tuple of the objects passed in."""
        hit = _hit("Filter")
        exc = HelpLookupError("filtr", hits=[hit])
        assert exc.hits == (hit,)
        assert exc.hits[0] is hit

    def test_keyword_only_extras(self) -> None:
        """``suggestions`` and ``hits`` are keyword-only."""
        with pytest.raises(TypeError):
            HelpLookupError("x", ("a",))  # type: ignore[misc]


class TestMessage:
    """Message format: ``No help entry for '{query}'.`` plus an optional suggestion tail."""

    def test_message_without_suggestions(self) -> None:
        """No suggestions produces the bare sentence."""
        exc = HelpLookupError("Workspace.nope")
        assert str(exc) == "No help entry for 'Workspace.nope'."
        assert exc.message == "No help entry for 'Workspace.nope'."

    def test_message_with_suggestions(self) -> None:
        """Suggestions are appended as ``Did you mean: a, b, c?``."""
        exc = HelpLookupError("Filtr", suggestions=("Filter", "FilterOperator", "Fx"))
        assert str(exc) == (
            "No help entry for 'Filtr'. Did you mean: Filter, FilterOperator, Fx?"
        )

    def test_message_with_single_suggestion(self) -> None:
        """A single suggestion has no separators."""
        exc = HelpLookupError("Filtr", suggestions=("Filter",))
        assert str(exc) == "No help entry for 'Filtr'. Did you mean: Filter?"

    def test_hits_do_not_change_message(self) -> None:
        """Search hits are carried on the instance but never rendered in the message."""
        exc = HelpLookupError("filtr", hits=(_hit("Filter"),))
        assert str(exc) == "No help entry for 'filtr'."

    def test_empty_query_still_formats(self) -> None:
        """An empty query renders with empty quotes."""
        assert str(HelpLookupError("")) == "No help entry for ''."


class TestCodeAndDetails:
    """Machine-readable code and ``to_dict()`` payload."""

    def test_code(self) -> None:
        """The stable code is ``HELP_NOT_FOUND``."""
        assert HelpLookupError("x").code == "HELP_NOT_FOUND"

    def test_details_carry_query_and_suggestions(self) -> None:
        """``details`` holds ``query`` and ``suggestions`` as JSON-friendly values."""
        exc = HelpLookupError("Filtr", suggestions=("Filter",))
        assert exc.details["query"] == "Filtr"
        assert exc.details["suggestions"] == ["Filter"]

    def test_to_dict_is_json_serializable(self) -> None:
        """``to_dict()`` round-trips through ``json.dumps``."""
        exc = HelpLookupError(
            "Filtr",
            suggestions=("Filter",),
            hits=(_hit("Filter"),),
        )
        payload = exc.to_dict()
        text = json.dumps(payload)
        assert json.loads(text) == payload
        assert payload["code"] == "HELP_NOT_FOUND"
        assert payload["message"].startswith("No help entry for 'Filtr'.")

    def test_repr(self) -> None:
        """``repr`` follows the base-class shape."""
        exc = HelpLookupError("Filtr")
        assert repr(exc) == (
            "HelpLookupError(message=\"No help entry for 'Filtr'.\", "
            "code='HELP_NOT_FOUND')"
        )
