import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

import { cn } from '@/lib/cn';

export type ButtonVariant = 'filled' | 'tonal' | 'outlined' | 'text' | 'elevated' | 'danger';
export type ButtonSize = 'sm' | 'md' | 'lg';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  fullWidth?: boolean;
  icon?: ReactNode;
  trailingIcon?: ReactNode;
}

/**
 * MD3 button. Pill-shaped in every variant (the single most recognisable
 * Material You trait) with a state layer for hover/press instead of a colour
 * swap, and `active:scale-95` so presses feel physical.
 */
const VARIANTS: Record<ButtonVariant, string> = {
  filled: 'bg-md-primary text-md-on-primary hover:bg-md-primary/90 active:bg-md-primary/80 hover:shadow-e2',
  tonal:
    'bg-md-secondary-container text-md-on-secondary-container hover:bg-md-secondary-container/80 active:bg-md-secondary-container/70 hover:shadow-e1',
  outlined:
    'border border-md-outline text-md-primary hover:bg-md-primary/[0.08] active:bg-md-primary/[0.12]',
  text: 'text-md-primary hover:bg-md-primary/[0.08] active:bg-md-primary/[0.12]',
  elevated:
    'bg-md-surface-container-low text-md-primary shadow-e1 hover:shadow-e2 hover:bg-md-primary/[0.06]',
  danger: 'bg-md-error text-md-on-error hover:bg-md-error/90 active:bg-md-error/80',
};

const SIZES: Record<ButtonSize, string> = {
  sm: 'h-9 px-4 text-label-md gap-1.5',
  md: 'h-11 px-6 text-label-lg gap-2',
  lg: 'h-14 px-8 text-body-md gap-2.5',
};

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = 'filled',
    size = 'md',
    loading = false,
    fullWidth = false,
    icon,
    trailingIcon,
    className,
    children,
    disabled,
    type = 'button',
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        'relative inline-flex select-none items-center justify-center rounded-full font-medium',
        'transition-all duration-medium ease-md active:scale-95',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-md-primary focus-visible:ring-offset-2 focus-visible:ring-offset-md-surface',
        'disabled:pointer-events-none disabled:opacity-50',
        VARIANTS[variant],
        SIZES[size],
        fullWidth && 'w-full',
        className,
      )}
      {...rest}
    >
      {loading ? (
        <span
          aria-hidden
          className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"
        />
      ) : (
        icon
      )}
      {children}
      {!loading && trailingIcon}
    </button>
  );
});
