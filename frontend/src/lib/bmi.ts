/**
 * Healthy weight range from height, via BMI.
 *
 * The WHO band for adults is 18.5 to 24.9, so the range is those two multiplied
 * by height in metres squared. Used to suggest a sensible goal weight during
 * setup, where the alternative is the user guessing.
 *
 * BMI knows nothing about body composition — it is mass over height and cannot
 * tell muscle from fat, which is why the UI presents this as a reference band
 * rather than a target, and why anyone carrying real muscle may sit above it
 * while lean. Kept deliberately simple for that reason: a more elaborate
 * formula would imply a precision the measure does not have.
 */

export const BMI_HEALTHY_MIN = 18.5;
export const BMI_HEALTHY_MAX = 24.9;

/** Below this height the adult BMI bands stop being meaningful. */
const MIN_PLAUSIBLE_HEIGHT_CM = 120;

export interface HealthyWeightRange {
  minKg: number;
  maxKg: number;
}

export function healthyWeightRange(heightCm: number | null): HealthyWeightRange | null {
  if (!heightCm || heightCm < MIN_PLAUSIBLE_HEIGHT_CM) return null;
  const metres = heightCm / 100;
  const square = metres * metres;
  return {
    minKg: BMI_HEALTHY_MIN * square,
    maxKg: BMI_HEALTHY_MAX * square,
  };
}

export function bmiFor(weightKg: number | null, heightCm: number | null): number | null {
  if (!weightKg || !heightCm || heightCm < MIN_PLAUSIBLE_HEIGHT_CM) return null;
  const metres = heightCm / 100;
  return weightKg / (metres * metres);
}

export type BmiBand = 'under' | 'healthy' | 'over';

export function bandFor(bmi: number | null): BmiBand | null {
  if (bmi === null) return null;
  if (bmi < BMI_HEALTHY_MIN) return 'under';
  if (bmi > BMI_HEALTHY_MAX) return 'over';
  return 'healthy';
}
