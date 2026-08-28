import type { Session } from '@supabase/supabase-js';
import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';

import { describeAuthError, isSupabaseConfigured, supabase } from '@/lib/supabase';
import { AuthContext, type AuthState } from './authContext';

/** Supabase errors are terse; rethrow them as sentences the UI can render. */
function fail(message: string): never {
  throw new Error(describeAuthError(message));
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [initialising, setInitialising] = useState(true);

  useEffect(() => {
    if (!isSupabaseConfigured) {
      setInitialising(false);
      return;
    }

    let active = true;
    supabase.auth
      .getSession()
      .then(({ data }) => {
        if (active) setSession(data.session ?? null);
      })
      .finally(() => {
        if (active) setInitialising(false);
      });

    const { data: subscription } = supabase.auth.onAuthStateChange((_event, nextSession) => {
      setSession(nextSession);
      setInitialising(false);
    });

    return () => {
      active = false;
      subscription.subscription.unsubscribe();
    };
  }, []);

  const signIn = useCallback(async (email: string, password: string) => {
    const { error } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    });
    if (error) fail(error.message);
  }, []);

  const signUp = useCallback(async (email: string, password: string, fullName: string) => {
    const { data, error } = await supabase.auth.signUp({
      email: email.trim(),
      password,
      options: {
        data: { full_name: fullName.trim() },
        emailRedirectTo: `${window.location.origin}/`,
      },
    });
    if (error) fail(error.message);
    // With email confirmation on, Supabase returns a user but no session.
    return { needsEmailConfirmation: Boolean(data.user && !data.session) };
  }, []);

  const sendPasswordReset = useCallback(async (email: string) => {
    const { error } = await supabase.auth.resetPasswordForEmail(email.trim(), {
      redirectTo: `${window.location.origin}/`,
    });
    if (error) fail(error.message);
  }, []);

  const signOut = useCallback(async () => {
    await supabase.auth.signOut();
    setSession(null);
  }, []);

  const value = useMemo<AuthState>(
    () => ({
      session,
      user: session?.user ?? null,
      initialising,
      configured: isSupabaseConfigured,
      signIn,
      signUp,
      sendPasswordReset,
      signOut,
    }),
    [session, initialising, signIn, signUp, sendPasswordReset, signOut],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
