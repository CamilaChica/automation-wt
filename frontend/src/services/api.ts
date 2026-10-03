import axios from 'axios';
import { RFQ, RFQDetailResponse, InventoryItem, Supplier, SupplierQuote, Quote, QuoteItem, AutomationEvent, Shipment, CommandResponse, InternalCommand } from '../types';
import type {
  AutomationPauseBody,
  CarrierTrackingBody,
  CreateShipmentBody,
  ExtractionReviewDecisionBody,
  ExtractionReviewResponse,
  EmployeeProfile,
  EmployeeWorkHours,
  EmployeeWorkHoursReport,
  FailedIntakeResetBody,
  FailedIntakeResetResponse,
  FreightQuoteBody,
  FreightQuoteResponse,
  IntakeResponse,
  LoginResponse,
  LlmConnectionTestResponse,
  LlmHealthResponse,
  LlmTelemetryRecord,
  MailboxHealthResponse,
  MailboxInboxResponse,
  MailboxMessageBody,
  MailboxSendResponse,
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
  OwnerAnalytics,
  MySales,
  SalesRep,
} from '../types/api';

const isCompanyDomainHost = window.location.hostname.endsWith('.wingedtycoons.com');
const hostedApiBase = isCompanyDomainHost
  ? 'https://api.wingedtycoons.com/api'
  : window.location.hostname === 'winged-tycoons-frontend.onrender.com'
    ? 'https://winged-tycoons-api.onrender.com/api'
    : '/api';
const configuredApiBase = import.meta.env.VITE_API_BASE_URL?.trim();
const isDeployedStaticHost = isCompanyDomainHost || window.location.hostname === 'winged-tycoons-frontend.onrender.com';
// Company domains must use the same-site API so the session cookie is never treated as third-party.
export const API_BASE = isCompanyDomainHost
  ? hostedApiBase
  : isDeployedStaticHost && (!configuredApiBase || configuredApiBase.startsWith('/'))
  ? hostedApiBase
  : (configuredApiBase || hostedApiBase);
axios.defaults.timeout = 10000;
axios.defaults.withCredentials = true;

const AUTH_STORAGE_KEYS = ['wt_access_token', 'wt_role', 'wt_email'];
let csrfToken: string | null = null;
let csrfBootstrap: Promise<void> | null = null;

for (const storage of [localStorage, sessionStorage]) {
  storage.removeItem('wt_access_token');
}

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
  if (!error.response) return 'Connection interrupted for a moment. Please try again.';
  const detail = error.response.data?.detail;
  return typeof detail === 'string' ? detail : error.message || fallback;
};

axios.interceptors.response.use(
  response => {
    const token = response.headers['x-csrf-token'];
    if (typeof token === 'string' && token) csrfToken = token;
    return response;
  },
  async error => {
    if (import.meta.env.DEV) {
      console.warn('API request failed', {
        method: error.config?.method,
        path: requestPath(error.config?.url),
        status: error.response?.status,
        hasRequest: Boolean(error.request),
      });
    }
    const token = error.response?.headers?.['x-csrf-token'];
    if (typeof token === 'string' && token) csrfToken = token;
    const path = requestPath(error.config?.url);
    const status = error.response?.status;
    const config = error.config as (typeof error.config & { _wtRetried?: boolean }) | undefined;
    const isCsrfFailure = status === 403 && String(error.response?.data ?? '').includes('CSRF validation failed');
    if (isCsrfFailure && config && !config._wtRetried) {
      config._wtRetried = true;
      csrfToken = null;
      return axios.request(config);
    }
    const isAuthCheck = /\/auth\/(otp\/(request|verify)|session|logout|csrf)$/.test(path);
    if (status === 401 && !isAuthCheck && storedValue('wt_role')) {
      try {
        await axios.get(`${API_BASE}/auth/session`);
      } catch (sessionError) {
        if (axios.isAxiosError(sessionError) && sessionError.response?.status === 401) clearStoredAuth();
      }
    }
    // Ride out brief API restarts: retry safe reads only, never submissions.
    const isNetworkFailure = !error.response && error.code === 'ERR_NETWORK';
    const networkConfig = config as (typeof config & { _wtNetworkRetries?: number }) | undefined;
    const retries = networkConfig?._wtNetworkRetries ?? 0;
    const isSafeRead = ['GET', 'HEAD'].includes((networkConfig?.method || 'get').toUpperCase());
    if (isNetworkFailure && networkConfig && isSafeRead && retries < 3) {
      networkConfig._wtNetworkRetries = retries + 1;
      await new Promise(resolve => setTimeout(resolve, 1000 * 2 ** retries));
      return axios.request(networkConfig);
    }
    if (isNetworkFailure) error.message = 'Connection interrupted for a moment. Please try again.';
    return Promise.reject(error);
  },
);

axios.interceptors.request.use(async config => {
  const method = (config.method || 'get').toUpperCase();
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && !csrfToken) {
    csrfBootstrap ??= axios.get(`${API_BASE}/auth/csrf`, { withCredentials: true })
      .then(response => {
        const token = response.headers['x-csrf-token'];
        if (typeof token === 'string' && token) csrfToken = token;
      })
      .finally(() => {
        csrfBootstrap = null;
      });
    await csrfBootstrap;
  }
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method) && csrfToken) {
    config.headers.set('X-CSRF-Token', csrfToken);
  }
  delete config.headers.Authorization;
  return config;
});

const rethrowAuthError = (error: unknown): never => {
  if (axios.isAxiosError(error) && error.response?.status === 401) {
    throw new Error(apiService.isAuthenticated() ? 'Request was not authorized. Please retry.' : 'Your session expired. Please sign in again.');
  }
  if (axios.isAxiosError(error) && error.response?.status === 403) {
    throw new Error('This action is not available for your account.');
  }
  throw error;
};

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

  async getOwnerAnalytics(): Promise<OwnerAnalytics> {
    const res = await axios.get(`${API_BASE}/internal/analytics/owner`);
    return res.data;
  },

  async getMySales(): Promise<MySales> {
    const res = await axios.get(`${API_BASE}/internal/sales/me`);
    return res.data;
  },

  async getSalesLeaderboard(): Promise<{ month: string; board: SalesRep[] }> {
    const res = await axios.get(`${API_BASE}/internal/sales/leaderboard`);
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

  async executeVoiceTool<T = unknown>(
    toolName: string,
    body: VoiceToolRequest,
    humanConfirmed = false,
  ): Promise<T> {
    const res = await axios.post(
      `${API_BASE}/voice/tools/${encodeURIComponent(toolName)}`,
      body,
      humanConfirmed ? { headers: { 'X-Human-Confirmed': 'true' } } : undefined,
    );
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

  async validateSession(): Promise<void> {
    if (!storedValue('wt_role')) return;
    try {
      const res = await axios.get(`${API_BASE}/auth/session`);
      if (res.data?.role) localStorage.setItem('wt_role', res.data.role);
      if (res.data?.email) localStorage.setItem('wt_email', res.data.email);
    } catch (error) {
      if (axios.isAxiosError(error) && error.response?.status === 401) clearStoredAuth();
    }
  },

  getRole(): 'customer' | 'internal' | null {
    const role = storedValue('wt_role');
    if (role === 'ROLE_CUSTOMER') return 'customer';
    if (role === 'ROLE_ADMIN' || role === 'ROLE_MANAGER' || role === 'ROLE_SALES' || role === 'ROLE_PURCHASING' || role === 'ROLE_INTERNAL') return 'internal';
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
    return this.getRole() !== null;
  },

  async getRFQsWithSource(): Promise<{ rfqs: RFQ[]; isFallback: boolean }> {
    try {
      const res = await axios.get<RFQ[]>(`${API_BASE}/rfqs`);
      return { rfqs: res.data, isFallback: false };
    } catch (error) {
      if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) rethrowAuthError(error);
      throw error;
    }
  },

  async getRFQs(): Promise<RFQ[]> {
    return (await this.getRFQsWithSource()).rfqs;
  },

  async processRFQ(rfqId: string): Promise<Record<string, unknown>> {
    const res = await axios.post(`${API_BASE}/rfqs/${encodeURIComponent(rfqId)}/process`);
    return res.data;
  },

  async resetFailedIntake(rfqId: string, body: FailedIntakeResetBody): Promise<FailedIntakeResetResponse> {
    const res = await axios.post(`${API_BASE}/internal/rfqs/${encodeURIComponent(rfqId)}/reset-intake`, body);
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

  async getLlmTelemetry(task?: string, limit = 100): Promise<LlmTelemetryRecord[]> {
    const res = await axios.get<LlmTelemetryRecord[]>(`${API_BASE}/internal/llm/telemetry`, { params: { task, limit } });
    return res.data;
  },

  async getLlmHealth(): Promise<LlmHealthResponse> {
    const res = await axios.get<LlmHealthResponse>(`${API_BASE}/internal/llm/health`);
    return res.data;
  },

  async testLlmConnections(): Promise<LlmConnectionTestResponse> {
    const res = await axios.post<LlmConnectionTestResponse>(`${API_BASE}/internal/llm/test-connections`);
    return res.data;
  },

  async getMailboxInbox(mailbox: 'sales' | 'purchasing'): Promise<MailboxInboxResponse> {
    const res = await axios.get<MailboxInboxResponse>(`${API_BASE}/internal/mailboxes/${mailbox}/inbox`);
    return res.data;
  },

  async sendMailboxMessage(mailbox: 'sales' | 'purchasing', body: MailboxMessageBody): Promise<MailboxSendResponse> {
    const res = await axios.post<MailboxSendResponse>(`${API_BASE}/internal/mailboxes/${mailbox}/send`, body);
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

  async quoteFreight(body: FreightQuoteBody): Promise<FreightQuoteResponse> {
    const res = await axios.post<FreightQuoteResponse>(`${API_BASE}/internal/freight/quote`, body);
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
      const res = await axios.get<Array<Pick<InventoryItem, 'part_number' | 'condition_code' | 'quantity_available' | 'certificate_type' | 'has_full_trace'>>>(`${API_BASE}/catalog/search`, { params: { query, condition } });
      return { results: res.data, isFallback: false };
    } catch (error) {
      if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) rethrowAuthError(error);
      throw error;
    }
  },

  async searchCatalog(query: string, condition?: string): Promise<Array<Pick<InventoryItem, 'part_number' | 'condition_code' | 'quantity_available' | 'certificate_type' | 'has_full_trace'>>> {
    return (await this.searchCatalogWithSource(query, condition)).results;
  },

  async getRFQDetail(rfq_id: string): Promise<RFQDetailResponse> {
    try {
      const res = await axios.get<RFQDetailResponse>(`${API_BASE}/rfqs/${encodeURIComponent(rfq_id)}`);
      return { ...res.data, isFallback: false };
    } catch (error) {
      if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) rethrowAuthError(error);
      throw error;
    }
  },

  async getInventoryWithSource(): Promise<{ inventory: InventoryItem[]; isFallback: boolean }> {
    try {
      const res = await axios.get<InventoryItem[]>(`${API_BASE}/inventory`);
      return { inventory: res.data, isFallback: false };
    } catch (error) {
      if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) rethrowAuthError(error);
      throw error;
    }
  },

  async getInventory(): Promise<InventoryItem[]> {
    return (await this.getInventoryWithSource()).inventory;
  },

  async getSuppliersWithSource(): Promise<{ suppliers: Supplier[]; isFallback: boolean }> {
    try {
      const res = await axios.get<Supplier[]>(`${API_BASE}/suppliers`);
      return { suppliers: res.data, isFallback: false };
    } catch (error) {
      if (axios.isAxiosError(error) && (error.response?.status === 401 || error.response?.status === 403)) rethrowAuthError(error);
      throw error;
    }
  },

  async getSuppliers(): Promise<Supplier[]> {
    return (await this.getSuppliersWithSource()).suppliers;
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
