# CLI Commands

Complete reference for the `mp` command-line interface.

!!! tip "Explore on DeepWiki"
    🤖 **[CLI Command Reference →](https://deepwiki.com/mixpanel/mixpanel-headless/7.1-cli-command-reference)**

    Ask questions about specific commands, explore options, or get examples for your use case.

## Report links

Two `mp reports` verbs and an opt-in flag on four `mp query` commands turn queries into Mixpanel URLs and back. Full walkthrough: [Report Links guide](../guide/report-links.md).

| Command | Purpose |
|---------|---------|
| `mp reports link [--params JSON \| --params-file PATH \| -] [--type T] [--name] [--description] [--workspace-id] [--bookmark-id] [--no-validate]` | Store params as an unsaved report and print its URL. `-f plain` prints only the URL. |
| `mp reports resolve LINK [--run] [--mode sankey\|paths\|tree]` | Resolve a URL, slug, or shortlink to its params; `--run` runs it and prints the result. Quote URLs — `#` starts a shell comment. |
| `mp query segmentation ... --link` | Adds `report_url` (event, dates, unit, bare `--on` only; omitted with a warning when `--where` or an expression is present). |
| `mp query funnel ID ... --link`, `mp query saved-report ID --link`, `mp query flows ID --link` | Adds `report_url` for the saved report. No network call. |

Exit codes for the report-link errors: not found 4; parse, unsupported, and scope mismatch 3 (with a `hint:` line); auth 2; shortlink extraction 1.

::: mkdocs-typer
    :module: mixpanel_headless.cli.main
    :command: app
    :prog_name: mp
    :depth: 2
