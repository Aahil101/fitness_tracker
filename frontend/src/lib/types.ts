/** Shapes returned by the FastAPI backend. Kept in one place so the API
 *  contract is reviewable at a glance rather than scattered through hooks. */

export type Sex = 'male' | 'female' | 'other';
export type ActivityLevel = 'sedentary' | 'light' | 'moderate' | 'active';
export type MealType = 'breakfast' | 'lunch' | 'dinner' | 'snack';
export type Intensity = 'light' | 'moderate' | 'vigorous';
export type UnitPreference = 'metric' | 'imperial';
export type FoodSource = 'manual' | 'ai_estimated' | 'ai_confirmed';
export type PeriodKey = 'week' | 'month' | 'year';
export type ForecastWindow = 7 | 14 | 30;
export type InsightKind = 'daily' | 'weekly' | 'monthly';

export interface Profile {
  id: string;
  email?: string | null;
  full_name: string | null;
  sex: Sex | null;
  birth_date: string | null;
  starting_weight_kg: number | null;
  goal_weight_kg: number | null;
  height_cm: number | null;
  activity_level: ActivityLevel | null;
  unit_preference: UnitPreference | null;
  timezone: string | null;
  onboarded_at: string | null;
}

export interface Goal {
  id?: string;
  daily_calorie_target: number | null;
  maintenance_calories: number | null;
  protein_target_g: number | null;
  carb_target_g: number | null;
  fat_target_g: number | null;
  fiber_target_g: number | null;
  target_weekly_deficit_kcal: number | null;
  effective_from?: string | null;
  is_provisional?: boolean;
}

export interface MeResponse {
  user: { id: string; email: string | null };
  profile: Profile;
  goal: Goal;
  goal_is_provisional: boolean;
  current_weight_kg: number | null;
  today: string;
  timezone: string;
  needs_onboarding: boolean;
  integrations: { supabase: boolean; gemini: boolean; usda: boolean; redis: boolean };
}

export interface FoodLog {
  id: string;
  logged_at: string;
  meal_type: MealType | null;
  food_item_id: string | null;
  food_name: string;
  portion_g: number;
  calories: number;
  protein_g: number | null;
  carbs_g: number | null;
  fat_g: number | null;
  fiber_g: number | null;
  source: FoodSource;
  ai_confidence: number | null;
  image_url: string | null;
}

export interface Workout {
  id: string;
  logged_at: string;
  activity_type: string;
  duration_min: number;
  calories_burned: number;
  intensity: Intensity | null;
  notes?: string | null;
  source: 'manual' | 'met_estimated';
}

export interface WeightLog {
  id: string;
  logged_at: string;
  weight_kg: number;
  note: string | null;
}

export interface PeriodStats {
  days: number;
  from: string;
  to: string;
  total_calories: number;
  daily_average: number;
  days_logged: number;
  total_burned: number;
  workout_sessions: number;
  workout_minutes: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
}

/** Weight with the daily water and gut-content noise taken out. */
export interface WeightTrend {
  trend_kg: number | null;
  scale_kg: number | null;
  /** Latest reading minus the trend — the number that justifies ignoring the scale. */
  deviation_kg: number | null;
  /** How much this user's readings typically scatter. */
  noise_kg: number | null;
  weekly_change_kg: number | null;
  /** As a share of bodyweight, which is the form the safe-rate guidance takes. */
  weekly_change_pct: number | null;
  rate_status: 'unknown' | 'holding' | 'gentle' | 'on_target' | 'rapid' | 'wrong_way';
  rate_label: string;
  rate_detail: string;
  days_of_data: number;
  span_days: number;
  interpolated_days: number;
  how_calculated: string;
  series: { date: string; trend_kg: number; scale_kg: number | null }[];
}

/** Maintenance calories, and where the figure came from. */
export interface Expenditure {
  maintenance_kcal: number;
  formula_kcal: number;
  measured_kcal: number | null;
  source: 'formula' | 'blended' | 'measured';
  confidence: 'low' | 'medium' | 'high';
  divergence_kcal: number | null;
  days_used: number;
  days_logged: number;
  logged_fraction: number;
  trust: number;
  how_calculated: string;
  notes: string[];
  target_calories: number;
  stored_target_calories: number;
}

/** Whether the plan was followed, as distinct from whether it was typed in. */
export interface Adherence {
  days_in_window: number;
  days_logged: number;
  days_compliant: number;
  compliance_rate: number | null;
  calorie_days: number;
  protein_days: number;
  current_streak: number;
  best_streak: number;
  status: 'unknown' | 'good' | 'watch' | 'risk';
  headline: string;
  detail: string;
  how_calculated: string;
  weakest_link: 'calories' | 'protein' | 'logging' | 'none';
  notes: string[];
}

export interface GaugeState {
  logged_calories: number;
  maintenance_calories: number;
  daily_calorie_target: number;
  remaining_to_target: number;
  remaining_to_maintenance: number;
  over_target: boolean;
  over_maintenance: boolean;
  fraction_of_maintenance: number;
  target_fraction_of_maintenance: number;
  workout_burn: number;
}

export interface ForecastState {
  window_days: number;
  days_with_data: number;
  avg_daily_intake: number;
  avg_daily_exercise_burn: number;
  avg_daily_net_kcal: number;
  projected_weekly_change_kg: number;
  projected_monthly_change_kg: number;
  observed_weekly_change_kg: number | null;
  effective_weekly_change_kg: number;
  projected_weight_7d_kg: number | null;
  projected_weight_30d_kg: number | null;
  days_to_goal: number | null;
  goal_date: string | null;
  /** Bounds on the goal date. A single date implies precision we do not have. */
  goal_date_earliest: string | null;
  goal_date_latest: string | null;
  goal_eta_note: string;
  confidence: 'low' | 'medium' | 'high';
  notes: string[];
}

export interface DeficitSummary {
  maintenance_calories: number;
  target_calories: number;
  exercise_burn: number;
  eaten_calories: number;
  food_deficit: number;
  exercise_deficit: number;
  total_deficit: number;
  target_deficit: number;
  progress_fraction: number;
  tracked_days: number;
  min_days_required: number;
  has_enough_history: boolean;
  avg_daily_deficit: number;
  projections: { days: number; loss_kg: number; weight_kg?: number }[];
  note: string;
}

export interface DashboardResponse {
  today: {
    date: string;
    calories: number;
    protein_g: number;
    carbs_g: number;
    fat_g: number;
    fiber_g: number;
    entry_count: number;
    workout_burn: number;
    workout_sessions: number;
    logs: FoodLog[];
    workouts: Workout[];
  };
  goal: Goal;
  gauge: GaugeState;
  periods: Record<PeriodKey, PeriodStats>;
  deficit: DeficitSummary;
  body_composition: BodyComposition;
  weight_trend: WeightTrend;
  expenditure: Expenditure;
  adherence: Adherence;
  forecast: ForecastState;
  weight: {
    current_kg: number | null;
    trend_kg: number | null;
    goal_kg: number | null;
    starting_kg: number | null;
    logged_today: boolean;
    latest_logged_at: string | null;
    total_change_kg: number | null;
  };
  profile: {
    full_name: string | null;
    unit_preference: UnitPreference;
    timezone: string;
    needs_onboarding: boolean;
  };
}

export interface CaloriePoint {
  date: string;
  calories_in: number;
  exercise_burn: number;
  calories_out: number;
  net: number | null;
  target: number;
  logged: boolean;
}

export interface MacroPoint {
  date: string;
  calories: number;
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  fiber_g: number;
}

export interface BodyCompositionSignal {
  key: 'rate' | 'protein' | 'training' | 'deficit';
  label: string;
  status: 'good' | 'watch' | 'risk' | 'unknown';
  value: number | null;
  detail: string;
}

export interface BodyComposition {
  verdict:
    | 'insufficient_data'
    | 'mostly_fat'
    | 'some_lean_risk'
    | 'high_lean_risk'
    | 'gaining'
    | 'maintaining';
  headline: string;
  focus: string;
  caveat: string;
  signals: BodyCompositionSignal[];
  lean_risk_score: number;
  /** Two or three lines of concrete daily numbers to reach the fat-loss zone. */
  zone_note: string;
  in_fat_loss_zone: boolean;
}

export interface AnalyticsResponse {
  range: { from: string; to: string; days: number };
  calorie_series: CaloriePoint[];
  weight_series: { date: string; weight_kg: number; trend_kg: number | null }[];
  weight_projection: { date: string; projected_kg: number }[];
  macro_series: MacroPoint[];
  macro_totals: Record<'protein_g' | 'carbs_g' | 'fat_g' | 'fiber_g', number>;
  macro_averages: Record<'calories' | 'protein_g' | 'carbs_g' | 'fat_g' | 'fiber_g', number>;
  macro_targets: Record<'protein_g' | 'carbs_g' | 'fat_g' | 'fiber_g', number | null>;
  workout_groups: Record<'day' | 'week', WorkoutGroup[]>;
  activity_breakdown: {
    activity: string;
    calories_burned: number;
    duration_min: number;
    sessions: number;
  }[];
  forecast: ForecastState & { observed_span_days: number };
  body_composition: BodyComposition;
  weight_trend: WeightTrend;
  expenditure: Expenditure;
  adherence: Adherence;
  targets: { daily_calorie_target: number; maintenance_calories: number };
}

export interface WorkoutGroup {
  bucket: string;
  calories_burned: number;
  duration_min: number;
  sessions: number;
}

export interface FoodSearchItem {
  fdc_id: string | null;
  food_item_id: string | null;
  name: string;
  brand: string | null;
  calories_per_100g: number | null;
  protein_per_100g: number | null;
  carbs_per_100g: number | null;
  fat_per_100g: number | null;
  fiber_per_100g: number | null;
  serving_size_g: number | null;
  source: 'cache' | 'usda';
}

export interface RecognisedFood {
  food_name: string;
  portion_g: number;
  confidence: number;
  calories: number | null;
  protein_g: number | null;
  carbs_g: number | null;
  fat_g: number | null;
  fiber_g: number | null;
  fdc_id: string | null;
  food_item_id: string | null;
  matched_name: string | null;
  resolution: 'cache' | 'usda' | 'estimated' | 'unresolved';
  notes: string | null;
}

export interface FoodPhotoDraft {
  items: RecognisedFood[];
  image_url: string | null;
  model: string | null;
  meal_type: MealType | null;
  total_calories: number;
  warnings: string[];
}

export interface GoalPreview {
  maintenance_calories: number;
  daily_calorie_target: number;
  bmr: number;
  target_weekly_deficit_kcal: number;
  projected_weekly_change_kg: number;
  macros: { protein_g: number; carb_g: number; fat_g: number; fiber_g: number };
  warnings: string[];
}

export interface Insight {
  kind: InsightKind;
  period_start: string;
  period_end: string;
  headline: string;
  body: string;
  highlights: string[];
  metrics: Record<string, unknown>;
  model: string | null;
  generated: boolean;
  cached: boolean;
}

export interface ChatSession {
  id: string;
  title: string;
  last_message_at: string;
  created_at: string;
}

export interface ChatMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at?: string | null;
  model?: string | null;
}

export interface ChatReply {
  session_id: string;
  session_title: string;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
  context_used: Record<string, number | null>;
  degraded: boolean;
}

export interface MetActivity {
  key: string;
  label: string;
  met: number;
  category: string;
}
