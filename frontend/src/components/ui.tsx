import { type ButtonHTMLAttributes, type ComponentProps, type ReactNode, useEffect, useId, useRef } from 'react';

export const cx = (...classes: (string | false | null | undefined)[]) => classes.filter(Boolean).join(' ');

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'danger' | 'ghost';
  busy?: boolean;
};

export function Button({ variant = 'primary', busy, className, children, disabled, type = 'button', ...props }: ButtonProps) {
  return (
    <button
      {...props}
      type={type}
      disabled={disabled || busy}
      className={cx(
        'inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-600 disabled:cursor-not-allowed disabled:opacity-50',
        variant === 'primary' && 'bg-brand-600 text-white hover:bg-brand-700',
        variant === 'secondary' && 'border border-stone-300 bg-white text-stone-700 hover:bg-stone-50',
        variant === 'danger' && 'border border-red-200 bg-white text-red-700 hover:bg-red-50',
        variant === 'ghost' && 'text-stone-600 hover:bg-stone-100',
        className,
      )}
    >
      {busy ? 'Aguarde…' : children}
    </button>
  );
}

const control =
  'rounded-lg border border-stone-300 bg-white px-3 py-2 text-sm shadow-xs focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100 disabled:bg-stone-100';

/** A labelled control: the label is tied to the input by id (clickable, read by screen readers). */
export function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium text-stone-700">
        {label}
      </label>
      {children(id)}
      {hint && <p className="text-xs text-stone-500">{hint}</p>}
    </div>
  );
}

/** Full width unless the caller sets a width of its own. */
const controlClass = (className?: string, extra?: string) =>
  cx(control, !/(^|\s)w-/.test(className ?? '') && 'w-full', extra, className);

export const Input = ({ className, ...props }: ComponentProps<'input'>) => (
  <input {...props} className={controlClass(className)} />
);
export const Select = ({ className, ...props }: ComponentProps<'select'>) => (
  <select {...props} className={controlClass(className)} />
);
export const Textarea = ({ className, ...props }: ComponentProps<'textarea'>) => (
  <textarea {...props} className={controlClass(className, 'min-h-20')} />
);

/** Native <dialog>: focus trap, Esc to close and a backdrop for free. */
export function Dialog({
  open,
  onClose,
  title,
  children,
  wide,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
      // showModal focuses the first control (the close button): move to the one meant to start with.
      dialog.querySelector<HTMLElement>('[data-autofocus]')?.focus();
    }
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      className={cx('m-auto w-full rounded-2xl p-0 shadow-xl backdrop:bg-stone-900/40', wide ? 'max-w-3xl' : 'max-w-lg')}
    >
      {open && (
        <div className="p-6">
          <div className="mb-4 flex items-start justify-between gap-4">
            <h2 className="text-lg font-semibold text-stone-900">{title}</h2>
            <button
              type="button"
              onClick={onClose}
              className="rounded p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-700"
              aria-label="Fechar"
            >
              ✕
            </button>
          </div>
          {children}
        </div>
      )}
    </dialog>
  );
}

export function Alert({ tone = 'error', children }: { tone?: 'error' | 'warning' | 'info' | 'success'; children: ReactNode }) {
  return (
    <div
      role={tone === 'error' ? 'alert' : 'status'}
      className={cx(
        'rounded-lg border px-3 py-2 text-sm',
        tone === 'error' && 'border-red-200 bg-red-50 text-red-800',
        tone === 'warning' && 'border-amber-200 bg-amber-50 text-amber-900',
        tone === 'info' && 'border-sky-200 bg-sky-50 text-sky-900',
        tone === 'success' && 'border-emerald-200 bg-emerald-50 text-emerald-900',
      )}
    >
      {children}
    </div>
  );
}

/** A failed request, if any. */
export const ErrorAlert = ({ error }: { error: Error | null | undefined }) => (error ? <Alert>{error.message}</Alert> : null);

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-2xl font-semibold text-stone-900">{title}</h1>
        {description && <p className="mt-1 text-sm text-stone-500">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export const Card = ({ children, className }: { children: ReactNode; className?: string }) => (
  <div className={cx('rounded-2xl border border-stone-200 bg-white p-5 shadow-xs', className)}>{children}</div>
);

const BADGE = {
  neutral: 'bg-stone-100 text-stone-700',
  brand: 'bg-brand-50 text-brand-700',
  green: 'bg-emerald-50 text-emerald-800',
  amber: 'bg-amber-50 text-amber-800',
  red: 'bg-red-50 text-red-700',
  blue: 'bg-sky-50 text-sky-800',
};

export function Badge({ children, tone = 'neutral' }: { children: ReactNode; tone?: keyof typeof BADGE }) {
  return (
    <span className={cx('inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap', BADGE[tone])}>
      {children}
    </span>
  );
}

export const Empty = ({ children }: { children: ReactNode }) => (
  <p className="py-8 text-center text-sm text-stone-500">{children}</p>
);

export const Loading = () => <p className="py-8 text-center text-sm text-stone-500">Carregando…</p>;

/** A plain table: header labels, then rows. Numbers align right (`num` columns). */
export function Table({ head, children, num = [] }: { head: ReactNode[]; children: ReactNode; num?: number[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-stone-200 bg-white">
      <table className="w-full text-sm">
        <thead className="border-b border-stone-200 bg-stone-50 text-left text-xs font-medium tracking-wide text-stone-500 uppercase">
          <tr>
            {head.map((label, i) => (
              <th key={i} className={cx('px-3 py-2 whitespace-nowrap', num.includes(i) && 'text-right')}>
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-stone-100 [&_td]:px-3 [&_td]:py-2">{children}</tbody>
      </table>
    </div>
  );
}

export function Tabs<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (value: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <div role="tablist" className="mb-5 flex flex-wrap gap-1 border-b border-stone-200">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="tab"
          aria-selected={o.value === value}
          onClick={() => onChange(o.value)}
          className={cx(
            '-mb-px border-b-2 px-3 py-2 text-sm font-medium',
            o.value === value ? 'border-brand-600 text-brand-700' : 'border-transparent text-stone-500 hover:text-stone-800',
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** A labelled figure for a summary row. */
export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <div className="rounded-xl border border-stone-200 bg-white px-4 py-3">
      <p className="text-xs font-medium text-stone-500">{label}</p>
      <p className="mt-1 text-xl font-semibold text-stone-900 tabular-nums">{value}</p>
      {hint && <p className="mt-0.5 text-xs text-stone-500">{hint}</p>}
    </div>
  );
}

export const formData = (form: HTMLFormElement) => Object.fromEntries(new FormData(form)) as Record<string, string>;
