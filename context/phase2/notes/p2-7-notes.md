# P2-7 running notes (entity models)

## Ground state
- TS repo main @ 2ee9f59 (P2-6 done). Python branch ts-port/phase2-contract-support.
- Sweep ALLOWLIST: 56 entity/param tags remain (conformance-runner/test/codec-sweep.test.ts:76).
- tag-universe rich_tags = 80; 24 already registered (P2-4/5/6); 56 left = ALLOWLIST.
- model-coverage.json: 56 corpus_tag / 38 entity_golden / 31 unresolved.
  Unresolved 31: AccountSummary AccountTestResult AlertBookmark AlertCreator
  AlertHistoryPagination AlertProject AlertValidation AlertWorkspace AnnotationUser
  AuditViolation BlueprintConfig BlueprintTemplate BookmarkHistoryPagination
  BookmarkMetadata CohortCreator CursorPagination CustomEventAlternative DashboardRow
  DashboardRowContent ExperimentCreator FlagHistoryParams OAuthBrowserAccount
  OAuthLoginResult OAuthTokenAccount PaginatedResponse Project ServiceAccount Session
  Target UpdateTextCardParams UploadLookupTableParams
- hint_failures: pagination.paginate_all (generic).

## TODO (high level)
1. Read record/codecs.py Pydantic model encode/decode contract.
2. Read one prior packet file (query-params/cohort.ts or results/discovery.ts) for conventions.
3. Read vector-codecs.ts registration pattern + bindings.
4. Enumerate 125 models from Python by area -> file mapping (C1: 14 entity files; auth models already in auth/? NO - auth READ: P2-4 made interfaces+parse factories; the Pydantic models ServiceAccount etc. count via authored fixture/deferral).
5. Build entities/*.ts one file at a time; register codecs per file; shrink allowlist per file.
6. Entity golden tests (api -> model table) using entity_golden_vector_ids.
7. Vendored cross-check test-d files; E4 alerts verification -> PROVENANCE.json.
8. model-coverage resolution: extend generator w/ overrides? or fill via P2-7 edit + regenerate discipline. DECIDE.
9. npm run check + 42 PASS + commit.

## Decisions
(fill as made)

## Progress log
- model dump v2 at notes/p2-7-model-dump.json (125 models, aliases resolved, constraints, docstrings via ast in drafting aid).
- Partition: 119 models across 14 entity files (C1 layout); 6 auth Pydantic models (ServiceAccount/OAuthBrowserAccount/OAuthTokenAccount/Session/Project/WorkspaceRef) stay in auth/ (P2-4).
- model-base.ts written: EntityModel base (defaults-on-absent, extra policy, alias resolution in prepareInit, coerce.ts lax scalars, nested reconstruct, datetime iso-text, nullable rejection, before/check hooks, afterValidate hook, computedSpecs; toJSON = tagged_models=False walk incl computed; toVectorPayload = datetime re-tagged). Errors: ResponseValidationError uniformly (R5.5 boundary; documented in module doc).
- 14 entity files generated from dump (drafting script /tmp/p27/gen_entities.py, reviewed), hand patches:
  PaginatedResponse<T> generic; BusinessContext computedSpecs + BUSINESS_CONTEXT_MAX_CHARS;
  AccountTestResult afterValidate; CreateCustomPropertyParams afterValidate;
  CreateCustomEventParams alternatives check; EventDeletionRequest filters before-normalizer;
  Target project pattern ^\d+$ + workspace gt 0.
- vector-codecs.ts: entityModelCodec + 56 rows (ENTITY_TAG_CODECS merged into CONTRACT_TAG_CODECS, moved to EOF for TDZ).
- codec-sweep: ALLOWLIST now EMPTY; entity instanceof probes via entities barrel lookup + EntityModel check. Sweep 8/8 PASS first run (all 56 tags round-trip byte-canonically).
- entity_golden = 38 models incl WorkspaceRef (auth interface — golden handler will adapt parseWorkspaceRef). All golden results are dict or list-of-dict; default extraction (list->elements, dict->payload) suffices (scan output in transcript).
- Unresolved 31 = 26 entity fixtures (authored-fixtures.test.ts) + 5 auth models (authored_fixture -> packages/core/test/auth/*.test.ts).
## Next
- entity-goldens.test.ts (conformance-runner/test, artifact-driven from model-coverage.json).
- authored-fixtures.test.ts + model-base.test.ts.
- lint prune unused imports in generated files.
- vendored cross-check test-d files + E4 alerts verification + PROVENANCE.
- Python: coverage overrides merge in generate_contract + regen + sync.
- batch flip? NO - batch-status is P2-8. bindings types.* adapters unchanged (no new types.* vectors for entities).

## Completion log
- Entity goldens: conformance-runner/test/entity-goldens.test.ts — artifact-driven from
  model-coverage.json (38 entity_golden models incl WorkspaceRef custom handler);
  155 tests PASS. Shared diff helper: conformance-runner/test/support/plain-diff.ts.
- Authored fixtures: packages/core/test/types/entities/authored-fixtures.test.ts (26 models,
  78 tests PASS). model-base behavioral tests: 19 PASS (incl 5 hand-ported validators,
  codepoint max_length, alias acceptance).
- Constraints hand-patched post-generator (MaxLen metadata was not captured by the dump):
  CreateAnnotationParams/UpdateAnnotationParams description<=512, CreateAlertParams name<=50,
  UploadLookupTableParams name 1..255, Target project ^\d+$ + workspace>0.
- Vendored cross-checks: packages/core/test/types/entities/vendored-contracts.test-d.ts
  (compile-only; alerts E4 exact-divergence assertions, webhooks key-equality,
  flags/experiments/drop-filter subset checks). Found+documented: ProjectWebhook.auth_type
  Python-only vs iron WebhookItem; vendored FeatureFlagStatus literal set differs from
  Python enum (documented, not asserted).
- E4 alerts verification DONE: endpoint mapping CONFIRMED (api_client.py:6078-6471 +
  12 recorded request paths all under alerts/custom/...); 9 divergence rows recorded in
  vendor/mixpanel-contracts/PROVENANCE.json under verified_divergences.alerts;
  npm run vendor:drift green (57 files, integrity OK).
- Python commits: f6383aa (generator merge + coverage_overrides.json + tests, 27 pass;
  ruff/mypy strict green) and 3d6ca82 (artifacts regenerated @ f6383aa; double-run
  byte-identical; conformance tests 393 pass). Statuses: 56 corpus_tag / 38 entity_golden /
  31 authored_fixture / 0 unresolved.
- TS resync: sync:corpus (5 contract artifacts, manifest pin 8ae76314 untouched);
  errors-codes.gen.ts regenerated (generated_from -> f6383aa).
- npm run check GREEN end-to-end: typecheck all workspaces, eslint, prettier, 60 test
  files / 1850 passed (corpus 3179: 461 PASS incl the 42 pre-existing, 2718 skipped),
  browser smoke OK.
- just check (full): EXIT=0 — 7116 passed / 1 skipped; conformance 393; Python runner 3179.
- Barrel surface verified: all 119 entity classes + BUSINESS_CONTEXT_MAX_CHARS exported
  from @mixpanel-headless/core (throwaway vitest probe).
- TS commit: 67c3ddf on main.
