# B6-W3 notes — bookmarks/reports + cohorts (16 members)

Spec: context/phase3/design/b6-packets.md §5. Status: IN PROGRESS.

## Inventory (start)
- TS repo main @ 5dd445e (B6-W2 landed). W1 + W2 on disk:
  packages/core/src/workspace-members/{lifecycle,dashboards}.ts.
- W4-W8 NOT on disk yet -> cross-entity suites (test_workspace_crud_edge.py,
  test_delegation_equivalence_pbt.py) can only cover W1/W2/W3 members today.

## RUN record
(pending)

## Progress log
- [1] `workspace-members/shared.ts` NEW: `requireResponse` + `native` lifted out
  of W2's `dashboards.ts` (two-line import change there) so W3–W8 share ONE
  implementation (R10.8). Recorded for the gate integrator.
- [2] `workspace-members/bookmarks-cohorts.ts` NEW: 16 members + the private
  `_validate_bookmark_params_schema` (composes the live B2/B3
  `validateSortingBlock` / `getRootModelForBookmarkType` /
  `PARTIAL_UPDATE_SUB_MODELS` / `validateWithPydantic`; adds NO validation).
- [3] `types/entities/cohorts.ts`: `_DefinitionFlatteningModel.model_dump`
  (`types.py:2865-2878`) was MISSING from Phase 2. Added as a
  `modelDumpExcludeNone` override on CreateCohortParams / UpdateCohortParams /
  BulkUpdateCohortEntry (same place Python puts it — the facade must not
  re-derive it). Falsy `{}` definitions drop entirely (`if definition:`).
- [4] **B4-C1 BUG FOUND + FIXED** — `client/response-validation.ts`
  `collectModelErrors` was ALIAS-BLIND: it probed only `spec.name`, so every
  required aliased field (`Bookmark.bookmark_type` ← `"type"`) reported a
  spurious `missing`. Arbiter probe:
  `Bookmark.model_validate({"id":1,"name":"A","params":{}})` →
  `loc == ["type"]` (the ALIAS), and BOTH `type=` and `bookmark_type=` are
  accepted (`populate_by_name=True`, `validate_by_alias/name=True`). Fix
  mirrors `prepareInit`'s key map (`nameAccepted` honoured) and reports the
  alias in `loc` for absent aliased fields. No B4/B5 consumer had an aliased
  REQUIRED field, which is why 2,876 vectors stayed green over the defect.
- [5] `crud-bookmarks-cohorts.test.ts`: 64 tests, green (TestWorkspaceBookmarkCRUD
  :530 + TestWorkspaceCohortCRUD :1319, assertion-for-assertion).
- [6] `workspace.ts`: the B6-W3 append-only section (16 one-line delegations)
  + the options-interface re-exports + `validateBookmarkParamsSchema`.
  `createBookmark` passes `(dashboardId, bookmarkId) => this.addReportToDashboard(...)`
  so Python's `self.` dispatch through the W2 member is preserved.
- [7] Layer-3 (all four packet files): `crud-bookmarks-cohorts.test.ts` (64),
  `workspace-bookmarks.test.ts` (17), `crud-edge.test.ts` (16 + 26 todo),
  `delegation-equivalence.pbt.test.ts` (6 properties, numRuns 100).
  `bookmark-fixtures.ts` mirrors `tests/unit/_bookmark_fixtures.py`.

## Deferrals (shard-order, NOT dropped)
The orchestrator dispatched W3 BEFORE W4–W8 (the packet §2 sequencing wants W3
last). Consequence, confined to ONE class:
`test_workspace_crud_edge.py::TestCodedResponseValidationCodes` (:416) has 30
cases; 4 (dashboards / bookmarks / cohorts) are translated and green, and the
other 26 are carried as `it.todo(...)` entries in `crud-edge.test.ts` naming
the Python case, its line and the owning shard (W4 ×4, W5 ×6, W6 ×4, W7 ×8,
W8 ×4). Each is a two-line body over the already-written
`makeResultsWorkspace` + `assertCoded` helpers; the shard that lands the
member fills its todo. Everything else in the two cross-entity suites is
FULLY translated: `TestRequestBodySerialization`, `TestEmptyResponseHandling`
and `TestWorkspaceMethodDelegation` only touch W1/W2/W3 members, and
`test_delegation_equivalence_pbt.py` is validator-level (tier-independent).

## Divergence recorded
`query_saved_report` (a B5 member; its facade test file is W3's): Python's
facade FILLS `bookmark_type="insights"` before forwarding
(`workspace.py:1874-1879`); the TS facade forwards the bag and
`LiveQueryService.querySavedReport` (`live-query.ts:537`) applies the same
default. Wire-identical; the translated assertions read the EFFECTIVE bag.

## Discrepancy #10 re-examination (NAMED SITE — packet §5 duty)
**Answer: YES, W3 exposes the ordering — and it is unfixable in TS, so the
ratified "unspecified" ruling should STAND.**

- Exposure path: `create_bookmark` / `update_bookmark` raise
  `BookmarkValidationError(schema_errors)`; `.errors`, `.details.errors` and
  the rendered message all preserve emission order, so a caller CAN depend on
  the order of `S3_UNKNOWN_FIELD` (`extra_forbidden`) rows.
- Measured divergence (2026-08-16, both languages, same input
  `{"displayOptions": {"chartType": "bar", "zz": 1, "2": 2, "10": 3, "1": 4}}`,
  partial mode):
  - Python: `zz, 2, 10, 1` (dict insertion order)
  - TS: `1, 2, 10, zz` (`Object.keys` puts integer-like keys first, ascending)
- Why it cannot be closed: the extra-key walk is
  `for (const key of Object.keys(value))` (`schema-sorting.ts:1316`), but the
  reordering is a property of the JS OBJECT, not of the walk — a `params`
  dict reaching the facade (literal or `JSON.parse`d) has ALREADY lost the
  integer-like keys' insertion order. Only a Map-valued params type could
  preserve it, which would change the public `params` annotation.
- Containment: NON-integer-like unknown keys keep Python's exact order (the
  `zz` row is last in TS too, after the integer-likes); integer-like unknown
  keys stay EXCLUDED from every W3 fuzz domain (harness §iii) per #9/#10.

## R10.9 harness
`throwaway/b6-w3/{wire-edges.ts,RUN.md}` — **checks 45 / failures 0**,
deterministic (no RNG/seed). Coverage table in `RUN.md`. The shard's one
latent defect was found by the Layer-3 translation, not the harness (see [4]).

## Gate/BIND hand-off
- 89 W3 vectors (`b6-packets.md` §1) replay through the real facade; bindings
  are the separate fable BIND task (§11).
- Integrator items: (a) the `workspace-members/shared.ts` extraction touched
  W2's `dashboards.ts` imports; (b) `crud-edge.test.ts`'s 26 todos must be
  filled as W4–W8 land; (c) the `response-validation.ts` alias fix is
  cross-batch (B4-C1 file) and should be re-checked against the corpus at the
  gate — full suite green (186 files / 8,428 tests) after it.
