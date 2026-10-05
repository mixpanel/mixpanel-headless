"""Scanners for the repository guards on ``mixpanel-plugin/`` content.

The guards in ``test_plugin_content.py`` check that the plugin's markdown
matches the installed library: help queries resolve, Python examples call
real methods with real keyword names, links resolve, frontmatter follows the
skill rules, and shipped text carries no plan bookkeeping. This module holds
the file discovery and the pure scanning functions. Each scanner returns
violation strings of the form ``"<path>:<line>: <reason>"`` so a guard can
report every failure in one assertion message.

All scanning is offline. Help queries resolve through
``mixpanel_headless.reference`` (no network, no credentials).

Scope decisions:

- ``mixpanel-plugin/evals/`` is excluded from every guard. Eval prompts and
  graders quote wrong code and forbidden strings on purpose.
- ``mixpanel-plugin/docs/`` and ``mixpanel-plugin/README.md`` are in scope
  for every markdown guard, because they ship with the plugin.
- CLI help commands are read from inline code spans and non-Python fences
  only, and only where the command starts the span or the shell command.
  Plain prose such as "use mp help when unsure" is not a query.
"""

from __future__ import annotations

import ast
import functools
import importlib
import inspect
import pkgutil
import re
import shlex
import textwrap
from dataclasses import dataclass
from pathlib import Path

import mixpanel_headless
from mixpanel_headless import Workspace
from mixpanel_headless._internal.help.resolve import parse_query
from mixpanel_headless.exceptions import HelpDomainError, HelpLookupError
from mixpanel_headless.reference import describe, search

REPO_ROOT = Path(__file__).resolve().parents[3]
"""Repository root (``tests/unit/plugin/_content.py`` → three levels up)."""

PLUGIN_ROOT = REPO_ROOT / "mixpanel-plugin"
"""Root directory of the Claude Code plugin."""

SKILLS_ROOT = PLUGIN_ROOT / "skills"
"""Directory that holds one sub-directory per skill."""

EXCLUDED_TOP_DIRS = frozenset({"evals"})
"""Top-level plugin directories that no guard scans (eval fixtures)."""

PYTHON_LANGS = frozenset({"python", "py", "python3"})
"""Fence info strings treated as Python source."""


# =============================================================================
# Data types
# =============================================================================


@dataclass(frozen=True)
class CodeBlock:
    """One fenced code block in a markdown file.

    Attributes:
        path: The markdown file that holds the block.
        line: The 1-based file line of the first code line (after the fence).
        lang: The lower-cased first word of the fence info string, or ``""``.
        text: The block body, dedented, with a trailing newline per line.
    """

    path: Path
    line: int
    lang: str
    text: str


@dataclass(frozen=True)
class HelpQuery:
    """One help invocation found in a markdown file.

    Attributes:
        path: The markdown file that holds the invocation.
        line: The 1-based file line of the invocation.
        query: The query text with flags removed (``""`` means the overview).
        domain: The ``--domain`` (or ``domain=``) value, when given.
        raw: The invocation text as written, for the failure message.
    """

    path: Path
    line: int
    query: str
    domain: str | None
    raw: str


# =============================================================================
# File discovery and reporting
# =============================================================================


def rel(path: Path) -> str:
    """Return ``path`` relative to the repository root when possible.

    Args:
        path: Any path.

    Returns:
        The repository-relative POSIX path, or ``str(path)`` for a path
        outside the repository (synthetic test paths).
    """
    try:
        return path.resolve().relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _is_excluded(path: Path) -> bool:
    """Tell whether a plugin file sits in a directory no guard scans.

    Args:
        path: A file under ``PLUGIN_ROOT``.

    Returns:
        ``True`` for files under an ``EXCLUDED_TOP_DIRS`` directory.
    """
    parts = path.relative_to(PLUGIN_ROOT).parts
    return bool(parts) and parts[0] in EXCLUDED_TOP_DIRS


def plugin_markdown_files() -> list[Path]:
    """List every shipped markdown file in the plugin.

    Returns:
        Sorted ``*.md`` paths under ``mixpanel-plugin/``, without ``evals/``.
    """
    return sorted(p for p in PLUGIN_ROOT.rglob("*.md") if not _is_excluded(p))


def shipped_text_files() -> list[Path]:
    """List every shipped text file in the plugin (markdown, JSON, scripts).

    Returns:
        Sorted ``.md``, ``.json``, ``.sh``, ``.py``, and ``.txt`` paths under
        ``mixpanel-plugin/``, plus every file in a skill ``scripts/``
        directory, without ``evals/``.
    """
    return sorted(
        p
        for p in PLUGIN_ROOT.rglob("*")
        if p.is_file() and not _is_excluded(p) and _is_shipped_text(p)
    )


def _is_shipped_text(path: Path) -> bool:
    """Tell whether a plugin file is text that the forbidden-text guard scans.

    Args:
        path: A file under ``PLUGIN_ROOT``.

    Returns:
        ``True`` for ``.md``, ``.json``, ``.sh``, ``.py``, and ``.txt`` files,
        and for any file inside a skill ``scripts/`` directory (except
        ``.DS_Store``).
    """
    if path.name == ".DS_Store":
        return False
    if path.suffix in {".md", ".json", ".sh", ".py", ".txt"}:
        return True
    if not path.is_relative_to(SKILLS_ROOT):
        return False
    return "scripts" in path.relative_to(SKILLS_ROOT).parts[:-1]


def skill_dirs() -> list[Path]:
    """List every skill directory.

    Returns:
        Sorted sub-directories of ``mixpanel-plugin/skills/``.
    """
    return sorted(p for p in SKILLS_ROOT.iterdir() if p.is_dir())


def reference_files(skill_dir: Path) -> list[Path]:
    """List the reference files of one skill.

    Args:
        skill_dir: A skill directory.

    Returns:
        Sorted ``*.md`` paths under ``<skill_dir>/references/``.
    """
    return sorted((skill_dir / "references").rglob("*.md"))


def read(path: Path) -> str:
    """Read a UTF-8 text file.

    Args:
        path: The file to read.

    Returns:
        The file content.
    """
    return path.read_text(encoding="utf-8")


def report(title: str, violations: list[str]) -> str:
    """Format a guard's violations as one assertion message.

    Args:
        title: The guard name, for example ``"Help queries resolve"``.
        violations: Every ``"<path>:<line>: <reason>"`` string found.

    Returns:
        A multi-line message: a count line, then one indented line each.
    """
    lines = [f"{title}: {len(violations)} violation(s)"]
    lines.extend(f"  {v}" for v in violations)
    return "\n".join(lines)


# =============================================================================
# Markdown splitting
# =============================================================================

_FENCE_OPEN = re.compile(r"^(?P<indent>\s*)(?P<fence>`{3,}|~{3,})\s*(?P<info>[^`]*)$")
"""An opening code fence with optional indent and info string."""

_INLINE_CODE = re.compile(r"(`+)(.+?)\1")
"""An inline code span (single or multiple backticks)."""


def split_markdown(
    path: Path, text: str
) -> tuple[list[CodeBlock], list[tuple[int, str]]]:
    """Split markdown into fenced code blocks and prose lines.

    Args:
        path: The file the text came from (stored on each block).
        text: The markdown text.

    Returns:
        ``(blocks, prose)``: every fenced block, and every line outside a
        fence as ``(line_number, text)``. Fence delimiter lines belong to
        neither list. An unclosed fence runs to the end of the file.

    Example:
        ```python
        blocks, prose = split_markdown(Path("x.md"), "a\\n```py\\nx=1\\n```\\n")
        # blocks[0].lang == "py", blocks[0].line == 3, prose == [(1, "a")]
        ```
    """
    blocks: list[CodeBlock] = []
    prose: list[tuple[int, str]] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        match = _FENCE_OPEN.match(lines[i])
        if match is None:
            prose.append((i + 1, lines[i]))
            i += 1
            continue
        fence = match.group("fence")
        info = match.group("info").strip()
        lang = info.split()[0].lower() if info else ""
        body: list[str] = []
        j = i + 1
        while j < len(lines):
            stripped = lines[j].strip()
            if stripped.startswith(fence[0] * len(fence)) and not stripped.strip(
                fence[0]
            ):
                break
            body.append(lines[j])
            j += 1
        source = textwrap.dedent("\n".join(body))
        blocks.append(
            CodeBlock(
                path=path,
                line=i + 2,
                lang=lang,
                text=source + "\n" if source else "",
            )
        )
        i = j + 1
    return blocks, prose


def markdown_blocks(path: Path) -> list[CodeBlock]:
    """Return the fenced code blocks of a markdown file.

    Args:
        path: A markdown file.

    Returns:
        Every fenced block in file order.
    """
    return split_markdown(path, read(path))[0]


# =============================================================================
# Help queries
# =============================================================================

_CLI_HELP = re.compile(
    r"(?:^\s*(?:\$\s+)?|&&\s*|;\s*|\|\|\s*|\$\(\s*)"
    r"(?:uv\s+run\s+)?(?:python3?\s+-m\s+)?"
    r"(?:mp|mixpanel_headless)\s+help\b(?P<rest>.*)"
)
"""A CLI help command at the start of a span or a shell command."""

_PY_HELP = re.compile(
    r"\b(?:mp|mixpanel_headless)\.help\(\s*(?:query\s*=\s*)?(?P<q>['\"])(?P<query>.*?)(?P=q)"
    r"(?P<tail>[^)]*)"
)
"""A Python ``mp.help("...")`` call with a string literal query."""

_PY_DOMAIN = re.compile(r"domain\s*=\s*(?P<q>['\"])(?P<domain>.*?)(?P=q)")
"""A ``domain="..."`` keyword inside an ``mp.help(...)`` call."""

_PLACEHOLDER = re.compile(r"<[^<>\s]*>|\.\.\.|…")
"""Template text: ``<query>``, ``Workspace.<method>``, or an ellipsis."""

_SHELL_STOP = frozenset({"|", "||", "&", "&&", ";", ")", "(", ">", ">>", "<", ">&"})
"""Shell operators that end the help command."""


def parse_help_args(rest: str) -> tuple[str, str | None] | None:
    """Strip flags from the text after ``mp help`` and return the query.

    Args:
        rest: The text after ``mp help`` (may hold flags, a comment, a pipe,
            or a redirect).

    Returns:
        ``(query, domain)`` where ``query`` is the remaining tokens joined by
        spaces (``""`` for the overview). ``None`` when the text is a
        template (a ``<placeholder>``, ``{x}``, ``$VAR``, ``[x]``, or an
        ellipsis) or asks for the command's own ``--help``.

    Example:
        ```python
        parse_help_args("Filter -f json --jq '.construction[].name'")
        # ("Filter", None)
        parse_help_args("Workspace.<method>")   # None
        ```
    """
    if _PLACEHOLDER.search(rest):
        return None
    lexer = shlex.shlex(rest, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = "#"
    try:
        tokens = list(lexer)
    except ValueError:
        tokens = rest.split()
    query: list[str] = []
    domain: str | None = None
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in _SHELL_STOP or set(token) <= set("|&;()<>"):
            if query and query[-1].isdigit() and token.startswith(">"):
                query.pop()  # "2>&1" / "2>/dev/null" redirect
            break
        if token in {"-h", "--help"}:
            return None
        if token in {"-f", "--format", "--jq", "--domain"}:
            value = tokens[i + 1] if i + 1 < len(tokens) else ""
            if token == "--domain":
                domain = value
            i += 2
            continue
        if token.startswith("--domain="):
            domain = token.split("=", 1)[1]
        elif not token.startswith("-"):
            if any(ch in token for ch in "{}$[]"):
                return None
            query.append(token)
        i += 1
    return " ".join(query), domain


def _cli_queries(path: Path, line: int, text: str) -> list[HelpQuery]:
    """Find CLI help commands in one span or one fence line.

    Args:
        path: The markdown file.
        line: The 1-based file line of ``text``.
        text: An inline code span's content or one line of a fence.

    Returns:
        One ``HelpQuery`` per non-template command.
    """
    found: list[HelpQuery] = []
    matches = list(_CLI_HELP.finditer(text))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        rest = text[match.start("rest") : end].rstrip().removesuffix("\\")
        parsed = parse_help_args(rest)
        if parsed is not None:
            found.append(HelpQuery(path, line, parsed[0], parsed[1], text.strip()))
    return found


def _py_queries(path: Path, line: int, text: str) -> list[HelpQuery]:
    """Find ``mp.help("...")`` calls in one line of text.

    Args:
        path: The markdown file.
        line: The 1-based file line of ``text``.
        text: One line of markdown, a span, or a fence line.

    Returns:
        One ``HelpQuery`` per call whose query is not a template.
    """
    found: list[HelpQuery] = []
    for match in _PY_HELP.finditer(text):
        query = match.group("query")
        if _PLACEHOLDER.search(query):
            continue
        dom = _PY_DOMAIN.search(match.group("tail"))
        domain = dom.group("domain") if dom else None
        found.append(HelpQuery(path, line, query, domain, match.group(0)))
    return found


def extract_help_queries(path: Path, text: str) -> list[HelpQuery]:
    """Find every help invocation in a markdown file.

    Covers ``mp help <query>``, ``python3 -m mixpanel_headless help <query>``
    (inline spans and non-Python fences), and ``mp.help("<query>")``
    (anywhere). Templates such as ``mp help <query>`` are skipped.

    Args:
        path: The markdown file.
        text: Its content.

    Returns:
        Every invocation in file order.
    """
    blocks, prose = split_markdown(path, text)
    found: list[tuple[int, int, HelpQuery]] = []
    for line, content in prose:
        for order, span in enumerate(_INLINE_CODE.finditer(content)):
            for query in _cli_queries(path, line, span.group(2)):
                found.append((line, order, query))
        for query in _py_queries(path, line, content):
            found.append((line, 1000, query))
    for block in blocks:
        for offset, content in enumerate(block.text.splitlines()):
            line = block.line + offset
            if block.lang not in PYTHON_LANGS:
                for query in _cli_queries(path, line, content):
                    found.append((line, 0, query))
            for query in _py_queries(path, line, content):
                found.append((line, 1, query))
    found.sort(key=lambda item: (item[0], item[1]))
    return [query for _, _, query in found]


@functools.cache
def check_help_query(query: str, domain: str | None) -> str | None:
    """Resolve one help query the way ``mp help`` does.

    Args:
        query: The query text with flags removed (``""`` for the overview,
            ``"search <term>"`` for a search).
        domain: The ``--domain`` value, when given.

    Returns:
        ``None`` when the query resolves (a search needs at least one hit),
        otherwise a short failure reason.
    """
    mode, payload = parse_query(query)
    if mode == "search":
        if domain is not None:
            return "--domain cannot be combined with search"
        if not payload:
            return "search needs a term"
        if not search(payload).hits:
            return f"search {payload!r} has no hits"
        return None
    target = payload if mode == "describe" else None
    try:
        describe(target, domain=domain)
    except HelpDomainError as exc:
        return f"bad --domain {domain!r}: {exc.message}"
    except HelpLookupError as exc:
        return f"no match: {exc.message}"
    return None


# =============================================================================
# Python block scanners
# =============================================================================


@functools.lru_cache(maxsize=1)
def workspace_members() -> frozenset[str]:
    """Return the public attribute names of ``Workspace``.

    Returns:
        Methods and properties that do not start with an underscore.
    """
    return frozenset(n for n in dir(Workspace) if not n.startswith("_"))


@functools.lru_cache(maxsize=1)
def public_names() -> frozenset[str]:
    """Return the names ``mixpanel_headless`` exposes publicly.

    Returns:
        ``__all__``, the public submodules (``types``, ``reference``,
        ``accounts``, ...), and ``__version__``.
    """
    submodules = {
        m.name
        for m in pkgutil.iter_modules(mixpanel_headless.__path__)
        if not m.name.startswith("_")
    }
    return frozenset(set(mixpanel_headless.__all__) | submodules | {"__version__"})


def _parse(block: CodeBlock) -> ast.Module | None:
    """Parse a Python block, or return ``None`` on a syntax error.

    Args:
        block: A Python code block.

    Returns:
        The module AST, or ``None`` (the parse guard reports the syntax error).
    """
    try:
        return ast.parse(block.text)
    except SyntaxError:
        return None


def _is_workspace_expr(node: ast.expr) -> bool:
    """Tell whether an expression is a ``Workspace`` instance by convention.

    Args:
        node: An AST expression.

    Returns:
        ``True`` for the name ``ws`` and for a ``Workspace(...)`` or
        ``mp.Workspace(...)`` call.
    """
    if isinstance(node, ast.Name):
        return node.id == "ws"
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name):
            return func.id == "Workspace"
        if isinstance(func, ast.Attribute):
            return func.attr == "Workspace"
    return False


def _keyword_names(member: str) -> tuple[frozenset[str], bool] | None:
    """Return the keyword parameter names of a ``Workspace`` method.

    Args:
        member: A public ``Workspace`` attribute name.

    Returns:
        ``(names, takes_var_keyword)``, or ``None`` when the attribute is a
        property or cannot be introspected.
    """
    raw = inspect.getattr_static(Workspace, member)
    if isinstance(raw, property):
        return None
    try:
        signature = inspect.signature(getattr(Workspace, member))
    except (TypeError, ValueError):
        return None
    keyword_kinds = {
        inspect.Parameter.POSITIONAL_OR_KEYWORD,
        inspect.Parameter.KEYWORD_ONLY,
    }
    names = frozenset(
        p.name
        for p in signature.parameters.values()
        if p.kind in keyword_kinds and p.name != "self"
    )
    var_kw = any(
        p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values()
    )
    return names, var_kw


def workspace_call_violations(block: CodeBlock) -> tuple[list[str], list[str]]:
    """Check ``ws.<name>`` use and keyword names in a Python block.

    Args:
        block: A Python code block.

    Returns:
        ``(member_violations, keyword_violations)``: unknown ``Workspace``
        attributes and unknown keyword arguments. A
        block that does not parse yields two empty lists.

    Example:
        ```python
        workspace_call_violations(block_with("ws.property_values(property='x')"))
        # ([], ["x.md:1: ws.property_values() has no parameter 'property'"])
        ```
    """
    tree = _parse(block)
    if tree is None:
        return [], []
    members = workspace_members()
    where = rel(block.path)
    member_violations: list[str] = []
    keyword_violations: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and _is_workspace_expr(node.value)
            and node.attr not in members
        ):
            line = block.line + node.lineno - 1
            member_violations.append(
                f"{where}:{line}: ws.{node.attr} is not a Workspace method or property"
            )
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and _is_workspace_expr(node.func.value)
            and node.func.attr in members
        ):
            continue
        params = _keyword_names(node.func.attr)
        if params is None or params[1]:
            continue
        for keyword in node.keywords:
            if keyword.arg is not None and keyword.arg not in params[0]:
                line = block.line + keyword.value.lineno - 1
                keyword_violations.append(
                    f"{where}:{line}: ws.{node.func.attr}() has no parameter "
                    f"{keyword.arg!r}"
                )
    return member_violations, keyword_violations


def _check_module(module: str) -> tuple[object | None, str | None]:
    """Import a ``mixpanel_headless`` submodule if it is public.

    Args:
        module: A dotted module path starting with ``mixpanel_headless.``.

    Returns:
        ``(module_object, None)`` on success, or ``(None, reason)`` when the
        path has a private segment or does not import.
    """
    if any(part.startswith("_") for part in module.split(".")[1:]):
        return None, f"{module} is a private module"
    try:
        return importlib.import_module(module), None
    except ImportError:
        return None, f"{module} does not exist"


def import_violations(block: CodeBlock) -> list[str]:
    """Check that a Python block uses only public ``mixpanel_headless`` names.

    Checks ``from mixpanel_headless import X``, ``from
    mixpanel_headless.<sub> import X``, ``import mixpanel_headless.<sub>``,
    and attribute access ``mp.X`` / ``mixpanel_headless.X`` (plus
    ``mp.<submodule>.Y``). ``mp`` is assumed to be the package even when
    the block omits the import.

    Args:
        block: A Python code block.

    Returns:
        Import violations. A block that does not parse yields ``[]``.
    """
    tree = _parse(block)
    if tree is None:
        return []
    public = public_names()
    where = rel(block.path)
    found: list[str] = []
    aliases = {"mp", "mixpanel_headless"}

    def add(node: ast.AST, reason: str) -> None:
        """Record one violation at a node's line.

        Args:
            node: The AST node (must carry ``lineno``).
            reason: The failure reason.
        """
        found.append(f"{where}:{block.line + getattr(node, 'lineno', 1) - 1}: {reason}")

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "mixpanel_headless":
                    aliases.add(alias.asname or alias.name)
                elif alias.name.startswith("mixpanel_headless."):
                    _, reason = _check_module(alias.name)
                    if reason:
                        add(node, reason)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module == "mixpanel_headless":
                for alias in node.names:
                    if alias.name != "*" and alias.name not in public:
                        add(node, f"mixpanel_headless.{alias.name} is not public")
            elif node.module.startswith("mixpanel_headless."):
                module, reason = _check_module(node.module)
                if reason:
                    add(node, reason)
                    continue
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    if alias.name.startswith("_") or not hasattr(module, alias.name):
                        add(node, f"{node.module}.{alias.name} is not public")
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        base = node.value
        if isinstance(base, ast.Name) and base.id in aliases:
            if node.attr not in public:
                add(node, f"mp.{node.attr} is not public")
        elif (
            isinstance(base, ast.Attribute)
            and isinstance(base.value, ast.Name)
            and base.value.id in aliases
            and base.attr in public
        ):
            sub = getattr(mixpanel_headless, base.attr, None)
            if inspect.ismodule(sub) and (
                node.attr.startswith("_") or not hasattr(sub, node.attr)
            ):
                add(node, f"mp.{base.attr}.{node.attr} is not public")
    return found


# =============================================================================
# Structure helpers
# =============================================================================

_CONTENTS_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s*|\*\*)?(?:table of )?contents\b", re.IGNORECASE
)
"""A "Contents" heading or bold label."""

_ANCHOR_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s*\[[^\]]+\]\(#")
"""A list item that links to an anchor in the same file."""

CONTENTS_WINDOW = 30
"""Number of leading lines searched for a contents list."""


def has_contents_list(text: str) -> bool:
    """Tell whether a file starts with a contents list.

    A contents list is a "Contents" heading (or bold label), or at least
    three list items that link to in-file anchors, within the first
    ``CONTENTS_WINDOW`` lines.

    Args:
        text: The markdown text.

    Returns:
        ``True`` when a contents list is present near the top.
    """
    head = text.splitlines()[:CONTENTS_WINDOW]
    if any(_CONTENTS_HEADING.match(line) for line in head):
        return True
    return sum(1 for line in head if _ANCHOR_ITEM.match(line)) >= 3


_LINK = re.compile(r"\[[^\]]*\]\((?P<target>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
"""An inline markdown link or image and its target."""


def iter_links(path: Path, text: str) -> list[tuple[int, str]]:
    """List markdown link targets outside code fences and code spans.

    Args:
        path: The markdown file (used for fence splitting only).
        text: Its content.

    Returns:
        ``(line_number, target)`` pairs in file order.
    """
    _, prose = split_markdown(path, text)
    links: list[tuple[int, str]] = []
    for line, content in prose:
        stripped = _INLINE_CODE.sub("", content)
        links.extend((line, m.group("target")) for m in _LINK.finditer(stripped))
    return links


def is_external(target: str) -> bool:
    """Tell whether a link target leaves the file system.

    Args:
        target: A markdown link target.

    Returns:
        ``True`` for URLs, ``mailto:``, and in-page anchors.
    """
    return "://" in target or target.startswith(("mailto:", "#"))


_FRONTMATTER_KEY = re.compile(r"^(?P<key>[A-Za-z_][\w-]*):\s*(?P<value>.*)$")
"""A top-level frontmatter ``key: value`` line."""


def _unquote(value: str) -> str:
    """Remove matching YAML quotes from a scalar.

    Args:
        value: A stripped scalar.

    Returns:
        The scalar without its surrounding quotes.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        inner = value[1:-1]
        return (
            inner.replace("''", "'") if value[0] == "'" else inner.replace('\\"', '"')
        )
    return value


def parse_frontmatter(text: str) -> dict[str, str] | None:
    """Parse the YAML frontmatter subset that skill files use.

    Supports top-level ``key: value`` pairs, quoted scalars, folded (``>``,
    ``>-``) and literal (``|``, ``|-``) block scalars, and plain scalars
    continued on indented lines.

    Args:
        text: The full ``SKILL.md`` text.

    Returns:
        The key/value map, or ``None`` when the file has no frontmatter.

    Example:
        ```python
        parse_frontmatter("---\\nname: setup\\n---\\n")   # {"name": "setup"}
        ```
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return None
    result: dict[str, str] = {}
    key: str | None = None
    style = ""
    parts: list[str] = []

    def flush() -> None:
        """Store the pending key with its joined value."""
        if key is None:
            return
        joiner = "\n" if style.startswith("|") else " "
        result[key] = _unquote(joiner.join(p for p in parts if p).strip())

    for line in lines[1:end]:
        match = _FRONTMATTER_KEY.match(line)
        if match and not line[0].isspace():
            flush()
            key = match.group("key")
            value = match.group("value").strip()
            style = value if value in {">", ">-", "|", "|-"} else ""
            parts = [] if style else [value]
        elif key is not None:
            parts.append(line.strip())
    flush()
    return result


# =============================================================================
# Text helpers
# =============================================================================

_DECISION = r"D(?:1[0-4]|[1-9])"
"""A design-decision code, D1 to D14."""

FORBIDDEN_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("mentions help.py (removed; use mp help)", re.compile(r"\bhelp\.py\b")),
    ("mentions ai-plugins", re.compile(r"ai-plugins", re.IGNORECASE)),
    ("plan code 'NNN redesign'", re.compile(r"\b0\d{2} redesign\b")),
    ("plan code FR-0NN", re.compile(r"\bFR-0\d+")),
    ("plan code 'Plan 0NN'", re.compile(r"\bPlan 0\d+")),
    ("section sign §", re.compile(r"§")),
    ("guard code (G plus a number)", re.compile(r"\bG(?:10|[1-9])\b")),
    (
        "decision code D1-D14",
        re.compile(
            rf"\({_DECISION}(?:\s*[,/]\s*{_DECISION})*\)"
            rf"|\b(?:per|see|decisions?)\s+{_DECISION}\b",
            re.IGNORECASE,
        ),
    ),
    (
        "spec or plan path",
        re.compile(r"\bspecs/0\d{2}-|\bcontext/[\w-]+(?:/[\w.-]+)*\.md"),
    ),
    ("mentions Cowork", re.compile(r"cowork", re.IGNORECASE)),
    (
        "mentions the bridge",
        re.compile(r"(?<![A-Za-z])bridges?(?![A-Za-z])", re.IGNORECASE),
    ),
)
"""Plan bookkeeping and removed names that must not appear in shipped text.

The plugin does not mention Cowork or the Cowork credential bridge. "bridge"
is matched as a word that may touch ``_`` or ``-``, so identifiers such as
``bridge_status`` and ``export-bridge`` are caught, but "Bridgeport" is not.

Bare decision codes (``D1``, ``D7``) are only flagged in parentheses or after
"per" / "see" / "decision", because ``D1`` and ``D7`` are also the standard
names for day-1 and day-7 retention in analytics text.
"""

CAPS_PATTERN = re.compile(r"\b(?:ALWAYS|NEVER|MUST)\b")
"""All-caps rule words; skills give a reason instead."""


def forbidden_text_violations(
    path: Path, text: str, *, caps_allowed: bool
) -> list[str]:
    """Scan shipped text for plan codes, removed names, and shouting.

    Args:
        path: The file the text came from.
        text: The text to scan (one line or a whole file).
        caps_allowed: When ``True``, skip the all-caps ``ALWAYS`` /
            ``NEVER`` / ``MUST`` check (the ``auth`` security rules, and
            non-markdown files).

    Returns:
        One ``"<path>:<line>: <reason>: <line text>"`` string per hit.
    """
    where = rel(path)
    found: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for reason, pattern in FORBIDDEN_PATTERNS:
            if pattern.search(line):
                found.append(f"{where}:{number}: {reason}: {line.strip()[:120]}")
        if not caps_allowed and CAPS_PATTERN.search(line):
            found.append(
                f"{where}:{number}: all-caps ALWAYS/NEVER/MUST: {line.strip()[:120]}"
            )
    return found


_FLOOR = re.compile(r"mixpanel-headless\s*>=\s*(?P<version>\d+(?:\.\d+)*)")
"""A ``mixpanel-headless>=X.Y.Z`` requirement."""


def parse_version_floor(text: str) -> tuple[int, ...] | None:
    """Read the ``mixpanel-headless`` version floor from ``setup.sh``.

    Args:
        text: The script text.

    Returns:
        The floor as an integer tuple padded to three parts, or ``None``
        when the package is not pinned with ``>=``.
    """
    match = _FLOOR.search(text)
    if match is None:
        return None
    parts = tuple(int(p) for p in match.group("version").split("."))
    return parts + (0,) * (3 - len(parts))


# =============================================================================
# Plugin-owned Python environment
# =============================================================================
#
# Skills run code with the plugin's own interpreter at
# ${CLAUDE_PLUGIN_DATA}/venv/bin/python. Claude Code substitutes
# ${CLAUDE_...} names in skill text before the permission check. A shell
# variable such as $CLAUDE_PLUGIN_DATA expands to nothing, and the check
# denies it. A denied ``!`command``` line aborts the whole skill.

READ_ONLY_MP_GRANTS = frozenset(
    {"Bash(mp --version)", "Bash(mp help)", "Bash(mp help *)"}
)
"""The only bare-``mp`` grants allowed: the read-only look-up fallback.

They let a skill check an ``mp`` on ``PATH`` and read its help before setup
builds the plugin venv. Matched exactly, without the ``:*`` normalization.
"""

_BARE_GRANT = re.compile(r"^Bash\(\s*(?:mp|python3?)(?=[\s:)])")
"""A ``Bash(...)`` grant whose command is a bare ``mp``, ``python``, or ``python3``."""


def _split_tools(value: str) -> list[str]:
    """Split an ``allowed-tools`` value into entries.

    Spaces inside parentheses belong to the entry, so
    ``Bash(uv run *) Read`` yields ``["Bash(uv run *)", "Read"]``.

    Args:
        value: The ``allowed-tools`` frontmatter value.

    Returns:
        The entries in order.
    """
    entries: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in value:
        if ch.isspace() and depth == 0:
            if current:
                entries.append("".join(current))
                current = []
            continue
        depth += (ch == "(") - (ch == ")")
        current.append(ch)
    if current:
        entries.append("".join(current))
    return entries


def allowed_tools_violations(path: Path, value: str) -> list[str]:
    """Reject ``allowed-tools`` grants for the system Python or a bare ``mp``.

    Any ``Bash(...)`` grant whose command starts with a bare ``mp``,
    ``python``, or ``python3`` is rejected, in either the ``Bash(cmd *)`` or
    the legacy ``Bash(cmd:*)`` spelling. The three exact entries in
    ``READ_ONLY_MP_GRANTS`` are the only exceptions.

    Args:
        path: The ``SKILL.md`` file (for the message).
        value: Its ``allowed-tools`` value.

    Returns:
        One violation per rejected entry.

    Example:
        ```python
        allowed_tools_violations(Path("SKILL.md"), "Bash(mp help *) Bash(mp *)")
        # ["SKILL.md:1: allowed-tools grants 'Bash(mp *)'; ..."]
        ```
    """
    found: list[str] = []
    for entry in _split_tools(value):
        normal = re.sub(r"\s+", " ", entry)
        if normal in READ_ONLY_MP_GRANTS or not _BARE_GRANT.match(normal):
            continue
        found.append(
            f"{rel(path)}:1: allowed-tools grants {entry!r}; use the plugin "
            "venv path (${CLAUDE_PLUGIN_DATA}/venv/bin/...) or one of "
            "Bash(mp --version), Bash(mp help), Bash(mp help *)"
        )
    return found


_SYSTEM_PYTHON = re.compile(
    r"(?<![\w.-])python3\s+(?:-c\b|-m\s+mixpanel_headless\b|(?!-)\S+\.py\b)"
)
"""A run of ``python3 -c``, ``python3 -m mixpanel_headless``, or ``python3 x.py``.

A path prefix is still a match (``.../venv/bin/python3 -c``), because the
skills' permission pattern names ``python`` and denies ``python3``.
"""


def system_python_violations(path: Path, text: str) -> list[str]:
    """Find runs of the system ``python3`` in skill markdown.

    Args:
        path: The markdown file.
        text: Its content (prose and code blocks are both scanned).

    Returns:
        One violation per matching line.
    """
    return [
        f"{rel(path)}:{number}: runs system python3; use "
        f"${{CLAUDE_PLUGIN_DATA}}/venv/bin/python: {line.strip()[:120]}"
        for number, line in enumerate(text.splitlines(), start=1)
        if _SYSTEM_PYTHON.search(line)
    ]


_INJECTION = re.compile(r"(?:^|(?<=\s))!`(?P<cmd>[^`]+)`")
"""A ``!`command``` shell injection at the start of a line or after a space."""

_CLAUDE_SUBST = re.compile(r"\$\{CLAUDE_[A-Z0-9_]+\}")
"""A ``${CLAUDE_...}`` name that Claude Code substitutes in skill text."""

_BARE_COMMANDS = frozenset({"mp", "python", "python3"})
"""Commands that no skill ``allowed-tools`` grants without the venv path."""


def injection_violations(path: Path, text: str) -> list[str]:
    """Check each ``!`command``` line in skill markdown.

    A command may use ``${CLAUDE_...}`` substitutions but no other ``$``
    (no shell variable and no ``$(...)``), and no pipeline segment may start
    with a bare ``mp``, ``python``, or ``python3``, because the permission
    check would deny it and abort the skill.

    Args:
        path: The markdown file.
        text: Its content.

    Returns:
        One violation per failing command.
    """
    found: list[str] = []
    for number, line in enumerate(text.splitlines(), start=1):
        for match in _INJECTION.finditer(line):
            command = match.group("cmd")
            where = f"{rel(path)}:{number}"
            if "$" in _CLAUDE_SUBST.sub("", command):
                found.append(
                    f"{where}: ! line uses a shell variable or $(...): {command[:120]}"
                )
            segments = re.split(r"\|\|?|&&|;", command)
            heads = {seg.split()[0] for seg in segments if seg.split()}
            bare = sorted(heads & _BARE_COMMANDS)
            if bare:
                found.append(
                    f"{where}: ! line runs bare {', '.join(bare)} (not in "
                    f"allowed-tools; use the venv path): {command[:120]}"
                )
    return found
