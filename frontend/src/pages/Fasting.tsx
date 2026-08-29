import { Clock, Flame, History, Play, Square, Timer, Trash2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import { FastingRing } from '@/components/FastingRing';
import { FastingStages } from '@/components/FastingStages';
import {
  Badge,
  Button,
  Card,
  Chip,
  ErrorState,
  SectionHeader,
  Skeleton,
  TextField,
  useToast,
} from '@/components/md';
import {
  useDeleteFast,
  useFasting,
  useFastingHistory,
  useRestoreFast,
  useStartFast,
  useStopFast,
} from '@/hooks/queries';
import { cn } from '@/lib/cn';
import { hmsLabel, hoursLabel } from '@/lib/format';
import type { FastingStageKey } from '@/lib/types';

/** The schedules people actually follow, named the way they name them. */
const PRESETS: { hours: number; label: string; blurb: string }[] = [
  { hours: 12, label: '12:12', blurb: 'Overnight' },
  { hours: 14, label: '14:10', blurb: 'Gentle start' },
  { hours: 16, label: '16:8', blurb: 'Most common' },
  { hours: 18, label: '18:6', blurb: 'Deeper ketosis' },
  { hours: 20, label: '20:4', blurb: 'Warrior' },
  { hours: 23, label: 'OMAD', blurb: 'One meal a day' },
];

const STAGE_TONE: Record<FastingStageKey, 'neutral' | 'info' | 'success' | 'warning' | 'error'> = {
  fed: 'neutral',
  glycogen: 'info',
  fat_burning: 'info',
  ketosis: 'success',
  deep_ketosis: 'success',
  deep_repair: 'warning',
  extended: 'error',
};

export function Fasting() {
  const { data, isLoading, error, refetch } = useFasting();
  const history = useFastingHistory();
  const startFast = useStartFast();
  const stopFast = useStopFast();
  const deleteFast = useDeleteFast();
  const restoreFast = useRestoreFast();
  const toast = useToast();

  const [target, setTarget] = useState(16);
  const [custom, setCustom] = useState('');
  const [showCustom, setShowCustom] = useState(false);

  // Local clock. The server is the source of truth for stage boundaries, but
  // refetching once a second to move a timer would be absurd, so the elapsed
  // figure is extrapolated between refetches from the authoritative start time.
  const [tick, setTick] = useState(() => Date.now());
  useEffect(() => {
    if (!data?.active) return;
    const id = window.setInterval(() => setTick(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [data?.active]);

  const live = useMemo(() => {
    if (!data) return null;
    if (!data.active || !data.started_at) return data;
    const elapsed = Math.max(0, (tick - new Date(data.started_at).getTime()) / 3_600_000);
    return {
      ...data,
      elapsed_hours: elapsed,
      remaining_hours: Math.max(0, data.target_hours - elapsed),
      progress: data.target_hours > 0 ? Math.min(1, elapsed / data.target_hours) : 0,
      target_reached: elapsed >= data.target_hours,
      // Re-derive stage status locally so a boundary crossed between refetches
      // is reflected immediately rather than up to five minutes late.
      stages: data.stages.map((stage) => ({
        ...stage,
        status:
          stage.end_hours !== null && elapsed >= stage.end_hours
            ? ('done' as const)
            : elapsed >= stage.start_hours
              ? ('active' as const)
              : ('upcoming' as const),
        progress:
          stage.end_hours === null
            ? elapsed >= stage.start_hours
              ? 1
              : 0
            : Math.max(
                0,
                Math.min(1, (elapsed - stage.start_hours) / (stage.end_hours - stage.start_hours)),
              ),
      })),
    };
  }, [data, tick]);

  const currentStageKey = live?.stages.find((s) => s.status === 'active')?.key ?? null;
  const currentStage = live?.stages.find((s) => s.key === currentStageKey);

  async function onStart() {
    try {
      await startFast.mutateAsync({ target_hours: target });
      toast.success(`Fast started. Target ${hoursLabel(target)}.`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not start the fast.');
    }
  }

  async function onStop() {
    try {
      const result = await stopFast.mutateAsync({});
      toast.success(
        result.met_target
          ? `${hoursLabel(result.hours)} fast complete — target met.`
          : `Fast ended at ${hoursLabel(result.hours)}.`,
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not stop the fast.');
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-5">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-72 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (error || !live) {
    return (
      <ErrorState
        title="Could not load your fast"
        message={error instanceof Error ? error.message : 'Something went wrong.'}
        onRetry={() => void refetch()}
      />
    );
  }

  return (
    <div className="space-y-5">
      <header>
        <p className="text-label-md text-md-on-surface-variant">Fasting</p>
        <h1 className="text-headline-sm font-medium tracking-tight">
          {live.active ? 'Fast in progress' : 'Start a fast'}
        </h1>
      </header>

      <div className="grid gap-5 lg:grid-cols-[1fr_1.1fr] lg:items-start">
        {/* -- Ring + controls -------------------------------------------- */}
        <Card tone="neo">
          <FastingRing
            elapsedHours={live.elapsed_hours}
            targetHours={live.target_hours}
            stages={live.stages}
            currentStageKey={currentStageKey}
            active={live.active}
          >
            {live.active ? (
              <>
                <span className="tabular text-headline-lg font-medium leading-none tracking-tight">
                  {hmsLabel(live.elapsed_hours)}
                </span>
                <span className="mt-1.5 text-label-sm text-md-on-surface-variant">
                  of {hoursLabel(live.target_hours)}
                </span>
                <span
                  className={cn(
                    'tabular mt-2 text-label-md font-medium',
                    live.target_reached ? 'text-md-success' : 'text-md-on-surface-variant',
                  )}
                >
                  {live.target_reached
                    ? 'Target reached'
                    : `${hoursLabel(live.remaining_hours)} left`}
                </span>
              </>
            ) : (
              <>
                <span className="tabular text-display-md font-medium leading-none tracking-tight text-md-on-surface-variant">
                  {target}h
                </span>
                <span className="mt-1.5 max-w-[9rem] text-label-sm text-md-on-surface-variant">
                  Not fasting yet
                </span>
              </>
            )}
          </FastingRing>

          <p className="mt-3 text-center text-label-sm text-md-on-surface-variant/80">
            Tap or hover a section of the ring for that cycle&apos;s timings.
          </p>

          {live.active && currentStage && (
            <div className="mt-5 text-center">
              <Badge tone={STAGE_TONE[currentStage.key]} icon={<Flame size={13} />}>
                {currentStage.label}
              </Badge>
              {live.hours_to_next_stage !== null && live.next_stage_key && (
                <p className="mt-2 font-prose text-label-md text-md-on-surface-variant">
                  Next stage in{' '}
                  <span className="tabular font-medium text-md-on-surface">
                    {hoursLabel(Math.max(0, live.hours_to_next_stage))}
                  </span>
                </p>
              )}
            </div>
          )}

          {/* Preset picker, only while there is nothing running — changing the
              target mid-fast would silently rewrite what was committed to. */}
          {!live.active && (
            <div className="mt-6">
              <p className="text-label-md font-medium text-md-on-surface">Pick a window</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {PRESETS.map((preset) => (
                  <Chip
                    key={preset.hours}
                    selected={!showCustom && target === preset.hours}
                    onClick={() => {
                      setTarget(preset.hours);
                      setShowCustom(false);
                    }}
                  >
                    {preset.label}
                  </Chip>
                ))}
                <Chip selected={showCustom} onClick={() => setShowCustom(true)}>
                  Custom
                </Chip>
              </div>

              <p className="mt-2 font-prose text-label-sm text-md-on-surface-variant">
                {showCustom
                  ? 'Anything from 1 to 168 hours.'
                  : PRESETS.find((p) => p.hours === target)?.blurb}
              </p>

              {showCustom && (
                <div className="mt-3 max-w-[10rem]">
                  <TextField
                    label="Hours"
                    type="number"
                    inputMode="decimal"
                    value={custom}
                    onChange={(event) => {
                      setCustom(event.target.value);
                      const parsed = Number(event.target.value);
                      if (Number.isFinite(parsed) && parsed > 0 && parsed <= 168) setTarget(parsed);
                    }}
                    placeholder="16"
                  />
                </div>
              )}
            </div>
          )}

          <div className="mt-6">
            {live.active ? (
              <Button
                variant="danger"
                fullWidth
                size="lg"
                icon={<Square size={18} />}
                loading={stopFast.isPending}
                onClick={() => void onStop()}
              >
                End fast
              </Button>
            ) : (
              <Button
                fullWidth
                size="lg"
                icon={<Play size={18} />}
                loading={startFast.isPending}
                onClick={() => void onStart()}
              >
                Start {hoursLabel(target)} fast
              </Button>
            )}
          </div>

          {live.active && live.started_at && (
            <p className="mt-3 text-center text-label-sm text-md-on-surface-variant">
              Started{' '}
              {new Date(live.started_at).toLocaleString(undefined, {
                weekday: 'short',
                hour: 'numeric',
                minute: '2-digit',
              })}
            </p>
          )}

          {live.caution && (
            <p className="mt-4 rounded-sm border border-md-warning/40 bg-md-warning-container/40 p-3 font-prose text-label-sm text-md-on-warning-container">
              {live.caution}
            </p>
          )}
        </Card>

        {/* -- Stage timeline -------------------------------------------- */}
        <Card tone="neo">
          <SectionHeader
            title="What's happening"
            subtitle={
              live.active
                ? 'Timed against your own weight, intake and training'
                : 'How your fast would unfold, based on your own data'
            }
            icon={<Timer size={18} />}
          />
          <div className="mt-5">
            <FastingStages
              stages={live.stages}
              elapsedHours={live.active ? live.elapsed_hours : -1}
              personalisation={live.personalisation}
              active={live.active}
            />
          </div>
        </Card>
      </div>

      {/* -- History ---------------------------------------------------- */}
      <Card tone="neo">
        <SectionHeader
          title="Your fasts"
          subtitle={
            history.data?.summary.sessions
              ? `${history.data.summary.sessions} completed · ${history.data.summary.completed_on_target} hit target`
              : 'Nothing finished yet'
          }
          icon={<History size={18} />}
        />

        {history.data && history.data.summary.sessions > 0 ? (
          <>
            <dl className="mt-5 grid grid-cols-3 gap-4">
              <Stat label="Longest" value={hoursLabel(history.data.summary.longest_hours ?? 0)} />
              <Stat label="Average" value={hoursLabel(history.data.summary.average_hours ?? 0)} />
              <Stat label="Total" value={`${Math.round(history.data.summary.total_hours)}h`} />
            </dl>

            <ul className="mt-5 divide-y divide-md-outline-variant/60">
              {history.data.sessions
                .filter((session) => session.ended_at)
                .slice(0, 8)
                .map((session) => {
                  const hours =
                    (new Date(session.ended_at as string).getTime() -
                      new Date(session.started_at).getTime()) /
                    3_600_000;
                  const met = hours >= session.target_hours;
                  return (
                    <li key={session.id} className="flex items-center justify-between py-2.5">
                      <div>
                        <p className="text-label-lg font-medium">{hoursLabel(hours)}</p>
                        <p className="text-label-sm text-md-on-surface-variant">
                          {new Date(session.started_at).toLocaleDateString(undefined, {
                            day: 'numeric',
                            month: 'short',
                          })}{' '}
                          · target {session.target_hours}h
                        </p>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <Badge tone={met ? 'success' : 'neutral'}>
                          {met ? 'Target met' : 'Short'}
                        </Badge>
                        {/* Always visible, never hover-only: on a touchscreen a
                            hover-revealed control does not exist. */}
                        <button
                          type="button"
                          aria-label={`Delete the ${hoursLabel(hours)} fast from ${new Date(
                            session.started_at,
                          ).toLocaleDateString()}`}
                          onClick={() => {
                            deleteFast.mutate(session.id, {
                              onSuccess: (result) =>
                                toast.show(`${hoursLabel(hours)} fast removed.`, 'success', {
                                  label: 'Undo',
                                  onClick: () => restoreFast.mutate(result.deleted),
                                }),
                              onError: (caught) =>
                                toast.error(
                                  caught instanceof Error ? caught.message : 'Delete failed.',
                                ),
                            });
                          }}
                          className="shrink-0 rounded-full p-2 text-md-on-surface-variant/70 transition-all duration-short hover:bg-md-error/10 hover:text-md-error focus-visible:text-md-error"
                        >
                          <Trash2 size={15} />
                        </button>
                      </div>
                    </li>
                  );
                })}
            </ul>
          </>
        ) : (
          <p className="mt-4 flex items-center gap-2 font-prose text-body-md text-md-on-surface-variant">
            <Clock size={16} />
            Finish a fast and it will show up here.
          </p>
        )}
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-label-sm text-md-on-surface-variant">{label}</dt>
      <dd className="tabular text-title-md font-medium text-md-on-surface">{value}</dd>
    </div>
  );
}
