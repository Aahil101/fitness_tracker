import { AnimatePresence, motion, useReducedMotion } from 'framer-motion';
import {
  ArrowRight,
  Camera,
  Check,
  Eye,
  EyeOff,
  Flame,
  Lock,
  Mail,
  MessageCircleHeart,
  Moon,
  Sparkles,
  Sun,
  TrendingDown,
  User,
} from 'lucide-react';
import { useMemo, useState, type FormEvent } from 'react';

import { CalorieGauge } from '@/components/CalorieGauge';
import { Badge, Blobs, Button, IconButton, TextField, useToast } from '@/components/md';
import { useAuth } from '@/hooks/authContext';
import { useTheme } from '@/hooks/useTheme';
import { cn } from '@/lib/cn';

type Mode = 'signin' | 'signup' | 'reset';

const FEATURES = [
  {
    icon: <Camera size={18} />,
    title: 'Photograph your plate',
    body: 'Gemini identifies each food, estimates the portion, and resolves real macros from the USDA database.',
  },
  {
    icon: <TrendingDown size={18} />,
    title: 'Know where you will land',
    body: 'Your rolling calorie balance becomes a weight projection — and it corrects itself against the scale.',
  },
  {
    icon: <MessageCircleHeart size={18} />,
    title: 'A coach that reads your log',
    body: 'Ask why the scale stalled. It answers with your own numbers, not generic advice.',
  },
];

const PASSWORD_RULES = [
  { label: '8+ characters', test: (value: string) => value.length >= 8 },
  { label: 'a letter', test: (value: string) => /[a-zA-Z]/.test(value) },
  { label: 'a number or symbol', test: (value: string) => /[\d\W]/.test(value) },
];

/**
 * Sign-in / sign-up. Two panes on desktop: a marketing-weight left column that
 * shows the actual product primitive (a live gauge) and the form on the right.
 * On mobile the pitch collapses to a compact header so the form stays above the
 * fold — nobody wants to scroll past a hero to log in.
 */
export function AuthPage() {
  const { signIn, signUp, signInWithGoogle, sendPasswordReset } = useAuth();
  const { theme, toggle } = useTheme();
  const toast = useToast();
  const reduceMotion = useReducedMotion();

  const [mode, setMode] = useState<Mode>('signin');
  const [fullName, setFullName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);

  // A demo gauge that animates on load, so the value proposition is visible
  // before signing up rather than described in prose.
  const demo = useMemo(() => ({ logged: 1420, maintenance: 2400, target: 1900 }), []);

  const passwordChecks = PASSWORD_RULES.map((rule) => ({
    ...rule,
    ok: rule.test(password),
  }));
  const passwordStrong = passwordChecks.every((check) => check.ok);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setError(null);

    if (mode === 'signup' && !fullName.trim()) {
      setError('What should we call you?');
      return;
    }
    if (mode === 'signup' && !passwordStrong) {
      setError('Pick a slightly stronger password.');
      return;
    }

    setBusy(true);
    try {
      if (mode === 'reset') {
        await sendPasswordReset(email);
        setSentTo(email);
        toast.success('Password reset link sent.');
      } else if (mode === 'signup') {
        const { needsEmailConfirmation } = await signUp(email, password, fullName);
        if (needsEmailConfirmation) {
          setSentTo(email);
          toast.success('Check your inbox to confirm your address.');
        }
      } else {
        await signIn(email, password);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Something went wrong.');
    } finally {
      setBusy(false);
    }
  }

  const copy = {
    signin: { title: 'Welcome back', cta: 'Sign in', switchTo: 'signup' as Mode },
    signup: { title: 'Create your account', cta: 'Create account', switchTo: 'signin' as Mode },
    reset: { title: 'Reset your password', cta: 'Send reset link', switchTo: 'signin' as Mode },
  }[mode];

  return (
    <div className="relative min-h-dvh overflow-hidden bg-md-surface">
      <Blobs variant="hero" />

      <div className="absolute right-4 top-4 z-20 sm:right-6 sm:top-6">
        <IconButton
          label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
          onClick={toggle}
          variant="outlined"
        >
          {theme === 'dark' ? <Sun size={19} /> : <Moon size={19} />}
        </IconButton>
      </div>

      <div className="relative mx-auto grid min-h-dvh max-w-6xl items-center gap-10 px-5 py-10 lg:grid-cols-[1.05fr_1fr] lg:gap-16 lg:px-8">
        {/* -- Pitch ----------------------------------------------------- */}
        <motion.section
          initial={reduceMotion ? undefined : { opacity: 0, y: 24 }}
          animate={reduceMotion ? undefined : { opacity: 1, y: 0 }}
          transition={{ duration: 0.6, ease: [0.2, 0, 0, 1] }}
          className="order-1"
        >
          <div className="flex items-center gap-3">
            <span className="grid h-11 w-11 place-items-center rounded-md bg-md-primary text-md-on-primary shadow-e2">
              <Flame size={22} />
            </span>
            <div>
              <p className="text-title-md font-medium tracking-tight">Pulse</p>
              <p className="text-label-sm text-md-on-surface-variant">
                AI nutrition &amp; fitness tracking
              </p>
            </div>
          </div>

          <h1 className="mt-7 text-headline-md font-medium leading-tight tracking-tight sm:text-headline-lg">
            Stop guessing.
            <span className="block bg-gradient-to-r from-md-primary via-md-tertiary to-md-primary bg-clip-text text-transparent">
              Watch the deficit happen.
            </span>
          </h1>

          <p className="mt-4 max-w-lg text-body-md text-md-on-surface-variant sm:text-body-lg">
            Snap a photo, get real macros, and see the exact weight your current pace is heading
            towards — recalculated with every entry.
          </p>

          {/* Live product primitive instead of a stock screenshot. */}
          <div className="relative mt-8 hidden max-w-md rounded-2xl bg-md-surface-container/80 p-6 shadow-e2 backdrop-blur-sm sm:block">
            <div className="flex items-center justify-between">
              <span className="text-label-md font-medium text-md-on-surface-variant">
                Today at a glance
              </span>
              <Badge tone="success" icon={<Sparkles size={12} />}>
                480 kcal left
              </Badge>
            </div>
            <div className="mt-2">
              <CalorieGauge {...demo} />
            </div>
          </div>

          <ul className="mt-8 grid gap-4 sm:grid-cols-3 lg:grid-cols-1 lg:gap-3">
            {FEATURES.map((feature, index) => (
              <motion.li
                key={feature.title}
                initial={reduceMotion ? undefined : { opacity: 0, y: 16 }}
                animate={reduceMotion ? undefined : { opacity: 1, y: 0 }}
                transition={{ duration: 0.5, delay: 0.15 + index * 0.1, ease: [0.2, 0, 0, 1] }}
                className="group flex gap-3 rounded-lg bg-md-surface-container/60 p-4 transition-all duration-medium ease-md hover:-translate-y-0.5 hover:bg-md-surface-container hover:shadow-e2"
              >
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-md-secondary-container text-md-on-secondary-container transition-transform duration-medium group-hover:scale-110">
                  {feature.icon}
                </span>
                <div>
                  <p className="text-label-lg font-medium">{feature.title}</p>
                  <p className="mt-0.5 text-body-sm text-md-on-surface-variant">{feature.body}</p>
                </div>
              </motion.li>
            ))}
          </ul>
        </motion.section>

        {/* -- Form ------------------------------------------------------ */}
        <motion.section
          initial={reduceMotion ? undefined : { opacity: 0, y: 24, scale: 0.98 }}
          animate={reduceMotion ? undefined : { opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.6, delay: 0.1, ease: [0.2, 0, 0, 1] }}
          className="order-2 w-full"
        >
          <div className="mx-auto w-full max-w-md rounded-2xl bg-md-surface-container p-6 shadow-e3 sm:p-8">
            {/* Mode switch */}
            {mode !== 'reset' && (
              <div
                role="tablist"
                aria-label="Authentication mode"
                className="mb-6 grid grid-cols-2 gap-1 rounded-full bg-md-surface-container-low p-1"
              >
                {(['signin', 'signup'] as const).map((value) => (
                  <button
                    key={value}
                    role="tab"
                    aria-selected={mode === value}
                    type="button"
                    onClick={() => {
                      setMode(value);
                      setError(null);
                      setSentTo(null);
                    }}
                    className={cn(
                      'h-10 rounded-full text-label-lg font-medium transition-all duration-medium ease-md active:scale-95',
                      mode === value
                        ? 'bg-md-surface text-md-primary shadow-e1'
                        : 'text-md-on-surface-variant hover:bg-md-on-surface/[0.06]',
                    )}
                  >
                    {value === 'signin' ? 'Sign in' : 'Sign up'}
                  </button>
                ))}
              </div>
            )}

            <h2 className="text-title-lg font-medium">{copy.title}</h2>
            <p className="mt-1 text-body-sm text-md-on-surface-variant">
              {mode === 'signup'
                ? 'Two minutes of setup, then logging takes seconds.'
                : mode === 'reset'
                  ? 'We will email you a link to choose a new password.'
                  : 'Pick up where you left off.'}
            </p>

            {sentTo ? (
              <div className="mt-6 rounded-lg bg-md-success-container p-5 text-md-on-success-container">
                <Check size={20} />
                <p className="mt-2 text-label-lg font-medium">Check your email</p>
                <p className="mt-1 text-body-sm opacity-90">
                  We sent a link to <span className="font-medium">{sentTo}</span>. Open it on this
                  device to continue.
                </p>
                <Button
                  variant="text"
                  size="sm"
                  className="mt-3 text-md-on-success-container"
                  onClick={() => {
                    setSentTo(null);
                    setMode('signin');
                  }}
                >
                  Back to sign in
                </Button>
              </div>
            ) : (
              <form onSubmit={onSubmit} className="mt-6 space-y-4" noValidate>
                <AnimatePresence initial={false} mode="popLayout">
                  {mode === 'signup' && (
                    <motion.div
                      key="name"
                      initial={{ opacity: 0, height: 0 }}
                      animate={{ opacity: 1, height: 'auto' }}
                      exit={{ opacity: 0, height: 0 }}
                      transition={{ duration: 0.28, ease: [0.2, 0, 0, 1] }}
                    >
                      <TextField
                        label="Your name"
                        autoComplete="name"
                        leading={<User size={18} />}
                        value={fullName}
                        onChange={(event) => setFullName(event.target.value)}
                        placeholder="Alex Rahman"
                        required
                      />
                    </motion.div>
                  )}
                </AnimatePresence>

                <TextField
                  label="Email"
                  type="email"
                  inputMode="email"
                  autoComplete="email"
                  leading={<Mail size={18} />}
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  placeholder="you@example.com"
                  required
                />

                {mode !== 'reset' && (
                  <div>
                    <TextField
                      label="Password"
                      type={showPassword ? 'text' : 'password'}
                      autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
                      leading={<Lock size={18} />}
                      trailing={
                        <button
                          type="button"
                          onClick={() => setShowPassword((value) => !value)}
                          aria-label={showPassword ? 'Hide password' : 'Show password'}
                          className="rounded-full p-1 transition-colors hover:text-md-on-surface"
                        >
                          {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                        </button>
                      }
                      value={password}
                      onChange={(event) => setPassword(event.target.value)}
                      placeholder="••••••••"
                      required
                    />

                    {mode === 'signup' && password.length > 0 && (
                      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 px-4">
                        {passwordChecks.map((check) => (
                          <li
                            key={check.label}
                            className={cn(
                              'flex items-center gap-1.5 text-label-sm transition-colors duration-short',
                              check.ok ? 'text-md-success' : 'text-md-on-surface-variant',
                            )}
                          >
                            <Check size={13} className={check.ok ? 'opacity-100' : 'opacity-35'} />
                            {check.label}
                          </li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}

                {mode === 'signin' && (
                  <div className="flex justify-end">
                    <Button
                      variant="text"
                      size="sm"
                      onClick={() => {
                        setMode('reset');
                        setError(null);
                      }}
                    >
                      Forgot password?
                    </Button>
                  </div>
                )}

                {error && (
                  <motion.p
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    role="alert"
                    className="rounded-sm bg-md-error-container px-4 py-3 text-body-sm text-md-on-error-container"
                  >
                    {error}
                  </motion.p>
                )}

                <Button
                  type="submit"
                  size="lg"
                  fullWidth
                  loading={busy}
                  trailingIcon={busy ? undefined : <ArrowRight size={18} />}
                >
                  {copy.cta}
                </Button>

                {mode !== 'reset' && (
                  <>
                    <div className="flex items-center gap-3 py-1">
                      <span className="h-px flex-1 bg-md-outline-variant" />
                      <span className="text-label-sm text-md-on-surface-variant">or</span>
                      <span className="h-px flex-1 bg-md-outline-variant" />
                    </div>

                    <Button
                      variant="outlined"
                      size="lg"
                      fullWidth
                      icon={<GoogleMark />}
                      onClick={() => {
                        setError(null);
                        void signInWithGoogle().catch((caught: unknown) =>
                          setError(
                            caught instanceof Error
                              ? `${caught.message} (enable the Google provider in Supabase Auth first)`
                              : 'Google sign-in failed.',
                          ),
                        );
                      }}
                    >
                      Continue with Google
                    </Button>
                  </>
                )}

                {mode === 'reset' && (
                  <Button variant="text" fullWidth onClick={() => setMode('signin')}>
                    Back to sign in
                  </Button>
                )}
              </form>
            )}

            <p className="mt-6 text-center text-label-sm text-md-on-surface-variant">
              {mode === 'signup' ? 'Already have an account?' : 'New here?'}{' '}
              <button
                type="button"
                onClick={() => {
                  setMode(copy.switchTo);
                  setError(null);
                  setSentTo(null);
                }}
                className="rounded font-medium text-md-primary underline-offset-2 hover:underline"
              >
                {mode === 'signup' ? 'Sign in' : 'Create one'}
              </button>
            </p>
          </div>

          <p className="mx-auto mt-4 max-w-md text-center text-label-sm text-md-on-surface-variant/80">
            Your log is private to your account, enforced by row-level security in the database.
          </p>
        </motion.section>
      </div>
    </div>
  );
}

function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" className="h-4.5 w-4.5" aria-hidden width={18} height={18}>
      <path
        fill="#4285F4"
        d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.27-4.74 3.27-8.1z"
      />
      <path
        fill="#34A853"
        d="M12 23c2.97 0 5.46-.98 7.28-2.65l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84A10.99 10.99 0 0 0 12 23z"
      />
      <path
        fill="#FBBC05"
        d="M5.84 14.11a6.6 6.6 0 0 1 0-4.22V7.05H2.18a11 11 0 0 0 0 9.9l3.66-2.84z"
      />
      <path
        fill="#EA4335"
        d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.05l3.66 2.84C6.71 7.31 9.14 5.38 12 5.38z"
      />
    </svg>
  );
}
