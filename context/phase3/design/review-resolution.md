# Phase-3 playbook — arbiter resolution

Arbiter · 2026-08-15 · Inputs: `review-fidelity.md` (8 findings), `review-gates.md`
(6 findings) against `phase3-playbook.md` v1.0. Output: playbook v1.1 (same file, edited
in place). Every finding was independently re-verified against the repos before ruling;
verification commands and observed evidence are noted per finding. Deduplication:
fidelity F1 and gates F2 are the same defect (ruled once). Net: **13 distinct findings,
13 APPLIED, 0 REJECTED**. No gate was weakened; two gates were strengthened (harness
retention, review item 5).

## Rulings

### R1 — gates F1 (BLOCKER): volume-tier tasks required to edit `bindings.ts` — APPLIED

Verified: playbook v1.0 P3-2(b) made "bind the api names in
`conformance-runner/src/bindings.ts`" a per-module done-criterion and P3-2(c) required
oracle-ts registration "in the same commit", while P3-3's own rig row and
`model-tiering-policy.md` ("Anything touching the conformance rig itself … fable — the
judge must be stronger than the judged") forbid sonnet/opus rig edits; Risk #2's
mitigation asserted "bindings are rig code = fable-only" with no task assigned to make
that true for B2/B3/B5/B6.

Fix applied: new P3-2 step **(b′)** — binding + oracle registration is ALWAYS fable.
Fable-tier batches (B0, B4, B7–B9) land it inline in the module task; volume-tier
batches (B2/B3/B5/B6) get a separate per-module fable binding task (new P3-6 step 3)
that writes the bindings, applies the P3-5 rule-3 honesty check, and runs the module's
vectors. Vector failures at (b′) are attributed to the MODULE task for escalation.
P3-5 rule 3 extended to ALL bindings (pure/builder included); P3-3 gains an explicit
(b′) row; P3-2(d) arbiter now verifies binding honesty per module; Risk #2 mitigation
updated. Step (c) reordered to run after (b′) (the harness needs oracle-ts registration).

### R2 — fidelity F1 = gates F2 (major): B5 flip prefix-captures `workspace.list_bookmarks_v2` — APPLIED

Verified: `batch-status.ts:90-95` is `api.startsWith(prefix)` longest-match; api-map has
`list_bookmarks` batch=B5, `list_bookmarks_v2` batch=B6; corpus recount:
`workspace.list_bookmarks_v2` = 7 vectors, `workspace.list_bookmarks` = 0; exhaustive
cross-batch prefix scan of all 205 member names reproduces exactly one collision.

Fix applied: P3-5 §4 now (a) states the `startsWith` semantics honestly (an "exact name"
entry is still a prefix), (b) adds a standing mechanical assertion — after generating
exact-name entries, no still-pending corpus api name may `startsWith` a generated entry —
and (c) resolves the known collision at the B5 gate with a longer overriding entry
`workspace.list_bookmarks_v2` → `pending` (longest-prefix wins), removed at the B6 gate
when the exact names collapse to `workspace.` → `done`. The override was chosen over
dropping the vectorless `list_bookmarks` entry because it stays correct if a corpus
re-pin later adds `list_bookmarks` vectors.

### R3 — fidelity F2 (major): P3-5 §1 ignored `call.setup[]` / shared state map — APPLIED

Verified: `runner.ts:446` creates one `state` map per vector; `:478-500` executes
`call.setup[]` through the bindings with the shared context and the single
`createVectorFetch` harness; doc comment `:51-52` names `set_workspace_id` as the reason.
Corpus setup histogram reproduced: 97 `api_client.set_workspace_id`, 8 `close`,
4 `retention`, 4 `list_bookmarks`, 2 `use`, 2 `resolve_workspace`,
2 `resolve_workspace_id`, plus discovery prerequisites and 1 `workspace.me`.

Fix applied: P3-5 §1 gains a mandatory paragraph — `clientFromSession` memoizes the
client in `context.state` so setup entries and the measured call share one instance; and
every setup api name needs a binding by replay time or `gateApis` (`runner.ts:368-386`)
short-circuits the vector.

### R4 — gates F3 (major): cross-batch setup vector breaks B4/B6 exact gate deltas — APPLIED

Verified: `gateApis` gates on `[...setup apis, measured api]`; exactly one corpus vector
is api_client-measured with a workspace setup
(`auth/api_client.resolve_workspace_id/test_workspace_resolution-testfacaderesolverwiring-test_resolves_from_me_cache_without_public_call`,
setup `workspace.me`, a B6 member); 22 forward workspace←api_client setups confirmed
benign (B4 lands first).

Fix applied: P3-1 table now carries a † footnote defining the standing rule (gate deltas
count vectors whose measured AND setup apis are owned by flipped batches) and the
adjusted expectations: B4 gate delta **842** (cumulative 1,837 at the B4 gate, 2,343 at
B5), B6 gate delta **354**. P3-2(e).2 and the P3-5 closing line now reference the gate
delta instead of the raw vector count; the B4/B6 scope rows note their deltas.

### R5 — gates F4 (major): "verify `oracle.info` lists them" unimplementable — APPLIED

Verified: both bridges' `info` return exactly
`{language, library_version, source_commit, protocol_version}`
(`conformance/oracle_py/server.py:279-286`; `differential/oracle/server.ts:568-575`);
oracle-py raises `OracleProtocolError` "unknown api …" for unregistered names
(`server.py:414-418`) and answers wire entries with `WIRE_OUT_OF_SCOPE`.

Fix applied: P3-2(e).3 replaces the info check with a mechanical probe — one
`oracle.call` per newly registered registry-covered api on BOTH bridges, requiring a
non-"unknown api" response; wire api names are exempt (no oracle call surface). The
protocol-1.2 `oracle.info.apis` alternative was not scheduled: the probe achieves the
same guarantee with zero rig changes.

### R6 — fidelity F3 (major): `_handle_response` fallthrough order inverted; 2xx JSON scalar missing — APPLIED

Verified against `api_client.py:652-662` and live httpx: `raise_for_status()` runs
before the object/array return (302 with request set raises `HTTPStatusError` ⊂
`httpx.HTTPError`, caught at `:801` → `HTTP_ERROR` wrap); `Response(200, b"42").json()`
returns `42` (and `'"ok"'` → `"ok"`).

Fix applied: the B0-2 checklist bullet now states the tail in exact source order:
(i) raise-for-status first — the R2.11 throwing helper must throw a
`MixpanelHttpError`-normalized error so `_execute_with_retry` wraps it as `HTTP_ERROR`
(a 3xx with a JSON object body is an error, never a success); (ii) object/array →
return; (iii) re-parse — JSON scalar returned as the result, parse failure →
`INVALID_RESPONSE` with `cpSlice(text, 0, 500)`.

### R7 — fidelity F4 (major): RateLimitError spec omitted `project_id` — APPLIED

Verified: all five raise sites pass `project_id=self.project_id` (`:779, :819, :1322,
:1386, :1890`); the fallthrough raises (`:814-820`, `:1381-1387`) omit
`retry_after`/`status_code`/`response_body`; the streaming site (`:1883-1891`) omits
`response_body` only; Layer-3 asserts exist at `test_api_client.py:504,527,1567,4090`.

Fix applied: the retry-policy checklist line now requires `project_id` (Python spelling,
R7.6), names all five raise sites, notes that `details_contain` vectors cannot catch the
omission (only the Layer-3 translation does), and specifies the per-site constructor
shapes verbatim.

### R8 — fidelity F5 (major): `_request_headers` had no B0 row (R10.8 dual ownership) — APPLIED

Verified: `_request_headers` at `api_client.py:452-481` (4-layer merge), consumed by
`_execute_with_retry` (`:747`), `app_request` (`:1264`), and streaming/replay sites
(`:1862`, `:7720`, `:7923`); v1.0 B4-C1 claimed "headers";
`test_settings_headers.py` was listed only under B8 and is mixed (outbound-merge class +
config/bridge classes).

Fix applied: B0-2 table gains a `_request_headers` → `client/headers.ts` row plus an
R10.8 ownership note spelling out the 4 layers; B4-C1's scope now says header
composition is imported from B0 by name, never re-implemented; the Layer-3 lock is
split — `TestSessionHeadersOnOutboundRequests` translates at B0, the config/bridge
attachment classes stay at B8 (B8 row annotated accordingly); B0's module list adds
`client/headers.ts` (and the other client files now named in the packet table).

### R9 — gates F5 (minor): `parseLossless` had no library home — APPLIED

Verified: `parseLossless` exists only at `conformance-runner/src/lossless-json.ts:52`;
`packages/core/src/client/` holds only a placeholder `index.ts`; no packet provisioned a
core-side parser.

Fix applied: B0-2 table gains a relocation row — `parseLossless` MOVES to
`packages/core/src/client/lossless-json.ts` with its unit tests, and the rig re-imports
from core (judge-uses-library direction; the library never imports from the rig).

### R10 — gates F6 (minor): harness deleted before review = self-reported RUN record — APPLIED

Verified: v1.0 P3-2(c) mandated deletion before review; rulebook R10.9 mandates the
harness but not deletion timing (the sequencing was the playbook's own addition), so
retaining it violates nothing and strengthens verification.

Fix applied: the harness now lives in a `throwaway/` directory inside the module commit;
the review pair gains checklist item (5) — re-run/spot-check from the RUN record's
seeds, with an unreproducible RUN record an explicit finding; the batch gate task
deletes `throwaway/` after arbiter sign-off.

### R11 — fidelity F6 (minor): `_error_message` `{"error": null}` branch — APPLIED

Verified: `api_client.py:98-100` — `body.get("error") is None` returns the default for
both absent and null. Fix applied: checklist restated as absent OR null → default;
string → as-is; other non-null → `pythonStr(raw)`; blank-after-strip → default.

### R12 — fidelity F7 (minor): "183 names to exactly one of C2–C5" — APPLIED

Verified: the 183 `api_client.*` api-index names include `use`, `set_workspace_id`,
`close`, `resolve_workspace`, `resolve_workspace_id`, `require_scoped_path`,
`maybe_scoped_path`, `request` (plus `_iter_jsonl_lines`). Fix applied: reworded to
"exactly one of C1–C6", with `maybe_scoped_path` B0-module/C1-bound and
`_iter_jsonl_lines` B0-owned; the mechanical coverage diff runs over the full 183.

### R13 — fidelity F8 (minor): B2 "kind: validation-error or builder" — APPLIED

Verified: kind histogram over the 690 `validation.`/`user_validators.` vectors =
690 builder / 0 validation-error. Fix applied: B2 row now says all `kind: builder` with
error cases via `expect.error`.

## Rejections

None. Every finding reproduced from repo evidence.

## Ripples chased

- P3-1 cumulative column adjusted at the B4/B5 gates (1,837 / 2,343) with the final
  totals unchanged (2,697 / 2,718 / 3,179+N intact).
- P3-2(c) reordered after (b′); P3-2(d) gains items for harness re-run and binding
  honesty; P3-2(e).2 speaks in gate deltas; P3-6 renumbered (binding task inserted as
  step 3, gate task now step 5, with `throwaway/` cleanup listed).
- P3-3 table gains the (b′) fable row; Risk #2 mitigation updated to cite the
  structural enforcement.
- B4-C1 sharding text, B8 Layer-3 list, and the B0 module list updated coherently with
  the `_request_headers` ownership decision (R8).
- Playbook status bumped to v1.1 citing this resolution.

## Human calls

None. Every ruling was decidable from the rulebook, the plan, the tiering policy, and
direct repo evidence; no gate was weakened, and the two additions (harness retention,
oracle probe) strengthen existing gates rather than alter their thresholds.
