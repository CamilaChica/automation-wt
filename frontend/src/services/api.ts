import axios from 'axios';
import { RFQ, RFQDetailResponse, InventoryItem, Supplier, SupplierQuote, Quote, QuoteItem, AgentAuditLog, AutomationEvent, Shipment, CommandResponse, InternalCommand } from '../types';
import type {
  AutomationPauseBody,
  CarrierTrackingBody,
  CreateShipmentBody,
  ExtractionReviewDecisionBody,
  ExtractionReviewResponse,
  EmployeeProfile,
  EmployeeWorkHours,
  EmployeeWorkHoursReport,
  FreightQuoteBody,
  IntakeResponse,
  LoginResponse,
  MailboxHealthResponse,
  MailboxInboxResponse,
  MailboxMessageBody,
  OtpRequestBody,
  OtpRequestResponse,
  OtpVerifyBody,
  PurchaseOrderApprovalRequest,
  ShipmentEventBody,
  ShipmentSmsBody,
  ShipmentTraceResponse,
  SystemHealthResponse,
  TraceDecisionBody,
  VoiceLanguageCode,
  VoiceSessionResponse,
  VoiceToolRequest,
} from '../types/api';

const hostedApiBase = window.location.hostname === 'winged-tycoons-frontend.onrender.com'
  ? 'https://winged-tycoons-api.onrender.com/api'
  : '/api';
const configuredApiBase = import.meta.env.VITE_API_BASE_URL?.trim();
const isDeployedStaticHost = window.location.hostname === 'winged-tycoons-frontend.onrender.com';
export const API_BASE = isDeployedStaticHost && (!configuredApiBase || configuredApiBase.startsWith('/'))
  ? hostedApiBase
  : (configuredApiBase || hostedApiBase);
const allowMockFallbacks = import.meta.env.VITE_ALLOW_MOCK_FALLBACKS === 'true';
axios.defaults.timeout = 10000;
axios.defaults.withCredentials = true;

const AUTH_STORAGE_KEYS = ['wt_access_token', 'wt_role', 'wt_email'];

function storedValue(key: string): string | null {
  return localStorage.getItem(key) || sessionStorage.getItem(key);
}

function clearStoredAuth(): void {
  for (const key of AUTH_STORAGE_KEYS) {
    localStorage.removeItem(key);
    sessionStorage.removeItem(key);
  }
  window.dispatchEvent(new Event('wt-auth-changed'));
}

function requestPath(url?: string): string {
  if (!url) return '';
  try {
    return new URL(url, window.location.origin).pathname;
  } catch {
    return url.split('?')[0];
  }
}

export const getApiErrorMessage = (error: unknown, fallback = 'The request could not be completed. Please retry.'): string => {
  if (!axios.isAxiosError(error)) return error instanceof Error ? error.message : fallback;
  const status = error.response?.status;
  if (status === 502 || status === 503 || status === 504) {
    return `Service temporarily unavailable (HTTP ${status}). Please retry.`;
  }
  if (error.code === 'ECONNABORTED' || error.code === 'ETIMEDOUT') {
    return 'The request timed out. Please retry.';
  }
  if (!error.response) return 'Unable to reach the service. Check your connection and retry.';
  const detail = error.response.data?.detail;
  return typeof detail === 'string' ? detail : error.message || fallback;
};

axios.interceptors.request.use(config => {
  const token = storedValue('wt_access_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

axios.interceptors.response.use(
  response => response,
  error => {
    if (import.meta.env.DEV) {
      console.warn('API request failed', {
        method: error.config?.method,
        path: requestPath(error.config?.url),
        status: error.response?.status,
        hasRequest: Boolean(error.request),
      });
    }
    const path = requestPath(error.config?.url);
    const isOtpFlow = /\/auth\/otp\/(request|verify)$/.test(path);
    if (error.response?.status === 401 && !isOtpFlow) clearStoredAuth();
    return Promise.reject(error);
  },
);

const rethrowAuthError = (error: unknown): never => {
  if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) {
    apiService.logout();
    throw new Error('Your session expired. Please sign in again.');
  }
  throw error;
};

export const mockRFQs: RFQ[] = [
  {
    id: 'WT-29471',
    customer_name: 'GLOBAL AIRLINES',
    customer_email: 'mro.ops@globalairlines.com',
    status: 'Sourcing',
    raw_text: 'NEED URGENT P/N 32-11-45-01 Main Landing Gear Actuator Qty 1 SV condition required. AOG Miami.',
    created_at: '2026-08-28T09:30:00Z',
    urgency: 'AOG',
    part_number: '32-11-45-01',
    quantity: 1,
    condition: 'SV',
    best_price: 12300,
    lead_time: '2 Days',
    delivery_location: 'MIA'
  },
  {
    id: 'WT-31005',
    customer_name: 'GLOBAL AIRLINES',
    customer_email: 'procurement@globalairlines.com',
    status: 'Quoted',
    raw_text: 'RFQ P/N 32-11-45-01 Qty 1 ATA 32 B737-800 Main Landing Gear Actuator.',
    created_at: '2026-08-28T08:15:00Z',
    urgency: 'AOG',
    part_number: '32-11-45-01',
    quantity: 1,
    condition: 'OH',
    best_price: 14200,
    lead_time: '1 Days',
    delivery_location: 'DFW'
  },
  {
    id: 'WT-31006',
    customer_name: 'CHARTER FLEET OPS',
    customer_email: 'parts@charterfleet.com',
    status: 'Routine',
    raw_text: 'Requesting quote for P/N 747-1011-00 Qty 2 OH condition.',
    created_at: '2026-08-27T14:20:00Z',
    urgency: 'Routine',
    part_number: '747-1011-00',
    quantity: 2,
    condition: 'OH',
    best_price: 1550,
    lead_time: '3 Days',
    delivery_location: 'LAX'
  },
  {
    id: 'WT-31007',
    customer_name: 'DELTA MRO SERVICES',
    customer_email: 'purchasing@deltamro.com',
    status: 'Pending Customer',
    raw_text: 'RFQ P/N 32-11-45-01 Qty 1 FAA 8130-3 required.',
    created_at: '2026-08-27T11:10:00Z',
    urgency: 'Routine',
    part_number: '32-11-45-01',
    quantity: 1,
    condition: 'SV',
    best_price: 1800,
    lead_time: '2 Days',
    delivery_location: 'MIA'
  }
];

export const mockSuppliers: Supplier[] = [
  {
    id: 'SUP-A',
    company_name: 'AERO PARTS DIRECT LLC',
    dba_name: 'Supplier A (Internal Stock)',
    contact_name: 'Marcus Vance',
    contact_title: 'Sales Director',
    phone: '+1 305-555-0192',
    email: 'quotes@aeroparts.com',
    address_line1: '4800 NW 36th St',
    city: 'Miami',
    state_province: 'FL',
    postal_code: '33166',
    country: 'US',
    approval_status: 'Approved',
    itar_certified: true,
    account_manager: 'Alex R.'
  },
  {
    id: 'SUP-B',
    company_name: 'FRANKFURT AERO LOGISTICS GMBH',
    dba_name: 'Supplier B',
    contact_name: 'Hans Gruber',
    contact_title: 'Key Account Manager',
    phone: '+49 69 6900',
    email: 'procurement@fra-aero.de',
    address_line1: 'Cargo City Sud 532',
    city: 'Frankfurt',
    state_province: 'HE',
    postal_code: '60549',
    country: 'DE',
    approval_status: 'Approved',
    itar_certified: true,
    account_manager: 'Maria G.'
  },
  {
    id: 'SUP-C',
    company_name: 'TEXAS AVIATION COMPONENTS',
    dba_name: 'Supplier C',
    contact_name: 'Sarah Connor',
    contact_title: 'Logistics Supervisor',
    phone: '+1 214-555-8833',
    email: 'orders@texasaero.com',
    address_line1: '2400 W Airfield Dr',
    city: 'DFW Airport',
    state_province: 'TX',
    postal_code: '75261',
    country: 'US',
    approval_status: 'Approved',
    itar_certified: false,
    account_manager: 'Eliza C.'
  }
];

export const mockInventory: InventoryItem[] = [
  {
    id: 'INV-001',
    part_number: '32-11-45-01',
    serial_number: 'MLG-9840',
    quantity_available: 3,
    condition_code: 'SV',
    warehouse_location: 'MIA-BIN-A12',
    unit_cost: 9800.0,
    certificate_type: 'FAA 8130-3',
    has_full_trace: true
  },
  {
    id: 'INV-002',
    part_number: '32-11-45-01',
    serial_number: 'MLG-9841',
    quantity_available: 1,
    condition_code: 'OH',
    warehouse_location: 'DFW-BIN-B04',
    unit_cost: 8500.0,
    certificate_type: 'EASA Form 1',
    has_full_trace: true
  },
  {
    id: 'INV-003',
    part_number: '747-1011-00',
    serial_number: 'ACT-4421',
    quantity_available: 5,
    condition_code: 'NE',
    warehouse_location: 'MIA-BIN-C01',
    unit_cost: 1100.0,
    certificate_type: 'CoC',
    has_full_trace: false
  }
];

export const apiService = {
  async getLiveness(): Promise<{ status: string }> {
    const res = await axios.get(`${API_BASE.replace(/\/api\/?$/, '')}/healthz`);
    return res.data;
  },

  async getEmployeeProfile(): Promise<EmployeeProfile> {
    const res = await axios.get(`${API_BASE}/internal/profile`);
    return res.data;
  },

  async updateEmployeeProfile(displayName: string, jobTitle: string): Promise<EmployeeProfile> {
    const res = await axios.patch(`${API_BASE}/internal/profile`, { display_name: displayName, job_title: jobTitle });
    return res.data;
  },

  async setEmployeePresence(isOnline: boolean): Promise<EmployeeProfile> {
    const res = await axios.put(`${API_BASE}/internal/profile/presence`, { is_online: isOnline });
    return res.data;
  },

  async recordEmployeeClockAction(action: 'clock_in' | 'clock_out'): Promise<EmployeeProfile> {
    const res = await axios.post(`${API_BASE}/internal/profile/clock`, { action });
    return res.data;
  },

  async getEmployeeWorkHours(month: string): Promise<EmployeeWorkHours> {
    const res = await axios.get(`${API_BASE}/internal/work-hours`, { params: { month } });
    return res.data;
  },

  async getHrWorkHoursReport(month: string): Promise<EmployeeWorkHoursReport> {
    const res = await axios.get(`${API_BASE}/internal/hr/work-hours`, { params: { month } });
    return res.data;
  },

  async getRootHealth(): Promise<{ status: string; service: string; version: string; docs_url: string; frontend_url: string }> {
    const res = await axios.get(`${API_BASE.replace(/\/api\/?$/, '')}/`);
    return res.data;
  },

  async getReadiness(): Promise<SystemHealthResponse> {
    const res = await axios.get(`${API_BASE.replace(/\/api\/?$/, '')}/ready`);
    return res.data;
  },

  async getMailboxHealth(): Promise<Partial<Record<'sales' | 'purchasing', { status: string; message_count: number }>>> {
    const res = await axios.get<{
      sales_mailbox: string;
      purchasing_mailbox: string;
      authenticated_user: string;
    }>(`${API_BASE}/internal/mailboxes/health`);
    return {
      sales: { status: res.data.sales_mailbox, message_count: 0 },
      purchasing: { status: res.data.purchasing_mailbox, message_count: 0 },
    };
  },

  async createRealtimeSession(language: VoiceLanguageCode): Promise<VoiceSessionResponse> {
    const res = await axios.post(`${API_BASE}/session`, { language });
    return res.data;
  },

  async getVoiceDashboard<T = Record<string, unknown>>(): Promise<T> {
    const res = await axios.get(`${API_BASE}/voice/dashboard`);
    return res.data as T;
  },

  async executeVoiceTool<T = unknown>(toolName: string, body: VoiceToolRequest): Promise<T> {
    const res = await axios.post(`${API_BASE}/voice/tools/${encodeURIComponent(toolName)}`, body);
    return res.data as T;
  },

  async requestOtp(email: string, role: 'ROLE_CUSTOMER' | 'ROLE_INTERNAL', fullName = ''): Promise<OtpRequestResponse> {
    const body: OtpRequestBody = { email, role, full_name: fullName };
    const res = await axios.post(`${API_BASE}/auth/otp/request`, body);
    return res.data;
  },

  async verifyOtp(challengeId: string, code: string): Promise<LoginResponse> {
    const body: OtpVerifyBody = { challenge_id: challengeId, code };
    const res = await axios.post(`${API_BASE}/auth/otp/verify`, body);
    localStorage.setItem('wt_access_token', res.data.access_token);
    localStorage.setItem('wt_role', res.data.role);
    localStorage.setItem('wt_email', res.data.email);
    return res.data;
  },

  async signOut(): Promise<void> {
    try {
      await axios.post(`${API_BASE}/auth/logout`);
    } finally {
      this.logout();
    }
  },
  logout() {
    clearStoredAuth();
  },

  getRole(): 'customer' | 'internal' | null {
    const role = storedValue('wt_role');
    if (role === 'ROLE_CUSTOMER') return 'customer';
    if (role === 'ROLE_ADMIN' || role === 'ROLE_MANAGER' || role === 'ROLE_SALES' || role === 'ROLE_PURCHASING') return 'internal';
    return null;
  },

  hasAnyRole(roles: readonly string[]): boolean {
    const role = storedValue('wt_role');
    return role !== null && roles.includes(role);
  },

  getUserEmail(): string | null {
    return storedValue('wt_email');
  },

  isAuthenticated() {
    return Boolean(storedValue('wt_access_token'));
  },

  async getRFQsWithSource(): Promise<{ rfqs: RFQ[]; isFallback: boolean }> {
    try {
      const res = await axios.get(`${API_BASE}/rfqs`);
      return { rfqs: res.data, isFallback: false };
    } catch (error) {
      if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) rethrowAuthError(error);
      if (!allowMockFallbacks) throw error;
      return { rfqs: mockRFQs, isFallback: true };
    }
  },

  async getRFQs(): Promise<RFQ[]> {
    return (await this.getRFQsWithSource()).rfqs;
  },

  async processRFQ(rfqId: string): Promise<Record<string, unknown>> {
    const res = await axios.post(`${API_BASE}/rfqs/${encodeURIComponent(rfqId)}/process`);
    return res.data;
  },

  async setAutomationPause(rfqId: string, body: AutomationPauseBody): Promise<Record<string, unknown>> {
    const res = await axios.post(`${API_BASE}/internal/rfqs/${encodeURIComponent(rfqId)}/automation`, body);
    return res.data;
  },

  async getAutomationEvents(status?: string): Promise<AutomationEvent[]> {
    const res = await axios.get(`${API_BASE}/internal/automation-events`, {
      params: { status, limit: 100 },
    });
    return res.data;
  },

  async getExtractionReviews(status = 'PENDING', limit = 100): Promise<ExtractionReviewResponse[]> {
    const res = await axios.get(`${API_BASE}/internal/extraction-reviews`, { params: { status, limit } });
    return res.data;
  },

  async getExtractionReview(reviewId: string): Promise<ExtractionReviewResponse> {
    const res = await axios.get(`${API_BASE}/internal/extraction-reviews/${encodeURIComponent(reviewId)}`);
    return res.data;
  },

  async decideExtractionReview(reviewId: string, body: ExtractionReviewDecisionBody): Promise<Record<string, unknown>> {
    const res = await axios.post(`${API_BASE}/internal/extraction-reviews/${encodeURIComponent(reviewId)}/decision`, body);
    return res.data;
  },

  async getLlmTelemetry(task?: string, limit = 100): Promise<Record<string, unknown>[]> {
    const res = await axios.get(`${API_BASE}/internal/llm/telemetry`, { params: { task, limit } });
    return res.data;
  },

  async getLlmHealth(): Promise<Record<string, unknown>> {
    const res = await axios.get(`${API_BASE}/internal/llm/health`);
    return res.data;
  },

  async getMailboxInbox(mailbox: 'sales' | 'purchasing'): Promise<MailboxInboxResponse> {
    const res = await axios.get(`${API_BASE}/internal/mailboxes/${mailbox}/inbox`);
    return res.data;
  },

  async sendMailboxMessage(mailbox: 'sales' | 'purchasing', body: MailboxMessageBody): Promise<Record<string, unknown>> {
    const res = await axios.post(`${API_BASE}/internal/mailboxes/${mailbox}/send`, body);
    return res.data;
  },

  async submitRFQ(raw_text: string): Promise<IntakeResponse> {
    try {
      const res = await axios.post(`${API_BASE}/rfqs/intake`, { raw_text });
      return res.data;
    } catch (error) {
      if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) rethrowAuthError(error);
      throw error;
    }
  },

  async uploadAttachment(file: File): Promise<{ attachment_id: string; filename: string; status: string }> {
    const form = new FormData();
    form.append('file', file);
    const res = await axios.post(`${API_BASE}/attachments`, form);
    return res.data;
  },
  async submitCustomerRFQ(raw_text: string, customer_name: string, customer_email: string, attachment_ids: string[] = []): Promise<IntakeResponse> {
    try {
      const res = await axios.post(`${API_BASE}/rfqs/intake`, { raw_text, customer_name, customer_email, attachment_ids });
      return res.data;
    } catch (error) {
      if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) rethrowAuthError(error);
      throw error;
    }
  },
  async submitPurchaseOrder(quote_id: string, po_number: string, customer_email: string, attachment_ids: string[] = []): Promise<{ status: string; po_number: string; quote_id?: string }> {
    const res = await axios.post(`${API_BASE}/purchase-orders`, {
      quote_id,
      po_number,
      customer_email,
      attachment_ids,
    });
    return res.data;
  },
  async trackShipment(public_token: string): Promise<ShipmentTraceResponse> {
    const res = await axios.get(`${API_BASE}/shipments/track/${encodeURIComponent(public_token)}`);
    return res.data;
  },
  async getSupplierOffers(part_number: string): Promise<SupplierQuote[]> {
    const res = await axios.get(`${API_BASE}/supplier-offers`, { params: { part_number } });
    return res.data;
  },
  async getShipments(): Promise<Shipment[]> {
    const res = await axios.get(`${API_BASE}/internal/shipments`);
    return res.data;
  },

  async createShipment(body: CreateShipmentBody): Promise<{ shipment_id: string; tracking_url: string; status: string; tracking_notification: string }> {
    const res = await axios.post(`${API_BASE}/internal/shipments`, body);
    return res.data;
  },

  async addShipmentEvent(shipmentId: string, body: ShipmentEventBody): Promise<{ status: string; event: Record<string, unknown> }> {
    const res = await axios.post(`${API_BASE}/internal/shipments/${encodeURIComponent(shipmentId)}/events`, body);
    return res.data;
  },

  async registerCarrierTracking(shipmentId: string, body: CarrierTrackingBody): Promise<Record<string, unknown>> {
    const res = await axios.post(`${API_BASE}/internal/shipments/${encodeURIComponent(shipmentId)}/tracking`, body);
    return res.data;
  },

  async refreshCarrierTracking(shipmentId: string): Promise<Record<string, unknown>> {
    const res = await axios.post(`${API_BASE}/internal/shipments/${encodeURIComponent(shipmentId)}/tracking/refresh`);
    return res.data;
  },

  async sendShipmentSms(shipmentId: string, body: ShipmentSmsBody): Promise<Record<string, unknown>> {
    const res = await axios.post(`${API_BASE}/internal/shipments/${encodeURIComponent(shipmentId)}/sms`, body);
    return res.data;
  },

  async quoteFreight(body: FreightQuoteBody): Promise<Record<string, unknown>> {
    const res = await axios.post(`${API_BASE}/internal/freight/quote`, body);
    return res.data;
  },

  async approvePurchaseOrder(quoteId: string, body: PurchaseOrderApprovalRequest): Promise<{ status: string; quote_id: string; rfq_id: string }> {
    const res = await axios.post(`${API_BASE}/purchase-orders/${encodeURIComponent(quoteId)}/approve`, body);
    return res.data;
  },
  async executeInternalCommand(command: InternalCommand, entityId: string, details?: string): Promise<CommandResponse> {
    const res = await axios.post(`${API_BASE}/internal/commands`, { command, entity_id: entityId, details });
    return res.data;
  },

  async searchCatalogWithSource(query: string, condition?: string): Promise<{ results: Array<Pick<InventoryItem, 'part_number' | 'condition_code' | 'quantity_available' | 'certificate_type' | 'has_full_trace'>>; isFallback: boolean }> {
    try {
      const res = await axios.get(`${API_BASE}/catalog/search`, { params: { query, condition } });
      return { results: res.data, isFallback: false };
    } catch (error) {
      if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) rethrowAuthError(error);
      if (!allowMockFallbacks) throw error;
      const normalizedQuery = query.trim().toLowerCase();
      return {
        results: mockInventory
          .filter(item => !normalizedQuery || item.part_number.toLowerCase().includes(normalizedQuery))
          .map(({ part_number, condition_code, quantity_available, certificate_type, has_full_trace }) => ({
            part_number, condition_code, quantity_available, certificate_type, has_full_trace
          })),
        isFallback: true,
      };
    }
  },

  async searchCatalog(query: string, condition?: string): Promise<Array<Pick<InventoryItem, 'part_number' | 'condition_code' | 'quantity_available' | 'certificate_type' | 'has_full_trace'>>> {
    return (await this.searchCatalogWithSource(query, condition)).results;
  },

  async getRFQDetail(rfq_id: string): Promise<RFQDetailResponse> {
    try {
      const res = await axios.get(`${API_BASE}/rfqs/${rfq_id}`);
      return { ...res.data, isFallback: false };
    } catch (error) {
      if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) rethrowAuthError(error);
      if (!allowMockFallbacks) throw error;
      const match = mockRFQs.find(r => r.id === rfq_id) || mockRFQs[0];
      const mockLogs: AgentAuditLog[] = [
        {
          rfq_id,
          agent_name: 'RFQIntakeAgent',
          action_type: 'parse_text',
          message: `Extracted P/N ${match.part_number}, Qty ${match.quantity}, Urgency ${match.urgency}`,
          status: 'SUCCESS',
          timestamp: new Date(Date.now() - 3600000).toISOString()
        },
        {
          rfq_id,
          agent_name: 'PartsIntelligenceAgent',
          action_type: 'validate_catalog',
          message: `Resolved P/N ${match.part_number} (Main Landing Gear Actuator) ATA Chapter 32`,
          status: 'SUCCESS',
          timestamp: new Date(Date.now() - 3300000).toISOString()
        },
        {
          rfq_id,
          agent_name: 'InventoryAgent',
          action_type: 'check_stock',
          message: 'Found 3 units in MIA-BIN-A12 with full back-to-birth trace',
          status: 'SUCCESS',
          timestamp: new Date(Date.now() - 3000000).toISOString()
        },
        {
          rfq_id,
          agent_name: 'ComplianceAgent',
          action_type: 'audit_trace',
          message: 'FAA 8130-3 release tag verified. Trace to 121 operator confirmed.',
          status: 'SUCCESS',
          timestamp: new Date(Date.now() - 2700000).toISOString()
        },
        {
          rfq_id,
          agent_name: 'PricingAgent',
          action_type: 'calculate_margin',
          message: 'Target margin set to 20%. Unit sell price $14,200.00.',
          status: 'SUCCESS',
          timestamp: new Date(Date.now() - 2400000).toISOString()
        }
      ];

      return {
        rfq: match,
        items: [
          {
            id: 'ITEM-01',
            rfq_id,
            requested_part_number: match.part_number || '32-11-45-01',
            resolved_part_number: match.part_number || '32-11-45-01',
            quantity: match.quantity || 1,
            uom: 'EA',
            aircraft_type: 'B737-800',
            condition_preference: 'SV'
          }
        ],
        logs: mockLogs,
        isFallback: true,
        quote_details: {
          quote: {
            id: `QTE-${rfq_id.replace('WT-', '')}`,
            rfq_id,
            subtotal: 14200,
            shipping_cost: 250,
            total_amount: 14450,
            status: 'Draft',
            comments: 'Hot-Shot shipping included for AOG delivery.'
          },
          items: [
            {
              id: 'QITEM-01',
              quote_id: `QTE-${rfq_id.replace('WT-', '')}`,
              rfq_item_id: 'ITEM-01',
              part_number: match.part_number || '32-11-45-01',
              quantity: match.quantity || 1,
              source: 'Inventory',
              unit_cost: 9800,
              unit_price: 14200,
              margin_percent: 30.98,
              certificate_type: 'FAA 8130-3',
              compliance_status: 'Pass'
            }
          ]
        }
      };
    }
  },

  async getInventory(): Promise<InventoryItem[]> {
    try {
      const res = await axios.get(`${API_BASE}/inventory`);
      return res.data;
    } catch (error) {
      if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) rethrowAuthError(error);
      if (!allowMockFallbacks) throw error;
      return mockInventory;
    }
  },

  async getSuppliers(): Promise<Supplier[]> {
    try {
      const res = await axios.get(`${API_BASE}/suppliers`);
      return res.data;
    } catch (error) {
      if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) rethrowAuthError(error);
      if (!allowMockFallbacks) throw error;
      return mockSuppliers;
    }
  },

  async getSupplier(supplierId: string): Promise<Supplier> {
    const res = await axios.get(`${API_BASE}/suppliers/${encodeURIComponent(supplierId)}`);
    return res.data;
  },

  async approveQuote(quote_id: string, operator_name: string, overrides?: Array<{ quote_item_id: string; unit_price: number }>, expected_version?: number): Promise<{ status: string; quote_id: string; message: string }> {
    try {
      const res = await axios.post(`${API_BASE}/quotes/${quote_id}/approve`, {
        operator_name,
        items_override: overrides,
        expected_version
      });
      return res.data;
    } catch (error) {
      if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) rethrowAuthError(error);
      throw error;
    }
  },

  async downloadAttachment(attachmentId: string): Promise<Blob> {
    const res = await axios.get(`${API_BASE}/attachments/${encodeURIComponent(attachmentId)}`, {
      responseType: 'blob'
    });
    return res.data;
  },

  async rejectQuote(quote_id: string, operator_name: string, comments: string): Promise<{ status: string; quote_id: string; message: string }> {
    try {
      const res = await axios.post(`${API_BASE}/quotes/${quote_id}/reject`, {
        operator_name,
        comments
      });
      return res.data;
    } catch (error) {
      if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) rethrowAuthError(error);
      throw error;
    }
  },
  async recordTraceDecision(rfq_id: string, decision: TraceDecisionBody['decision'], reason?: string): Promise<{ decision: string; automation_paused: boolean }> {
    const body: TraceDecisionBody = { decision, reason };
    const res = await axios.post(`${API_BASE}/internal/rfqs/${encodeURIComponent(rfq_id)}/trace-decision`, body);
    return res.data;
  }
};
