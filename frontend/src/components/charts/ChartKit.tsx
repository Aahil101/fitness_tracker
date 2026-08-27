import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';

/**
 * Shared chart chrome. Colour tokens live in ./chartTheme so this file only
 * exports components and Vite's fast refresh stays reliable.
 */

interface TooltipRow {
  name?: string | number;
  value?: number | string;
  color?: string;
  dataKey?: string | number;
}

/** MD3 surface tooltip; Recharts' default is a white box that breaks dark mode. */
export function ChartTooltip({
  active,
  payload,
  label,
  formatter,
  labelFormatter,
}: {
  active?: boolean;
  payload?: TooltipRow[];
  label?: string | number;
  formatter?: (value: number | string, name: string) => string;
  labelFormatter?: (label: string | number) => string;
}) {
  if (!active || !payload?.length) return null;

  return (
    <div className="rounded-sm border border-md-outline-variant/60 bg-md-surface-container-high px-3 py-2 shadow-e2">
      {label !== undefined && (
        <p className="mb-1 text-label-sm font-medium text-md-on-surface">
          {labelFormatter ? labelFormatter(label) : label}
        </p>
      )}
      <ul className="space-y-0.5">
        {payload
          .filter((row) => row.value !== null && row.value !== undefined)
          .map((row, index) => (
            <li
              key={`${row.dataKey ?? index}`}
              className="flex items-center gap-2 text-label-sm text-md-on-surface-variant"
            >
              <span
                aria-hidden
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ background: row.color }}
              />
              <span className="capitalize">{String(row.name ?? '')}</span>
              <span className="tabular ml-auto font-medium text-md-on-surface">
                {formatter && row.value !== undefined
                  ? formatter(row.value, String(row.name ?? ''))
                  : row.value}
              </span>
            </li>
          ))}
      </ul>
    </div>
  );
}

export function ChartLegend({
  items,
  className,
}: {
  items: { label: string; color: string; dashed?: boolean }[];
  className?: string;
}) {
  return (
    <ul className={cn('flex flex-wrap items-center gap-x-4 gap-y-2', className)}>
      {items.map((item) => (
        <li
          key={item.label}
          className="flex items-center gap-2 text-label-sm text-md-on-surface-variant"
        >
          <span
            aria-hidden
            className={cn('h-0.5 w-5 rounded-full', item.dashed && 'opacity-70')}
            style={
              item.dashed
                ? { backgroundImage: `repeating-linear-gradient(90deg, ${item.color} 0 4px, transparent 4px 8px)` }
                : { background: item.color }
            }
          />
          {item.label}
        </li>
      ))}
    </ul>
  );
}

export function ChartFrame({
  title,
  subtitle,
  action,
  children,
  height = 260,
}: {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  height?: number;
}) {
  return (
    <div>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-title-md font-medium">{title}</h3>
          {subtitle && <p className="mt-0.5 text-label-md text-md-on-surface-variant">{subtitle}</p>}
        </div>
        {action}
      </div>
      <div className="mt-4 w-full" style={{ height }}>
        {children}
      </div>
    </div>
  );
}
