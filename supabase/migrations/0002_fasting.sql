-- ============================================================================
-- Fasting sessions
-- Run this in the Supabase SQL Editor (or `supabase db push`).
-- Safe to re-run: every statement is guarded.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- fasting_sessions — one row per fast, open while ended_at is null
-- ----------------------------------------------------------------------------
create table if not exists fasting_sessions (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references profiles (id) on delete cascade,
  started_at   timestamptz not null default now(),
  ended_at     timestamptz,
  -- The plan, not the outcome: a 16:8 fast stores 16 here whether or not it
  -- was seen through. Comparing target against the achieved duration is the
  -- whole point of keeping both.
  target_hours numeric not null default 16 check (target_hours > 0 and target_hours <= 168),
  note         text,
  created_at   timestamptz default now(),
  -- A fast cannot finish before it starts.
  check (ended_at is null or ended_at >= started_at)
);

-- One open fast per user. Enforced in the database rather than the router
-- because two rapid taps on "start" would otherwise race past any check the
-- application does, and an account with two open fasts has no correct answer
-- to "how long have I been fasting".
create unique index if not exists fasting_sessions_one_open_idx
  on fasting_sessions (user_id)
  where ended_at is null;

-- ----------------------------------------------------------------------------
-- Indexes
-- ----------------------------------------------------------------------------
create index if not exists fasting_sessions_user_started_idx
  on fasting_sessions (user_id, started_at desc);

-- ----------------------------------------------------------------------------
-- Row Level Security — same rule as every other user-scoped table
-- ----------------------------------------------------------------------------
alter table fasting_sessions enable row level security;

drop policy if exists "fasting_sessions: own rows only" on fasting_sessions;
create policy "fasting_sessions: own rows only" on fasting_sessions
  for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
