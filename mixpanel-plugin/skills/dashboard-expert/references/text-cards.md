# Text cards

How to write dashboard text cards that render correctly, and how to add data-driven explainer cards in Explain mode.

## Contents

- [1. Allowed HTML](#1-allowed-html)
- [2. Formatting rules](#2-formatting-rules)
- [3. Card patterns](#3-card-patterns)
- [4. Send a card](#4-send-a-card)
- [5. Explain mode](#5-explain-mode)

---

## 1. Allowed HTML

Mixpanel renders text cards in a TipTap editor. The editor sanitizes the HTML and keeps only these tags:

| Category | Tags | Notes |
|---|---|---|
| Headings | `<h1>`, `<h2>`, `<h3>` | Use `<h2>` and `<h3>`. `<h1>` is too large for a card. |
| Text | `<p>`, `<strong>`, `<em>`, `<u>`, `<s>`, `<mark>`, `<code>` | |
| Structure | `<blockquote>`, `<hr>`, `<br>` | `<blockquote>` shows as an indented block with a left border. |
| Lists | `<ul>`, `<ol>`, `<li>` | Nested lists work. |
| Links | `<a href="...">` | External links open in a new tab. |

The sanitizer removes these without a warning, so the card renders without them:

| Removed | Use instead |
|---|---|
| `<div>` | `<p>` |
| `<span>` | `<strong>`, `<em>`, or another inline tag |
| `<b>` | `<strong>` |
| `<i>` | `<em>` |
| `<img>` | Nothing; images are not supported |
| `<table>`, `<tr>`, `<td>`, `<th>` | A report with the `table` chart type |
| `style` and `class` attributes | Semantic tags |

---

## 2. Formatting rules

1. **Remove every newline before you send.** Call `.replace("\n", "").strip()` on the HTML. With newlines, the editor takes a markdown code path and garbles the HTML. Runs of spaces or tabs can also break the rendering, so collapse them.
2. **Each element is one visual line.** One `<p>` is one line, and two `<p>` tags are two lines. Do not use `\n` for line breaks.
3. **Keep a card short.** The limit is 2,000 characters. Keep a card under 500 characters, because a dashboard card has little vertical space.
4. **Use HTML, not markdown.** The field is named `markdown`, but `# Heading` and `**bold**` show as literal text. Use `<h2>Heading</h2>` and `<strong>bold</strong>`.
5. **Section header:** `<h2>Section Title</h2><p>One sentence.</p>`. Keep the title to 2 to 4 words.
6. **Explainer:** `<p>^ One data-driven finding about the chart above.</p>`. The `^` shows that the card explains the chart directly above it.
7. **Every dashboard gets an intro card and section headers.** The intro says what the dashboard is for and its time period. The headers group the reports, and the analyze steps use them to find sections.

To write a card over several source lines, use Python string concatenation. Adjacent string literals join with no newline:

```python
wrong = "<h2>Title</h2>\n<p>Description</p>"  # the newline garbles the card

right = (
    "<h2>Title</h2>"
    "<p>Description</p>"
)
```

---

## 3. Card patterns

```text
Intro:        <h2>Product Health</h2><p>Core product metrics. Time period: last 90 days.</p>
Section:      <h2>Acquisition</h2><p>How users find the product and sign up.</p>
Explainer:    <p>^ Signup conversion is <strong>23.4%</strong>, up 2.1 points.</p>
Methodology:  <p><em>Methodology:</em> DAU counts unique users who sent any event in a calendar day.</p>
Takeaway:     <h3>Key Takeaway</h3><p>Mobile converts <strong>2.3x</strong> better than desktop.</p>
Caveat:       <p><strong>Note:</strong> Data before Jan 15 uses the old tracking plan. Do not compare across that date.</p>
Callout:      <blockquote>This dashboard covers acquisition, activation, and retention. Revenue is on the Revenue dashboard.</blockquote>
```

A bullet summary:

```python
markdown = (
    "<h3>Q1 Highlights</h3>"
    "<ul>"
    "<li>DAU grew <strong>18%</strong> quarter over quarter</li>"
    "<li>Signup funnel conversion rose from 12% to 15%</li>"
    "<li>7-day retention held at <strong>42%</strong></li>"
    "</ul>"
)
```

---

## 4. Send a card

```python
import mixpanel_headless as mp
from mixpanel_headless.types import UpdateDashboardParams, UpdateTextCardParams

ws = mp.Workspace()
html = (
    "<h2>Section Title</h2>"
    "<p>Paragraph one.</p>"
    "<p>Paragraph two.</p>"
).replace("\n", "").strip()

# New card: goes to a new full-width row at the bottom
ws.update_dashboard(dashboard_id, UpdateDashboardParams(
    content={
        "action": "create",
        "content_type": "text",
        "content_params": {"markdown": html},
    }
))

# Existing card: the ID is the content_id of its layout cell
ws.update_text_card(dashboard_id, text_card_id, UpdateTextCardParams(markdown=html))
```

To place a new card at a specific position, move its row after the create. Row IDs change after a create, so read the dashboard again first.

---

## 5. Explain mode

Explain mode adds data-driven cards to an existing dashboard.

1. **Analyze.** Read the dashboard structure and run every report (the analyze steps in `SKILL.md`).
2. **Compute the finding.** Use numbers from `result.df`, not estimates. A text card that states a wrong number is worse than no card.
3. **Write the card.** One finding per card, with the key number in `<strong>`.
4. **Insert the card** under the chart it explains, and check the result in Mixpanel.

```python
latest = df.iloc[-1]["count"]
previous = df.iloc[-8]["count"]  # same weekday, one week earlier, for a daily series
change = (latest - previous) / previous * 100
direction = "up" if change > 0 else "down"
html = (
    f"<p>^ DAU is <strong>{latest:,.0f}</strong>, "
    f"{direction} <strong>{abs(change):.1f}%</strong> vs. last week.</p>"
).replace("\n", "")

ws.update_dashboard(dashboard_id, UpdateDashboardParams(
    content={
        "action": "create",
        "content_type": "text",
        "content_params": {"markdown": html},
    }
))
```

Check the column names of `result.df` before you index it. The columns differ by report type and by breakdown.

Guard the arithmetic: a zero baseline makes the percent change undefined. State "new this week" or leave the change out in that case.
