import {
  BookOpen,
  ChartLine,
  Home,
  LogOut,
  Moon,
  MessageCircleHeart,
  Settings as SettingsIcon,
  Sun,
} from 'lucide-react';
import type { ReactNode } from 'react';
import { NavLink, useLocation } from 'react-router-dom';

import { Blobs, IconButton } from '@/components/md';
import { useAuth } from '@/hooks/authContext';
import { useTheme } from '@/hooks/useTheme';
import { cn } from '@/lib/cn';
import { initials } from '@/lib/format';

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
}

const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Home', icon: <Home size={22} /> },
  { to: '/diary', label: 'Diary', icon: <BookOpen size={22} /> },
  { to: '/analytics', label: 'Trends', icon: <ChartLine size={22} /> },
  { to: '/coach', label: 'Coach', icon: <MessageCircleHeart size={22} /> },
  { to: '/settings', label: 'Settings', icon: <SettingsIcon size={22} /> },
];

/**
 * Responsive chrome: a bottom navigation bar on phones and a persistent side
 * rail from `lg` up. Both render the same items from one array so the two
 * layouts cannot drift apart.
 */
export function AppShell({
  children,
  userName,
  userEmail,
}: {
  children: ReactNode;
  userName?: string | null;
  userEmail?: string | null;
}) {
  const { theme, toggle } = useTheme();
  const { signOut } = useAuth();
  const location = useLocation();

  return (
    <div className="relative min-h-dvh bg-md-surface">
      <Blobs variant="page" />

      {/* -- Top bar ------------------------------------------------------ */}
      <header className="sticky top-0 z-30 border-b border-md-outline-variant/50 bg-md-surface/85 backdrop-blur-lg">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
          <NavLink to="/" className="flex items-center gap-2.5" aria-label="Pulse home">
            <span className="grid h-9 w-9 place-items-center rounded-sm bg-md-primary text-md-on-primary shadow-e1">
              <GaugeMark />
            </span>
            <span className="text-title-md font-medium tracking-tight">Pulse</span>
          </NavLink>

          <div className="flex items-center gap-1.5">
            <IconButton
              label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              onClick={toggle}
            >
              {theme === 'dark' ? <Sun size={19} /> : <Moon size={19} />}
            </IconButton>
            <IconButton label="Sign out" onClick={() => void signOut()}>
              <LogOut size={19} />
            </IconButton>
            <NavLink
              to="/settings"
              aria-label="Your profile"
              className="ml-1 grid h-9 w-9 place-items-center rounded-full bg-md-secondary-container text-label-md font-medium text-md-on-secondary-container transition-transform duration-short hover:scale-105 active:scale-95"
            >
              {initials(userName, userEmail)}
            </NavLink>
          </div>
        </div>
      </header>

      <div className="mx-auto flex max-w-6xl gap-6 px-4 sm:px-6">
        {/* -- Side rail (lg+) ------------------------------------------ */}
        <nav
          aria-label="Main navigation"
          className="sticky top-20 hidden h-fit shrink-0 flex-col gap-1 py-6 lg:flex"
        >
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === '/'}
              className={({ isActive }) =>
                cn(
                  'group flex w-[7.5rem] flex-col items-center gap-1 rounded-md px-3 py-3',
                  'transition-all duration-medium ease-md active:scale-95',
                  isActive
                    ? 'bg-md-secondary-container text-md-on-secondary-container'
                    : 'text-md-on-surface-variant hover:bg-md-on-surface/[0.06]',
                )
              }
            >
              {item.icon}
              <span className="text-label-sm font-medium">{item.label}</span>
            </NavLink>
          ))}
        </nav>

        {/* -- Page content --------------------------------------------- */}
        <main
          className="min-w-0 flex-1 pb-28 pt-5 sm:pt-6 lg:pb-10"
          // Re-run entrance animations on navigation.
          key={location.pathname}
        >
          <div className="animate-fade-up">{children}</div>
        </main>
      </div>

      {/* -- Bottom navigation (mobile) -------------------------------- */}
      <nav
        aria-label="Main navigation"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-md-outline-variant/50 bg-md-surface-container/95 backdrop-blur-lg lg:hidden"
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
      >
        <ul className="mx-auto flex max-w-lg items-stretch justify-between px-2">
          {NAV_ITEMS.map((item) => (
            <li key={item.to} className="flex-1">
              <NavLink
                to={item.to}
                end={item.to === '/'}
                className={({ isActive }) =>
                  cn(
                    'flex flex-col items-center gap-1 px-1 py-2.5',
                    'transition-colors duration-short ease-md',
                    isActive ? 'text-md-primary' : 'text-md-on-surface-variant',
                  )
                }
              >
                {({ isActive }) => (
                  <>
                    {/* MD3 active indicator: a tonal pill behind the icon. */}
                    <span
                      className={cn(
                        'grid h-8 w-16 place-items-center rounded-full transition-all duration-medium ease-md',
                        isActive ? 'bg-md-secondary-container' : 'bg-transparent',
                      )}
                    >
                      {item.icon}
                    </span>
                    <span className="text-label-sm font-medium">{item.label}</span>
                  </>
                )}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
    </div>
  );
}

/** The gauge motif from the app icon, reused as the wordmark glyph. */
function GaugeMark() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" aria-hidden>
      <path
        d="M4 15a8 8 0 0 1 16 0"
        fill="none"
        stroke="currentColor"
        strokeOpacity="0.4"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
      <path
        d="M4 15a8 8 0 0 1 5.2-7.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.6"
        strokeLinecap="round"
      />
      <circle cx="12" cy="15" r="1.6" fill="currentColor" />
    </svg>
  );
}
