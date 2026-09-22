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

import math
from typing import TYPE_CHECKING

import pandas as pd

from mixpanel_headless._internal.replays.rrweb_analyzer import finger_downs

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


_RAGE_TAP_COLUMNS = [
    "replay_id",
    "t_start",
    "t_end",
    "target_desc",
    "x",
    "y",
    "count",
    "kind",
]


def _interval_has_change(screens: list[tuple[int, str]], lo: int, hi: int) -> bool:
    """Whether a screen changes in the interval ``(lo, hi]``.

    Args:
        screens: ``(timestamp, description)`` of the replay's screen
            actions, in timestamp order.
        lo: The interval start (excluded).
        hi: The interval end (included).

    Returns:
        True when a screen in the interval has a description that differs
        from the latest screen description at or before ``lo`` (or when
        there is no earlier screen).

    Example:
        ```python
        screens = [(1000, "Wireframe: Home"), (2250, "Wireframe: Cart")]
        _interval_has_change(screens, 2000, 2200)  # False
        _interval_has_change(screens, 2200, 2400)  # True
        ```
    """
    baseline: str | None = None
    for timestamp, description in screens:
        if timestamp <= lo:
            baseline = description
        elif timestamp <= hi:
            if description != baseline:
                return True
        else:
            break
    return False


def rage_taps(
    bundle: ReplayBundle,
    threshold: int = 3,
    window_ms: int = 2000,
    radius_px: float = 24,
    grace_ms: int = 1000,
) -> pd.DataFrame:
    """Rage and dead tap bursts in the bundle's screenshot recordings.

    Finger-downs come from each replay's ``rrweb_events`` (see
    :func:`finger_downs`); DOM recordings give none. Bursts form greedily
    in time order: an unused finger-down opens a burst, and every later
    unused finger-down within ``window_ms`` of it and within
    ``radius_px`` of its point joins. A finger-down at another point does
    not break the burst.

    A burst with at least ``threshold`` members is classified per
    interval. The intervals are the ``count - 1`` gaps between consecutive
    finger-downs, ``(t_k, t_k+1]``, plus the grace window after the last
    one, ``(t_end, t_end + grace_ms]``. An interval has a change when it
    holds a ``"screen"`` action whose description differs from the latest
    screen description at or before the interval's start. Then:

    - no interval has a change: ``"dead"``;
    - otherwise, every gap between finger-downs has a change: an
      intentional run (a quantity stepper, a carousel), which is skipped
      (a one-tap burst has no gaps, so a change skips it);
    - otherwise: ``"rage"``.

    Known limit: a screen that changes on its own (a live clock, a timer,
    an animation) counts as a change, so a dead control on such a screen
    can read as ``"rage"`` or be skipped as intentional.

    Args:
        bundle: The bundle to scan.
        threshold: Minimum finger-downs per burst. Default 3.
        window_ms: Maximum burst span from the first finger-down, in
            milliseconds. Default 2000.
        radius_px: Maximum distance from the first finger-down, in
            touch-space pixels. Default 24.
        grace_ms: Time after the last finger-down in which a screen change
            still counts, in milliseconds. Default 1000.

    Returns:
        DataFrame with columns ``replay_id``, ``t_start``, ``t_end``,
        ``target_desc``, ``x``, ``y``, ``count``, ``kind`` — one row per
        reported burst, in replay order and then time order.

    Example:
        ```python
        # Three taps on "Pay" at 2000, 2300, and 2600 ms with no screen change
        # between them, then a "Receipt" screen at 2700 ms (in the grace window):
        rage_taps(bundle)
        #   replay_id  t_start  t_end target_desc    x    y  count  kind
        # 0       r-1     2000   2600  button:Pay  100  100      3  rage
        ```
    """
    rows: list[dict[str, object]] = []
    for replay in bundle.replays:
        downs = finger_downs(replay.rrweb_events)
        if len(downs) < threshold:
            continue
        screens = [
            (a.timestamp, a.description) for a in replay.actions if a.action == "screen"
        ]
        used = [False] * len(downs)
        for i, first in enumerate(downs):
            if used[i]:
                continue
            members = [i]
            for j in range(i + 1, len(downs)):
                candidate = downs[j]
                if candidate.timestamp - first.timestamp > window_ms:
                    break
                if not used[j] and (
                    math.hypot(candidate.x - first.x, candidate.y - first.y)
                    <= radius_px
                ):
                    members.append(j)
            if len(members) < threshold:
                continue
            for j in members:
                used[j] = True
            times = [downs[j].timestamp for j in members]
            t_start = times[0]
            t_end = times[-1]
            gaps = [
                _interval_has_change(screens, lo, hi)
                for lo, hi in zip(times, times[1:], strict=False)
            ]
            grace = _interval_has_change(screens, t_end, t_end + grace_ms)
            changed = grace or any(gaps)
            if changed and all(gaps):
                continue
            rows.append(
                {
                    "replay_id": replay.replay_id,
                    "t_start": t_start,
                    "t_end": t_end,
                    "target_desc": first.target_desc,
                    "x": first.x,
                    "y": first.y,
                    "count": len(members),
                    "kind": "rage" if changed else "dead",
                }
            )
    return pd.DataFrame(rows, columns=_RAGE_TAP_COLUMNS)


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
