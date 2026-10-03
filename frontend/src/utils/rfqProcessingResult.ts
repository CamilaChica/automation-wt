export interface RfqProcessingNotice {
  type: 'success' | 'info' | 'error';
  message: string;
}

const nonEmptyText = (value: unknown): string | undefined =>
  typeof value === 'string' && value.trim() ? value.trim() : undefined;

export function describeRfqProcessingResult(
  rfqId: string,
  result: Record<string, unknown> | undefined,
): RfqProcessingNotice {
  const status = nonEmptyText(result?.status);
  const error = nonEmptyText(result?.error);
  const detail = nonEmptyText(result?.message) || nonEmptyText(result?.reason);
  const transmission = nonEmptyText(result?.transmission_status);
  const key = status?.toUpperCase();
  const label = status?.replace(/_/g, ' ');

  if (error || key === 'FAILED' || key?.endsWith('_FAILED') || key?.endsWith('_HALTED')) {
    return { type: 'error', message: `${rfqId}: ${label || 'Processing failed'}.${error || detail ? ` ${error || detail}` : ''}` };
  }
  if (!status) {
    return { type: 'error', message: `${rfqId}: The API returned no workflow status. Quote dispatch cannot be confirmed.` };
  }
  if (key === 'QUOTE_SENT') {
    if (transmission && transmission.toUpperCase() !== 'SENT') {
      return { type: 'error', message: `${rfqId}: The API returned an inconsistent delivery status (${transmission}). Quote dispatch cannot be confirmed.` };
    }
    return { type: 'success', message: `${rfqId}: Quote sent. Email dispatch confirmed; inbox receipt is not verified.` };
  }
  if (key === 'QUOTE_DISPATCH_PENDING') {
    return { type: 'info', message: `${rfqId}: Quote dispatch pending${transmission ? ` (${transmission})` : ''}. Email dispatch is not confirmed.${detail ? ` ${detail}` : ''}` };
  }
  return { type: 'info', message: `${rfqId}: ${label}.${detail ? ` ${detail}` : ''}` };
}
