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

export const supabase: SupabaseClient = createClient(
  isSupabaseConfigured ? url! : 'http://localhost:54321',
  isSupabaseConfigured ? anonKey! : 'public-anon-key-placeholder',
  {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
      storageKey: 'pulse.auth',
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
