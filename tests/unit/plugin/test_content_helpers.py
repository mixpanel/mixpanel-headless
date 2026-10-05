"""Unit tests for the plugin-content scanners in ``tests/unit/plugin/_content.py``.

The guards in ``test_plugin_content.py`` run these scanners over the real
plugin files. The tests here pin the scanners themselves on small synthetic
markdown samples, so a guard that passes means the content is right, not
that the scanner missed it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.plugin._content import (
    CodeBlock,
    allowed_tools_violations,
    check_help_query,
    extract_help_queries,
    forbidden_text_violations,
    has_contents_list,
    import_violations,
    injection_violations,
    iter_links,
    parse_frontmatter,
    parse_help_args,
    parse_version_floor,
    split_markdown,
    system_python_violations,
    workspace_call_violations,
)

SAMPLE = Path("sample.md")
"""Placeholder path used in synthetic scans (never read from disk)."""


def _block(source: str, line: int = 1) -> CodeBlock:
    """Build a Python ``CodeBlock`` for the AST-based scanners.

    Args:
        source: The Python source of the block.
        line: The 1-based file line of the first source line.

    Returns:
        A ``CodeBlock`` with language ``python`` at ``SAMPLE``.
    """
    return CodeBlock(path=SAMPLE, line=line, lang="python", text=source)


# =============================================================================
# Markdown splitting
# =============================================================================


class TestSplitMarkdown:
    """``split_markdown`` separates fenced blocks from prose lines."""

    def test_fence_language_line_and_text(self) -> None:
        """A fence yields its language, first code line number, and body."""
        text = "intro\n\n```python\nx = 1\ny = 2\n```\nafter\n"
        blocks, prose = split_markdown(SAMPLE, text)
        assert len(blocks) == 1
        assert blocks[0].lang == "python"
        assert blocks[0].line == 4
        assert blocks[0].text == "x = 1\ny = 2\n"
        assert [n for n, _ in prose] == [1, 2, 7]

    def test_indented_fence_is_dedented(self) -> None:
        """A fence nested in a list item is dedented before parsing."""
        text = "1. Step\n\n   ```python\n   x = 1\n   ```\n"
        blocks, _ = split_markdown(SAMPLE, text)
        assert blocks[0].text == "x = 1\n"

    def test_tilde_fence_and_no_language(self) -> None:
        """Tilde fences and fences without a language are recognized."""
        text = "~~~\nmp help Filter\n~~~\n"
        blocks, prose = split_markdown(SAMPLE, text)
        assert blocks[0].lang == ""
        assert prose == []


# =============================================================================
# Help query extraction and resolution
# =============================================================================


class TestParseHelpArgs:
    """``parse_help_args`` strips flags and flags placeholder queries."""

    @pytest.mark.parametrize(
        ("rest", "query", "domain"),
        [
            ("Workspace.query", "Workspace.query", None),
            ("Filter -f json --jq '.construction[].name'", "Filter", None),
            ('Workspace --domain "feature flags"', "Workspace", "feature flags"),
            ("Workspace --domain=cohorts", "Workspace", "cohorts"),
            ("--no-hints MathType", "MathType", None),
            ("search retention", "search retention", None),
            ("", "", None),
            ("Filter  # a comment", "Filter", None),
            ("-f json Workspace.query >/dev/null", "Workspace.query", None),
            ("Filter | head", "Filter", None),
        ],
    )
    def test_strips_flags(self, rest: str, query: str, domain: str | None) -> None:
        """Flags and their values are removed; the query tokens remain.

        Args:
            rest: The text after ``mp help``.
            query: The expected query text.
            domain: The expected ``--domain`` value.
        """
        assert parse_help_args(rest) == (query, domain)

    @pytest.mark.parametrize(
        "rest", ["<query>", "Workspace.<method>", "search <term>", "X ..."]
    )
    def test_placeholder_returns_none(self, rest: str) -> None:
        """A placeholder token means the command is a template, not a query.

        Args:
            rest: The text after ``mp help``.
        """
        assert parse_help_args(rest) is None


class TestExtractHelpQueries:
    """``extract_help_queries`` finds every help invocation form."""

    def test_inline_fenced_and_python_forms(self) -> None:
        """Inline spans, shell fences, and ``mp.help("...")`` are all found."""
        text = (
            "Run `mp help search cohort` first.\n"
            "```bash\n"
            "python3 -m mixpanel_headless help Filter\n"
            "```\n"
            "```python\n"
            'mp.help("Workspace.query")\n'
            "```\n"
            "Template: `mp help <query>`.\n"
        )
        found = [(q.line, q.query) for q in extract_help_queries(SAMPLE, text)]
        assert found == [
            (1, "search cohort"),
            (3, "Filter"),
            (6, "Workspace.query"),
        ]

    def test_prose_without_backticks_is_ignored(self) -> None:
        """Plain prose is not scanned, so sentences are not read as queries."""
        text = "Use mp help when you are unsure.\n"
        assert extract_help_queries(SAMPLE, text) == []


class TestCheckHelpQuery:
    """``check_help_query`` resolves queries against the reference API."""

    @pytest.mark.parametrize(
        ("query", "domain"),
        [
            ("Workspace.query_funnel", None),
            ("Filter", None),
            ("search retention", None),
            ("", None),
            ("types", None),
        ],
    )
    def test_valid(self, query: str, domain: str | None) -> None:
        """A resolvable query yields no failure reason.

        Args:
            query: The query text.
            domain: The ``--domain`` value.
        """
        assert check_help_query(query, domain) is None

    def test_valid_domain(self) -> None:
        """A real domain title on ``Workspace`` resolves."""
        from mixpanel_headless._internal.help.registry import WORKSPACE_DOMAINS

        title = WORKSPACE_DOMAINS[0][0]
        assert check_help_query("Workspace", title) is None

    @pytest.mark.parametrize(
        ("query", "domain"),
        [
            ("Workspace.no_such_method", None),
            ("search zzqqxxnomatch", None),
            ("search", None),
            ("Workspace", "no such domain"),
            ("Filter", "cohorts"),
            ("search cohort", "cohorts"),
        ],
    )
    def test_invalid(self, query: str, domain: str | None) -> None:
        """A miss, an empty search, or a bad domain yields a reason.

        Args:
            query: The query text.
            domain: The ``--domain`` value.
        """
        assert check_help_query(query, domain)


# =============================================================================
# Python AST scanners
# =============================================================================


class TestWorkspaceCallViolations:
    """``workspace_call_violations`` checks ``ws.<name>`` and keywords."""

    def test_real_method_and_keywords_pass(self) -> None:
        """A real method with real keyword names has no violations."""
        src = "ws = mp.Workspace()\nr = ws.query('Login', last=30, math='unique')\n"
        assert workspace_call_violations(_block(src)) == ([], [])

    def test_unknown_method(self) -> None:
        """An unknown method is a member violation with the file line."""
        members, keywords = workspace_call_violations(
            _block("x = 1\nws.not_a_method()\n", line=10)
        )
        assert len(members) == 1
        assert "sample.md:11" in members[0]
        assert "not_a_method" in members[0]
        assert keywords == []

    def test_unknown_keyword(self) -> None:
        """An unknown keyword is a keyword violation naming the method."""
        _, keywords = workspace_call_violations(
            _block("ws.property_values(property='x')\n")
        )
        assert len(keywords) == 1
        assert "property_values" in keywords[0]
        assert "property" in keywords[0]

    def test_property_access_and_splat(self) -> None:
        """Property access and ``**kwargs`` splats are not flagged."""
        src = "ws.project.id\nopts = {}\nws.query('x', **opts)\n"
        assert workspace_call_violations(_block(src)) == ([], [])

    def test_workspace_constructor_chain(self) -> None:
        """A call chained on ``mp.Workspace(...)`` is checked too."""
        members, _ = workspace_call_violations(_block("mp.Workspace().nope()\n"))
        assert len(members) == 1


class TestImportViolations:
    """``import_violations`` checks public names of ``mixpanel_headless``."""

    def test_public_names_pass(self) -> None:
        """Public exports, submodules, and submodule members pass."""
        src = (
            "import mixpanel_headless as mp\n"
            "from mixpanel_headless import Workspace, Filter\n"
            "from mixpanel_headless.types import SegmentationResult\n"
            "mp.Filter\nmp.accounts\nmp.reference.describe\nmp.__version__\n"
        )
        assert import_violations(_block(src)) == []

    def test_private_and_missing_names(self) -> None:
        """Missing names and private modules are each reported."""
        src = (
            "from mixpanel_headless import NoSuchThing\n"
            "from mixpanel_headless._internal.config import ConfigManager\n"
            "import mixpanel_headless as mp\n"
            "mp.NotReal\n"
            "from mixpanel_headless.types import AlsoNotReal\n"
        )
        found = import_violations(_block(src))
        assert len(found) == 4
        assert any("NoSuchThing" in v for v in found)
        assert any("_internal" in v for v in found)
        assert any("NotReal" in v for v in found)
        assert any("AlsoNotReal" in v for v in found)


# =============================================================================
# Structure and text helpers
# =============================================================================


class TestHasContentsList:
    """``has_contents_list`` detects a contents list near the top."""

    def test_contents_heading(self) -> None:
        """A ``## Contents`` heading counts."""
        assert has_contents_list("# Title\n\n## Contents\n\n- [A](#a)\n")

    def test_anchor_list(self) -> None:
        """Three anchor links near the top count."""
        text = "# Title\n\n- [A](#a)\n- [B](#b)\n- [C](#c)\n"
        assert has_contents_list(text)

    def test_missing(self) -> None:
        """Plain prose does not count."""
        assert not has_contents_list("# Title\n\nSome text.\n" * 5)


class TestIterLinks:
    """``iter_links`` yields markdown link targets outside code fences."""

    def test_links(self) -> None:
        """Inline links are found with line numbers; fenced ones are not."""
        text = "See [a](references/a.md) and [b](https://x.y).\n```\n[c](c.md)\n```\n"
        assert iter_links(SAMPLE, text) == [
            (1, "references/a.md"),
            (1, "https://x.y"),
        ]


class TestParseFrontmatter:
    """``parse_frontmatter`` reads the YAML subset skills use."""

    def test_folded_and_plain(self) -> None:
        """Folded scalars are joined with spaces; plain values are kept."""
        text = (
            "---\nname: setup\ndescription: >-\n  One line.\n  Two line.\n"
            "allowed-tools: Bash Read\n---\n# Body\n"
        )
        assert parse_frontmatter(text) == {
            "name": "setup",
            "description": "One line. Two line.",
            "allowed-tools": "Bash Read",
        }

    def test_quoted(self) -> None:
        """Quoted values lose their quotes."""
        text = "---\nname: \"auth\"\ndescription: 'Hi: there'\n---\n"
        assert parse_frontmatter(text) == {"name": "auth", "description": "Hi: there"}

    def test_missing(self) -> None:
        """A file without frontmatter yields ``None``."""
        assert parse_frontmatter("# Title\n") is None


class TestForbiddenText:
    """``forbidden_text_violations`` flags plan codes and shouting."""

    @pytest.mark.parametrize(
        "line",
        [
            "Run help.py first.",
            "See the ai-plugins repo.",
            "Per the 042 redesign.",
            "Implements FR-012.",
            "From Plan 047.",
            "See § 5.2.",
            "Guard G3 checks this.",
            "Chosen in (D6).",
            "Per D12, no agents.",
            "Details in specs/045-report-links/plan.md.",
            "You MUST do this.",
            "NEVER guess.",
            "Set up Claude Cowork first.",
            "Works in COWORK sessions.",
            "Check the bridge file.",
            "Run mp account export-bridge.",
            "bridge_status = load()",
            "Bridges are cached.",
        ],
    )
    def test_flagged(self, line: str) -> None:
        """Each forbidden form is reported.

        Args:
            line: A line of shipped text.
        """
        assert forbidden_text_violations(SAMPLE, line, caps_allowed=False)

    @pytest.mark.parametrize(
        "line",
        [
            "D1 retention and D7 retention are day buckets.",
            "Use G-Suite login.",
            "Always check the date range.",
            "The MUSTANG event.",
            "A 404 means the dashboard is gone.",
            "The Bridgeport event is rare.",
        ],
    )
    def test_not_flagged(self, line: str) -> None:
        """Ordinary analytics text is not reported.

        Args:
            line: A line of shipped text.
        """
        assert forbidden_text_violations(SAMPLE, line, caps_allowed=False) == []

    def test_caps_allowed(self) -> None:
        """All-caps words pass where the caller allows them (auth rules)."""
        assert forbidden_text_violations(SAMPLE, "NEVER log", caps_allowed=True) == []


class TestParseVersionFloor:
    """``parse_version_floor`` reads the pin in ``setup.sh``."""

    def test_floor(self) -> None:
        """A ``>=`` pin yields its version tuple."""
        text = 'MIXPANEL_HEADLESS_PKG="mixpanel-headless>=0.3.0"\n'
        assert parse_version_floor(text) == (0, 3, 0)

    def test_unpinned(self) -> None:
        """An unpinned package yields ``None``."""
        assert (
            parse_version_floor('MIXPANEL_HEADLESS_PKG="mixpanel-headless"\n') is None
        )


# =============================================================================
# Plugin-owned Python environment scanners
# =============================================================================


class TestAllowedToolsViolations:
    """``allowed_tools_violations`` rejects system Python and bare ``mp`` grants."""

    def test_venv_grants_pass(self) -> None:
        """The plugin venv interpreter and CLI patterns are allowed."""
        value = (
            "Bash(${CLAUDE_PLUGIN_DATA}/venv/bin/python *) "
            "Bash(${CLAUDE_PLUGIN_DATA}/venv/bin/mp *) Bash(uv run *) Read Write Edit "
            "WebFetch(domain:mixpanel.github.io)"
        )
        assert allowed_tools_violations(SAMPLE, value) == []

    def test_read_only_mp_grants_pass(self) -> None:
        """The three exact read-only ``mp`` grants for the look-up fallback pass."""
        value = "Bash(mp --version) Bash(mp help) Bash(mp help *) Read"
        assert allowed_tools_violations(SAMPLE, value) == []

    @pytest.mark.parametrize(
        "entry",
        [
            "Bash(python3 *)",
            "Bash(python *)",
            "Bash(mp *)",
            "Bash(python3:*)",
            "Bash(mp:*)",
            "Bash(mp)",
            "Bash(mp query *)",
            "Bash(mp help:*)",
            "Bash(mp --version *)",
            "Bash(mp help  x)",
            "Bash(mp helper *)",
            "Bash(python3 -c *)",
            "Bash(python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py *)",
        ],
    )
    def test_system_grants_flagged(self, entry: str) -> None:
        """Each system Python or bare ``mp`` grant is reported.

        Args:
            entry: One ``allowed-tools`` entry.
        """
        found = allowed_tools_violations(SAMPLE, f"Read {entry} Write")
        assert len(found) == 1
        assert entry in found[0]


class TestSystemPythonViolations:
    """``system_python_violations`` finds system ``python3`` runs in skill text."""

    @pytest.mark.parametrize(
        "line",
        [
            'python3 -c "import mixpanel_headless"',
            "Run `python3 -m mixpanel_headless help Filter`.",
            "python3 analysis.py",
            "python3 ${CLAUDE_PLUGIN_ROOT}/skills/auth/scripts/auth_manager.py status",
            "${CLAUDE_PLUGIN_DATA}/venv/bin/python3 -c 'x'",
        ],
    )
    def test_flagged(self, line: str) -> None:
        """Each system ``python3`` run is reported.

        Args:
            line: A line of skill markdown.
        """
        assert system_python_violations(SAMPLE, line)

    @pytest.mark.parametrize(
        "line",
        [
            '${CLAUDE_PLUGIN_DATA}/venv/bin/python -c "import mixpanel_headless"',
            "${CLAUDE_PLUGIN_DATA}/venv/bin/python script.py",
            "uv run python analysis.py",
            "Python 3.10 or later is required; python3 must be on PATH.",
            "python3 -m venv is the fallback that setup uses.",
        ],
    )
    def test_not_flagged(self, line: str) -> None:
        """Venv runs and plain mentions of Python are not reported.

        Args:
            line: A line of skill markdown.
        """
        assert system_python_violations(SAMPLE, line) == []


class TestInjectionViolations:
    """``injection_violations`` checks ``!`command``` lines in skill text."""

    def test_clean_injection_passes(self) -> None:
        """A venv command with only ``${CLAUDE_...}`` substitutions passes."""
        text = (
            "!`${CLAUDE_PLUGIN_DATA}/venv/bin/python -m mixpanel_headless --version "
            '2>/dev/null || echo "run setup"`\n'
            "!`${CLAUDE_PLUGIN_DATA}/venv/bin/mp help 2>/dev/null | grep -A 30 "
            '"^Workspace domains" || echo "none"`\n'
        )
        assert injection_violations(SAMPLE, text) == []

    @pytest.mark.parametrize(
        "line",
        [
            "!`$CLAUDE_PLUGIN_DATA/venv/bin/python -V`",
            "!`echo $HOME`",
            "!`echo $(date)`",
            "!`mp help 2>/dev/null | head -1`",
            "!`python3 -m mixpanel_headless --version`",
            "!`echo hi && python -V`",
        ],
    )
    def test_flagged(self, line: str) -> None:
        """A shell variable, a subshell, or a bare ``mp`` / ``python`` is reported.

        Args:
            line: A line of skill markdown with one injection.
        """
        found = injection_violations(SAMPLE, f"Intro.\n{line}\n")
        assert found
        assert found[0].startswith("sample.md:2:")

    def test_plain_bang_text_is_ignored(self) -> None:
        """An exclamation mark before ordinary code is not an injection."""
        assert injection_violations(SAMPLE, "Done!`x` is fine?\n") == []
