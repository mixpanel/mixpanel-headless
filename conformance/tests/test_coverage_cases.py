"""P2-1 recorder-coverage closure cases (phase2-design C10 / Discrepancy #10).

Five ``types.*`` entry points carry coded constructor/classmethod guards but
had ZERO recorded vectors in the AD-6 corpus: ``types.FunnelStep`` and
``types.RetentionEvent`` (real ``__post_init__`` guards, previously absent
from the D4 recorder registry), ``types.CohortCriteria.did_not_do_event``
(registered, never exercised at a recordable depth), and the previously
unregistered public factories ``types.CohortCriteria.property_is_set`` /
``property_is_not_set``. The suite's own ``tests/`` tree is frozen for
Phase 2 (support-branch rule: ``conformance/``-only changes), so the
guard-failure cases live HERE and are appended to the record invocation via
``conformance/record/exclusions.args`` (see ``conformance/record/README.md``).

Under the record plugin every failing construction below emits one
``builder``-kind vector with ``expect.error = {class, code}`` through the
``error_only`` guard entries added to ``conformance/record/registry.py``;
success-path constructions are silently skipped at emit (RR-7 fix c) and
exist to pin the non-raising contract in the normal test runs. Guard-input
selection follows the GATE-VERDICT R1 convention: at least two distinct
violating inputs per code site.
"""

from __future__ import annotations

from typing import Any

import pytest

from mixpanel_headless.exceptions import ParamValidationError
from mixpanel_headless.types import CohortCriteria, FunnelStep, RetentionEvent


class TestFunnelStepGuardVectors:
    """Recorded guard-failure cases for ``types.FunnelStep`` (EV1/EV2)."""

    @pytest.mark.parametrize(
        ("event", "code"),
        [
            # EV1 (empty event) — 2 distinct violating inputs for the site.
            ("", "EV1_EMPTY_EVENT"),
            ("   ", "EV1_EMPTY_EVENT"),
            # EV2 (control characters) — 2 distinct violating inputs.
            ("a\x00b", "EV2_CONTROL_CHAR_EVENT"),
            ("a\x7fb", "EV2_CONTROL_CHAR_EVENT"),
        ],
    )
    def test_guard_raises_coded_error(self, event: str, code: str) -> None:
        """Each FunnelStep event-name guard raises with its code.

        Args:
            event: The violating event name.
            code: The expected registry code.

        Raises:
            AssertionError: If the raise is missing or carries a
                different code.
        """
        with pytest.raises(ParamValidationError) as excinfo:
            FunnelStep(event)
        assert excinfo.value.code == code

    def test_valid_event_constructs(self) -> None:
        """A plain event name constructs without raising.

        Raises:
            AssertionError: If defaults deviate from the declared contract.
        """
        step = FunnelStep("Signup")
        assert step.event == "Signup"
        assert step.label is None
        assert step.filters is None
        assert step.filters_combinator == "all"
        assert step.order is None


class TestRetentionEventGuardVectors:
    """Recorded guard-failure cases for ``types.RetentionEvent`` (EV1/EV2)."""

    @pytest.mark.parametrize(
        ("event", "code"),
        [
            # EV1 (empty event) — 2 distinct violating inputs for the site.
            ("", "EV1_EMPTY_EVENT"),
            ("   ", "EV1_EMPTY_EVENT"),
            # EV2 (control characters) — 2 distinct violating inputs.
            ("a\x00b", "EV2_CONTROL_CHAR_EVENT"),
            ("a\x7fb", "EV2_CONTROL_CHAR_EVENT"),
        ],
    )
    def test_guard_raises_coded_error(self, event: str, code: str) -> None:
        """Each RetentionEvent event-name guard raises with its code.

        Args:
            event: The violating event name.
            code: The expected registry code.

        Raises:
            AssertionError: If the raise is missing or carries a
                different code.
        """
        with pytest.raises(ParamValidationError) as excinfo:
            RetentionEvent(event)
        assert excinfo.value.code == code

    def test_valid_event_constructs(self) -> None:
        """A plain event name constructs without raising.

        Raises:
            AssertionError: If defaults deviate from the declared contract.
        """
        born = RetentionEvent("Signup")
        assert born.event == "Signup"
        assert born.filters is None
        assert born.filters_combinator == "all"


class TestDidNotDoEventGuardVectors:
    """Recorded guard-failure cases for ``CohortCriteria.did_not_do_event``.

    The factory delegates to ``did_event(event, exactly=0, ...)``; under the
    record plugin the OUTER ``did_not_do_event`` seam owns the vector (the
    inner ``did_event`` capture is suppressed by the re-entrancy guard), so
    these cases close the registered-but-zero-vectors hole.
    """

    @pytest.mark.parametrize(
        ("kwargs", "code"),
        [
            # CD4 (empty event) — 2 distinct violating inputs.
            ({"event": ""}, "CD4_EMPTY_EVENT"),
            ({"event": "   "}, "CD4_EMPTY_EVENT"),
            # CD3 (exactly one time constraint required) — none given,
            # then two rolling windows given.
            ({"event": "Login"}, "CD3_TIME_CONSTRAINT_REQUIRED"),
            (
                {"event": "Login", "within_days": 30, "within_weeks": 4},
                "CD3_TIME_CONSTRAINT_REQUIRED",
            ),
            # CD3 (rolling window must be positive).
            ({"event": "Login", "within_days": 0}, "CD3_WINDOW_NOT_POSITIVE"),
            ({"event": "Login", "within_weeks": -1}, "CD3_WINDOW_NOT_POSITIVE"),
            # CD5 (absolute dates must be paired).
            ({"event": "Login", "from_date": "2024-01-01"}, "CD5_FROM_REQUIRES_TO"),
            ({"event": "Login", "to_date": "2024-03-31"}, "CD5_TO_REQUIRES_FROM"),
            # CD6 (dates must parse and be ordered).
            (
                {"event": "Login", "from_date": "2024-13-01", "to_date": "2024-12-31"},
                "CD6_DATE_INVALID",
            ),
            (
                {"event": "Login", "from_date": "2024-03-31", "to_date": "2024-01-01"},
                "CD6_DATE_ORDER",
            ),
        ],
    )
    def test_guard_raises_coded_error(self, kwargs: dict[str, Any], code: str) -> None:
        """Each did_not_do_event guard raises with its delegated code.

        Args:
            kwargs: Factory keyword arguments (violating).
            code: The expected registry code.

        Raises:
            AssertionError: If the raise is missing or carries a
                different code.
        """
        with pytest.raises(ParamValidationError) as excinfo:
            CohortCriteria.did_not_do_event(**kwargs)
        assert excinfo.value.code == code

    def test_valid_call_constructs(self) -> None:
        """A windowed did_not_do_event constructs without raising.

        Raises:
            AssertionError: If the equivalence with
                ``did_event(exactly=0)`` breaks.
        """
        criterion = CohortCriteria.did_not_do_event("Login", within_days=30)
        twin = CohortCriteria.did_event("Login", exactly=0, within_days=30)
        assert criterion._selector_node == twin._selector_node
        assert criterion._behavior == twin._behavior


class TestPropertyIsSetGuardVectors:
    """Recorded guard-failure cases for ``CohortCriteria.property_is_set``.

    Delegates to ``has_property`` (CD7 guard); the OUTER factory seam owns
    the vector once registered.
    """

    @pytest.mark.parametrize("property_name", ["", "   "])
    def test_empty_property_raises_coded_error(self, property_name: str) -> None:
        """An empty/whitespace property name raises CD7.

        Args:
            property_name: The violating property name.

        Raises:
            AssertionError: If the raise is missing or carries a
                different code.
        """
        with pytest.raises(ParamValidationError) as excinfo:
            CohortCriteria.property_is_set(property_name)
        assert excinfo.value.code == "CD7_EMPTY_PROPERTY"

    def test_valid_property_constructs(self) -> None:
        """A non-empty property name constructs a 'defined' criterion.

        Raises:
            AssertionError: If the selector node deviates from the
                ``has_property(..., operator="is_set")`` contract.
        """
        criterion = CohortCriteria.property_is_set("email")
        assert criterion._selector_node is not None
        assert criterion._selector_node["value"] == "email"


class TestPropertyIsNotSetGuardVectors:
    """Recorded guard-failure cases for ``CohortCriteria.property_is_not_set``.

    Delegates to ``has_property`` (CD7 guard); the OUTER factory seam owns
    the vector once registered.
    """

    @pytest.mark.parametrize("property_name", ["", "   "])
    def test_empty_property_raises_coded_error(self, property_name: str) -> None:
        """An empty/whitespace property name raises CD7.

        Args:
            property_name: The violating property name.

        Raises:
            AssertionError: If the raise is missing or carries a
                different code.
        """
        with pytest.raises(ParamValidationError) as excinfo:
            CohortCriteria.property_is_not_set(property_name)
        assert excinfo.value.code == "CD7_EMPTY_PROPERTY"

    def test_valid_property_constructs(self) -> None:
        """A non-empty property name constructs a 'not defined' criterion.

        Raises:
            AssertionError: If the selector node deviates from the
                ``has_property(..., operator="is_not_set")`` contract.
        """
        criterion = CohortCriteria.property_is_not_set("phone")
        assert criterion._selector_node is not None
        assert criterion._selector_node["value"] == "phone"
