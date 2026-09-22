"""Unit tests for ``mixpanel_headless._internal.help.relations``.

Covers the cross-reference helpers:

- ``used_by``: exact hint-tree matching on ``Workspace`` method
  parameters, the Literal-alias case, and the string fallback.
- ``referenced_types``: exported types in a callable's parameter and
  return annotations, with the owner class excluded.
- ``see_also``: domain siblings from ``WORKSPACE_DOMAINS``.
- ``exception_tree`` / ``subclasses_of`` / ``raised_by``: the exported
  exception hierarchy and the ``Raises:`` index.
- Per-name caching and ``clear_cache``.

Real-library counts were measured on 2026-09-21: ``Filter`` is accepted by
10 ``Workspace`` methods (exact matching; the substring approach the old
script used reported 16 because it also matched ``FrequencyFilter`` and
``FilterOperator``), and ``SignedURLExpiredError`` sits at depth 3.
"""

from __future__ import annotations

import inspect
import re

import pytest

from mixpanel_headless import (
    APIError,
    Filter,
    FlowQueryResult,
    MixpanelHeadlessError,
    SessionReplayError,
    SignedURLExpiredError,
    Workspace,
)
from mixpanel_headless._internal.help import relations
from mixpanel_headless._internal.help.docstrings import first_line, parse_docstring
from mixpanel_headless._internal.help.introspect import resolved_hints
from mixpanel_headless._internal.help.inventory import (
    export,
    exports_of_kind,
    workspace_members,
)
from mixpanel_headless._internal.help.models import HelpKind, UsageDoc
from mixpanel_headless._internal.help.registry import WORKSPACE_DOMAINS
from mixpanel_headless._internal.help.relations import (
    clear_cache,
    exception_tree,
    raised_by,
    referenced_types,
    see_also,
    subclasses_of,
    used_by,
)
from mixpanel_headless._literal_types import ALIAS_DOCS


@pytest.fixture(autouse=True)
def _fresh_cache() -> None:
    """Start every test with empty relation caches.

    Returns:
        ``None``; the fixture only clears module state.
    """
    clear_cache()


def _hint_tree(hint: object) -> list[object]:
    """Flatten a resolved hint into every nested node, including itself.

    Args:
        hint: A resolved annotation object.

    Returns:
        The hint followed by every argument reachable through ``typing.get_args``.
    """
    import typing

    nodes: list[object] = [hint]
    for arg in typing.get_args(hint):
        nodes.extend(_hint_tree(arg))
    return nodes


def _method_names() -> tuple[str, ...]:
    """Return the public ``Workspace`` method names.

    Returns:
        Sorted method names from the inventory (properties excluded).
    """
    return tuple(name for name, kind in workspace_members() if kind == "method")


def _unresolvable(where: Filter | Undefined, limit: int) -> FlowQueryResult:  # type: ignore[name-defined]  # noqa: F821
    """Fixture callable whose annotations cannot be resolved.

    ``Undefined`` does not exist, so ``typing.get_type_hints`` raises
    ``NameError`` and ``resolved_hints`` returns ``{}``. The relation
    functions must then fall back to word-boundary matching on the string
    annotations, which still name ``Filter`` and ``FlowQueryResult``.

    Args:
        where: Annotation that names ``Filter`` next to an unknown name.
        limit: A builtin annotation that must not produce a referenced type.

    Returns:
        Never returns; the body raises.

    Raises:
        NotImplementedError: Always; the function exists for its annotations.
    """
    raise NotImplementedError(where, limit)


class TestUsedBy:
    """``used_by`` matches parameter types exactly, never by substring."""

    def test_filter_count_and_parameter_names(self) -> None:
        """``Filter`` is accepted by exactly 10 methods, always via ``where``."""
        usages = used_by("Filter")
        assert len(usages) == 10
        assert all(usage.params == ("where",) for usage in usages)
        assert UsageDoc("query", ("where",)) in usages
        assert UsageDoc("build_flow_params", ("where",)) in usages

    def test_sorted_by_method_name(self) -> None:
        """Usages are sorted by method name."""
        names = [usage.method for usage in used_by("Filter")]
        assert names == sorted(names)

    def test_every_usage_really_references_the_type(self) -> None:
        """Each listed parameter's resolved hint tree contains the export object."""
        target = export("Filter")
        assert target is not None
        for usage in used_by("Filter"):
            hints = resolved_hints(getattr(Workspace, usage.method))
            for param in usage.params:
                assert any(node is target.obj for node in _hint_tree(hints[param]))

    def test_substring_matches_are_excluded(self) -> None:
        """Mentions of ``FrequencyFilter`` or ``FilterOperator`` alone do not count."""
        exact = {usage.method for usage in used_by("Filter")}
        substring = {
            name
            for name in _method_names()
            if "Filter" in str(inspect.signature(getattr(Workspace, name)))
        }
        assert exact < substring
        target = export("Filter")
        assert target is not None
        for name in substring - exact:
            hints = resolved_hints(getattr(Workspace, name))
            for param, hint in hints.items():
                if param != "return":
                    assert all(node is not target.obj for node in _hint_tree(hint))

    def test_cohort_does_not_match_cohort_prefixed_types(self) -> None:
        """``Cohort`` is only ever returned, so nothing accepts it."""
        assert used_by("Cohort") == ()
        target = export("Cohort")
        assert target is not None
        for name in _method_names():
            hints = resolved_hints(getattr(Workspace, name))
            for param, hint in hints.items():
                if param != "return":
                    assert all(node is not target.obj for node in _hint_tree(hint))

    def test_literal_alias(self) -> None:
        """``MathType`` is accepted by ``query`` and ``build_params`` via ``math``."""
        assert used_by("MathType") == (
            UsageDoc("build_params", ("math",)),
            UsageDoc("query", ("math",)),
        )

    def test_return_types_are_not_usages(self) -> None:
        """``FlowQueryResult`` is returned by ``query_flow``, which is not a usage."""
        usages = used_by("FlowQueryResult")
        assert all(usage.method != "query_flow" for usage in usages)
        # It is still accepted as a parameter by the report-link builder.
        assert UsageDoc("create_report_link", ("params",)) in usages

    def test_unknown_name(self) -> None:
        """An unknown export name yields no usages."""
        assert used_by("NoSuchExport") == ()

    def test_string_fallback_when_hints_fail(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When hints resolve to ``{}``, word-boundary matching keeps ``query(where)``."""
        monkeypatch.setattr(relations, "resolved_hints", lambda _obj: {})
        clear_cache()
        usages = used_by("Filter")
        assert UsageDoc("query", ("where",)) in usages
        for usage in usages:
            signature = inspect.signature(getattr(Workspace, usage.method))
            for param in usage.params:
                annotation = str(signature.parameters[param].annotation)
                assert re.search(r"\bFilter\b", annotation)

    def test_string_fallback_uses_word_boundaries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The fallback does not let ``Cohort`` match ``CohortMetric``."""
        monkeypatch.setattr(relations, "resolved_hints", lambda _obj: {})
        clear_cache()
        for usage in used_by("Cohort"):
            signature = inspect.signature(getattr(Workspace, usage.method))
            for param in usage.params:
                annotation = str(signature.parameters[param].annotation)
                assert re.search(r"\bCohort\b", annotation)


class TestReferencedTypes:
    """``referenced_types`` collects exported types from annotations."""

    def test_create_dashboard(self) -> None:
        """The parameter type and the return type appear with their summaries."""
        from mixpanel_headless import CreateDashboardParams, Dashboard

        assert referenced_types(Workspace.create_dashboard) == (
            ("CreateDashboardParams", first_line(CreateDashboardParams.__doc__)),
            ("Dashboard", first_line(Dashboard.__doc__)),
        )

    def test_query_flow_includes_return_type(self) -> None:
        """``FlowQueryResult`` is found through the resolved return hint."""
        names = [name for name, _summary in referenced_types(Workspace.query_flow)]
        assert "FlowQueryResult" in names
        assert "Filter" in names
        assert names == sorted(names)

    def test_owner_class_excluded(self) -> None:
        """``Filter.equals`` returns ``Filter``, but the owner is not listed."""
        names = [name for name, _summary in referenced_types(Filter.equals)]
        assert "Filter" not in names

    def test_workspace_excluded_for_methods(self) -> None:
        """``Workspace`` never lists itself even when a method returns it."""
        names = [name for name, _summary in referenced_types(Workspace.use)]
        assert "Workspace" not in names

    def test_literal_alias_summary_comes_from_alias_docs(self) -> None:
        """A Literal alias uses ``ALIAS_DOCS`` for its summary."""
        pairs = dict(referenced_types(Workspace.query))
        assert pairs["MathType"] == ALIAS_DOCS["MathType"]

    def test_string_fallback(self) -> None:
        """Unresolvable annotations still yield the names present as whole words."""
        assert resolved_hints(_unresolvable) == {}
        pairs = referenced_types(_unresolvable)
        assert [name for name, _summary in pairs] == ["Filter", "FlowQueryResult"]
        assert pairs[0][1] == first_line(Filter.__doc__)

    def test_functions_and_modules_are_never_referenced(self) -> None:
        """Only type-like kinds qualify; functions, modules, and constants do not."""
        excluded: tuple[HelpKind, ...] = ("module", "function", "constant")
        excluded_names = {
            row.name for kind in excluded for row in exports_of_kind(kind)
        }
        for name in _method_names():
            for ref, _summary in referenced_types(getattr(Workspace, name)):
                assert ref not in excluded_names

    def test_object_without_signature(self) -> None:
        """A non-callable yields no references instead of raising."""
        assert referenced_types(object()) == ()


class TestSeeAlso:
    """``see_also`` returns domain siblings from ``WORKSPACE_DOMAINS``."""

    def test_create_dashboard_siblings(self) -> None:
        """Siblings are the other ``dashboards`` methods, sorted, without itself."""
        title, siblings = see_also("Workspace.create_dashboard")
        expected = tuple(
            sorted(set(dict(WORKSPACE_DOMAINS)["dashboards"]) - {"create_dashboard"})
        )
        assert title == "dashboards"
        assert siblings == expected
        assert "create_dashboard" not in siblings

    def test_non_workspace_query(self) -> None:
        """Types and other exports have no domain."""
        assert see_also("Filter") == ("", ())

    def test_workspace_property(self) -> None:
        """Properties are not registered in any domain."""
        assert see_also("Workspace.api") == ("", ())

    def test_unknown_member(self) -> None:
        """An unknown ``Workspace`` member has no domain."""
        assert see_also("Workspace.nonesuch") == ("", ())

    def test_deeper_paths_are_not_methods(self) -> None:
        """A parameter path is not a method and has no siblings."""
        assert see_also("Workspace.query.events") == ("", ())


class TestExceptionTree:
    """``exception_tree`` and ``subclasses_of``."""

    def test_root_first(self) -> None:
        """The tree starts at ``MixpanelHeadlessError`` with depth 0."""
        assert exception_tree()[0] == ("MixpanelHeadlessError", 0)

    def test_known_depths(self) -> None:
        """The chain down to ``SignedURLExpiredError`` spans depths 0 through 3."""
        tree = exception_tree()
        assert ("APIError", 1) in tree
        assert ("SessionReplayError", 2) in tree
        assert ("SignedURLExpiredError", 3) in tree
        assert max(depth for _name, depth in tree) == 3

    def test_covers_every_exported_exception_once(self) -> None:
        """Every exported exception appears exactly once."""
        names = [name for name, _depth in exception_tree()]
        assert sorted(names) == sorted(row.name for row in exports_of_kind("exception"))
        assert len(names) == len(set(names))

    def test_depth_steps_by_at_most_one(self) -> None:
        """A depth-first listing never skips a level going down."""
        depths = [depth for _name, depth in exception_tree()]
        assert all(
            later <= earlier + 1
            for earlier, later in zip(depths, depths[1:], strict=False)
        )

    def test_children_sorted(self) -> None:
        """Direct children of the root appear in name order."""
        children = [name for name, depth in exception_tree() if depth == 1]
        assert children == sorted(children)
        assert children == list(subclasses_of(MixpanelHeadlessError))

    def test_subtree_matches_slice_of_full_tree(self) -> None:
        """``exception_tree(APIError)`` equals the ``APIError`` slice, re-based to depth 0."""
        full = exception_tree()
        start = full.index(("APIError", 1))
        end = next(
            (i for i in range(start + 1, len(full)) if full[i][1] <= 1),
            len(full),
        )
        expected = tuple((name, depth - 1) for name, depth in full[start:end])
        assert exception_tree(APIError) == expected
        assert exception_tree(APIError)[0] == ("APIError", 0)

    def test_leaf_subtree(self) -> None:
        """A leaf exception yields only itself."""
        assert exception_tree(SignedURLExpiredError) == (("SignedURLExpiredError", 0),)
        assert subclasses_of(SignedURLExpiredError) == ()

    def test_subclasses_of_intermediate(self) -> None:
        """``SessionReplayError`` has ``SignedURLExpiredError`` among its children."""
        assert "SignedURLExpiredError" in subclasses_of(SessionReplayError)
        assert subclasses_of(SessionReplayError) == tuple(
            sorted(subclasses_of(SessionReplayError))
        )

    def test_unexported_root(self) -> None:
        """A root outside the inventory still anchors its exported descendants."""
        tree = exception_tree(Exception)
        assert tree[0] == ("Exception", 0)
        assert ("MixpanelHeadlessError", 1) in tree
        assert ("SignedURLExpiredError", 4) in tree


class TestRaisedBy:
    """``raised_by`` from the ``Raises:`` docstring sections."""

    def test_workspace_scope_error(self) -> None:
        """Methods that document ``WorkspaceScopeError`` are returned, sorted, without params."""
        usages = raised_by("WorkspaceScopeError")
        assert usages
        assert all(usage.params == () for usage in usages)
        names = [usage.method for usage in usages]
        assert names == sorted(names)
        for name in names:
            raises = parse_docstring(getattr(Workspace, name).__doc__).raises
            assert any(
                exc.rsplit(".", 1)[-1] == "WorkspaceScopeError" for exc, _ in raises
            )

    def test_complete(self) -> None:
        """No method that documents the exception is missed."""
        listed = {usage.method for usage in raised_by("WorkspaceScopeError")}
        for name in _method_names():
            raises = parse_docstring(getattr(Workspace, name).__doc__).raises
            if any(
                exc.rsplit(".", 1)[-1] == "WorkspaceScopeError" for exc, _ in raises
            ):
                assert name in listed

    def test_dotted_name_matches_last_segment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A ``Raises:`` entry written as ``mp.APIError`` matches ``APIError``."""
        monkeypatch.setattr(
            relations,
            "_raises_index",
            lambda: (("some_method", ("mp.APIError",)),),
        )
        assert raised_by("APIError") == (UsageDoc("some_method", ()),)
        assert raised_by("mp.APIError") == ()

    def test_unknown_exception(self) -> None:
        """An exception nobody documents yields no methods."""
        assert raised_by("NoSuchError") == ()


class TestCache:
    """Per-name caching and ``clear_cache``."""

    def test_used_by_is_cached(self) -> None:
        """Repeated calls return the identical tuple."""
        assert used_by("Filter") is used_by("Filter")

    def test_raised_by_is_cached(self) -> None:
        """Repeated calls return the identical tuple."""
        assert raised_by("WorkspaceScopeError") is raised_by("WorkspaceScopeError")

    def test_clear_cache_rebuilds(self) -> None:
        """After ``clear_cache`` the result is a new but equal tuple."""
        first = used_by("Filter")
        clear_cache()
        second = used_by("Filter")
        assert second is not first
        assert second == first

    def test_exception_tree_is_deterministic(self) -> None:
        """Two calls produce equal trees."""
        assert exception_tree() == exception_tree()
