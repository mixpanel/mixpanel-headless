---
type: llm
focus: { source: file, path: add_intro.py }
---

PASS if the text card body is HTML (for example `<h2>` and `<p>` tags, not Markdown `#` headings) and the HTML string that is sent contains no newline characters: either it is written on one line, or the code removes newlines before sending (for example `.replace("\n", "")`), and the card is created with a content action (`"action": "create"`, `"content_type": "text"`) inside `UpdateDashboardParams` passed to `update_dashboard(123, ...)`.
FAIL if the card uses Markdown instead of HTML, if a multi-line HTML string is sent as-is, or if the code does not use a create content action on dashboard 123.
