import { requestJson } from '../api';

export interface AdminOverview {
  checked_at: string;
  environment: string;
  app_version: string;
  core_services: { healthy: number; total: number; status: string };
  ai_model: { provider: string | null; model: string | null; mode: string | null; reachable: boolean | null };
  today_llm_calls: number;
  today_prompt_tokens: number | null;
  today_completion_tokens: number | null;
  today_total_tokens: number | null;
  today_errors: number;
  registered_users: number;
  active_users: number;
  latest_error: AuditLogItem | null;
  latest_config_change: AuditLogItem | null;
}

export interface AdminServiceHealth {
  checked_at: string;
  services: Array<{
    name: string;
    status: string;
    latency_ms: number | null;
    description: string;
    version: string | null;
    mode: string | null;
    error: string | null;
    components?: Record<string, string>;
  }>;
}

export interface AdminLlmStatus {
  checked_at: string;
  configuration: {
    provider: string;
    provider_class: string | null;
    model: string | null;
    base_url_domain: string | null;
    configured: boolean;
    reachable: boolean;
    mode: string;
    error_type: string | null;
  };
  metrics: {
    today_calls: number;
    success_count: number;
    today_prompt_tokens: number | null;
    today_completion_tokens: number | null;
    today_total_tokens: number | null;
    avg_latency_ms: number | null;
    latest_latency_ms: number | null;
    success_rate: number | null;
    failure_count: number;
    fallback_count: number;
    latest_success_at: string | null;
    latest_failure_at: string | null;
    latest_error_type: string | null;
  };
  note: string;
}

export interface AdminPermissions {
  roles: Array<{ name: string; description: string; permissions: string[] }>;
  users: Array<{ id: number; username: string; roles: string[]; status: string; last_login_at: string | null; created_at: string }>;
  editable: boolean;
  message: string;
}

export interface AuditLogItem {
  id: number;
  user_id: number | null;
  username: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  result: string;
  detail: unknown;
  created_at: string;
}

export interface AdminAuditLogs {
  total: number;
  limit: number;
  offset: number;
  items: AuditLogItem[];
}

export interface AdminAuditEventType {
  value: string;
  label: string;
}

export interface AdminConfig {
  items: Array<{
    label: string;
    name: string;
    value: unknown;
    description: string;
    default: unknown;
    requires_restart: boolean;
    sensitive: boolean;
    editable: boolean;
  }>;
  editable: boolean;
  message: string;
}

export function fetchAdminOverview(): Promise<AdminOverview> {
  return requestJson<AdminOverview>('/admin/console/overview');
}

export function fetchAdminHealth(): Promise<AdminServiceHealth> {
  return requestJson<AdminServiceHealth>('/admin/console/health');
}

export function fetchAdminLlm(): Promise<AdminLlmStatus> {
  return requestJson<AdminLlmStatus>('/admin/console/llm');
}

export function fetchAdminPermissions(): Promise<AdminPermissions> {
  return requestJson<AdminPermissions>('/admin/console/permissions');
}

export function updateAdminUserRole(userId: number, role: 'User' | 'Admin'): Promise<AdminPermissions['users'][number]> {
  return requestJson<AdminPermissions['users'][number]>(`/admin/console/users/${userId}/role`, {
    method: 'PATCH',
    body: JSON.stringify({ role }),
  });
}

export function deleteAdminUser(userId: number): Promise<void> {
  return requestJson<void>(`/admin/console/users/${userId}`, {
    method: 'DELETE',
  });
}

export function fetchAdminAuditEventTypes(): Promise<AdminAuditEventType[]> {
  return requestJson<AdminAuditEventType[]>('/admin/console/audit/event-types');
}

export function fetchAdminAuditLogs(params: { actionType?: string; username?: string; result?: string; limit?: number; offset?: number }): Promise<AdminAuditLogs> {
  const search = new URLSearchParams();
  if (params.actionType) search.set('action_type', params.actionType);
  if (params.username) search.set('username', params.username);
  if (params.result) search.set('result', params.result);
  search.set('limit', String(params.limit ?? 20));
  search.set('offset', String(params.offset ?? 0));
  return requestJson<AdminAuditLogs>(`/admin/console/audit-logs?${search.toString()}`);
}

export function fetchAdminConfig(): Promise<AdminConfig> {
  return requestJson<AdminConfig>('/admin/console/config');
}
