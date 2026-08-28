import {
  CalendarDays,
  ChevronLeft,
  ChevronRight,
  Dumbbell,
  Plus,
  Scale,
  Trash2,
  Utensils,
} from 'lucide-react';
import { useMemo, useState } from 'react';

import { LogFoodSheet } from '@/components/logging/LogFoodSheet';
import { LogWeightDialog } from '@/components/logging/LogWeightDialog';
import { LogWorkoutSheet } from '@/components/logging/LogWorkoutSheet';
import {
  Badge,
  Button,
  Card,
  EmptyState,
  IconButton,
  LinearProgress,
  SectionHeader,
  Skeleton,
  useToast,
} from '@/components/md';
import {
  useDeleteFoodLog,
  useRestoreFoodLog,
  useDeleteWorkout,
  useFoodLogs,
  useMe,
  useWeights,
  useWorkouts,
} from '@/hooks/queries';
import { cn } from '@/lib/cn';
import {
  addDays,
  durationLabel,
  kcal,
  localDateKey,
  MEAL_LABELS,
  MEAL_ORDER,
  relativeDay,
  timeOfDay,
  weight as formatWeight,
} from '@/lib/format';
import type { FoodLog } from '@/lib/types';

/** Day-by-day review: what was eaten, what was trained, what the scale said. */
export function Diary() {
  const me = useMe();
  const toast = useToast();
  const today = me.data?.today ?? localDateKey();

  const [day, setDay] = useState(today);
  const [foodOpen, setFoodOpen] = useState(false);
  const [workoutOpen, setWorkoutOpen] = useState(false);
  const [weightOpen, setWeightOpen] = useState(false);

  const foods = useFoodLogs(day, day);
  const workouts = useWorkouts(day, day);
  const weights = useWeights(365);
  const deleteFood = useDeleteFoodLog();
  const restoreFood = useRestoreFoodLog();
  const deleteWorkout = useDeleteWorkout();

  const unit = me.data?.profile.unit_preference ?? 'metric';
  const target = me.data?.goal.daily_calorie_target ?? 0;

  const dayWeight = useMemo(
    () => weights.data?.logs.find((log) => log.logged_at.slice(0, 10) === day) ?? null,
    [weights.data, day],
  );

  const totals = foods.data?.totals ?? { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0, fiber_g: 0 };
  const burn = workouts.data?.totals.calories_burned ?? 0;
  const isFuture = day > today;
  const grouped = useMemo(() => groupByMeal(foods.data?.logs ?? []), [foods.data?.logs]);
  const logs = foods.data?.logs ?? [];

  return (
    <div className="space-y-5">
      {/* Date navigation */}
      <Card tone="container" className="flex items-center justify-between gap-3">
        <IconButton label="Previous day" onClick={() => setDay(addDays(day, -1))}>
          <ChevronLeft size={20} />
        </IconButton>

        <div className="min-w-0 text-center">
          <p className="text-title-md font-medium">{relativeDay(day, today)}</p>
          <p className="text-label-sm text-md-on-surface-variant">
            {new Date(`${day}T12:00:00`).toLocaleDateString(undefined, {
              weekday: 'long',
              day: 'numeric',
              month: 'short',
              year: 'numeric',
            })}
          </p>
        </div>

        <div className="flex items-center gap-1">
          {day !== today && (
            <Button variant="text" size="sm" onClick={() => setDay(today)}>
              Today
            </Button>
          )}
          <IconButton
            label="Next day"
            disabled={isFuture}
            onClick={() => setDay(addDays(day, 1))}
          >
            <ChevronRight size={20} />
          </IconButton>
        </div>
      </Card>

      {/* Day summary */}
      <Card tone="container">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-label-md text-md-on-surface-variant">Eaten</p>
            <p className="tabular text-display-md font-medium leading-none">
              {kcal(totals.calories)}
              <span className="ml-2 text-title-md font-normal text-md-on-surface-variant">
                / {kcal(target)} kcal
              </span>
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {burn > 0 && <Badge tone="info">{kcal(burn)} kcal burned</Badge>}
            <Badge tone={totals.calories > target ? 'warning' : 'success'}>
              {totals.calories > target
                ? `${kcal(totals.calories - target)} over`
                : `${kcal(target - totals.calories)} left`}
            </Badge>
          </div>
        </div>

        <LinearProgress
          className="mt-4"
          value={target ? totals.calories / target : 0}
          tone={totals.calories > target ? 'warning' : 'gauge'}
          label="Calories against target"
        />

        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {(
            [
              ['Protein', totals.protein_g],
              ['Carbs', totals.carbs_g],
              ['Fat', totals.fat_g],
              ['Fibre', totals.fiber_g],
            ] as const
          ).map(([label, value]) => (
            <div key={label} className="rounded-sm bg-md-surface-container-low px-3 py-2.5">
              <p className="text-label-sm text-md-on-surface-variant">{label}</p>
              <p className="tabular mt-0.5 text-title-md font-medium">{Math.round(value)} g</p>
            </div>
          ))}
        </div>
      </Card>

      {/* Weight for the day */}
      <Card tone="container" className="flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-full bg-md-secondary-container text-md-on-secondary-container">
            <Scale size={18} />
          </span>
          <div>
            <p className="text-label-md text-md-on-surface-variant">Weight</p>
            <p className="tabular text-title-lg font-medium">
              {dayWeight ? formatWeight(dayWeight.weight_kg, unit) : 'Not logged'}
            </p>
            {dayWeight?.note && (
              <p className="mt-0.5 text-label-sm text-md-on-surface-variant">{dayWeight.note}</p>
            )}
          </div>
        </div>
        {day === today && (
          <Button variant="tonal" size="sm" onClick={() => setWeightOpen(true)}>
            {dayWeight ? 'Update' : 'Log weight'}
          </Button>
        )}
      </Card>

      {/* Food */}
      <Card tone="container">
        <SectionHeader
          title="Food"
          subtitle={`${logs.length} ${logs.length === 1 ? 'entry' : 'entries'}`}
          icon={<Utensils size={18} />}
          action={
            day === today ? (
              <Button variant="tonal" size="sm" icon={<Plus size={16} />} onClick={() => setFoodOpen(true)}>
                Add
              </Button>
            ) : undefined
          }
        />

        {foods.isLoading ? (
          <div className="mt-4 space-y-2">
            {[0, 1, 2].map((index) => (
              <Skeleton key={index} className="h-12 w-full rounded-sm" />
            ))}
          </div>
        ) : logs.length === 0 ? (
          <EmptyState
            className="py-8"
            icon={<CalendarDays size={22} />}
            title={isFuture ? 'Still to come' : 'Nothing logged this day'}
            description={
              isFuture
                ? 'You can only log food up to today.'
                : 'Past days can be back-filled from the food search.'
            }
          />
        ) : (
          <div className="mt-4 space-y-5">
            {grouped.map(([meal, mealLogs]) => (
              <div key={meal}>
                <div className="flex items-baseline justify-between">
                  <h3 className="text-label-lg font-medium text-md-on-surface-variant">
                    {MEAL_LABELS[meal] ?? 'Other'}
                  </h3>
                  <span className="tabular text-label-md text-md-on-surface-variant">
                    {kcal(mealLogs.reduce((sum, log) => sum + log.calories, 0))} kcal
                  </span>
                </div>
                <ul className="mt-2 divide-y divide-md-outline-variant/40">
                  {mealLogs.map((log) => (
                    <li key={log.id} className="group flex items-center gap-3 py-2.5">
                      {log.image_url && (
                        <img
                          src={log.image_url}
                          alt=""
                          className="h-10 w-10 shrink-0 rounded-sm object-cover"
                        />
                      )}
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-body-md">{log.food_name}</p>
                        <p className="tabular text-label-sm text-md-on-surface-variant">
                          {Math.round(log.portion_g)} g · {timeOfDay(log.logged_at)}
                          {log.protein_g !== null && ` · P ${Math.round(log.protein_g)} g`}
                        </p>
                      </div>
                      <span className="tabular shrink-0 text-label-lg font-medium">
                        {kcal(log.calories)}
                      </span>
                      <button
                        type="button"
                        aria-label={`Delete ${log.food_name}`}
                        onClick={() =>
                          deleteFood.mutate(log.id, {
                            onSuccess: (result) =>
                              toast.show(`${log.food_name} removed.`, 'success', {
                                label: 'Undo',
                                onClick: () => restoreFood.mutate(result.deleted),
                              }),
                          })
                        }
                        className="shrink-0 rounded-full p-2 text-md-on-surface-variant/70 transition-all hover:bg-md-error/10 hover:text-md-error focus-visible:text-md-error"
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
          title="Workouts"
          subtitle={
            workouts.data
              ? `${workouts.data.totals.sessions} sessions · ${durationLabel(workouts.data.totals.duration_min)}`
              : undefined
          }
          icon={<Dumbbell size={18} />}
          action={
            day === today ? (
              <Button
                variant="tonal"
                size="sm"
                icon={<Plus size={16} />}
                onClick={() => setWorkoutOpen(true)}
              >
                Add
              </Button>
            ) : undefined
          }
        />

        {(workouts.data?.workouts.length ?? 0) === 0 ? (
          <p className="mt-4 text-body-sm text-md-on-surface-variant">No workouts on this day.</p>
        ) : (
          <ul className="mt-4 divide-y divide-md-outline-variant/40">
            {workouts.data?.workouts.map((workout) => (
              <li key={workout.id} className="group flex items-center gap-3 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-body-md capitalize">
                    {workout.activity_type.replace(/_/g, ' ')}
                  </p>
                  <p className="tabular text-label-sm text-md-on-surface-variant">
                    {durationLabel(workout.duration_min)} · {workout.intensity ?? 'moderate'} ·{' '}
                    {timeOfDay(workout.logged_at)}
                  </p>
                  {workout.notes && (
                    <p className="mt-0.5 text-label-sm text-md-on-surface-variant/85">
                      {workout.notes}
                    </p>
                  )}
                </div>
                <Badge tone="info">{kcal(workout.calories_burned)} kcal</Badge>
                <button
                  type="button"
                  aria-label={`Delete ${workout.activity_type}`}
                  onClick={() =>
                    deleteWorkout.mutate(workout.id, {
                      onSuccess: () => toast.success('Workout removed.'),
                    })
                  }
                  className={cn(
                    'shrink-0 rounded-full p-2 text-md-on-surface-variant/70 transition-all',
                    'hover:bg-md-error/10 hover:text-md-error focus-visible:text-md-error',
                  )}
                >
                  <Trash2 size={15} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <LogFoodSheet open={foodOpen} onClose={() => setFoodOpen(false)} />
      <LogWorkoutSheet open={workoutOpen} onClose={() => setWorkoutOpen(false)} />
      <LogWeightDialog
        open={weightOpen}
        onClose={() => setWeightOpen(false)}
        unit={unit}
        currentWeightKg={dayWeight?.weight_kg ?? me.data?.current_weight_kg ?? null}
      />
    </div>
  );
}

function groupByMeal(logs: FoodLog[]): [string, FoodLog[]][] {
  const order = [...MEAL_ORDER, 'other'];
  const groups = new Map<string, FoodLog[]>();
  for (const log of logs) {
    const key = log.meal_type ?? 'other';
    groups.set(key, [...(groups.get(key) ?? []), log]);
  }
  return [...groups.entries()].sort(([a], [b]) => order.indexOf(a) - order.indexOf(b));
}
