import { AnimatePresence, motion } from 'framer-motion';
import {
  AlertTriangle,
  ArrowUp,
  Loader2,
  MessageCircleHeart,
  Plus,
  Sparkles,
  Trash2,
} from 'lucide-react';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';

import {
  Badge,
  Button,
  Card,
  EmptyState,
  IconButton,
  Skeleton,
  useToast,
} from '@/components/md';
import {
  useAiStatus,
  useChatMessages,
  useChatSessions,
  useChatSuggestions,
  useDeleteChatSession,
  useMe,
  useSendChatMessage,
} from '@/hooks/queries';
import { cn } from '@/lib/cn';
import { firstName, timeOfDay } from '@/lib/format';
import type { ChatMessage } from '@/lib/types';

/**
 * The coach. Every request re-sends a snapshot of the user's real numbers plus
 * the last turns of this conversation, so answers are grounded and follow-ups
 * resolve. History is persisted per session in Postgres, not kept in component
 * state, which means it survives reloads and device switches.
 */
export function Coach() {
  const me = useMe();
  const toast = useToast();
  const aiStatus = useAiStatus();
  const sessions = useChatSessions();
  const suggestions = useChatSuggestions();
  const deleteSession = useDeleteChatSession();
  const send = useSendChatMessage();

  const [sessionId, setSessionId] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  /** Shown immediately so the conversation feels responsive before the round trip. */
  const [pending, setPending] = useState<string | null>(null);

  const messages = useChatMessages(sessionId);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Open the most recent conversation on first load.
  useEffect(() => {
    if (sessionId || !sessions.data?.sessions.length) return;
    setSessionId(sessions.data.sessions[0].id);
  }, [sessions.data, sessionId]);

  const thread: ChatMessage[] = messages.data?.messages ?? [];

  useLayoutEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' });
  }, [thread.length, pending]);

  async function submit(text: string) {
    const content = text.trim();
    if (!content || send.isPending) return;

    setDraft('');
    setPending(content);
    try {
      const reply = await send.mutateAsync({ content, sessionId: sessionId ?? undefined });
      setSessionId(reply.session_id);
      if (reply.degraded) {
        toast.show('AI is unavailable — showing your raw numbers instead.', 'info');
      }
    } catch (caught) {
      toast.error(caught instanceof Error ? caught.message : 'Message failed to send.');
      setDraft(content);
    } finally {
      setPending(null);
    }
  }

  const geminiMissing = aiStatus.data && !aiStatus.data.gemini_configured;

  return (
    <div className="grid gap-5 lg:grid-cols-[16rem_1fr]">
      {/* -- Conversations ------------------------------------------------ */}
      <aside className="space-y-3">
        <Button
          fullWidth
          variant="tonal"
          icon={<Plus size={18} />}
          onClick={() => {
            setSessionId(null);
            setDraft('');
            inputRef.current?.focus();
          }}
        >
          New conversation
        </Button>

        {sessions.isLoading ? (
          <div className="space-y-2">
            {[0, 1, 2].map((index) => (
              <Skeleton key={index} className="h-12 w-full rounded-sm" />
            ))}
          </div>
        ) : (
          <ul className="no-scrollbar flex gap-2 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible">
            {sessions.data?.sessions.map((session) => (
              <li key={session.id} className="shrink-0 lg:shrink">
                <div
                  className={cn(
                    'group flex items-center gap-1 rounded-sm transition-colors duration-short',
                    session.id === sessionId
                      ? 'bg-md-secondary-container text-md-on-secondary-container'
                      : 'bg-md-surface-container hover:bg-md-surface-container-high',
                  )}
                >
                  <button
                    type="button"
                    onClick={() => setSessionId(session.id)}
                    className="min-w-0 flex-1 px-3 py-2.5 text-left"
                  >
                    <span className="block max-w-[12rem] truncate text-label-md font-medium lg:max-w-none">
                      {session.title}
                    </span>
                    <span className="block text-label-sm opacity-70">
                      {new Date(session.last_message_at).toLocaleDateString(undefined, {
                        day: 'numeric',
                        month: 'short',
                      })}
                    </span>
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete ${session.title}`}
                    onClick={() =>
                      deleteSession.mutate(session.id, {
                        onSuccess: () => {
                          if (session.id === sessionId) setSessionId(null);
                          toast.success('Conversation deleted.');
                        },
                      })
                    }
                    className="mr-1 rounded-full p-1.5 opacity-0 transition-opacity hover:bg-md-error/10 hover:text-md-error focus-visible:opacity-100 group-hover:opacity-100"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </aside>

      {/* -- Thread ------------------------------------------------------ */}
      <Card tone="container" padded={false} className="flex min-h-[70dvh] flex-col overflow-hidden">
        <header className="flex items-center justify-between gap-3 border-b border-md-outline-variant/50 px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="grid h-10 w-10 place-items-center rounded-full bg-md-primary text-md-on-primary">
              <MessageCircleHeart size={19} />
            </span>
            <div>
              <p className="text-title-md font-medium">Your coach</p>
              <p className="text-label-sm text-md-on-surface-variant">
                Reads your log · {aiStatus.data?.model ?? 'AI'}
              </p>
            </div>
          </div>
          {geminiMissing && (
            <Badge tone="warning" icon={<AlertTriangle size={12} />}>
              No AI key
            </Badge>
          )}
        </header>

        <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-5">
          {messages.isLoading && sessionId && (
            <div className="space-y-3">
              <Skeleton className="ml-auto h-16 w-2/3 rounded-lg" />
              <Skeleton className="h-24 w-4/5 rounded-lg" />
            </div>
          )}

          {!sessionId && thread.length === 0 && (
            <div className="py-6">
              <EmptyState
                icon={<Sparkles size={22} />}
                title={`Ask anything, ${firstName(me.data?.profile.full_name) || 'friend'}`}
                description="It can see your targets, today's log, your 14-day averages and your weight trend. It cannot see anything you have not logged."
              />
              <div className="mx-auto mt-2 flex max-w-lg flex-wrap justify-center gap-2">
                {(suggestions.data?.prompts ?? []).map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    onClick={() => void submit(prompt)}
                    className="rounded-full border border-md-outline-variant px-4 py-2 text-label-md text-md-on-surface-variant transition-all duration-medium ease-md hover:-translate-y-0.5 hover:border-md-primary hover:text-md-primary active:scale-95"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>
          )}

          <AnimatePresence initial={false}>
            {thread.map((message) => (
              <motion.div
                key={message.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.25, ease: [0.2, 0, 0, 1] }}
                className={cn('flex', message.role === 'user' ? 'justify-end' : 'justify-start')}
              >
                <div
                  className={cn(
                    'max-w-[85%] rounded-lg px-4 py-3 text-body-md shadow-e1 sm:max-w-[75%]',
                    message.role === 'user'
                      ? 'rounded-br-xs bg-md-primary text-md-on-primary'
                      : 'rounded-bl-xs bg-md-surface-container-low text-md-on-surface',
                  )}
                >
                  <p className="whitespace-pre-wrap break-words">{message.content}</p>
                  {message.created_at && (
                    <p
                      className={cn(
                        'mt-1.5 text-label-sm',
                        message.role === 'user'
                          ? 'text-md-on-primary/70'
                          : 'text-md-on-surface-variant/70',
                      )}
                    >
                      {timeOfDay(message.created_at)}
                    </p>
                  )}
                </div>
              </motion.div>
            ))}
          </AnimatePresence>

          {pending && (
            <>
              <div className="flex justify-end">
                <div className="max-w-[85%] rounded-lg rounded-br-xs bg-md-primary/80 px-4 py-3 text-body-md text-md-on-primary sm:max-w-[75%]">
                  <p className="whitespace-pre-wrap break-words">{pending}</p>
                </div>
              </div>
              <div className="flex justify-start">
                <div className="flex items-center gap-2 rounded-lg rounded-bl-xs bg-md-surface-container-low px-4 py-3 text-md-on-surface-variant">
                  <Loader2 size={16} className="animate-spin" />
                  <span className="text-body-sm">Reading your log…</span>
                </div>
              </div>
            </>
          )}
        </div>

        {/* -- Composer -------------------------------------------------- */}
        <div className="border-t border-md-outline-variant/50 p-4">
          <div className="flex items-end gap-2 rounded-lg bg-md-surface-container-low p-2">
            <textarea
              ref={inputRef}
              value={draft}
              rows={1}
              onChange={(event) => {
                setDraft(event.target.value);
                // Grow with the content, capped so the thread stays visible.
                event.target.style.height = 'auto';
                event.target.style.height = `${Math.min(140, event.target.scrollHeight)}px`;
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault();
                  void submit(draft);
                }
              }}
              placeholder="Ask about your day, your macros, or what to eat next…"
              aria-label="Message your coach"
              className="max-h-36 min-h-[2.75rem] flex-1 resize-none bg-transparent px-3 py-2.5 text-body-md outline-none placeholder:text-md-on-surface-variant/60"
            />
            <IconButton
              label="Send message"
              variant="filled"
              disabled={!draft.trim() || send.isPending}
              onClick={() => void submit(draft)}
            >
              {send.isPending ? <Loader2 size={18} className="animate-spin" /> : <ArrowUp size={18} />}
            </IconButton>
          </div>
          <p className="mt-2 px-1 text-label-sm text-md-on-surface-variant/75">
            General fitness and nutrition guidance only — not medical advice. Enter sends,
            Shift+Enter adds a line.
          </p>
        </div>
      </Card>
    </div>
  );
}
