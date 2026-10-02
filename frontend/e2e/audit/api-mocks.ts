import type { BrowserContext, Request } from '@playwright/test';

export interface AuditMockStats {
  apiRequests: number;
  mockedMutations: number;
}

const sampleRfqs = [{
  id: 'RFQ-AUDIT-1001',
  customer_name: 'Audit Customer',
  customer_email: 'customer@example.test',
  status: 'Quote_Sent',
  part_number: '32-11-45-01',
  quantity: 1,
  created_at: '2026-09-01T12:00:00Z',
}];

function jsonBody(body: unknown): string {
  return JSON.stringify(body);
}

function payloadFor(request: Request, path: string, otpRole: () => string): unknown {
  const method = request.method().toUpperCase();
  if (path.endsWith('/ready')) {
    return { status: 'ready', database: { healthy: true }, persistence: { storage_engine: 'mock' } };
  }
  if (path.endsWith('/auth/csrf')) return { csrf_token: 'audit-csrf' };
  if (path.endsWith('/auth/otp/request')) {
    return { challenge_id: 'audit-challenge', development_otp: '123456' };
  }
  if (path.endsWith('/auth/otp/verify')) {
    const role = otpRole();
    return {
      access_token: `audit-${role.toLowerCase()}-session`,
      token_type: 'bearer',
      role,
      email: role === 'ROLE_CUSTOMER' ? 'customer@example.test' : 'operator@wingedtycoons.com',
    };
  }
  if (path.endsWith('/internal/mailboxes/health')) {
    return { sales_mailbox: 'ok', purchasing_mailbox: 'ok', authenticated_user: 'operator@wingedtycoons.com' };
  }
  if (path.endsWith('/internal/profile')) {
    return { email: 'operator@wingedtycoons.com', display_name: 'Audit Operator', job_title: 'QA', is_online: true };
  }
  if (path.endsWith('/internal/work-hours') || path.endsWith('/internal/hr/work-hours')) {
    return { month: '2026-09', employees: [] };
  }
  if (path.endsWith('/voice/dashboard')) return { inventory: [], requests: [], human_queue: [] };
  if (path.endsWith('/rfqs') && method === 'GET') return sampleRfqs;
  if (/\/rfqs\/[^/]+$/.test(path) && method === 'GET') {
    return {
      rfq: sampleRfqs[0],
      items: [{
        id: 'RFQ-ITEM-AUDIT-1', rfq_id: sampleRfqs[0].id,
        requested_part_number: '32-11-45-01', resolved_part_number: '32-11-45-01',
        quantity: 1, uom: 'EA', condition_preference: 'NE',
      }],
      logs: [],
      quote_details: {
        quote: {
          id: 'QTE-1001', rfq_id: sampleRfqs[0].id, subtotal: 125,
          shipping_cost: 0, total_amount: 125, status: 'Sent', version: 1,
          valid_until: '2026-12-31', lead_time_days: 7,
        },
        items: [{
          id: 'QUOTE-ITEM-AUDIT-1', quote_id: 'QTE-1001', part_number: '32-11-45-01',
          quantity: 1, unit_price: 125, condition: 'NE', certificate_type: 'FAA 8130-3',
          compliance_status: 'Pass', lead_time_days: 7,
        }],
      },
    };
  }
  if (path.endsWith('/catalog/search')) {
    return [{ part_number: '32-11-45-01', condition_code: 'NE', quantity_available: 3, certificate_type: 'FAA 8130-3', has_full_trace: true }];
  }
  if (/\/shipments\/track\/[^/]+$/.test(path)) {
    return {
      shipment_id: 'SHIP-AUDIT-1', status: 'In Transit', part_numbers: ['32-11-45-01'], quantity: 1,
      carrier: 'Audit Carrier', tracking_number: 'AUDIT-TRACK-1001', estimated_delivery: '2026-10-05', events: [],
    };
  }
  if (path.endsWith('/internal/automation-events')) return [];
  if (path.endsWith('/internal/shipments') || path.endsWith('/suppliers') || path.endsWith('/supplier-offers')) return [];
  if (path.endsWith('/auth/otp/request')) return { challenge_id: 'audit-challenge' };
  if (method === 'POST' && path.endsWith('/rfqs/intake')) {
    return { rfq_id: 'RFQ-AUDIT-NEW', status: 'Pending_Internal_Review', message: 'Audit request accepted.' };
  }
  if (method === 'POST' && path.endsWith('/attachments')) {
    return { attachment_id: 'ATT-AUDIT-1', filename: 'audit.pdf', status: 'ACCEPTED' };
  }
  if (method === 'POST' && path.endsWith('/purchase-orders')) {
    return { status: 'Pending_PO_Review', po_number: 'PO-4321', quote_id: 'QTE-1001' };
  }
  if (method === 'POST' && path.endsWith('/quotes/QTE-1001/approve')) {
    return { status: 'Quote_Dispatch_Pending', quote_id: 'QTE-1001', message: 'Quote queued.' };
  }
  if (method === 'POST' && path.endsWith('/auth/otp/verify')) {
    const role = otpRole();
    return { access_token: `audit-${role}-session`, token_type: 'bearer', role, email: 'audit@example.test' };
  }
  return method === 'GET' ? [] : { status: 'mocked', ok: true };
}

export async function installAuditApiMocks(context: BrowserContext): Promise<AuditMockStats> {
  const stats: AuditMockStats = { apiRequests: 0, mockedMutations: 0 };
  let requestedRole = 'ROLE_CUSTOMER';

  await context.route('**/api/**', async route => {
    const request = route.request();
    const url = new URL(request.url());
    stats.apiRequests += 1;
    if (url.pathname.endsWith('/auth/otp/request')) {
      try {
        const body = request.postDataJSON() as { role?: string };
        requestedRole = body.role === 'ROLE_INTERNAL' ? 'ROLE_ADMIN' : 'ROLE_CUSTOMER';
      } catch {
        requestedRole = 'ROLE_CUSTOMER';
      }
    }
    if (!['GET', 'HEAD', 'OPTIONS'].includes(request.method().toUpperCase())) stats.mockedMutations += 1;
    const body = payloadFor(request, url.pathname, () => requestedRole);
    const headers: Record<string, string> = url.pathname.endsWith('/auth/csrf')
      ? { 'x-csrf-token': 'audit-csrf' }
      : {};
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      headers,
      body: jsonBody(body),
    });
  });

  return stats;
}