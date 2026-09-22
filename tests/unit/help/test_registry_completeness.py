"""Completeness guards for the built-in help registry (Plan 047, D3/D4/D5/D8).

These tests lock four invariants that keep ``mp.help()`` output current:

- ``mixpanel_headless.__all__`` has no duplicate names (F7).
- Every exported ``Literal`` alias has a one-line entry in
  ``LITERAL_ALIAS_DOCS`` and every key in that dict is exported (D4).
- Every public ``Workspace`` method appears in exactly one domain of
  ``WORKSPACE_DOMAINS`` and every registered name exists (D5).
- Every ``REFERENCE_HINTS`` source path exists under ``docs/`` (D8).
"""

from __future__ import annotations

import inspect
import typing
from pathlib import Path

import pytest

import mixpanel_headless as mp
from mixpanel_headless._internal.help.registry import (
    DOCS_BASE,
    REFERENCE_HINTS,
    WORKSPACE_DOMAINS,
    WORKSPACE_HINT,
    domain_of,
    hint_url,
)
from mixpanel_headless._literal_types import LITERAL_ALIAS_DOCS
from mixpanel_headless.workspace import Workspace

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_DIR = REPO_ROOT / "docs"


def _exported_literal_aliases() -> list[str]:
    """Return every ``__all__`` name whose runtime value is a ``typing.Literal``.

    Returns:
        Sorted list of export names.
    """
    return sorted(
        name
        for name in set(mp.__all__)
        if typing.get_origin(getattr(mp, name)) is typing.Literal
    )


def _public_workspace_methods() -> list[str]:
    """Return every public callable attribute of ``Workspace`` that is not a property.

    Returns:
        Sorted list of method names.
    """
    names: list[str] = []
    for name in dir(Workspace):
        if name.startswith("_"):
            continue
        static = inspect.getattr_static(Workspace, name)
        if isinstance(static, property):
            continue
        if callable(getattr(Workspace, name)):
            names.append(name)
    return sorted(names)


def _registered_methods() -> list[str]:
    """Return every method name listed in ``WORKSPACE_DOMAINS`` in registry order.

    Returns:
        List of method names, with duplicates preserved if any exist.
    """
    return [name for _title, names in WORKSPACE_DOMAINS for name in names]


class TestAllUniqueness:
    """``__all__`` carries each public name once (D3, F7)."""

    def test_all_has_no_duplicates(self) -> None:
        """``len(__all__)`` equals the size of its set."""
        duplicates = sorted(
            name for name in set(mp.__all__) if mp.__all__.count(name) > 1
        )
        assert duplicates == []
        assert len(mp.__all__) == len(set(mp.__all__))

    def test_every_all_name_resolves(self) -> None:
        """Every name in ``__all__`` is an attribute of the package."""
        missing = [name for name in mp.__all__ if not hasattr(mp, name)]
        assert missing == []

    def test_help_lookup_error_is_exported(self) -> None:
        """``HelpLookupError`` is listed in ``__all__``."""
        assert "HelpLookupError" in mp.__all__


class TestLiteralAliasDocs:
    """Every exported ``Literal`` alias is described in ``LITERAL_ALIAS_DOCS`` (D4)."""

    def test_probe_finds_the_expected_alias_count(self) -> None:
        """The package exports exactly 38 ``Literal`` aliases (plan §2.4)."""
        assert len(_exported_literal_aliases()) == 38

    def test_every_exported_literal_alias_has_an_entry(self) -> None:
        """Each exported ``Literal`` alias has a key in ``LITERAL_ALIAS_DOCS``."""
        missing = [
            n for n in _exported_literal_aliases() if n not in LITERAL_ALIAS_DOCS
        ]
        assert missing == []

    def test_every_key_is_an_exported_literal_alias(self) -> None:
        """Each key in ``LITERAL_ALIAS_DOCS`` names an exported ``Literal`` alias."""
        aliases = set(_exported_literal_aliases())
        extra = sorted(k for k in LITERAL_ALIAS_DOCS if k not in aliases)
        assert extra == []

    @pytest.mark.parametrize("name", sorted(LITERAL_ALIAS_DOCS))
    def test_description_is_one_plain_sentence(self, name: str) -> None:
        """Each description is a single non-empty line that ends with a period."""
        text = LITERAL_ALIAS_DOCS[name]
        assert text.strip() == text
        assert text
        assert "\n" not in text
        assert text.endswith(".")

    def test_known_descriptions_name_their_call_sites(self) -> None:
        """Spot-check that descriptions point at the methods that accept the alias."""
        assert "Workspace.query" in LITERAL_ALIAS_DOCS["MathType"]
        assert "build_params" in LITERAL_ALIAS_DOCS["MathType"]
        assert "query_retention" in LITERAL_ALIAS_DOCS["RetentionAlignment"]
        assert "create_report_link" in LITERAL_ALIAS_DOCS["ReportLinkType"]


class TestWorkspaceDomains:
    """``WORKSPACE_DOMAINS`` covers every public ``Workspace`` method once (D5)."""

    def test_every_public_method_is_registered_once(self) -> None:
        """Each public ``Workspace`` method appears in exactly one domain."""
        registered = _registered_methods()
        counts = {name: registered.count(name) for name in _public_workspace_methods()}
        unregistered = sorted(n for n, c in counts.items() if c == 0)
        duplicated = sorted(n for n, c in counts.items() if c > 1)
        assert unregistered == []
        assert duplicated == []

    def test_every_registered_name_is_a_public_method(self) -> None:
        """Each registered name exists on ``Workspace`` as a public non-property callable."""
        public = set(_public_workspace_methods())
        unknown = sorted(n for n in _registered_methods() if n not in public)
        assert unknown == []

    def test_registered_count_matches_method_count(self) -> None:
        """The registry lists the same number of names as ``Workspace`` has methods."""
        assert len(_registered_methods()) == len(_public_workspace_methods())

    def test_no_properties_are_registered(self) -> None:
        """Properties such as ``api`` and ``session`` are not domain members."""
        registered = set(_registered_methods())
        for prop in ("account", "api", "project", "session", "workspace"):
            assert prop not in registered

    def test_domain_titles_are_unique_lowercase_and_nonempty(self) -> None:
        """Domain titles are unique, lowercase phrases, and each domain has methods."""
        titles = [title for title, _names in WORKSPACE_DOMAINS]
        assert len(titles) == len(set(titles))
        for title, names in WORKSPACE_DOMAINS:
            assert title == title.lower()
            assert title.strip() == title
            assert title
            assert len(names) > 0

    def test_domain_count_is_about_thirty(self) -> None:
        """The 46 section comments collapse to roughly 30 domains (plan D5)."""
        assert 28 <= len(WORKSPACE_DOMAINS) <= 36

    def test_expected_domain_titles_are_present(self) -> None:
        """The titles named in plan D5 are all present."""
        titles = {title for title, _names in WORKSPACE_DOMAINS}
        expected = {
            "session and switching",
            "discovery",
            "lexicon schemas",
            "streaming",
            "legacy live queries",
            "insights query",
            "funnel query",
            "retention query",
            "flow query",
            "user query",
            "report links",
            "dashboards",
            "reports",
            "cohorts",
            "feature flags",
            "experiments",
            "annotations",
            "webhooks",
            "alerts",
            "lexicon governance",
            "drop filters",
            "custom properties",
            "custom events",
            "lookup tables",
            "tracking and history",
            "schema registry",
            "schema enforcement",
            "data audit",
            "volume anomalies",
            "deletion requests",
            "business context",
            "session replay",
        }
        assert expected <= titles

    def test_domains_are_tuples(self) -> None:
        """The registry is an immutable tuple of ``(title, tuple_of_names)`` pairs."""
        assert isinstance(WORKSPACE_DOMAINS, tuple)
        for entry in WORKSPACE_DOMAINS:
            assert isinstance(entry, tuple)
            title, names = entry
            assert isinstance(title, str)
            assert isinstance(names, tuple)


class TestDomainOf:
    """``domain_of`` maps a method name to its domain title."""

    @pytest.mark.parametrize(
        ("method", "expected"),
        [
            ("query", "insights query"),
            ("build_params", "insights query"),
            ("query_funnel", "funnel query"),
            ("query_retention", "retention query"),
            ("query_flow", "flow query"),
            ("query_user", "user query"),
            ("create_dashboard", "dashboards"),
            ("create_bookmark", "reports"),
            ("create_cohort", "cohorts"),
            ("use", "session and switching"),
            ("events", "discovery"),
            ("schema_graph", "lexicon schemas"),
            ("stream_events", "streaming"),
            ("segmentation", "legacy live queries"),
            ("create_report_link", "report links"),
            ("fetch_replay", "session replay"),
            ("set_business_context", "business context"),
            ("create_drop_filter", "drop filters"),
            ("upload_lookup_table", "lookup tables"),
            ("run_audit", "data audit"),
        ],
    )
    def test_known_methods(self, method: str, expected: str) -> None:
        """Known methods resolve to the plan D5 domain title."""
        assert domain_of(method) == expected

    def test_unknown_returns_none(self) -> None:
        """An unregistered name returns ``None``."""
        assert domain_of("no_such_method") is None

    def test_property_returns_none(self) -> None:
        """A ``Workspace`` property name returns ``None``."""
        assert domain_of("api") is None

    def test_private_returns_none(self) -> None:
        """A private helper name returns ``None``."""
        assert domain_of("_resolve_and_build_params") is None


class TestReferenceHints:
    """``REFERENCE_HINTS`` is well formed and points at real docs pages (D8)."""

    def test_shape(self) -> None:
        """Each entry is ``(triggers, title, path)`` with non-empty string members."""
        assert isinstance(REFERENCE_HINTS, tuple)
        for triggers, title, path in REFERENCE_HINTS:
            assert isinstance(triggers, tuple)
            assert len(triggers) > 0
            assert all(isinstance(t, str) and t for t in triggers)
            assert isinstance(title, str)
            assert title
            assert isinstance(path, str)
            assert path.endswith(".md")
            assert not path.startswith("/")
            assert not path.startswith("docs/")

    def test_triggers_have_no_duplicates_within_an_entry(self) -> None:
        """No trigger is repeated inside a single entry."""
        for triggers, _title, _path in REFERENCE_HINTS:
            assert len(triggers) == len(set(triggers))

    def test_paths_are_hosted_docs_not_plugin_local(self) -> None:
        """No hint points at the plugin's ``dashboard-expert`` files (F8)."""
        for _triggers, _title, path in REFERENCE_HINTS:
            assert "dashboard-expert" not in path
            assert "skills/" not in path

    @pytest.mark.parametrize(
        "needle",
        [
            "guide/session-replay.md",
            "guide/report-links.md",
            "guide/business-context.md",
            "guide/data-governance.md",
            "api/auth.md",
            "cli/commands.md",
            "guide/entity-management.md",
            "guide/discovery.md",
            "guide/query.md",
            "guide/query-funnels.md",
            "guide/query-retention.md",
            "guide/query-flows.md",
            "guide/query-users.md",
        ],
    )
    def test_required_pages_are_hinted(self, needle: str) -> None:
        """The plan's required pages (D8, F9) each appear at least once."""
        assert needle in {path for _t, _title, path in REFERENCE_HINTS}

    def test_dashboard_methods_point_at_entity_management(self) -> None:
        """The first entry that triggers on ``create_dashboard`` is entity management."""
        for triggers, _title, path in REFERENCE_HINTS:
            if "create_dashboard" in triggers:
                assert path == "guide/entity-management.md"
                break
        else:  # pragma: no cover - defensive
            pytest.fail("no hint triggers on create_dashboard")

    def test_funnel_entry_precedes_insights_entry(self) -> None:
        """``query_funnel`` is triggered before the generic insights entry (P17)."""
        paths = [path for _t, _title, path in REFERENCE_HINTS]
        assert paths.index("guide/query-funnels.md") < paths.index("guide/query.md")

    @pytest.mark.skipif(not DOCS_DIR.is_dir(), reason="docs/ not present")
    @pytest.mark.parametrize(
        "path",
        sorted({path for _t, _title, path in REFERENCE_HINTS} | {WORKSPACE_HINT[1]}),
    )
    def test_every_hint_path_exists_under_docs(self, path: str) -> None:
        """Every hint source path resolves to a file under ``docs/``."""
        assert (DOCS_DIR / path).is_file(), path

    def test_workspace_hint_points_at_api_page(self) -> None:
        """The bare ``Workspace`` query hint targets the hosted API reference page."""
        title, path = WORKSPACE_HINT
        assert title
        assert path == "api/workspace.md"


class TestHintUrl:
    """``hint_url`` maps a docs source path to its hosted ``index.md`` URL."""

    def test_docs_base_is_hosted_site_with_trailing_slash(self) -> None:
        """``DOCS_BASE`` is the GitHub Pages site root."""
        assert DOCS_BASE == "https://mixpanel.github.io/mixpanel-headless/"

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            (
                "guide/query.md",
                "https://mixpanel.github.io/mixpanel-headless/guide/query/index.md",
            ),
            (
                "guide/entity-management.md",
                "https://mixpanel.github.io/mixpanel-headless/"
                "guide/entity-management/index.md",
            ),
            (
                "api/workspace.md",
                "https://mixpanel.github.io/mixpanel-headless/api/workspace/index.md",
            ),
            (
                "api/index.md",
                "https://mixpanel.github.io/mixpanel-headless/api/index.md",
            ),
            (
                "index.md",
                "https://mixpanel.github.io/mixpanel-headless/index.md",
            ),
            (
                "cli/commands.md",
                "https://mixpanel.github.io/mixpanel-headless/cli/commands/index.md",
            ),
        ],
    )
    def test_directory_urls(self, path: str, expected: str) -> None:
        """A page ``x.md`` is served at ``x/index.md``; an ``index.md`` stays put."""
        assert hint_url(path) == expected

    def test_leading_slash_and_docs_prefix_are_tolerated(self) -> None:
        """Leading ``/`` and a ``docs/`` prefix produce the same URL as the bare path."""
        bare = hint_url("guide/query.md")
        assert hint_url("/guide/query.md") == bare
        assert hint_url("docs/guide/query.md") == bare

    def test_every_hint_url_is_under_docs_base(self) -> None:
        """Every registered hint renders to a URL under ``DOCS_BASE``."""
        for _t, _title, path in REFERENCE_HINTS:
            url = hint_url(path)
            assert url.startswith(DOCS_BASE)
            assert url.endswith("index.md")
            assert "//" not in url[len("https://") :]
