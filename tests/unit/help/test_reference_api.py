"""Unit tests for ``mixpanel_headless.reference``.

The public module assembles one ``HelpEntry`` per ``HelpKind`` from the
private ``_internal/help`` building blocks and prints it through ``help()``.
These tests lock, with real library objects:

- one structural ``describe()`` test per query-grammar form (counts and
  shapes, never prose, so docstring edits elsewhere do not break them);
- ``help()`` routing (overview / ``search <term>`` / describe), the ``file``
  and ``format`` arguments, the miss path (``Did you mean?`` plus search
  hits, never an exception), and the usage text for a bare ``search``;
- ``domain=`` filtering for ``Workspace`` and its error cases;
- the isolation guarantee (no file is created under an empty ``HOME``);
- ``clear_cache()`` fan-out to every internal cache;
- a guard: every inventory name and every ``Workspace`` member describes and
  renders in all three formats without raising.
"""

from __future__ import annotations

import dataclasses
import io
import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

import mixpanel_headless as mp
from mixpanel_headless import HelpLookupError
from mixpanel_headless import reference as ref
from mixpanel_headless._internal.help import introspect as introspect_module
from mixpanel_headless._internal.help import inventory as inventory_module
from mixpanel_headless._internal.help import relations as relations_module
from mixpanel_headless._internal.help import search as search_module
from mixpanel_headless._internal.help.models import (
    HELP_FORMATS,
    HELP_KINDS,
    MemberDoc,
)
from mixpanel_headless._internal.help.registry import WORKSPACE_DOMAINS
from mixpanel_headless._internal.help.relations import exception_tree, raised_by
from mixpanel_headless._literal_types import ALIAS_DOCS
from mixpanel_headless.exceptions import HelpDomainError
from mixpanel_headless.workspace import Workspace

DOMAIN_TITLES = tuple(title for title, _ in WORKSPACE_DOMAINS)
"""Every registered ``Workspace`` domain title, in registry order."""

TYPE_KINDS = frozenset({"model", "dataclass", "enum", "literal", "alias", "class"})
"""Inventory kinds that the ``types`` listing shows."""

RESULT_TYPES = (
    "HelpEntry",
    "SearchResult",
    "SearchHit",
    "ParamDoc",
    "SignatureDoc",
    "FieldDoc",
    "MemberDoc",
    "Group",
    "DocSections",
    "UsageDoc",
    "Hint",
)
"""The help result types exported from the package root as well as ``reference``."""


# =============================================================================
# Fixtures and helpers
# =============================================================================


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    """Clear every help cache before and after each test.

    Yields:
        Nothing; the fixture only brackets the test with ``clear_cache()``.
    """
    ref.clear_cache()
    yield
    ref.clear_cache()


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``HOME`` and ``MP_CONFIG_PATH`` at an empty directory with no ``MP_*`` vars.

    Args:
        tmp_path: Pytest temporary directory.
        monkeypatch: Pytest monkeypatch fixture.

    Returns:
        The empty directory that must stay empty.
    """
    for key in list(os.environ):
        if key.startswith("MP_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MP_CONFIG_PATH", str(tmp_path / "config.toml"))
    return tmp_path


def _capture(*args: object, **kwargs: object) -> str:
    """Run ``ref.help`` with a string buffer as ``file`` and return the text.

    Args:
        *args: Positional arguments forwarded to ``ref.help``.
        **kwargs: Keyword arguments forwarded to ``ref.help``.

    Returns:
        Everything ``help()`` printed.
    """
    buffer = io.StringIO()
    ref.help(*args, file=buffer, **kwargs)  # type: ignore[arg-type]
    return buffer.getvalue()


def _group_titles(entry: ref.HelpEntry) -> list[str]:
    """Return the group titles of an entry in order.

    Args:
        entry: The entry.

    Returns:
        The titles.
    """
    return [group.title for group in entry.groups]


# =============================================================================
# Module surface
# =============================================================================


class TestModuleSurface:
    """``reference`` exports the public API and the result types."""

    def test_help_is_exported_and_identical(self) -> None:
        """``mp.help`` is the same object as ``reference.help``."""
        assert mp.help is ref.help
        assert "help" in mp.__all__
        assert "reference" in mp.__all__
        assert mp.reference is ref

    @pytest.mark.parametrize(
        "name",
        [
            "help",
            "describe",
            "search",
            "render",
            "clear_cache",
            "HelpEntry",
            "SearchResult",
            "SearchHit",
            "Group",
            "MemberDoc",
            "SignatureDoc",
            "ParamDoc",
            "FieldDoc",
            "UsageDoc",
            "Hint",
            "DocSections",
            "HelpKind",
            "HelpFormat",
            "HelpLookupError",
        ],
    )
    def test_all_lists_public_names(self, name: str) -> None:
        """Every public name is in ``reference.__all__`` and importable.

        Args:
            name: The public name.
        """
        assert name in ref.__all__
        assert hasattr(ref, name)

    def test_all_has_no_duplicates(self) -> None:
        """``reference.__all__`` has no duplicate entries."""
        assert len(ref.__all__) == len(set(ref.__all__))

    def test_search_is_the_internal_search(self) -> None:
        """``reference.search`` returns the same result as the internal search."""
        assert ref.search("cohort").hits == search_module.search("cohort").hits
        assert len(ref.search("cohort", limit=2).hits) == 2

    @pytest.mark.parametrize("name", RESULT_TYPES)
    def test_result_types_are_exported_from_the_package_root(self, name: str) -> None:
        """Each result type is the same object at ``mp.<name>`` and ``reference.<name>``.

        Args:
            name: A help result type name.
        """
        assert getattr(mp, name) is getattr(ref, name)
        assert name in mp.__all__

    @pytest.mark.parametrize("name", RESULT_TYPES)
    def test_result_types_describe_themselves(self, name: str) -> None:
        """The help system can describe its own result types.

        Args:
            name: A help result type name.
        """
        entry = ref.describe(name)
        assert entry.kind == "dataclass"
        assert entry.name == name
        assert entry.summary
        assert entry.hints

    def test_assembler_covers_every_help_kind(self) -> None:
        """Every ``HelpKind`` is a synthetic kind or has a builder in the assembler table."""
        assert set(ref._ENTRY_BUILDERS) | {"overview", "listing"} == set(HELP_KINDS)

    def test_render_rejects_unknown_format(self) -> None:
        """``render`` raises ``ValueError`` for an unknown format."""
        entry = ref.describe("MathType")
        with pytest.raises(ValueError, match="format"):
            ref.render(entry, "yaml")  # type: ignore[arg-type]


# =============================================================================
# describe(): one test per query-grammar form
# =============================================================================


class TestOverview:
    """``None`` / ``""`` → ``overview``."""

    @pytest.mark.parametrize("query", [None, "", "   "])
    def test_overview_kind(self, query: str | None) -> None:
        """Blank queries resolve to the overview entry.

        Args:
            query: The blank query form.
        """
        entry = ref.describe(query)
        assert entry.kind == "overview"
        assert entry.name == "mixpanel_headless"
        assert entry.summary == mp.__version__

    def test_overview_body_and_length(self) -> None:
        """The overview names the entry points and stays under 60 lines."""
        entry = ref.describe(None)
        text = ref.render(entry, "text")
        lines = text.splitlines()
        assert len(lines) < 60
        assert mp.__version__ in text
        assert "llms.txt" in text
        assert "import mixpanel_headless as mp" in text
        for token in ("mp.help(", "describe(", "search(", "render(", "mp help"):
            assert token in text
        assert "python3 -m mixpanel_headless help" in text
        for title in DOMAIN_TITLES:
            assert title in text
        assert entry.groups == ()


class TestWorkspaceListing:
    """``Workspace`` → ``listing`` grouped by domain, properties first."""

    def test_groups_and_counts(self) -> None:
        """Properties come first, then every domain; one item per ``Workspace`` member."""
        members = inventory_module.workspace_members()
        entry = ref.describe("Workspace")
        assert entry.kind == "listing"
        assert entry.name == "Workspace"
        titles = _group_titles(entry)
        assert titles[0] == "properties"
        assert tuple(titles[1:]) == DOMAIN_TITLES
        assert len(titles) == len(DOMAIN_TITLES) + 1
        assert sum(len(group.items) for group in entry.groups) == len(members)
        assert all(item.kind == "property" for item in entry.groups[0].items)
        assert [item.name for item in entry.groups[0].items] == [
            name for name, kind in members if kind == "property"
        ]
        methods = [item for group in entry.groups[1:] for item in group.items]
        assert all(item.kind == "method" for item in methods)
        assert all(item.signature is not None for item in methods)
        assert len(entry.hints) == 1
        assert "api/workspace" in entry.hints[0].url

    def test_object_forms(self) -> None:
        """The class object resolves to the same listing as the string."""
        assert ref.describe(Workspace).kind == "listing"
        assert _group_titles(ref.describe(Workspace)) == _group_titles(
            ref.describe("Workspace")
        )

    def test_domain_exact(self) -> None:
        """``domain="funnel query"`` keeps one group with three items."""
        entry = ref.describe("Workspace", domain="funnel query")
        assert _group_titles(entry) == ["funnel query"]
        assert len(entry.groups[0].items) == 3

    @pytest.mark.parametrize("domain", ["FUNNEL", "Funnel Q", "funnel query"])
    def test_domain_case_insensitive_prefix(self, domain: str) -> None:
        """A unique prefix in any case selects the domain.

        Args:
            domain: The user-typed domain.
        """
        entry = ref.describe("Workspace", domain=domain)
        assert _group_titles(entry) == ["funnel query"]

    def test_unknown_domain_raises_with_titles(self) -> None:
        """An unknown domain raises ``HelpDomainError`` carrying every title."""
        with pytest.raises(HelpDomainError) as info:
            ref.describe("Workspace", domain="nonesuch")
        error = info.value
        assert error.reason == "unknown"
        assert error.query == "Workspace"
        assert error.domain == "nonesuch"
        assert error.domains == DOMAIN_TITLES
        assert str(error) == "Unknown domain 'nonesuch'."

    def test_ambiguous_domain_raises_with_candidates(self) -> None:
        """A prefix shared by several domains raises and lists only them."""
        with pytest.raises(HelpDomainError) as info:
            ref.describe("Workspace", domain="s")
        error = info.value
        assert error.reason == "ambiguous"
        assert error.domain == "s"
        assert len(error.domains) > 1
        assert error.domains == tuple(t for t in DOMAIN_TITLES if t.startswith("s"))
        assert str(error).startswith("Ambiguous domain 's': ")

    def test_domain_on_non_workspace_raises(self) -> None:
        """``domain=`` with any other query is a domain error naming the query."""
        with pytest.raises(HelpDomainError) as info:
            ref.describe("Filter", domain="funnel query")
        error = info.value
        assert error.reason == "not_workspace"
        assert error.query == "Filter"
        assert error.domain == "funnel query"
        assert error.domains == ()
        assert str(error) == (
            "--domain applies only to the Workspace listing; "
            "'Filter' is not the Workspace class."
        )
        with pytest.raises(HelpDomainError):
            ref.describe("Workspace.query", domain="insights query")

    def test_domain_on_non_workspace_object_uses_qualname(self) -> None:
        """An object query reports its canonical name as ``query``."""
        with pytest.raises(HelpDomainError) as info:
            ref.describe(mp.Filter, domain="dashboards")
        assert info.value.query == "Filter"

    def test_miss_with_domain_is_a_plain_lookup_error(self) -> None:
        """A name miss stays a miss even when ``domain=`` is set."""
        with pytest.raises(HelpLookupError) as info:
            ref.describe("Filtr", domain="dashboards")
        assert not isinstance(info.value, HelpDomainError)
        assert info.value.query == "Filtr"
        assert "Filter" in info.value.suggestions


class TestMethod:
    """``Workspace.<method>`` → ``method``."""

    def test_workspace_query(self) -> None:
        """``Workspace.query`` carries signature, references, see also, hint."""
        entry = ref.describe("Workspace.query")
        assert entry.kind == "method"
        assert entry.name == "Workspace.query"
        assert entry.qualname == "Workspace.query"
        assert entry.signature is not None
        assert entry.signature.params[0].name == "events"
        assert entry.referenced_types
        assert entry.domain == "insights query"
        assert entry.groups == ()
        assert entry.see_also
        assert "query" not in entry.see_also
        assert len(entry.hints) == 1
        assert entry.doc.summary

    def test_object_form(self) -> None:
        """The unbound function resolves to the same entry."""
        assert ref.describe(Workspace.query) == ref.describe("Workspace.query")

    def test_non_workspace_class_member(self) -> None:
        """``Filter.equals`` is a method with no see-also domain."""
        entry = ref.describe("Filter.equals")
        assert entry.kind == "method"
        assert entry.name == "Filter.equals"
        assert entry.domain is None
        assert entry.groups == ()
        assert entry.see_also == ()
        assert entry.signature is not None
        assert entry.signature.params[0].name == "property"


class TestProperty:
    """``Workspace.<property>`` → ``property``."""

    def test_account(self) -> None:
        """``Workspace.account`` reports its return annotation."""
        entry = ref.describe("Workspace.account")
        assert entry.kind == "property"
        assert entry.name == "Workspace.account"
        assert entry.signature is not None
        assert entry.signature.params == ()
        assert entry.signature.returns
        assert entry.doc.summary


class TestParameter:
    """``Workspace.<method>.<param>`` → ``parameter``."""

    def test_query_events(self) -> None:
        """``Workspace.query.events`` isolates one ``ParamDoc``."""
        entry = ref.describe("Workspace.query.events")
        assert entry.kind == "parameter"
        assert entry.name == "Workspace.query.events"
        assert entry.signature is not None
        assert len(entry.signature.params) == 1
        assert entry.signature.params[0].name == "events"
        assert entry.signature.name == "query"
        assert entry.doc.summary == entry.signature.params[0].description

    def test_literal_parameter_values(self) -> None:
        """``Workspace.query.math`` exposes the 22 ``MathType`` values."""
        entry = ref.describe("Workspace.query.math")
        assert len(entry.values) == 22
        assert entry.values == entry.signature.params[0].values  # type: ignore[union-attr]


class TestClasses:
    """``<Dataclass>`` / ``<Model>`` / ``<Class>`` views."""

    def test_filter_dataclass(self) -> None:
        """``Filter`` has 28 constructors, no public fields, 10 usages."""
        entry = ref.describe("Filter")
        assert entry.kind == "dataclass"
        assert len(entry.construction) == 28
        assert entry.fields == ()
        assert entry.methods == ()
        assert len(entry.used_by) == 10
        assert entry.see_also == ()
        assert entry.hints

    def test_filter_object_form(self) -> None:
        """``describe(mp.Filter)`` equals ``describe("Filter")``."""
        assert ref.describe(mp.Filter) == ref.describe("Filter")

    def test_create_dashboard_params_model(self) -> None:
        """``CreateDashboardParams`` lists its fields and config pairs."""
        entry = ref.describe("CreateDashboardParams")
        assert entry.kind == "model"
        assert len(entry.fields) == 9
        assert isinstance(entry.config, tuple)
        assert all(len(pair) == 2 for pair in entry.config)
        names = [field.name for field in entry.fields]
        assert len(names) == len(set(names))
        assert len(entry.used_by) == 1

    def test_plain_class(self) -> None:
        """``QueryMeta`` is a plain ``class`` entry with no fields."""
        entry = ref.describe("QueryMeta")
        assert entry.kind == "class"
        assert entry.fields == ()


class TestEnumsAndLiterals:
    """``<Enum>``, ``<LiteralAlias>``, ``<Enum>.<member>``."""

    def test_math_type_literal(self) -> None:
        """``MathType`` has 22 values, the docs summary, and two usages."""
        entry = ref.describe("MathType")
        assert entry.kind == "literal"
        assert len(entry.values) == 22
        assert entry.summary == ALIAS_DOCS["MathType"]
        assert [usage.method for usage in entry.used_by] == ["build_params", "query"]

    def test_feature_flag_status_enum(self) -> None:
        """``FeatureFlagStatus`` lists members as fields and names as values."""
        entry = ref.describe("FeatureFlagStatus")
        assert entry.kind == "enum"
        assert entry.values == ("ENABLED", "DISABLED", "ARCHIVED")
        assert [field.name for field in entry.fields] == list(entry.values)
        assert entry.fields[0].default == "'enabled'"
        assert entry.fields[0].annotation == "str"

    def test_enum_member_constant(self) -> None:
        """``FeatureFlagStatus.ENABLED`` is a constant typed by its enum."""
        entry = ref.describe("FeatureFlagStatus.ENABLED")
        assert entry.kind == "constant"
        assert entry.name == "FeatureFlagStatus.ENABLED"
        assert entry.bases == ("FeatureFlagStatus",)
        assert entry.value == "'enabled'"
        assert entry.values == ()
        assert entry.summary == ref.describe("FeatureFlagStatus").summary

    def test_enum_member_object_form(self) -> None:
        """An enum member object resolves to its enum class, like any other instance."""
        assert ref.describe(mp.FeatureFlagStatus.ENABLED) == ref.describe(
            "FeatureFlagStatus"
        )


class TestAliasExceptionModuleConstant:
    """``alias``, ``exception``, ``module``, ``constant`` rows."""

    def test_account_alias(self) -> None:
        """``Account`` expands to its three member types."""
        entry = ref.describe("Account")
        assert entry.kind == "alias"
        assert entry.values == (
            "ServiceAccount",
            "OAuthBrowserAccount",
            "OAuthTokenAccount",
        )
        assert [name for name, _ in entry.referenced_types] == list(entry.values)
        assert all(summary for _, summary in entry.referenced_types)

    def test_api_error_exception(self) -> None:
        """``APIError`` shows its base and a non-empty subclass tree."""
        entry = ref.describe("APIError")
        assert entry.kind == "exception"
        assert entry.bases == ("MixpanelHeadlessError",)
        assert _group_titles(entry) == ["Subclasses"]
        items = entry.groups[0].items
        assert items
        assert [(item.name, item.depth) for item in items] == [
            (name, depth - 1) for name, depth in exception_tree(mp.APIError)[1:]
        ]
        assert not any(item.name.startswith(" ") for item in items)
        assert {item.depth for item in items} == {0, 1}

    def test_workspace_scope_error_raised_by(self) -> None:
        """``WorkspaceScopeError.used_by`` is the ``Raises:`` index."""
        entry = ref.describe("WorkspaceScopeError")
        assert entry.used_by == raised_by("WorkspaceScopeError")
        assert len(entry.used_by) == 4

    def test_accounts_module(self) -> None:
        """``accounts`` lists its 13 ``__all__`` members with signatures."""
        entry = ref.describe("accounts")
        assert entry.kind == "module"
        assert _group_titles(entry) == ["Members"]
        items = entry.groups[0].items
        assert len(items) == 13
        assert all(item.signature is not None for item in items)
        assert all(item.kind == "function" for item in items)

    def test_module_object_form(self) -> None:
        """``describe(mp.accounts)`` equals ``describe("accounts")``."""
        assert ref.describe(mp.accounts) == ref.describe("accounts")

    def test_module_member_function(self) -> None:
        """``accounts.add`` is a function entry."""
        entry = ref.describe("accounts.add")
        assert entry.kind == "function"
        assert entry.name == "accounts.add"
        assert entry.signature is not None

    def test_constant(self) -> None:
        """``BUSINESS_CONTEXT_MAX_CHARS`` shows type and value."""
        entry = ref.describe("BUSINESS_CONTEXT_MAX_CHARS")
        assert entry.kind == "constant"
        assert entry.bases == ("int",)
        assert entry.value == repr(mp.BUSINESS_CONTEXT_MAX_CHARS)
        assert entry.values == ()


class TestListings:
    """``types`` and ``exceptions`` listings."""

    def test_types_listing(self) -> None:
        """``types`` has six groups and covers every type-like export."""
        entry = ref.describe("types")
        assert entry.kind == "listing"
        assert _group_titles(entry) == [
            "models",
            "dataclasses",
            "enums",
            "literal aliases",
            "other aliases",
            "protocols and plain classes",
        ]
        expected = sum(
            1
            for row in inventory_module.inventory()
            if row.kind in TYPE_KINDS and row.name != "Workspace"
        )
        assert sum(len(group.items) for group in entry.groups) == expected
        assert not any(
            item.name == "Workspace" for group in entry.groups for item in group.items
        )
        assert entry.hints == ()
        assert all(item.summary for group in entry.groups for item in group.items)
        for group in (entry.groups[3], entry.groups[4]):
            assert group.items
            assert all(item.summary == ALIAS_DOCS[item.name] for item in group.items)

    def test_types_listing_hints_stay_empty(self) -> None:
        """``hints=True`` still yields no hint for ``types``."""
        assert ref.describe("types", hints=True).hints == ()

    def test_exceptions_listing(self) -> None:
        """``exceptions`` lists every exported exception as an indented tree with no hints."""
        entry = ref.describe("exceptions")
        assert entry.kind == "listing"
        assert _group_titles(entry) == ["Exceptions"]
        items = entry.groups[0].items
        assert [(item.name, item.depth) for item in items] == list(exception_tree())
        assert items[0] == MemberDoc(
            "MixpanelHeadlessError", "exception", items[0].summary, depth=0
        )
        assert items[1].name == "APIError"
        assert items[1].depth == 1
        assert max(item.depth for item in items) >= 3
        assert entry.hints == ()

    def test_exceptions_listing_json_depth_matches_the_class_hierarchy(self) -> None:
        """Every JSON item has a bare name and a ``depth`` equal to its distance from the root."""
        payload = ref.describe("exceptions").to_dict()
        groups = payload["groups"]
        assert isinstance(groups, list)
        items = groups[0]["items"]
        assert items
        for item in items:
            name = item["name"]
            assert name == name.strip()
            cls = getattr(mp, name)
            lineage = [
                base
                for base in cls.__mro__
                if issubclass(base, mp.MixpanelHeadlessError)
            ]
            assert item["depth"] == len(lineage) - 1, name


def _dig(payload: object, path: str) -> object:
    """Follow a dotted path of dict keys and list indexes into a JSON payload.

    Args:
        payload: A ``to_dict()`` result or any nested part of one.
        path: Dotted path such as ``"signature.params.0.name"``.

    Returns:
        The value at the path.

    Raises:
        TypeError: When the path descends into a scalar.
    """
    node: object = payload
    for part in path.split("."):
        if isinstance(node, list):
            node = node[int(part)]
        elif isinstance(node, dict):
            node = node[part]
        else:
            raise TypeError(f"cannot descend into {node!r} at {part!r} of {path!r}")
    return node


_ALWAYS_POPULATED = frozenset({"kind", "name", "qualname", "summary"})
"""Top-level keys every entry populates."""

JSON_CONVENTIONS: dict[str, tuple[str | None, frozenset[str], dict[str, object]]] = {
    "overview": (None, frozenset(), {"name": "mixpanel_headless", "groups": []}),
    "listing": (
        "exceptions",
        frozenset({"groups"}),
        {
            "groups.0.title": "Exceptions",
            "groups.0.items.0.name": "MixpanelHeadlessError",
            "groups.0.items.0.depth": 0,
            "groups.0.items.0.kind": "exception",
            "groups.0.items.1.depth": 1,
            "hints": [],
        },
    ),
    "class": ("QueryMeta", frozenset({"bases", "hints"}), {"bases": ["dict"]}),
    "model": (
        "CreateDashboardParams",
        frozenset({"fields", "used_by", "hints"}),
        {
            "fields.0.name": "title",
            "fields.0.required": True,
            "fields.0.default": None,
            "used_by.0.method": "create_dashboard",
            "used_by.0.params": ["params"],
        },
    ),
    "dataclass": (
        "Filter",
        frozenset({"construction", "used_by", "hints"}),
        {"construction.0.kind": "method", "fields": []},
    ),
    "enum": (
        "FeatureFlagStatus",
        frozenset({"bases", "fields", "values", "hints"}),
        {
            "bases": ["str", "Enum"],
            "values": ["ENABLED", "DISABLED", "ARCHIVED"],
            "fields.0.name": "ENABLED",
            "fields.0.annotation": "str",
            "fields.0.default": "'enabled'",
            "fields.0.required": False,
        },
    ),
    "literal": (
        "Region",
        frozenset({"values", "hints"}),
        {"values": ["us", "eu", "in"]},
    ),
    "alias": (
        "Account",
        frozenset({"values", "referenced_types", "hints"}),
        {
            "values": ["ServiceAccount", "OAuthBrowserAccount", "OAuthTokenAccount"],
            "referenced_types.0.0": "ServiceAccount",
        },
    ),
    "exception": (
        "AccountExistsError",
        frozenset({"bases", "hints"}),
        {"bases": ["ConfigError"], "groups": [], "used_by": []},
    ),
    "function": (
        "accounts.add",
        frozenset({"signature", "referenced_types", "hints"}),
        {
            "signature.name": "add",
            "signature.params.0.name": "name",
            "signature.returns": "AccountSummary",
            "domain": None,
            "see_also": [],
        },
    ),
    "method": (
        "Workspace.create_dashboard",
        frozenset({"signature", "referenced_types", "see_also", "domain", "hints"}),
        {
            "signature.name": "create_dashboard",
            "signature.params.0.name": "params",
            "domain": "dashboards",
            "groups": [],
            "see_also.0": "add_report_to_dashboard",
        },
    ),
    "property": (
        "Workspace.account",
        frozenset({"signature", "hints"}),
        {"signature.name": "account", "signature.params": []},
    ),
    "parameter": (
        "Workspace.query.math",
        frozenset({"signature", "values", "hints"}),
        {
            "signature.name": "query",
            "signature.params.0.name": "math",
            "signature.params.0.default": "'total'",
            "values.0": "total",
        },
    ),
    "module": (
        "session",
        frozenset({"groups", "hints"}),
        {"groups.0.title": "Members", "groups.0.items.0.kind": "function"},
    ),
    "constant": (
        "FeatureFlagStatus.ENABLED",
        frozenset({"bases", "value", "hints"}),
        {"bases": ["FeatureFlagStatus"], "value": "'enabled'", "values": []},
    ),
}
"""Per-kind JSON packing contract: ``(query, populated keys, dotted-path expectations)``.

``populated keys`` are the top-level keys (besides the four every entry
fills and ``doc``) that hold a non-empty value for the sample entry; the
dotted paths pin where each kind stores its kind-specific data. A port
that reads ``describe(...).to_dict()`` can rely on this table.
"""


class TestJsonConventions:
    """One ``to_dict()`` golden per ``HelpKind`` pins the per-kind packing conventions."""

    def test_table_covers_every_kind(self) -> None:
        """The convention table names every ``HelpKind`` exactly once."""
        assert set(JSON_CONVENTIONS) == set(HELP_KINDS)

    @pytest.mark.parametrize("kind", sorted(JSON_CONVENTIONS))
    def test_kind_packs_its_fields_as_documented(self, kind: str) -> None:
        """The sample entry of each kind populates exactly the documented keys.

        Args:
            kind: The ``HelpKind`` under test.
        """
        query, populated, expectations = JSON_CONVENTIONS[kind]
        payload = ref.describe(query).to_dict()
        assert payload["kind"] == kind
        assert list(payload) == [f.name for f in dataclasses.fields(ref.HelpEntry)]
        actual = {
            key
            for key, value in payload.items()
            if key != "doc" and value not in ([], None, "", {})
        }
        assert actual == _ALWAYS_POPULATED | populated
        for path, expected in expectations.items():
            assert _dig(payload, path) == expected, path

    def test_overview_summary_is_the_package_version(self) -> None:
        """The overview packs the installed version in ``summary``."""
        assert ref.describe(None).to_dict()["summary"] == mp.__version__

    def test_parameter_values_mirror_the_param_doc(self) -> None:
        """A ``parameter`` entry repeats ``signature.params[0].values`` in ``values``."""
        payload = ref.describe("Workspace.query.math").to_dict()
        assert payload["values"] == _dig(payload, "signature.params.0.values")
        assert len(payload["values"]) == 22  # type: ignore[arg-type]

    def test_plain_constant_packs_type_and_repr(self) -> None:
        """A module-level constant stores its type name in ``bases`` and ``repr`` in ``value``."""
        payload = ref.describe("BUSINESS_CONTEXT_MAX_CHARS").to_dict()
        assert payload["bases"] == ["int"]
        assert payload["value"] == repr(mp.BUSINESS_CONTEXT_MAX_CHARS)
        assert payload["values"] == []
        assert payload["domain"] is None

    def test_enum_members_are_field_docs(self) -> None:
        """Enum members reuse ``FieldDoc``: name, value-type annotation, ``repr`` default."""
        payload = ref.describe("FeatureFlagStatus").to_dict()
        fields = payload["fields"]
        assert isinstance(fields, list)
        assert [f["name"] for f in fields] == payload["values"]
        assert all(f["required"] is False for f in fields)
        assert all(
            f["default"] == repr(mp.FeatureFlagStatus[f["name"]].value) for f in fields
        )


class TestHelpFunctionEntry:
    """``help`` → ``function``; the function documents itself."""

    def test_help_entry(self) -> None:
        """``describe("help")`` is a function whose docstring holds the grammar table."""
        entry = ref.describe("help")
        assert entry.kind == "function"
        assert entry.name == "help"
        assert entry.signature is not None
        assert [param.name for param in entry.signature.params] == [
            "query",
            "format",
            "file",
            "hints",
            "domain",
        ]
        assert "| Query | Result kind |" in entry.doc.body
        assert "search <term>" in entry.doc.body

    def test_help_object_form(self) -> None:
        """``describe(mp.help)`` equals ``describe("help")``."""
        assert ref.describe(mp.help) == ref.describe("help")


class TestHintsFlag:
    """``hints=False`` empties the hint tuple on every kind."""

    @pytest.mark.parametrize(
        "query",
        ["Workspace", "Workspace.query", "Filter", "MathType", "APIError", "accounts"],
    )
    def test_hints_false(self, query: str) -> None:
        """No hint survives ``hints=False``.

        Args:
            query: A query that normally carries a hint.
        """
        assert ref.describe(query, hints=False).hints == ()

    def test_hints_true_by_default(self) -> None:
        """The default keeps the hint."""
        assert ref.describe("Workspace.query").hints


class TestDescribeMiss:
    """A miss raises ``HelpLookupError`` with suggestions and search hits."""

    def test_miss_carries_hits(self) -> None:
        """The error carries suggestions and up to five search hits."""
        with pytest.raises(HelpLookupError) as info:
            ref.describe("Cohor")
        error = info.value
        assert error.query == "Cohor"
        assert "Cohort" in error.suggestions
        assert 0 < len(error.hits) <= 5
        assert all(isinstance(hit, ref.SearchHit) for hit in error.hits)

    def test_total_miss_has_no_hits(self) -> None:
        """A query that matches nothing at all has empty hits."""
        with pytest.raises(HelpLookupError) as info:
            ref.describe("zzqqxxyy")
        assert info.value.hits == ()

    def test_foreign_object_raises(self) -> None:
        """Objects outside the package are a miss."""
        with pytest.raises(HelpLookupError):
            ref.describe(json)

    def test_uninspectable_builtin_member_is_a_miss(self) -> None:
        """An inherited builtin without a signature is a miss, not a ``ValueError``.

        ``str.maketrans`` is reachable on a ``str``-based enum but has no
        inspectable signature; inspectable inherited callables such as the
        Pydantic ``model_dump`` keep working.
        """
        with pytest.raises(HelpLookupError) as info:
            ref.describe("FeatureFlagStatus.maketrans")
        assert not isinstance(info.value, HelpDomainError)
        assert info.value.query == "FeatureFlagStatus.maketrans"
        assert ref.describe("CreateDashboardParams.model_dump").kind == "method"

    def test_parameter_missing_from_signature_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A parameter the signature builder does not report is a miss.

        The resolver and ``signature_doc`` normally agree; when they do not,
        the entry is not fabricated from an empty ``ParamDoc``.

        Args:
            monkeypatch: Pytest monkeypatch fixture.
        """
        real = introspect_module.signature_doc

        def _without_events(obj: object, *, name: str) -> ref.SignatureDoc:
            """Return the real signature minus the ``events`` parameter.

            Args:
                obj: The callable.
                name: Display name forwarded to the real builder.

            Returns:
                A copy of the real ``SignatureDoc`` without ``events``.
            """
            doc = real(obj, name=name)
            params = tuple(p for p in doc.params if p.name != "events")
            return ref.SignatureDoc(name=doc.name, params=params, returns=doc.returns)

        monkeypatch.setattr(introspect_module, "signature_doc", _without_events)
        with pytest.raises(HelpLookupError) as info:
            ref.describe("Workspace.query.events")
        assert not isinstance(info.value, HelpDomainError)
        assert info.value.query == "Workspace.query.events"
        assert info.value.suggestions == ("Workspace.query",)


# =============================================================================
# help(): printing wrapper
# =============================================================================


class TestHelpPrinting:
    """``help()`` prints and returns ``None``."""

    def test_prints_to_file_and_returns_none(self) -> None:
        """Output goes to ``file`` and matches ``render(describe(...))``."""
        text = _capture("Workspace.create_dashboard")
        assert text.endswith("\n")
        expected = ref.render(ref.describe("Workspace.create_dashboard"), "text")
        assert text == expected + "\n"
        assert "Referenced types (2):" in text
        assert "See also (dashboards):" in text

    def test_default_file_is_stdout(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Without ``file`` the text goes to ``sys.stdout``.

        Args:
            capsys: Pytest capture fixture.
        """
        ref.help("MathType")
        captured = capsys.readouterr()
        assert "MathType = Literal[22 values]" in captured.out
        assert captured.err == ""

    def test_overview_when_no_query(self) -> None:
        """``help()`` with no query prints the overview."""
        text = _capture()
        assert text.startswith(f"mixpanel_headless {mp.__version__}")

    def test_object_query(self) -> None:
        """An object query prints the same text as its string form."""
        assert _capture(mp.Filter) == _capture("Filter")

    def test_search_route(self) -> None:
        """``help("search cohort")`` prints the search view."""
        text = _capture("search cohort")
        assert text.startswith('# Search: "cohort"')
        assert "Cohort" in text

    def test_search_route_json(self) -> None:
        """``help("search cohort", format="json")`` prints the result dict."""
        payload = json.loads(_capture("search cohort", format="json"))
        assert payload["term"] == "cohort"
        assert payload["hits"]

    def test_search_without_term_prints_usage(self) -> None:
        """A bare ``search`` prints a short usage text and does not raise."""
        text = _capture("search")
        assert "search <term>" in text
        assert "No help entry" not in text

    def test_search_without_term_json(self) -> None:
        """A bare ``search`` with JSON output prints a JSON object."""
        payload = json.loads(_capture("search   ", format="json"))
        assert "usage" in payload

    def test_miss_prints_did_you_mean(self) -> None:
        """A miss prints the error message, then the hits; it does not raise."""
        text = _capture("Cohor")
        with pytest.raises(HelpLookupError) as info:
            ref.describe("Cohor")
        first_line, _, rest = text.partition("\n")
        assert first_line == info.value.message
        assert first_line.startswith(
            "No help entry for 'Cohor'. Did you mean: Cohort, "
        )
        assert '# Search: "Cohor"' in rest
        assert text.count("Did you mean") == 1

    def test_total_miss_prints_message_only(self) -> None:
        """A miss without suggestions or hits prints only the message."""
        text = _capture("zzqqxxyy")
        assert text == "No help entry for 'zzqqxxyy'.\n"

    def test_miss_json(self) -> None:
        """A miss with ``format="json"`` prints an error object."""
        payload = json.loads(_capture("Cohor", format="json"))
        with pytest.raises(HelpLookupError) as info:
            ref.describe("Cohor")
        assert set(payload) == {"error", "query", "suggestions", "hits"}
        assert payload["error"] == info.value.message
        assert payload["query"] == "Cohor"
        assert "Cohort" in payload["suggestions"]
        assert payload["hits"] == [hit.to_dict() for hit in info.value.hits[:5]]
        assert payload["hits"][0]["name"]

    def test_miss_with_domain_prints_instead_of_raising(self) -> None:
        """A name miss prints the miss even when ``domain=`` is set."""
        text = _capture("Filtr", domain="dashboards")
        assert text.startswith("No help entry for 'Filtr'.")

    def test_unknown_domain_raises(self) -> None:
        """An unknown ``domain=`` raises ``HelpDomainError`` and prints nothing."""
        buffer = io.StringIO()
        with pytest.raises(HelpDomainError) as info:
            ref.help("Workspace", domain="nope", file=buffer)
        assert buffer.getvalue() == ""
        assert info.value.domains == DOMAIN_TITLES

    def test_hit_json(self) -> None:
        """A hit with ``format="json"`` prints ``to_dict()``."""
        payload = json.loads(_capture("Filter", format="json"))
        assert payload == ref.describe("Filter").to_dict()

    def test_markdown_has_fence(self) -> None:
        """Markdown output contains a fenced code block."""
        text = _capture("Workspace.query", format="markdown")
        assert "```python" in text
        assert text.startswith("# Workspace.query")

    def test_invalid_format_raises(self) -> None:
        """An unknown format raises ``ValueError`` before anything prints."""
        buffer = io.StringIO()
        with pytest.raises(ValueError, match="format"):
            ref.help("Filter", format="yaml", file=buffer)  # type: ignore[arg-type]
        assert buffer.getvalue() == ""

    def test_hints_false(self) -> None:
        """``hints=False`` drops the ``Tip:`` block."""
        assert "Tip:" in _capture("Workspace.query")
        assert "Tip:" not in _capture("Workspace.query", hints=False)

    def test_domain_filter(self) -> None:
        """``domain=`` narrows the ``Workspace`` listing."""
        text = _capture("Workspace", domain="funnel query")
        assert "funnel query (3):" in text
        assert "properties (" not in text

    def test_domain_on_non_workspace_raises(self) -> None:
        """``domain=`` with another query raises ``HelpDomainError``."""
        with pytest.raises(HelpDomainError) as info:
            ref.help("Filter", domain="funnel query", file=io.StringIO())
        assert info.value.reason == "not_workspace"

    def test_no_rich_markup(self) -> None:
        """Listing output keeps the literal ``[property]`` tag."""
        assert "[property]" in _capture("Workspace")


# =============================================================================
# Isolation, caching, guard
# =============================================================================


class TestIsolation:
    """Help never reads config or writes a file."""

    def test_describe_creates_no_file(self, isolated_home: Path) -> None:
        """``describe("Workspace.query")`` leaves the empty home empty.

        Args:
            isolated_home: Empty home directory fixture.
        """
        ref.describe("Workspace.query")
        assert list(isolated_home.iterdir()) == []

    def test_help_creates_no_file(self, isolated_home: Path) -> None:
        """``help("Filter", file=buf)`` leaves the empty home empty.

        Args:
            isolated_home: Empty home directory fixture.
        """
        buffer = io.StringIO()
        ref.help("Filter", file=buffer)
        assert buffer.getvalue()
        assert list(isolated_home.iterdir()) == []


class TestClearCache:
    """``clear_cache()`` fans out to every internal cache."""

    def test_clears_every_cache(self) -> None:
        """Inventory, hints, relations, and search caches are all dropped."""
        before = inventory_module.inventory()
        ref.describe("Filter")
        ref.search("cohort")
        assert introspect_module._HINTS_CACHE
        assert relations_module._USED_BY
        assert search_module._INDEX is not None
        ref.clear_cache()
        assert inventory_module._INVENTORY is None
        assert introspect_module._HINTS_CACHE == {}
        assert relations_module._USED_BY == {}
        assert search_module._INDEX is None
        after = inventory_module.inventory()
        assert after is not before
        assert after == before


def _workspace_queries() -> list[str]:
    """Return every ``Workspace.<member>`` query string.

    Returns:
        The dotted queries in name order.
    """
    return [f"Workspace.{name}" for name, _ in inventory_module.workspace_members()]


class TestGuard:
    """Every public name describes and renders in every format."""

    def test_every_export_and_member_renders(self) -> None:
        """No inventory name or ``Workspace`` member raises in any format."""
        queries = [*inventory_module.inventory_names(), *_workspace_queries()]
        assert len(queries) == len(inventory_module.inventory()) + len(
            inventory_module.workspace_members()
        )
        failures: list[str] = []
        for query in queries:
            try:
                entry = ref.describe(query)
                for fmt in HELP_FORMATS:
                    rendered = ref.render(entry, fmt)
                    assert rendered
                json.loads(ref.render(entry, "json"))
            except Exception as exc:  # collect every failure, then report
                failures.append(f"{query}: {exc!r}")
        assert failures == []

    def test_listings_and_overview_render(self) -> None:
        """The synthetic entries render in every format too."""
        for query in (None, "types", "exceptions", "help"):
            entry = ref.describe(query)
            for fmt in HELP_FORMATS:
                assert ref.render(entry, fmt)
