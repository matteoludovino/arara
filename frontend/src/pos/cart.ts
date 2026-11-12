import { toCents } from '../lib/money';
import type { Lookup } from '../lib/types';

export interface CartLine {
  variant: number;
  sku: string;
  name: string;
  size: string;
  color: string;
  unitPrice: string;
  quantity: number;
}

/** "3*7891234567895" sells three; a plain code sells one. */
export function parseScan(text: string): { code: string; quantity: number } | null {
  const match = /^(?:(\d{1,3})\s*[*xX]\s*)?(\S+)$/.exec(text.trim());
  if (!match) return null;
  const quantity = match[1] ? Number(match[1]) : 1;
  return quantity > 0 ? { code: match[2]!, quantity } : null;
}

/** The same SKU scanned again adds to its line, which moves to the top (what was just scanned). */
export function addToCart(lines: CartLine[], item: Lookup, quantity: number): CartLine[] {
  const existing = lines.find((l) => l.variant === item.id);
  const line: CartLine = existing
    ? { ...existing, quantity: existing.quantity + quantity }
    : {
        variant: item.id,
        sku: item.sku,
        name: item.product.name,
        size: item.size,
        color: item.color,
        unitPrice: item.current_price ?? '0',
        quantity,
      };
  return [line, ...lines.filter((l) => l.variant !== item.id)];
}

export function setQuantity(lines: CartLine[], variant: number, quantity: number): CartLine[] {
  return quantity <= 0 ? lines.filter((l) => l.variant !== variant) : lines.map((l) => (l.variant === variant ? { ...l, quantity } : l));
}

export const lineCents = (line: CartLine) => toCents(line.unitPrice) * line.quantity;
export const subtotalCents = (lines: CartLine[]) => lines.reduce((sum, l) => sum + lineCents(l), 0);
export const pieces = (lines: CartLine[]) => lines.reduce((sum, l) => sum + l.quantity, 0);

/** A discount typed as "10%" or "15,00" (money), in cents of this subtotal. NaN if unreadable. */
export function discountCents(typed: string, subtotal: number): number {
  const text = typed.trim();
  if (!text) return 0;
  if (text.endsWith('%')) {
    const percent = toCents(text.slice(0, -1)); // in hundredths of a percent
    if (Number.isNaN(percent)) return Number.NaN;
    // Half up, in integers: subtotal × percent / 10000.
    return Math.floor((subtotal * percent + 5000) / 10000);
  }
  return toCents(text);
}
