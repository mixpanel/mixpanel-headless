"""pm4py adapter for ReplayBundle event logs (044, US4/T079).

Wraps a session-replay event log DataFrame in a pm4py ``EventLog`` for
process-mining workflows (inductive miner, BPMN discovery, DFG, etc.).
``pm4py`` is an optional dependency — the import happens inside the
function body, and callers without ``[replay-mining]`` installed
short-circuit to the underlying DataFrame in
:meth:`ReplayBundle.event_log`.

The XES column convention (``case:concept:name``, ``concept:name``,
``time:timestamp``) is already established by :meth:`ReplayBundle.event_log`,
so this adapter is a thin pm4py wrapping step — no column rewriting.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def wrap_event_log_dataframe(df: pd.DataFrame) -> Any:
    """Convert a DataFrame into a pm4py ``EventLog`` via ``format_dataframe``.

    Args:
        df: Event-log DataFrame with the XES columns
            (``case:concept:name``, ``concept:name``, ``time:timestamp``).

    Returns:
        A ``pm4py.objects.log.obj.EventLog`` — typed as ``Any`` because
        pm4py is an optional dependency and importing its type here would
        defeat the lazy-import pattern.

    Raises:
        ImportError: pm4py is not installed (caller should fall back to
            the bare DataFrame).
    """
    import pm4py  # type: ignore[import-not-found]

    return pm4py.format_dataframe(
        df,
        case_id="case:concept:name",
        activity_key="concept:name",
        timestamp_key="time:timestamp",
    )
