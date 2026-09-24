import { describe, expect, it } from 'vitest';
import { failedRfq, extractedRfq, pendingExtractionRfq } from '../src/tests/fixtures/rfqFixtures';
import { isFailedRfq, rfqStatusLabel } from '../src/utils/rfqState';

describe('RFQ state fixtures', () => {
  it('preserves extracted canonical fields', () => {
    expect(extractedRfq.status).toBe('Quoted');
    expect(extractedRfq.part_number).toBe('32-11-45-01');
    expect(extractedRfq.quantity).toBe(2);
    expect(extractedRfq.customer_email).toContain('@');
  });

  it('represents pending extraction without invented fields', () => {
    expect(pendingExtractionRfq.status).toBe('Pending_Extraction');
    expect(pendingExtractionRfq.part_number).toBeUndefined();
    expect(pendingExtractionRfq.quantity).toBeUndefined();
  });

  it('identifies failed extraction as non-mutatable', () => {
    expect(isFailedRfq(failedRfq)).toBe(true);
    expect(rfqStatusLabel(failedRfq)).toBe('Intake Failed - Extraction Error');
  });
});
