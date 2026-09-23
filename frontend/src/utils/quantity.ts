export const normalizeQuantityInput = (rawValue: string | number): number => {
  if (typeof rawValue === 'number') {
    return Number.isFinite(rawValue) && rawValue > 0 ? Math.trunc(rawValue) : 1;
  }

  const trimmed = rawValue.trim();
  if (!trimmed) {
    return 1;
  }

  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return 1;
  }

  return Math.trunc(parsed);
};
