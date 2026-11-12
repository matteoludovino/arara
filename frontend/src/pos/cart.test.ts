import { describe, expect, it } from 'vitest';
import type { Lookup } from '../lib/types';
import { addToCart, discountCents, parseScan, pieces, setQuantity, subtotalCents } from './cart';

const shirt = (id: number, price = '79.90'): Lookup => ({
  id,
  sku: `CAM-001-PRE-${id}`,
  product: { id: 1, reference: 'CAM-001', name: 'Camiseta' },
  size: 'M',
  color: 'Preto',
  is_active: true,
  current_price: price,
});

describe('scanning', () => {
  it.each([
    ['7891234567895', { code: '7891234567895', quantity: 1 }],
    ['3*7891234567895', { code: '7891234567895', quantity: 3 }],
    ['2x CAM-001-PRE-M', { code: 'CAM-001-PRE-M', quantity: 2 }],
    ['0*123', null],
    ['', null],
  ])('%s', (text, expected) => expect(parseScan(text)).toEqual(expected));
});

describe('the cart', () => {
  it('merges the same SKU and puts it on top', () => {
    let cart = addToCart([], shirt(1), 1);
    cart = addToCart(cart, shirt(2), 2);
    cart = addToCart(cart, shirt(1), 2);
    expect(cart.map((l) => [l.variant, l.quantity])).toEqual([
      [1, 3],
      [2, 2],
    ]);
    expect(pieces(cart)).toBe(5);
    expect(subtotalCents(cart)).toBe(5 * 7990);
  });

  it('drops a line set to zero', () => {
    const cart = setQuantity(addToCart([], shirt(1), 2), 1, 0);
    expect(cart).toEqual([]);
  });
});

describe('discounts', () => {
  it.each([
    ['', 0],
    ['15,98', 1598],
    ['10%', 1598], // 10% of 159.80
    ['12,5%', 1998], // 19.975 rounds half up
    ['abc', Number.NaN],
  ])('%s', (typed, cents) => expect(discountCents(typed, 15980)).toBe(cents));
});
