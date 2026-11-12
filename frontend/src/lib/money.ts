/**
 * Money travels as decimal strings ("79.90") and is added up here in integer cents: never in
 * floating point. The server has the last word on every total; the screen only previews it.
 */

/** "79.90", "79,90", "1.234,50" or 79.9 → 7990. NaN when it isn't an amount. */
export function toCents(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return Number.NaN;
  let text = String(value).trim().replace(/^R\$\s*/, '');
  if (text.includes(',')) text = text.replace(/\./g, '').replace(',', '.'); // Brazilian typing
  if (!/^-?\d+(\.\d+)?$/.test(text)) return Number.NaN;
  const negative = text.startsWith('-');
  const [whole = '0', fraction = ''] = text.replace('-', '').split('.');
  const padded = (fraction + '000').slice(0, 3);
  // Half up on the third decimal, like the server (ROUND_HALF_UP).
  const cents = Number(whole) * 100 + Number(padded.slice(0, 2)) + (Number(padded[2]) >= 5 ? 1 : 0);
  return negative ? -cents : cents;
}

/** 7990 → "79.90", what the API expects. */
export function fromCents(cents: number): string {
  const sign = cents < 0 ? '-' : '';
  const abs = Math.abs(cents);
  return `${sign}${Math.floor(abs / 100)}.${String(abs % 100).padStart(2, '0')}`;
}

const BRL = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });

/** "79.90" or 7990 cents → "R$ 79,90" (a dash for nothing). */
export function brl(value: string | null | undefined): string {
  const cents = toCents(value);
  return Number.isNaN(cents) ? '—' : BRL.format(cents / 100);
}

export const brlCents = (cents: number) => BRL.format(cents / 100);
