# Daily Lunch Order Agent

This agent orders lunch on a weekday schedule so you do not forget and do not have to decide. You set preferences once through onboarding; each day it picks a safe, in-budget main course, checks with you, and places the order.

**North star:** you never go hungry at lunch, and you never have to think about it. The agent must never become a new reason you miss lunch.

---

## Who this is for

A busy weekday professional who often skips lunch because they forget to order or get stuck deciding. Both failures end the same way: no lunch. The agent removes both causes.

---

## How it works

### What you set up

Run onboarding once: `python src/agent.py --onboard`. Using the sample config as an example:

| Setting | Role | Example |
|---------|------|---------|
| Schedule | Weekdays and lunch time; agent checks in ~5 min before | Mon-Fri, 12:00 |
| Budget | Max price plus a small approved overage; firm ceiling | $18 base, up to $21 |
| Allergens (hard) | Never ordered; unconfirmed items skipped | shellfish, peanuts |
| No-go (hard) | Never ordered | liver |
| Tastes (soft) | Rank options, do not exclude | cuisine order, dislikes, favorites |
| Fallback foods | Main meals tried when nothing else fits | turkey sandwich, garden salad, veggie wrap |
| Confirmation | Lead time, reminder interval, auto-order on silence | 5 min, 10 min, yes |

Hard settings keep you safe and on budget. Soft settings shape what you get. Fallbacks guarantee there is always something to try.

Only **main** meals can be the lunch pick. Sides and drinks may exist on the menu but never stand alone as lunch.

### Daily flow

1. **Setup (once).** Onboarding saves preferences. Allergens are read back for explicit confirmation.
2. **Each scheduled day**, a few minutes before lunch, the agent:
   - checks it has not already handled today and is not paused
   - filters the menu (allergens, no-go, budget, unconfirmed allergen data, non-mains)
   - ranks survivors by taste and variety, picks one main dish
   - sends one message: *"Lunch in 5 min: [pick]. Order it / show another / not today"*
3. **You reply, or you do not.**
   - *Order it* → places the order
   - *Show another* → re-picks immediately (no wait; you are present)
   - *Not today* → skips the day
   - *No reply* → reminds once after 10 minutes, then auto-orders
4. **On failure**, it tries the next option, then fallbacks, then notifies you early. It never breaks a hard limit, never fails silently, and never double-charges. If order status is unknown, it asks you to check instead of re-ordering.
5. **Over time**, rate items (thumbs up/down), review a weekly summary, or block items you never want again.

---

## Design rationale

These choices follow from the north star and the take-home scope (agent judgment over platform integration).

**The agent acts, it does not just remind.** A reminder-only agent is an alarm. Automation is the point. Every order stays inside hard limits, so the worst case is a lunch you did not actively want, not an unsafe or over-budget one.

**Help by exclusion, not by choice.** Decision fatigue means no menu handoff. The agent rules things out and presents one option. You react instead of choosing from many.

**Hard limits vs soft preferences.** Allergens, budget ceiling, and no-go are enforced in code. Cuisine ranking, dislikes, and favorites only affect ranking. If allergen status cannot be confirmed, the item is skipped. Fallback meals are reserved for the failure ladder, not the daily ranked pool.

**Confirmation UX.** Active disagreement and silence are treated differently. *Show another* re-picks now; the 10-minute wait applies only to silence.

**Trust over time (without a permission ramp).** Trust means the agent gets more accurate and asks less, not that it earns the right to spend more freely. Light feedback (rate, block, weekly summary) closes the loop without a dashboard or learning model.

**Runs with any LLM, or none.** Filter, pick, confirm, order, and failure handling are deterministic. A model only helps read messy menu text for allergen checks. When enabled, it may only **tighten** checks; it can never override a keyword-level unsafe result.

**Mock provider by design.** There is no open lunch-ordering API worth integrating for this exercise. A provider interface plus `MockProvider` keeps the demo offline and swappable later.

---

## What was left out (and why)

| Feature | Why |
|---------|-----|
| Real payment onboarding | Assumed pre-configured; separate problem |
| Live delivery API | Provider interface + mock; logic is the deliverable |
| Preference learning model | Ranked selection, ratings, and weekly summary show the trust loop |
| Full dashboard | CLI and JSON state are enough |
| Side or drink add-ons | Only mains are picked; add-on ordering is future work |
| Live confirmation loop | Lead-time push, reminder, and auto-order on silence are designed and simulated via `--response`, but production auto-orders immediately without waiting for a real reply. Next: push/SMS/chat outbound, inbound callbacks, timeout jobs |
| Calendar, location, weather signals | High integration and privacy cost; pause/skip covers "do not order today" |
| Pushing untried items | Trust-first; stay inside stated preferences |
| Delivery, refunds, support | Agent scope ends at a good order placed and confirmed |
| Health or diet goals | Different product; would blur the focus |
| Substring preference matching | Works for the demo; structured tags would be more robust |

---

## Requirements

- Python 3.10+
- `pip install -r requirements.txt`

No network calls in the default mock path. Optional LLM: `openai`, `OPENAI_API_KEY`, and `LUNCH_AGENT_USE_LLM=true`.

## How to run

```bash
pip install -r requirements.txt

# First-time setup
python src/agent.py --onboard

# Simulated day (clean user output)
python src/agent.py --once

# Simulated day with filter/rank trace
python src/agent.py --once --verbose

# Normal run (respects schedule and idempotency)
python src/agent.py

# Scheduler loop
python src/scheduler.py

# Trust loop
python src/agent.py --rate "Salmon Poke Bowl" up
python src/agent.py --block "Liver and Onions"
python src/agent.py --summary

# Tests
pytest
```

## Assumptions

- Payment is already configured on the delivery platform.
- Notifications in production would use push, SMS, or chat; the demo prints to stdout.
- `user_preferences.yaml` is created by onboarding and validated on every run.
- Timezone and schedule in preferences are authoritative.

## Project layout

```
SKILL.md                 Agent specification (procedure, schema, failure ladder)
user_preferences.yaml    User config (created by onboarding)
data/state.json          Per-day history (gitignored)
src/agent.py             Deterministic run loop
src/onboard.py           Interactive setup
src/config.py            Preference validation
src/provider.py          Provider interface + MockProvider
src/menu_matcher.py      Keyword allergen matching (optional LLM)
src/scheduler.py         Time-based trigger
tests/                   Offline pytest suite
```

For the full agent procedure and config schema, see `SKILL.md`.
