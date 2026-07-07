"""Regression guard: documentation must not teach the removed kwargs API.

The 045-era migration made the four query models (InsightsQuery,
FunnelQuery, RetentionQuery, FlowQuery) the only public query API.
The published mkdocs site, plugin skills, and READMEs are actively fed
to LLM agents (help.py and the mixpanelyst skill point at the GitHub
Pages URLs), so a stale kwargs example doesn't just mislead a reader —
it becomes authoritative guidance for code generation. This scan fails
on any markdown surface that still shows a removed call shape.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).parents[2]

_DOC_ROOTS = ("docs", "mixpanel-plugin")
_DOC_FILES = ("README.md",)

_REMOVED_API_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Positional / kwargs calls the model-only signatures no longer accept
    ("ws.query(<str>)", re.compile(r"\bws\.query\(\s*[\"']")),
    ("ws.query(<list>)", re.compile(r"\bws\.query\(\s*\[")),
    ("ws.query(events=)", re.compile(r"\bws\.query\(\s*events=")),
    (
        "query(<str>, math=...)",
        re.compile(r"\bws\.query\((?!\s*InsightsQuery)[^)]*\bmath="),
    ),
    ("query_funnel(<old>)", re.compile(r"\bquery_funnel\(\s*(?:steps=|\[|[\"'])")),
    (
        "query_retention(<old>)",
        re.compile(r"\bquery_retention\(\s*(?:born_event=|[\"'])"),
    ),
    ("query_flow(<old>)", re.compile(r"\bquery_flow\(\s*(?:event=|forward=|[\"'])")),
    ("build_params(<old>)", re.compile(r"\bbuild_params\(\s*(?:[\"']|\[|events=)")),
    (
        "build_funnel_params(<old>)",
        re.compile(r"\bws\.build_funnel_params\(\s*(?:steps=|\[|[\"'])"),
    ),
    (
        "build_retention_params(<old>)",
        re.compile(r"\bws\.build_retention_params\(\s*(?:born_event=|[\"'])"),
    ),
    (
        "build_flow_params(<old>)",
        re.compile(r"\bws\.build_flow_params\(\s*(?:event=|[\"'])"),
    ),
    # Signature reference blocks showing the removed kwargs signatures
    ("def query(self, events...)", re.compile(r"def query\(\s*self,\s*events")),
    (
        "def query_funnel(self, steps...)",
        re.compile(r"def query_funnel\(\s*self,\s*steps"),
    ),
    (
        "def query_retention(self, born_event...)",
        re.compile(r"def query_retention\(\s*self,\s*born_event"),
    ),
    (
        "def query_flow(self, event...)",
        re.compile(r"def query_flow\(\s*self,\s*event"),
    ),
)


def _markdown_files() -> list[Path]:
    """Collect every markdown file in the documented surfaces."""
    files: list[Path] = [
        _REPO_ROOT / name for name in _DOC_FILES if (_REPO_ROOT / name).exists()
    ]
    for root in _DOC_ROOTS:
        files.extend(sorted((_REPO_ROOT / root).rglob("*.md")))
    return files


def test_docs_do_not_teach_removed_kwargs_api() -> None:
    """No markdown surface shows a removed query call shape."""
    offenders: list[str] = []
    for path in _markdown_files():
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(_REPO_ROOT)
        for lineno, line in enumerate(text.splitlines(), start=1):
            for label, pattern in _REMOVED_API_PATTERNS:
                if pattern.search(line):
                    offenders.append(f"{rel}:{lineno} [{label}] {line.strip()}")
                    break
        # Signature reference blocks span lines — scan the whole text too
        for label, pattern in _REMOVED_API_PATTERNS:
            if label.startswith("def "):
                for m in pattern.finditer(text):
                    lineno = text.count("\n", 0, m.start()) + 1
                    offenders.append(f"{rel}:{lineno} [{label}] (multi-line)")
    assert not offenders, (
        f"{len(offenders)} removed-API example(s) in docs "
        "(migrate to the query models):\n" + "\n".join(offenders[:50])
    )
