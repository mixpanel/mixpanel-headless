# Internal Contract: MemoryBackend & path helpers

**Feature**: 045-memory-storage-foundation | **Date**: 2026-08-18

These are `_internal` contracts (not part of the public `mixpanel_headless` API surface in this slice). They define the seam the sibling issues build on. Signatures are the intended shape; exact typing is finalized in code under `mypy --strict`.

## `MemoryBackend` protocol

```python
class MemoryBackend(Protocol):
    """Content-agnostic byte store addressed by relative key within one scope."""

    def read(self, key: str) -> bytes | None:
        """Return the bytes stored at ``key``, or ``None`` if absent.

        Raises:
            ValueError: ``key`` is empty, absolute, or escapes the scope.
            CredentialPathError: the note path is a symlink.
            OSError: other I/O failure (EACCES, etc.).
        """

    def write(self, key: str, data: bytes) -> None:
        """Atomically store ``data`` at ``key``, creating the scope dir on demand.

        Raises:
            ValueError: ``key`` is empty, absolute, or escapes the scope.
            OSError: I/O failure.
        """

    def list(self, prefix: str = "") -> list[str]:
        """Return relative keys under ``prefix`` (sorted). Empty/absent scope -> []."""

    def delete(self, key: str) -> None:
        """Remove ``key`` if present; no-op if absent.

        Raises:
            ValueError: ``key`` is empty, absolute, or escapes the scope.
        """
```

### Behavioral contract (tested)

| Operation | Precondition | Postcondition |
|-----------|--------------|---------------|
| `read(k)` | k valid, note absent | returns `None`, no raise |
| `read(k)` | k valid, note present, regular file | returns exact bytes written |
| `read(k)` | note path is a symlink | raises `CredentialPathError` |
| `read(k)` | note file mode is `0o644` (looser than credential rule) | returns bytes (NO owner-only rejection) |
| `write(k, d)` | scope dir absent | dir created (restrictive umask), file written `0o600` |
| `write(k, d)` | process killed mid-write | prior file intact OR new file present, never partial |
| `list()` | scope absent | returns `[]` |
| `list(pfx)` | notes present | returns sorted keys under `pfx` |
| `delete(k)` | note absent | no-op success |
| any | k empty / absolute / `..`-escaping | raises `ValueError` before touching disk |

## `LocalFilesystemBackend`

```python
class LocalFilesystemBackend:
    """MemoryBackend over a single on-disk scope directory."""

    def __init__(self, scope_dir: Path) -> None: ...
```

- Bound to one resolved scope directory (`user_memory_dir(...)` or `project_memory_dir(...)`).
- `write` uses `io_utils.atomic_write_bytes(path, data, mode=0o600)` and ensures `scope_dir` exists via the `os.umask(0o077)` + `mkdir(parents=True, exist_ok=True)` pattern.
- `read` calls `reject_if_symlink(path)`, returns `None` when the path does not exist, else reads the file bytes directly (no credential-grade invariants).

## Pure path helpers (`paths.py`)

```python
def validate_account_name(name: str) -> str: ...        # ^[a-zA-Z0-9_-]{1,64}$
def validate_project_id(project_id: str) -> str: ...    # ^\d{1,20}$, returned opaque
def user_memory_dir(name: str, *, root: Path) -> Path: ...       # <root>/accounts/{name}/memory
def project_memory_dir(project_id: str, *, root: Path) -> Path: ... # <root>/projects/{id}/memory
def resolve_key(scope_dir: Path, key: str) -> Path: ...  # in-tree join; raises ValueError on escape
```

- All pure and I/O-free (`root` injected). These are the Hypothesis PBT + mutmut targets.
- Invariants to property-test:
  - Valid `(name|id, key)` → resolved path is always under the scope dir.
  - Any `key` containing an escaping `..` sequence → `ValueError`.
  - Any invalid id/name → `ValueError`, regardless of key.
  - `resolve_key(scope_dir, k)` is deterministic and idempotent for fixed inputs.
