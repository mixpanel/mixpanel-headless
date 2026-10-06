---
description: A funnel whose first step is "A or B". A funnel step takes one event, so the script should use one custom event for the step ("$custom_event:<id>") or explain the limit, not pass a list of events as one step.
tags: [offline]
max_turns: 25
timeout_seconds: 420
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write]
---

Write a mixpanel_headless script for a two-step funnel over the last 30 days. Step 1 is a user who did either "Login" or "SSO Login". Step 2 is "Purchase". Save it as login_funnel.py in the current directory. Do not run it; I will run it myself later.
