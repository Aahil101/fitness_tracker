# Pulse — AI nutrition & fitness tracker

A personal-use nutrition and fitness tracker for a small group (5–10 people). Photograph a
meal to log it, watch your calorie deficit fill in real time, and see where your current pace
puts your weight. Every service it depends on stays inside a free tier at this scale.

- **Frontend** React 18 + Vite + TypeScript, installable PWA, Material You (MD3) design system
- **Backend** FastAPI (Python 3.11+)
- **Data / auth / storage** Supabase — Postgres, Row Level Security, Auth, private photo bucket
- **Cache & rate limits** Upstash Redis (optional; falls back to an in-process cache)
- **Food vision** Gemini, structured JSON output
- **Nutrition data** USDA FoodData Central
- **Charts** Recharts
- **Hosting** Vercel (web) + Render or Railway (API)

---

## What it does

**Photo food logging.** A photo goes to Gemini, which returns each food it can see with an
estimated weight in grams and a confidence score. Each item is resolved against the shared
`food_items` cache first, then USDA FoodData Central, and the result is scaled to the portion.
You always get an editable draft — nothing is written to your log until you confirm it.

**Deficit tracking.** Maintenance calories come from Mifflin-St Jeor plus an activity
multiplier. Your daily target is maintenance minus the daily share of your weekly goal, with a
30%-below-maintenance cap and a 1,200 kcal floor enforced in code rather than in the UI.

**Weight forecasting.** Two numbers, answering different questions:

- *Projected* — the trailing N-day mean of `calories_in − (maintenance + exercise burn)`,
  converted at 7,700 kcal/kg. Reacts immediately when behaviour changes.
- *Measured* — an ordinary least-squares fit through your weigh-ins. Slower, but it captures
  under-reporting and metabolic adaptation that arithmetic cannot.

Time-to-goal uses the measured trend once there are at least 14 days of weigh-ins, and the
calorie estimate before that. Days with no food logged are excluded from the average — counting
a forgotten day as a 2,000 kcal deficit would wreck the projection.

**AI coach.** Every message re-sends a compact JSON snapshot of your real numbers (targets,
today's entries, 14-day averages, weight trend, forecast) plus the last turns of the
conversation. The model is instructed never to invent a figure. History is persisted per session
in Postgres, so it survives reloads and device switches.

**Generated recaps.** Daily, weekly and monthly summaries. The metrics are computed
server-side and the model only writes the prose, so the numbers on screen always match the log.
If Gemini is unavailable the backend falls back to a rule-based summary instead of erroring.

**Workouts.** A 43-activity MET table suggests `MET × body mass × hours`, editable because a
watch reading beats a table. Queryable by hour, day or week.

---

## Repository layout

```
backend/                FastAPI service
  app/
    config.py           settings from env
    security.py         Supabase JWT verification (JWKS + legacy HS256)
    db.py               PostgREST client carrying the end user's token
    cache.py            Upstash Redis + fixed-window rate limiter
    deps.py             request context: profile, active goal, timezone
    services/
      energy.py         Mifflin-St Jeor, TDEE, macro split, deficit guard rails
      forecast.py       rolling net-balance projection + OLS weight regression
      met.py            MET table and burn estimation
      aggregate.py      timezone-aware day bucketing and roll-ups
      usda.py           FoodData Central client (normalised to per-100 g)
      gemini.py         vision, chat and structured-output calls
      insights.py       recap generation with a deterministic fallback
    routers/            profile, goals, food, workouts, weight, dashboard, ai, chat
  tests/                45 unit tests, no credentials required
frontend/
  src/
    components/md/      MD3 primitives (Button, TextField, Sheet, Chip, FAB, Toast…)
    components/         CalorieGauge, HomeGauge, AppShell, InsightCard
    components/logging/ food / weight / workout entry flows
    components/charts/  Recharts wrappers themed from the MD3 tokens
    pages/              Auth, Onboarding, Dashboard, Diary, Analytics, Coach, Settings
    hooks/              auth, theme, React Query bindings
    lib/                api client, Supabase client, formatters, types
supabase/migrations/    schema + RLS + storage policies
```

---

## Setup

### 1. Get the free API keys

| Service | Where | Needed? |
| --- | --- | --- |
| Supabase | [supabase.com/dashboard](https://supabase.com/dashboard) → new project → Settings → API | **Required** |
| Gemini | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Required for photo logging, coach and recaps |
| USDA FoodData Central | [fdc.nal.usda.gov/api-key-signup](https://fdc.nal.usda.gov/api-key-signup) | Required for nutrition lookup (`DEMO_KEY` works for a quick try) |
| Upstash Redis | [console.upstash.com](https://console.upstash.com) → database → REST API | Optional |

The app degrades honestly without the optional ones: search and manual entry work without
Gemini, and the cache falls back to an in-process store without Upstash.

### 2. Create the database

In the Supabase SQL editor, paste and run
[`supabase/migrations/0001_init.sql`](supabase/migrations/0001_init.sql). It creates every
table, the RLS policies, the private `food-photos` bucket with per-user path policies, and a
trigger that creates a profile row on signup. The script is idempotent — re-running it is safe.

### 3. Configure and run

```bash
make setup     # venv + npm install + copies both .env templates
```

Fill in `backend/.env` and `frontend/.env.local` (see `.env.example` in each), then:

```bash
make backend   # http://127.0.0.1:8000  (docs at /docs)
make web       # http://127.0.0.1:5173
```

Without `make`:

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/uvicorn app.main:app --reload --port 8000

cd frontend && npm install && npm run dev
```

`GET /health` reports which integrations are wired up without echoing any secret.

---

## Deployment

### Frontend → Vercel

Import the repo, set **Root Directory** to `frontend` (`vercel.json` covers the rest), and add:

```
VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY, VITE_API_BASE_URL
```

`VITE_API_BASE_URL` is your deployed API origin. Only `VITE_`-prefixed values reach the
browser — never put the Gemini key or a service role key there.

### Backend → Render or Railway

- **Render** — "New Blueprint" picks up [`render.yaml`](render.yaml). Set the secret env vars in
  the dashboard. Free web services sleep after ~15 minutes idle, so the first request afterwards
  takes a few seconds.
- **Railway** — deploys `backend/Dockerfile` via [`backend/railway.json`](backend/railway.json).
- **Anywhere with Docker** —
  `docker build -t pulse-api backend && docker run -p 8000:8000 --env-file backend/.env pulse-api`

Then set `CORS_ORIGINS` on the API to your Vercel domain. `*.vercel.app` preview URLs are
already allowed by a regex, so previews work without extra configuration.

### Supabase

Add your production URL under Authentication → URL Configuration → Redirect URLs, otherwise
email confirmation and Google OAuth will bounce back to localhost. Google sign-in also needs
the provider enabled under Authentication → Providers.

---

## Design system

Material You (MD3) built from a `#6750A4` seed. Tokens live as CSS variables holding **RGB
channels** rather than hex, which is what lets Tailwind's alpha modifiers express the MD3
state-layer model as ordinary utilities (`bg-md-primary/90` for hover, `/10` for a ghost
button) and makes light/dark a single class on `<html>`.

Conventions in use: pill-shaped buttons everywhere, filled text fields with rounded top
corners and a 2px bottom border that turns primary on focus, tonal surfaces instead of borders
for separation, 24px cards and 32–48px hero containers, `cubic-bezier(0.2, 0, 0, 1)` easing,
`active:scale-95` on everything tappable, layered blurred organic shapes for atmosphere, and
`prefers-reduced-motion` respected globally.

### The calorie gauge

`src/components/CalorieGauge.tsx` is hand-rolled SVG, not a chart library, so it stays crisp at
any size and restyling is a token change. Three layers, back to front:

1. **Track** — neutral, spans 0 → maintenance calories. The ceiling reference.
2. **Fill** — teal, 0 → calories logged today. Ramps to amber past your goal and to error red
   past maintenance.
3. **Goal marker** — a coral radial tick at your daily target. A tick, never a fill, so it
   cannot be mistaken for progress.

Orientation is a single constant:

```ts
const ORIENTATION: Orientation = 'flat-top';  // flat side up (default), or 'flat-bottom'
const ZERO_ON_LEFT = true;                    // false mirrors the scale
```

Every point is derived from the angle helpers, so flipping either value needs no other edit.
All four combinations are verified geometrically.

---

## Notes on the maths

**MET burn double-counts.** MET values describe *total* energy expenditure, so they overlap
with the activity multiplier already baked into your maintenance figure. If you log workouts
individually, set activity level to **sedentary** — the app warns about this in onboarding, in
the workout sheet and in settings.

**Averages divide by days logged, not days elapsed.** Dividing a 3-day week by 7 understates
intake and makes the number useless.

**Nothing is ML.** With 5–10 users and a few hundred rows there is nothing to learn that the
arithmetic does not already say. Gemini is used for vision and for writing prose — never for
computing a number you see.

**Timezones.** Every day boundary is computed in the user's timezone and then converted to UTC
for querying. Getting this wrong is how trackers show an empty gauge at 1 a.m.

---

## Security

- Row Level Security is the enforcement boundary. The API forwards each user's access token to
  PostgREST, so a bug in a handler cannot leak another user's rows.
- Access tokens are verified locally against the project JWKS (with legacy HS256 and a remote
  `/auth/v1/user` check as fallbacks).
- Food photos live in a private bucket; policies key on the first path segment matching
  `auth.uid()`, and reads go through short-lived signed URLs.
- The Gemini and USDA keys are server-side only.
- Per-user hourly rate limits on the vision, chat and recap endpoints keep a runaway loop
  inside the free tiers.
- The coach is instructed to refuse medical advice, to never suggest under 1,200 kcal/day or
  more than 1 kg/week, and to respond with care to signs of disordered eating.

---

## Tests

```bash
make test    # backend: 45 unit tests over the energy, forecast, MET,
             # aggregation and API-surface layers — no credentials needed
make lint    # ruff, eslint, tsc
make build   # production frontend build
```

CI runs all of it on every push ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)).
