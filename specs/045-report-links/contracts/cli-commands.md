# Contract: CLI Commands

**Feature**: 045-report-links
**Surface**: `mp reports link`, `mp reports resolve`, `--link` on four `mp query` commands
**Audience**: CLI users, agents, and the implementer

Every command delegates to a `Workspace` method in [python-api.md](python-api.md). The CLI does input parsing and output formatting only.

---

## 1. `mp reports link`

```text
mp reports link [--params JSON | --params-file PATH | -]
                [--type insights|funnels|retention|flows]
                [--name TEXT] [--description TEXT]
                [--workspace-id INT] [--bookmark-id INT]
                [--no-validate]
                [--format json|jsonl|table|csv|plain] [--jq EXPR]
```

**Input**:
- `--params JSON`: an inline JSON object.
- `--params-file PATH`: a file with a JSON object.
- `-` or no option with a non-TTY stdin: read a JSON object from stdin.
- `--params` and `--params-file` together is an error. Exit 3.
- Invalid JSON, or JSON that is not an object, is an error. Exit 3. Reuse `validate_json_object`.

**Behavior**: calls `ws.create_report_link(params, report_type=type, name=, description=, workspace_id=, bookmark_id=, validate=not no_validate)`.

**Output**:
- Default JSON: `ReportLink.to_dict()` through `output_result`.
- `--format plain`: the bare URL and a newline, nothing else. This makes `$(mp reports link ... -f plain)` work.

**Examples**:

```bash
mp reports link --params '{"sections": {...}}' --name "Logins"
mp query segmentation -e Login --from 2026-08-01 --to 2026-08-31 --link --jq .report_url
cat params.json | mp reports link -f plain
```

---

## 2. `mp reports resolve`

```text
mp reports resolve LINK [--run] [--mode sankey|paths|tree]
                        [--format json|jsonl|table|csv|plain] [--jq EXPR]
```

**Input**: `LINK` is a full URL, a shortlink, or a bare 12-character slug. Quote it in the shell, because `#` starts a comment.

**Behavior**:
- Without `--run`: calls `ws.resolve_report_link(link)` and prints `ResolvedReport.to_dict()` through `output_result`.
- With `--run`: calls `ws.query_report_link(link, mode=mode)` and prints the typed result through `present_result`.
- `--mode` without `--run` is accepted and ignored.

**Examples**:

```bash
mp reports resolve 'https://mixpanel.com/project/3/view/75/app/insights#EBrV5bW2u9Mw'
mp reports resolve EBrV5bW2u9Mw --jq .params
mp reports resolve 'https://mixpanel.com/s/AbC123' --run -f csv
mp reports resolve 'https://mixpanel.com/project/3/app/insights#report/123' --run
```

---

## 3. `--link` on `mp query` commands

The flag defaults to off. When off, output is byte-for-byte unchanged.

| Command | With `--link` |
|---------|---------------|
| `mp query segmentation -e EVENT --from D --to D [-u UNIT] [--on PROP]` | Builds Insights params with `ws.build_params(event, from_date=, to_date=, unit=, group_by=on)` and calls `create_report_link`. Adds `report_url` to the output dict. |
| `mp query segmentation ... --where EXPR --link` | Prints `warning: --link is not supported with --where; link omitted` to stderr. Omits `report_url`. Exit 0. |
| `mp query segmentation ... --on 'properties["x"] > 1' --link` | Same warning for a non-bare breakdown. |
| `mp query funnel FUNNEL_ID --link` | Adds `report_url = ws.saved_report_link(funnel_id, report_type="funnels")`. No network. |
| `mp query saved-report ID --link` | Adds `report_url = ws.saved_report_link(id, report_type=result.report_type)`. `"funnel"` normalizes to `"funnels"`. No network. |
| `mp query flows ID --link` | Adds `report_url = ws.saved_report_link(id, report_type="flows")`. No network. |

**Bare property rule for `--on`**: the value is a bare property name unless it contains any of these tokens: `properties[`, `(`, `)`, `==`, `!=`, `<`, `>`, `defined`, `boolean(`, `number(`, `string(`, or the words ` and ` or ` or ` with spaces on both sides. Spaces, `$`, and Unicode inside a plain name are allowed, so `Plan Type` and `$city` are bare. An empty `--on` means no breakdown.

**Failure isolation**: any `MixpanelHeadlessError` raised by `create_report_link` inside a query command prints `warning: could not create report link: {message}` to stderr. The query result still prints. Exit 0.

**Not supported**: `mp query retention --link`, and `--link` on `event-counts`, `property-counts`, `frequency`, `activity-feed`, and the `segmentation-*` variants. The flag does not exist on those commands.

---

## 4. Exit codes

Branches are added to `handle_errors` in `cli/utils.py` before the generic `except MixpanelHeadlessError`.

| Exception | Exit code | stderr |
|-----------|-----------|--------|
| `ReportLinkNotFoundError` | 4 `NOT_FOUND` | `error: {message}` |
| `ReportLinkParseError` | 3 `INVALID_ARGS` | `error: {message}` plus `hint: {details["hint"]}` when present |
| `UnsupportedReportLinkError` | 3 `INVALID_ARGS` | same |
| `ReportLinkScopeMismatchError` | 3 `INVALID_ARGS` | same |
| `ShortLinkResolutionError` | 1 `GENERAL_ERROR` | `error: {message}` |
| `AuthenticationError` (login redirect) | 2 `AUTH_ERROR` | existing branch |
| `BookmarkValidationError` | 3 `INVALID_ARGS` | `error: params failed schema validation` then one line per error: `  {path}: {message}`. New branch; today this class falls through to the generic branch and exits 1. |
| Local input errors (bad JSON, two param sources) | 3 `INVALID_ARGS` | printed by the command |

The `cli/CLAUDE.md` exit-code table gains one row per new exception.

---

## 5. Help text

Each new command and flag has `--help` text with at least one example, per the constitution quality gate. The `--link` help on `segmentation` states that the link reproduces the event, dates, unit, and a bare breakdown only.
