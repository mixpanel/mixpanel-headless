"""Property-based tests for the pure fingerprint and backoff-delay logic.

The I/O-free ``locking`` module carries the mutation-kill weight for this
slice's fingerprint/retry-decision logic, so these properties stress the
determinism, absence-distinctness, and inequality invariants across
randomized byte payloads, plus the backoff-delay distribution bound.
"""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from mixpanel_headless._internal.memory.locking import (
    RETRY_BACKOFF_BASE_SECONDS,
    fingerprint_of,
    next_backoff_delay,
)

byte_payloads = st.binary(min_size=0, max_size=512)


class TestFingerprintOfProperties:
    """``fingerprint_of`` is deterministic and absence-distinct."""

    @given(data=byte_payloads)
    def test_deterministic(self, data: bytes) -> None:
        """Fingerprinting the same bytes twice always yields the same value."""
        assert fingerprint_of(data) == fingerprint_of(data)

    @given(a=byte_payloads, b=byte_payloads)
    def test_distinct_payloads_produce_distinct_fingerprints(
        self, a: bytes, b: bytes
    ) -> None:
        """Two independently-drawn distinct payloads fingerprint differently.

        Standard sha256 collision-freedom assumption -- this asserts
        inequality for unequal inputs, not collision resistance itself.
        """
        if a != b:
            assert fingerprint_of(a) != fingerprint_of(b)

    @given(data=byte_payloads)
    def test_absence_never_equals_any_content_fingerprint(self, data: bytes) -> None:
        """``fingerprint_of(None)`` differs from every drawn payload's fingerprint.

        Includes ``b""`` -- an existing empty file must never be confused
        with "no file exists" (FR-009).
        """
        assert fingerprint_of(None) != fingerprint_of(data)


class TestNextBackoffDelayProperties:
    """``next_backoff_delay`` always returns a value within the base window."""

    @given(_iteration=st.integers(min_value=0, max_value=200))
    def test_always_in_bounds(self, _iteration: int) -> None:
        """Repeated calls always fall in ``[0, RETRY_BACKOFF_BASE_SECONDS)``."""
        delay = next_backoff_delay()
        assert 0.0 <= delay < RETRY_BACKOFF_BASE_SECONDS
