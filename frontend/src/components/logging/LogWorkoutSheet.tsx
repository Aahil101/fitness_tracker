import { useQuery } from '@tanstack/react-query';
import { Check, Dumbbell, Info, Timer } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';

import {
  Badge,
  Button,
  Card,
  Chip,
  SelectField,
  Sheet,
  TextAreaField,
  TextField,
  useToast,
} from '@/components/md';
import { useCreateWorkout, useMetCatalog } from '@/hooks/queries';
import { api } from '@/lib/api';
import { durationLabel, kcal } from '@/lib/format';
import type { Intensity } from '@/lib/types';

const DURATION_PRESETS = [15, 20, 30, 45, 60, 90];
const INTENSITIES: { value: Intensity; label: string }[] = [
  { value: 'light', label: 'Light' },
  { value: 'moderate', label: 'Moderate' },
  { value: 'vigorous', label: 'Vigorous' },
];

/**
 * Workout entry. The MET table suggests the burn from activity × body mass ×
 * duration; the field stays editable because a watch reading beats a table.
 */
export function LogWorkoutSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const toast = useToast();
  const catalog = useMetCatalog();
  const createWorkout = useCreateWorkout();

  const [activity, setActivity] = useState('walking');
  const [duration, setDuration] = useState(30);
  const [intensity, setIntensity] = useState<Intensity>('moderate');
  const [override, setOverride] = useState('');
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setOverride('');
    setNotes('');
  }, [open]);

  // Server-side estimate so the number saved matches the number shown.
  const estimate = useQuery({
    queryKey: ['burn-estimate', activity, duration, intensity],
    queryFn: () =>
      api.estimateBurn({ activity_type: activity, duration_min: duration, intensity }),
    enabled: open && duration > 0,
    staleTime: 60_000,
  });

  const grouped = useMemo(() => {
    const groups = new Map<string, { key: string; label: string }[]>();
    for (const item of catalog.data?.activities ?? []) {
      const list = groups.get(item.category) ?? [];
      list.push({ key: item.key, label: item.label });
      groups.set(item.category, list);
    }
    return [...groups.entries()];
  }, [catalog.data]);

  const suggested = estimate.data?.calories_burned ?? null;
  const finalCalories = override ? Number(override) : suggested;

  async function save() {
    if (!duration || duration <= 0) {
      setError('How long did you train?');
      return;
    }
    try {
      await createWorkout.mutateAsync({
        activity_type: activity,
        duration_min: duration,
        intensity,
        notes: notes.trim() || undefined,
        // Omitting calories lets the backend estimate and tag it met_estimated.
        calories_burned: override ? Number(override) : undefined,
      });
      toast.success('Workout logged.');
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save the workout.');
    }
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Log a workout"
      description="Burn is estimated from the Compendium of Physical Activities using your latest weight."
      footer={
        <>
          <Button variant="text" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={createWorkout.isPending} icon={<Check size={18} />} onClick={() => void save()}>
            Save workout
          </Button>
        </>
      }
    >
      <div className="space-y-4 pb-2">
        <SelectField
          label="Activity"
          leading={<Dumbbell size={18} />}
          value={activity}
          onChange={(event) => setActivity(event.target.value)}
        >
          {grouped.map(([category, items]) => (
            <optgroup key={category} label={category}>
              {items.map((item) => (
                <option key={item.key} value={item.key}>
                  {item.label}
                </option>
              ))}
            </optgroup>
          ))}
        </SelectField>

        <TextField
          label="Duration"
          type="number"
          inputMode="numeric"
          min={1}
          max={1440}
          suffix="min"
          leading={<Timer size={18} />}
          value={String(duration)}
          onChange={(event) => setDuration(Math.max(0, Number(event.target.value) || 0))}
        />

        <div className="no-scrollbar -mx-1 flex gap-2 overflow-x-auto px-1">
          {DURATION_PRESETS.map((preset) => (
            <Chip key={preset} selected={duration === preset} onClick={() => setDuration(preset)}>
              {durationLabel(preset)}
            </Chip>
          ))}
        </div>

        <div>
          <p className="mb-2 px-1 text-label-md text-md-on-surface-variant">Intensity</p>
          <div className="flex gap-2">
            {INTENSITIES.map((option) => (
              <Chip
                key={option.value}
                selected={intensity === option.value}
                onClick={() => setIntensity(option.value)}
              >
                {option.label}
              </Chip>
            ))}
          </div>
        </div>

        <Card tone="low" className="rounded-md">
          <div className="flex items-baseline justify-between gap-3">
            <div>
              <p className="text-label-sm text-md-on-surface-variant">Estimated burn</p>
              <p className="tabular text-headline-sm font-medium text-md-primary">
                {suggested === null ? '—' : kcal(finalCalories)}
                <span className="ml-1 text-label-md font-normal text-md-on-surface-variant">kcal</span>
              </p>
            </div>
            {estimate.data && (
              <Badge tone="info">
                MET {estimate.data.met} · {estimate.data.weight_kg_used} kg
              </Badge>
            )}
          </div>

          <TextField
            containerClassName="mt-3"
            label="Override (optional)"
            type="number"
            inputMode="decimal"
            min={0}
            suffix="kcal"
            value={override}
            onChange={(event) => setOverride(event.target.value)}
            hint="Got a number from a watch or machine? Use it — it beats a table."
          />
        </Card>

        <TextAreaField
          label="Notes (optional)"
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          placeholder="5×5 squats, felt strong"
          rows={2}
        />

        <p className="flex gap-2 px-1 text-label-sm text-md-on-surface-variant">
          <Info size={14} className="mt-0.5 shrink-0" />
          MET values describe total energy use, which overlaps with the activity multiplier in your
          goal. If you log every workout, set your activity level to sedentary in Settings.
        </p>

        {error && (
          <p role="alert" className="rounded-sm bg-md-error-container px-4 py-3 text-body-sm text-md-on-error-container">
            {error}
          </p>
        )}
      </div>
    </Sheet>
  );
}
