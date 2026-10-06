---
description: The user asks for a business number "as our analytics team defines it". The team's definition can be a saved metric, so the script should look for one with list_metrics and query a match by reference before it builds an inline definition.
tags: [offline]
max_turns: 25
timeout_seconds: 420
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write]
---

Write a mixpanel_headless script that reports our weekly checkout conversion rate for the last 12 weeks, using the definition that our analytics team uses in Mixpanel. Save it as checkout.py in the current directory. Do not run it; I will run it myself later.
