import type { Session, User } from '@supabase/supabase-js';
import { createContext, useContext } from 'react';

export interface AuthState {
  session: Session | null;
  user: User | null;
  /** True until the first session check resolves — prevents an auth-page flash. */
  initialising: boolean;
  configured: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (
    email: string,
    password: string,
    fullName: string,
  ) => Promise<{ needsEmailConfirmation: boolean }>;
  sendPasswordReset: (email: string) => Promise<void>;
  signOut: () => Promise<void>;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside <AuthProvider>');
  return context;
}
