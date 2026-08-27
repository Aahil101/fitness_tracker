/**
 * Typed client for the FastAPI backend.
 *
 * Every request carries the Supabase access token, which the backend forwards to
 * PostgREST — so authorisation is enforced by Row Level Security in Postgres,
 * not by this file.
 */

import { getAccessToken } from './supabase';
import type {
  AnalyticsResponse,
  ChatMessage,
  ChatReply,
  ChatSession,
  DashboardResponse,
  FoodLog,
  FoodPhotoDraft,
  FoodSearchItem,
  ForecastWindow,
  Goal,
  GoalPreview,
  Insight,
  InsightKind,
  MeResponse,
  MetActivity,
  Profile,
  WeightLog,
  Workout,
} from './types';

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '');

export const apiBaseUrl = BASE_URL;

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string = 'error',
    readonly retryAfter?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  get isAuthError() {
    return this.status === 401;
  }

  get isRateLimit() {
    return this.status === 429;
  }

  /** 503 means the backend is running but missing an API key. */
  get isConfigError() {
    return this.status === 503;
  }
}

interface RequestOptions {
  method?: 'GET' | 'POST' | 'PATCH' | 'DELETE';
  body?: unknown;
  formData?: FormData;
  signal?: AbortSignal;
  query?: Record<string, string | number | boolean | undefined | null>;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, formData, signal, query } = options;

  const url = new URL(`${BASE_URL}${path}`);
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value));
      }
    }
  }

  const token = await getAccessToken();
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers['Content-Type'] = 'application/json';

  let response: Response;
  try {
    response = await fetch(url.toString(), {
      method,
      headers,
      body: formData ?? (body !== undefined ? JSON.stringify(body) : undefined),
      signal,
    });
  } catch (error) {
    if ((error as Error).name === 'AbortError') throw error;
    throw new ApiError(
      `Cannot reach the API at ${BASE_URL}. Is the backend running?`,
      0,
      'network_error',
    );
  }

  if (response.status === 204) return undefined as T;

  const raw = await response.text();
  let payload: unknown = null;
  if (raw) {
    try {
      payload = JSON.parse(raw);
    } catch {
      payload = { error: { message: raw.slice(0, 300) } };
    }
  }

  if (!response.ok) {
    const envelope = payload as { error?: { code?: string; message?: string }; detail?: string };
    const message =
      envelope?.error?.message ?? envelope?.detail ?? `Request failed (${response.status})`;
    const retryAfter = Number(response.headers.get('Retry-After')) || undefined;
    throw new ApiError(message, response.status, envelope?.error?.code ?? 'error', retryAfter);
  }

  return payload as T;
}

// ---------------------------------------------------------------------------
// Meta
// ---------------------------------------------------------------------------
export const api = {
  health: () =>
    request<{
      status: string;
      env: string;
      integrations: Record<string, boolean | string | null>;
    }>('/health'),

  // -- profile ------------------------------------------------------------
  me: () => request<MeResponse>('/api/me'),

  updateProfile: (patch: Partial<Profile>) =>
    request<{ profile: Profile }>('/api/me', { method: 'PATCH', body: patch }),

  completeOnboarding: (body: {
    full_name?: string;
    sex?: string;
    birth_date?: string;
    height_cm?: number;
    goal_weight_kg?: number;
    activity_level?: string;
    unit_preference?: string;
    timezone?: string;
    current_weight_kg: number;
    weekly_change_kg: number;
    maintenance_override?: number;
  }) =>
    request<{
      profile: Profile;
      goal: Goal;
      computation: GoalPreview & { warnings: string[] };
    }>('/api/me/onboarding', { method: 'POST', body }),

  // -- goals --------------------------------------------------------------
  goals: () => request<{ goals: Goal[]; active: Goal; is_provisional: boolean }>('/api/goals'),

  previewGoal: (body: {
    weight_kg?: number;
    height_cm?: number;
    age_years?: number;
    sex?: string;
    activity_level?: string;
    weekly_change_kg?: number;
    maintenance_override?: number;
  }) => request<GoalPreview>('/api/goals/preview', { method: 'POST', body }),

  saveGoal: (body: Record<string, unknown>) =>
    request<{ goal: Goal; computation: GoalPreview }>('/api/goals', { method: 'POST', body }),

  // -- dashboard / analytics ---------------------------------------------
  dashboard: (forecastWindow: ForecastWindow = 7) =>
    request<DashboardResponse>('/api/dashboard', { query: { forecast_window: forecastWindow } }),

  analytics: (days = 30, forecastWindow: ForecastWindow = 14) =>
    request<AnalyticsResponse>('/api/analytics', {
      query: { days, forecast_window: forecastWindow },
    }),

  // -- food ---------------------------------------------------------------
  searchFood: (q: string, signal?: AbortSignal) =>
    request<FoodSearchItem[]>('/api/food/search', { query: { q, limit: 20 }, signal }),

  recentFoods: () => request<{ foods: Partial<FoodLog>[] }>('/api/food/recent'),

  foodLogs: (params: { date?: string; from?: string; to?: string }) =>
    request<{ from: string; to: string; logs: FoodLog[]; totals: Record<string, number> }>(
      '/api/food/logs',
      { query: params },
    ),

  createFoodLog: (body: Record<string, unknown>) =>
    request<{ log: FoodLog }>('/api/food/logs', { method: 'POST', body }),

  createFoodLogs: (body: Record<string, unknown>[]) =>
    request<{ logs: FoodLog[]; count: number }>('/api/food/logs/batch', { method: 'POST', body }),

  updateFoodLog: (id: string, body: Record<string, unknown>) =>
    request<{ log: FoodLog }>(`/api/food/logs/${id}`, { method: 'PATCH', body }),

  deleteFoodLog: (id: string) =>
    request<{ deleted: FoodLog }>(`/api/food/logs/${id}`, { method: 'DELETE' }),

  // -- workouts -----------------------------------------------------------
  metCatalog: () => request<{ activities: MetActivity[] }>('/api/workouts/catalog'),

  estimateBurn: (body: {
    activity_type: string;
    duration_min: number;
    intensity?: string;
    weight_kg?: number;
  }) =>
    request<{ calories_burned: number; met: number; weight_kg_used: number; intensity: string }>(
      '/api/workouts/estimate',
      { method: 'POST', body },
    ),

  workouts: (params: { from?: string; to?: string; days?: number }) =>
    request<{
      from: string;
      to: string;
      workouts: Workout[];
      totals: { calories_burned: number; duration_min: number; sessions: number };
    }>('/api/workouts', { query: params }),

  createWorkout: (body: Record<string, unknown>) =>
    request<{ workout: Workout }>('/api/workouts', { method: 'POST', body }),

  updateWorkout: (id: string, body: Record<string, unknown>) =>
    request<{ workout: Workout }>(`/api/workouts/${id}`, { method: 'PATCH', body }),

  deleteWorkout: (id: string) =>
    request<{ deleted: Workout }>(`/api/workouts/${id}`, { method: 'DELETE' }),

  // -- weight -------------------------------------------------------------
  weights: (days = 90) =>
    request<{
      logs: WeightLog[];
      count: number;
      latest: WeightLog | null;
      observed_weekly_change_kg: number | null;
      span_days: number;
    }>('/api/weight', { query: { days } }),

  logWeight: (body: { weight_kg: number; logged_at?: string; note?: string }) =>
    request<{
      log: WeightLog;
      change_since_previous_kg: number | null;
      previous: WeightLog | null;
    }>('/api/weight', { method: 'POST', body }),

  deleteWeight: (id: string) =>
    request<{ deleted: WeightLog }>(`/api/weight/${id}`, { method: 'DELETE' }),

  weighInStreak: () => request<{ streak: number; logged_today: boolean }>('/api/weight/streak'),

  // -- AI -----------------------------------------------------------------
  aiStatus: () =>
    request<{
      gemini_configured: boolean;
      model: string;
      model_available: boolean;
      available_models: string[];
      usda_key_is_demo: boolean;
      redis_configured: boolean;
    }>('/api/ai/status'),

  analysePhoto: (file: File, hint?: string) => {
    const formData = new FormData();
    formData.append('file', file);
    if (hint) formData.append('hint', hint);
    return request<FoodPhotoDraft>('/api/ai/food-photo', { method: 'POST', formData });
  },

  insight: (kind: InsightKind, refresh = false) =>
    request<Insight>('/api/ai/insight', { method: 'POST', body: { kind, refresh } }),

  // -- chat ---------------------------------------------------------------
  chatSuggestions: () => request<{ prompts: string[] }>('/api/chat/suggestions'),

  chatSessions: () => request<{ sessions: ChatSession[] }>('/api/chat/sessions'),

  createChatSession: (title?: string) =>
    request<{ session: ChatSession }>('/api/chat/sessions', { method: 'POST', body: { title } }),

  deleteChatSession: (id: string) =>
    request<{ deleted: ChatSession }>(`/api/chat/sessions/${id}`, { method: 'DELETE' }),

  chatMessages: (sessionId: string) =>
    request<{ session: ChatSession; messages: ChatMessage[] }>(
      `/api/chat/sessions/${sessionId}/messages`,
    ),

  sendChatMessage: (content: string, sessionId?: string) =>
    request<ChatReply>('/api/chat/messages', {
      method: 'POST',
      body: { content, session_id: sessionId },
    }),
};
