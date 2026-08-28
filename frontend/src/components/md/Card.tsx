import type { HTMLAttributes, ReactNode } from 'react';

import { cn } from '@/lib/cn';

type Tone =
  | 'container'
  | 'low'
  | 'high'
  | 'primary'
  | 'tertiary'
  | 'outlined'
  | 'glass'
  | 'neo';

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  tone?: Tone;
  /** Adds the hover lift + scale used for tappable cards. */
  interactive?: boolean;
  padded?: boolean;
  children: ReactNode;
}

const TONES: Record<Tone, string> = {
  container: 'bg-md-surface-container text-md-on-surface',
  low: 'bg-md-surface-container-low text-md-on-surface',
  high: 'bg-md-surface-container-high text-md-on-surface',
  primary: 'bg-md-primary-container text-md-on-primary-container',
  tertiary: 'bg-md-tertiary-container text-md-on-tertiary-container',
  outlined: 'border border-md-outline-variant bg-md-surface text-md-on-surface',
  glass: 'md-glass text-md-on-surface',
  // Extruded rather than layered: no border, paired light and shadow instead.
  neo: 'bg-md-surface-container text-md-on-surface shadow-neo',
};

/**
 * Tonal surface card — 24px radius, no border, depth from the surface step
 * rather than a heavy shadow. Interactive cards progress e1 -> e2 on hover.
 */
export function Card({
  tone = 'container',
  interactive = false,
  padded = true,
  className,
  children,
  ...rest
}: CardProps) {
  return (
    <div
      className={cn(
        'rounded-lg shadow-e1 transition-all duration-medium ease-md',
        TONES[tone],
        padded && 'p-5 sm:p-6',
        interactive &&
          'group cursor-pointer hover:-translate-y-0.5 hover:shadow-e2 active:translate-y-0 active:scale-[0.99]',
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}

interface SectionHeaderProps {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  icon?: ReactNode;
  className?: string;
}

export function SectionHeader({ title, subtitle, action, icon, className }: SectionHeaderProps) {
  return (
    <div className={cn('flex items-start justify-between gap-3', className)}>
      <div className="flex min-w-0 items-start gap-3">
        {icon && (
          <span className="mt-0.5 grid h-9 w-9 shrink-0 place-items-center rounded-full bg-md-secondary-container text-md-on-secondary-container">
            {icon}
          </span>
        )}
        <div className="min-w-0">
          <h2 className="text-title-md font-medium text-md-on-surface">{title}</h2>
          {subtitle && (
            <p className="mt-0.5 font-prose text-label-md text-md-on-surface-variant">{subtitle}</p>
          )}
        </div>
      </div>
      {action}
    </div>
  );
}
