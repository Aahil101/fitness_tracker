import { useEffect, useRef, useState } from 'react';

/**
 * Animates a number from its previous value to the next one.
 *
 * The point is not decoration: when a logged meal changes the deficit, a figure
 * that slides makes it obvious *which* figure moved and by roughly how much,
 * where an instant swap reads as a page reload. It runs only on change, never on
 * first paint, so arriving at the dashboard does not set every number spinning.
 *
 * Honours prefers-reduced-motion by jumping straight to the value — animated
 * numbers are exactly the sort of movement that setting exists to suppress.
 */
export function useCountUp(value: number, durationMs = 650): number {
  const [display, setDisplay] = useState(value);
  const previous = useRef(value);
  const frame = useRef<number>();

  useEffect(() => {
    const from = previous.current;
    previous.current = value;

    if (from === value) return;

    const reduced =
      typeof window !== 'undefined' &&
      window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (reduced || durationMs <= 0) {
      setDisplay(value);
      return;
    }

    const start = performance.now();
    const step = (now: number) => {
      const progress = Math.min(1, (now - start) / durationMs);
      // Ease out: fast enough to feel responsive, settling rather than stopping.
      const eased = 1 - (1 - progress) ** 3;
      setDisplay(from + (value - from) * eased);
      if (progress < 1) frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);

    return () => {
      if (frame.current !== undefined) cancelAnimationFrame(frame.current);
    };
  }, [value, durationMs]);

  return display;
}
