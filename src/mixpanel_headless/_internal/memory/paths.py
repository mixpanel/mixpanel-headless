"""Pure path construction and validation for the Headless Memory trees.

This module is deliberately free of filesystem and network I/O: every
function is a deterministic transform over strings and :class:`~pathlib.Path`
values, with the storage ``root`` injected by the caller. That purity is what
makes the logic exhaustively property-testable (Hypothesis) and
mutation-testable (mutmut) in isolation, per the feature's Definition of Done.

Two scopes, kept physically separate:

* **user** — keyed on account name, at ``<root>/accounts/{name}/memory``.
* **project** — keyed on project id, at ``<root>/projects/{id}/memory``.

The account-name rule mirrors the one enforced on account directories in
:mod:`mixpanel_headless._internal.auth.storage`; the project-id rule is new
here. Both are defense-in-depth against path traversal via the scope key.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

__all__ = [
    "project_memory_dir",
    "resolve_key",
    "user_memory_dir",
    "validate_account_name",
    "validate_project_id",
]

# Mirrors ``auth.storage._ACCOUNT_NAME_PATTERN``. Duplicated (not imported)
# to keep the memory layer decoupled from auth internals; the account-name
# rule is stable, so drift risk is negligible.
_ACCOUNT_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

# Project ids are Mixpanel's globally-unique integers (real ids are 7-10
# digits). Bounded to 20 digits to reject pathological lengths while
# comfortably covering every real id. Treated as an opaque string — NOT
# int-normalized — so the on-disk directory matches the string form callers
# already thread through the ``/me`` layer.
_PROJECT_ID_PATTERN = re.compile(r"^\d{1,20}$")


def validate_account_name(name: str) -> str:
    """Return ``name`` unchanged if it is a valid account directory name.

    Args:
        name: Candidate account name.

    Returns:
        The validated ``name``, unchanged.

    Raises:
        ValueError: If ``name`` does not match ``^[a-zA-Z0-9_-]{1,64}$``.

    Example:
        ```python
        validate_account_name("personal")  # "personal"
        ```
    """
    if not _ACCOUNT_NAME_PATTERN.fullmatch(name):
        raise ValueError(
            f"Invalid account name: {name!r}. Must match `^[a-zA-Z0-9_-]{{1,64}}$`."
        )
    return name


def validate_project_id(project_id: str) -> str:
    """Return ``project_id`` unchanged if it is a valid project id.

    The id is treated as an opaque string: it is validated but never
    coerced to ``int``, preserving the exact string form (including any
    leading zeros) for the on-disk path.

    Args:
        project_id: Candidate project id.

    Returns:
        The validated ``project_id``, unchanged.

    Raises:
        ValueError: If ``project_id`` does not match ``^\\d{1,20}$``.

    Example:
        ```python
        validate_project_id("3713224")  # "3713224"
        ```
    """
    if not _PROJECT_ID_PATTERN.fullmatch(project_id):
        raise ValueError(
            f"Invalid project id: {project_id!r}. Must match `^\\d{{1,20}}$`."
        )
    return project_id


def user_memory_dir(name: str, *, root: Path) -> Path:
    """Return the user-scoped memory directory for account ``name``.

    Args:
        name: Account name (validated via :func:`validate_account_name`).
        root: The resolved storage root (injected to keep this pure).

    Returns:
        ``<root>/accounts/{name}/memory``. Not created by this call.

    Raises:
        ValueError: If ``name`` is invalid.
    """
    validate_account_name(name)
    return root / "accounts" / name / "memory"


def project_memory_dir(project_id: str, *, root: Path) -> Path:
    """Return the project-scoped memory directory for ``project_id``.

    Project memory is keyed on the id alone — independent of any account —
    so any account resolving the same project shares this tree.

    Args:
        project_id: Project id (validated via :func:`validate_project_id`).
        root: The resolved storage root (injected to keep this pure).

    Returns:
        ``<root>/projects/{project_id}/memory``. Not created by this call.

    Raises:
        ValueError: If ``project_id`` is invalid.
    """
    validate_project_id(project_id)
    return root / "projects" / project_id / "memory"


def resolve_key(scope_dir: Path, key: str) -> Path:
    """Resolve a relative note ``key`` to a path guaranteed inside ``scope_dir``.

    Pure and filesystem-free: normalizes lexically (``os.path.normpath``) and
    asserts the result is a strict descendant of ``scope_dir``. Rejects empty,
    absolute, and traversal (``..``-escaping) keys before any caller touches
    disk.

    Args:
        scope_dir: The scope's memory directory (from :func:`user_memory_dir`
            or :func:`project_memory_dir`).
        key: Relative key naming a note within the scope (e.g. ``notes.md``
            or ``context/goals.md``).

    Returns:
        The absolute-within-scope path for ``key``.

    Raises:
        ValueError: If ``key`` is empty, absolute, or escapes ``scope_dir``.

    Example:
        ```python
        resolve_key(scope, "notes.md")        # <scope>/notes.md
        resolve_key(scope, "../../secrets")   # raises ValueError
        ```
    """
    if not key or not key.strip():
        raise ValueError("Memory key must be a non-empty relative path.")
    if os.path.isabs(key):
        raise ValueError(f"Memory key must be relative, got absolute path: {key!r}.")

    scope_norm = Path(os.path.normpath(scope_dir))
    candidate = Path(os.path.normpath(scope_norm / key))
    if scope_norm not in candidate.parents:
        raise ValueError(
            f"Memory key {key!r} escapes its scope directory {str(scope_dir)!r}."
        )
    return candidate
