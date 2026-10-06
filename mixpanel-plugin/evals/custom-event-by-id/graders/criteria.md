---
type: llm
focus: { source: file, path: signed_in.py }
---

Background: in mixpanel_headless, a query for a custom event's display name, such as `ws.query("Signed In (any method)")`, looks for an event with that name, finds none, and returns zero rows with no error. A custom event runs by id: `CustomEventRef(<id>)` in `ws.query()`, or the event name `"$custom_event:<id>"`. The id is the `custom_event_id` of an entry of `ws.list_custom_events()`. That listing can hold orphan entries whose `custom_event_id` is `None` or `0`, and several custom events can share one display name.
PASS if the script finds the id by matching the name in `ws.list_custom_events()`, keeps only entries with a positive `custom_event_id`, and handles both edge cases explicitly: no valid match (it stops with a clear message or asks for the id) and several valid matches (it stops and lists them, or takes an id from the user). It then queries that id with unique-user math, daily, over the last 30 days. Taking the id from the user instead of the listing also passes.
FAIL if the script passes the display name "Signed In (any method)" as an event name to a query, takes the first name match without the positive-id check or without handling several matches, or uses an id that it never looks up and does not ask the user for.
