export const internalRfq = {
  id: 'RFQ-UI-001',
  customer_name: 'Global Airlines',
  customer_email: 'mro.ops@globalairlines.com',
  status: 'Pending_Approval',
  raw_text: 'Request P/N XYZ123 quantity 2, condition OH, FAA 8130-3 required.',
  created_at: '2026-09-20T10:00:00Z',
  urgency: 'Routine',
  part_number: 'XYZ123',
  quantity: 2,
  condition: 'OH',
};

export const internalRfqDetail = {
  rfq: internalRfq,
  items: [{
    id: 'RFQ-ITEM-001',
    rfq_id: internalRfq.id,
    requested_part_number: 'XYZ123',
    resolved_part_number: 'XYZ123',
    quantity: 2,
    uom: 'EA',
    condition_preference: 'OH',
  }],
  logs: [],
  quote_details: {
    quote: {
      id: 'QTE-UI-001',
      rfq_id: internalRfq.id,
      subtotal: 2400,
      shipping_cost: 0,
      total_amount: 2400,
      status: 'Draft',
    },
    items: [{
      id: 'QITEM-UI-001',
      quote_id: 'QTE-UI-001',
      rfq_item_id: 'RFQ-ITEM-001',
      part_number: 'XYZ123',
      quantity: 2,
      source: 'Supplier',
      unit_cost: 1000,
      unit_price: 1200,
      margin_percent: 16.67,
      certificate_type: 'FAA 8130-3',
      compliance_status: 'Pass',
    }],
  },
};

export const automationEvent = {
  id: 'AUT-UI-001',
  event_type: 'predictive_check',
  entity_type: 'rfq',
  entity_id: internalRfq.id,
  status: 'SUCCEEDED',
  attempts: 1,
  max_attempts: 3,
  result: 'Demand risk LOW',
  created_at: '2026-09-20T10:01:00Z',
};