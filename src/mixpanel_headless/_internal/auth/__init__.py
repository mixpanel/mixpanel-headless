"""OAuth 2.0 PKCE authentication module.

Implements the OAuth 2.0 Authorization Code + PKCE flow for Mixpanel,
including Dynamic Client Registration (RFC 7591), token management, and
secure local storage.

Components:
- PkceChallenge: PKCE verifier/challenge generation (RFC 7636)
- OAuthTokens: Immutable token model with expiry tracking
- OAuthClientInfo: Cached DCR client registration info
- OAuthStorage: Secure JSON file storage for tokens and client info
- OAuthFlow: Flow orchestrator (login, token exchange, refresh)
- CallbackResult: Authorization callback result model
- ensure_client_registered: Dynamic Client Registration helper
"""

from mixpanel_headless._internal.auth.account import (
    Account,
    AccountType,
    OAuthBrowserAccount,
    OAuthTokenAccount,
    Region,
    ServiceAccount,
    TokenResolver,
)
from mixpanel_headless._internal.auth.callback_server import CallbackResult
from mixpanel_headless._internal.auth.client_registration import (
    ensure_client_registered,
)
from mixpanel_headless._internal.auth.flow import OAuthFlow
from mixpanel_headless._internal.auth.pkce import PkceChallenge
from mixpanel_headless._internal.auth.session import (
    ActiveSession,
    Project,
    Session,
    WorkspaceRef,
)
from mixpanel_headless._internal.auth.storage import (
    OAuthStorage,
    account_dir,
    ensure_account_dir,
)
from mixpanel_headless._internal.auth.token import OAuthClientInfo, OAuthTokens
from mixpanel_headless._internal.auth.token_resolver import OnDiskTokenResolver

__all__ = [
    "Account",
    "AccountType",
    "ActiveSession",
    "CallbackResult",
    "OAuthBrowserAccount",
    "OAuthClientInfo",
    "OAuthFlow",
    "OAuthStorage",
    "OAuthTokenAccount",
    "OAuthTokens",
    "OnDiskTokenResolver",
    "PkceChallenge",
    "Project",
    "Region",
    "ServiceAccount",
    "Session",
    "TokenResolver",
    "WorkspaceRef",
    "account_dir",
    "ensure_account_dir",
    "ensure_client_registered",
]
