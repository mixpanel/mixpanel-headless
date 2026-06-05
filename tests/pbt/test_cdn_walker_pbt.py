"""Property-based tests for the session-replay CDN walker (044).

Invariants verified across randomly generated 404 positions and per-file
event counts:

- The walker terminates at exactly the 404 position (or at ``max_files``
  when no 404 falls in the bound).
- The 404 file is never re-fetched.
- ``max_files`` is respected even when the 404 sentinel falls beyond it.
- Returned events are sorted by ``timestamp`` regardless of in-batch
  fetch ordering.
- A 404 at position 0 raises :class:`ReplayNotFoundError` rather than
  returning an empty list (the "replay doesn't exist on CDN" signal).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock
from urllib.parse import urlparse

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mixpanel_headless._internal.services.replays import ReplaysService
from mixpanel_headless.exceptions import ReplayNotFoundError
from mixpanel_headless.types import SignedReplay


def _signed() -> SignedReplay:
    """Build a SignedReplay pointing at the fake CDN host."""
    return SignedReplay(
        replay_id="r-pbt",
        url="https://cdn.test/srr-us/sha-pbt/",
        query_string="URLPrefix=A&Signature=S",
        env="prod",
        signed_at=1716810000.0,
    )


def _file_num(url: str) -> int:
    """Extract the NNNN index from a CDN URL like ``...0007-30.json?...``."""
    last = urlparse(url).path.rsplit("/", 1)[-1]
    return int(last.split("-", 1)[0])


def _mock_api() -> MagicMock:
    """A minimal MixpanelAPIClient stand-in for ReplaysService construction."""
    api = MagicMock()
    api.project_id = "12345"
    api.sign_replays = MagicMock(return_value=[])
    return api


# Bounded to keep PBT runs fast: 0 ≤ k ≤ 50 for the 404 position; up to 5
# events per file; max_files capped at 100. Wider ranges would just churn
# CPU without exercising additional logic.
@settings(deadline=None, max_examples=50)
@given(
    k=st.integers(min_value=1, max_value=50),
    event_counts=st.lists(
        st.integers(min_value=1, max_value=5),
        min_size=51,
        max_size=51,
    ),
    max_files=st.integers(min_value=1, max_value=100),
    concurrency=st.integers(min_value=1, max_value=10),
)
def test_walker_terminates_at_404_and_respects_max_files(
    k: int,
    event_counts: list[int],
    max_files: int,
    concurrency: int,
) -> None:
    """Walker stops at exactly min(k, max_files); 404 is never re-fetched."""
    requested: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Serve 200s with ``event_counts[n]`` events until file ``k`` → 404."""
        file_num = _file_num(str(request.url))
        requested.append(file_num)
        if file_num >= k:
            return httpx.Response(404)
        events = [
            {"type": 3, "data": {}, "timestamp": file_num * 1000 + i}
            for i in range(event_counts[file_num])
        ]
        return httpx.Response(200, json=events)

    api = _mock_api()
    transport = httpx.MockTransport(handler)
    service = ReplaysService(api, _async_transport=transport)

    if k >= max_files:
        # Bound reached before the 404 → no exception, capped output.
        events = service.fetch_files(
            _signed(),
            retention_days=30,
            max_files=max_files,
            concurrency=concurrency,
        )
        # All file numbers fetched are within [0, max_files).
        assert all(n < max_files for n in requested)
        # We expect events for files [0, max_files) since none hit the
        # 404 sentinel within the bound.
        expected = sum(event_counts[n] for n in range(max_files))
        assert len(events) == expected
    else:
        # k < max_files → 404 sentinel terminates the walk cleanly.
        events = service.fetch_files(
            _signed(),
            retention_days=30,
            max_files=max_files,
            concurrency=concurrency,
        )
        # The 404 file was fetched once at most.
        assert requested.count(k) <= 1
        # No file >= k contributed events.
        assert sum(event_counts[n] for n in range(k)) == len(events)


@settings(deadline=None, max_examples=30)
@given(
    event_counts=st.lists(
        st.integers(min_value=1, max_value=5),
        min_size=10,
        max_size=10,
    ),
    concurrency=st.integers(min_value=1, max_value=4),
)
def test_walker_returns_timestamp_sorted_events(
    event_counts: list[int],
    concurrency: int,
) -> None:
    """Output is sorted ascending by ``timestamp`` regardless of fetch order."""

    # Use deliberately scrambled timestamps within each file so the in-file
    # sort matters: file N contributes timestamps in reverse order.
    def handler(request: httpx.Request) -> httpx.Response:
        """Serve files with deliberately out-of-order in-file timestamps."""
        file_num = _file_num(str(request.url))
        if file_num >= 10:
            return httpx.Response(404)
        n_events = event_counts[file_num]
        # Reverse-order within the file; sort must put them back in order.
        events = [
            {"type": 3, "data": {}, "timestamp": file_num * 1000 + (n_events - i)}
            for i in range(n_events)
        ]
        return httpx.Response(200, json=events)

    api = _mock_api()
    transport = httpx.MockTransport(handler)
    service = ReplaysService(api, _async_transport=transport)

    events = service.fetch_files(
        _signed(), retention_days=30, max_files=500, concurrency=concurrency
    )
    # Within each file: timestamps strictly ascending (the in-file sort).
    # Across files: monotonically non-decreasing because file N+1's
    # timestamps start at (N+1)*1000 > N*1000+n_events for our generator
    # (n_events ≤ 5, gap = 1000).
    ts = [int(e["timestamp"]) for e in events]
    assert ts == sorted(ts)


@settings(deadline=None, max_examples=20)
@given(concurrency=st.integers(min_value=1, max_value=10))
def test_first_file_404_always_raises_replay_not_found(concurrency: int) -> None:
    """404 at position 0 ALWAYS raises ReplayNotFoundError (never empty list)."""

    def handler(_request: httpx.Request) -> httpx.Response:
        """Serve 404 for every file — first-file 404 is the not-found signal."""
        return httpx.Response(404)

    api = _mock_api()
    transport = httpx.MockTransport(handler)
    service = ReplaysService(api, _async_transport=transport)

    with pytest.raises(ReplayNotFoundError):
        service.fetch_files(
            _signed(),
            retention_days=30,
            max_files=10,
            concurrency=concurrency,
        )


# Keep Any reachable so the file's typing surface is non-empty for tools
# that scan for unused-import suppressions.
_ = Any
