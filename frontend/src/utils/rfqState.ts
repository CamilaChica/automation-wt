import { RFQ } from '../types';

export const FAILED_RFQ_STATUS = 'Intake_Failed';

export const isFailedRfq = (rfq?: Pick<RFQ, 'status'> | null): boolean => {
  const status = rfq?.status.trim().toUpperCase();
  return status === FAILED_RFQ_STATUS.toUpperCase() || status === 'FAILED' || status === 'NEEDS_HUMAN_REVIEW';
};

export const rfqStatusLabel = (rfq: Pick<RFQ, 'status'>): string => {
  if (rfq.status.trim().toUpperCase() === 'NEEDS_HUMAN_REVIEW') return 'Needs Human Review';
  return isFailedRfq(rfq) ? 'Intake Failed - Extraction Error' : rfq.status;
};
