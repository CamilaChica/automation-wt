import { RFQ } from '../../types';

const baseRfq: RFQ = {
  id: 'RFQ-FIXTURE-001',
  customer_name: 'Fixture Aviation',
  customer_email: 'ops@fixture-aviation.example',
  status: 'Pending_Extraction',
  raw_text: 'Request for aviation component.',
  created_at: '2026-09-24T00:00:00Z',
  part_number: '32-11-45-01',
  quantity: 1,
};

export const extractedRfq: RFQ = {
  ...baseRfq,
  id: 'RFQ-EXTRACTED-001',
  status: 'Quoted',
  part_number: '32-11-45-01',
  quantity: 2,
};

export const pendingExtractionRfq: RFQ = {
  ...baseRfq,
  id: 'RFQ-PENDING-001',
  status: 'Pending_Extraction',
  part_number: undefined,
  quantity: undefined,
};

export const failedRfq: RFQ = {
  ...baseRfq,
  id: 'RFQ-FAILED-001',
  status: 'Intake_Failed',
  part_number: undefined,
  quantity: undefined,
};
