export interface CustomerPurchase {
  partNumber: string;
  requestedCondition: 'FN' | 'OH' | 'SV' | 'NE';
  quantity: number;
  customerUnitPrice: number;
}

export interface SupplierOffer {
  supplierId: string;
  partNumber: string;
  offeredCondition: 'FN' | 'OH' | 'SV' | 'NE';
  availableQuantity: number;
  supplierUnitCost: number;
  certificateType: string;
}

export interface AutoBuyDecision {
  approved: boolean;
  vendorPoGenerated: boolean;
  reason?: string;
  computedMarginPercent?: number;
}

const ALLOWED_TRACE_DOCS = new Set(['FAA 8130-3', 'EASA Form 1']);

export const evaluateAutoBuy = (
  purchase: CustomerPurchase,
  offer: SupplierOffer,
  targetMarginPercent: number
): AutoBuyDecision => {
  if (purchase.partNumber !== offer.partNumber) {
    return { approved: false, vendorPoGenerated: false, reason: 'PART_NUMBER_MISMATCH' };
  }
  if (purchase.requestedCondition !== offer.offeredCondition) {
    return { approved: false, vendorPoGenerated: false, reason: 'CONDITION_MISMATCH' };
  }
  if (!ALLOWED_TRACE_DOCS.has(offer.certificateType)) {
    return { approved: false, vendorPoGenerated: false, reason: 'TRACE_DOC_MISSING_OR_INVALID' };
  }
  if (offer.availableQuantity < purchase.quantity) {
    return { approved: false, vendorPoGenerated: false, reason: 'INSUFFICIENT_SUPPLIER_STOCK' };
  }

  const marginPercent =
    ((purchase.customerUnitPrice - offer.supplierUnitCost) / purchase.customerUnitPrice) * 100;
  if (marginPercent < targetMarginPercent) {
    return {
      approved: false,
      vendorPoGenerated: false,
      reason: 'MARGIN_BELOW_TARGET',
      computedMarginPercent: Number(marginPercent.toFixed(2)),
    };
  }

  return {
    approved: true,
    vendorPoGenerated: true,
    computedMarginPercent: Number(marginPercent.toFixed(2)),
  };
};
