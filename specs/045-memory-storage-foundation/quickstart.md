# Quickstart: Memory Storage Foundation

**Feature**: 045-memory-storage-foundation | **Date**: 2026-08-18

Internal-only in this slice — there is no public API or CLI yet (that is AIE-608). This shows how a sibling feature or a test exercises the substrate.

## Resolve a scope directory and store a note

```python
from mixpanel_headless._internal.storage_root import storage_root
from mixpanel_headless._internal.memory.paths import (
    user_memory_dir,
    project_memory_dir,
)
from mixpanel_headless._internal.memory.backend import LocalFilesystemBackend

root = storage_root()  # $MP_OAUTH_STORAGE_DIR or ~/.mp, resolved now

# User-scoped memory for account "personal"
user_backend = LocalFilesystemBackend(user_memory_dir("personal", root=root))
user_backend.write("notes.md", b"# Preferences\n- prefers concise output\n")

# Project-scoped memory for project 3713224
proj_backend = LocalFilesystemBackend(project_memory_dir("3713224", root=root))
proj_backend.write("notes.md", b"# Project context\n- flagship events: Login, Purchase\n")

# The two "notes.md" are independent
assert user_backend.read("notes.md") != proj_backend.read("notes.md")

# Absent key -> None, listing, idempotent delete
assert user_backend.read("missing.md") is None
assert user_backend.list() == ["notes.md"]
user_backend.delete("missing.md")  # no-op, no raise
```

## Hermetic test pattern

```python
def test_memory_is_hermetic(tmp_path, monkeypatch):
    monkeypatch.setenv("MP_OAUTH_STORAGE_DIR", str(tmp_path))
    from mixpanel_headless._internal.storage_root import storage_root
    from mixpanel_headless._internal.memory.paths import project_memory_dir
    from mixpanel_headless._internal.memory.backend import LocalFilesystemBackend

    backend = LocalFilesystemBackend(project_memory_dir("42", root=storage_root()))
    backend.write("a.md", b"hello")

    assert (tmp_path / "projects" / "42" / "memory" / "a.md").read_bytes() == b"hello"
    # Nothing written under the real home directory.
```

## Rejections (safety)

```python
from mixpanel_headless._internal.memory.paths import validate_project_id, resolve_key
import pytest

validate_project_id("3713224")              # ok -> "3713224"
with pytest.raises(ValueError):
    validate_project_id("12ab")             # non-numeric
with pytest.raises(ValueError):
    validate_project_id("../etc")           # traversal attempt

with pytest.raises(ValueError):
    resolve_key(scope_dir, "../../secrets") # escapes the scope tree
```

## Verify the DoD locally

```bash
just test -k memory          # unit + integration for this slice
just test-pbt                # Hypothesis property tests (includes memory paths)
just typecheck               # mypy --strict
just check                   # full gate (lint + fmt + typecheck + cov + build)
just mutate-check            # mutmut >= 80% on new pure modules
```
