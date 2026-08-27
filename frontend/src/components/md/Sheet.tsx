import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import { X } from 'lucide-react';
import { useEffect, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

import { cn } from '@/lib/cn';
import { IconButton } from './IconButton';

interface SheetProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  /** 'sheet' slides from the bottom on mobile; 'dialog' is always centred. */
  variant?: 'sheet' | 'dialog';
  size?: 'sm' | 'md' | 'lg';
  hideClose?: boolean;
}

const SIZES = { sm: 'sm:max-w-md', md: 'sm:max-w-xl', lg: 'sm:max-w-3xl' } as const;

/**
 * Bottom sheet on phones, centred dialog from `sm` up — one component so the
 * logging flows do not need two code paths. Locks background scroll, closes on
 * Escape or backdrop click, and animates with MD3's emphasised easing.
 */
export function Sheet({
  open,
  onClose,
  title,
  description,
  children,
  footer,
  variant = 'sheet',
  size = 'md',
  hideClose = false,
}: SheetProps) {
  const reduceMotion = useReducedMotion();

  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
    };
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [open, onClose]);

  const isSheet = variant === 'sheet';

  return createPortal(
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50 flex items-end justify-center sm:items-center sm:p-6">
          <motion.div
            className="absolute inset-0 bg-black/45 backdrop-blur-sm"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.2 }}
            onClick={onClose}
            aria-hidden
          />

          <motion.div
            role="dialog"
            aria-modal="true"
            aria-label={title}
            initial={
              reduceMotion
                ? { opacity: 0 }
                : isSheet
                  ? { y: '100%', opacity: 1 }
                  : { opacity: 0, scale: 0.96 }
            }
            animate={reduceMotion ? { opacity: 1 } : { y: 0, opacity: 1, scale: 1 }}
            exit={
              reduceMotion
                ? { opacity: 0 }
                : isSheet
                  ? { y: '100%' }
                  : { opacity: 0, scale: 0.97 }
            }
            transition={{ duration: reduceMotion ? 0.01 : 0.32, ease: [0.2, 0, 0, 1] }}
            className={cn(
              'relative flex max-h-[92dvh] w-full flex-col bg-md-surface-container shadow-e5',
              // 28px top corners on mobile, fully rounded once centred.
              isSheet ? 'rounded-t-xl sm:rounded-xl' : 'rounded-xl',
              SIZES[size],
            )}
          >
            {/* Drag handle affordance, mobile only */}
            {isSheet && (
              <div className="flex justify-center pt-3 sm:hidden" aria-hidden>
                <span className="h-1 w-10 rounded-full bg-md-outline-variant" />
              </div>
            )}

            <header className="flex items-start justify-between gap-4 px-5 pb-3 pt-4 sm:px-7 sm:pt-6">
              <div className="min-w-0">
                <h2 className="text-title-lg font-medium text-md-on-surface">{title}</h2>
                {description && (
                  <p className="mt-1 text-body-sm text-md-on-surface-variant">{description}</p>
                )}
              </div>
              {!hideClose && (
                <IconButton label="Close" onClick={onClose} className="-mr-1 -mt-1">
                  <X size={20} />
                </IconButton>
              )}
            </header>

            <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-2 sm:px-7">{children}</div>

            {footer && (
              <footer
                className="flex flex-wrap items-center justify-end gap-3 border-t border-md-outline-variant/60 px-5 py-4 sm:px-7"
                style={{ paddingBottom: 'max(1rem, env(safe-area-inset-bottom))' }}
              >
                {footer}
              </footer>
            )}
          </motion.div>
        </div>
      )}
    </AnimatePresence>,
    document.body,
  );
}
