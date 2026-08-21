"""Normative canonicalization algorithm shared by both runners (design D6).

This module is the Python implementation of the D6 canonicalization spec;
``conformance-runner/src/canonical.ts`` in the TS repo implements the same
algorithm, and behavioral parity between the two is locked by the shared
selftest artifact ``conformance/schema/canonical-selftest.json`` (executed
here by ``conformance/tests/test_canonical_selftest.py`` and on the TS side
by a vitest suite — design D6/D12/TS-3).

Public surface:
    - :func:`canonicalize` — JSON-like value → canonical UTF-8 JSON string
      (D6 rules 1-5, 10, 11; includes the rule-4 segfilter operand-position
      numeric-string normalization, applied structurally).
    - :func:`canonicalize_error` — ``expect.error``-shaped object → canonical
      string with ``message``/``suggestion``/``fix`` dropped at KNOWN error
      levels only (D6 rule 6).
    - :func:`canonicalize_interactions` — interaction list → canonical string
      after the rule-9 unordered-group sort (same sort as
      ``conformance.record.emit.sort_unordered_groups``).
    - :func:`headers_match` — ``headers_contain`` subset/pattern comparison
      (D6 rules 7-8, D5.2/D5.6).
    - :func:`normalize_numeric_string` — the rule-4 numeric-string
      normalizer, exposed for direct testing.
    - :exc:`CanonicalizationError` — raised for values that are illegal in
      vectors (``NaN``/``Infinity``, lone surrogates, non-JSON types).

Comparison between two canonicalized values is plain string equality of the
two canonical forms (D6 closing rule).
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

_SURROGATE_RE = re.compile("[\ud800-\udfff]")
"""Matches any lone surrogate code point (D6 rule 2 — illegal in vectors).

Python ``str`` stores code points, so ANY surrogate in a ``str`` is unpaired
by construction; a well-formed astral character is a single non-surrogate
code point.
"""

_STRIPPED_ERROR_KEYS = frozenset({"message", "suggestion", "fix"})
"""Advisory keys dropped from error objects before diffing (D6 rule 6, R5.4)."""


class CanonicalizationError(Exception):
    """A value cannot be canonicalized under the D6 rules.

    Raised for ``NaN``/``Infinity`` floats (D6 rule 5), strings or object
    keys containing lone surrogates (D6 rule 2), non-string object keys,
    and values outside the JSON-like type universe (D6 preamble).
    """


# ---------------------------------------------------------------------------
# Rule 5 — float rendering (Python repr → ECMAScript Number::toString form)
# ---------------------------------------------------------------------------


def _js_form_from_repr_exponent(text: str) -> str:
    """Re-render a Python exponent-form ``repr(float)`` per ECMAScript rules.

    Implements the ECMAScript ``Number::toString`` digit/exponent layout
    (ECMA-262 §6.1.6.1.20) over the shortest-round-trip digits Python's
    ``repr`` already computed. Both languages agree on the digits for every
    finite double; only the plain-vs-exponent threshold and the exponent
    spelling differ (D6 rule 5 "exponent-threshold window"):

    - Python uses exponent form for ``|x| >= 1e16`` or ``|x| < 1e-4``; JS
      only for ``|x| >= 1e21`` or ``|x| < 1e-6``.
    - Python zero-pads exponents to two digits (``1e-07``); JS does not
      (``1e-7``).

    Args:
        text: A Python ``repr(float)`` string containing ``e`` (e.g.
            ``"1.5e+16"``, ``"1e-07"``).

    Returns:
        The ECMAScript ``String(x)`` rendering (e.g.
        ``"15000000000000000"``, ``"1e-7"``).
    """
    mantissa, _, exponent_text = text.partition("e")
    negative = mantissa.startswith("-")
    if negative:
        mantissa = mantissa[1:]
    digits = mantissa.replace(".", "")
    # ECMAScript variables: s = digits, k = len(digits), n = decimal point
    # position such that value == 0.s * 10**n; Python's repr exponent is
    # relative to the FIRST digit, so n = exponent + 1.
    k = len(digits)
    n = int(exponent_text) + 1
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        exponent = n - 1
        sign = "+" if exponent >= 0 else "-"
        head = digits if k == 1 else digits[0] + "." + digits[1:]
        body = head + "e" + sign + str(abs(exponent))
    return ("-" if negative else "") + body


def _render_float(value: float) -> str:
    """Render a float in the D6 rule-5 canonical form.

    Shortest-round-trip decimal rendering: Python ``repr`` for plain forms
    (which preserves the ``.0`` integral marker and ``-0.0``'s sign — D6
    rules 3/5), with Python's exponent forms converted to the ECMAScript
    ``Number::toString`` spelling via :func:`_js_form_from_repr_exponent`
    (the conversion table is pinned in ``canonical-selftest.json``).

    Args:
        value: A finite Python float.

    Returns:
        The canonical decimal rendering (e.g. ``"18.0"``, ``"-0.0"``,
        ``"10000000000000000"``, ``"1e-7"``).

    Raises:
        CanonicalizationError: If ``value`` is ``NaN`` or ``Infinity``
            (illegal in vectors, D6 rule 5).
    """
    if not math.isfinite(value):
        raise CanonicalizationError(
            f"non-finite float {value!r} is illegal in vectors (D6 rule 5)"
        )
    text = repr(value)
    if "e" in text:
        return _js_form_from_repr_exponent(text)
    return text


# ---------------------------------------------------------------------------
# Rule 4 — segfilter operand-position numeric-string normalization
# ---------------------------------------------------------------------------


def normalize_numeric_string(text: str) -> str | None:
    """Normalize a numeric string per D6 rule 4 (R10.11).

    Parses ``text`` with the Python float grammar (``float(text)`` —
    including underscore grouping and surrounding whitespace, both pinned in
    the selftest so the TS side mirrors them), then renders via the rule-5
    shortest-round-trip form with int-collapse: a trailing ``.0`` is
    stripped (``"18.0"`` → ``"18"``, ``"18.50"`` → ``"18.5"``).

    Args:
        text: The candidate operand string.

    Returns:
        The normalized string, or ``None`` when ``text`` does not parse
        under the Python float grammar OR parses to a non-finite value
        (``"nan"``/``"inf"`` are parseable but never normalized — rendering
        them is illegal, D6 rule 5).
    """
    try:
        parsed = float(text)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    rendered = _render_float(parsed)
    if rendered.endswith(".0"):
        return rendered[: -len(".0")]
    return rendered


def _is_number_filter_entry(value: Mapping[str, Any]) -> bool:
    """Detect the segfilter number-filter structural pattern (D6 rule 4).

    Operand positions are identified STRUCTURALLY, never heuristically: an
    object with ``selected_property_type: "number"`` AND a ``filter`` member
    that is an object carrying an ``operand`` key (the
    ``_build_number_filter`` output shape, segfilter.py:158).

    Args:
        value: The mapping under inspection.

    Returns:
        True when ``value`` matches the number-filter entry pattern.
    """
    if value.get("selected_property_type") != "number":
        return False
    filter_member = value.get("filter")
    return isinstance(filter_member, Mapping) and "operand" in filter_member


def _normalize_operand(operand: object) -> object:
    """Apply rule-4 normalization to an operand value in position.

    String operands are normalized via :func:`normalize_numeric_string`
    (untouched when unparseable); list operands have each STRING element
    normalized. Non-string values pass through — rule 4 is numeric-STRING
    normalization only; numbers in operand position render per rule 3.

    Args:
        operand: The value found at ``filter.operand``.

    Returns:
        The normalized operand (never mutates the input).
    """
    if isinstance(operand, str):
        return normalize_numeric_string(operand) or operand
    if isinstance(operand, Sequence) and not isinstance(operand, (str, bytes)):
        return [
            (normalize_numeric_string(item) or item) if isinstance(item, str) else item
            for item in operand
        ]
    return operand


def _apply_segfilter_normalization(value: object) -> object:
    """Walk a JSON-like tree applying rule-4 operand normalization.

    Structural detection applies ANYWHERE in the tree (segfilter entries are
    nested inside larger section payloads); everything outside a detected
    operand position — bookmark ``filterValue``, engage selector strings,
    arbitrary numeric-looking strings — is left untouched (D6 rule 4
    explicit non-targets).

    Args:
        value: Any JSON-like value.

    Returns:
        A transformed copy (input never mutated); scalars pass through
        unchanged by identity.
    """
    if isinstance(value, Mapping):
        transformed: dict[Any, Any] = {
            key: _apply_segfilter_normalization(member) for key, member in value.items()
        }
        if _is_number_filter_entry(value):
            filter_member = dict(transformed["filter"])
            filter_member["operand"] = _normalize_operand(filter_member["operand"])
            transformed["filter"] = filter_member
        return transformed
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_apply_segfilter_normalization(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Rules 1-3, 5, 10, 11 — the canonical serializer
# ---------------------------------------------------------------------------


def _render_string(value: str) -> str:
    """Render a string as a canonical JSON string token (D6 rule 2).

    Verbatim content (no NFC/NFD normalization, no date re-parsing) in the
    minimal-escape form: short escapes for ``\\``/``"``/``\\b\\t\\n\\f\\r``,
    ``\\uXXXX`` only for the remaining control characters, everything else
    (including non-BMP characters) emitted as raw UTF-8. This is exactly the
    behavior shared by Python ``json.dumps(ensure_ascii=False)`` and
    ECMAScript ``JSON.stringify``.

    Args:
        value: The string to render.

    Returns:
        The quoted, escaped JSON token.

    Raises:
        CanonicalizationError: If ``value`` contains a lone surrogate
            (illegal in vectors, D6 rule 2 — UTF-8 cannot encode it and the
            D14 bridge protocol would die mid-session).
    """
    if _SURROGATE_RE.search(value):
        raise CanonicalizationError(
            f"lone surrogate in string {value!r} is illegal in vectors (D6 rule 2)"
        )
    return json.dumps(value, ensure_ascii=False)


def _write_canonical(value: object, out: list[str]) -> None:
    """Serialize one JSON-like value into ``out`` in canonical form.

    Implements D6 rules 1 (codepoint-sorted keys, absent ≠ null preserved),
    2 (strings), 3/5 (numbers — Python ``int``/``float`` mirror the raw JSON
    token distinction the loaders preserve), 10/11 (``$type``-tagged and
    bytes objects are ordinary objects). Output uses compact separators
    (``,`` and ``:``) matching ``JSON.stringify``.

    Args:
        value: The value to serialize.
        out: Accumulator receiving canonical string fragments.

    Raises:
        CanonicalizationError: For non-finite floats, lone surrogates,
            non-string object keys, or values outside the JSON type
            universe.
    """
    if value is None:
        out.append("null")
    elif isinstance(value, bool):
        out.append("true" if value else "false")
    elif isinstance(value, int):
        out.append(str(value))
    elif isinstance(value, float):
        out.append(_render_float(value))
    elif isinstance(value, str):
        out.append(_render_string(value))
    elif isinstance(value, Mapping):
        out.append("{")
        first = True
        for key in sorted(value.keys()):
            if not isinstance(key, str):
                raise CanonicalizationError(
                    f"non-string object key {key!r} is illegal in vectors (D6 rule 1)"
                )
            if not first:
                out.append(",")
            first = False
            out.append(_render_string(key))
            out.append(":")
            _write_canonical(value[key], out)
        out.append("}")
    elif isinstance(value, Sequence) and not isinstance(value, bytes):
        out.append("[")
        for index, item in enumerate(value):
            if index:
                out.append(",")
            _write_canonical(item, out)
        out.append("]")
    else:
        raise CanonicalizationError(
            f"value of type {type(value).__name__} is not JSON-like "
            "(bytes must arrive as $type-tagged objects, D6 rule 11)"
        )


def canonicalize(value: object) -> str:
    """Produce the canonical UTF-8 JSON string for a JSON-like value (D6).

    Applies the rule-4 segfilter operand-position numeric-string
    normalization structurally, then serializes under rules 1-3/5/10/11.
    Comparison between two values is string equality of their canonical
    forms.

    Args:
        value: Any JSON-like value (``None``, ``bool``, ``int``, ``float``,
            ``str``, mappings with string keys, sequences).

    Returns:
        The canonical JSON string (sorted keys, compact separators, minimal
        escapes, D6 number rendering).

    Raises:
        CanonicalizationError: If the value contains ``NaN``/``Infinity``,
            lone surrogates, non-string keys, or non-JSON types.

    Example:
        ```python
        canonicalize({"b": 18.0, "a": None})
        # '{"a":null,"b":18.0}'
        ```
    """
    out: list[str] = []
    _write_canonical(_apply_segfilter_normalization(value), out)
    return "".join(out)


# ---------------------------------------------------------------------------
# Rule 6 — error-object stripping at known levels only
# ---------------------------------------------------------------------------


def canonicalize_error(error: Mapping[str, Any]) -> str:
    """Canonicalize an ``expect.error``-shaped object (D6 rule 6, R5.4).

    Drops ``message``, ``suggestion``, and ``fix`` at KNOWN ERROR-OBJECT
    LEVELS ONLY — the top-level error object and each mapping element of
    ``errors[]`` — NEVER recursively inside ``details_contain`` values: a
    server response body embedded there may legitimately contain a
    ``message`` member that IS wire data (exceptions.py:154), and recursive
    deletion would mask a port that drops or fabricates it. The surviving
    keys (``class``, ``code``, ``path``, ``severity``, ``details_contain``
    contents, …) are compared strictly via the canonical form.

    Args:
        error: The error object (live-side serialized exception or the
            vector's ``expect.error``).

    Returns:
        The canonical JSON string of the stripped error object.

    Raises:
        CanonicalizationError: If the stripped object violates the
            canonicalization rules (non-finite floats, lone surrogates, …).

    Example:
        ```python
        canonicalize_error({"class": "E", "message": "boom", "code": "V7"})
        # '{"class":"E","code":"V7"}'
        ```
    """
    stripped: dict[str, Any] = {
        key: member for key, member in error.items() if key not in _STRIPPED_ERROR_KEYS
    }
    errors_member = stripped.get("errors")
    if isinstance(errors_member, Sequence) and not isinstance(
        errors_member, (str, bytes)
    ):
        stripped["errors"] = [
            {
                key: member
                for key, member in item.items()
                if key not in _STRIPPED_ERROR_KEYS
            }
            if isinstance(item, Mapping)
            else item
            for item in errors_member
        ]
    return canonicalize(stripped)


# ---------------------------------------------------------------------------
# Rule 9 — unordered-group sort for interaction sequences
# ---------------------------------------------------------------------------


def _interaction_sort_key(interaction: Mapping[str, Any]) -> str:
    """Compute the canonical ``(method, path, params)`` key (D2/D6 rule 9).

    This is the SAME key ``conformance.record.emit.interaction_sort_key``
    uses at write time (emit-side determinism, D2), so replay-side sorting
    can never disagree with the committed corpus ordering.

    Args:
        interaction: A serialized interaction object.

    Returns:
        Canonical JSON of the request's method/path/params triple.
    """
    request = interaction.get("request")
    request_map: Mapping[str, Any] = request if isinstance(request, Mapping) else {}
    return canonicalize(
        [request_map.get("method"), request_map.get("path"), request_map.get("params")]
    )


def canonicalize_interactions(interactions: Sequence[Mapping[str, Any]]) -> str:
    """Canonicalize an interaction list after the rule-9 group sort (D6.9).

    Interactions WITHOUT ``unordered_group`` keep their positions; members
    sharing a group id are reordered among the positions the group occupies,
    sorted (stably) by the canonical ``(method, path, params)`` key — the
    identical sort ``emit.py`` applies at write time, so comparing two
    sequences canonicalized here is order-insensitive exactly within groups.

    Args:
        interactions: Serialized interaction objects in observed order.

    Returns:
        The canonical JSON string of the group-sorted interaction list.

    Raises:
        CanonicalizationError: If any interaction violates the
            canonicalization rules.
    """
    result: list[Mapping[str, Any]] = list(interactions)
    groups: dict[int, list[int]] = {}
    for position, interaction in enumerate(interactions):
        group = interaction.get("unordered_group")
        if isinstance(group, int) and not isinstance(group, bool):
            groups.setdefault(group, []).append(position)
    for positions in groups.values():
        members = sorted(
            (interactions[position] for position in positions),
            key=_interaction_sort_key,
        )
        for position, member in zip(positions, members, strict=True):
            result[position] = member
    return canonicalize(result)


# ---------------------------------------------------------------------------
# Rules 7-8 — header comparison (subset, patterns, lowercase keys)
# ---------------------------------------------------------------------------


def headers_match(
    headers_contain: Mapping[str, Any],
    actual_headers: Mapping[str, str],
) -> bool:
    """Compare captured request headers against ``headers_contain`` (D6.7/8).

    Subset semantics per the vector schema: ONLY listed headers are
    compared; headers present in ``actual_headers`` but absent from
    ``headers_contain`` are ignored (the D5.6 allowlist means transport-
    added headers never appear in vectors, and a selftest case proves the
    ignore behavior on both sides). Keys are lowercased on both sides before
    comparison (rule 8); a ``{"pattern": ...}`` expected value (always used
    for ``authorization``, D5.2) is matched as a regex against the actual
    value (rule 7), and plain-string expected values compare by equality
    (case-sensitive values, case-insensitive keys).

    Args:
        headers_contain: The vector's expected-header object; values are
            strings or ``{"pattern": <regex>}`` objects.
        actual_headers: The headers captured from the replayed request.

    Returns:
        True when every listed header is present and matches.

    Raises:
        CanonicalizationError: If an expected value is neither a string nor
            a ``{"pattern": ...}`` object (malformed vector).
    """
    actual_lower = {key.lower(): member for key, member in actual_headers.items()}
    for key, expected in headers_contain.items():
        actual = actual_lower.get(key.lower())
        if actual is None:
            return False
        if isinstance(expected, str):
            if actual != expected:
                return False
        elif isinstance(expected, Mapping) and isinstance(expected.get("pattern"), str):
            if re.search(expected["pattern"], actual) is None:
                return False
        else:
            raise CanonicalizationError(
                f"malformed headers_contain value for {key!r}: {expected!r}"
            )
    return True
