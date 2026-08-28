import { CheckCircle2, Target, TriangleAlert } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { Badge, Button } from '@/components/md';
import { cn } from '@/lib/cn';
import type { BodyComposition } from '@/lib/types';

const VERDICT: Record<
  BodyComposition['verdict'],
  { label: string; tone: 'success' | 'warning' | 'error' | 'info' }
> = {
  mostly_fat: { label: 'Mostly fat', tone: 'success' },
  some_lean_risk: { label: 'Some muscle at risk', tone: 'warning' },
  high_lean_risk: { label: 'Muscle loss likely', tone: 'error' },
  gaining: { label: 'Gaining', tone: 'info' },
  maintaining: { label: 'Holding steady', tone: 'info' },
  insufficient_data: { label: 'Need more data', tone: 'info' },
};

/**
 * Sits under the macros: is the weight coming off fat or muscle, why, and what
 * the daily numbers would have to become to keep it fat.
 *
 * Compact by design — the full signal-by-signal breakdown lives on Analytics.
 * Here it is the verdict, the reason behind it, and the arithmetic to fix it.
 */
export function FatLossNote({ data }: { data: BodyComposition }) {
  const navigate = useNavigate();
  const verdict = VERDICT[data.verdict];
  const inZone = data.in_fat_loss_zone;

  // The reason, taken from whichever signal is actually dragging.
  const culprit = data.signals.find((s) => s.status === 'risk')
    ?? data.signals.find((s) => s.status === 'watch');

  return (
    <div className="mt-5 border-t border-md-outline-variant pt-4">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'grid h-7 w-7 shrink-0 place-items-center rounded-full',
              inZone
                ? 'bg-md-success-container text-md-on-success-container'
                : 'bg-md-warning-container text-md-on-warning-container',
            )}
          >
            {inZone ? <CheckCircle2 size={15} /> : <TriangleAlert size={15} />}
          </span>
          <p className="text-label-lg font-medium">Fat or muscle?</p>
        </div>
        <Badge tone={verdict.tone}>{verdict.label}</Badge>
      </div>

      <p className="mt-2.5 font-prose text-body-sm text-md-on-surface">{data.headline}</p>

      {culprit && !inZone && (
        <p className="mt-1.5 font-prose text-label-sm text-md-on-surface-variant">
          <span className="font-medium">Why: </span>
          {culprit.detail}
        </p>
      )}

      {data.zone_note && (
        <div
          className={cn(
            'mt-3 rounded-md px-3.5 py-3',
            inZone
              ? 'bg-md-success-container/50 text-md-on-success-container'
              : 'bg-md-info-container/60 text-md-on-info-container',
          )}
        >
          <p className="flex items-center gap-1.5 text-label-sm font-medium">
            <Target size={13} />
            {inZone ? 'In the fat-loss zone' : 'To reach the fat-loss zone'}
          </p>
          <p className="mt-1 font-prose text-label-md leading-relaxed">{data.zone_note}</p>
        </div>
      )}

      <Button
        variant="text"
        size="sm"
        className="mt-2"
        onClick={() => navigate('/analytics')}
      >
        See the full breakdown
      </Button>
    </div>
  );
}
