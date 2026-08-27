import {
  AlertTriangle,
  Camera,
  Check,
  Clock,
  ImageUp,
  Loader2,
  Search,
  Sparkles,
  Trash2,
  Utensils,
  X,
} from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';

import {
  Badge,
  Button,
  Card,
  Chip,
  EmptyState,
  Sheet,
  Skeleton,
  TextField,
  useToast,
} from '@/components/md';
import { useAiStatus, useAnalysePhoto, useCreateFoodLog, useCreateFoodLogs, useRecentFoods } from '@/hooks/queries';
import { api, ApiError } from '@/lib/api';
import { cn } from '@/lib/cn';
import { kcal, MEAL_LABELS, MEAL_ORDER } from '@/lib/format';
import type { FoodSearchItem, MealType, RecognisedFood } from '@/lib/types';

type Tab = 'search' | 'photo' | 'recent';

const PORTION_PRESETS = [30, 50, 100, 150, 200, 300];

interface LogFoodSheetProps {
  open: boolean;
  onClose: () => void;
  defaultMeal?: MealType;
  /** Opens straight onto the camera tab (used by the PWA shortcut). */
  initialTab?: Tab;
}

/** Per-100 g basis so editing the portion rescales every macro consistently. */
interface DraftEntry {
  key: string;
  name: string;
  grams: number;
  per100: {
    calories: number;
    protein_g: number | null;
    carbs_g: number | null;
    fat_g: number | null;
    fiber_g: number | null;
  };
  fdcId: string | null;
  foodItemId: string | null;
  confidence?: number;
  resolution?: RecognisedFood['resolution'];
  note?: string | null;
}

function scale(per100: DraftEntry['per100'], grams: number) {
  const factor = grams / 100;
  const value = (input: number | null) => (input === null ? null : Number((input * factor).toFixed(1)));
  return {
    calories: Number((per100.calories * factor).toFixed(1)),
    protein_g: value(per100.protein_g),
    carbs_g: value(per100.carbs_g),
    fat_g: value(per100.fat_g),
    fiber_g: value(per100.fiber_g),
  };
}

function fromSearchItem(item: FoodSearchItem): DraftEntry {
  return {
    key: item.fdc_id ?? item.food_item_id ?? item.name,
    name: item.name,
    grams: item.serving_size_g && item.serving_size_g > 10 ? item.serving_size_g : 100,
    per100: {
      calories: item.calories_per_100g ?? 0,
      protein_g: item.protein_per_100g,
      carbs_g: item.carbs_per_100g,
      fat_g: item.fat_per_100g,
      fiber_g: item.fiber_per_100g,
    },
    fdcId: item.fdc_id,
    foodItemId: item.food_item_id,
  };
}

function fromRecognised(item: RecognisedFood, index: number): DraftEntry {
  const grams = item.portion_g || 100;
  const basis = (value: number | null) =>
    value === null ? null : Number(((value / grams) * 100).toFixed(2));
  return {
    key: `${item.food_name}-${index}`,
    name: item.food_name,
    grams,
    per100: {
      calories: basis(item.calories) ?? 0,
      protein_g: basis(item.protein_g),
      carbs_g: basis(item.carbs_g),
      fat_g: basis(item.fat_g),
      fiber_g: basis(item.fiber_g),
    },
    fdcId: item.fdc_id,
    foodItemId: item.food_item_id,
    confidence: item.confidence,
    resolution: item.resolution,
    note: item.notes,
  };
}

export function LogFoodSheet({ open, onClose, defaultMeal, initialTab = 'search' }: LogFoodSheetProps) {
  const [tab, setTab] = useState<Tab>(initialTab);
  const [meal, setMeal] = useState<MealType>(defaultMeal ?? 'lunch');

  useEffect(() => {
    if (!open) return;
    setTab(initialTab);
    if (defaultMeal) setMeal(defaultMeal);
  }, [open, initialTab, defaultMeal]);

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Log food"
      description="Search the USDA database, photograph your plate, or repeat something you eat often."
      size="lg"
    >
      <div className="pb-4">
        {/* Meal selector */}
        <div className="no-scrollbar -mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
          {MEAL_ORDER.map((value) => (
            <Chip key={value} selected={meal === value} onClick={() => setMeal(value)}>
              {MEAL_LABELS[value]}
            </Chip>
          ))}
        </div>

        {/* Entry method */}
        <div
          role="tablist"
          aria-label="Entry method"
          className="mt-4 grid grid-cols-3 gap-1 rounded-full bg-md-surface-container-low p-1"
        >
          {(
            [
              { value: 'search', label: 'Search', icon: <Search size={16} /> },
              { value: 'photo', label: 'Photo', icon: <Camera size={16} /> },
              { value: 'recent', label: 'Recent', icon: <Clock size={16} /> },
            ] as const
          ).map((option) => (
            <button
              key={option.value}
              role="tab"
              type="button"
              aria-selected={tab === option.value}
              onClick={() => setTab(option.value)}
              className={cn(
                'inline-flex h-10 items-center justify-center gap-1.5 rounded-full text-label-md font-medium',
                'transition-all duration-medium ease-md active:scale-95',
                tab === option.value
                  ? 'bg-md-surface text-md-primary shadow-e1'
                  : 'text-md-on-surface-variant hover:bg-md-on-surface/[0.06]',
              )}
            >
              {option.icon}
              {option.label}
            </button>
          ))}
        </div>

        <div className="mt-5">
          {tab === 'search' && <SearchTab meal={meal} onDone={onClose} />}
          {tab === 'photo' && <PhotoTab meal={meal} onDone={onClose} />}
          {tab === 'recent' && <RecentTab meal={meal} onDone={onClose} />}
        </div>
      </div>
    </Sheet>
  );
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------
function SearchTab({ meal, onDone }: { meal: MealType; onDone: () => void }) {
  const toast = useToast();
  const createLog = useCreateFoodLog();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<FoodSearchItem[]>([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [selected, setSelected] = useState<DraftEntry | null>(null);

  // Debounced search with cancellation so fast typing does not stack requests.
  useEffect(() => {
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      setResults([]);
      setSearching(false);
      return;
    }

    const controller = new AbortController();
    setSearching(true);
    const timer = window.setTimeout(() => {
      api
        .searchFood(trimmed, controller.signal)
        .then((items) => {
          setResults(items);
          setSearchError(items.length === 0 ? 'No matches. Try a simpler term like "brown rice".' : null);
        })
        .catch((error: unknown) => {
          if (error instanceof Error && error.name === 'AbortError') return;
          setSearchError(error instanceof Error ? error.message : 'Search failed.');
        })
        .finally(() => setSearching(false));
    }, 350);

    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [query]);

  async function save() {
    if (!selected) return;
    const macros = scale(selected.per100, selected.grams);
    try {
      await createLog.mutateAsync({
        food_name: selected.name,
        portion_g: selected.grams,
        meal_type: meal,
        source: 'manual',
        fdc_id: selected.fdcId ?? undefined,
        food_item_id: selected.foodItemId ?? undefined,
        ...macros,
      });
      toast.success(`${selected.name} logged.`);
      onDone();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not save the entry.');
    }
  }

  if (selected) {
    return (
      <PortionEditor
        entry={selected}
        onChange={setSelected}
        onBack={() => setSelected(null)}
        onSave={() => void save()}
        saving={createLog.isPending}
      />
    );
  }

  return (
    <div className="space-y-4">
      <TextField
        label="Search foods"
        leading={<Search size={18} />}
        trailing={
          query ? (
            <button type="button" aria-label="Clear search" onClick={() => setQuery('')}>
              <X size={16} />
            </button>
          ) : undefined
        }
        value={query}
        autoFocus
        onChange={(event) => setQuery(event.target.value)}
        placeholder="chicken breast, basmati rice, greek yogurt…"
        hint="Generic whole foods come first; branded items follow."
      />

      {searching && (
        <div className="space-y-2">
          {[0, 1, 2].map((index) => (
            <Skeleton key={index} className="h-16 w-full rounded-md" />
          ))}
        </div>
      )}

      {!searching && searchError && query.trim().length >= 2 && (
        <p className="px-1 text-body-sm text-md-on-surface-variant">{searchError}</p>
      )}

      {!searching && results.length > 0 && (
        <ul className="space-y-2">
          {results.map((item) => (
            <li key={`${item.fdc_id ?? item.food_item_id ?? item.name}`}>
              <button
                type="button"
                onClick={() => setSelected(fromSearchItem(item))}
                className="flex w-full items-center justify-between gap-3 rounded-md bg-md-surface-container-low px-4 py-3 text-left transition-all duration-medium ease-md hover:bg-md-surface-container-high active:scale-[0.99]"
              >
                <span className="min-w-0">
                  <span className="block truncate text-label-lg font-medium">{item.name}</span>
                  <span className="mt-0.5 flex flex-wrap items-center gap-x-2 text-label-sm text-md-on-surface-variant">
                    {item.brand && <span className="truncate">{item.brand}</span>}
                    <span className="tabular">{kcal(item.calories_per_100g)} kcal / 100 g</span>
                    {item.source === 'cache' && <Badge tone="info">cached</Badge>}
                  </span>
                </span>
                <span className="shrink-0 text-md-primary">
                  <Utensils size={18} />
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {!searching && !query && (
        <EmptyState
          icon={<Search size={22} />}
          title="Find a food"
          description="Type at least two characters. Results come from USDA FoodData Central and are cached after the first lookup."
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Portion editor (shared by search and recent)
// ---------------------------------------------------------------------------
function PortionEditor({
  entry,
  onChange,
  onBack,
  onSave,
  saving,
}: {
  entry: DraftEntry;
  onChange: (entry: DraftEntry) => void;
  onBack: () => void;
  onSave: () => void;
  saving: boolean;
}) {
  const macros = useMemo(() => scale(entry.per100, entry.grams), [entry]);

  return (
    <div className="space-y-4">
      <button
        type="button"
        onClick={onBack}
        className="text-label-md font-medium text-md-primary hover:underline"
      >
        ← Back to results
      </button>

      <Card tone="low" className="rounded-md">
        <p className="text-title-md font-medium">{entry.name}</p>
        <p className="tabular mt-1 text-label-md text-md-on-surface-variant">
          {kcal(entry.per100.calories)} kcal per 100 g
        </p>
      </Card>

      <TextField
        label="Portion"
        type="number"
        inputMode="decimal"
        min={1}
        step="1"
        suffix="g"
        value={String(entry.grams)}
        onChange={(event) => onChange({ ...entry, grams: Math.max(1, Number(event.target.value) || 0) })}
      />

      <div className="no-scrollbar -mx-1 flex gap-2 overflow-x-auto px-1">
        {PORTION_PRESETS.map((preset) => (
          <Chip
            key={preset}
            selected={entry.grams === preset}
            onClick={() => onChange({ ...entry, grams: preset })}
          >
            {preset} g
          </Chip>
        ))}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <MacroBox label="Calories" value={kcal(macros.calories)} accent />
        <MacroBox label="Protein" value={`${macros.protein_g ?? '—'} g`} />
        <MacroBox label="Carbs" value={`${macros.carbs_g ?? '—'} g`} />
        <MacroBox label="Fat" value={`${macros.fat_g ?? '—'} g`} />
      </div>

      <Button fullWidth size="lg" loading={saving} icon={<Check size={18} />} onClick={onSave}>
        Add {kcal(macros.calories)} kcal
      </Button>
    </div>
  );
}

function MacroBox({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div
      className={cn(
        'rounded-sm px-3 py-2.5',
        accent ? 'bg-md-primary-container text-md-on-primary-container' : 'bg-md-surface-container-low',
      )}
    >
      <p className="text-label-sm opacity-80">{label}</p>
      <p className="tabular mt-0.5 text-title-md font-medium">{value}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Photo → Gemini → USDA → editable draft
// ---------------------------------------------------------------------------
function PhotoTab({ meal, onDone }: { meal: MealType; onDone: () => void }) {
  const toast = useToast();
  const aiStatus = useAiStatus();
  const analyse = useAnalysePhoto();
  const createLogs = useCreateFoodLogs();
  const fileInput = useRef<HTMLInputElement>(null);

  const [preview, setPreview] = useState<string | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [hint, setHint] = useState('');
  const [drafts, setDrafts] = useState<DraftEntry[] | null>(null);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Revoke the object URL when it changes or unmounts, or the blob leaks.
  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview);
  }, [preview]);

  function pick(nextFile: File | null) {
    if (!nextFile) return;
    if (preview) URL.revokeObjectURL(preview);
    setFile(nextFile);
    setPreview(URL.createObjectURL(nextFile));
    setDrafts(null);
    setError(null);
    setWarnings([]);
  }

  async function run() {
    if (!file) return;
    setError(null);
    try {
      const result = await analyse.mutateAsync({ file, hint: hint.trim() || undefined });
      setDrafts(result.items.map(fromRecognised));
      setWarnings(result.warnings);
      setImageUrl(result.image_url);
      if (result.items.length === 0) {
        setError('Nothing recognisable in that photo. Try a closer, brighter shot.');
      }
    } catch (caught) {
      const apiError = caught instanceof ApiError ? caught : null;
      setError(
        apiError?.isConfigError
          ? 'Add GEMINI_API_KEY to the backend environment to enable photo logging.'
          : caught instanceof Error
            ? caught.message
            : 'Analysis failed.',
      );
    }
  }

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

  const totalCalories = drafts?.reduce((sum, entry) => sum + scale(entry.per100, entry.grams).calories, 0) ?? 0;

  if (aiStatus.data && !aiStatus.data.gemini_configured) {
    return (
      <EmptyState
        icon={<Sparkles size={22} />}
        title="Photo logging needs a Gemini key"
        description="Get a free key at aistudio.google.com/apikey, add it to backend/.env as GEMINI_API_KEY, and restart the API. Search and manual entry work without it."
      />
    );
  }

  return (
    <div className="space-y-4">
      <input
        ref={fileInput}
        type="file"
        accept="image/*"
        // `capture` opens the rear camera directly on phones; on desktop the
        // browser falls back to a file picker, so one input covers both.
        capture="environment"
        className="sr-only"
        onChange={(event) => pick(event.target.files?.[0] ?? null)}
      />

      {!preview ? (
        <button
          type="button"
          onClick={() => fileInput.current?.click()}
          className="group flex w-full flex-col items-center gap-3 rounded-lg border-2 border-dashed border-md-outline-variant bg-md-surface-container-low px-6 py-12 transition-all duration-medium ease-md hover:border-md-primary hover:bg-md-primary/[0.06] active:scale-[0.99]"
        >
          <span className="grid h-16 w-16 place-items-center rounded-xl bg-md-tertiary text-md-on-tertiary shadow-e3 transition-transform duration-medium group-hover:scale-110">
            <Camera size={28} />
          </span>
          <span className="text-title-md font-medium">Photograph your plate</span>
          <span className="max-w-sm text-center text-body-sm text-md-on-surface-variant">
            Shoot from above with the whole plate in frame. A fork or hand in shot helps the model
            judge the portion.
          </span>
        </button>
      ) : (
        <div className="relative overflow-hidden rounded-lg">
          <img src={preview} alt="Food to analyse" className="h-56 w-full object-cover sm:h-72" />
          <div className="absolute right-3 top-3 flex gap-2">
            <Button
              size="sm"
              variant="tonal"
              icon={<ImageUp size={15} />}
              onClick={() => fileInput.current?.click()}
            >
              Replace
            </Button>
          </div>
        </div>
      )}

      {preview && !drafts && (
        <>
          <TextField
            label="Anything the photo hides? (optional)"
            value={hint}
            onChange={(event) => setHint(event.target.value)}
            placeholder="cooked in 2 tsp olive oil, sauce on the side…"
            hint="A short hint noticeably improves the portion estimate."
          />
          <Button
            fullWidth
            size="lg"
            loading={analyse.isPending}
            icon={analyse.isPending ? undefined : <Sparkles size={18} />}
            onClick={() => void run()}
          >
            {analyse.isPending ? 'Identifying food…' : 'Analyse photo'}
          </Button>
        </>
      )}

      {analyse.isPending && (
        <div className="flex items-center gap-3 rounded-md bg-md-secondary-container px-4 py-3 text-md-on-secondary-container">
          <Loader2 size={18} className="animate-spin" />
          <p className="text-body-sm">
            Identifying each item, then resolving real macros from USDA FoodData Central…
          </p>
        </div>
      )}

      {error && (
        <p
          role="alert"
          className="rounded-sm bg-md-error-container px-4 py-3 text-body-sm text-md-on-error-container"
        >
          {error}
        </p>
      )}

      {warnings.map((warning) => (
        <p
          key={warning}
          className="flex gap-2 rounded-sm bg-md-warning-container px-4 py-3 text-body-sm text-md-on-warning-container"
        >
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          {warning}
        </p>
      ))}

      {drafts && drafts.length > 0 && (
        <>
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
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Recent
// ---------------------------------------------------------------------------
function RecentTab({ meal, onDone }: { meal: MealType; onDone: () => void }) {
  const toast = useToast();
  const recent = useRecentFoods();
  const createLog = useCreateFoodLog();
  const [pendingName, setPendingName] = useState<string | null>(null);

  async function relog(item: {
    food_name?: string;
    portion_g?: number;
    calories?: number;
    protein_g?: number | null;
    carbs_g?: number | null;
    fat_g?: number | null;
    fiber_g?: number | null;
    food_item_id?: string | null;
  }) {
    if (!item.food_name || !item.portion_g || item.calories === undefined) return;
    setPendingName(item.food_name);
    try {
      await createLog.mutateAsync({
        food_name: item.food_name,
        portion_g: item.portion_g,
        calories: item.calories,
        protein_g: item.protein_g ?? undefined,
        carbs_g: item.carbs_g ?? undefined,
        fat_g: item.fat_g ?? undefined,
        fiber_g: item.fiber_g ?? undefined,
        meal_type: meal,
        source: 'manual',
        food_item_id: item.food_item_id ?? undefined,
      });
      toast.success(`${item.food_name} logged again.`);
      onDone();
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : 'Could not save the entry.');
    } finally {
      setPendingName(null);
    }
  }

  if (recent.isLoading) {
    return (
      <div className="space-y-2">
        {[0, 1, 2, 3].map((index) => (
          <Skeleton key={index} className="h-14 w-full rounded-md" />
        ))}
      </div>
    );
  }

  const foods = recent.data?.foods ?? [];
  if (foods.length === 0) {
    return (
      <EmptyState
        icon={<Clock size={22} />}
        title="Nothing logged yet"
        description="Foods you log show up here so repeat meals take one tap."
      />
    );
  }

  return (
    <ul className="space-y-2">
      {foods.map((item, index) => (
        <li key={`${item.food_name}-${index}`}>
          <button
            type="button"
            disabled={createLog.isPending}
            onClick={() => void relog(item)}
            className="flex w-full items-center justify-between gap-3 rounded-md bg-md-surface-container-low px-4 py-3 text-left transition-all duration-medium ease-md hover:bg-md-surface-container-high active:scale-[0.99] disabled:opacity-60"
          >
            <span className="min-w-0">
              <span className="block truncate text-label-lg font-medium">{item.food_name}</span>
              <span className="tabular mt-0.5 block text-label-sm text-md-on-surface-variant">
                {Math.round(item.portion_g ?? 0)} g · {kcal(item.calories)} kcal
              </span>
            </span>
            {pendingName === item.food_name ? (
              <Loader2 size={18} className="shrink-0 animate-spin text-md-primary" />
            ) : (
              <span className="shrink-0 text-md-primary">+</span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}
