"""Unit tests for ``mixpanel_headless._internal.help.hints``.

Covers Plan 047 Phase 4 step 3 (P17, D8):

- ``tokens`` splits a query on ``.`` and whitespace into whole tokens.
- ``hints_for`` returns at most one hint: the bare ``Workspace`` query
  points at the hosted API page, ``listing`` entries get none, and
  otherwise the first ``REFERENCE_HINTS`` rule whose trigger set intersects
  the token set wins (so ``query_funnel`` picks funnels before insights).
- Every returned URL is hosted under ``DOCS_BASE``.
"""

from __future__ import annotations

import pytest

from mixpanel_headless._internal.help.hints import hints_for, tokens
from mixpanel_headless._internal.help.models import Hint
from mixpanel_headless._internal.help.registry import (
    DOCS_BASE,
    REFERENCE_HINTS,
    WORKSPACE_HINT,
    hint_url,
)


class TestTokens:
    """``tokens`` splitting."""

    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            ("Workspace.query_funnel", ("Workspace", "query_funnel")),
            ("search cohort", ("search", "cohort")),
            ("search   cohort", ("search", "cohort")),
            (" a . b ", ("a", "b")),
            ("Workspace.query.events", ("Workspace", "query", "events")),
            ("Filter", ("Filter",)),
            ("", ()),
            ("   ", ()),
            ("..", ()),
        ],
    )
    def test_split(self, query: str, expected: tuple[str, ...]) -> None:
        """Dots and whitespace separate tokens; empty pieces are dropped."""
        assert tokens(query) == expected

    def test_underscores_are_kept(self) -> None:
        """A method name stays one token so ``query_funnel`` can match its trigger."""
        assert tokens("query_funnel") == ("query_funnel",)


class TestHintsFor:
    """``hints_for`` precedence and suppression."""

    def test_query_funnel_prefers_funnels_over_insights(self) -> None:
        """``Workspace.query_funnel`` picks the funnels page, not the generic query page."""
        hints = hints_for(tokens("Workspace.query_funnel"), kind="method")
        assert len(hints) == 1
        assert hints[0].url == hint_url("guide/query-funnels.md")

    def test_query_alone_picks_insights(self) -> None:
        """``Workspace.query`` picks the generic query guide."""
        (hint,) = hints_for(tokens("Workspace.query"), kind="method")
        assert hint.url == hint_url("guide/query.md")

    def test_workspace_alone_picks_api_page(self) -> None:
        """The bare ``Workspace`` query points at the hosted API reference (P17)."""
        title, path = WORKSPACE_HINT
        assert hints_for(("Workspace",), kind="listing") == (
            Hint(title, hint_url(path)),
        )

    def test_workspace_alone_is_case_insensitive(self) -> None:
        """``workspace`` resolves to the same API page hint."""
        assert hints_for(("workspace",), kind="listing") == hints_for(
            ("Workspace",), kind="listing"
        )

    @pytest.mark.parametrize("query", ["types", "exceptions"])
    def test_listings_get_no_hint(self, query: str) -> None:
        """``types`` and ``exceptions`` suppress hints (P17)."""
        assert hints_for(tokens(query), kind="listing") == ()

    def test_listing_kind_suppresses_even_with_triggers(self) -> None:
        """Any ``listing`` other than ``Workspace`` yields nothing, whatever the tokens."""
        assert hints_for(("Filter", "query_funnel"), kind="listing") == ()

    def test_create_dashboard_picks_entity_management(self) -> None:
        """Dashboard queries point at the entity-management guide (F8)."""
        (hint,) = hints_for(tokens("Workspace.create_dashboard"), kind="method")
        assert hint.url == hint_url("guide/entity-management.md")

    def test_replays_for_user_picks_session_replay(self) -> None:
        """Session-replay queries point at the session-replay guide (F9)."""
        (hint,) = hints_for(tokens("Workspace.replays_for_user"), kind="method")
        assert hint.url == hint_url("guide/session-replay.md")

    def test_login_unified_picks_auth(self) -> None:
        """Auth queries point at the auth API page (F9)."""
        (hint,) = hints_for(tokens("login_unified"), kind="function")
        assert hint.url == hint_url("api/auth.md")

    def test_no_trigger(self) -> None:
        """A query with no trigger token yields no hint."""
        assert hints_for(("nonesuch",), kind="class") == ()
        assert hints_for((), kind="class") == ()

    def test_whole_tokens_only(self) -> None:
        """``query_saved_report`` is not the ``query`` trigger (whole-token rule)."""
        hints = hints_for(("Workspace", "query_saved_report"), kind="method")
        assert hints != hints_for(("query",), kind="method")
        assert hints == () or hints[0].url != hint_url("guide/query.md")

    def test_case_insensitive_trigger(self) -> None:
        """``filter`` matches the ``Filter`` trigger."""
        assert hints_for(("filter",), kind="dataclass") == hints_for(
            ("Filter",), kind="dataclass"
        )
        assert hints_for(("Filter",), kind="dataclass") != ()

    def test_first_matching_rule_wins(self) -> None:
        """When tokens hit several rules, the earliest rule in the table wins."""
        tokens_hit_two = ("query_user", "query_funnel")
        (hint,) = hints_for(tokens_hit_two, kind="method")
        assert hint.url == hint_url("guide/query-users.md")

    def test_title_and_url_come_from_the_rule(self) -> None:
        """The hint carries the rule's title and the hosted URL of its path."""
        (hint,) = hints_for(("query_funnel",), kind="method")
        rule = next(rule for rule in REFERENCE_HINTS if "query_funnel" in rule[0])
        assert hint == Hint(rule[1], hint_url(rule[2]))

    def test_at_most_one_hint_for_every_rule_trigger(self) -> None:
        """Each trigger in the table yields exactly one hint under ``DOCS_BASE``."""
        for triggers, _title, _path in REFERENCE_HINTS:
            for trigger in triggers:
                hints = hints_for((trigger,), kind="method")
                assert len(hints) == 1
                assert hints[0].url.startswith(DOCS_BASE)
                assert hints[0].url.endswith("index.md")
