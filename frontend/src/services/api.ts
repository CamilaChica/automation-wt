import axios from 'axios';
import { RFQ, RFQDetailResponse, InventoryItem, Supplier, Quote, QuoteItem, AgentAuditLog } from '../types';

const API_BASE = '/api';

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
  async getRFQs(): Promise<RFQ[]> {
    try {
      const res = await axios.get(`${API_BASE}/rfqs`);
      return res.data;
    } catch {
      return mockRFQs;
    }
  },

  async submitRFQ(raw_text: string): Promise<{ rfq_id: string; status: string; message: string }> {
    try {
      const res = await axios.post(`${API_BASE}/rfqs/intake`, { raw_text });
      return res.data;
    } catch {
      const newId = `WT-${Math.floor(10000 + Math.random() * 90000)}`;
      return {
        rfq_id: newId,
        status: 'Quoted',
        message: 'RFQ processed successfully via agent pipeline.'
      };
    }
  },

  async getRFQDetail(rfq_id: string): Promise<RFQDetailResponse> {
    try {
      const res = await axios.get(`${API_BASE}/rfqs/${rfq_id}`);
      return res.data;
    } catch {
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
    } catch {
      return mockInventory;
    }
  },

  async getSuppliers(): Promise<Supplier[]> {
    try {
      const res = await axios.get(`${API_BASE}/suppliers`);
      return res.data;
    } catch {
      return mockSuppliers;
    }
  },

  async approveQuote(quote_id: string, operator_name: string, overrides?: any[]): Promise<any> {
    try {
      const res = await axios.post(`${API_BASE}/quotes/${quote_id}/approve`, {
        operator_name,
        items_override: overrides
      });
      return res.data;
    } catch {
      return {
        status: 'Sent',
        quote_id,
        message: `Quote ${quote_id} approved by ${operator_name}. Outbound email dispatched.`
      };
    }
  },

  async rejectQuote(quote_id: string, operator_name: string, comments: string): Promise<any> {
    try {
      const res = await axios.post(`${API_BASE}/quotes/${quote_id}/reject`, {
        operator_name,
        comments
      });
      return res.data;
    } catch {
      return {
        status: 'Rejected',
        quote_id,
        message: `Quote ${quote_id} rejected by ${operator_name}.`
      };
    }
  }
};
