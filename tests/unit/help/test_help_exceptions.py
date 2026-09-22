"""Unit tests for ``HelpLookupError`` and ``HelpDomainError``.

Covers the hierarchy, the structured attributes ``query`` / ``suggestions`` /
``hits`` (and ``domain`` / ``domains`` on the domain error), the message
format per case, ``to_dict()`` shape, and the package-level export.
"""

from __future__ import annotations

import json

import pytest

import mixpanel_headless as mp
from mixpanel_headless._internal.help.models import SearchHit
from mixpanel_headless.exceptions import (
    HelpDomainError,
    HelpDomainReason,
    HelpLookupError,
    MixpanelHeadlessError,
)


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

    def test_details_carry_hits_as_dicts(self) -> None:
        """``details["hits"]`` is the ``to_dict()`` form of every hit."""
        hit = _hit("Filter")
        exc = HelpLookupError("filtr", hits=(hit,))
        assert exc.details["hits"] == [hit.to_dict()]
        assert exc.to_dict()["details"]["hits"] == [hit.to_dict()]

    def test_details_hits_default_empty_list(self) -> None:
        """Without hits, ``details["hits"]`` is an empty list, not missing."""
        assert HelpLookupError("x").details["hits"] == []

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


# =============================================================================
# HelpDomainError
# =============================================================================


TITLES = ("dashboards", "reports", "cohorts")
"""Stand-in domain titles for the domain-error tests."""


class TestDomainErrorHierarchy:
    """``HelpDomainError`` is a ``HelpLookupError`` with its own code."""

    def test_subclasses_lookup_error(self) -> None:
        """The class sits under ``HelpLookupError`` and the package base."""
        assert issubclass(HelpDomainError, HelpLookupError)
        assert issubclass(HelpDomainError, MixpanelHeadlessError)

    def test_catchable_as_lookup_error(self) -> None:
        """A raise is caught by ``except HelpLookupError``."""
        with pytest.raises(HelpLookupError):
            raise HelpDomainError("Workspace", domain="nope", domains=TITLES)

    def test_code(self) -> None:
        """The stable code is ``HELP_BAD_DOMAIN``."""
        exc = HelpDomainError("Workspace", domain="nope", domains=TITLES)
        assert exc.code == "HELP_BAD_DOMAIN"

    def test_keyword_only_domain(self) -> None:
        """``domain`` is keyword-only."""
        with pytest.raises(TypeError):
            HelpDomainError("Workspace", "nope")  # type: ignore[misc]

    def test_exported_from_package(self) -> None:
        """The class and its reason alias are reachable from the package root."""
        assert mp.HelpDomainError is HelpDomainError
        assert mp.HelpDomainReason is HelpDomainReason
        assert "HelpDomainError" in mp.__all__
        assert "HelpDomainReason" in mp.__all__

    def test_listed_under_help_lookup_error_in_the_exception_tree(self) -> None:
        """``mp.help("exceptions")`` places ``HelpDomainError`` one level below its parent."""
        from mixpanel_headless._internal.help.relations import exception_tree

        rows = exception_tree()
        parent = rows.index(("HelpLookupError", 1))
        assert rows[parent + 1] == ("HelpDomainError", 2)


class TestDomainErrorAttributes:
    """``query``, ``domain``, ``domains``, ``suggestions``, and ``hits``."""

    def test_query_is_the_help_query_not_the_domain(self) -> None:
        """``query`` echoes the help query text; ``domain`` holds the flag value."""
        exc = HelpDomainError("Workspace", domain="nope", domains=TITLES)
        assert exc.query == "Workspace"
        assert exc.domain == "nope"

    def test_domains_are_stored_as_tuple(self) -> None:
        """A list of titles is normalized to a tuple in the given order."""
        exc = HelpDomainError("Workspace", domain="nope", domains=list(TITLES))
        assert exc.domains == TITLES
        assert isinstance(exc.domains, tuple)

    def test_suggestions_mirror_domains(self) -> None:
        """``suggestions`` repeats ``domains`` so generic handlers still see them."""
        exc = HelpDomainError("Workspace", domain="nope", domains=TITLES)
        assert exc.suggestions == TITLES

    def test_domains_default_empty(self) -> None:
        """``domains`` defaults to ``()`` and ``hits`` is always ``()``."""
        exc = HelpDomainError("Filter", domain="dashboards", reason="not_workspace")
        assert exc.domains == ()
        assert exc.suggestions == ()
        assert exc.hits == ()

    def test_reason_is_stored(self) -> None:
        """``reason`` defaults to ``unknown`` and echoes the constructor value."""
        assert HelpDomainError("W", domain="x").reason == "unknown"
        exc = HelpDomainError("W", domain="se", domains=TITLES, reason="ambiguous")
        assert exc.reason == "ambiguous"


class TestDomainErrorMessage:
    """One fixed sentence per reason; never ``No help entry``."""

    def test_unknown(self) -> None:
        """An unknown domain names the domain only."""
        exc = HelpDomainError("Workspace", domain="nope", domains=TITLES)
        assert str(exc) == "Unknown domain 'nope'."

    def test_ambiguous_lists_candidates(self) -> None:
        """An ambiguous prefix lists the candidate titles in order."""
        exc = HelpDomainError(
            "Workspace",
            domain="se",
            domains=("session and switching", "session replay"),
            reason="ambiguous",
        )
        assert str(exc) == (
            "Ambiguous domain 'se': session and switching, session replay."
        )

    def test_not_workspace_names_the_query(self) -> None:
        """``domain=`` on another query explains the restriction and names it."""
        exc = HelpDomainError("Filter", domain="dashboards", reason="not_workspace")
        assert str(exc) == (
            "--domain applies only to the Workspace listing; "
            "'Filter' is not the Workspace class."
        )

    @pytest.mark.parametrize("reason", ["unknown", "ambiguous", "not_workspace"])
    def test_message_never_says_no_help_entry(self, reason: HelpDomainReason) -> None:
        """No reason produces the parent's ``No help entry`` sentence.

        Args:
            reason: The domain-error reason under test.
        """
        exc = HelpDomainError("Workspace", domain="x", domains=TITLES, reason=reason)
        assert "No help entry" not in str(exc)


class TestDomainErrorDetails:
    """``details`` and ``to_dict()`` carry the structured fields."""

    def test_details_keys(self) -> None:
        """``details`` holds query, domain, domains, suggestions, and hits."""
        exc = HelpDomainError("Workspace", domain="nope", domains=TITLES)
        assert exc.details == {
            "query": "Workspace",
            "domain": "nope",
            "domains": list(TITLES),
            "suggestions": list(TITLES),
            "hits": [],
        }

    def test_to_dict_is_json_serializable(self) -> None:
        """``to_dict()`` round-trips through ``json.dumps``."""
        exc = HelpDomainError("Workspace", domain="nope", domains=TITLES)
        payload = exc.to_dict()
        assert json.loads(json.dumps(payload)) == payload
        assert payload["code"] == "HELP_BAD_DOMAIN"
        assert payload["message"] == "Unknown domain 'nope'."

    def test_repr(self) -> None:
        """``repr`` follows the base-class shape."""
        exc = HelpDomainError("Workspace", domain="nope", domains=TITLES)
        assert repr(exc) == (
            "HelpDomainError(message=\"Unknown domain 'nope'.\", "
            "code='HELP_BAD_DOMAIN')"
        )
