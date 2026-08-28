import { Activity, Dumbbell, Scale, TrendingDown, TrendingUp } from 'lucide-react';
import { useState } from 'react';

import { CaloriesInOutChart, NetBalanceChart } from '@/components/charts/CalorieChart';
import { ChartFrame } from '@/components/charts/ChartKit';
import { BodyCompositionCard } from '@/components/BodyCompositionCard';
import { MacroSplitChart, MacroTrendChart, WorkoutChart } from '@/components/charts/MacroCharts';
import { WeightChart } from '@/components/charts/WeightChart';
import {
  Badge,
  Card,
  ErrorState,
  SectionHeader,
  Segmented,
  Skeleton,
} from '@/components/md';
import { useAnalytics, useMe } from '@/hooks/queries';
import { durationLabel, kcal, signedKcal, weightDelta } from '@/lib/format';
import type { ForecastWindow } from '@/lib/types';

const RANGE_OPTIONS = [
  { value: 14, label: '14d' },
  { value: 30, label: '30d' },
  { value: 90, label: '90d' },
  { value: 365, label: '1y' },
];

const WINDOW_OPTIONS: { value: ForecastWindow; label: string }[] = [
  { value: 7, label: '7d' },
  { value: 14, label: '14d' },
  { value: 30, label: '30d' },
];

export function Analytics() {
  const me = useMe();
  const [days, setDays] = useState(30);
  const [window, setWindow] = useState<ForecastWindow>(14);
  const { data, isLoading, error, refetch } = useAnalytics(days, window);

  const unit = me.data?.profile.unit_preference ?? 'metric';

  if (isLoading) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-72 w-full rounded-lg" />
        <Skeleton className="h-72 w-full rounded-lg" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <ErrorState
        title="Could not load your trends"
        message={error instanceof Error ? error.message : 'Unknown error'}
        onRetry={() => void refetch()}
      />
    );
  }

  const { forecast, macro_averages: averages, macro_totals: totals } = data;
  const losing = forecast.effective_weekly_change_kg < 0;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-headline-sm font-medium tracking-tight">Trends</h1>
          <p className="text-label-md text-md-on-surface-variant">
            {new Date(`${data.range.from}T12:00:00`).toLocaleDateString(undefined, {
              day: 'numeric',
              month: 'short',
            })}{' '}
            – today · {data.range.days} days
          </p>
        </div>
        <Segmented
          label="Date range"
          options={RANGE_OPTIONS}
          value={days}
          onChange={(value) => setDays(Number(value))}
        />
      </div>

      {/* Headline numbers */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          label="Avg daily intake"
          value={`${kcal(averages.calories)}`}
          unit="kcal"
          hint={`Target ${kcal(data.targets.daily_calorie_target)}`}
        />
        <StatCard
          label="Avg net balance"
          value={signedKcal(forecast.avg_daily_net_kcal)}
          unit="kcal/day"
          hint={`over ${forecast.days_with_data} logged days`}
          tone={forecast.avg_daily_net_kcal <= 0 ? 'success' : 'warning'}
        />
        <StatCard
          label="Projected change"
          value={weightDelta(forecast.projected_weekly_change_kg, unit)}
          unit="per week"
          hint={`${forecast.confidence} confidence`}
          icon={losing ? <TrendingDown size={16} /> : <TrendingUp size={16} />}
        />
        <StatCard
          label="Measured change"
          value={
            forecast.observed_weekly_change_kg !== null
              ? weightDelta(forecast.observed_weekly_change_kg, unit)
              : '—'
          }
          unit="per week"
          hint={
            forecast.observed_span_days
              ? `${forecast.observed_span_days} days of weigh-ins`
              : 'needs 3+ weigh-ins'
          }
          icon={<Scale size={16} />}
        />
      </div>

      {/* Weight + projection */}
      <Card tone="container">
        <ChartFrame
          title="Weight trend"
          subtitle="Solid is what you weighed; dashed is where your calorie balance points."
          height={300}
          action={
            <Segmented
              size="sm"
              label="Forecast window"
              options={WINDOW_OPTIONS}
              value={window}
              onChange={setWindow}
            />
          }
        >
          <WeightChart
            series={data.weight_series}
            projection={data.weight_projection}
            goalKg={me.data?.profile.goal_weight_kg ?? null}
            unit={unit}
          />
        </ChartFrame>

        {forecast.notes.length > 0 && (
          <ul className="mt-3 space-y-1">
            {forecast.notes.map((note) => (
              <li key={note} className="text-label-sm text-md-on-surface-variant">
                {note}
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Calories in vs out */}
      <Card tone="container">
        <ChartFrame
          title="Calories in vs out"
          subtitle="Out includes your maintenance burn plus logged exercise."
          height={300}
        >
          <CaloriesInOutChart series={data.calorie_series} target={data.targets.daily_calorie_target} />
        </ChartFrame>
      </Card>

      {/* Net balance */}
      <Card tone="container">
        <ChartFrame
          title="Daily net balance"
          subtitle="Below the line is a deficit. The average of these bars drives the forecast."
          height={260}
        >
          <NetBalanceChart series={data.calorie_series} />
        </ChartFrame>
      </Card>

      {/* Macros */}
      <div className="grid gap-5 lg:grid-cols-2">
        <Card tone="container">
          <ChartFrame
            title="Where your calories come from"
            subtitle="Share of energy, not grams."
            height={280}
          >
            <MacroSplitChart totals={totals} />
          </ChartFrame>
          <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
            <MiniMacro label="Protein" value={averages.protein_g} target={data.macro_targets.protein_g} />
            <MiniMacro label="Carbs" value={averages.carbs_g} target={data.macro_targets.carbs_g} />
            <MiniMacro label="Fat" value={averages.fat_g} target={data.macro_targets.fat_g} />
            <MiniMacro label="Fibre" value={averages.fiber_g} target={data.macro_targets.fiber_g} />
          </div>
        </Card>

        <Card tone="container">
          <ChartFrame title="Macros per day" subtitle="Stacked grams on logged days." height={280}>
            <MacroTrendChart series={data.macro_series} />
          </ChartFrame>
        </Card>
      </div>

      <BodyCompositionCard data={data.body_composition} />

      {/* Workouts */}
      <Card tone="container">
        <SectionHeader
          title="Training output"
          subtitle="Exercise calories by day"
          icon={<Dumbbell size={18} />}
        />
        <div className="mt-4 h-64">
          <WorkoutChart groups={data.workout_groups.day} />
        </div>

        {data.activity_breakdown.length > 0 && (
          <ul className="mt-5 space-y-2">
            {data.activity_breakdown.slice(0, 6).map((row) => (
              <li
                key={row.activity}
                className="flex items-center justify-between gap-3 rounded-sm bg-md-surface-container-low px-4 py-2.5"
              >
                <span className="inline-flex min-w-0 items-center gap-2">
                  <Activity size={15} className="shrink-0 text-md-on-surface-variant" />
                  <span className="truncate text-body-sm">{row.activity}</span>
                </span>
                <span className="flex shrink-0 items-center gap-3 text-label-sm text-md-on-surface-variant">
                  <span className="tabular">{durationLabel(row.duration_min)}</span>
                  <Badge tone="info">{kcal(row.calories_burned)} kcal</Badge>
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

function StatCard({
  label,
  value,
  unit,
  hint,
  tone = 'neutral',
  icon,
}: {
  label: string;
  value: string;
  unit?: string;
  hint?: string;
  tone?: 'neutral' | 'success' | 'warning';
  icon?: React.ReactNode;
}) {
  const valueTone =
    tone === 'success' ? 'text-md-success' : tone === 'warning' ? 'text-md-warning' : 'text-md-on-surface';

  return (
    <Card tone="container" className="p-4 sm:p-5">
      <p className="flex items-center gap-1.5 text-label-sm text-md-on-surface-variant">
        {icon}
        {label}
      </p>
      <p className={`tabular mt-1 text-title-lg font-medium ${valueTone}`}>
        {value}
        {unit && (
          <span className="ml-1 text-label-md font-normal text-md-on-surface-variant">{unit}</span>
        )}
      </p>
      {hint && <p className="mt-0.5 text-label-sm text-md-on-surface-variant/80">{hint}</p>}
    </Card>
  );
}

function MiniMacro({
  label,
  value,
  target,
}: {
  label: string;
  value: number;
  target: number | null;
}) {
  return (
    <div className="rounded-sm bg-md-surface-container-low px-3 py-2">
      <p className="text-label-sm text-md-on-surface-variant">{label}</p>
      <p className="tabular mt-0.5 text-label-lg font-medium">
        {Math.round(value)}
        {target ? (
          <span className="font-normal text-md-on-surface-variant"> / {Math.round(target)} g</span>
        ) : (
          ' g'
        )}
      </p>
    </div>
  );
}
