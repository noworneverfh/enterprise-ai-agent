import type { CurrentUser, UserRole } from '../types';

export interface FrontendPermissions {
  viewDashboard: boolean;
  viewReports: boolean;
  viewReportDetail: boolean;
  generateReport: boolean;
  manageKnowledge: boolean;
  manageSystem: boolean;
}

export const permissions: Record<UserRole, FrontendPermissions> = {
  admin: {
    viewDashboard: true,
    viewReports: true,
    viewReportDetail: true,
    generateReport: true,
    manageKnowledge: true,
    manageSystem: true,
  },
  user: {
    viewDashboard: true,
    viewReports: true,
    viewReportDetail: true,
    generateReport: false,
    manageKnowledge: false,
    manageSystem: false,
  },
};

export function resolvePrimaryRole(user: CurrentUser | null): UserRole {
  if (!user) return 'user';

  const userWithFlexibleRole = user as CurrentUser & {
    role?: unknown;
    roles?: unknown;
    role_name?: unknown;
    roleName?: unknown;
  };

  const roles = [
    ...normalizeRoles(userWithFlexibleRole.roles),
    ...normalizeRoles(userWithFlexibleRole.role),
    ...normalizeRoles(userWithFlexibleRole.role_name),
    ...normalizeRoles(userWithFlexibleRole.roleName),
  ];

  if (roles.includes('admin')) return 'admin';
  const permissionSet = new Set(user.permissions ?? []);
  if (
    permissionSet.has('users:manage') ||
    permissionSet.has('knowledge:delete') ||
    permissionSet.has('system:manage')
  ) {
    return 'admin';
  }

  return 'user';
}

export function getFrontendPermissions(user: CurrentUser | null): FrontendPermissions {
  return permissions[resolvePrimaryRole(user)];
}

export function canViewReportDetail(user: CurrentUser | null): boolean {
  return getFrontendPermissions(user).viewReportDetail;
}

function normalizeRoles(value: unknown): UserRole[] {
  if (!value) return [];
  const values = Array.isArray(value) ? value : [value];

  return values
    .map((item) => {
      if (typeof item === 'string') return item;
      if (item && typeof item === 'object') {
        const roleObject = item as Record<string, unknown>;
        const candidate = roleObject.name ?? roleObject.role ?? roleObject.code ?? roleObject.role_name ?? roleObject.roleName;
        return typeof candidate === 'string' ? candidate : '';
      }
      return '';
    })
    .map((role) => role.trim().toLowerCase())
    .map((role) => (role === 'admin' ? 'admin' : 'user'))
    .filter((role): role is UserRole => role === 'admin' || role === 'user');
}
