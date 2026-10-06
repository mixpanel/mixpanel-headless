---
description: A custom event named by its display name. Querying the display name returns zero rows with no error, so the script should find the custom event's id and query CustomEventRef(<id>) or "$custom_event:<id>".
tags: [offline]
max_turns: 25
timeout_seconds: 420
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write]
---

Our Mixpanel project has a custom event called "Signed In (any method)". Write a mixpanel_headless script that counts the unique users who did it each day over the last 30 days. Save it as signed_in.py in the current directory. Do not run it; I will run it myself later.
