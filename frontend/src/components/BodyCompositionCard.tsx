import { ArrowRight, CheckCircle2, CircleAlert, HelpCircle, TriangleAlert } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

import { Badge, Button, Card, SectionHeader } from '@/components/md';
import { cn } from '@/lib/cn';
import type { BodyComposition, BodyCompositionSignal } from '@/lib/types';

const VERDICT_TONE: Record<BodyComposition['verdict'], 'success' | 'warning' | 'error' | 'info'> = {
  mostly_fat: 'success',
  some_lean_risk: 'warning',
  high_lean_risk: 'error',
  gaining: 'info',
  maintaining: 'info',
  insufficient_data: 'info',
};

const VERDICT_LABEL: Record<BodyComposition['verdict'], string> = {
  mostly_fat: 'Mostly fat loss',
  some_lean_risk: 'Some muscle at risk',
  high_lean_risk: 'Muscle loss likely',
  gaining: 'Gaining',
  maintaining: 'Holding steady',
  insufficient_data: 'Need more data',
};

const STATUS_ICON = {
  good: <CheckCircle2 size={15} className="text-md-success" />,
  watch: <CircleAlert size={15} className="text-md-warning" />,
  risk: <TriangleAlert size={15} className="text-md-error" />,
  unknown: <HelpCircle size={15} className="text-md-on-surface-variant" />,
};

/**
 * Reads the four levers that decide whether a deficit spares muscle, and says
 * plainly which way the current trend is going.
 *
 * Presented as indicators rather than a measurement on purpose: splitting fat
 * from lean mass needs a scan, and a user who wrongly believes they are losing
 * pure fat has no reason to fix the protein intake costing them muscle.
 */
export function BodyCompositionCard({ data }: { data: BodyComposition }) {
  const navigate = useNavigate();

  /** Hands the coach the specific question with the numbers already in it. */
  function askTheCoach() {
    const worst = [...data.signals]
      .filter((s) => s.status === 'risk' || s.status === 'watch')
      .map((s) => `${s.label.toLowerCase()} (${s.detail})`)
      .join('; ');

    const question = [
      `My analytics say: ${data.headline}`,
      worst ? `Flagged: ${worst}` : 'Nothing is flagged.',
      `Suggested focus: ${data.focus}`,
      '',
      'Looking at my actual logs, is my weight loss coming from fat or muscle,',
      'and what exactly should I change this week? Be specific about my numbers.',
    ].join('\n');

    // The coach reads the signed-in user's own log server-side, so only the
    // question needs carrying across.
    navigate('/coach', { state: { prefill: question } });
  }

  return (
    <Card tone="container">
      <SectionHeader
        title="Fat or muscle?"
        subtitle="What the loss is actually made of"
        icon={<TriangleAlert size={18} />}
        action={<Badge tone={VERDICT_TONE[data.verdict]}>{VERDICT_LABEL[data.verdict]}</Badge>}
      />

      <p className="mt-3 text-body-md font-medium">{data.headline}</p>

      <ul className="mt-4 grid gap-2 sm:grid-cols-2">
        {data.signals.map((signal) => (
          <SignalRow key={signal.key} signal={signal} />
        ))}
      </ul>

      <div className="mt-4 rounded-md bg-md-secondary-container px-4 py-3 text-md-on-secondary-container">
        <p className="text-label-md font-medium">What to work on</p>
        <p className="mt-1 text-body-sm">{data.focus}</p>
      </div>

      <Button
        variant="text"
        size="sm"
        className="mt-3"
        trailingIcon={<ArrowRight size={16} />}
        onClick={askTheCoach}
      >
        To know more, ask the coach
      </Button>

      <p className="mt-2 text-label-sm text-md-on-surface-variant/85">{data.caveat}</p>
    </Card>
  );
}

function SignalRow({ signal }: { signal: BodyCompositionSignal }) {
  return (
    <li
      className={cn(
        'flex gap-2.5 rounded-md px-3 py-2.5',
        signal.status === 'risk' ? 'bg-md-error/[0.07]' : 'bg-md-surface-container-low',
      )}
    >
      <span className="mt-0.5 shrink-0">{STATUS_ICON[signal.status]}</span>
      <span className="min-w-0">
        <span className="block text-label-md font-medium">{signal.label}</span>
        <span className="block text-label-sm text-md-on-surface-variant">{signal.detail}</span>
      </span>
    </li>
  );
}
