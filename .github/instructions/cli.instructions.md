---
applyTo: "src/mixpanel_headless/cli/**"
---
# CLI

Read first: `src/mixpanel_headless/cli/CLAUDE.md` and
`src/mixpanel_headless/cli/commands/CLAUDE.md` (command pattern, output
flow, exit codes).

- CLI modules do not import or construct `MixpanelAPIClient` or an httpx
  client. They reach Mixpanel through `Workspace`, the public namespaces
  (`mp.accounts`, `mp.session`, `mp.targets`), or an internal helper that
  owns its HTTP calls (for example, the region probe).
- Data output goes through `output_result()` and the formatters, so
  `--format` and `--jq` apply to it.
- An option that is valid only with another option fails with an error
  before any request. It is not silently ignored. Example: `mp help --jq`
  without `-f json` exits with code 3.
- Exit codes follow the `ExitCode` table in `cli/commands/CLAUDE.md`.

Greptile rule for this area: `cli-no-api-client`.
