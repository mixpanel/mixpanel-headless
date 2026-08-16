# B6-W7 notes — drop filters + custom properties + lookup tables + custom events

**Packet**: `context/phase3/design/b6-packets.md` §9 (24 members, 44 vectors,
1 zero-vector member `upload_lookup_table`). Spec of record: `phase3-playbook.md`
v1.1. Arbiter: `workspace.py:7583-8525` at support-branch HEAD, re-read
2026-08-16 (drop filters :7583-7737, custom properties :7739-7952, lookup
tables :7954-8361, custom events :8363-8525).

Status: **DONE** — 24 members live, Layer-3 translated and green, harness run,
`npm run check` green (193 files, 8629 tests). Vector replay is the BIND task's
exit (§11), not this shard's.

## 1. Member inventory (24) — all delegate to B4-C5 client methods (R10.8)

| # | Python member | TS facade | body shape |
|---|---|---|---|
| 1 | `list_drop_filters` :7586 | `listDropFilters` | forward + `validateResponseModels` |
| 2 | `create_drop_filter` :7613 | `createDropFilter` | plain dump + models |
| 3 | `update_drop_filter` :7648 | `updateDropFilter` | plain dump + models |
| 4 | `delete_drop_filter` :7682 | `deleteDropFilter` | forward + models |
| 5 | `get_drop_filter_limits` :7711 | `getDropFilterLimits` | forward + model |
| 6 | `list_custom_properties` :7742 | `listCustomProperties` | **`displayFormula` re-raise branch** |
| 7 | `create_custom_property` :7791 | `createCustomProperty` | dump(by_alias, mode=json → W7-D4) + model |
| 8 | `get_custom_property` :7831 | `getCustomProperty` | forward + model |
| 9 | `update_custom_property` :7861 | `updateCustomProperty` | dump(by_alias) + model |
| 10 | `delete_custom_property` :7897 | `deleteCustomProperty` | void forward |
| 11 | `validate_custom_property` :7918 | `validateCustomProperty` | dump(by_alias) + opaque passthrough |
| 12 | `list_lookup_tables` :7957 | `listLookupTables` | kwonly forward + models |
| 13 | `upload_lookup_table` :7989 | `uploadLookupTable` | **5-step orchestrator + poll loop (W7-D1/D2)** |
| 14 | `mark_lookup_table_ready` :8146 | `markLookupTableReady` | hand-built form data + model |
| 15 | `get_lookup_upload_url` :8190 | `getLookupUploadUrl` | positional default + model |
| 16 | `get_lookup_upload_status` :8222 | `getLookupUploadStatus` | opaque passthrough |
| 17 | `update_lookup_table` :8247 | `updateLookupTable` | plain dump + model |
| 18 | `delete_lookup_tables` :8281 | `deleteLookupTables` | void forward |
| 19 | `download_lookup_table` :8302 | `downloadLookupTable` | kwonly forward, `Uint8Array` |
| 20 | `get_lookup_download_url` :8337 | `getLookupDownloadUrl` | string forward |
| 21 | `create_custom_event` :8366 | `createCustomEvent` | `toFormBody()` (W7-D3) + model |
| 22 | `list_custom_events` :8409 | `listCustomEvents` | forward + models |
| 23 | `update_custom_event` :8436 | `updateCustomEvent` | dump(by_alias) + model |
| 24 | `delete_custom_event` :8494 | `deleteCustomEvent` | void forward |

21 of 24 are pure forwards; the three non-forwarding bodies are #6, #13, #14.
**Zero empty-response guards** exist in the whole 943-line range (grep-verified),
so `requireResponse` is deliberately unused — the W5/W6 precedent.

## 2. Arbiter-visible decisions

- **W7-D1 (packet-mandated) — `readFile` seam.** `Path(params.file_path)
  .read_bytes()` (`:8044`) becomes `WorkspaceOptions.readFile?: (path) =>
  Promise<Uint8Array>`; the default `unportedReadFile()` throws
  `MixpanelHeadlessError` code **`UNPORTED_FILE_READ_SEAM`** with
  `details.seam = "readFile"` — the W1 `UNPORTED_RESOLVER_SEAM` shape.
  `TODO(port): B8` wires `node:fs` in `packages/node`.
- **W7-D2 — the poll clock.** `_poll_lookup_upload` (`:8099-8102`) mixes
  `time.monotonic()` with `time.sleep()`. The sleep rides the client's EXISTING
  injected seam (`client.core.sleep`) with the single seconds→ms conversion at
  the call site (R2.12); the deadline rides a new
  `WorkspaceOptions.monotonic?: () => number` (SECONDS), default
  `Date.now() / 1000`. **Sanctioned micro-deviation**: `Date.now()` is a wall
  clock, so a mid-poll system-clock adjustment shifts the deadline where CPython's
  monotonic source would not. No monotonic source exists in the runtime-agnostic
  core (`tsconfig` `types: []`, no DOM lib → `performance` is untyped); the seam
  lets `packages/node`/tests inject one, and every Layer-3/harness poll test does
  exactly that (virtual clock, no real timers — playbook risk #4).
- **W7-D3 — `CreateCustomEventParams.toFormBody()`** landed on the Phase-2 model
  (`types/entities/data-governance.ts`), mirroring Python's `types.py:4929-4942`
  where the MODEL owns the serializer. Implemented over the existing
  `pythonJsonDumps` (R10.8 — CPython `json.dumps` defaults: space after every
  colon/comma, `ensure_ascii=True`; `JSON.stringify` would differ on BOTH).
- **W7-D4 — `mode="json"` is a no-op in the TS twin.** `create_custom_property`
  (`:7825`) is the facade's ONLY `mode="json"` dump. Its one Python effect on
  `CreateCustomPropertyParams` is converting the `str`-`Enum` `resource_type`
  (`types.py:5333`) to a plain string; the TS enum is already a plain string at
  runtime (`types/enums.ts:114-118`) and nested models recurse in BOTH pydantic
  modes. Recorded, not modelled: no `modeJson` flag added to
  `modelDumpExcludeNone`. Locked by a harness check on the exact dumped body.
- **W7-D5 (cross-shard fidelity fix, flagged for the review pair) — Phase-2
  model bug: `CreateDropFilterParams.filters` was non-nullable.** Python
  `filters: Any` (`types.py:5276`) is REQUIRED but nullable — pydantic v2's bare
  `Any` admits `None`. Probe (uv, 2026-08-16):
  `CreateDropFilterParams(event_name="e", filters=None).model_dump(exclude_none=True)`
  → `{'event_name': 'e'}`, while omitting the key raises `ValidationError`. The
  TS spec said `{ name: "filters", required: true }`, which rejected an explicit
  `null` with `RESPONSE_VALIDATION_ERROR`. Fixed to `nullable: true` with the
  probe recorded in a code comment. **Scope**: this is the ONLY bare required
  `Any` field in the whole Python model set (`grep -nE '^    [a-z_]+: Any$'
  types.py` → one hit), so the fix is complete, not a sample of a class. Found by
  the R10.9 edge set (`filters=None`), which is exactly what that edge exists for.

## 3. R10.9 RUN record — `throwaway/b6-w7/wire-edges.ts`

    npx vite-node throwaway/b6-w7/wire-edges.ts
    checks 56   failures 0

Deterministic: no RNG, no seed — every case is a hand-built canned interaction
over the injected-fetch seam; the poll loop rides a virtual clock (sleep advances
`monotonic`), so no real timer is used anywhere.

Coverage, per the packet's four clauses:

1. **(i) Delegation equivalence** (4 probes): `list_drop_filters`,
   `get_custom_property`, `list_lookup_tables` and `validate_custom_property` —
   facade result === direct `client.<method>` result pushed through the SAME
   `validateResponseModel(s)` / `toNativeJson` seam over the same interaction.
2. **(ii) Wire status branches** (5): `create_drop_filter` 200 / 400
   (`QueryError`/`QUERY_FAILED`); `download_lookup_table` 200 (bytes) / 404
   (`QueryError`) / 500 (`ServerError`/`SERVER_ERROR`).
3. **(iii) Mandatory edge set** — `18.0`, `1.5`, `true`, `null`, `[]`, `""`,
   `"𝒳"` pushed through every param whose ANNOTATION admits it (Discrepancy #8):
   - all seven through `CreateDropFilterParams.filters` (`Any`; `null` correctly
     vanishes under `exclude_none` — the W7-D5 finding);
   - `""` / `"𝒳"` through `UpdateDropFilterParams.event_name` (`str | None`) with
     `active=true`;
   - all seven inside the two `dict[str, Any]` opaque passthroughs
     (`get_lookup_upload_status`, `validate_custom_property`) — verbatim,
     JSON-compared;
   - `1.5` / `18.0` through the shard's ONLY float params (`poll_interval`,
     `max_poll_seconds`) driving a real 12-iteration poll to SUCCESS;
   - `""` / `"𝒳"` through the `mark_lookup_table_ready` form-data builder.
   No integer-like unknown keys anywhere (#9/#10).
4. **(iv) Every W7-local branch** (43 checks):
   - `list_custom_properties` re-raise: the `displayFormula` arm (new
     `QueryError`, message, `statusCode`/`requestMethod`/`requestUrl` carried,
     `cause` chained) + all four pass-through arms (other field, absent
     `response_body`, non-dict `response_body`, non-`QueryError`);
   - upload orchestration: sync-complete (3 calls in order), form body with and
     without `data-group-id`, the signed-URL PUT receiving the `readFile` bytes,
     the `name` back-fill on a `{id}`-only register response, async
     poll-then-ready, `SUCCESS`-with-non-dict-result → `INVALID_RESPONSE`,
     `FAILURE`/`REVOKED` → `UPLOAD_FAILED`, `NOTFOUND` → `UPLOAD_NOT_FOUND`,
     deadline → `UPLOAD_TIMEOUT`, absent `uploadStatus` → UNKNOWN keeps polling,
     and the timeout message rendering `after 300.0s` (`pythonFloatStr`, which
     sidesteps Discrepancy #12 at this site);
   - the `readFile` seam default → `UNPORTED_FILE_READ_SEAM`;
   - all four dump/serialize spellings (plain, `by_alias`, `by_alias`+mode=json,
     `to_form_body` with an astral escape);
   - `RESPONSE_VALIDATION_ERROR` from a malformed 200 for five validated members
     — plus the recorded exception: `get_lookup_upload_url` raises the B4
     client's `MISSING_FIELD` guard FIRST and never reaches the model seam;
   - the three void members resolving `undefined`.

## 4. Layer-3 translation — `packages/core/test/workspace/governance-data.test.ts`

62 tests, all green. **39 translated** from the 24 W7-owned classes of
`tests/unit/test_workspace_data_governance.py` (the class list and line cites are
in the file header); **23 additive**, in three clearly-headed `ADDITIVE:` blocks
(B5 Caution #13): the `displayFormula` branch (5, no Python coverage exists), the
`toFormBody` spelling (2), the upload seams/poll arms (8) and the per-member
delegation contracts (8).

R10.2 notes — nothing dropped or loosened:
- `temp_dir` has no TS analog and is dropped everywhere EXCEPT
  `TestUploadLookupTable`, where Python's real tmp CSV becomes the injected
  `readFile` seam returning the identical bytes (W7-D1).
- Python's three URL-capturing tests assert only the RESULT
  (`list_lookup_tables(data_group_id=5)` :1402, `get_lookup_upload_url` :1698,
  `download_lookup_table` :1807). The translations keep those assertions AND add
  a clearly-marked ADDITIVE param-spelling assertion over the captured URL.
- `pytest.raises(AuthenticationError)` → `rejects.toBeInstanceOf(AuthenticationError)`
  (the class, not the message — R5.4).
- `pytest.raises(..., match="timed out"|"failed")` → `rejects.toThrow(/timed out/)`
  / `/failed/`; the codes (`UPLOAD_TIMEOUT`, `UPLOAD_FAILED`) are additionally
  locked in the ADDITIVE block, since codes — not messages — are the contract.

## 5. Files touched

TS (`main`):
- `packages/core/src/workspace-members/governance-data.ts` (NEW, 24 members)
- `packages/core/src/workspace.ts` — the append-only
  `// === B6-W7 … (W7 owns; append-only) ===` section (24 one-line delegations +
  the `#lookupUploadSeams` getter), the import/re-export block, two
  `WorkspaceOptions` members (`readFile`, `monotonic`), two private fields + two
  constructor lines, and one optional `info?` on `WorkspaceLogger` (the single
  `logger.info` site at `workspace.py:8062`).
- `packages/core/src/types/entities/data-governance.ts` — `toFormBody()` (W7-D3)
  and the `filters` nullability fix (W7-D5).
- `packages/core/test/workspace/governance-data.test.ts` (NEW, 62 tests)
- `throwaway/b6-w7/wire-edges.ts` (NEW, 56 checks)

Python (`ts-port/phase2-contract-support`): this notes file only (no source or
conformance change; `just check` therefore not required — no Python code touched).

## 6. Forward notes for the BIND task (§11) and the review pair

- All 24 W7 member names are **wire_api** kind; none is a property, so all 24
  bind. `upload_lookup_table` has ZERO vectors but must still be bound (§11.1
  straggler ratchet) — the binding needs a `readFile` seam on the facade twin
  (`workspaceFromSession`), otherwise any future authored vector throws
  `UNPORTED_FILE_READ_SEAM`. Recommend wiring `readFile` and `monotonic` in
  `wire-workspace.ts` from the rig shims (`shims.monotonic()` is already the
  virtual monotonic clock the runner owns) rather than leaving the defaults.
- kwarg→options mapping the binding needs: `list_lookup_tables(data_group_id=)`,
  `download_lookup_table(file_name=, limit=)`, `upload_lookup_table(poll_interval=,
  max_poll_seconds=)` are options bags with the Python key spellings;
  `get_lookup_upload_url(content_type)` is POSITIONAL with a `"text/csv"` default.
- `download_lookup_table` returns `bytes` in Python and `Uint8Array` in TS — the
  codec twin needs the recorded bytes spelling (the two Python tests assert the
  content, so the corpus vectors presumably carry a base64/latin-1 form; check
  before binding).
