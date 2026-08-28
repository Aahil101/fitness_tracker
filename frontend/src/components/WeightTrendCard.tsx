import { Scale } from 'lucide-react';

import { Badge, Card, Disclosure, SectionHeader } from '@/components/md';
import { useCountUp } from '@/hooks/useCountUp';
import { cn } from '@/lib/cn';
import { weight, weightDelta } from '@/lib/format';
import type { UnitPreference, WeightTrend } from '@/lib/types';

/** Band colour AND a written label — never colour on its own. */
const RATE_TONE = {
  on_target: 'success',
  gentle: 'info',
  holding: 'neutral',
  rapid: 'warning',
  wrong_way: 'error',
  unknown: 'neutral',
} as const;

/**
 * Trend weight as the headline, with the raw reading kept beside it.
 *
 * The scale is the noisiest input this app has: water and gut contents swing it
 * by more in a day than a good week of dieting moves it. Leading with the trend
 * is what makes the number worth looking at — but hiding the raw reading would
 * be worse than showing noise, because the user has just stood on the scale and
 * will trust their own eyes over ours. So both appear, with the gap between them
 * named and explained rather than left to be discovered as a discrepancy.
 */
export function WeightTrendCard({
  data,
  unit = 'metric',
  goalKg,
}: {
  data: WeightTrend;
  unit?: UnitPreference;
  goalKg?: number | null;
}) {
  const shownTrend = useCountUp(data.trend_kg ?? 0);

  if (data.trend_kg === null) {
    return (
      <Card tone="neo">
        <SectionHeader title="Weight trend" icon={<Scale size={18} />} />
        <p className="mt-4 font-prose text-body-md text-md-on-surface-variant">
          Log a weigh-in and this will start separating real change from the day-to-day swing.
        </p>
      </Card>
    );
  }

  return (
    <Card tone="neo">
      <SectionHeader
        title="Weight trend"
        icon={<Scale size={18} />}
        action={<Badge tone={RATE_TONE[data.rate_status]}>{data.rate_label}</Badge>}
      />

      <div className="mt-5 flex flex-wrap items-end gap-x-6 gap-y-3">
        <div>
          <dt className="text-label-sm text-md-on-surface-variant">Trend weight</dt>
          <dd className="tabular text-display-md font-medium leading-none text-md-on-surface">
            {weight(shownTrend, unit)}
          </dd>
        </div>

        {data.weekly_change_kg !== null && (
          <div>
            <dt className="text-label-sm text-md-on-surface-variant">Per week</dt>
            <dd
              className={cn(
                'tabular text-headline-sm font-medium leading-none',
                data.weekly_change_kg < 0 ? 'text-md-success' : 'text-md-on-surface',
              )}
            >
              {weightDelta(data.weekly_change_kg, unit)}
              {data.weekly_change_pct !== null && (
                <span className="ml-1.5 text-label-md font-normal text-md-on-surface-variant">
                  {Math.abs(data.weekly_change_pct).toFixed(2)}% of bodyweight
                </span>
              )}
            </dd>
          </div>
        )}
      </div>

      {/* The scale reading, and how much this user's own readings scatter. */}
      <p className="mt-3 font-prose text-label-md text-md-on-surface-variant">
        Scale said{' '}
        <span className="tabular font-medium text-md-on-surface">
          {weight(data.scale_kg, unit)}
        </span>
        {data.noise_kg !== null && data.noise_kg > 0.05 && (
          <> — your readings swing about {weight(data.noise_kg, unit)} either side of the trend</>
        )}
        .
      </p>

      {data.weekly_change_pct !== null && (
        <RateBand pct={data.weekly_change_pct} status={data.rate_status} />
      )}

      <p className="mt-3 font-prose text-label-md leading-relaxed text-md-on-surface-variant">
        {data.rate_detail}
      </p>

      {goalKg !== null && goalKg !== undefined && data.trend_kg !== null && (
        <p className="mt-2 font-prose text-label-sm text-md-on-surface-variant/85">
          {weight(Math.abs(data.trend_kg - goalKg), unit)} from your goal of {weight(goalKg, unit)}.
        </p>
      )}

      <Disclosure>{data.how_calculated}</Disclosure>
    </Card>
  );
}

/**
 * Where this week's rate sits against the guidance band.
 *
 * A percentage on its own means nothing to most people — 0.7% of bodyweight is
 * not a figure anyone has intuition for. Drawing the recommended band and
 * marking their position turns it into a judgement they can act on. Labelled as
 * an image with a spoken description, since a marker on a strip is meaningless
 * to a screen reader.
 */
function RateBand({ pct, status }: { pct: number; status: WeightTrend['rate_status'] }) {
  const SCALE_MAX = 1.5; // %/week; beyond this the exact figure stops mattering
  const magnitude = Math.min(Math.abs(pct), SCALE_MAX);
  const position = (magnitude / SCALE_MAX) * 100;
  const bandStart = (0.5 / SCALE_MAX) * 100;
  const bandEnd = (1.0 / SCALE_MAX) * 100;

  return (
    <div className="mt-4">
      <div
        role="img"
        aria-label={`${Math.abs(pct).toFixed(2)}% of bodyweight per week, against a recommended band of 0.5 to 1%. Status: ${status.replace('_', ' ')}.`}
        className="relative h-2.5 w-full overflow-hidden rounded-full bg-md-surface-container-high"
      >
        {/* The recommended band, drawn rather than described. */}
        <div
          className="absolute inset-y-0 bg-md-success/30"
          style={{ left: `${bandStart}%`, width: `${bandEnd - bandStart}%` }}
        />
        {/* Where the user actually is. */}
        <div
          className="absolute inset-y-0 w-1 -translate-x-1/2 rounded-full bg-md-on-surface"
          style={{ left: `${position}%` }}
        />
      </div>
      <div className="mt-1 flex justify-between text-label-sm text-md-on-surface-variant/80">
        <span>0%</span>
        <span>0.5–1% recommended</span>
        <span>{SCALE_MAX}%+</span>
      </div>
    </div>
  );
}
