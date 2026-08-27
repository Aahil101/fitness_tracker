import { useEffect, useState } from 'react';

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() =>
    typeof window === 'undefined' ? false : window.matchMedia(query).matches,
  );

  useEffect(() => {
    const media = window.matchMedia(query);
    setMatches(media.matches);
    const onChange = (event: MediaQueryListEvent) => setMatches(event.matches);
    media.addEventListener('change', onChange);
    return () => media.removeEventListener('change', onChange);
  }, [query]);

  return matches;
}

/** Tailwind's `sm` breakpoint — the point where sheets become dialogs. */
export const useIsDesktop = () => useMediaQuery('(min-width: 640px)');

/** `lg` — where the bottom nav is replaced by a persistent side rail. */
export const useIsWide = () => useMediaQuery('(min-width: 1024px)');
