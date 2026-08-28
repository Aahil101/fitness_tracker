import { ChevronDown, Info } from 'lucide-react';
import { useId, useState, type ReactNode } from 'react';

import { cn } from '@/lib/cn';

export interface DisclosureProps {
  /** Button text. Defaults to a question, because that is what the user has. */
  label?: string;
  children: ReactNode;
  className?: string;
}

/**
 * A small expandable explanation, for "how was this number worked out?".
 *
 * Every derived figure in this app — trend weight, measured maintenance, the
 * projected date — is the output of arithmetic the user cannot see. A number
 * they cannot interrogate is a number they have to take on faith, and the first
 * time it disagrees with their bathroom scale they will stop believing any of
 * it. So each one carries its own derivation, one tap away.
 *
 * Deliberately a real button with `aria-expanded`, not a hover tooltip: hover
 * does not exist on a phone, which is where this app is mostly used, and a
 * tooltip is unreachable by keyboard and inconsistently announced by screen
 * readers. The panel stays mounted and is hidden with the `hidden` attribute so
 * that `aria-controls` always points at something real.
 */
export function Disclosure({ label = 'How is this worked out?', children, className }: DisclosureProps) {
  const [open, setOpen] = useState(false);
  const panelId = useId();

  return (
    <div className={cn('mt-3', className)}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={panelId}
        className={cn(
          'inline-flex items-center gap-1.5 rounded-xs px-1 py-0.5',
          'font-prose text-label-sm text-md-on-surface-variant',
          'transition-colors hover:text-md-on-surface',
          'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-md-info',
        )}
      >
        <Info size={13} aria-hidden />
        {label}
        <ChevronDown
          size={13}
          aria-hidden
          className={cn('transition-transform motion-reduce:transition-none', open && 'rotate-180')}
        />
      </button>

      <div
        id={panelId}
        hidden={!open}
        className="mt-2 rounded-sm border border-md-outline-variant bg-md-surface-container-low p-3"
      >
        <p className="font-prose text-label-sm leading-relaxed text-md-on-surface-variant">
          {children}
        </p>
      </div>
    </div>
  );
}
