# Recon: realistic response-body sources for parse vectors and golden files

Date: 2026-08-14. Branch: fix/latent-bugs-stress-test @ 5269674. All counts derived
with `find`/`grep`/`ls`, not estimated, unless labeled estimate.

## 1. tests/fixtures/** (Python repo) — full inventory (13 files)

| Path | Size | What it is | Consumed by |
|---|---|---|---|
| tests/fixtures/rrweb/sample-replay-001.json | 6,429 B | Hand-built rrweb stream, 20 events (verified via json load: type 0 ×1, type 1 ×1, FullSnapshot ×3, IncrementalSnapshot ×11, Meta ×4); login → dashboard → profile-edit flow, 15 s, timestamps from 1716810000000 | tests/unit/test_replay_bundle.py:30 (`_FIXTURE_001 = Path("tests/fixtures/rrweb/sample-replay-001.json")`) |
| tests/fixtures/rrweb/README.md | 2,761 B | Event-by-event doc of the fixture + rrweb event-shape reference table (types 0–6, IncrementalSnapshot sources 1–5) | humans |
| tests/fixtures/phase008/activity_feed.json | 831 B | `{status, results:{events:[...]}}` stream/activity-feed shape | **ORPHANED** — no test loads any phase008 file from disk (`grep -rln phase008 tests/` matches only tests/unit/test_types_phase008.py, and that file's only hit is a test *name* at line 670; no Path/fixture loading in it) |
| tests/fixtures/phase008/insights.json | 495 B | insights query shape (`computed_at`, `headers`, `series`) | orphaned (same) |
| tests/fixtures/phase008/segmentation_numeric.json | 438 B | `{data:{series, values}, legend_size}` numeric-bucket segmentation | orphaned |
| tests/fixtures/phase008/frequency.json | 200 B | `{data:{date: [counts...]}}` frequency/retention-style | orphaned |
| tests/fixtures/phase008/segmentation_sum.json | 177 B | `{status, computed_at, results:{date: float}}` | orphaned |
| tests/fixtures/phase008/segmentation_average.json | 115 B | `{status, results:{date: float}}` | orphaned |
| tests/fixtures/configs/simple.toml | 408 B | v3 config golden (one SA account + `[active]`) | tests/unit/test_config.py:630 (`_FIXTURE_DIR / "simple.toml"`) |
| tests/fixtures/configs/multi.toml | 641 B | v3 config golden (3 account types + 2 targets) | tests/unit/test_config.py:646 |
| tests/fixtures/configs/.gitkeep | 0 B | placeholder | — |
| tests/fixtures/oauth/tokens_us.json | 220 B | legacy v2 token-file shape (access/refresh/expires_at/scope/project_id) | tests/unit/test_auth_storage.py (writes its own copies to tmp; the fixture models the legacy layout) |
| tests/fixtures/oauth/.gitkeep | 0 B | placeholder | — |

Takeaways: on-disk fixtures are tiny and synthetic. The phase008 set is a
ready-made (if minimal) catalog of the 5–6 raw query-response envelope variants
but is currently dead weight — good seed material for parse vectors, not
sufficient volume. The rrweb fixture is the only one exercised, and it is the
canonical corpus seed for the replay analyzer.

## 2. `contract` marker — recorded HTTP response shapes

- Marker declared: pyproject.toml:144 — `"contract: marks tests that lock recorded HTTP response shapes (auth redesign R6 layered tests)"`.
- Actual usage: exactly ONE test in the whole suite —
  tests/integration/test_workspace_lazy_resolve.py:110
  `test_lazy_resolve_against_recorded_response_layered_marker`, which is a
  placeholder that does `pytest.skip("Contract layer recording deferred to Phase 8 release prep.")` (line 113).
- **There are no recorded response bodies on disk for contract tests.** The
  R6 "recorded" layer was never filled in.
- Where recorded-ish shapes actually live: inline `httpx.MockTransport`
  handlers returning literal JSON dicts — 176 occurrences across 50 test
  files (grep counts). Example: test_workspace_lazy_resolve.py:59-73 locks the
  `/api/app/projects/{pid}/workspaces/public` envelope
  `{"results": [{id, name, project_id, is_default}], "status": "ok"}`.
  These inline dicts are the richest in-repo source of response shapes but must
  be harvested per-test-file, not from a fixtures directory.

## 3. tests/qa/** and tests/live/** — recording/caching

- tests/qa/ contains ONLY an empty `__init__.py` (1 file). No tests, no fixtures.
- tests/live/ = 10 .py files (9 test modules + conftest_042.py), opt-in via env
  (MP_LIVE_TESTS / MP_LIVE_SA_* / MP_LIVE_OAUTH_TOKEN). Caching is **in-memory
  only**: conftest_042.py caches a once-per-session credential-probe result
  (docstrings at lines 276-295); nothing writes response bodies to disk. The
  only file writes in live tests are test-input CSVs for lookup tables
  (test_data_governance_live.py:1475,1521,1590). **No reusable recorded
  corpus exists in live tests.** conftest_042.py:22 reads the developer's real
  `~/.mp/oauth/tokens_us.json` — a pattern to avoid in the rig.

## 4. /Users/jaredmcfarland/Developer/analytics/iron/.storybook/mocks/api/** (READ-ONLY)

Total: 81 JSON files, ~1.2 MB (`du -sk` = 1196 KB; app 460 KB, query 736 KB).

| Dir | Files | Entity / endpoint mirrored |
|---|---|---|
| app/bookmarks/ | 20 | App API single-bookmark GET (report definitions: insights type, full `params.sections` query DSL) |
| app/boards/ | 7 | App API board/dashboard GET (layout v2.0.0, embedded `contents.report` map); board_9425929.json is 126 KB |
| query/insights/ | 36 | /api/query/insights raw results keyed by bookmark id; incl. variants `_repoll`, `_exclude`, `_with_formula` and error cases |
| query/arb_funnels/ | 6 | /api/query/arb_funnels raw results (steps/nodes/edges graph; largest 102 KB); incl. `_exclude` variant and an empty-steps + `"overallConversionRate": "NaN"` edge case (bookmark_87176748.json) |
| query/metrics/ | 12 | metrics/timeseries responses (`meta` + `aggregate` + `timeseries` + nested `comparisons`), keyed node{uuid}_in_the_last_{3_month,7_day} |

Realism check (8 bodies read):
- **App API envelope: YES** — app/bookmarks/60327233.json and
  app/boards/board_9759336.json are exact `{"status": "ok", "results": {...}}`
  envelopes with production-grade field sets (project_id 3018488,
  workspace_id 3536632, dashboard ancestry, permission booleans, full
  `params.sections` bookmark DSL). These mirror what
  `mixpanel_headless` App-API CRUD parses.
- **Query API: raw un-enveloped bodies** — query/insights/bookmark_60327221.json
  is a real-shape insights response (`computed_at`, `headers`, `date_range`,
  `meta.report_sections`, nested `series` with `$overall` + per-segment maps).
  query/metrics/* have production timestamps (2025-08) and float precision that
  read as genuinely recorded, not hand-typed.
- **Caveat — wrapper format**: 9 of 81 files (8 insights + 1 arb_funnels) are NOT
  raw bodies but storybook fetch-mock wrappers
  `{"body": {...}, "init": {"status": 502}}` (e.g.
  query/insights/bookmark_76412137.json = a 502 "Internal Error"). Useful as
  error-path vectors, but a harvester must unwrap `body`/`init` for these.
- arb_funnels bodies use string-encoded counts (`"totalCount": "10254"`) —
  valuable parse-vector realism (type-coercion traps for the TS port).

## 5. analytics/iron/replay-embed/__test__/fixtures.ts (190 lines)

TypeScript factory helpers, no static rrweb JSON:
- `metaEvent` / `fullSnapshotEvent` / `interactionEvent` / `incrementalEvent`
  (lines 15-61) — minimal single-event builders (FullSnapshot's DOM is just
  `{type:0, childNodes:[], id:1}` — far less realistic than the Python repo's
  sample-replay-001.json).
- `generateReplayFiles` (lines 147-190) — programmatically generates multi-file
  replay sequences (`{seq:04d}-{fileSuffix}.json` naming, full snapshot in first
  file, uniform incremental events, exact end-timestamp in last file). This
  encodes the **chunked-file naming/sequencing contract** used by
  Replay fetching — useful as spec reference for the TS port's replay-file
  merging, not as body corpus.
- `createEmbedParams` (line 63) documents the signed-params shape
  `{url, query_string, replay_id}` — matches the Python `SignedReplay` contract
  (tests/unit/test_types_signed_replay.py:149 "query_string must be non-empty").

## 6. Flags (not decided here) re: copying analytics fixtures into the Python-repo corpus

1. **Internal data provenance**: bodies appear recorded from a real Mixpanel
   internal demo project (project_id 3018488, workspace_id 3536632, board/
   bookmark ids in the 60M–90M range). analytics is a private internal repo;
   the mixpanel-headless corpus may end up in a public or semi-public repo.
2. **PII-looking values**: 5 real-looking employee emails appear
   (alix.becker@, areeb.iqbal@, mack.duan@, pablo.fierro@, test@mixpanel.com)
   plus creator_id/creator_name fields. Would need scrubbing or synthetic
   re-keying before inclusion.
3. **Size**: ~1.2 MB total is manageable, but 4 files exceed 60 KB
   (board_9425929 126 KB, bookmark_85374361 142 KB, arb_funnels 60391517
   102 KB, arb_funnels 60327697 79 KB) — decide whether the corpus wants
   whole-body goldens or trimmed representative slices.
4. **Format mismatch**: 9/81 files use the storybook `{body, init}` wrapper —
   mechanical unwrap needed; naive bulk copy would poison parse vectors.
5. **Coverage gap regardless of copying**: analytics mocks cover only
   bookmarks/boards/insights/arb_funnels/metrics. No mocks there for
   segmentation, retention, engage/profiles, cohorts, flags, lexicon,
   annotations, webhooks, etc. — those shapes exist only inline in
   mixpanel-headless unit tests (176 MockTransport sites / 50 files).
