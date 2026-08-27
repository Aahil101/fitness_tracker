import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { fromKg, shortDate, weightUnitLabel } from '@/lib/format';
import type { UnitPreference } from '@/lib/types';
import { ChartLegend, ChartTooltip } from './ChartKit';
import { AXIS_PROPS, CHART_COLORS } from './chartTheme';

interface WeightChartProps {
  series: { date: string; weight_kg: number }[];
  projection: { date: string; projected_kg: number }[];
  goalKg: number | null;
  unit: UnitPreference;
}

/**
 * Measured weight as a solid line, the forecast continued as a dashed line.
 * Both are merged into one dataset keyed by date so the two lines share an axis
 * and the join is continuous rather than two charts stitched together.
 */
export function WeightChart({ series, projection, goalKg, unit }: WeightChartProps) {
  const byDate = new Map<string, { date: string; actual?: number; projected?: number }>();

  for (const point of series) {
    byDate.set(point.date, { date: point.date, actual: fromKg(point.weight_kg, unit) });
  }
  for (const point of projection) {
    const existing = byDate.get(point.date) ?? { date: point.date };
    byDate.set(point.date, { ...existing, projected: fromKg(point.projected_kg, unit) });
  }

  const data = [...byDate.values()].sort((a, b) => a.date.localeCompare(b.date));
  const unitLabel = weightUnitLabel(unit);

  if (data.length === 0) {
    return (
      <p className="grid h-full place-items-center text-body-sm text-md-on-surface-variant">
        Log your weight for a few days and the trend will appear here.
      </p>
    );
  }

  const values = data.flatMap((row) => [row.actual, row.projected].filter((v): v is number => v !== undefined));
  const goal = goalKg !== null ? fromKg(goalKg, unit) : null;
  if (goal !== null) values.push(goal);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = Math.max(0.5, (max - min) * 0.15);

  return (
    <>
      <ResponsiveContainer width="100%" height="88%">
        <LineChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <CartesianGrid stroke={CHART_COLORS.grid} strokeOpacity={0.4} vertical={false} />
          <XAxis dataKey="date" {...AXIS_PROPS} tickFormatter={shortDate} minTickGap={24} />
          <YAxis
            {...AXIS_PROPS}
            domain={[Number((min - pad).toFixed(1)), Number((max + pad).toFixed(1))]}
            tickFormatter={(value: number) => value.toFixed(1)}
            width={52}
          />
          <Tooltip
            content={
              <ChartTooltip
                labelFormatter={(label) => shortDate(String(label))}
                formatter={(value) => `${Number(value).toFixed(1)} ${unitLabel}`}
              />
            }
          />

          {goal !== null && (
            <ReferenceLine
              y={goal}
              stroke={CHART_COLORS.marker}
              strokeDasharray="6 4"
              label={{
                value: `Goal ${goal.toFixed(1)}`,
                position: 'insideTopRight',
                fill: CHART_COLORS.marker,
                fontSize: 11,
              }}
            />
          )}

          <Line
            type="monotone"
            dataKey="actual"
            name="Weight"
            stroke={CHART_COLORS.primary}
            strokeWidth={2.5}
            dot={{ r: 2.5, strokeWidth: 0, fill: CHART_COLORS.primary }}
            activeDot={{ r: 5 }}
            connectNulls
          />
          <Line
            type="monotone"
            dataKey="projected"
            name="Projected"
            stroke={CHART_COLORS.in}
            strokeWidth={2}
            strokeDasharray="6 5"
            dot={false}
            connectNulls
          />
        </LineChart>
      </ResponsiveContainer>

      <ChartLegend
        className="mt-2 justify-center"
        items={[
          { label: 'Measured', color: CHART_COLORS.primary },
          { label: 'Projected from calorie balance', color: CHART_COLORS.in, dashed: true },
          ...(goal !== null ? [{ label: 'Goal weight', color: CHART_COLORS.marker, dashed: true }] : []),
        ]}
      />
    </>
  );
}
