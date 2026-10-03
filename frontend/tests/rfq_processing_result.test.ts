import { describe, expect, it } from 'vitest';
import { describeRfqProcessingResult } from '../src/utils/rfqProcessingResult';

describe('RFQ processing feedback', () => {
  it('reports quote dispatch only for a confirmed Quote_Sent status', () => {
    expect(describeRfqProcessingResult('RFQ-TEST', { status: 'Quote_Sent', quote_id: 'Q-TEST' })).toEqual({
      type: 'success',
      message: 'RFQ-TEST: Quote sent. Email dispatch confirmed; inbox receipt is not verified.',
    });
  });

  it.each(['QUEUED', 'DRY_RUN', 'UNKNOWN'])('does not report conflicting %s delivery as sent', transmission_status => {
    const result = describeRfqProcessingResult('RFQ-TEST', { status: 'Quote_Sent', transmission_status });
    expect(result.type).toBe('error');
    expect(result.message).toContain('inconsistent delivery status');
    expect(result.message).not.toContain('Email dispatch confirmed');
  });

  it('distinguishes an outbox queue from completed email dispatch', () => {
    const result = describeRfqProcessingResult('RFQ-TEST', {
      status: 'Quote_Dispatch_Pending',
      transmission_status: 'QUEUED',
      email_body: 'Private customer email body',
    });
    expect(result.type).toBe('info');
    expect(result.message).toContain('Email dispatch is not confirmed');
    expect(result.message).toContain('QUEUED');
    expect(result.message).not.toContain('Private customer');
  });

  it.each(['Intake_Failed', 'Quote_Dispatch_Failed', 'Verification_Halted', 'Compliance_Halted'])(
    'shows %s as an error even when the API returns HTTP 200',
    status => {
      const result = describeRfqProcessingResult('RFQ-TEST', { status, error: 'Required certificate is missing.' });
      expect(result.type).toBe('error');
      expect(result.message).toContain('Required certificate is missing.');
      expect(result.message).not.toContain('Email dispatch confirmed');
    },
  );

  it('keeps failed statuses visible even without an error field', () => {
    expect(describeRfqProcessingResult('RFQ-TEST', { status: 'Quote_Dispatch_Failed' }).type).toBe('error');
  });

  it('preserves paused workflow reasons', () => {
    const result = describeRfqProcessingResult('RFQ-TEST', { status: 'Automation_Paused', reason: 'Waiting for review.' });
    expect(result.type).toBe('info');
    expect(result.message).toContain('Waiting for review.');
    expect(result.message).not.toContain('Email dispatch confirmed');
  });

  it.each(['Supplier_Request_Sent', 'Pending_Internal_Review', 'Pending_Approval', 'Pricing'])(
    'does not treat %s as a customer quote dispatch',
    status => {
      const result = describeRfqProcessingResult('RFQ-TEST', { status, message: 'Workflow detail.' });
      expect(result.type).toBe('info');
      expect(result.message).toContain('Workflow detail.');
      expect(result.message).not.toContain('Email dispatch confirmed');
    },
  );

  it.each([undefined, {}, { message: 'Completed.' }, { status: '   ' }])(
    'reports a missing workflow status explicitly',
    response => {
      const result = describeRfqProcessingResult('RFQ-TEST', response);
      expect(result.type).toBe('error');
      expect(result.message).toContain('no workflow status');
    },
  );

  it('prioritizes workflow errors over a sent status', () => {
    const result = describeRfqProcessingResult('RFQ-TEST', { status: 'Quote_Sent', error: 'Dispatch failed.' });
    expect(result.type).toBe('error');
    expect(result.message).toContain('Dispatch failed.');
    expect(result.message).not.toContain('Email dispatch confirmed');
  });
});
