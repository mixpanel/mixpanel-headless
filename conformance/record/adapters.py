"""Invocable-shape adapters for registry entries (design D4.2 items 5 and 9).

Two D4.2 builder contracts have no directly-registrable callable of the
right shape, so the registry targets these thin adapters instead:

- ``replay_labels.selector_label_fn`` is a FACTORY returning a closure; the
  design records it as ``(attr, action) -> label`` ("the CLOSURE result is
  invoked, factory value is not a vector" — D4.2 item 5).
  :func:`selector_label_fn` flattens factory + closure into one call.
- ``api_client._iter_jsonl_lines`` consumes a live streaming
  ``httpx.Response``; its chunk-boundary contract enters the corpus via
  hand-authored chunk vectors (design D2/D4.2 item 9).
  :func:`iter_jsonl_lines` rebuilds a stream-backed response from raw
  chunks (preserving boundaries) and returns the reassembled lines.

Both adapters delegate to the real library code — they add shape, never
behavior.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx

from mixpanel_headless.types import UserAction


class _ChunkStream(httpx.SyncByteStream):
    """One-shot byte stream yielding explicit chunks (boundary-preserving)."""

    def __init__(self, chunks: list[bytes]) -> None:
        """Store the chunk list to yield.

        Args:
            chunks: Body chunks in yield order — boundaries are the
                contract under test (design D2).
        """
        self._chunks = chunks

    def __iter__(self) -> Iterator[bytes]:
        """Yield each configured chunk exactly once.

        Returns:
            Iterator over the configured chunks, unchanged.
        """
        return iter(self._chunks)


def selector_label_fn(attr: str, action: UserAction) -> str:
    """Flattened ``replay_labels.selector_label_fn`` (design D4.2 item 5).

    Builds the closure for ``attr`` and immediately applies it to
    ``action`` so the recordable contract is ``(attr, action) -> label``.

    Args:
        attr: The HTML attribute the label function prefers
            (e.g. ``"data-testid"``).
        action: The replay user action to label.

    Returns:
        The label the closure produces for ``action``.

    Example:
        ```python
        label = selector_label_fn("data-testid", action)
        # 'Clicked [data-testid="submit-button"]'
        ```
    """
    from mixpanel_headless import replay_labels

    return replay_labels.selector_label_fn(attr)(action)


def iter_jsonl_lines(
    chunks: list[bytes], headers: dict[str, str] | None = None
) -> list[str]:
    """Run ``_iter_jsonl_lines`` over explicit chunks (design D4.2 item 9).

    Rebuilds a stream-backed ``httpx.Response`` whose byte stream yields
    ``chunks`` verbatim (so lines split across chunk boundaries — and gzip
    bodies when ``headers`` says ``content-encoding: gzip`` — exercise the
    real buffering logic), then collects the reassembled lines.

    Args:
        chunks: Raw body chunks in arrival order (``$type: bytes`` tagged
            in vector inputs).
        headers: Response headers; drive httpx's decoding
            (``content-encoding``) exactly as a live response would.

    Returns:
        The complete JSONL lines the library yields, in order.

    Raises:
        httpx.DecodingError: If ``headers`` promises an encoding the chunk
            bytes do not satisfy.

    Example:
        ```python
        lines = iter_jsonl_lines([b'{"a": 1}\\n{"b"', b': 2}\\n'])
        # ['{"a": 1}', '{"b": 2}']
        ```
    """
    from mixpanel_headless._internal.api_client import _iter_jsonl_lines

    response = httpx.Response(200, headers=headers, stream=_ChunkStream(list(chunks)))
    return list(_iter_jsonl_lines(response))
