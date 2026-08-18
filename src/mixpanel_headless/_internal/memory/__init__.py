"""Headless Memory storage substrate (internal).

The on-disk foundation for agent memory: two physically-separate trees —
user-scoped (keyed on account name) and project-scoped (keyed on project id) —
behind a content-agnostic :class:`~mixpanel_headless._internal.memory.backend.MemoryBackend`
seam. This package owns only storage and scoping; note format, size limits,
concurrency, PII handling, and the user-facing tool verbs are separate layers
built on top.

Do not import from here outside ``_internal``.
"""

from __future__ import annotations

from mixpanel_headless._internal.memory.backend import (
    LocalFilesystemBackend,
    MemoryBackend,
)
from mixpanel_headless._internal.memory.paths import (
    project_memory_dir,
    resolve_key,
    user_memory_dir,
    validate_account_name,
    validate_project_id,
)

__all__ = [
    "LocalFilesystemBackend",
    "MemoryBackend",
    "project_memory_dir",
    "resolve_key",
    "user_memory_dir",
    "validate_account_name",
    "validate_project_id",
]
