"""Invocable-shape adapters for registry entries (design D4.2 items 5 and 9).

Some recorded contracts have no directly-registrable callable of the
right shape, so the registry targets these thin adapters instead:

- ``replay_labels.selector_label_fn`` is a FACTORY returning a closure; the
  design records it as ``(attr, action) -> label`` ("the CLOSURE result is
  invoked, factory value is not a vector" — D4.2 item 5).
  :func:`selector_label_fn` flattens factory + closure into one call.
- ``api_client._iter_jsonl_lines`` consumes a live streaming
  ``httpx.Response``; its chunk-boundary contract enters the corpus via
  hand-authored chunk vectors (design D2/D4.2 item 9).
  :func:`iter_jsonl_lines` rebuilds a stream-backed response from raw
  chunks (preserving boundaries) and returns the reassembled lines.
- ``RrwebAnalyzer.analyze`` is a method on a stateless class; the design
  D3.1 item-3 rrweb seed golden freezes its output over
  ``tests/fixtures/rrweb/sample-replay-001.json``. :func:`analyze_rrweb`
  flattens construction + call into one registrable function.
- ``Replay.capture``, ``Replay.has_wireframes``, ``Replay.screen_path``,
  and ``ReplayBundle.rage_taps`` are members of result objects that
  :meth:`Workspace.fetch_replay` builds from a raw event stream.
  :func:`replay_capture`, :func:`replay_has_wireframes`,
  :func:`replay_screen_path`, and :func:`replay_bundle_rage_taps` take the
  raw events, build the object the same way (the analyzer fills
  ``actions``), and return the member's value. ``rage_taps`` returns a
  DataFrame, so its adapter returns the rows as a list of dicts.
- ``bookmark_schema.validate_with_pydantic`` takes a pydantic model
  CLASS — not JSON-transportable. :func:`validate_with_pydantic`
  resolves a model NAME over a fixed five-entry map and forwards with
  the DEFAULT code mapper (b3-packets.md §"validate_with_pydantic —
  adapter retarget"; the ``_sorting_code_mapper`` path is fuzz-covered
  through ``validation.validate_sorting_block``, bound at B2).

All adapters delegate to the real library code — they add shape, never
behavior.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import httpx

from mixpanel_headless._internal.replays.rrweb_analyzer import AnalyzerResult
from mixpanel_headless.types import UserAction

if TYPE_CHECKING:
    from mixpanel_headless.exceptions import ValidationError
    from mixpanel_headless.types import Replay


class _ChunkStream(httpx.SyncByteStream):
    """One-shot byte stream yielding explicit chunks (boundary-preserving)."""

    def __init__(self, chunks: list[bytes]) -> None:
        """Store the chunk list to yield.

        Args:
            chunks: Body chunks in yield order — boundaries are the
                contract under test (design D2).
        """
        self._chunks = chunks

    def __iter__(self) -> Iterator[bytes]:
        """Yield each configured chunk exactly once.

        Returns:
            Iterator over the configured chunks, unchanged.
        """
        return iter(self._chunks)


def selector_label_fn(attr: str, action: UserAction) -> str:
    """Flattened ``replay_labels.selector_label_fn`` (design D4.2 item 5).

    Builds the closure for ``attr`` and immediately applies it to
    ``action`` so the recordable contract is ``(attr, action) -> label``.

    Args:
        attr: The HTML attribute the label function prefers
            (e.g. ``"data-testid"``).
        action: The replay user action to label.

    Returns:
        The label the closure produces for ``action``.

    Example:
        ```python
        label = selector_label_fn("data-testid", action)
        # 'Clicked [data-testid="submit-button"]'
        ```
    """
    from mixpanel_headless import replay_labels

    return replay_labels.selector_label_fn(attr)(action)


def iter_jsonl_lines(
    chunks: list[bytes], headers: dict[str, str] | None = None
) -> list[str]:
    """Run ``_iter_jsonl_lines`` over explicit chunks (design D4.2 item 9).

    Rebuilds a stream-backed ``httpx.Response`` whose byte stream yields
    ``chunks`` verbatim (so lines split across chunk boundaries — and gzip
    bodies when ``headers`` says ``content-encoding: gzip`` — exercise the
    real buffering logic), then collects the reassembled lines.

    Args:
        chunks: Raw body chunks in arrival order (``$type: bytes`` tagged
            in vector inputs).
        headers: Response headers; drive httpx's decoding
            (``content-encoding``) exactly as a live response would.

    Returns:
        The complete JSONL lines the library yields, in order.

    Raises:
        httpx.DecodingError: If ``headers`` promises an encoding the chunk
            bytes do not satisfy.

    Example:
        ```python
        lines = iter_jsonl_lines([b'{"a": 1}\\n{"b"', b': 2}\\n'])
        # ['{"a": 1}', '{"b": 2}']
        ```
    """
    from mixpanel_headless._internal.api_client import _iter_jsonl_lines

    response = httpx.Response(200, headers=headers, stream=_ChunkStream(list(chunks)))
    return list(_iter_jsonl_lines(response))


def analyze_rrweb(events: list[dict[str, Any]]) -> AnalyzerResult:
    """Run the rrweb analyzer over a raw event stream (design D3.1 item 3).

    Flattens ``RrwebAnalyzer().analyze(events)`` into one registrable
    callable so the rrweb seed-golden vectors (PR-7) can freeze the
    analyzer's Python output — the plan's Layer-3 rrweb golden-file
    mandate, exercised early via the corpus.

    Args:
        events: Raw rrweb event dicts (the fixture body; order-insensitive
            — the analyzer sorts by timestamp).

    Returns:
        The ``AnalyzerResult`` dataclass (actions, markdown_summary,
        pages, errors) — encoded to its plain to-dict shape in expect
        position by the generic codec.

    Example:
        ```python
        result = analyze_rrweb([{"type": 4, "data": {"href": "/"}, "timestamp": 0}])
        # AnalyzerResult(actions=[...], markdown_summary="...", ...)
        ```
    """
    from mixpanel_headless._internal.replays.rrweb_analyzer import RrwebAnalyzer

    return RrwebAnalyzer().analyze(events)


def _replay_from_events(events: list[dict[str, Any]]) -> Replay:
    """Build a ``Replay`` from raw events, as ``Workspace.fetch_replay`` does.

    The analyzer runs over ``events`` and fills ``actions``. The identity
    and time fields are fixed placeholders, because no adapted member
    reads them except ``replay_id``, which ``rage_taps`` copies into each
    row.

    Args:
        events: Raw rrweb event dicts.

    Returns:
        The replay, with ``replay_id="r1"``.
    """
    from mixpanel_headless._internal.replays.rrweb_analyzer import RrwebAnalyzer
    from mixpanel_headless.types import Replay

    return Replay(
        replay_id="r1",
        distinct_id=None,
        project_id=1,
        start_time=1,
        end_time=1,
        retention_days=30,
        rrweb_events=events,
        actions=list(RrwebAnalyzer().analyze(events).actions),
    )


def replay_capture(events: list[dict[str, Any]]) -> str:
    """Return ``Replay.capture`` for a raw event stream.

    Args:
        events: Raw rrweb event dicts.

    Returns:
        ``"dom"`` or ``"screenshot"``.

    Example:
        ```python
        replay_capture([{"type": 4, "data": {"href": ""}, "timestamp": 1}])
        # 'screenshot'
        ```
    """
    return _replay_from_events(events).capture


def replay_has_wireframes(events: list[dict[str, Any]]) -> bool:
    """Return ``Replay.has_wireframes`` for a raw event stream.

    Args:
        events: Raw rrweb event dicts.

    Returns:
        True when the analyzer emits at least one ``"screen"`` action.
    """
    return _replay_from_events(events).has_wireframes


def replay_screen_path(events: list[dict[str, Any]]) -> list[str]:
    """Return ``Replay.screen_path()`` for a raw event stream.

    Args:
        events: Raw rrweb event dicts.

    Returns:
        The screen headings in timestamp order.
    """
    return _replay_from_events(events).screen_path()


def replay_bundle_rage_taps(
    events: list[dict[str, Any]],
    threshold: int = 3,
    window_ms: int = 2000,
    radius_px: float = 24,
    grace_ms: int = 1000,
) -> list[dict[str, Any]]:
    """Return ``ReplayBundle.rage_taps()`` rows for a one-replay bundle.

    The DataFrame is not a vector value, so the rows come back as plain
    dicts with the DataFrame's column names as keys, in row order.

    Args:
        events: Raw rrweb event dicts of the only replay in the bundle.
        threshold: Forwarded to ``rage_taps``.
        window_ms: Forwarded to ``rage_taps``.
        radius_px: Forwarded to ``rage_taps``.
        grace_ms: Forwarded to ``rage_taps``.

    Returns:
        One dict per reported burst: ``replay_id``, ``t_start``, ``t_end``,
        ``target_desc``, ``x``, ``y``, ``count``, and ``kind``.

    Example:
        ```python
        replay_bundle_rage_taps(events)
        # [{'replay_id': 'r1', 'count': 4, 'kind': 'dead', ...}]
        ```
    """
    from mixpanel_headless.types import ReplayBundle

    bundle = ReplayBundle(
        replays=[_replay_from_events(events)], computed_at="", project_id=1
    )
    frame = bundle.rage_taps(
        threshold=threshold,
        window_ms=window_ms,
        radius_px=radius_px,
        grace_ms=grace_ms,
    )
    rows: list[dict[str, Any]] = [
        {
            "replay_id": str(row["replay_id"]),
            "t_start": int(row["t_start"]),
            "t_end": int(row["t_end"]),
            "target_desc": str(row["target_desc"]),
            "x": int(row["x"]),
            "y": int(row["y"]),
            "count": int(row["count"]),
            "kind": str(row["kind"]),
        }
        for row in frame.to_dict(orient="records")
    ]
    return rows


def validate_with_pydantic(
    model: str, value: Any, path_prefix: str = ""
) -> list[ValidationError]:
    """Name-resolving ``bookmark_schema.validate_with_pydantic`` shim (B3 b′).

    The real function takes a pydantic model CLASS, which is not
    JSON-transportable; this adapter accepts the model NAME, resolves it
    over a fixed five-entry map, and forwards with the DEFAULT code
    mapper (b3-packets.md §"validate_with_pydantic — adapter retarget").
    The TS mirror is ``BOOKMARK_MODEL_HANDLES`` in
    ``packages/core/src/bookmarks/schema.ts`` — five entries, same
    spellings.

    Args:
        model: One of ``InsightsBookmarkSortConfig`` /
            ``InsightsBookmarkParams`` / ``FlowsBookmarkParams`` /
            ``Sections`` / ``DisplayOptions``.
        value: The raw value to validate.
        path_prefix: Optional JSONPath prefix forwarded verbatim.

    Returns:
        The ``ValidationError`` list the real function produces.

    Raises:
        ValueError: If ``model`` is not one of the five mapped names (a
            harness bug — the fuzz strategies draw mapped names only).

    Example:
        ```python
        errors = validate_with_pydantic("DisplayOptions", {"chartType": "nope"})
        # [ValidationError(code="B0_INVALID_LITERAL", ...)]
        ```
    """
    from mixpanel_headless._internal import bookmark_schema

    models: dict[str, Any] = {
        "InsightsBookmarkSortConfig": bookmark_schema.InsightsBookmarkSortConfig,
        "InsightsBookmarkParams": bookmark_schema.InsightsBookmarkParams,
        "FlowsBookmarkParams": bookmark_schema.FlowsBookmarkParams,
        "Sections": bookmark_schema.Sections,
        "DisplayOptions": bookmark_schema.DisplayOptions,
    }
    if model not in models:
        raise ValueError(f"unknown bookmark_schema model {model!r}")
    return bookmark_schema.validate_with_pydantic(
        models[model], value, path_prefix=path_prefix
    )
