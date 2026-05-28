"""Bundle-level aggregations over normalized actions (044/T058).

Each function returns a ``pandas.DataFrame`` so callers can chain into
sort, filter, and join idioms without re-deriving the underlying
counts. The functions deliberately work off the bundle's already-cached
``actions_df`` — they don't re-walk the per-replay action lists.

Conventions:
- Counts are integers; rates are floats in ``[0, 1]``.
- All time-window thresholds are in milliseconds for click-pattern
  aggregators (rage / dead clicks) and seconds for ``long_pauses``.
- Empty input is always a valid empty DataFrame with the documented
  columns — never raise on a zero-action bundle.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pandas as pd

from mixpanel_headless._internal.replays.labels import default_label_fn

if TYPE_CHECKING:
    from mixpanel_headless.types import ReplayBundle, UserAction


def top_paths(
    bundle: ReplayBundle,
    n: int = 10,
    *,
    label_fn: Callable[[UserAction], str] | None = None,
) -> pd.DataFrame:
    """Top-N most-common action paths (sequences of labels per replay).

    Args:
        bundle: The :class:`ReplayBundle` to aggregate over.
        n: How many distinct paths to return.
        label_fn: Optional label function; defaults to
            :func:`default_label_fn`.

    Returns:
        DataFrame with columns ``path``, ``count``, sorted descending by
        count. Empty when the bundle has no replays.
    """
    fn = label_fn or default_label_fn
    counts: dict[tuple[str, ...], int] = {}
    for replay in bundle.replays:
        path = tuple(fn(a) for a in replay.actions)
        if not path:
            continue
        counts[path] = counts.get(path, 0) + 1
    if not counts:
        return pd.DataFrame(columns=["path", "count"])
    rows = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:n]
    return pd.DataFrame([{"path": " → ".join(p), "count": c} for p, c in rows])


def top_clicks(bundle: ReplayBundle, n: int = 10) -> pd.DataFrame:
    """Top-N click targets across the bundle.

    Args:
        bundle: The bundle to aggregate.
        n: How many click targets to return.

    Returns:
        DataFrame with columns ``target_desc``, ``count``, sorted
        descending by count.
    """
    df = bundle.actions_df
    if df.empty:
        return pd.DataFrame(columns=["target_desc", "count"])
    clicks = df[df["action"] == "click"]
    if clicks.empty:
        return pd.DataFrame(columns=["target_desc", "count"])
    grouped: pd.DataFrame = (
        clicks.groupby("target_desc", dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
        .head(n)
        .reset_index(drop=True)
    )
    return grouped


def top_pages(bundle: ReplayBundle, n: int = 10) -> pd.DataFrame:
    """Top-N most-visited pages.

    Args:
        bundle: The bundle to aggregate.
        n: How many pages to return.

    Returns:
        DataFrame with columns ``url``, ``visits``, sorted descending by
        visits.
    """
    df = bundle.pages_df
    if df.empty:
        return pd.DataFrame(columns=["url", "visits"])
    grouped: pd.DataFrame = (
        df.groupby("url", dropna=False)
        .size()
        .reset_index(name="visits")
        .sort_values("visits", ascending=False)
        .head(n)
        .reset_index(drop=True)
    )
    return grouped


def dead_clicks(bundle: ReplayBundle, window_ms: int = 200) -> pd.DataFrame:
    """Clicks with no follow-up DOM activity within ``window_ms``.

    Heuristic: a click that's followed by NO other action (input, scroll,
    navigate, viewport_resize, …) within ``window_ms`` is "dead" — the
    target presumably wasn't interactive.

    Args:
        bundle: The bundle to scan.
        window_ms: Look-ahead window in milliseconds. Default 200.

    Returns:
        DataFrame with columns ``replay_id``, ``t``, ``target_desc`` —
        one row per dead click.
    """
    rows: list[dict[str, object]] = []
    for replay in bundle.replays:
        for i, action in enumerate(replay.actions):
            if action.action != "click":
                continue
            # Look forward at subsequent actions within window_ms.
            has_follow_up = any(
                later.timestamp - action.timestamp <= window_ms
                and later.timestamp > action.timestamp
                for later in replay.actions[i + 1 :]
            )
            if not has_follow_up:
                rows.append(
                    {
                        "replay_id": replay.replay_id,
                        "t": action.timestamp,
                        "target_desc": action.target_desc,
                    }
                )
    return pd.DataFrame(rows, columns=["replay_id", "t", "target_desc"])


def rage_clicks(
    bundle: ReplayBundle,
    threshold: int = 3,
    window_ms: int = 1000,
) -> pd.DataFrame:
    """Bursts of ≥ ``threshold`` clicks on the same target within ``window_ms``.

    Args:
        bundle: The bundle to scan.
        threshold: Minimum clicks per burst. Default 3.
        window_ms: Maximum span of the burst in milliseconds. Default 1000.

    Returns:
        DataFrame with columns ``replay_id``, ``t_start``, ``target_desc``,
        ``count`` — one row per rage burst.
    """
    rows: list[dict[str, object]] = []
    for replay in bundle.replays:
        clicks = [a for a in replay.actions if a.action == "click"]
        i = 0
        while i < len(clicks):
            j = i + 1
            while (
                j < len(clicks)
                and clicks[j].target_desc == clicks[i].target_desc
                and clicks[j].timestamp - clicks[i].timestamp <= window_ms
            ):
                j += 1
            burst = j - i
            if burst >= threshold:
                rows.append(
                    {
                        "replay_id": replay.replay_id,
                        "t_start": clicks[i].timestamp,
                        "target_desc": clicks[i].target_desc,
                        "count": burst,
                    }
                )
                i = j
            else:
                i += 1
    return pd.DataFrame(rows, columns=["replay_id", "t_start", "target_desc", "count"])


def long_pauses(bundle: ReplayBundle, threshold_s: float = 10) -> pd.DataFrame:
    """Idle stretches between consecutive actions longer than ``threshold_s``.

    Args:
        bundle: The bundle to scan.
        threshold_s: Minimum pause length in seconds. Default 10.

    Returns:
        DataFrame with columns ``replay_id``, ``t_start``, ``duration_s``.
    """
    threshold_ms = int(threshold_s * 1000)
    rows: list[dict[str, object]] = []
    for replay in bundle.replays:
        for prev, curr in zip(replay.actions, replay.actions[1:], strict=False):
            gap_ms = curr.timestamp - prev.timestamp
            if gap_ms >= threshold_ms:
                rows.append(
                    {
                        "replay_id": replay.replay_id,
                        "t_start": prev.timestamp,
                        "duration_s": gap_ms / 1000.0,
                    }
                )
    return pd.DataFrame(rows, columns=["replay_id", "t_start", "duration_s"])


def error_sessions(bundle: ReplayBundle) -> list[str]:
    """Replay IDs that emitted at least one ``console_error`` action.

    Args:
        bundle: The bundle to scan.

    Returns:
        List of replay IDs in input order. Empty when the bundle has no
        console errors.
    """
    return [
        replay.replay_id
        for replay in bundle.replays
        if any(a.action == "console_error" for a in replay.actions)
    ]
