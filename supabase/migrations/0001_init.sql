-- ============================================================================
-- AI Nutrition & Fitness Tracker — initial schema
-- Run this in the Supabase SQL Editor (or `supabase db push`).
-- Safe to re-run: every statement is guarded.
-- ============================================================================

create extension if not exists "pgcrypto";

-- ----------------------------------------------------------------------------
-- profiles
-- ----------------------------------------------------------------------------
-- NOTE (addition to the original brief): `sex` and `birth_date` are required by
-- the Mifflin-St Jeor equation, which the forecasting engine uses to derive
-- maintenance calories. They are nullable — the backend falls back to a neutral
-- average when they are missing — but accuracy degrades without them.
create table if not exists profiles (
  id                  uuid primary key references auth.users (id) on delete cascade,
  full_name           text,
  sex                 text check (sex in ('male', 'female', 'other')),
  birth_date          date,
  starting_weight_kg  numeric,
  goal_weight_kg      numeric,
  height_cm           numeric,
  activity_level      text default 'sedentary'
                        check (activity_level in ('sedentary', 'light', 'moderate', 'active')),
  unit_preference     text default 'metric' check (unit_preference in ('metric', 'imperial')),
  timezone            text default 'UTC',
  onboarded_at        timestamptz,
  created_at          timestamptz default now(),
  updated_at          timestamptz default now()
);

-- ----------------------------------------------------------------------------
-- goals — one row per "effective_from" date; latest row <= today wins
-- ----------------------------------------------------------------------------
create table if not exists goals (
  id                       uuid primary key default gen_random_uuid(),
  user_id                  uuid not null references profiles (id) on delete cascade,
  daily_calorie_target     int not null,   -- deficit-adjusted goal (maintenance - deficit)
  maintenance_calories     int not null,   -- TDEE at current weight/activity; gauge ceiling
  protein_target_g         numeric,
  carb_target_g            numeric,
  fat_target_g             numeric,
  fiber_target_g           numeric,
  target_weekly_deficit_kcal int,          -- e.g. -3500 for ~1 lb/week
  effective_from           date not null default current_date,
  created_at               timestamptz default now(),
  unique (user_id, effective_from)
);

-- ----------------------------------------------------------------------------
-- food_items — shared nutrition cache (USDA FoodData Central resolutions)
-- ----------------------------------------------------------------------------
create table if not exists food_items (
  id                 uuid primary key default gen_random_uuid(),
  fdc_id             text unique,
  name               text not null,
  brand              text,
  calories_per_100g  numeric,
  protein_per_100g   numeric,
  carbs_per_100g     numeric,
  fat_per_100g       numeric,
  fiber_per_100g     numeric,
  serving_size_g     numeric,
  data_source        text default 'usda',  -- usda | manual | ai
  created_at         timestamptz default now()
);

create index if not exists food_items_name_trgm_idx on food_items using gin (to_tsvector('english', name));

-- ----------------------------------------------------------------------------
-- food_logs
-- ----------------------------------------------------------------------------
create table if not exists food_logs (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references profiles (id) on delete cascade,
  logged_at     timestamptz not null default now(),
  meal_type     text check (meal_type in ('breakfast', 'lunch', 'dinner', 'snack')),
  food_item_id  uuid references food_items (id) on delete set null,
  food_name     text not null,
  portion_g     numeric not null check (portion_g > 0),
  calories      numeric not null check (calories >= 0),
  protein_g     numeric,
  carbs_g       numeric,
  fat_g         numeric,
  fiber_g       numeric,
  source        text not null default 'manual'
                  check (source in ('manual', 'ai_estimated', 'ai_confirmed')),
  ai_confidence numeric,
  image_url     text,
  created_at    timestamptz default now()
);

-- ----------------------------------------------------------------------------
-- workouts
-- ----------------------------------------------------------------------------
create table if not exists workouts (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references profiles (id) on delete cascade,
  logged_at       timestamptz not null default now(),
  activity_type   text not null,
  duration_min    int not null check (duration_min > 0),
  calories_burned numeric not null check (calories_burned >= 0),
  intensity       text check (intensity in ('light', 'moderate', 'vigorous')),
  notes           text,
  source          text default 'manual' check (source in ('manual', 'met_estimated')),
  created_at      timestamptz default now()
);

-- ----------------------------------------------------------------------------
-- weight_logs — one entry per calendar day
-- ----------------------------------------------------------------------------
create table if not exists weight_logs (
  id         uuid primary key default gen_random_uuid(),
  user_id    uuid not null references profiles (id) on delete cascade,
  logged_at  date not null default current_date,
  weight_kg  numeric not null check (weight_kg > 0),
  note       text,
  created_at timestamptz default now(),
  unique (user_id, logged_at)
);

-- ----------------------------------------------------------------------------
-- chat_sessions / chat_messages — persistent AI assistant history
-- ----------------------------------------------------------------------------
create table if not exists chat_sessions (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references profiles (id) on delete cascade,
  title           text not null default 'New conversation',
  last_message_at timestamptz default now(),
  created_at      timestamptz default now()
);

create table if not exists chat_messages (
  id           uuid primary key default gen_random_uuid(),
  session_id   uuid not null references chat_sessions (id) on delete cascade,
  user_id      uuid not null references profiles (id) on delete cascade,
  role         text not null check (role in ('user', 'assistant', 'system')),
  content      text not null,
  -- snapshot of the numbers the assistant was shown, so old answers stay auditable
  context_snapshot jsonb,
  model        text,
  created_at   timestamptz default now()
);

-- ----------------------------------------------------------------------------
-- ai_insights — cached generated summaries (daily / weekly digests)
-- ----------------------------------------------------------------------------
create table if not exists ai_insights (
  id           uuid primary key default gen_random_uuid(),
  user_id      uuid not null references profiles (id) on delete cascade,
  kind         text not null check (kind in ('daily', 'weekly', 'monthly')),
  period_start date not null,
  period_end   date not null,
  headline     text,
  body         text not null,
  highlights   jsonb,
  metrics      jsonb,
  model        text,
  created_at   timestamptz default now(),
  unique (user_id, kind, period_start)
);

-- ----------------------------------------------------------------------------
-- Indexes
-- ----------------------------------------------------------------------------
create index if not exists food_logs_user_logged_idx   on food_logs (user_id, logged_at desc);
create index if not exists workouts_user_logged_idx    on workouts (user_id, logged_at desc);
create index if not exists weight_logs_user_logged_idx on weight_logs (user_id, logged_at desc);
create index if not exists goals_user_effective_idx    on goals (user_id, effective_from desc);
create index if not exists chat_messages_session_idx   on chat_messages (session_id, created_at);
create index if not exists chat_sessions_user_idx      on chat_sessions (user_id, last_message_at desc);
create index if not exists ai_insights_user_kind_idx   on ai_insights (user_id, kind, period_start desc);

-- ----------------------------------------------------------------------------
-- Row Level Security — every user-scoped table is locked to auth.uid()
-- ----------------------------------------------------------------------------
alter table profiles      enable row level security;
alter table goals         enable row level security;
alter table food_logs     enable row level security;
alter table workouts      enable row level security;
alter table weight_logs   enable row level security;
alter table chat_sessions enable row level security;
alter table chat_messages enable row level security;
alter table ai_insights   enable row level security;
alter table food_items    enable row level security;

-- profiles keys on `id` rather than `user_id`
drop policy if exists "profiles: own row" on profiles;
create policy "profiles: own row" on profiles
  for all using (auth.uid() = id) with check (auth.uid() = id);

do $$
declare t text;
begin
  foreach t in array array['goals', 'food_logs', 'workouts', 'weight_logs',
                           'chat_sessions', 'chat_messages', 'ai_insights']
  loop
    execute format('drop policy if exists %I on %I', t || ': own rows only', t);
    execute format(
      'create policy %I on %I for all using (auth.uid() = user_id) with check (auth.uid() = user_id)',
      t || ': own rows only', t
    );
  end loop;
end $$;

-- food_items is a shared nutrition cache: any signed-in user may read it and
-- contribute rows, but nobody may mutate or delete existing rows.
drop policy if exists "food_items: read for authenticated" on food_items;
create policy "food_items: read for authenticated" on food_items
  for select to authenticated using (true);

drop policy if exists "food_items: insert for authenticated" on food_items;
create policy "food_items: insert for authenticated" on food_items
  for insert to authenticated with check (true);

-- ----------------------------------------------------------------------------
-- Auto-create a profile row when a user signs up
-- ----------------------------------------------------------------------------
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, full_name)
  values (new.id, coalesce(new.raw_user_meta_data ->> 'full_name', split_part(new.email, '@', 1)))
  on conflict (id) do nothing;
  return new;
end $$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- keep profiles.updated_at fresh
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end $$;

drop trigger if exists profiles_touch_updated_at on profiles;
create trigger profiles_touch_updated_at
  before update on profiles
  for each row execute function public.touch_updated_at();

-- ----------------------------------------------------------------------------
-- Storage bucket for food photos (private; path convention: <user_id>/<file>)
-- ----------------------------------------------------------------------------
insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
values ('food-photos', 'food-photos', false, 8388608,
        array['image/jpeg', 'image/png', 'image/webp', 'image/heic'])
on conflict (id) do update
  set file_size_limit = excluded.file_size_limit,
      allowed_mime_types = excluded.allowed_mime_types;

drop policy if exists "food-photos: owner read" on storage.objects;
create policy "food-photos: owner read" on storage.objects
  for select using (
    bucket_id = 'food-photos' and (storage.foldername(name))[1] = auth.uid()::text
  );

drop policy if exists "food-photos: owner write" on storage.objects;
create policy "food-photos: owner write" on storage.objects
  for insert with check (
    bucket_id = 'food-photos' and (storage.foldername(name))[1] = auth.uid()::text
  );

drop policy if exists "food-photos: owner delete" on storage.objects;
create policy "food-photos: owner delete" on storage.objects
  for delete using (
    bucket_id = 'food-photos' and (storage.foldername(name))[1] = auth.uid()::text
  );
