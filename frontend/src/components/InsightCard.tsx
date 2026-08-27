import { RefreshCw, Sparkles, WandSparkles } from 'lucide-react';
import { useState } from 'react';

import { Badge, Button, Card, Segmented, Skeleton } from '@/components/md';
import { useInsight, useRefreshInsight } from '@/hooks/queries';
import { ApiError } from '@/lib/api';
import type { InsightKind } from '@/lib/types';

const KINDS: { value: InsightKind; label: string }[] = [
  { value: 'daily', label: 'Today' },
  { value: 'weekly', label: 'Week' },
  { value: 'monthly', label: 'Month' },
];

/**
 * Generated recap. The metrics are computed server-side and the model only
 * writes the prose, so the numbers quoted here always match the log. When Gemini
 * is unavailable the backend falls back to a rule-based summary rather than
 * failing, which is why there is no hard error state for a missing key.
 */
export function InsightCard() {
  const [kind, setKind] = useState<InsightKind>('daily');
  const insight = useInsight(kind);
  const refresh = useRefreshInsight(kind);

  const data = refresh.data ?? insight.data;
  const error = insight.error;
  const busy = insight.isLoading || refresh.isPending;

  return (
    <Card tone="container" className="relative overflow-hidden">
      <span
        aria-hidden
        className="md-blob right-[-20%] top-[-40%] h-48 w-48 animate-drift-slow bg-md-tertiary/25"
      />

      <div className="relative">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="inline-flex items-center gap-2 text-label-md font-medium text-md-on-surface-variant">
            <WandSparkles size={16} />
            Your recap
          </span>
          <div className="flex items-center gap-2">
            <Segmented size="sm" label="Recap period" options={KINDS} value={kind} onChange={setKind} />
            <Button
              variant="text"
              size="sm"
              icon={<RefreshCw size={14} className={refresh.isPending ? 'animate-spin' : undefined} />}
              onClick={() => refresh.mutate()}
              disabled={busy}
            >
              New
            </Button>
          </div>
        </div>

        {busy && !data && (
          <div className="mt-4 space-y-2">
            <Skeleton className="h-6 w-2/3" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
          </div>
        )}

        {error && !data && (
          <p className="mt-4 text-body-sm text-md-on-surface-variant">
            {error instanceof ApiError && error.isRateLimit
              ? 'Summary limit reached for this hour — it will be back shortly.'
              : 'Log a day of food and a recap will appear here.'}
          </p>
        )}

        {data && (
          <div className="mt-4">
            <p className="text-title-lg font-medium leading-snug">{data.headline}</p>
            <p className="mt-2 text-body-md text-md-on-surface-variant">{data.body}</p>

            {data.highlights.length > 0 && (
              <ul className="mt-4 flex flex-wrap gap-2">
                {data.highlights.map((highlight) => (
                  <li key={highlight}>
                    <Badge tone="info" icon={<Sparkles size={12} />}>
                      {highlight}
                    </Badge>
                  </li>
                ))}
              </ul>
            )}

            <p className="mt-4 text-label-sm text-md-on-surface-variant/75">
              {data.model
                ? `Written by ${data.model} from your logged numbers.`
                : 'Generated from your logged numbers without the AI model.'}
              {data.cached && ' · cached'}
            </p>
          </div>
        )}
      </div>
    </Card>
  );
}
