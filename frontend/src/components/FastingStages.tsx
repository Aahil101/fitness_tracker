import { Check, Circle, Loader } from 'lucide-react';

import { Disclosure } from '@/components/md';
import { cn } from '@/lib/cn';
import { hoursLabel } from '@/lib/format';
import type { FastingPersonalisation, FastingStage } from '@/lib/types';

const STATUS_BAR: Record<FastingStage['status'], string> = {
  done: 'bg-md-success',
  active: 'bg-md-info',
  upcoming: 'bg-md-outline-variant',
};

/**
 * The metabolic timeline, one row per stage with its own progress.
 *
 * A single overall percentage hides the thing people actually fast for. Showing
 * each stage separately makes the shape of the fast legible: which are behind
 * you, which one you are in and how far through it, and how long the next is.
 *
 * Status is carried by an icon and the word itself as well as colour, so the
 * timeline still reads for anyone who cannot distinguish the bars.
 */
export function FastingStages({
  stages,
  elapsedHours,
  personalisation,
  active,
}: {
  stages: FastingStage[];
  elapsedHours: number;
  personalisation: FastingPersonalisation | null;
  active: boolean;
}) {
  return (
    <div>
      <ol className="space-y-4">
        {stages.map((stage) => {
          const Icon = stage.status === 'done' ? Check : stage.status === 'active' ? Loader : Circle;
          const hoursAway = stage.start_hours - elapsedHours;

          return (
            <li key={stage.key}>
              <div className="flex items-start gap-3">
                <span
                  className={cn(
                    'mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-full',
                    stage.status === 'done'
                      ? 'bg-md-success-container text-md-on-success-container'
                      : stage.status === 'active'
                        ? 'bg-md-info-container text-md-on-info-container'
                        : 'bg-md-surface-container-high text-md-on-surface-variant',
                  )}
                >
                  <Icon size={14} aria-hidden />
                </span>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3">
                    <p
                      className={cn(
                        'text-label-lg font-medium',
                        stage.status === 'upcoming' ? 'text-md-on-surface-variant' : 'text-md-on-surface',
                      )}
                    >
                      {stage.label}
                      <span className="sr-only"> — {stage.status}</span>
                    </p>
                    <p className="tabular text-label-sm text-md-on-surface-variant">
                      {stage.end_hours === null
                        ? `${hoursLabel(stage.start_hours)}+`
                        : `${hoursLabel(stage.start_hours)} – ${hoursLabel(stage.end_hours)}`}
                    </p>
                  </div>

                  <div
                    role="progressbar"
                    aria-valuenow={Math.round(stage.progress * 100)}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-label={`${stage.label} progress`}
                    className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-md-surface-container-high"
                  >
                    <div
                      className={cn(
                        'h-full rounded-full transition-[width] duration-700 ease-md motion-reduce:transition-none',
                        STATUS_BAR[stage.status],
                      )}
                      style={{ width: `${Math.max(stage.status === 'upcoming' ? 0 : 3, stage.progress * 100)}%` }}
                    />
                  </div>

                  {/* Only the active stage gets its full explanation. Showing all
                      seven at once is a wall of text nobody reads. */}
                  {stage.status === 'active' ? (
                    <p className="mt-2 font-prose text-label-md leading-relaxed text-md-on-surface-variant">
                      {stage.detail}
                    </p>
                  ) : (
                    <p className="mt-1 font-prose text-label-sm text-md-on-surface-variant/85">
                      {stage.summary}
                      {stage.status === 'upcoming' && active && hoursAway > 0 && (
                        <> · {hoursLabel(hoursAway)} away</>
                      )}
                    </p>
                  )}
                </div>
              </div>
            </li>
          );
        })}
      </ol>

      {personalisation && (
        <>
          {personalisation.notes.map((note) => (
            <p key={note} className="mt-3 font-prose text-label-sm text-md-on-surface-variant/85">
              {note}
            </p>
          ))}
          <Disclosure label="Why are my timings different?">
            {personalisation.how_calculated}
          </Disclosure>
        </>
      )}
    </div>
  );
}
