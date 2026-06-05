"""Activity labels for the rrweb action stream (044-session-replay, US2/T057).

A label is the grouping key for the path / click / transition
aggregations on :class:`ReplayBundle`. Stable labels are the precondition
for any cross-session analysis: two ``click on button "Sign in"`` events
from different replays must produce the same label string, or the
downstream aggregations fragment.

This module ships three policies:

- :func:`default_label_fn` — the canonical ``"{action}:{tag}@{url}"``
  shape. URL normalization strips query strings and replaces numeric path
  segments with ``:id`` so ``/users/12345/profile`` and
  ``/users/67890/profile`` collapse into a single activity.
- :func:`selector_label_fn` — factory for projects with stable
  ``data-testid`` (or equivalent) attributes; falls back to the default
  when the attribute is absent.
- :func:`url_normalizer` — exposed as a standalone helper for callers
  who want to apply the same normalization outside the label-fn path.

These helpers are part of the public API. Import them from the top-level
package (``from mixpanel_headless import default_label_fn``) or from this
module directly; do not reach into ``mixpanel_headless._internal``.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from mixpanel_headless.types import UserAction

# Numeric path segments — IDs, version numbers, year/month/day pieces — are
# replaced with ``:id`` so URLs collapse across users / instances. Hex IDs
# (UUIDs, short SHAs) also count as IDs; pure-text segments survive.
_NUMERIC_OR_HEX = re.compile(r"^([0-9]+|[0-9a-f]{8,}|[0-9a-fA-F\-]{8,})$")


def url_normalizer(url: str) -> str:
    """Normalize a URL into a path template suitable for label aggregation.

    Strips the query string and replaces numeric / hex path segments with
    ``:id``. The host portion is preserved when present (otherwise the
    function treats the input as a bare path).

    Args:
        url: A URL, absolute or relative.

    Returns:
        The normalized path template. Example:
        ``/users/12345/profile?ref=x`` → ``/users/:id/profile``.

    Example:
        ```python
        url_normalizer("/users/12345/profile?ref=x")
        # '/users/:id/profile'
        url_normalizer("https://app.example.com/orders/abc12345-de00")
        # 'https://app.example.com/orders/:id'
        ```
    """
    if not url:
        return url
    # Split host from path. Naive splitter — anything before the first
    # single slash after a possible scheme is the host.
    host_prefix = ""
    rest = url
    if "://" in url:
        scheme, after = url.split("://", 1)
        if "/" in after:
            host, path = after.split("/", 1)
            host_prefix = f"{scheme}://{host}"
            rest = "/" + path
        else:
            return f"{scheme}://{after}"
    # Drop the query string.
    if "?" in rest:
        rest = rest.split("?", 1)[0]
    # Walk path segments and replace numeric / hex ones.
    parts = rest.split("/")
    normalized = [
        ":id" if part and _NUMERIC_OR_HEX.match(part) else part for part in parts
    ]
    return host_prefix + "/".join(normalized)


def default_label_fn(action: UserAction) -> str:
    """Canonical activity label: ``"{action}:{tag}@{normalized_url}"``.

    ``tag`` comes from ``action.target_desc`` (the analyzer's best
    description of the element — e.g. ``'button "Sign in"'``). The URL
    is normalized through :func:`url_normalizer` so analogous actions on
    parameterized pages aggregate cleanly.

    Args:
        action: A :class:`UserAction` from a replay's analyzer output.

    Returns:
        The activity label string.

    Example:
        ```python
        action = UserAction(timestamp=1, action="click",
                            target_node_id=42, target_desc='button "Sign in"',
                            url="/users/12345/profile?ref=x", metadata={})
        default_label_fn(action)
        # 'click:button "Sign in"@/users/:id/profile'
        ```
    """
    tag = action.target_desc or "(unknown)"
    url = url_normalizer(action.url) if action.url else "(no-url)"
    return f"{action.action}:{tag}@{url}"


def selector_label_fn(attr: str = "data-testid") -> Callable[[UserAction], str]:
    """Build a label-fn that prefers a stable selector attribute when present.

    For instrumented apps, ``data-testid`` (or your project's equivalent)
    is the most stable activity identifier — it survives DOM refactors,
    locale changes, and CSS tweaks. The returned label-fn looks for the
    requested attribute in ``action.metadata`` and uses it as the label
    body when present; otherwise it falls back to :func:`default_label_fn`.

    Args:
        attr: The metadata key to consult. Default ``"data-testid"``.

    Returns:
        A callable ``(UserAction) -> str`` suitable as a ``label_fn`` override
        for :meth:`ReplayBundle.find_pattern`.

    Example:
        ```python
        label_fn = selector_label_fn("data-testid")
        bundle.find_pattern(["click:button@/", ...], label_fn=label_fn)
        ```
    """

    def _label(action: UserAction) -> str:
        """Use the configured selector attribute when present; fall back otherwise."""
        candidate = action.metadata.get(attr) if action.metadata else None
        if candidate:
            url = url_normalizer(action.url) if action.url else "(no-url)"
            return f"{action.action}:{candidate}@{url}"
        return default_label_fn(action)

    return _label
