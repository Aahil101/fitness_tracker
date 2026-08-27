import { AnimatePresence, motion } from 'framer-motion';
import { AlertTriangle, CheckCircle2, Info, X } from 'lucide-react';
import { useCallback, useMemo, useRef, useState, type ReactNode } from 'react';

import { cn } from '@/lib/cn';
import { ToastContext, type ToastAction, type ToastApi, type ToastTone } from './toastContext';

interface Toast {
  id: number;
  message: string;
  tone: ToastTone;
  action?: ToastAction;
}

const ICONS: Record<ToastTone, ReactNode> = {
  success: <CheckCircle2 size={18} className="text-md-success" />,
  error: <AlertTriangle size={18} className="text-md-error" />,
  info: <Info size={18} className="text-md-primary-fixed-dim" />,
};

/** MD3 snackbar: inverse surface, 12px radius, bottom-centred above the nav. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }, []);

  const show = useCallback<ToastApi['show']>(
    (message, tone = 'info', action) => {
      const id = nextId.current++;
      // Keep at most three on screen; older ones drop off the top.
      setToasts((current) => [...current.slice(-2), { id, message, tone, action }]);
      // Errors linger; confirmations get out of the way.
      window.setTimeout(() => dismiss(id), tone === 'error' ? 7000 : 4000);
    },
    [dismiss],
  );

  const api = useMemo<ToastApi>(
    () => ({
      show,
      success: (message) => show(message, 'success'),
      error: (message) => show(message, 'error'),
    }),
    [show],
  );

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed inset-x-0 z-[60] flex flex-col items-center gap-2 px-4"
        style={{ bottom: 'max(5.75rem, calc(env(safe-area-inset-bottom) + 5.25rem))' }}
      >
        <AnimatePresence initial={false}>
          {toasts.map((toast) => (
            <motion.div
              key={toast.id}
              layout
              initial={{ opacity: 0, y: 16, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 8, scale: 0.97 }}
              transition={{ duration: 0.26, ease: [0.2, 0, 0, 1] }}
              className={cn(
                'pointer-events-auto flex w-full max-w-md items-center gap-3 rounded-sm',
                'bg-md-inverse px-4 py-3 text-body-sm text-md-on-inverse shadow-e3',
              )}
            >
              {ICONS[toast.tone]}
              <span className="min-w-0 flex-1">{toast.message}</span>
              {toast.action && (
                <button
                  type="button"
                  onClick={() => {
                    toast.action?.onClick();
                    dismiss(toast.id);
                  }}
                  className="shrink-0 rounded-full px-2 py-1 text-label-md font-medium text-md-primary-fixed-dim hover:bg-white/10"
                >
                  {toast.action.label}
                </button>
              )}
              <button
                type="button"
                aria-label="Dismiss"
                onClick={() => dismiss(toast.id)}
                className="shrink-0 rounded-full p-1 opacity-70 transition-opacity hover:opacity-100"
              >
                <X size={16} />
              </button>
            </motion.div>
          ))}
        </AnimatePresence>
      </div>
    </ToastContext.Provider>
  );
}
