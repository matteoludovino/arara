const TZ = 'America/Sao_Paulo';

export const dateTime = (iso: string | null | undefined) =>
  iso
    ? new Intl.DateTimeFormat('pt-BR', { timeZone: TZ, day: '2-digit', month: '2-digit', year: '2-digit', hour: '2-digit', minute: '2-digit' }).format(new Date(iso))
    : '—';

export const time = (iso: string) => new Intl.DateTimeFormat('pt-BR', { timeZone: TZ, hour: '2-digit', minute: '2-digit' }).format(new Date(iso));

/** "2026-11-12" (a calendar day, no time zone) → "12/11/2026". */
export const day = (isoDate: string | null | undefined) => (isoDate ? isoDate.split('-').reverse().join('/') : '—');

/** Today in the store's time zone, as the API wants it: "2026-11-12". */
export function today(offsetDays = 0): string {
  const date = new Date(Date.now() + offsetDays * 86_400_000);
  return new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(date);
}

export const int = (n: number) => new Intl.NumberFormat('pt-BR').format(n);

export const percent = (value: string | null | undefined) => (value == null ? '—' : `${value.replace('.', ',')}%`);

export const signed = (n: number) => (n > 0 ? `+${n}` : String(n));
