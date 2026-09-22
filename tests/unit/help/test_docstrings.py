"""Unit tests for ``mixpanel_headless._internal.help.docstrings``.

``parse_docstring`` splits a Google-style docstring into ``DocSections``.
These tests cover each section header and edge case with small literal
docstrings, plus structural assertions on real docstrings from the library.
"""

from __future__ import annotations

import inspect

import pytest

import mixpanel_headless as mp
from mixpanel_headless._internal.help.docstrings import (
    SECTION_HEADERS,
    first_line,
    parse_docstring,
)
from mixpanel_headless._internal.help.models import DocSections

# =============================================================================
# Empty input and header table
# =============================================================================


@pytest.mark.parametrize("doc", [None, "", "   ", "\n\n", "\n    \n"])
def test_empty_input_yields_empty_sections(doc: str | None) -> None:
    """``None``, empty, and whitespace-only docstrings yield an all-empty result.

    Args:
        doc: The docstring under test.
    """
    assert parse_docstring(doc) == DocSections()


def test_section_headers_table() -> None:
    """``SECTION_HEADERS`` lists every recognized Google header word once."""
    expected = {
        "Args",
        "Attributes",
        "Example",
        "Examples",
        "Note",
        "Notes",
        "Raises",
        "Returns",
        "Yields",
    }
    assert set(SECTION_HEADERS) == expected
    assert len(SECTION_HEADERS) == len(set(SECTION_HEADERS))


# =============================================================================
# Summary and body
# =============================================================================


def test_single_line_docstring() -> None:
    """A one-line docstring is both the summary and the body."""
    result = parse_docstring("Do the thing.")
    assert result.summary == "Do the thing."
    assert result.body == "Do the thing."
    assert result.args == ()
    assert result.returns == ""
    assert result.raises == ()
    assert result.example == ""
    assert result.notes == ""


def test_summary_is_first_paragraph_joined_with_spaces() -> None:
    """The summary joins the lines of the first paragraph with single spaces."""
    doc = "Run a query against\nthe API.\n\nSecond paragraph\nspans lines."
    result = parse_docstring(doc)
    assert result.summary == "Run a query against the API."


def test_body_is_everything_before_first_header() -> None:
    """The body keeps every paragraph before the first header, verbatim."""
    doc = "Run a query against\nthe API.\n\nSecond paragraph\nspans lines.\n\nArgs:\n    x: X."
    result = parse_docstring(doc)
    assert (
        result.body == "Run a query against\nthe API.\n\nSecond paragraph\nspans lines."
    )


def test_summary_stops_at_first_header() -> None:
    """Text before ``Args:`` is the summary; the header itself is not included."""
    doc = "Summary line.\n\nArgs:\n    x: X."
    result = parse_docstring(doc)
    assert result.summary == "Summary line."
    assert result.body == "Summary line."


def test_docstring_starting_with_header_has_empty_summary() -> None:
    """A docstring whose first line is a header has no summary or body."""
    result = parse_docstring("Args:\n    x: X.")
    assert result.summary == ""
    assert result.body == ""
    assert result.args == (("x", "X."),)


def test_lowercase_header_is_not_a_header() -> None:
    """Header matching is case-sensitive; ``args:`` stays in the body."""
    result = parse_docstring("Summary.\n\nargs:\n    x: X.")
    assert result.args == ()
    assert "args:" in result.body


def test_header_word_without_colon_is_not_a_header() -> None:
    """``Returns`` without a colon is ordinary text."""
    result = parse_docstring("Returns the thing.\n\nReturns\nnothing")
    assert result.returns == ""
    assert result.summary == "Returns the thing."


def test_raw_docstring_is_cleaned_like_inspect_getdoc() -> None:
    """A raw, indented ``__doc__`` parses the same as its ``inspect.cleandoc`` form."""
    raw = """Summary line.

        Longer text.

        Args:
            x: The x.

        Returns:
            Nothing.
        """
    assert parse_docstring(raw) == parse_docstring(inspect.cleandoc(raw))
    assert parse_docstring(raw).body == "Summary line.\n\nLonger text."


# =============================================================================
# Args
# =============================================================================


def test_args_simple_pairs() -> None:
    """Each ``name: description`` line becomes one pair, in order."""
    doc = "S.\n\nArgs:\n    a: First.\n    b: Second."
    assert parse_docstring(doc).args == (("a", "First."), ("b", "Second."))


def test_args_continuation_lines_joined_with_single_space() -> None:
    """Indented continuation lines join the description with one space."""
    doc = "S.\n\nArgs:\n    events: Event name(s) to query.\n        Accepts a string\n        or a list.\n    where: Filter."
    assert parse_docstring(doc).args == (
        ("events", "Event name(s) to query. Accepts a string or a list."),
        ("where", "Filter."),
    )


def test_args_type_in_parentheses_is_dropped() -> None:
    """``name (type): desc`` reduces to ``name``."""
    doc = "S.\n\nArgs:\n    count (int): How many.\n    opts (dict[str, int], optional): Options."
    assert parse_docstring(doc).args == (("count", "How many."), ("opts", "Options."))


def test_args_star_names() -> None:
    """``*args`` and ``**kwargs`` names are kept with their stars."""
    doc = "S.\n\nArgs:\n    *args: Positional.\n    **kwargs: Keyword."
    assert parse_docstring(doc).args == (
        ("*args", "Positional."),
        ("**kwargs", "Keyword."),
    )


def test_args_item_without_description() -> None:
    """``name:`` with nothing after it yields an empty description."""
    doc = "S.\n\nArgs:\n    x:\n    y: Y."
    assert parse_docstring(doc).args == (("x", ""), ("y", "Y."))


def test_args_description_containing_colon() -> None:
    """Only the first ``:`` after the name splits name from description."""
    doc = 'S.\n\nArgs:\n    unit: Time unit. Default: ``"day"``.'
    assert parse_docstring(doc).args == (("unit", 'Time unit. Default: ``"day"``.'),)


def test_args_blank_line_between_items_is_ignored() -> None:
    """Blank lines inside ``Args:`` do not create empty entries."""
    doc = "S.\n\nArgs:\n    a: A.\n\n    b: B."
    assert parse_docstring(doc).args == (("a", "A."), ("b", "B."))


def test_args_unindented_free_text_joins_previous_item() -> None:
    """A non-item line at item indent joins the previous description."""
    doc = "S.\n\nArgs:\n    a: A starts here\n    and continues badly.\n    b: B."
    assert parse_docstring(doc).args == (
        ("a", "A starts here and continues badly."),
        ("b", "B."),
    )


def test_args_leading_free_text_without_item_is_dropped() -> None:
    """Free text before the first ``Args:`` item is dropped."""
    doc = "S.\n\nArgs:\n    Some intro sentence\n    a: A."
    assert parse_docstring(doc).args == (("a", "A."),)


def test_args_empty_section() -> None:
    """An ``Args:`` header with no items yields no pairs."""
    doc = "S.\n\nArgs:\n\nReturns:\n    R."
    result = parse_docstring(doc)
    assert result.args == ()
    assert result.returns == "R."


def test_two_args_sections_are_concatenated() -> None:
    """A second ``Args:`` section appends to the first."""
    doc = "S.\n\nArgs:\n    a: A.\n\nReturns:\n    R.\n\nArgs:\n    b: B."
    assert parse_docstring(doc).args == (("a", "A."), ("b", "B."))


# =============================================================================
# Returns, Yields, Raises
# =============================================================================


def test_returns_text() -> None:
    """``Returns:`` content is dedented text."""
    doc = "S.\n\nReturns:\n    The newly created ``Dashboard``."
    assert parse_docstring(doc).returns == "The newly created ``Dashboard``."


def test_returns_multiline_keeps_newlines() -> None:
    """Multi-line ``Returns:`` keeps its line breaks after dedent."""
    doc = "S.\n\nReturns:\n    A result with\n    two lines.\n\n    And a paragraph."
    assert (
        parse_docstring(doc).returns == "A result with\ntwo lines.\n\nAnd a paragraph."
    )


def test_yields_maps_to_returns() -> None:
    """``Yields:`` content is stored in ``returns``."""
    doc = "S.\n\nYields:\n    Each event dict."
    assert parse_docstring(doc).returns == "Each event dict."


def test_returns_and_yields_both_present_are_joined() -> None:
    """When both ``Returns:`` and ``Yields:`` appear, texts join with a blank line."""
    doc = "S.\n\nReturns:\n    R.\n\nYields:\n    Y."
    assert parse_docstring(doc).returns == "R.\n\nY."


def test_returns_inline_text_after_header() -> None:
    """Text on the same line as ``Returns:`` is the section content."""
    doc = "S.\n\nReturns: The count."
    assert parse_docstring(doc).returns == "The count."


def test_raises_pairs() -> None:
    """``Raises:`` yields ``(ExceptionName, description)`` pairs."""
    doc = "S.\n\nRaises:\n    ValueError: If bad.\n    httpx.HTTPError: On network\n        failure."
    assert parse_docstring(doc).raises == (
        ("ValueError", "If bad."),
        ("httpx.HTTPError", "On network failure."),
    )


# =============================================================================
# Example, Note, Attributes
# =============================================================================


def test_example_block_kept_verbatim_with_fences() -> None:
    """``Example:`` content is dedented but otherwise verbatim, fences included."""
    doc = "S.\n\nExample:\n    ```python\n    ws = Workspace()\n\n    ws.query(\n        events=['Login'],\n    )\n    ```"
    assert parse_docstring(doc).example == (
        "```python\nws = Workspace()\n\nws.query(\n    events=['Login'],\n)\n```"
    )


def test_examples_header_maps_to_example() -> None:
    """``Examples:`` is stored in ``example``."""
    doc = "S.\n\nExamples:\n    x = 1"
    assert parse_docstring(doc).example == "x = 1"


def test_two_example_sections_joined_with_blank_line() -> None:
    """``Example:`` followed by ``Examples:`` joins with one blank line."""
    doc = "S.\n\nExample:\n    a\n\nExamples:\n    b"
    assert parse_docstring(doc).example == "a\n\nb"


def test_header_like_line_inside_example_content_stays_in_example() -> None:
    """A header word indented deeper than the section header stays in the section."""
    doc = "S.\n\nExample:\n    ```text\n    Args:\n        shown as text\n    ```\n\nReturns:\n    R."
    result = parse_docstring(doc)
    assert result.example == "```text\nArgs:\n    shown as text\n```"
    assert result.args == ()
    assert result.returns == "R."


def test_note_and_notes_map_to_notes() -> None:
    """``Note:`` and ``Notes:`` both feed ``notes``; multiple notes join with a blank line."""
    doc = "S.\n\nNote:\n    First.\n\nNotes:\n    Second\n    line."
    assert parse_docstring(doc).notes == "First.\n\nSecond\nline."


def test_inline_note_in_summary_terminates_summary() -> None:
    """``Note: text`` on one line ends the summary and becomes the note (script parity)."""
    doc = "Summary here.\nNote: ``x`` is immutable.\nTrailing line."
    result = parse_docstring(doc)
    assert result.summary == "Summary here."
    assert result.body == "Summary here."
    assert result.notes == "``x`` is immutable.\nTrailing line."


def test_attributes_header_terminates_summary_and_is_dropped() -> None:
    """``Attributes:`` ends the summary; its content is not stored anywhere."""
    doc = "A model.\n\nAttributes:\n    id: The id.\n    name: The name.\n\nExample:\n    m = Model()"
    result = parse_docstring(doc)
    assert result.summary == "A model."
    assert result.body == "A model."
    assert result.args == ()
    assert result.example == "m = Model()"
    assert "The id." not in result.notes
    assert "The id." not in result.returns


# =============================================================================
# Indented headers
# =============================================================================


def test_headers_indented_by_four_spaces() -> None:
    """Headers indented by four spaces (content at eight) parse the same as flush headers."""
    doc = "Summary.\n\n    Args:\n        a: A.\n        b: B\n            continued.\n\n    Returns:\n        R.\n\n    Example:\n        code()"
    result = parse_docstring(doc)
    assert result.summary == "Summary."
    assert result.body == "Summary."
    assert result.args == (("a", "A."), ("b", "B continued."))
    assert result.returns == "R."
    assert result.example == "code()"


def test_trailing_blank_lines_in_sections_are_trimmed() -> None:
    """Blank lines at the end of a section are removed from its text."""
    doc = "S.\n\nReturns:\n    R.\n\n\n"
    assert parse_docstring(doc).returns == "R."


def test_full_google_docstring() -> None:
    """A complete docstring with every section parses into the expected model."""
    doc = (
        "Create a new dashboard.\n"
        "\n"
        "Args:\n"
        "    params: Dashboard creation parameters.\n"
        "\n"
        "Returns:\n"
        "    The newly created ``Dashboard``.\n"
        "\n"
        "Raises:\n"
        "    ConfigError: If credentials are not available.\n"
        "    QueryError: Invalid parameters (400, 422).\n"
        "\n"
        "Example:\n"
        "    ```python\n"
        "    ws = Workspace()\n"
        "    ```\n"
        "\n"
        "Note:\n"
        "    Needs the App API.\n"
    )
    assert parse_docstring(doc) == DocSections(
        summary="Create a new dashboard.",
        body="Create a new dashboard.",
        args=(("params", "Dashboard creation parameters."),),
        returns="The newly created ``Dashboard``.",
        raises=(
            ("ConfigError", "If credentials are not available."),
            ("QueryError", "Invalid parameters (400, 422)."),
        ),
        example="```python\nws = Workspace()\n```",
        notes="Needs the App API.",
    )


# =============================================================================
# first_line
# =============================================================================


@pytest.mark.parametrize("doc", [None, "", "  \n  "])
def test_first_line_empty(doc: str | None) -> None:
    """``first_line`` returns an empty string for empty input.

    Args:
        doc: The docstring under test.
    """
    assert first_line(doc) == ""


def test_first_line_returns_first_non_empty_line() -> None:
    """``first_line`` skips leading blank lines and strips the result."""
    assert first_line("\n\n   Run a query.  \n   More.") == "Run a query."


def test_first_line_ignores_sections() -> None:
    """``first_line`` on a docstring that starts with a header is empty."""
    assert first_line("Args:\n    x: X.") == ""


def test_first_line_is_the_first_physical_line_not_the_paragraph() -> None:
    """``first_line`` returns one physical line even when the summary paragraph wraps."""
    assert first_line("Run a query against\nthe API.") == "Run a query against"


# =============================================================================
# Real library docstrings (structure only, not exact text)
# =============================================================================


def test_real_workspace_query_docstring() -> None:
    """``Workspace.query`` parses with args, returns, and an example."""
    result = parse_docstring(mp.Workspace.query.__doc__)
    names = [name for name, _ in result.args]
    assert result.summary.startswith("Run a typed insights query")
    assert "events" in names
    assert "where" in names
    assert "unit" in names
    assert len(names) == len(set(names))
    assert all(description for _, description in result.args)
    assert "\n" not in dict(result.args)["events"]
    assert result.returns
    assert "```python" in result.example
    assert result.body.startswith(result.summary.split(" ")[0])


def test_real_workspace_create_dashboard_docstring() -> None:
    """``Workspace.create_dashboard`` parses args, returns, raises, and example."""
    result = parse_docstring(inspect.getdoc(mp.Workspace.create_dashboard))
    assert result.summary == "Create a new dashboard."
    assert result.args == (("params", "Dashboard creation parameters."),)
    assert "Dashboard" in result.returns
    raised = [name for name, _ in result.raises]
    assert "ConfigError" in raised
    assert "AuthenticationError" in raised
    assert "```python" in result.example
    assert "CreateDashboardParams" in result.example


def test_real_filter_class_docstring() -> None:
    """``Filter`` parses a multi-line summary and an example block."""
    result = parse_docstring(mp.Filter.__doc__)
    assert result.summary == "Represents a typed filter condition on a property."
    assert "factory classmethods" in result.body
    assert "Filter.equals" in result.example
    assert result.args == ()


def test_every_workspace_parameter_has_a_description() -> None:
    """Every ``Workspace`` method parameter has a non-empty ``Args:`` description.

    ``_parse_items`` drops ``Args:`` lines that do not look like ``name: desc``,
    so a malformed entry would surface here as a missing description.
    """
    prefixes: dict[inspect._ParameterKind, str] = {
        inspect.Parameter.VAR_POSITIONAL: "*",
        inspect.Parameter.VAR_KEYWORD: "**",
    }
    checked = 0
    for name, value in vars(mp.Workspace).items():
        if name.startswith("_") or not inspect.isfunction(value):
            continue
        described = dict(parse_docstring(inspect.getdoc(value)).args)
        for pname, param in inspect.signature(value).parameters.items():
            if pname == "self":
                continue
            prefix = prefixes.get(param.kind, "")
            description = described.get(f"{prefix}{pname}") or described.get(pname)
            assert description, (
                f"Workspace.{name}: parameter {pname!r} has no description"
            )
            checked += 1
    assert checked >= 500


def test_every_public_export_docstring_parses() -> None:
    """``parse_docstring`` never raises on any public export or ``Workspace`` member."""
    objects: list[object] = [getattr(mp, name) for name in sorted(set(mp.__all__))]
    objects.extend(
        getattr(mp.Workspace, name)
        for name in dir(mp.Workspace)
        if not name.startswith("_")
    )
    parsed = 0
    for obj in objects:
        doc = inspect.getdoc(obj)
        result = parse_docstring(doc)
        assert isinstance(result, DocSections)
        if doc:
            parsed += 1
            assert " ".join(result.body.split()).startswith(
                " ".join(result.summary.split())
            )
    assert parsed > 200
