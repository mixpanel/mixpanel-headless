"""Google-style docstring parser for the built-in API reference.

``parse_docstring`` splits a docstring into :class:`~.models.DocSections`.
It is pure: no imports of library objects, no I/O, and it never raises on
any string input.

Conventions (chosen here and locked by ``tests/unit/help/test_docstrings.py``):

- Input is normalized with ``inspect.cleandoc`` first, so a raw ``__doc__``
  and ``inspect.getdoc(obj)`` parse identically.
- A **header line** is a line whose stripped text starts with one of
  ``SECTION_HEADERS`` followed by ``:`` (case-sensitive). Any text after the
  colon on the same line is the first line of that section, which mirrors
  the ``startswith("Note:")`` rule of the plugin's ``help.py``.
- The **body** is everything before the first header line, dedented, with
  newlines kept. The **summary** is the first paragraph of the body with its
  lines joined by single spaces. ``first_line`` returns the first physical
  line instead, for listings.
- Before the first header, a header line at any indentation ends the body.
  Inside a section, a header line only ends that section when its
  indentation is not deeper than the section's own header. A ``Returns:``
  that appears inside an indented example block therefore stays in the
  example.
- ``Args:`` and ``Raises:`` become ``(name, description)`` pairs. The
  ``name (type):`` form reduces to ``name``. Continuation lines join the
  description with a single space.
- ``Returns:`` / ``Yields:``, ``Example:`` / ``Examples:``, and ``Note:`` /
  ``Notes:`` are dedented text with newlines kept. Repeated sections of one
  kind join with a blank line.
- ``Attributes:`` is recognized so that it ends the body, but its content is
  dropped: ``DocSections`` has no ``attributes`` field.
"""

from __future__ import annotations

import inspect
import re
import textwrap

from .models import DocSections

SECTION_HEADERS: tuple[str, ...] = (
    "Args",
    "Attributes",
    "Example",
    "Examples",
    "Note",
    "Notes",
    "Raises",
    "Returns",
    "Yields",
)
"""Google section header words recognized by ``parse_docstring`` (without the colon)."""

_HEADER_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<name>" + "|".join(SECTION_HEADERS) + r"):(?P<rest>.*)$"
)
"""Matches a section header line; ``rest`` holds any inline text after the colon."""

_ITEM_RE = re.compile(r"^(?P<name>[\w*.]+)\s*(?:\(.*?\))?\s*:(?P<desc>.*)$")
"""Matches an ``Args:`` / ``Raises:`` item line: ``name: desc`` or ``name (type): desc``."""

_Section = tuple[str, str, list[str]]
"""One raw section: ``(header_name, inline_text, content_lines)``."""


def parse_docstring(doc: str | None) -> DocSections:
    """Parse a Google-style docstring into ``DocSections``.

    Args:
        doc: Raw ``__doc__`` text, ``inspect.getdoc`` output, or ``None``.

    Returns:
        The parsed sections. ``None``, empty, and whitespace-only input yield
        ``DocSections()`` with every field empty.

    Example:
        ```python
        sections = parse_docstring(Workspace.create_dashboard.__doc__)
        sections.summary   # "Create a new dashboard."
        sections.args      # (("params", "Dashboard creation parameters."),)
        sections.raises[0] # ("ResponseValidationError", "Malformed API response ...")
        ```
    """
    if not doc or not doc.strip():
        return DocSections()
    preamble, sections = _split(inspect.cleandoc(doc))
    body = _clean_block(preamble)
    args: list[tuple[str, str]] = []
    raises: list[tuple[str, str]] = []
    returns: list[str] = []
    examples: list[str] = []
    notes: list[str] = []
    for name, inline, lines in sections:
        text = _section_text(inline, lines)
        if name == "Args":
            args.extend(_parse_items(text))
        elif name == "Raises":
            raises.extend(_parse_items(text))
        elif name in ("Returns", "Yields"):
            returns.append(text)
        elif name in ("Example", "Examples"):
            examples.append(text)
        elif name in ("Note", "Notes"):
            notes.append(text)
        # "Attributes" ends the body but has no home in DocSections.
    return DocSections(
        summary=_first_paragraph(body),
        body=body,
        args=tuple(args),
        returns=_join_blocks(returns),
        raises=tuple(raises),
        example=_join_blocks(examples),
        notes=_join_blocks(notes),
    )


def first_line(doc: str | None) -> str:
    """Return the first non-empty line of a docstring's summary, stripped.

    Used by listings, which show one physical line per member. A docstring
    that starts with a section header has no summary, so the result is ``""``.

    Args:
        doc: Raw ``__doc__`` text, ``inspect.getdoc`` output, or ``None``.

    Returns:
        The first non-blank line before any section header, or ``""``.

    Example:
        ```python
        first_line("Run a query against\\nthe API.")  # "Run a query against"
        first_line("Args:\\n    x: X.")                # ""
        ```
    """
    if not doc:
        return ""
    for line in inspect.cleandoc(doc).split("\n"):
        if _HEADER_RE.match(line):
            return ""
        if line.strip():
            return line.strip()
    return ""


def _split(text: str) -> tuple[list[str], list[_Section]]:
    """Split cleaned docstring text into the preamble and raw sections.

    Args:
        text: Output of ``inspect.cleandoc``.

    Returns:
        ``(preamble_lines, sections)`` where each section is
        ``(header_name, inline_text, content_lines)`` in source order.
    """
    preamble: list[str] = []
    sections: list[_Section] = []
    current: list[str] | None = None
    current_indent = 0
    for line in text.split("\n"):
        match = _HEADER_RE.match(line)
        if match and (current is None or len(match["indent"]) <= current_indent):
            current = []
            current_indent = len(match["indent"])
            sections.append((match["name"], match["rest"].strip(), current))
        elif current is None:
            preamble.append(line)
        else:
            current.append(line)
    return preamble, sections


def _clean_block(lines: list[str]) -> str:
    """Dedent a block of lines and trim surrounding blank lines.

    Args:
        lines: Raw lines of one section or of the preamble.

    Returns:
        The dedented text with trailing whitespace removed from every line and
        leading and trailing blank lines dropped. Empty when nothing remains.
    """
    stripped = [line.rstrip() for line in lines]
    while stripped and not stripped[0]:
        stripped.pop(0)
    while stripped and not stripped[-1]:
        stripped.pop()
    return textwrap.dedent("\n".join(stripped))


def _section_text(inline: str, lines: list[str]) -> str:
    """Combine a header's inline text with its dedented content lines.

    Args:
        inline: Text that followed the header colon on the same line (may be ``""``).
        lines: Content lines below the header.

    Returns:
        The section text: inline text first, then the dedented block.
    """
    block = _clean_block(lines)
    if inline and block:
        return f"{inline}\n{block}"
    return inline or block


def _parse_items(text: str) -> list[tuple[str, str]]:
    """Parse ``Args:`` / ``Raises:`` content into ``(name, description)`` pairs.

    An item starts on a flush-left line matching ``name: desc`` or
    ``name (type): desc``. Indented lines, and flush-left lines that do not
    look like an item, continue the previous description. Text before the
    first item is dropped. Blank lines are ignored.

    Args:
        text: Dedented section text.

    Returns:
        Pairs in source order; descriptions are single-line with one space
        between joined fragments.
    """
    items: list[tuple[str, list[str]]] = []
    for line in text.split("\n"):
        if not line.strip():
            continue
        match = None if line[0].isspace() else _ITEM_RE.match(line)
        if match:
            desc = match["desc"].strip()
            items.append((match["name"], [desc] if desc else []))
        elif items:
            items[-1][1].append(line.strip())
    return [(name, " ".join(parts)) for name, parts in items]


def _first_paragraph(body: str) -> str:
    """Return the first paragraph of the body with lines joined by single spaces.

    Args:
        body: Dedented preamble text.

    Returns:
        The joined first paragraph, or ``""`` for an empty body.
    """
    lines: list[str] = []
    for line in body.split("\n"):
        if not line.strip():
            if lines:
                break
            continue
        lines.append(line.strip())
    return " ".join(lines)


def _join_blocks(blocks: list[str]) -> str:
    """Join non-empty section texts with one blank line between them.

    Args:
        blocks: Section texts of one kind in source order.

    Returns:
        The joined text, or ``""`` when every block is empty.
    """
    return "\n\n".join(block for block in blocks if block)


__all__ = ["SECTION_HEADERS", "first_line", "parse_docstring"]
