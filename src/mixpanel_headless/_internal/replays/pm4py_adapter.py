"""pm4py adapter for ReplayBundle event logs (044, US4/T079).

Formats a session-replay event log DataFrame into pm4py's standard
event-log shape for process-mining workflows (inductive miner, BPMN
discovery, DFG, etc.). ``pm4py`` is an optional dependency — the import
happens inside the function body, and callers without ``[replay-mining]``
installed short-circuit to the underlying DataFrame in
:meth:`ReplayBundle.event_log`.

The XES column convention (``case:concept:name``, ``concept:name``,
``time:timestamp``) is already established by :meth:`ReplayBundle.event_log`,
so this adapter is a thin ``pm4py.format_dataframe`` step — no column
rewriting. pm4py 2.7+ treats the formatted DataFrame as a first-class event
log (the mining functions accept it directly), so no separate ``EventLog``
object is built here.
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def wrap_event_log_dataframe(df: pd.DataFrame) -> Any:
    """Format a DataFrame into pm4py's event-log shape via ``format_dataframe``.

    ``pm4py.format_dataframe`` standardizes the case/activity/timestamp
    columns and returns a pandas ``DataFrame`` (pm4py 2.7+ uses DataFrames as
    first-class event logs — the mining functions accept one directly). This
    is intentionally a formatted DataFrame, not a
    ``pm4py.objects.log.obj.EventLog``; callers needing the legacy object form
    can pass the result to ``pm4py.convert_to_event_log``.

    Args:
        df: Event-log DataFrame with the XES columns
            (``case:concept:name``, ``concept:name``, ``time:timestamp``).

    Returns:
        A pm4py-formatted pandas ``DataFrame`` — typed ``Any`` because pm4py
        is an optional dependency and importing its types here would defeat
        the lazy-import pattern.

    Raises:
        ImportError: pm4py is not installed (caller should fall back to
            the bare DataFrame).
    """
    import pm4py

    formatted: Any = pm4py.format_dataframe(
        df,
        case_id="case:concept:name",
        activity_key="concept:name",
        timestamp_key="time:timestamp",
    )
    return formatted
