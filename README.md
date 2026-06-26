# Daily Lunch Order Agent

A weekday lunch agent that picks a safe, in-budget meal for you and asks once on Discord — so you do not forget lunch and do not have to decide from a long menu.

**North star:** you never go hungry at lunch, and you never have to think about it. The agent must never become a new reason you miss lunch.

---

## Core design (what matters most)

These are the judgments the code is built around:

**Code owns safety.** Allergens, budget ceiling, no-go items, and main-meal-only picks are enforced in deterministic code — not by an LLM. If allergen status cannot be confirmed, the item is skipped (fail-closed). An optional model may only *tighten* keyword checks; it cannot override an unsafe result.

**Hard limits vs soft preferences.** Hard limits drop items. Soft preferences (cuisine, distance, ratings, favorites, recent variety) only affect ranking. Fallback meals are reserved for the failure ladder, not the daily pool.

**Help by exclusion, not by choice.** The agent filters and ranks, then presents **one** option. You react (`1` order / `2` another / `3` skip) instead of browsing.

**Failure ladder.** No valid pick → try fallbacks → notify you early. Placement fails → next candidate → fallbacks → notify. Status unknown after placement → **do not re-order** (no double charge); mark `needs-verification`.

**One confirmation per day.** Idempotency key `lunch-order-YYYY-MM-DD`. If today is already handled in state, the agent exits.

**Ranking favors what you can actually get.** After hard filters, survivors are scored with distance, Google rating (when enabled), budget, personal history, and a light cuisine tie-breaker. Distance, rating, and budget dominate; cuisine is capped so the agent is not locked to one type when the neighborhood lacks options.

---

## What is real vs modeled

| Piece | Status |
|-------|--------|
| Restaurant discovery (OSM / Overpass) | **Live** — no API key; set `LUNCH_AGENT_OSM_MODE=live` |
| Ratings, price level, Maps links (Google Places) | **Live** — optional; needs `GOOGLE_PLACES_API_KEY` |
| Discord confirmation (`1` / `2` / `3`, reminder, silence auto-order) | **Live** — REST bot; set `LUNCH_AGENT_CONFIRMATION=discord` |
| Checkout | **Deep link only** — DoorDash search URL on the card; agent does not complete payment |
| Mock menu / offline tests | **Default for `--once`** — `MockProvider` + fake transports for pytest |
| Uber Eats order placement | **Modeled** — interface + fake transport; live API needs Uber approval |
| Yelp discovery | **Optional** — live search; meal picks still synthetic |

The default **production-style demo** is OSM live + Google live + Discord live. Mock mode remains for fast offline runs and tests.

---

## Daily flow

1. A few minutes before lunch (or `--demo` on demand), the agent checks guards (not paused, not already handled today).
2. **Discover** nearby restaurants (OSM), filter closed (best-effort hours), enrich with Google (rating, price estimate, map link).
3. **Hard-filter** survivors (allergens, budget, no-go, unconfirmed allergens, non-mains).
4. **Rank** by distance, rating, budget, history; pick one from the top three (weighted random).
5. Send **one** Discord message: greeting, short discovery summary, pick card (distance, rating, `~$/person`, why, DoorDash + map links).
6. You reply `1` / `2` / `3`. Replying `1` records the choice and ends — no extra confirmation ping. `2` re-picks immediately. Silence → reminder → optional auto-order per prefs.

---

## How to run

```bash
pip install -r requirements.txt
python src/agent.py --onboard          # first-time setup

python src/agent.py --demo             # live demo now (OSM + Google + Discord); run only one instance
python src/agent.py --once             # offline simulated day (mock provider)
python src/agent.py --once --verbose   # same, with filter/rank trace

python src/scheduler.py                # poll clock; triggers on schedule (weekdays, lead_time before lunch)

python src/agent.py --rate "Item" up   # trust loop
python src/agent.py --block "Item"
python src/agent.py --summary

pytest                                 # 75 offline tests
```

**Demo tip:** if Discord shows duplicate cards, a stale `--demo` process is still running. Run `pkill -f "agent.py --demo"` before starting again.

---

## Setup & integrations

Copy `.env.example` to `.env`. Key settings:

| Goal | Env / prefs |
|------|-------------|
| Live discovery | `LUNCH_AGENT_OSM_MODE=live`, `OSM_LATITUDE`, `OSM_LONGITUDE`, `OSM_RADIUS_METERS`; `ordering_platform: osm` in `user_preferences.yaml` |
| Google enrichment | `LUNCH_AGENT_GOOGLE_PLACES_MODE=live`, `GOOGLE_PLACES_API_KEY` (enable **Places API** in Google Cloud) |
| Discord confirm | `LUNCH_AGENT_CONFIRMATION=discord`, `LUNCH_AGENT_DISCORD_MODE=live`, `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID` |
| Offline tests | `LUNCH_AGENT_OSM_MODE=fake`, `LUNCH_AGENT_GOOGLE_PLACES_MODE=off` or `fake`, `LUNCH_AGENT_DISCORD_MODE=fake` |

**Bellevue Key Center example:** `OSM_LATITUDE=47.6160`, `OSM_LONGITUDE=-122.1968`, `OSM_RADIUS_METERS=600`, timezone `America/Los_Angeles` in prefs.

**DoorDash link:** built in `src/order_links.py` with `?event_type=search`. Results still depend on the delivery address in your browser.

**Ghost VM:** clone repo, `bash scripts/ghost_setup.sh`, fill `.env`, run `python src/ghost_runner.py` (scheduler + Discord). See [agents.inference.ai](https://agents.inference.ai/).

Optional providers (`uber`, `yelp`) swap via `ordering_platform`; see source files for modeled vs live behavior.

---

## What we did not build

| Omitted | Why |
|---------|-----|
| Real payment / DoorDash API checkout | No stable public API; deep link is the honest handoff |
| Preference learning model | Ranked selection + ratings + weekly summary is enough for the trust loop |
| Calendar / GPS / weather signals | High cost; pause/skip covers "not today" |
| Full dashboard | CLI + `data/state.json` suffices |
| Uber live ordering | Modeled pending partner API access |

---

## Project layout

```
src/agent.py           Main loop: guard → filter → rank → confirm → record
src/osm_provider.py    OSM / Overpass discovery
src/google_places.py   Google Places enrichment
src/order_links.py     DoorDash / Maps deep links
src/discord_confirm.py Discord confirmation (fake or live)
src/provider.py        Provider interface + MockProvider
src/scheduler.py       Time-based trigger
src/ghost_runner.py    Ghost entry point
user_preferences.yaml  User config (onboarding)
SKILL.md               Full procedure and schema
tests/                 Offline pytest suite
```

For the complete agent procedure and config schema, see `SKILL.md`.
