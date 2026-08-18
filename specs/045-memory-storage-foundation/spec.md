# Feature Specification: Memory Storage Foundation & Two-Tree Scoping

**Feature Branch**: `045-memory-storage-foundation` (developed on the long-running `msiebert-agent-memory` integration branch)
**Created**: 2026-08-18
**Status**: Draft
**Linear**: AIE-603 — blocks all other Headless Memory build issues
**Input**: User description: "Memory storage foundation & two-tree scoping (AIE-603). Establish the on-disk substrate for Headless Memory: two separate trees of plain-markdown files kept split from day one..."

## Overview

Headless Memory lets an AI agent working through `mixpanel_headless` accumulate durable, plain-markdown notes across sessions — some tied to *who* is working (the account), some tied to *what project* is being worked on. This feature establishes only the **storage substrate**: where those notes live on disk, how the two scopes stay separated, how paths are validated, and a seam that lets project memory later move to a shared/team backend without rewriting callers. It deliberately stops short of the note format, the read/write tool verbs, size limits, concurrency, and PII handling — each owned by a sibling issue.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Durable notes separated by scope (Priority: P1)

An agent (or a higher-layer memory tool built on this substrate) needs to persist and retrieve two kinds of notes: user-scoped notes that follow the authenticated account, and project-scoped notes that follow the Mixpanel project. The substrate must keep these two trees physically separate so a note written about a project is never confused with a note about the user, and vice-versa.

**Why this priority**: This is the foundational capability the entire Headless Memory milestone rests on. Without two cleanly separated, addressable trees, no sibling feature (format, tool verbs, size limits, team backend) can be built. It is the MVP.

**Independent Test**: Write bytes to a user-scoped key and a project-scoped key using the same relative name, then read each back; confirm the two values are independent and land under distinct on-disk locations keyed on account name and project id respectively.

**Acceptance Scenarios**:

1. **Given** an account `personal` and a project `3713224`, **When** a note is written to the user scope under key `notes.md` and a different note is written to the project scope under the same key, **Then** reading each scope's `notes.md` returns its own value with no cross-contamination.
2. **Given** a project-scoped write for project `3713224`, **When** the write completes, **Then** the note is stored under a project-keyed location that is independent of any account and shared by any account that later resolves the same project id.
3. **Given** a freshly-configured environment with no prior memory, **When** the first note is written, **Then** the necessary scope directory is created on demand and the note is retrievable on a subsequent read.

---

### User Story 2 - Safe, predictable addressing (Priority: P1)

A caller addresses a note by a relative key within a scope. The substrate must reject inputs that could escape the intended tree (path traversal, absolute paths, symlinked targets) and must validate the identifiers used to build scope paths — account name and project id — before touching disk.

**Why this priority**: Memory paths are built from externally-influenced identifiers (account names, project ids) and relative keys. Any addressing gap is a path-traversal or symlink-substitution risk. Correct addressing is inseparable from the P1 storage capability.

**Independent Test**: Feed the path/validator logic a battery of valid and hostile identifiers and keys (including traversal sequences and non-numeric project ids) with no filesystem present, and confirm valid inputs produce the expected in-tree path while hostile inputs are rejected.

**Acceptance Scenarios**:

1. **Given** a project id `3713224`, **When** it is validated, **Then** it is accepted; **Given** a project id `../etc` or `12ab` or an empty string, **When** validated, **Then** it is rejected.
2. **Given** an account name that violates the established account-name rule, **When** a user-scoped path is requested, **Then** the request is rejected before any directory is created.
3. **Given** a relative key that attempts to traverse outside its scope (e.g. `../../secrets`), **When** used, **Then** the operation is refused rather than resolving outside the scope tree.
4. **Given** a note path that is a symlink, **When** a read is attempted, **Then** the read is refused rather than following the link.

---

### User Story 3 - Hermetic, relocatable storage root (Priority: P2)

A test run, a CI job, or an alternate deployment needs all memory to live under a chosen root instead of the developer's real home directory, and needs that choice honored at call time rather than frozen at import time.

**Why this priority**: Without call-time root resolution, tests leak into the developer's real `~/.mp` and the substrate can't be exercised hermetically — which blocks the ≥90% coverage and mutation-testing bar for every sibling issue. It is required for a healthy build, hence a close P2.

**Independent Test**: Point the storage-root override at a temporary directory, perform writes and reads, and confirm every artifact lands under the temporary root and nothing appears under the real home directory.

**Acceptance Scenarios**:

1. **Given** the storage-root override is set to a temporary directory, **When** any memory write occurs, **Then** the file appears under that directory and not under the real home directory.
2. **Given** the override is unset, **When** memory is accessed, **Then** the default home-based root is used.
3. **Given** the override is changed between two calls, **When** the second call runs, **Then** it resolves against the new root (no import-time caching).

---

### User Story 4 - A backend seam ready for a future team home (Priority: P2)

Project memory is expected to move to a shared/team backend later (a separate issue). The substrate must expose a thin, content-agnostic seam so that swap can happen behind the same interface without rewriting the callers that read and write notes.

**Why this priority**: Getting the seam shape right now avoids a costly rewrite when the team backend lands. It is not required for the local MVP to function, so it sits at P2, but building the local implementation *through* the seam is what makes the seam real rather than theoretical.

**Independent Test**: Exercise the read/write/list/delete operations exclusively through the abstract seam against the local implementation, confirming no caller depends on filesystem specifics beyond the seam.

**Acceptance Scenarios**:

1. **Given** the abstract memory backend interface, **When** the local filesystem implementation is used, **Then** read, write, list, and delete over relative keys all behave correctly.
2. **Given** a caller written against the seam, **When** a different backend implementation is substituted, **Then** the caller requires no changes to compile or operate.

---

### Edge Cases

- **Same key across scopes**: identical relative key in the user tree and the project tree must remain independent (covered by US1).
- **Cold read**: reading a key that was never written returns an explicit "absent" result, not an error or a partial value.
- **Listing an empty or nonexistent scope**: returns an empty listing, not an error.
- **Deleting an absent key**: is a no-op success, not an error (idempotent).
- **Interrupted write**: a process killed mid-write must never leave a half-written note in place of a previously-good one; a reader observes either the old note or the new note.
- **Loosened permissions on an existing note**: a note file whose permission bits are wider than the credential standard must still be readable (memory is not held to the credential owner-only rule), while a symlinked note path is still refused.
- **Project id leading zeros / very long ids**: bounded numeric ids are accepted up to a sane length; absurdly long or non-numeric ids are rejected.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST provide two separate, independently-addressable memory trees — a user-scoped tree keyed on account name and a project-scoped tree keyed on project id — kept physically separate from creation.
- **FR-002**: The user-scoped tree MUST be located to mirror the existing per-account layout, under a dedicated memory area within the account's directory so memory files never intermix with account credential files.
- **FR-003**: The project-scoped tree MUST be a new tree keyed solely on project id, independent of any account, so that any account resolving the same project shares the same project memory.
- **FR-004**: The system MUST validate project ids against a bounded numeric rule before using them to build a path, treating the id as an opaque string, and MUST reject non-conforming ids.
- **FR-005**: The system MUST validate account names against the established account-name rule before building a user-scoped path.
- **FR-006**: The system MUST refuse relative keys that would resolve outside their scope tree (path traversal / absolute paths).
- **FR-007**: The system MUST refuse to read a note whose path is a symlink.
- **FR-008**: The system MUST resolve the storage root at call time, honoring the storage-root override environment variable and falling back to the home-based default, so relocation and hermetic testing work without import-time caching.
- **FR-009**: The system MUST expose a thin, content-agnostic backend seam offering read, write, list, and delete over relative keys returning/accepting text or bytes, with a single local filesystem implementation in this slice.
- **FR-010**: Writes MUST be atomic with respect to interruption — an interrupted write never replaces a good note with a partial one.
- **FR-011**: Reads MUST use a lighter path than credential reads: they retain the atomic-write and symlink-refusal protections but MUST NOT enforce the credential owner-only-mode rule nor the credential size cap.
- **FR-012**: Reading an absent key MUST return an explicit absent result; listing an empty/absent scope MUST return an empty listing; deleting an absent key MUST succeed as a no-op.
- **FR-013**: Directories for a scope MUST be created on demand on first write and MUST NOT be required to pre-exist.
- **FR-014**: The pure path-and-validation logic MUST be free of filesystem and network I/O so it can be exhaustively property-tested and mutation-tested in isolation.

### Out of Scope (owned by sibling issues)

- Markdown note format and confidence labels (AIE-604).
- Write-time size-limit enforcement (AIE-605).
- Optimistic-locking / concurrency control for writes (AIE-606).
- PII protection on writes (AIE-607).
- User-facing memory tool verbs — Read / Write / List / String-replace (AIE-608).
- The shared/team project-memory backend implementation (AIE-620).
- Any workspace-level memory scope (the path layout must not preclude it, but it is not built here).

### Key Entities *(include if feature involves data)*

- **User-scoped memory tree**: the collection of notes tied to an authenticated account, addressed by account name and a relative key.
- **Project-scoped memory tree**: the collection of notes tied to a Mixpanel project, addressed by project id and a relative key, independent of account.
- **Memory backend (seam)**: the abstract capability to read, write, list, and delete note content by relative key; content-agnostic; local filesystem is the only implementation in this slice.
- **Storage root**: the call-time-resolved base directory under which both trees live; overridable for tests/deployments.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A note written to one scope is never returned when reading the other scope, for 100% of key collisions across the two trees.
- **SC-002**: Every invalid identifier or traversal/symlink attempt in the addressing battery is rejected — zero escapes outside the intended scope tree.
- **SC-003**: With the storage-root override pointed at a temporary directory, 100% of memory artifacts are created under that directory and 0 appear under the real home directory.
- **SC-004**: A caller written against the backend seam operates unchanged when the backend implementation is swapped — 0 caller edits required.
- **SC-005**: The pure path-and-validation logic reaches ≥90% test coverage and ≥80% mutation-kill rate, exercised without any filesystem or network access.
- **SC-006**: An interrupted write never yields a partially-written note — a reader always observes either the prior note or the complete new note.

## Assumptions

- The "users" of this substrate are the sibling Headless Memory features and, ultimately, the AI agents that read and write notes through them; there is no direct end-user UI in this slice.
- Mixpanel project ids are globally unique integers, so keying project memory on the id alone (no region or account prefix) is safe and is the desired sharing semantics.
- Reusing the existing account-name validation rule and the existing atomic-write and symlink-refusal primitives is acceptable and preferred over inventing new ones.
- Memory notes are not held to the same secrecy standard as credentials; the owner-only-mode and size-cap enforcement applied to credential reads is intentionally not applied to memory reads, anticipating the future team backend where files may carry looser bits.
- The storage-root override that already governs all on-disk artifacts is the same override memory honors; no new environment variable is introduced for the root.
- A single writer/reader per note at a time is assumed for this slice; concurrent-write safety beyond atomic replacement is deferred to the concurrency sibling issue.
