export interface ParsedPurchasingEmail {
  supplierName: string;
  contactEmail: string;
  partNumber: string;
  quantity: number;
  unitCost: number;
  conditionCode: string;
  certificateType: string;
}

const readMatch = (regex: RegExp, text: string, fallback = ''): string => {
  const match = text.match(regex);
  return match?.[1]?.trim() ?? fallback;
};

export const parsePurchasingEmail = (rawEmail: string): ParsedPurchasingEmail => {
  const supplierName = readMatch(/supplier\s*:\s*(.+)/i, rawEmail, 'Unknown Supplier');
  const contactEmail = readMatch(/email\s*:\s*([^\s,;]+@[^\s,;]+)/i, rawEmail, 'unknown@supplier.invalid');
  const partNumber = readMatch(/(?:part|p\/n|pn)\s*:\s*([A-Z0-9\-]+)/i, rawEmail).toUpperCase();
  const quantity = Number.parseInt(readMatch(/(?:qty|quantity)\s*:\s*(\d+)/i, rawEmail, '0'), 10);
  const unitCost = Number.parseFloat(readMatch(/(?:unit\s*cost|price)\s*:\s*\$?([0-9]+(?:\.[0-9]+)?)/i, rawEmail, '0'));
  const conditionCode = readMatch(/condition\s*:\s*([A-Z]+)/i, rawEmail, 'NE').toUpperCase();
  const certificateType = readMatch(/(?:cert|certificate)\s*:\s*(.+)/i, rawEmail, 'FAA 8130-3');

  if (!partNumber || quantity <= 0 || unitCost <= 0) {
    throw new Error('Unable to parse purchasing email fields: part number, quantity, and unit cost are required.');
  }

  return {
    supplierName,
    contactEmail,
    partNumber,
    quantity,
    unitCost,
    conditionCode,
    certificateType,
  };
};
