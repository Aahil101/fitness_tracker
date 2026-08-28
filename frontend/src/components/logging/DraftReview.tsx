import { Check, Trash2 } from 'lucide-react';
import { useMemo } from 'react';

import { Badge, Button, Card, TextField, useToast } from '@/components/md';
import { useCreateFoodLogs } from '@/hooks/queries';
import { kcal } from '@/lib/format';
import type { MealType } from '@/lib/types';

import { scale, type DraftEntry } from './draft';

interface DraftReviewProps {
  drafts: DraftEntry[];
  setDrafts: (update: (current: DraftEntry[] | null) => DraftEntry[] | null) => void;
  meal: MealType;
  /** Present for photo logging; a typed meal has no image to attach. */
  imageUrl?: string | null;
  onDone: () => void;
}

/**
 * The confirm-before-saving step for AI-drafted entries, shared by photo and
 * free-text logging. Both produce the same item shape from the backend, so the
 * review, per-item correction and batch save live here once.
 *
 * Nothing is written until the user presses save: the model's portion estimate
 * is a starting point, not an answer.
 */
export function DraftReview({ drafts, setDrafts, meal, imageUrl, onDone }: DraftReviewProps) {
  const toast = useToast();
  const createLogs = useCreateFoodLogs();

  const totalCalories = useMemo(
    () => drafts.reduce((sum, entry) => sum + scale(entry.per100, entry.grams).calories, 0),
    [drafts],
  );

  async function saveAll() {
    if (!drafts?.length) return;
    try {
      const payload = drafts.map((entry) => ({
        food_name: entry.name,
        portion_g: entry.grams,
        meal_type: meal,
        // The user reviewed and accepted the estimate, so record it as confirmed.
        source: 'ai_confirmed',
        ai_confidence: entry.confidence,
        image_url: imageUrl ?? undefined,
        fdc_id: entry.fdcId ?? undefined,
        food_item_id: entry.foodItemId ?? undefined,
        ...scale(entry.per100, entry.grams),
      }));
      const result = await createLogs.mutateAsync(payload);
      toast.success(`${result.count} ${result.count === 1 ? 'item' : 'items'} logged.`);
      onDone();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : 'Could not save the entries.');
    }
  }

  return (
    <div className="space-y-4">
          <div className="flex items-center justify-between">
            <p className="text-label-lg font-medium">Check before saving</p>
            <span className="tabular text-label-md text-md-on-surface-variant">
              {kcal(totalCalories)} kcal total
            </span>
          </div>

          <ul className="space-y-3">
            {drafts.map((entry, index) => {
              const macros = scale(entry.per100, entry.grams);
              const lowConfidence = (entry.confidence ?? 1) < 0.55;
              return (
                <li key={entry.key}>
                  <Card tone="low" className="rounded-md">
                    <div className="flex items-start justify-between gap-3">
                      <input
                        value={entry.name}
                        aria-label={`Name for item ${index + 1}`}
                        onChange={(event) =>
                          setDrafts((current) =>
                            current?.map((row, i) =>
                              i === index ? { ...row, name: event.target.value } : row,
                            ) ?? null,
                          )
                        }
                        className="min-w-0 flex-1 border-b border-transparent bg-transparent text-label-lg font-medium outline-none transition-colors focus:border-md-primary"
                      />
                      <button
                        type="button"
                        aria-label={`Remove ${entry.name}`}
                        onClick={() =>
                          setDrafts((current) => current?.filter((_, i) => i !== index) ?? null)
                        }
                        className="shrink-0 rounded-full p-1.5 text-md-on-surface-variant transition-colors hover:bg-md-error/10 hover:text-md-error"
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>

                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      {entry.resolution === 'unresolved' ? (
                        <Badge tone="error">No nutrition match</Badge>
                      ) : (
                        <Badge tone={entry.resolution === 'cache' ? 'info' : 'success'}>
                          {entry.resolution === 'cache' ? 'from cache' : 'USDA matched'}
                        </Badge>
                      )}
                      {entry.confidence !== undefined && (
                        <Badge tone={lowConfidence ? 'warning' : 'neutral'}>
                          {Math.round(entry.confidence * 100)}% confident
                        </Badge>
                      )}
                    </div>

                    <div className="mt-3 grid grid-cols-2 gap-3">
                      <TextField
                        label="Portion"
                        type="number"
                        inputMode="decimal"
                        min={1}
                        suffix="g"
                        value={String(entry.grams)}
                        onChange={(event) =>
                          setDrafts((current) =>
                            current?.map((row, i) =>
                              i === index
                                ? { ...row, grams: Math.max(1, Number(event.target.value) || 0) }
                                : row,
                            ) ?? null,
                          )
                        }
                      />
                      <TextField
                        label="Calories"
                        type="number"
                        inputMode="decimal"
                        min={0}
                        suffix="kcal"
                        value={String(Math.round(macros.calories))}
                        onChange={(event) => {
                          const nextCalories = Math.max(0, Number(event.target.value) || 0);
                          setDrafts((current) =>
                            current?.map((row, i) =>
                              i === index
                                ? {
                                    ...row,
                                    per100: {
                                      ...row.per100,
                                      calories: (nextCalories / row.grams) * 100,
                                    },
                                  }
                                : row,
                            ) ?? null,
                          );
                        }}
                      />
                    </div>

                    <p className="tabular mt-2 text-label-sm text-md-on-surface-variant">
                      P {macros.protein_g ?? '—'} g · C {macros.carbs_g ?? '—'} g · F{' '}
                      {macros.fat_g ?? '—'} g
                    </p>

                    {entry.note && (
                      <p className="mt-2 text-label-sm text-md-on-surface-variant/85">{entry.note}</p>
                    )}
                  </Card>
                </li>
              );
            })}
          </ul>

          <Button
            fullWidth
            size="lg"
            loading={createLogs.isPending}
            icon={<Check size={18} />}
            onClick={() => void saveAll()}
          >
            Save {drafts.length} {drafts.length === 1 ? 'item' : 'items'} · {kcal(totalCalories)} kcal
          </Button>
          <p className="text-center text-label-sm text-md-on-surface-variant">
            Nothing is saved until you press this — the estimate is always yours to correct.
          </p>
    </div>
  );
}
