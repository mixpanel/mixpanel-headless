"""Integration tests: pacers in several processes and threads share one ledger.

Each worker builds its own ``Pacer`` on a shared temporary storage root with
a configured Query API limit and reserves slots directly. ``reserve`` never
sleeps and ``max_wait_s`` is infinite, so a reservation past the limit
returns a future slot at once. The parent then checks the ledger's
invariant: no window of ``window + margin`` seconds holds more than
``limit`` slots. Equal slots are legal.
"""

from __future__ import annotations

import math
import multiprocessing
import threading
from pathlib import Path
from typing import Any

import pytest

from mixpanel_headless._internal.pacer import (
    BUDGETS,
    MARGIN_S,
    LedgerKey,
    Pacer,
    PacerSettings,
)

#: The configured Query API limit for these tests.
_LIMIT = 6

#: Number of concurrent workers.
_WORKERS = 4

#: Reservations per worker (more than the limit in total, so later ones wait).
_PER_WORKER = 5

#: The ledger every worker shares.
_KEY = LedgerKey(host="mixpanel.com", project_id="12345", bucket="query")


def _reserve_many(storage_root: str, count: int) -> list[float]:
    """Reserve ``count`` slots on the shared ledger.

    Args:
        storage_root: The shared storage root.
        count: The number of reservations.

    Returns:
        The reserved slot times, in order.
    """
    pacer = Pacer(
        PacerSettings(max_wait_s=math.inf, query_limit=_LIMIT),
        storage_root=Path(storage_root),
    )
    return [pacer.reserve(_KEY) for _ in range(count)]


def _process_worker(
    storage_root: str,
    count: int,
    barrier: Any,
    results: Any,
) -> None:
    """Wait for every worker to start, then reserve and report the slots.

    Module-level so the ``spawn`` start method can import it in the child.

    Args:
        storage_root: The shared storage root.
        count: The number of reservations.
        barrier: A multiprocessing barrier shared by all workers.
        results: A multiprocessing queue that receives the slot list.
    """
    barrier.wait()
    results.put(_reserve_many(storage_root, count))


def _assert_ledger_invariants(slots: list[float]) -> None:
    """Assert the window invariant over all reservations (equal slots are legal).

    Args:
        slots: Every reserved slot from every worker.
    """
    assert len(slots) == _WORKERS * _PER_WORKER
    window = BUDGETS["query"].window_s + MARGIN_S
    ordered = sorted(slots)
    for index, start in enumerate(ordered):
        in_window = sum(1 for slot in ordered[index:] if slot < start + window)
        assert in_window <= _LIMIT, f"{in_window} slots in one window from {start}"
    # The limit is reached, so the later reservations are pushed a window out.
    assert ordered[_LIMIT] >= ordered[0] + window


def test_processes_never_exceed_the_limit(tmp_path: Path) -> None:
    """Several processes reserve on one ledger without breaking the limit."""
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(_WORKERS)
    results = ctx.Queue()
    workers = [
        ctx.Process(
            target=_process_worker,
            args=(str(tmp_path), _PER_WORKER, barrier, results),
        )
        for _ in range(_WORKERS)
    ]
    for worker in workers:
        worker.start()
    slots: list[float] = []
    try:
        for _ in workers:
            slots.extend(results.get(timeout=30))
    finally:
        for worker in workers:
            worker.join(timeout=30)
            if worker.is_alive():  # pragma: no cover - only on a hang
                worker.terminate()
                worker.join(timeout=5)
    assert not any(worker.is_alive() for worker in workers)
    assert all(worker.exitcode == 0 for worker in workers)
    _assert_ledger_invariants(slots)


def test_threads_never_exceed_the_limit(tmp_path: Path) -> None:
    """Several threads, each with its own pacer, share one ledger safely."""
    barrier = threading.Barrier(_WORKERS)
    slots: list[float] = []
    errors: list[BaseException] = []
    guard = threading.Lock()

    def run() -> None:
        """Reserve this thread's slots and collect them."""
        try:
            barrier.wait()
            mine = _reserve_many(str(tmp_path), _PER_WORKER)
        except BaseException as exc:  # noqa: BLE001 - reported below
            with guard:
                errors.append(exc)
            return
        with guard:
            slots.extend(mine)

    # Daemon threads: a hung worker cannot keep pytest alive after the timeout.
    threads = [threading.Thread(target=run, daemon=True) for _ in range(_WORKERS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    _assert_ledger_invariants(slots)


def test_single_worker_reserves_in_order(tmp_path: Path) -> None:
    """One pacer alone gets increasing slots, pushed out once at the limit.

    Args:
        tmp_path: The storage root.
    """
    slots = _reserve_many(str(tmp_path), _LIMIT + 1)
    assert slots == sorted(slots)
    window = BUDGETS["query"].window_s + MARGIN_S
    # rel=0: a relative tolerance would be ~1,790 s at epoch 1.79e9.
    assert slots[_LIMIT] == pytest.approx(slots[0] + window, rel=0, abs=1e-6)
