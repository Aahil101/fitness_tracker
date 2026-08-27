import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

import { cn } from '@/lib/cn';

interface FabProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: ReactNode;
  /** Omit for a circular FAB; provide it for the extended variant. */
  label?: string;
  tone?: 'tertiary' | 'primary' | 'surface';
  size?: 'md' | 'lg';
  srLabel?: string;
}

const TONES = {
  tertiary: 'bg-md-tertiary text-md-on-tertiary hover:shadow-glow-tertiary',
  primary: 'bg-md-primary text-md-on-primary hover:shadow-glow-primary',
  surface: 'bg-md-surface-container-high text-md-primary',
} as const;

/**
 * Floating action button — 28px radius (not a pill) per MD3, e3 at rest rising
 * to e5 with a colour glow on hover.
 */
export const Fab = forwardRef<HTMLButtonElement, FabProps>(function Fab(
  { icon, label, tone = 'tertiary', size = 'md', srLabel, className, ...rest },
  ref,
) {
  const extended = Boolean(label);
  return (
    <button
      ref={ref}
      type="button"
      aria-label={srLabel ?? label}
      className={cn(
        'inline-flex items-center justify-center gap-2.5 rounded-xl font-medium shadow-e3',
        'transition-all duration-medium ease-md hover:shadow-e5 active:scale-95',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-md-primary focus-visible:ring-offset-2 focus-visible:ring-offset-md-surface',
        TONES[tone],
        extended
          ? size === 'lg'
            ? 'h-16 px-7 text-body-md'
            : 'h-14 px-6 text-label-lg'
          : size === 'lg'
            ? 'h-16 w-16'
            : 'h-14 w-14',
        className,
      )}
      {...rest}
    >
      {icon}
      {label}
    </button>
  );
});
