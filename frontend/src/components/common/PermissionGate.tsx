import React from 'react';
import { AppPermission, AppRole, canUsePermission } from '../../auth/permissions';

interface PermissionGateProps {
  role: AppRole | null;
  permission: AppPermission;
  fallback?: React.ReactNode;
  children: React.ReactNode;
}

export const PermissionGate: React.FC<PermissionGateProps> = ({ role, permission, fallback = null, children }) => (
  canUsePermission(role, permission) ? <>{children}</> : <>{fallback}</>
);

