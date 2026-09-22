"""Unit tests for ``mixpanel_headless._internal.help.resolve``.

The resolver answers one question: *what object does this query name, and
what kind is it?* These tests lock:

- the query grammar split (``parse_query``) between overview, describe, and
  search;
- dotted-path navigation from the package root for exports,
  ``Workspace`` members, class members, namespace-module members, and
  callable parameters;
- exact-then-unique-case-insensitive name matching, with a natural
  ambiguity (``Session`` / ``session``) that must raise;
- object queries for classes, functions, bound and unbound methods,
  modules, the package, a ``Workspace`` instance, and foreign objects;
- "Did you mean?" suggestions on a miss;
- the isolation guarantee: resolution reads no config and writes no file.
"""

from __future__ import annotations

import inspect
import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

import mixpanel_headless as mp
from mixpanel_headless import HelpLookupError
from mixpanel_headless._internal.help import inventory as inventory_module
from mixpanel_headless._internal.help.inventory import (
    Export,
    clear_cache,
    export,
    inventory,
    inventory_names,
    workspace_members,
)
from mixpanel_headless._internal.help.resolve import (
    Target,
    parse_query,
    resolve,
    suggestions_for,
)
from mixpanel_headless.workspace import Workspace
from tests.conftest import make_session

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    """Clear the inventory cache before and after every test.

    Yields:
        Nothing; the fixture only brackets the test with ``clear_cache()``.
    """
    clear_cache()
    yield
    clear_cache()


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


@pytest.fixture
def workspace(isolated_home: Path) -> Workspace:
    """Build a ``Workspace`` from a stub session without any I/O.

    Args:
        isolated_home: Empty home directory fixture (keeps the build hermetic).

    Returns:
        A ``Workspace`` bound to a service-account stub session.
    """
    return Workspace(session=make_session())


# =============================================================================
# Target record
# =============================================================================


class TestTarget:
    """``Target`` is a frozen record keyed on kind and qualname."""

    def test_defaults(self) -> None:
        """Owner fields default to ``None``."""
        target = Target(kind="class", qualname="Filter", obj=mp.Filter)
        assert target.owner is None
        assert target.owner_name is None
        assert target.member is None

    def test_frozen(self) -> None:
        """Assigning a field raises."""
        target = Target(kind="class", qualname="Filter", obj=mp.Filter)
        with pytest.raises(AttributeError):
            target.qualname = "Other"  # type: ignore[misc]

    def test_equality_ignores_objects(self) -> None:
        """Equality compares kind, qualname, owner_name, and member only."""
        first = Target(kind="class", qualname="Filter", obj=mp.Filter)
        second = Target(kind="class", qualname="Filter", obj=object())
        assert first == second
        assert hash(first) == hash(second)


# =============================================================================
# parse_query
# =============================================================================


class TestParseQuery:
    """``parse_query`` splits the grammar into overview, search, and describe."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            pytest.param("", ("overview", ""), id="empty"),
            pytest.param("   ", ("overview", ""), id="blank"),
            pytest.param("search cohort", ("search", "cohort"), id="search"),
            pytest.param("search", ("search", ""), id="search-no-term"),
            pytest.param("  search   two words ", ("search", "two words"), id="ws"),
            pytest.param("Workspace.query", ("describe", "Workspace.query"), id="dot"),
            pytest.param("types", ("describe", "types"), id="types"),
            pytest.param("Workspace query", ("describe", "Workspace query"), id="two"),
        ],
    )
    def test_parse(self, text: str, expected: tuple[str, str]) -> None:
        """Each query text maps to the expected mode and payload.

        Args:
            text: Raw query text.
            expected: ``(mode, payload)``.
        """
        assert parse_query(text) == expected

    def test_search_keyword_is_case_sensitive(self) -> None:
        """Only a lowercase leading ``search`` token selects search mode."""
        assert parse_query("Search cohort") == ("describe", "Search cohort")


# =============================================================================
# String queries
# =============================================================================


class TestOverviewAndListings:
    """``None``, ``""``, ``types``, and ``exceptions`` map to special targets."""

    @pytest.mark.parametrize("query", [None, "", "   "])
    def test_overview(self, query: str | None) -> None:
        """Empty input resolves to the package overview.

        Args:
            query: ``None`` or blank text.
        """
        target = resolve(query)
        assert target.kind == "overview"
        assert target.qualname == ""
        assert target.obj is mp

    @pytest.mark.parametrize("query", ["types", "exceptions"])
    def test_listings(self, query: str) -> None:
        """``types`` and ``exceptions`` resolve to ``listing`` targets.

        Args:
            query: The listing keyword.
        """
        target = resolve(query)
        assert target.kind == "listing"
        assert target.qualname == query
        assert target.obj is None


class TestExports:
    """Every inventory name resolves to itself."""

    @pytest.mark.parametrize("name", sorted(set(mp.__all__)))
    def test_round_trip(self, name: str) -> None:
        """``resolve(name)`` yields the export's kind, name, and object.

        Args:
            name: An ``__all__`` entry.
        """
        row = export(name)
        assert row is not None
        target = resolve(name)
        assert target == Target(kind=row.kind, qualname=name, obj=row.obj)
        assert target.obj is row.obj

    def test_surrounding_whitespace_is_ignored(self) -> None:
        """Leading and trailing whitespace does not change the result."""
        assert resolve("  Filter  ") == resolve("Filter")

    @pytest.mark.parametrize(
        ("query", "kind"),
        [
            pytest.param("Workspace", "class", id="Workspace"),
            pytest.param("FeatureFlagStatus", "enum", id="enum"),
            pytest.param("Filter", "dataclass", id="dataclass"),
            pytest.param("CreateDashboardParams", "model", id="model"),
            pytest.param("MathType", "literal", id="literal"),
            pytest.param("Account", "alias", id="alias"),
            pytest.param("APIError", "exception", id="exception"),
            pytest.param("login_unified", "function", id="function"),
            pytest.param("accounts", "module", id="module"),
            pytest.param("BUSINESS_CONTEXT_MAX_CHARS", "constant", id="constant"),
        ],
    )
    def test_query_kinds(self, query: str, kind: str) -> None:
        """Each documented query form resolves to its expected kind.

        Args:
            query: Query text.
            kind: Expected ``HelpKind``.
        """
        assert resolve(query).kind == kind


class TestWorkspaceMembers:
    """``Workspace.<member>`` resolves for every public member."""

    @pytest.mark.parametrize(("name", "kind"), workspace_members())
    def test_every_member(self, name: str, kind: str) -> None:
        """Each member resolves with its kind, owner, and member name.

        Args:
            name: Member name.
            kind: ``method`` or ``property``.
        """
        target = resolve(f"Workspace.{name}")
        assert target.kind == kind
        assert target.qualname == f"Workspace.{name}"
        assert target.owner is Workspace
        assert target.owner_name == "Workspace"
        assert target.member == name

    def test_method_object(self) -> None:
        """A method target holds the plain function from the class."""
        target = resolve("Workspace.query")
        assert target.obj is Workspace.query
        assert inspect.isfunction(target.obj)

    def test_property_object(self) -> None:
        """A property target holds the ``property`` descriptor."""
        target = resolve("Workspace.account")
        assert target.kind == "property"
        assert isinstance(target.obj, property)
        assert target.obj is inspect.getattr_static(Workspace, "account")


class TestParameters:
    """``Workspace.<method>.<param>`` resolves to a ``parameter`` target."""

    def test_query_events(self) -> None:
        """``Workspace.query.events`` yields the ``inspect.Parameter``."""
        target = resolve("Workspace.query.events")
        assert target.kind == "parameter"
        assert target.qualname == "Workspace.query.events"
        assert isinstance(target.obj, inspect.Parameter)
        assert target.obj.name == "events"
        assert target.owner is Workspace.query
        assert target.owner_name == "Workspace.query"
        assert target.member == "events"

    def test_keyword_only_parameter(self) -> None:
        """A keyword-only parameter resolves like a positional one."""
        target = resolve("Workspace.query.math")
        assert target.kind == "parameter"
        assert isinstance(target.obj, inspect.Parameter)
        assert target.obj.default == "total"

    def test_self_is_not_a_parameter(self) -> None:
        """``self`` is never exposed as a parameter."""
        with pytest.raises(HelpLookupError):
            resolve("Workspace.query.self")

    def test_function_parameter(self) -> None:
        """Parameters of a top-level function resolve too."""
        target = resolve("login_unified.region")
        assert target.kind == "parameter"
        assert target.owner is mp.login_unified

    def test_module_function_parameter(self) -> None:
        """Parameters of a namespace-module function resolve (three segments)."""
        target = resolve("accounts.add.name")
        assert target.kind == "parameter"
        assert target.qualname == "accounts.add.name"
        assert target.owner is mp.accounts.add

    def test_parameter_has_no_children(self) -> None:
        """A fourth segment below a parameter is a miss."""
        with pytest.raises(HelpLookupError):
            resolve("Workspace.query.events.x")

    def test_property_has_no_parameters(self) -> None:
        """A segment below a property is a miss."""
        with pytest.raises(HelpLookupError):
            resolve("Workspace.account.x")


class TestClassMembers:
    """``<Class>.<member>`` resolves for any public class."""

    def test_classmethod(self) -> None:
        """``Filter.equals`` is a ``method`` owned by ``Filter``."""
        target = resolve("Filter.equals")
        assert target.kind == "method"
        assert target.qualname == "Filter.equals"
        assert target.owner is mp.Filter
        assert target.owner_name == "Filter"
        assert target.member == "equals"
        assert target.obj == mp.Filter.equals

    def test_classmethod_parameter(self) -> None:
        """``Filter.equals.value`` resolves to a parameter without ``cls``."""
        target = resolve("Filter.equals.value")
        assert target.kind == "parameter"
        with pytest.raises(HelpLookupError):
            resolve("Filter.equals.cls")

    def test_inherited_pydantic_method(self) -> None:
        """Public inherited methods such as ``model_dump`` resolve."""
        target = resolve("CreateDashboardParams.model_dump")
        assert target.kind == "method"

    def test_property_on_result_type(self) -> None:
        """A ``property`` on a public class resolves as ``property``."""
        target = resolve("QueryResult.df")
        assert target.kind == "property"
        assert target.owner is mp.QueryResult

    def test_enum_member(self) -> None:
        """An enum member resolves as a ``constant`` owned by the enum."""
        target = resolve("FeatureFlagStatus.ENABLED")
        assert target.kind == "constant"
        assert target.obj is mp.FeatureFlagStatus.ENABLED
        assert target.owner is mp.FeatureFlagStatus

    def test_exception_member(self) -> None:
        """Members of exported exceptions resolve like any class member."""
        target = resolve("HelpLookupError.with_traceback")
        assert target.kind == "method"

    def test_unknown_member_raises(self) -> None:
        """An unknown class member raises ``HelpLookupError``."""
        with pytest.raises(HelpLookupError):
            resolve("Filter.no_such_member")


class TestModuleMembers:
    """``<module>.<name>`` resolves through the namespace module's ``__all__``."""

    def test_function(self) -> None:
        """``accounts.add`` is a ``function`` owned by the module."""
        target = resolve("accounts.add")
        assert target.kind == "function"
        assert target.qualname == "accounts.add"
        assert target.obj is mp.accounts.add
        assert target.owner is mp.accounts
        assert target.owner_name == "accounts"
        assert target.member == "add"

    @pytest.mark.parametrize("module_name", ["accounts", "session", "targets"])
    def test_every_all_member(self, module_name: str) -> None:
        """Each ``__all__`` entry of the namespace module resolves.

        Args:
            module_name: Export name of the namespace module.
        """
        module = getattr(mp, module_name)
        for name in module.__all__:
            target = resolve(f"{module_name}.{name}")
            assert target.obj is getattr(module, name)
            assert target.qualname == f"{module_name}.{name}"

    def test_name_outside_all_raises(self) -> None:
        """A module attribute that is not in ``__all__`` is a miss."""
        assert hasattr(mp.accounts, "annotations")
        assert "annotations" not in mp.accounts.__all__
        with pytest.raises(HelpLookupError):
            resolve("accounts.annotations")


class TestCaseInsensitive:
    """Exact match first, then a unique case-insensitive match."""

    def test_filter_lowercase(self) -> None:
        """``filter`` resolves to ``Filter``."""
        target = resolve("filter")
        assert target.qualname == "Filter"
        assert target.obj is mp.Filter

    def test_member_case_insensitive(self) -> None:
        """Member segments also accept a unique case-insensitive match."""
        assert resolve("workspace.QUERY") == resolve("Workspace.query")

    def test_exact_wins_over_case_insensitive(self) -> None:
        """``session`` (module) and ``Session`` (model) both exist; exact wins."""
        assert resolve("session").kind == "module"
        assert resolve("Session").kind == "model"

    def test_ambiguous_raises_with_candidates(self) -> None:
        """``SESSION`` matches two names and raises with both as suggestions."""
        with pytest.raises(HelpLookupError) as info:
            resolve("SESSION")
        assert info.value.query == "SESSION"
        assert set(info.value.suggestions) == {"Session", "session"}
        assert info.value.hits == ()


class TestHelpQuery:
    """``help`` resolves through the inventory like any other export."""

    def test_help_function(self) -> None:
        """``help`` resolves to the package-level ``help`` function."""
        target = resolve("help")
        assert target.kind == "function"
        assert target.qualname == "help"
        assert target.obj is mp.help
        assert target.obj is mp.reference.help


class TestPrivateAndMalformed:
    """Private names and malformed paths are never resolvable."""

    @pytest.mark.parametrize(
        "query",
        [
            "_internal",
            "Workspace._api_client",
            "Workspace.query._x",
            "Filter._property",
            ".Filter",
            "Filter.",
            "Workspace..query",
            "search cohort",
            "Workspace query",
            "types.x",
            "exceptions.APIError",
        ],
    )
    def test_raises(self, query: str) -> None:
        """Each malformed or private query raises ``HelpLookupError``.

        Args:
            query: Query text.
        """
        with pytest.raises(HelpLookupError) as info:
            resolve(query)
        assert info.value.query == query

    def test_literal_has_no_members(self) -> None:
        """A segment below a Literal alias is a miss that suggests the alias."""
        with pytest.raises(HelpLookupError) as info:
            resolve("MathType.total")
        assert info.value.suggestions == ("MathType",)


# =============================================================================
# Suggestions
# =============================================================================


class TestSuggestions:
    """Misses carry ``difflib`` close-match suggestions."""

    def test_root_miss_suggests_close_exports(self) -> None:
        """A misspelled export suggests the close export names."""
        with pytest.raises(HelpLookupError) as info:
            resolve("Filtr")
        assert info.value.query == "Filtr"
        assert info.value.suggestions
        assert info.value.suggestions[0] == "Filter"
        assert len(info.value.suggestions) <= 5

    def test_root_miss_suggests_workspace_members(self) -> None:
        """A bare misspelled method name suggests the qualified member."""
        with pytest.raises(HelpLookupError) as info:
            resolve("query_funel")
        assert "Workspace.query_funnel" in info.value.suggestions

    def test_dotted_miss_prefixes_parent(self) -> None:
        """A dotted miss restricts to the parent's members with the parent prefix."""
        with pytest.raises(HelpLookupError) as info:
            resolve("Workspace.query_funel")
        assert info.value.suggestions
        assert info.value.suggestions[0] == "Workspace.query_funnel"
        assert all(s.startswith("Workspace.") for s in info.value.suggestions)

    def test_dotted_miss_without_close_match_suggests_parent(self) -> None:
        """When nothing is close, the parent itself is the only suggestion."""
        with pytest.raises(HelpLookupError) as info:
            resolve("Workspace.zzzzzzzzzzzz")
        assert info.value.suggestions == ("Workspace",)

    def test_parameter_miss_suggests_sibling_parameters(self) -> None:
        """A misspelled parameter suggests the close parameter names."""
        with pytest.raises(HelpLookupError) as info:
            resolve("Workspace.query.evnts")
        assert info.value.suggestions == ("Workspace.query.events",)

    def test_root_miss_without_close_match_has_no_suggestions(self) -> None:
        """A miss with nothing close carries an empty suggestion tuple."""
        with pytest.raises(HelpLookupError) as info:
            resolve("zzzzzzzzzzzz")
        assert info.value.suggestions == ()

    def test_suggestions_for(self) -> None:
        """``suggestions_for`` matches against root-level names, capped at five."""
        matches = suggestions_for("Filtr")
        assert matches[0] == "Filter"
        assert len(matches) <= 5
        assert "Workspace.query_funnel" in suggestions_for("query_funel")
        assert suggestions_for("zzzzzzzzzzzz") == ()

    def test_suggestions_are_unique(self) -> None:
        """Suggestions never repeat a name."""
        matches = suggestions_for("session")
        assert len(matches) == len(set(matches))


# =============================================================================
# Object queries
# =============================================================================


class TestObjectQueries:
    """Objects resolve to the same targets as their string forms."""

    def test_class(self) -> None:
        """``mp.Filter`` resolves like ``"Filter"``."""
        assert resolve(mp.Filter) == resolve("Filter")

    def test_enum_class(self) -> None:
        """An exported enum class resolves by identity."""
        assert resolve(mp.FeatureFlagStatus).qualname == "FeatureFlagStatus"

    def test_exception_class(self) -> None:
        """An exported exception class resolves by identity."""
        assert resolve(HelpLookupError).kind == "exception"

    def test_unbound_method(self) -> None:
        """``Workspace.query`` (plain function) resolves to ``Workspace.query``."""
        assert resolve(Workspace.query) == resolve("Workspace.query")

    def test_bound_method(self, workspace: Workspace) -> None:
        """A bound method resolves through its owner class, not the instance.

        Args:
            workspace: Stub-session ``Workspace``.
        """
        target = resolve(workspace.query)
        assert target == resolve("Workspace.query")
        assert target.owner is Workspace

    def test_bound_classmethod(self) -> None:
        """``Filter.equals`` (bound to the class) resolves to ``Filter.equals``."""
        assert resolve(mp.Filter.equals) == resolve("Filter.equals")

    def test_property_object(self) -> None:
        """A ``property`` descriptor resolves through its getter's qualname."""
        prop = inspect.getattr_static(Workspace, "account")
        assert resolve(prop) == resolve("Workspace.account")

    def test_workspace_instance(self, workspace: Workspace) -> None:
        """A ``Workspace`` instance resolves to the ``Workspace`` class.

        Args:
            workspace: Stub-session ``Workspace``.
        """
        assert resolve(workspace) == resolve("Workspace")

    def test_instance_of_exported_class(self) -> None:
        """An instance of an exported class resolves to that class."""
        assert resolve(mp.Filter.equals("plan", "pro")) == resolve("Filter")
        assert resolve(mp.FeatureFlagStatus.ENABLED) == resolve("FeatureFlagStatus")

    def test_top_level_function(self) -> None:
        """``mp.login_unified`` resolves by identity."""
        assert resolve(mp.login_unified) == resolve("login_unified")

    def test_module_function(self) -> None:
        """``mp.accounts.add`` resolves to ``accounts.add``."""
        assert resolve(mp.accounts.add) == resolve("accounts.add")

    def test_namespace_module(self) -> None:
        """``mp.accounts`` resolves to the ``module`` target."""
        target = resolve(mp.accounts)
        assert target.kind == "module"
        assert target.qualname == "accounts"

    def test_package(self) -> None:
        """The package itself resolves to the overview."""
        assert resolve(mp) == resolve(None)

    @pytest.mark.parametrize(
        "obj",
        [
            pytest.param(json.dumps, id="foreign-function"),
            pytest.param(json, id="foreign-module"),
            pytest.param(dict, id="builtin-type"),
            pytest.param(object(), id="foreign-instance"),
            pytest.param(42, id="int"),
            pytest.param(Path("x").exists, id="foreign-bound-method"),
            pytest.param(inventory, id="internal-function"),
            pytest.param(Target, id="internal-class"),
        ],
    )
    def test_foreign_or_internal_objects_raise(self, obj: object) -> None:
        """Objects outside the public surface raise ``HelpLookupError``.

        Args:
            obj: A foreign or private object.
        """
        with pytest.raises(HelpLookupError):
            resolve(obj)

    def test_local_function_raises(self) -> None:
        """A function defined inside another function is not resolvable."""

        def _inner() -> None:
            """Local helper."""

        _inner.__module__ = "mixpanel_headless.workspace"
        with pytest.raises(HelpLookupError):
            resolve(_inner)


class TestEdgeCases:
    """Rare shapes: ambiguous members, builtins without signatures, bare properties."""

    def test_ambiguous_member_raises_with_prefixed_candidates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two members that differ only by case raise with both as suggestions.

        Args:
            monkeypatch: Pytest monkeypatch fixture.
        """

        class _Twins:
            """Class with two members that differ only by case."""

            def alpha(self) -> None:
                """Lowercase member."""

            def Alpha(self) -> None:  # noqa: N802
                """Capitalized member."""

        rows = (*inventory(), Export(name="Twins", kind="class", obj=_Twins))
        monkeypatch.setattr(inventory_module, "_INVENTORY", rows)
        with pytest.raises(HelpLookupError) as info:
            resolve("Twins.ALPHA")
        assert set(info.value.suggestions) == {"Twins.Alpha", "Twins.alpha"}
        assert resolve("Twins.alpha").member == "alpha"

    def test_builtin_without_signature_has_no_parameters(self) -> None:
        """A builtin whose signature is unavailable exposes no parameters."""
        target = resolve("FeatureFlagStatus.maketrans")
        assert target.kind == "method"
        with pytest.raises(HelpLookupError) as info:
            resolve("FeatureFlagStatus.maketrans.x")
        assert info.value.suggestions == ("FeatureFlagStatus.maketrans",)

    def test_property_without_getter_raises(self) -> None:
        """A bare ``property()`` has no getter to resolve through."""
        with pytest.raises(HelpLookupError):
            resolve(property())

    def test_function_with_borrowed_qualname_raises(self) -> None:
        """A function that only mimics ``Filter.equals`` by qualname is a miss."""

        def _impostor() -> None:
            """Function that borrows a public qualname."""

        _impostor.__qualname__ = "Filter.equals"
        _impostor.__module__ = "mixpanel_headless.types"
        with pytest.raises(HelpLookupError):
            resolve(_impostor)


# =============================================================================
# No side effects
# =============================================================================


class TestNoSideEffects:
    """Resolution touches no config file and creates nothing under ``HOME``."""

    def test_resolution_creates_no_files(self, isolated_home: Path) -> None:
        """``resolve`` and ``inventory`` leave the empty home directory empty.

        Args:
            isolated_home: Empty home directory with no ``MP_*`` variables.
        """
        assert list(isolated_home.iterdir()) == []
        resolve("Workspace.query")
        resolve("Workspace")
        resolve(None)
        inventory()
        inventory_names()
        with pytest.raises(HelpLookupError):
            resolve("Workspace.nope")
        assert list(isolated_home.iterdir()) == []
