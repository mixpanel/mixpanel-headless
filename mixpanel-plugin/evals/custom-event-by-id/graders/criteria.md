---
type: llm
focus: { source: file, path: signed_in.py }
---

Background: in mixpanel_headless, a query for a custom event's display name, such as `ws.query("Signed In (any method)")`, looks for an event with that name, finds none, and returns zero rows with no error. A custom event runs by id: `CustomEventRef(<id>)` in `ws.query()`, or the event name `"$custom_event:<id>"`. The id is the `custom_event_id` of an entry of `ws.list_custom_events()`.
PASS if the script finds the custom event's id (for example by matching the name in `ws.list_custom_events()` and reading `custom_event_id`) and queries it by id with unique-user math, daily, over the last 30 days.
FAIL if the script passes the display name "Signed In (any method)" as an event name to a query, or uses an id that it never looks up and does not ask the user for.
