# B6-W2 notes — dashboards (CRUD + advanced operations)

Packet: `context/phase3/design/b6-packets.md` §4 — 22 members, 38
measured vectors, 10 zero-vector members. Spec of record:
`phase3-playbook.md` v1.1. Corpus pin `70c904dc`. Arbiter: Python
`workspace.py` at support-branch HEAD (11,292 lines), re-read
2026-08-16.

## 0. Inventory (start of shard)

- W1 landed first (`b093180`, TS `main`): `workspace-members/lifecycle.ts`,
  `services/me.ts`, `EntityModel.modelDumpExcludeNone()` (W1-D4), and the
  B6-W1 append-only section ending with the private `#businessContextHost`.
- Already live below the facade (R10.8 — composed, never re-implemented):
  `services/entities/dashboards.ts` (B4-C3, all 22 wire methods, composed
  onto the client at `client.ts:1077+`), `client/response-validation.ts`
  (B4-C1), the Phase-2 `types/entities/dashboards.ts` models
  (`Dashboard`, `BlueprintTemplate`, `BlueprintConfig`, the five `*Params`
  classes).
- No prior W2 work on disk.

## 1. What landed

| file | role |
| --- | --- |
| `packages/core/src/workspace-members/dashboards.ts` (NEW) | all 22 member bodies + the two W2 options interfaces |
| `packages/core/src/workspace.ts` | the `// === B6-W2 dashboard members (W2 owns; append-only) ===` section (22 one-line delegations, appended AFTER W1's section at class end) + the member/type imports + the two options re-exports |
| `packages/core/src/types/entities/model-base.ts` | `modelDumpExcludeNone({byAlias})` — the W1-D4 helper extended, see §2 |
| `packages/core/test/workspace/crud-dashboards.test.ts` (NEW) | Layer-3 translation + the additive blocks (48 tests) |
| `throwaway/b6-w2/{wire-edges.ts,RUN.md}` | R10.9 harness (deleted at the gate; RUN record mirrored in §4) |

`npm run check` green (typecheck ×5 workspaces, eslint, prettier, 182
test files / 8,325 tests, browser smoke). No Python source touched, so
`just check` is not in scope for this shard (only this notes file is
written, per the "Python writes ONLY under conformance/ and
context/phase3/" rule).

## 2. Design decisions (arbiter-visible)

**W2-D1 — `by_alias` lands on the W1-D4 helper, not in the shard.**
`workspace.py` has 21 `model_dump(..., by_alias=True)` sites; three are
W2's (`finalize_blueprint` :4985, `create_rca_dashboard` :5022,
`update_report_link` :5109). Rather than re-derive an alias dump in the
member module (a review finding under R10.8), `EntityModel.modelDumpExcludeNone`
takes an options bag: `modelDumpExcludeNone({byAlias: true})` emits each
declared field under its `EntityFieldSpec.wire` key and threads the flag
into nested models, exactly as pydantic does (`BlueprintFinishParams` has
no alias of its own, but its nested `BlueprintCard.card_type` serializes
as `type` — corpus-verified against
`entities/workspace.finalize_blueprint/...test_finalize_blueprint_sends_card_type_as_type`).
Extras and computed fields have no alias and keep their own key.
**W4–W8 consume this by name** — a shard adding a second alias dump is a
review finding.

**W2-D2 — member bodies live in the module; `workspace.ts` holds
one-liners.** Per packet §2. The bodies are 2–4 lines each (params dump →
client call → guard → `validateResponseModel(s)`), so the module is where
the guards are grep-auditable. Every body takes `client: MixpanelClient`
as its first argument (no host interface needed — unlike W1's
`BusinessContextHost`, no W2 member reads facade state).

**W2-D3 — the `raw is None` guards are ported although unreachable.**
Seven members carry `if raw is None: raise MixpanelHeadlessError("API
returned empty response for X")` (default code `UNKNOWN_ERROR`, packet
Caution #8). In Python the B4 client method raises
`"Unexpected response from X: expected dict, got NoneType"` BEFORE `None`
can reach the facade (`api_client.py:3745-3757` and siblings), so the
branch is dead in both languages. Ported verbatim anyway; typed via
`const raw: unknown = await client.X(...)` so the null test is
meaningful under `tsc --strict`, and locked at the member seam (the
`ADDITIVE: empty-response guards` block + harness group (iv)).

**W2-D4 — result payloads normalize with `toNativeJson` before model
construction.** The B4 client returns the LOSSLESS `JsonValue` tree; the
Phase-2 models validate native values. This is the `client.ts:878`
(`list_workspaces`) precedent and the exact defect W1's harness caught in
`MeService`. Applied at every W2 model site plus the two verbatim
returns (`get_bookmark_dashboard_ids`, `get_dashboard_erf`), which Python
returns as plain `json.loads` output.

**W2-D5 — `add_report_to_dashboard`'s guard.** Python:
`if not isinstance(raw, dict) or "id" not in raw` (`:4832`). Ported as
`!isPlainRecord(raw) || !Object.hasOwn(raw, "id")` — watchlist #13
(prototype discrimination via the shared `isPlainRecord`, never
`typeof`) + R4.8. The message reprs the payload with `pythonRepr` over
the NATIVE tree, so the 204 case reads `{'status': 'ok'}` exactly as
Python does (harness group (iv) asserts the full string).

## 3. Layer-3 translation

`packages/core/test/workspace/crud-dashboards.test.ts` — 48 tests, green.

| Python source | Taken |
| --- | --- |
| `tests/unit/test_workspace_crud.py::TestWorkspaceDashboardCRUD` (:189) | 19 tests, 1:1 |
| `::TestWorkspaceBlueprintCohorts` (:1763) | 1 test |
| `::TestRemoveReportFromDashboard` (:1785) | 1 test |
| `::TestAddReportToDashboard` (:1812) | 3 tests |

Translation seams: `httpx.MockTransport` → the injected-fetch
`fakeTransport`; `_make_workspace(temp_dir, handler)` → `makeWorkspace`
(client over the OAuth session, facade over the service-account
`_TEST_SESSION`, exactly as Python wires it); `temp_dir` dropped (no TS
analog — no config file is touched).

ADDITIVE blocks (clearly headed; B5 Caution #13 pattern, never
substituting for a translated assertion):

1. **zero-vector members (10)** — delegation contracts for
   `favorite/unfavorite/pin/unpin_dashboard`,
   `list_blueprint_templates` (both `include_reports` states),
   `create_blueprint`, `get_blueprint_config`,
   `get_bookmark_dashboard_ids`, `get_dashboard_erf`,
   `update_text_card` (incl. its exclude-none `{}` body). These suites
   are the ONLY behavior lock for those members (packet §1).
2. **`by_alias` bodies** — `finalize_blueprint`, `create_rca_dashboard`,
   `update_report_link`. **Overlap note**: those three vectors come from
   `test_workspace_crud_edge.py::TestRequestBodySerialization` (:92),
   which the packet assigns to W3 as a WHOLE-file translation. W2 lands
   the code, so W2 lands a local lock; W3 should keep its translation
   (duplicate coverage is fine, a missing lock is not).
3. **empty-response guards** (W2-D3) and **response-validation codes**
   (the two corpus-locked `RESPONSE_VALIDATION_ERROR` branches of
   `list_dashboards` / `create_dashboard`, with the byte-exact pydantic
   `missing` error list).

## 4. R10.9 harness — `throwaway/b6-w2/` (RUN record)

`npx vite-node throwaway/b6-w2/wire-edges.ts` → **checks 55, failures 0**
(deterministic; no RNG/seed).

| group | checks |
| --- | ---: |
| (i) delegation equivalence — facade result === client result re-validated through the same model seam (12 members) | 14 |
| (ii) wire status branches — `get_dashboard` 200/404/empty-body/500, `add_report_to_dashboard` 200/400/422 | 7 |
| (iii) mandatory edge set — `18.0, 1.5, true, null, [], "", "𝒳"` through `ids=`, `title`, `duplicate` (+ the `ids=[]` omission) | 22 |
| (iv) every facade-local error branch — 7 empty-response guards, both `add_report` guard flavors (incl. the full repr string), 3 response-validation branches | 12 |

No W2 body defects. Three measured rows (full tables in
`throwaway/b6-w2/RUN.md`, deleted at the gate — reproduced here):

- **`ids=[18.0]`** → Python sends `18.0`, TS sends `18`. `ids` is
  annotated `list[int] | None`, so a float element is OUT OF ANNOTATION
  (ratified Discrepancy #8) and JS cannot spell an integral float
  distinctly (Discrepancy #12's class). Every in-annotation value
  matches via `pythonStr` (R11.7). All other edge rows match
  (`1.5`→`1.5`, `True`→`True`, `None`→`None`, `[]`→`[]`, `""`→``,
  `𝒳`→`𝒳`, `ids=[]` → param omitted).
- **`CreateDashboardParams(duplicate=True)`** → Python coerces to `1`
  (a bool IS an int for pydantic); TS raises. This is the ratified
  port-wide rule R4.12 (`coerce.ts:121`), identical to W1's
  `organization_id=True` row — not a W2 decision. Every other
  `title` / `duplicate` row matches (see RUN.md table).
- **`BlueprintConfig.variables`** — see §5.

## 5. Findings / outbound

1. **Phase-2 model gap — `BlueprintConfig.variables` is unvalidated.**
   Python: `variables: dict[str, str]`; `BlueprintConfig(variables=7)`,
   `(variables=[])`, `(variables={"a": 7})` all raise `ValidationError`
   (measured 2026-08-16). The Phase-2 TS spec
   (`packages/core/src/types/entities/dashboards.ts:709`) declares
   `{ name: "variables", required: true }` with no `kind`/`container`,
   so `get_blueprint_config` happily returns a model whose `variables`
   is `7`. NOT a W2 body defect (the facade composes the shared model
   seam) and NOT vector-observable today (`get_blueprint_config` has 0
   corpus vectors). W2 did not edit a Phase-2 model to avoid a
   cross-shard change; **the review pair / arbiter should place this**
   (candidate owners: a Phase-2 follow-up sweep for scalar-typed dict
   fields across all 125 models, since the gap is generic rather than
   dashboard-specific).
2. **`response-validation.ts:22-27` `TODO(port)` (B5 §8 inbound, owner
   B6)**: W2's CRUD suites exercise only the corpus-locked
   `type: "missing"` rows; the non-missing pydantic wording stays
   unlocked here. Triage stays where the packet put it — the W3 review
   (§13 ledger row).
3. **No new pending api names / no oracle strategies** — all 22 members
   are wire-kind; §11.5 stands.

## 6. Rule audit (self-check before commit)

- R10.8: no request assembly / header merging / URL building / status
  branching in `workspace-members/dashboards.ts` — grep-clean; every
  path string comes from the B4 client.
- R2.13: no `new URL()` in ported code (the two occurrences in the test
  file and the harness are assertion helpers over captured URLs, the
  established B5/W1 test convention).
- R11.7: no bare `trim`/`parseInt`/`Number()`; the only string-rendering
  path is `pythonRepr` (error message) and the client's `pythonStr`
  (`joinIds`).
- Watchlist #6 (truthiness): the one Python `if ids:` lives in the B4
  client (`truthyList`); no facade-local truthiness guard exists.
- Watchlist #13: `isPlainRecord` reused from `client/internals.js` (the
  same module `services/entities/shared.ts` imports).
- R5: codes, not messages — every error assertion checks class + code;
  the two message assertions are the ported Python strings, marked as
  out-of-contract (R5.4).
- Caution #9: no result pre-shaping below the facade — model
  construction happens ONLY here, with the exact `endpoint=` strings
  Python passes.
