export interface PricingInput {
  baseUnitCost: number;
  baseMarginPercent: number;
  stockAvailable: number;
  requestedQuantity: number;
  isCriticalFlightComponent: boolean;
  creditApproved: boolean;
}

export interface PricingResult {
  approved: boolean;
  rejectionReason?: string;
  appliedMarginPercent?: number;
  unitPrice?: number;
}

export const calculateAutomatedQuote = (input: PricingInput): PricingResult => {
  if (!input.creditApproved) {
    return {
      approved: false,
      rejectionReason: 'CUSTOMER_CREDIT_CHECK_FAILED',
    };
  }

  const stockRatio =
    input.stockAvailable <= 0 ? 0 : input.stockAvailable / input.requestedQuantity;
  const marginBoost =
    input.isCriticalFlightComponent && stockRatio < 1 ? 15 : 0;
  const appliedMarginPercent = input.baseMarginPercent + marginBoost;
  const unitPrice = Number(
    (input.baseUnitCost * (1 + appliedMarginPercent / 100)).toFixed(2)
  );

  return {
    approved: true,
    appliedMarginPercent,
    unitPrice,
  };
};
