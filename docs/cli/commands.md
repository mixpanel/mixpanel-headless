# CLI Commands

Complete reference for the `mp` command-line interface.

!!! tip "Explore on DeepWiki"
    🤖 **[CLI Command Reference →](https://deepwiki.com/mixpanel/mixpanel-headless/7.1-cli-command-reference)**

    Ask questions about specific commands, explore options, or get examples for your use case.

## Report links

Two `mp reports` verbs and an opt-in flag on four `mp query` commands turn queries into Mixpanel URLs and back. Full walkthrough: [Report Links guide](../guide/report-links.md).

| Command | Purpose |
|---------|---------|
| `mp reports link [--params JSON \| --params-file PATH \| -] [--type T] [--name] [--description] [--workspace-id] [--bookmark-id] [--no-validate]` | Store params as an unsaved report and print its URL. `-f plain` prints only the URL. `-`, `--params -`, and `--params-file -` read stdin and refuse a terminal. |
| `mp reports resolve LINK [--run] [--mode sankey\|paths\|tree]` | Resolve a URL, slug, or shortlink to its params; `--run` runs it and prints the result. Quote URLs so the shell does not interpret `#`. |
| `mp query segmentation ... --link` | Adds `report_url` (event, dates, unit, bare `--on` only). With `--where` or an expression in `--on`, or on any link error, `report_url` is `null` and `report_url_error` says why; the exit code stays 0. |
| `mp query funnel ID ... --link`, `mp query saved-report ID --link`, `mp query flows ID --link` | Adds `report_url` for the saved report. No network call. A link error never fails the query. |

Exit codes for the report-link errors: not found 4; parse, unsupported, and scope mismatch 3 (with a `hint:` line); auth 2; shortlink extraction 1.

## Saved metrics and behaviors

Two project-scoped groups manage saved metrics and saved behaviors. Full walkthrough: [Saved Metrics and Behaviors guide](../guide/saved-metrics.md).

| Command | Purpose |
|---------|---------|
| `mp metrics list [--type metric\|formula\|warehouse] [--verified \| --no-verified] [--name-contains TEXT] [--viewable-only]` | List saved metrics. The server list includes metrics that you cannot view; `--viewable-only` drops them. The filters apply locally. `--format table` shows `id`, `name`, `type`, `verified`, `can_view`, `modified`. |
| `mp metrics get ID` | Print one saved metric with its definition. |
| `mp metrics create --name NAME --definition-file FILE\|- [--kind metric\|formula\|warehouse] [--warehouse-source-id N] [--description TEXT] [--owner-id N] [--verified] [--no-validate]` | Create a saved metric from a wire definition (the `definition` object that `get` prints). `--kind` defaults to formula for a formula block, warehouse for a query, otherwise metric. The owner and the verified flag go in a second request. |
| `mp metrics update ID [--name] [--description] [--definition-file FILE\|-] [--kind] [--warehouse-source-id N] [--owner-id N] [--verified \| --no-verified] [--no-validate]` | Change the options you pass. A new definition must keep the kind; it keeps the stored display and goals unless it sets them. |
| `mp metrics verify ID [ID ...] [--unverify]` | Set (or clear) the verified flag in one request; skipped IDs are named on stderr. |
| `mp metrics delete ID [ID ...] [--force]` | One ID: read, then delete (an unknown ID fails and deletes nothing). Several IDs: one list read, then one bulk request; the server skips unknown IDs. A metric whose `can_update_basic` is false for your account is refused before any delete (a superadmin's delete would reach metrics that other users own); `--force` deletes it anyway. No prompt; the message goes to stderr. |
| `mp behaviors list [--type simple\|funnel\|retention] [--name-contains TEXT]` | List saved behaviors. `--format table` shows `id`, `name`, `type`, `verified`, `can_view`, `modified`. |
| `mp behaviors get ID` | Print one saved behavior with its definition. The server answers an unknown ID with a 500. |
| `mp behaviors create --name NAME --definition-file FILE\|- [--description TEXT] [--no-validate]` | Create a saved behavior from a wire definition (`{"behavior": {...}}`); the type comes from `behavior.type`. |
| `mp behaviors update ID [--name] [--description] [--definition-file FILE\|-] [--verified \| --no-verified] [--no-validate]` | Change the options you pass. A new definition must keep the behavior type. |
| `mp behaviors delete ID [ID ...] [--force]` | Same rules as `mp metrics delete`, including the `can_update_basic` guard and `--force`, through the bulk behavior route. |

## Built-in help

`mp help` prints an offline API reference from the installed package. It needs no credentials, ignores `-a / -p / -w / -t`, and never contacts Mixpanel. Full walkthrough: [Built-in Help guide](../guide/built-in-help.md).

| Command | Purpose |
|---------|---------|
| `mp help [QUERY...] [-f text\|markdown\|json] [--jq EXPR] [--domain NAME] [--no-hints]` | Describe one name (`Workspace.query`, `Filter`, `MathType`, `exceptions`, `types`, `accounts`, …) or search (`mp help search cohort`). Tokens are joined with spaces. The default format is `text`; `--jq` requires `-f json`; `--domain` applies to `Workspace` only. |
| `python3 -m mixpanel_headless help [QUERY...] [options]` | Same command through the module entry point, for environments where `mp` is not on `PATH`. |

Exit codes: 0 found, or a search with hits; 2 for an option value the parser rejects (`-f table`); 3 for `--jq` without `-f json`, a bare `search` with no term, or a `--domain` that is unknown, ambiguous, or given with anything other than the `Workspace` query, including `search` and the overview (message on stderr, nothing on stdout); 4 for a miss or a search with zero hits (the miss line and search view print to stdout first; under `-f json`, `--jq` filters the miss object too). The full table is in the [guide](../guide/built-in-help.md#exit-codes-and-errors).

::: mkdocs-typer
    :module: mixpanel_headless.cli.main
    :command: app
    :prog_name: mp
    :depth: 2
