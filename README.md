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
   - ranks survivors by distance, rating, budget, personal history, variety, and a light cuisine preference, then picks one main dish
   - sends **one** message: a short greeting, a discovery summary, then the pick card (distance, rating, price, why) with reply options `1` order / `2` another / `3` skip
3. **You reply, or you do not.**
   - `1` order → records the choice (and shows a DoorDash link to finish checkout manually)
   - `2` another → re-picks immediately (no wait; you are present)
   - `3` skip → skips the day
   - *No reply* → reminds once after 10 minutes, then auto-orders
4. **On failure**, it tries the next option, then fallbacks, then notifies you early. It never breaks a hard limit, never fails silently, and never double-charges. If order status is unknown, it asks you to check instead of re-ordering.
5. **Over time**, rate items (thumbs up/down), review a weekly summary, or block items you never want again.

---

## Design rationale

These choices follow from the north star and the take-home scope (agent judgment over platform integration).

**The agent acts, it does not just remind.** A reminder-only agent is an alarm. Automation is the point. Every order stays inside hard limits, so the worst case is a lunch you did not actively want, not an unsafe or over-budget one.

**Help by exclusion, not by choice.** Decision fatigue means no menu handoff. The agent rules things out and presents one option. You react instead of choosing from many.

**Hard limits vs soft preferences.** Allergens, budget ceiling, and no-go are enforced in code. Cuisine ranking, dislikes, favorites, distance, personal ratings, and recent variety only affect ranking. If allergen status cannot be confirmed, the item is skipped. Fallback meals are reserved for the failure ladder, not the daily ranked pool.

**Multi-signal ranking (after hard filter).** Survivors are scored and sorted by:

| Signal | Effect |
|--------|--------|
| Distance (OSM lat/lng) | +20 within 200m, +12 within 400m, +6 within 600m |
| Favorite name match | +25 |
| Personal thumbs up (same restaurant/item) | +25 |
| Personal thumbs down | -30 |
| Google rating ≥ 4.5 | +10 |
| Google rating ≥ 4.0 | +5 |
| OSM Michelin `stars` tag | +15 per star |
| OSM `opening_hours` listed | +5 |
| Cuisine preference (`cuisine_ranking`) | up to +12, soft tie-breaker by list position |
| Under base budget | +3 |
| Soft dislikes | -8 each |
| Recent same item (5 days) | -20 |
| Recent same restaurant (3 days) | -20 |
| Recent same cuisine (3 days) | -8 |

The agent then weighted-random picks from the top three. **Distance, rating, and budget dominate; cuisine is only a light tie-breaker** so the agent is not locked to one cuisine when the neighborhood lacks options. OSM does not provide Yelp-style public ratings, so Google Places (when enabled), Michelin stars, and your own thumbs up/down are the rating inputs.

**Confirmation UX.** One message carries everything (greeting, discovery summary, pick card). Active disagreement and silence are treated differently: `2` re-picks now; the 10-minute wait applies only to silence. Replying `1` is itself the confirmation — no extra "order confirmed" ping is sent.

**Trust over time (without a permission ramp).** Trust means the agent gets more accurate and asks less, not that it earns the right to spend more freely. Light feedback (rate, block, weekly summary) closes the loop without a dashboard or learning model.

**Runs with any LLM, or none.** Filter, pick, confirm, order, and failure handling are deterministic. A model only helps read messy menu text for allergen checks. When enabled, it may only **tighten** checks; it can never override a keyword-level unsafe result.

**Mock provider by design.** There is no open lunch-ordering API worth integrating for this exercise. A provider interface plus `MockProvider` keeps the demo offline and swappable later.

---

## What was left out (and why)

| Feature | Why |
|---------|-----|
| Real payment onboarding | Assumed pre-configured; separate problem |
| Live delivery API | Provider interface + mock (default); optional `uber` provider modeled on Uber Consumer Delivery flow (see Integration notes) |
| Preference learning model | Ranked selection, ratings, and weekly summary show the trust loop |
| Full dashboard | CLI and JSON state are enough |
| Side or drink add-ons | Only mains are picked; add-on ordering is future work |
| Live confirmation loop | Lead-time push, reminder, and auto-order on silence are designed and simulated via `--response`, but production auto-orders immediately without waiting for a real reply. Next: push/SMS/chat outbound, inbound callbacks, timeout jobs |
| Calendar, location, weather signals | High integration and privacy cost; pause/skip covers "do not order today" |
| Pushing untried items | Trust-first; stay inside stated preferences |
| Delivery, refunds, support | Agent scope ends at a good order placed and confirmed |
| Health or diet goals | Different product; would blur the focus |
| Substring preference matching | Works for the demo; structured tags would be more robust |

### Integration notes (Uber Eats)

The optional `uber` provider is modeled on Uber's public Consumer Delivery flow (account linking, merchant discovery, menu, cart, order submission, status). Exact endpoint paths and request/response schemas are not public and require Uber early-access approval; placeholder shapes in `src/uber_provider.py` are marked as modeled pending that spec. The HTTP layer runs offline via `FakeUberTransport` by default (`LUNCH_AGENT_UBER_MODE=fake`). Going live needs a linked Uber account (`UBER_ACCESS_TOKEN`), Uber written approval, and a real HTTP transport. Set `ordering_platform: uber` in `user_preferences.yaml` to select it.

### Integration notes (OpenStreetMap / Overpass)

The optional `osm` provider uses [Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API) to discover nearby restaurants from [OpenStreetMap](https://wiki.openstreetmap.org/wiki/Tag:amenity=restaurant). **No API key required.** Default mode is offline (`LUNCH_AGENT_OSM_MODE=fake`) with canned OSM-shaped data. Set `LUNCH_AGENT_OSM_MODE=live` to query `overpass-api.de` with `OSM_LATITUDE`, `OSM_LONGITUDE`, and `OSM_RADIUS_METERS`.

Discovery runs three steps before ranking:

1. Find nearby `amenity=restaurant|fast_food|cafe` within radius
2. Filter by `opening_hours` (best-effort open/closed check for today)
3. Surface Michelin `stars` and `description` tags — OSM does **not** have Yelp-style user ratings or reviews

Each discovered restaurant becomes a synthetic lunch item with `dist_m=...`, `price_est=...`, `price_source=...`, and optional Google rating metadata for ranking.

### Integration notes (Google Places enrichment)

Optional layer on top of OSM discovery. Google does **not** return an exact per-person dollar amount; it returns `price_level` (`$` to `$$$$`), star rating, review count, and location.

| Mode | Env | Behavior |
|------|-----|----------|
| `off` (default) | `LUNCH_AGENT_GOOGLE_PLACES_MODE=off` | Heuristic price from OSM `amenity` + `cuisine` |
| `fake` | `LUNCH_AGENT_GOOGLE_PLACES_MODE=fake` | Offline canned Google matches for tests |
| `live` | `LUNCH_AGENT_GOOGLE_PLACES_MODE=live` + `GOOGLE_PLACES_API_KEY` | Nearby Search near `OSM_LATITUDE` / `OSM_LONGITUDE` |

### Google Cloud setup (Places API)

Do this once:

1. Open [Google Cloud Console](https://console.cloud.google.com/)
2. Create or select a project
3. Go to **APIs & Services → Library**
4. Search **Places API** and click **Enable**
5. Go to **APIs & Services → Credentials**
6. Click **Create credentials → API key**
7. Copy the key into `.env` as `GOOGLE_PLACES_API_KEY`
8. Recommended: edit the key and restrict it to **Places API** only
9. Billing must be enabled on the project (Google includes monthly free credits)

Then in `.env`:

```bash
LUNCH_AGENT_OSM_MODE=live
OSM_LATITUDE=47.6160
OSM_LONGITUDE=-122.1968
OSM_RADIUS_METERS=600
LUNCH_AGENT_GOOGLE_PLACES_MODE=live
GOOGLE_PLACES_API_KEY=your-key-here
LUNCH_AGENT_CONFIRMATION=discord
```

Quick test without Google:

```bash
LUNCH_AGENT_GOOGLE_PLACES_MODE=off python src/agent.py --once --verbose
```

With Google live:

```bash
set -a && source .env && set +a
python src/agent.py --once --verbose
```

Price mapping used by the agent:

| Google `price_level` | Estimated lunch price |
|----------------------|----------------------|
| `$` (1) | ~$12 |
| `$$` (2) | ~$20 |
| `$$$` (3) | ~$32 |
| `$$$$` (4) | ~$50 |

Without Google, heuristic defaults apply (`fast_food` ~$12, `cafe` ~$15, `restaurant` ~$25, cuisine-adjusted).

### Checkout via DoorDash deep link

The agent does not complete payment. The pick card carries a **DoorDash search link** for that restaurant so you can finish checkout manually. This avoids brittle browser automation and does not require DoorDash API access. The link includes `?event_type=search` so DoorDash opens directly on the search results (results are still delivery-address dependent on DoorDash's side).

Example card line:

```text
🛒 Order on DoorDash: https://www.doordash.com/search/store/Chipotle?event_type=search
🗺️ Map: https://www.google.com/maps/place/?q=place_id:...
```

`src/order_links.py` builds these links from the restaurant name. The Map link appears when Google Places enrichment is enabled.

Menu items are synthetic lunch picks built from discovered restaurants. Set `ordering_platform: osm` in `user_preferences.yaml`.

Bellevue Key Center example (live):

```bash
# .env
LUNCH_AGENT_OSM_MODE=live
OSM_LATITUDE=47.6160
OSM_LONGITUDE=-122.1968
OSM_RADIUS_METERS=600
```

```bash
LUNCH_AGENT_OSM_MODE=fake python src/agent.py --once --verbose
```

### Integration notes (Yelp discovery)

The optional `yelp` provider uses [Yelp Fusion](https://docs.developer.yelp.com/docs/fusion-intro) to discover **open nearby restaurants** (`LUNCH_AGENT_YELP_MODE=live` needs `YELP_API_KEY`, `YELP_LATITUDE`, `YELP_LONGITUDE`). Yelp does not expose full menus or consumer ordering in the public API, so meal picks still come from the mock catalog filtered to discovered restaurants. Each item description includes a Yelp page link when matched. `place_order` remains simulated via the inner mock layer. Set `ordering_platform: yelp` in `user_preferences.yaml`.

Offline demo:

```bash
LUNCH_AGENT_YELP_MODE=fake python src/agent.py --once --verbose
```

Live discovery + Discord:

```bash
# .env: YELP_API_KEY, YELP_LATITUDE, YELP_LONGITUDE, ordering_platform: yelp
LUNCH_AGENT_CONFIRMATION=discord python src/agent.py  # scheduled run
```

### Running on Inference Ghost

Ghost provides the always-on VM and Discord channel. The agent logic stays the same; production confirmation uses Discord instead of `--response`.

1. Provision a Ghost VM at [agents.inference.ai](https://agents.inference.ai/) and connect Discord (dashboard toggle + bot token).
2. SSH into the VM, clone this repo, run `bash scripts/ghost_setup.sh`.
3. Copy `.env.example` to `.env` and set `DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`.
4. Run onboarding: `python src/agent.py --onboard`.
5. Start the service: `set -a && source .env && set +a && python src/ghost_runner.py`.

`ghost_runner.py` sets `LUNCH_AGENT_CONFIRMATION=discord` and runs `scheduler.py`. At each trigger it posts to Discord, waits for your reply (`1` / `2` / `3`), then places the order through the configured provider (`mock` or `uber`). Menu and order still use the provider layer; Uber live API remains pending approval.

Local dry run with fake Discord (no network):

```bash
LUNCH_AGENT_CONFIRMATION=discord LUNCH_AGENT_DISCORD_MODE=fake \
  DISCORD_BOT_TOKEN=test DISCORD_CHANNEL_ID=test \
  python src/agent.py --once
```

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

# Live demo now (real OSM + Google + Discord; skips the clock/schedule guard)
# Reply 1/2/3 in Discord. Run only one at a time to avoid duplicate cards.
python src/agent.py --demo

# Uber provider (offline fake transport; set ordering_platform: uber in prefs)
LUNCH_AGENT_UBER_MODE=fake python src/agent.py --once --verbose

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
src/osm_provider.py      OpenStreetMap/Overpass discovery (live, no API key)
src/google_places.py     Google Places enrichment (price/rating, optional)
src/order_links.py       DoorDash / Maps deep links for manual checkout
src/uber_provider.py     Uber Consumer Delivery provider (offline fake transport)
src/yelp_provider.py     Yelp Fusion discovery + mock menu catalog
src/menu_matcher.py      Keyword allergen matching (optional LLM)
src/scheduler.py         Time-based trigger
src/discord_confirm.py   Discord confirmation (REST, fake or live)
src/ghost_runner.py      Ghost VM entry point (scheduler + Discord)
scripts/ghost_setup.sh   Bootstrap on Ghost
tests/                   Offline pytest suite
```

For the full agent procedure and config schema, see `SKILL.md`.
