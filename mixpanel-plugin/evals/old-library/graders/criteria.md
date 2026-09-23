---
type: llm
---

The user's `mp` printed "No such command 'help'". That means the mixpanel_headless on their laptop is older than 0.3.0, the release that added `mp help`.
PASS if the reply addresses that error: it says the installed mixpanel_headless is too old (or lacks the built-in reference) and tells the user how to upgrade (for example `pip install -U mixpanel_headless`, `uv tool upgrade`, or the plugin's setup command), or it gives them a working fallback for the reference such as `python3 -m mixpanel_headless help` together with an upgrade note.
FAIL if the reply ignores the error, or only says that `mp help` works in this environment without telling the user what to do on their laptop.
