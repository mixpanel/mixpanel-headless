# Phase 1 Recon: Test Infra + CI Machinery

Repo: `/Users/jaredmcfarland/Developer/mixpanel-headless` @ `5269674` (branch `fix/latent-bugs-stress-test`).
All line numbers cite that commit. Scope amendment honored: mutation testing (`[tool.mutmut]`, `just mutate*`, StrykerJS) is OUT OF SCOPE and ignored; judge validation = deliberate-break smoke test (Section 3).

## Counts (verified, not estimated)

```json
{
  "total_collected": 7325,
  "non_live_collected": 6769,
  "live_marked": 556,
  "pbt_selected_by_k_pbt": 556,
  "pbt_live_overlap": 0,
  "pbt_files_star_pbt": 39,
  "composite_strategies": 41,
  "hypothesis_given_files_not_named_pbt": 1,
  "autouse_fixtures": 2,
  "ci_python_matrix": ["3.10", "3.11", "3.12", "3.13"],
  "coverage_gate_pct": 90,
  "hypothesis_ci_max_examples": 200
}
```

Derivations:
- `uv run pytest --collect-only -q -o addopts="" -m "not live"` → `6769/7325 tests collected (556 deselected)`.
- `uv run pytest --collect-only -q -o addopts="" -m live` → `556/7325`.
- `uv run pytest --collect-only -q -o addopts="" -m "not live" -k "_pbt"` → `556/7325` (numeric coincidence with live count; sets are disjoint — `-m live -k "_pbt"` collects 0).
- `grep -rc "@st.composite" tests/` (decorator lines, 13 files) → 41. Plan's claim of 41 composite strategies VERIFIED.
- `find tests -name "*_pbt.py" | wc -l` → 39 files (12 in `tests/pbt/`, rest in `tests/` and `tests/unit/`, incl. `tests/unit/cli/`).
- `uv run python -c "import mixpanel_headless; print(mixpanel_headless.__file__)"` → `/Users/jaredmcfarland/Developer/mixpanel-headless/src/mixpanel_headless/__init__.py` (editable, resolves repo src).

## 1. pytest config + autouse fixtures

`pyproject.toml:138-145` (`[tool.pytest.ini_options]`):
- `testpaths = ["tests"]` (L139)
- `addopts = "-vv --tb=short -m 'not live'"` (L140) — **every pytest invocation deselects `live` by default**, including a future record-mode run. `-vv` also makes `--collect-only -q` output verbose (docstrings interleaved); use `-o addopts=""` when the rig needs machine-parseable collection output.
- Markers (L141-145): `live`, `destructive`, `contract` ("locks recorded HTTP response shapes" — the `contract` marker is prior art for the conformance idea; grep shows it applied in `tests/integration/` auth tests).

Autouse fixtures — exactly two in the whole tree (`grep -rn autouse tests --include=conftest.py`):

1. `_clean_mp_env` — `tests/conftest.py:143-154`, function-scoped, autouse. Deletes exactly these 7 env vars before EVERY test (`_MP_ENV_VARS`, `tests/conftest.py:132-140`): `MP_USERNAME, MP_SECRET, MP_PROJECT_ID, MP_REGION, MP_OAUTH_TOKEN, MP_AUTH_FILE, MP_WORKSPACE_ID`.
   **Record-plugin implication**: any per-test configuration the record plugin needs MUST NOT ride on those names. Note `MP_CONFIG_PATH` and `MP_TEST_GUARD_REAL_HOME` are *not* scrubbed, but the safe move is a non-`MP_` prefix (e.g., `CORPUS_RECORD_DIR`) — monkeypatch deletion is per-test and restored after, so a session-level env var with a non-scrubbed name survives fine.

2. `_no_test_writes_to_real_home_mp` — `tests/conftest.py:199-237`, session-scoped, autouse. Snapshots mtimes under the real `~/.mp/` at session start/end and `pytest.fail`s on any change. Gated by `_real_home_mp_guard_enabled()` (`tests/conftest.py:157-172`): active only when `$CI` is set or `MP_TEST_GUARD_REAL_HOME=1`.
   **Record-plugin implication**: vector emission during the session is safe anywhere EXCEPT under the developer's/CI-runner's real `~/.mp/`. Writing JSON vectors under `context/phase1/…` or a tmp dir will not trip the guard. In CI (`$CI` set) the guard is live, so the record plugin must never route through real-home config paths — which it shouldn't anyway since `_clean_mp_env` guarantees tests run credential-hermetic.

Sub-conftests have **zero autouse fixtures**:
- `tests/unit/conftest.py` (23 lines): only opt-in `mock_session` (L13) and `mock_config_manager` (L19).
- `tests/integration/conftest.py` (67 lines): opt-in `tmp_mp_home` (L18-36, monkeypatches `HOME` + `MP_CONFIG_PATH` to a tmpdir), `recorded_responses` (L39), `live_marker` (L53, reads `MP_LIVE_TESTS=1`).
- `tests/pbt/`, `tests/live/`, `tests/qa/` have no conftest.py (`tests/live/conftest_042.py` exists but is not a conftest pytest loads automatically).

Other useful shared machinery in `tests/conftest.py` the record plugin will observe constantly: `make_session()` (L65-129, default fake creds `test_user`/`test_secret`/project `12345`/region `us`) and `mock_client_factory` (L285-307) which builds `MixpanelAPIClient(session=..., _transport=httpx.MockTransport(handler))` — i.e., **the entire non-live suite already runs against mock transports; record mode can hook `MixpanelAPIClient` request/response boundaries without network concerns**.

## 2. Hypothesis

- Profile registration: `tests/conftest.py:22-54` — four profiles: `default` (100 examples), `ci` (200, `derandomize=True`, L30-37), `dev` (10, verbose), `debug` (10, single-bug). All suppress `HealthCheck.differing_executors` (a mutmut-era accommodation; harmless to leave).
- Profile selection: `tests/conftest.py:57` — `settings.load_profile(os.getenv("HYPOTHESIS_PROFILE", "default"))`, evaluated at conftest import time. CI sets `HYPOTHESIS_PROFILE=ci` (`.github/workflows/ci.yml:59,65`); justfile `test-dev`/`test-ci`/`test-pbt-*` set it inline (justfile L24-41).
- Composite strategies: **41** `@st.composite` decorators across 13 files (largest: `tests/pbt/test_session_pbt.py` 6, `tests/unit/test_discovery_pbt.py` 6, `tests/test_cohort_definition_pbt.py` 5, `tests/test_user_query_pbt.py` 5). Plan's "41" is exact at this commit. Note strategies live in *test files*, not a shared `strategies/` module.
- PBT identifiability for record-mode EXCLUSION:
  - `-k "_pbt"` selects exactly 556 tests, all from `*_pbt.py` files (per-file breakdown verified; top: `tests/unit/test_types_pbt.py` 82, `tests/test_types_funnel_pbt.py` 40, `tests/unit/test_types_data_governance_pbt.py` 37).
  - **Gap**: filename-based exclusion is NOT sufficient. `tests/test_query_user_structural.py` contains 2 `@given` Hypothesis tests (L419, L445) in a non-`_pbt` file. The record plugin should exclude by Hypothesis detection — `hasattr(item.obj, "hypothesis")` (Hypothesis attaches a `.hypothesis` attribute / `is_hypothesis_test`) — with `-k "not _pbt"` as belt-and-braces, not the sole gate.
- Why PBT pollutes extraction: Hypothesis generates different inputs per run (under `default` profile, non-derandomized) and per Hypothesis version/DB state; recorded call vectors would be nondeterministic — corpus diffs would churn on every regeneration, and shrunk/adversarial inputs (NUL-laden strings, 10^308 floats) encode Hypothesis's search strategy rather than API contract intent. Even `ci`'s `derandomize=True` only pins the seed per test-name — any strategy edit or Hypothesis upgrade reshuffles all examples. Exclude all 558 Hypothesis tests (556 `_pbt`-named + 2 structural) from record mode; the TS port gets its own PBT via fast-check per the rulebook, separately from the corpus.

## 3. Judge sanity check (deliberate-break smoke test) groundwork

### Worktree mechanics — VERIFIED WORKING
- `git worktree add /tmp/mp-sabotage-recon HEAD` succeeds cleanly (repo already carries two other worktrees; `git worktree list` shows them — one prunable at `/private/tmp/pr195-rereview-21de3d24`).
- `uv.lock` is git-tracked, so the worktree gets it for free.
- `[tool.uv]` has only `exclude-newer = "7 days"` (`pyproject.toml:191-192`) — no `UV_PROJECT_ENVIRONMENT` pinning, no workspace config. Running `uv run …` inside the worktree auto-creates a **fresh `.venv` inside the worktree** ("Creating virtual environment at: .venv … Built mixpanel-headless @ file:///private/tmp/mp-sabotage-recon … Installed 43 packages in 238ms" — warm uv cache; whole first `uv run` ≈ 16 s wall).
- `uv run python -c "import mixpanel_headless; print(mixpanel_headless.__file__)"` inside the worktree → `/private/tmp/mp-sabotage-recon/src/mixpanel_headless/__init__.py` — **resolves the worktree copy of src/, not the main checkout**.
- Editable verified: appended `SABOTAGE_MARKER = True` to the worktree's `src/mixpanel_headless/__init__.py` post-sync; next `uv run` import saw it immediately with no re-sync. So sabotage = plain `sed`/patch on the worktree source, then run the corpus runner via `uv run` from the worktree cwd. (Bare `uv run` installs only base deps — 43 pkgs, no pytest; a standalone corpus-runner script that only imports `mixpanel_headless` needs nothing more. If the runner uses pytest, `uv sync --all-extras` first.)
- Cleanup: `git worktree remove --force /tmp/<name>` verified.
- One caveat: `_no_test_writes_to_real_home_mp` fires in worktree runs too if `$CI` is set — irrelevant for a standalone runner, relevant if the smoke test shells out to pytest.

### Proposed sabotage sites (12, spanning capability areas — each is a one-line semantic break a healthy corpus MUST catch)

| # | Area | File:line | Break |
|---|------|-----------|-------|
| 1 | Validation | `src/mixpanel_headless/_internal/validation.py:116` | `if prop.id <= 0:` → `< 0` (CustomPropertyRef id=0 silently accepted) |
| 2 | Validation | `src/mixpanel_headless/_internal/validation.py:381` | replace `datetime.date.fromisoformat(date_str)` with `pass` (invalid calendar dates like 2025-02-30 pass validation) |
| 3 | API routing | `src/mixpanel_headless/_internal/api_client.py:2653` | `self._build_url("query", "/segmentation")` → `"/segment"` (wrong endpoint path in every segmentation request vector) |
| 4 | API routing | `src/mixpanel_headless/_internal/api_client.py:153` | us `"query"` base `https://mixpanel.com/api/query` → `https://eu.mixpanel.com/api/query` (region routing corrupted) |
| 5 | Query builder | `src/mixpanel_headless/workspace.py:2139-2141` | drop the `percentile` → `custom_percentile` mapping (`bookmark_math = item_math`) — bookmark JSON emits server-rejected math name |
| 6 | Pagination | `src/mixpanel_headless/_internal/pagination.py:287-288` | `if next_cursor is None: break` → `if next_cursor is not None: break` (silent single-page truncation of all App API listings) |
| 7 | Cohort/segfilter | `src/mixpanel_headless/_internal/segfilter.py:47` | `"equals": "=="` → `"equals": "!="` (cohort filter operator inversion) |
| 8 | Expressions | `src/mixpanel_headless/_internal/expressions.py:52` | `return f'properties["{escaped}"]'` → `return on` (bare property names no longer wrapped in accessor syntax) |
| 9 | User query builder | `src/mixpanel_headless/_internal/query/user_builders.py:248` | `" and ".join(...)` → `" or ".join(...)` (multi-filter combinator flipped) |
| 10 | Result transform | `src/mixpanel_headless/_internal/services/live_query.py:137` | `conv_rate = 1.0 if idx == 0 else (count / prev_count …)` → always `count / steps[0].count` (step conversion becomes overall conversion) |
| 11 | Result transform | `src/mixpanel_headless/_internal/services/live_query.py:202` | `count / size if size > 0 else 0.0` → `count / size if size > 0 else 1.0` (empty-cohort retention reports 100%) |
| 12 | Auth resolution | `src/mixpanel_headless/_internal/auth/resolver.py:161-168` | move the `explicit` param check above `sa = _env_account_from_service_quad()` (env>param priority inverted; contradicts documented order at `resolver.py:145-149`) |

Selection rationale: 3, 4 break the *request* side of vectors; 5, 7, 8, 9 break *serialized payload* shape; 1, 2 break *validation verdict* vectors; 6, 10, 11 break *response-transform* vectors; 12 breaks *session resolution* vectors. A corpus that stays green under any of these has a coverage hole in that area.

## 4. CI + justfile wiring

`.github/workflows/ci.yml` — single job `test` (L24), `ubuntu-latest`, `permissions: contents: read`, matrix `python-version: [3.10, 3.11, 3.12, 3.13]` (L32). Steps:
1. `actions/checkout` v6.0.2 (L36)
2. `actions/setup-python` v6.2.0 with matrix version (L39)
3. `astral-sh/setup-uv` v8.1.0 (L44) — **pattern: system python via setup-python, then uv on top; `uv sync --all-extras`** (L47)
4. `ruff check src/ tests/` (L50)
5. `mypy src/ tests/` (L53)
6. pytest with `HYPOTHESIS_PROFILE: ci` — plain on 3.10/3.11/3.13 (L55-59); on 3.12 with `--cov … --cov-fail-under=90` (L61-65)
7. codecov upload, 3.12 only, `fail_ci_if_error: false` (L67-71)
8. `uv build`, 3.12 only (L73-75)

No `timeout-minutes` or runtime data in the yml (runtimes not visible without `gh run list`; not derivable from the file — flagged as unavailable rather than estimated).

Path filters (L7-21): `src/**, tests/**, pyproject.toml, justfile, .github/**` for both push-to-main and PR. **A conformance job whose corpus lives under `context/` (or a new `conformance/` dir) will NOT trigger CI on corpus-only changes unless the paths list is extended** — slot the corpus dir into both `paths:` blocks when adding the job.

Where the conformance job slots: a new sibling job (e.g., `conformance`) after L75, single Python (3.12 to match the coverage/build leg), same 3-step setup (checkout → setup-python → setup-uv → `uv sync --all-extras`), then (a) record-mode drift check: re-run the record plugin over the non-live suite and diff emitted vectors against the committed corpus; (b) corpus runner: execute the Python corpus runner against the committed vectors. `needs: test` optional; independent job is fine since it re-syncs its own env.

Relevant justfile recipes (justfile, tracked):
- `check` (L12): `lint fmt-check typecheck docstring-cov test-cov build` — documented as strict superset of CI; a `conformance` recipe should be appended to this dependency list when the rig lands.
- `test` (L20-21): `uv run pytest {{args}}`.
- `test-cov` (L97-98): `uv run pytest --cov=src/mixpanel_headless --cov-report=term-missing --cov-fail-under=90`.
- `test-dev`/`test-ci` (L24-29): same with `HYPOTHESIS_PROFILE=dev|ci`.
- `test-pbt` (L32-33): `uv run pytest -k "_pbt"` — the inverse selector `-k "not _pbt"` is the natural record-mode base (plus Hypothesis-attribute exclusion per Section 2).
- Ignore: `mutate*` recipes (L~60-95) — out of scope per amendment.

## 5. Reality-check transcript (exact outputs)

```
$ uv run python -c "import mixpanel_headless; print(mixpanel_headless.__file__)"
/Users/jaredmcfarland/Developer/mixpanel-headless/src/mixpanel_headless/__init__.py

$ uv run pytest --collect-only -q 2>/dev/null | tail -3
============= 6769/7325 tests collected (556 deselected) in 0.97s ==============

$ uv run pytest --collect-only -q -m live 2>/dev/null | tail -3
============= 556/7325 tests collected (6769 deselected) in 0.95s ==============
```

Live distribution (per-file, `-o addopts="" -m live`): `tests/live/` 547 across 8 files (largest `test_040_query_completeness_live.py` 158, `test_data_governance_live.py` 94), plus 9 live-marked in `tests/integration/` (`test_bookmark_schema_roundtrip.py` 4, `test_replays_live.py` 4, `test_workspace_lazy_resolve.py` 1).
