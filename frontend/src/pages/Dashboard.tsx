import { Dumbbell, Flame, Plus, Scale, Trash2, Utensils } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';

import { HomeGauge } from '@/components/HomeGauge';
import { InsightCard } from '@/components/InsightCard';
import { LogFoodSheet } from '@/components/logging/LogFoodSheet';
import { LogWeightDialog } from '@/components/logging/LogWeightDialog';
import { LogWorkoutSheet } from '@/components/logging/LogWorkoutSheet';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Fab,
  LinearProgress,
  SectionHeader,
  Skeleton,
  useToast,
} from '@/components/md';
import {
  useDashboard,
  useDeleteFoodLog,
  useDeleteWorkout,
  useMe,
  useRestoreFoodLog,
} from '@/hooks/queries';
import { cn } from '@/lib/cn';
import { durationLabel, greeting, firstName, kcal, MEAL_LABELS, timeOfDay } from '@/lib/format';
import type { ForecastWindow } from '@/lib/types';

export function Dashboard() {
  const [searchParams, setSearchParams] = useSearchParams();
  const me = useMe();
  const toast = useToast();

  const [forecastWindow, setForecastWindow] = useState<ForecastWindow>(7);
  const { data, isLoading, error, refetch } = useDashboard(forecastWindow);

  const [foodOpen, setFoodOpen] = useState(false);
  const [weightOpen, setWeightOpen] = useState(false);
  const [workoutOpen, setWorkoutOpen] = useState(false);

  const deleteFood = useDeleteFoodLog();
  const restoreFood = useRestoreFoodLog();
  const deleteWorkout = useDeleteWorkout();

  // PWA shortcuts land here with ?action=…
  useEffect(() => {
    const action = searchParams.get('action');
    if (!action) return;
    if (action === 'log-food') setFoodOpen(true);
    if (action === 'log-weight') setWeightOpen(true);
    if (action === 'log-workout') setWorkoutOpen(true);
    searchParams.delete('action');
    setSearchParams(searchParams, { replace: true });
  }, [searchParams, setSearchParams]);

  const unit = me.data?.profile.unit_preference ?? 'metric';

  if (isLoading) return <DashboardSkeleton />;

  if (error || !data) {
    return (
      <ErrorState
        title="Could not load today"
        message={error instanceof Error ? error.message : 'Unknown error'}
        onRetry={() => void refetch()}
      />
    );
  }

  const { today, goal } = data;
  const mealGroups = groupByMeal(today.logs);

  return (
    <div className="space-y-5">
      <div>
        <p className="text-label-md text-md-on-surface-variant">
          {greeting()}
          {firstName(me.data?.profile.full_name) ? `, ${firstName(me.data?.profile.full_name)}` : ''}
        </p>
        <h1 className="text-headline-sm font-medium tracking-tight">
          {new Date(`${today.date}T12:00:00`).toLocaleDateString(undefined, {
            weekday: 'long',
            day: 'numeric',
            month: 'long',
          })}
        </h1>
      </div>

      <HomeGauge
        data={data}
        forecastWindow={forecastWindow}
        onForecastWindowChange={setForecastWindow}
        onLogFood={() => setFoodOpen(true)}
        onLogWeight={() => setWeightOpen(true)}
        unit={unit}
      />

      <div className="grid gap-5 lg:grid-cols-2">
        <InsightCard />

        {/* Macro progress against the goal */}
        <Card tone="container">
          <SectionHeader title="Macros today" icon={<Flame size={18} />} />
          <div className="mt-5 space-y-4">
            <MacroBar
              label="Protein"
              value={today.protein_g}
              target={goal.protein_target_g}
              tone="primary"
            />
            <MacroBar label="Carbs" value={today.carbs_g} target={goal.carb_target_g} tone="gauge" />
            <MacroBar label="Fat" value={today.fat_g} target={goal.fat_target_g} tone="warning" />
            <MacroBar
              label="Fibre"
              value={today.fiber_g}
              target={goal.fiber_target_g}
              tone="success"
            />
          </div>
        </Card>
      </div>

      {/* Today's food, grouped by meal */}
      <Card tone="container">
        <SectionHeader
          title="Today's entries"
          subtitle={
            today.entry_count === 0
              ? 'Nothing logged yet'
              : `${today.entry_count} ${today.entry_count === 1 ? 'entry' : 'entries'} · ${kcal(today.calories)} kcal`
          }
          icon={<Utensils size={18} />}
          action={
            <Button variant="tonal" size="sm" icon={<Plus size={16} />} onClick={() => setFoodOpen(true)}>
              Add
            </Button>
          }
        />

        {today.logs.length === 0 ? (
          <EmptyState
            className="py-8"
            icon={<Utensils size={22} />}
            title="Log your first meal"
            description="Search the food database, or photograph your plate and let the AI fill in the macros."
            action={
              <Button icon={<Plus size={18} />} onClick={() => setFoodOpen(true)}>
                Log food
              </Button>
            }
          />
        ) : (
          <div className="mt-5 space-y-5">
            {mealGroups.map(([meal, logs]) => (
              <div key={meal}>
                <div className="flex items-baseline justify-between">
                  <h3 className="text-label-lg font-medium text-md-on-surface-variant">
                    {MEAL_LABELS[meal] ?? 'Other'}
                  </h3>
                  <span className="tabular text-label-md text-md-on-surface-variant">
                    {kcal(logs.reduce((sum, log) => sum + log.calories, 0))} kcal
                  </span>
                </div>
                <ul className="mt-2 divide-y divide-md-outline-variant/40">
                  {logs.map((log) => (
                    <li key={log.id} className="group flex items-center gap-3 py-2.5">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-body-md">{log.food_name}</p>
                        <p className="tabular text-label-sm text-md-on-surface-variant">
                          {Math.round(log.portion_g)} g · {timeOfDay(log.logged_at)}
                          {log.source !== 'manual' && (
                            <span className="ml-2 text-md-primary">AI</span>
                          )}
                        </p>
                      </div>
                      <span className="tabular shrink-0 text-label-lg font-medium">
                        {kcal(log.calories)}
                      </span>
                      <button
                        type="button"
                        aria-label={`Delete ${log.food_name}`}
                        onClick={() => {
                          deleteFood.mutate(log.id, {
                            onSuccess: (result) =>
                              toast.show(`${log.food_name} removed.`, 'success', {
                                label: 'Undo',
                                onClick: () => restoreFood.mutate(result.deleted),
                              }),
                            onError: (caught) =>
                              toast.error(caught instanceof Error ? caught.message : 'Delete failed.'),
                          });
                        }}
                        className="shrink-0 rounded-full p-2 text-md-on-surface-variant/70 transition-all hover:bg-md-error/10 hover:text-md-error focus-visible:text-md-error duration-short"
                      >
                        <Trash2 size={15} />
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Workouts */}
      <Card tone="container">
        <SectionHeader
          title="Movement today"
          subtitle={
            today.workout_sessions === 0
              ? 'No workouts logged'
              : `${today.workout_sessions} ${today.workout_sessions === 1 ? 'session' : 'sessions'} · ${kcal(today.workout_burn)} kcal burned`
          }
          icon={<Dumbbell size={18} />}
          action={
            <Button
              variant="tonal"
              size="sm"
              icon={<Plus size={16} />}
              onClick={() => setWorkoutOpen(true)}
            >
              Add
            </Button>
          }
        />

        {today.workouts.length === 0 ? (
          <p className="mt-4 text-body-sm text-md-on-surface-variant">
            Logging workouts sharpens the forecast — exercise burn is subtracted from your net
            balance for the day.
          </p>
        ) : (
          <ul className="mt-4 divide-y divide-md-outline-variant/40">
            {today.workouts.map((workout) => (
              <li key={workout.id} className="group flex items-center gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-body-md capitalize">
                    {workout.activity_type.replace(/_/g, ' ')}
                  </p>
                  <p className="tabular text-label-sm text-md-on-surface-variant">
                    {durationLabel(workout.duration_min)} · {timeOfDay(workout.logged_at)}
                    {workout.source === 'met_estimated' && (
                      <span className="ml-2">estimated</span>
                    )}
                  </p>
                </div>
                <Badge tone="info">{kcal(workout.calories_burned)} kcal</Badge>
                <button
                  type="button"
                  aria-label={`Delete ${workout.activity_type}`}
                  onClick={() => {
                    deleteWorkout.mutate(workout.id, {
                      onSuccess: () => toast.success('Workout removed.'),
                    });
                  }}
                  className="shrink-0 rounded-full p-2 text-md-on-surface-variant/70 transition-all hover:bg-md-error/10 hover:text-md-error focus-visible:text-md-error duration-short"
                >
                  <Trash2 size={15} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* Floating quick actions — mobile only; the hero buttons cover desktop. */}
      <div className="fixed bottom-24 right-4 z-20 flex flex-col gap-3 lg:hidden">
        <Fab
          tone="surface"
          icon={<Scale size={20} />}
          srLabel="Log weight"
          onClick={() => setWeightOpen(true)}
        />
        <Fab icon={<Plus size={24} />} srLabel="Log food" onClick={() => setFoodOpen(true)} />
      </div>

      <LogFoodSheet open={foodOpen} onClose={() => setFoodOpen(false)} />
      <LogWeightDialog
        open={weightOpen}
        onClose={() => setWeightOpen(false)}
        unit={unit}
        currentWeightKg={data.weight.current_kg}
      />
      <LogWorkoutSheet open={workoutOpen} onClose={() => setWorkoutOpen(false)} />
    </div>
  );
}

function MacroBar({
  label,
  value,
  target,
  tone,
}: {
  label: string;
  value: number;
  target: number | null;
  tone: 'primary' | 'gauge' | 'warning' | 'success';
}) {
  const goal = target ?? 0;
  const fraction = goal > 0 ? value / goal : 0;
  const over = fraction > 1.05;

  return (
    <div>
      <div className="flex items-baseline justify-between text-label-md">
        <span className="font-medium">{label}</span>
        <span className={cn('tabular', over ? 'text-md-warning' : 'text-md-on-surface-variant')}>
          {Math.round(value)} / {goal ? Math.round(goal) : '—'} g
        </span>
      </div>
      <LinearProgress className="mt-1.5" value={fraction} tone={over ? 'warning' : tone} label={label} />
    </div>
  );
}

function groupByMeal<T extends { meal_type: string | null }>(logs: T[]): [string, T[]][] {
  const order = ['breakfast', 'lunch', 'dinner', 'snack', 'other'];
  const groups = new Map<string, T[]>();
  for (const log of logs) {
    const key = log.meal_type ?? 'other';
    groups.set(key, [...(groups.get(key) ?? []), log]);
  }
  return [...groups.entries()].sort(
    ([a], [b]) => order.indexOf(a) - order.indexOf(b),
  );
}

function DashboardSkeleton() {
  return (
    <div className="space-y-5">
      <Skeleton className="h-8 w-56" />
      <Skeleton className="h-[26rem] w-full rounded-2xl" />
      <div className="grid gap-5 lg:grid-cols-2">
        <Skeleton className="h-48 w-full rounded-lg" />
        <Skeleton className="h-48 w-full rounded-lg" />
      </div>
      <Skeleton className="h-64 w-full rounded-lg" />
    </div>
  );
}
