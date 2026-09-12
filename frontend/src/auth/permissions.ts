import { ViewMode } from '../types';

export type AppRole =
  | 'ROLE_CUSTOMER'
  | 'ROLE_ADMIN'
  | 'ROLE_MANAGER'
  | 'ROLE_SALES'
  | 'ROLE_PURCHASING'
  | 'ROLE_INTERNAL';

export type AppPermission =
  | 'quote.approve'
  | 'quote.issue'
  | 'quote.export'
  | 'sourcing.escalate'
  | 'trace.certify'
  | 'audit.logs.view';

const VIEW_ACCESS: Record<ViewMode, AppRole[]> = {
  customer: ['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_SALES', 'ROLE_PURCHASING', 'ROLE_INTERNAL'],
  sourcing: ['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_PURCHASING', 'ROLE_INTERNAL'],
  'aero-procurement': ['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_PURCHASING', 'ROLE_INTERNAL'],
  'trace-vault': ['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_PURCHASING', 'ROLE_INTERNAL'],
  fulfillment: ['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_SALES', 'ROLE_PURCHASING', 'ROLE_INTERNAL'],
  sales: ['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_SALES', 'ROLE_INTERNAL'],
};

const PERMISSION_ACCESS: Record<AppPermission, AppRole[]> = {
  'quote.approve': ['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_SALES', 'ROLE_INTERNAL'],
  'quote.issue': ['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_SALES', 'ROLE_INTERNAL'],
  'quote.export': ['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_SALES', 'ROLE_INTERNAL'],
  'sourcing.escalate': ['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_PURCHASING', 'ROLE_INTERNAL'],
  'trace.certify': ['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_PURCHASING', 'ROLE_INTERNAL'],
  'audit.logs.view': ['ROLE_ADMIN', 'ROLE_MANAGER', 'ROLE_SALES', 'ROLE_PURCHASING', 'ROLE_INTERNAL'],
};

export const normalizeAppRole = (rawRole: string | null): AppRole | null => {
  if (!rawRole) return null;
  if (rawRole === 'ROLE_CUSTOMER') return rawRole;
  if (rawRole === 'ROLE_ADMIN') return rawRole;
  if (rawRole === 'ROLE_MANAGER') return rawRole;
  if (rawRole === 'ROLE_SALES') return rawRole;
  if (rawRole === 'ROLE_PURCHASING') return rawRole;
  if (rawRole === 'ROLE_INTERNAL') return rawRole;
  return null;
};

export const isInternalRole = (role: AppRole | null): boolean =>
  role !== null && role !== 'ROLE_CUSTOMER';

export const canAccessView = (role: AppRole | null, view: ViewMode): boolean => {
  if (!role) return false;
  return VIEW_ACCESS[view].includes(role);
};

export const canUsePermission = (role: AppRole | null, permission: AppPermission): boolean => {
  if (!role) return false;
  return PERMISSION_ACCESS[permission].includes(role);
};

export const getAvailableViews = (role: AppRole | null): ViewMode[] =>
  (Object.keys(VIEW_ACCESS) as ViewMode[]).filter(view => canAccessView(role, view));

export const getDefaultInternalView = (role: AppRole | null): ViewMode => {
  if (role === 'ROLE_SALES') return 'sales';
  if (role === 'ROLE_PURCHASING') return 'sourcing';
  return 'customer';
};

