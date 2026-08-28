import {
  ArrowDownRight,
  ArrowUpRight,
  CalendarRange,
  Camera,
  Flame,
  Minus,
  Scale,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { useState } from 'react';

import { CalorieGauge } from '@/components/CalorieGauge';
import { Badge, Blobs, Button, Card, Segmented } from '@/components/md';
import { cn } from '@/lib/cn';
import { kcal, signedKcal, weightDelta, weightUnitLabel } from '@/lib/format';
import type { DashboardResponse, ForecastWindow, PeriodKey, UnitPreference } from '@/lib/types';

interface HomeGaugeProps {
  data: DashboardResponse;
  forecastWindow: ForecastWindow;
  onForecastWindowChange: (window: ForecastWindow) => void;
  onLogFood: () => void;
  onLogWeight: () => void;
  unit?: UnitPreference;
}

const PERIOD_OPTIONS: { value: PeriodKey; label: string }[] = [
  { value: 'week', label: 'Week' },
  { value: 'month', label: 'Month' },
  { value: 'year', label: 'Year' },
];

const PERIOD_PHRASE: Record<PeriodKey, string> = {
  week: 'in the last 7 days',
  month: 'in the last 30 days',
  year: 'in the last 365 days',
};

const WINDOW_OPTIONS: { value: ForecastWindow; label: string }[] = [
  { value: 7, label: '7d' },
  { value: 14, label: '14d' },
  { value: 30, label: '30d' },
];

const CONFIDENCE_TONE = {
  high: 'success',
  medium: 'info',
  low: 'warning',
} as const;

/**
 * The front page hero. Four blocks, in the order the spec lays them out:
 *   4.1 the semicircular calorie gauge
 *   4.2 rolling-window stats with a week/month/year toggle
 *   4.3 the live weight projection with a 7/14/30-day averaging window
 *   4.4 the two primary actions
 */
export function HomeGauge({
  data,
  onLogFood,
  onLogWeight,
}: HomeGaugeProps) {
  const { gauge, weight } = data;
  const remaining = gauge.remaining_to_target;

  return (
    <Card
      tone="neo"
      padded={false}
      // Extra-large radius: this is the hero container, not a regular card.
      className="relative overflow-hidden rounded-2xl sm:rounded-3xl"
    >
      <Blobs variant="hero" />

      <div className="relative p-5 sm:p-8">
        {/* -- 4.4 Primary actions, pinned to the top of the hero -------- */}
        {/* Always stacked: this card is half width now, so badges and both
            actions cannot share a row without clipping the second label. */}
        <div className="mb-6 flex flex-col gap-3">
          <div className="flex items-center gap-2">
            <Badge tone={gauge.over_target ? 'warning' : 'success'} icon={<Flame size={13} />}>
              {remaining >= 0 ? `${kcal(remaining)} kcal left` : `${kcal(-remaining)} kcal over`}
            </Badge>
            {gauge.workout_burn > 0 && (
              <Badge tone="info">+{kcal(gauge.workout_burn)} burned</Badge>
            )}
            {data.goal.is_provisional && (
              <Badge tone="warning">Estimated goal — finish setup</Badge>
            )}
          </div>

          {/* Column-first: this card now shares a row, so a horizontal pair
              clipped the second label at narrow widths. */}
          {/* Full width and taller on phones: paired side by side these were
              narrow pills with cramped labels. They only pair up with room. */}
          <div className="flex flex-col gap-2.5 sm:flex-row">
            <Button
              size="lg"
              icon={<Camera size={20} />}
              onClick={onLogFood}
              className="h-14 w-full whitespace-nowrap px-6 sm:h-12 sm:w-auto sm:flex-1"
            >
              Log food
            </Button>
            <Button
              size="lg"
              variant="tonal"
              icon={<Scale size={20} />}
              onClick={onLogWeight}
              className="h-14 w-full whitespace-nowrap px-6 sm:h-12 sm:w-auto sm:flex-1"
            >
              {weight.logged_today ? 'Update weight' : 'Log weight'}
            </Button>
          </div>
        </div>

        {/* -- 4.1 Gauge -------------------------------------------------- */}
        {/* Narrower than before: it sits beside the stats panel now. */}
        <div className="mx-auto max-w-[19rem]">
          <CalorieGauge
            logged={gauge.logged_calories}
            maintenance={gauge.maintenance_calories}
            target={gauge.daily_calorie_target}
          />
        </div>

        {/* Legend: name the three layers so the colours are not a guess. */}
        <div className="mt-4 flex flex-wrap items-center justify-center gap-x-5 gap-y-2 text-label-sm text-md-on-surface-variant">
          <LegendSwatch className="bg-md-gauge" label="Logged" />
          <LegendSwatch className="bg-md-gauge-track" label="Maintenance" />
          <LegendSwatch className="bg-md-gauge-marker" label="Daily goal" isTick />
        </div>

      </div>
    </Card>
  );
}


// ---------------------------------------------------------------------------
// Intake and projection, split out of the gauge card
// ---------------------------------------------------------------------------
/**
 * The numeric breakdown that used to sit inside the gauge card. It moved out
 * when the gauge became a half-width column: two segmented controls and a
 * four-up stat row cannot share that space without wrapping badly, so they run
 * full width beneath instead.
 */
export function HomeBreakdown({
  data,
  forecastWindow,
  onForecastWindowChange,
  unit = 'metric',
}: HomeGaugeProps) {
  const [period, setPeriod] = useState<PeriodKey>('week');
  const { forecast, periods, weight, today } = data;
  const stats = periods[period];
  const projected = forecast.projected_weekly_change_kg;
  const direction = projected <= -0.05 ? 'lose' : projected >= 0.05 ? 'gain' : 'hold';

  return (
    <div className="space-y-4">
    <div className="mt-6 grid gap-4 md:grid-cols-2">
      {/* -- 4.2 Rolling-window stats ------------------------------- */}
      <div className="rounded-lg bg-md-surface/70 p-5 backdrop-blur-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="inline-flex items-center gap-2 text-label-md font-medium text-md-on-surface-variant">
            <CalendarRange size={16} />
            Intake
          </span>
          <Segmented
            size="sm"
            label="Statistics period"
            options={PERIOD_OPTIONS}
            value={period}
            onChange={setPeriod}
          />
        </div>

        <p className="mt-4 text-body-md text-md-on-surface-variant">
          You&apos;ve eaten{' '}
          <span className="tabular text-headline-sm font-medium text-md-on-surface">
            {kcal(stats.total_calories)}
          </span>{' '}
          calories {PERIOD_PHRASE[period]}.
        </p>

        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-label-md">
          <StatPair label="Daily average" value={`${kcal(stats.daily_average)} kcal`} />
          <StatPair label="Days logged" value={`${stats.days_logged} of ${stats.days}`} />
          <StatPair label="Protein" value={`${Math.round(stats.protein_g)} g`} />
          <StatPair
            label="Workouts"
            value={
              stats.workout_sessions > 0
                ? `${stats.workout_sessions} · ${kcal(stats.total_burned)} kcal`
                : 'none logged'
            }
          />
        </dl>
      </div>

      {/* -- 4.3 Live weight trend --------------------------------- */}
      <div className="rounded-lg bg-md-surface/70 p-5 backdrop-blur-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="inline-flex items-center gap-2 text-label-md font-medium text-md-on-surface-variant">
            <Sparkles size={16} />
            Projection
          </span>
          <Segmented
            size="sm"
            label="Averaging window"
            options={WINDOW_OPTIONS}
            value={forecastWindow}
            onChange={onForecastWindowChange}
          />
        </div>

        <p className="mt-4 flex items-start gap-2 text-body-md text-md-on-surface-variant">
          <TrendIcon direction={direction} />
          <span>
            At your current pace you&apos;re projected to{' '}
            {direction === 'hold' ? (
              <span className="font-medium text-md-on-surface">hold steady</span>
            ) : (
              <>
                <span className="font-medium text-md-on-surface">
                  {direction === 'lose' ? 'lose' : 'gain'}
                </span>{' '}
                <span className="tabular text-headline-sm font-medium text-md-on-surface">
                  {weightDelta(Math.abs(projected), unit).replace(/^[+−]/, '')}
                </span>
              </>
            )}{' '}
            over the next 7 days.
          </span>
        </p>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Badge tone={CONFIDENCE_TONE[forecast.confidence]}>
            {forecast.confidence} confidence
          </Badge>
          <span className="tabular text-label-md text-md-on-surface-variant">
            {signedKcal(forecast.avg_daily_net_kcal)} kcal/day net balance
          </span>
        </div>

        {forecast.observed_weekly_change_kg !== null && (
          <p className="mt-2 text-label-md text-md-on-surface-variant">
            Your scale says{' '}
            <span className="tabular font-medium text-md-on-surface">
              {weightDelta(forecast.observed_weekly_change_kg, unit)}
            </span>{' '}
            per week.
          </p>
        )}

        {forecast.days_to_goal !== null && weight.goal_kg !== null && (
          <p className="mt-2 text-label-md text-md-on-surface-variant">
            {forecast.days_to_goal === 0
              ? 'You are at your goal weight.'
              : `~${forecast.days_to_goal} days to ${weight.goal_kg} ${weightUnitLabel(unit)}`}
            {forecast.goal_date && forecast.days_to_goal > 0 && (
              <span className="text-md-on-surface-variant/80">
                {' '}
                (around{' '}
                {new Date(`${forecast.goal_date}T12:00:00`).toLocaleDateString(undefined, {
                  month: 'short',
                  year: 'numeric',
                })}
                )
              </span>
            )}
          </p>
        )}

        {forecast.notes.length > 0 && (
          <p className="mt-3 text-label-sm text-md-on-surface-variant/80">
            {forecast.notes[0]}
          </p>
        )}
      </div>
    </div>

    {/* Today's context strip */}
    <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
      <MiniStat label="Entries today" value={String(today.entry_count)} />
      <MiniStat label="Protein" value={`${Math.round(today.protein_g)} g`} />
      <MiniStat label="Carbs" value={`${Math.round(today.carbs_g)} g`} />
      <MiniStat label="Fat" value={`${Math.round(today.fat_g)} g`} />
    </div>
    </div>
  );
}

function LegendSwatch({
  className,
  label,
  isTick = false,
}: {
  className: string;
  label: string;
  isTick?: boolean;
}) {
  return (
    <span className="inline-flex items-center gap-2">
      <span
        aria-hidden
        className={cn(isTick ? 'h-3.5 w-1 rounded-full' : 'h-2.5 w-6 rounded-full', className)}
      />
      {label}
    </span>
  );
}

function TrendIcon({ direction }: { direction: 'lose' | 'gain' | 'hold' }) {
  const shared = 'mt-1 h-4 w-4 shrink-0';
  if (direction === 'lose') return <TrendingDown className={cn(shared, 'text-md-success')} />;
  if (direction === 'gain') return <TrendingUp className={cn(shared, 'text-md-warning')} />;
  return <Minus className={cn(shared, 'text-md-on-surface-variant')} />;
}

function StatPair({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-label-sm text-md-on-surface-variant">{label}</dt>
      <dd className="tabular mt-0.5 font-medium text-md-on-surface">{value}</dd>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-sm bg-md-surface/60 px-3 py-2.5 backdrop-blur-sm">
      <p className="text-label-sm text-md-on-surface-variant">{label}</p>
      <p className="tabular mt-0.5 text-title-md font-medium text-md-on-surface">{value}</p>
    </div>
  );
}

/** Compact variant used in the diary header — gauge only, no stats blocks. */
export function GaugeSummaryRow({
  logged,
  target,
  maintenance,
}: {
  logged: number;
  target: number;
  maintenance: number;
}) {
  const remaining = target - logged;
  return (
    <div className="flex items-center gap-4">
      <div className="w-32 shrink-0">
        <CalorieGauge logged={logged} maintenance={maintenance} target={target} animate={false} />
      </div>
      <div>
        <p className="tabular text-headline-sm font-medium">{kcal(logged)}</p>
        <p className="text-label-md text-md-on-surface-variant">
          {remaining >= 0 ? (
            <>
              <ArrowDownRight size={13} className="mr-1 inline" />
              {kcal(remaining)} kcal to your goal
            </>
          ) : (
            <>
              <ArrowUpRight size={13} className="mr-1 inline" />
              {kcal(-remaining)} kcal over your goal
            </>
          )}
        </p>
      </div>
    </div>
  );
}
