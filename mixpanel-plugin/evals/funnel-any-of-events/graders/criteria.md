---
type: llm
---

Background: in mixpanel_headless, a funnel step takes one event, and `query_funnel()` refuses a list of events as a step. For "did A or B" as one step, the step is one custom event that covers both events, written as the event name `"$custom_event:<id>"`. The id is the `custom_event_id` of an entry of `ws.list_custom_events()`. A new custom event (`create_custom_event`) writes to the project.
PASS if the first step is one custom event that covers both login events: the script finds its id (for example in `ws.list_custom_events()`) and uses `"$custom_event:<id>"` as step 1, or it creates such a custom event and the reply says that this writes to the project, or the reply explains that a funnel step takes one event and asks the user for the custom event. Step 2 is "Purchase", over the last 30 days.
FAIL if the script passes a list of events (for example `["Login", "SSO Login"]`) as one step, invents a parameter for "any of", drops one of the two login events without saying so, or splits the question into two funnels without saying that this changes the answer.
