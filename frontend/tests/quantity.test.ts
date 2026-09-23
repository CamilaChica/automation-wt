import { describe, expect, it } from 'vitest';

import { normalizeQuantityInput } from '../src/utils/quantity';

describe('normalizeQuantityInput', () => {
  it('removes leading zero formatting while preserving the numeric value', () => {
    expect(normalizeQuantityInput('04')).toBe(4);
    expect(normalizeQuantityInput('0007')).toBe(7);
  });

  it('clamps invalid or empty values to a minimum of 1', () => {
    expect(normalizeQuantityInput('')).toBe(1);
    expect(normalizeQuantityInput('0')).toBe(1);
    expect(normalizeQuantityInput('-3')).toBe(1);
  });
});