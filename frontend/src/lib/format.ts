/** Display helpers. Units are stored in metric and converted only at the edge. */

import type { UnitPreference } from './types';

export const KG_TO_LB = 2.2046226218;
export const CM_TO_IN = 0.3937007874;

const numberFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 });
const oneDecimal = new Intl.NumberFormat(undefined, {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

export function kcal(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return numberFormat.format(Math.round(value));
}

export function grams(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${Math.round(value)} g`;
}

export function signedKcal(value: number): string {
  const rounded = Math.round(value);
  return `${rounded > 0 ? '+' : ''}${numberFormat.format(rounded)}`;
}

export function weight(kg: number | null | undefined, unit: UnitPreference = 'metric'): string {
  if (kg === null || kg === undefined || Number.isNaN(kg)) return '—';
  return unit === 'imperial' ? `${oneDecimal.format(kg * KG_TO_LB)} lb` : `${oneDecimal.format(kg)} kg`;
}

export function weightDelta(kg: number | null | undefined, unit: UnitPreference = 'metric'): string {
  if (kg === null || kg === undefined || Number.isNaN(kg)) return '—';
  const value = unit === 'imperial' ? kg * KG_TO_LB : kg;
  const suffix = unit === 'imperial' ? 'lb' : 'kg';
  const sign = value > 0 ? '+' : value < 0 ? '−' : '';
  return `${sign}${oneDecimal.format(Math.abs(value))} ${suffix}`;
}

export function weightUnitLabel(unit: UnitPreference = 'metric'): string {
  return unit === 'imperial' ? 'lb' : 'kg';
}

export function toKg(value: number, unit: UnitPreference = 'metric'): number {
  return unit === 'imperial' ? value / KG_TO_LB : value;
}

export function fromKg(kg: number, unit: UnitPreference = 'metric'): number {
  return unit === 'imperial' ? kg * KG_TO_LB : kg;
}

export function percent(value: number, digits = 0): string {
  return `${(value * 100).toFixed(digits)}%`;
}

/** "Losing" / "gaining" phrasing for a weekly rate. */
export function trendVerb(weeklyChangeKg: number): 'losing' | 'gaining' | 'holding' {
  if (weeklyChangeKg <= -0.05) return 'losing';
  if (weeklyChangeKg >= 0.05) return 'gaining';
  return 'holding';
}

export function timeOfDay(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' });
}

export function shortDate(iso: string): string {
  const date = new Date(`${iso.slice(0, 10)}T12:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function weekdayShort(iso: string): string {
  const date = new Date(`${iso.slice(0, 10)}T12:00:00`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, { weekday: 'short' });
}

export function relativeDay(iso: string, today: string): string {
  const day = iso.slice(0, 10);
  if (day === today) return 'Today';
  const todayDate = new Date(`${today}T12:00:00`);
  const yesterday = new Date(todayDate.getTime() - 86_400_000).toISOString().slice(0, 10);
  if (day === yesterday) return 'Yesterday';
  return shortDate(day);
}

export function durationLabel(minutes: number): string {
  if (minutes < 60) return `${Math.round(minutes)} min`;
  const hours = Math.floor(minutes / 60);
  const rest = Math.round(minutes % 60);
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}

export function greeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 5) return 'Still up';
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  if (hour < 22) return 'Good evening';
  return 'Good night';
}

export function firstName(fullName: string | null | undefined): string {
  if (!fullName) return '';
  return fullName.trim().split(/\s+/)[0] ?? '';
}

export function initials(fullName: string | null | undefined, email?: string | null): string {
  const source = fullName?.trim() || email?.split('@')[0] || '';
  if (!source) return '·';
  const parts = source.split(/[\s._-]+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[parts.length - 1][0]}`.toUpperCase();
}

export const MEAL_LABELS: Record<string, string> = {
  breakfast: 'Breakfast',
  lunch: 'Lunch',
  dinner: 'Dinner',
  snack: 'Snacks',
};

export const MEAL_ORDER = ['breakfast', 'lunch', 'dinner', 'snack'] as const;

/** Local YYYY-MM-DD (never UTC — that shifts the day for half the planet). */
export function localDateKey(date = new Date()): string {
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 10);
}

export function addDays(isoDate: string, days: number): string {
  const date = new Date(`${isoDate}T12:00:00`);
  date.setDate(date.getDate() + days);
  return localDateKey(date);
}

export function browserTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/**
 * Hours as a duration: 15.13 becomes "15h 08m".
 *
 * A decimal hour reads as a quantity rather than a time, which is wrong for a
 * clock that someone is watching count up.
 */
export function hoursLabel(hours: number): string {
  const safe = Number.isFinite(hours) ? Math.max(0, hours) : 0;
  const whole = Math.floor(safe);
  const minutes = Math.round((safe - whole) * 60);
  if (minutes === 60) return `${whole + 1}h 00m`;
  return `${whole}h ${String(minutes).padStart(2, '0')}m`;
}
