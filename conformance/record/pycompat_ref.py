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

from typing import Any

import httpx


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
