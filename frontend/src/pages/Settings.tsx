import { useEffect, useState } from 'react';
import {
  fetchAdminAuditEventTypes,
  fetchAdminAuditLogs,
  fetchAdminConfig,
  fetchAdminHealth,
  fetchAdminLlm,
  fetchAdminOverview,
  fetchAdminPermissions,
  deleteAdminUser,
  updateAdminUserRole,
  type AdminAuditEventType,
  type AdminAuditLogs,
  type AdminConfig,
  type AdminLlmStatus,
  type AdminOverview,
  type AdminPermissions,
  type AdminServiceHealth,
  type AuditLogItem,
} from '../api/admin';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  PageShell,
  ProductHero,
  SectionCard,
  StatusBadge,
} from '../components/IndustrialUI';
import type { CurrentUser } from '../types';
import { formatDateTime, formatDuration } from '../utils/reportFormatter';

type TabKey = 'overview' | 'health' | 'llm' | 'permissions' | 'audit' | 'config';

const tabs: Array<{ key: TabKey; label: string; description: string }> = [
  { key: 'overview', label: '系统概览', description: '核心摘要' },
  { key: 'health', label: '服务健康', description: '依赖状态' },
  { key: 'llm', label: 'AI 模型', description: '模型运行' },
  { key: 'permissions', label: '权限治理', description: '角色边界' },
  { key: 'audit', label: '审计日志', description: '治理行为' },
  { key: 'config', label: '系统配置', description: '只读配置' },
];

export default function SettingsPage({ currentUser }: { currentUser: CurrentUser | null }) {
  const canManageSystem = currentUser?.permissions.includes('users:manage') ?? false;
  const [activeTab, setActiveTab] = useState<TabKey>('overview');
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [health, setHealth] = useState<AdminServiceHealth | null>(null);
  const [llm, setLlm] = useState<AdminLlmStatus | null>(null);
  const [permissions, setPermissions] = useState<AdminPermissions | null>(null);
  const [audit, setAudit] = useState<AdminAuditLogs | null>(null);
  const [auditEventTypes, setAuditEventTypes] = useState<AdminAuditEventType[]>([]);
  const [config, setConfig] = useState<AdminConfig | null>(null);
  const [auditFilter, setAuditFilter] = useState({ actionType: '', username: '', result: '' });
  const [loading, setLoading] = useState(false);
  const [operationLoading, setOperationLoading] = useState<number | null>(null);
  const [operationMessage, setOperationMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastRefreshAt, setLastRefreshAt] = useState<string | null>(null);

  async function loadTab(tab: TabKey, options?: { force?: boolean }) {
    if (!canManageSystem) return;
    if (!options?.force) {
      if (tab === 'overview' && overview) return;
      if (tab === 'health' && health) return;
      if (tab === 'llm' && llm) return;
      if (tab === 'permissions' && permissions) return;
      if (tab === 'audit' && audit) return;
      if (tab === 'config' && config) return;
    }

    setLoading(true);
    setError(null);
    try {
      if (tab === 'overview') setOverview(await fetchAdminOverview());
      if (tab === 'health') setHealth(await fetchAdminHealth());
      if (tab === 'llm') setLlm(await fetchAdminLlm());
      if (tab === 'permissions') setPermissions(await fetchAdminPermissions());
      if (tab === 'audit') {
        const [types, logs] = await Promise.all([
          auditEventTypes.length ? Promise.resolve(auditEventTypes) : fetchAdminAuditEventTypes(),
          fetchAdminAuditLogs({ ...auditFilter, limit: 20, offset: 0 }),
        ]);
        setAuditEventTypes(types);
        setAudit(logs);
      }
      if (tab === 'config') setConfig(await fetchAdminConfig());
      setLastRefreshAt(new Date().toISOString());
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '系统管理数据加载失败。');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadTab(activeTab);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, canManageSystem]);

  async function refreshCurrentTab() {
    await loadTab(activeTab, { force: true });
  }

  async function applyAuditFilter() {
    setLoading(true);
    setError(null);
    try {
      setAudit(await fetchAdminAuditLogs({ ...auditFilter, limit: 20, offset: 0 }));
      setLastRefreshAt(new Date().toISOString());
    } catch (auditError) {
      setError(auditError instanceof Error ? auditError.message : '审计日志加载失败。');
    } finally {
      setLoading(false);
    }
  }

  async function clearAuditFilter() {
    const emptyFilter = { actionType: '', username: '', result: '' };
    setAuditFilter(emptyFilter);
    setLoading(true);
    setError(null);
    try {
      setAudit(await fetchAdminAuditLogs({ ...emptyFilter, limit: 20, offset: 0 }));
      setLastRefreshAt(new Date().toISOString());
    } catch (auditError) {
      setError(auditError instanceof Error ? auditError.message : '审计日志加载失败。');
    } finally {
      setLoading(false);
    }
  }

  async function changeUserRole(userId: number, role: 'User' | 'Admin') {
    setOperationLoading(userId);
    setOperationMessage(null);
    setError(null);
    try {
      await updateAdminUserRole(userId, role);
      setOperationMessage('用户角色已更新。');
      setPermissions(await fetchAdminPermissions());
      setLastRefreshAt(new Date().toISOString());
    } catch (roleError) {
      setError(roleError instanceof Error ? roleError.message : '用户角色更新失败。');
    } finally {
      setOperationLoading(null);
    }
  }

  async function removeUser(userId: number, username: string) {
    if (!window.confirm(`确认删除用户 ${username}？删除后该账号将无法登录。`)) return;
    setOperationLoading(userId);
    setOperationMessage(null);
    setError(null);
    try {
      await deleteAdminUser(userId);
      setOperationMessage(`用户 ${username} 已删除。`);
      setPermissions(await fetchAdminPermissions());
      setLastRefreshAt(new Date().toISOString());
    } catch (deleteError) {
      setError(deleteError instanceof Error ? deleteError.message : '用户删除失败。');
    } finally {
      setOperationLoading(null);
    }
  }

  return (
    <PageShell>
      <ProductHero
        eyebrow="Admin Console"
        title="系统管理控制台"
        description="Admin 专属的系统治理与运行监控。"
        side={
          <div className="grid gap-3 text-sm">
            <InfoLine label="当前管理员" value={currentUser?.username ?? '-'} />
            <InfoLine label="最近刷新" value={lastRefreshAt ? formatDateTime(lastRefreshAt) : '暂无数据'} />
            <button
              type="button"
              onClick={() => void refreshCurrentTab()}
              disabled={loading || !canManageSystem}
              className="h-10 rounded-xl bg-sky-700 text-sm font-semibold text-white transition hover:bg-sky-800 disabled:bg-slate-300"
            >
              {loading ? '刷新中...' : '重新检测'}
            </button>
          </div>
        }
      />

      {!canManageSystem ? <ErrorState message="当前账号暂无系统管理权限。" /> : null}
      {canManageSystem ? (
        <div className="grid gap-4">
          <div className="overflow-x-auto rounded-[24px] border border-slate-200 bg-white p-2 shadow-sm">
            <div className="flex min-w-max gap-2">
              {tabs.map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setActiveTab(tab.key)}
                  className={`rounded-2xl px-4 py-3 text-left transition ${
                    activeTab === tab.key
                      ? 'bg-sky-700 text-white shadow-sm'
                      : 'text-slate-600 hover:bg-slate-50 hover:text-slate-950'
                  }`}
                >
                  <div className="text-sm font-semibold">{tab.label}</div>
                  <div className="mt-1 text-xs opacity-75">{tab.description}</div>
                </button>
              ))}
            </div>
          </div>

          {error ? <ErrorState message={error} /> : null}
          {operationMessage ? (
            <div className="rounded-2xl border border-emerald-400/25 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-200">
              {operationMessage}
            </div>
          ) : null}
          {loading ? <LoadingState title="正在读取系统管理数据" steps={['请求后端', '校验权限', '渲染视图']} /> : null}

          {activeTab === 'overview' ? <OverviewTab overview={overview} /> : null}
          {activeTab === 'health' ? <HealthTab health={health} /> : null}
          {activeTab === 'llm' ? <LlmTab llm={llm} /> : null}
          {activeTab === 'permissions' ? (
            <PermissionsTab
              permissions={permissions}
              currentUserId={currentUser?.id ?? null}
              operationLoading={operationLoading}
              onChangeRole={(userId, role) => void changeUserRole(userId, role)}
              onDeleteUser={(userId, username) => void removeUser(userId, username)}
            />
          ) : null}
          {activeTab === 'audit' ? (
            <AuditTab
              audit={audit}
              filter={auditFilter}
              setFilter={setAuditFilter}
              eventTypes={auditEventTypes}
              onApply={() => void applyAuditFilter()}
              onClear={() => void clearAuditFilter()}
            />
          ) : null}
          {activeTab === 'config' ? <ConfigTab config={config} /> : null}
        </div>
      ) : null}
    </PageShell>
  );
}

function OverviewTab({ overview }: { overview: AdminOverview | null }) {
  if (!overview) return null;
  const modelTitle = overview.ai_model.model ?? '暂无模型';
  return (
    <div className="grid gap-5">
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="核心服务" value={`${overview.core_services.healthy}/${overview.core_services.total} 正常`} description="API、数据库、向量库、AI 模型" tone={overview.core_services.status === 'healthy' ? 'normal' : 'warning'} />
        <MetricCard label="AI 模型" value={overview.ai_model.reachable ? '可用' : '不可用'} description={`${modelTitle} · ${overview.ai_model.mode ?? '未知模式'}`} tone={overview.ai_model.reachable ? 'normal' : 'danger'} />
        <MetricCard label="今日模型调用" value={`${overview.today_llm_calls} 次`} description="真实业务模型调用" />
        <MetricCard label="今日错误" value={`${overview.today_errors} 次`} description="来自审计日志失败事件" tone={overview.today_errors ? 'warning' : 'normal'} />
      </div>
      <div className="grid items-start gap-5 xl:grid-cols-2">
        <SectionCard eyebrow="Summary" title="系统摘要">
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <InfoTile label="运行环境" value={formatEnvironmentDisplay(overview.environment)} />
            <InfoTile label="应用版本" value={overview.app_version} />
            <InfoTile label="注册用户" value={`${overview.registered_users} 人`} />
            <InfoTile label="启用用户" value={`${overview.active_users} 人`} />
            <InfoTile label="今日 Token" value={overview.today_total_tokens == null ? '暂无真实调用记录' : String(overview.today_total_tokens)} />
            <InfoTile label="最近检查" value={formatDateTime(overview.checked_at)} />
          </div>
        </SectionCard>
        <SectionCard eyebrow="Recent Exception" title="最近异常">
          <div className="mt-4">
            {overview.latest_error ? <AuditCard item={overview.latest_error} /> : <EmptyState title="暂无系统异常" description="当前没有可展示的失败审计事件。" />}
          </div>
        </SectionCard>
      </div>
    </div>
  );
}

function HealthTab({ health }: { health: AdminServiceHealth | null }) {
  if (!health) return null;
  return (
    <SectionCard eyebrow="Service Health" title="服务健康">
      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        {health.services.map((service) => (
          <article key={service.name} className="rounded-[24px] border border-slate-200 bg-slate-50 p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="text-lg font-semibold text-slate-950">{service.name}</h3>
                <p className="mt-1 text-sm text-slate-500">{service.description}</p>
              </div>
              <StatusBadge label={statusLabel(service.status)} healthy={service.status === 'healthy'} />
            </div>
            <dl className="mt-4 grid gap-x-6 gap-y-2 text-sm md:grid-cols-2">
              <CompactRow label="最近检测" value={formatDateTime(health.checked_at)} />
              <CompactRow label="响应延迟" value={service.latency_ms == null ? '暂无检测记录' : formatDuration(service.latency_ms)} />
              <CompactRow label="运行模式" value={service.mode ?? '暂无数据'} />
              <CompactRow label="版本/标识" value={service.version ?? '暂无数据'} />
            </dl>
            {service.error ? <div className="mt-4 rounded-2xl bg-red-50 p-3 text-sm text-red-700">错误原因：{service.error}</div> : null}
          </article>
        ))}
      </div>
    </SectionCard>
  );
}

function LlmTab({ llm }: { llm: AdminLlmStatus | null }) {
  if (!llm) return null;
  const config = llm.configuration;
  const metrics = llm.metrics;
  return (
    <div className="grid gap-5">
      <SectionCard eyebrow="Model Runtime" title={friendlyModelTitle(config.model)}>
        <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <InfoTile label="Provider" value={config.provider} />
          <InfoTile label="Provider Class" value={config.provider_class ?? '暂无数据'} />
          <InfoTile label="Model" value={config.model ?? '暂无数据'} />
          <InfoTile label="Domain" value={config.base_url_domain ?? '未配置'} />
          <InfoTile label="Mode" value={config.mode === 'mock' ? 'Mock 开发模式' : '真实模型'} />
          <InfoTile label="Configured" value={config.configured ? '已配置' : '未配置'} />
          <InfoTile label="Reachable" value={config.reachable ? '可达' : '不可达'} />
          <InfoTile label="最近错误" value={config.error_type ?? '无'} />
        </div>
      </SectionCard>
      <SectionCard eyebrow="Usage Metrics" title="运行指标">
        <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <MetricCard label="今日模型调用" value={`${metrics.today_calls} 次`} description="真实业务 LLM invocation" />
          <MetricCard label="今日成功调用" value={`${metrics.success_count} 次`} description="真实模型成功返回" tone={metrics.success_count ? 'normal' : 'default'} />
          <MetricCard label="今日失败调用" value={`${metrics.failure_count} 次`} description="真实模型失败记录" tone={metrics.failure_count ? 'warning' : 'normal'} />
          <MetricCard label="Fallback" value={`${metrics.fallback_count} 次`} description="降级生成次数" tone={metrics.fallback_count ? 'warning' : 'normal'} />
          <MetricCard label="Prompt Tokens" value={metrics.today_prompt_tokens == null ? '暂无真实调用记录' : String(metrics.today_prompt_tokens)} description="今日真实输入 token" />
          <MetricCard label="Completion Tokens" value={metrics.today_completion_tokens == null ? '暂无真实调用记录' : String(metrics.today_completion_tokens)} description="今日真实输出 token" />
          <MetricCard label="Total Tokens" value={metrics.today_total_tokens == null ? '暂无真实调用记录' : String(metrics.today_total_tokens)} description="Prompt + Completion" />
          <MetricCard label="平均耗时" value={metrics.avg_latency_ms == null ? '暂无数据' : formatDuration(metrics.avg_latency_ms)} description="业务模型调用平均响应时间" />
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-2">
          <InfoTile label="最近成功调用" value={metrics.latest_success_at ? formatDateTime(metrics.latest_success_at) : '暂无数据'} />
          <InfoTile label="最近失败调用" value={metrics.latest_failure_at ? formatDateTime(metrics.latest_failure_at) : '暂无数据'} />
        </div>
        <div className="mt-4 rounded-2xl bg-slate-50 p-4 text-sm leading-6 text-slate-500">{llm.note}</div>
      </SectionCard>
    </div>
  );
}

function PermissionsTab({
  permissions,
  currentUserId,
  operationLoading,
  onChangeRole,
  onDeleteUser,
}: {
  permissions: AdminPermissions | null;
  currentUserId: number | null;
  operationLoading: number | null;
  onChangeRole: (userId: number, role: 'User' | 'Admin') => void;
  onDeleteUser: (userId: number, username: string) => void;
}) {
  if (!permissions) return null;
  const userRole = permissions.roles.find((role) => role.name === 'User');
  const adminRole = permissions.roles.find((role) => role.name === 'Admin');
  return (
    <div className="grid gap-5">
      <SectionCard eyebrow="Role Policy" title="角色策略">
        <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm leading-6 text-slate-600">
          {permissions.message}
        </div>
        <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200">
          <table className="w-full table-fixed text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-4 py-3">能力</th>
                <th className="px-4 py-3">User</th>
                <th className="px-4 py-3">Admin</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 bg-white">
              {permissionRows.map((row) => (
                <tr key={row.permission}>
                  <td className="px-4 py-3 font-semibold text-slate-800">{row.label}</td>
                  <td className="px-4 py-3">{userRole?.permissions.includes(row.permission) ? <Allowed /> : <Denied />}</td>
                  <td className="px-4 py-3">{adminRole?.permissions.includes(row.permission) ? <Allowed /> : <Denied />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </SectionCard>
      <SectionCard eyebrow="Users" title="用户治理">
        <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200">
          <table className="w-full table-fixed text-left text-sm">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <th className="w-[28%] px-4 py-3">用户</th>
                <th className="w-[18%] px-4 py-3">状态</th>
                <th className="w-[20%] px-4 py-3">角色</th>
                <th className="w-[22%] px-4 py-3">创建时间</th>
                <th className="w-[12%] px-4 py-3 text-right">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 bg-white">
              {permissions.users.map((user) => {
                const role = user.roles.includes('Admin') ? 'Admin' : 'User';
                const busy = operationLoading === user.id;
                const isSelf = user.id === currentUserId;
                return (
                  <tr key={user.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <div className="font-semibold text-slate-950">{user.username}</div>
                      <div className="mt-1 text-xs text-slate-500">ID：{user.id}</div>
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge label={user.status === 'active' ? '启用' : user.status} healthy={user.status === 'active'} />
                    </td>
                    <td className="px-4 py-3">
                      <select
                        value={role}
                        disabled={busy || isSelf}
                        onChange={(event) => onChangeRole(user.id, event.target.value as 'User' | 'Admin')}
                        className="h-9 w-full rounded-xl border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-800 outline-none transition focus:border-sky-500 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-500"
                      >
                        <option value="User">User 运维用户</option>
                        <option value="Admin">Admin 管理员</option>
                      </select>
                    </td>
                    <td className="px-4 py-3 text-slate-500">{formatDateTime(user.created_at)}</td>
                    <td className="px-4 py-3 text-right">
                      <button
                        type="button"
                        disabled={busy || isSelf}
                        onClick={() => onDeleteUser(user.id, user.username)}
                        className="inline-flex h-9 items-center justify-center whitespace-nowrap rounded-xl border border-red-400/30 px-3 text-xs font-semibold text-red-200 transition hover:bg-red-500/10 disabled:cursor-not-allowed disabled:border-slate-600 disabled:text-slate-500"
                      >
                        {busy ? '处理中' : isSelf ? '当前账号' : '删除'}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </SectionCard>
    </div>
  );
}

function AuditTab({
  audit,
  filter,
  setFilter,
  eventTypes,
  onApply,
  onClear,
}: {
  audit: AdminAuditLogs | null;
  filter: { actionType: string; username: string; result: string };
  setFilter: (filter: { actionType: string; username: string; result: string }) => void;
  eventTypes: AdminAuditEventType[];
  onApply: () => void;
  onClear: () => void;
}) {
  return (
    <SectionCard eyebrow="Audit Logs" title="审计日志">
      <div className="mt-4 grid gap-3 md:grid-cols-[220px_1fr_180px_auto_auto]">
        <select value={filter.actionType} onChange={(event) => setFilter({ ...filter, actionType: event.target.value })} className="h-11 rounded-2xl border border-slate-300 px-3 text-sm outline-none focus:border-sky-600">
          <option value="">全部操作类型</option>
          {eventTypes.map((type) => (
            <option key={type.value} value={type.value}>{type.label}</option>
          ))}
        </select>
        <input value={filter.username} onChange={(event) => setFilter({ ...filter, username: event.target.value })} placeholder="输入用户名" className="h-11 rounded-2xl border border-slate-300 px-3 text-sm outline-none focus:border-sky-600" />
        <select value={filter.result} onChange={(event) => setFilter({ ...filter, result: event.target.value })} className="h-11 rounded-2xl border border-slate-300 px-3 text-sm outline-none focus:border-sky-600">
          <option value="">全部结果</option>
          <option value="success">成功</option>
          <option value="failed">失败</option>
        </select>
        <button type="button" onClick={onApply} className="h-11 rounded-2xl bg-sky-700 px-5 text-sm font-semibold text-white hover:bg-sky-800">筛选</button>
        <button type="button" onClick={onClear} className="h-11 rounded-2xl border border-slate-200 bg-white px-5 text-sm font-semibold text-slate-700 hover:bg-slate-50">清空</button>
      </div>
      <div className="mt-4 grid gap-3">
        {audit?.items.map((item) => <AuditCard key={item.id} item={item} />)}
        {audit && !audit.items.length ? <EmptyState title="未找到符合条件的审计日志" description="请调整操作类型、操作人或结果筛选条件后重试。" /> : null}
      </div>
    </SectionCard>
  );
}

function ConfigTab({ config }: { config: AdminConfig | null }) {
  if (!config) return null;
  return (
    <SectionCard eyebrow="Configuration" title="系统配置">
      <div className="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-4 text-sm leading-6 text-slate-600">{config.message}</div>
      <div className="mt-4 grid gap-3">
        {config.items.map((item) => (
          <article key={item.name} className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 md:grid-cols-[220px_minmax(0,1fr)_140px] md:items-center">
            <div>
              <div className="font-semibold text-slate-950">{item.label}</div>
              <div className="mt-1 text-xs text-slate-500">{item.name}</div>
              <div className="mt-1 text-xs text-slate-500">{item.requires_restart ? '修改后需重启' : '即时读取'}</div>
            </div>
            <div className="text-sm leading-6 text-slate-600">
              <div className="font-semibold text-slate-900">{String(item.value)}</div>
              <div className="mt-1">{item.description}</div>
            </div>
            <StatusBadge label={item.editable ? '可编辑' : '只读'} healthy={!item.sensitive} />
          </article>
        ))}
      </div>
    </SectionCard>
  );
}

function AuditCard({ item }: { item: AuditLogItem }) {
  return (
    <article className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-slate-950">{translateAction(item.action)}</div>
          <div className="mt-1 text-xs text-slate-500">操作人：{item.username ?? '系统'} · 对象：{item.resource_type}{item.resource_id ? ` / ${item.resource_id}` : ''}</div>
          <div className="mt-2 text-xs text-slate-500">{formatDateTime(item.created_at)}</div>
        </div>
        <StatusBadge label={item.result === 'success' ? '成功' : '失败'} healthy={item.result === 'success'} />
      </div>
    </article>
  );
}

function InfoLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-slate-500">{label}</span>
      <span className="min-w-0 truncate text-right font-semibold text-slate-950">{value}</span>
    </div>
  );
}

function InfoTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <div className="text-xs font-semibold text-slate-500">{label}</div>
      <div className="mt-2 break-words text-sm font-semibold text-slate-950">{value}</div>
    </div>
  );
}

function CompactRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[86px_minmax(0,1fr)] gap-3">
      <dt className="text-slate-500">{label}</dt>
      <dd className="min-w-0 truncate font-semibold text-slate-800">{value}</dd>
    </div>
  );
}

function Allowed() {
  return <span className="inline-flex rounded-full bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-700 ring-1 ring-emerald-200">允许</span>;
}

function Denied() {
  return <span className="inline-flex rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-500 ring-1 ring-slate-200">不可用</span>;
}

const permissionRows = [
  { label: '查看设备画像', permission: 'devices:view' },
  { label: '查看风险事件', permission: 'reports:view' },
  { label: '查看诊断报告', permission: 'reports:view' },
  { label: '查看维修闭环', permission: 'reports:view' },
  { label: '执行智能诊断', permission: 'diagnosis:execute' },
  { label: '触发风险扫描', permission: 'diagnosis:execute' },
  { label: '管理知识库', permission: 'knowledge:upload' },
  { label: '查看 Agent 监控', permission: 'users:manage' },
  { label: '查看审计日志', permission: 'users:manage' },
  { label: '查看系统配置', permission: 'users:manage' },
];

function statusLabel(status: string): string {
  if (status === 'healthy') return '正常';
  if (status === 'degraded') return '警告';
  if (status === 'unhealthy') return '异常';
  return '未知';
}

function friendlyModelTitle(model: string | null): string {
  if (!model) return 'AI 模型服务';
  if (model.includes('deepseek')) return 'DeepSeek Chat';
  if (model.includes('qwen')) return 'Qwen';
  return model;
}

function formatEnvironmentDisplay(environment: string): string {
  const normalized = environment.toLowerCase();
  if (normalized === 'demo') return '企业演示环境';
  if (normalized === 'production' || normalized === 'prod') return '生产环境';
  if (normalized === 'development' || normalized === 'dev') return '开发环境';
  if (normalized === 'test' || normalized === 'testing') return '测试环境';
  return environment;
}

function translateAction(action: string): string {
  const map: Record<string, string> = {
    'auth.login': '用户登录',
    'auth.register': '用户注册',
    'diagnosis.execute': '执行智能诊断',
    'diagnosis.risk_analysis': '执行全局风险分析',
    'risk.scan': '触发风险扫描',
    'knowledge.upload': '上传知识文档',
    'knowledge.delete': '删除知识文档',
    'maintenance.create': '创建维修记录',
    'config.read': '系统配置读取',
    'llm.failed': 'LLM 调用失败',
    'agent.failed': 'Agent 执行失败',
    'health.failed': '健康检查异常',
  };
  return map[action] ?? action;
}

