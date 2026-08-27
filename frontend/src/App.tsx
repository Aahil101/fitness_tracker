import { Loader2 } from 'lucide-react';
import { lazy, Suspense } from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';

import { AppShell } from '@/components/AppShell';
import { Blobs, ErrorState } from '@/components/md';
import { useMe } from '@/hooks/queries';
import { useAuth } from '@/hooks/authContext';
import { ApiError } from '@/lib/api';
import { AuthPage } from '@/pages/Auth';
import { Dashboard } from '@/pages/Dashboard';
import { Onboarding } from '@/pages/Onboarding';
import { SetupRequired } from '@/pages/SetupRequired';

// Route-level splitting: the charts and chat bundles only load when visited.
const Analytics = lazy(() => import('@/pages/Analytics').then((m) => ({ default: m.Analytics })));
const Coach = lazy(() => import('@/pages/Coach').then((m) => ({ default: m.Coach })));
const Diary = lazy(() => import('@/pages/Diary').then((m) => ({ default: m.Diary })));
const Settings = lazy(() => import('@/pages/Settings').then((m) => ({ default: m.Settings })));

export function App() {
  const { session, initialising, configured } = useAuth();

  // Missing Supabase env vars: show setup instructions rather than a broken app.
  if (!configured) return <SetupRequired />;
  if (initialising) return <FullScreenLoader label="Restoring your session" />;
  if (!session) return <AuthPage />;

  return <AuthenticatedApp />;
}

function AuthenticatedApp() {
  const { data, isLoading, error, refetch } = useMe();

  if (isLoading) return <FullScreenLoader label="Loading your numbers" />;

  if (error) {
    const apiError = error instanceof ApiError ? error : null;
    return (
      <div className="mx-auto max-w-xl px-4 py-16">
        <ErrorState
          title={apiError?.isConfigError ? 'Backend is not fully configured' : 'Could not load your profile'}
          message={error instanceof Error ? error.message : 'Unknown error'}
          onRetry={() => void refetch()}
        />
      </div>
    );
  }

  // First run: collect the numbers the maths needs before showing the gauge.
  if (data?.needs_onboarding) return <Onboarding />;

  return (
    <AppShell userName={data?.profile.full_name} userEmail={data?.user.email}>
      <Suspense fallback={<InlineLoader />}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/diary" element={<Diary />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/coach" element={<Coach />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    </AppShell>
  );
}

function FullScreenLoader({ label }: { label: string }) {
  return (
    <div className="relative grid min-h-dvh place-items-center bg-md-surface px-6">
      <Blobs variant="page" />
      <div className="flex flex-col items-center gap-4">
        <span className="grid h-14 w-14 place-items-center rounded-xl bg-md-primary text-md-on-primary shadow-e3">
          <Loader2 size={24} className="animate-spin" />
        </span>
        <p className="text-body-sm text-md-on-surface-variant">{label}…</p>
      </div>
    </div>
  );
}

function InlineLoader() {
  return (
    <div className="flex items-center justify-center py-20 text-md-on-surface-variant">
      <Loader2 size={22} className="animate-spin" />
    </div>
  );
}
