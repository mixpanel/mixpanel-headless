"""Replay target construction for wire vectors (design D7).

Rebuilds the library object a vector's ``call.api`` prefix names —
``api_client.*`` / ``workspace.*`` / ``replays.*`` / ``oauth_flow.*`` /
``region_probe.*`` / ``pagination.*`` / ``wirestub.*`` — around a
:class:`conformance.runner.transport.VectorTransport`, reconstructing the
recorded :class:`Session` from ``call.session`` (design D5.1: the session
the vector carries is what the replay client must be built from).
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import httpx
from pydantic import SecretStr

from conformance.runner.transport import VectorTransport


class TargetConstructionError(Exception):
    """Raised when a vector's replay target cannot be built.

    Always a vector/runner bug (unknown api prefix, missing session,
    unknown account type) — surfaces as a vector failure with a precise
    reason, never a silent skip.
    """


_DEFAULT_SESSION_VALUES = {
    "type": "service_account",
    "region": "us",
    "project_id": "12345",
    "account_name": "conformance_replay",
    "username": "replay_user",
    "secret": "replay_secret",
}
"""Synthetic session for builder-kind replays: builder vectors carry no
session (design D5.1 — no client makes requests), but ``Workspace`` facade
construction requires one. Requests can never escape: builder replays bind
an EMPTY :class:`VectorTransport`, so any accidental network attempt fails
the vector loudly."""


def build_session(encoded: Mapping[str, Any]) -> Any:
    """Reconstruct a :class:`Session` from a vector ``call.session`` object.

    Inverse of ``conformance.record.emit._encode_session`` (design D5.1):
    credentials are the recorded fake test values, custom headers rebuild
    the D5.6 custom-header traffic, and ``workspace_id`` rebuilds the
    workspace ref.

    Args:
        encoded: The vector's session object (schema ``$defs.session``).

    Returns:
        The reconstructed ``Session``.

    Raises:
        TargetConstructionError: On an unknown account type or a session
            shape the recorder could not have produced.
    """
    from mixpanel_headless._internal.auth.account import (
        OAuthBrowserAccount,
        OAuthTokenAccount,
        ServiceAccount,
    )
    from mixpanel_headless._internal.auth.session import (
        Project,
        Session,
        WorkspaceRef,
    )

    account_type = str(encoded.get("type"))
    name = str(encoded.get("account_name", "conformance_replay"))
    region = str(encoded.get("region", "us"))
    default_project = encoded.get("default_project")
    account: Any
    if account_type == "service_account":
        account = ServiceAccount(
            name=name,
            region=region,
            username=str(encoded["username"]),
            secret=SecretStr(str(encoded["secret"])),
            default_project=(
                str(default_project) if default_project is not None else None
            ),
        )
    elif account_type == "oauth_token":
        if "token" not in encoded:
            raise TargetConstructionError(
                "oauth_token session without a token is unreplayable "
                "(the recorder adopts resolver-observed bearers, D5.2)"
            )
        account = OAuthTokenAccount(
            name=name,
            region=region,
            token=SecretStr(str(encoded["token"])),
            default_project=(
                str(default_project) if default_project is not None else None
            ),
        )
    elif account_type == "oauth_browser":
        account = OAuthBrowserAccount(
            name=name,
            region=region,
        )
    else:
        raise TargetConstructionError(f"unknown session type {account_type!r}")
    workspace = None
    workspace_id = encoded.get("workspace_id")
    if workspace_id is not None:
        workspace = WorkspaceRef(id=int(workspace_id))
    headers = {
        str(key): str(value)
        for key, value in dict(encoded.get("headers") or {}).items()
    }
    return Session(
        account=account,
        project=Project(id=str(encoded["project_id"])),
        workspace=workspace,
        headers=headers,
    )


class _StaticTokenResolver:
    """Token resolver returning the vector-recorded bearer (design D5.2).

    Injected for ``oauth_browser`` sessions whose bearer was adopted into
    ``call.session.token`` at record time; never touches ``~/.mp``.
    """

    def __init__(self, token: str) -> None:
        """Store the recorded bearer.

        Args:
            token: The bearer token from the vector session.
        """
        self._token = token

    def get_browser_token(self, name: str, region: str) -> str:
        """Return the recorded bearer for a browser account.

        Args:
            name: Account name (unused — one vector, one token).
            region: Region (unused).

        Returns:
            The recorded bearer.
        """
        del name, region
        return self._token

    def get_static_token(self, account: Any) -> str:
        """Return the recorded bearer for a static-token account.

        Args:
            account: The account (unused).

        Returns:
            The recorded bearer.
        """
        del account
        return self._token


class RecordingClientFactory:
    """Replay stand-in for the ``probe_region`` ``client_factory`` callback.

    The recorded factory was test infrastructure (its base URLs are
    environment, not library behavior), so replay injects a real factory
    whose clients route to the vector's :class:`VectorTransport`; the base
    URL for each built client comes from the NEXT unconsumed recorded
    interaction's ``scheme_host`` — the same environment the recording ran
    in. Calls are logged (positional args, like any callback stub) so
    ``expect.callback_calls.client_factory`` still diffs.

    Attributes:
        calls: One positional-argument list per invocation, in order.
    """

    def __init__(
        self,
        transport: VectorTransport,
        interactions: Sequence[Mapping[str, Any]],
    ) -> None:
        """Bind the factory to the vector transport and recording.

        Args:
            transport: The vector's replay transport.
            interactions: The vector's recorded interactions (for base-URL
                lookup).
        """
        self._transport = transport
        self._interactions = list(interactions)
        self.calls: list[list[Any]] = []

    def __call__(self, region: str) -> httpx.Client:
        """Build one probe client over the vector transport.

        Args:
            region: The region being probed (logged).

        Returns:
            A client whose traffic serves from the recording.
        """
        self.calls.append([region])
        base_url = "https://mixpanel.com"
        for index in self._transport.unconsumed_indexes():
            request = self._interactions[index].get("request")
            if isinstance(request, Mapping) and "scheme_host" in request:
                base_url = str(request["scheme_host"])
                break
        return httpx.Client(transport=self._transport, base_url=base_url)


def make_api_client(
    session_obj: Any,
    transport: VectorTransport,
    client_options: Mapping[str, Any] | None,
    browser_token: str | None = None,
) -> Any:
    """Construct the replay ``MixpanelAPIClient`` (design D7).

    Args:
        session_obj: The reconstructed ``Session``.
        transport: The vector's replay transport.
        client_options: Recorded non-default constructor kwargs
            (``max_retries`` — schema extension 12), or None.
        browser_token: The vector-recorded bearer for ``oauth_browser``
            sessions (``call.session.token``, adopted per D5.2); injected
            via a static resolver so replay never reads ``~/.mp``.

    Returns:
        The client bound to the vector transport.
    """
    from mixpanel_headless._internal.api_client import MixpanelAPIClient
    from mixpanel_headless._internal.auth.account import OAuthBrowserAccount

    kwargs: dict[str, Any] = {}
    if client_options and "max_retries" in client_options:
        kwargs["max_retries"] = int(client_options["max_retries"])
    if isinstance(session_obj.account, OAuthBrowserAccount):
        if browser_token is None:
            raise TargetConstructionError(
                "oauth_browser session without an adopted token is "
                "unreplayable (design D5.2)"
            )
        kwargs["token_resolver"] = _StaticTokenResolver(browser_token)
    return MixpanelAPIClient(session=session_obj, _transport=transport, **kwargs)


def oauth_flow_region(interactions: Sequence[Mapping[str, Any]]) -> str:
    """Derive the ``OAuthFlow`` region from the recorded interactions.

    The recorder does not capture the flow's constructor region; the OAuth
    base-URL table is a fixed three-entry map, so the first recorded
    ``scheme_host`` identifies it unambiguously (an off-table URL means a
    corpus bug and falls back to ``us``, where the path diff then fails
    precisely).

    Args:
        interactions: The vector's recorded interactions.

    Returns:
        ``"us"`` / ``"eu"`` / ``"in"``.
    """
    from mixpanel_headless._internal.auth.client_registration import (
        OAUTH_BASE_URLS,
    )

    hosts = {region: url.split("/oauth")[0] for region, url in OAUTH_BASE_URLS.items()}
    for interaction in interactions:
        request = interaction.get("request")
        if not isinstance(request, Mapping):
            continue
        scheme_host = request.get("scheme_host")
        for region, host in hosts.items():
            if scheme_host == host:
                return region
    return "us"


def make_oauth_flow(
    transport: VectorTransport, interactions: Sequence[Mapping[str, Any]]
) -> Any:
    """Construct the replay ``OAuthFlow`` (design D7).

    Storage points at a throwaway temp directory so replay can never touch
    ``~/.mp`` (the registered surface — ``refresh_tokens`` — does not
    persist, but the constructor default would resolve the real home).

    Args:
        transport: The vector's replay transport.
        interactions: The recorded interactions (region derivation).

    Returns:
        The flow bound to an ``httpx.Client`` over the vector transport.
    """
    from mixpanel_headless._internal.auth.flow import OAuthFlow
    from mixpanel_headless._internal.auth.storage import OAuthStorage

    region = oauth_flow_region(interactions)
    storage_dir = Path(tempfile.mkdtemp(prefix="mp-conformance-oauth-"))
    return OAuthFlow(
        region=region,
        storage=OAuthStorage(storage_dir=storage_dir),
        http_client=httpx.Client(transport=transport),
    )


def make_workspace(session_obj: Any, client: Any) -> Any:
    """Construct the replay ``Workspace`` facade (design D5.1).

    Args:
        session_obj: The FACADE session (``workspace_session`` when the
            vector carries one, else the client session).
        client: The injected ``MixpanelAPIClient``.

    Returns:
        The facade bound to the injected client.
    """
    from mixpanel_headless.workspace import Workspace

    return Workspace(session=session_obj, _api_client=client)


def make_replays_service(client: Any, transport: VectorTransport) -> Any:
    """Construct the replay ``ReplaysService`` (design D1.1 seam P4).

    Args:
        client: The replay ``MixpanelAPIClient`` (used only if the vector's
            call path re-signs — mock-dependent re-sign captures are
            excluded at record time, PR-6).
        transport: The vector transport (async CDN seam).

    Returns:
        The service with both seams bound to the vector transport.
    """
    from mixpanel_headless._internal.services.replays import ReplaysService

    return ReplaysService(client, _async_transport=transport)


def default_builder_session() -> Any:
    """Build the synthetic session for builder-kind facade replays.

    Returns:
        A ``Session`` from :data:`_DEFAULT_SESSION_VALUES`.
    """
    return build_session(_DEFAULT_SESSION_VALUES)


def make_wirestub_client(transport: VectorTransport) -> Any:
    """Construct the D13 wire-stub client over the vector transport.

    Args:
        transport: The vector's replay transport.

    Returns:
        The ``WireStubClient`` mirror stub.
    """
    from conformance.record.pycompat_ref import WireStubClient

    return WireStubClient(transport=transport)


def probe_region_callable(
    transport: VectorTransport,
    interactions: Sequence[Mapping[str, Any]],
    kwargs: dict[str, Any],
) -> tuple[Callable[..., Any], RecordingClientFactory]:
    """Prepare the ``probe_region`` call with the replay factory injected.

    Args:
        transport: The vector's replay transport.
        interactions: The recorded interactions.
        kwargs: The decoded ``call.input`` (mutated: ``client_factory``
            replaced with the recording replay factory).

    Returns:
        ``(probe_region, factory)`` — the callable and the injected
        factory whose call log diffs against ``callback_calls``.
    """
    from mixpanel_headless._internal.auth.region_probe import probe_region

    factory = RecordingClientFactory(transport, interactions)
    kwargs["client_factory"] = factory
    return probe_region, factory
