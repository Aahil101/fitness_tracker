import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';

import { cn } from '@/lib/cn';

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Required: icon-only controls are invisible to screen readers without it. */
  label: string;
  variant?: 'standard' | 'filled' | 'tonal' | 'outlined';
  size?: 'sm' | 'md';
  children: ReactNode;
}

const VARIANTS = {
  standard: 'text-md-on-surface-variant hover:bg-md-on-surface/[0.08] active:bg-md-on-surface/[0.12]',
  filled: 'bg-md-primary text-md-on-primary hover:bg-md-primary/90 active:bg-md-primary/80',
  tonal:
    'bg-md-secondary-container text-md-on-secondary-container hover:bg-md-secondary-container/80',
  outlined:
    'border border-md-outline-variant text-md-on-surface-variant hover:bg-md-on-surface/[0.08]',
} as const;

export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(function IconButton(
  { label, variant = 'standard', size = 'md', className, children, type = 'button', ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      aria-label={label}
      title={label}
      className={cn(
        // 44px minimum touch target even at the small size.
        'inline-flex shrink-0 items-center justify-center rounded-full',
        'transition-all duration-short ease-md active:scale-95',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-md-primary focus-visible:ring-offset-2 focus-visible:ring-offset-md-surface',
        'disabled:pointer-events-none disabled:opacity-40',
        size === 'sm' ? 'h-9 w-9' : 'h-11 w-11',
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
});
