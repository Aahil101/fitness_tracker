import { useQuery } from '@tanstack/react-query';
import { AnimatePresence, motion } from 'framer-motion';
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Flame,
  Info,
  Ruler,
  Scale,
  Target,
  User,
} from 'lucide-react';
import { useMemo, useState } from 'react';

import { Badge, Blobs, Button, Card, Chip, SelectField, TextField, useToast } from '@/components/md';
import { useCompleteOnboarding } from '@/hooks/queries';
import { bmiFor, healthyWeightRange } from '@/lib/bmi';
import { api } from '@/lib/api';
import { cn } from '@/lib/cn';
import {
  browserTimezone,
  CM_TO_IN,
  fromKg,
  kcal,
  toKg,
  weightUnitLabel,
} from '@/lib/format';
import type { ActivityLevel, Sex, UnitPreference } from '@/lib/types';

const ACTIVITY_OPTIONS: { value: ActivityLevel; label: string; hint: string }[] = [
  { value: 'sedentary', label: 'Sedentary', hint: 'Desk job, little deliberate movement' },
  { value: 'light', label: 'Light', hint: 'Light exercise 1–3 days a week' },
  { value: 'moderate', label: 'Moderate', hint: 'Moderate exercise 3–5 days a week' },
  { value: 'active', label: 'Active', hint: 'Hard exercise 6–7 days a week' },
];

const PACE_OPTIONS = [
  { value: -0.75, label: 'Fast', detail: '0.75 kg / week' },
  { value: -0.5, label: 'Steady', detail: '0.5 kg / week' },
  { value: -0.25, label: 'Gentle', detail: '0.25 kg / week' },
  { value: 0, label: 'Maintain', detail: 'Hold weight' },
  { value: 0.25, label: 'Lean gain', detail: '+0.25 kg / week' },
];

const STEPS = ['About you', 'Your weight', 'Your pace'] as const;

const MONTHS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
] as const;

/** Youngest and oldest ages the metabolic equation is validated for. */
const MIN_AGE = 13;
const MAX_AGE = 100;

/** Calendar length of a month, leap-year aware once a year is chosen. */
function daysInMonth(year: number | null, month: number | null): number {
  if (!month) return 31;
  return new Date(year ?? 2000, month, 0).getDate();
}

/**
 * First-run setup. Three short steps because the forecasting maths genuinely
 * needs height, age and sex — Mifflin-St Jeor cannot run without them, and
 * guessing would quietly bias every projection afterwards.
 */
export function Onboarding() {
  const toast = useToast();
  const onboard = useCompleteOnboarding();

  const [step, setStep] = useState(0);
  const [unit, setUnit] = useState<UnitPreference>('metric');
  const [fullName, setFullName] = useState('');
  const [sex, setSex] = useState<Sex>('male');
  // Split into three selects: a native date input makes people click back
  // through decades of months to reach a birth year.
  const [birthDay, setBirthDay] = useState('');
  const [birthMonth, setBirthMonth] = useState('');
  const [birthYear, setBirthYear] = useState('');
  const [heightValue, setHeightValue] = useState('');
  const [currentWeight, setCurrentWeight] = useState('');
  const [goalWeight, setGoalWeight] = useState('');
  const [activity, setActivity] = useState<ActivityLevel>('sedentary');
  const [pace, setPace] = useState(-0.5);
  const [error, setError] = useState<string | null>(null);

  // Year range runs newest-first so the common case is a short scroll.
  const years = useMemo(() => {
    const thisYear = new Date().getFullYear();
    return Array.from({ length: MAX_AGE - MIN_AGE + 1 }, (_, i) => thisYear - MIN_AGE - i);
  }, []);

  const dayCount = daysInMonth(Number(birthYear) || null, Number(birthMonth) || null);
  const days = useMemo(
    () => Array.from({ length: dayCount }, (_, i) => i + 1),
    [dayCount],
  );

  /** ISO date the API expects, or '' until all three parts are chosen. */
  const birthDate = useMemo(() => {
    if (!birthDay || !birthMonth || !birthYear) return '';
    return `${birthYear}-${birthMonth.padStart(2, '0')}-${birthDay.padStart(2, '0')}`;
  }, [birthDay, birthMonth, birthYear]);

  /** Keep 31 Feb from ever existing: clamp the day when the month/year shrinks. */
  function clampDay(nextMonth: string, nextYear: string) {
    const limit = daysInMonth(Number(nextYear) || null, Number(nextMonth) || null);
    if (birthDay && Number(birthDay) > limit) setBirthDay(String(limit));
  }

  const heightCm = useMemo(() => {
    const raw = Number(heightValue);
    if (!raw || Number.isNaN(raw)) return null;
    return unit === 'imperial' ? raw / CM_TO_IN : raw;
  }, [heightValue, unit]);

  const currentKg = useMemo(() => {
    const raw = Number(currentWeight);
    return raw && !Number.isNaN(raw) ? toKg(raw, unit) : null;
  }, [currentWeight, unit]);

  const goalKg = useMemo(() => {
    const raw = Number(goalWeight);
    return raw && !Number.isNaN(raw) ? toKg(raw, unit) : null;
  }, [goalWeight, unit]);

  /** Healthy band from the height entered in step 1, shown while picking a goal. */
  const healthyRange = useMemo(() => healthyWeightRange(heightCm), [heightCm]);
  const currentBmi = useMemo(() => bmiFor(currentKg, heightCm), [currentKg, heightCm]);
  const goalOutsideRange = Boolean(
    goalKg && healthyRange && (goalKg < healthyRange.minKg || goalKg > healthyRange.maxKg),
  );

  const age = useMemo(() => {
    if (!birthDate) return null;
    const born = new Date(birthDate);
    if (Number.isNaN(born.getTime())) return null;
    const now = new Date();
    let years = now.getFullYear() - born.getFullYear();
    if (
      now.getMonth() < born.getMonth() ||
      (now.getMonth() === born.getMonth() && now.getDate() < born.getDate())
    ) {
      years -= 1;
    }
    return years;
  }, [birthDate]);

  // Live target preview straight from the backend, so what the user sees during
  // setup is exactly what will be saved.
  const canPreview = Boolean(heightCm && currentKg && step === 2);
  const preview = useQuery({
    queryKey: ['goal-preview', heightCm, currentKg, age, sex, activity, pace],
    queryFn: () =>
      api.previewGoal({
        weight_kg: currentKg!,
        height_cm: heightCm!,
        age_years: age ?? undefined,
        sex,
        activity_level: activity,
        weekly_change_kg: pace,
      }),
    enabled: canPreview,
    staleTime: 60_000,
  });

  function validateStep(index: number): string | null {
    if (index === 0) {
      if (!fullName.trim()) return 'Add your name so the app can greet you.';
      if (!birthDate) return 'Your date of birth is needed for the metabolic estimate.';
      if (age !== null && (age < 13 || age > 100)) return 'Enter a date of birth between 13 and 100 years ago.';
      if (!heightCm || heightCm < 90 || heightCm > 260) return 'Enter a realistic height.';
    }
    if (index === 1) {
      if (!currentKg || currentKg < 25 || currentKg > 350) return 'Enter your current weight.';
      if (goalKg && (goalKg < 25 || goalKg > 350)) return 'That goal weight looks off.';
    }
    return null;
  }

  function next() {
    const problem = validateStep(step);
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    setStep((value) => Math.min(STEPS.length - 1, value + 1));
  }

  async function submit() {
    for (let index = 0; index < STEPS.length; index += 1) {
      const problem = validateStep(index);
      if (problem) {
        setStep(index);
        setError(problem);
        return;
      }
    }

    try {
      await onboard.mutateAsync({
        full_name: fullName.trim(),
        sex,
        birth_date: birthDate,
        height_cm: Number(heightCm!.toFixed(1)),
        goal_weight_kg: goalKg ? Number(goalKg.toFixed(2)) : undefined,
        activity_level: activity,
        unit_preference: unit,
        timezone: browserTimezone(),
        current_weight_kg: Number(currentKg!.toFixed(2)),
        weekly_change_kg: pace,
      });
      toast.success('You are all set. Log your first meal.');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save your setup.');
    }
  }

  return (
    <div className="relative min-h-dvh bg-md-surface px-5 py-10">
      <Blobs variant="hero" />

      <div className="relative mx-auto max-w-xl">
        <div className="flex items-center gap-3">
          <span className="grid h-11 w-11 place-items-center rounded-md bg-md-primary text-md-on-primary shadow-e2">
            <Flame size={22} />
          </span>
          <div>
            <h1 className="text-title-lg font-medium tracking-tight">Set up your plan</h1>
            <p className="text-label-md text-md-on-surface-variant">
              Step {step + 1} of {STEPS.length} · {STEPS[step]}
            </p>
          </div>
        </div>

        <Card tone="container" className="mt-6 rounded-2xl">
          <AnimatePresence mode="wait">
            <motion.div
              key={step}
              initial={{ opacity: 0, x: 24 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -24 }}
              transition={{ duration: 0.3, ease: [0.2, 0, 0, 1] }}
              className="space-y-4"
            >
              {step === 0 && (
                <>
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <p className="text-body-sm text-md-on-surface-variant">
                      Used to estimate your resting metabolism.
                    </p>
                    <div className="flex gap-2">
                      {(['metric', 'imperial'] as const).map((value) => (
                        <Chip
                          key={value}
                          selected={unit === value}
                          onClick={() => setUnit(value)}
                        >
                          {value === 'metric' ? 'kg / cm' : 'lb / in'}
                        </Chip>
                      ))}
                    </div>
                  </div>

                  <TextField
                    label="Your name"
                    leading={<User size={18} />}
                    value={fullName}
                    onChange={(event) => setFullName(event.target.value)}
                    autoComplete="name"
                    required
                  />

                  <SelectField
                    label="Sex (for the metabolic equation)"
                    value={sex}
                    onChange={(event) => setSex(event.target.value as Sex)}
                  >
                    <option value="male">Male</option>
                    <option value="female">Female</option>
                    <option value="other">Prefer not to say</option>
                  </SelectField>

                  <div>
                    <p className="px-1 text-label-md text-md-on-surface-variant">Date of birth</p>
                    <div className="mt-1.5 grid grid-cols-[1fr_1.4fr_1fr] gap-2">
                      <SelectField
                        label="Day"
                        value={birthDay}
                        onChange={(event) => setBirthDay(event.target.value)}
                      >
                        <option value="">–</option>
                        {days.map((day) => (
                          <option key={day} value={day}>
                            {day}
                          </option>
                        ))}
                      </SelectField>

                      <SelectField
                        label="Month"
                        value={birthMonth}
                        onChange={(event) => {
                          setBirthMonth(event.target.value);
                          clampDay(event.target.value, birthYear);
                        }}
                      >
                        <option value="">–</option>
                        {MONTHS.map((month, index) => (
                          <option key={month} value={index + 1}>
                            {month}
                          </option>
                        ))}
                      </SelectField>

                      <SelectField
                        label="Year"
                        value={birthYear}
                        onChange={(event) => {
                          setBirthYear(event.target.value);
                          clampDay(birthMonth, event.target.value);
                        }}
                      >
                        <option value="">–</option>
                        {years.map((year) => (
                          <option key={year} value={year}>
                            {year}
                          </option>
                        ))}
                      </SelectField>
                    </div>
                    {age !== null && (
                      <p className="mt-1.5 px-1 text-label-sm text-md-on-surface-variant">
                        {age} years old
                      </p>
                    )}
                  </div>

                  <TextField
                    label={`Height (${unit === 'imperial' ? 'inches' : 'cm'})`}
                    type="number"
                    inputMode="decimal"
                    step="0.1"
                    leading={<Ruler size={18} />}
                    value={heightValue}
                    onChange={(event) => setHeightValue(event.target.value)}
                    suffix={unit === 'imperial' ? 'in' : 'cm'}
                    hint={
                      unit === 'imperial' && heightCm
                        ? `${Math.floor(Number(heightValue) / 12)}′ ${Math.round(Number(heightValue) % 12)}″ · ${heightCm.toFixed(0)} cm`
                        : undefined
                    }
                    required
                  />
                </>
              )}

              {step === 1 && (
                <>
                  <p className="text-body-sm text-md-on-surface-variant">
                    Today&apos;s weight becomes your first data point. Log it daily — the forecast
                    corrects itself against the scale.
                  </p>

                  <TextField
                    label={`Current weight (${weightUnitLabel(unit)})`}
                    type="number"
                    inputMode="decimal"
                    step="0.1"
                    leading={<Scale size={18} />}
                    value={currentWeight}
                    onChange={(event) => setCurrentWeight(event.target.value)}
                    suffix={weightUnitLabel(unit)}
                    required
                  />

                  <TextField
                    label={`Goal weight (${weightUnitLabel(unit)}) — optional`}
                    type="number"
                    inputMode="decimal"
                    step="0.1"
                    leading={<Target size={18} />}
                    value={goalWeight}
                    onChange={(event) => setGoalWeight(event.target.value)}
                    suffix={weightUnitLabel(unit)}
                    hint="Leave blank if you just want to track."
                  />

                  {healthyRange && (
                    <div className="rounded-sm bg-md-surface-container-low px-4 py-3">
                      <p className="font-prose text-body-sm text-md-on-surface">
                        Based on your height, a BMI in the healthy range puts your optimal
                        weight at{' '}
                        <span className="font-medium">
                          {fromKg(healthyRange.minKg, unit).toFixed(1)}
                          {' ~ '}
                          {fromKg(healthyRange.maxKg, unit).toFixed(1)} {weightUnitLabel(unit)}
                        </span>
                        {currentBmi !== null && <> — you are at {currentBmi.toFixed(1)} now.</>}
                      </p>
                      {goalOutsideRange && (
                        <p className="mt-1.5 font-prose text-label-sm text-md-on-surface-variant">
                          Your goal of {fromKg(goalKg!, unit).toFixed(1)}{' '}
                          {weightUnitLabel(unit)} sits{' '}
                          {goalKg! < healthyRange.minKg ? 'below' : 'above'} that band.
                        </p>
                      )}
                      <p className="mt-1.5 font-prose text-label-sm text-md-on-surface-variant/85">
                        BMI is only mass over height — it cannot tell muscle from fat, so treat
                        this as a reference rather than a target.
                      </p>
                    </div>
                  )}

                  {currentKg && goalKg && (
                    <div className="rounded-sm bg-md-secondary-container px-4 py-3 text-body-sm text-md-on-secondary-container">
                      That is{' '}
                      <span className="font-medium">
                        {Math.abs(fromKg(currentKg - goalKg, unit)).toFixed(1)}{' '}
                        {weightUnitLabel(unit)}
                      </span>{' '}
                      {currentKg > goalKg ? 'to lose' : 'to gain'}.
                    </div>
                  )}
                </>
              )}

              {step === 2 && (
                <>
                  <div>
                    <p className="text-label-lg font-medium">How active are you day to day?</p>
                    <div className="mt-3 grid gap-2">
                      {ACTIVITY_OPTIONS.map((option) => (
                        <button
                          key={option.value}
                          type="button"
                          onClick={() => setActivity(option.value)}
                          aria-pressed={activity === option.value}
                          className={cn(
                            'flex items-center justify-between gap-3 rounded-md px-4 py-3 text-left',
                            'transition-all duration-medium ease-md active:scale-[0.99]',
                            activity === option.value
                              ? 'bg-md-secondary-container text-md-on-secondary-container shadow-e1'
                              : 'bg-md-surface-container-low text-md-on-surface hover:bg-md-on-surface/[0.06]',
                          )}
                        >
                          <span>
                            <span className="block text-label-lg font-medium">{option.label}</span>
                            <span className="block text-label-sm opacity-80">{option.hint}</span>
                          </span>
                          {activity === option.value && <Check size={18} />}
                        </button>
                      ))}
                    </div>
                    <p className="mt-2 flex gap-2 px-1 text-label-sm text-md-on-surface-variant">
                      <Info size={14} className="mt-0.5 shrink-0" />
                      Pick <strong className="font-medium">Sedentary</strong> if you plan to log
                      workouts individually — otherwise exercise gets counted twice.
                    </p>
                  </div>

                  <div>
                    <p className="text-label-lg font-medium">Target pace</p>
                    <div className="no-scrollbar mt-3 flex gap-2 overflow-x-auto pb-1">
                      {PACE_OPTIONS.map((option) => (
                        <Chip
                          key={option.value}
                          selected={pace === option.value}
                          onClick={() => setPace(option.value)}
                        >
                          {option.label}
                        </Chip>
                      ))}
                    </div>
                    <p className="mt-2 px-1 text-label-sm text-md-on-surface-variant">
                      {PACE_OPTIONS.find((option) => option.value === pace)?.detail}
                    </p>
                  </div>

                  {/* Live preview of what will be saved */}
                  <Card tone="low" className="rounded-md">
                    {preview.isLoading && (
                      <p className="text-body-sm text-md-on-surface-variant">
                        Calculating your targets…
                      </p>
                    )}
                    {preview.data && (
                      <div className="space-y-3">
                        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
                          <div>
                            <p className="text-label-sm text-md-on-surface-variant">Daily target</p>
                            <p className="tabular text-headline-sm font-medium text-md-primary">
                              {kcal(preview.data.daily_calorie_target)}
                              <span className="ml-1 text-label-md font-normal text-md-on-surface-variant">
                                kcal
                              </span>
                            </p>
                          </div>
                          <div>
                            <p className="text-label-sm text-md-on-surface-variant">Maintenance</p>
                            <p className="tabular text-title-lg font-medium">
                              {kcal(preview.data.maintenance_calories)}
                            </p>
                          </div>
                          <div>
                            <p className="text-label-sm text-md-on-surface-variant">BMR</p>
                            <p className="tabular text-title-lg font-medium">
                              {kcal(preview.data.bmr)}
                            </p>
                          </div>
                        </div>

                        <div className="flex flex-wrap gap-2">
                          <Badge tone="primary">
                            Protein {Math.round(preview.data.macros.protein_g)} g
                          </Badge>
                          <Badge tone="info">
                            Carbs {Math.round(preview.data.macros.carb_g)} g
                          </Badge>
                          <Badge tone="warning">Fat {Math.round(preview.data.macros.fat_g)} g</Badge>
                          <Badge>Fibre {Math.round(preview.data.macros.fiber_g)} g</Badge>
                        </div>

                        {preview.data.warnings.map((warning) => (
                          <p
                            key={warning}
                            className="rounded-sm bg-md-warning-container px-3 py-2 text-label-md text-md-on-warning-container"
                          >
                            {warning}
                          </p>
                        ))}
                      </div>
                    )}
                    {preview.isError && (
                      <p className="text-body-sm text-md-error">
                        Could not reach the API to calculate targets. You can still finish setup.
                      </p>
                    )}
                  </Card>
                </>
              )}
            </motion.div>
          </AnimatePresence>

          {error && (
            <p
              role="alert"
              className="mt-4 rounded-sm bg-md-error-container px-4 py-3 text-body-sm text-md-on-error-container"
            >
              {error}
            </p>
          )}

          <div className="mt-6 flex items-center justify-between gap-3">
            <Button
              variant="text"
              icon={<ArrowLeft size={18} />}
              disabled={step === 0}
              onClick={() => {
                setError(null);
                setStep((value) => Math.max(0, value - 1));
              }}
            >
              Back
            </Button>

            {step < STEPS.length - 1 ? (
              <Button trailingIcon={<ArrowRight size={18} />} onClick={next}>
                Continue
              </Button>
            ) : (
              <Button
                loading={onboard.isPending}
                trailingIcon={<Check size={18} />}
                onClick={() => void submit()}
              >
                Start tracking
              </Button>
            )}
          </div>
        </Card>
      </div>
    </div>
  );
}
