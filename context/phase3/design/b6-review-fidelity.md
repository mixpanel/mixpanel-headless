# B6 adversarial review — DELEGATION FIDELITY lens (P3-2d, fable)

**Status**: COMPLETE · 2026-08-16. Reviewer scope: the 8 opus W-shards +
fable BIND (TS `b093180..7a851f0`; Python notes commits `624a036..cfe9b93`).
Verdict: **GO with 1 MAJOR + 3 MINOR** findings. Everything verified against
`workspace.py` / `me.py` at support-branch HEAD, line-by-line for every
sampled member.

## 1 Harness re-runs (P3-2d item 5) — all REPRODUCED

| shard | recorded | re-run (2026-08-16) |
|---|---|---|
| W1 `throwaway/b6-w1/wire-edges.ts` | checks 61 / failures 0 | 61 / 0 |
| W6 `throwaway/b6-w6/wire-edges.ts` | checks 55 / failures 0 | 55 / 0 |
| W7 `throwaway/b6-w7/wire-edges.ts` | checks 56 / failures 0 | 56 / 0 |

All three are deterministic canned-interaction harnesses (no RNG/seeds, as
the RUN records state). RUN records for all 8 shards exist in
`context/phase3/notes/B6-W*-notes.md` (W6–W8 keep the record in the notes
file only — no `RUN.md` in `throwaway/`, which the packet's "RUN record →
notes file" wording permits).

Independent replication of the BIND claim: `npm run conformance` →
**3,251 vectors — 3,230 PASS / 0 FAIL / 21 UNPORTED @ 70c904dc** (exactly
the B6-BIND commit message; the dagger vector is inside the PASS set,
failures list empty). Binding-name census: 143 `bind("workspace.…")` in
`wire-workspace-entities.ts` + 11 W1 registrations in `wire-workspace.ts`
(incl. the multi-line `resolve_workspace_id` / 4 business-context forms) =
**154**, matching §11.1. All Layer-3 workspace suites re-run green:
1,429 passed / 26 todo (the todos ARE finding F1).

## 2 Member sample — ~80 members diffed against the Python bodies
(target was 40; the member modules are compact enough that whole-module
line-by-line reads were cheaper than sampling)

- **W1 (all 15 + 3 veneers + MeService)**: `use()` branch structure
  (target/account/pure-axis) matches `workspace.py:605-693` exactly incl.
  guard-before-resolution order, FR-033 no-project ConfigError, explicit
  `workspace=` short-circuiting the env seam, cache-clear block, persist
  AFTER swap. `MeService` vs `me.py:609-915`: peek/fetch two-level cache,
  401→ConfigError, 403 SA-vs-generic wording fork, `MeResponse` validate on
  the NATIVE tree, `list_projects` name.lower() codepoint sort,
  `list_workspaces` `pythonInt` project-id guard, `resolve_workspace`
  peek-only + `selectWorkspaceId` composition — all faithful. The
  business-context quartet (incl. `_resolve_organization_id` /
  `_cached_organization_id` / `_require_str_field` twins) matches
  `:10265-10674` branch-for-branch (sorted-by-codepoint org keys,
  hasOwn-based field reads, codepointLength for the 50k cap,
  validate-level-then-length order). W1-D2 close-in-place divergence and
  the absent `_initial_workspace_id` are accurately disclosed in code
  comments + notes.
- **W2 (17)**: guard placement audited against source — `requireResponse`
  used exactly where Python has `if raw is None` (create/get/update
  dashboard, blueprint trio, finalize, rca) and NOT where it doesn't
  (`remove_report_from_dashboard`); `add_report_to_dashboard`'s
  `isPlainRecord + Object.hasOwn("id")` guard is the watchlist-#13/R4.8
  twin of `:4832-4837`; by_alias dumps only at `:4985/:5022/:5109`
  (finalize/rca/report-link) with `update_text_card` correctly plain.
- **W3 (16 + private validator)**: `validateBookmarkParamsSchema` COMPOSES
  `validateSortingBlock`/`getRootModelForBookmarkType`/
  `PARTIAL_UPDATE_SUB_MODELS`/`validateWithPydantic` (B2/B3 surfaces, zero
  re-derived logic); `create_bookmark` preserves the 3-step order
  (dashboard_id guard → schema gate → create → `self.`-dispatched
  `add_report_to_dashboard`); update path partial gate + plain dump vs
  create's by_alias dump both correct; `list_cohorts_full` →
  `listCohortsApp` (the non-like-named client method, correctly noted).
- **W4 (6 sampled)**: `conclude_experiment` empty-`{}` body,
  `get_flag_history` empty-dict→`None` collapse + `pythonStr(page_size)`
  (R11.7), `set_flag_test_users` bare-dump mapping (see F4).
- **W5 (5 sampled)**: annotation dates stay strings end-to-end (watchlist
  #5); `test_alert` opaque passthrough; `validate_alerts_for_bookmark`
  exclude_none dump — all match.
- **W6 (6 sampled)**: `list_lexicon_tags` str-branch id=0 sentinel
  (`typeof === "string"` is correct — string discrimination, not #13);
  by_alias on the four definition writers vs plain on the tag writers,
  mirroring `:7266/:7325/:7406/:7452` vs `:7526/:7557`; opaque tracking
  passthroughs.
- **W7 (6 sampled incl. the orchestrator)**: `uploadLookupTable` steps and
  `pollLookupUpload` (monotonic seam, sleep-first loop, ms conversion at
  the ONE sleep site, `uploadStatus` default-on-absence-only,
  SUCCESS/FAILURE/REVOKED/NOTFOUND/timeout codes) match `:7989-8145`; the
  url/path/key guard is composed from the B4 client (verified it lives at
  `api_client.py:7609-7623` — not re-derived). One guard gap → F2.
  `list_custom_properties` displayFormula re-raise: detail-bag walk,
  isPlainRecord discrimination, carried request context — faithful.
  W7-D4 (`mode="json"` no-op) justification independently checked against
  `types.py` enum shape: sound.
- **W8 (6 sampled)**: `auditResponseFrom` is an exemplary port (watchlist
  #6 emptiness, #13 metadata discrimination, `computed_at`
  default-on-absence); `delete_schemas` facade-owned
  entity_name-requires-entity_type guard matches `:8864-8868`;
  `preview_deletion_filters` byAlias dump; `update_anomaly` family's
  plain `modelDump({byAlias})` addition matches `:9169/:9198`.

R10.8 duplication hunt: greps over `workspace-members/*` + `services/me.ts`
for fetch/URL/status/header/auth assembly — **clean** (the only
`statusCode === 403` is MeService's ported exception-classification, which
mirrors `me.py:739`). `modelDumpExcludeNone`/`modelDump` have exactly one
implementation (`model-base.ts`); `requireResponse`/`native` were extracted
to `workspace-members/shared.ts` at W3 and consumed by name; `isPlainRecord`
is imported from `client/internals.js`, never re-derived. Bindings audited:
every sampled registration calls the REAL facade member with
`requireWireKwarg`/`optionsBag` plumbing only (honest per P3-5 rule 3).

Zero-vector members: additive delegation suites present and clearly headed
(`crud-dashboards.test.ts:508+` for W2's 10; `TestUploadLookupTable` +
seam-default branches for W7's 1; W1's 9 are covered by the translated
facade/use/init/streaming suites).

## 3 Findings

### F1 — MAJOR · 27 `it.todo` stubs in `crud-edge.test.ts` were never
filled by W4–W8 (dropped hand-off)
`packages/core/test/workspace/crud-edge.test.ts:386-413`. W3 (which ran
FIRST, not last as the packet sequenced) translated only the 4
W1/W2/W3-member cases of
`test_workspace_crud_edge.py::TestCodedResponseValidationCodes` (:416, 30
cases total) and stubbed the rest as `it.todo(...)` with an explicit
hand-off: "the shard that lands the member converts its todo"
(`B6-W3-notes.md` §Gate/BIND hand-off item (b)). W4–W8 ALL landed
afterwards; none converted a single todo, no W4–W8 notes file mentions
them, and the BIND task didn't sweep them. Result: 27 real Python
assertions (ResponseValidationError class + `RESPONSE_VALIDATION_ERROR`
code across the flags/experiments/annotations/webhooks/alerts/lexicon/
drop-filter/custom-property/lookup-table/custom-event/schema/deletion
families — verified present at `test_workspace_crud_edge.py:459-643`)
exist only as stubs on `main`. Each fix is the documented two-liner over
the already-built `makeResultsWorkspace` + `assertCoded` helpers. This is
exactly playbook Risk #3 at B6 volume, in its sneakiest form: nothing was
weakened per-shard — the coverage fell through a sequencing gap.
**Required before the gate**: fill all 27 (W4 ×4, W5 ×6, W6 ×4, W7 ×8,
W8 ×5 per the stub labels; W3's notes say 26 — the real count is 27).

### F2 — MINOR · `uploadLookupTable` drops Python's two
`isinstance(raw, dict)` guards on the register response
`packages/core/src/workspace-members/governance-data.ts:670-696` casts the
`register_lookup_table` payload with `native(...) as Record<string,
unknown>` where Python branches on `isinstance(raw, dict)` twice
(`workspace.py:8060` uploadId read, `:8072` name-inject). On a non-dict
response Python hands the raw value to `validate_response_model`
untouched; the TS spread (`{...raw, name}`) mangles arrays/scalars into an
object first. Because `LookupTable` requires both `id` and `name`, every
constructed non-dict case still ends in the same
RESPONSE_VALIDATION_ERROR family — divergence is confined to error
details/message, and the member has ZERO vectors. Still a watchlist-#13
pattern violation (packet Caution #10: "any isinstance(x, dict) in facade
bodies ports via isPlainRecord"). Fix: guard both sites with
`isPlainRecord`.

### F3 — MINOR · R6.2 facade-level identity assert is one level shallower
than the Python assert
`workspace-use.test.ts:121-158` asserts `ws.client` WRAPPER identity
(`toBe`) across all three `use()` swaps; the Python source asserts
`id(client._http)` — the inner pool (`test_workspace_use.py:132-166`).
Pool-token identity across `client.use()` is locked at B4
(`client-core.test.ts:283-299`, `httpHandle()` `toBe`), so composition
covers the invariant, and `close()`-in-`use()` style regressions would
still be caught indirectly. But a facade-path pool assertion is a
one-line addition (`ws.client.httpHandle()` before/after) and would make
the translated test assert what Python's asserts. R10.2 precision note,
not a coverage hole.

### F4 — MINOR/NIT · `set_flag_test_users` maps Python's bare
`model_dump()` to `toJSON()` instead of the exact `modelDump()` twin
`flags-experiments.ts:295`. W4 predates W8's `modelDump()` (added for
`update_anomaly`/`bulk_update_anomalies`), whose own JSDoc states
"toJSON is NOT a substitute" (no extras, no aliases). For
`SetTestUsersParams` specifically this is provably equivalent
(extra='ignore', one required field, no aliases — verified both sides),
so behavior is correct TODAY; it becomes wrong the moment the model gains
an alias/extra field. One-line harmonization to `params.modelDump()`.

## 4 Cross-shard items verified (for the arbiter)

- The W6-applied fix to W3's `delegation-equivalence.pbt.test.ts` (bare
  `trim` → `pythonStrip`, `B6-W6-notes.md` §4) is in place with the R11.7
  cite; the fix is CORRECT (CPython `"\x1f".strip()` → `""`); charge the
  original R11.7 miss to W3 as the notes request. Confirmed not scope
  creep.
- W1-D2 (close-in-place, pin-retention divergence) and W7-D1/D2 (readFile /
  monotonic seams), W7-D4 (mode="json" no-op): disclosures accurate against
  source; no vector exposure.
- `b6-packets.md` §5's "TestRequestBodySerialization :92 …" class list and
  the W3 file's coverage reconcile; the packet's W3-runs-LAST sequencing
  was inverted by the orchestrator — F1 is the only casualty found.
- Empty-response-guard asymmetry across shards (W2/W3 use
  `requireResponse`, W5/W6/W7 deliberately don't) matches the Python
  source in every sampled member — the guard exists exactly where Python
  has `if raw is None`.

## 5 Verdict

**GO** for the gate CONDITIONAL on F1 (fill the 27 todos — mechanical,
helpers exist). F2–F4 are one-line fixes the arbiter can batch. No
binding-honesty violations, no R10.8 duplication, conformance and all
three re-run harnesses reproduce exactly, /me caching semantics faithful,
R6.2 locked (modulo the F3 precision note).
