---
type: llm
---

Ground truth from the fixtures: (1) a dead-tap burst on the "Apply" button next to the promo code field: 6 taps over about 1.7 seconds with no screen change, so the promo code never applied; (2) a rage burst on "Place order": 4 taps over about 1.6 seconds, and the "Order placed" screen arrived only after the burst, so the button responded slowly. The user then finished the order. Screens have no names; the only valid screen labels are text that appears on them, such as "Your cart", "Delivery details", "Order placed".
PASS if the reply reports both bursts with their control (Apply, Place order), their tap counts (6 and 4), and a time span for each (about 1.7 s and 1.6 s, or the start and end times), and it does not present an invented screen name as if the app labeled it.
Generic words for a step of the flow, such as "the cart" or "at checkout", are fine. An invented screen name is a specific title that is not text in the timeline, given as the screen's name, for example a bold or quoted "Checkout Screen", "Payment page", or "Promo screen".
FAIL if either burst is missing, if tap counts or spans are missing or wrong, if it invents friction the data does not show (a crash, an error message shown to the user, an abandoned order), or if it gives a screen an invented name.
