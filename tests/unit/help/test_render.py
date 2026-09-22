"""Unit tests for ``mixpanel_headless._internal.help.render``.

The renderers are pure functions from ``HelpEntry`` / ``SearchResult`` to a
string. These tests lock:

- every ``HelpKind`` renders in every ``HelpFormat`` without raising;
- exact text layout for small hand-made fixtures (signature block, column
  widths, ``Referenced types (N):``, ``See also``, hint block, ``Literal[N
  values]`` header, search columns, ``No matches for "x"``);
- markdown output uses ``##`` headings, fenced blocks, and link hints;
- JSON output parses back into ``to_dict()``;
- the literal ``[property]`` / ``[method]`` tags survive and no Rich
  markup is emitted;
- an unknown format raises ``ValueError``.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from mixpanel_headless._internal.help.models import (
    HELP_FORMATS,
    HELP_KINDS,
    DocSections,
    FieldDoc,
    Group,
    HelpEntry,
    HelpFormat,
    HelpKind,
    Hint,
    MemberDoc,
    ParamDoc,
    SearchHit,
    SearchResult,
    SignatureDoc,
    UsageDoc,
)
from mixpanel_headless._internal.help.render import (
    NAME_WIDTH,
    _compact_signature,
    _wrap_values,
    render,
    render_json,
    render_markdown,
    render_search_json,
    render_search_markdown,
    render_search_text,
    render_text,
)

DOCS = "https://mixpanel.github.io/mixpanel-headless"
"""Hosted docs base used by the hint fixtures."""

ENTITY_HINT = Hint(
    title="dashboards, reports, and cohorts (entity management)",
    url=f"{DOCS}/guide/entity-management/index.md",
)
"""Hint fixture for the ``create_dashboard`` reference example."""

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def method_entry() -> HelpEntry:
    """Return a hand-built ``Workspace.create_dashboard`` entry.

    Returns:
        A ``method`` entry with signature, doc sections, two referenced types,
        a single domain group, two see-also names, and one hint.
    """
    return HelpEntry(
        kind="method",
        name="Workspace.create_dashboard",
        qualname="mixpanel_headless.workspace.Workspace.create_dashboard",
        summary="Create a new dashboard.",
        doc=DocSections(
            summary="Create a new dashboard.",
            body="Create a new dashboard.",
            args=(("params", "Dashboard creation parameters."),),
            returns="The created dashboard.",
            raises=(("APIError", "When the request fails."),),
            example="```python\nws.create_dashboard(params)\n```",
        ),
        signature=SignatureDoc(
            name="create_dashboard",
            params=(ParamDoc(name="params", annotation="CreateDashboardParams"),),
            returns="Dashboard",
        ),
        groups=(Group(title="dashboards", items=()),),
        referenced_types=(
            ("CreateDashboardParams", "Parameters for creating a new dashboard."),
            ("Dashboard", "A Mixpanel dashboard as returned by the App API."),
        ),
        see_also=("add_report_to_dashboard", "bulk_delete_dashboards"),
        hints=(ENTITY_HINT,),
    )


@pytest.fixture
def class_entry() -> HelpEntry:
    """Return a small ``Filter``-like dataclass entry with every class section.

    Returns:
        A ``dataclass`` entry with construction, fields (required, default,
        factory, constraints, alias, inline values), a property, a method,
        and one used-by row.
    """
    return HelpEntry(
        kind="dataclass",
        name="Filter",
        qualname="mixpanel_headless.types.Filter",
        summary="A property filter.",
        doc=DocSections(summary="A property filter.", body="A property filter."),
        config=(("frozen", "True"),),
        construction=(
            MemberDoc(
                name="equals",
                kind="method",
                summary="Build an equals filter.",
                signature=SignatureDoc(
                    name="equals",
                    params=(
                        ParamDoc(name="property", annotation="str"),
                        ParamDoc(name="value", annotation="object"),
                        ParamDoc(
                            name="property_type", annotation="str", default="'string'"
                        ),
                    ),
                    returns="Filter",
                ),
            ),
        ),
        fields=(
            FieldDoc(name="property", annotation="str", required=True),
            FieldDoc(
                name="operator",
                annotation="FilterOperatorInput",
                default="'equals'",
                values=("equals", "not_equals"),
            ),
            FieldDoc(name="tags", annotation="list[str]", default="<factory list>"),
            FieldDoc(
                name="name",
                annotation="str",
                default="'x'",
                constraints=("max_length=255",),
                alias="displayName",
            ),
        ),
        properties=(
            MemberDoc(
                name="is_empty", kind="property", summary="Whether the filter is empty."
            ),
        ),
        methods=(
            MemberDoc(
                name="to_dict",
                kind="method",
                summary="Serialize the filter.",
                signature=SignatureDoc(name="to_dict", returns="dict[str, object]"),
            ),
        ),
        used_by=(UsageDoc(method="query", params=("where",)),),
    )


@pytest.fixture
def search_result() -> SearchResult:
    """Return a two-hit search result for ``"cohort"``.

    Returns:
        A ``SearchResult`` with one ``type`` hit and one ``method`` hit.
    """
    return SearchResult(
        term="cohort",
        hits=(
            SearchHit(
                category="type",
                name="Cohort",
                summary="A saved cohort.",
                matched_on="name",
            ),
            SearchHit(
                category="method",
                name="Workspace.create_cohort",
                summary="Create a cohort.",
                matched_on="name",
            ),
        ),
    )


def make_entries() -> dict[HelpKind, HelpEntry]:
    """Build one small ``HelpEntry`` for every ``HelpKind``.

    Returns:
        A mapping from kind to a representative entry that exercises the
        sections the renderer prints for that kind.
    """
    doc = DocSections(summary="Summary line.", body="Summary line.\n\nMore text.")
    sig = SignatureDoc(
        name="fn",
        params=(ParamDoc(name="x", annotation="int", default="1"),),
        returns="str",
    )
    member = MemberDoc(name="fn", kind="function", summary="Do it.", signature=sig)
    prop = MemberDoc(name="name", kind="property", summary="The name.")
    meth = MemberDoc(name="query", kind="method", summary="Run a query.")
    usage = (UsageDoc(method="query", params=("math",)),)
    entries: dict[HelpKind, HelpEntry] = {
        "overview": HelpEntry(
            kind="overview",
            name="mixpanel_headless",
            qualname="mixpanel_headless",
            summary="0.3.0",
            doc=DocSections(body="Query grammar:\n  Workspace.<method>"),
            groups=(Group(title="Entry points", items=(member,)),),
        ),
        "class": HelpEntry(
            kind="class",
            name="Thing",
            qualname="mixpanel_headless.Thing",
            summary="Summary line.",
            doc=doc,
            bases=("Base",),
            methods=(member,),
        ),
        "model": HelpEntry(
            kind="model",
            name="Params",
            qualname="mixpanel_headless.types.Params",
            summary="Summary line.",
            doc=doc,
            bases=("BaseModel",),
            config=(("extra", "'forbid'"),),
            fields=(FieldDoc(name="name", annotation="str", required=True),),
        ),
        "dataclass": HelpEntry(
            kind="dataclass",
            name="Row",
            qualname="mixpanel_headless.types.Row",
            summary="Summary line.",
            doc=doc,
            fields=(FieldDoc(name="n", annotation="int", default="0"),),
        ),
        "enum": HelpEntry(
            kind="enum",
            name="Status",
            qualname="mixpanel_headless.types.Status",
            summary="Summary line.",
            doc=doc,
            fields=(FieldDoc(name="ON", annotation="str", default="'on'"),),
            values=("ON",),
            used_by=usage,
        ),
        "literal": HelpEntry(
            kind="literal",
            name="Mode",
            qualname="mixpanel_headless._literal_types.Mode",
            summary="Summary line.",
            doc=doc,
            values=("a", "b"),
            used_by=usage,
        ),
        "alias": HelpEntry(
            kind="alias",
            name="Account",
            qualname="mixpanel_headless.auth_types.Account",
            summary="Summary line.",
            doc=doc,
            values=("ServiceAccount", "OAuthTokenAccount"),
            referenced_types=(("ServiceAccount", "Basic auth."),),
        ),
        "exception": HelpEntry(
            kind="exception",
            name="APIError",
            qualname="mixpanel_headless.exceptions.APIError",
            summary="Summary line.",
            doc=doc,
            bases=("MixpanelHeadlessError",),
            groups=(
                Group(
                    title="Subclasses",
                    items=(
                        MemberDoc(
                            name="RateLimitError", kind="exception", summary="429"
                        ),
                    ),
                ),
            ),
            used_by=(UsageDoc(method="query", params=()),),
        ),
        "function": HelpEntry(
            kind="function",
            name="login_unified",
            qualname="mixpanel_headless.accounts.login_unified",
            summary="Summary line.",
            doc=doc,
            signature=sig,
            hints=(ENTITY_HINT,),
        ),
        "method": HelpEntry(
            kind="method",
            name="Workspace.query",
            qualname="mixpanel_headless.workspace.Workspace.query",
            summary="Summary line.",
            doc=doc,
            signature=sig,
            see_also=("build_params",),
        ),
        "property": HelpEntry(
            kind="property",
            name="Workspace.name",
            qualname="mixpanel_headless.workspace.Workspace.name",
            summary="Summary line.",
            doc=doc,
            signature=SignatureDoc(name="name", returns="str"),
        ),
        "parameter": HelpEntry(
            kind="parameter",
            name="Workspace.query.math",
            qualname="mixpanel_headless.workspace.Workspace.query.math",
            summary="Aggregation.",
            doc=DocSections(summary="Aggregation.", body="Aggregation."),
            signature=SignatureDoc(
                name="query",
                params=(
                    ParamDoc(
                        name="math",
                        annotation="MathType",
                        default="'total'",
                        description="Aggregation.",
                        values=("total", "unique"),
                    ),
                ),
            ),
            values=("total", "unique"),
        ),
        "module": HelpEntry(
            kind="module",
            name="accounts",
            qualname="mixpanel_headless.accounts",
            summary="Summary line.",
            doc=doc,
            methods=(member,),
        ),
        "constant": HelpEntry(
            kind="constant",
            name="BUSINESS_CONTEXT_MAX_CHARS",
            qualname="mixpanel_headless.BUSINESS_CONTEXT_MAX_CHARS",
            summary="Summary line.",
            doc=doc,
            bases=("int",),
            values=("65536",),
        ),
        "listing": HelpEntry(
            kind="listing",
            name="Workspace",
            qualname="mixpanel_headless.workspace.Workspace",
            summary="Primary facade.",
            doc=DocSections(),
            groups=(
                Group(title="Properties", items=(prop,)),
                Group(title="Insights query", items=(meth,)),
            ),
        ),
        "search": HelpEntry(
            kind="search",
            name="search",
            qualname="mixpanel_headless.reference.search",
            summary="Summary line.",
            doc=doc,
        ),
    }
    return entries


ENTRIES = make_entries()
"""One representative entry per ``HelpKind``."""


# =============================================================================
# Dispatch and formats
# =============================================================================


def test_make_entries_covers_every_kind() -> None:
    """The fixture table has exactly one entry per ``HelpKind``."""
    assert set(ENTRIES) == set(HELP_KINDS)


@pytest.mark.parametrize("kind", HELP_KINDS)
@pytest.mark.parametrize("fmt", HELP_FORMATS)
def test_every_kind_renders_in_every_format(kind: HelpKind, fmt: HelpFormat) -> None:
    """Each kind renders to a non-empty string in each format.

    Args:
        kind: The ``HelpKind`` under test.
        fmt: The ``HelpFormat`` under test.
    """
    out = render(ENTRIES[kind], fmt)
    assert isinstance(out, str)
    assert out.strip()
    assert ENTRIES[kind].name in out


def test_render_defaults_to_text(method_entry: HelpEntry) -> None:
    """``render`` without a format returns the text rendering."""
    assert render(method_entry) == render_text(method_entry)


def test_render_dispatches_search_result(search_result: SearchResult) -> None:
    """``render`` routes a ``SearchResult`` to the search renderers."""
    assert render(search_result, "text") == render_search_text(search_result)
    assert render(search_result, "markdown") == render_search_markdown(search_result)
    assert render(search_result, "json") == render_search_json(search_result)


@pytest.mark.parametrize("bad", ["", "html", "TEXT", "yaml"])
def test_unknown_format_raises(method_entry: HelpEntry, bad: str) -> None:
    """An unknown format raises ``ValueError`` naming the bad value.

    Args:
        bad: The invalid format string.
    """
    with pytest.raises(ValueError, match="format"):
        render(method_entry, bad)  # type: ignore[arg-type]


def test_json_round_trips_entry(method_entry: HelpEntry) -> None:
    """JSON output parses back into ``to_dict()`` and is indented by two."""
    out = render_json(method_entry)
    assert json.loads(out) == method_entry.to_dict()
    assert out == json.dumps(method_entry.to_dict(), indent=2)


def test_json_round_trips_search(search_result: SearchResult) -> None:
    """Search JSON output parses back into ``to_dict()``."""
    assert json.loads(render_search_json(search_result)) == search_result.to_dict()


@pytest.mark.parametrize("kind", HELP_KINDS)
def test_text_has_no_rich_markup_and_no_trailing_newline(kind: HelpKind) -> None:
    """Text output carries no Rich markup close tags and no trailing newline.

    Args:
        kind: The ``HelpKind`` under test.
    """
    out = render_text(ENTRIES[kind])
    assert "[/" not in out
    assert not out.endswith("\n")
    assert all(not line.endswith(" ") for line in out.splitlines())


# =============================================================================
# Callables: method, function, property, parameter
# =============================================================================


def test_method_text_exact(method_entry: HelpEntry) -> None:
    """The canonical ``create_dashboard`` entry renders the expected text layout."""
    expected = "\n".join(
        [
            "Workspace.create_dashboard(",
            "    params: CreateDashboardParams",
            ") -> Dashboard",
            "",
            "Create a new dashboard.",
            "",
            "Args:",
            "    params: Dashboard creation parameters.",
            "",
            "Returns:",
            "    The created dashboard.",
            "",
            "Raises:",
            "    APIError: When the request fails.",
            "",
            "Example:",
            "    ```python",
            "    ws.create_dashboard(params)",
            "    ```",
            "",
            "Referenced types (2):",
            "  CreateDashboardParams                      "
            "Parameters for creating a new dashboard.",
            "  Dashboard                                  "
            "A Mixpanel dashboard as returned by the App API.",
            "",
            "See also (dashboards): add_report_to_dashboard, bulk_delete_dashboards",
            "",
            "---",
            "Tip: For dashboards, reports, and cohorts (entity management),",
            f'     WebFetch(url="{DOCS}/guide/entity-management/index.md")',
        ]
    )
    assert render_text(method_entry) == expected


def test_signature_block_multiple_params_and_defaults() -> None:
    """Each parameter sits on its own line; defaults follow ``= ``."""
    entry = HelpEntry(
        kind="function",
        name="fn",
        qualname="m.fn",
        summary="S.",
        doc=DocSections(summary="S.", body="S."),
        signature=SignatureDoc(
            name="fn",
            params=(
                ParamDoc(name="a", annotation="int"),
                ParamDoc(name="b", annotation="str | None", default="None"),
                ParamDoc(name="c", annotation="", default="1"),
            ),
            returns="None",
        ),
    )
    assert render_text(entry) == (
        "fn(\n    a: int,\n    b: str | None = None,\n    c = 1\n) -> None\n\nS."
    )


def test_signature_block_no_params_no_returns_prints_ellipsis() -> None:
    """A signature with no parameters and no return prints ``Name(...)``."""
    entry = HelpEntry(
        kind="function",
        name="opaque",
        qualname="m.opaque",
        summary="",
        doc=DocSections(),
        signature=SignatureDoc(name="opaque"),
    )
    assert render_text(entry) == "opaque(...)\n\n(no docstring)"


def test_signature_block_no_params_with_returns() -> None:
    """A signature with no parameters but a return prints ``Name() -> R``."""
    entry = HelpEntry(
        kind="method",
        name="Workspace.clear",
        qualname="m.Workspace.clear",
        summary="Clear.",
        doc=DocSections(summary="Clear.", body="Clear."),
        signature=SignatureDoc(name="clear", returns="None"),
    )
    assert render_text(entry).startswith("Workspace.clear() -> None\n\nClear.")


def test_callable_without_signature_prints_name_only() -> None:
    """A callable entry whose ``signature`` is ``None`` prints the bare name."""
    entry = HelpEntry(
        kind="function",
        name="fn",
        qualname="m.fn",
        summary="S.",
        doc=DocSections(summary="S.", body="S."),
    )
    assert render_text(entry) == "fn\n\nS."


def test_args_wrap_long_descriptions_with_hanging_indent() -> None:
    """A long ``Args:`` description wraps at 88 columns with an 8-space indent."""
    long = " ".join(["word"] * 30)
    entry = HelpEntry(
        kind="function",
        name="fn",
        qualname="m.fn",
        summary="S.",
        doc=DocSections(summary="S.", body="S.", args=(("p", long),)),
        signature=SignatureDoc(
            name="fn", params=(ParamDoc(name="p", annotation="str"),)
        ),
    )
    lines = render_text(entry).splitlines()
    arg_lines = [line for line in lines if "word" in line]
    assert len(arg_lines) > 1
    assert arg_lines[0].startswith("    p: word")
    assert all(line.startswith("        word") for line in arg_lines[1:])
    assert all(len(line) <= 88 for line in arg_lines)


def test_notes_section_rendered() -> None:
    """A ``Notes:`` section prints under a ``Notes:`` header, indented."""
    entry = HelpEntry(
        kind="function",
        name="fn",
        qualname="m.fn",
        summary="S.",
        doc=DocSections(summary="S.", body="S.", notes="Be careful.\nReally."),
        signature=SignatureDoc(name="fn"),
    )
    assert render_text(entry).endswith("Notes:\n    Be careful.\n    Really.")


def test_see_also_without_domain_group() -> None:
    """With no group, the line is ``See also: a, b``."""
    entry = ENTRIES["method"]
    assert "\n\nSee also: build_params" in render_text(entry)
    assert "See also (" not in render_text(entry)


def test_see_also_with_two_groups_has_no_domain(method_entry: HelpEntry) -> None:
    """Two groups do not identify a domain, so no parenthesised title prints."""
    entry = dataclasses.replace(
        method_entry, groups=(Group(title="a", items=()), Group(title="b", items=()))
    )
    out = render_text(entry)
    assert "See also: add_report_to_dashboard, bulk_delete_dashboards" in out
    assert "See also (" not in out


def test_multiple_hints_each_get_a_tip_block(method_entry: HelpEntry) -> None:
    """Every hint prints its own ``---`` / ``Tip:`` / ``WebFetch`` block."""
    second = Hint(title="Second", url=f"{DOCS}/x/index.md")
    entry = dataclasses.replace(method_entry, hints=(ENTITY_HINT, second))
    out = render_text(entry)
    assert out.count("\n---\nTip: ") == 2
    assert out.endswith(
        f'---\nTip: For Second,\n     WebFetch(url="{DOCS}/x/index.md")'
    )


def test_property_text_exact() -> None:
    """A property prints ``Name -> ret`` then the docstring."""
    entry = HelpEntry(
        kind="property",
        name="Workspace.project_id",
        qualname="m.Workspace.project_id",
        summary="Project id.",
        doc=DocSections(summary="Project id.", body="Project id."),
        signature=SignatureDoc(name="project_id", returns="int"),
    )
    assert render_text(entry) == "Workspace.project_id -> int\n\nProject id."


def test_property_without_returns() -> None:
    """A property with no return annotation prints the bare name."""
    entry = HelpEntry(
        kind="property",
        name="Workspace.name",
        qualname="m.Workspace.name",
        summary="Name.",
        doc=DocSections(summary="Name.", body="Name."),
    )
    assert render_text(entry) == "Workspace.name\n\nName."


def test_parameter_text_exact() -> None:
    """A parameter prints its annotation, default, allowed values, and description."""
    expected = "\n".join(
        [
            "Workspace.query.math: MathType = 'total'",
            "Allowed values:",
            "  total | unique",
            "",
            "Aggregation.",
        ]
    )
    assert render_text(ENTRIES["parameter"]) == expected


def test_parameter_without_values_or_default() -> None:
    """A required parameter with no values prints only the annotation line."""
    entry = HelpEntry(
        kind="parameter",
        name="Workspace.query.events",
        qualname="m.Workspace.query.events",
        summary="Events.",
        doc=DocSections(summary="Events.", body="Events."),
        signature=SignatureDoc(
            name="query", params=(ParamDoc(name="events", annotation="str | Metric"),)
        ),
    )
    assert render_text(entry) == "Workspace.query.events: str | Metric\n\nEvents."


def test_parameter_falls_back_to_entry_values_and_param_description() -> None:
    """Without ``entry.values`` the ``ParamDoc`` values and description are used."""
    entry = HelpEntry(
        kind="parameter",
        name="Workspace.query.mode",
        qualname="m.Workspace.query.mode",
        summary="",
        doc=DocSections(),
        signature=SignatureDoc(
            name="query",
            params=(
                ParamDoc(
                    name="mode",
                    annotation="Mode",
                    description="Shape.",
                    values=("a", "b"),
                ),
            ),
        ),
    )
    out = render_text(entry)
    assert out == "Workspace.query.mode: Mode\nAllowed values:\n  a | b\n\nShape."


def test_parameter_without_signature_prints_name() -> None:
    """A parameter entry with no signature prints just its name and description."""
    entry = HelpEntry(
        kind="parameter",
        name="Workspace.query.x",
        qualname="m.Workspace.query.x",
        summary="X.",
        doc=DocSections(summary="X.", body="X."),
    )
    assert render_text(entry) == "Workspace.query.x\n\nX."


# =============================================================================
# Classes, models, dataclasses
# =============================================================================


def test_class_text_exact(class_entry: HelpEntry) -> None:
    """A dataclass entry renders header, config, sections, and used-by rows."""
    expected = "\n".join(
        [
            "class Filter",
            "  Inherits: (none)",
            "  Config: frozen=True",
            "",
            "A property filter.",
            "",
            "Construction (1 classmethods):",
            "  Filter.equals(property, value, property_type='string')",
            "",
            "Fields (public):",
            "  property: str (required)",
            "  operator: FilterOperatorInput = 'equals'  # values: equals | not_equals",
            "  tags: list[str] = <factory list>",
            "  name: str = 'x' [max_length=255] alias → displayName",
            "",
            "Properties:",
            "  is_empty                                   "
            "[property] Whether the filter is empty.",
            "",
            "Methods:",
            "  to_dict()                                  Serialize the filter.",
            "",
            "Used by Workspace (1 methods):",
            "  query(where)",
        ]
    )
    assert render_text(class_entry) == expected


def test_class_inherits_joins_bases() -> None:
    """Bases print comma-separated on the ``Inherits:`` line."""
    entry = HelpEntry(
        kind="model",
        name="P",
        qualname="m.P",
        summary="S.",
        doc=DocSections(summary="S.", body="S."),
        bases=("Base", "BaseModel"),
    )
    assert render_text(entry) == "class P\n  Inherits: Base, BaseModel\n\nS."


def test_class_without_docstring_prints_placeholder() -> None:
    """A class with no docstring prints ``(no docstring)``."""
    entry = HelpEntry(
        kind="class", name="C", qualname="m.C", summary="", doc=DocSections()
    )
    assert render_text(entry) == "class C\n  Inherits: (none)\n\n(no docstring)"


def test_long_method_row_still_separated_by_one_space() -> None:
    """A compact signature longer than the column still gets one space before its summary."""
    long_name = "a" * 50
    entry = HelpEntry(
        kind="class",
        name="C",
        qualname="m.C",
        summary="S.",
        doc=DocSections(summary="S.", body="S."),
        methods=(
            MemberDoc(
                name=long_name,
                kind="method",
                summary="Long.",
                signature=SignatureDoc(name=long_name),
            ),
        ),
    )
    assert f"  {long_name}() Long." in render_text(entry)


# =============================================================================
# Enum, literal, alias, exception, module, constant
# =============================================================================


def test_enum_text_exact() -> None:
    """An enum prints a padded member table, the docstring, then used-by."""
    entry = HelpEntry(
        kind="enum",
        name="FeatureFlagStatus",
        qualname="m.FeatureFlagStatus",
        summary="Lifecycle status.",
        doc=DocSections(summary="Lifecycle status.", body="Lifecycle status."),
        fields=(
            FieldDoc(name="ENABLED", annotation="str", default="'enabled'"),
            FieldDoc(name="DISABLED", annotation="str", default="'disabled'"),
        ),
        values=("ENABLED", "DISABLED"),
        used_by=(UsageDoc(method="list_feature_flags", params=("status",)),),
    )
    expected = "\n".join(
        [
            "enum FeatureFlagStatus",
            "  ENABLED   = 'enabled'",
            "  DISABLED  = 'disabled'",
            "",
            "Lifecycle status.",
            "",
            "Used by Workspace (1 methods):",
            "  list_feature_flags(status)",
        ]
    )
    assert render_text(entry) == expected


def test_enum_without_fields_falls_back_to_values() -> None:
    """When the assembler supplies only ``values``, member names print alone."""
    entry = HelpEntry(
        kind="enum",
        name="E",
        qualname="m.E",
        summary="S.",
        doc=DocSections(summary="S.", body="S."),
        values=("A", "BB"),
    )
    assert render_text(entry) == "enum E\n  A\n  BB\n\nS."


def test_literal_text_exact_with_wrapping() -> None:
    """A literal prints ``Name = Literal[N values]`` and a wrapped value list."""
    values = tuple(f"value_{i:02d}" for i in range(12))
    entry = HelpEntry(
        kind="literal",
        name="MathType",
        qualname="m.MathType",
        summary="Aggregation for an event.",
        doc=DocSections(summary="Aggregation for an event."),
        values=values,
        used_by=(
            UsageDoc(method="build_params", params=("math",)),
            UsageDoc(method="query", params=("math",)),
        ),
    )
    expected = "\n".join(
        [
            "MathType = Literal[12 values]",
            "  value_00 | value_01 | value_02 | value_03 | value_04 | value_05 | value_06"
            " | value_07",
            "  | value_08 | value_09 | value_10 | value_11",
            "",
            "Aggregation for an event.",
            "",
            "Used by Workspace (2 methods):",
            "  build_params(math)",
            "  query(math)",
        ]
    )
    out = render_text(entry)
    assert out == expected
    assert all(len(line) <= 88 for line in out.splitlines())


def test_wrap_values_helper() -> None:
    """``_wrap_values`` packs greedily and starts continuation lines with ``| ``."""
    assert _wrap_values(("a", "b", "c"), width=9) == ["  a | b", "  | c"]
    assert _wrap_values((), width=9) == []
    assert _wrap_values(("only",), width=3) == ["  only"]


def test_alias_text_exact() -> None:
    """A union alias prints ``Name = A | B`` and one row per documented member."""
    entry = HelpEntry(
        kind="alias",
        name="Account",
        qualname="m.Account",
        summary="Any account.",
        doc=DocSections(summary="Any account.", body="Any account."),
        values=("ServiceAccount", "OAuthTokenAccount"),
        referenced_types=(
            ("ServiceAccount", "Basic auth."),
            ("OAuthTokenAccount", "Static bearer."),
        ),
    )
    expected = "\n".join(
        [
            "Account = ServiceAccount | OAuthTokenAccount",
            "  ServiceAccount                             Basic auth.",
            "  OAuthTokenAccount                          Static bearer.",
            "",
            "Any account.",
        ]
    )
    assert render_text(entry) == expected


def test_exception_text_exact() -> None:
    """An exception prints its base, doc, subclass tree, and raised-by rows."""
    entry = HelpEntry(
        kind="exception",
        name="APIError",
        qualname="m.APIError",
        summary="API failure.",
        doc=DocSections(summary="API failure.", body="API failure."),
        bases=("MixpanelHeadlessError", "Exception"),
        groups=(
            Group(
                title="Subclasses",
                items=(
                    MemberDoc(
                        name="SessionReplayError", kind="exception", summary="Replay."
                    ),
                    MemberDoc(
                        name="  SignedURLExpiredError",
                        kind="exception",
                        summary="Expired.",
                    ),
                ),
            ),
        ),
        used_by=(
            UsageDoc(method="fetch_replay", params=()),
            UsageDoc(method="query", params=()),
        ),
    )
    expected = "\n".join(
        [
            "exception APIError(MixpanelHeadlessError)",
            "",
            "API failure.",
            "",
            "Subclasses:",
            "  SessionReplayError                         Replay.",
            "    SignedURLExpiredError                    Expired.",
            "",
            "Raised by Workspace (2 methods):",
            "  fetch_replay",
            "  query",
        ]
    )
    assert render_text(entry) == expected


def test_exception_without_bases_uses_exception() -> None:
    """With no recorded bases the header falls back to ``(Exception)``."""
    entry = HelpEntry(
        kind="exception",
        name="E",
        qualname="m.E",
        summary="S.",
        doc=DocSections(summary="S.", body="S."),
    )
    assert render_text(entry) == "exception E(Exception)\n\nS."


def test_module_text_exact() -> None:
    """A module prints its doc then ``Members (N):`` with compact signatures."""
    entry = HelpEntry(
        kind="module",
        name="accounts",
        qualname="mixpanel_headless.accounts",
        summary="Account management.",
        doc=DocSections(summary="Account management.", body="Account management."),
        methods=(
            MemberDoc(
                name="add",
                kind="function",
                summary="Add an account.",
                signature=SignatureDoc(
                    name="add",
                    params=(
                        ParamDoc(name="name", annotation="str"),
                        ParamDoc(name="region", annotation="Region", default="'us'"),
                    ),
                ),
            ),
            MemberDoc(name="DEFAULT", kind="constant", summary="Default name."),
        ),
    )
    expected = "\n".join(
        [
            "module accounts",
            "",
            "Account management.",
            "",
            "Members (2):",
            "  add(name, region='us')                     Add an account.",
            "  DEFAULT                                    Default name.",
        ]
    )
    assert render_text(entry) == expected


def test_module_with_groups_renders_group_titles() -> None:
    """When a module entry carries groups, each prints as ``Title (N):``."""
    entry = HelpEntry(
        kind="module",
        name="targets",
        qualname="mixpanel_headless.targets",
        summary="S.",
        doc=DocSections(summary="S.", body="S."),
        groups=(
            Group(
                title="Functions",
                items=(MemberDoc(name="use", kind="function", summary="Use."),),
            ),
        ),
    )
    assert render_text(entry).endswith("Functions (1):\n  use" + " " * 40 + "Use.")


def test_constant_text_exact() -> None:
    """A constant prints ``NAME: type = value`` from ``bases[0]`` / ``values[0]``."""
    entry = HelpEntry(
        kind="constant",
        name="BUSINESS_CONTEXT_MAX_CHARS",
        qualname="m.BUSINESS_CONTEXT_MAX_CHARS",
        summary="Max chars.",
        doc=DocSections(summary="Max chars.", body="Max chars."),
        bases=("int",),
        values=("65536",),
    )
    assert render_text(entry) == "BUSINESS_CONTEXT_MAX_CHARS: int = 65536\n\nMax chars."


def test_constant_without_type_or_value() -> None:
    """Missing type and value parts are omitted from the constant header."""
    entry = HelpEntry(
        kind="constant", name="X", qualname="m.X", summary="", doc=DocSections()
    )
    assert render_text(entry) == "X"
    only_value = HelpEntry(
        kind="constant",
        name="X",
        qualname="m.X",
        summary="",
        doc=DocSections(),
        values=("1",),
    )
    assert render_text(only_value) == "X = 1"


# =============================================================================
# Listing, overview
# =============================================================================


def test_listing_text_exact_with_literal_tags() -> None:
    """A listing prints ``Title (N):`` groups with literal ``[property]`` / ``[method]`` tags."""
    expected = "\n".join(
        [
            "Workspace: Primary facade.",
            "",
            "Properties (1):",
            "  name                                       [property] The name.",
            "",
            "Insights query (1):",
            "  query                                      [method] Run a query.",
        ]
    )
    assert render_text(ENTRIES["listing"]) == expected


def test_listing_rows_without_method_kind_have_no_tag() -> None:
    """Rows for non-member kinds (models, exceptions) print the name and summary only."""
    entry = HelpEntry(
        kind="listing",
        name="types",
        qualname="mixpanel_headless",
        summary="",
        doc=DocSections(),
        groups=(
            Group(
                title="Models",
                items=(
                    MemberDoc(name="Dashboard", kind="model", summary="A dashboard."),
                ),
            ),
            Group(
                title="Tree",
                items=(MemberDoc(name="  Child", kind="exception", summary="Nested."),),
            ),
        ),
    )
    expected = "\n".join(
        [
            "types",
            "",
            "Models (1):",
            "  Dashboard                                  A dashboard.",
            "",
            "Tree (1):",
            "    Child                                    Nested.",
        ]
    )
    assert render_text(entry) == expected


def test_overview_text_layout() -> None:
    """The overview prints ``name version``, the body, then group tables."""
    out = render_text(ENTRIES["overview"])
    lines = out.splitlines()
    assert lines[0] == "mixpanel_headless 0.3.0"
    assert lines[1] == ""
    assert lines[2:4] == ["Query grammar:", "  Workspace.<method>"]
    assert "Entry points (1):" in lines
    assert f"  {'fn(x=1)':<{NAME_WIDTH}} Do it." in lines
    assert len(lines) < 60


# =============================================================================
# Search
# =============================================================================


def test_search_text_exact(search_result: SearchResult) -> None:
    """Search rows use ``[category ]`` padded to 9 and a name column sized to the longest hit."""
    expected = "\n".join(
        [
            '# Search: "cohort" — 2 matches',
            "",
            "  [type     ] Cohort                   A saved cohort.",
            "  [method   ] Workspace.create_cohort  Create a cohort.",
        ]
    )
    assert render_search_text(search_result) == expected


def test_search_text_long_category_is_not_truncated() -> None:
    """A category longer than 9 characters prints in full."""
    result = SearchResult(
        term="x",
        hits=(
            SearchHit(
                category="verylongcategory", name="X", summary="", matched_on="doc"
            ),
        ),
    )
    assert "[verylongcategory] X" in render_search_text(result)


def test_search_text_no_hits_with_suggestions() -> None:
    """A miss prints ``No matches for "x"`` then a ``Did you mean?`` list."""
    result = SearchResult(term="cohrt", suggestions=("Cohort", "CohortMetric"))
    assert render_search_text(result) == (
        'No matches for "cohrt"\n\nDid you mean?\n  Cohort\n  CohortMetric'
    )


def test_search_text_no_hits_no_suggestions() -> None:
    """A miss with no suggestions prints only the ``No matches`` line."""
    assert render_search_text(SearchResult(term="zzz")) == 'No matches for "zzz"'


def test_search_markdown_with_and_without_hits(search_result: SearchResult) -> None:
    """Search markdown uses a table for hits and a list for suggestions."""
    out = render_search_markdown(search_result)
    assert out.startswith('# Search: "cohort" — 2 matches')
    assert "| Category | Name | Summary |" in out
    assert "| method | `Workspace.create_cohort` | Create a cohort. |" in out
    miss = render_search_markdown(SearchResult(term="q", suggestions=("Query",)))
    assert 'No matches for "q"' in miss
    assert "## Did you mean?" in miss
    assert "- `Query`" in miss


# =============================================================================
# Markdown
# =============================================================================


def test_markdown_method_has_fenced_signature_and_sections(
    method_entry: HelpEntry,
) -> None:
    """Method markdown has a fenced signature, ``##`` sections, a table, and a link hint."""
    out = render_markdown(method_entry)
    assert out.startswith(
        "# Workspace.create_dashboard\n\n```python\nWorkspace.create_dashboard(\n"
        "    params: CreateDashboardParams\n) -> Dashboard\n```\n\n"
        "Create a new dashboard.\n"
    )
    assert "## Args\n\n- `params`: Dashboard creation parameters." in out
    assert "## Returns\n\nThe created dashboard." in out
    assert "## Raises\n\n- `APIError`: When the request fails." in out
    assert "## Example\n\n```python\nws.create_dashboard(params)\n```" in out
    assert "## Referenced types\n\n| Type | Summary |\n| --- | --- |\n" in out
    assert "| `Dashboard` | A Mixpanel dashboard as returned by the App API. |" in out
    assert (
        "## See also (dashboards)\n\n`add_report_to_dashboard`, `bulk_delete_dashboards`"
        in out
    )
    assert out.endswith(
        f"## Further reading\n\n- [{ENTITY_HINT.title}]({ENTITY_HINT.url})"
    )


def test_markdown_example_without_fence_is_wrapped() -> None:
    """An example that carries no fence is wrapped in a ``python`` fence."""
    entry = HelpEntry(
        kind="function",
        name="fn",
        qualname="m.fn",
        summary="S.",
        doc=DocSections(summary="S.", body="S.", example="fn(1)"),
        signature=SignatureDoc(name="fn"),
    )
    assert "## Example\n\n```python\nfn(1)\n```" in render_markdown(entry)


def test_markdown_class_tables_and_literal_tags(class_entry: HelpEntry) -> None:
    """Class markdown renders field, property, and method tables with literal tags."""
    out = render_markdown(class_entry)
    assert out.startswith("# Filter\n\n")
    assert "Inherits: (none)" in out
    assert "Config: `frozen=True`" in out
    assert (
        "## Construction\n\n```python\nFilter.equals(property, value, property_type='string')\n```"
        in out
    )
    assert (
        "## Fields\n\n| Field | Type | Default | Notes |\n| --- | --- | --- | --- |"
        in out
    )
    assert "| `property` | `str` | (required) |  |" in out
    assert (
        "| `operator` | `FilterOperatorInput` | `'equals'` | values: equals \\| not_equals |"
        in out
    )
    assert "| `name` | `str` | `'x'` | max_length=255; alias → displayName |" in out
    assert (
        "## Properties\n\n| Property | Summary |\n| --- | --- |\n| `is_empty` | [property] Whether the filter is empty. |"
        in out
    )
    assert (
        "## Methods\n\n| Method | Summary |\n| --- | --- |\n| `to_dict()` | Serialize the filter. |"
        in out
    )
    assert "## Used by Workspace\n\n- `query(where)`" in out


def test_markdown_listing_keeps_literal_tags() -> None:
    """Listing markdown keeps ``[property]`` and ``[method]`` as literal text."""
    out = render_markdown(ENTRIES["listing"])
    assert (
        "## Properties (1)\n\n| Name | Summary |\n| --- | --- |\n| `name` | [property] The name. |"
        in out
    )
    assert "| `query` | [method] Run a query. |" in out


def test_markdown_enum_literal_alias_exception_constant() -> None:
    """The remaining kinds render their headline blocks in markdown."""
    enum_md = render_markdown(ENTRIES["enum"])
    assert (
        "# enum Status\n\n| Member | Value |\n| --- | --- |\n| `ON` | `'on'` |"
        in enum_md
    )
    literal_md = render_markdown(ENTRIES["literal"])
    assert "```python\nMode = Literal[2 values]\n  a | b\n```" in literal_md
    assert "## Used by Workspace\n\n- `query(math)`" in literal_md
    alias_md = render_markdown(ENTRIES["alias"])
    assert "```python\nAccount = ServiceAccount | OAuthTokenAccount\n```" in alias_md
    assert "| `ServiceAccount` | Basic auth. |" in alias_md
    exc_md = render_markdown(ENTRIES["exception"])
    assert exc_md.startswith("# exception APIError(MixpanelHeadlessError)")
    assert (
        "## Subclasses\n\n| Name | Summary |\n| --- | --- |\n| `RateLimitError` | 429 |"
        in exc_md
    )
    assert "## Raised by Workspace\n\n- `query`" in exc_md
    const_md = render_markdown(ENTRIES["constant"])
    assert "```python\nBUSINESS_CONTEXT_MAX_CHARS: int = 65536\n```" in const_md
    param_md = render_markdown(ENTRIES["parameter"])
    assert "```python\nWorkspace.query.math: MathType = 'total'\n```" in param_md
    assert "**Allowed values:** `total`, `unique`" in param_md
    module_md = render_markdown(ENTRIES["module"])
    assert (
        "## Members\n\n| Member | Summary |\n| --- | --- |\n| `fn(x=1)` | Do it. |"
        in module_md
    )
    prop_md = render_markdown(ENTRIES["property"])
    assert "```python\nWorkspace.name -> str\n```" in prop_md


def test_markdown_escapes_pipes_in_cells() -> None:
    """A ``|`` inside a summary is escaped so the table stays valid."""
    entry = HelpEntry(
        kind="function",
        name="fn",
        qualname="m.fn",
        summary="S.",
        doc=DocSections(summary="S.", body="S."),
        signature=SignatureDoc(name="fn"),
        referenced_types=(("T", "a | b"),),
    )
    assert "| `T` | a \\| b |" in render_markdown(entry)


def test_markdown_has_no_trailing_newline_and_no_rich_markup(
    method_entry: HelpEntry,
) -> None:
    """Markdown output ends without a newline and contains no Rich close tags."""
    out = render_markdown(method_entry)
    assert not out.endswith("\n")
    assert "[/" not in out


# =============================================================================
# Helpers
# =============================================================================


def test_compact_signature_forms() -> None:
    """``_compact_signature`` prints names and defaults only, with an optional prefix."""
    sig = SignatureDoc(
        name="equals",
        params=(
            ParamDoc(name="property", annotation="str"),
            ParamDoc(name="value", annotation="object", default="None"),
        ),
        returns="Filter",
    )
    assert _compact_signature(sig) == "equals(property, value=None)"
    assert (
        _compact_signature(sig, prefix="Filter.")
        == "Filter.equals(property, value=None)"
    )
    assert _compact_signature(SignatureDoc(name="f")) == "f()"


def test_markdown_field_without_default_has_empty_default_cell() -> None:
    """An optional field with no recorded default prints an empty Default cell."""
    entry = HelpEntry(
        kind="model",
        name="P",
        qualname="m.P",
        summary="S.",
        doc=DocSections(summary="S.", body="S."),
        fields=(FieldDoc(name="note", annotation="str | None"),),
    )
    assert "| `note` | `str | None` |  |  |".replace("str | None", "str \\| None") in (
        render_markdown(entry)
    )


def test_markdown_enum_without_fields_lists_values_only() -> None:
    """Enum markdown falls back to ``values`` with an empty Value cell."""
    entry = HelpEntry(
        kind="enum",
        name="E",
        qualname="m.E",
        summary="S.",
        doc=DocSections(summary="S.", body="S."),
        values=("A",),
    )
    assert "| `A` |  |" in render_markdown(entry)


def test_markdown_module_with_groups_renders_group_tables() -> None:
    """Module markdown prefers ``groups`` over ``methods`` when groups exist."""
    entry = HelpEntry(
        kind="module",
        name="targets",
        qualname="mixpanel_headless.targets",
        summary="S.",
        doc=DocSections(summary="S.", body="S."),
        groups=(
            Group(
                title="Functions",
                items=(MemberDoc(name="use", kind="function", summary="Use."),),
            ),
        ),
    )
    out = render_markdown(entry)
    assert (
        "## Functions (1)\n\n| Name | Summary |\n| --- | --- |\n| `use` | Use. |" in out
    )
    assert "## Members" not in out
