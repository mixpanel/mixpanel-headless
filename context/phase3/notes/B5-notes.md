# B5 batch notes

**Status**: OPEN — created by the B5 arbiter (B5-ARB) to carry the
outbound-deferrals ledger the review pair flagged as header-only
(assertions review F2, `b5-review-resolution.md`). The B5 GATE task
finalizes this file (RUN-record roll-up, review findings, discrepancies,
escalations) per P3-2 step (e) item 5 — do NOT treat this file as the
finished batch notes until the gate commit lands.

Shard notes: `B5-S1-notes.md` · `B5-S2-notes.md` · `B5-S3-notes.md` ·
`B5-BIND-notes.md`. Reviews: `../design/b5-review-fidelity.md` ·
`../design/b5-review-assertions.md`. Arbiter resolution:
`../design/b5-review-resolution.md`.

## Outbound deferrals to B6 (BINDING ledger — the B6 design-lite packet MUST cite this section)

| # | Item | Owner | Source of record | What B6 must do |
|---|---|---|---|---|
| 1 | `TestDiscoveryCacheAcrossUse` (`tests/unit/test_query_workspace_scoping.py:401`) | **B6-W1** | `b5-packets.md` §8 (packet-cited) + `facade-scoping.test.ts` header | Translate into `packages/core/test/workspace/facade-scoping.test.ts` once `Workspace.use()` lands (`use()` discards `self._discovery` — the cache-drop invariant). |
| 2 | `TestWorkspaceFacadeScoping` (`tests/unit/test_query_workspace_scoping.py:379`) | **B6-W1** | `facade-scoping.test.ts:1-25` header ONLY (packet §3 routed it to B5 on the wrong assumption that the facade half was `use()`-free; the case calls `ws.use(workspace=4242)`, a B6-W1 stub) | Translate into `facade-scoping.test.ts` — the additive session-pinned lock already there makes this a one-line delta. This is the only Python lock on `use()`-workspace-scoping threading through the facade. |
| 3 | `TestListCustomPropertiesErrorHandling` (`tests/unit/.../list_custom_properties` suite, facade re-raise contract `workspace.py:7742-7790`) | **B6** (api-map: `workspace.list_custom_properties` batch B6) | `custom-property-query.test.ts:9-22` header ONLY (packet said "translate against the B4 client method", but the B4 client does no `displayFormula` QueryError re-raise — the contract lives in the facade member) | Translate with the facade member: assert `raised is not original`, `__cause__`/`cause` is the original, HTTP context carried over. |
| 4 | `workspace.list_bookmarks_v2` pending-override REMOVAL | **B6 gate** | playbook P3-5 flip rules (B5-gate adds the longer `pending` entry; B6-gate replaces the 44 exact names + override with `workspace.` → done) | Mechanical, part of the B6 flip commit. |
| 5 | R11.7 straggler: `types/results/query-engine.ts` `overall_conversion_rate` NON-STRING ladder (`floatValue(value) ?? 0.0` where CPython `float(None/list/dict)` raises `TypeError`) | **B6 gate** (R11.7 straggler sweep) | `b5-review-resolution.md` ASR-F6b (the STRING arm was fixed at B5-ARB via `pythonFloat`; the non-string ladder needs a `pythonFloatCoerce` compat twin — a B0-style both-repo addition, out of arbiter-patch scope) | Add `pythonFloatCoerce` to `packages/core/src/compat/` mirrored in `pycompat_ref.py` (+ oracle strategy), then route the non-string arm through it. Blame: P2-6 commit `2ee9f59`, pre-R11.7-amendment. |

## Arbiter remediation summary (2026-08-16)

See `context/phase3/design/b5-review-resolution.md` for the full
findings ledger, fixes (all red-first), and post-fix re-run evidence
(S1/S2/S3 harness seeds, BIND fuzz with the extended rrweb timestamp
domain, 506-vector replay, `npm run check`, `just check`).
