import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { thirdPartyMockServer } from '../../src/testing/msw/server';

describe('third-party mock services', () => {
  beforeAll(() => thirdPartyMockServer.listen({ onUnhandledRequest: 'error' }));
  afterEach(() => thirdPartyMockServer.resetHandlers());
  afterAll(() => thirdPartyMockServer.close());

  it('returns logistics rates from FedEx and DHL mocks', async () => {
    const fedex = await fetch('http://127.0.0.1/third-party/fedex/rates', {
      method: 'POST',
    }).then(res => res.json());
    const dhl = await fetch('http://127.0.0.1/third-party/dhl/rates', {
      method: 'POST',
    }).then(res => res.json());

    expect(fedex.provider).toBe('FedEx');
    expect(dhl.provider).toBe('DHL');
    expect(fedex.tracking_id).toContain('FDX');
    expect(dhl.tracking_id).toContain('DHL');
  });

  it('supports signed PDF, corrupted payload, and timeout webhook scenarios', async () => {
    const valid = await fetch('http://127.0.0.1/third-party/esign/sign', {
      method: 'POST',
      body: JSON.stringify({ scenario: 'valid' }),
      headers: { 'content-type': 'application/json' },
    }).then(res => res.json());
    expect(valid.status).toBe('signed');
    expect(valid.signed_pdf_base64.startsWith('JVBERi0')).toBe(true);

    const corrupted = await fetch('http://127.0.0.1/third-party/esign/sign', {
      method: 'POST',
      body: JSON.stringify({ scenario: 'corrupted' }),
      headers: { 'content-type': 'application/json' },
    }).then(res => res.json());
    expect(corrupted.status).toBe('signed');
    expect(corrupted.signed_pdf_base64).toBe('NOT_A_VALID_BASE64_PDF_PAYLOAD');

    thirdPartyMockServer.use(
      http.post('http://127.0.0.1/third-party/esign/sign', () => {
        return HttpResponse.json({ status: 'webhook_timeout' });
      })
    );
    const timeout = await fetch('http://127.0.0.1/third-party/esign/sign', {
      method: 'POST',
      body: JSON.stringify({ scenario: 'timeout_webhook' }),
      headers: { 'content-type': 'application/json' },
    }).then(res => res.json());
    expect(timeout.status).toBe('webhook_timeout');
  });
});
