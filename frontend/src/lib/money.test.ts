import { describe, expect, it } from 'vitest';
import { brl, fromCents, toCents } from './money';

describe('toCents', () => {
  it.each([
    ['79.90', 7990],
    ['79,90', 7990],
    ['1.234,50', 123450],
    ['R$ 10', 1000],
    [0.1, 10],
    ['0.005', 1], // half up, like the server
    ['0.004', 0],
    ['-5.5', -550],
  ])('%s → %i', (input, cents) => expect(toCents(input)).toBe(cents));

  it.each(['', 'abc', '1,2,3', null])('rejects %s', (input) => expect(toCents(input)).toBeNaN());

  it('adds up where floating point does not', () => {
    expect(0.1 + 0.2).not.toBe(0.3);
    expect(fromCents(toCents('0.1') + toCents('0.2'))).toBe('0.30');
  });
});

describe('fromCents and brl', () => {
  it('formats', () => {
    expect([fromCents(7990), fromCents(5), fromCents(-410)]).toEqual(['79.90', '0.05', '-4.10']);
    expect(brl('1234.5').replace(/\s/g, ' ')).toBe('R$ 1.234,50');
    expect(brl(null)).toBe('—');
  });
});
