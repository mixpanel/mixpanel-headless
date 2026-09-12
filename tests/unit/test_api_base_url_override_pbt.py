"""Property-based tests for the ``MP_API_BASE_URL`` host override.

Properties tested:
- For any well-formed base URL and any run of trailing slashes, every API
  family resolves to ``base.rstrip("/") + prefix`` — no double slashes, no
  region influence, and ``_build_url`` appends the normalised path after it.
- With the override unset, ``_endpoints_for`` returns the live table object
  and the live table is never modified by resolving an override.
"""

from __future__ import annotations

import os
from unittest import mock

from hypothesis import given
from hypothesis import strategies as st

from mixpanel_headless._internal.api_client import (
    ENDPOINTS,
    MixpanelAPIClient,
    _endpoints_for,
)
from tests.conftest import make_session

_PREFIXES: dict[str, str] = {
    "query": "/api/query",
    "export": "/api/2.0",
    "engage": "/api/query/engage",
    "app": "/api/app",
}
"""The documented per-family path prefixes."""

_LIVE_SNAPSHOT: dict[str, dict[str, str]] = {
    region: dict(table) for region, table in ENDPOINTS.items()
}
"""Deep copy of the live table at import, to detect any later mutation."""

# =============================================================================
# Strategies
# =============================================================================

regions = st.sampled_from(["us", "eu", "in"])
api_types = st.sampled_from(sorted(_PREFIXES))

_label = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789", min_size=1, max_size=8
)
_hosts = st.one_of(
    st.just("127.0.0.1"),
    st.just("localhost"),
    st.lists(_label, min_size=1, max_size=3).map(".".join),
)
_ports = st.one_of(st.none(), st.integers(min_value=1, max_value=65535))
_path_segments = st.lists(
    st.text(alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_", min_size=1, max_size=8),
    max_size=3,
)


@st.composite
def base_urls(draw: st.DrawFn) -> str:
    """Generate a normalised base URL with no trailing slash.

    Args:
        draw: Hypothesis draw function.

    Returns:
        A URL like ``http://host:port/seg/seg`` with no trailing slash.
    """
    scheme = draw(st.sampled_from(["http", "https"]))
    host = draw(_hosts)
    port = draw(_ports)
    segments = draw(_path_segments)
    netloc = host if port is None else f"{host}:{port}"
    path = "".join(f"/{seg}" for seg in segments)
    return f"{scheme}://{netloc}{path}"


slash_runs = st.integers(min_value=0, max_value=5).map(lambda n: "/" * n)


# =============================================================================
# Properties
# =============================================================================


@given(base=base_urls(), slashes=slash_runs, region=regions)
def test_override_table_is_base_plus_prefix(
    base: str, slashes: str, region: str
) -> None:
    """Every family URL is exactly ``base + prefix`` regardless of slashes/region.

    Args:
        base: Normalised base URL (no trailing slash).
        slashes: Trailing slash run appended to the env value.
        region: Region passed to the resolver (must not matter).
    """
    with mock.patch.dict(os.environ, {"MP_API_BASE_URL": f"{base}{slashes}"}):
        table = _endpoints_for(region)
    assert table == {family: f"{base}{prefix}" for family, prefix in _PREFIXES.items()}
    for url in table.values():
        assert url.startswith(base)
        assert "//" not in url[len(base) :]


@given(base=base_urls(), slashes=slash_runs, region=regions, api_type=api_types)
def test_build_url_appends_normalised_path(
    base: str, slashes: str, region: str, api_type: str
) -> None:
    """``_build_url`` yields ``base + prefix + "/" + path`` (leading slash added once).

    Args:
        base: Normalised base URL.
        slashes: Trailing slash run appended to the env value.
        region: Session region (must not matter).
        api_type: API family.
    """
    client = MixpanelAPIClient(session=make_session(region=region))
    try:
        with mock.patch.dict(os.environ, {"MP_API_BASE_URL": f"{base}{slashes}"}):
            with_slash = client._build_url(api_type, "/segmentation")
            without_slash = client._build_url(api_type, "segmentation")
    finally:
        client.close()
    expected = f"{base}{_PREFIXES[api_type]}/segmentation"
    assert with_slash == expected
    assert without_slash == expected


@given(region=regions)
def test_unset_returns_live_table_untouched(region: str) -> None:
    """With the vars absent the resolver hands back the pristine live table.

    Args:
        region: Region under test.
    """
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("MP_API_BASE_URL", "MP_APP_BASE_URL")
    }
    with mock.patch.dict(os.environ, env, clear=True):
        table = _endpoints_for(region)
    assert table is ENDPOINTS[region]
    assert table == _LIVE_SNAPSHOT[region]


@given(base=base_urls(), slashes=slash_runs, region=regions)
def test_resolving_override_never_mutates_live_table(
    base: str, slashes: str, region: str
) -> None:
    """Resolving under the override leaves ``ENDPOINTS`` equal to its import-time copy.

    Args:
        base: Normalised base URL.
        slashes: Trailing slash run appended to the env value.
        region: Region under test.
    """
    with mock.patch.dict(os.environ, {"MP_API_BASE_URL": f"{base}{slashes}"}):
        _endpoints_for(region)
    with mock.patch.dict(os.environ, {"MP_APP_BASE_URL": f"{base}{slashes}"}):
        _endpoints_for(region)
    assert ENDPOINTS == _LIVE_SNAPSHOT
