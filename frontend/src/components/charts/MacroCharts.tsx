import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { shortDate } from '@/lib/format';
import type { MacroPoint } from '@/lib/types';
import { ChartTooltip } from './ChartKit';
import { AXIS_PROPS, CHART_COLORS } from './chartTheme';

const MACRO_KEYS = [
  { key: 'protein_g' as const, label: 'Protein', color: CHART_COLORS.protein, kcalPerGram: 4 },
  { key: 'carbs_g' as const, label: 'Carbs', color: CHART_COLORS.carbs, kcalPerGram: 4 },
  { key: 'fat_g' as const, label: 'Fat', color: CHART_COLORS.fat, kcalPerGram: 9 },
];

/**
 * Energy split by macro. Shown as a share of *calories* rather than grams —
 * 30 g of fat and 30 g of carbs are not comparable amounts of energy, and a
 * gram-based donut quietly misleads.
 */
export function MacroSplitChart({
  totals,
}: {
  totals: { protein_g: number; carbs_g: number; fat_g: number };
}) {
  const data = MACRO_KEYS.map((macro) => ({
    name: macro.label,
    grams: Math.round(totals[macro.key]),
    value: Math.round(totals[macro.key] * macro.kcalPerGram),
    color: macro.color,
  })).filter((row) => row.value > 0);

  const totalKcal = data.reduce((sum, row) => sum + row.value, 0);

  if (totalKcal === 0) {
    return (
      <p className="grid h-full place-items-center text-body-sm text-md-on-surface-variant">
        Log some food to see the macro split.
      </p>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <PieChart>
        <Pie
          data={data}
          dataKey="value"
          nameKey="name"
          innerRadius="58%"
          outerRadius="82%"
          paddingAngle={3}
          strokeWidth={0}
        >
          {data.map((row) => (
            <Cell key={row.name} fill={row.color} />
          ))}
        </Pie>
        <Tooltip
          content={
            <ChartTooltip
              formatter={(value) =>
                `${Math.round(Number(value))} kcal (${Math.round((Number(value) / totalKcal) * 100)}%)`
              }
            />
          }
        />
        <Legend
          verticalAlign="bottom"
          height={28}
          formatter={(value: string) => {
            const row = data.find((item) => item.name === value);
            return (
              <span style={{ color: CHART_COLORS.axis, fontSize: 12 }}>
                {value} · {row?.grams ?? 0} g
              </span>
            );
          }}
        />
      </PieChart>
    </ResponsiveContainer>
  );
}

/** Stacked daily macro grams — shows consistency, not just averages. */
export function MacroTrendChart({ series }: { series: MacroPoint[] }) {
  const data = series.filter((point) => point.calories > 0);

  if (data.length === 0) {
    return (
      <p className="grid h-full place-items-center text-body-sm text-md-on-surface-variant">
        No logged days in this range yet.
      </p>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
        <CartesianGrid stroke={CHART_COLORS.grid} strokeOpacity={0.4} vertical={false} />
        <XAxis dataKey="date" {...AXIS_PROPS} tickFormatter={shortDate} minTickGap={24} />
        <YAxis {...AXIS_PROPS} width={46} tickFormatter={(value: number) => `${value}g`} />
        <Tooltip
          content={
            <ChartTooltip
              labelFormatter={(label) => shortDate(String(label))}
              formatter={(value) => `${Math.round(Number(value))} g`}
            />
          }
        />
        {MACRO_KEYS.map((macro, index) => (
          <Bar
            key={macro.key}
            dataKey={macro.key}
            name={macro.label}
            stackId="macros"
            fill={macro.color}
            maxBarSize={28}
            radius={index === MACRO_KEYS.length - 1 ? [4, 4, 0, 0] : undefined}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Exercise output per day. */
export function WorkoutChart({
  groups,
}: {
  groups: { bucket: string; calories_burned: number; duration_min: number; sessions: number }[];
}) {
  const data = groups.filter((group) => group.calories_burned > 0);

  if (data.length === 0) {
    return (
      <p className="grid h-full place-items-center text-body-sm text-md-on-surface-variant">
        No workouts logged in this range.
      </p>
    );
  }

  return (
    <ResponsiveContainer width="100%" height="100%">
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
        <CartesianGrid stroke={CHART_COLORS.grid} strokeOpacity={0.4} vertical={false} />
        <XAxis dataKey="bucket" {...AXIS_PROPS} tickFormatter={shortDate} minTickGap={20} />
        <YAxis {...AXIS_PROPS} width={50} />
        <Tooltip
          content={
            <ChartTooltip
              labelFormatter={(label) => shortDate(String(label))}
              formatter={(value, name) =>
                name === 'Minutes' ? `${Math.round(Number(value))} min` : `${Math.round(Number(value))} kcal`
              }
            />
          }
        />
        <Bar
          dataKey="calories_burned"
          name="Burned"
          fill={CHART_COLORS.out}
          radius={[4, 4, 0, 0]}
          maxBarSize={28}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
