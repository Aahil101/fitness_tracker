import type { ButtonHTMLAttributes, ReactNode } from 'react';

import { cn } from '@/lib/cn';

interface ChipProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  selected?: boolean;
  icon?: ReactNode;
  children: ReactNode;
}

/** MD3 filter chip. Selected state uses the secondary container tone. */
export function Chip({ selected = false, icon, className, children, ...rest }: ChipProps) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      className={cn(
        'inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full px-4 text-label-md font-medium',
        'transition-all duration-short ease-md active:scale-95',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-md-primary focus-visible:ring-offset-2 focus-visible:ring-offset-md-surface',
        selected
          ? 'bg-md-secondary-container text-md-on-secondary-container shadow-e1'
          : 'border border-md-outline-variant text-md-on-surface-variant hover:bg-md-on-surface/[0.06]',
        className,
      )}
      {...rest}
    >
      {icon}
      {children}
    </button>
  );
}

interface SegmentedOption<T extends string | number> {
  value: T;
  label: string;
  icon?: ReactNode;
}

interface SegmentedProps<T extends string | number> {
  options: SegmentedOption<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
  size?: 'sm' | 'md';
  className?: string;
}

/**
 * MD3 segmented button group — a pill split into connected segments. Used for
 * the week/month/year and 7/14/30-day toggles on the front page.
 */
export function Segmented<T extends string | number>({
  options,
  value,
  onChange,
  label,
  size = 'md',
  className,
}: SegmentedProps<T>) {
  return (
    <div
      role="group"
      aria-label={label}
      className={cn(
        'inline-flex shrink-0 items-center gap-0.5 rounded-full bg-md-surface-container-low p-1',
        className,
      )}
    >
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={String(option.value)}
            type="button"
            aria-pressed={active}
            onClick={() => onChange(option.value)}
            className={cn(
              'relative inline-flex items-center justify-center gap-1.5 rounded-full font-medium',
              'transition-all duration-short ease-md active:scale-95',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-md-primary',
              size === 'sm' ? 'h-7 px-3 text-label-sm' : 'h-9 px-4 text-label-md',
              active
                ? 'bg-md-surface text-md-primary shadow-e1'
                : 'text-md-on-surface-variant hover:bg-md-on-surface/[0.06]',
            )}
          >
            {option.icon}
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

interface BadgeProps {
  tone?: 'neutral' | 'primary' | 'success' | 'warning' | 'error' | 'info';
  icon?: ReactNode;
  children: ReactNode;
  className?: string;
}

const BADGE_TONES = {
  neutral: 'bg-md-surface-container-high text-md-on-surface-variant',
  primary: 'bg-md-primary-container text-md-on-primary-container',
  success: 'bg-md-success-container text-md-on-success-container',
  warning: 'bg-md-warning-container text-md-on-warning-container',
  error: 'bg-md-error-container text-md-on-error-container',
  info: 'bg-md-secondary-container text-md-on-secondary-container',
} as const;

export function Badge({ tone = 'neutral', icon, children, className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-label-sm font-medium',
        BADGE_TONES[tone],
        className,
      )}
    >
      {icon}
      {children}
    </span>
  );
}
