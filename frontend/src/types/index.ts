export type ViewMode = 
  | 'customer' 
  | 'sourcing' 
  | 'aero-procurement' 
  | 'trace-vault' 
  | 'fulfillment' 
  | 'sales'
  | 'swarm-simulation';

export type ThemeMode = 'dark' | 'light';

export interface RFQItem {
  id: string;
  rfq_id: string;
  requested_part_number: string;
  resolved_part_number?: string;
  quantity: number;
  uom: string;
  aircraft_type?: string;
  condition_preference?: 'SV' | 'NE' | 'NS' | 'OH' | 'AR';
}

export interface RFQ {
  id: string;
  customer_name: string;
  customer_email: string;
  status: string;
  raw_text: string;
  created_at: string;
  urgency?: 'AOG' | 'Critical' | 'Routine';
  part_number?: string;
  quantity?: number;
  condition?: string;
  best_price?: number;
  lead_time?: string;
  delivery_location?: string;
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
}

export interface ShipmentEvent {
  id: string;
  status: string;
  location?: string;
  description: string;
}

export interface Shipment {
  id: string;
  status: string;
  carrier?: string;
  tracking_number?: string;
  estimated_delivery?: string;
  events?: ShipmentEvent[];
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
  approved_at?: string;
}

export interface AgentAuditLog {
  id?: number;
  rfq_id: string;
  agent_name: string;
  action_type: string;
  message: string;
  status: 'SUCCESS' | 'WARNING' | 'FAILURE';
  payload_json?: string;
  timestamp: string;
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
  created_at: string;
}

export interface RFQDetailResponse {
  rfq: RFQ;
  items: RFQItem[];
  logs: AgentAuditLog[];
  quote_details?: {
    quote: Quote;
    items: QuoteItem[];
  };
}
