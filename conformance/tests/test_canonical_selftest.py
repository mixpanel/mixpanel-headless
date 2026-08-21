"""Selftest-driven tests for the D6 canonicalizer (design D6/D12, PR-4).

Iterates every case in ``conformance/schema/canonical-selftest.json`` — the
cross-language contract artifact the TS canonicalizer (TS-3) must also pass
— through :mod:`conformance.runner.canonical`, plus structural guards that
the selftest file itself keeps the coverage the design mandates (float-
exponent table, ``-0.0``, segfilter operand positive/negative cases, error
stripping at known levels only, null-vs-absent, ignored-unlisted-header,
unordered-group sorting, bytes encoding, lone-surrogate rejection).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from conformance.runner.canonical import (
    CanonicalizationError,
    canonicalize,
    canonicalize_error,
    canonicalize_interactions,
    headers_match,
)

SELFTEST_PATH = (
    Path(__file__).resolve().parents[1] / "schema" / "canonical-selftest.json"
)
"""Location of the committed selftest artifact (design D6)."""

_SPECIAL_FLOATS = {
    "nan": math.nan,
    "infinity": math.inf,
    "negative_infinity": -math.inf,
}
"""Non-finite doubles constructible only via the ``special`` case field."""

_MANDATED_CASE_IDS = frozenset(
    {
        # Float-exponent conversion table (D6 rule 5) + -0.0.
        "float-window-1e16",
        "float-window-1e-5",
        "float-exp-1e21",
        "float-exp-1e-7",
        "float-negative-zero",
        # Rule-3 raw-token discipline.
        "float-int-tokens-not-unified",
        "int-beyond-2-53",
        # Segfilter operand normalization, positive AND negative (rule 4).
        "segfilter-operand-scalar-normalized",
        "segfilter-operand-array-normalized",
        "segfilter-operand-string-type-untouched",
        "segfilter-no-selected-type-untouched",
        "bookmark-filtervalue-not-normalized",
        "engage-selector-not-normalized",
        # Error stripping at known levels only (rule 6).
        "error-strip-top-level",
        "error-strip-errors-elements",
        "error-details-contain-message-survives",
        # Null-vs-absent (rule 1).
        "null-vs-absent-null-kept",
        "null-vs-absent-empty-object",
        # Ignored-unlisted-header (D5.6 / rules 7-8).
        "headers-ignore-unlisted",
        # Unordered-group sorting (rule 9).
        "interactions-unordered-group-sorted",
        # Bytes encoding (rule 11).
        "bytes-tagged-ordinary-object",
        # Lone-surrogate rejection (rule 2).
        "reject-lone-surrogate-string",
    }
)
"""Case ids the PR-4 done-criteria name explicitly — deletion must fail CI."""


def _load_selftest() -> dict[str, Any]:
    """Load the committed selftest document from disk.

    Returns:
        The parsed selftest JSON document.

    Raises:
        FileNotFoundError: If the selftest artifact is missing.
        json.JSONDecodeError: If the file is not valid JSON.
    """
    with SELFTEST_PATH.open(encoding="utf-8") as fh:
        document: dict[str, Any] = json.load(fh)
    return document


def _cases() -> list[dict[str, Any]]:
    """Return the selftest case list.

    Returns:
        Every case object from the committed selftest file.
    """
    cases: list[dict[str, Any]] = _load_selftest()["cases"]
    return cases


def _case_ids(cases: list[dict[str, Any]]) -> list[str]:
    """Extract the ``id`` of every case for pytest parametrization.

    Args:
        cases: The selftest case objects.

    Returns:
        The case ids in file order.
    """
    return [str(case["id"]) for case in cases]


_ALL_CASES = _cases()
"""Cases loaded once at collection time (the file is a committed artifact)."""


@pytest.mark.parametrize("case", _ALL_CASES, ids=_case_ids(_ALL_CASES))
def test_selftest_case(case: dict[str, Any]) -> None:
    """Every selftest case holds against the Python canonicalizer (D6).

    Dispatches on the case ``kind`` exactly as the selftest ``$comment``
    prescribes for both language harnesses: ``value``/``error``/
    ``interactions`` compare canonical strings, ``headers`` compares the
    match verdict, ``reject`` expects :exc:`CanonicalizationError`.

    Args:
        case: One case object from ``canonical-selftest.json``.

    Raises:
        AssertionError: If the canonical output, match verdict, or
            rejection behavior deviates from the pinned expectation.
    """
    kind = case["kind"]
    if kind == "value":
        assert canonicalize(json.loads(case["input_json"])) == case["canonical"]
    elif kind == "error":
        assert canonicalize_error(json.loads(case["input_json"])) == case["canonical"]
    elif kind == "interactions":
        actual = canonicalize_interactions(json.loads(case["input_json"]))
        assert actual == case["canonical"]
    elif kind == "headers":
        verdict = headers_match(case["headers_contain"], case["actual_headers"])
        assert verdict is case["matches"]
    elif kind == "reject":
        special = case.get("special")
        value = (
            _SPECIAL_FLOATS[special]
            if special is not None
            else json.loads(case["input_json"])
        )
        with pytest.raises(CanonicalizationError):
            canonicalize(value)
    else:  # pragma: no cover - guards against malformed selftest edits
        pytest.fail(f"unknown selftest case kind {kind!r}")


def test_selftest_case_ids_unique() -> None:
    """Case ids are unique so both harnesses report unambiguously.

    Raises:
        AssertionError: If two cases share an id.
    """
    ids = _case_ids(_ALL_CASES)
    assert len(ids) == len(set(ids))


def test_selftest_meets_design_size() -> None:
    """The selftest carries the ~40-case coverage the design mandates (D6).

    Raises:
        AssertionError: If the case count drops below 40.
    """
    assert len(_ALL_CASES) >= 40


def test_selftest_contains_mandated_cases() -> None:
    """Every done-criteria case id from design PR-4 is present.

    Guards the selftest file against accidental deletion of the coverage
    the design names explicitly (float-exponent table, ``-0.0``, segfilter
    positive/negative, error stripping, null-vs-absent, unlisted headers,
    unordered groups, bytes, lone surrogates).

    Raises:
        AssertionError: If any mandated case id is missing.
    """
    present = set(_case_ids(_ALL_CASES))
    missing = _MANDATED_CASE_IDS - present
    assert not missing, f"selftest lost mandated cases: {sorted(missing)}"


def test_selftest_rejects_survive_double_check() -> None:
    """Reject-kind cases stay rejected under :func:`canonicalize_error` too.

    A malformed error object carrying a lone surrogate or non-finite float
    must not slip through the rule-6 stripping path either.

    Raises:
        AssertionError: If a reject input canonicalizes via the error path.
    """
    with pytest.raises(CanonicalizationError):
        canonicalize_error({"class": "E", "details_contain": {"bad": math.nan}})
    with pytest.raises(CanonicalizationError):
        canonicalize_error({"class": "\ud800"})
