import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  Check,
  Database,
  Download,
  Info,
  LogOut,
  Ruler,
  Sparkles,
  Target,
  User,
} from 'lucide-react';
import { useEffect, useState } from 'react';

import {
  Badge,
  Button,
  Card,
  Chip,
  SectionHeader,
  SelectField,
  TextField,
  useToast,
} from '@/components/md';
import { useAiStatus, useMe, useSaveGoal, useUpdateProfile, useWeights } from '@/hooks/queries';
import { useAuth } from '@/hooks/authContext';
import { api } from '@/lib/api';
import { cn } from '@/lib/cn';
import { CM_TO_IN, fromKg, kcal, toKg, weightUnitLabel } from '@/lib/format';
import type { ActivityLevel, Sex, UnitPreference } from '@/lib/types';

const ACTIVITY_LEVELS: ActivityLevel[] = ['sedentary', 'light', 'moderate', 'active'];
const PACE_OPTIONS = [-0.75, -0.5, -0.25, 0, 0.25];

export function Settings() {
  const me = useMe();
  const toast = useToast();
  const { signOut } = useAuth();
  const updateProfile = useUpdateProfile();
  const saveGoal = useSaveGoal();
  const aiStatus = useAiStatus();
  const weights = useWeights(365);

  const profile = me.data?.profile;
  const goal = me.data?.goal;

  const [unit, setUnit] = useState<UnitPreference>('metric');
  const [fullName, setFullName] = useState('');
  const [sex, setSex] = useState<Sex>('male');
  const [birthDate, setBirthDate] = useState('');
  const [heightValue, setHeightValue] = useState('');
  const [goalWeight, setGoalWeight] = useState('');
  const [activity, setActivity] = useState<ActivityLevel>('sedentary');
  const [pace, setPace] = useState(-0.5);
  const [calorieOverride, setCalorieOverride] = useState('');

  // Seed the form once the profile arrives.
  useEffect(() => {
    if (!profile) return;
    const preference = profile.unit_preference ?? 'metric';
    setUnit(preference);
    setFullName(profile.full_name ?? '');
    setSex((profile.sex as Sex) ?? 'male');
    setBirthDate(profile.birth_date ?? '');
    setHeightValue(
      profile.height_cm
        ? (preference === 'imperial' ? profile.height_cm * CM_TO_IN : profile.height_cm).toFixed(1)
        : '',
    );
    setGoalWeight(
      profile.goal_weight_kg ? fromKg(profile.goal_weight_kg, preference).toFixed(1) : '',
    );
    setActivity((profile.activity_level as ActivityLevel) ?? 'sedentary');
    if (goal?.target_weekly_deficit_kcal) {
      const weekly = goal.target_weekly_deficit_kcal / 7700;
      const nearest = PACE_OPTIONS.reduce((best, option) =>
        Math.abs(option - weekly) < Math.abs(best - weekly) ? option : best,
      );
      setPace(nearest);
    }
  }, [profile, goal]);

  const heightCm = heightValue
    ? unit === 'imperial'
      ? Number(heightValue) / CM_TO_IN
      : Number(heightValue)
    : null;
  const currentWeightKg = me.data?.current_weight_kg ?? null;

  const preview = useQuery({
    queryKey: ['settings-goal-preview', heightCm, currentWeightKg, sex, activity, pace, birthDate],
    queryFn: () =>
      api.previewGoal({
        weight_kg: currentWeightKg ?? undefined,
        height_cm: heightCm ?? undefined,
        sex,
        activity_level: activity,
        weekly_change_kg: pace,
      }),
    enabled: Boolean(heightCm && currentWeightKg),
    staleTime: 30_000,
  });

  async function saveProfile() {
    try {
      await updateProfile.mutateAsync({
        full_name: fullName.trim() || null,
        sex,
        birth_date: birthDate || null,
        height_cm: heightCm ? Number(heightCm.toFixed(1)) : null,
        goal_weight_kg: goalWeight ? Number(toKg(Number(goalWeight), unit).toFixed(2)) : null,
        activity_level: activity,
        unit_preference: unit,
      });
      toast.success('Profile saved.');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not save your profile.');
    }
  }

  async function applyTargets() {
    try {
      await saveGoal.mutateAsync({
        weekly_change_kg: pace,
        activity_level: activity,
        height_cm: heightCm ?? undefined,
        sex,
        daily_calorie_target: calorieOverride ? Number(calorieOverride) : undefined,
      });
      toast.success('Targets updated from today.');
      setCalorieOverride('');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not update your targets.');
    }
  }

  function exportData() {
    const payload = {
      exported_at: new Date().toISOString(),
      profile,
      goal,
      weight_logs: weights.data?.logs ?? [],
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `pulse-export-${new Date().toISOString().slice(0, 10)}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-headline-sm font-medium tracking-tight">Settings</h1>
        <p className="text-label-md text-md-on-surface-variant">{me.data?.user.email}</p>
      </div>

      {/* Profile */}
      <Card tone="container">
        <SectionHeader
          title="About you"
          subtitle="These values feed the metabolic estimate."
          icon={<User size={18} />}
        />

        <div className="mt-5 grid gap-4 sm:grid-cols-2">
          <TextField
            label="Name"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
          />
          <SelectField label="Sex" value={sex} onChange={(event) => setSex(event.target.value as Sex)}>
            <option value="male">Male</option>
            <option value="female">Female</option>
            <option value="other">Prefer not to say</option>
          </SelectField>
          <TextField
            label="Date of birth"
            type="date"
            value={birthDate}
            max={new Date().toISOString().slice(0, 10)}
            onChange={(event) => setBirthDate(event.target.value)}
          />
          <TextField
            label={`Height (${unit === 'imperial' ? 'in' : 'cm'})`}
            type="number"
            step="0.1"
            leading={<Ruler size={18} />}
            suffix={unit === 'imperial' ? 'in' : 'cm'}
            value={heightValue}
            onChange={(event) => setHeightValue(event.target.value)}
          />
          <TextField
            label={`Goal weight (${weightUnitLabel(unit)})`}
            type="number"
            step="0.1"
            leading={<Target size={18} />}
            suffix={weightUnitLabel(unit)}
            value={goalWeight}
            onChange={(event) => setGoalWeight(event.target.value)}
          />
          <div>
            <p className="mb-2 px-1 text-label-md text-md-on-surface-variant">Units</p>
            <div className="flex gap-2">
              {(['metric', 'imperial'] as const).map((value) => (
                <Chip key={value} selected={unit === value} onClick={() => setUnit(value)}>
                  {value === 'metric' ? 'kg / cm' : 'lb / in'}
                </Chip>
              ))}
            </div>
          </div>
        </div>

        <div className="mt-5 flex justify-end">
          <Button loading={updateProfile.isPending} icon={<Check size={18} />} onClick={() => void saveProfile()}>
            Save profile
          </Button>
        </div>
      </Card>

      {/* Targets */}
      <Card tone="container">
        <SectionHeader
          title="Goal & deficit"
          subtitle="Saving creates a new goal effective from today; past days keep their old target."
          icon={<Target size={18} />}
        />

        <div className="mt-5">
          <p className="mb-2 text-label-md text-md-on-surface-variant">Activity level</p>
          <div className="flex flex-wrap gap-2">
            {ACTIVITY_LEVELS.map((level) => (
              <Chip key={level} selected={activity === level} onClick={() => setActivity(level)}>
                <span className="capitalize">{level}</span>
              </Chip>
            ))}
          </div>
          <p className="mt-2 flex gap-2 px-1 text-label-sm text-md-on-surface-variant">
            <Info size={14} className="mt-0.5 shrink-0" />
            Choose sedentary if you log workouts individually — otherwise exercise is counted twice.
          </p>
        </div>

        <div className="mt-5">
          <p className="mb-2 text-label-md text-md-on-surface-variant">Weekly pace</p>
          <div className="flex flex-wrap gap-2">
            {PACE_OPTIONS.map((option) => (
              <Chip key={option} selected={pace === option} onClick={() => setPace(option)}>
                {option === 0 ? 'Maintain' : `${option > 0 ? '+' : ''}${option} kg/wk`}
              </Chip>
            ))}
          </div>
        </div>

        {preview.data && (
          <div className="mt-5 grid gap-3 sm:grid-cols-3">
            <PreviewStat label="New daily target" value={kcal(preview.data.daily_calorie_target)} accent />
            <PreviewStat label="Maintenance" value={kcal(preview.data.maintenance_calories)} />
            <PreviewStat label="BMR" value={kcal(preview.data.bmr)} />
          </div>
        )}

        {preview.data?.warnings.map((warning) => (
          <p
            key={warning}
            className="mt-3 rounded-sm bg-md-warning-container px-4 py-2.5 text-label-md text-md-on-warning-container"
          >
            {warning}
          </p>
        ))}

        <TextField
          containerClassName="mt-5"
          label="Or set the daily calorie target yourself"
          type="number"
          suffix="kcal"
          min={1000}
          max={6000}
          value={calorieOverride}
          onChange={(event) => setCalorieOverride(event.target.value)}
          hint={
            goal?.daily_calorie_target
              ? `Currently ${kcal(goal.daily_calorie_target)} kcal · maintenance ${kcal(goal.maintenance_calories)}`
              : undefined
          }
        />

        <div className="mt-5 flex justify-end">
          <Button loading={saveGoal.isPending} icon={<Check size={18} />} onClick={() => void applyTargets()}>
            Apply targets
          </Button>
        </div>
      </Card>

      {/* Integrations */}
      <Card tone="container">
        <SectionHeader
          title="Integrations"
          subtitle="Which services this deployment is wired up to."
          icon={<Sparkles size={18} />}
        />
        <ul className="mt-5 space-y-2">
          <IntegrationRow
            label="Supabase (database, auth, photo storage)"
            ok={me.data?.integrations.supabase ?? false}
            detail="Required"
          />
          <IntegrationRow
            label={`Gemini (photo recognition, coach, recaps)${aiStatus.data?.model ? ` · ${aiStatus.data.model}` : ''}`}
            ok={aiStatus.data?.gemini_configured ?? me.data?.integrations.gemini ?? false}
            detail="aistudio.google.com/apikey"
          />
          <IntegrationRow
            label="USDA FoodData Central (nutrition lookup)"
            ok={me.data?.integrations.usda ?? false}
            detail={aiStatus.data?.usda_key_is_demo ? 'Using DEMO_KEY — rate limited' : 'Keyed'}
            warn={aiStatus.data?.usda_key_is_demo}
          />
          <IntegrationRow
            label="Upstash Redis (cache & rate limits)"
            ok={me.data?.integrations.redis ?? false}
            detail="Optional — falls back to in-process cache"
            optional
          />
        </ul>

        {aiStatus.data && !aiStatus.data.model_available && aiStatus.data.available_models.length > 0 && (
          <p className="mt-4 rounded-sm bg-md-warning-container px-4 py-3 text-label-md text-md-on-warning-container">
            The configured model <strong>{aiStatus.data.model}</strong> is not available to your key.
            Try one of: {aiStatus.data.available_models.slice(0, 4).join(', ')} — set GEMINI_MODEL in
            the backend environment.
          </p>
        )}
      </Card>

      {/* Data */}
      <Card tone="container">
        <SectionHeader
          title="Your data"
          subtitle="Row-level security means only your account can read these rows."
          icon={<Database size={18} />}
        />
        <div className="mt-5 flex flex-wrap gap-3">
          <Button variant="outlined" icon={<Download size={17} />} onClick={exportData}>
            Export as JSON
          </Button>
          <Button variant="text" icon={<LogOut size={17} />} onClick={() => void signOut()}>
            Sign out
          </Button>
        </div>
        <p className="mt-3 text-label-sm text-md-on-surface-variant">
          <Activity size={13} className="mr-1 inline" />
          {weights.data?.count ?? 0} weigh-ins recorded
          {me.data?.timezone && ` · timezone ${me.data.timezone}`}
        </p>
      </Card>
    </div>
  );
}

function PreviewStat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div
      className={cn(
        'rounded-sm px-4 py-3',
        accent ? 'bg-md-primary-container text-md-on-primary-container' : 'bg-md-surface-container-low',
      )}
    >
      <p className="text-label-sm opacity-80">{label}</p>
      <p className="tabular mt-0.5 text-title-lg font-medium">
        {value}
        <span className="ml-1 text-label-md font-normal opacity-80">kcal</span>
      </p>
    </div>
  );
}

function IntegrationRow({
  label,
  ok,
  detail,
  optional,
  warn,
}: {
  label: string;
  ok: boolean;
  detail?: string;
  optional?: boolean;
  warn?: boolean;
}) {
  const tone = ok ? (warn ? 'warning' : 'success') : optional ? 'neutral' : 'error';
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 rounded-sm bg-md-surface-container-low px-4 py-3">
      <span className="min-w-0 text-body-sm">{label}</span>
      <span className="flex items-center gap-2">
        {detail && <span className="text-label-sm text-md-on-surface-variant">{detail}</span>}
        <Badge tone={tone}>{ok ? 'connected' : optional ? 'not set' : 'missing'}</Badge>
      </span>
    </li>
  );
}
