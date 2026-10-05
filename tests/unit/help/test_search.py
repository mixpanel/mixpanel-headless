"""Unit tests for ``mixpanel_headless._internal.help.search``.

``search(term)`` is a case-insensitive substring search over the public
surface. These tests lock:

- the three match tiers and their order: names, then docstring summaries,
  then enum members and Literal values;
- the category vocabulary (``MemberKind``): the inventory ``ExportKind``
  plus ``method`` / ``property`` for ``Workspace`` members (Literal aliases
  are ``literal``, never ``function``);
- the display names: ``Workspace.<member>`` and ``<module>.<member>``;
- deduplication by ``(category, name)``;
- ``limit`` truncation and the empty-term error;
- the miss path: no hits, "Did you mean?" suggestions, never an exception
  for a non-empty term;
- module-state caching and ``clear_cache()``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from mixpanel_headless import HelpLookupError
from mixpanel_headless._internal.help import inventory as inventory_module
from mixpanel_headless._internal.help import search as search_module
from mixpanel_headless._internal.help.models import SearchHit, SearchResult
from mixpanel_headless._internal.help.search import clear_cache, search
from mixpanel_headless._literal_types import ALIAS_DOCS

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    """Clear the search index cache before and after every test.

    Yields:
        Nothing; the fixture only brackets the test with ``clear_cache()``.
    """
    clear_cache()
    yield
    clear_cache()


def _names(result: SearchResult, matched_on: str | None = None) -> list[str]:
    """Return the hit names of a result, optionally for one match tier.

    Args:
        result: A ``SearchResult``.
        matched_on: Keep only hits with this ``matched_on`` value; ``None``
            keeps every hit.

    Returns:
        The hit names in display order.
    """
    return [
        hit.name
        for hit in result.hits
        if matched_on is None or hit.matched_on == matched_on
    ]


def _by_name(result: SearchResult, name: str) -> SearchHit:
    """Return the single hit with ``name``.

    Args:
        result: A ``SearchResult``.
        name: The display name to find.

    Returns:
        The matching hit.

    Raises:
        AssertionError: When zero or several hits carry ``name``.
    """
    matches = [hit for hit in result.hits if hit.name == name]
    assert len(matches) == 1, f"{name!r} appears {len(matches)} times"
    return matches[0]


# =============================================================================
# Result shape
# =============================================================================


class TestResultShape:
    """``search`` returns a ``SearchResult`` whose ``term`` is the caller's text."""

    def test_returns_search_result_with_given_term(self) -> None:
        """The result echoes the term and holds ``SearchHit`` rows."""
        result = search("cohort")
        assert isinstance(result, SearchResult)
        assert result.term == "cohort"
        assert result.hits
        assert all(isinstance(hit, SearchHit) for hit in result.hits)
        assert result.suggestions == ()

    def test_surrounding_whitespace_is_ignored_for_matching(self) -> None:
        """Leading and trailing whitespace does not change the hits."""
        assert search("  cohort ").hits == search("cohort").hits

    def test_empty_term_raises_help_lookup_error(self) -> None:
        """An empty term raises ``HelpLookupError`` with an empty query."""
        with pytest.raises(HelpLookupError) as info:
            search("")
        assert info.value.query == ""
        assert info.value.suggestions == ()
        assert info.value.hits == ()

    def test_whitespace_only_term_raises_help_lookup_error(self) -> None:
        """A whitespace-only term is treated as empty."""
        with pytest.raises(HelpLookupError):
            search("   \t ")


# =============================================================================
# Match tiers and ordering
# =============================================================================


class TestOrdering:
    """Name hits come first, then doc hits, then member hits; each tier is sorted."""

    def test_tiers_appear_in_name_doc_member_order(self) -> None:
        """``matched_on`` values never go backwards along the hit list.

        ``day`` is used because it hits all three tiers on the real inventory
        (``DayUnit`` by name, ``TimeUnit`` by doc, ``AlertFrequencyPreset`` by
        member); ``cohort`` has no member-tier hit.
        """
        rank = {"name": 0, "doc": 1, "member": 2}
        for term in ("day", "cohort"):
            ranks = [rank[hit.matched_on] for hit in search(term).hits]
            assert ranks == sorted(ranks)
        assert {hit.matched_on for hit in search("day").hits} == {
            "name",
            "doc",
            "member",
        }

    def test_each_tier_is_sorted_by_category_then_name(self) -> None:
        """Within one tier, hits are sorted by ``(category, name)``."""
        result = search("cohort")
        for tier in ("name", "doc", "member"):
            keys = [
                (hit.category, hit.name)
                for hit in result.hits
                if hit.matched_on == tier
            ]
            assert keys == sorted(keys)

    def test_first_hit_is_the_smallest_name_tier_key(self) -> None:
        """``search("retention")`` starts with the name hit whose ``(category, name)`` is smallest.

        ``RetentionAlignment`` matches by name too, but as a ``literal`` it
        sorts behind any ``class`` or ``dataclass`` name hit. The assertion is
        on the ordering rule, not on a particular first name, so a new export
        cannot break it.
        """
        result = search("retention")
        first = result.hits[0]
        assert first.matched_on == "name"
        name_keys = [
            (h.category, h.name) for h in result.hits if h.matched_on == "name"
        ]
        assert (first.category, first.name) == min(name_keys)
        alignment = _by_name(result, "RetentionAlignment")
        assert alignment.category == "literal"
        assert alignment.matched_on == "name"
        assert result.hits.index(alignment) > 0

    def test_doc_tier_beats_member_tier(self) -> None:
        """An entry that matches in both the doc and member tiers reports ``doc``.

        The synthetic entry pins the tier order independently of the
        inventory; the real-inventory check finds every indexed row whose
        summary and members both contain ``day`` while its name does not
        (``FlowConversionWindowUnit`` today) and expects the same answer.
        """
        entry = search_module.IndexEntry(
            "literal", "Sample", "Buckets per day.", ("value day",)
        )
        hit = entry.match("day")
        assert hit is not None
        assert hit.matched_on == "doc"
        assert hit.summary == "Buckets per day."
        both = [
            row
            for row in search_module._index()
            if "day" not in row.name.lower()
            and "day" in row.summary.lower()
            and any("day" in text.lower() for text in row.members)
        ]
        assert both
        result = search("day")
        for row in both:
            live = _by_name(result, row.name)
            assert live.matched_on == "doc"
            assert live.summary == row.summary

    def test_name_tier_beats_doc_and_member_tiers(self) -> None:
        """An entry that matches in every tier reports ``name`` with its summary."""
        entry = search_module.IndexEntry(
            "literal", "DayUnit", "Buckets per day.", ("value day",)
        )
        hit = entry.match("day")
        assert hit is not None
        assert hit.matched_on == "name"
        assert hit.summary == "Buckets per day."

    def test_name_hits_contain_the_needle_in_their_name(self) -> None:
        """Every name-tier hit has the needle in its name."""
        result = search("Retention")
        for hit in result.hits:
            if hit.matched_on == "name":
                assert "retention" in hit.name.lower()

    def test_doc_hits_do_not_contain_the_needle_in_their_name(self) -> None:
        """A doc-tier hit matched only through its summary."""
        result = search("cohort")
        for hit in result.hits:
            if hit.matched_on == "doc":
                assert "cohort" not in hit.name.lower()
                assert "cohort" in hit.summary.lower()

    def test_workspace_ref_is_a_doc_hit_for_cohort(self) -> None:
        """``WorkspaceRef`` appears for ``cohort`` through its first doc line."""
        hit = _by_name(search("cohort"), "WorkspaceRef")
        assert hit.matched_on == "doc"
        assert hit.category == "model"
        assert "cohort" in hit.summary.lower()


# =============================================================================
# Categories
# =============================================================================


class TestCategories:
    """Categories are the inventory kinds plus ``method`` / ``property``."""

    def test_literal_alias_has_literal_category_and_summary(self) -> None:
        """``CohortAggregationType`` is ``literal`` with a non-empty summary."""
        hit = _by_name(search("cohort"), "CohortAggregationType")
        assert hit.category == "literal"
        assert hit.summary
        assert hit.matched_on == "name"

    def test_module_category_for_namespace_modules(self) -> None:
        """``accounts`` is a ``module`` hit with its docstring summary."""
        hit = _by_name(search("accounts"), "accounts")
        assert hit.category == "module"
        assert hit.summary

    def test_workspace_methods_are_qualified_and_categorized(self) -> None:
        """``search("query")`` includes ``Workspace.query`` with category ``method``."""
        result = search("query")
        hit = _by_name(result, "Workspace.query")
        assert hit.category == "method"
        assert hit.matched_on == "name"
        assert hit.summary
        assert not any(hit.name == "query" for hit in result.hits)

    def test_workspace_properties_have_property_category(self) -> None:
        """``Workspace.account`` is a ``property`` hit."""
        hit = _by_name(search("account"), "Workspace.account")
        assert hit.category == "property"
        assert hit.summary

    def test_namespace_module_members_are_qualified_functions(self) -> None:
        """``accounts.login_unified`` is a ``function`` hit under its module."""
        result = search("login_unified")
        hit = _by_name(result, "accounts.login_unified")
        assert hit.category == "function"
        assert hit.summary
        assert _by_name(result, "login_unified").category == "function"

    def test_exception_enum_model_dataclass_categories(self) -> None:
        """Exports keep their inventory kind as the category."""
        assert _by_name(search("APIError"), "APIError").category == "exception"
        assert _by_name(search("Filter"), "Filter").category == "dataclass"
        assert _by_name(search("Dashboard"), "Dashboard").category == "model"
        assert (
            _by_name(search("FeatureFlagStatus"), "FeatureFlagStatus").category
            == "enum"
        )

    def test_alias_and_constant_categories(self) -> None:
        """Union aliases are ``alias``; module constants are ``constant``.

        Neither has a docstring of its own, so both read their summary from
        ``ALIAS_DOCS`` instead of the ``typing`` / ``int`` docstring.
        """
        alias = _by_name(search("PropertySpec"), "PropertySpec")
        assert alias.category == "alias"
        assert alias.summary == ALIAS_DOCS["PropertySpec"]
        constant = _by_name(
            search("BUSINESS_CONTEXT_MAX_CHARS"), "BUSINESS_CONTEXT_MAX_CHARS"
        )
        assert constant.category == "constant"
        assert constant.summary == ALIAS_DOCS["BUSINESS_CONTEXT_MAX_CHARS"]

    def test_category_vocabulary_is_closed(self) -> None:
        """Every category across a broad search comes from the known set."""
        allowed = {
            "exception",
            "enum",
            "model",
            "dataclass",
            "class",
            "literal",
            "alias",
            "function",
            "module",
            "constant",
            "method",
            "property",
        }
        for term in ("e", "a", "_"):
            assert {hit.category for hit in search(term).hits} <= allowed


# =============================================================================
# Member hits
# =============================================================================


class TestMemberHits:
    """Enum member names and values, and Literal values, are searchable."""

    def test_enum_member_value_hit(self) -> None:
        """Searching an enum value string finds the enum through its member."""
        hit = _by_name(search("86400"), "AlertFrequencyPreset")
        assert hit.matched_on == "member"
        assert hit.category == "enum"
        assert hit.summary == "member DAILY = 86400"

    def test_enum_member_name_hit(self) -> None:
        """Searching an enum member name finds the enum through its member."""
        hit = _by_name(search("HOURLY"), "AlertFrequencyPreset")
        assert hit.matched_on == "member"
        assert hit.summary.startswith("member HOURLY = ")

    def test_literal_value_hit(self) -> None:
        """Searching a Literal value finds the alias with a ``value`` summary."""
        result = search("unique")
        hit = _by_name(result, "MathType")
        assert hit.category == "literal"
        assert hit.matched_on == "member"
        assert hit.summary == "value unique"

    def test_member_summary_shows_the_first_matching_member(self) -> None:
        """When several members match, the summary shows the first in order.

        ``"00"`` matches every ``AlertFrequencyPreset`` value (3600, 86400,
        604800) but neither the enum name nor its first docstring line, so
        the hit can only come from the member tier.
        """
        hit = _by_name(search("00"), "AlertFrequencyPreset")
        assert hit.matched_on == "member"
        assert hit.summary == "member HOURLY = 3600"

    def test_name_match_wins_over_member_match(self) -> None:
        """An entry whose name matches is reported once, as a name hit."""
        hit = _by_name(search("preset"), "AlertFrequencyPreset")
        assert hit.matched_on == "name"


# =============================================================================
# Deduplication and limit
# =============================================================================


class TestDedupAndLimit:
    """No ``(category, name)`` pair repeats; ``limit`` truncates the tail."""

    @pytest.mark.parametrize("term", ["cohort", "query", "a", "e", "s"])
    def test_no_duplicate_category_name_pairs(self, term: str) -> None:
        """Broad searches never repeat a ``(category, name)`` pair.

        Args:
            term: A search term with many hits.
        """
        keys = [(hit.category, hit.name) for hit in search(term).hits]
        assert len(keys) == len(set(keys))

    def test_limit_truncates_in_order(self) -> None:
        """``limit`` keeps the first ``limit`` hits of the untruncated result."""
        full = search("cohort")
        assert len(full.hits) > 3
        assert search("cohort", limit=3).hits == full.hits[:3]
        assert search("cohort", limit=0).hits == ()

    def test_limit_larger_than_hits_is_a_no_op(self) -> None:
        """A ``limit`` above the hit count returns every hit."""
        full = search("cohort")
        assert search("cohort", limit=len(full.hits) + 100) == full

    def test_negative_limit_raises_value_error(self) -> None:
        """A negative ``limit`` is rejected."""
        with pytest.raises(ValueError, match="limit"):
            search("cohort", limit=-1)


# =============================================================================
# Case-insensitivity
# =============================================================================


class TestCaseInsensitivity:
    """Matching ignores case in the needle and in the indexed text."""

    def test_session_upper_equals_lower(self) -> None:
        """``search("SESSION")`` and ``search("session")`` yield the same hits."""
        assert search("SESSION").hits == search("session").hits

    def test_session_finds_both_class_and_module(self) -> None:
        """``Session`` (model) and ``session`` (module) are separate hits."""
        result = search("session")
        assert _by_name(result, "Session").category == "model"
        assert _by_name(result, "session").category == "module"


# =============================================================================
# Miss path
# =============================================================================


class TestMiss:
    """A term that matches nothing gives no hits and close-name suggestions."""

    def test_miss_returns_suggestions_and_no_hits(self) -> None:
        """A near-miss returns ``difflib`` suggestions and an empty ``hits``."""
        result = search("Filtr")
        assert result.hits == ()
        assert "Filter" in result.suggestions
        assert len(result.suggestions) <= 5

    def test_miss_without_close_names_returns_empty_suggestions(self) -> None:
        """Gibberish returns no hits and no suggestions, without raising."""
        result = search("zqxjkvbnm_zz")
        assert result == SearchResult(term="zqxjkvbnm_zz")

    def test_multiword_term_is_matched_literally(self) -> None:
        """A term with an inner space is one needle, not two words."""
        result = search("nonexistent phrase")
        assert result.hits == ()


# =============================================================================
# Caching
# =============================================================================


class TestCaching:
    """The text index is built once per inventory and dropped by ``clear_cache``."""

    def test_index_is_reused_between_calls(self) -> None:
        """Two searches share the same index object."""
        search("cohort")
        first = search_module._INDEX
        search("query")
        assert search_module._INDEX is first

    def test_clear_cache_drops_the_index(self) -> None:
        """``clear_cache()`` resets the module state."""
        search("cohort")
        assert search_module._INDEX is not None
        clear_cache()
        assert search_module._INDEX is None

    def test_index_rebuilds_when_inventory_cache_is_cleared(self) -> None:
        """A fresh inventory tuple triggers a fresh index."""
        search("cohort")
        first = search_module._INDEX
        inventory_module.clear_cache()
        search("cohort")
        assert search_module._INDEX is not first


class TestPureSearchCore:
    """``build_index`` and ``search_index`` work over any supplied rows."""

    def test_build_index_dedupes_first_wins_and_sorts_by_code_point(self) -> None:
        """The first row per ``(category, name)`` wins; uppercase sorts first."""
        rows = [
            search_module.IndexEntry("method", "b", "first", ()),
            search_module.IndexEntry("method", "B", "", ()),
            search_module.IndexEntry("method", "b", "second", ()),
            search_module.IndexEntry("class", "z", "", ()),
        ]
        index = search_module.build_index(rows)
        assert [(r.category, r.name, r.summary) for r in index] == [
            ("class", "z", ""),
            ("method", "B", ""),
            ("method", "b", "first"),
        ]

    def test_search_index_uses_the_supplied_suggester_on_a_miss(self) -> None:
        """A miss asks ``suggest`` with the stripped term."""
        seen: list[str] = []

        def suggest(term: str) -> tuple[str, ...]:
            """Record the term and offer one name.

            Args:
                term: The stripped search term.

            Returns:
                A fixed suggestion.
            """
            seen.append(term)
            return ("Alpha",)

        index = search_module.build_index(
            [search_module.IndexEntry("class", "Alpha", "", ())]
        )
        result = search_module.search_index(index, "  zz ", suggest=suggest)
        assert result.hits == ()
        assert result.suggestions == ("Alpha",)
        assert result.term == "  zz "
        assert seen == ["zz"]

    def test_live_search_equals_search_index_over_the_live_index(self) -> None:
        """``search`` is ``search_index`` over the cached live index."""
        live = search("cohort", limit=4)
        pure = search_module.search_index(
            search_module._index(),
            "cohort",
            limit=4,
            suggest=lambda _term: (),
        )
        assert live == pure
