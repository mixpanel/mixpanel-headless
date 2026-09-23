---
description: Mixpanel custom property formulas do not support \d or {n} quantifiers in regex.
tags: [offline]
max_turns: 20
timeout_seconds: 360
allowed_tools: [Read, Glob, Grep, Skill, Bash, Write]
---

I need a Mixpanel custom property formula. Our campaign_name values start with a 4-digit date code and an underscore, like "2407_Spring_Sale" or "2311_Black_Friday". The formula should strip that prefix so I get "Spring_Sale" and "Black_Friday". Write just the formula expression (the text I paste into the formula box, with the property as A) into formula.txt.
