import type {
  AgentAuditLog,
  AutomationEvent,
  CommandResponse,
  InternalCommand,
  InventoryItem,
  Quote,
  QuoteItem,
  RFQ,
  RFQDetailResponse,
  RFQItem,
  Shipment,
  ShipmentEvent,
  Supplier,
  SupplierQuote,
} from './index';

export type IsoDateTime = string;
export type ApiStatus = 'PENDING' | 'EXTRACTED' | 'QUOTED' | 'FAILED' | 'NEEDS_HUMAN_REVIEW' | (string & {});

export interface ReadinessPersistence {
  storage_engine?: string;
  operational_store_path?: string;
  full_operational_persistence_ready?: boolean;
  inventory_postgres_mirror_enabled?: boolean;
  [key: string]: unknown;
}

export interface SystemHealthResponse {
  status: string;
  database?: { healthy: boolean };
  postgresql_mirroring?: boolean;
  persistence?: ReadinessPersistence;
  storage_engine?: string;
  operational_store_path?: string;
  [key: string]: unknown;
}

export interface MailboxHealth {
  status: 'ok' | 'error' | string;
  message_count: number;
  latest_from?: string;
  latest_subject?: string;
  error?: string;
}

export type MailboxHealthResponse = Partial<Record<'sales' | 'purchasing', MailboxHealth>>;

export interface OtpRequestBody { email: string; role: 'ROLE_CUSTOMER' | 'ROLE_INTERNAL'; full_name?: string }
export interface OtpRequestResponse { challenge_id: string; development_otp?: string }
export interface OtpVerifyBody { challenge_id: string; code: string }
export interface LoginResponse { access_token: string; token_type: string; role: string; email: string }
export interface EmployeeProfile {
  user_id: string;
  email: string;
  display_name: string;
  job_title: string;
  is_online: boolean;
  is_clocked_in: boolean;
  updated_at: IsoDateTime;
}
export interface EmployeeWorkHours {
  email: string;
  display_name: string;
  job_title: string;
  is_online: boolean;
  total_seconds: number;
  daily_seconds: Record<string, number>;
}
export interface EmployeeWorkHoursReport {
  month: string;
  employees: EmployeeWorkHours[];
}
export interface EmployeeProfileUpdateBody { display_name: string; job_title: string }
export interface EmployeePresenceBody { is_online: boolean }
export interface EmployeeClockBody { action: 'clock_in' | 'clock_out' }
export interface IntakeRequestBody {
  raw_text: string;
  customer_name?: string;
  customer_email?: string;
  reply_to?: string;
  customer_country?: string;
  attachment_ids?: string[];
}
export interface IntakeResponse { rfq_id: string; status: ApiStatus; message: string }
export interface ApproveQuoteBody {
  operator_name: string;
  comments?: string;
  items_override?: Array<{ quote_item_id: string; unit_price: number }>;
}
export interface RejectQuoteBody { operator_name: string; comments: string }
export interface PurchaseOrderBody {
  quote_id: string;
  po_number: string;
  customer_email?: string;
  attachment_ids: string[];
}
export interface PurchaseOrderApprovalRequest { operator_name: string; comments?: string }
export interface PurchaseOrderResponse {
  status: string;
  po_number: string;
  quote_id?: string;
  internal_notification?: unknown;
  supplier_confirmation_count?: number;
}
export interface ShipmentTraceResponse {
  shipment_id: string;
  status: string;
  part_numbers: string[];
  quantity: number;
  carrier?: string | null;
  tracking_number?: string | null;
  estimated_delivery?: string | null;
  events: Array<ShipmentEvent & { shipment_id: string; occurred_at: IsoDateTime }>;
}
export interface CatalogSearchItem {
  part_number: string;
  condition_code: string;
  quantity_available: number;
  certificate_type: string;
  has_full_trace: boolean;
  is_sample_data?: boolean;
}
export interface TraceDecisionBody { decision: 'certify' | 'reject' | 'rescan' | 'freeze'; reason?: string }
export interface InternalCommandBody { command: InternalCommand; entity_id: string; details?: string }
export interface CreateShipmentBody { rfq_id: string; quote_id?: string; part_numbers: string[]; quantity: number }
export interface ShipmentEventBody { status: string; location?: string; description: string }
export interface CarrierTrackingBody { carrier: string; tracking_number: string }
export interface MailboxMessageBody { recipient: string; subject: string; body: string; reply_to?: string }
export interface MailboxMessageSummary {
  mailbox: string;
  message_id: string;
  from: string;
  subject: string;
  date: IsoDateTime;
}
export interface MailboxInboxResponse { mailbox: string; messages: MailboxMessageSummary[] }
export type VoiceLanguageCode = 'en' | 'es' | 'fr' | 'de' | 'pt' | 'it' | 'ja' | 'zh' | 'ko' | 'nl' | 'ar' | 'hi';
export interface VoiceSessionRequest { language: VoiceLanguageCode }
export interface VoiceSessionResponse { client_secret: string; model: string }
export interface VoiceToolRequest {
  part_number?: string;
  rfq_or_order_id?: string;
  issue_type?: string;
  details?: string;
}
export interface ExtractionReviewDecisionBody {
  decision: 'approve' | 'reject';
  operator_name?: string;
  comments?: string;
  approved_extraction?: Record<string, unknown>;
}
export interface ExtractionReviewResponse { id: string; status: string; [key: string]: unknown }
export interface FreightQuoteBody {
  origin: string;
  destination: string;
  weight_kg: number;
  packages: number;
  service_level: string;
}
export interface ShipmentSmsBody { recipient: string; status: string; tracking_url?: string }
export interface AutomationPauseBody { paused: boolean; reason?: string }
export interface TraceDecisionResponse { decision: string; automation_paused: boolean }
export interface FulfillmentStage {
  shipment_id: string;
  stage: string;
  status: string;
  carrier?: string | null;
  tracking_number?: string | null;
  updated_at?: IsoDateTime;
  is_derived_from_shipment: true;
}

/** Concrete UI-facing route contracts. The backend does not expose a quotes collection,
 * a fulfillment-stages route, or shipment-by-id GET; those views must use RFQ detail,
 * shipment list, and token-based tracking respectively.
 */
export interface ApiRouteContracts {
  'GET /': { response: { status: string; service: string; version: string; docs_url: string; frontend_url: string } };
  'GET /healthz': { response: { status: string } };
  'GET /ready': { response: SystemHealthResponse };
  'POST /api/auth/otp/request': { request: OtpRequestBody; response: OtpRequestResponse };
  'POST /api/auth/otp/verify': { request: OtpVerifyBody; response: LoginResponse };
  'POST /api/auth/logout': { response: void };
  'POST /api/session': { request: VoiceSessionRequest; response: VoiceSessionResponse };
  'GET /api/voice/dashboard': { response: Record<string, unknown> };
  'POST /api/voice/tools/{tool_name}': { request: VoiceToolRequest; response: Record<string, unknown> };
  'GET /api/internal/profile': { response: EmployeeProfile };
  'PATCH /api/internal/profile': { request: EmployeeProfileUpdateBody; response: EmployeeProfile };
  'PUT /api/internal/profile/presence': { request: EmployeePresenceBody; response: EmployeeProfile };
  'POST /api/internal/profile/clock': { request: EmployeeClockBody; response: EmployeeProfile };
  'GET /api/internal/work-hours': { response: EmployeeWorkHours };
  'GET /api/internal/hr/work-hours': { response: EmployeeWorkHoursReport };
  'GET /api/internal/mailboxes/health': { response: MailboxHealthResponse };
  'GET /api/rfqs': { response: RFQ[] };
  'POST /api/rfqs/intake': { request: IntakeRequestBody; response: IntakeResponse };
  'GET /api/rfqs/{rfq_id}': { response: RFQDetailResponse };
  'GET /api/supplier-offers?part_number={part_number}': { response: SupplierQuote[] };
  'GET /api/internal/shipments': { response: Shipment[] };
  'GET /api/shipments/track/{public_token}': { response: ShipmentTraceResponse };
  'GET /api/internal/automation-events': { response: AutomationEvent[] };
  'GET /api/internal/extraction-reviews': { response: ExtractionReviewResponse[] };
  'GET /api/internal/extraction-reviews/{review_id}': { response: ExtractionReviewResponse };
  'POST /api/internal/extraction-reviews/{review_id}/decision': { request: ExtractionReviewDecisionBody; response: Record<string, unknown> };
  'GET /api/internal/llm/telemetry': { response: Record<string, unknown>[] };
  'GET /api/internal/llm/health': { response: Record<string, unknown> };
  'GET /api/internal/mailboxes/{mailbox}/inbox': { response: MailboxInboxResponse };
  'POST /api/internal/mailboxes/{mailbox}/send': { request: MailboxMessageBody; response: Record<string, unknown> };
  'POST /api/quotes/{quote_id}/approve': { request: ApproveQuoteBody; response: { status: string; quote_id: string; message: string } };
  'POST /api/quotes/{quote_id}/reject': { request: RejectQuoteBody; response: { status: string; quote_id: string; message: string } };
  'POST /api/purchase-orders': { request: PurchaseOrderBody; response: PurchaseOrderResponse };
  'POST /api/internal/rfqs/{rfq_id}/trace-decision': { request: TraceDecisionBody; response: { decision: string; automation_paused: boolean } };
  'POST /api/internal/rfqs/{rfq_id}/automation': { request: AutomationPauseBody; response: Record<string, unknown> };
  'POST /api/rfqs/{rfq_id}/process': { response: Record<string, unknown> };
  'POST /api/internal/commands': { request: InternalCommandBody; response: CommandResponse };
  'POST /api/internal/shipments': { request: CreateShipmentBody; response: { shipment_id: string; tracking_url: string; status: string; tracking_notification: string } };
  'POST /api/internal/shipments/{shipment_id}/events': { request: ShipmentEventBody; response: { status: string; event: ShipmentEvent } };
  'POST /api/internal/shipments/{shipment_id}/tracking': { request: CarrierTrackingBody; response: { shipment_id: string; carrier: string; tracking_number: string; provider: unknown } };
  'POST /api/internal/shipments/{shipment_id}/tracking/refresh': { response: Record<string, unknown> };
  'POST /api/internal/shipments/{shipment_id}/sms': { request: ShipmentSmsBody; response: Record<string, unknown> };
  'POST /api/internal/freight/quote': { request: FreightQuoteBody; response: Record<string, unknown> };
  'POST /api/purchase-orders/{quote_id}/approve': { request: PurchaseOrderApprovalRequest; response: { status: string; quote_id: string; rfq_id: string } };
  'GET /api/attachments/{attachment_id}': { response: Blob };
  'POST /api/attachments': { response: { attachment_id: string; filename: string; status: string } };
  'GET /api/catalog/search': { response: CatalogSearchItem[] };
  'GET /api/inventory': { response: InventoryItem[] };
  'GET /api/suppliers': { response: Supplier[] };
  'GET /api/quotes/{quote_id}': never;
  'GET /api/fulfillment/stages': never;
  'GET /api/shipments/{shipment_id}': never;
}

export type QuoteDetail = { quote: Quote; items: QuoteItem[] };
export type RFQDetail = RFQDetailResponse & { rfq: RFQ; items: RFQItem[]; logs: AgentAuditLog[] };
