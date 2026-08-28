import { Flame, TrendingDown } from 'lucide-react';

import { Card } from '@/components/md';
import { cn } from '@/lib/cn';
import { kcal } from '@/lib/format';
import type { DeficitSummary } from '@/lib/types';

/**
 * Today's energy accounting, in the order it makes sense to read:
 * what maintaining costs, what you may eat, what you burned, and the deficit
 * those three produce. Then what that deficit is worth in kilograms.
 *
 * Colour carries the meaning: neutral for maintenance because it is a fact
 * rather than a goal, green for the intake allowance, red for exercise burn,
 * blue for the resulting deficit.
 */
export function DeficitPanel({ data }: { data: DeficitSummary }) {
  const { progress_fraction: progress } = data;
  const beyondPlan = progress > 1;

  return (
    <Card tone="container" className="flex h-full flex-col rounded-2xl sm:rounded-3xl">
      <div className="flex items-center gap-2">
        <span className="grid h-9 w-9 place-items-center rounded-full bg-md-info-container text-md-on-info-container">
          <Flame size={17} />
        </span>
        <div>
          <h2 className="text-title-md font-medium">Today&apos;s energy</h2>
          <p className="font-prose text-label-sm text-md-on-surface-variant">
            Where your deficit comes from
          </p>
        </div>
      </div>

      <dl className="mt-5 grid grid-cols-2 gap-x-4 gap-y-4">
        <Stat
          label="To maintain"
          value={data.maintenance_calories}
          hint="Burned just existing"
          className="text-md-on-surface"
        />
        <Stat
          label="To eat"
          value={data.target_calories}
          hint={`${kcal(data.eaten_calories)} eaten so far`}
          className="text-md-success"
        />
        <Stat
          label="Burned"
          value={data.exercise_burn}
          hint="Exercise today"
          className="text-md-error"
        />
        <Stat
          label="Deficit"
          value={data.total_deficit}
          hint={`${kcal(data.food_deficit)} food + ${kcal(data.exercise_deficit)} exercise`}
          className="text-md-info"
        />
      </dl>

      {/* Progress towards the deficit the plan asks for. */}
      <div className="mt-5">
        <div className="flex items-baseline justify-between text-label-sm">
          <span className="text-md-on-surface-variant">Deficit progress</span>
          <span className="tabular font-medium text-md-info">
            {Math.round(progress * 100)}%
            {data.target_deficit > 0 && (
              <span className="ml-1 font-normal text-md-on-surface-variant">
                of {kcal(data.target_deficit)}
              </span>
            )}
          </span>
        </div>
        <div
          className="mt-1.5 h-2.5 w-full overflow-hidden rounded-full bg-md-surface-container-highest"
          role="progressbar"
          aria-valuenow={Math.round(progress * 100)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label="Deficit progress"
        >
          <div
            className={cn(
              'h-full rounded-full transition-[width] duration-1000 ease-md',
              beyondPlan ? 'bg-md-success' : 'bg-md-info',
            )}
            style={{ width: `${Math.min(100, progress * 100)}%` }}
          />
        </div>
      </div>

      {/* What the deficit is worth, once there is enough history to mean it. */}
      <div className="mt-5 rounded-md bg-md-surface-container-low p-4">
        <div className="flex items-center gap-2">
          <TrendingDown size={15} className="text-md-info" />
          <p className="text-label-md font-medium">Projected loss</p>
        </div>

        {data.has_enough_history && data.projections.length > 0 ? (
          <ul className="mt-3 grid grid-cols-3 gap-2">
            {data.projections.map((projection) => (
              <li key={projection.days} className="rounded-sm bg-md-surface p-2.5 text-center">
                <p className="text-label-sm text-md-on-surface-variant">
                  {projection.days} days
                </p>
                <p className="tabular mt-0.5 text-title-md font-medium text-md-info">
                  −{projection.loss_kg.toFixed(2)}
                  <span className="ml-0.5 text-label-sm font-normal">kg</span>
                </p>
                {projection.weight_kg !== undefined && (
                  <p className="tabular text-label-sm text-md-on-surface-variant">
                    {projection.weight_kg} kg
                  </p>
                )}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 font-prose text-body-sm text-md-on-surface-variant">{data.note}</p>
        )}

        {data.has_enough_history && data.projections.length > 0 && (
          <p className="mt-2.5 font-prose text-label-sm text-md-on-surface-variant/85">
            {data.note}
          </p>
        )}
      </div>
    </Card>
  );
}

function Stat({
  label,
  value,
  hint,
  className,
}: {
  label: string;
  value: number;
  hint: string;
  className: string;
}) {
  return (
    <div>
      <dt className="text-label-sm text-md-on-surface-variant">{label}</dt>
      <dd className={cn('tabular text-headline-sm font-medium leading-tight', className)}>
        {kcal(value)}
        <span className="ml-1 text-label-md font-normal text-md-on-surface-variant">kcal</span>
      </dd>
      <p className="font-prose text-label-sm text-md-on-surface-variant/85">{hint}</p>
    </div>
  );
}
