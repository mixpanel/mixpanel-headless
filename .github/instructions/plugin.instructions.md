---
applyTo: "mixpanel-plugin/**"
---
# Claude Code plugin

- Skills teach analysis judgment. For API facts (signatures, types, allowed
  values), they point at `mp help` or `mp.help()`. They do not copy the
  reference.
- Skills run the plugin's own environment by full path:
  `${CLAUDE_PLUGIN_DATA}/venv/bin/python` and
  `${CLAUDE_PLUGIN_DATA}/venv/bin/mp`. Setup installs only into that
  environment, never into a system or user Python.
- Code examples in skill Markdown files catch `mp.MixpanelHeadlessError`
  or a specific subclass, not `Exception`. Scripts follow the library rule:
  a broad catch needs a `# noqa: BLE001` comment with the reason.
- Shell snippets keep stderr visible. Do not redirect it to `/dev/null`.
- Feature PRs do not change the plugin version.
