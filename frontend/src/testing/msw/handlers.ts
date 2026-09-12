import { http, HttpResponse, delay } from 'msw';

export type SignatureScenario = 'valid' | 'corrupted' | 'timeout_webhook';

const signedPdfPayload =
  'JVBERi0xLjQKJeLjz9MKMSAwIG9iago8PCAvVHlwZSAvQ2F0YWxvZyA+PgplbmRvYmoK';

const corruptedPayload = 'NOT_A_VALID_BASE64_PDF_PAYLOAD';

export const thirdPartyHandlers = [
  http.post('*/third-party/fedex/rates', async () => {
    return HttpResponse.json({
      provider: 'FedEx',
      service: 'Priority Overnight',
      tracking_id: 'FDX-TEST-0001',
      eta_hours: 14,
      quote_usd: 420,
    });
  }),
  http.post('*/third-party/dhl/rates', async () => {
    return HttpResponse.json({
      provider: 'DHL',
      service: 'Express Worldwide',
      tracking_id: 'DHL-TEST-0007',
      eta_hours: 18,
      quote_usd: 390,
    });
  }),
  http.post('*/third-party/esign/sign', async ({ request }) => {
    const body = (await request.json()) as { scenario?: SignatureScenario };
    const scenario = body.scenario ?? 'valid';

    if (scenario === 'corrupted') {
      return HttpResponse.json({
        signed_pdf_base64: corruptedPayload,
        digest: 'sha256:bad-digest',
        status: 'signed',
      });
    }

    if (scenario === 'timeout_webhook') {
      await delay(2_500);
      return HttpResponse.json({
        signed_pdf_base64: signedPdfPayload,
        digest: 'sha256:timeout-case',
        status: 'webhook_timeout',
      });
    }

    return HttpResponse.json({
      signed_pdf_base64: signedPdfPayload,
      digest: 'sha256:ok-digest',
      status: 'signed',
    });
  }),
];
