"""Property-based tests for the client-side request pacer using Hypothesis.

Properties tested:
- Window bound: once the limit is known
  (stored from the server, or learned mid-run from a 429), no new
  reservation's window of ``window + margin`` holds more than ``limit``
  committed reservations, over any mix of arrivals and responses.
- Causality: each reservation is at or after the time it was committed.
- Optimality: with a known limit N and no rejections, each slot equals the
  recurrence ``max(a_i, t_(i-N) + W')``.
- Parser safety: the rate-limit header parser never raises and returns only
  sane values; it reads back any well-formed policy exactly.
- Classifier safety: ``classify`` never raises and returns only safe keys.
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import httpx
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from mixpanel_headless._internal.pacer import (
    BUDGETS,
    MARGIN_S,
    LedgerKey,
    Pacer,
    PacerSettings,
    _body_params,
    classify,
    parse_rate_limit_headers,
)

NOW = 1_790_000_000.0
"""Fake epoch time at which every scenario starts."""

W = 3600.0 + MARGIN_S
"""The effective window: the server window plus the latency margin."""

KEY = LedgerKey(host="mixpanel.com", project_id="12345", bucket="query")
"""The Query API ledger key used by every scenario."""

URL = "https://mixpanel.com/api/query/insights?project_id=12345"
"""A counted Query API URL."""

RESPONSES = {
    "ok": (200, {}),
    "error": (500, {}),
    "auth": (401, {}),
    "plan": (402, {}),
    "concurrency": (429, {"RateLimit": '"project-concurrency";r=0;t=10'}),
    "window": (429, {"RateLimit": '"project";r=0;t=3600'}),
    "shed": (429, {}),
}
"""Response kinds that carry no policy, so they never teach a limit."""

LEARN = "learn"
"""A window trip whose policy teaches the scenario's limit."""


def refunded(kind: str) -> bool:
    """Tell whether the Query API removes a request after this response kind.

    Args:
        kind: The response kind.

    Returns:
        True for 401, 402, and every 429.
    """
    status = RESPONSES[kind][0] if kind in RESPONSES else 429
    return status in (401, 402, 429)


class Clock:
    """A fake wall clock that the fake sleep moves forward."""

    def __init__(self) -> None:
        """Start the clock at ``NOW``."""
        self.now = NOW

    def __call__(self) -> float:
        """Return the current fake time.

        Returns:
            The fake epoch time.
        """
        return self.now

    def sleep(self, seconds: float) -> None:
        """Move the clock forward instead of sleeping.

        Args:
            seconds: Seconds to add.
        """
        self.now += seconds


def seed_server_limit(root: Path, limit: int, key: LedgerKey = KEY) -> None:
    """Write an empty ledger whose limit the server confirmed at ``NOW``.

    Args:
        root: The storage root.
        limit: The learned limit.
        key: The ledger key.
    """
    path = root / "pacer" / key.host / f"{key.project_id}-{key.bucket}.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "v": 1,
                "limit": limit,
                "limit_source": "server",
                "learned_at": NOW,
                "blocked_until": 0,
                "sent": [],
            }
        ),
        encoding="utf-8",
    )


@settings(deadline=None)
@given(
    limit=st.integers(min_value=1, max_value=5),
    known_from_start=st.booleans(),
    ops=st.lists(
        st.tuples(
            st.floats(min_value=0.0, max_value=2000.0, allow_nan=False),
            st.sampled_from([*sorted(RESPONSES), LEARN]),
        ),
        max_size=25,
    ),
)
def test_window_bound_and_causality(
    limit: int, known_from_start: bool, ops: list[tuple[float, str]]
) -> None:
    """Once the limit is known, no new reservation overfills its window.

    The limit is known from the start (a stored server limit) or from the
    first response that teaches it. Every reservation is at or after the
    time it was committed.
    """
    key = KEY
    learn_headers = {
        "RateLimit": '"project";r=0;t=3600',
        "RateLimit-Policy": f'"project";q={limit};w=3600',
    }
    clock = Clock()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        if known_from_start:
            seed_server_limit(root, limit, key)
        pacer = Pacer(
            PacerSettings(max_wait_s=math.inf),
            storage_root=root,
            clock=clock,
            sleep=clock.sleep,
        )
        known = known_from_start
        committed: list[float] = []
        for advance, kind in ops:
            clock.now += advance
            commit_time = clock.now
            request = httpx.Request("GET", URL)
            pacer.before_send(request, key)
            _key, slot = request.extensions["mp_pacer"]
            assert slot >= commit_time
            status, headers = RESPONSES.get(kind, (429, learn_headers))
            pacer.after_response(
                httpx.Response(status, headers=headers, request=request)
            )
            if not refunded(kind):
                committed.append(slot)
                if known:
                    in_window = sum(1 for s in committed if slot - W < s <= slot)
                    assert in_window <= limit
            known = known or kind == LEARN


@settings(deadline=None)
@given(
    limit=st.integers(min_value=1, max_value=5),
    gaps=st.lists(
        st.floats(min_value=0.0, max_value=1500.0, allow_nan=False),
        min_size=1,
        max_size=30,
    ),
)
def test_slots_follow_the_optimal_recurrence(limit: int, gaps: list[float]) -> None:
    """With a known limit N, slot i equals max(a_i, t_(i-N) + W')."""
    clock = Clock()
    with tempfile.TemporaryDirectory() as tmp:
        pacer = Pacer(
            PacerSettings(max_wait_s=math.inf, query_limit=limit),
            storage_root=Path(tmp),
            clock=clock,
            sleep=lambda _seconds: None,  # arrivals do not wait for each other
        )
        slots: list[float] = []
        for gap in gaps:
            clock.now += gap
            arrival = clock.now
            expected = arrival
            if len(slots) >= limit:
                expected = max(arrival, slots[len(slots) - limit] + W)
            slots.append(pacer.reserve(KEY))
            # The pacer adds the same floats in the same order, so this is
            # exact in practice; the absolute tolerance only guards float
            # rounding (rel=0: a relative one would be ~1,790 s at 1.79e9).
            assert slots[-1] == pytest.approx(expected, rel=0, abs=1e-6)


@given(
    policy=st.text(max_size=80),
    rate=st.text(max_size=80),
)
def test_parser_never_raises(policy: str, rate: str) -> None:
    """Arbitrary header text never raises and gives sane values."""
    headers = httpx.Headers(
        [
            (b"RateLimit-Policy", policy.encode("utf-8", "replace")),
            (b"RateLimit", rate.encode("utf-8", "replace")),
        ]
    )
    info = parse_rate_limit_headers(headers)
    if info is not None:
        assert info.window_quota is None or info.window_quota > 0
        assert info.window_seconds is None or info.window_seconds > 0
        assert info.tripped in (None, "window", "concurrency")


@given(
    quota=st.integers(min_value=1, max_value=100_000),
    window=st.integers(min_value=1, max_value=86_400),
    concurrency=st.integers(min_value=1, max_value=100),
)
def test_parser_reads_policy_exactly(quota: int, window: int, concurrency: int) -> None:
    """A well-formed server policy reads back its project quota and window."""
    policy = (
        f'"project";q={quota};w={window}, '
        f'"project-concurrency";q={concurrency};qu="concurrent-requests"'
    )
    info = parse_rate_limit_headers(httpx.Headers({"RateLimit-Policy": policy}))
    assert info is not None
    assert (info.window_quota, info.window_seconds) == (quota, window)


@given(
    segments=st.lists(
        st.text(
            alphabet=st.characters(exclude_categories=("Cc", "Cs")),
            max_size=12,
        ),
        max_size=4,
    ),
    project_id=st.text(max_size=70),
    family=st.sampled_from(["query", "engage", "export", "app", None]),
    content=st.one_of(
        st.none(),
        st.binary(max_size=60),
        st.one_of(st.text(max_size=12), st.integers(), st.booleans()).map(
            lambda pid: json.dumps({"project_id": pid}).encode()
        ),
        st.text(alphabet="0123456789", min_size=1, max_size=8).map(
            lambda pid: f"project_id={pid}".encode()
        ),
    ),
)
def test_classify_never_raises(
    segments: list[str],
    project_id: str,
    family: str | None,
    content: bytes | None,
) -> None:
    """Arbitrary paths, project IDs, and bodies never raise; keys are safe.

    The key's project is the effective one: a body value replaces the URL
    value, like the server merges them.
    """
    base = "https://mixpanel.com/api/query"
    url = httpx.URL(base + "/" + "/".join(segments), params={"project_id": project_id})
    key = classify(url, family, base, content=content)
    if key is not None:
        body = _body_params(content)
        effective = str(body["project_id"]) if "project_id" in body else project_id
        assert key.bucket in BUDGETS
        assert key.project_id == effective
        assert "/" not in key.project_id and key.project_id not in ("", ".", "..")
