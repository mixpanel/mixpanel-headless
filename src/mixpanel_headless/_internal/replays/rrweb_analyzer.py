"""Pragmatic rrweb event-stream analyzer (044-session-replay, US2/T055).

Walks the raw rrweb event stream and emits normalized :class:`UserAction`
records plus a markdown timeline. Pure stdlib — no third-party deps —
so it works in every environment ``mixpanel-headless`` already supports.

**Source provenance**: the spec calls for a one-time port of
``analytics/backend/replays/rrweb_analyzer.py`` from Mixpanel's
analytics monorepo. That source is not accessible from this repo, so
this file is a from-scratch implementation against the rrweb-types
event spec and the documented Phase 1 fixture
(``tests/fixtures/rrweb/sample-replay-001.json``). The public surface
(``RrwebAnalyzer.analyze``, the ``AnalyzerResult`` dataclass) matches
what Phase 2 callers — :class:`Workspace.fetch_replay`,
:class:`ReplayBundle` aggregations — expect.

**Coverage** (Phase 2 baseline):

- Type 4 (Meta) → ``navigate`` action; updates active URL
- Type 3 source 2 type 2 (MouseInteraction Click) → ``click`` action
- Type 3 source 5 (Input) → ``input`` action with ``text_length``
- Type 3 source 3 (Scroll) → ``scroll`` action
- Type 3 source 4 (ViewportResize) → ``viewport_resize`` action
- Type 3 source 11 + ``level: "error"`` (Log plugin) → ``console_error``
- Type 2 (FullSnapshot) / Type 3 source 0 (Mutation) → updates the
  DOM tracker; no action emitted

A "DOM tracker" walks ``FullSnapshot`` nodes plus IncrementalSnapshot
Mutation events so the analyzer can produce human-readable target
descriptions (``button "Sign in"``, ``input[type=email]``) instead of
bare node IDs.

**Next upstream diff due**: 2026-Q4. Re-diff this file against
``analytics/backend/replays/rrweb_analyzer.py`` once that path becomes
reachable and pick up any new IncrementalSource handlers / dead-click
heuristics that ship upstream in the interim.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from mixpanel_headless.types import UserAction

# rrweb event discriminators reused throughout.
_TYPE_FULL_SNAPSHOT = 2
_TYPE_INCREMENTAL_SNAPSHOT = 3
_TYPE_META = 4

_SOURCE_MUTATION = 0
_SOURCE_MOUSE_INTERACTION = 2
_SOURCE_SCROLL = 3
_SOURCE_VIEWPORT_RESIZE = 4
_SOURCE_INPUT = 5
_SOURCE_LOG = 11

_MOUSE_TYPE_CLICK = 2

# Default truncation for description strings so we never balloon a
# bundle DataFrame with multi-kilobyte cells.
_DESC_TRUNCATE = 80


@dataclass(frozen=True)
class PageVisit:
    """A single page navigation extracted from Meta events."""

    timestamp: int
    url: str


@dataclass(frozen=True)
class ConsoleError:
    """A console-error log entry extracted from rrweb's Log plugin events."""

    timestamp: int
    message: str
    url: str | None


@dataclass(frozen=True)
class AnalyzerResult:
    """The full bundle returned by :meth:`RrwebAnalyzer.analyze`.

    Attributes:
        actions: Normalized :class:`UserAction` records in timestamp order.
        markdown_summary: Human-readable markdown timeline of the session.
        pages: Each Meta navigation as a :class:`PageVisit`.
        errors: Console errors emitted during the session.
    """

    actions: list[UserAction] = field(default_factory=list)
    markdown_summary: str = ""
    pages: list[PageVisit] = field(default_factory=list)
    errors: list[ConsoleError] = field(default_factory=list)


class _DomTracker:
    """Maintain a node_id → element-info map across rrweb mutations.

    rrweb nests its DOM snapshots arbitrarily deep. The tracker walks
    each ``FullSnapshot.data.node`` recursively, and applies
    ``Mutation.adds`` to extend the map. ``Mutation.removes`` and
    ``Mutation.attributes`` are deliberately NOT modeled — for label
    purposes the tracker only needs the element's tag + attributes at
    interaction time, which the initial snapshot + adds cover for the
    vast majority of clicks.
    """

    def __init__(self) -> None:
        """Initialize an empty node map."""
        self._nodes: dict[int, dict[str, Any]] = {}

    def ingest_snapshot(self, node: Any) -> None:
        """Recursively walk a FullSnapshot's root node, recording each element."""
        self._walk(node)

    def ingest_adds(self, adds: list[dict[str, Any]] | None) -> None:
        """Apply ``Mutation.adds`` so freshly inserted nodes are findable."""
        if not adds:
            return
        for add in adds:
            node = add.get("node")
            if node is not None:
                self._walk(node)

    def describe(self, node_id: int | None) -> str:
        """Produce a human-readable description of the node, if known.

        Examples:
        - ``button "Sign in"`` for ``<button>Sign in</button>``
        - ``input[type=email]`` for an email input
        - ``div#main`` for a node with an id attribute
        - ``a "Edit profile"`` for ``<a>Edit profile</a>``

        Args:
            node_id: rrweb node identifier; ``None`` returns the
                ``(unknown)`` placeholder.

        Returns:
            Best-effort element description. Always non-empty.
        """
        if node_id is None or node_id not in self._nodes:
            return "(unknown)"
        info = self._nodes[node_id]
        tag = str(info.get("tagName", "")).lower() or "(unknown)"
        attrs = info.get("attributes") or {}
        text = info.get("text")

        if tag in {"button", "a"} and text:
            return f'{tag} "{text[:_DESC_TRUNCATE]}"'
        if tag == "input":
            input_type = attrs.get("type") or "text"
            return f"input[type={input_type}]"
        if tag in {"textarea", "select"}:
            return tag
        if "id" in attrs and attrs["id"]:
            return f"{tag}#{attrs['id']}"
        if "data-testid" in attrs and attrs["data-testid"]:
            return f"{tag}[data-testid={attrs['data-testid']}]"
        if text:
            return f'{tag} "{text[:_DESC_TRUNCATE]}"'
        return tag

    def attrs(self, node_id: int | None) -> dict[str, Any]:
        """Return the attribute dict for the node, or empty when unknown."""
        if node_id is None or node_id not in self._nodes:
            return {}
        attrs = self._nodes[node_id].get("attributes") or {}
        return dict(attrs)

    def _walk(self, node: Any) -> None:
        """Recursively record element nodes plus their first child text."""
        if not isinstance(node, dict):
            return
        node_id = node.get("id")
        # rrweb node types: 0=Document, 1=DocumentType, 2=Element, 3=Text, 4=CDATA, 5=Comment.
        if node.get("type") == 2 and isinstance(node_id, int):
            info: dict[str, Any] = {
                "tagName": node.get("tagName", ""),
                "attributes": dict(node.get("attributes", {})),
            }
            # Pull the first text-child as the element's "text" so
            # describe() can produce 'button "Sign in"'-style labels.
            for child in node.get("childNodes", []) or []:
                if isinstance(child, dict) and child.get("type") == 3:
                    text = child.get("textContent")
                    if isinstance(text, str) and text.strip():
                        info["text"] = text.strip()
                        break
            self._nodes[node_id] = info
        for child in node.get("childNodes", []) or []:
            self._walk(child)


class RrwebAnalyzer:
    """Convert a raw rrweb event stream into normalized actions + summary.

    The analyzer is stateless across calls — each :meth:`analyze` call
    constructs its own DOM tracker. Inputs are not mutated.

    Example:
        ```python
        analyzer = RrwebAnalyzer()
        result = analyzer.analyze(rrweb_events)
        for action in result.actions:
            print(action.timestamp, action.action, action.target_desc)
        print(result.markdown_summary)
        ```
    """

    def analyze(self, events: list[dict[str, Any]]) -> AnalyzerResult:
        """Walk ``events`` once and produce the :class:`AnalyzerResult`.

        Args:
            events: A timestamp-sorted list of raw rrweb event dicts (or
                any order — the analyzer sorts a shallow copy before
                walking).

        Returns:
            An :class:`AnalyzerResult` with the action list, markdown
            timeline, page visits, and console errors populated. Empty
            lists / empty string on an empty event stream.
        """
        if not events:
            return AnalyzerResult(actions=[], markdown_summary="", pages=[], errors=[])

        # Sort defensively — analyzer behavior should be order-stable.
        sorted_events = sorted(events, key=lambda e: int(e.get("timestamp", 0)))

        tracker = _DomTracker()
        actions: list[UserAction] = []
        pages: list[PageVisit] = []
        errors: list[ConsoleError] = []
        current_url: str | None = None

        for event in sorted_events:
            type_ = event.get("type")
            raw_data = event.get("data")
            data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
            timestamp = int(event.get("timestamp", 0))

            if type_ == _TYPE_META:
                href = data.get("href")
                if isinstance(href, str):
                    current_url = href
                    pages.append(PageVisit(timestamp=timestamp, url=href))
                    actions.append(
                        UserAction(
                            timestamp=timestamp,
                            action="navigate",
                            target_node_id=None,
                            target_desc=href[:_DESC_TRUNCATE] or "(no-url)",
                            url=href,
                            metadata={"href": href},
                        )
                    )
                continue

            if type_ == _TYPE_FULL_SNAPSHOT:
                root = data.get("node")
                if root is not None:
                    tracker.ingest_snapshot(root)
                continue

            if type_ != _TYPE_INCREMENTAL_SNAPSHOT:
                continue

            source = data.get("source")

            if source == _SOURCE_MUTATION:
                tracker.ingest_adds(data.get("adds"))
                continue

            if source == _SOURCE_MOUSE_INTERACTION:
                if data.get("type") != _MOUSE_TYPE_CLICK:
                    continue
                node_id = data.get("id") if isinstance(data.get("id"), int) else None
                desc = tracker.describe(node_id)
                metadata: dict[str, Any] = {
                    "x": data.get("x"),
                    "y": data.get("y"),
                }
                attrs = tracker.attrs(node_id)
                if "data-testid" in attrs:
                    metadata["data-testid"] = attrs["data-testid"]
                actions.append(
                    UserAction(
                        timestamp=timestamp,
                        action="click",
                        target_node_id=node_id,
                        target_desc=desc,
                        url=current_url,
                        metadata=metadata,
                    )
                )
                continue

            if source == _SOURCE_INPUT:
                node_id = data.get("id") if isinstance(data.get("id"), int) else None
                desc = tracker.describe(node_id)
                text = data.get("text", "")
                metadata = {
                    "text_length": len(text) if isinstance(text, str) else 0,
                    "is_checked": bool(data.get("isChecked", False)),
                }
                attrs = tracker.attrs(node_id)
                if "data-testid" in attrs:
                    metadata["data-testid"] = attrs["data-testid"]
                actions.append(
                    UserAction(
                        timestamp=timestamp,
                        action="input",
                        target_node_id=node_id,
                        target_desc=desc,
                        url=current_url,
                        metadata=metadata,
                    )
                )
                continue

            if source == _SOURCE_SCROLL:
                node_id = data.get("id") if isinstance(data.get("id"), int) else None
                actions.append(
                    UserAction(
                        timestamp=timestamp,
                        action="scroll",
                        target_node_id=node_id,
                        target_desc=tracker.describe(node_id),
                        url=current_url,
                        metadata={"x": data.get("x"), "y": data.get("y")},
                    )
                )
                continue

            if source == _SOURCE_VIEWPORT_RESIZE:
                actions.append(
                    UserAction(
                        timestamp=timestamp,
                        action="viewport_resize",
                        target_node_id=None,
                        target_desc="(viewport)",
                        url=current_url,
                        metadata={
                            "width": data.get("width"),
                            "height": data.get("height"),
                        },
                    )
                )
                continue

            if source == _SOURCE_LOG and data.get("level") == "error":
                message = " ".join(str(p) for p in data.get("payload", []))
                errors.append(
                    ConsoleError(
                        timestamp=timestamp,
                        message=message,
                        url=current_url,
                    )
                )
                actions.append(
                    UserAction(
                        timestamp=timestamp,
                        action="console_error",
                        target_node_id=None,
                        target_desc=message[:_DESC_TRUNCATE] or "(console error)",
                        url=current_url,
                        metadata={"message": message},
                    )
                )
                continue

        markdown = _render_markdown(actions, pages)
        return AnalyzerResult(
            actions=actions,
            markdown_summary=markdown,
            pages=pages,
            errors=errors,
        )


def _render_markdown(actions: list[UserAction], pages: list[PageVisit]) -> str:
    """Render the action stream as a markdown timeline.

    The format is intended for direct stdout consumption — agents and
    operators read this for a quick "what happened in this session".

    Args:
        actions: All analyzer actions in timestamp order.
        pages: All Meta navigations.

    Returns:
        Multi-line markdown string. Empty string when ``actions`` is empty.
    """
    if not actions:
        return ""
    first_ts = actions[0].timestamp
    last_ts = actions[-1].timestamp
    duration_s = max(0, (last_ts - first_ts) // 1000)
    minutes, seconds = divmod(duration_s, 60)
    pages_count = len(pages)
    lines = [
        f"# Session — {minutes}m {seconds:02d}s — {pages_count} page(s)",
        "",
        "## Timeline",
        "",
    ]
    for action in actions:
        hhmmss = datetime.fromtimestamp(
            action.timestamp / 1000.0, tz=timezone.utc
        ).strftime("%H:%M:%S")
        if action.action == "navigate":
            lines.append(f"- {hhmmss} navigate to `{action.url or '(no-url)'}`")
        elif action.action == "click":
            lines.append(f"- {hhmmss} click `{action.target_desc}`")
        elif action.action == "input":
            length = action.metadata.get("text_length", 0) if action.metadata else 0
            lines.append(f"- {hhmmss} input `{action.target_desc}` ({length} chars)")
        elif action.action == "scroll":
            lines.append(f"- {hhmmss} scroll on `{action.target_desc}`")
        elif action.action == "viewport_resize":
            w = action.metadata.get("width") if action.metadata else None
            h = action.metadata.get("height") if action.metadata else None
            lines.append(f"- {hhmmss} viewport resize → {w}×{h}")
        elif action.action == "console_error":
            lines.append(f"- {hhmmss} console error: `{action.target_desc}`")
        else:
            lines.append(f"- {hhmmss} {action.action} on `{action.target_desc}`")
    return "\n".join(lines)
