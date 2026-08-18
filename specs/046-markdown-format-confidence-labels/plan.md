# Implementation Plan: Markdown Entry Format & Confidence Labels

**Branch**: `msiebert-agent-memory` (slice `046-markdown-format-confidence-labels`) | **Date**: 2026-08-18 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/046-markdown-format-confidence-labels/spec.md`
**Linear**: AIE-604

## Summary

Define the Headless Memory *entry format* that rides on top of the AIE-603 byte-store: a four-value confidence label and an immutable `MemoryEntry` (label + free-form markdown body) with a stable text serialization. Serialization is a leading `---`-fenced front-matter block carrying only `confidence:`, followed by the verbatim body. A pure, I/O-free `format` module (`serialize` / `parse`) is the property- and mutation-tested core, mirroring how 045 split pure `paths.py` from I/O `backend.py`. The parser is stdlib-only — no YAML dependency — rejects missing/unknown labels loudly, and preserves bodies that themselves contain `---` lines. The label type and entry type live in the internal memory package; nothing in this slice touches the backend's byte I/O, size limits, locking, or PII (each owned by a sibling issue).

## Technical Context

**Language/Version**: Python 3.10+ (mypy --strict)
**Primary Dependencies**: Standard library only (`dataclasses`, `typing`, `json` for `to_dict` consumers). No new third-party dependency — explicitly no PyYAML. Reuses nothing from the backend I/O path.
**Storage**: N/A in this slice — the format is pure text; encoding to bytes and persistence belong to the backend (AIE-603) and the tool primitives (AIE-608).
**Testing**: pytest; Hypothesis (PBT on the pure `format` module, `_pbt` suffix); mutmut (mutation testing on the pure `format` and `entry` modules).
**Target Platform**: POSIX primary; the format layer is platform-independent (no filesystem).
**Project Type**: Single Python library (`mixpanel_headless`) — internal infrastructure layer only in this slice.
**Performance Goals**: Not a hot path; serialize/parse are linear single-pass string operations. No specific latency target.
**Constraints**: ≥90% coverage; mutmut ≥80% on the new pure modules; mypy --strict; full Google-style docstrings; no `Any` without justification; the `format` module must be free of filesystem/network I/O.
**Scale/Scope**: Two new `_internal/memory/` modules (`entry.py`, `format.py`). Handful of notes per scope in practice; entries are small markdown documents.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Library-First | ✅ PASS | Format + types live in the Python library (`_internal/memory/`); no CLI in this slice. Tool verbs (AIE-608) will surface entries via the library. |
| II. Agent-Native Design | ✅ PASS | Pure functions and an immutable dataclass; no prompts, no interactivity. `to_dict()` yields structured, pipe-able output for the eventual CLI/`--jq`. |
| III. Context Window Efficiency | ✅ PASS | Entry carries one label + free-form body; no schema bloat. Parse returns a precise entry or an explicit error, never a dump. |
| IV. Two Data Paths | ➖ N/A | Memory is neither a live query nor a DuckDB analysis path; orthogonal. |
| V. Explicit Over Implicit | ✅ PASS | Parsing NEVER substitutes a default label — missing/unknown labels raise a typed error. The entry is immutable (frozen). No hidden coercion beyond documented whitespace-trim on the label value. |
| VI. Unix Philosophy | ✅ PASS | One small thing (an entry format) behind a pure seam; `to_dict()` composes with `jq`. |
| VII. Secure by Default | ✅ PASS | No credentials, no I/O, no logging of content in this slice. PII handling is explicitly deferred to AIE-607; this layer neither weakens nor claims to provide it. |

**Gate result: PASS** (no deviations — Complexity Tracking is empty for this slice).

## Project Structure

### Documentation (this feature)

```text
specs/046-markdown-format-confidence-labels/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (internal module contracts)
│   └── memory_entry_format.md
├── checklists/
│   └── requirements.md  # Spec quality checklist (from /speckit.specify)
└── tasks.md             # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
src/mixpanel_headless/_internal/memory/
├── __init__.py          # EDIT — export ConfidenceLabel, MemoryEntry, serialize, parse, MemoryFormatError
├── paths.py             # UNCHANGED (from 045)
├── backend.py           # UNCHANGED (from 045) — this slice does not touch byte I/O
├── entry.py             # NEW — ConfidenceLabel Literal + CONFIDENCE_LABELS + frozen MemoryEntry (+ to_dict)
└── format.py            # NEW — serialize / parse (pure, I/O-free) + MemoryFormatError (PBT/mutmut target)

tests/
├── unit/
│   ├── test_memory_entry.py        # NEW — MemoryEntry construction, label validation, to_dict
│   └── test_memory_format.py       # NEW — serialize/parse behavior, malformed-input rejection
└── pbt/
    └── test_memory_format_pbt.py   # NEW — Hypothesis round-trip + invariants on the pure module
```

**Structure Decision**: Single-library layout. New code is confined to two files under the existing `_internal/memory/` package. The pure format logic (`format.py`) is split from the type definitions (`entry.py`) so the mutation-testing bar is met on focused, I/O-free modules — the same pure/IO discipline 045 applied to `paths.py`/`backend.py`. There is no integration test tier here because the slice performs no filesystem or network I/O; the entire surface is exercised by unit + property tests.

## Complexity Tracking

*No constitution violations — this slice introduces no deviations. Table intentionally empty.*

| Deviation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| — | — | — |
