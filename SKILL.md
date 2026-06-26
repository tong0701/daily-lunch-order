---
name: daily-lunch-order
description: >-
  Orders lunch on a weekday schedule using deterministic filtering and
  confirmation. Invoke on the daily schedule trigger, when the user runs
  setup or onboarding, or when they ask to change, pause, resume, review,
  or rate lunch ordering preferences.
---

# Daily Lunch Order

North star: the user never goes hungry at lunch and never has to think about it.

The workflow lives in `src/agent.py`. Safety and decisions are enforced in code. An LLM is optional and only helps read messy menu text in `src/menu_matcher.py`.

## When to invoke

| Trigger | Action |
|---------|--------|
| Scheduled run (weekday, `lead_time_min` before `order_times`) | Run the daily workflow |
| First-time setup | Run `python src/agent.py --onboard` |
| User asks to change preferences | Run onboarding again or edit `user_preferences.yaml` |
| User asks to pause | Set `schedule.paused: true` or `pause_until` |
| User asks to resume | Clear pause fields |
| User asks to review history | Run `python src/agent.py --summary` |
| User gives thumbs up or down | Run `python src/agent.py --rate "Item Name" up` or `down` |
| User blocks an item | Run `python src/agent.py --block "Item Name"` |

## Procedure (each run)

Follow these steps in order. They match `src/agent.py`.

1. **Guard.** Exit without ordering if paused, today is not in `schedule.days`, or `data/state.json` already records today as `ordered`, `skipped`, `failed`, or `needs-verification`.

2. **Load config and history.** Read and validate `user_preferences.yaml`. Read `data/state.json`.

3. **Build candidates.** Search the provider menu (`ordering_platform`: `mock`, `osm`, `yelp`, or `uber`).
   - Hard filter: drop items over `budget.max_usd + budget.approved_overage_usd`; drop hard allergens, `no_go`, and `do_not_show_again`; drop items whose allergen status is not confirmed; drop sides and drinks (only `main` items can be the lunch pick); drop items matching `fallback_foods` (reserved for the fallback ladder).
   - Rank survivors by distance, Google rating (when enabled), cuisine preference (light tie-breaker), `favorites`, `dislikes_soft`, personal ratings, recent variety, and base-budget bonus.
   - Pick one option from the top three with weighted randomness.

4. **Confirm.** About `confirmation.lead_time_min` before `order_times`, present one main dish. With `LUNCH_AGENT_CONFIRMATION=discord`, post one card to Discord and wait for `1` / `2` / `3`. With the default mock path, use `--once --response`. On no response, remind once after `reminder_interval_min`; if still no response and `auto_order_on_no_response` is true, place the order.

5. **Place order.** Use idempotency key `lunch-order-YYYY-MM-DD`. Call `place_order`, then `get_order_status`.

6. **Failure ladder.** If no ranked candidate exists, try `fallback_foods` (main meals only). If placement fails, try the next ranked candidate, then fallbacks. If all paths fail, notify the user early to order manually. If status is unknown after a successful placement, mark `needs-verification` and do not re-order.

7. **Record outcome.** Write today's result to `data/state.json` (`status`, `item_name`, `price_usd`, `user_response`, `order_id`, `message`).

8. **Trust loop (after lunch).** Record ratings with `--rate`, review with `--summary`, block items with `--block` (adds to `no_go`).

## Configuration schema

All user settings live in `user_preferences.yaml`. Each field is marked as a **hard limit** (never broken in code) or a **soft preference** (ranking only).

### schedule

| Field | Type | Limit | Description |
|-------|------|-------|-------------|
| `order_times` | list of HH:MM | hard | Target lunch times. Scheduler triggers `lead_time_min` before each. |
| `timezone` | string | hard | IANA timezone for scheduling. |
| `days` | list | hard | Weekdays when the agent runs. |
| `paused` | bool | hard | When true, agent exits without ordering. |
| `pause_until` | date or null | hard | Pause through this date inclusive. |

### ordering_platform

| Field | Type | Limit | Description |
|-------|------|-------|-------------|
| `ordering_platform` | string | hard | Provider name: `mock` (default), `uber`, `yelp`, or `osm`. |

### budget

| Field | Type | Limit | Description |
|-------|------|-------|-------------|
| `max_usd` | float | hard | Base price ceiling. Must be at least $5. |
| `approved_overage_usd` | float | hard | Extra dollars allowed only when nothing fits under `max_usd`. Firm ceiling is `max_usd + approved_overage_usd`. |

### preferences

| Field | Type | Limit | Description |
|-------|------|-------|-------------|
| `allergens_hard` | list | hard | Never ordered. Unconfirmed menu items are treated as unsafe. |
| `no_go` | list | hard | Never ordered (preference). |
| `cuisine_ranking` | list | soft | Most to least preferred cuisines for ranking. |
| `dislikes_soft` | list | soft | Down-weighted in ranking, not excluded. |
| `favorites` | list | soft | Boosted in ranking. Should name main meals. |
| `fallback_foods` | list | hard | 3 to 5 trusted main meals used when nothing else fits. |

### confirmation

| Field | Type | Limit | Description |
|-------|------|-------|-------------|
| `lead_time_min` | int | hard | Minutes before `order_times` to send the confirmation. |
| `reminder_interval_min` | int | hard | Minutes to wait before a no-response reminder. |
| `auto_order_on_no_response` | bool | hard | When true, auto-order after the reminder if still silent. |

### State file (`data/state.json`)

| Field | Description |
|-------|-------------|
| `days` | Per-day outcomes for idempotency and history. |
| `ratings` | Thumbs up/down by item name. |
| `do_not_show_again` | Items blocked by the user (merged into `no_go`). |

## Error handling and fallback

### Failure ladder

| Situation | Action |
|-----------|--------|
| No valid ranked candidate | Try `fallback_foods` (main meals only). |
| Fallback also fails | Notify user early to order manually. Record `failed`. |
| Placement fails | Try next ranked candidate, then fallbacks, then notify. |
| Status unknown after placement | Do not re-order. Record `needs-verification`. Ask user to check the delivery app. |

### Invariants

1. **Never break a hard limit to succeed.** Allergens, budget ceiling, `no_go`, and main-meal-only picks are enforced in code.
2. **Never fail silently or too late.** If the agent cannot order safely, it tells the user with enough time to order manually.
3. **Never double-charge.** One idempotency key per day. No re-order when status is unknown.

### Other exits

| Situation | Action |
|-----------|--------|
| Paused or wrong day | Exit quietly (not an error). |
| Invalid config | Exit with a clear configuration error. |
| Today already handled | Exit without ordering. |

## Commands

```bash
# Setup
python src/agent.py --onboard

# Simulated day (user-facing output)
python src/agent.py --once

# Live demo (OSM + Google + Discord; skips schedule guard)
python src/agent.py --demo

# Simulated day with engine trace
python src/agent.py --once --verbose

# Production run
python src/agent.py

# Scheduler
python src/scheduler.py

# Trust loop
python src/agent.py --rate "Salmon Poke Bowl" up
python src/agent.py --block "Liver and Onions"
python src/agent.py --summary

# Tests
pytest
```

## Optional LLM

Set `LUNCH_AGENT_USE_LLM=true` and `OPENAI_API_KEY` to use a model for allergen checks on messy menu text. Default is keyword and tag matching only. All safety logic stays in code. The model may only tighten allergen checks; it can never override a keyword-level unsafe result.
