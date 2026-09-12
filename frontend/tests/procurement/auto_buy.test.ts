import { describe, expect, it } from 'vitest';
import { evaluateAutoBuy } from '../../src/testing/engines/procurementEngine';

describe('procurement auto-buy engine', () => {
  it('generates vendor PO when condition, trace docs, and margin all match', () => {
    const decision = evaluateAutoBuy(
      {
        partNumber: 'AOG-9981',
        requestedCondition: 'FN',
        quantity: 1,
        customerUnitPrice: 14000,
      },
      {
        supplierId: 'SUP-001',
        partNumber: 'AOG-9981',
        offeredCondition: 'FN',
        availableQuantity: 2,
        supplierUnitCost: 10000,
        certificateType: 'FAA 8130-3',
      },
      20
    );

    expect(decision.approved).toBe(true);
    expect(decision.vendorPoGenerated).toBe(true);
    expect(decision.computedMarginPercent).toBeCloseTo(28.57, 2);
  });

  it('rejects supplier offer on condition mismatch', () => {
    const decision = evaluateAutoBuy(
      {
        partNumber: 'AOG-9981',
        requestedCondition: 'FN',
        quantity: 1,
        customerUnitPrice: 14000,
      },
      {
        supplierId: 'SUP-001',
        partNumber: 'AOG-9981',
        offeredCondition: 'OH',
        availableQuantity: 2,
        supplierUnitCost: 10000,
        certificateType: 'FAA 8130-3',
      },
      20
    );

    expect(decision.approved).toBe(false);
    expect(decision.reason).toBe('CONDITION_MISMATCH');
  });
});
