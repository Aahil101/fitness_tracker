import { CheckCircle2, CircleSlash, Target, TriangleAlert } from 'lucide-react';

import { Badge, Card, Disclosure, SectionHeader } from '@/components/md';
import { cn } from '@/lib/cn';
import type { Adherence } from '@/lib/types';

const STATUS_TONE = {
  good: 'success',
  watch: 'warning',
  risk: 'error',
  unknown: 'neutral',
} as const;

const STATUS_ICON = {
  good: CheckCircle2,
  watch: TriangleAlert,
  risk: TriangleAlert,
  unknown: CircleSlash,
} as const;

const STATUS_LABEL = {
  good: 'On plan',
  watch: 'Patchy',
  risk: 'Off plan',
  unknown: 'No data',
} as const;

/**
 * How often the plan was actually followed.
 *
 * Without this, a stalled week has no explanation on screen and the obvious
 * conclusion — that the targets are wrong — is usually the wrong one. Counting
 * the days where calories *and* protein both landed in range separates "the plan
 * does not work" from "the plan was not followed", which are opposite problems
 * with opposite fixes.
 */
export function AdherenceCard({ data }: { data: Adherence }) {
  const Icon = STATUS_ICON[data.status];
  const rate = data.compliance_rate;

  return (
    <Card tone="neo">
      <SectionHeader
        title="Sticking to the plan"
        icon={<Target size={18} />}
        action={
          <Badge tone={STATUS_TONE[data.status]} icon={<Icon size={13} />}>
            {STATUS_LABEL[data.status]}
          </Badge>
        }
      />

      <p className="mt-4 text-title-md font-medium text-md-on-surface">{data.headline}</p>

      {rate !== null && (
        <div className="mt-4">
          <div
            role="progressbar"
            aria-valuenow={Math.round(rate * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Days on plan"
            className="h-2.5 w-full overflow-hidden rounded-full bg-md-surface-container-high"
          >
            <div
              className={cn(
                'h-full rounded-full transition-[width] duration-700 motion-reduce:transition-none',
                data.status === 'good'
                  ? 'bg-md-success'
                  : data.status === 'watch'
                    ? 'bg-md-warning'
                    : 'bg-md-error',
              )}
              style={{ width: `${Math.max(2, rate * 100)}%` }}
            />
          </div>
          <p className="mt-1.5 tabular text-label-sm text-md-on-surface-variant">
            {data.days_compliant} of {data.days_logged} logged days on plan
            {data.current_streak > 1 && <> · {data.current_streak} in a row</>}
          </p>
        </div>
      )}

      {/* The split: which of the two non-negotiables is the problem. */}
      {data.days_logged > 0 && (
        <dl className="mt-4 grid grid-cols-2 gap-4">
          <Split label="Calories in range" hit={data.calorie_days} of={data.days_logged} />
          <Split label="Protein met" hit={data.protein_days} of={data.days_logged} />
        </dl>
      )}

      <p className="mt-4 font-prose text-label-md leading-relaxed text-md-on-surface-variant">
        {data.detail}
      </p>

      {data.notes.map((note) => (
        <p key={note} className="mt-2 font-prose text-label-sm text-md-on-surface-variant/85">
          {note}
        </p>
      ))}

      <Disclosure label="What counts as on plan?">{data.how_calculated}</Disclosure>
    </Card>
  );
}

function Split({ label, hit, of }: { label: string; hit: number; of: number }) {
  const short = hit < of;
  return (
    <div>
      <dt className="text-label-sm text-md-on-surface-variant">{label}</dt>
      <dd
        className={cn(
          'tabular text-headline-sm font-medium leading-tight',
          short ? 'text-md-warning' : 'text-md-success',
        )}
      >
        {hit}
        <span className="text-label-md font-normal text-md-on-surface-variant">/{of}</span>
      </dd>
    </div>
  );
}
