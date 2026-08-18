# Data Model: Memory Storage Foundation & Two-Tree Scoping

**Feature**: 045-memory-storage-foundation | **Date**: 2026-08-18

This slice stores opaque bytes at addressed locations. There is no rich record schema (that is AIE-604). The "model" here is the addressing scheme and the backend abstraction.

## Entities

### MemoryScope (conceptual)

The two trees. Not necessarily a runtime enum in this slice, but the two addressable roots:

| Scope | Keyed on | On-disk location | Validator |
|-------|----------|------------------|-----------|
| user | account name | `<root>/accounts/{name}/memory/` | `^[a-zA-Z0-9_-]{1,64}$` (existing account-name rule) |
| project | project id | `<root>/projects/{id}/memory/` | `^\d{1,20}$` (new, opaque string) |

- **Relationships**: A user scope belongs to one account; a project scope belongs to one project id and is shared across any account resolving that id. No workspace scope in this slice (path layout does not preclude adding one later).
- **Validation**: The scope key (account name or project id) MUST pass its validator before any path is constructed or any directory is touched.

### MemoryKey (value)

A relative key naming a note within a scope (e.g. `notes.md`, `context/goals.md`).

- **Fields**: a relative path string.
- **Validation rules**:
  - MUST be relative (no leading `/`, no drive/absolute forms).
  - MUST NOT resolve outside its scope tree — reject any key that, after normalization, escapes the scope root (`..` traversal).
  - MUST NOT be empty.
- **State**: none; a key is a pure address.

### StorageRoot (value)

The call-time-resolved base directory under which both trees live.

- **Resolution**: `$MP_OAUTH_STORAGE_DIR` if set, else `~/.mp`. Resolved on every call (no import-time capture).
- **Relationships**: parent of both `accounts/` and `projects/`.

### MemoryBackend (abstraction)

The content-agnostic seam. See [contracts/memory_backend.md](./contracts/memory_backend.md) for the full contract.

- **Operations**: `read(key) -> bytes | None`, `write(key, data: bytes) -> None`, `list(prefix: str = "") -> list[str]`, `delete(key) -> None`.
- **Implementations (this slice)**: `LocalFilesystemBackend`, bound to a resolved scope directory.
- **Invariants**:
  - `read` of an absent key returns `None` (explicit absent), never raises for absence.
  - `write` is atomic w.r.t. interruption (via `atomic_write_bytes`).
  - `write` creates the scope directory on demand (restrictive umask).
  - `list` of an empty/absent scope returns `[]`.
  - `delete` of an absent key is a successful no-op.
  - Reads refuse a symlinked note path (via `reject_if_symlink`) but do not enforce owner-only mode or a size cap.

## Path construction (pure)

Deterministic, I/O-free functions in `paths.py`:

- `validate_account_name(name) -> str` — reuse/mirror the existing account-name pattern; raise `ValueError` on mismatch.
- `validate_project_id(project_id) -> str` — `^\d{1,20}$`; raise `ValueError` on mismatch; returns the id unchanged (opaque).
- `user_memory_dir(name, *, root) -> Path` — `<root>/accounts/{name}/memory`.
- `project_memory_dir(project_id, *, root) -> Path` — `<root>/projects/{id}/memory`.
- `resolve_key(scope_dir, key) -> Path` — join + normalize + assert the result stays within `scope_dir`; raise `ValueError` on escape.

These take `root` as a parameter so they remain pure; the backend supplies `storage_root()` at the boundary.

## Non-goals (owned elsewhere)

- Note content schema, front-matter, confidence labels (AIE-604).
- Byte-size limits on writes (AIE-605).
- Concurrency / optimistic locking beyond atomic replace (AIE-606).
- PII detection/redaction (AIE-607).
- User-facing verbs and their argument shapes (AIE-608).
- Remote/team backend implementation (AIE-620).
