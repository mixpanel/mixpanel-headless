# Implementation Plan: Memory Storage Foundation & Two-Tree Scoping

**Branch**: `045-memory-storage-foundation` (built on `msiebert-agent-memory`) | **Date**: 2026-08-18 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/045-memory-storage-foundation/spec.md`
**Linear**: AIE-603

## Summary

Establish the on-disk substrate for Headless Memory: two physically-separate trees of plain-markdown notes — user-scoped (keyed on account name) and project-scoped (keyed on project id) — behind a thin, content-agnostic backend seam. The slice delivers pure path/validation logic (I/O-free, property- and mutation-tested), a `MemoryBackend` protocol with a single `LocalFilesystemBackend` implementation, and a call-time-resolved storage root shared with the existing auth layer. It reuses the codebase's atomic-write and symlink-refusal primitives but deliberately omits the credential-read owner-only-mode and 1 MiB-cap enforcement. Everything else in the memory milestone (format, size limits, locking, PII, tool verbs, team backend) is out of scope.

## Technical Context

**Language/Version**: Python 3.10+ (mypy --strict)
**Primary Dependencies**: Standard library only for this slice (`os`, `pathlib`, `re`, `stat`, `errno`). Reuses in-repo `_internal/io_utils.py`. No new third-party dependencies.
**Storage**: Plain files on the local filesystem under a resolved storage root (`$MP_OAUTH_STORAGE_DIR` → `~/.mp`).
**Testing**: pytest; Hypothesis (PBT on pure path/validator logic, `_pbt` suffix); mutmut (mutation testing on new pure modules).
**Target Platform**: POSIX (macOS/Linux) primary; Windows-tolerant via the existing `hasattr(os, ...)` fallbacks in `io_utils`.
**Project Type**: Single Python library (`mixpanel_headless`) with CLI wrapper — internal infrastructure layer only in this slice.
**Performance Goals**: Not a hot path; per-note read/write is a single filesystem operation. No specific latency target beyond "one syscall's worth."
**Constraints**: ≥90% coverage; mutmut ≥80% on new pure modules; mypy --strict; full Google-style docstrings; no `Any` without justification; pure path logic must be free of filesystem/network I/O.
**Scale/Scope**: Two new `_internal` modules plus one small shared-root extraction. Handful of notes per scope in practice; no pagination needed.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Library-First | ✅ PASS | Substrate lives in the Python library (`_internal/memory/`); no CLI in this slice. Tool verbs (AIE-608) will delegate to it. |
| II. Agent-Native Design | ✅ PASS | Pure functions and a backend protocol; no prompts, no interactivity. |
| III. Context Window Efficiency | ✅ PASS | Content-agnostic byte/text I/O; returns precise absent/present results, no dumps. |
| IV. Two Data Paths | ➖ N/A | Memory is neither a live query nor a DuckDB analysis path; orthogonal. |
| V. Explicit Over Implicit | ✅ PASS | Explicit validation before any disk touch; absent-read returns explicit "absent"; delete-absent is an explicit documented no-op; no hidden overwrites beyond atomic replace. |
| VI. Unix Philosophy | ✅ PASS | One small thing (addressed byte storage) behind a swappable seam. |
| VII. Secure by Default | ✅ PASS | Symlink refusal retained; directories created via the existing restrictive-umask pattern. **Deviation (justified):** memory reads intentionally skip the credential owner-only-mode enforcement and 1 MiB cap — memory is not credential-secret and the future team backend (AIE-620) may carry looser bits. Recorded in Complexity Tracking. |

**Gate result: PASS** (one documented, justified deviation — see Complexity Tracking).

## Project Structure

### Documentation (this feature)

```text
specs/045-memory-storage-foundation/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (internal module contracts)
│   └── memory_backend.md
├── checklists/
│   └── requirements.md  # Spec quality checklist (from /speckit.specify)
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
src/mixpanel_headless/_internal/
├── storage_root.py          # NEW — shared call-time root resolver (lifted from auth/storage.py)
├── io_utils.py              # REUSE — atomic_write_bytes, reject_if_symlink
├── auth/
│   └── storage.py           # EDIT — delegate _storage_root() to storage_root.py (compat shim)
└── memory/                  # NEW package
    ├── __init__.py          # Package marker + internal exports
    ├── paths.py             # NEW — pure validators + path builders (PBT/mutmut target)
    └── backend.py           # NEW — MemoryBackend protocol + LocalFilesystemBackend

tests/
├── unit/
│   ├── test_memory_paths.py         # NEW — validators + path builders
│   ├── test_memory_backend.py       # NEW — LocalFilesystemBackend behavior
│   └── test_storage_root.py         # NEW — shared root resolution + env override
├── pbt/
│   └── test_memory_paths_pbt.py     # NEW — Hypothesis invariants on pure path logic
└── integration/
    └── test_memory_scoping.py       # NEW — two-tree isolation, hermetic root
```

**Structure Decision**: Single-library layout. New code is confined to `_internal/memory/` plus a small `_internal/storage_root.py` extraction. The pure logic (`paths.py`) is split from all I/O (`backend.py`) so the property- and mutation-testing bar is met on an I/O-free module. `auth/storage.py` keeps its `_storage_root` name as a thin re-export to avoid churn in the heavily-tested auth suite.

## Complexity Tracking

| Deviation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| Memory reads skip credential owner-only-mode + 1 MiB cap (Principle VII partial deviation) | Memory notes are not secrets; the future team-shared backend (AIE-620) may sync files with looser permission bits, and the size policy is owned by AIE-605. Enforcing credential invariants here would reject legitimate memory files later. | Reusing `read_credential_text` wholesale (the ticket's literal anchor) would bake credential-grade constraints into a non-credential store and force a rewrite when AIE-605/AIE-620 land. Symlink refusal — the invariant that actually matters for safety — is retained. |
| New `_internal/storage_root.py` module (one more file) | Both auth and memory must resolve the same root at call time honoring `$MP_OAUTH_STORAGE_DIR`; memory reaching into `auth.storage._storage_root` would invert the dependency direction (memory → auth internals). | Leaving `_storage_root` private to auth couples the new memory layer to the auth module's internals. A shared leaf module keeps the arrow pointing at shared infrastructure. |
