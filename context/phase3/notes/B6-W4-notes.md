# B6-W4 notes — feature flags + experiments (23 facade members)

Packet: `context/phase3/design/b6-packets.md` §6 (+ §0 batch invariants).
Spec of record: `phase3-playbook.md` v1.1. Arbiter: Python at
`ts-port/phase2-contract-support` HEAD (`workspace.py:5751-6461`).

Status: DONE (module + Layer-3 + harness). Vector green is the BIND
task's exit (packet §11), charged back here on failure.

## 1. Scope

23 members, **40 corpus vectors** (re-measured 2026-08-16 against the
pinned corpus `70c904dc` — matches the packet §1 row exactly). Zero
zero-vector members, so every member also has a translated Python
assertion behind it.

| group | members | py def (HEAD, verified) |
|---|---|---|
| FEATURE FLAG CRUD | `list_feature_flags` :5753, `create_feature_flag` :5784, `get_feature_flag` :5817, `update_feature_flag` :5848, `delete_feature_flag` :5888 | ✓ |
| FEATURE FLAG LIFECYCLE | `archive_feature_flag` :5913, `restore_feature_flag` :5934, `duplicate_feature_flag` :5963 | ✓ |
| FEATURE FLAG OPERATIONS | `set_flag_test_users` :5996, `get_flag_history` :6021, `get_flag_limits` :6065 | ✓ |
| EXPERIMENT CRUD | `list_experiments` :6096, `create_experiment` :6125, `get_experiment` :6158, `update_experiment` :6189, `delete_experiment` :6227 | ✓ |
| EXPERIMENT LIFECYCLE | `launch_experiment` :6252, `conclude_experiment` :6279, `decide_experiment` :6315 | ✓ |
| EXPERIMENT MANAGEMENT | `archive_experiment` :6354, `restore_experiment` :6375, `duplicate_experiment` :6402, `list_erf_experiments` :6441 | ✓ |

Vector distribution (measured): `list_feature_flags` 5, `list_experiments` 4,
`get_feature_flag` 3, `get_experiment`/`set_flag_test_users`/`get_flag_limits`/
`get_flag_history`/`duplicate_experiment`/`delete_feature_flag`/
`create_feature_flag`/`conclude_experiment` 2 each, the remaining 12 members
1 each. Σ = 40. Four of them (`get_experiment`, `get_feature_flag`,
`list_experiments`, `list_feature_flags`) live in
`corpus/entities/test_workspace_crud_edge.jsonl` and are the
`TestCodedResponseValidationCodes` arms — W3 owns that file's Layer-3
translation, W4 owns the members they exercise.

## 2. Files

- `packages/core/src/workspace-members/flags-experiments.ts` (NEW, 23 members)
- `packages/core/src/workspace.ts` — `// === B6-W4 feature-flag + experiment
  members (W4 owns; append-only) ===` section + the import block and the
  four `Workspace*Options` re-exports
- `packages/core/test/workspace/workspace-flags.test.ts` (26 tests)
- `packages/core/test/workspace/workspace-experiments.test.ts` (21 tests)
- `throwaway/b6-w4/{wire-edges.ts,RUN.md}` (removed at the gate)

Nothing below the facade was touched (R10.8): `services/entities/flags.ts`
and `experiments.ts` (B4-C4), `response-validation.ts`,
`types/entities/{feature-flags,experiments}.ts` (Phase 2) are all consumed
as-is. `workspace-members/shared.ts` (`requireResponse` / `native`, W3's
extraction) is reused, not re-derived.

## 3. Decisions

**W4-D1 — kwargs→options (R3.3/R3.8/Caution #6).** Four members carry a
keyword-only tail and therefore an options bag whose keys keep the PYTHON
spelling:

| member | positional | options bag |
|---|---|---|
| `list_feature_flags` | — | `{ include_archived }` |
| `list_experiments` | — | `{ include_archived }` |
| `get_flag_history` | `flagId` | `{ page, page_size }` |
| `conclude_experiment` | `experimentId` | `{ params }` |

Everything else is positional. Note `duplicate_experiment(experiment_id,
params)` — `params` is a REQUIRED POSITIONAL in Python (the api-map row
agrees, and `test_workspace_experiments.py` calls it both ways: `params=`
at :417 and positionally at :438), so TS keeps it positional. The
recorder replays kwargs by name, so the binding maps `call.input.params`
into the second positional slot for that one member; recorded here for
the BIND task.

**W4-D2 — the two non-forwarding bodies, ported branch-for-branch.**

1. `get_flag_history` (`:6053-6060`) builds `query_params: dict[str, str]`
   by adding `page` when `page is not None` and `str(page_size)` when
   `page_size is not None`, then passes `params=query_params if
   query_params else None`. Ported literally: explicit `!== null` tests
   (never `if (!x)` — watchlist #6), `pythonStr` for `str(page_size)`
   (R11.7 forbids bare `String()`), and the empty-dict→`null` collapse
   spelled as `Object.keys(...).length > 0 ? queryParams : null`. All
   five arms are locked in the harness and three in the Layer-3 additive
   section.
2. `conclude_experiment` (`:6300`): `body = params.model_dump(exclude_none=True)
   if params else {}`. A pydantic `BaseModel` defines neither `__bool__`
   nor `__len__`, so `if params` is an identity test against `None`, NOT
   a truthiness test on the model's contents — an
   `ExperimentConcludeParams()` with every field unset is TRUTHY in
   Python and yields `{}` via the exclude-none dump, not via the
   `else` arm. Ported as an explicit null check; the harness pins the
   distinction ("conclude_experiment empty-params body").

**W4-D3 — `set_flag_test_users` is the shard's ONE bare `model_dump()`**
(`:6019`, no `exclude_none`). The faithful TS twin is `toJSON()`
(`model-base.ts:508`), the dump that keeps `None` as `null`;
`modelDumpExcludeNone` would be the wrong spelling (R3.5 —
absent-vs-null is vector-observable). `SetTestUsersParams` declares a
single required non-nullable field, so the two dumps coincide on every
reachable input, but the spelling follows the Python call. Both vectors
(`users: {on,off}` and `users: {}`) exercise it.

**W4-D4 — empty-response guards exist on SIX members only.** `create_/get_/
update_feature_flag` (`:5810`, `:5842`, `:5878`) and `create_/get_/
update_experiment` (`:6151`, `:6183`, `:6221`). The lifecycle and
management members (`restore_*`, `duplicate_*`, `launch_*`, `conclude_*`,
`decide_*`, `get_flag_history`, `get_flag_limits`) carry NO guard in
Python and carry none here — a shard that adds one would diverge on a
`None` payload. Message text ported verbatim, code = the
`exceptions.py` ctor default `UNKNOWN_ERROR` (Caution #8).

**W4-D5 — `list_erf_experiments` returns the client payload verbatim.**
Python does no model validation (`return client.list_erf_experiments()`,
`:6461`); TS mirrors that with the `native()` walk per item (the W3
`bookmark_linked_dashboard_ids` precedent) and the declared
`Array<Record<string, unknown>>` return. The one vector's `expect.result`
is the raw list, confirmed.

**W4-D6 — no new URL, no request assembly, no status branching in the
facade** (R2.13 / R10.8): grep-audited — `flags-experiments.ts` contains
no `new URL`, no `fetch`, no header literal, no status comparison. Every
path/query/scoping decision stays in `services/entities/{flags,
experiments}.ts` (B4-C4), including the flag domain's
`require_scoped_path` workspace auto-discovery and `get_flag_limits`'s
always-project-scoped path.

**Watchlist sweeps.** #13 `isinstance(x, dict)`: none in the Python range
(re-read at HEAD). #6 truthiness: two sites, both listed in W4-D2. #5
dates: `ExperimentConcludeParams.end_date` /
`UpdateExperimentParams.start_date`/`end_date` stay STRINGS end-to-end —
no `Date` is constructed anywhere in the shard. R11.7: one `str(int)`
site (`get_flag_history`), routed through `pythonStr`.

## 4. R10.9 RUN record (`throwaway/b6-w4/`)

```
npx vite-node throwaway/b6-w4/wire-edges.ts
checks 53   failures 0
```

Deterministic (no RNG, no seed) — every case is a hand-built canned
interaction over the injected-fetch seam.

| group | cases |
|---|---|
| (i) delegation equivalence | `list_feature_flags`, `get_feature_flag`, `get_flag_history`, `get_flag_limits`, `list_experiments`, `get_experiment`, `list_erf_experiments` — facade result === direct client result re-validated through the SAME model seam (7) |
| (ii) wire status branches | `get_feature_flag` 200 / 404 (`QueryError/QUERY_FAILED`) / 500 (`ServerError/SERVER_ERROR`); `decide_experiment` 200 / 400 / 422 (both `QueryError/QUERY_FAILED`) / 204-empty (`ResponseValidationError/RESPONSE_VALIDATION_ERROR`) (7) |
| (iii) edge set | `18.0`, `1.5`, `true`, `null`, `[]`, `""`, `"𝒳"` through the flag `ruleset` dict (7) and the experiment `settings` dict (7) — the shard's two `dict[str, Any]` annotations, the only places the #8 boundary admits them; plus the exclude-none drop and the #12 integral-float wire-spelling record (16) |
| (iv) W4-local branches | six empty-response guards; `get_flag_history` query assembly ×5; `conclude_experiment` body ×3; `set_flag_test_users` bare-dump ×2; `duplicate_experiment` dump; four `RESPONSE_VALIDATION_ERROR` shapes; two void-member batches (23) |

Observations:

1. **#12 class (recorded, not a defect)** — an integral float inside a
   `dict[str, Any]` param renders `18` on the wire where CPython's
   `json.dumps(18.0)` writes `18.0`; the entity models hold plain JS
   numbers. NO W4 corpus vector asserts a request body (every
   `expect.interactions[].request.body` is `null` — measured), so no
   vector is exposed. Same class W2 recorded for `ids=`
   (`B6-W2-notes.md:143-145`); not W4-local, no new deferral opened.
2. **404 and 422 collapse to `QueryError`/`QUERY_FAILED`** — the B0
   status mapping, unchanged by the facade.
3. **The six empty-response guards are unreachable through the wire** —
   the B4 client raises for a non-dict envelope before `None` can reach
   the facade (the finding W3 recorded for its five guards); they are
   ported defensively and probed at the member seam.

## 5. Layer-3 translation

WHOLE-file translations, per packet §6:

| Python | TS | tests |
|---|---|---|
| `tests/unit/test_workspace_flags.py` (533 lines, 3 classes) | `test/workspace/workspace-flags.test.ts` | 16 translated + 10 additive |
| `tests/unit/test_workspace_experiments.py` (464 lines, 3 classes) | `test/workspace/workspace-experiments.test.ts` | 17 translated + 5 additive |

Translation conventions (both file headers carry the cites):

- `httpx.MockTransport` → the injected-fetch `fakeTransport` seam;
  `_make_workspace(temp_dir, handler)` → `makeWorkspace(handler)`, client
  over the OAuth session and facade over the service-account
  `_TEST_SESSION`, exactly as Python does. `temp_dir` has no TS analog.
- The flags rig pins `client.setWorkspaceId(100)`
  (`test_workspace_flags.py:87`); the experiments rig does NOT (every
  experiment path is project-scoped).
- `flag.model_extra` → the Phase-2 `__extras` spillover bag
  (`extra='allow'`).

ADDITIVE sections are clearly headed and never substitute for a
translated Python assertion (B5 Caution #13): the six empty-response
guards, the `get_flag_history` query-dict arms and the
`conclude_experiment` body arms — all facade-local branches Python's
suite never reaches through the wire.

## 6. Deferrals

**Inbound**: none placed on W4 by the packet.

**Outbound**: none. No `TODO(port)` marker was added by this shard.

**For the BIND task (§11)**: all 23 names are `wire_api` kind. The one
non-uniform mapping is `duplicate_experiment` (W4-D1) — `params` is
positional in TS while the recorder replays it as the kwarg `params`.
`conclude_experiment`'s `params` IS keyword-only and maps into the
options bag. `list_feature_flags` / `list_experiments` take
`{ include_archived }`; `get_flag_history` takes `{ page, page_size }`.
