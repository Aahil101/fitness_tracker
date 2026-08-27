/**
 * Visual QA entry point. Mounts the real HomeGauge, gauge states and MD3
 * primitives against fixture data so layouts can be screenshotted at any
 * viewport without a Supabase session.
 *
 * Excluded from the production build (see vite.config.ts). `npm run preview:ui`.
 */

import { createRoot } from 'react-dom/client';

import { CalorieGauge } from './components/CalorieGauge';
import { HomeGauge } from './components/HomeGauge';
import {
  Badge,
  Button,
  Card,
  Chip,
  LinearProgress,
  SectionHeader,
  Segmented,
  TextField,
} from './components/md';
import type { DashboardResponse } from './lib/types';
import './index.css';

const today = new Date().toISOString().slice(0, 10);

const DASHBOARD: DashboardResponse = {
  today: {
    date: today,
    calories: 1420,
    protein_g: 118,
    carbs_g: 146,
    fat_g: 44,
    fiber_g: 21,
    entry_count: 5,
    workout_burn: 380,
    workout_sessions: 1,
    logs: [],
    workouts: [],
  },
  goal: {
    daily_calorie_target: 1900,
    maintenance_calories: 2450,
    protein_target_g: 150,
    carb_target_g: 190,
    fat_target_g: 53,
    fiber_target_g: 27,
    target_weekly_deficit_kcal: -3850,
    effective_from: today,
    is_provisional: false,
  },
  gauge: {
    logged_calories: 1420,
    maintenance_calories: 2450,
    daily_calorie_target: 1900,
    remaining_to_target: 480,
    remaining_to_maintenance: 1030,
    over_target: false,
    over_maintenance: false,
    fraction_of_maintenance: 0.5796,
    target_fraction_of_maintenance: 0.7755,
    workout_burn: 380,
  },
  periods: {
    week: {
      days: 7, from: today, to: today, total_calories: 12180, daily_average: 1740,
      days_logged: 7, total_burned: 1420, workout_sessions: 4, workout_minutes: 165,
      protein_g: 903, carbs_g: 1120, fat_g: 322, fiber_g: 148,
    },
    month: {
      days: 30, from: today, to: today, total_calories: 49600, daily_average: 1772,
      days_logged: 28, total_burned: 6100, workout_sessions: 16, workout_minutes: 690,
      protein_g: 3800, carbs_g: 4600, fat_g: 1290, fiber_g: 590,
    },
    year: {
      days: 365, from: today, to: today, total_calories: 214000, daily_average: 1810,
      days_logged: 118, total_burned: 24500, workout_sessions: 64, workout_minutes: 2800,
      protein_g: 15200, carbs_g: 19800, fat_g: 5400, fiber_g: 2400,
    },
  },
  forecast: {
    window_days: 7,
    days_with_data: 7,
    avg_daily_intake: 1740,
    avg_daily_exercise_burn: 203,
    avg_daily_net_kcal: -913,
    projected_weekly_change_kg: -0.83,
    projected_monthly_change_kg: -3.56,
    observed_weekly_change_kg: -0.56,
    effective_weekly_change_kg: -0.56,
    projected_weight_7d_kg: 81.6,
    projected_weight_30d_kg: 78.9,
    days_to_goal: 55,
    goal_date: '2026-10-21',
    confidence: 'high',
    notes: ['Time-to-goal uses your measured trend (-0.56 kg/week over 20 days).'],
  },
  weight: {
    current_kg: 82.4,
    goal_kg: 78,
    starting_kg: 84,
    logged_today: true,
    latest_logged_at: today,
    total_change_kg: -1.6,
  },
  profile: {
    full_name: 'Aahil Shaik',
    unit_preference: 'metric',
    timezone: 'Asia/Kolkata',
    needs_onboarding: false,
  },
};

const GAUGE_STATES = [
  { label: 'Empty — nothing logged', logged: 0, target: 1900, maintenance: 2450 },
  { label: 'Under goal', logged: 1420, target: 1900, maintenance: 2450 },
  { label: 'At goal', logged: 1900, target: 1900, maintenance: 2450 },
  { label: 'Over goal (amber)', logged: 2150, target: 1900, maintenance: 2450 },
  { label: 'Over maintenance (error)', logged: 2800, target: 1900, maintenance: 2450 },
  { label: 'Surplus goal (bulking)', logged: 2600, target: 2900, maintenance: 2450 },
];

export function Preview() {
  return (
    <div className="min-h-dvh bg-md-surface px-4 py-8 sm:px-6">
      <div className="mx-auto max-w-6xl space-y-8">
        <header>
          <p className="text-label-md text-md-on-surface-variant">Visual QA harness</p>
          <h1 className="text-headline-sm font-medium tracking-tight">
            Pulse — Material You components
          </h1>
        </header>

        <section>
          <h2 className="mb-3 text-title-lg font-medium">HomeGauge (front page hero)</h2>
          <HomeGauge
            data={DASHBOARD}
            forecastWindow={7}
            onForecastWindowChange={() => {}}
            onLogFood={() => {}}
            onLogWeight={() => {}}
            unit="metric"
          />
        </section>

        <section>
          <h2 className="mb-3 text-title-lg font-medium">Gauge colour states</h2>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {GAUGE_STATES.map((state) => (
              <Card key={state.label} tone="container">
                <p className="mb-2 text-label-md text-md-on-surface-variant">{state.label}</p>
                <CalorieGauge
                  logged={state.logged}
                  target={state.target}
                  maintenance={state.maintenance}
                  animate={false}
                />
              </Card>
            ))}
          </div>
        </section>

        <section>
          <h2 className="mb-3 text-title-lg font-medium">Primitives</h2>
          <Card tone="container" className="space-y-6">
            <div className="flex flex-wrap items-center gap-3">
              <Button>Filled</Button>
              <Button variant="tonal">Tonal</Button>
              <Button variant="outlined">Outlined</Button>
              <Button variant="text">Text</Button>
              <Button variant="elevated">Elevated</Button>
              <Button variant="danger">Danger</Button>
              <Button loading>Loading</Button>
              <Button disabled>Disabled</Button>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button size="sm">Small</Button>
              <Button size="md">Medium</Button>
              <Button size="lg">Large</Button>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <Chip selected>Selected</Chip>
              <Chip>Unselected</Chip>
              <Badge tone="primary">primary</Badge>
              <Badge tone="success">success</Badge>
              <Badge tone="warning">warning</Badge>
              <Badge tone="error">error</Badge>
              <Badge tone="info">info</Badge>
              <Badge>neutral</Badge>
            </div>

            <Segmented
              label="demo"
              options={[
                { value: 'week', label: 'Week' },
                { value: 'month', label: 'Month' },
                { value: 'year', label: 'Year' },
              ]}
              value="week"
              onChange={() => {}}
            />

            <div className="grid gap-4 sm:grid-cols-2">
              <TextField label="Food name" defaultValue="Grilled chicken thigh" />
              <TextField label="Portion" defaultValue="180" suffix="g" type="number" />
              <TextField label="Email" placeholder="you@example.com" hint="We never share it." />
              <TextField label="Weight" defaultValue="9999" error="That weight looks off." />
            </div>

            <div className="space-y-3">
              <LinearProgress value={0.4} label="protein" />
              <LinearProgress value={0.85} tone="gauge" label="carbs" />
              <LinearProgress value={1.2} tone="warning" label="fat" />
            </div>

            <SectionHeader
              title="Section header"
              subtitle="With a subtitle and a trailing action"
              action={<Button size="sm" variant="tonal">Action</Button>}
            />
          </Card>
        </section>

        <section>
          <h2 className="mb-3 text-title-lg font-medium">Surface tones</h2>
          <div className="grid gap-4 sm:grid-cols-3">
            {(['container', 'low', 'high', 'primary', 'tertiary', 'outlined'] as const).map(
              (tone) => (
                <Card key={tone} tone={tone} interactive>
                  <p className="text-label-lg font-medium capitalize">{tone}</p>
                  <p className="mt-1 text-body-sm opacity-80">Interactive card, hover to lift</p>
                </Card>
              ),
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(<Preview />);
