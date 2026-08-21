"""Unit tests for the B0-1 pythonCompat reference wrappers (P3-4 packet).

Covers the R11.3 parse-grammar wrappers (``python_int``/``python_float``),
the R11.3 enabling dependency ``python_strip``, and the R11.5/R11.6
codepoint wrappers (``sorted_strings``/``cp_length``/``cp_slice``) against
the CPython 3.14.6 probe results recorded in
``context/phase3/notes/B0-notes.md``. The authored ``compat.*`` vectors
freeze exactly these outputs; the TS port must match vector-for-vector.
"""

from __future__ import annotations

import pytest

from conformance.record.pycompat_ref import (
    cp_length,
    cp_slice,
    python_float,
    python_int,
    python_strip,
    sorted_strings,
)
from mixpanel_headless.exceptions import MixpanelHeadlessError


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("42", 42),
        ("007", 7),
        ("+42", 42),
        ("-42", -42),
        ("1_0", 10),
        ("00_0", 0),
        ("\t42\n", 42),
        ("  1_5  ", 15),
        ("\x8542\xa0", 42),
        (" 42　", 42),
        ("٤٢", 42),
        ("４２", 42),
        ("-๑๒๓", -123),
        ("\U0001d7d9\U0001d7da", 12),
        ("9007199254740991", 9007199254740991),
        ("-9007199254740991", -9007199254740991),
    ],
)
def test_python_int_matches_cpython(value: str, expected: int) -> None:
    """``python_int`` reproduces CPython ``int(str)`` inside the safe range.

    Args:
        value: Input literal.
        expected: CPython's ``int()`` result.

    Raises:
        AssertionError: If the wrapper deviates from CPython.
    """
    assert python_int(value) == expected == int(value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "+",
        "-",
        "+ 1",
        "5.5",
        ".5",
        "1e5",
        "0x5",
        "inf",
        "nan",
        "1__0",
        "_1",
        "1_",
        "+_1",
        "\x1c42\x1f",
        "﻿42",
        " 4 2 ",
        "²",
        "〇",
        "\U0001d4b3",
    ],
)
def test_python_int_rejects_with_coded_error(value: str) -> None:
    """``python_int`` maps CPython ``ValueError`` to the coded rig error.

    R5.5 excludes uncoded builtin raises from vectors (the recorder's
    ``_encode_error`` returns ``None`` for them), so the reference wrapper
    re-raises as ``MixpanelHeadlessError`` code ``PY_INT_INVALID_LITERAL``
    (B0-notes design decision 1).

    Args:
        value: An invalid literal per the CPython probes.

    Raises:
        AssertionError: If no error or the wrong code is raised.
    """
    with pytest.raises(ValueError):
        int(value)  # the CPython contract the code translates
    with pytest.raises(MixpanelHeadlessError) as excinfo:
        python_int(value)
    assert excinfo.value.code == "PY_INT_INVALID_LITERAL"


@pytest.mark.parametrize(
    "value",
    ["9007199254740992", "-9007199254740992", "123456789012345678901234567890"],
)
def test_python_int_rejects_beyond_two_pow_53(value: str) -> None:
    """Magnitudes beyond 2^53 - 1 raise the R4.5 policy code.

    CPython parses these fine (arbitrary precision); the wrapper mirrors
    the TS port's deliberate deviation (the canonicalizer 2^53 policy) so
    the two sides stay vector-comparable.

    Args:
        value: A literal whose magnitude exceeds the JS-safe bound.

    Raises:
        AssertionError: If no error or the wrong code is raised.
    """
    assert abs(int(value)) > 2**53 - 1  # CPython itself accepts it
    with pytest.raises(MixpanelHeadlessError) as excinfo:
        python_int(value)
    assert excinfo.value.code == "PY_INT_UNSAFE_INTEGER"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.5", 1.5),
        ("42", 42.0),
        (".5", 0.5),
        ("5.", 5.0),
        ("1.e1", 10.0),
        ("1_0.5", 10.5),
        ("1_0e1_0", 1e11),
        ("+1e+5", 1e5),
        ("١٢.٣٤", 12.34),
        ("١e٢", 100.0),
        ("\t1.5\n", 1.5),
        ("\xa01.5　", 1.5),
        ("-0.0", -0.0),
    ],
)
def test_python_float_matches_cpython_finite(value: str, expected: float) -> None:
    """``python_float`` reproduces CPython ``float(str)`` for finite results.

    Args:
        value: Input literal.
        expected: CPython's ``float()`` result.

    Raises:
        AssertionError: If the wrapper deviates from CPython.
    """
    result = python_float(value)
    assert isinstance(result, float)
    assert result == expected == float(value)
    assert repr(result) == repr(expected)  # locks the -0.0 sign


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("inf", "inf"),
        ("Infinity", "inf"),
        ("-iNf", "-inf"),
        ("+INFINITY", "inf"),
        (" inf ", "inf"),
        ("nan", "nan"),
        ("+nAn", "nan"),
        ("-nan", "nan"),
        ("1e400", "inf"),
        ("-1e400", "-inf"),
    ],
)
def test_python_float_non_finite_sentinels(value: str, expected: str) -> None:
    """Non-finite results return the ``repr`` sentinel string (D6 rule 5).

    Non-finite floats cannot ride vectors (codec + canonicalizer both
    reject), so the wrapper — and the TS binding, which mirrors it —
    renders them as ``"inf"``/``"-inf"``/``"nan"`` (B0-notes decision 2).

    Args:
        value: A literal parsing to a non-finite float.
        expected: The sentinel string (``repr`` of the CPython result).

    Raises:
        AssertionError: If the sentinel deviates.
    """
    assert python_float(value) == expected == repr(float(value))


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "+",
        ".",
        ".e1",
        "1e",
        "1e+",
        "abc",
        "0x5",
        "1__0",
        "1._5",
        "in",
        "nans",
        "\x1c1.5\x1f",
        "﻿1.5",
        "\U0001d4b3",
    ],
)
def test_python_float_rejects_with_coded_error(value: str) -> None:
    """``python_float`` maps CPython ``ValueError`` to the coded rig error.

    Args:
        value: An invalid literal per the CPython probes.

    Raises:
        AssertionError: If no error or the wrong code is raised.
    """
    with pytest.raises(ValueError):
        float(value)  # the CPython contract the code translates
    with pytest.raises(MixpanelHeadlessError) as excinfo:
        python_float(value)
    assert excinfo.value.code == "PY_FLOAT_INVALID_LITERAL"


@pytest.mark.parametrize(
    "value",
    [
        " \t hi \n ",
        "\x1chi\x1f",
        "﻿hi﻿",
        "\xa0hi　",
        "",
        " \t　\x1c",
        "  a \t b  ",
        " \U0001d4b3 ",
        "\U0001d4b3",
    ],
)
def test_python_strip_matches_str_strip(value: str) -> None:
    """``python_strip`` is exactly ``str.strip()`` (whitespace-table lock).

    Args:
        value: Input string.

    Raises:
        AssertionError: If the wrapper deviates from CPython.
    """
    assert python_strip(value) == value.strip()


def test_sorted_strings_is_codepoint_order() -> None:
    """``sorted_strings`` reproduces Python ``sorted()`` (R11.5).

    The halfwidth-ideographic-full-stop vs emoji pair is the UTF-16
    unit-order inversion the TS port must NOT reproduce.

    Raises:
        AssertionError: If ordering or non-mutation deviates.
    """
    values = ["\U0001f600", "｡", "abc", "ab", "", "ab"]
    result = sorted_strings(values)
    assert result == ["", "ab", "ab", "abc", "｡", "\U0001f600"]
    assert result == sorted(values)
    assert values[0] == "\U0001f600"  # input not mutated


@pytest.mark.parametrize(
    "value",
    ["", "abc", "\U0001d4b3", "a\U0001d4b3b\U0001f600"],
)
def test_cp_length_counts_codepoints(value: str) -> None:
    """``cp_length`` is Python ``len(str)`` — codepoints, not UTF-16 units.

    Args:
        value: Input string.

    Raises:
        AssertionError: If the count deviates.
    """
    assert cp_length(value) == len(value)


@pytest.mark.parametrize(
    ("value", "start", "end"),
    [
        ("hello", None, None),
        ("hello", 2, None),
        ("hello", None, 2),
        ("abc", 0, 500),
        ("abc", -500, 500),
        ("abc", 5, 9),
        ("hello", -3, None),
        ("hello", 0, -1),
        ("a\U0001d4b3b", 0, 2),
        ("a\U0001d4b3b", -2, None),
        ("hello", 3, 2),
        ("", 0, 10),
    ],
)
def test_cp_slice_matches_python_slicing(
    value: str, start: int | None, end: int | None
) -> None:
    """``cp_slice`` is exactly ``value[start:end]`` (R11.6).

    Args:
        value: Input string.
        start: Slice start (``None`` for the open end).
        end: Slice end (``None`` for the open end).

    Raises:
        AssertionError: If the slice deviates from CPython.
    """
    assert cp_slice(value, start=start, end=end) == value[start:end]
