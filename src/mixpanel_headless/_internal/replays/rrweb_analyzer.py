"""rrweb event-stream analyzer (044-session-replay).

Walks the raw rrweb event stream, maintains DOM state, and produces two
outputs from a single pass:

- a list of :class:`mixpanel_headless.types.UserAction` records in
  timestamp order (the structured surface that :class:`ReplayBundle`
  aggregations consume), and
- a plain-text markdown timeline (``{timestamp_seconds}: {description}``
  per line) for stdout / LLM consumption, rendered from that sorted
  action list.

Two recording types exist, and :func:`detect_capture` picks one before
the walk:

- A **DOM recording** comes from the Mixpanel JavaScript SDK. Its Meta
  events carry ``href``, and a full snapshot holds the real page DOM.
- A **screenshot recording** comes from the iOS, Android, React Native,
  and Flutter SDKs. The DOM is one screenshot image, and the Meta events
  carry no ``href``. When wireframes are on, the SDK also sends each
  screen as an ``mp_wireframe`` Custom event (a flat element list with
  role, label, and bounds). A stream that has any ``mp_wireframe`` event,
  or that has Meta events and none of them carries an ``href``, is a
  screenshot recording. A stream with no Meta event at all stays a DOM
  recording.

In a screenshot recording, touches go through a gesture state machine
(finger down, drag, lift-off): little finger travel is a tap, more is a
scroll. A mouse click is a one-event gesture. Wireframe screens are
sampled around each gesture only, so animation frames do not flood the
timeline. The screenshot image never names the element, so taps and
clicks report their coordinates, and a hit test against the current
wireframe screen names the element in ``target_desc``. The wireframe
rendering and the gesture rules follow the upstream analyzer's mobile
support. The recording-type decision, the click rule, the input type
guards, the structured screen data, and the hit test are local changes.

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
- ``Wireframe: {elements}`` (screenshot recordings) → ``screen`` (the
  ``target_desc`` is an approximate heading; ``metadata`` holds the
  structured elements, viewport, scale, fingerprint, and element count)
- ``Tapped at ({x}, {y})`` / ``Tapped`` (screenshot recordings) →
  ``touch_start`` (with ``metadata["interaction"]="tapped"``, the
  ``x`` / ``y`` coordinates when known, and ``hit`` / ``attribution``
  when the point hits a screen element, which ``target_desc`` then names)
- ``Clicked at ({x}, {y})`` / ``Clicked`` (screenshot recordings) →
  ``click`` (with ``metadata["interaction"]="clicked"`` and the same
  coordinate and hit fields as a tap)
- ``Scrolled`` (scroll events, and touch gestures that travel) → ``scroll``
- ``Set {desc} to {state}`` / ``Entered ... in {desc}`` / ``Modified
  {desc}`` → ``input``
- ``Selected '{text}'`` / ``Selected text`` → ``select``
- ``Console error: {msg}`` → ``console_error``
"""

from __future__ import annotations

import hashlib
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Literal, cast
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
    # Custom events; the mobile SDKs send wireframe screens as these.
    CUSTOM = 5
    PLUGIN = 6


class IncrementalSource(IntEnum):
    """RRWeb IncrementalSnapshot.data.source discriminators we handle."""

    MUTATION = 0
    MOUSE_INTERACTION = 2
    SCROLL = 3
    INPUT = 5
    # Finger-drag samples during a touch gesture (a ``positions`` list); the
    # travel across them separates a scroll from a tap.
    TOUCH_MOVE = 6
    SELECTION = 14


class MouseInteractionType(IntEnum):
    """MouseInteraction.data.type values we emit actions for."""

    CLICK = 2
    CONTEXT_MENU = 3
    DBL_CLICK = 4
    FOCUS = 5
    TOUCH_START = 7
    TOUCH_END = 9
    TOUCH_CANCEL = 10


class NodeType(IntEnum):
    """rrweb DOM node types."""

    ELEMENT = 2
    TEXT = 3


# =============================================================================
# Recording-type detection
# =============================================================================


CaptureKind = Literal["dom", "screenshot"]
"""The two recording types the analyzer knows.

``"dom"`` is a recording of a real page DOM (the Mixpanel JavaScript SDK).
``"screenshot"`` is a recording whose DOM is one screenshot image per
screen (the iOS, Android, React Native, and Flutter SDKs).
"""

WIREFRAME_TAG = "mp_wireframe"
"""The Custom event (type 5) tag that the mobile SDKs use for screens."""

WIREFRAME_SCREEN_PREFIX = "Wireframe: "
"""The description prefix of every rendered wireframe screen."""


def detect_capture(events: Sequence[Any]) -> CaptureKind:
    """Decide the recording type of an rrweb stream before the walk.

    The stream is a screenshot recording when any Custom event carries the
    ``mp_wireframe`` tag, or when the stream has Meta events and none of
    them carries a non-empty ``href``. The mobile SDKs and Flutter (on
    mobile, web, and desktop) send no ``href``; the Mixpanel JavaScript SDK
    always sends one. A stream with no Meta event at all stays a DOM
    recording, so partial web streams keep the web behavior.

    The decision covers the whole stream. A touch that arrives before the
    first wireframe still goes through the gesture rules. The upstream
    analyzer decides per event (after the first wireframe only), which
    misreads early iOS touches.

    Args:
        events: Raw rrweb event dicts, in any order. Entries that are not
            dicts are skipped.

    Returns:
        ``"screenshot"`` or ``"dom"``.

    Example:
        ```python
        detect_capture([{"type": 4, "timestamp": 1, "data": {"width": 411}}])
        # "screenshot"
        detect_capture([{"type": 4, "timestamp": 1, "data": {"href": "/"}}])
        # "dom"
        ```
    """
    saw_meta = False
    saw_href = False
    for event in events:
        if not isinstance(event, dict):
            continue
        raw_data = event.get("data")
        data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
        event_type = event.get("type")
        if event_type == EventType.CUSTOM and data.get("tag") == WIREFRAME_TAG:
            return "screenshot"
        if event_type == EventType.META:
            saw_meta = True
            if data.get("href"):
                saw_href = True
    return "screenshot" if saw_meta and not saw_href else "dom"


def _finite_number(value: Any) -> float | None:
    """Return ``value`` as a finite float, or None when it is not a usable number.

    A bool is not a number here (``True`` is an ``int`` in Python). Strings,
    NaN, infinities, and integers too large for a float are rejected, so
    no later ``int()`` or arithmetic call can raise.

    Args:
        value: A raw JSON value from an rrweb event.

    Returns:
        The float value, or None.

    Example:
        ```python
        _finite_number(3)             # 3.0
        _finite_number(True)          # None (a bool is not a number here)
        _finite_number("3")           # None
        _finite_number(float("nan"))  # None
        _finite_number(10**400)       # None (too large for a float)
        ```
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if math.isfinite(number) else None


def _node_id(value: Any) -> int | None:
    """Return an rrweb node id as an int, or None when it is not usable.

    A bool is not an id. An integral float (``28.0``) becomes ``28``.

    Args:
        value: The raw ``id`` value of an event.

    Returns:
        The integer node id, or None.

    Example:
        ```python
        _node_id(28)    # 28
        _node_id(28.0)  # 28
        _node_id(True)  # None
        _node_id(28.5)  # None
        ```
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value) and value.is_integer():
        return int(value)
    return None


def _point(x: Any, y: Any) -> tuple[int, int] | None:
    """Return integer ``(x, y)`` coordinates, or None when either is unusable.

    Floats truncate toward zero, as ``int()`` does in the upstream analyzer.

    Args:
        x: The raw x value.
        y: The raw y value.

    Returns:
        The ``(x, y)`` integer pair, or None.
    """
    fx = _finite_number(x)
    fy = _finite_number(y)
    if fx is None or fy is None:
        return None
    return int(fx), int(fy)


def _coords(x: Any, y: Any) -> tuple[float, float] | None:
    """Return float ``(x, y)`` coordinates for travel math, or None.

    Args:
        x: The raw x value.
        y: The raw y value.

    Returns:
        The ``(x, y)`` float pair, or None when either value is unusable.

    Example:
        ```python
        _coords(1, 2.5)   # (1.0, 2.5)
        _coords(1, None)  # None
        ```
    """
    fx = _finite_number(x)
    fy = _finite_number(y)
    if fx is None or fy is None:
        return None
    return fx, fy


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


def _selector_attrs(sanitized_attrs: dict[str, Any]) -> dict[str, str]:
    """Pick the stable ``data-*`` selector attributes from a node's attrs.

    These are the test-id-style hooks (``data-testid``, ``data-cy``,
    ``data-qa``, …) that :func:`mixpanel_headless.selector_label_fn` reads off
    ``UserAction.metadata``. Capturing every ``data-*`` attribute keeps the
    public helper working for whatever convention a project actually uses,
    rather than a hard-coded allowlist.

    Args:
        sanitized_attrs: A node's already-sanitized ``{attr: value}`` map.

    Returns:
        The subset whose keys start with ``data-`` and whose values are
        non-empty strings. Empty when the node carries no such attribute.
    """
    return {
        k: v
        for k, v in sanitized_attrs.items()
        if k.startswith("data-") and isinstance(v, str) and v
    }


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
            if node_id is None:
                continue

            if node_id not in self.nodes and len(self.nodes) >= self.MAX_NODES:
                # Skip every new node once at the cap — and stop descending into
                # its subtree (we `continue` before enqueuing children). The
                # reached_max_nodes flag only de-dupes the log; it must NOT gate
                # the skip itself, or only the first over-limit node is dropped
                # and the map grows past MAX_NODES unbounded.
                #
                # Expected on large real sessions (complex SPA full-snapshots
                # routinely exceed MAX_NODES); the analyzer degrades gracefully.
                # DEBUG, not WARNING — this matches the upstream analyzer's
                # intent and isn't actionable for callers.
                if not self.reached_max_nodes:
                    log.debug(
                        "DOMTracker reached maximum node limit; skipping new nodes"
                    )
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

                selector_attrs = _selector_attrs(sanitized_attrs)
                if selector_attrs:
                    self.nodes[node_id]["selectors"] = selector_attrs

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
            selector_attrs = _selector_attrs(sanitized_attrs)
            if selector_attrs:
                self.nodes[node_id].setdefault("selectors", {}).update(selector_attrs)
            self._description_cache.pop(node_id, None)

    def get_node_selectors(self, node_id: int) -> dict[str, str]:
        """Return the node's captured ``data-*`` selector attributes.

        These are the stable identifiers (``data-testid``, ``data-cy``, …)
        that :func:`mixpanel_headless.selector_label_fn` consults on
        ``UserAction.metadata``. Empty when the node was never recorded or
        carried no ``data-*`` attribute.

        Args:
            node_id: The rrweb node id.

        Returns:
            A ``{attr: value}`` dict of the node's ``data-*`` attributes (a
            fresh copy; safe for the caller to merge into action metadata).
        """
        node = self.nodes.get(node_id)
        if not node:
            return {}
        selectors = node.get("selectors")
        if not selectors:
            return {}
        return {str(k): str(v) for k, v in selectors.items()}

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
# Structured screen data and the tap hit test
# =============================================================================


_SCREEN_TARGET = "(screen)"
"""Fallback ``target_desc`` for a screen with no usable heading."""

_MAX_ELEMENT_TEXT = 50
"""Cap for one element label, before the ellipsis."""

SCALE_TOLERANCE = 0.05
"""Width ratios within this distance of 1.0 are not a coordinate scale.

Small differences come from rounding (a 412-wide Meta against a 411-wide
viewport) or from system bars, not from a change of pixel unit.
"""

HIT_SLOP_PX = 8.0
"""Distance (touch-space px) within which a near miss still hits an element."""

FINGERPRINT_LENGTH = 12
"""Hex characters in a screen fingerprint."""


def _bounds_ints(bounds: Any) -> list[int] | None:
    """Return an element's ``[x, y, w, h]`` rect as integers, or None.

    A missing, malformed, or all-zero rect carries no geometry. Only
    finite numbers count; a bool or a string makes the rect malformed.
    Floats truncate toward zero.

    Args:
        bounds: The raw ``bounds`` value of one element.

    Returns:
        The four integers, or None when the rect is omitted.
    """
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        return None
    values: list[int] = []
    for value in bounds:
        number = _finite_number(value)
        if number is None:
            return None
        values.append(int(number))
    if not any(values):
        return None
    return values


def _clean_role(raw_role: Any) -> str:
    """Return a stripped element role, or ``"element"`` when unusable.

    Args:
        raw_role: The raw ``role`` value.

    Returns:
        The role string.
    """
    role = raw_role.strip() if isinstance(raw_role, str) else ""
    return role or "element"


def _clean_label(raw_text: Any) -> str:
    """Return a stripped element label, cut at the label cap with an ellipsis.

    Args:
        raw_text: The raw ``text`` value.

    Returns:
        The label, or ``""`` when the value is not a non-blank string.
    """
    text = raw_text.strip() if isinstance(raw_text, str) else ""
    if len(text) > _MAX_ELEMENT_TEXT:
        text = text[:_MAX_ELEMENT_TEXT] + "…"
    return text


def _positive_number(value: Any) -> float | None:
    """Return ``value`` as a positive finite float, or None.

    Args:
        value: A raw JSON value.

    Returns:
        The float, or None when the value is not a positive finite number.
    """
    number = _finite_number(value)
    return number if number is not None and number > 0 else None


@dataclass(frozen=True)
class ScreenStructure:
    """The structured form of one wireframe screen.

    Attributes:
        elements: One dict per element, in client order, with the keys
            ``role``, ``text`` (None when empty), ``bounds`` (``[x, y, w,
            h]`` integers in the touch coordinate space, or None),
            ``offscreen`` (True when the rect lies fully outside the screen
            width), and ``background`` (True when the rect crosses both side
            edges of the screen, as a bar's blur layer does).
        viewport: The payload ``viewport`` as integer ``[w, h]``, or None.
        scale: The factor applied to convert the bounds into the touch
            space; ``1.0`` when the spaces match.
    """

    elements: list[dict[str, Any]]
    viewport: list[int] | None
    scale: float


def screen_structure(payload: Any, meta_width: float | None) -> ScreenStructure:
    """Build the structured form of a wireframe payload.

    The touch coordinates follow the Meta event ``width``. Some SDK builds
    send the wireframe bounds in physical pixels instead; the payload
    ``viewport`` then differs from the Meta width. When the ratio
    ``meta_width / viewport[0]`` differs from 1.0 by more than
    :data:`SCALE_TOLERANCE`, every rect is multiplied by it (and rounded).
    No scale applies when the truncated viewport width is not positive, or
    when the ratio or any scaled value is not finite; the bounds then stay
    raw and ``scale`` is ``1.0``.

    An element whose rect lies fully outside ``[0, screen width]`` is
    flagged ``offscreen``. An element whose rect crosses both side edges
    (``x < 0`` and ``x + w > screen width``) is flagged ``background``: a
    full-width layer such as the blur behind a tab bar. The screen width is
    the Meta width, or the viewport width (when positive) without a Meta
    width; without either, neither flag is set.

    Labels follow the rendered string's rules (stripped, cut at 50
    characters) but keep ``|`` characters, which only the rendered
    separator needs to replace.

    Args:
        payload: The raw wireframe ``payload`` value. A value that is not a
            dict, or an ``elements`` value that is not a list, gives no
            elements. Elements that are not dicts are skipped.
        meta_width: The latest usable Meta ``width``, or None.

    Returns:
        The :class:`ScreenStructure`.

    Example:
        ```python
        s = screen_structure(
            {"viewport": [1080, 2400], "elements": [
                {"role": "button", "text": "Go", "bounds": [0, 1080, 540, 200]}]},
            411.0,
        )
        s.elements[0]["bounds"]
        # [0, 411, 206, 76]
        ```
    """
    raw_payload: dict[str, Any] = payload if isinstance(payload, dict) else {}
    raw_elements = raw_payload.get("elements")
    elements_in = raw_elements if isinstance(raw_elements, list) else []

    viewport: list[int] | None = None
    raw_viewport = raw_payload.get("viewport")
    if isinstance(raw_viewport, (list, tuple)) and len(raw_viewport) == 2:
        vw = _positive_number(raw_viewport[0])
        vh = _positive_number(raw_viewport[1])
        if vw is not None and vh is not None:
            viewport = [int(vw), int(vh)]

    viewport_width = viewport[0] if viewport is not None and viewport[0] > 0 else None

    scale = 1.0
    if viewport_width is not None and meta_width is not None:
        ratio = meta_width / viewport_width
        if math.isfinite(ratio) and abs(ratio - 1.0) > SCALE_TOLERANCE:
            scale = ratio

    dict_elements = [el for el in elements_in if isinstance(el, dict)]
    all_bounds = [_bounds_ints(el.get("bounds")) for el in dict_elements]
    if scale != 1.0:
        scaled = [None if b is None else [v * scale for v in b] for b in all_bounds]
        if all(math.isfinite(v) for b in scaled if b is not None for v in b):
            all_bounds = [None if b is None else [round(v) for v in b] for b in scaled]
        else:
            scale = 1.0

    screen_width: float | None = meta_width
    if screen_width is None and viewport_width is not None:
        screen_width = float(viewport_width)

    elements: list[dict[str, Any]] = []
    for el, bounds in zip(dict_elements, all_bounds, strict=True):
        offscreen = False
        background = False
        if bounds is not None and screen_width is not None:
            x, _, w, _ = bounds
            offscreen = x + w <= 0 or x >= screen_width
            background = x < 0 and x + w > screen_width
        elements.append(
            {
                "role": _clean_role(el.get("role")),
                "text": _clean_label(el.get("text")) or None,
                "bounds": bounds,
                "offscreen": offscreen,
                "background": background,
            }
        )
    return ScreenStructure(elements=elements, viewport=viewport, scale=scale)


def screen_heading(elements: Sequence[dict[str, Any]]) -> str:
    """Pick an approximate heading for a screen.

    The heading is the label of the top-most on-screen ``text`` element
    that has a label: the smallest ``y``, then the smallest ``x``. Text
    clipped above the top edge (``y < 0``, content scrolled away) is
    skipped. When no labeled ``text`` element has bounds, the first one in
    client order wins. The heading is a heuristic, not a screen name: the
    SDKs send no screen name, and the heading can be a back-button label or
    scrolled content on the title row.

    Args:
        elements: The ``elements`` of a :class:`ScreenStructure`.

    Returns:
        The heading, or ``"(screen)"`` when no labeled text element exists.

    Raises:
        KeyError: An element dict lacks the ``role``, ``text``,
            ``offscreen``, or ``bounds`` key. Dicts from
            :func:`screen_structure` always have them.

    Example:
        ```python
        screen_heading([
            {"role": "text", "text": "Title", "bounds": [16, 38, 80, 20],
             "offscreen": False, "background": False},
            {"role": "text", "text": "Body", "bounds": [16, 200, 100, 20],
             "offscreen": False, "background": False},
        ])
        # "Title"
        ```
    """
    labeled = [
        e for e in elements if e["role"] == "text" and e["text"] and not e["offscreen"]
    ]
    placed = [e for e in labeled if e["bounds"] is not None]
    if placed:
        visible = [e for e in placed if e["bounds"][1] >= 0]
        if not visible:
            return _SCREEN_TARGET
        top = min(visible, key=lambda e: (e["bounds"][1], e["bounds"][0]))
        return str(top["text"])
    if labeled:
        return str(labeled[0]["text"])
    return _SCREEN_TARGET


def _rect_distance(bounds: list[int], x: float, y: float) -> float:
    """Return the distance from a point to a rect; 0.0 inside or on the edge.

    Args:
        bounds: The ``[x, y, w, h]`` rect.
        x: The point x.
        y: The point y.

    Returns:
        The Euclidean distance in px.

    Raises:
        ValueError: ``bounds`` does not hold exactly four values.
    """
    bx, by, bw, bh = bounds
    dx = max(bx - x, 0.0, x - (bx + bw))
    dy = max(by - y, 0.0, y - (by + bh))
    return math.hypot(dx, dy)


def hit_test(
    elements: Sequence[dict[str, Any]], x: float, y: float
) -> tuple[dict[str, Any], str] | None:
    """Find the screen element under a touch or click point.

    Only on-screen elements with bounds are candidates; ``background``
    layers (rects that cross both side edges of the screen) are never
    candidates, because they contain every point of a bar. When rects contain
    the point (edges included), a non-text role beats a ``text`` role, and
    then the smallest area wins; the attribution is ``"bounds"``. With no
    containing rect, the nearest element within :data:`HIT_SLOP_PX` wins
    (then a non-text role, then the smallest area); the attribution is
    ``"bounds_slop"``. Rects can overlap, so the result is an inference.

    Args:
        elements: The ``elements`` of a :class:`ScreenStructure`.
        x: The point x, in the touch coordinate space.
        y: The point y, in the touch coordinate space.

    Returns:
        ``(element, attribution)``, or None when no element is near.

    Raises:
        KeyError: An element dict lacks the ``bounds``, ``offscreen``, or
            ``role`` key. Dicts from :func:`screen_structure` always have
            them.

    Example:
        ```python
        save = {"role": "button", "text": "Save", "bounds": [10, 300, 100, 40],
                "offscreen": False, "background": False}
        hit_test([save], 50, 320)    # (save, "bounds")
        hit_test([save], 50, 345)    # (save, "bounds_slop"): 5 px below the rect
        hit_test([save], 400, 400)   # None
        ```
    """
    scored: list[tuple[float, bool, int, int]] = []
    for index, e in enumerate(elements):
        bounds = e["bounds"]
        if bounds is None or e["offscreen"] or e.get("background"):
            continue
        distance = _rect_distance(bounds, x, y)
        if distance <= HIT_SLOP_PX:
            scored.append((distance, e["role"] == "text", bounds[2] * bounds[3], index))
    if not scored:
        return None
    inside = [s for s in scored if s[0] == 0.0]
    if inside:
        best = min(inside, key=lambda s: (s[1], s[2], s[3]))
        return elements[best[3]], "bounds"
    best = min(scored)
    return elements[best[3]], "bounds_slop"


def hit_target_desc(element: dict[str, Any]) -> str:
    """Describe a hit element for ``target_desc``.

    Args:
        element: An element dict of a :class:`ScreenStructure`.

    Returns:
        The bare label for a labeled ``text`` element, ``role:label`` for
        another labeled role, and ``role [x,y,w,h]`` (touch-space bounds)
        for an element without a label, such as an icon.

    Raises:
        KeyError: The element lacks the ``role``, ``text``, or ``bounds``
            key.
        TypeError: The element has no label and its ``bounds`` is None
            (:func:`hit_test` never returns such an element).

    Example:
        ```python
        hit_target_desc({"role": "button", "text": "Save", "bounds": [10, 300, 100, 40]})
        # "button:Save"
        hit_target_desc({"role": "text", "text": "Cupcake", "bounds": [72, 104, 62, 21]})
        # "Cupcake"
        hit_target_desc({"role": "image", "text": None, "bounds": [363, 27, 48, 48]})
        # "image [363,27,48,48]"
        ```
    """
    role = str(element["role"])
    text = element["text"]
    if text:
        return str(text) if role == "text" else f"{role}:{text}"
    x, y, w, h = element["bounds"]
    return f"{role} [{x},{y},{w},{h}]"


def _hit_fields(
    screen: Sequence[dict[str, Any]] | None, point: tuple[int, int]
) -> tuple[str, dict[str, Any]]:
    """Return the ``target_desc`` and metadata extras for a point.

    Args:
        screen: The elements of the screen that was current, or None.
        point: The integer ``(x, y)`` point.

    Returns:
        ``(target_desc, extras)``. With a hit, the extras hold ``hit``
        (role, text, bounds) and ``attribution``; without one, the target
        is ``"(x, y)"`` and the extras are empty.
    """
    px, py = point
    hit = hit_test(screen, px, py) if screen else None
    if hit is None:
        return f"({px}, {py})", {}
    element, attribution = hit
    return hit_target_desc(element), {
        "hit": {
            "role": element["role"],
            "text": element["text"],
            "bounds": list(element["bounds"]),
        },
        "attribution": attribution,
    }


def _fingerprint(description: str) -> str:
    """Return a short stable hash of a rendered screen description.

    Args:
        description: The ``Wireframe: …`` description.

    Returns:
        The first :data:`FINGERPRINT_LENGTH` hex characters of its SHA-1.
        Characters that UTF-8 cannot encode (a lone surrogate, which JSON
        allows) are replaced before hashing.
    """
    digest = hashlib.sha1(
        description.encode("utf-8", errors="replace"), usedforsecurity=False
    )
    return digest.hexdigest()[:FINGERPRINT_LENGTH]


MAX_EVENT_TIMESTAMP_MS = 253_402_300_799_999
"""Largest usable rrweb timestamp: 9999-12-31T23:59:59.999Z in Unix ms.

``datetime`` cannot represent a later instant, so a larger value (for
example ``1e30``) would raise wherever a replay bound becomes a date.
"""


def _event_timestamp(event: Any) -> int:
    """Return an event's timestamp as an int, or 0 when it is unusable.

    Shared by every reader of raw rrweb timestamps (the analyzer, the
    ``Replay`` projections, the CDN walker, and ``fetch_replay``), so a
    damaged event cannot raise. A usable timestamp is a finite int or float
    in the range ``0 < t <= MAX_EVENT_TIMESTAMP_MS``; it is truncated to an
    int. Anything else (a string, None, a bool, NaN, infinity, zero, a
    negative or too-large number, a missing key, or an event that is not a
    dict) gives 0; actions at timestamp 0 are dropped.

    Args:
        event: A raw rrweb event, normally a dict.

    Returns:
        The integer timestamp, or 0.

    Example:
        ```python
        _event_timestamp({"timestamp": 1716810000000.7})  # 1716810000000
        _event_timestamp({"timestamp": "abc"})            # 0
        _event_timestamp({"timestamp": 1e30})             # 0 (after year 9999)
        _event_timestamp(None)                            # 0
        ```
    """
    if not isinstance(event, dict):
        return 0
    number = _finite_number(event.get("timestamp"))
    if number is None or not 0 < number <= MAX_EVENT_TIMESTAMP_MS:
        return 0
    return int(number)


@dataclass(frozen=True)
class FingerDown:
    """One finger-down (or screenshot click) in a screenshot recording.

    Attributes:
        timestamp: Unix ms timestamp of the event.
        x: The integer x coordinate.
        y: The integer y coordinate.
        target_desc: The hit-test target against the screen that was
            current at the event, or ``"(x, y)"`` without a hit.
    """

    timestamp: int
    x: int
    y: int
    target_desc: str


def finger_downs(events: Sequence[Any]) -> list[FingerDown]:
    """List every finger-down of a screenshot recording, in timestamp order.

    A finger-down is a TOUCH_START, or a mouse CLICK (Flutter web and
    desktop send clicks). These are counted directly from the raw events,
    because the analyzer classifies a gesture at lift-off: overlapping
    fingers and drifting lift-off points turn many finger-downs into
    scrolls or into no action. Events without usable coordinates or with a
    timestamp of zero or less are skipped. A DOM recording gives an empty
    list.

    Args:
        events: Raw rrweb event dicts, in any order.

    Returns:
        The :class:`FingerDown` records, sorted by timestamp.

    Example:
        ```python
        events = [
            {"type": 4, "timestamp": 1, "data": {"width": 400}},
            {"type": 5, "timestamp": 1000, "data": {"tag": "mp_wireframe", "payload": {
                "elements": [{"role": "button", "text": "Add", "bounds": [50, 80, 100, 40]}]}}},
            {"type": 3, "timestamp": 2000,
             "data": {"source": 2, "type": 7, "id": 28, "x": 100, "y": 100}},
            {"type": 3, "timestamp": 2100,
             "data": {"source": 2, "type": 2, "id": 28, "x": 5, "y": 5}},
        ]
        finger_downs(events)
        # [FingerDown(timestamp=2000, x=100, y=100, target_desc='button:Add'),
        #  FingerDown(timestamp=2100, x=5, y=5, target_desc='(5, 5)')]
        ```
    """
    if detect_capture(events) != "screenshot":
        return []
    dict_events = [e for e in events if isinstance(e, dict)]
    meta_width: float | None = None
    screen: list[dict[str, Any]] | None = None
    downs: list[FingerDown] = []
    for event in sorted(dict_events, key=_event_timestamp):
        raw_data = event.get("data")
        data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
        timestamp = _event_timestamp(event)
        event_type = event.get("type")
        if event_type == EventType.META:
            width = _positive_number(data.get("width"))
            if width is not None:
                meta_width = width
        elif (
            event_type == EventType.CUSTOM
            and data.get("tag") == WIREFRAME_TAG
            and timestamp > 0
        ):
            screen = screen_structure(data.get("payload"), meta_width).elements
        elif (
            event_type == EventType.INCREMENTAL_SNAPSHOT
            and data.get("source") == IncrementalSource.MOUSE_INTERACTION
            and data.get("type")
            in (MouseInteractionType.TOUCH_START, MouseInteractionType.CLICK)
            and timestamp > 0
        ):
            point = _point(data.get("x"), data.get("y"))
            if point is None:
                continue
            target_desc, _ = _hit_fields(screen, point)
            downs.append(
                FingerDown(
                    timestamp=timestamp, x=point[0], y=point[1], target_desc=target_desc
                )
            )
    return downs


# =============================================================================
# MobileWireframeTracker — gesture-gated sampler for wireframe screens
# =============================================================================


class MobileWireframeTracker:
    """Gesture-gated sampler for wireframe screens (rrweb Custom events).

    Screenshot recordings have no DOM. When wireframes are on, the SDK
    sends the screen as an ``mp_wireframe`` Custom event (a flat element
    list) on every visual change. Emitting all of them floods the
    timeline, because anything that animates sends a stream of screens.
    So a gesture is the activity gate:

    - At gesture start, the tracker emits the screen the user rested on
      (the "before" screen), through :meth:`on_gesture_start`.
    - At gesture end (a tap, a scroll, a cancel, or a screenshot click),
      it arms capture of the next :attr:`MAX_AFTER_FRAMES` screens (the
      "after" screens), through :meth:`on_gesture_end`.
    - A session with no gesture keeps its first screen, and every session
      keeps its last buffered screen (:meth:`finalize`).

    Consecutive identical screens collapse, so a gesture that changes
    nothing costs nothing. The rendering and the sampling follow the
    upstream analyzer; the input type guards and the timestamp guard are
    local changes.
    """

    WIREFRAME_TAG = WIREFRAME_TAG
    MAX_ELEMENT_TEXT = _MAX_ELEMENT_TEXT
    MAX_AFTER_FRAMES = 2  # screens to keep after each gesture
    MAX_WIREFRAMES = 1000  # cap on emitted screens per session
    # Separator between rendered elements. Labels carry no quotes, so a
    # ``|`` inside a label becomes ``/`` before the join.
    ELEMENT_SEPARATOR = " | "

    def __init__(self) -> None:
        """Initialize an empty tracker with no buffered screen."""
        self.actions: list[UserAction] = []
        self._pending: UserAction | None = None
        self._first: UserAction | None = None
        self._after_frames_remaining = 0
        self._last_desc: str | None = None
        self._cap_logged = False

    @property
    def current_elements(self) -> list[dict[str, Any]] | None:
        """The structured elements of the latest screen, or None before any.

        This is the screen the user sees now, whether or not the sampler
        emitted it. The hit test for a tap uses it.

        Returns:
            The ``elements`` list of the latest buffered screen (see
            :func:`screen_structure`), or None when no wireframe arrived yet.
        """
        if self._pending is None:
            return None
        elements: list[dict[str, Any]] = self._pending.metadata["elements"]
        return elements

    def process_wireframe(
        self,
        timestamp: int,
        data: dict[str, Any],
        url: str | None,
        meta_width: float | None = None,
    ) -> None:
        """Buffer one Custom event; emit it at once when it is an "after" screen.

        Custom events with another tag are ignored. A wireframe with a
        timestamp of zero or less is skipped, because ``UserAction``
        rejects such a timestamp and one bad event must not fail the whole
        analysis. A payload or an ``elements`` value of the wrong type
        gives an empty screen.

        The screen action carries the approximate heading
        (:func:`screen_heading`) as ``target_desc`` and the structured data
        in ``metadata``: ``elements`` and ``scale`` (see
        :func:`screen_structure`), ``viewport`` when the payload has a
        valid one, ``fingerprint`` (a short hash of the description), and
        ``element_count``. The description keeps the raw bounds.

        Args:
            timestamp: Unix ms timestamp of the event.
            data: The event ``data`` dict.
            url: The current page URL, if a Meta event set one.
            meta_width: The latest usable Meta ``width``, or None.
        """
        if data.get("tag") != self.WIREFRAME_TAG or timestamp <= 0:
            return
        payload = data.get("payload")
        elements = payload.get("elements") if isinstance(payload, dict) else None
        description = (
            f"{WIREFRAME_SCREEN_PREFIX}"
            f"{self._render_elements(elements if isinstance(elements, list) else [])}"
        )
        structure = screen_structure(payload, meta_width)
        metadata: dict[str, Any] = {
            "elements": structure.elements,
            "scale": structure.scale,
            "fingerprint": _fingerprint(description),
            "element_count": len(structure.elements),
        }
        if structure.viewport is not None:
            metadata["viewport"] = structure.viewport
        action = UserAction(
            timestamp=timestamp,
            action="screen",
            target_node_id=None,
            target_desc=screen_heading(structure.elements),
            url=url,
            metadata=metadata,
            description=description,
        )
        if self._first is None:
            self._first = action
        # Right after a gesture, the next new screens are its result.
        if self._after_frames_remaining > 0 and self._emit(action):
            self._after_frames_remaining -= 1
        self._pending = action

    def on_gesture_start(self) -> None:
        """Emit the resting screen as the "before" screen of a new gesture.

        The screen a scroll settles on is captured as that scroll's result
        and again as the "before" of the next gesture. The consecutive
        duplicate collapses, so the overlap costs nothing.
        """
        if self._pending is not None:
            self._emit(self._pending)

    def on_gesture_end(self) -> None:
        """Arm capture of the next screens a finished gesture produces.

        A tap navigates or opens something, and a scroll reveals new
        content, so both arm the "after" screens. This gates the screen
        sampling only; the analyzer reports the gesture action itself.
        """
        self._after_frames_remaining = self.MAX_AFTER_FRAMES

    def finalize(self) -> None:
        """Flush the buffered screens after the last event.

        A session with no gesture emits its first screen as a keyframe.
        Every session also emits its last buffered screen, so the final
        state survives. The duplicate check drops a screen that is
        already the last one emitted.
        """
        if not self.actions and self._first is not None:
            self._emit(self._first)
        if self._pending is not None:
            self._emit(self._pending)

    def _emit(self, action: UserAction) -> bool:
        """Record a screen, collapse a consecutive duplicate, and apply the cap.

        Args:
            action: The screen action to record.

        Returns:
            True when the screen was recorded; False when it duplicates the
            last recorded screen or the cap is reached.
        """
        if action.description == self._last_desc:
            return False
        if len(self.actions) >= self.MAX_WIREFRAMES:
            if not self._cap_logged:
                log.debug(
                    "Wireframe cap (%d) reached; dropping further screens",
                    self.MAX_WIREFRAMES,
                )
                self._cap_logged = True
            return False
        self.actions.append(action)
        self._last_desc = action.description
        return True

    @staticmethod
    def _format_bounds(bounds: Any) -> str:
        """Render an element's ``[x, y, w, h]`` rect, or ``""``.

        The rect lets a reader reason about layout and check whether a
        ``Tapped at (x, y)`` point falls inside an element. A missing,
        malformed, or all-zero rect carries no geometry, so it is omitted.
        Only finite numbers count; a bool or a string makes the rect
        malformed. Floats truncate toward zero.

        Args:
            bounds: The raw ``bounds`` value of one element.

        Returns:
            ``"[x,y,w,h]"``, or ``""`` when the rect is omitted.
        """
        values = _bounds_ints(bounds)
        if values is None:
            return ""
        x, y, w, h = values
        return f"[{x},{y},{w},{h}]"

    @classmethod
    def _render_elements(cls, elements: list[Any]) -> str:
        """Render a screen's element list as one compact string.

        Each element renders as ``label [x,y,w,h]`` for role ``text``,
        ``role:label [x,y,w,h]`` for other roles, and the bare role when the
        label is empty. Elements keep the order the client sent them. An
        element that is not a dict is skipped. A role that is not a
        non-blank string renders as ``element``. A label is stripped, its
        ``|`` characters become ``/``, and it is cut at
        :attr:`MAX_ELEMENT_TEXT` characters with an ellipsis.

        Args:
            elements: The raw ``elements`` list of the payload.

        Returns:
            The elements joined with :attr:`ELEMENT_SEPARATOR`, or
            ``"(empty screen)"`` when no element renders.
        """
        parts: list[str] = []
        for el in elements:
            if not isinstance(el, dict):
                continue
            role = _clean_role(el.get("role"))
            # Replace the pipe before the cut, as the upstream analyzer does.
            raw_text = el.get("text")
            text = raw_text.strip() if isinstance(raw_text, str) else ""
            text = text.replace("|", "/")
            if len(text) > cls.MAX_ELEMENT_TEXT:
                text = text[: cls.MAX_ELEMENT_TEXT] + "…"
            if not text:
                core = role
            elif role == "text":
                core = text
            else:
                core = f"{role}:{text}"
            bounds = cls._format_bounds(el.get("bounds"))
            parts.append(f"{core} {bounds}" if bounds else core)
        return cls.ELEMENT_SEPARATOR.join(parts) if parts else "(empty screen)"


@dataclass
class _Gesture:
    """An open touch gesture: the finger is down and has not lifted.

    Attributes:
        timestamp: Unix ms timestamp of the finger-down event.
        start: The finger-down point as floats, or None without usable
            coordinates (travel is then not tracked).
        node_id: The raw rrweb node id of the finger-down event.
        x: The raw finger-down x value.
        y: The raw finger-down y value.
        screen: The structured elements of the screen that was current at
            finger-down, or None before any screen; the tap hit test uses it.
        travel: The largest distance from ``start`` seen so far, in px.
    """

    timestamp: int
    start: tuple[float, float] | None
    node_id: Any
    x: Any
    y: Any
    screen: list[dict[str, Any]] | None = None
    travel: float = 0.0


# =============================================================================
# EventAnalyzer — emits structured public UserAction records
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
    """Single-pass rrweb event walker emitting structured actions.

    Applies per-source debouncing (scroll / input / selection at 1s each)
    and plugin-event filtering for ``rrweb/console@*`` console errors.
    Emits the public :class:`mixpanel_headless.types.UserAction` so
    downstream aggregations keep their schema-stable action literals.

    The ``capture`` argument selects the recording type (see
    :func:`detect_capture`). A DOM analyzer names the DOM element of each
    interaction. A screenshot analyzer runs the touch gesture state
    machine, treats a mouse click as a one-event gesture, reports
    coordinates instead of the screenshot image, and samples wireframe
    screens through :class:`MobileWireframeTracker`. Call :meth:`finalize`
    after the last event: it flushes the deferred state and sorts
    :attr:`user_actions` by timestamp.
    """

    SCROLL_DEBOUNCE_MS = 1000
    SELECTION_DEBOUNCE_MS = 1000
    INPUT_DEBOUNCE_MS = 1000

    # A touch whose finger travels no more than this far (px, from the
    # finger-down point) is a tap; more is a scroll or a swipe.
    TAP_MAX_TRAVEL_PX = 10.0

    def __init__(
        self,
        dom_tracker: DOMTracker | None = None,
        *,
        capture: CaptureKind = "dom",
    ) -> None:
        """Initialize the analyzer.

        Args:
            dom_tracker: Optional pre-seeded DOM tracker.
            capture: The recording type, from :func:`detect_capture`.
                Defaults to ``"dom"``.
        """
        self.dom_tracker = dom_tracker or DOMTracker()
        self.capture: CaptureKind = capture
        self.wireframe_tracker = MobileWireframeTracker()
        self.user_actions: list[UserAction] = []
        self.pages: list[PageVisit] = []
        self.errors: list[ConsoleError] = []
        self.current_url: str | None = None
        # The latest usable Meta width: the touch coordinate space.
        self.meta_width: float | None = None
        self.last_scroll_time = 0
        self.last_selection_time = 0
        self.last_input_time: dict[int, int] = {}
        # The open touch gesture (finger down, not yet up), or None.
        self._active_touch: _Gesture | None = None
        self._finalized = False

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
        """Append a structured UserAction.

        An action with a timestamp of zero or less is dropped, not raised.
        ``UserAction`` rejects such a timestamp, and one bad event must not
        fail the whole analysis. The debounce state and the current URL
        still update, as for any other event.

        Args:
            timestamp: Unix ms.
            action: One of the public ``UserAction.action`` literal values.
            description: Human-readable description text for the markdown
                line.
            target_node_id: rrweb node id, if applicable.
            target_desc: Human-readable element label (defaults to the
                description when not provided).
            url: Active page URL.
            metadata: Action-specific extras.
        """
        if timestamp <= 0:
            return
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
        """Dispatch a single rrweb event to its type-specific handler.

        An entry that is not a dict is skipped. An unusable timestamp reads
        as 0 (see :func:`_event_timestamp`), so its action is dropped.

        Args:
            event: One raw rrweb event.

        Raises:
            AttributeError: A DOM recording carries a malformed DOM payload,
                for example a mutation ``adds`` entry that is not a dict. The
                screenshot path and the timestamp handling never raise.
        """
        if not isinstance(event, dict):
            return
        event_type = event.get("type")
        timestamp = _event_timestamp(event)
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
        elif event_type == EventType.CUSTOM:
            self.wireframe_tracker.process_wireframe(
                timestamp, data, self.current_url, self.meta_width
            )

    def _process_meta(self, timestamp: int, data: dict[str, Any]) -> None:
        """Handle Meta events: record the screen width; emit a navigation.

        A positive finite ``width`` becomes the touch coordinate space for
        wireframe scaling. A non-empty ``href`` updates the current URL and
        emits a ``navigate`` action.
        """
        width = _positive_number(data.get("width"))
        if width is not None:
            self.meta_width = width
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
        elif source == IncrementalSource.TOUCH_MOVE:
            self._process_touch_move(timestamp, data)
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
        """Emit click-family / focus / touch-start actions for interactions.

        A screenshot recording routes to
        :meth:`_process_screenshot_interaction`. A DOM recording names the
        DOM element; its touch end, touch cancel, mouse down, and mouse up
        events emit nothing.
        """
        if self.capture == "screenshot":
            self._process_screenshot_interaction(timestamp, data)
            return

        interaction_type = data.get("type")
        node_id = data.get("id")

        if not isinstance(interaction_type, int):
            return
        verb = _MOUSE_INTERACTION_NAMES.get(interaction_type)
        if not verb:
            return

        node_desc = (
            self.dom_tracker.get_node_description(node_id)
            if node_id is not None
            else "unknown element"
        )
        if node_desc == "unknown element":
            return

        action_literal = _INTERACTION_TO_ACTION.get(verb, "click")
        metadata: dict[str, Any] = {"interaction": verb}
        target_node_id = _node_id(node_id)
        if target_node_id is not None:
            # Surface the element's data-* selectors so selector_label_fn can
            # group by a stable test id instead of falling through to the URL.
            metadata.update(self.dom_tracker.get_node_selectors(target_node_id))
        self._emit(
            timestamp,
            action_literal,
            f"{verb.capitalize()} {node_desc}",
            target_node_id=target_node_id,
            target_desc=node_desc,
            metadata=metadata,
        )

    def _process_screenshot_interaction(
        self, timestamp: int, data: dict[str, Any]
    ) -> None:
        """Handle a mouse or touch interaction in a screenshot recording.

        Touches go through the gesture state machine: TOUCH_START opens a
        gesture, TOUCH_END closes and classifies it, and TOUCH_CANCEL closes
        it with no action. A CLICK is a one-event gesture. Every other
        interaction (mouse down, mouse up, double-click, right-click, focus)
        is ignored: its only target is the screenshot image, which names
        nothing.

        Args:
            timestamp: Unix ms timestamp of the event.
            data: The event ``data`` dict.
        """
        interaction_type = data.get("type")
        node_id = data.get("id")
        x = data.get("x")
        y = data.get("y")
        if interaction_type == MouseInteractionType.TOUCH_START:
            self._begin_touch(timestamp, node_id, x, y)
        elif interaction_type == MouseInteractionType.TOUCH_END:
            self._end_touch(timestamp, node_id, x, y)
        elif interaction_type == MouseInteractionType.TOUCH_CANCEL:
            self._cancel_touch()
        elif interaction_type == MouseInteractionType.CLICK:
            self._screenshot_click(timestamp, node_id, x, y)

    def _screenshot_click(self, timestamp: int, node_id: Any, x: Any, y: Any) -> None:
        """Handle a mouse click in a screenshot recording as a one-event gesture.

        Flutter web and Flutter desktop send clicks instead of touches. The
        click emits the "before" screen, the ``Clicked at (x, y)`` action,
        and then arms the "after" screens, as a tap does.

        Args:
            timestamp: Unix ms timestamp of the click.
            node_id: The raw rrweb node id of the click target.
            x: The raw x coordinate.
            y: The raw y coordinate.
        """
        self.wireframe_tracker.on_gesture_start()
        self._emit_point_action(
            timestamp,
            "click",
            verb="Clicked",
            interaction="clicked",
            fallback_target="(click)",
            node_id=node_id,
            x=x,
            y=y,
            screen=self.wireframe_tracker.current_elements,
        )
        self.wireframe_tracker.on_gesture_end()

    def _emit_point_action(
        self,
        timestamp: int,
        action: str,
        *,
        verb: str,
        interaction: str,
        fallback_target: str,
        node_id: Any,
        x: Any,
        y: Any,
        screen: list[dict[str, Any]] | None,
    ) -> None:
        """Emit a tap or a click that reports its point.

        With usable coordinates the description is ``{verb} at (x, y)`` and
        the metadata carries integer ``x`` and ``y``. The point is then hit
        tested against ``screen`` (:func:`hit_test`): with a hit, the target
        names the element and the metadata adds ``hit`` and
        ``attribution``; without one, the target is ``(x, y)``. Without
        coordinates the description is the bare verb and the target is
        ``fallback_target``. The description never names the element, so
        it stays equal to the upstream analyzer's text.

        Args:
            timestamp: Unix ms timestamp of the action.
            action: The public ``UserAction.action`` literal.
            verb: The description verb (``Tapped`` or ``Clicked``).
            interaction: The ``metadata["interaction"]`` value.
            fallback_target: The ``target_desc`` without coordinates.
            node_id: The raw rrweb node id.
            x: The raw x coordinate.
            y: The raw y coordinate.
            screen: The elements of the screen that was current when the
                gesture started, or None.
        """
        metadata: dict[str, Any] = {"interaction": interaction}
        point = _point(x, y)
        if point is None:
            description = verb
            target_desc = fallback_target
        else:
            px, py = point
            description = f"{verb} at ({px}, {py})"
            metadata["x"] = px
            metadata["y"] = py
            target_desc, extras = _hit_fields(screen, point)
            metadata.update(extras)
        self._emit(
            timestamp,
            action,
            description,
            target_node_id=_node_id(node_id),
            target_desc=target_desc,
            metadata=metadata,
        )

    def _begin_touch(self, timestamp: int, node_id: Any, x: Any, y: Any) -> None:
        """Open a touch gesture and emit the resting screen as its "before".

        A gesture that is still open (its TOUCH_END was dropped) is flushed
        as a tap first: a new finger-down means the previous touch ended,
        and a tap is the safe reading when no travel was seen.

        Args:
            timestamp: Unix ms timestamp of the finger-down event.
            node_id: The raw rrweb node id.
            x: The raw x coordinate.
            y: The raw y coordinate.

        Example:
            ```python
            # A second finger-down before the first lift-off flushes the first
            # gesture as a tap at its finger-down point.
            # touch start (1, 1) at 2000, touch start (2, 2) at 3000, lift-off at 3050
            # -> "Tapped at (1, 1)", "Tapped at (2, 2)"
            ```
        """
        if self._active_touch is not None:
            self._flush_active_touch_as_tap()
        self.wireframe_tracker.on_gesture_start()
        self._active_touch = _Gesture(
            timestamp=timestamp,
            start=_coords(x, y),
            node_id=node_id,
            x=x,
            y=y,
            screen=self.wireframe_tracker.current_elements,
        )

    def _process_touch_move(self, timestamp: int, data: dict[str, Any]) -> None:
        """Add finger-drag travel to the open gesture (screenshot recordings only).

        A drag with no open gesture (the session started mid-drag) is a
        scroll. A DOM recording reports scrolling through scroll events, so
        its touch moves are ignored. Samples that are not dicts or that
        lack finite coordinates add no travel.

        Args:
            timestamp: Unix ms timestamp of the event.
            data: The event ``data`` dict (``positions`` list).
        """
        if self.capture != "screenshot":
            return
        raw_positions = data.get("positions")
        positions = raw_positions if isinstance(raw_positions, list) else []
        gesture = self._active_touch
        if gesture is None:
            if any(
                isinstance(pos, dict)
                and _coords(pos.get("x"), pos.get("y")) is not None
                for pos in positions
            ):
                self._record_scroll(timestamp)
            return
        if gesture.start is None:
            return
        sx, sy = gesture.start
        for pos in positions:
            if not isinstance(pos, dict):
                continue
            point = _coords(pos.get("x"), pos.get("y"))
            if point is None:
                continue
            gesture.travel = max(
                gesture.travel, math.hypot(point[0] - sx, point[1] - sy)
            )

    def _end_touch(self, timestamp: int, node_id: Any, x: Any, y: Any) -> None:
        """Close the open gesture and classify it as a tap or a scroll.

        Travel above :attr:`TAP_MAX_TRAVEL_PX` is a scroll; other travel is
        a tap at the lift-off point when both lift-off coordinates are
        usable numbers, and at the finger-down point otherwise. The node id
        falls back to the finger-down one when the lift-off has none. Both arm the "after" screens. A TOUCH_END with
        no open gesture is ignored.

        Args:
            timestamp: Unix ms timestamp of the lift-off event.
            node_id: The raw rrweb node id.
            x: The raw x coordinate.
            y: The raw y coordinate.

        Example:
            ```python
            # touch start (4, 5), lift-off (50, None): the lift-off point is partial,
            # so the finger-down point is used -> "Tapped at (4, 5)"
            # touch start (200, 800), drag to (200, 500), lift-off (200, 480):
            # travel 320 px > 10 px -> "Scrolled"
            ```
        """
        gesture = self._active_touch
        self._active_touch = None
        if gesture is None:
            return
        travel = gesture.travel
        end = _coords(x, y)
        if end is not None and gesture.start is not None:
            travel = max(
                travel,
                math.hypot(end[0] - gesture.start[0], end[1] - gesture.start[1]),
            )
        self.wireframe_tracker.on_gesture_end()
        if travel > self.TAP_MAX_TRAVEL_PX:
            self._record_scroll(timestamp)
            return
        # The lift-off point replaces the finger-down point only as a whole:
        # a lift-off with one unusable coordinate keeps both finger-down ones.
        tap_x, tap_y = (x, y) if end is not None else (gesture.x, gesture.y)
        self._emit_tap(
            timestamp,
            node_id if node_id is not None else gesture.node_id,
            tap_x,
            tap_y,
            gesture.screen,
        )

    def _cancel_touch(self) -> None:
        """Close the open gesture with no action (the system took the touch).

        A cancelled touch is neither a tap nor a scroll. It still arms the
        "after" screens, because a cancel often comes with a screen change.
        A cancel with no open gesture is ignored.
        """
        gesture = self._active_touch
        self._active_touch = None
        if gesture is None:
            return
        self.wireframe_tracker.on_gesture_end()

    def _emit_tap(
        self,
        timestamp: int,
        node_id: Any,
        x: Any,
        y: Any,
        screen: list[dict[str, Any]] | None,
    ) -> None:
        """Emit a confirmed tap in a screenshot recording.

        Args:
            timestamp: Unix ms timestamp of the tap.
            node_id: The raw rrweb node id.
            x: The raw x coordinate.
            y: The raw y coordinate.
            screen: The elements of the screen that was current at
                finger-down, or None; the hit test uses it.
        """
        self._emit_point_action(
            timestamp,
            "touch_start",
            verb="Tapped",
            interaction="tapped",
            fallback_target="(tap)",
            node_id=node_id,
            x=x,
            y=y,
            screen=screen,
        )

    def _flush_active_touch_as_tap(self) -> None:
        """Emit the open gesture at its finger-down time, with no lift-off.

        Used when a TOUCH_END never arrives (a dropped event, or the session
        ends mid-touch). A gesture whose drag travel already passed
        :attr:`TAP_MAX_TRAVEL_PX` is a scroll; any other gesture is a tap at
        its finger-down point. Either way the "after" screens are armed, as
        at a lift-off, so screens that arrive between overlapping touches are
        sampled. Does nothing when no gesture is open.

        Example:
            ```python
            # touch start (200, 800), drag to (200, 500), then a new touch start at
            # (10, 10) before any lift-off: the first gesture dragged 300 px, so it
            # is flushed as a scroll -> "Scrolled", then "Tapped at (10, 10)"
            ```
        """
        gesture = self._active_touch
        self._active_touch = None
        if gesture is None:
            return
        self.wireframe_tracker.on_gesture_end()
        if gesture.travel > self.TAP_MAX_TRAVEL_PX:
            self._record_scroll(gesture.timestamp)
            return
        self._emit_tap(
            gesture.timestamp, gesture.node_id, gesture.x, gesture.y, gesture.screen
        )

    def _process_scroll(self, timestamp: int, data: dict[str, Any]) -> None:
        """Emit a debounced scroll action for a scroll event."""
        _ = data
        self._record_scroll(timestamp)

    def _record_scroll(self, timestamp: int) -> None:
        """Emit a debounced scroll action (one per :data:`SCROLL_DEBOUNCE_MS`).

        Scroll events and touch gestures that travel share this debounce.

        Args:
            timestamp: Unix ms timestamp of the scroll.
        """
        if timestamp - self.last_scroll_time > self.SCROLL_DEBOUNCE_MS:
            self._emit(timestamp, "scroll", "Scrolled", target_desc="(viewport)")
        self.last_scroll_time = timestamp

    def _process_input(self, timestamp: int, data: dict[str, Any]) -> None:
        """Emit a debounced input action (per-node, :data:`INPUT_DEBOUNCE_MS`)."""
        node_id = data.get("id")
        text = data.get("text", "")
        is_checked = data.get("isChecked")

        if node_id is not None:
            last_time = self.last_input_time.get(node_id, 0)
            if timestamp - last_time <= self.INPUT_DEBOUNCE_MS:
                return
            self.last_input_time[node_id] = timestamp

        node_desc = (
            self.dom_tracker.get_node_description(node_id)
            if node_id is not None
            else "input"
        )

        if is_checked is not None:
            state = "checked" if is_checked else "unchecked"
            description = f"Set {node_desc} to {state}"
        elif text:
            description = f"Entered '{text}' in {node_desc}"
        else:
            description = f"Modified {node_desc}"

        metadata: dict[str, Any] = {
            "text_length": len(text) if isinstance(text, str) else 0,
            "is_checked": is_checked,
        }
        target_node_id = _node_id(node_id)
        if target_node_id is not None:
            metadata.update(self.dom_tracker.get_node_selectors(target_node_id))
        self._emit(
            timestamp,
            "input",
            description,
            target_node_id=target_node_id,
            target_desc=node_desc,
            metadata=metadata,
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

    def finalize(self) -> None:
        """Flush the deferred state and sort the action list by timestamp.

        A gesture still open at the end is flushed as a tap. The wireframe
        tracker flushes its buffered screens, which merge into
        :attr:`user_actions`. The stable sort then puts every action in
        timestamp order; the tracker emits screens after their arrival, so
        the merge alone is out of order. Actions with equal timestamps keep
        their emission order, with screens after the other actions. A
        second call does nothing.
        """
        if self._finalized:
            return
        self._finalized = True
        self._flush_active_touch_as_tap()
        self.wireframe_tracker.finalize()
        self.user_actions.extend(self.wireframe_tracker.actions)
        self.user_actions.sort(key=lambda a: a.timestamp)


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
        """Initialize with (timestamp_ms, description) pairs in timeline order."""
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
    mutated; events are sorted by timestamp before processing, and the
    recording type (:func:`detect_capture`) is decided one time, before
    the walk.

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
            An :class:`AnalyzerResult` with the action list (sorted by
            timestamp), the markdown timeline rendered from that list, page
            visits, and console errors populated. Empty on empty input.

        Raises:
            AttributeError: A DOM recording carries a malformed DOM payload,
                for example a mutation ``adds`` entry that is not a dict (see
                :meth:`EventAnalyzer.process_event`). Unusable timestamps,
                entries that are not dicts, and malformed wireframe or touch
                input never raise.
        """
        if not events:
            return AnalyzerResult()

        sorted_events = sorted(
            (e for e in events if isinstance(e, dict)), key=_event_timestamp
        )

        dom_tracker = DOMTracker()
        event_analyzer = EventAnalyzer(
            dom_tracker, capture=detect_capture(sorted_events)
        )
        for event in sorted_events:
            event_analyzer.process_event(event)
        event_analyzer.finalize()

        actions = event_analyzer.user_actions
        markdown = MarkdownReporter(
            [(a.timestamp, a.description) for a in actions]
        ).generate()
        log.info("Generated %d user actions", len(actions))
        return AnalyzerResult(
            actions=actions,
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


def actions_contain_wireframes(actions: Sequence[UserAction]) -> bool:
    """Whether a structured action list holds wireframe screens.

    It reads the ``"screen"`` action label, not the rendered line format,
    so a description that only looks like a screen does not count.

    Args:
        actions: Structured actions, as in :attr:`AnalyzerResult.actions`.

    Returns:
        True when at least one action is a ``"screen"`` action.
    """
    return any(a.action == "screen" for a in actions)


# Used by Replay.summary_markdown to render a timeline from the structured
# action list. Each UserAction carries a full ``description`` (e.g.
# 'Clicked button "Sign in"'); ``target_desc`` is the fallback for actions
# built without the analyzer (hand-constructed fixtures).
def _render_markdown(actions: list[UserAction]) -> str:
    """Render a markdown timeline from a structured action list.

    Renders each action's full ``description`` (falling back to
    ``target_desc`` when empty) and collapses consecutive duplicates via
    :func:`_collapse_timeline`, matching the analyzer's ``markdown_summary``.

    Args:
        actions: Structured action list (may be empty).

    Returns:
        Multi-line markdown string. Empty when ``actions`` is empty.
    """
    if not actions:
        return ""
    return _collapse_timeline(
        [(a.timestamp, a.description or a.target_desc) for a in actions]
    )
