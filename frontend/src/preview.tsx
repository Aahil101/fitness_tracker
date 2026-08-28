/**
 * Visual QA entry point. Mounts the real HomeGauge, gauge states and MD3
 * primitives against fixture data so layouts can be screenshotted at any
 * viewport without a Supabase session.
 *
 * Excluded from the production build (see vite.config.ts). `npm run preview:ui`.
 */

import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

import { AdherenceCard } from './components/AdherenceCard';
import { BodyCompositionCard } from './components/BodyCompositionCard';
import { CalorieGauge } from './components/CalorieGauge';
import { DeficitPanel } from './components/DeficitPanel';
import { HomeBreakdown, HomeGauge } from './components/HomeGauge';
import { WeightTrendCard } from './components/WeightTrendCard';
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
import type { BodyComposition, DashboardResponse } from './lib/types';
import './index.css';

const today = new Date().toISOString().slice(0, 10);

// Body-composition verdicts, so every state can be eyeballed at once.
const BODY_COMP_STATES: BodyComposition[] = [
  {
    verdict: 'mostly_fat',
    headline: 'The loss looks like mostly fat.',
    focus: 'Nothing to change: hold protein, training and pace where they are.',
    caveat:
      'Worked out from your logs, not a body-composition measurement — only a DEXA or similar scan can split fat from muscle. Early drops are largely water and glycogen too.',
    lean_risk_score: 0,
    zone_note:
      'You are in the fat-loss zone: the pace, protein, training and deficit are all where they need to be. Hold these numbers and the weight coming off should be mostly fat.',
    in_fat_loss_zone: true,
    signals: [
      { key: 'rate', label: 'Rate of loss', status: 'good', value: 0.63, detail: '0.63% of bodyweight a week is in the range that favours fat loss.' },
      { key: 'protein', label: 'Protein intake', status: 'good', value: 1.75, detail: '1.8 g/kg is enough to defend muscle in a deficit.' },
      { key: 'training', label: 'Resistance training', status: 'good', value: 2.0, detail: '2.0 strength sessions a week gives muscle a reason to stay.' },
      { key: 'deficit', label: 'Deficit depth', status: 'good', value: 19, detail: 'Eating 19% below maintenance is a sustainable gap.' },
    ],
  },
  {
    verdict: 'high_lean_risk',
    headline: 'This pattern is likely costing you muscle as well as fat.',
    focus: 'Push protein toward 1.6 g per kg of bodyweight — it is the biggest lever you have.',
    caveat:
      'Worked out from your logs, not a body-composition measurement — only a DEXA or similar scan can split fat from muscle. Early drops are largely water and glycogen too.',
    lean_risk_score: 8,
    zone_note:
      'Protein needs to reach about 134 g a day (72 g more than your recent average). Keep intake above roughly 1,888 kcal — a deeper cut than that starts taking muscle with the fat. Aim to lose no more than about 0.63 kg a week.',
    in_fat_loss_zone: false,
    signals: [
      { key: 'rate', label: 'Rate of loss', status: 'risk', value: 1.75, detail: '1.75% a week is faster than fat stores can supply, so muscle is probably making up the difference.' },
      { key: 'protein', label: 'Protein intake', status: 'risk', value: 0.75, detail: '0.8 g/kg is well under the 1.6 g/kg that spares muscle.' },
      { key: 'training', label: 'Resistance training', status: 'risk', value: 0, detail: 'No strength sessions logged. Without a reason to keep muscle, the body sheds it.' },
      { key: 'deficit', label: 'Deficit depth', status: 'risk', value: 46, detail: '46% below maintenance is severe and hard to do without losing muscle.' },
    ],
  },
  {
    verdict: 'insufficient_data',
    headline: 'Not enough history yet to tell fat loss from muscle loss.',
    focus: 'Keep logging meals and weighing in for about two weeks — the trend needs that long before it means anything.',
    caveat:
      'Worked out from your logs, not a body-composition measurement — only a DEXA or similar scan can split fat from muscle. Early drops are largely water and glycogen too.',
    lean_risk_score: 0,
    zone_note:
      'Two resistance sessions a week give your body a reason to keep muscle.',
    in_fat_loss_zone: false,
    signals: [
      { key: 'rate', label: 'Rate of loss', status: 'unknown', value: null, detail: 'Not enough weigh-ins yet to see a trend.' },
      { key: 'protein', label: 'Protein intake', status: 'unknown', value: null, detail: 'Log protein for a few days to judge this.' },
      { key: 'training', label: 'Resistance training', status: 'watch', value: 1.0, detail: '1.0 strength sessions a week; two or more protects lean mass better.' },
      { key: 'deficit', label: 'Deficit depth', status: 'unknown', value: null, detail: 'Log meals for a few days to judge this.' },
    ],
  },
];



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
  body_composition: {
    verdict: 'some_lean_risk',
    headline: 'Mostly fat loss, but some muscle is probably going with it.',
    focus: 'Push protein toward 1.6 g per kg of bodyweight — it is the biggest lever you have.',
    caveat:
      'Worked out from your logs, not a body-composition measurement — only a DEXA or similar scan can split fat from muscle. Early drops are largely water and glycogen too.',
    lean_risk_score: 3,
    zone_note:
      'Protein needs to reach about 134 g a day (72 g more than your recent average). Keep intake above roughly 1,888 kcal — a deeper cut than that starts taking muscle with the fat.',
    in_fat_loss_zone: false,
    signals: [
      { key: 'rate', label: 'Rate of loss', status: 'good', value: 0.62, detail: '0.62% of bodyweight a week is in the range that favours fat loss.' },
      { key: 'protein', label: 'Protein intake', status: 'risk', value: 0.74, detail: '0.7 g/kg is well under the 1.6 g/kg that spares muscle.' },
      { key: 'training', label: 'Resistance training', status: 'watch', value: 1, detail: '1.0 strength sessions a week; two or more protects lean mass better.' },
      { key: 'deficit', label: 'Deficit depth', status: 'good', value: 21, detail: 'Eating 21% below maintenance is a sustainable gap.' },
    ],
  },
  deficit: {
    maintenance_calories: 2400,
    target_calories: 1900,
    exercise_burn: 320,
    eaten_calories: 1480,
    food_deficit: 920,
    exercise_deficit: 320,
    total_deficit: 1240,
    target_deficit: 500,
    progress_fraction: 1.5,
    tracked_days: 6,
    min_days_required: 3,
    has_enough_history: true,
    avg_daily_deficit: 610,
    projections: [
      { days: 7, loss_kg: 0.55, weight_kg: 83.5 },
      { days: 14, loss_kg: 1.11, weight_kg: 82.9 },
      { days: 30, loss_kg: 2.38, weight_kg: 81.7 },
    ],
    note: 'Based on your average 610 kcal deficit across 6 logged days.',
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
    goal_date_earliest: '2026-10-02',
    goal_date_latest: '2026-10-21',
    goal_eta_note:
      'Somewhere between 2 Oct and 21 Oct — your logged calories and your measured weight trend disagree by enough to move the date by 19 days.',
    confidence: 'high',
    notes: ['Time-to-goal uses your measured trend (-0.56 kg/week over 20 days).'],
  },
  weight_trend: {
    trend_kg: 82.4,
    scale_kg: 82.4,
    deviation_kg: 0,
    noise_kg: 0.42,
    weekly_change_kg: -0.57,
    weekly_change_pct: -0.69,
    rate_status: 'on_target',
    rate_label: 'In the sweet spot',
    rate_detail:
      '0.69% of bodyweight a week sits inside the 0.5-1.0% band that tends to preserve muscle while the fat comes off.',
    days_of_data: 21,
    span_days: 20,
    interpolated_days: 0,
    how_calculated:
      'Each weigh-in moves the trend 10% of the way towards itself, so water and food swings average out.',
    series: [],
  },
  expenditure: {
    maintenance_kcal: 2510,
    formula_kcal: 2450,
    measured_kcal: 2510,
    source: 'measured',
    confidence: 'high',
    divergence_kcal: 60,
    days_used: 28,
    days_logged: 25,
    logged_fraction: 0.89,
    trust: 0.96,
    how_calculated:
      'Measured from your data: over 27 days your trend weight moved -2.20 kg while you logged 1,740 kcal a day.',
    notes: [],
    target_calories: 1900,
    stored_target_calories: 1900,
  },
  adherence: {
    days_in_window: 14,
    days_logged: 12,
    days_compliant: 9,
    compliance_rate: 0.75,
    calorie_days: 11,
    protein_days: 9,
    current_streak: 3,
    best_streak: 5,
    status: 'watch',
    headline: 'Protein short on 3 of 12 days',
    detail:
      'Calories were fine on 11 days, but protein reached its floor on only 9. In a deficit that is the difference between losing fat and losing muscle.',
    how_calculated:
      'A day counts when calories land within 190 kcal of your 1,900 kcal target and protein reaches 135 g.',
    weakest_link: 'protein',
    notes: ['2 of the last 14 days have no food logged and are not counted either way.'],
  },
  weight: {
    current_kg: 82.4,
    trend_kg: 82.4,
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

/** Every band the rate classifier can return, so the colour + label pairing
 *  can be checked at a glance rather than reasoned about. */
const RATE_STATES: Partial<DashboardResponse['weight_trend']>[] = [
  {
    rate_status: 'on_target',
    rate_label: 'In the sweet spot',
    weekly_change_kg: -0.57,
    weekly_change_pct: -0.69,
    rate_detail: '0.69% of bodyweight a week sits inside the 0.5-1.0% band.',
  },
  {
    rate_status: 'gentle',
    rate_label: 'Slow and steady',
    weekly_change_kg: -0.25,
    weekly_change_pct: -0.3,
    rate_detail: '0.30% of bodyweight a week — below the usual 0.5-1.0% band.',
  },
  {
    rate_status: 'rapid',
    rate_label: 'Faster than ideal',
    weekly_change_kg: -1.35,
    weekly_change_pct: -1.62,
    rate_detail: '1.62% of bodyweight a week is above 1.0%. More of the loss tends to be muscle.',
  },
  {
    rate_status: 'wrong_way',
    rate_label: 'Trending the wrong way',
    weekly_change_kg: 0.5,
    weekly_change_pct: 0.6,
    rate_detail: 'Your trend is gaining 0.60% of bodyweight a week, away from your goal.',
  },
  {
    rate_status: 'holding',
    rate_label: 'Not moving yet',
    weekly_change_kg: -0.02,
    weekly_change_pct: -0.02,
    rate_detail: 'Your trend is flat, within 0.1% of bodyweight a week.',
  },
  {
    rate_status: 'unknown',
    rate_label: 'Not enough weigh-ins',
    weekly_change_kg: null,
    weekly_change_pct: null,
    rate_detail: 'Weigh in on a few more days and this will show how fast you are moving.',
  },
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
          <h2 className="mb-3 text-title-lg font-medium">HomeBreakdown (intake + projection)</h2>
          <HomeBreakdown
            data={DASHBOARD}
            forecastWindow={7}
            onForecastWindowChange={() => {}}
            onLogFood={() => {}}
            onLogWeight={() => {}}
            unit="metric"
          />
        </section>

        <section>
          <h2 className="mb-3 text-title-lg font-medium">Measured metrics</h2>
          <div className="grid gap-4 lg:grid-cols-2">
            <WeightTrendCard data={DASHBOARD.weight_trend} unit="metric" goalKg={78} />
            <AdherenceCard data={DASHBOARD.adherence} />
            <DeficitPanel data={DASHBOARD.deficit} expenditure={DASHBOARD.expenditure} />
          </div>
        </section>

        <section>
          <h2 className="mb-3 text-title-lg font-medium">Rate bands</h2>
          <div className="grid gap-4 lg:grid-cols-2">
            {RATE_STATES.map((state) => (
              <WeightTrendCard
                key={state.rate_status}
                data={{ ...DASHBOARD.weight_trend, ...state }}
                unit="metric"
              />
            ))}
          </div>
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
          <h2 className="mb-3 text-title-lg font-medium">Fat or muscle?</h2>
          <div className="grid gap-4 lg:grid-cols-3">
            {BODY_COMP_STATES.map((state) => (
              <BodyCompositionCard key={state.verdict} data={state} />
            ))}
          </div>
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

createRoot(document.getElementById('root')!).render(
  // BodyCompositionCard links to the coach, so it needs router context here.
  <MemoryRouter>
    <Preview />
  </MemoryRouter>,
);
