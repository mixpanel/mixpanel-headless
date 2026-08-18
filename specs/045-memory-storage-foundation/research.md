# Research: Memory Storage Foundation & Two-Tree Scoping

**Feature**: 045-memory-storage-foundation | **Date**: 2026-08-18

All technical unknowns were resolved during brainstorming (see AIE-603 comment). No `NEEDS CLARIFICATION` markers remain. This document records the decisions and the rejected alternatives so the sibling issues inherit the reasoning.

## D1 — On-disk layout: `memory/` subdirectory per scope

- **Decision**: `<root>/accounts/{name}/memory/` (user) and `<root>/projects/{id}/memory/` (project). A dedicated `memory/` subdir inside each scope directory.
- **Rationale**: The account directory already holds credential JSON (`tokens.json`, `client.json`, `me.json`) and is swept by `OAuthStorage.delete_all()` (`*.json`) and `clear_me_cache()` (`me_*.json`). Isolating memory in its own subtree prevents collisions and accidental deletion, and lets memory carry a distinct permission/size policy.
- **Alternatives rejected**: Files directly in the scope dir (flatter, but intermixes memory with credentials and is exposed to the credential-glob deletes).

## D2 — Project memory keyed on project id alone

- **Decision**: Project tree keyed solely on the project id string; no account or region prefix. Any account resolving the same project shares the tree.
- **Rationale**: Mixpanel project ids are globally unique integers. Project memory is about the *project*, not the accessor. Shared-by-project is the correct semantics and pre-wires the team-shared backend (AIE-620).
- **Alternatives rejected**: Keying under the account (`accounts/{name}/projects/{id}/`) would fork project memory per accessor and duplicate notes; a region prefix is unnecessary given global id uniqueness.

## D3 — Content-agnostic backend seam

- **Decision**: `MemoryBackend` protocol — `read(key) -> bytes | None`, `write(key, data) -> None`, `list(prefix="") -> list[str]`, `delete(key) -> None` — over relative keys, content-agnostic. `LocalFilesystemBackend` is the only implementation in this slice.
- **Rationale**: Format (AIE-604), size limits (AIE-605), and tool verbs (AIE-608) build on top. A dumb seam keeps 603's blast radius minimal and gives AIE-620 a stable interface to swap behind. Mirrors the injected-strategy pattern of `TokenResolver` / `WorkspaceResolver` already in the codebase.
- **Alternatives rejected**: A memory-record-aware backend (understands confidence labels/metadata now) leaks 604/608 concerns into 603 and couples the team-backend seam to an unfinalized format.

## D4 — Lighter read path than credentials

- **Decision**: Writes go through `atomic_write_bytes`; the note path is guarded by `reject_if_symlink`. Reads do **not** use `read_credential_text`; they read the file directly after a symlink check, without the credential helper's owner-only-mode enforcement or 1 MiB cap.
- **Rationale**: The credential invariants (owner-only mode, home-anchored dirfd walk, 1 MiB cap) are correct for secrets. For memory, the owner-only rule would reject team-synced / externally-managed files (AIE-620), and the size policy belongs to AIE-605. Symlink refusal — the invariant that actually matters against same-UID substitution — is kept.
- **Alternatives rejected**: Reusing `read_credential_text` wholesale (the ticket's literal anchor). Documented as the one intentional divergence from the anchor, both in the plan's Complexity Tracking and the Linear comment.

## D5 — Project-id validator `^\d{1,20}$`, opaque string

- **Decision**: New validator `^\d{1,20}$`, treating the id as an opaque string (no `int()` normalization). Lives in the pure `paths.py`.
- **Rationale**: Analogous to the existing account-name (`^[a-zA-Z0-9_-]{1,64}$`) and region (`^[a-z]{2}$`) validators. Length-bounded to reject absurd ids while comfortably covering real Mixpanel ids (7–10 digits). Keeping it a string means the on-disk dir matches the string form already threaded through `me.py` (`me.projects` keys, `int(project_id)` comparisons happen at call sites, not here).
- **Alternatives rejected**: Unbounded `^\d+$` (allows pathological lengths); `int` normalization (would drop leading-zero fidelity and mismatch the string keys callers pass).

## D6 — Shared call-time storage root

- **Decision**: Extract the root resolver into a new leaf module `_internal/storage_root.py::storage_root()`, resolved at every call (`$MP_OAUTH_STORAGE_DIR` → `~/.mp`). `auth/storage.py` keeps `_storage_root` as a thin re-export/delegate for backward compatibility.
- **Rationale**: Both auth and memory need the same call-time root. A shared leaf module keeps the dependency arrow pointing at shared infrastructure rather than having memory import `auth.storage` internals. Call-time resolution (not import-time capture) is required for hermetic tests that monkeypatch `$HOME` / `$MP_OAUTH_STORAGE_DIR` — the existing rationale in `_storage_root`'s docstring.
- **Alternatives rejected**: Memory importing `auth.storage._storage_root` (inverts the dependency direction); duplicating the resolver in memory (two sources of truth for the root, drift risk).

## D7 — Testing strategy for the DoD

- **Decision**: Split pure logic (`paths.py`: validators + path builders, zero I/O) from I/O (`backend.py`). Hypothesis PBT (`test_memory_paths_pbt.py`) asserts invariants — valid ids/names/keys always yield in-tree paths; hostile inputs always raise; round-trip key→path→key stability. mutmut targets `paths.py` (and any pure helpers in `backend.py`). Integration test asserts two-tree isolation and hermetic-root containment.
- **Rationale**: The ≥80% mutmut bar is only tractable on I/O-free code; isolating the pure logic makes both the PBT and mutation targets clean. Matches the project's established `_pbt` convention and prior features' structure.
- **Alternatives rejected**: Mutation-testing the I/O module directly (filesystem side effects make mutants slow and flaky to kill).

## Reused repo anchors (confirmed present)

- `_internal/io_utils.py`: `atomic_write_bytes`, `reject_if_symlink`, `CredentialPathError` — verified signatures during brainstorming.
- `_internal/auth/storage.py`: `_storage_root`, `account_dir`, `ensure_account_dir`, `_ACCOUNT_NAME_PATTERN`, the `0o700`/`0o600` + `os.umask(0o077)` directory pattern.
- `_internal/me.py` `MeCache`: single-file read/write/invalidate template (TTL dropped — memory is durable).
