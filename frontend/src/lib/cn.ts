import { clsx, type ClassValue } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';

/**
 * tailwind-merge has to be told about this theme's custom scales, or it guesses
 * wrong and silently drops classes.
 *
 * The type scale registers font sizes named `label-md`, `title-lg` and so on,
 * while colours live under an `md-` prefix. Both produce `text-*` utilities, so
 * out of the box `text-md-on-info` and `text-label-md` look like the same
 * conflict group and the earlier one is removed. Button labels lost their colour
 * that way — every filled button rendered body-coloured text on a saturated
 * fill, which is exactly the poor contrast that prompted this change.
 *
 * Declaring the two groups explicitly keeps a size and a colour on the same
 * element, as intended.
 */
const TYPE_SCALE = [
  'display-lg', 'display-md', 'display-sm',
  'headline-lg', 'headline-md', 'headline-sm',
  'title-lg', 'title-md', 'title-sm',
  'body-lg', 'body-md', 'body-sm',
  'label-lg', 'label-md', 'label-sm',
];

/** Colour utilities in this theme are all prefixed, e.g. `md-on-info`. */
const isThemeColour = (value: string) => value.startsWith('md-');

const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      'font-size': [{ text: TYPE_SCALE }],
      'text-color': [{ text: [isThemeColour] }],
    },
  },
});

/** Merge conditional classes, letting later Tailwind utilities win. */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
