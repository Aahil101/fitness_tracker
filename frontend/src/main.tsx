import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';

import { App } from './App';
import { ToastProvider } from './components/md';
import { AuthProvider } from './hooks/useAuth';
import { ApiError } from './lib/api';
import './index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 10 * 60_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        // Never retry auth, validation or configuration failures — they will
        // fail identically every time and only delay the error message.
        if (error instanceof ApiError) {
          if (error.isAuthError || error.isConfigError || error.isRateLimit) return false;
          if (error.status >= 400 && error.status < 500) return false;
        }
        return failureCount < 2;
      },
    },
    mutations: { retry: false },
  },
});

/**
 * Pick up a new deployment without a manual hard refresh.
 *
 * The generated service worker uses skipWaiting + clientsClaim, so a new version
 * activates and claims open pages straight away — but a page already loaded keeps
 * the assets it fetched, leaving the user on the previous build until they reload
 * by hand. That stranded a shipped feature behind a cached shell.
 *
 * `controllerchange` fires exactly when the new worker takes over, which is the
 * right moment to reload. The flag guards against a reload loop.
 */
function reloadOnServiceWorkerUpdate(): void {
  if (!('serviceWorker' in navigator)) return;
  // A page with no controller yet is a first install, not an update; reloading
  // then would interrupt the very first visit for nothing.
  const wasControlled = Boolean(navigator.serviceWorker.controller);
  let reloading = false;
  navigator.serviceWorker.addEventListener('controllerchange', () => {
    if (!wasControlled || reloading) return;
    reloading = true;
    window.location.reload();
  });
}

reloadOnServiceWorkerUpdate();

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <ToastProvider>
            <App />
          </ToastProvider>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
