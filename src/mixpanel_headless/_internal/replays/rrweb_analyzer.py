"""rrweb event-stream analyzer (044-session-replay, US2/T055).

Walks the raw rrweb event stream, maintains DOM state, and emits two
parallel outputs from a single pass:

- a list of :class:`mixpanel_headless.types.UserAction` records (the
  structured surface that :class:`ReplayBundle` aggregations consume), and
- a plain-text markdown timeline (``{timestamp_seconds}: {description}``
  per line) for stdout / LLM consumption.

This module is a fork. The initial cut took its DOM tracker, debouncing
thresholds, mouse-interaction naming, and console-plugin event detection
from a similar analyzer used internally inside Mixpanel; from this point
on it lives entirely in this repo and evolves on its own cadence. The
public surface here is wider than the initial source: :class:`AnalyzerResult`
exposes both the structured action list and the markdown string so
:class:`Workspace.fetch_replay` and :class:`ReplayBundle` can lean on
schema-stable activity labels.

The structured-action mapping from internal interactions to public
``UserAction.action`` literals:

- ``Navigated to {url}`` → ``navigate``
- ``Clicked {desc}`` / ``Double-clicked`` / ``Right-clicked`` → ``click``
- ``Focused {desc}`` → ``click`` (with ``metadata["interaction"]="focus"``)
- ``Tapped {desc}`` → ``touch_start``
- ``Scrolled`` → ``scroll``
- ``Set {desc} to {state}`` / ``Entered ... in {desc}`` / ``Modified
  {desc}`` → ``input``
- ``Selected '{text}'`` / ``Selected text`` → ``select``
- ``Console error: {msg}`` → ``console_error``
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, cast
from urllib.parse import urlparse

from mixpanel_headless.types import UserAction

log = logging.getLogger(__name__)


# =============================================================================
# rrweb event-shape enums
# =============================================================================


class EventType(IntEnum):
    """RRWeb event types."""

    FULL_SNAPSHOT = 2
    INCREMENTAL_SNAPSHOT = 3
    META = 4
    PLUGIN = 6


class IncrementalSource(IntEnum):
    """RRWeb IncrementalSnapshot.data.source discriminators we handle."""

    MUTATION = 0
    MOUSE_INTERACTION = 2
    SCROLL = 3
    INPUT = 5
    SELECTION = 14


class MouseInteractionType(IntEnum):
    """MouseInteraction.data.type values we emit actions for."""

    CLICK = 2
    CONTEXT_MENU = 3
    DBL_CLICK = 4
    FOCUS = 5
    TOUCH_START = 7


class NodeType(IntEnum):
    """rrweb DOM node types."""

    ELEMENT = 2
    TEXT = 3


# =============================================================================
# Public result types
# =============================================================================


@dataclass(frozen=True)
class PageVisit:
    """A single page navigation extracted from Meta events.

    Attributes:
        timestamp: Unix ms timestamp of the Meta event.
        url: The navigated-to URL.
    """

    timestamp: int
    url: str


@dataclass(frozen=True)
class ConsoleError:
    """A console-error log entry extracted from the rrweb console plugin.

    Attributes:
        timestamp: Unix ms timestamp.
        message: Joined message text.
        url: Active page URL at the time of the error (None if unknown).
    """

    timestamp: int
    message: str
    url: str | None = None


@dataclass(frozen=True)
class AnalyzerResult:
    """The full bundle returned by :meth:`RrwebAnalyzer.analyze`.

    Attributes:
        actions: Structured :class:`UserAction` records in timestamp order;
            consumed by :class:`ReplayBundle` aggregations.
        markdown_summary: Plain-text markdown timeline
            (``{timestamp_seconds}: {description}`` per line).
        pages: Each Meta navigation as a :class:`PageVisit`.
        errors: Console errors emitted during the session.
    """

    actions: list[UserAction] = field(default_factory=list)
    markdown_summary: str = ""
    pages: list[PageVisit] = field(default_factory=list)
    errors: list[ConsoleError] = field(default_factory=list)


# =============================================================================
# DOMTracker
# =============================================================================


class DOMTracker:
    """Lightweight DOM state tracker.

    Tracks all nodes with metadata needed for user-action descriptions.
    Walks ``FullSnapshot`` roots, applies ``Mutation.adds`` / removes /
    text-changes / attribute-changes, and exposes
    :meth:`get_node_description` for human-readable element labels.
    """

    INTERACTIVE_TAGS = {
        "button",
        "a",
        "input",
        "textarea",
        "select",
        "form",
        "video",
        "audio",
        "svg",
        "img",
        "canvas",
    }

    DESCRIPTIVE_ATTRS = [
        "aria-label",
        "title",
        "alt",
        "placeholder",
        "href",
        "id",
        "type",
    ]

    MAX_ANCESTOR_DEPTH = 3
    MAX_NODES = 50000

    def __init__(self) -> None:
        """Initialize an empty node map + description cache."""
        self.nodes: dict[int, dict[str, Any]] = {}
        self._description_cache: dict[int, str] = {}
        self.reached_max_nodes = False

    @staticmethod
    def _sanitize_value(value: Any) -> Any:
        """Strip / drop trivially uninformative string values (empty, 'none')."""
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped or stripped.lower() == "none":
                return ""
            return stripped
        return value

    def add_node(self, node: dict[str, Any], parent_id: int | None = None) -> None:
        """Walk a FullSnapshot / mutation-add root and record element nodes.

        Args:
            node: The rrweb node dict to ingest.
            parent_id: Optional parent rrweb node id for ancestor traversal.
        """
        queue: list[tuple[dict[str, Any], int | None]] = [(node, parent_id)]

        while queue:
            current_node, current_parent_id = queue.pop(0)

            node_id = current_node.get("id")
            if not node_id:
                continue

            if (
                node_id not in self.nodes
                and len(self.nodes) >= self.MAX_NODES
                and not self.reached_max_nodes
            ):
                # Expected on large real sessions (complex SPA full-snapshots
                # routinely exceed MAX_NODES); the analyzer degrades gracefully
                # by skipping new nodes. DEBUG, not WARNING — this matches the
                # upstream analyzer's intent and isn't actionable for callers.
                log.debug("DOMTracker reached maximum node limit; skipping new nodes")
                self.reached_max_nodes = True
                continue

            node_type = current_node.get("type")

            self.nodes[node_id] = {
                "type": node_type,
                "parent_id": current_parent_id,
            }

            if node_type == NodeType.ELEMENT:
                tag_name = current_node.get("tagName", "").lower()
                attributes = current_node.get("attributes", {})
                self.nodes[node_id]["tag"] = tag_name
                sanitized_attrs = {
                    k: v for k, v in attributes.items() if self._sanitize_value(v)
                }
                descriptive_attrs = {
                    attr: sanitized_attrs[attr]
                    for attr in self.DESCRIPTIVE_ATTRS
                    if attr in sanitized_attrs
                }

                if descriptive_attrs:
                    self.nodes[node_id]["attributes"] = descriptive_attrs

                if tag_name in self.INTERACTIVE_TAGS:
                    self.nodes[node_id]["text"] = self._extract_text(current_node)

            elif node_type == NodeType.TEXT:
                text_content = self._sanitize_value(current_node.get("textContent", ""))
                if text_content:
                    self.nodes[node_id]["text"] = text_content
                    if (
                        current_parent_id
                        and current_parent_id in self.nodes
                        and "text" in self.nodes[current_parent_id]
                    ):
                        self.nodes[current_parent_id]["text"] = text_content

            for child in current_node.get("childNodes", []):
                queue.append((child, node_id))

    def _extract_text(self, node: dict[str, Any]) -> str:
        """Concatenate direct text-child content for an interactive element."""
        texts: list[str] = []
        for child in node.get("childNodes", []):
            if child.get("type") == NodeType.TEXT:
                text = self._sanitize_value(child.get("textContent", ""))
                if text:
                    texts.append(text)
        return " ".join(texts)

    def remove_node(self, node_id: int) -> None:
        """Drop a node + its cached description (mutation remove)."""
        self.nodes.pop(node_id, None)
        self._description_cache.pop(node_id, None)

    def update_text(self, node_id: int, text: str) -> None:
        """Update the text of a node + its interactive ancestor, if any."""
        sanitized_text = self._sanitize_value(text)
        if node_id in self.nodes:
            if sanitized_text:
                self.nodes[node_id]["text"] = sanitized_text
            else:
                self.nodes[node_id].pop("text", None)
            self._description_cache.pop(node_id, None)

        parent_id = self.nodes.get(node_id, {}).get("parent_id")
        if parent_id and parent_id in self.nodes and "text" in self.nodes[parent_id]:
            if sanitized_text:
                self.nodes[parent_id]["text"] = sanitized_text
            else:
                self.nodes[parent_id].pop("text", None)
            self._description_cache.pop(parent_id, None)

    def update_attributes(self, node_id: int, attributes: dict[str, Any]) -> None:
        """Merge new descriptive attributes onto an existing node."""
        sanitized_attrs = {
            k: v for k, v in attributes.items() if self._sanitize_value(v)
        }
        descriptive_attrs = {
            attr: sanitized_attrs[attr]
            for attr in self.DESCRIPTIVE_ATTRS
            if attr in sanitized_attrs
        }
        if node_id in self.nodes:
            if "attributes" not in self.nodes[node_id]:
                self.nodes[node_id]["attributes"] = {}
            self.nodes[node_id]["attributes"].update(descriptive_attrs)
            self._description_cache.pop(node_id, None)

    def get_node_description(self, node_id: int) -> str:
        """Best-effort human-readable description of a node.

        Returns a description built from the node's own tag / attributes /
        text, falling back to ancestor context, then to the literal
        ``"element"`` sentinel.
        """
        if node_id in self._description_cache:
            return self._description_cache[node_id]

        direct_desc = self._build_node_description(node_id)
        if direct_desc:
            self._description_cache[node_id] = direct_desc
            return direct_desc

        ancestor_desc = self._get_ancestor_context(node_id)
        if ancestor_desc:
            self._description_cache[node_id] = ancestor_desc
            return ancestor_desc

        fallback = "element"
        self._description_cache[node_id] = fallback
        return fallback

    def _build_node_description(self, node_id: int) -> str | None:
        """Build a description from the node's own metadata, if any.

        Returns:
            The description string, or None when the node carries no
            meaningful descriptive info (caller falls back to ancestor
            traversal).
        """
        if node_id not in self.nodes:
            return None

        node_data = self.nodes[node_id]
        tag = node_data.get("tag", "element")
        attrs = node_data.get("attributes", {})
        text = node_data.get("text", "")
        parts: list[str] = [tag]
        has_meaningful_info = False

        if attrs.get("aria-label") is not None:
            parts.append(f'"{attrs["aria-label"]}"')
            has_meaningful_info = True
        elif attrs.get("title") is not None:
            parts.append(f'"{attrs["title"]}"')
            has_meaningful_info = True
        elif attrs.get("alt") is not None:
            parts.append(f'alt="{attrs["alt"]}"')
            has_meaningful_info = True
        elif text:
            parts.append(f'"{text}"')
            has_meaningful_info = True
        elif attrs.get("placeholder") is not None:
            parts.append(f'placeholder="{attrs["placeholder"]}"')
            has_meaningful_info = True

        if attrs.get("href") is not None and tag == "a":
            href = attrs["href"]
            if href.startswith("http"):
                try:
                    parsed = urlparse(href)
                    path = parsed.path
                    if path and path != "/":
                        parts.append(f"to {path}")
                        has_meaningful_info = True
                except Exception:  # noqa: BLE001 — defensively swallow URL parse failures
                    pass

        if attrs.get("id") is not None and not has_meaningful_info:
            parts.append(f"#{attrs['id']}")
            has_meaningful_info = True

        if tag == "input" and attrs.get("type") is not None:
            parts.append(f"type={attrs['type']}")
            has_meaningful_info = True

        if has_meaningful_info:
            return " ".join(parts)
        return None

    def _get_ancestor_context(self, node_id: int) -> str | None:
        """Walk up to :data:`MAX_ANCESTOR_DEPTH` parents for descriptive context.

        Returns:
            ``"{tag} in {parent_description}"`` when a describable ancestor
            is reachable; None otherwise.
        """
        if node_id not in self.nodes:
            return None

        node_data = self.nodes[node_id]
        tag = node_data.get("tag", "element")

        parent_id = node_data.get("parent_id")
        depth = 0
        visited: set[int] = set()

        while parent_id and depth < self.MAX_ANCESTOR_DEPTH:
            if parent_id in visited:
                break
            visited.add(parent_id)

            parent_desc = self._description_cache.get(
                parent_id
            ) or self._build_node_description(parent_id)
            if parent_desc:
                return f"{tag} in {parent_desc}"

            if parent_id in self.nodes:
                parent_id = self.nodes[parent_id].get("parent_id")
                depth += 1
            else:
                break

        return None


# =============================================================================
# EventAnalyzer — emits structured public UserAction + description lines
# =============================================================================


# Maps MouseInteractionType to a human-readable verb used in description strings.
_MOUSE_INTERACTION_NAMES: dict[int, str] = {
    int(MouseInteractionType.CLICK): "clicked",
    int(MouseInteractionType.DBL_CLICK): "double-clicked",
    int(MouseInteractionType.CONTEXT_MENU): "right-clicked",
    int(MouseInteractionType.FOCUS): "focused",
    int(MouseInteractionType.TOUCH_START): "tapped",
}

# Maps the human-readable verb to the public UserAction.action literal.
# All click-family interactions collapse to "click" so ReplayBundle
# aggregations (top_clicks, rage_clicks) work uniformly;
# the original interaction is preserved in metadata["interaction"].
_INTERACTION_TO_ACTION: dict[str, str] = {
    "clicked": "click",
    "double-clicked": "click",
    "right-clicked": "click",
    "focused": "click",
    "tapped": "touch_start",
}


class EventAnalyzer:
    """Single-pass rrweb event walker emitting structured + textual actions.

    Applies per-source debouncing (scroll / input / selection at 1s each)
    and plugin-event filtering for ``rrweb/console@*`` console errors.
    Emits the public :class:`mixpanel_headless.types.UserAction` so
    downstream aggregations keep their schema-stable action literals.
    """

    SCROLL_DEBOUNCE_MS = 1000
    SELECTION_DEBOUNCE_MS = 1000
    INPUT_DEBOUNCE_MS = 1000

    def __init__(self, dom_tracker: DOMTracker | None = None) -> None:
        """Initialize the analyzer with an optional pre-seeded DOM tracker."""
        self.dom_tracker = dom_tracker or DOMTracker()
        self.user_actions: list[UserAction] = []
        # Parallel list of (timestamp_ms, description) pairs for the markdown
        # reporter — kept distinct from user_actions so we render the
        # `{ts}: {desc}` line format directly instead of reverse-engineering
        # it from the structured UserAction objects.
        self.descriptions: list[tuple[int, str]] = []
        self.pages: list[PageVisit] = []
        self.errors: list[ConsoleError] = []
        self.current_url: str | None = None
        self.last_scroll_time = 0
        self.last_selection_time = 0
        self.last_input_time: dict[int, int] = {}

    def _emit(
        self,
        timestamp: int,
        action: str,
        description: str,
        *,
        target_node_id: int | None = None,
        target_desc: str | None = None,
        url: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Append both a structured UserAction and a (timestamp, description) line.

        Args:
            timestamp: Unix ms.
            action: One of the public ``UserAction.action`` literal values.
            description: Human-readable description text for the markdown line.
            target_node_id: rrweb node id, if applicable.
            target_desc: Human-readable element label (defaults to the
                description when not provided).
            url: Active page URL.
            metadata: Action-specific extras.
        """
        self.descriptions.append((timestamp, description))
        self.user_actions.append(
            UserAction(
                timestamp=timestamp,
                action=cast(Any, action),
                target_node_id=target_node_id,
                target_desc=target_desc or description,
                url=url if url is not None else self.current_url,
                metadata=metadata or {},
                description=description,
            )
        )

    def process_event(self, event: dict[str, Any]) -> None:
        """Dispatch a single rrweb event to its type-specific handler."""
        event_type = event.get("type")
        timestamp = int(event.get("timestamp", 0))
        raw_data = event.get("data")
        data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}

        if event_type == EventType.META:
            self._process_meta(timestamp, data)
        elif event_type == EventType.FULL_SNAPSHOT:
            self._process_full_snapshot(timestamp, data)
        elif event_type == EventType.INCREMENTAL_SNAPSHOT:
            self._process_incremental_snapshot(timestamp, data)
        elif event_type == EventType.PLUGIN:
            self._process_plugin_event(timestamp, data)

    def _process_meta(self, timestamp: int, data: dict[str, Any]) -> None:
        """Handle navigations (Meta events): update current URL + emit action."""
        url = data.get("href")
        if url:
            self.current_url = url
            self.pages.append(PageVisit(timestamp=timestamp, url=url))
            self._emit(
                timestamp,
                "navigate",
                f"Navigated to {url}",
                url=url,
                metadata={"url": url},
            )

    def _process_full_snapshot(self, timestamp: int, data: dict[str, Any]) -> None:
        """Ingest a FullSnapshot root into the DOM tracker; emit no action."""
        _ = timestamp
        node = data.get("node")
        if node:
            self.dom_tracker.add_node(node)

    def _process_incremental_snapshot(
        self, timestamp: int, data: dict[str, Any]
    ) -> None:
        """Route incremental snapshots by their `data.source` discriminator."""
        source = data.get("source")
        if source == IncrementalSource.MUTATION:
            self._process_mutation(timestamp, data)
        elif source == IncrementalSource.MOUSE_INTERACTION:
            self._process_mouse_interaction(timestamp, data)
        elif source == IncrementalSource.SCROLL:
            self._process_scroll(timestamp, data)
        elif source == IncrementalSource.INPUT:
            self._process_input(timestamp, data)
        elif source == IncrementalSource.SELECTION:
            self._process_selection(timestamp, data)

    def _process_mutation(self, timestamp: int, data: dict[str, Any]) -> None:
        """Apply Mutation adds / removes / texts / attributes to the DOM tracker."""
        _ = timestamp
        for add in data.get("adds", []) or []:
            node = add.get("node")
            parent_id = add.get("parentId")
            if node:
                self.dom_tracker.add_node(node, parent_id)
        for remove in data.get("removes", []) or []:
            node_id = remove.get("id")
            if node_id:
                self.dom_tracker.remove_node(node_id)
        for text_change in data.get("texts", []) or []:
            node_id = text_change.get("id")
            value = text_change.get("value")
            if node_id and value:
                self.dom_tracker.update_text(node_id, value)
        for attr_change in data.get("attributes", []) or []:
            node_id = attr_change.get("id")
            attributes = attr_change.get("attributes")
            if node_id and attributes:
                self.dom_tracker.update_attributes(node_id, attributes)

    def _process_mouse_interaction(self, timestamp: int, data: dict[str, Any]) -> None:
        """Emit click-family / focus / touch-start actions for interactions."""
        interaction_type = data.get("type")
        node_id = data.get("id")

        if not isinstance(interaction_type, int):
            return
        verb = _MOUSE_INTERACTION_NAMES.get(interaction_type)
        if not verb:
            return

        node_desc = (
            self.dom_tracker.get_node_description(node_id)
            if node_id
            else "unknown element"
        )
        if node_desc == "unknown element":
            return

        action_literal = _INTERACTION_TO_ACTION.get(verb, "click")
        self._emit(
            timestamp,
            action_literal,
            f"{verb.capitalize()} {node_desc}",
            target_node_id=node_id if isinstance(node_id, int) else None,
            target_desc=node_desc,
            metadata={"interaction": verb},
        )

    def _process_scroll(self, timestamp: int, data: dict[str, Any]) -> None:
        """Emit a debounced scroll action (one per :data:`SCROLL_DEBOUNCE_MS`)."""
        _ = data
        if timestamp - self.last_scroll_time > self.SCROLL_DEBOUNCE_MS:
            self._emit(timestamp, "scroll", "Scrolled", target_desc="(viewport)")
        self.last_scroll_time = timestamp

    def _process_input(self, timestamp: int, data: dict[str, Any]) -> None:
        """Emit a debounced input action (per-node, :data:`INPUT_DEBOUNCE_MS`)."""
        node_id = data.get("id")
        text = data.get("text", "")
        is_checked = data.get("isChecked")

        if node_id:
            last_time = self.last_input_time.get(node_id, 0)
            if timestamp - last_time <= self.INPUT_DEBOUNCE_MS:
                return
            self.last_input_time[node_id] = timestamp

        node_desc = (
            self.dom_tracker.get_node_description(node_id) if node_id else "input"
        )

        if is_checked is not None:
            state = "checked" if is_checked else "unchecked"
            description = f"Set {node_desc} to {state}"
        elif text:
            description = f"Entered '{text}' in {node_desc}"
        else:
            description = f"Modified {node_desc}"

        self._emit(
            timestamp,
            "input",
            description,
            target_node_id=node_id if isinstance(node_id, int) else None,
            target_desc=node_desc,
            metadata={
                "text_length": len(text) if isinstance(text, str) else 0,
                "is_checked": is_checked,
            },
        )

    def _process_selection(self, timestamp: int, data: dict[str, Any]) -> None:
        """Emit a debounced text-selection action when the user selects text."""
        ranges = data.get("ranges", [])
        if not ranges:
            return

        if timestamp - self.last_selection_time > self.SELECTION_DEBOUNCE_MS:
            selected_texts: list[str] = []

            for range_data in ranges:
                start_node_id = range_data.get("start")
                end_node_id = range_data.get("end")
                start_offset = range_data.get("startOffset", 0)
                end_offset = range_data.get("endOffset", 0)

                if (
                    start_node_id == end_node_id
                    and start_node_id
                    and start_node_id in self.dom_tracker.nodes
                ):
                    node_data = self.dom_tracker.nodes[start_node_id]
                    if "text" in node_data:
                        text_content = node_data["text"]
                        text = text_content[start_offset:end_offset].strip()
                        if text:
                            selected_texts.append(text)

            if selected_texts:
                combined = " ... ".join(selected_texts)
                description = f"Selected '{combined}'"
            else:
                description = "Selected text"

            self._emit(
                timestamp,
                "select",
                description,
                target_desc="(selection)",
                metadata={"range_count": len(ranges)},
            )
        self.last_selection_time = timestamp

    def _process_plugin_event(self, timestamp: int, data: dict[str, Any]) -> None:
        """Emit console_error actions for `rrweb/console@*` plugin payloads."""
        plugin = data.get("plugin", "")
        if not plugin.startswith("rrweb/console@"):
            return

        payload = data.get("payload", {})
        level = payload.get("level", "")
        if level != "error":
            return

        messages = payload.get("payload", [])
        if not messages:
            return

        message = " ".join(str(m).strip('"') for m in messages)
        if not message:
            return

        self.errors.append(
            ConsoleError(timestamp=timestamp, message=message, url=self.current_url)
        )
        self._emit(
            timestamp,
            "console_error",
            f"Console error: {message}",
            target_desc=message,
            metadata={"message": message},
        )


# =============================================================================
# Markdown reporter
# =============================================================================


def _collapse_timeline(lines: list[tuple[int, str]]) -> str:
    """Render ``{ts_seconds}: {description}`` lines, collapsing runs.

    Consecutive entries with an identical description are coalesced into a
    single line with a ``(×N)`` suffix — e.g. a data grid that re-renders the
    same cell 67 times becomes one line, not 67. The timestamp shown is the
    first in the run.

    Args:
        lines: ``(timestamp_ms, description)`` pairs in timeline order.

    Returns:
        Newline-joined markdown; ``""`` for empty input.
    """
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        ts, desc = lines[i]
        j = i + 1
        while j < n and lines[j][1] == desc:
            j += 1
        run = j - i
        suffix = f" (×{run})" if run > 1 else ""
        out.append(f"{ts // 1000}: {desc}{suffix}")
        i = j
    return "\n".join(out)


class MarkdownReporter:
    """Render ``{ts_seconds}: {description}`` lines from a description list."""

    def __init__(self, descriptions: list[tuple[int, str]]) -> None:
        """Initialize with parallel (timestamp_ms, description) pairs."""
        self.descriptions = descriptions

    def generate(self) -> str:
        """Produce the markdown string, collapsing consecutive duplicates.

        Returns:
            ``"No user actions recorded."`` for an empty list; otherwise
            one line per (timestamp, description) run via
            :func:`_collapse_timeline`.
        """
        if not self.descriptions:
            return "No user actions recorded."
        return _collapse_timeline(self.descriptions)


# =============================================================================
# Public entry point
# =============================================================================


class RrwebAnalyzer:
    """Convert a raw rrweb event stream into normalized actions + markdown.

    Stateless across calls: each :meth:`analyze` invocation constructs its
    own :class:`DOMTracker` + :class:`EventAnalyzer`. Inputs are not
    mutated; events are sorted by timestamp before processing.

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
            events: Raw rrweb event dicts. Order doesn't matter — the
                analyzer sorts a shallow copy by ``timestamp`` before
                walking.

        Returns:
            An :class:`AnalyzerResult` with the action list, markdown
            timeline, page visits, and console errors populated. Empty
            on empty input.
        """
        if not events:
            return AnalyzerResult()

        sorted_events = sorted(events, key=lambda e: int(e.get("timestamp", 0)))

        dom_tracker = DOMTracker()
        event_analyzer = EventAnalyzer(dom_tracker)
        for event in sorted_events:
            event_analyzer.process_event(event)

        markdown = MarkdownReporter(event_analyzer.descriptions).generate()
        log.info("Generated %d user actions", len(event_analyzer.user_actions))
        return AnalyzerResult(
            actions=event_analyzer.user_actions,
            markdown_summary=markdown,
            pages=event_analyzer.pages,
            errors=event_analyzer.errors,
        )


def analyze_events(rrweb_events: list[dict[str, Any]]) -> str:
    """Convenience entry: walk events + return the markdown string.

    Sugar for ``RrwebAnalyzer().analyze(events).markdown_summary`` for
    callers that only want the markdown timeline.

    Args:
        rrweb_events: List of rrweb event dicts.

    Returns:
        The markdown timeline string.

    Raises:
        ValueError: ``rrweb_events`` is empty or not a list.
    """
    if not rrweb_events:
        raise ValueError("Events list cannot be empty")
    if not isinstance(rrweb_events, list):
        raise ValueError("Events must be a list of dictionaries")

    log.info("Analyzing %d rrweb events", len(rrweb_events))
    return RrwebAnalyzer().analyze(rrweb_events).markdown_summary


# Used by Replay.summary_markdown to render a timeline from the structured
# action list. Each UserAction carries a full ``description`` (e.g.
# 'Clicked button "Sign in"'); ``target_desc`` is the fallback for actions
# built without the analyzer (hand-constructed fixtures).
def _render_markdown(
    actions: list[UserAction], pages: list[PageVisit] | None = None
) -> str:
    """Render a markdown timeline from a structured action list.

    Renders each action's full ``description`` (falling back to
    ``target_desc`` when empty) and collapses consecutive duplicates via
    :func:`_collapse_timeline`, matching the analyzer's ``markdown_summary``.

    Args:
        actions: Structured action list (may be empty).
        pages: Optional page list (currently unused; reserved for the
            future "Pages visited" preamble).

    Returns:
        Multi-line markdown string. Empty when ``actions`` is empty.
    """
    _ = pages
    if not actions:
        return ""
    return _collapse_timeline(
        [(a.timestamp, a.description or a.target_desc) for a in actions]
    )
