import { AlertTriangle } from 'lucide-react';
import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';
import { Button } from './Button';

/** Shimmering placeholder that matches the tonal surfaces. */
export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('md-skeleton rounded-sm', className)} aria-hidden />;
}

export function LinearProgress({
  value,
  tone = 'primary',
  className,
  label,
}: {
  /** 0..1; values above 1 are clamped but tint the bar as over-target. */
  value: number;
  tone?: 'primary' | 'success' | 'warning' | 'error' | 'gauge';
  className?: string;
  label?: string;
}) {
  const clamped = Math.max(0, Math.min(1, value));
  const tones = {
    primary: 'bg-md-primary',
    success: 'bg-md-success',
    warning: 'bg-md-warning',
    error: 'bg-md-error',
    gauge: 'bg-md-gauge',
  } as const;

  return (
    <div
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(clamped * 100)}
      aria-label={label}
      className={cn('h-2 w-full overflow-hidden rounded-full bg-md-surface-container-high', className)}
    >
      <div
        className={cn('h-full rounded-full transition-all duration-long ease-md', tones[tone])}
        style={{ width: `${clamped * 100}%` }}
      />
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn('flex flex-col items-center gap-3 px-6 py-10 text-center', className)}>
      {icon && (
        <span className="grid h-14 w-14 place-items-center rounded-full bg-md-secondary-container text-md-on-secondary-container">
          {icon}
        </span>
      )}
      <div>
        <p className="text-title-md font-medium text-md-on-surface">{title}</p>
        {description && (
          <p className="mx-auto mt-1 max-w-sm text-body-sm text-md-on-surface-variant">
            {description}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}

export function ErrorState({
  title = 'Something went wrong',
  message,
  onRetry,
  className,
}: {
  title?: string;
  message: string;
  onRetry?: () => void;
  className?: string;
}) {
  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col items-start gap-3 rounded-lg bg-md-error-container p-5 text-md-on-error-container sm:flex-row sm:items-center',
        className,
      )}
    >
      <AlertTriangle size={20} className="shrink-0" />
      <div className="min-w-0 flex-1">
        <p className="text-label-lg font-medium">{title}</p>
        <p className="mt-0.5 break-words text-body-sm opacity-90">{message}</p>
      </div>
      {onRetry && (
        <Button variant="text" size="sm" onClick={onRetry} className="text-md-on-error-container">
          Try again
        </Button>
      )}
    </div>
  );
}

/**
 * The signature Material You atmosphere: large organic shapes, heavily blurred,
 * positioned partly off-canvas. Purely decorative, so hidden from assistive tech.
 */
export function Blobs({
  variant = 'page',
  className,
}: {
  variant?: 'page' | 'hero' | 'corner';
  className?: string;
}) {
  if (variant === 'hero') {
    return (
      <div aria-hidden className={cn('pointer-events-none absolute inset-0 overflow-hidden', className)}>
        <span className="md-blob left-[-12%] top-[-18%] h-[26rem] w-[26rem] animate-drift bg-md-primary/30" />
        <span className="md-blob right-[-14%] top-[-8%] h-[22rem] w-[22rem] animate-drift-slow bg-md-tertiary/25" />
        <span className="md-blob bottom-[-24%] left-[28%] h-[24rem] w-[34rem] animate-drift bg-md-secondary/25" />
        <span className="absolute inset-0 bg-md-hero" />
      </div>
    );
  }

  if (variant === 'corner') {
    return (
      <div aria-hidden className={cn('pointer-events-none absolute inset-0 overflow-hidden', className)}>
        <span className="md-blob right-[-18%] top-[-30%] h-64 w-64 animate-drift-slow bg-md-primary/25" />
      </div>
    );
  }

  return (
    <div
      aria-hidden
      className={cn('pointer-events-none fixed inset-0 -z-10 overflow-hidden', className)}
    >
      <span className="md-blob left-[-10%] top-[-12%] h-80 w-80 animate-drift bg-md-primary/20" />
      <span className="md-blob right-[-12%] top-[22%] h-72 w-72 animate-drift-slow bg-md-tertiary/[0.18]" />
      <span className="md-blob bottom-[-16%] left-[35%] h-80 w-96 animate-drift bg-md-secondary/[0.16]" />
    </div>
  );
}
