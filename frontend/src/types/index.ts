export type ViewMode = 
  | 'customer' 
  | 'sourcing' 
  | 'aero-procurement' 
  | 'trace-vault' 
  | 'fulfillment' 
  | 'sales'
  | 'owner-analytics'
  | 'my-sales'
  | 'sales-race'
  | 'shipments-map';

export type ThemeMode = 'dark' | 'light';
export type ISODateTime = string;
export type RFQStatus =
  | 'Intake' | 'Validating' | 'Supplier_Sourcing' | 'Compliance_Check' | 'Pricing'
  | 'Pending_Approval' | 'Quote_Sent' | 'Quote_Dispatch_Pending' | 'Rejected'
  | 'FAILED' | 'NEEDS_HUMAN_REVIEW' | 'Intake_Failed' | (string & {});

export interface RFQItem {
  id: string;
  rfq_id: string;
  requested_part_number: string;
  resolved_part_number?: string;
  quantity: number;
  uom: string;
  aircraft_type?: string;
  condition_preference?: 'SV' | 'NE' | 'NS' | 'OH' | 'AR';
  is_sample_data?: boolean;
}

export interface RFQ {
  id: string;
  customer_name: string;
  customer_email: string;
  status: RFQStatus;
  raw_text: string;
  created_at: ISODateTime;
  urgency?: 'AOG' | 'Critical' | 'Routine';
  part_number?: string;
  quantity?: number;
  condition?: string;
  best_price?: number;
  lead_time?: string;
  delivery_location?: string;
  workflow_state?: string;
  automation_paused?: boolean;
  pause_reason?: string | null;
  version?: number;
  is_sample_data?: boolean;
}

export interface InventoryItem {
  id: string;
  part_number: string;
  serial_number: string;
  quantity_available: number;
  condition_code: string;
  warehouse_location: string;
  unit_cost: number;
  certificate_type: string;
  has_full_trace: boolean;
  is_sample_data?: boolean;
}

export interface Supplier {
  id: string;
  company_name: string;
  dba_name?: string;
  contact_name: string;
  contact_title?: string;
  phone: string;
  phone_alt?: string;
  email: string;
  email_quotes?: string;
  website?: string;
  address_line1: string;
  address_line2?: string;
  city: string;
  state_province: string;
  postal_code: string;
  country: string;
  approval_status: 'Approved' | 'Conditional' | 'Unapproved' | 'On-Watch';
  itar_certified: boolean;
  account_manager?: string;
  notes?: string;
  is_sample_data?: boolean;
}

export interface SupplierQuote {
  id: string;
  rfq_item_id: string;
  supplier_id?: string;
  supplier_name: string;
  contact_email?: string;
  contact_phone?: string;
  part_number: string;
  unit_cost: number;
  quantity_available: number;
  lead_time_days: number;
  certificate_type: string;
  condition?: string;
  location?: string;
  historical_reliability?: string;
  return_rate?: string;
  confidence?: number;
  supplier_email?: string;
  is_sample_data?: boolean;
}

export interface QuoteItem {
  id: string;
  quote_id: string;
  rfq_item_id: string;
  part_number: string;
  quantity: number;
  source: string;
  unit_cost: number;
  unit_price: number;
  margin_percent: number;
  certificate_type: string;
  compliance_status: 'Pass' | 'Warn' | 'Fail';
  attachments?: string[];
  description?: string;
  condition?: string;
  lead_time_days?: number;
  is_sample_data?: boolean;
}

export interface ShipmentEvent {
  id: string;
  shipment_id?: string;
  status: string;
  location?: string;
  description: string;
  occurred_at?: ISODateTime;
}

export interface Shipment {
  id: string;
  status: string;
  carrier?: string;
  tracking_number?: string;
  estimated_delivery?: string;
  events?: ShipmentEvent[];
  rfq_id?: string;
  quote_id?: string;
  part_numbers?: string[];
  quantity?: number;
  created_at?: ISODateTime;
  updated_at?: ISODateTime;
  is_sample_data?: boolean;
}

export type InternalCommand =
  | 'add_to_quote'
  | 'issue_po'
  | 'document_audit'
  | 'generate_quote'
  | 'split_po'
  | 'escalate_aog'
  | 'print_tags'
  | 'generate_stamps';

export interface CommandResponse {
  command: InternalCommand;
  entity_id: string;
  status: string;
  message: string;
}

export interface Quote {
  id: string;
  rfq_id: string;
  subtotal: number;
  shipping_cost: number;
  total_amount: number;
  status: 'Draft' | 'Approved' | 'Rejected' | 'Sent';
  comments?: string;
  approved_by?: string;
  approved_at?: ISODateTime;
  lead_time_days?: number;
  valid_until?: string;
  version?: number;
  is_sample_data?: boolean;
}

export interface AgentAuditLog {
  id?: number;
  rfq_id: string;
  agent_name: string;
  action_type: string;
  message: string;
  status: 'SUCCESS' | 'WARNING' | 'FAILURE';
  payload_json?: string;
  timestamp: ISODateTime;
}

export interface AutomationEvent {
  id: string;
  event_type: string;
  entity_type: string;
  entity_id: string;
  status: string;
  attempts: number;
  max_attempts: number;
  execution_time?: string;
  result?: string;
  error?: string;
  created_at: ISODateTime;
}

export interface RFQDetailResponse {
  rfq: RFQ;
  items: RFQItem[];
  logs?: AgentAuditLog[];
  isFallback?: boolean;
  quote_details?: {
    quote: Quote;
    items: Array<QuoteItem | CustomerQuoteItem>;
  };
  is_sample_data?: boolean;
}

export interface CustomerQuoteItem {
  part_number: string;
  quantity: number;
  unit_price: number;
  certificate_type: string;
  compliance_status: string;
  attachments?: string[];
  is_sample_data?: boolean;
}
