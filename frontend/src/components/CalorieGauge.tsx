import { useMemo } from 'react';

import { cn } from '@/lib/cn';
import { kcal } from '@/lib/format';

/**
 * Semicircular calorie gauge, hand-rolled in SVG rather than a chart library so
 * the geometry stays crisp at any size and restyling is a token change.
 *
 * Three layers, back to front (colours X, Y, Z from the spec):
 *   1. track   — colour X, neutral, spans 0 -> maintenance_calories (the ceiling)
 *   2. fill    — colour Y, 0 -> calories logged today, grows as food is logged
 *   3. marker  — colour Z, a radial tick at daily_calorie_target
 *
 * ORIENTATION is a single constant: the spec asks for a flat side up, and
 * mirroring to a speedometer-style rainbow is one value change here, with no
 * other geometry edits, because every point is derived from the angle helpers.
 */

type Orientation = 'flat-top' | 'flat-bottom';

/** 'flat-top' = flat edge up, arc bowing downwards (spec default). */
const ORIENTATION: Orientation = 'flat-top';

/** false mirrors the scale so maintenance sits on the left. */
const ZERO_ON_LEFT = true;

// Viewbox geometry. The arc is drawn inside a 2R x R half-square plus padding
// for the stroke width and the goal marker overshoot.
const R = 100;
const STROKE = 18;
const PAD = 16;
const VIEW_W = 2 * R + 2 * PAD;
const VIEW_H = R + 2 * PAD + STROKE / 2;

const CX = VIEW_W / 2;
// With a flat top the circle centre sits near the top edge; with a flat bottom
// it sits near the bottom and the arc bows up.
const CY = ORIENTATION === 'flat-top' ? PAD + STROKE / 2 : VIEW_H - PAD - STROKE / 2;

/** SVG angles: 0 = right, 90 = down, 180 = left, 270 = up. */
const SWEEP_START = ZERO_ON_LEFT ? 180 : 0;
/** Through the bottom for a flat top, through the top for a flat bottom. */
const THROUGH_BOTTOM = ORIENTATION === 'flat-top';

function angleAt(fraction: number): number {
  const clamped = Math.max(0, Math.min(1, fraction));
  const span = THROUGH_BOTTOM
    ? (ZERO_ON_LEFT ? -180 : 180)
    : (ZERO_ON_LEFT ? 180 : -180);
  return SWEEP_START + span * clamped;
}

function polar(radius: number, angleDeg: number) {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: CX + radius * Math.cos(rad), y: CY + radius * Math.sin(rad) };
}

/** Arc path across the whole scale, used by both the track and the fill. */
function arcPath(radius: number): string {
  const from = polar(radius, angleAt(0));
  const to = polar(radius, angleAt(1));
  // largeArcFlag is 0 for a half turn; sweepFlag follows the drawing direction.
  const sweepFlag = THROUGH_BOTTOM === ZERO_ON_LEFT ? 0 : 1;
  return `M ${from.x.toFixed(2)} ${from.y.toFixed(2)} A ${radius} ${radius} 0 0 ${sweepFlag} ${to.x.toFixed(2)} ${to.y.toFixed(2)}`;
}

const TRACK_PATH = arcPath(R);
const MINOR_TICKS = [0.25, 0.5, 0.75];

export interface CalorieGaugeProps {
  /** Sum of today's food logs. */
  logged: number;
  /** TDEE at current weight/activity — the scale's ceiling. */
  maintenance: number;
  /** Deficit-adjusted goal; drawn as the marker. */
  target: number;
  className?: string;
  /** Suppresses the sweep animation on first paint (used in tests/print). */
  animate?: boolean;
}

export function CalorieGauge({
  logged,
  maintenance,
  target,
  className,
  animate = true,
}: CalorieGaugeProps) {
  // The arc spans 0 -> maintenance, per spec. A surplus goal (bulking) would
  // otherwise pin the marker at the end and misreport where the target sits, so
  // the scale extends to whichever is larger.
  const scaleMax = Math.max(1, maintenance, target);
  const safeMaintenance = Math.max(1, maintenance);
  const maintenanceBelowMax = scaleMax > safeMaintenance;

  const {
    fillFraction,
    targetFraction,
    overTarget,
    overMaintenance,
    remaining,
    markerLine,
    maintenanceTick,
    fillEnd,
  } = useMemo(() => {
    const fill = Math.max(0, Math.min(1, logged / scaleMax));
    const goal = Math.max(0, Math.min(1, target / scaleMax));
    const markerAngle = angleAt(goal);
    const inner = polar(R - STROKE / 2 - 5, markerAngle);
    const outer = polar(R + STROKE / 2 + 5, markerAngle);

    // Only drawn when the scale had to stretch past maintenance.
    const maintenanceAngle = angleAt(safeMaintenance / scaleMax);

    return {
      fillFraction: fill,
      targetFraction: goal,
      overTarget: logged > target,
      overMaintenance: logged > safeMaintenance,
      remaining: target - logged,
      markerLine: { inner, outer, angle: markerAngle },
      maintenanceTick: {
        inner: polar(R - STROKE / 2, maintenanceAngle),
        outer: polar(R + STROKE / 2, maintenanceAngle),
      },
      fillEnd: polar(R, angleAt(fill)),
    };
  }, [logged, safeMaintenance, scaleMax, target]);

  /*
   * Colour state: teal under the goal, amber past it, error past maintenance.
   * The error step only applies to a deficit goal — for a surplus (bulking)
   * target, eating above maintenance is the plan working, not a problem.
   */
  const isSurplusGoal = target >= safeMaintenance;
  const state = overMaintenance && !isSurplusGoal ? 'error' : overTarget ? 'warn' : 'ok';

  const fillColor = { error: 'stroke-md-error', warn: 'stroke-md-warning', ok: 'stroke-md-gauge' }[state];
  const knobColor = { error: 'fill-md-error', warn: 'fill-md-warning', ok: 'fill-md-gauge' }[state];
  const numberColor = { error: 'text-md-error', warn: 'text-md-warning', ok: 'text-md-on-surface' }[state];

  const summary = `${kcal(logged)} calories logged of ${kcal(
    safeMaintenance,
  )} maintenance calories. Daily goal ${kcal(target)}. ${
    remaining >= 0 ? `${kcal(remaining)} remaining.` : `${kcal(Math.abs(remaining))} over goal.`
  }`;

  return (
    <div className={cn('flex w-full flex-col', className)}>
      {/* Scale endpoints, rendered as HTML on the flat side so they use real
          text styles and can never clip out of the viewBox. */}
      <div
        className={cn(
          'flex items-baseline justify-between px-1 text-label-sm tabular text-md-on-surface-variant',
          ORIENTATION === 'flat-top' ? 'mb-1 order-first' : 'mt-1 order-last',
        )}
      >
        <span>{ZERO_ON_LEFT ? '0' : kcal(scaleMax)}</span>
        <span className="text-[11px] uppercase tracking-wider text-md-on-surface-variant/70">
          {maintenanceBelowMax ? 'goal scale' : 'maintenance scale'}
        </span>
        <span>{ZERO_ON_LEFT ? kcal(scaleMax) : '0'}</span>
      </div>

      <div className="relative w-full">
        <svg
          viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
          className="w-full overflow-visible"
          role="img"
          aria-label={summary}
        >
          <defs>
            {/* Soft glow so the live edge of the fill reads as "current". */}
            <filter id="gauge-knob-glow" x="-80%" y="-80%" width="260%" height="260%">
              <feGaussianBlur stdDeviation="4" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* Layer 1 — background track: the maintenance ceiling reference. */}
          <path
            d={TRACK_PATH}
            className="stroke-md-gauge-track"
            strokeWidth={STROKE}
            strokeLinecap="round"
            fill="none"
          />

          {/* Quarter ticks: orientation cues without a full axis. */}
          {MINOR_TICKS.map((tick) => {
            const angle = angleAt(tick);
            const from = polar(R - STROKE / 2 + 3, angle);
            const to = polar(R + STROKE / 2 - 3, angle);
            return (
              <line
                key={tick}
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                className="stroke-md-surface/70"
                strokeWidth={2}
                strokeLinecap="round"
              />
            );
          })}

          {/* Layer 2 — filled progress. pathLength normalises the dash maths to 100
              so the sweep is a single CSS transition regardless of radius. */}
          {fillFraction > 0.004 && (
            <path
              d={TRACK_PATH}
              pathLength={100}
              strokeDasharray={100}
              strokeDashoffset={100 - fillFraction * 100}
              className={cn(
                fillColor,
                animate && 'transition-[stroke-dashoffset,stroke] duration-1000 ease-md',
              )}
              strokeWidth={STROKE}
              strokeLinecap="round"
              fill="none"
            />
          )}

          {/* Live edge marker: a glow in the fill colour with a light core, so
              the current position reads against the band it sits on. */}
          {fillFraction > 0.01 && (
            <g className={animate ? 'transition-all duration-1000 ease-md' : undefined}>
              <circle
                cx={fillEnd.x}
                cy={fillEnd.y}
                r={STROKE / 2 - 2}
                className={knobColor}
                filter="url(#gauge-knob-glow)"
              />
              <circle
                cx={fillEnd.x}
                cy={fillEnd.y}
                r={STROKE / 2 - 6}
                className="fill-md-surface-container"
              />
            </g>
          )}

          {/* Maintenance reference, only when the scale runs past it. */}
          {maintenanceBelowMax && (
            <line
              x1={maintenanceTick.inner.x}
              y1={maintenanceTick.inner.y}
              x2={maintenanceTick.outer.x}
              y2={maintenanceTick.outer.y}
              className="stroke-md-on-surface-variant"
              strokeWidth={2.5}
              strokeLinecap="round"
            />
          )}

          {/* Layer 3 — goal marker: a tick, never a fill, so it cannot be mistaken
              for progress. */}
          <line
            x1={markerLine.inner.x}
            y1={markerLine.inner.y}
            x2={markerLine.outer.x}
            y2={markerLine.outer.y}
            className="stroke-md-gauge-marker"
            strokeWidth={5}
            strokeLinecap="round"
          />
          <circle
            cx={markerLine.outer.x}
            cy={markerLine.outer.y}
            r={3.5}
            className="fill-md-gauge-marker"
          />
        </svg>

        {/* Centre label. Positioned in the widest part of the arc's interior —
            for a flat top that is just under the flat edge, since the bowl
            narrows towards the bottom and would clip a wide line of text. */}
        <div
          className={cn(
            'pointer-events-none absolute inset-x-0 mx-auto flex max-w-[62%] flex-col items-center text-center',
            ORIENTATION === 'flat-top' ? 'top-[20%]' : 'bottom-[6%]',
          )}
        >
          <span
            className={cn(
              'tabular text-display-md font-medium leading-none tracking-tight transition-colors duration-medium',
              numberColor,
            )}
          >
            {kcal(logged)}
          </span>
          <span className="mt-1.5 text-label-sm text-md-on-surface-variant">
            kcal logged today
          </span>
        </div>
      </div>

      {/* Spec's subtext, kept outside the arc so it can never overlap the band. */}
      <p className="mt-1 text-center text-label-md text-md-on-surface-variant">
        of <span className="tabular">{kcal(safeMaintenance)}</span> maintenance · goal{' '}
        <span className="tabular font-medium text-md-gauge-marker">{kcal(target)}</span>
        {maintenanceBelowMax && <span className="ml-1">(surplus)</span>}
      </p>

      {/* Percentages of the scale, for readers who want the raw geometry. */}
      <span className="sr-only">
        Fill {(fillFraction * 100).toFixed(0)}% of the arc; goal marker at{' '}
        {(targetFraction * 100).toFixed(0)}%.
      </span>
    </div>
  );
}
