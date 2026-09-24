import { RFQ } from '../types';

export const FAILED_RFQ_STATUS = 'Intake_Failed';

export const isFailedRfq = (rfq?: Pick<RFQ, 'status'> | null): boolean =>
  rfq?.status === FAILED_RFQ_STATUS;

export const rfqStatusLabel = (rfq: Pick<RFQ, 'status'>): string =>
  isFailedRfq(rfq) ? 'Intake Failed - Extraction Error' : rfq.status;
