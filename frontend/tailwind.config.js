/**
 * Material You (MD3) token system.
 *
 * Colours are declared as space-separated RGB channels in CSS variables so
 * Tailwind's alpha modifiers work on every token — that is what makes the MD3
 * state-layer model (`bg-md-primary/90`, `bg-md-primary/10`) expressible as
 * utilities instead of one-off CSS. Swapping the light/dark palette is then a
 * matter of toggling one class on <html>.
 */

/** @param {string} variable */
const token = (variable) => `rgb(var(${variable}) / <alpha-value>)`;

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        md: {
          // Surfaces — never pure white; depth comes from tonal steps.
          surface: token('--md-surface'),
          'surface-dim': token('--md-surface-dim'),
          'surface-container': token('--md-surface-container'),
          'surface-container-low': token('--md-surface-container-low'),
          'surface-container-high': token('--md-surface-container-high'),
          'surface-container-highest': token('--md-surface-container-highest'),
          'surface-variant': token('--md-surface-variant'),

          // Content
          'on-surface': token('--md-on-surface'),
          'on-surface-variant': token('--md-on-surface-variant'),
          'on-background': token('--md-on-surface'),

          // Primary
          primary: token('--md-primary'),
          'on-primary': token('--md-on-primary'),
          'primary-container': token('--md-primary-container'),
          'on-primary-container': token('--md-on-primary-container'),
          'primary-fixed-dim': token('--md-primary-fixed-dim'),

          // Secondary
          secondary: token('--md-secondary'),
          'on-secondary': token('--md-on-secondary'),
          'secondary-container': token('--md-secondary-container'),
          'on-secondary-container': token('--md-on-secondary-container'),

          // Tertiary — accents and FABs
          tertiary: token('--md-tertiary'),
          'on-tertiary': token('--md-on-tertiary'),
          'tertiary-container': token('--md-tertiary-container'),
          'on-tertiary-container': token('--md-on-tertiary-container'),

          // Feedback
          error: token('--md-error'),
          'on-error': token('--md-on-error'),
          'error-container': token('--md-error-container'),
          'on-error-container': token('--md-on-error-container'),
          success: token('--md-success'),
          'success-container': token('--md-success-container'),
          'on-success-container': token('--md-on-success-container'),
          warning: token('--md-warning'),
          'warning-container': token('--md-warning-container'),
          'on-warning-container': token('--md-on-warning-container'),
          info: token('--md-info'),
          'info-strong': token('--md-info-strong'),
          'on-info': token('--md-on-info'),
          'info-container': token('--md-info-container'),
          'on-info-container': token('--md-on-info-container'),

          // Outlines
          outline: token('--md-outline'),
          'outline-variant': token('--md-outline-variant'),
          border: token('--md-outline-variant'),

          // Inverse (snackbars, tooltips)
          inverse: token('--md-inverse-surface'),
          'on-inverse': token('--md-inverse-on-surface'),

          // Data-visualisation roles used by the gauge and charts
          gauge: token('--md-gauge-fill'),
          'gauge-track': token('--md-gauge-track'),
          'gauge-marker': token('--md-gauge-marker'),
          'chart-in': token('--md-chart-in'),
          'chart-out': token('--md-chart-out'),
          'chart-protein': token('--md-chart-protein'),
          'chart-carbs': token('--md-chart-carbs'),
          'chart-fat': token('--md-chart-fat'),
          'chart-fiber': token('--md-chart-fiber'),
        },
      },

      fontFamily: {
        // Scoutie Sans carries the interface; Inter is for descriptive copy,
        // where its larger x-height reads better at small sizes.
        sans: ['"Scoutie Sans"', 'Inter', 'system-ui', '-apple-system', 'sans-serif'],
        prose: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        // Tabular figures keep changing numbers from jittering the layout.
        numeric: ['"Roboto Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },

      // MD3 type scale.
      fontSize: {
        'display-lg': ['3.5rem', { lineHeight: '1.14', letterSpacing: '-0.01em' }],
        'display-md': ['2.8rem', { lineHeight: '1.16', letterSpacing: '-0.01em' }],
        'headline-lg': ['3rem', { lineHeight: '1.2', letterSpacing: '-0.01em' }],
        'headline-md': ['2rem', { lineHeight: '1.25', letterSpacing: '0' }],
        'headline-sm': ['1.75rem', { lineHeight: '1.28', letterSpacing: '0' }],
        'title-lg': ['1.5rem', { lineHeight: '1.33', letterSpacing: '0' }],
        'title-md': ['1.125rem', { lineHeight: '1.4', letterSpacing: '0.01em' }],
        'body-lg': ['1.25rem', { lineHeight: '1.55' }],
        'body-md': ['1rem', { lineHeight: '1.55' }],
        'body-sm': ['0.9375rem', { lineHeight: '1.5' }],
        'label-lg': ['0.9375rem', { lineHeight: '1.4', letterSpacing: '0.01em' }],
        'label-md': ['0.875rem', { lineHeight: '1.4', letterSpacing: '0.01em' }],
        'label-sm': ['0.75rem', { lineHeight: '1.4', letterSpacing: '0.02em' }],
      },

      // MD3 shape scale.
      borderRadius: {
        xs: '8px',
        sm: '12px',
        md: '16px',
        lg: '24px',
        xl: '28px',
        '2xl': '32px',
        '3xl': '48px',
      },

      // Soft, diffuse elevation — low opacity, large blur, no harsh drops.
      boxShadow: {
        e1: '0 1px 2px 0 rgb(0 0 0 / 0.05), 0 1px 3px 1px rgb(0 0 0 / 0.06)',
        e2: '0 1px 2px 0 rgb(0 0 0 / 0.06), 0 2px 6px 2px rgb(0 0 0 / 0.08)',
        e3: '0 4px 8px 3px rgb(0 0 0 / 0.08), 0 1px 3px 0 rgb(0 0 0 / 0.06)',
        e4: '0 6px 10px 4px rgb(0 0 0 / 0.09), 0 2px 3px 0 rgb(0 0 0 / 0.07)',
        e5: '0 8px 12px 6px rgb(0 0 0 / 0.1), 0 4px 4px 0 rgb(0 0 0 / 0.08)',
        // Soft UI: paired highlight and shadow so a surface reads as extruded
        // from the page rather than floating above it.
        neo: '-6px -6px 14px rgb(var(--md-neo-light) / 0.9), 6px 6px 16px rgb(var(--md-neo-shadow) / 0.5)',
        'neo-sm': '-3px -3px 7px rgb(var(--md-neo-light) / 0.85), 3px 3px 8px rgb(var(--md-neo-shadow) / 0.45)',
        'neo-inset': 'inset 3px 3px 7px rgb(var(--md-neo-shadow) / 0.45), inset -3px -3px 7px rgb(var(--md-neo-light) / 0.85)',
        'glow-primary': '0 0 0 1px rgb(var(--md-primary) / 0.18), 0 8px 32px -8px rgb(var(--md-primary) / 0.45)',
        'glow-tertiary': '0 0 0 1px rgb(var(--md-tertiary) / 0.18), 0 8px 32px -8px rgb(var(--md-tertiary) / 0.45)',
      },

      transitionTimingFunction: {
        // MD3 "emphasized decelerate" — the signature easing.
        md: 'cubic-bezier(0.2, 0, 0, 1)',
        'md-accelerate': 'cubic-bezier(0.3, 0, 0.8, 0.15)',
        'md-standard': 'cubic-bezier(0.2, 0, 0, 1)',
      },

      transitionDuration: {
        short: '200ms',
        medium: '300ms',
        long: '450ms',
      },

      keyframes: {
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(12px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'fade-in': {
          from: { opacity: '0' },
          to: { opacity: '1' },
        },
        'scale-in': {
          from: { opacity: '0', transform: 'scale(0.96)' },
          to: { opacity: '1', transform: 'scale(1)' },
        },
        'sheet-up': {
          from: { transform: 'translateY(100%)' },
          to: { transform: 'translateY(0)' },
        },
        // Slow drift for the background blur shapes.
        drift: {
          '0%, 100%': { transform: 'translate3d(0,0,0) scale(1)' },
          '33%': { transform: 'translate3d(3%, -4%, 0) scale(1.06)' },
          '66%': { transform: 'translate3d(-3%, 3%, 0) scale(0.96)' },
        },
        'pulse-ring': {
          '0%': { transform: 'scale(0.9)', opacity: '0.6' },
          '70%': { transform: 'scale(1.25)', opacity: '0' },
          '100%': { transform: 'scale(1.25)', opacity: '0' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
        'gauge-sweep': {
          from: { strokeDasharray: '0 10000' },
        },
      },

      animation: {
        'fade-up': 'fade-up 450ms cubic-bezier(0.2, 0, 0, 1) both',
        'fade-in': 'fade-in 300ms cubic-bezier(0.2, 0, 0, 1) both',
        'scale-in': 'scale-in 300ms cubic-bezier(0.2, 0, 0, 1) both',
        'sheet-up': 'sheet-up 300ms cubic-bezier(0.2, 0, 0, 1) both',
        drift: 'drift 22s ease-in-out infinite',
        'drift-slow': 'drift 34s ease-in-out infinite',
        'pulse-ring': 'pulse-ring 2.4s cubic-bezier(0.2, 0, 0, 1) infinite',
        shimmer: 'shimmer 1.6s infinite',
      },

      backgroundImage: {
        'md-hero':
          'radial-gradient(circle at 15% 15%, rgb(var(--md-primary) / 0.18) 0%, transparent 45%), radial-gradient(circle at 85% 10%, rgb(var(--md-tertiary) / 0.16) 0%, transparent 42%)',
      },

      screens: {
        // Below this the two primary action buttons stack instead of overflowing.
        xs: '380px',
      },
    },
  },
  plugins: [],
};
