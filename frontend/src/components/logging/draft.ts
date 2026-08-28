/**
 * Draft entries shared by every AI-assisted logging path.
 *
 * A draft is a *proposal*: per-100g nutrition from USDA plus a portion the model
 * estimated. Nutrition is stored per 100g and scaled on demand so editing the
 * portion recomputes the macros without another round trip.
 */
import type { FoodSearchItem, RecognisedFood } from '@/lib/types';

export interface DraftEntry {
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

export function scale(per100: DraftEntry['per100'], grams: number) {
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

export function fromSearchItem(item: FoodSearchItem): DraftEntry {
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

export function fromRecognised(item: RecognisedFood, index: number): DraftEntry {
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
