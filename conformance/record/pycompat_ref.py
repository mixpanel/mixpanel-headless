"""pythonCompat reference implementations + wire-stub mirror client (D13).

The hello-world gate module (design D13) replays hand-authored vectors
through BOTH runners. The Python side of those vectors executes against the
tiny reference implementations in this module:

- :func:`zfill` / :func:`python_str` / :func:`python_float_str` are thin
  wrappers over ``str.zfill``, ``str()``, and ``repr(float)`` — CPython
  itself is the oracle (design D13); the TS port's ``pythonCompat`` module
  (rulebook R11.1/R11.2/R11.4) must match them vector-for-vector.
- :class:`WireStubClient` is the Python mirror of the ~30-line TS stub
  client behind the ``wirestub.*`` gate vectors (design D13 wire-path gate
  slice): it issues HTTP calls exactly as its inputs direct — a test double
  for the replay pipeline (VectorTransport sequence/keyed serving, canned
  responses, ``body_stream`` chunk reassembly, ``transport_error``
  surfacing), NOT a port of any real module.

All entries here are registered in ``conformance/record/registry.py`` so the
Python corpus runner (design D7) executes the authored compat/wirestub
vectors like any other vector.
"""

from __future__ import annotations

import math
from typing import Any

import httpx

from mixpanel_headless.exceptions import MixpanelHeadlessError

_MAX_SAFE_INT = 2**53 - 1
"""The canonicalizer's exact-integer bound (rulebook R4.5)."""


def zfill(value: str, width: int) -> str:
    """Reference ``str.zfill`` — sign-aware zero padding (rulebook R11.4).

    Args:
        value: The string to pad (may carry a leading ``+``/``-`` sign).
        width: Target width; no-op when ``len(value) >= width``.

    Returns:
        ``value.zfill(width)`` — e.g. ``("-1", 3)`` yields ``"-01"``.

    Example:
        ```python
        zfill("-1", 3)
        # "-01"
        ```
    """
    return value.zfill(width)


def python_str(value: object) -> str:
    """Reference Python ``str()`` rendering (rulebook R11.1).

    Args:
        value: Any Python value; the contractual cases are ``True`` ->
            ``"True"``, ``None`` -> ``"None"``, and list/dict reprs.

    Returns:
        ``str(value)``.

    Example:
        ```python
        python_str(True)
        # "True"
        ```
    """
    return str(value)


def python_float_str(value: float) -> str:
    """Reference Python float rendering via ``repr`` (rulebook R11.2).

    Encodes the highest-frequency semantic traps of the port (design D13):
    integral floats keep their ``.0`` (``18.0`` -> ``"18.0"``), the
    exponent-threshold window uses Python's two-digit zero-padded exponent
    forms (``1e-05``), and negative zero is sign-preserving (``"-0.0"``).

    Args:
        value: A finite float (non-finite values are rejected by the codec
            layer before any vector can carry them — design D6 rule 5).

    Returns:
        ``repr(value)``.

    Example:
        ```python
        python_float_str(18.0)
        # "18.0"
        ```
    """
    return repr(value)


def python_int(value: str) -> int:
    """Reference CPython ``int(str)`` parse under the R4.5 safe bound (R11.3).

    CPython is the oracle for the grammar (underscores between digits,
    signed, Unicode digit/whitespace fold); two rig-contract translations
    apply on top (B0-notes design decision 1):

    - ``ValueError`` re-raises as :class:`MixpanelHeadlessError` code
      ``PY_INT_INVALID_LITERAL`` — uncoded builtin raises are R5.5-excluded
      from vectors, so the wrapper defines a coded, vector-comparable form.
    - Results beyond ±(2^53 − 1) raise code ``PY_INT_UNSAFE_INTEGER``: the
      TS port returns a JS ``number`` and deliberately rejects unsafe
      magnitudes (the canonicalizer 2^53 policy, R4.5); the wrapper mirrors
      that deviation so both sides stay vector-comparable.

    Args:
        value: The string to parse.

    Returns:
        ``int(value)`` when valid and within ±(2^53 − 1).

    Raises:
        MixpanelHeadlessError: Code ``PY_INT_INVALID_LITERAL`` for invalid
            literals; code ``PY_INT_UNSAFE_INTEGER`` beyond the bound.

    Example:
        ```python
        python_int("  1_5  ")
        # 15
        ```
    """
    try:
        result = int(value)
    except ValueError as exc:
        raise MixpanelHeadlessError(str(exc), code="PY_INT_INVALID_LITERAL") from exc
    if abs(result) > _MAX_SAFE_INT:
        raise MixpanelHeadlessError(
            f"int literal magnitude exceeds 2^53 - 1 (canonicalizer policy R4.5): "
            f"{value!r}",
            code="PY_INT_UNSAFE_INTEGER",
        )
    return result


def python_float(value: str) -> float | str:
    """Reference CPython ``float(str)`` parse (R11.3).

    CPython is the oracle for the grammar (decimal/exponent forms,
    dangling dots, underscores, signed case-insensitive inf/nan, Unicode
    digit/whitespace fold, silent overflow to infinity). Two rig-contract
    translations apply (B0-notes design decisions 1–2):

    - ``ValueError`` re-raises as :class:`MixpanelHeadlessError` code
      ``PY_FLOAT_INVALID_LITERAL`` (R5.5: uncoded raises cannot ride
      vectors).
    - Non-finite results return the ``repr`` sentinel string (``"inf"`` /
      ``"-inf"`` / ``"nan"``): non-finite floats are illegal in vector
      JSON (design D6 rule 5), and the TS binding mirrors the sentinel.
      The TS LIBRARY function itself returns the real non-finite double.

    Args:
        value: The string to parse.

    Returns:
        ``float(value)`` when finite; ``repr(float(value))`` otherwise.

    Raises:
        MixpanelHeadlessError: Code ``PY_FLOAT_INVALID_LITERAL`` for
            invalid literals.

    Example:
        ```python
        python_float("1_0.5")
        # 10.5
        python_float("-iNf")
        # "-inf"
        ```
    """
    try:
        result = float(value)
    except ValueError as exc:
        raise MixpanelHeadlessError(str(exc), code="PY_FLOAT_INVALID_LITERAL") from exc
    if math.isfinite(result):
        return result
    return repr(result)


def python_float_coerce(value: Any) -> float | str:
    """Reference CPython ``float(x)`` coercion ladder (R11.7).

    B6-gate addition (B5-notes.md outbound ledger item 5 /
    b5-review-resolution.md ASR-F6b): CPython itself is the oracle for
    the NON-string arms — ``float(True)`` -> ``1.0``, ``float(None)`` /
    ``float([])`` / ``float({})`` -> ``TypeError``, huge ints ->
    ``OverflowError`` — while the string arm is the R11.3
    :func:`python_float` grammar. The same rig-contract translations as
    :func:`python_float` apply (B0-notes design decisions 1-2):
    ``ValueError`` re-raises coded; non-finite results return the
    ``repr`` sentinel string. ``TypeError``/``OverflowError`` propagate
    BARE for class-name comparison (oracle-protocol.md §4.1, the
    ratified Discrepancy #8 in-annotation raise contract).

    Args:
        value: Any payload value (the ``Any``-typed interior domain the
            library site reads from ``steps_data``).

    Returns:
        ``float(value)`` when finite; ``repr(float(value))`` otherwise.

    Raises:
        MixpanelHeadlessError: Code ``PY_FLOAT_INVALID_LITERAL`` for
            invalid string literals.
        TypeError: Where CPython ``float(x)`` raises (None/list/dict).
        OverflowError: Where CPython raises (int too large for float).

    Example:
        ```python
        python_float_coerce(True)
        # 1.0
        python_float_coerce("inf")
        # "inf"
        ```
    """
    try:
        result = float(value)
    except ValueError as exc:
        raise MixpanelHeadlessError(str(exc), code="PY_FLOAT_INVALID_LITERAL") from exc
    if math.isfinite(result):
        return result
    return repr(result)


def python_strip(value: str) -> str:
    """Reference CPython ``str.strip()`` (R11.3 enabling dependency).

    CPython itself is the oracle: the strip set is the ``str.isspace()``
    table, which differs from the JS ``String.prototype.trim()`` set
    (Python strips U+001C..U+001F; JS trims U+FEFF).

    Args:
        value: The string to strip.

    Returns:
        ``value.strip()``.

    Example:
        ```python
        python_strip("\\x1chi\\x1f")
        # "hi"
        ```
    """
    return value.strip()


def sorted_strings(values: list[str]) -> list[str]:
    """Reference Python ``sorted()`` over strings (R11.5).

    Python compares strings by codepoint; JS default ``sort()`` compares
    UTF-16 units, inverting e.g. ``"｡"`` (U+FF61) vs ``"😀"`` (U+1F600).

    Args:
        values: The strings to sort (not mutated).

    Returns:
        ``sorted(values)`` — a new list.

    Example:
        ```python
        sorted_strings(["😀", "｡"])
        # ["｡", "😀"]
        ```
    """
    return sorted(values)


def cp_length(value: str) -> int:
    """Reference Python ``len(str)`` — codepoints, not UTF-16 units (R11.6).

    Args:
        value: The string to measure.

    Returns:
        ``len(value)``.

    Example:
        ```python
        cp_length("𝒳")
        # 1
        ```
    """
    return len(value)


def cp_slice(value: str, start: int | None = None, end: int | None = None) -> str:
    """Reference Python two-argument string slice (R11.6).

    Negative indices count from the end, out-of-range indices clamp, and
    a surrogate pair is never split (Python strings ARE codepoints) — the
    invariant behind every ``text[:N]`` truncation the port carries.

    Args:
        value: The string to slice.
        start: Inclusive start; ``None`` (or absent) for the open end.
        end: Exclusive end; ``None`` (or absent) for the open end.

    Returns:
        ``value[start:end]``.

    Example:
        ```python
        cp_slice("a𝒳b", start=0, end=2)
        # "a𝒳"
        ```
    """
    return value[start:end]


class WireStubClient:
    """Mirror wire-stub client for the D13 wire-path gate vectors.

    A deliberately trivial "client": every public method issues the HTTP
    traffic its arguments describe, verbatim, against the injected
    transport. The authored ``wirestub.*`` vectors replay through it to
    prove the wire replay pipeline (sequence + keyed unordered serving,
    header patterns, ``params_absent``, chunk reassembly, transport-error
    surfacing) before any real module is ported.

    Example:
        ```python
        client = WireStubClient(transport=httpx.MockTransport(handler))
        result = client.request("GET", "/ping")
        # {"status": 200, "body": {"ok": True}}
        client.close()
        ```
    """

    def __init__(
        self,
        *,
        transport: httpx.BaseTransport,
        base_url: str = "https://wirestub.invalid",
    ) -> None:
        """Bind the stub to a transport (the replay seam, design D7/D12).

        Args:
            transport: The transport serving canned responses
                (``VectorTransport`` at replay; ``httpx.MockTransport`` in
                unit tests).
            base_url: Base URL prepended to request paths.
        """
        self._client = httpx.Client(transport=transport, base_url=base_url)

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        json_body: Any | None = None,
    ) -> dict[str, Any]:
        """Issue one request exactly as directed and return a plain result.

        Transport failures propagate unchanged (``httpx.ConnectError``
        etc.) — the D13 ``transport_error`` gate vectors assert the raised
        class via ``expect.error``.

        Args:
            method: HTTP method (``GET``/``POST``/...).
            path: Request path relative to the base URL.
            params: Query params to send; omit entirely for the
                ``params_absent`` case.
            headers: Extra request headers to set verbatim.
            json_body: JSON request body, when given.

        Returns:
            ``{"status": <int>, "body": <parsed json | text>}`` — the body
            is JSON-parsed when the response ``content-type`` says JSON.

        Raises:
            httpx.HTTPError: Whatever the transport raises (surfaced, never
                wrapped — the mapping under test in real clients is
                exactly what this stub must NOT preempt).
        """
        response = self._client.request(
            method, path, params=params, headers=headers, json=json_body
        )
        content_type = response.headers.get("content-type", "")
        body: Any = response.json() if "json" in content_type.lower() else response.text
        return {"status": response.status_code, "body": body}

    def request_sequence(self, requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Issue several requests in the given order (multi-interaction gate).

        Within an ``unordered_group`` vector the input order may differ
        from the recorded order — keyed serving (design D2/D7) is exactly
        what this exercises.

        Args:
            requests: One :meth:`request` kwargs mapping per call, in issue
                order (``method``/``path`` plus the optional keys).

        Returns:
            One :meth:`request` result per issued request, in issue order.

        Raises:
            httpx.HTTPError: Propagated from the first failing request.
        """
        return [self.request(**request) for request in requests]

    def stream_chunks(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> list[str]:
        """Stream a response and return its raw chunks (chunk-reassembly gate).

        Uses ``iter_raw`` so the transport-provided chunk boundaries reach
        the caller verbatim — the ``body_stream`` -> stream rebuild in both
        runners must preserve them (design D2/D12).

        Args:
            method: HTTP method.
            path: Request path relative to the base URL.
            headers: Extra request headers to set verbatim.

        Returns:
            The response's raw chunks decoded as UTF-8, in arrival order.

        Raises:
            httpx.HTTPError: Whatever the transport raises.
            UnicodeDecodeError: If a chunk is not valid UTF-8 (gate vectors
                use text bodies only).
        """
        with self._client.stream(method, path, headers=headers) as response:
            return [chunk.decode("utf-8") for chunk in response.iter_raw()]

    def close(self) -> None:
        """Close the underlying HTTP client (lifecycle only, never a vector)."""
        self._client.close()
