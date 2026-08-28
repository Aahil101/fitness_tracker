import { createClient, type SupabaseClient } from '@supabase/supabase-js';

const url = import.meta.env.VITE_SUPABASE_URL?.trim();
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY?.trim();

/**
 * True only when both values are present *and* look real. Placeholder values
 * from .env.example would otherwise produce confusing network errors instead of
 * the setup screen we actually want to show.
 */
export const isSupabaseConfigured = Boolean(
  url && anonKey && url.startsWith('http') && !url.includes('YOUR-PROJECT') && anonKey.length > 20,
);

const STORAGE_KEY = 'pulse.auth';
const REMEMBER_KEY = 'pulse.remember';
const LAST_EMAIL_KEY = 'pulse.last-email';

/** Storage access throws in some privacy modes, so every call is guarded. */
function safe<T>(operation: () => T, fallback: T): T {
  try {
    return operation();
  } catch {
    return fallback;
  }
}

/**
 * Whether the session should outlive the browser session. Defaults to true:
 * being signed out on every visit is the worse surprise, and the preference is
 * only ever turned off deliberately.
 */
export function isRememberMeEnabled(): boolean {
  return safe(() => window.localStorage.getItem(REMEMBER_KEY) !== '0', true);
}

/**
 * Records the choice *before* signing in, so the session Supabase writes lands
 * in the right store. Also clears the other store's copy, otherwise a stale
 * session in the abandoned store could revive a sign-in the user opted out of.
 */
export function setRememberMe(remember: boolean): void {
  safe(() => {
    window.localStorage.setItem(REMEMBER_KEY, remember ? '1' : '0');
    (remember ? window.sessionStorage : window.localStorage).removeItem(STORAGE_KEY);
  }, undefined);
}

/** Last address signed in with, so returning users need not retype it. */
export function rememberedEmail(): string {
  return isRememberMeEnabled() ? safe(() => window.localStorage.getItem(LAST_EMAIL_KEY) ?? '', '') : '';
}

export function rememberEmail(email: string): void {
  safe(() => {
    if (isRememberMeEnabled()) window.localStorage.setItem(LAST_EMAIL_KEY, email);
    else window.localStorage.removeItem(LAST_EMAIL_KEY);
  }, undefined);
}

/**
 * Routes the session to localStorage when "keep me signed in" is on and to
 * sessionStorage when it is off, where the browser discards it on close. The
 * decision is read per call rather than captured once, so toggling it takes
 * effect without rebuilding the client.
 */
const rememberAwareStorage = {
  getItem: (key: string) =>
    safe(() => (isRememberMeEnabled() ? window.localStorage : window.sessionStorage).getItem(key), null),
  setItem: (key: string, value: string) =>
    safe(() => (isRememberMeEnabled() ? window.localStorage : window.sessionStorage).setItem(key, value), undefined),
  removeItem: (key: string) =>
    safe(() => {
      // Remove from both: the preference may have flipped since the write.
      window.localStorage.removeItem(key);
      window.sessionStorage.removeItem(key);
    }, undefined),
};

export const supabase: SupabaseClient = createClient(
  isSupabaseConfigured ? url! : 'http://localhost:54321',
  isSupabaseConfigured ? anonKey! : 'public-anon-key-placeholder',
  {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
      storageKey: STORAGE_KEY,
      storage: rememberAwareStorage,
      flowType: 'pkce',
    },
  },
);

/** Current access token, refreshing first if the session is close to expiry. */
export async function getAccessToken(): Promise<string | null> {
  if (!isSupabaseConfigured) return null;
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token ?? null;
}

/** Turns Supabase's terse auth errors into something a person can act on. */
export function describeAuthError(message: string): string {
  const text = message.toLowerCase();
  if (text.includes('invalid login credentials')) {
    return 'That email and password combination does not match an account.';
  }
  if (text.includes('email not confirmed')) {
    return 'Check your inbox and confirm your email address first.';
  }
  if (text.includes('user already registered')) {
    return 'An account with this email already exists — try signing in instead.';
  }
  if (text.includes('password should be at least')) {
    return 'Passwords need at least 8 characters.';
  }
  if (text.includes('rate limit') || text.includes('too many')) {
    return 'Too many attempts. Wait a minute and try again.';
  }
  if (text.includes('failed to fetch') || text.includes('networkerror')) {
    return 'Could not reach Supabase. Check your connection and VITE_SUPABASE_URL.';
  }
  return message;
}
