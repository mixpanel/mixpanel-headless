"""Bundle-level aggregations over normalized actions (044).

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

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from mixpanel_headless.types import ReplayBundle


def real_clicks(actions_df: pd.DataFrame) -> pd.DataFrame:
    """Genuine clicks from an ``actions_df`` — drops focus-only interactions.

    A real user click fires BOTH a ``focused`` and a ``clicked`` rrweb
    interaction, and the analyzer maps both to the ``click`` action literal.
    Counting both double-counts every click and inflates element rankings, so
    this keeps the ``clicked`` / ``double-clicked`` / ``right-clicked`` rows and
    drops the paired ``focused`` ones (``metadata['interaction'] == 'focused'``).

    Args:
        actions_df: A bundle or replay ``actions_df`` projection.

    Returns:
        The subset of click rows excluding focus-only interactions. Rows with
        no ``interaction`` metadata are kept (treated as genuine clicks).
    """
    if actions_df.empty:
        return actions_df
    clicks: pd.DataFrame = actions_df[actions_df["action"] == "click"]
    if clicks.empty:
        return clicks
    keep = clicks["metadata"].map(lambda m: (m or {}).get("interaction") != "focused")
    filtered: pd.DataFrame = clicks[keep]
    return filtered


def top_clicks(bundle: ReplayBundle, n: int = 10) -> pd.DataFrame:
    """Top-N click targets across the bundle.

    Counts genuine clicks only: focus-only interactions are excluded via
    :func:`real_clicks` so each user click counts once.

    Args:
        bundle: The bundle to aggregate.
        n: How many click targets to return.

    Returns:
        DataFrame with columns ``target_desc``, ``count``, sorted
        descending by count.
    """
    clicks = real_clicks(bundle.actions_df)
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
        # Drop focus-only interactions: the analyzer maps both a real click and
        # its paired focus event to action="click", so counting the focus row
        # inflates burst sizes. Same predicate real_clicks() uses.
        clicks = [
            a
            for a in replay.actions
            if a.action == "click"
            and (a.metadata or {}).get("interaction") != "focused"
        ]
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
