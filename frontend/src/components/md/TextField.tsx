import {
  forwardRef,
  useId,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from 'react';

import { cn } from '@/lib/cn';

/**
 * MD3 *filled* text field: rounded top corners, square bottom, and a 2px bottom
 * border that turns primary on focus. The label is always visible above the
 * value rather than animating into the border, which keeps it readable at the
 * 56px height and avoids the placeholder-as-label accessibility trap.
 */

const FIELD_SHELL =
  'group relative flex w-full flex-col rounded-t-sm border-b-2 bg-md-surface-container-low px-4 transition-colors duration-short ease-md';

// Hover is scoped to the unfocused state on purpose. Tailwind emits `hover:`
// after `focus-within:`, so a plain `hover:border-md-outline` would win while the
// cursor rests on a focused field and leave the underline grey instead of
// primary — exactly when the focus state most needs to read clearly.
const FIELD_BORDER =
  'border-md-outline-variant [&:hover:not(:focus-within)]:border-md-outline focus-within:border-md-primary';

interface BaseProps {
  label: string;
  hint?: string;
  error?: string | null;
  leading?: ReactNode;
  trailing?: ReactNode;
  suffix?: string;
  containerClassName?: string;
}

interface TextFieldProps extends BaseProps, Omit<InputHTMLAttributes<HTMLInputElement>, 'className'> {
  inputClassName?: string;
}

export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  {
    label,
    hint,
    error,
    leading,
    trailing,
    suffix,
    containerClassName,
    inputClassName,
    id,
    required,
    ...rest
  },
  ref,
) {
  const autoId = useId();
  const fieldId = id ?? autoId;
  const describedBy = error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined;

  return (
    <div className={cn('w-full', containerClassName)}>
      <div
        className={cn(
          FIELD_SHELL,
          'h-14 justify-center',
          error ? 'border-md-error' : FIELD_BORDER,
        )}
      >
        <div className="flex items-center gap-3">
          {leading && <span className="text-md-on-surface-variant">{leading}</span>}
          <div className="min-w-0 flex-1">
            <label
              htmlFor={fieldId}
              className={cn(
                'block text-label-sm transition-colors duration-short',
                error ? 'text-md-error' : 'text-md-on-surface-variant group-focus-within:text-md-primary',
              )}
            >
              {label}
              {required && <span aria-hidden> *</span>}
            </label>
            <div className="flex items-baseline gap-1.5">
              <input
                ref={ref}
                id={fieldId}
                required={required}
                aria-invalid={error ? true : undefined}
                aria-describedby={describedBy}
                className={cn(
                  'w-full bg-transparent text-body-md text-md-on-surface outline-none',
                  'placeholder:text-md-on-surface-variant/60',
                  inputClassName,
                )}
                {...rest}
              />
              {suffix && (
                <span className="shrink-0 text-label-md text-md-on-surface-variant">{suffix}</span>
              )}
            </div>
          </div>
          {trailing && <span className="text-md-on-surface-variant">{trailing}</span>}
        </div>
      </div>
      <FieldMessage id={fieldId} error={error} hint={hint} />
    </div>
  );
});

interface SelectFieldProps
  extends BaseProps,
    Omit<SelectHTMLAttributes<HTMLSelectElement>, 'className'> {
  children: ReactNode;
}

export const SelectField = forwardRef<HTMLSelectElement, SelectFieldProps>(function SelectField(
  { label, hint, error, leading, containerClassName, id, children, ...rest },
  ref,
) {
  const autoId = useId();
  const fieldId = id ?? autoId;

  return (
    <div className={cn('w-full', containerClassName)}>
      <div className={cn(FIELD_SHELL, 'h-14 justify-center', error ? 'border-md-error' : FIELD_BORDER)}>
        <div className="flex items-center gap-3">
          {leading && <span className="text-md-on-surface-variant">{leading}</span>}
          <div className="min-w-0 flex-1">
            <label
              htmlFor={fieldId}
              className="block text-label-sm text-md-on-surface-variant group-focus-within:text-md-primary"
            >
              {label}
            </label>
            <select
              ref={ref}
              id={fieldId}
              aria-describedby={error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined}
              className="w-full appearance-none bg-transparent pr-6 text-body-md text-md-on-surface outline-none"
              {...rest}
            >
              {children}
            </select>
          </div>
          <svg
            aria-hidden
            viewBox="0 0 20 20"
            className="pointer-events-none h-4 w-4 shrink-0 text-md-on-surface-variant"
          >
            <path d="M5 7.5 10 12.5 15 7.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
          </svg>
        </div>
      </div>
      <FieldMessage id={fieldId} error={error} hint={hint} />
    </div>
  );
});

interface TextAreaProps
  extends BaseProps,
    Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'className'> {}

export const TextAreaField = forwardRef<HTMLTextAreaElement, TextAreaProps>(function TextAreaField(
  { label, hint, error, containerClassName, id, rows = 3, ...rest },
  ref,
) {
  const autoId = useId();
  const fieldId = id ?? autoId;

  return (
    <div className={cn('w-full', containerClassName)}>
      <div className={cn(FIELD_SHELL, 'py-3', error ? 'border-md-error' : FIELD_BORDER)}>
        <label
          htmlFor={fieldId}
          className="block text-label-sm text-md-on-surface-variant group-focus-within:text-md-primary"
        >
          {label}
        </label>
        <textarea
          ref={ref}
          id={fieldId}
          rows={rows}
          aria-describedby={error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined}
          className="w-full resize-none bg-transparent text-body-md text-md-on-surface outline-none placeholder:text-md-on-surface-variant/60"
          {...rest}
        />
      </div>
      <FieldMessage id={fieldId} error={error} hint={hint} />
    </div>
  );
});

function FieldMessage({
  id,
  error,
  hint,
}: {
  id: string;
  error?: string | null;
  hint?: string;
}) {
  if (!error && !hint) return null;
  return (
    <p
      id={error ? `${id}-error` : `${id}-hint`}
      role={error ? 'alert' : undefined}
      className={cn(
        'mt-1.5 px-4 font-prose text-label-sm',
        error ? 'text-md-error' : 'text-md-on-surface-variant',
      )}
    >
      {error ?? hint}
    </p>
  );
}
