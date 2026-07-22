import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchLatestTrace } from '../api';
import { fetchDashboardOverview } from '../api/dashboard';
import { fetchDeviceStatistics, fetchDevices } from '../api/devices';
import { fetchDiagnosisHistory, fetchRecentAlarms } from '../api/diagnosis';
import { fetchSystemHealth } from '../api/health';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  PageShell,
  ProductHero,
  RiskBadge,
  RiskIntervalScale,
  SectionCard,
  StatusBadge,
} from '../components/IndustrialUI';
import { formatAlarmLabel, formatBusinessText, formatDateTime, formatRiskLevel, formatStatus, uniqueDocumentNames } from '../utils/reportFormatter';
import { formatDeviceName, formatDeviceType } from '../utils/deviceDisplay';
import { canViewReportDetail, resolvePrimaryRole } from '../utils/permissions';
import type {
  CurrentUser,
  DashboardOverview,
  DeviceStatistics,
  DiagnosisHistoryItem,
  RecentAlarm,
  RiskLevel,
  SystemHealth,
  ToolDeviceInfo,
  AgentTrace,
} from '../types';

type RiskDevice = {
  deviceCode: string;
  deviceName: string;
  deviceType: string;
  alarmLabels: string[];
  level: RiskLevel;
  latestAt: string;
};

const riskRank: Record<RiskLevel, number> = {
  unknown: 0,
  normal: 1,
  low: 2,
  medium: 3,
  high: 4,
  critical: 5,
};

export default function DashboardPage({ currentUser }: { currentUser: CurrentUser | null }) {
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [statistics, setStatistics] = useState<DeviceStatistics | null>(null);
  const [alarms, setAlarms] = useState<RecentAlarm[]>([]);
  const [history, setHistory] = useState<DiagnosisHistoryItem[]>([]);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [devices, setDevices] = useState<ToolDeviceInfo[]>([]);
  const [latestTrace, setLatestTrace] = useState<AgentTrace | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const role = resolvePrimaryRole(currentUser);
  const isUser = role === 'user';
  const canOpenReports = canViewReportDetail(currentUser);

  useEffect(() => {
    let cancelled = false;

    async function loadDashboard() {
      setLoading(true);
      setError(null);
      try {
        const [overviewData, statisticsData, alarmData, historyData, healthData, deviceData, traceData] = await Promise.all([
          fetchDashboardOverview(),
          fetchDeviceStatistics(),
          fetchRecentAlarms(),
          fetchDiagnosisHistory(20),
          fetchSystemHealth(),
          fetchDevices(),
          fetchLatestTrace().catch(() => null),
        ]);
        if (!cancelled) {
          setOverview(overviewData);
          setStatistics(statisticsData);
          setAlarms(alarmData);
          setHistory(historyData);
          setHealth(healthData);
          setDevices(deviceData);
          setLatestTrace(traceData);
        }
      } catch (dashboardError) {
        if (!cancelled) {
          setError(dashboardError instanceof Error ? dashboardError.message : '首页数据加载失败，请稍后重试。');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadDashboard();
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') void loadDashboard();
    };
    window.addEventListener('focus', refreshWhenVisible);
    document.addEventListener('visibilitychange', refreshWhenVisible);
    return () => {
      cancelled = true;
      window.removeEventListener('focus', refreshWhenVisible);
      document.removeEventListener('visibilitychange', refreshWhenVisible);
    };
  }, []);

  const unresolvedAlarms = alarms.filter((alarm) => alarm.status !== 'resolved');
  const totalDevices = statistics?.total ?? devices.length;
  const normalDeviceCount = statistics?.normal ?? 0;
  const abnormalDeviceCount = statistics?.warning ?? 0;
  const maintenanceDeviceCount = statistics?.maintenance ?? 0;
  const pendingAlarmCount = unresolvedAlarms.length;
  const dashboardRiskLevel = resolveDashboardRisk(totalDevices, abnormalDeviceCount, pendingAlarmCount);
  const topRiskDevices = useMemo(() => buildTopRiskDevices(unresolvedAlarms, devices), [unresolvedAlarms, devices]);
  const highestRiskDevice = topRiskDevices[0] ?? null;
  const latestSync = findLatestTime(history, alarms, devices);

  return (
    <PageShell>
      <ProductHero
        eyebrow={isUser ? 'Operations Center' : 'Industrial AI'}
        title={isUser ? '企业设备运行监控中心' : '企业设备智能运维控制台'}
        description={
          isUser
            ? '面向运维人员展示设备状态、异常报警、AI 辅助诊断报告和现场处置入口，帮助值班人员快速掌握运行风险。'
            : '汇总设备数据、报警记录、维修知识和 AI 分析能力，支撑设备风险识别、诊断报告生成和知识治理。'
        }
        side={
          <div className="grid gap-3 text-sm">
            <InfoLine label="当前账号" value={currentUser?.username ?? '未登录'} />
            <div className="flex items-center justify-between gap-3">
              <span className="text-slate-500">系统状态</span>
              <StatusBadge label={allHealthy(health) ? '运行正常' : '需要关注'} healthy={allHealthy(health)} />
            </div>
            <InfoLine label="最近同步" value={latestSync ? formatDateTime(latestSync) : '暂无同步记录'} />
          </div>
        }
      />

      {error ? <ErrorState message={error} /> : null}
      {loading ? <LoadingState title="正在读取企业运维数据" steps={['设备台账', '报警记录', '诊断报告']} /> : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6">
        <MetricCard label="设备总数" value={loading ? '-' : `${totalDevices} 台`} description="数据库设备台账总量" trend="来自 /devices/statistics" />
        <MetricCard label="正常运行设备" value={loading ? '-' : `${normalDeviceCount} 台`} description="最新运行状态为正常" tone="normal" trend="保持日常巡检" />
        <MetricCard label="异常设备" value={loading ? '-' : `${abnormalDeviceCount} 台`} description="最新运行状态为异常" tone={abnormalDeviceCount ? 'warning' : 'normal'} trend={abnormalDeviceCount ? '需要重点关注' : '暂无集中风险'} />
        <MetricCard label="维护中设备" value={loading ? '-' : `${maintenanceDeviceCount} 台`} description="离线或维护状态设备" tone={maintenanceDeviceCount ? 'warning' : 'normal'} trend="按维护计划跟进" />
        <MetricCard label="待处理报警" value={loading ? '-' : `${pendingAlarmCount} 条`} description="当前未关闭报警记录" tone={pendingAlarmCount ? 'warning' : 'normal'} trend="按风险等级处理" />
        <MetricCard label="今日诊断报告" value={loading ? '-' : `${overview?.today_diagnosis_count ?? 0} 份`} description="今日生成报告" trend="可在报告列表查看" />
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_380px]">
        <SectionCard eyebrow="Risk Decision" title="整体风险决策" right={<RiskBadge level={dashboardRiskLevel} />}>
          <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
            <div className="grid gap-4">
              <RiskIntervalScale
                level={dashboardRiskLevel}
                title="当前整体风险等级"
                basis={['异常设备数量', '未处理报警数量', '最近诊断记录']}
              />
              <div className="grid gap-3 md:grid-cols-3">
                <DecisionItem title="风险原因" items={buildRiskReasons(abnormalDeviceCount, maintenanceDeviceCount, pendingAlarmCount, history)} />
                <DecisionItem title="最高风险设备" items={highestRiskDevice ? [`${highestRiskDevice.deviceCode} · ${highestRiskDevice.deviceName}`, highestRiskDevice.alarmLabels[0] ?? '设备异常'] : ['暂无高风险设备']} />
                <DecisionItem title="建议动作" items={buildRecommendedActions(dashboardRiskLevel, highestRiskDevice)} />
              </div>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
              <div className="text-sm font-semibold text-slate-950">过去 7 天风险趋势</div>
              <p className="mt-3 text-sm leading-6 text-slate-600">{buildTrendNarrative(history, dashboardRiskLevel)}</p>
              <div className="mt-4 rounded-xl bg-white px-3 py-2 text-xs leading-5 text-slate-500 ring-1 ring-slate-200">
                趋势说明基于历史诊断报告、设备状态统计和未处理报警记录，不使用前端伪造时间序列。
              </div>
            </div>
          </div>
        </SectionCard>

        {isUser ? <BusinessServiceStatus health={health} /> : <AgentServiceStatus health={health} overview={overview} />}
      </div>

      <AgentTrajectory trace={latestTrace} latestReport={history[0] ?? null} latestAlarm={unresolvedAlarms[0] ?? null} />

      <div className="grid gap-5 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <RiskRanking topRiskDevices={topRiskDevices} history={history} canOpenReports={canOpenReports} />
        <RecentReports history={history} canOpenReports={canOpenReports} />
      </div>
    </PageShell>
  );
}

function InfoLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-slate-500">{label}</span>
      <span className="min-w-0 truncate font-semibold text-slate-950">{value}</span>
    </div>
  );
}

function DecisionItem({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-4">
      <div className="text-sm font-semibold text-slate-950">{title}</div>
      <ul className="mt-3 grid gap-2 text-sm leading-6 text-slate-600">
        {items.map((item) => (
          <li key={item} className="flex gap-2">
            <span className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-sky-600" />
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function BusinessServiceStatus({ health }: { health: SystemHealth | null }) {
  return (
    <SectionCard eyebrow="Service Status" title="智能分析服务状态" right={<StatusBadge label={allHealthy(health) ? '运行正常' : '需要关注'} healthy={allHealthy(health)} />}>
      <div className="mt-4 grid gap-3">
        <ServiceRow label="数据采集服务" healthy={health?.tools === 'healthy'} description="设备状态与报警数据可正常读取" />
        <ServiceRow label="异常检测服务" healthy={health?.router === 'healthy'} description="系统可识别设备异常与风险任务" />
        <ServiceRow label="分析报告服务" healthy={health?.llm === 'healthy'} description="可生成设备辅助诊断报告" />
      </div>
    </SectionCard>
  );
}

function AgentServiceStatus({ health, overview }: { health: SystemHealth | null; overview: DashboardOverview | null }) {
  return (
    <SectionCard eyebrow="Service Status" title="平台运行状态" right={<StatusBadge label={formatStatus(overview?.agent_status)} healthy={overview?.agent_status === 'healthy'} />}>
      <div className="mt-4 grid gap-3">
        <ServiceRow label="任务识别" healthy={health?.router === 'healthy'} description="识别诊断任务并规划执行链路" />
        <ServiceRow label="数据工具" healthy={health?.tools === 'healthy'} description="读取设备状态、报警记录和知识资料" />
        <ServiceRow label="知识检索" healthy={health?.rag === 'healthy'} description="检索企业维修知识和历史案例" />
        <ServiceRow label="AI 分析" healthy={health?.llm === 'healthy'} description="生成结构化诊断报告" />
      </div>
    </SectionCard>
  );
}

function ServiceRow({ label, description, healthy }: { label: string; description: string; healthy: boolean }) {
  return (
    <article className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-950">{label}</div>
          <div className="mt-1 text-xs leading-5 text-slate-500">{description}</div>
        </div>
        <StatusBadge label={healthy ? '正常' : '需关注'} healthy={healthy} />
      </div>
    </article>
  );
}

function AgentTrajectory({
  trace,
  latestReport,
  latestAlarm,
}: {
  trace: AgentTrace | null;
  latestReport: DiagnosisHistoryItem | null;
  latestAlarm: RecentAlarm | null;
}) {
  const toolCount = trace?.tool_results.filter((item) => item.success).length ?? 0;
  const documents = trace ? uniqueDocumentNames(trace.rag_results).slice(0, 2) : [];
  const steps = [
    {
      title: '异常发现',
      status: latestAlarm ? '已发现' : '暂无待处理异常',
      detail: latestAlarm ? `${latestAlarm.device_code} · ${latestAlarm.alarm_code} ${latestAlarm.alarm_name || ''}` : '当前未返回未处理报警记录。',
    },
    {
      title: '数据查询',
      status: trace ? '已完成' : '等待诊断任务',
      detail: trace ? `已执行 ${toolCount} 项数据获取。` : '暂无最近 Agent Trace。',
    },
    {
      title: '知识检索',
      status: documents.length ? '已命中' : '未返回引用',
      detail: documents.length ? documents.join(' / ') : '最近任务未返回企业知识库引用。',
    },
    {
      title: '诊断生成',
      status: latestReport ? '已生成报告' : '暂无报告',
      detail: latestReport ? `${latestReport.device_code ?? '多设备'} · ${formatDateTime(latestReport.created_at)}` : '尚未生成诊断报告。',
    },
  ];

  return (
    <SectionCard eyebrow="Agent Trajectory" title="AI Agent 运行轨迹" right={<StatusBadge label={trace ? '最近任务可追踪' : '暂无 Trace'} healthy={Boolean(trace)} />}>
      <div className="mt-4 grid gap-3 lg:grid-cols-4">
        {steps.map((step, index) => (
          <article key={step.title} className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
            <div className="flex items-center gap-3">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-sky-700 text-xs font-semibold text-white">{index + 1}</span>
              <div className="min-w-0">
                <div className="font-semibold text-slate-950">{step.title}</div>
                <div className="mt-1 text-xs font-semibold text-slate-500">{step.status}</div>
              </div>
            </div>
            <p className="mt-3 line-clamp-2 text-xs leading-5 text-slate-500">{step.detail}</p>
          </article>
        ))}
      </div>
    </SectionCard>
  );
}

function RiskRanking({
  topRiskDevices,
  history,
  canOpenReports,
}: {
  topRiskDevices: RiskDevice[];
  history: DiagnosisHistoryItem[];
  canOpenReports: boolean;
}) {
  return (
    <SectionCard eyebrow="Risk Devices" title="设备风险中心" right={<span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">TOP5</span>}>
      <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200">
        <table className="w-full table-fixed text-left text-sm">
          <thead className="bg-slate-50 text-xs font-semibold text-slate-500">
            <tr>
              <th className="w-[15%] px-4 py-3">设备编号</th>
              <th className="w-[21%] px-4 py-3">设备名称</th>
              <th className="w-[21%] px-4 py-3">异常类型</th>
              <th className="w-[15%] px-4 py-3">风险等级</th>
              <th className="w-[15%] px-4 py-3">更新时间</th>
              <th className="w-[13%] px-4 py-3 text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 bg-white">
            {topRiskDevices.length ? (
              topRiskDevices.slice(0, 5).map((device) => {
                const report = history.find((item) => item.device_code === device.deviceCode);
                return (
                  <tr key={device.deviceCode} className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-semibold text-slate-950">{device.deviceCode}</td>
                    <td className="px-4 py-3 text-slate-600">{device.deviceName}</td>
                    <td className="px-4 py-3 text-slate-600">{device.alarmLabels.join(' / ')}</td>
                    <td className="px-4 py-3"><RiskBadge level={device.level} /></td>
                    <td className="px-4 py-3 text-slate-500">{formatDateTime(device.latestAt)}</td>
                    <td className="px-4 py-3 text-right">
                      {canOpenReports && report ? (
                        <Link to={`/reports/${report.report_id}`} className="inline-flex h-9 min-w-[96px] items-center justify-center whitespace-nowrap rounded-lg border border-sky-400/30 bg-sky-400/10 px-3 text-xs font-semibold text-sky-100 transition hover:bg-sky-400/20">
                          查看诊断
                        </Link>
                      ) : (
                        <Link to={`/devices/${device.deviceCode}`} className="inline-flex h-9 min-w-[96px] items-center justify-center whitespace-nowrap rounded-lg border border-white/10 px-3 text-xs font-semibold text-slate-200 transition hover:border-sky-400/40 hover:text-sky-100">
                          设备详情
                        </Link>
                      )}
                    </td>
                  </tr>
                );
              })
            ) : (
              <tr><td colSpan={6} className="px-4 py-8"><EmptyState title="暂无风险设备" description="当前没有未处理报警设备，继续保持日常监控。" /></td></tr>
            )}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}

function RecentReports({ history, canOpenReports }: { history: DiagnosisHistoryItem[]; canOpenReports: boolean }) {
  return (
    <SectionCard eyebrow="Reports" title="最近分析报告" right={<span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">{history.length} 条</span>}>
      <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200">
        <div className="max-h-[520px] overflow-y-auto">
          {history.slice(0, 8).map((record) => (
            <article key={record.report_id} className="grid gap-3 border-b border-slate-200 bg-white px-4 py-3 last:border-b-0 hover:bg-slate-50 md:grid-cols-[minmax(0,1fr)_112px] md:items-center">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-slate-950">{record.device_code ?? '多设备风险分析'}</span>
                  <RiskBadge level={record.risk_level} />
                </div>
                <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-600">{formatBusinessText(record.problem_summary) || '系统已生成辅助诊断报告，请结合现场情况确认。'}</p>
                <p className="mt-2 text-xs text-slate-500">{formatDateTime(record.created_at)} · {formatStatus(record.status)}</p>
              </div>
              {canOpenReports ? (
                <Link to={`/reports/${record.report_id}`} className="inline-flex h-9 min-w-[92px] items-center justify-center whitespace-nowrap rounded-xl border border-sky-200 bg-white px-3 text-xs font-semibold text-sky-700 transition hover:bg-sky-50">
                  查看报告
                </Link>
              ) : null}
            </article>
          ))}
          {!history.length ? <div className="p-4"><EmptyState title="暂无分析报告" description="系统生成诊断后会在这里展示最近报告。" /></div> : null}
        </div>
      </div>
    </SectionCard>
  );
}

function buildTopRiskDevices(alarms: RecentAlarm[], devices: ToolDeviceInfo[]): RiskDevice[] {
  const deviceMap = new Map(devices.map((device) => [device.device_code, device]));
  const grouped = new Map<string, RiskDevice>();
  alarms.forEach((alarm) => {
    const device = deviceMap.get(alarm.device_code);
    const current = grouped.get(alarm.device_code);
    const level = alarm.alarm_level;
    if (!current) {
      grouped.set(alarm.device_code, {
        deviceCode: alarm.device_code,
        deviceName: device ? formatDeviceName(device) : alarm.device_code,
        deviceType: device ? formatDeviceType(device.device_type) : '设备',
        alarmLabels: [formatAlarmLabel(alarm)],
        level,
        latestAt: alarm.created_at,
      });
      return;
    }
    current.alarmLabels = Array.from(new Set([...current.alarmLabels, formatAlarmLabel(alarm)]));
    if (riskRank[level] > riskRank[current.level]) current.level = level;
    if (new Date(alarm.created_at).getTime() > new Date(current.latestAt).getTime()) current.latestAt = alarm.created_at;
  });
  return Array.from(grouped.values()).sort((a, b) => riskRank[b.level] - riskRank[a.level] || new Date(b.latestAt).getTime() - new Date(a.latestAt).getTime());
}

function resolveDashboardRisk(total: number, abnormal: number, pendingAlarms: number): RiskLevel {
  if (!total) return 'unknown';
  if (abnormal >= Math.max(3, Math.ceil(total * 0.4)) || pendingAlarms >= 5) return 'high';
  if (abnormal > 0 || pendingAlarms > 0) return 'medium';
  return 'normal';
}

function buildRiskReasons(abnormal: number, maintenance: number, pendingAlarms: number, history: DiagnosisHistoryItem[]): string[] {
  const reasons: string[] = [];
  if (abnormal > 0) reasons.push(`${abnormal} 台设备最新状态异常`);
  if (maintenance > 0) reasons.push(`${maintenance} 台设备处于维护或离线状态`);
  if (pendingAlarms > 0) reasons.push(`${pendingAlarms} 条报警仍待处理`);
  if (history.some((item) => ['high', 'critical'].includes(item.risk_level))) reasons.push('近期报告中存在高风险诊断');
  return reasons.length ? reasons : ['当前设备状态整体平稳'];
}

function buildRecommendedActions(level: RiskLevel, highestRiskDevice: RiskDevice | null): string[] {
  if (level === 'high' || level === 'critical') {
    return [
      highestRiskDevice ? `优先复核 ${highestRiskDevice.deviceCode}` : '优先复核高风险设备',
      '确认未处理报警和运行参数',
      '必要时安排现场停机检查',
    ];
  }
  if (level === 'medium') {
    return ['安排当班巡检', '跟进未处理报警', '观察设备状态是否继续恶化'];
  }
  return ['保持日常巡检', '继续沉淀维修记录'];
}

function buildTrendNarrative(history: DiagnosisHistoryItem[], riskLevel: RiskLevel): string {
  const recent = history.slice(0, 7);
  const highCount = recent.filter((item) => ['high', 'critical'].includes(item.risk_level)).length;
  if (!recent.length) return '暂无足够历史报告形成趋势判断。';
  if (riskLevel === 'high' || riskLevel === 'critical') {
    return `近期 ${recent.length} 份报告中有 ${highCount} 份为高风险或严重风险，整体风险处于较高区间。`;
  }
  if (riskLevel === 'medium') {
    return `近期仍存在关注级风险，建议持续跟进未处理报警和重点设备状态。`;
  }
  return '近期报告未显示明显集中风险，设备整体处于稳定运行区间。';
}

function findLatestTime(history: DiagnosisHistoryItem[], alarms: RecentAlarm[], devices: ToolDeviceInfo[]): string | null {
  const times = [
    ...history.map((item) => item.created_at),
    ...alarms.map((item) => item.created_at),
    ...devices.map((item) => item.created_at),
  ]
    .map((item) => new Date(item).getTime())
    .filter((item) => Number.isFinite(item));
  if (!times.length) return null;
  return new Date(Math.max(...times)).toISOString();
}

function allHealthy(health: SystemHealth | null): boolean {
  if (!health) return false;
  return [health.router, health.tools, health.rag, health.llm].every((item) => item === 'healthy');
}

