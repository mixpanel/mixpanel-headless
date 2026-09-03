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

::: mkdocs-typer
    :module: mixpanel_headless.cli.main
    :command: app
    :prog_name: mp
    :depth: 2
