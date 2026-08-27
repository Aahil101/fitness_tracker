import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { kcal, shortDate } from '@/lib/format';
import type { CaloriePoint } from '@/lib/types';
import { ChartLegend, ChartTooltip } from './ChartKit';
import { AXIS_PROPS, CHART_COLORS } from './chartTheme';

/** Calories in vs total out (maintenance + exercise), with the target line. */
export function CaloriesInOutChart({
  series,
  target,
}: {
  series: CaloriePoint[];
  target: number;
}) {
  const data = series.map((point) => ({
    ...point,
    // Hide zero-fill on unlogged days: a flat line at 0 reads as "ate nothing".
    calories_in: point.logged ? point.calories_in : null,
  }));

  return (
    <>
      <ResponsiveContainer width="100%" height="88%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
          <defs>
            <linearGradient id="calories-in-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={CHART_COLORS.in} stopOpacity={0.35} />
              <stop offset="100%" stopColor={CHART_COLORS.in} stopOpacity={0.02} />
            </linearGradient>
            <linearGradient id="calories-out-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={CHART_COLORS.out} stopOpacity={0.22} />
              <stop offset="100%" stopColor={CHART_COLORS.out} stopOpacity={0.02} />
            </linearGradient>
          </defs>

          <CartesianGrid stroke={CHART_COLORS.grid} strokeOpacity={0.4} vertical={false} />
          <XAxis dataKey="date" {...AXIS_PROPS} tickFormatter={shortDate} minTickGap={24} />
          <YAxis {...AXIS_PROPS} width={52} tickFormatter={(value: number) => kcal(value)} />
          <Tooltip
            content={
              <ChartTooltip
                labelFormatter={(label) => shortDate(String(label))}
                formatter={(value) => `${kcal(Number(value))} kcal`}
              />
            }
          />

          <ReferenceLine
            y={target}
            stroke={CHART_COLORS.marker}
            strokeDasharray="6 4"
            label={{
              value: `Target ${kcal(target)}`,
              position: 'insideTopLeft',
              fill: CHART_COLORS.marker,
              fontSize: 11,
            }}
          />

          <Area
            type="monotone"
            dataKey="calories_out"
            name="Burned (total)"
            stroke={CHART_COLORS.out}
            strokeWidth={2}
            fill="url(#calories-out-fill)"
          />
          <Area
            type="monotone"
            dataKey="calories_in"
            name="Eaten"
            stroke={CHART_COLORS.in}
            strokeWidth={2.5}
            fill="url(#calories-in-fill)"
            connectNulls
          />
          <Line type="monotone" dataKey="exercise_burn" name="Exercise" stroke={CHART_COLORS.fat} strokeWidth={1.5} dot={false} />
        </AreaChart>
      </ResponsiveContainer>

      <ChartLegend
        className="mt-2 justify-center"
        items={[
          { label: 'Eaten', color: CHART_COLORS.in },
          { label: 'Burned (maintenance + exercise)', color: CHART_COLORS.out },
          { label: 'Exercise only', color: CHART_COLORS.fat },
          { label: 'Daily target', color: CHART_COLORS.marker, dashed: true },
        ]}
      />
    </>
  );
}

/** Daily net balance: deficit bars below zero, surplus above. */
export function NetBalanceChart({ series }: { series: CaloriePoint[] }) {
  const data = series.filter((point) => point.logged);

  if (data.length === 0) {
    return (
      <p className="grid h-full place-items-center text-body-sm text-md-on-surface-variant">
        No logged days in this range yet.
      </p>
    );
  }

  return (
    <>
      <ResponsiveContainer width="100%" height="88%">
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -14 }}>
          <CartesianGrid stroke={CHART_COLORS.grid} strokeOpacity={0.4} vertical={false} />
          <XAxis dataKey="date" {...AXIS_PROPS} tickFormatter={shortDate} minTickGap={24} />
          <YAxis {...AXIS_PROPS} width={56} tickFormatter={(value: number) => kcal(value)} />
          <Tooltip
            content={
              <ChartTooltip
                labelFormatter={(label) => shortDate(String(label))}
                formatter={(value) => `${kcal(Number(value))} kcal`}
              />
            }
          />
          <ReferenceLine y={0} stroke={CHART_COLORS.axis} strokeOpacity={0.6} />
          <Bar dataKey="net" name="Net balance" radius={[4, 4, 4, 4]} maxBarSize={26}>
            {data.map((point) => (
              <Cell
                key={point.date}
                fill={(point.net ?? 0) <= 0 ? CHART_COLORS.fiber : CHART_COLORS.fat}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      <ChartLegend
        className="mt-2 justify-center"
        items={[
          { label: 'Deficit (losing)', color: CHART_COLORS.fiber },
          { label: 'Surplus (gaining)', color: CHART_COLORS.fat },
        ]}
      />
    </>
  );
}
