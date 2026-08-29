/**
 * React Query bindings. All server state flows through these hooks so cache
 * invalidation lives in one place: any mutation that changes a number the front
 * page shows invalidates `dashboard` and `analytics` together.
 */

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseQueryOptions,
} from '@tanstack/react-query';

import { api } from '@/lib/api';
import type {
  AnalyticsResponse,
  DashboardResponse,
  FastingSession,
  FoodLog,
  ForecastWindow,
  InsightKind,
  MeResponse,
} from '@/lib/types';

export const queryKeys = {
  me: ['me'] as const,
  dashboard: (window: ForecastWindow) => ['dashboard', window] as const,
  analytics: (days: number, window: ForecastWindow) => ['analytics', days, window] as const,
  foodLogs: (from: string, to: string) => ['food-logs', from, to] as const,
  recentFoods: ['recent-foods'] as const,
  workouts: (from: string, to: string) => ['workouts', from, to] as const,
  weights: (days: number) => ['weights', days] as const,
  fasting: ['fasting'] as const,
  fastingHistory: (days: number) => ['fasting-history', days] as const,
  streak: ['weigh-in-streak'] as const,
  metCatalog: ['met-catalog'] as const,
  aiStatus: ['ai-status'] as const,
  insight: (kind: InsightKind) => ['insight', kind] as const,
  chatSessions: ['chat-sessions'] as const,
  chatMessages: (id: string) => ['chat-messages', id] as const,
  suggestions: ['chat-suggestions'] as const,
};

/** Everything that changes when a log is added, edited or removed. */
const LOG_DEPENDENT_KEYS = ['dashboard', 'analytics', 'food-logs', 'workouts', 'weights', 'insight'];

/** Fasting state and its history, invalidated together on start/stop. */
const FASTING_KEYS = ['fasting', 'fasting-history'];

export function useInvalidateLogs() {
  const client = useQueryClient();
  return () => {
    for (const key of LOG_DEPENDENT_KEYS) {
      void client.invalidateQueries({ queryKey: [key] });
    }
  };
}

export function useMe(options?: Partial<UseQueryOptions<MeResponse>>) {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: api.me,
    staleTime: 60_000,
    ...options,
  });
}

export function useDashboard(window: ForecastWindow = 7) {
  return useQuery<DashboardResponse>({
    queryKey: queryKeys.dashboard(window),
    queryFn: () => api.dashboard(window),
    staleTime: 20_000,
    refetchOnWindowFocus: true,
  });
}

export function useAnalytics(days: number, window: ForecastWindow = 14) {
  return useQuery<AnalyticsResponse>({
    queryKey: queryKeys.analytics(days, window),
    queryFn: () => api.analytics(days, window),
    staleTime: 60_000,
  });
}

export function useFoodLogs(from: string, to: string) {
  return useQuery({
    queryKey: queryKeys.foodLogs(from, to),
    queryFn: () => api.foodLogs({ from, to }),
    staleTime: 20_000,
  });
}

export function useWorkouts(from: string, to: string) {
  return useQuery({
    queryKey: queryKeys.workouts(from, to),
    queryFn: () => api.workouts({ from, to }),
    staleTime: 20_000,
  });
}

/**
 * The open fast, if any.
 *
 * Polled rather than merely cached: the page ticks its own clock between
 * refetches, but a fast that crosses a stage boundary changes what the server
 * says, and a phone that has been asleep for two hours needs the truth rather
 * than a locally extrapolated guess.
 */
export function useFasting() {
  return useQuery({
    queryKey: queryKeys.fasting,
    queryFn: api.fastingCurrent,
    staleTime: 30_000,
    refetchInterval: 5 * 60_000,
    refetchOnWindowFocus: true,
  });
}

export function useFastingHistory(days = 90) {
  return useQuery({
    queryKey: queryKeys.fastingHistory(days),
    queryFn: () => api.fastingHistory(days),
    staleTime: 60_000,
  });
}

function useInvalidateFasting() {
  const client = useQueryClient();
  const invalidateLogs = useInvalidateLogs();
  return () => {
    for (const key of FASTING_KEYS) {
      void client.invalidateQueries({ queryKey: [key] });
    }
    invalidateLogs();
  };
}

export function useStartFast() {
  const invalidate = useInvalidateFasting();
  return useMutation({ mutationFn: api.startFast, onSuccess: invalidate });
}

export function useStopFast() {
  const invalidate = useInvalidateFasting();
  return useMutation({ mutationFn: api.stopFast, onSuccess: invalidate });
}

export function useDeleteFast() {
  const invalidate = useInvalidateFasting();
  return useMutation({ mutationFn: api.deleteFast, onSuccess: invalidate });
}

/**
 * Puts a deleted fast back, for the Undo on the toast.
 *
 * Writes a closed row through /log rather than /start, so undoing works even if
 * a new fast happens to be running — /start would be refused.
 */
export function useRestoreFast() {
  const invalidate = useInvalidateFasting();
  return useMutation({
    mutationFn: (row: FastingSession) =>
      api.logFast({
        started_at: row.started_at,
        ended_at: row.ended_at ?? row.started_at,
        target_hours: row.target_hours,
        note: row.note ?? undefined,
      }),
    onSuccess: invalidate,
  });
}

export function useWeights(days = 90) {
  return useQuery({
    queryKey: queryKeys.weights(days),
    queryFn: () => api.weights(days),
    staleTime: 60_000,
  });
}

export function useWeighInStreak() {
  return useQuery({
    queryKey: queryKeys.streak,
    queryFn: api.weighInStreak,
    staleTime: 5 * 60_000,
  });
}

export function useRecentFoods() {
  return useQuery({
    queryKey: queryKeys.recentFoods,
    queryFn: api.recentFoods,
    staleTime: 5 * 60_000,
  });
}

export function useMetCatalog() {
  return useQuery({
    queryKey: queryKeys.metCatalog,
    queryFn: api.metCatalog,
    // The MET table is static; never refetch it during a session.
    staleTime: Infinity,
    gcTime: Infinity,
  });
}

export function useAiStatus() {
  return useQuery({
    queryKey: queryKeys.aiStatus,
    queryFn: api.aiStatus,
    staleTime: 10 * 60_000,
    retry: false,
  });
}

export function useInsight(kind: InsightKind, enabled = true) {
  return useQuery({
    queryKey: queryKeys.insight(kind),
    queryFn: () => api.insight(kind, false),
    enabled,
    staleTime: 30 * 60_000,
    retry: false,
  });
}

export function useChatSessions() {
  return useQuery({
    queryKey: queryKeys.chatSessions,
    queryFn: api.chatSessions,
    staleTime: 30_000,
  });
}

export function useChatMessages(sessionId: string | null) {
  return useQuery({
    queryKey: queryKeys.chatMessages(sessionId ?? 'none'),
    queryFn: () => api.chatMessages(sessionId!),
    enabled: Boolean(sessionId),
    staleTime: 10_000,
  });
}

export function useChatSuggestions() {
  return useQuery({
    queryKey: queryKeys.suggestions,
    queryFn: api.chatSuggestions,
    staleTime: Infinity,
  });
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------
export function useLogWeight() {
  const invalidate = useInvalidateLogs();
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.logWeight,
    onSuccess: () => {
      invalidate();
      void client.invalidateQueries({ queryKey: queryKeys.streak });
      void client.invalidateQueries({ queryKey: queryKeys.me });
    },
  });
}

export function useCreateFoodLog() {
  const invalidate = useInvalidateLogs();
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.createFoodLog,
    onSuccess: () => {
      invalidate();
      void client.invalidateQueries({ queryKey: queryKeys.recentFoods });
    },
  });
}

export function useCreateFoodLogs() {
  const invalidate = useInvalidateLogs();
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.createFoodLogs,
    onSuccess: () => {
      invalidate();
      void client.invalidateQueries({ queryKey: queryKeys.recentFoods });
    },
  });
}

export function useUpdateFoodLog() {
  const invalidate = useInvalidateLogs();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Record<string, unknown> }) =>
      api.updateFoodLog(id, body),
    onSuccess: invalidate,
  });
}

export function useDeleteFoodLog() {
  const invalidate = useInvalidateLogs();
  return useMutation({ mutationFn: api.deleteFoodLog, onSuccess: invalidate });
}

/**
 * Puts a deleted entry back. The delete endpoint returns the row it removed, so
 * an undo needs no extra bookkeeping — it re-creates the same values, keeping
 * the original timestamp so the entry lands back on the day it belonged to.
 */
export function useRestoreFoodLog() {
  const invalidate = useInvalidateLogs();
  return useMutation({
    mutationFn: (log: FoodLog) =>
      api.createFoodLog({
        food_name: log.food_name,
        portion_g: log.portion_g,
        calories: log.calories,
        protein_g: log.protein_g,
        carbs_g: log.carbs_g,
        fat_g: log.fat_g,
        fiber_g: log.fiber_g,
        meal_type: log.meal_type,
        food_item_id: log.food_item_id,
        source: log.source,
        logged_at: log.logged_at,
      }),
    onSuccess: invalidate,
  });
}

export function useCreateWorkout() {
  const invalidate = useInvalidateLogs();
  return useMutation({ mutationFn: api.createWorkout, onSuccess: invalidate });
}

export function useDeleteWorkout() {
  const invalidate = useInvalidateLogs();
  return useMutation({ mutationFn: api.deleteWorkout, onSuccess: invalidate });
}

export function useDeleteWeight() {
  const invalidate = useInvalidateLogs();
  return useMutation({ mutationFn: api.deleteWeight, onSuccess: invalidate });
}

export function useUpdateProfile() {
  const client = useQueryClient();
  const invalidate = useInvalidateLogs();
  return useMutation({
    mutationFn: api.updateProfile,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.me });
      invalidate();
    },
  });
}

export function useSaveGoal() {
  const client = useQueryClient();
  const invalidate = useInvalidateLogs();
  return useMutation({
    mutationFn: api.saveGoal,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.me });
      invalidate();
    },
  });
}

export function useCompleteOnboarding() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.completeOnboarding,
    onSuccess: () => {
      void client.invalidateQueries();
    },
  });
}

export function useAnalyseFoodText() {
  return useMutation({ mutationFn: (text: string) => api.analyseFoodText(text) });
}

export function useAnalysePhoto() {
  return useMutation({
    mutationFn: ({ file, hint }: { file: File; hint?: string }) => api.analysePhoto(file, hint),
  });
}

export function useRefreshInsight(kind: InsightKind) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: () => api.insight(kind, true),
    onSuccess: (data) => {
      client.setQueryData(queryKeys.insight(kind), data);
    },
  });
}

export function useSendChatMessage() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ content, sessionId }: { content: string; sessionId?: string }) =>
      api.sendChatMessage(content, sessionId),
    onSuccess: (reply) => {
      void client.invalidateQueries({ queryKey: queryKeys.chatSessions });
      void client.invalidateQueries({ queryKey: queryKeys.chatMessages(reply.session_id) });
    },
  });
}

export function useDeleteChatSession() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: api.deleteChatSession,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: queryKeys.chatSessions });
    },
  });
}
