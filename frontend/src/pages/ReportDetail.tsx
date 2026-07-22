import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { fetchDiagnosisReport } from '../api/diagnosis';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  PageShell,
  RiskBadge,
  RiskIntervalScale,
  riskBandLabel,
  SectionCard,
  StatusBadge,
  TrendLine,
} from '../components/IndustrialUI';
import {
  formatAlarmName,
  formatBusinessText,
  formatDateTime,
  formatDocumentName,
  formatKnowledgeSummary,
  formatRiskLevel,
  formatStatus,
  uniqueKnowledgeEvidence,
} from '../utils/reportFormatter';
import { formatDeviceName, formatDeviceType } from '../utils/deviceDisplay';
import type {
  DiagnosisHistoryDetail,
  DiagnosisRagSource,
  DiagnosisReportV2,
  FleetRiskReportV2,
  RiskLevel,
  ToolAlarmRecord,
  ToolRuntimeData,
} from '../types';

type DeviceCard = {
  code: string;
  name: string;
  type: string;
  location: string;
  online: boolean;
  runtime: ToolRuntimeData | null;
  alarms: ToolAlarmRecord[];
  riskLevel: RiskLevel;
};

export default function ReportDetailPage() {
  const { reportId } = useParams<{ reportId: string }>();
  const [report, setReport] = useState<DiagnosisHistoryDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function loadReport() {
      if (!reportId) {
        setError('报告编号缺失，请返回列表重新选择。');
        setLoading(false);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const data = await fetchDiagnosisReport(reportId);
        if (!cancelled) setReport(data);
      } catch (loadError) {
        if (!cancelled) setError(loadError instanceof Error ? loadError.message : '报告详情加载失败，请稍后重试。');
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void loadReport();
    return () => {
      cancelled = true;
    };
  }, [reportId]);

  const devices = useMemo(() => buildDeviceCards(report), [report]);
  const summary = useMemo(() => buildSummary(report), [report]);
  const causes = useMemo(() => buildCauses(report), [report]);
  const actions = useMemo(() => buildActionSteps(report), [report]);
  const facts = useMemo(() => buildFacts(report), [report]);
  const knowledgeSources = useMemo(() => buildKnowledgeSources(report), [report]);

  return (
    <PageShell>
      <div className="rounded-[24px] border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-sky-700">AI Diagnosis Report</p>
            <h1 className="mt-2 text-2xl font-semibold text-slate-950">
              {loading ? '正在加载报告...' : report ? reportTitle(report) : '报告不存在'}
            </h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              本报告根据设备运行参数、报警记录和企业维修知识库生成，用于辅助现场排查。最终处理结论应结合现场检查确认。
            </p>
          </div>
          <Link to="/evaluation" className="inline-flex h-10 items-center justify-center whitespace-nowrap rounded-xl border border-slate-200 bg-white px-4 text-sm font-semibold text-slate-700 transition hover:border-sky-200 hover:bg-sky-50 hover:text-sky-700">
            返回报告列表
          </Link>
        </div>
      </div>

      {error ? <ErrorState message={error} /> : null}

      {loading ? (
        <LoadingState title="正在读取诊断报告" steps={['报告摘要', '证据链', '维修建议']} />
      ) : report ? (
        <>
          <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
            <section className="rounded-[24px] border border-slate-200 bg-white p-5 shadow-sm">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.14em] text-sky-700">AI诊断结论</p>
                <h2 className="mt-2 text-2xl font-semibold leading-9 text-slate-950">{summary}</h2>
                <p className="mt-3 text-sm leading-6 text-slate-500">
                  分析对象：{report.device_code ?? '多设备风险分析'}；异常类型：{report.alarm_code ? `${report.alarm_code} ${report.alarm_name ?? formatAlarmName(report.alarm_code)}` : alarmSummary(report)}。
                </p>
                <div className="mt-5 grid gap-3 sm:grid-cols-3">
                  <SummaryPill label="关联设备" value={`${devices.length || 1} 台`} />
                  <SummaryPill label="待处理报警" value={`${countAlarms(report)} 条`} />
                  <SummaryPill label="维修资料" value={`${knowledgeSources.length} 份`} />
                </div>
              </div>
            </section>
            <RiskIntervalScale
              level={report.risk_level}
              title="本次诊断风险区间"
              basis={['设备事实', '报警记录', '参数观察', '维修资料引用']}
              className="self-start"
            />
          </div>

          <div className="grid gap-4 md:grid-cols-4">
            <MetricCard label="关联设备" value={`${devices.length || 1} 台`} description="报告覆盖设备范围" />
            <MetricCard label="待处理报警" value={`${countAlarms(report)} 条`} description="当前报告识别的报警数量" tone={countAlarms(report) ? 'warning' : 'normal'} />
            <MetricCard label="维修资料" value={`${knowledgeSources.length} 份`} description="企业知识库引用资料" />
            <MetricCard label="报告状态" value={formatStatus(report.status)} description={formatDateTime(report.created_at)} />
          </div>

          <SectionCard eyebrow="Evidence Chain" title="诊断依据" right={<StatusBadge label={`${facts.length} 项证据`} />}>
            <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {facts.map((fact) => <EvidenceFactCard key={fact.name} fact={fact} />)}
            </div>
          </SectionCard>

          <SectionCard eyebrow="Device State" title="设备运行情况" right={<StatusBadge label={`${devices.length || 1} 台设备`} />}>
            <div className={devices.length <= 1 ? 'mt-4 grid gap-4' : 'mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3'}>
              {devices.length ? devices.map((device) => <DeviceInfoCard key={device.code} device={device} />) : <EmptyState title="暂无设备信息" description="该报告未返回设备资产信息。" />}
            </div>
          </SectionCard>

          <div className="grid gap-4 xl:grid-cols-2">
            <SectionCard eyebrow="Cause Analysis" title="AI异常原因分析" right={<StatusBadge label={`${causes.length} 条`} />}>
              <div className="mt-4 grid gap-3">
                {causes.length ? causes.map((cause, index) => <CauseCard key={`${cause}-${index}`} cause={cause} index={index} hasCitation={knowledgeSources.length > 0} />) : <EmptyState title="暂无明确原因" description="当前证据不足，建议补充现场巡检数据后复核。" />}
              </div>
            </SectionCard>

            <SectionCard eyebrow="Action Plan" title="处理建议" right={<StatusBadge label={`${actions.length} 步`} />}>
              <div className="mt-4 grid gap-3">
                {actions.length ? actions.map((action, index) => <ActionCard key={`${action}-${index}`} action={action} index={index} />) : <EmptyState title="暂无处理步骤" description="请由现场人员补充检查结论。" />}
              </div>
            </SectionCard>
          </div>

          <SectionCard eyebrow="Knowledge References" title="引用维修文档" right={<StatusBadge label={`${knowledgeSources.length} 份资料`} />}>
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              {knowledgeSources.length ? (
                knowledgeSources.map((source, index) => <KnowledgeSourceCard key={`${formatDocumentName(source)}-${index}`} source={source} />)
              ) : (
                <EmptyState title="暂无维修资料引用" description="本次报告未返回可引用的企业知识库文档，系统不会伪造资料来源。" />
              )}
            </div>
          </SectionCard>
        </>
      ) : (
        <EmptyState title="没有找到该报告" description="请返回报告列表重新选择。" />
      )}
    </PageShell>
  );
}

function buildDeviceCards(report: DiagnosisHistoryDetail | null): DeviceCard[] {
  if (!report) return [];
  if (report.response?.device) {
    return [{
      code: report.response.device.device_code,
      name: formatDeviceName(report.response.device),
      type: formatDeviceType(report.response.device.device_type),
      location: report.response.device.location,
      online: report.response.device.is_online,
      runtime: report.response.device_status,
      alarms: report.response.recent_alarms,
      riskLevel: report.response.risk_level,
    }];
  }
  if (report.risk_report?.device_risks?.length) {
    return report.risk_report.device_risks.map((item) => ({
      code: item.device.device_code,
      name: formatDeviceName(item.device),
      type: formatDeviceType(item.device.device_type),
      location: item.device.location,
      online: item.device.is_online,
      runtime: item.latest_runtime_data,
      alarms: item.unresolved_alarms,
      riskLevel: item.risk_level,
    }));
  }
  return [];
}

function buildSummary(report: DiagnosisHistoryDetail | null): string {
  if (!report) return '';
  if (isFleetReport(report.report_v2)) return formatBusinessText(report.report_v2.summary);
  if (isSingleReport(report.report_v2)) return formatBusinessText(report.report_v2.conclusion);
  const summary = formatBusinessText(report.problem_summary || report.risk_report?.summary);
  if (summary) return summary;
  if (report.device_code && report.alarm_code) {
    return `${report.device_code} 存在 ${report.alarm_code} ${report.alarm_name ?? formatAlarmName(report.alarm_code)}。系统已根据设备数据、报警记录和维修资料生成辅助诊断结果，请结合现场情况确认。`;
  }
  if (report.device_code) return `${report.device_code} 的设备诊断报告已生成，请重点查看运行参数、当前报警和处理建议。`;
  return '多设备风险分析报告已生成，请优先处理高风险设备和待处理报警。';
}

function buildFacts(report: DiagnosisHistoryDetail | null) {
  if (!report) return [];
  if (isSingleReport(report.report_v2) && report.report_v2.confirmed_facts.length) {
    return report.report_v2.confirmed_facts.slice(0, 8).map((fact) => ({
      name: fact.label,
      result: fact.value,
      note: fact.source === 'device_runtime_data' ? '来自设备最新运行参数。' : fact.source === 'device_alarm_records' ? '来自设备报警记录。' : '来自可信设备数据。',
    }));
  }
  if (isFleetReport(report.report_v2) && report.report_v2.devices.length) {
    return [
      { name: '分析范围', result: `${report.report_v2.devices.length} 台设备`, note: '系统已汇总设备状态、报警记录和风险排序。' },
      { name: '风险设备', result: `${report.report_v2.devices.filter((item) => item.risk.level !== 'normal' && item.risk.level !== 'unknown').length} 台`, note: '建议优先查看高风险和中风险设备。' },
      { name: '维修资料', result: `${buildKnowledgeSources(report).length} 份`, note: buildKnowledgeSources(report).length ? '已引用企业知识库资料。' : '未获得可引用维修资料。' },
      { name: '报告状态', result: formatStatus(report.status), note: '请结合现场处理结果更新维修结论。' },
    ];
  }
  const alarmCount = countAlarms(report);
  const runtime = report.response?.device_status;
  return [
    { name: '报警记录', result: alarmCount ? `${alarmCount} 条待处理报警` : '未发现待处理报警', note: alarmCount ? alarmSummary(report) : '可继续保持日常巡检。' },
    { name: '运行参数', result: runtime ? runtimeSummary(runtime) : report.risk_report ? '已汇总多台设备运行状态' : '未返回实时参数', note: runtime ? '来自设备最新运行数据。' : '建议现场补充仪表读数和历史趋势。' },
    { name: '知识库资料', result: buildKnowledgeSources(report).length ? `${buildKnowledgeSources(report).length} 份维修资料` : '未返回资料', note: buildKnowledgeSources(report).length ? '已引用企业设备知识库中的维修资料。' : '资料不足时不建议直接判定最终原因。' },
    { name: '报告状态', result: formatStatus(report.status), note: '请结合现场检查结果形成最终维修结论。' },
  ];
}

function buildCauses(report: DiagnosisHistoryDetail | null): string[] {
  if (!report) return [];
  if (isSingleReport(report.report_v2) && report.report_v2.possible_causes.length) {
    return report.report_v2.possible_causes.map((cause) => `${cause.title}：${cause.description}`).map(formatBusinessText).filter(Boolean);
  }
  if (isFleetReport(report.report_v2) && report.report_v2.devices.length) {
    return report.report_v2.devices.flatMap((device) =>
      device.possible_causes.map((cause) => `${device.device_code}：${cause.description}`),
    ).map(formatBusinessText).filter(Boolean);
  }
  if (report.response?.possible_causes?.length) return cleanList(report.response.possible_causes);
  if (report.risk_report?.key_findings?.length) return cleanList(report.risk_report.key_findings);
  if (report.risk_report?.device_risks?.length) {
    return report.risk_report.device_risks.flatMap((item) =>
      item.reasons.map((reason) => `${item.device.device_code}：${formatBusinessText(reason)}`),
    );
  }
  if (report.alarm_code) {
    return [`可能与 ${report.alarm_code} ${report.alarm_name ?? formatAlarmName(report.alarm_code)} 相关，需要结合现场负载、环境条件和运行趋势确认。`];
  }
  return [];
}

function buildActionSteps(report: DiagnosisHistoryDetail | null): string[] {
  if (!report) return [];
  if (isSingleReport(report.report_v2) && report.report_v2.action_plan.length) {
    return report.report_v2.action_plan.map((action) => action.description).map(formatBusinessText).filter(Boolean);
  }
  if (isFleetReport(report.report_v2) && report.report_v2.devices.length) {
    return report.report_v2.devices.flatMap((device) =>
      device.action_plan.map((action) => `${device.device_code}：${action.description}`),
    ).slice(0, 10).map(formatBusinessText).filter(Boolean);
  }
  if (report.response?.recommended_actions?.length) return cleanList(report.response.recommended_actions);
  if (report.risk_report?.recommended_actions?.length) return cleanList(report.risk_report.recommended_actions);
  return ['现场复核设备运行状态和报警记录。', '结合维修手册检查相关部件。', '处理完成后记录维修结果并持续观察运行趋势。'];
}

function DeviceInfoCard({ device }: { device: DeviceCard }) {
  const telemetry = device.runtime ? [
    { label: '温度', value: `${device.runtime.temperature}℃` },
    { label: '电压', value: `${device.runtime.voltage}V` },
    { label: '电流', value: `${device.runtime.current}A` },
    { label: '振动', value: `${device.runtime.vibration}mm/s` },
  ] : [];

  return (
    <article className="rounded-3xl border border-slate-200 bg-slate-50 p-4">
      <div className="grid gap-5 lg:grid-cols-[minmax(260px,0.8fr)_minmax(320px,1.2fr)]">
        <div className="min-w-0">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="font-mono text-sm font-semibold text-slate-950">{device.code}</div>
              <div className="mt-1 truncate text-sm font-semibold text-slate-100">{device.name}</div>
            </div>
            <StatusBadge label={device.online ? '在线' : '离线或未知'} healthy={device.online} />
          </div>
          <div className="mt-4 grid gap-2 text-xs leading-5 text-slate-600">
            <div>设备类型：{device.type}</div>
            <div>安装位置：{device.location}</div>
            <div>当前报警：{device.alarms.length ? device.alarms.map((alarm) => `${alarm.alarm_code} ${formatAlarmName(alarm.alarm_code)}`).join(' / ') : '无待处理报警'}</div>
          </div>
        </div>
        <div className="min-w-0 rounded-2xl border border-slate-200 bg-white/60 p-3">
          {device.runtime ? (
            <>
              <div className="grid gap-2 sm:grid-cols-4">
                {telemetry.map((item) => (
                  <div key={item.label} className="rounded-xl border border-slate-200 bg-slate-50 px-3 py-2">
                    <div className="text-[11px] text-slate-500">{item.label}</div>
                    <div className="mt-1 text-sm font-semibold text-slate-50">{item.value}</div>
                  </div>
                ))}
              </div>
              <div className="mt-3">
                <TrendLine
                  values={[device.runtime.temperature, device.runtime.current * 8, device.runtime.vibration * 120]}
                  tone={device.riskLevel === 'high' || device.riskLevel === 'critical' ? 'red' : device.riskLevel === 'medium' ? 'amber' : 'emerald'}
                />
              </div>
            </>
          ) : (
            <div className="text-sm text-slate-500">未返回最新运行参数。</div>
          )}
        </div>
      </div>
    </article>
  );
}

function EvidenceFactCard({ fact }: { fact: { name: string; result: string; note: string } }) {
  return (
    <article className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <div className="text-xs font-semibold text-sky-700">{fact.name}</div>
      <div className="mt-2 text-sm font-semibold leading-6 text-slate-50">{fact.result}</div>
      <p className="mt-2 text-xs leading-5 text-slate-500">{fact.note}</p>
    </article>
  );
}

function SummaryPill({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.035] px-4 py-3">
      <div className="text-xs font-semibold text-slate-400">{label}</div>
      <div className="mt-1 text-lg font-semibold text-slate-50">{value}</div>
    </div>
  );
}

function CauseCard({ cause, index, hasCitation }: { cause: string; index: number; hasCitation: boolean }) {
  return (
    <article className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex items-start gap-3">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-sky-700 text-sm font-semibold text-white">{index + 1}</span>
        <div>
          <div className="text-sm font-semibold text-slate-950">可能原因 {index + 1}</div>
          <p className="mt-1 text-sm leading-6 text-slate-600">{formatBusinessText(cause)}</p>
          <div className="mt-3 inline-flex rounded-full bg-amber-50 px-3 py-1 text-xs font-semibold text-amber-700">
            可信程度：{hasCitation ? '有维修资料支撑，仍需现场确认' : '需要现场检查确认'}
          </div>
        </div>
      </div>
    </article>
  );
}

function ActionCard({ action, index }: { action: string; index: number }) {
  const titles = ['立即处理', '现场验证', '计划维护', '持续跟踪'];
  return (
    <article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <span className={`grid h-8 w-8 shrink-0 place-items-center rounded-xl text-sm font-semibold ${index === 0 ? 'bg-red-50 text-red-700' : index === 1 ? 'bg-amber-50 text-amber-700' : 'bg-sky-50 text-sky-700'}`}>{index + 1}</span>
        <div>
          <div className="text-sm font-semibold text-slate-950">{titles[index] ?? '持续跟踪'}</div>
          <p className="mt-1 text-sm leading-6 text-slate-600">{formatBusinessText(action)}</p>
        </div>
      </div>
    </article>
  );
}

function KnowledgeSourceCard({ source }: { source: DiagnosisRagSource }) {
  const retrieval = reportRetrievalStatus(source);
  return (
    <article className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-sm font-semibold text-slate-950">{formatDocumentName(source)}</div>
          <div className="mt-1 text-xs text-slate-500">来源：企业设备知识库 · 章节：维修处理建议</div>
        </div>
        <StatusBadge label={retrieval} />
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-600">{formatKnowledgeSummary(source)}</p>
    </article>
  );
}

function reportRetrievalStatus(source: DiagnosisRagSource): string {
  if (typeof source.rerank_score === 'number') return 'Rerank 增强';
  if (typeof source.vector_score === 'number' || typeof source.distance === 'number') return '向量召回';
  return '已引用';
}

function reportTitle(report: DiagnosisHistoryDetail): string {
  if (report.device_code) return `${report.device_code} 设备诊断报告`;
  return '多设备风险分析报告';
}

function runtimeSummary(runtime: ToolRuntimeData): string {
  return `温度 ${runtime.temperature}℃，电压 ${runtime.voltage}V，电流 ${runtime.current}A，振动 ${runtime.vibration}mm/s`;
}

function alarmSummary(report: DiagnosisHistoryDetail): string {
  const alarms = report.response?.recent_alarms ?? report.risk_report?.device_risks.flatMap((item) => item.unresolved_alarms) ?? [];
  if (!alarms.length) return report.alarm_code ? `${report.alarm_code} ${report.alarm_name ?? formatAlarmName(report.alarm_code)}` : '未返回待处理报警';
  return alarms.slice(0, 3).map((alarm) => `${alarm.alarm_code} ${formatAlarmName(alarm.alarm_code)}`).join(' / ');
}

function countAlarms(report: DiagnosisHistoryDetail): number {
  if (report.response?.recent_alarms?.length) return report.response.recent_alarms.length;
  if (report.risk_report?.device_risks?.length) {
    return report.risk_report.device_risks.reduce((total, item) => total + item.unresolved_alarms.length, 0);
  }
  return report.alarm_code ? 1 : 0;
}

function riskAdvice(level: RiskLevel): string {
  if (level === 'critical' || level === 'high') return '建议立即安排现场复核，必要时降低负载或停机检查。';
  if (level === 'medium') return '建议纳入当班重点巡检，确认报警原因和运行参数变化。';
  if (level === 'low' || level === 'normal') return '当前风险较低，建议按计划巡检并持续观察。';
  return '现有证据不足，建议补充现场检查结果。';
}

function cleanList(values: string[]) {
  return values.map(formatBusinessText).filter(Boolean);
}

function buildKnowledgeSources(report: DiagnosisHistoryDetail | null): DiagnosisRagSource[] {
  if (!report) return [];
  const citations = isSingleReport(report.report_v2)
    ? report.report_v2.citations
    : isFleetReport(report.report_v2)
      ? report.report_v2.citations
      : [];
  if (citations.length) {
    return uniqueKnowledgeEvidence(citations.map((citation, index) => ({
      source: citation.source,
      filename: citation.title,
      chunk_id: citation.chunk_id ?? index,
      chunk_index: citation.chunk_index ?? null,
      distance: citation.distance ?? null,
      content: citation.excerpt ?? null,
    })));
  }
  return uniqueKnowledgeEvidence(report.rag_sources);
}

function isSingleReport(value: DiagnosisHistoryDetail['report_v2']): value is DiagnosisReportV2 {
  return Boolean(value && 'conclusion' in value && 'risk' in value);
}

function isFleetReport(value: DiagnosisHistoryDetail['report_v2']): value is FleetRiskReportV2 {
  return Boolean(value && 'summary' in value && 'devices' in value);
}

