import { Copy, ExternalLink, KeyRound, Terminal } from 'lucide-react';
import { useState } from 'react';

import { Badge, Blobs, Button, Card } from '@/components/md';
import { apiBaseUrl } from '@/lib/api';

const ENV_TEMPLATE = `VITE_SUPABASE_URL=https://YOUR-PROJECT.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-or-publishable-key
VITE_API_BASE_URL=${apiBaseUrl}`;

const STEPS = [
  {
    title: 'Create a free Supabase project',
    body: 'supabase.com → New project. The free tier covers a group this size comfortably.',
    href: 'https://supabase.com/dashboard',
  },
  {
    title: 'Run the schema migration',
    body: 'Paste supabase/migrations/0001_init.sql into the SQL editor and run it. It creates every table, the RLS policies and the photo bucket.',
  },
  {
    title: 'Copy the project URL and anon key',
    body: 'Project Settings → API. Put them in frontend/.env.local using the template below.',
  },
  {
    title: 'Start the backend',
    body: 'Fill backend/.env from backend/.env.example, then run uvicorn app.main:app --reload.',
  },
];

/** Shown when VITE_SUPABASE_* are missing — a checklist beats a blank screen. */
export function SetupRequired() {
  const [copied, setCopied] = useState(false);

  async function copyTemplate() {
    try {
      await navigator.clipboard.writeText(ENV_TEMPLATE);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="relative min-h-dvh bg-md-surface px-5 py-12">
      <Blobs variant="hero" />
      <div className="relative mx-auto max-w-2xl">
        <Badge tone="warning" icon={<KeyRound size={13} />}>
          Configuration needed
        </Badge>
        <h1 className="mt-4 text-headline-md font-medium tracking-tight">
          Connect Pulse to your Supabase project
        </h1>
        <p className="mt-3 text-body-md text-md-on-surface-variant">
          The app is built and running — it just has no database to talk to yet. Four steps and
          you are in.
        </p>

        <ol className="mt-8 space-y-3">
          {STEPS.map((step, index) => (
            <li key={step.title}>
              <Card tone="container" className="flex gap-4">
                <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-md-primary text-label-lg font-medium text-md-on-primary">
                  {index + 1}
                </span>
                <div className="min-w-0">
                  <p className="text-label-lg font-medium">{step.title}</p>
                  <p className="mt-1 text-body-sm text-md-on-surface-variant">{step.body}</p>
                  {step.href && (
                    <a
                      href={step.href}
                      target="_blank"
                      rel="noreferrer noopener"
                      className="mt-2 inline-flex items-center gap-1.5 text-label-md font-medium text-md-primary hover:underline"
                    >
                      Open Supabase <ExternalLink size={14} />
                    </a>
                  )}
                </div>
              </Card>
            </li>
          ))}
        </ol>

        <Card tone="low" className="mt-6">
          <div className="flex items-center justify-between gap-3">
            <span className="inline-flex items-center gap-2 text-label-md font-medium text-md-on-surface-variant">
              <Terminal size={16} />
              frontend/.env.local
            </span>
            <Button
              variant="text"
              size="sm"
              icon={<Copy size={15} />}
              onClick={() => void copyTemplate()}
            >
              {copied ? 'Copied' : 'Copy'}
            </Button>
          </div>
          <pre className="mt-3 overflow-x-auto rounded-sm bg-md-surface p-4 text-label-md leading-relaxed text-md-on-surface-variant">
            {ENV_TEMPLATE}
          </pre>
          <p className="mt-3 text-label-sm text-md-on-surface-variant">
            Restart <code>npm run dev</code> after editing — Vite only reads env files at startup.
          </p>
        </Card>
      </div>
    </div>
  );
}
