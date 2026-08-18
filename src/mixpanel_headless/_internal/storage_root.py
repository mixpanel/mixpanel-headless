"""Shared call-time resolver for the mixpanel_headless on-disk storage root.

Every on-disk artifact mixpanel_headless writes — per-account credential
directories, OAuth tokens, the ``/me`` cache, and (as of the Headless
Memory work) the user- and project-scoped memory trees — lives under a
single root. That root is resolved *at every call* rather than captured at
import time, so test isolation via ``$HOME`` / ``$MP_OAUTH_STORAGE_DIR``
monkeypatching takes effect. A module-level constant frozen at import would
silently leak the developer's real ``~/.mp/`` into hermetic tests.

The auth layer historically owned this logic as ``auth.storage._storage_root``;
it now delegates here so both auth and memory share one source of truth
without memory reaching into the auth module's internals.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["storage_root"]


def storage_root() -> Path:
    """Return the root directory under which mixpanel_headless writes state.

    Resolved on every call so ``$MP_OAUTH_STORAGE_DIR`` (and ``$HOME`` for
    tests) is honored at call time, not import time.

    Despite its historical name, ``MP_OAUTH_STORAGE_DIR`` controls EVERY
    on-disk artifact mixpanel_headless writes (per-account dirs, OAuth
    tokens, ``/me`` cache, memory trees), not just the OAuth subtree. The
    name is preserved as a backwards-compatible env var only.

    Returns:
        ``$MP_OAUTH_STORAGE_DIR`` if set and non-empty, else ``$HOME/.mp``.
    """
    env_dir = os.environ.get("MP_OAUTH_STORAGE_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".mp"
