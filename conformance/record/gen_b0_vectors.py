"""Generate the B0-1 authored compat vectors (P3-4 packet B0-1).

Emits ``conformance/vectors/authored/compat/pythoncompat-b0.jsonl``: the
authored vector lines for the six pythonCompat completion wrappers
(``python_int``/``python_float``/``python_strip``/``sorted_strings``/
``cp_length``/``cp_slice``). Every ``expect`` value is COMPUTED by calling
the reference wrapper (CPython is the oracle) rather than hand-typed, so
the frozen outputs cannot drift from the pinned interpreter.

Usage (stamp = the semantic support-branch commit the vectors are
authored against, per the e73f303/c4bc884 precedent):
    uv run python -m conformance.record.gen_b0_vectors --commit <sha>

Deterministic: re-running with the same stamp reproduces the file
byte-for-byte (D8 discipline).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from conformance.record import pycompat_ref

OUT_PATH = (
    Path(__file__).resolve().parents[1]
    / "vectors"
    / "authored"
    / "compat"
    / "pythoncompat-b0.jsonl"
)

SOURCE_FILE = "conformance/vectors/authored/compat/pythoncompat-b0.jsonl"

_INT_OK: tuple[tuple[str, str], ...] = (
    ("basic-42", "42"),
    ("leading-zeros", "007"),
    ("plus-sign", "+42"),
    ("minus-sign", "-42"),
    ("underscore", "1_0"),
    ("ascii-ws-underscore", "  1_5  "),
    ("tab-newline-wrap", "\t42\n"),
    ("nel-nbsp-wrap", "\x8542\xa0"),
    ("arabic-indic-nd", "٤٢"),
    ("nonbmp-nd-digits", "\U0001d7d9\U0001d7da"),
    ("max-safe", "9007199254740991"),
    ("min-safe", "-9007199254740991"),
)

_INT_ERR: tuple[tuple[str, str], ...] = (
    ("empty-string", ""),
    ("float-form", "5.5"),
    ("double-underscore", "1__0"),
    ("fs-us-separators", "\x1c42\x1f"),
    ("nonbmp-nondigit", "\U0001d4b3"),
    ("hex-prefix", "0x5"),
    ("inf-spelling", "inf"),
    ("unsafe-magnitude", "9007199254740992"),
)

_FLOAT_OK: tuple[tuple[str, str], ...] = (
    ("fractional", "1.5"),
    ("integral-token", "42"),
    ("integral-float-token", "18.0"),
    ("leading-dot", ".5"),
    ("dangling-dot", "5."),
    ("dot-exponent", "1.e1"),
    ("underscores", "1_0.5"),
    ("signed-exponent", "+1e+5"),
    ("exponent-underscores", "1_0e1_0"),
    ("negative-zero", "-0.0"),
    ("arabic-indic-nd", "١٢.٣٤"),
    ("ws-wrap", "\t1.5\n"),
    ("inf-lower", "inf"),
    ("inf-mixed-case-signed", "-iNf"),
    ("nan-signed", "+nAn"),
    ("overflow-to-inf", "1e400"),
)

_FLOAT_ERR: tuple[tuple[str, str], ...] = (
    ("empty-string", ""),
    ("bare-dot", "."),
    ("underscore-after-dot", "1._5"),
    ("bom-prefix", "﻿1.5"),
)

_STRIP: tuple[tuple[str, str], ...] = (
    ("ascii-ws", " \t hi \n "),
    ("fs-us-separators", "\x1chi\x1f"),
    ("bom-kept", "﻿hi﻿"),
    ("nbsp-ideographic", "\xa0hi　"),
    ("empty-string", ""),
    ("all-whitespace", " \t　\x1c"),
    ("interior-kept", "  a \t b  "),
    ("nonbmp-payload", " \U0001d4b3 "),
)

_SORTED: tuple[tuple[str, list[str]], ...] = (
    ("utf16-inversion-pair", ["\U0001f600", "｡"]),
    ("prefixes-first", ["abc", "ab", "a", ""]),
    ("stable-duplicates", ["b", "a", "b", "a"]),
    ("empty-list", []),
    ("single-empty-string", [""]),
    ("bmp-vs-nonbmp", ["\U0001d4b3", "\U0001d4b2", "z"]),
    ("numeric-strings-lexicographic", ["10", "9", "1"]),
    ("python-literal-spellings", ["True", "None", "18.0", "1.5"]),
)

_CP_LENGTH: tuple[tuple[str, str], ...] = (
    ("empty-string", ""),
    ("ascii", "abc"),
    ("single-nonbmp", "\U0001d4b3"),
    ("mixed-nonbmp", "a\U0001d4b3b\U0001f600"),
    ("true-spelling", "True"),
)

_CP_SLICE: tuple[tuple[str, str, int | None, int | None, bool], ...] = (
    # (slug, value, start, end, use_null_spelling_for_open_ends)
    ("open-both", "hello", None, None, False),
    ("open-end-null-spelling", "hello", 2, None, True),
    ("open-start-null-spelling", "hello", None, 2, True),
    ("clamp-end", "abc", 0, 500, False),
    ("clamp-both", "abc", -500, 500, False),
    ("start-past-end-of-string", "abc", 5, 9, False),
    ("negative-end", "hello", 0, -1, False),
    ("nonbmp-cut-point", "a\U0001d4b3b", 0, 2, False),
    ("negative-start-nonbmp", "a\U0001d4b3b", -2, None, False),
    ("start-after-end", "hello", 3, 2, False),
    ("empty-string", "", 0, 10, False),
)


def _vector(api: str, slug: str, body: dict[str, Any]) -> dict[str, Any]:
    """Assemble one authored vector line in canonical key order.

    Args:
        api: The dotted registry api name.
        slug: The id tail (``authored-<slug>``).
        body: ``{"input": ..., "expect": ...}``.

    Returns:
        The full vector object.
    """
    return {
        "call": {"api": api, "input": body["input"]},
        "capability": "compat",
        "expect": body["expect"],
        "id": f"compat/{api}/authored-{slug}",
        "kind": "builder",
        "origin": "authored",
        "schema_version": "1.0",
    }


def _int_error_expect(value: str) -> dict[str, Any]:
    """Compute the expected error object by invoking the wrapper.

    Args:
        value: The invalid literal.

    Returns:
        The ``expect`` object with the raised class + code.
    """
    try:
        pycompat_ref.python_int(value)
    except Exception as exc:  # noqa: BLE001 - freezing the raised contract
        return {
            "error": {"class": type(exc).__name__, "code": exc.code}  # type: ignore[attr-defined]
        }
    raise AssertionError(f"python_int unexpectedly accepted {value!r}")


def _float_error_expect(value: str) -> dict[str, Any]:
    """Compute the expected error object by invoking the wrapper.

    Args:
        value: The invalid literal.

    Returns:
        The ``expect`` object with the raised class + code.
    """
    try:
        pycompat_ref.python_float(value)
    except Exception as exc:  # noqa: BLE001 - freezing the raised contract
        return {
            "error": {"class": type(exc).__name__, "code": exc.code}  # type: ignore[attr-defined]
        }
    raise AssertionError(f"python_float unexpectedly accepted {value!r}")


def build_vectors() -> list[dict[str, Any]]:
    """Build every B0-1 authored vector, outputs computed via the wrappers.

    Returns:
        The vector objects in emission order.
    """
    vectors: list[dict[str, Any]] = []
    for slug, value in _INT_OK:
        vectors.append(
            _vector(
                "compat.python_int",
                slug,
                {
                    "input": {"value": value},
                    "expect": {"output": pycompat_ref.python_int(value)},
                },
            )
        )
    for slug, value in _INT_ERR:
        vectors.append(
            _vector(
                "compat.python_int",
                slug,
                {"input": {"value": value}, "expect": _int_error_expect(value)},
            )
        )
    for slug, value in _FLOAT_OK:
        vectors.append(
            _vector(
                "compat.python_float",
                slug,
                {
                    "input": {"value": value},
                    "expect": {"output": pycompat_ref.python_float(value)},
                },
            )
        )
    for slug, value in _FLOAT_ERR:
        vectors.append(
            _vector(
                "compat.python_float",
                slug,
                {"input": {"value": value}, "expect": _float_error_expect(value)},
            )
        )
    for slug, value in _STRIP:
        vectors.append(
            _vector(
                "compat.python_strip",
                slug,
                {
                    "input": {"value": value},
                    "expect": {"output": pycompat_ref.python_strip(value)},
                },
            )
        )
    for slug, values in _SORTED:
        vectors.append(
            _vector(
                "compat.sorted_strings",
                slug,
                {
                    "input": {"values": values},
                    "expect": {"output": pycompat_ref.sorted_strings(values)},
                },
            )
        )
    for slug, value in _CP_LENGTH:
        vectors.append(
            _vector(
                "compat.cp_length",
                slug,
                {
                    "input": {"value": value},
                    "expect": {"output": pycompat_ref.cp_length(value)},
                },
            )
        )
    for slug, value, start, end, null_spelling in _CP_SLICE:
        input_obj: dict[str, Any] = {"value": value}
        if start is not None or null_spelling:
            input_obj["start"] = start
        if end is not None or null_spelling:
            input_obj["end"] = end
        vectors.append(
            _vector(
                "compat.cp_slice",
                slug,
                {
                    "input": input_obj,
                    "expect": {
                        "output": pycompat_ref.cp_slice(value, start=start, end=end)
                    },
                },
            )
        )
    return vectors


def main() -> int:
    """Write the bundle.

    Returns:
        Process exit code (0 on success).
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--commit",
        required=True,
        help="$bundle source_commit stamp — injected externally (D3).",
    )
    args = parser.parse_args()
    vectors = build_vectors()
    header = {
        "$bundle": {
            "count": len(vectors),
            "source_commit": args.commit,
            "source_file": SOURCE_FILE,
        }
    }
    lines = [json.dumps(header, ensure_ascii=True, sort_keys=True)]
    lines.extend(
        json.dumps(vector, ensure_ascii=True, sort_keys=True) for vector in vectors
    )
    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT_PATH} ({len(vectors)} vectors)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
