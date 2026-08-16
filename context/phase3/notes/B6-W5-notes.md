# B6-W5 notes — annotations + webhooks + alerts (23 facade members)

Packet: `context/phase3/design/b6-packets.md` §7 (W5). Spec of record:
`phase3-playbook.md` v1.1. Behavior arbiter: Python `workspace.py`
:6462-7196 at `ts-port/phase2-contract-support` HEAD (re-read
line-by-line 2026-08-16).

Status: **DONE** — 23/23 members live, Layer-3 translations green,
`npm run check` green, harness RUN record below.

## 1. Inventory (start of task)

- W1–W4 already landed on TS `main` (`3cfe49a` B6-W4). `workspace.ts`
  = 4,116 lines; last in-class section marker
  `// === B6-W4 feature-flag + experiment members ... ===` at :3690.
- `workspace-members/` held `lifecycle.ts`, `dashboards.ts`,
  `bookmarks-cohorts.ts`, `flags-experiments.ts`, `shared.ts`.
  W5 adds `annotations-webhooks-alerts.ts`.
- Everything below the facade is LIVE: `services/entities/annotations.ts`
  (7 methods), `webhooks.ts` (5), `alerts.ts` (11) — exactly the 23
  W5 members, 1:1 by name (B4-C4). Result models all present in
  `types/entities/{annotations,webhooks,alerts}.ts`.
- Vector census re-measured 2026-08-16 over the pinned corpus: the 23
  member names sum to **43** vectors — matches the packet §1 W5 row.

## 2. Findings from the Python re-read (`workspace.py:6462-7196`)

Arbiter-visible; all four are recorded in the module header of
`packages/core/src/workspace-members/annotations-webhooks-alerts.ts`.

1. **All 23 members are PURE FORWARDS.** The packet §7 Scope predicted
   that "`test_alert`, `get_alert_screenshot_url`,
   `validate_alerts_for_bookmark` have more-than-forward bodies"; at
   HEAD they do not (`:7118-7119`, `:7146-7149`, `:7179-7183` are each
   `client = self._require_api_client()` → optional
   `body = params.model_dump(exclude_none=True)` → the client call →
   `validate_response_model(...)` or a bare return). There is NO
   composite body anywhere in the range: no multi-step orchestration,
   no conditional query assembly (contrast W4's `get_flag_history`),
   no decision-payload shaping. **Packet prediction corrected; no
   branch was dropped.**
2. **ZERO empty-response guards.** `grep 'if raw'` / `'is None:'` /
   `'raise '` over :6462-7196 returns nothing — the shard has no
   `if raw is None: raise MixpanelHeadlessError(...)` (packet Caution
   #8) at all. The shared `requireResponse` helper
   (`workspace-members/shared.ts`) is therefore deliberately UNUSED in
   this module; adding it would invent a branch Python does not have.
   W5 is the first shard without any such guard (W2/W3/W4 all had
   several).
3. **`test_alert` is the shard's one opaque passthrough** — `:7118-7119`
   returns `client.test_alert(body)` verbatim under a `dict[str, Any]`
   annotation with no `validate_response_model` call. The TS twin
   returns `native(raw) as Record<string, unknown>` — the W4
   `list_erf_experiments` precedent (`flags-experiments.ts:605-610`),
   kept identical so no shard re-derives the passthrough spelling.
4. **No R11.7 / watchlist-#6 / watchlist-#13 sites.** No `int(str)`, no
   `.strip()`, no `isinstance(x, dict)` and no truthiness guard exists
   in the range, so `pythonInt`/`pythonStrip`/`isPlainRecord` have
   nothing to bind to in this module. Recorded so the review pair's
   grep audit does not read their absence as an omission.

### kwargs → options mapping (R3.3/R3.8; keys keep the Python spelling)

| member | positional | options bag |
| --- | --- | --- |
| `list_annotations` | — | `{from_date, to_date, tags}` |
| `list_alerts` | — | `{bookmark_id, skip_user_filter}` |
| `get_alert_count` | — | `{alert_type}` |
| `get_alert_history` | `alert_id` | `{page_size, next_cursor, previous_cursor}` |

All other 19 members are positional-only (max 2 positionals:
`(entityId, params)`), matching the api-map `ts_signature` rows.

Python forwards the raw `None` defaults straight through to the client
(`:6871-6872`, `:7076-7080`), and the CLIENT owns the `is not None`
gating (B4-C4), so the facade maps `?? null` rather than dropping
absent keys — R3.9, and never re-derives the gate (R10.8). The
consequence that matters: **`skip_user_filter: false` must survive**
(`False is not None`, sent on the wire as `"false"`), so no truthiness
drop anywhere (watchlist #6). Locked in both the Layer-3 additive
section and harness group (iv).

### Dates (watchlist #5 / packet Caution #12)

`list_annotations`'s `from_date`/`to_date` and
`CreateAnnotationParams.date` are STRINGS end-to-end; no `Date` is
constructed in the request path. Harness group (iii) asserts the
query params reach the wire byte-for-byte
(`fromDate=2026-01-01` / `toDate=2026-03-31`) and that a
`"2026-03-31 12:00:00"` body date is forwarded verbatim.

## 3. RUN record — `throwaway/b6-w5/`

Mirror of `throwaway/b6-w5/RUN.md` (deleted at the B6 gate, §12.6).

```
npx vite-node throwaway/b6-w5/wire-edges.ts
checks 62   failures 0
```

Deterministic (no RNG, no seed): every case is a hand-built canned
interaction over the injected-fetch seam. One file (`wire-edges.ts`) —
all-wire shard, so no `py-side.py` differential half (§11.5).

| group | cases |
| --- | --- |
| (i) delegation equivalence | `list_annotations`, `get_annotation`, `list_annotation_tags`, `list_webhooks`, `test_webhook`, `list_alerts`, `get_alert_count`, `get_alert_history`, `get_alert_screenshot_url`, `test_alert` — facade result === direct client result re-validated through the SAME model seam (10) |
| (ii) wire status branches | `create_annotation` 200 / 400 (`QueryError`/`QUERY_FAILED`); `test_webhook` 200 / 429-exhausted (`RateLimitError`/`RATE_LIMITED` + a retry-count assertion) / 500 (`ServerError`/`SERVER_ERROR`) (6) |
| (iii) edge set | `18.0`, `1.5`, `true`, `null`, `[]`, `""`, `"𝒳"` through the alert `condition` dict (7) and `bookmark_params` (7) — the shard's two `dict[str, Any]` param annotations, #8 boundary, NO integer-like unknown keys per #9/#10; plus the two watchlist-#5 date-string checks (2) |
| (iv) W5-local branches | the four option-bag `?? null` forwards in default + populated arms incl. explicit-`false` (8); the `exclude_none` drop on all nine dumping members (9); `RESPONSE_VALIDATION_ERROR` for eleven malformed-200 shapes (11); the four void members (1 batched); `test_alert` verbatim passthrough (1) |

Harness observations beyond §2:

- **`ValidateAlertsForBookmarkResponse` accepts `{}`** — both declared
  fields carry defaults (`alert_validations=[]`, `invalid_count=0`), so
  its malformed-200 probe uses a type violation
  (`{"invalid_count": "nope"}`) rather than an empty body.
- **No #12 exposure in this shard's vectors.** `test_alert`'s single
  vector expects `{"status": "sent"}` — no float in either direction —
  and no W5 vector asserts a request body containing an integral float.

## 4. Files landed

TS repo (`main`):

- `packages/core/src/workspace-members/annotations-webhooks-alerts.ts`
  (NEW — 23 member functions + 4 options interfaces)
- `packages/core/src/workspace.ts` — the append-only
  `// === B6-W5 annotation + webhook + alert members (W5 owns;
  append-only) ===` section (23 one-line delegations) + the member/type
  imports and the four `Workspace*Options` re-exports (the B5 export
  pattern `wire-workspace.ts` consumes)
- `packages/core/test/workspace/workspace-annotations.test.ts` (18)
- `packages/core/test/workspace/workspace-webhooks.test.ts` (13)
- `packages/core/test/workspace/workspace-alerts.test.ts` (22)
- `throwaway/b6-w5/{wire-edges.ts,RUN.md}` (deleted at the gate)

Layer-3 coverage: the WHOLE of `tests/unit/test_workspace_annotations.py`
(2 classes, 14 tests), `test_workspace_webhooks.py` (2 classes, 9) and
`test_workspace_alerts.py` (2 classes, 15) = 38 translated tests, plus
15 clearly-headed ADDITIVE delegation-contract tests (B5 Caution #13 /
packet §0.2) that never substitute for a translated Python assertion.
53 tests total, all green.

## 5. Outbound notes for the BIND task (§11) and the review pair

1. **No new deferrals.** W5 opened no `TODO(port)` markers and consumed
   no seam beyond the live B4-C4 client methods.
2. **BIND names**: all 23 W5 members are `wire_api` kind; the options
   bags take the Python kwarg spellings verbatim, so
   `wire-workspace-entities.ts` can map `call.input` keys 1:1 (packet
   Caution #6). The only two shapes needing care are the entity-model
   params (`$type`-tagged in `call.input`, constructed via `fromDict`)
   and `test_alert`'s opaque record result (no `toVectorPayload()` —
   it is a plain record, not a model).
3. **`test_alert` vector shape verified** against the pinned corpus:
   `entities/workspace.test_alert/...test_test_alert` sends
   `CreateAlertParams` with `notification_windows: null` and expects
   the request body to OMIT that key — i.e. the `exclude_none` dump is
   vector-observable here. Locked in Layer-3 + harness group (iv).
