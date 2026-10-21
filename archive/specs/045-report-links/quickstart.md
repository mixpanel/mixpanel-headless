# Quickstart: Report Links

**Feature**: 045-report-links | **Date**: 2026-09-02

This guide proves the feature end to end. It has three parts: automated gates, a live smoke test, and a browser check. Contracts and type shapes are in [contracts/](contracts/) and [data-model.md](data-model.md).

## Prerequisites

- A clone of the repository on branch `045-report-links`.
- `uv sync --all-extras` and `just install-hooks` done.
- For the live parts: an active account with project access. Run `mp login` if needed. Confirm with `mp session show`.
- For the browser part: a browser logged in to the same Mixpanel project.

## Part 1: Automated gates

```bash
just check
```

Expected: lint, format, mypy strict, tests with coverage at or above 90 percent, and build all pass.

```bash
just test -k report_link
```

Expected: every test in these files passes.

- `tests/unit/test_exceptions_report_links.py`
- `tests/unit/test_report_links.py`
- `tests/unit/test_report_links_pbt.py`
- `tests/unit/test_api_client_bookmark_urls.py`
- `tests/unit/test_workspace_report_links.py`
- `tests/integration/cli/test_report_link_commands.py`

```bash
just test-pbt-dev -k report_links
```

Expected: the round trip, decoration invariance, totality, and slug invariants pass with the `dev` profile.

```bash
PYTEST_ADDOPTS="-k 'report_link or bookmark_url' -p no:cacheprovider" \
  uv run mutmut run "mixpanel_headless._internal.report_links*"
just mutate-results
```

mutmut 3.5 has no `--paths-to-mutate` flag; the mutant-name prefix scopes the run to the pure module, and `PYTEST_ADDOPTS` keeps the stats pass on the report-link tests (two integration tests shell out from inside `mutants/` and would fail it). `mutmut results` lists only surviving mutants; count the emoji lines in the run output for the score.

Expected: mutation score at or above 80 percent for the pure module.

## Part 2: Live smoke test

Gated tests:

```bash
MP_LIVE_TESTS=1 just test tests/integration/test_report_links_live.py
```

Expected: each of these passes against the active account.

1. Create a link from `ws.build_params("<event>", last=7)`.
2. Resolve the link URL. The type equals the input. The parameters are the server's canonical form: the time section and metric count survive, but the server rewrites `behavior.type` (`event` → `simple`), may swap an auto-captured event name for its display name, drops `filtersDeterminer`, and adds defaults (`primaryYAxisOptions`, `behaviors`, `executedMigrations`). Verified live on 2026-09-02.
3. Resolve the bare slug. Same result.
4. Resolve a known saved bookmark URL. The type comes from the bookmark.
5. Run the resolved report. The result is a `QueryResult`.
6. Create and resolve a Flows link.
7. Optional: resolve a fixture shortlink named by `MP_TEST_SHORT_LINK`.

Manual Python check:

```bash
uv run python -c "
import mixpanel_headless as mp
ws = mp.Workspace()
params = ws.build_params('Login', last=7)
link = ws.create_report_link(params, name='headless smoke')
print(link.url)
r = ws.resolve_report_link(link.url)
assert r.report_type == 'insights' and r.params['sections']['time'] == params['sections']['time']
print(ws.query_report_link(r).df.head())
"
```

Expected: one URL printed, then the first rows of a DataFrame. No exception.

Manual CLI checks. Replace the placeholders with the values from the Python check.

```bash
uv run mp reports resolve 'https://mixpanel.com/project/<pid>/view/<wid>/app/insights#<slug>'
uv run mp reports resolve '<slug>' --jq .report_type
uv run mp reports resolve 'https://mixpanel.com/project/<pid>/app/insights#report/<bookmark_id>' --run
uv run mp query segmentation -e Login --from 2026-08-01 --to 2026-08-31 --link --jq .report_url
uv run mp query saved-report <bookmark_id> --link --jq .report_url
echo '{"bad": ' | uv run mp reports link; echo "exit=$?"
uv run mp reports resolve 'https://mixpanel.com/project/999999999/app/insights#<slug>'; echo "exit=$?"
uv run mp reports resolve 'https://mixpanel.com/project/<pid>/app/insights#~(sections~())'; echo "exit=$?"
uv run mp reports resolve 'https://mixpanel.com/project/<pid>/app/insights#ZZZZZZZZZZZZ'; echo "exit=$?"
```

Expected exit codes, in order of the last four commands:

| Command | Exit |
|---------|------|
| bad JSON to `reports link` | 3 |
| project mismatch | 3, no network call, message names both projects |
| legacy hash | 3, message tells the user to open it in a browser |
| unknown slug | 4 |

## Part 3: Browser check

1. Open the URL printed by the Python check. The Insights editor loads with the `Login` event and a 7-day range.
2. Create a Funnels link:

```bash
uv run python -c "
import mixpanel_headless as mp
ws = mp.Workspace()
r = ws.query_funnel([mp.FunnelStep('Login'), mp.FunnelStep('Purchase')], last=30)
print(ws.create_report_link(r).url)
"
```

3. Open that URL. The editor must show a funnel, not an empty Insights report. If it shows an empty Insights report, change `SLUG_APP_FOR_TYPE["funnels"]` to `"funnels"` and `["retention"]` to `"retention"`, rerun `just test -k report_links`, and repeat this step.
4. Open the URL from `mp query saved-report <id> --link`. The saved report loads.

## Part 4: Security check

```bash
MP_LIVE_TESTS=1 uv run pytest tests/integration/test_report_links_live.py -s 2>&1 | grep -i "authorization\|bearer\|basic " ; echo "grep exit=$?"
```

Expected: `grep exit=1`, which means no credential text appeared in any output or log line.

## Done when

- Part 1 passes with no failures.
- Part 2 passes for a service-account account and for at least one OAuth account type.
- Part 3 confirms all four report types open in the browser.
- Part 4 shows no credential leak.
- `CHANGELOG.md` has an `## Unreleased` entry that names the new methods and commands.
