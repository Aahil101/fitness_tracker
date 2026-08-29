import { useMemo, useState } from 'react';

import { cn } from '@/lib/cn';
import { hmsLabel, hoursLabel } from '@/lib/format';
import type { FastingStage } from '@/lib/types';

/**
 * Full-circle fasting progress, with the metabolic stages drawn onto the track
 * and each one interrogable.
 *
 * The ring is not just a countdown. Stage boundaries are marked as ticks and
 * each stage is its own hit area, so pointing at a segment tells you which cycle
 * it is, when it runs, and how much of it is left. A bare percentage cannot say
 * that, and a bare percentage is what most fasting timers show.
 *
 * Pointing, not hovering. Hover does not exist on a phone, which is where this
 * app is mostly used, so every segment is also tappable and keyboard focusable
 * and carries its own aria-label. Hover is the shortcut, not the mechanism.
 *
 * Geometry follows CalorieGauge — `pathLength={100}` normalises the dash maths so
 * the sweep is one CSS transition regardless of radius — but a single SVG arc
 * cannot close a full circle, so the track is a `<circle>` rotated to start at
 * twelve o'clock rather than three.
 */

const R = 100;
const STROKE = 16;
const PAD = 18;
const SIZE = 2 * (R + PAD);
const CENTRE = SIZE / 2;

/** Angle in degrees for a fraction of the ring, measured from twelve o'clock. */
function angleAt(fraction: number): number {
  return -90 + 360 * Math.max(0, Math.min(1, fraction));
}

function polar(radius: number, angleDeg: number) {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: CENTRE + radius * Math.cos(rad), y: CENTRE + radius * Math.sin(rad) };
}

/** Arc between two fractions of the ring, for a single stage's segment. */
function segmentPath(from: number, to: number, radius: number): string {
  const a1 = angleAt(from);
  const a2 = angleAt(to);
  const p1 = polar(radius, a1);
  const p2 = polar(radius, a2);
  const largeArc = to - from > 0.5 ? 1 : 0;
  return `M ${p1.x.toFixed(2)} ${p1.y.toFixed(2)} A ${radius} ${radius} 0 ${largeArc} 1 ${p2.x.toFixed(2)} ${p2.y.toFixed(2)}`;
}

export interface FastingRingProps {
  /** Hours completed. May exceed the target. */
  elapsedHours: number;
  targetHours: number;
  stages: FastingStage[];
  /** Drives the colour: a fast in ketosis reads differently from one just begun. */
  currentStageKey: string | null;
  active: boolean;
  className?: string;
  children?: React.ReactNode;
}

/** Stage-derived ring colour. Paired with the stage name in the label below. */
const STAGE_COLOR: Record<string, { stroke: string; fill: string }> = {
  fed: { stroke: 'stroke-md-on-surface-variant', fill: 'fill-md-on-surface-variant' },
  glycogen: { stroke: 'stroke-md-info', fill: 'fill-md-info' },
  fat_burning: { stroke: 'stroke-md-gauge', fill: 'fill-md-gauge' },
  ketosis: { stroke: 'stroke-md-success', fill: 'fill-md-success' },
  deep_ketosis: { stroke: 'stroke-md-success', fill: 'fill-md-success' },
  deep_repair: { stroke: 'stroke-md-warning', fill: 'fill-md-warning' },
  extended: { stroke: 'stroke-md-error', fill: 'fill-md-error' },
};

const NEUTRAL = { stroke: 'stroke-md-on-surface-variant', fill: 'fill-md-on-surface-variant' };

export function FastingRing({
  elapsedHours,
  targetHours,
  stages,
  currentStageKey,
  active,
  className,
  children,
}: FastingRingProps) {
  const [pointed, setPointed] = useState<string | null>(null);

  // The ring spans the target, or the elapsed time once it runs past — otherwise
  // an overrun fast would sit pinned at full with no indication of by how much.
  const scaleMax = Math.max(1, targetHours, elapsedHours);
  const fraction = Math.max(0, Math.min(1, elapsedHours / scaleMax));

  const { segments, ticks, targetTick, headPoint } = useMemo(() => {
    // Only stages that begin inside the visible scale get a segment, clipped to
    // the end of it: a 16-hour ring cannot show a boundary at 72 hours.
    const visible = stages
      .filter((stage) => stage.start_hours < scaleMax)
      .map((stage) => {
        const from = stage.start_hours / scaleMax;
        const to = Math.min(1, (stage.end_hours ?? scaleMax) / scaleMax);
        return {
          stage,
          from,
          to,
          path: segmentPath(from, Math.max(from + 0.001, to), R),
        };
      });

    const marks = stages
      // The first stage starts at zero, where a tick is just noise.
      .filter((stage) => stage.start_hours > 0 && stage.start_hours <= scaleMax)
      .map((stage) => {
        const angle = angleAt(stage.start_hours / scaleMax);
        return {
          key: stage.key,
          reached: elapsedHours >= stage.start_hours,
          inner: polar(R - STROKE / 2, angle),
          outer: polar(R + STROKE / 2, angle),
        };
      });

    const targetAngle = angleAt(targetHours / scaleMax);
    return {
      segments: visible,
      ticks: marks,
      targetTick:
        elapsedHours > targetHours
          ? {
              inner: polar(R - STROKE / 2 - 6, targetAngle),
              outer: polar(R + STROKE / 2 + 6, targetAngle),
            }
          : null,
      headPoint: polar(R, angleAt(fraction)),
    };
  }, [stages, scaleMax, elapsedHours, targetHours, fraction]);

  const colour = (currentStageKey && STAGE_COLOR[currentStageKey]) || NEUTRAL;
  const currentStage = stages.find((s) => s.key === currentStageKey);
  const pointedSegment = segments.find((s) => s.stage.key === pointed);

  const summary = active
    ? `Fasting for ${hoursLabel(elapsedHours)} of a ${hoursLabel(targetHours)} target, ${Math.round(
        fraction * 100,
      )}% through.${currentStage ? ` Currently in the ${currentStage.label} cycle.` : ''}`
    : `Not fasting. Target ${hoursLabel(targetHours)}.`;

  return (
    <div className={cn('relative mx-auto w-full max-w-[19rem]', className)}>
      <svg
        viewBox={`0 0 ${SIZE} ${SIZE}`}
        className="w-full overflow-visible"
        role="img"
        aria-label={summary}
      >
        <defs>
          <filter id="fasting-head-glow" x="-80%" y="-80%" width="260%" height="260%">
            <feGaussianBlur stdDeviation="4" result="blur" />
            <feMerge>
              <feMergeNode in="blur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>

        {/* Track */}
        <circle
          cx={CENTRE}
          cy={CENTRE}
          r={R}
          className="stroke-md-gauge-track"
          strokeWidth={STROKE}
          fill="none"
        />

        {/* Stage boundaries, so the fast has visible structure rather than
            being one undifferentiated sweep. */}
        {ticks.map((tick) => (
          <line
            key={tick.key}
            x1={tick.inner.x}
            y1={tick.inner.y}
            x2={tick.outer.x}
            y2={tick.outer.y}
            className={tick.reached ? 'stroke-md-surface/80' : 'stroke-md-on-surface-variant/40'}
            strokeWidth={2}
            strokeLinecap="round"
          />
        ))}

        {/* Elapsed. Rotated so zero is at the top rather than at three o'clock. */}
        {fraction > 0.002 && (
          <circle
            cx={CENTRE}
            cy={CENTRE}
            r={R}
            pathLength={100}
            strokeDasharray={100}
            strokeDashoffset={100 - fraction * 100}
            transform={`rotate(-90 ${CENTRE} ${CENTRE})`}
            className={cn(
              colour.stroke,
              'pointer-events-none transition-[stroke-dashoffset,stroke] duration-1000 ease-md motion-reduce:transition-none',
            )}
            strokeWidth={STROKE}
            strokeLinecap="round"
            fill="none"
          />
        )}

        {/* Where the target sat, once the fast has gone past it. */}
        {targetTick && (
          <line
            x1={targetTick.inner.x}
            y1={targetTick.inner.y}
            x2={targetTick.outer.x}
            y2={targetTick.outer.y}
            className="pointer-events-none stroke-md-gauge-marker"
            strokeWidth={4}
            strokeLinecap="round"
          />
        )}

        {/* Live edge */}
        {active && fraction > 0.01 && (
          <g className="pointer-events-none">
            <circle
              cx={headPoint.x}
              cy={headPoint.y}
              r={STROKE / 2 - 1}
              className={colour.fill}
              filter="url(#fasting-head-glow)"
            />
            <circle
              cx={headPoint.x}
              cy={headPoint.y}
              r={STROKE / 2 - 5}
              className="fill-md-surface-container"
            />
          </g>
        )}

        {/* Highlight for the segment being interrogated. Drawn under the hit
            areas so it cannot swallow the pointer, and in the stage's own colour
            so the link to the panel in the middle is unmistakable. */}
        {pointedSegment && (
          <path
            d={pointedSegment.path}
            fill="none"
            strokeWidth={STROKE + 8}
            strokeLinecap="butt"
            className={cn(
              'pointer-events-none opacity-30',
              STAGE_COLOR[pointedSegment.stage.key]?.stroke ?? NEUTRAL.stroke,
            )}
          />
        )}

        {/* Interrogable stage segments, on top so they receive the pointer.
            Transparent stroke wider than the band gives a forgiving hit area on
            a touchscreen without changing how the ring looks. */}
        {segments.map((segment) => (
          <path
            key={segment.stage.key}
            d={segment.path}
            fill="none"
            strokeWidth={STROKE + 12}
            strokeLinecap="butt"
            tabIndex={0}
            role="button"
            aria-label={segmentLabel(segment.stage, elapsedHours)}
            className={cn(
              'cursor-pointer outline-none',
              pointed === segment.stage.key ? 'stroke-md-on-surface/[0.08]' : 'stroke-transparent',
              'focus-visible:stroke-md-info/25',
            )}
            onMouseEnter={() => setPointed(segment.stage.key)}
            onMouseLeave={() => setPointed((key) => (key === segment.stage.key ? null : key))}
            onFocus={() => setPointed(segment.stage.key)}
            onBlur={() => setPointed((key) => (key === segment.stage.key ? null : key))}
            onClick={() =>
              setPointed((key) => (key === segment.stage.key ? null : segment.stage.key))
            }
          />
        ))}
      </svg>

      {/* Centre content, hidden while a segment is being interrogated so the two
          never overlap. */}
      <div
        className={cn(
          'pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center',
          'transition-opacity duration-short',
          pointedSegment && 'opacity-0',
        )}
      >
        {children}
      </div>

      {/* The answer to "what is this part of the ring?", in the middle where the
          eye already is. Anchoring it to the segment pushed it outside the card
          on the upper arcs; the coloured highlight on the arc carries the link
          instead. */}
      {pointedSegment && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-6">
          <div
            role="status"
            className="w-full max-w-[11.5rem] rounded-sm border border-md-outline-variant bg-md-surface-container-high/95 p-2.5 text-left shadow-e2 backdrop-blur-sm"
          >
            <SegmentTooltip
              stage={pointedSegment.stage}
              elapsedHours={elapsedHours}
              active={active}
            />
          </div>
        </div>
      )}

      <span className="sr-only">{Math.round(fraction * 100)}% of the ring filled.</span>
    </div>
  );
}

/** Spoken description of a segment, for screen readers and the aria-label. */
function segmentLabel(stage: FastingStage, elapsedHours: number): string {
  const window =
    stage.end_hours === null
      ? `from ${hoursLabel(stage.start_hours)} onwards`
      : `${hoursLabel(stage.start_hours)} to ${hoursLabel(stage.end_hours)}`;
  if (stage.status === 'done') return `${stage.label} cycle, ${window}. Complete.`;
  if (stage.status === 'active') {
    const left = stage.end_hours === null ? null : stage.end_hours - elapsedHours;
    return `${stage.label} cycle, ${window}. Currently in it${
      left !== null ? `, ${hoursLabel(left)} of this cycle remaining` : ''
    }.`;
  }
  return `${stage.label} cycle, ${window}. Starts in ${hoursLabel(
    stage.start_hours - elapsedHours,
  )}.`;
}

const STATUS_WORD: Record<FastingStage['status'], string> = {
  done: 'Complete',
  active: 'In progress',
  upcoming: 'Not yet',
};

function SegmentTooltip({
  stage,
  elapsedHours,
  active,
}: {
  stage: FastingStage;
  elapsedHours: number;
  active: boolean;
}) {
  const cycleLeft = stage.end_hours === null ? null : Math.max(0, stage.end_hours - elapsedHours);
  const untilStart = Math.max(0, stage.start_hours - elapsedHours);

  return (
    <>
      <p className="text-label-md font-medium leading-tight text-md-on-surface">{stage.label}</p>
      <p className="tabular mt-0.5 text-label-sm text-md-on-surface-variant">
        {stage.end_hours === null
          ? `${hoursLabel(stage.start_hours)}+`
          : `${hoursLabel(stage.start_hours)} – ${hoursLabel(stage.end_hours)}`}
      </p>

      <dl className="mt-2 space-y-1">
        <Row label="Status" value={STATUS_WORD[stage.status]} />
        {active && <Row label="Fast time" value={hmsLabel(Math.max(0, elapsedHours))} />}
        {stage.status === 'active' && cycleLeft !== null && (
          <Row label="Left in cycle" value={hmsLabel(cycleLeft)} emphasis />
        )}
        {stage.status === 'upcoming' && active && (
          <Row label="Starts in" value={hmsLabel(untilStart)} />
        )}
        {stage.status === 'done' && stage.end_hours !== null && (
          <Row label="Finished at" value={hoursLabel(stage.end_hours)} />
        )}
      </dl>
    </>
  );
}

function Row({ label, value, emphasis }: { label: string; value: string; emphasis?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <dt className="text-label-sm text-md-on-surface-variant">{label}</dt>
      <dd
        className={cn(
          'tabular text-label-sm',
          emphasis ? 'font-medium text-md-info' : 'text-md-on-surface',
        )}
      >
        {value}
      </dd>
    </div>
  );
}
