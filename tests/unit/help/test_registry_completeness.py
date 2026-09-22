"""Completeness guards for the built-in help registry.

These tests lock four invariants that keep ``mp.help()`` output current:

- ``mixpanel_headless.__all__`` has no duplicate names.
- Every export that has no docstring of its own (``Literal``, ``Union``,
  and ``Annotated`` aliases, module constants) has a one-line entry in
  ``ALIAS_DOCS``, and every key in that dict names such an export.
- Every public ``Workspace`` method appears in exactly one domain of
  ``WORKSPACE_DOMAINS`` and every registered name exists.
- Every ``REFERENCE_HINTS`` source path exists under ``docs/``.
"""

from __future__ import annotations

import inspect
import json
import re
import typing
from pathlib import Path

import pytest

import mixpanel_headless as mp
from mixpanel_headless._internal.help.inventory import (
    exports_of_kind,
    inventory,
    workspace_members,
)
from mixpanel_headless._internal.help.registry import (
    DOCS_BASE,
    REFERENCE_HINTS,
    WORKSPACE_DOMAINS,
    WORKSPACE_HINT,
    domain_of,
    hint_url,
)
from mixpanel_headless._internal.help.relations import referenced_types, used_by
from mixpanel_headless._literal_types import ALIAS_DOCS
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


def _exports_without_own_docstring() -> list[str]:
    """Return every export whose runtime object carries no docstring of its own.

    Classes, functions, and modules own their ``__doc__``. Any other export
    (a ``Literal`` / ``Union`` / ``Annotated`` alias or a module constant)
    either has ``__doc__ = None`` or inherits the docstring of its runtime
    type (``typing`` internals, ``int``), which the help must not show.
    Those exports read their summary from ``ALIAS_DOCS`` instead.

    Returns:
        Sorted list of export names.
    """
    names: list[str] = []
    for row in inventory():
        obj = row.obj
        if isinstance(obj, type) or inspect.ismodule(obj) or inspect.isroutine(obj):
            continue
        doc = getattr(obj, "__doc__", None)
        if doc is None or doc == type(obj).__doc__:
            names.append(row.name)
    return sorted(names)


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
    """``__all__`` carries each public name once."""

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


class TestAliasDocs:
    """``ALIAS_DOCS`` describes exactly the exports that have no docstring of their own."""

    def test_literal_probe_agrees_with_the_inventory(self) -> None:
        """The ``typing.Literal`` probe and the inventory's ``literal`` kind agree."""
        assert set(_exported_literal_aliases()) == {
            row.name for row in exports_of_kind("literal")
        }

    def test_every_exported_literal_alias_has_an_entry(self) -> None:
        """Each exported ``Literal`` alias has a key in ``ALIAS_DOCS``."""
        missing = [n for n in _exported_literal_aliases() if n not in ALIAS_DOCS]
        assert missing == []

    def test_every_export_without_a_docstring_has_an_entry(self) -> None:
        """Each export whose member summary would otherwise be blank has a key."""
        missing = [n for n in _exports_without_own_docstring() if n not in ALIAS_DOCS]
        assert missing == []

    def test_every_key_names_an_export_without_a_docstring(self) -> None:
        """No key describes a name that is not exported or that documents itself."""
        undocumented = set(_exports_without_own_docstring())
        extra = sorted(k for k in ALIAS_DOCS if k not in undocumented)
        assert extra == []

    @pytest.mark.parametrize("name", sorted(ALIAS_DOCS))
    def test_description_is_one_plain_sentence(self, name: str) -> None:
        """Each description is a single non-empty ASCII line that ends with a period."""
        text = ALIAS_DOCS[name]
        assert text.strip() == text
        assert text
        assert "\n" not in text
        assert text.endswith(".")
        assert text.isascii()

    @pytest.mark.parametrize("name", sorted(ALIAS_DOCS))
    def test_description_is_the_entry_summary(self, name: str) -> None:
        """``describe(name)`` carries the table text and every format shows it."""
        entry = mp.reference.describe(name, hints=False)
        assert entry.summary == ALIAS_DOCS[name]
        assert ALIAS_DOCS[name] in mp.reference.render(entry, "text")
        assert ALIAS_DOCS[name] in mp.reference.render(entry, "markdown")
        payload = json.loads(mp.reference.render(entry, "json"))
        assert payload["summary"] == ALIAS_DOCS[name]

    def test_known_descriptions_name_their_call_sites(self) -> None:
        """Spot-check that descriptions point at the places that accept the alias."""
        assert "Workspace.query" in ALIAS_DOCS["MathType"]
        assert "build_params" in ALIAS_DOCS["MathType"]
        assert "query_retention" in ALIAS_DOCS["RetentionAlignment"]
        assert "create_report_link" in ALIAS_DOCS["ReportLinkType"]
        assert "query_saved_report" in ALIAS_DOCS["ReportLinkType"]
        assert "did_event (aggregation)" in ALIAS_DOCS["CohortAggregationType"]
        assert "TypeAdapter" in ALIAS_DOCS["Account"]
        assert "query_report_link" in ALIAS_DOCS["ReportLinkQueryResult"]
        assert "set_business_context" in ALIAS_DOCS["BUSINESS_CONTEXT_MAX_CHARS"]

    def test_concept_texts_do_not_single_out_one_caller(self) -> None:
        """Aliases accepted by several methods describe the concept, not one caller.

        ``CountType`` and ``FlowChartType`` are each accepted by four
        ``Workspace`` methods; the live ``used_by`` block already lists them,
        so the sentence must not name a subset and go stale.
        """
        for name in ("CountType", "FlowChartType"):
            accepted = {usage.method for usage in used_by(name)}
            assert len(accepted) >= 4
            named = {method for method in accepted if method in ALIAS_DOCS[name]}
            assert named in (set(), accepted), (name, named)

    def test_named_workspace_methods_still_reference_the_alias(self) -> None:
        """Every ``snake_case`` ``Workspace`` method a type alias names still uses it.

        This is the drift guard: when a method stops accepting or returning
        an alias, the sentence that names it must change too. Constants are
        skipped because signatures never reference them.
        """
        methods = [name for name, kind in workspace_members() if kind == "method"]
        referencing = {
            method: {
                name for name, _summary in referenced_types(getattr(Workspace, method))
            }
            for method in methods
        }
        for kind in ("literal", "alias"):
            for row in exports_of_kind(kind):
                text = ALIAS_DOCS[row.name]
                named = {
                    token
                    for token in re.findall(r"\b[a-z]+(?:_[a-z0-9]+)+\b", text)
                    if token in referencing
                }
                stale = sorted(m for m in named if row.name not in referencing[m])
                assert stale == [], (row.name, stale)


class TestWorkspaceDomains:
    """``WORKSPACE_DOMAINS`` covers every public ``Workspace`` method once."""

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
        """The domain table groups ``Workspace`` methods into roughly 30 domains."""
        assert 28 <= len(WORKSPACE_DOMAINS) <= 36

    def test_expected_domain_titles_are_present(self) -> None:
        """The expected domain titles are all present."""
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
        """Known methods resolve to their expected domain title."""
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
    """``REFERENCE_HINTS`` is well formed and points at real docs pages."""

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
        """No hint points at the plugin's ``dashboard-expert`` files."""
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
        """The required docs pages each appear at least once."""
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
        """``query_funnel`` is triggered before the generic insights entry."""
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
