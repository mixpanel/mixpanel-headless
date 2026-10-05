---
description: A funnel script that asks for a median time to convert. Funnel math="median" is property math, not time to convert, so the plugin should look the API up with mp help before it writes code and handle the median honestly.
tags: [offline]
max_turns: 25
timeout_seconds: 420
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write]
---

Using the mixpanel_headless Python library, write a script that computes the median time it takes users to convert from Signup to Purchase over the last 90 days, broken down by platform. Save it as funnel_median.py in the current directory. Do not run it; I will run it myself later.
