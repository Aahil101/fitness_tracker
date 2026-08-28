import { useMemo } from 'react';

import { cn } from '@/lib/cn';
import type { FastingStage } from '@/lib/types';

/**
 * Full-circle fasting progress, with the metabolic stages drawn onto the track.
 *
 * The ring is not just a countdown. The stage boundaries are marked on it as
 * ticks, so the shape of the fast is visible at a glance: how far into fat
 * burning you are, how much further ketosis is. A bare percentage cannot say
 * that, and a bare percentage is what most fasting timers show.
 *
 * Geometry follows CalorieGauge — `pathLength={100}` normalises the dash maths
 * so the sweep is one CSS transition regardless of radius — but a single SVG arc
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
const STAGE_COLOR: Record<string, { stroke: string; fill: string; text: string }> = {
  fed: { stroke: 'stroke-md-on-surface-variant', fill: 'fill-md-on-surface-variant', text: 'text-md-on-surface' },
  glycogen: { stroke: 'stroke-md-info', fill: 'fill-md-info', text: 'text-md-info' },
  fat_burning: { stroke: 'stroke-md-gauge', fill: 'fill-md-gauge', text: 'text-md-on-surface' },
  ketosis: { stroke: 'stroke-md-success', fill: 'fill-md-success', text: 'text-md-success' },
  deep_ketosis: { stroke: 'stroke-md-success', fill: 'fill-md-success', text: 'text-md-success' },
  deep_repair: { stroke: 'stroke-md-warning', fill: 'fill-md-warning', text: 'text-md-warning' },
  extended: { stroke: 'stroke-md-error', fill: 'fill-md-error', text: 'text-md-error' },
};

const NEUTRAL = {
  stroke: 'stroke-md-on-surface-variant',
  fill: 'fill-md-on-surface-variant',
  text: 'text-md-on-surface',
};

export function FastingRing({
  elapsedHours,
  targetHours,
  stages,
  currentStageKey,
  active,
  className,
  children,
}: FastingRingProps) {
  // The ring spans the target, or the elapsed time once it runs past — otherwise
  // an overrun fast would sit pinned at full with no indication of by how much.
  const scaleMax = Math.max(1, targetHours, elapsedHours);
  const fraction = Math.max(0, Math.min(1, elapsedHours / scaleMax));

  const { ticks, targetTick, headPoint } = useMemo(() => {
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

    // Only worth drawing when the fast ran past its target.
    const targetAngle = angleAt(targetHours / scaleMax);
    return {
      ticks: marks,
      targetTick:
        elapsedHours > targetHours
          ? { inner: polar(R - STROKE / 2 - 6, targetAngle), outer: polar(R + STROKE / 2 + 6, targetAngle) }
          : null,
      headPoint: polar(R, angleAt(fraction)),
    };
  }, [stages, scaleMax, elapsedHours, targetHours, fraction]);

  const colour = (currentStageKey && STAGE_COLOR[currentStageKey]) || NEUTRAL;
  const currentStage = stages.find((s) => s.key === currentStageKey);

  const summary = active
    ? `Fasting for ${elapsedHours.toFixed(1)} of ${targetHours} target hours, ${Math.round(
        fraction * 100,
      )}% through. ${currentStage ? `Currently in the ${currentStage.label} stage.` : ''}`
    : `Not fasting. Target ${targetHours} hours.`;

  return (
    <div className={cn('relative mx-auto w-full max-w-[19rem]', className)}>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="w-full overflow-visible" role="img" aria-label={summary}>
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
              'transition-[stroke-dashoffset,stroke] duration-1000 ease-md motion-reduce:transition-none',
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
            className="stroke-md-gauge-marker"
            strokeWidth={4}
            strokeLinecap="round"
          />
        )}

        {/* Live edge */}
        {active && fraction > 0.01 && (
          <g>
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
      </svg>

      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
        {children}
      </div>

      <span className="sr-only">{Math.round(fraction * 100)}% of the ring filled.</span>
    </div>
  );
}
