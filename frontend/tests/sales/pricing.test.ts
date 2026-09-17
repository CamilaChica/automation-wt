import { describe, expect, it } from 'vitest';
import { calculateAutomatedQuote } from '../../src/testing/engines/pricingEngine';

describe('automated pricing engine', () => {
  it('inflates margin by 15 points for low stock critical components', () => {
    const result = calculateAutomatedQuote({
      baseUnitCost: 1000,
      baseMarginPercent: 20,
      stockAvailable: 1,
      requestedQuantity: 5,
      isCriticalFlightComponent: true,
      creditApproved: true,
    });

    expect(result.approved).toBe(true);
    expect(result.appliedMarginPercent).toBe(35);
    expect(result.unitPrice).toBe(1350);
  });

  it('rejects RFQs when customer credit checks fail', () => {
    const result = calculateAutomatedQuote({
      baseUnitCost: 1000,
      baseMarginPercent: 20,
      stockAvailable: 10,
      requestedQuantity: 1,
      isCriticalFlightComponent: false,
      creditApproved: false,
    });

    expect(result.approved).toBe(false);
    expect(result.rejectionReason).toBe('CUSTOMER_CREDIT_CHECK_FAILED');
  });
});
