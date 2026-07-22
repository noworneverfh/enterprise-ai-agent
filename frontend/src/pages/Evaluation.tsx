import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { fetchDashboardOverview } from '../api/dashboard';
import { fetchDiagnosisHistory, fetchRecentAlarms } from '../api/diagnosis';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  PageShell,
  ProductHero,
  RiskBadge,
  SectionCard,
} from '../components/IndustrialUI';
import { formatAlarmName, formatBusinessText, formatDateTime, formatDuration, formatStatus } from '../utils/reportFormatter';
import { canViewReportDetail, resolvePrimaryRole } from '../utils/permissions';
import type { CurrentUser, DashboardOverview, DiagnosisHistoryItem, RecentAlarm } from '../types';

export default function EvaluationPage({ currentUser }: { currentUser: CurrentUser | null }) {
  const [history, setHistory] = useState<DiagnosisHistoryItem[]>([]);
  const [alarms, setAlarms] = useState<RecentAlarm[]>([]);
  const [overview, setOverview] = useState<DashboardOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const role = resolvePrimaryRole(currentUser);
  const isUser = role === 'user';
  const canOpenReports = canViewReportDetail(currentUser);

  useEffect(() => {
    let cancelled = false;
    async function loadData() {
      setLoading(true);
      setError(null);
      try {
        const [records, alarmData, overviewData] = await Promise.all([
          fetchDiagnosisHistory(30),
          fetchRecentAlarms(),
          fetchDashboardOverview(),
        ]);
        if (!cancelled) {
          setHistory(records);
          setAlarms(alarmData);
          setOverview(overviewData);
        }
      } catch (loadError) {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : '报告数据加载失败。');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadData();
    return () => {
      cancelled = true;
    };
  }, []);

  const metrics = useMemo(() => buildServiceMetrics(history, alarms, overview), [history, alarms, overview]);

  return (
    <PageShell>
      <ProductHero
        eyebrow={isUser ? 'Service Reports' : 'Platform Governance'}
        title={isUser ? '设备诊断服务报告' : '平台治理与智能服务质量'}
        description={
          isUser
            ? '汇总历史诊断、待确认异常和高风险设备，帮助运维人员快速判断近期设备风险处理情况。'
            : '面向管理员展示报告生成、证据覆盖、知识引用和响应时间，指标均来自真实诊断历史。'
        }
      />

      {error ? <ErrorState message={error} /> : null}
      {loading ? <LoadingState title="正在加载报告记录" steps={['历史报告', '报警数据', '服务概览']} /> : null}

      {isUser ? (
        <UserServiceReport history={history} loading={loading} metrics={metrics} canOpenReports={canOpenReports} />
      ) : (
        <AdminGovernanceReport history={history} loading={loading} metrics={metrics} canOpenReports={canOpenReports} />
      )}
    </PageShell>
  );
}

function UserServiceReport({
  history,
  loading,
  metrics,
  canOpenReports,
}: {
  history: DiagnosisHistoryItem[];
  loading: boolean;
  metrics: ReturnType<typeof buildServiceMetrics>;
  canOpenReports: boolean;
}) {
  return (
    <>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="累计诊断报告" value={loading ? '-' : String(history.length)} description="系统已生成的设备分析报告总数" />
        <MetricCard label="待确认异常" value={loading ? '-' : String(metrics.pendingAlarmCount)} description="仍需现场确认或处理的报警" tone={metrics.pendingAlarmCount ? 'warning' : 'normal'} />
        <MetricCard label="高风险设备" value={loading ? '-' : String(metrics.highRiskDeviceCount)} description="存在高风险或严重风险报警的设备" tone={metrics.highRiskDeviceCount ? 'danger' : 'normal'} />
        <MetricCard label="已完成报告" value={loading ? '-' : String(metrics.completedReportCount)} description="已完成生成的历史诊断报告" />
      </div>
      <ReportTable title="最近诊断报告" history={history} loading={loading} userMode canOpenReports={canOpenReports} />
    </>
  );
}

function AdminGovernanceReport({
  history,
  loading,
  metrics,
  canOpenReports,
}: {
  history: DiagnosisHistoryItem[];
  loading: boolean;
  metrics: ReturnType<typeof buildServiceMetrics>;
  canOpenReports: boolean;
}) {
  return (
    <>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="报告生成成功率" value={loading ? '-' : `${metrics.reportSuccessRate}%`} description="已完成报告占历史诊断记录比例" tone={metrics.reportSuccessRate >= 90 ? 'normal' : 'warning'} />
        <MetricCard label="证据覆盖率" value={loading ? '-' : `${metrics.evidenceCoverageRate}%`} description="包含工具结果或知识来源的报告比例" tone={metrics.evidenceCoverageRate >= 80 ? 'normal' : 'warning'} />
        <MetricCard label="知识引用率" value={loading ? '-' : `${metrics.knowledgeCitationRate}%`} description="包含企业维修资料引用的报告比例" tone={metrics.knowledgeCitationRate >= 60 ? 'normal' : 'warning'} />
        <MetricCard label="平均响应时间" value={loading ? '-' : formatDuration(metrics.averageLatencyMs)} description="来自诊断历史耗时字段" />
      </div>
      <ReportTable title="最近平台报告" history={history} loading={loading} canOpenReports={canOpenReports} />
    </>
  );
}

function ReportTable({
  title,
  history,
  loading,
  userMode = false,
  canOpenReports,
}: {
  title: string;
  history: DiagnosisHistoryItem[];
  loading: boolean;
  userMode?: boolean;
  canOpenReports: boolean;
}) {
  return (
    <SectionCard eyebrow={userMode ? '报告列表' : '治理记录'} title={title} right={<span className="rounded-full bg-slate-100 px-3 py-1 text-xs font-semibold text-slate-600">{history.length} 条</span>}>
      <div className="mt-4 overflow-hidden rounded-2xl border border-slate-200">
        <table className="min-w-full divide-y divide-slate-200 text-sm">
          <thead className="bg-slate-50 text-xs text-slate-500">
            <tr>
              <th className="px-4 py-3 text-left">{userMode ? '设备' : '报告对象'}</th>
              <th className="px-4 py-3 text-left">异常类型</th>
              <th className="px-4 py-3 text-left">诊断状态</th>
              <th className="px-4 py-3 text-left">风险等级</th>
              <th className="px-4 py-3 text-left">生成时间</th>
              <th className="px-4 py-3 text-left">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 bg-white">
            {loading ? (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-500">正在加载记录...</td></tr>
            ) : history.length ? (
              history.slice(0, 12).map((record) => (
                <tr key={record.report_id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 font-semibold text-slate-950">{record.device_code ?? '多设备风险分析'}</td>
                  <td className="px-4 py-3 text-slate-600">{record.alarm_code ? `${record.alarm_code} ${record.alarm_name ?? formatAlarmName(record.alarm_code)}` : '综合风险分析'}</td>
                  <td className="px-4 py-3 text-slate-600">{formatStatus(record.status)}</td>
                  <td className="px-4 py-3"><RiskBadge level={record.risk_level} /></td>
                  <td className="px-4 py-3 text-slate-500">{formatDateTime(record.created_at)}</td>
                  <td className="px-4 py-3">
                    {canOpenReports ? (
                      <Link to={`/reports/${record.report_id}`} className="inline-flex h-8 min-w-[92px] items-center justify-center whitespace-nowrap rounded-lg border border-sky-200 bg-sky-50 px-3 text-xs font-semibold text-sky-700 transition hover:bg-sky-100">
                        查看报告
                      </Link>
                    ) : (
                      <span className="text-xs text-slate-400">暂无权限</span>
                    )}
                  </td>
                </tr>
              ))
            ) : (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-500">暂无历史记录。</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {!loading && !history.length ? <div className="mt-4"><EmptyState title="暂无报告" description="执行诊断后会在这里生成报告记录。" /></div> : null}
    </SectionCard>
  );
}

function buildServiceMetrics(history: DiagnosisHistoryItem[], alarms: RecentAlarm[], overview: DashboardOverview | null) {
  const pendingAlarms = alarms.filter((alarm) => alarm.status !== 'resolved');
  const highRiskDevices = new Set(pendingAlarms.filter((alarm) => ['high', 'critical'].includes(alarm.alarm_level)).map((alarm) => alarm.device_code));
  const completed = history.filter((record) => record.status === 'completed').length;
  const withEvidence = history.filter((record) => record.tools_used.length || record.sources.length).length;
  const withKnowledge = history.filter((record) => record.sources.length).length;

  return {
    pendingAlarmCount: pendingAlarms.length,
    highRiskDeviceCount: highRiskDevices.size,
    completedReportCount: completed,
    reportSuccessRate: percentage(completed, history.length),
    evidenceCoverageRate: percentage(withEvidence, history.length),
    knowledgeCitationRate: percentage(withKnowledge, history.length),
    averageLatencyMs: overview?.avg_response_time ?? null,
  };
}

function percentage(value: number, total: number): number {
  if (!total) return 0;
  return Math.round((value / total) * 100);
}
