"""Repository guards G1-G10 for the ``mixpanel-plugin/`` content.

The plugin's skills point at the library's built-in reference (``mp help``)
instead of copying signatures. These guards keep the remaining text honest
against the installed library, and keep the skill structure inside its
budgets. Every guard is offline and reports every violation (file, line,
reason) in one assertion message.

| Guard | Fails when |
| --- | --- |
| G1 | A help query in plugin markdown does not resolve. |
| G2 | A ``ws.<name>`` in a Python block is not a ``Workspace`` member. |
| G3 | A keyword argument in a ``ws.<method>(...)`` call is not a parameter. |
| G4 | A ``mixpanel_headless`` import or ``mp.X`` names a non-public object. |
| G5 | A ```` ```python ```` block does not parse. |
| G6 | A skill or reference file is over its size budget. |
| G7 | A relative link is broken, crosses skills, or a reference is orphaned. |
| G8 | Skill frontmatter breaks the name, length, or key rules. |
| G9 | Shipped text carries removed names, Cowork, plan codes, or all-caps rules. |
| G10 | ``setup.sh`` pins a floor below the version that added ``mp help``. |

Scanners live in ``_content.py`` and have their own tests in
``test_content_helpers.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.unit.plugin._content import (
    PLUGIN_ROOT,
    PYTHON_LANGS,
    SKILLS_ROOT,
    check_help_query,
    extract_help_queries,
    forbidden_text_violations,
    has_contents_list,
    import_violations,
    is_external,
    iter_links,
    markdown_blocks,
    parse_frontmatter,
    parse_version_floor,
    plugin_markdown_files,
    read,
    reference_files,
    rel,
    report,
    shipped_text_files,
    skill_dirs,
    workspace_call_violations,
)

HELP_FLOOR = (0, 3, 0)
"""The ``mixpanel_headless`` version that introduced ``mp help``."""

ANY_SKILL_MAX_LINES = 500
"""Line budget for any ``SKILL.md``."""

SKILL_MAX_LINES = {
    "mixpanelyst": 250,
    "dashboard-expert": 250,
    "session-replay": 200,
    "setup": 120,
}
"""Tighter per-skill line budgets for ``SKILL.md``."""

REFERENCE_TOC_THRESHOLD = 100
"""A reference file longer than this needs a contents list at the top."""

DESCRIPTION_MAX_CHARS = 1024
"""Maximum length of a skill ``description``."""

PORTABLE_KEYS = frozenset(
    {"name", "description", "allowed-tools", "license", "compatibility", "metadata"}
)
"""Frontmatter keys allowed on every skill."""

EXTRA_KEYS = {
    "setup": frozenset({"disable-model-invocation"}),
    "auth": frozenset({"argument-hint"}),
}
"""Frontmatter keys allowed on one skill only."""

CAPS_EXEMPT = frozenset({SKILLS_ROOT / "auth" / "SKILL.md"})
"""Files whose security rules may use all-caps ALWAYS / NEVER / MUST."""


def _python_blocks() -> list[tuple[Path, int, str]]:
    """Collect every Python fence in shipped plugin markdown.

    Returns:
        ``(path, first_line, source)`` for each ```` ```python ```` block.
    """
    return [
        (block.path, block.line, block.text)
        for path in plugin_markdown_files()
        for block in markdown_blocks(path)
        if block.lang in PYTHON_LANGS
    ]


class TestG1HelpQueries:
    """G1: every help query in plugin markdown resolves."""

    def test_help_queries_resolve(self) -> None:
        """Each ``mp help`` / ``mp.help()`` query resolves via the reference API.

        Covers ``mp help <query>``, ``python3 -m mixpanel_headless help
        <query>``, and ``mp.help("<query>")``; ``search <term>`` needs at
        least one hit, and a ``--domain`` value must name a real domain.
        """
        violations: list[str] = []
        for path in plugin_markdown_files():
            for query in extract_help_queries(path, read(path)):
                reason = check_help_query(query.query, query.domain)
                if reason:
                    violations.append(
                        f"{rel(query.path)}:{query.line}: {reason} [{query.raw}]"
                    )
        assert not violations, report("G1 help queries resolve", violations)


class TestG2WorkspaceMembers:
    """G2: every ``ws.<name>`` in a Python block exists on ``Workspace``."""

    def test_workspace_members_exist(self) -> None:
        """Each ``ws.<name>`` names a real ``Workspace`` method or property."""
        violations: list[str] = []
        for path in plugin_markdown_files():
            for block in markdown_blocks(path):
                if block.lang in PYTHON_LANGS:
                    violations.extend(workspace_call_violations(block)[0])
        assert not violations, report("G2 Workspace calls exist", violations)


class TestG3KeywordArguments:
    """G3: every keyword in a ``ws.<method>(...)`` call is a real parameter."""

    def test_keyword_arguments_exist(self) -> None:
        """Each keyword is a parameter of the method (unless it takes ``**kwargs``)."""
        violations: list[str] = []
        for path in plugin_markdown_files():
            for block in markdown_blocks(path):
                if block.lang in PYTHON_LANGS:
                    violations.extend(workspace_call_violations(block)[1])
        assert not violations, report("G3 keyword arguments exist", violations)


class TestG4PublicImports:
    """G4: Python blocks use only public ``mixpanel_headless`` names."""

    def test_imports_are_public(self) -> None:
        """Each import and ``mp.X`` access names a public object."""
        violations: list[str] = []
        for path in plugin_markdown_files():
            for block in markdown_blocks(path):
                if block.lang in PYTHON_LANGS:
                    violations.extend(import_violations(block))
        assert not violations, report("G4 imports exist", violations)


class TestG5PythonParses:
    """G5: every Python block parses."""

    def test_python_blocks_parse(self) -> None:
        """Each ```` ```python ```` block parses with ``ast.parse``."""
        violations: list[str] = []
        for path, line, source in _python_blocks():
            try:
                ast.parse(source)
            except SyntaxError as exc:
                where = line + (exc.lineno or 1) - 1
                violations.append(
                    f"{rel(path)}:{where}: does not parse ({exc.msg}); "
                    "use ```text for pseudo-code"
                )
        assert not violations, report("G5 Python blocks parse", violations)


class TestG6SizeBudgets:
    """G6: skill entry files and reference files stay inside their budgets."""

    def test_skill_line_budgets(self) -> None:
        """Each ``SKILL.md`` fits the general and per-skill line budgets."""
        violations: list[str] = []
        for skill in skill_dirs():
            entry = skill / "SKILL.md"
            if not entry.is_file():
                continue
            lines = len(read(entry).splitlines())
            budget = min(ANY_SKILL_MAX_LINES, SKILL_MAX_LINES.get(skill.name, 10**9))
            if lines > budget:
                violations.append(f"{rel(entry)}:1: {lines} lines > budget {budget}")
        assert not violations, report("G6 skill size budgets", violations)

    def test_long_references_have_contents(self) -> None:
        """A reference file over 100 lines starts with a contents list."""
        violations: list[str] = []
        for skill in skill_dirs():
            for ref in reference_files(skill):
                text = read(ref)
                lines = len(text.splitlines())
                if lines > REFERENCE_TOC_THRESHOLD and not has_contents_list(text):
                    violations.append(
                        f"{rel(ref)}:1: {lines} lines and no contents list at the top"
                    )
        assert not violations, report("G6 reference contents lists", violations)


class TestG7Links:
    """G7: links resolve, stay inside their skill, and references stay one deep."""

    def test_relative_links_resolve(self) -> None:
        """Each relative link resolves inside the plugin and inside its own skill."""
        violations: list[str] = []
        for path in plugin_markdown_files():
            skill = _skill_of(path)
            for line, target in iter_links(path, read(path)):
                if is_external(target):
                    continue
                where = f"{rel(path)}:{line}"
                target_path = target.split("#", 1)[0]
                if target_path.startswith("/"):
                    violations.append(f"{where}: absolute link {target!r}")
                    continue
                resolved = (path.parent / target_path).resolve()
                if not resolved.exists():
                    violations.append(f"{where}: broken link {target!r}")
                elif not resolved.is_relative_to(PLUGIN_ROOT.resolve()):
                    violations.append(f"{where}: link leaves the plugin {target!r}")
                elif skill is not None and _skill_of(resolved) not in {None, skill}:
                    violations.append(f"{where}: link into another skill {target!r}")
        assert not violations, report("G7 relative links", violations)

    def test_references_are_linked_from_skill(self) -> None:
        """Each reference file is named by its skill's ``SKILL.md``.

        A markdown link or a ``references/<file>`` mention (for example in a
        reading-guide table) both count.
        """
        violations: list[str] = []
        for skill in skill_dirs():
            entry = skill / "SKILL.md"
            text = read(entry) if entry.is_file() else ""
            for ref in reference_files(skill):
                name = ref.relative_to(skill).as_posix()
                if name not in text:
                    violations.append(f"{rel(ref)}:1: not referenced from {rel(entry)}")
        assert not violations, report("G7 orphan references", violations)

    def test_references_do_not_link_references(self) -> None:
        """A reference file does not link to or name another reference file."""
        violations: list[str] = []
        for skill in skill_dirs():
            for ref in reference_files(skill):
                text = read(ref)
                for line, target in iter_links(ref, text):
                    if is_external(target):
                        continue
                    resolved = (ref.parent / target.split("#", 1)[0]).resolve()
                    if resolved != ref.resolve() and "references" in resolved.parts:
                        violations.append(
                            f"{rel(ref)}:{line}: links another reference {target!r}"
                        )
                for number, content in enumerate(text.splitlines(), start=1):
                    for other in reference_files(skill):
                        mention = f"references/{other.name}"
                        if other != ref and mention in content:
                            violations.append(
                                f"{rel(ref)}:{number}: names another reference "
                                f"{mention!r}"
                            )
        assert not violations, report("G7 one-level references", violations)


def _skill_of(path: Path) -> str | None:
    """Return the skill directory name that holds a path.

    Args:
        path: Any path.

    Returns:
        The skill name for paths under ``mixpanel-plugin/skills/<name>/``,
        else ``None``.
    """
    try:
        parts = path.resolve().relative_to(SKILLS_ROOT.resolve()).parts
    except ValueError:
        return None
    return parts[0] if len(parts) > 1 else None


class TestG8Frontmatter:
    """G8: skill frontmatter follows the name, length, and key rules."""

    def test_frontmatter(self) -> None:
        """Each skill has frontmatter with a matching name, a short description, allowed keys."""
        violations: list[str] = []
        for skill in skill_dirs():
            entry = skill / "SKILL.md"
            where = f"{rel(entry)}:1"
            if not entry.is_file():
                violations.append(f"{where}: skill directory has no SKILL.md")
                continue
            meta = parse_frontmatter(read(entry))
            if meta is None:
                violations.append(f"{where}: no frontmatter")
                continue
            if meta.get("name") != skill.name:
                violations.append(
                    f"{where}: name {meta.get('name')!r} != directory {skill.name!r}"
                )
            description = meta.get("description", "")
            if not description:
                violations.append(f"{where}: no description")
            elif len(description) > DESCRIPTION_MAX_CHARS:
                violations.append(
                    f"{where}: description is {len(description)} chars "
                    f"> {DESCRIPTION_MAX_CHARS}"
                )
            allowed = PORTABLE_KEYS | EXTRA_KEYS.get(skill.name, frozenset())
            for key in sorted(set(meta) - allowed):
                violations.append(f"{where}: key {key!r} is not allowed here")
        assert not violations, report("G8 frontmatter", violations)


class TestG9ForbiddenText:
    """G9: shipped text carries no removed names, plan codes, or shouting."""

    def test_no_forbidden_text(self) -> None:
        """No ``help.py``, ``ai-plugins``, Cowork, plan codes, or all-caps rule words.

        The all-caps check applies to markdown only, and not to the ``auth``
        skill, whose security rules are the one place firm rules stay.
        """
        violations: list[str] = []
        for path in shipped_text_files():
            if "cowork" in rel(path).lower():
                violations.append(f"{rel(path)}:1: file name mentions Cowork")
            caps_allowed = path.suffix != ".md" or path in CAPS_EXEMPT
            violations.extend(
                forbidden_text_violations(path, read(path), caps_allowed=caps_allowed)
            )
        assert not violations, report("G9 forbidden text", violations)


class TestG10VersionFloor:
    """G10: ``setup.sh`` installs a library that has ``mp help``."""

    def test_setup_floor(self) -> None:
        """The ``mixpanel-headless>=`` floor in ``setup.sh`` is at least 0.3.0."""
        script = SKILLS_ROOT / "setup" / "scripts" / "setup.sh"
        floor = parse_version_floor(read(script))
        expected = ".".join(map(str, HELP_FLOOR))
        assert floor is not None, (
            f"G10 version floor: {rel(script)} does not pin mixpanel-headless>={expected}"
        )
        assert floor >= HELP_FLOOR, (
            f"G10 version floor: {rel(script)} pins "
            f">={'.'.join(map(str, floor))}, needs >={expected}"
        )
