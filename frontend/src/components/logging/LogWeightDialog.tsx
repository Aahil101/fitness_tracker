import { Flame, Scale, TrendingDown, TrendingUp } from 'lucide-react';
import { useEffect, useState } from 'react';

import { Badge, Button, Sheet, TextAreaField, TextField, useToast } from '@/components/md';
import { useLogWeight, useWeighInStreak } from '@/hooks/queries';
import { fromKg, localDateKey, toKg, weightDelta, weightUnitLabel } from '@/lib/format';
import type { UnitPreference } from '@/lib/types';

interface LogWeightDialogProps {
  open: boolean;
  onClose: () => void;
  unit?: UnitPreference;
  currentWeightKg?: number | null;
}

/**
 * Deliberately one field. Weighing in should be a two-second interaction, so the
 * input is pre-filled with the last known weight and the note is optional and
 * collapsed until asked for.
 */
export function LogWeightDialog({
  open,
  onClose,
  unit = 'metric',
  currentWeightKg,
}: LogWeightDialogProps) {
  const toast = useToast();
  const logWeight = useLogWeight();
  const streak = useWeighInStreak();

  const [value, setValue] = useState('');
  const [note, setNote] = useState('');
  const [showNote, setShowNote] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Seed with the previous weigh-in: most days it barely moves, so the common
  // case becomes "adjust by 0.2 and hit save".
  useEffect(() => {
    if (!open) return;
    setError(null);
    setNote('');
    setShowNote(false);
    setValue(currentWeightKg ? fromKg(currentWeightKg, unit).toFixed(1) : '');
  }, [open, currentWeightKg, unit]);

  const parsed = Number(value);
  const validRange = unit === 'imperial' ? [55, 770] : [25, 350];
  const isValid = Boolean(value) && !Number.isNaN(parsed) && parsed >= validRange[0] && parsed <= validRange[1];
  const deltaKg = isValid && currentWeightKg ? toKg(parsed, unit) - currentWeightKg : null;

  async function save() {
    if (!isValid) {
      setError(`Enter a weight between ${validRange[0]} and ${validRange[1]} ${weightUnitLabel(unit)}.`);
      return;
    }
    try {
      const result = await logWeight.mutateAsync({
        weight_kg: Number(toKg(parsed, unit).toFixed(2)),
        logged_at: localDateKey(),
        note: note.trim() || undefined,
      });
      toast.success(
        result.change_since_previous_kg
          ? `Logged. ${weightDelta(result.change_since_previous_kg, unit)} since last weigh-in.`
          : 'Weight logged.',
      );
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Could not save your weight.');
    }
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      variant="dialog"
      size="sm"
      title="Log today's weight"
      description={`Weigh in at the same time each day — first thing, before eating, is the most consistent.`}
      footer={
        <>
          <Button variant="text" onClick={onClose}>
            Cancel
          </Button>
          <Button loading={logWeight.isPending} onClick={() => void save()} disabled={!isValid}>
            Save weight
          </Button>
        </>
      }
    >
      <div className="space-y-4 pb-2">
        <TextField
          label={`Weight (${weightUnitLabel(unit)})`}
          type="number"
          inputMode="decimal"
          step="0.1"
          autoFocus
          leading={<Scale size={18} />}
          suffix={weightUnitLabel(unit)}
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            setError(null);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && isValid) void save();
          }}
          error={error}
        />

        <div className="flex flex-wrap items-center gap-2">
          {deltaKg !== null && Math.abs(deltaKg) >= 0.05 && (
            <Badge
              tone={deltaKg < 0 ? 'success' : 'warning'}
              icon={deltaKg < 0 ? <TrendingDown size={13} /> : <TrendingUp size={13} />}
            >
              {weightDelta(deltaKg, unit)} vs last entry
            </Badge>
          )}
          {streak.data && streak.data.streak > 0 && (
            <Badge tone="info" icon={<Flame size={13} />}>
              {streak.data.streak}-day weigh-in streak
            </Badge>
          )}
        </div>

        {showNote ? (
          <TextAreaField
            label="Note (optional)"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Slept badly, salty dinner, travelling…"
            rows={2}
          />
        ) : (
          <Button variant="text" size="sm" onClick={() => setShowNote(true)}>
            Add a note
          </Button>
        )}

        <p className="text-label-sm text-md-on-surface-variant">
          Day-to-day swings are mostly water and food volume. The projection uses the trend, not
          any single reading.
        </p>
      </div>
    </Sheet>
  );
}
