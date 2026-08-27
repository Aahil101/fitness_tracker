/**
 * Chart tokens. Recharts needs concrete colour strings, so these read the same
 * CSS variables the rest of the UI uses — the charts then follow the MD3 palette
 * and switch with the light/dark toggle without a second source of truth.
 *
 * Kept out of the component file so Vite's fast refresh stays reliable.
 */

export const CHART_COLORS = {
  in: 'rgb(var(--md-chart-in))',
  out: 'rgb(var(--md-chart-out))',
  protein: 'rgb(var(--md-chart-protein))',
  carbs: 'rgb(var(--md-chart-carbs))',
  fat: 'rgb(var(--md-chart-fat))',
  fiber: 'rgb(var(--md-chart-fiber))',
  primary: 'rgb(var(--md-primary))',
  marker: 'rgb(var(--md-gauge-marker))',
  grid: 'rgb(var(--md-outline-variant))',
  axis: 'rgb(var(--md-on-surface-variant))',
  surface: 'rgb(var(--md-surface-container))',
} as const;

export const AXIS_PROPS = {
  stroke: CHART_COLORS.axis,
  tick: { fill: CHART_COLORS.axis, fontSize: 12 },
  tickLine: false,
  axisLine: false,
} as const;
