# B6-W8 notes — schema registry + enforcement + audit + anomalies + deletion requests

**Packet**: `context/phase3/design/b6-packets.md` §10 (20 members, 51 vectors,
0 zero-vector members). Spec of record: `phase3-playbook.md` v1.1. Arbiter:
`workspace.py:8651-9331` at support-branch HEAD, re-read line-by-line
2026-08-16 (registry :8651-8874, enforcement :8876-9024, auditing :9026-9105,
anomalies :9107-9199, deletion requests :9201-9331).

Status: **DONE** — 20 members live, Layer-3 translated and green, harness run,
`npm run check` green (195 files, 8694 tests; +65 over the W7 baseline of
8629). Vector replay is the BIND task's exit (§11), not this shard's.

## 1. Member inventory (20) — all delegate to B4-C5 client methods (R10.8)

| # | Python member | TS facade | body shape |
|---|---|---|---|
| 1 | `list_schema_registry` :8654 | `listSchemaRegistry` | kwonly forward + models |
| 2 | `create_schema` :8689 | `createSchema` | 3 positionals, opaque passthrough |
| 3 | `create_schemas_bulk` :8722 | `createSchemasBulk` | dump(exclude_none, by_alias) + model |
| 4 | `update_schema` :8760 | `updateSchema` | 3 positionals, opaque passthrough |
| 5 | `update_schemas_bulk` :8793 | `updateSchemasBulk` | dump(exclude_none, by_alias) + models |
| 6 | `delete_schemas` :8830 | `deleteSchemas` | **facade-local guard** + models |
| 7 | `get_schema_enforcement` :8879 | `getSchemaEnforcement` | kwonly forward + model |
| 8 | `init_schema_enforcement` :8913 | `initSchemaEnforcement` | dump + opaque passthrough |
| 9 | `update_schema_enforcement` :8943 | `updateSchemaEnforcement` | dump + opaque passthrough |
| 10 | `replace_schema_enforcement` :8973 | `replaceSchemaEnforcement` | dump + opaque passthrough |
| 11 | `delete_schema_enforcement` :9005 | `deleteSchemaEnforcement` | no-arg + opaque passthrough |
| 12 | `run_audit` :9029 | `runAudit` | **composite** (:9050-9067) |
| 13 | `run_audit_events_only` :9069 | `runAuditEventsOnly` | **composite** (:9088-9104) |
| 14 | `list_data_volume_anomalies` :9110 | `listDataVolumeAnomalies` | kwonly forward + models |
| 15 | `update_anomaly` :9143 | `updateAnomaly` | **plain** dump(by_alias) + passthrough |
| 16 | `bulk_update_anomalies` :9171 | `bulkUpdateAnomalies` | **plain** dump(by_alias) + passthrough |
| 17 | `list_deletion_requests` :9204 | `listDeletionRequests` | no-arg forward + models |
| 18 | `create_deletion_request` :9229 | `createDeletionRequest` | dump + models (FULL list) |
| 19 | `cancel_deletion_request` :9268 | `cancelDeletionRequest` | positional id + models (FULL list) |
| 20 | `preview_deletion_filters` :9296 | `previewDeletionFilters` | dump + opaque list passthrough |

17 of 20 are pure forwards; the three non-forwarding bodies are #6, #12, #13.
Nine members are opaque passthroughs (`:8720`, `:8791`, `:8939`, `:8969`,
`:9001`, `:9023`, `:9169`, `:9198`, `:9328`) returning the client product
verbatim under a `dict[str, Any]` / `list[dict[str, Any]]` annotation.
**Zero empty-response guards** exist in the whole 681-line range
(grep-verified), so `requireResponse` is deliberately unused — the W5/W6/W7
precedent. Packet §10's "`preview_deletion_filters` (:9296) carries a
composite body" is not borne out at HEAD: `:9296-9331` is a plain
dump-and-forward (re-read and recorded here so the review pair does not hunt
for a missing branch).

## 2. Arbiter-visible decisions

- **W8-D1 — `EntityModel.modelDump({byAlias})`, the plain
  `model_dump()` twin (NEW, `types/entities/model-base.ts`).** Two facade
  sites dump WITHOUT `exclude_none`: `update_anomaly` (`:9169`) and
  `bulk_update_anomalies` (`:9198`), both `params.model_dump(by_alias=True)`.
  W1-D4's `modelDumpExcludeNone` cannot express it (it drops `None`s) and
  `toJSON()` cannot either (no aliases, no extras — it mirrors the RECORDER's
  payload shape, not pydantic's dump). Rather than let W8 re-derive a dump
  inline (an R10.8 violation), `modelDump` landed as a sibling of
  `modelDumpExcludeNone` over ONE shared walker (`dumpFields(byAlias,
  excludeNone)` + `dumpValue(...)`); `modelDumpExcludeNone` now delegates to
  it, byte-identical behaviour (whole suite green). pydantic probe (uv,
  2026-08-16), which the harness locks:
  `ReplaceSchemaEnforcementParams(...).model_dump(by_alias=True)` →
  `{…, 'schemaId': None}` while `model_dump(exclude_none=True, by_alias=True)`
  drops `schemaId`; `BulkUpdateAnomalyParams(...).model_dump(by_alias=True)` →
  `{'anomalies': [{'id': 1, 'anomalyClass': 'Event'}], 'status': …}` (nested
  recursion with aliases). For the two ACTUAL W8 params models the two dumps
  coincide (every field is required and non-nullable), so this is a fidelity
  fix, not a behaviour change — recorded so the review pair can see it was
  measured, not assumed. W4's one bare `model_dump()` site
  (`set_flag_test_users`, `:6019`) still uses `toJSON()`; its model
  (`SetTestUsersParams`, a single required `dict[str, str]`, no aliases, no
  extras) makes the two spellings identical, so that shard's module is left
  untouched (never edit another shard's file) — flagged here for the review
  pair as a forward note, not a defect.
- **W8-D2 — recorded divergence, no vector coverage.** When the audit
  metadata carries `{"computed_at": null}`, Python's
  `metadata.get("computed_at", "")` yields `None` (the default fires on
  ABSENCE only) and `AuditResponse(...)` then raises a BARE
  `pydantic_core.ValidationError` — verified by probe (uv, 2026-08-16) — i.e.
  an out-of-contract leak (the member's declared `Raises:` list does not
  include it; Discrepancy #8 territory). The TS twin raises the port's
  standard wrapper for that same pydantic failure,
  `ResponseValidationError` / `RESPONSE_VALIDATION_ERROR`. Same trigger, same
  rejection, different class name. No corpus vector exercises it (all three
  `run_audit` vectors and both `run_audit_events_only` vectors carry either
  `[]` or a well-formed `computed_at` string).
- **Composite ordering is exact.** Both audit bodies port branch-for-branch:
  `if not raw` → explicit `raw.length === 0` (watchlist #6, never `if (!x)`);
  the non-list head raise BEFORE any validation, with
  `type(raw[0]).__name__` supplied by the existing `pythonTypeNameOf`
  (composed from `services/entities/shared.ts`, never re-derived) computed
  over the LOSSLESS value so `1.5` reads `float`, not `int`; the metadata
  pick via `isPlainRecord` (watchlist #13 — prototype discrimination, never
  `typeof`); and `metadata.get("computed_at", "")` as an `Object.hasOwn`
  read (R4.8) so a recorded `null` is NOT swallowed by `??`.
- **Guard-before-side-effects.** `delete_schemas` raises before
  `_require_api_client()` in Python (`:8864-8868`), so the TS twin raises
  before touching `this.client` — locked in both the Layer-3 suite (no
  captured request) and the harness (empty call log). Code is the
  `exceptions.py` constructor default `UNKNOWN_ERROR` (packet Caution #8);
  the message is ported verbatim but is out of contract (R5.4).
- **No new URL(), no header/status logic, no re-derived quoting.** The
  `urllib.parse.quote(..., safe="")` segment encoding for
  `entity_type`/`entity_name`, the `results.anomalies` extraction and the
  `_raw=True` envelope handling all stay in the B4-C5 client (R2.13/R10.8);
  the facade never sees a URL.
- **Key ORDER of dumped bodies** follows Python `model_fields` order (e.g.
  `CreateDeletionRequestParams` emits `fromDate, toDate, eventName`), which
  the Phase-2 field specs already mirror. The corpus records `json_body` with
  SORTED keys, so order is not vector-observable either way — noted because
  the harness's first draft asserted the corpus's sorted spelling and failed.

## 3. R10.9 RUN record — `throwaway/b6-w8/wire-edges.ts`

    npx vite-node throwaway/b6-w8/wire-edges.ts
    checks 88   failures 0

Deterministic: no RNG, no seed, no timers — every case is a hand-built canned
interaction over the injected-fetch seam or a recording stub client.

Coverage, per the packet's four clauses:

1. **(i) Delegation equivalence** (4 probes): `list_schema_registry`,
   `get_schema_enforcement`, `list_deletion_requests` and
   `preview_deletion_filters` — facade result === direct `client.<method>`
   result pushed through the SAME `validateResponseModel(s)` / `toNativeJson`
   seam over the same interaction.
2. **(ii) Wire status branches** (the packet's named pairs, 6 checks):
   `create_schema` 200 / 400 (`QueryError`/`QUERY_FAILED`) / 422
   (same mapping — recorded: the B0 handler maps 4xx uniformly, so 422 is not
   a distinct arm); `run_audit` 200 (violations + `computed_at`) / 500
   (`ServerError`/`SERVER_ERROR`).
3. **(iii) Mandatory edge set** — `18.0`, `1.5`, `true`, `null`, `[]`, `""`,
   `"𝒳"` pushed through every param whose ANNOTATION admits it
   (Discrepancy #8):
   - all seven as VALUES of the two `schema_json: dict[str, Any]` request
     bodies (`create_schema` + `update_schema`), round-tripped through the
     captured body text (14 checks);
   - the two string edges through `query_params: dict[str, str]` — the
     annotation admits strings only — asserted on the encoded query string;
   - all seven (plus a nested copy) through six opaque RESULT passthroughs
     (`create_schema`, `update_schema`, `init_schema_enforcement`,
     `delete_schema_enforcement`, `update_anomaly`,
     `preview_deletion_filters`), JSON-compared verbatim.
   No integer-like unknown keys anywhere (#9/#10). Recorded caveat: the
   `18.0` spelling narrows to `18` on both the request and result side
   because TS has one number type and `native()` collapses `JsonNumber` —
   the same behaviour every earlier shard's passthroughs have (Discrepancy
   #12 is an output-TEXT rule; the JSON value is unchanged).
4. **(iv) Every W8-local branch** (64 checks):
   - the `delete_schemas` guard: raises `MixpanelHeadlessError`/
     `UNKNOWN_ERROR` with an EMPTY call log, and all three allowed filter
     combinations forward `{entity_type, entity_name}` with `?? null`;
   - both `run_audit*` bodies: empty `raw`, 1-element `raw`, non-dict
     metadata, metadata without `computed_at`, a 3-element `raw` (extra
     elements ignored), the non-list head over all six CPython type names
     (`dict`, `str`, `int`, `float`, `bool`, `NoneType`) with the exact
     message text, the error code, and a malformed violation →
     `RESPONSE_VALIDATION_ERROR`;
   - the three dump spellings incl. the W8-D1 `schemaId: null` retention,
     nested alias recursion, and the two anomaly bodies observed on the wire;
   - the `?? null` kwarg forwards for the three keyword-only readers;
   - `RESPONSE_VALIDATION_ERROR` from a malformed 200 for all nine
     model-validating members, plus the `details.model` name for three;
   - the positive typed twins (anomalies, cancel, bulk create/patch,
     events-only audit, replace-enforcement passthrough).

## 4. Layer-3 translation

Two files, 65 tests, all green.

- `packages/core/test/workspace/workspace-schemas.test.ts` — the WHOLE of
  `tests/unit/test_workspace_schemas.py` (877 lines, 6 classes): **27
  translated** + **6 ADDITIVE** delegation-contract tests.
- `packages/core/test/workspace/workspace-governance.test.ts` — the WHOLE of
  `tests/unit/test_workspace_governance.py` (781 lines, 14 classes
  :194-:781): **22 translated** + **10 ADDITIVE** (the `run_audit` composite
  branches, which Python's suite never reaches, and the delegation/dump
  contracts).

R10.2 notes — nothing dropped or loosened:
- `temp_dir` has no TS analog (no config file is touched) and is dropped
  everywhere — the W6/W7 precedent.
- Python's `hasattr(schemas[0], "customField") or "customField" in
  model_extra` (`test_list_schemas_extra_fields_preserved`, :271) becomes an
  assertion on `__extras["customField"]`, the port's `__pydantic_extra__`
  mirror.
- `pytest.raises(MixpanelHeadlessError, match="entity_name requires
  entity_type")` translates as BOTH `rejects.toBeInstanceOf(...)` (the class
  is the contract, R5.4) and `rejects.toThrow(/…/)` (because Python's
  `match=` asserts it too), plus an ADDITIVE assertion that the code is
  `UNKNOWN_ERROR` and that no request was captured.
- The three URL-shape assertions (`"schemas/event" in url`,
  `"My Event / Test" not in url`, `"$user" not in url or "%24user" in url`)
  are kept verbatim as substring checks over the captured URL — they assert
  the B4 client's quoting, which the facade must not disturb.
- The ADDITIVE `ReplaceSchemaEnforcementParams` construction fills every
  required field (the model requires all but `schema_id`); the first draft
  passed `rule_event` alone and failed red, which is exactly what the
  translation step is for.

## 5. Files touched

TS (`main`):
- `packages/core/src/workspace-members/schemas-audit.ts` (NEW, 20 members +
  the shared `auditResponseFrom` composite helper)
- `packages/core/src/workspace.ts` — the append-only
  `// === B6-W8 … (W8 owns; append-only) ===` section (20 one-line
  delegations) and the import / re-export block (member functions, the four
  options interfaces, the 16 entity types). No other shard's section touched.
- `packages/core/src/types/entities/model-base.ts` — W8-D1: the new
  `modelDump()` plus the shared `dumpFields`/`dumpValue` walkers that
  `modelDumpExcludeNone` now delegates to.
- `packages/core/test/workspace/workspace-schemas.test.ts` (NEW, 33 tests)
- `packages/core/test/workspace/workspace-governance.test.ts` (NEW, 32 tests)
- `throwaway/b6-w8/wire-edges.ts` (NEW, 88 checks)

Python (`ts-port/phase2-contract-support`): this notes file only (no source
or conformance change; `just check` therefore not required — no Python code
touched). Two read-only `uv run python` probes were used as the arbiter for
W8-D1 and W8-D2.

## 6. Forward notes for the BIND task (§11) and the review pair

- All 20 W8 member names are **wire_api** kind; none is a property, so all 20
  bind, and all 20 carry vectors (no straggler ratchet needed here).
- kwarg→options mapping the binding needs (Python key spellings kept
  verbatim — packet Caution #6):
  `list_schema_registry(entity_type=)`,
  `delete_schemas(entity_type=, entity_name=)`,
  `get_schema_enforcement(fields=)`,
  `list_data_volume_anomalies(query_params=)` are single options bags;
  `create_schema` / `update_schema` take THREE positionals
  (`entity_type`, `entity_name`, `schema_json`);
  `cancel_deletion_request` takes the `request_id` positional; every
  `params`-taking member takes the model positionally.
- Corpus shapes verified against the pin 2026-08-16 (51 vectors): inputs are
  keyed by Python parameter name; `params` arrives as a `$type`-tagged model
  payload; four vectors expect `ResponseValidationError` /
  `RESPONSE_VALIDATION_ERROR` (`list_schema_registry`, `delete_schemas`,
  `list_deletion_requests`, `cancel_deletion_request`) — all four run through
  `validateResponseModel(s)` with the endpoint strings above.
- No vector covers the `delete_schemas` guard, the audit non-list-head raise,
  or W8-D2; those are Layer-3 + harness locks only. If the gate's referee
  wants a wire-authored vector for the guard, it must expect zero
  interactions.
