import { FormEvent, ReactNode, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { analyzeAllDeviceRisk, diagnose, fetchLatestTrace } from '../api';
import { fetchDevices } from '../api/devices';
import { fetchDiagnosisHistory } from '../api/diagnosis';
import { fetchPlatformHealth, type PlatformHealth } from '../api/health';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  PageShell,
  ProductHero,
  RiskBadge,
  RiskIntervalScale,
  SectionCard,
  StatusBadge,
} from '../components/IndustrialUI';
import { formatDeviceName, formatDeviceOption, formatDeviceType, sortDevicesByCode } from '../utils/deviceDisplay';
import { getFrontendPermissions, resolvePrimaryRole } from '../utils/permissions';
import type {
  AgentDiagnoseResponse,
  AgentTrace,
  CurrentUser,
  DiagnosisCitationV2,
  DiagnosisHistoryItem,
  DiagnosisReportV2,
  FleetRiskReportV2,
  MultiDeviceRiskResponse,
  RiskLevel,
  ToolAlarmRecord,
  ToolRuntimeData,
  TraceRagResult,
  TraceToolResult,
} from '../types';

const quickCases = [
  { label: 'DEV-003 温度异常', deviceCode: 'DEV-003', query: '分析设备温度异常原因以及如何解决' },
  { label: 'DEV-005 振动异常', deviceCode: 'DEV-005', query: '分析设备振动异常原因以及处理方法' },
  { label: '分析全部设备风险', deviceCode: '', query: '分析当前所有设备风险' },
];

const riskRank: Record<RiskLevel, number> = {
  critical: 5,
  high: 4,
  medium: 3,
  low: 2,
  normal: 1,
  unknown: 0,
};

const alarmNameMap: Record<string, string> = {
  E101: '温度异常',
  E201: '振动异常',
  E203: '电机运行异常',
  E302: '液压压力波动',
  E404: '通信异常',
  E501: '润滑异常',
};

const riskText: Record<string, string> = {
  critical: '严重风险',
  high: '高风险',
  medium: '中风险',
  low: '低风险',
  normal: '正常',
  unknown: '待确认',
};

export default function DiagnosisPage({ currentUser }: { currentUser: CurrentUser | null }) {
  const role = resolvePrimaryRole(currentUser);
  const canDiagnose = getFrontendPermissions(currentUser).generateReport;
  const showTechnicalTrace = role === 'admin';
  const [devices, setDevices] = useState<Array<{ device_code: string; name: string; device_type?: string; location?: string }>>([]);
  const [deviceCode, setDeviceCode] = useState('');
  const [query, setQuery] = useState('');
  const [singleResult, setSingleResult] = useState<AgentDiagnoseResponse | null>(null);
  const [riskResult, setRiskResult] = useState<MultiDeviceRiskResponse | null>(null);
  const [trace, setTrace] = useState<AgentTrace | null>(null);
  const [savedReport, setSavedReport] = useState<DiagnosisHistoryItem | null>(null);
  const [loading, setLoading] = useState(false);
  const [durationMs, setDurationMs] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [platformHealth, setPlatformHealth] = useState<PlatformHealth | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function loadDevices() {
      try {
        const deviceList = sortDevicesByCode(await fetchDevices());
        if (!cancelled) {
          setDevices(deviceList);
          setDeviceCode((current) => current || deviceList[0]?.device_code || '');
        }
      } catch {
        if (!cancelled) setDevices([]);
      }
    }
    void loadDevices();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadPlatformHealth() {
      try {
        const health = await fetchPlatformHealth();
        if (!cancelled) setPlatformHealth(health);
      } catch {
        if (!cancelled) setPlatformHealth(null);
      }
    }
    void loadPlatformHealth();
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedDevice = useMemo(() => devices.find((device) => device.device_code === deviceCode) ?? null, [devices, deviceCode]);
  const isRiskAnalysis = useMemo(() => /所有设备|全部设备|全局|整体风险|设备风险/.test(query), [query]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!query.trim() || loading || !canDiagnose) return;

    setLoading(true);
    setError(null);
    setSingleResult(null);
    setRiskResult(null);
    setTrace(null);
    setSavedReport(null);
    setDurationMs(null);
    const started = performance.now();

    try {
      if (isRiskAnalysis) {
        setRiskResult(await analyzeAllDeviceRisk({ query: query.trim(), include_knowledge: true, knowledge_top_k: 5 }));
      } else {
        setSingleResult(await diagnose({
          query: query.trim(),
          device_code: deviceCode || null,
          knowledge_top_k: 5,
          include_device_status: true,
          include_knowledge: true,
        }));
      }
      setDurationMs(Math.round(performance.now() - started));

      try {
        setTrace(await fetchLatestTrace());
      } catch {
        setTrace(null);
      }

      try {
        const records = await fetchDiagnosisHistory(30);
        setSavedReport(findSavedDiagnosisRecord(records, { deviceCode: isRiskAnalysis ? null : deviceCode || null, isRiskAnalysis }));
      } catch {
        setSavedReport(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '诊断请求失败，请稍后重试。');
    } finally {
      setLoading(false);
    }
  }

  return (
    <PageShell>
      <ProductHero
        eyebrow="AI DIAGNOSIS"
        title="工业设备 AI Agent 智能诊断"
        description="输入设备与故障描述后，系统会读取设备状态、报警记录和企业维修资料，生成带证据来源的结构化诊断报告。"
        side={<ProcessMini health={platformHealth} />}
      />

      <form onSubmit={submit} className="surface-card grid gap-4 p-4 lg:grid-cols-[280px_minmax(0,1fr)_150px]">
        <label className="grid gap-2 text-sm font-semibold text-slate-200">
          设备选择
          <select
            value={deviceCode}
            onChange={(event) => setDeviceCode(event.target.value)}
            disabled={isRiskAnalysis}
            className="h-12 rounded-2xl border border-white/10 bg-slate-950/45 px-4 text-sm font-semibold text-slate-50 outline-none transition focus:border-sky-400/70 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {devices.map((device) => (
              <option key={device.device_code} value={device.device_code}>
                {formatDeviceOption(device)}
              </option>
            ))}
          </select>
        </label>

        <label className="grid gap-2 text-sm font-semibold text-slate-200">
          故障描述
          <textarea
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            rows={3}
            placeholder="例如：分析设备温度异常原因，或分析当前所有设备风险"
            className="min-h-24 resize-none rounded-2xl border border-white/10 bg-slate-950/45 px-4 py-3 text-sm font-medium text-slate-50 outline-none transition placeholder:text-slate-500 focus:border-sky-400/70"
          />
        </label>

        <button
          type="submit"
          disabled={!canDiagnose || !query.trim() || loading}
          className="self-end rounded-2xl bg-sky-600 px-5 py-4 text-sm font-semibold text-white transition hover:bg-sky-500 disabled:cursor-not-allowed disabled:bg-slate-600 disabled:text-slate-300"
        >
          {loading ? '分析中...' : '开始诊断'}
        </button>

        <div className="flex flex-wrap gap-2 lg:col-span-3">
          {quickCases.map((item) => (
            <button
              key={item.label}
              type="button"
              onClick={() => {
                setQuery(item.query);
                if (item.deviceCode) setDeviceCode(item.deviceCode);
              }}
              className="rounded-full border border-white/10 bg-slate-950/35 px-4 py-2 text-xs font-semibold text-slate-300 transition hover:border-sky-400/50 hover:text-sky-200"
            >
              {item.label}
            </button>
          ))}
        </div>
      </form>

      {error ? <ErrorState message={error} /> : null}
      {!canDiagnose ? <ErrorState message="当前账号暂无诊断权限，请使用管理员账号执行智能诊断和全局风险分析。" /> : null}

      <RetrievalEnhancementPanel health={platformHealth} />

      <AgentExecutionBoard
        loading={loading}
        query={query}
        deviceCode={isRiskAnalysis ? null : deviceCode || null}
        selectedDeviceName={selectedDevice ? formatDeviceName(selectedDevice) : null}
        trace={trace}
        singleResult={singleResult}
        riskResult={riskResult}
        durationMs={durationMs}
        savedReport={savedReport}
        showTechnicalTrace={showTechnicalTrace}
        platformHealth={platformHealth}
      />

      {loading ? <LoadingState title="AI Agent 正在执行诊断任务" steps={['任务规划', '设备数据获取', '知识库检索', '风险分析', '报告生成']} /> : null}

      {!loading && singleResult ? <SingleDiagnosisView result={singleResult} trace={trace} savedReport={savedReport} durationMs={durationMs} /> : null}
      {!loading && riskResult ? <FleetRiskView result={riskResult} trace={trace} durationMs={durationMs} /> : null}

      {!loading && !singleResult && !riskResult && !error ? (
        <EmptyState
          title="选择设备并输入故障描述开始诊断"
          description="诊断结果会展示 AI 结论、设备状态、原因分析、处理建议、知识库依据和 Agent 执行过程。"
        />
      ) : null}
    </PageShell>
  );
}

function RetrievalEnhancementPanel({ health }: { health: PlatformHealth | null }) {
  const ragMode = retrievalModeFromHealth(health);
  const enabled = health?.rag?.reranker_enabled === true;
  const model = health?.rag?.reranker_model?.split('/').pop() || 'bge-reranker-v2-m3';
  const candidateK = health?.rag?.candidate_k ?? 20;

  return (
    <section className="surface-card overflow-hidden p-4 sm:p-5">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <p className="eyebrow">RAG RETRIEVAL</p>
            <span className={`rounded-full border px-3 py-1 text-xs font-semibold ${ragMode.className}`}>{ragMode.label}</span>
          </div>
          <h2 className="mt-2 text-xl font-semibold text-slate-50">企业知识检索增强状态</h2>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-400">{ragMode.description}</p>
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div className="rounded-2xl border border-white/10 bg-slate-950/35 p-3">
            <div className="text-xs font-semibold text-slate-500">召回层</div>
            <div className="mt-2 text-sm font-semibold text-slate-100">Chroma Top-K</div>
            <div className="mt-1 text-xs text-slate-500">向量检索候选资料</div>
          </div>
          <div className={`rounded-2xl border p-3 ${enabled ? 'border-cyan-400/25 bg-cyan-400/10' : 'border-white/10 bg-slate-950/35'}`}>
            <div className="text-xs font-semibold text-slate-500">重排序层</div>
            <div className="mt-2 text-sm font-semibold text-slate-100">{enabled ? model : '未启用 Rerank'}</div>
            <div className="mt-1 text-xs text-slate-500">{enabled ? `候选 ${candidateK} 条后重排` : '配置 RERANKER_ENABLED=true 后启用'}</div>
          </div>
          <div className="rounded-2xl border border-white/10 bg-slate-950/35 p-3">
            <div className="text-xs font-semibold text-slate-500">证据输出</div>
            <div className="mt-2 text-sm font-semibold text-slate-100">Report V2 Sources</div>
            <div className="mt-1 text-xs text-slate-500">保留向量分与重排分</div>
          </div>
        </div>
      </div>
    </section>
  );
}

function ProcessMini({ health }: { health: PlatformHealth | null }) {
  const ragMode = retrievalModeFromHealth(health);
  return (
    <div className="grid gap-2 text-sm text-slate-300">
      {['任务规划', '数据获取', '知识检索', '风险分析', '报告生成'].map((step, index) => (
        <div key={step} className="flex items-center gap-3">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-sky-500/90 text-xs font-bold text-white">{index + 1}</span>
          <span className="min-w-0">
            {step}
            {step === '知识检索' ? (
              <span className="ml-2 rounded-full border border-cyan-400/25 bg-cyan-400/10 px-2 py-0.5 text-[11px] font-semibold text-cyan-200">
                {ragMode.label}
              </span>
            ) : null}
          </span>
        </div>
      ))}
      <div className="mt-2 rounded-2xl border border-white/10 bg-slate-950/45 p-3">
        <div className="flex items-center justify-between gap-3">
          <span className="text-xs font-semibold text-slate-300">知识检索模式</span>
          <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${ragMode.className}`}>{ragMode.label}</span>
        </div>
        <p className="mt-2 text-[11px] leading-5 text-slate-500">{ragMode.description}</p>
      </div>
    </div>
  );
}

function AgentExecutionBoard({
  loading,
  query,
  deviceCode,
  selectedDeviceName,
  trace,
  singleResult,
  riskResult,
  durationMs,
  savedReport,
  showTechnicalTrace,
  platformHealth,
}: {
  loading: boolean;
  query: string;
  deviceCode: string | null;
  selectedDeviceName: string | null;
  trace: AgentTrace | null;
  singleResult: AgentDiagnoseResponse | null;
  riskResult: MultiDeviceRiskResponse | null;
  durationMs: number | null;
  savedReport: DiagnosisHistoryItem | null;
  showTechnicalTrace: boolean;
  platformHealth: PlatformHealth | null;
}) {
  const report = singleResult?.report_v2 ?? null;
  const fleetReport = riskResult?.report_v2 ?? null;
  const runtime = singleResult?.device_status ?? null;
  const alarms = singleResult?.recent_alarms ?? [];
  const ragResults = uniqueRagResults(trace?.rag_results ?? []);
  const tools = trace?.tool_results ?? [];
  const citations = report?.citations ?? fleetReport?.citations ?? [];
  const docs = uniqueDocNames([...ragResults, ...citations, ...(singleResult?.sources ?? []), ...(riskResult?.sources ?? [])]);
  const ragMode = retrievalModeFromHealth(platformHealth);
  const hasResult = Boolean(singleResult || riskResult);
  const status = loading ? '执行中' : hasResult ? '已完成' : '待开始';

  const stageCards = [
    {
      no: 1,
      title: '任务规划',
      status: loading ? '执行中' : query ? '已规划' : '待输入',
      rows: [
        ['任务类型', riskResult ? '全局设备风险分析' : '单设备故障诊断'],
        ['目标设备', riskResult ? '全部在线设备' : selectedDeviceName || deviceCode || '待选择设备'],
        ['执行策略', query ? '先获取设备事实，再检索知识库，最后生成结构化报告' : '等待用户输入问题'],
      ],
    },
    {
      no: 2,
      title: '数据获取',
      status: loading ? '查询中' : tools.length || hasResult ? '已完成' : '待执行',
      rows: [
        ['调用工具', toolSummary(tools, riskResult)],
        ['实时数据', runtime ? runtimeSummary(runtime) : riskResult ? `${riskResult.device_risks.length} 台设备完成状态汇总` : '等待设备状态返回'],
        ['报警记录', alarmSummary(alarms, riskResult)],
      ],
    },
    {
      no: 3,
      title: '知识检索',
      status: loading ? '检索中' : docs.length ? '已命中' : hasResult ? '未命中' : '待执行',
      rows: [
        ['检索结果', docs.length ? `${docs.length} 份维修资料` : hasResult ? '本次没有返回可引用维修资料' : '等待报警与故障上下文'],
        ['引用文档', docs.slice(0, 2).join(' / ') || '暂无'],
        ['检索增强', rerankSummary(ragResults)],
        ['引用片段', knowledgeExcerpt(ragResults, citations)],
      ],
    },
    {
      no: 4,
      title: '风险分析',
      status: loading ? '分析中' : hasResult ? '已完成' : '待执行',
      rows: [
        ['异常指标', abnormalMetricSummary(runtime, report, fleetReport)],
        ['阈值比较', thresholdSummary(report, fleetReport)],
        ['风险判断', riskSummary(singleResult, riskResult, report, fleetReport)],
      ],
    },
    {
      no: 5,
      title: '报告生成',
      status: loading ? '生成中' : hasResult ? '已生成' : '待执行',
      rows: [
        ['报告编号', savedReport?.report_id || '诊断完成后生成'],
        ['诊断结论', report?.conclusion || fleetReport?.summary || singleResult?.problem_summary || riskResult?.summary || '等待生成结构化报告'],
        ['引用来源', docs.length ? docs.join(' / ') : '暂无可引用资料'],
      ],
    },
  ];

  return (
    <SectionCard
      eyebrow="AGENT RUNTIME"
      title="AI Agent 执行流程"
      right={
        <div className="flex flex-wrap justify-end gap-2">
          <StatusBadge label={ragMode.label} healthy={platformHealth?.rag?.reranker_enabled ?? false} />
          <StatusBadge label={status} healthy={hasResult && !loading} />
        </div>
      }
    >
      <div className="mt-4 grid gap-3 xl:grid-cols-5">
        {stageCards.map((stage) => (
          <article key={stage.no} className="rounded-2xl border border-white/10 bg-slate-950/35 p-4 shadow-[0_18px_42px_rgba(0,0,0,0.18)]">
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-center gap-3">
                <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-sky-500/90 text-sm font-bold text-white">{stage.no}</span>
                <h3 className="font-semibold text-slate-50">{stage.title}</h3>
              </div>
              <StageBadge label={stage.status} />
            </div>
            <div className="mt-4 grid gap-2">
              {stage.rows.map(([label, value]) => (
                <ResultLine key={label} label={label} value={value} />
              ))}
            </div>
          </article>
        ))}
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
        <FinalDiagnosisCard singleResult={singleResult} riskResult={riskResult} savedReport={savedReport} />
        <AgentTraceLog trace={trace} durationMs={durationMs} showTechnicalTrace={showTechnicalTrace} />
      </div>
    </SectionCard>
  );
}

function StageBadge({ label }: { label: string }) {
  const tone = label.includes('未') ? 'border-amber-400/35 text-amber-200 bg-amber-500/10' : label.includes('待') ? 'border-slate-500/35 text-slate-300 bg-slate-500/10' : 'border-emerald-400/35 text-emerald-200 bg-emerald-500/10';
  return <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${tone}`}>{label}</span>;
}

function ResultLine({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="rounded-xl border border-white/10 bg-slate-900/55 px-3 py-2">
      <div className="text-[11px] font-semibold text-sky-200/80">{label}</div>
      <div className="mt-1 line-clamp-2 text-xs leading-5 text-slate-200">{value || '暂无数据'}</div>
    </div>
  );
}

function FinalDiagnosisCard({
  singleResult,
  riskResult,
  savedReport,
}: {
  singleResult: AgentDiagnoseResponse | null;
  riskResult: MultiDeviceRiskResponse | null;
  savedReport: DiagnosisHistoryItem | null;
}) {
  const report = singleResult?.report_v2 ?? null;
  const fleet = riskResult?.report_v2 ?? null;
  const level = report?.risk.level || fleet?.overall_risk.level || singleResult?.risk_level || riskResult?.overall_risk_level || 'unknown';
  const device = singleResult?.device?.device_code || savedReport?.device_code || (riskResult ? '全部设备' : '待诊断');
  const alarm = savedReport?.alarm_code ? `${savedReport.alarm_code} ${alarmName(savedReport.alarm_code)}` : singleResult?.recent_alarms[0] ? `${singleResult.recent_alarms[0].alarm_code} ${alarmName(singleResult.recent_alarms[0].alarm_code)}` : riskResult ? '多设备风险' : '待确认';
  const causes = buildCauses(singleResult, report, fleet);
  const actions = buildActions(singleResult, riskResult, report, fleet);
  const docs = uniqueDocNames([...(report?.citations ?? []), ...(fleet?.citations ?? []), ...(singleResult?.sources ?? []), ...(riskResult?.sources ?? [])]);

  return (
    <div className="rounded-2xl border border-white/10 bg-slate-950/35 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="eyebrow">FINAL DIAGNOSIS</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-50">最终诊断结果</h3>
        </div>
        <RiskBadge level={level} />
      </div>
      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <ResultLine label="设备" value={device} />
        <ResultLine label="风险等级" value={riskText[level] ?? '待确认'} />
        <ResultLine label="故障类型" value={alarm} />
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <InfoList title="原因分析" items={causes.slice(0, 3)} />
        <InfoList title="处理建议" items={actions.slice(0, 3)} />
        <InfoList title="知识引用" items={docs.slice(0, 3)} empty="本次未返回可引用资料" />
      </div>
      {savedReport?.report_id ? (
        <Link to={`/reports/${savedReport.report_id}`} className="mt-4 inline-flex rounded-full border border-sky-400/40 px-4 py-2 text-xs font-semibold text-sky-200 transition hover:bg-sky-400/10">
          查看完整历史报告
        </Link>
      ) : null}
    </div>
  );
}

function AgentTraceLog({ trace, durationMs, showTechnicalTrace }: { trace: AgentTrace | null; durationMs: number | null; showTechnicalTrace: boolean }) {
  const logs = buildAgentLogs(trace, durationMs, showTechnicalTrace);
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-950/35 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="eyebrow">TRACE LOG</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-50">Agent Trace 执行日志</h3>
        </div>
        <StatusBadge label={trace ? '已记录' : '待记录'} healthy={Boolean(trace)} />
      </div>
      <div className="mt-4 grid gap-2">
        {logs.map((log) => (
          <div key={log.name} className="grid gap-2 rounded-xl border border-white/10 bg-slate-900/55 px-3 py-2 sm:grid-cols-[120px_minmax(0,1fr)_auto] sm:items-center">
            <div className="text-xs font-semibold text-sky-200">{log.name}</div>
            <div className="min-w-0 text-xs leading-5 text-slate-300">{log.detail}</div>
            <StageBadge label={log.status} />
          </div>
        ))}
      </div>
    </div>
  );
}

function SingleDiagnosisView({ result, trace, savedReport, durationMs }: { result: AgentDiagnoseResponse; trace: AgentTrace | null; savedReport: DiagnosisHistoryItem | null; durationMs: number | null }) {
  const report = result.report_v2 ?? null;
  const runtime = result.device_status;
  const causes = buildCauses(result, report, null);
  const actions = buildActions(result, null, report, null);
  const facts = buildConfirmedFacts(result, report);

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="grid gap-4">
        <SectionCard eyebrow="AI CONCLUSION" title="AI诊断结论" right={<RiskBadge level={report?.risk.level ?? result.risk_level} />}>
          <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_300px]">
            <div className="rounded-2xl border border-white/10 bg-slate-950/35 p-4">
              <h3 className="text-xl font-semibold text-slate-50">{report?.conclusion || result.problem_summary || '系统已生成辅助诊断结果，请结合现场情况确认。'}</h3>
              <p className="mt-3 text-sm leading-6 text-slate-400">分析对象：{result.device?.device_code ?? '未知设备'}；异常类型：{result.recent_alarms[0] ? `${result.recent_alarms[0].alarm_code} ${alarmName(result.recent_alarms[0].alarm_code)}` : '待确认'}。</p>
              <div className="mt-4 grid gap-3 sm:grid-cols-3">
                <ResultLine label="关联设备" value={result.device?.device_code ?? '暂无'} />
                <ResultLine label="待处理报警" value={`${result.recent_alarms.filter((alarm) => !alarm.is_resolved).length} 条`} />
                <ResultLine label="维修资料" value={`${uniqueDocNames([...(report?.citations ?? []), ...result.sources]).length} 份`} />
              </div>
            </div>
            <RiskIntervalScale level={report?.risk.level ?? result.risk_level} title="本次诊断风险区间" basis={['设备运行参数', '报警记录', '维修知识库依据']} />
          </div>
        </SectionCard>

        <RuntimePanel runtime={runtime} />
        <EvidenceTable facts={facts} />
        <ParameterAnalysis runtime={runtime} report={report} />
        <div className="grid gap-4 lg:grid-cols-2">
          <CauseAnalysis causes={causes} />
          <ActionPlan actions={actions} />
        </div>
        <RagEvidence trace={trace} citations={report?.citations ?? []} sources={result.sources} />
      </div>
      <AgentProcess trace={trace} durationMs={durationMs} savedReport={savedReport} />
    </div>
  );
}

function FleetRiskView({ result, trace, durationMs }: { result: MultiDeviceRiskResponse; trace: AgentTrace | null; durationMs: number | null }) {
  const report = result.report_v2 ?? null;
  const devices = [...result.device_risks].sort((a, b) => riskRank[b.risk_level] - riskRank[a.risk_level]);
  const actions = buildActions(null, result, null, report);

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_380px]">
      <div className="grid gap-4">
        <SectionCard eyebrow="FLEET RISK" title="多设备风险分析" right={<RiskBadge level={report?.overall_risk.level ?? result.overall_risk_level} />}>
          <p className="mt-4 text-xl font-semibold text-slate-50">{report?.summary || result.summary}</p>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <ResultLine label="分析设备" value={`${devices.length} 台`} />
            <ResultLine label="风险设备" value={`${devices.filter((item) => item.risk_level !== 'normal' && item.risk_level !== 'low').length} 台`} />
            <ResultLine label="知识引用" value={`${uniqueDocNames([...(report?.citations ?? []), ...result.sources]).length} 份`} />
          </div>
        </SectionCard>

        <SectionCard eyebrow="RISK RANKING" title="设备风险排行">
          <div className="mt-4 overflow-hidden rounded-2xl border border-white/10">
            <table className="w-full table-fixed text-left text-sm">
              <thead className="bg-slate-950/45 text-xs uppercase tracking-wide text-slate-400">
                <tr>
                  <th className="px-4 py-3">设备</th>
                  <th className="px-4 py-3">异常信息</th>
                  <th className="px-4 py-3">风险</th>
                  <th className="px-4 py-3">建议</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/10">
                {devices.map((item) => (
                  <tr key={item.device.device_code} className="bg-slate-950/20 align-top">
                    <td className="px-4 py-3 font-semibold text-slate-50">{item.device.device_code}<div className="mt-1 text-xs font-normal text-slate-400">{formatDeviceType(item.device.device_type)}</div></td>
                    <td className="px-4 py-3 text-slate-300">{item.unresolved_alarms.map((alarm) => `${alarm.alarm_code} ${alarmName(alarm.alarm_code)}`).join(' / ') || '无未处理报警'}</td>
                    <td className="px-4 py-3"><RiskBadge level={item.risk_level} /></td>
                    <td className="px-4 py-3 text-slate-300">{item.recommended_actions[0] || '保持巡检并关注趋势。'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </SectionCard>

        <ActionPlan actions={actions} />
        <RagEvidence trace={trace} citations={report?.citations ?? []} sources={result.sources} />
      </div>
      <AgentProcess trace={trace} durationMs={durationMs} />
    </div>
  );
}

function RuntimePanel({ runtime }: { runtime: ToolRuntimeData | null }) {
  const values = runtime
    ? [
        { label: '温度', value: runtime.temperature, unit: '°C', range: '0-60°C', status: runtime.temperature > 60 ? 'danger' : runtime.temperature > 50 ? 'warning' : 'normal' },
        { label: '电压', value: runtime.voltage, unit: 'V', range: '220-240V', status: runtime.voltage < 220 || runtime.voltage > 240 ? 'danger' : 'normal' },
        { label: '电流', value: runtime.current, unit: 'A', range: '0-8A', status: runtime.current > 8 ? 'danger' : runtime.current > 6 ? 'warning' : 'normal' },
        { label: '振动', value: runtime.vibration, unit: 'mm/s', range: '0-0.4mm/s', status: runtime.vibration > 0.4 ? 'danger' : runtime.vibration > 0.3 ? 'warning' : 'normal' },
      ]
    : [];

  return (
    <SectionCard eyebrow="DEVICE TELEMETRY" title="当前设备状态">
      {runtime ? (
        <>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            {values.map((item) => (
              <div key={item.label} className="rounded-2xl border border-white/10 bg-slate-950/35 p-4">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-slate-300">{item.label}</span>
                  <span className={`h-2.5 w-2.5 rounded-full ${item.status === 'danger' ? 'bg-red-400' : item.status === 'warning' ? 'bg-amber-400' : 'bg-emerald-400'}`} />
                </div>
                <div className="mt-3 text-3xl font-semibold text-slate-50">{formatNumber(item.value)} <span className="text-sm text-slate-400">{item.unit}</span></div>
                <div className="mt-2 text-xs leading-5 text-slate-400">安全范围：{item.range}<br />状态解释：{item.status === 'danger' ? '超过阈值' : item.status === 'warning' ? '接近阈值' : '参数正常'}</div>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-slate-500">数据时间：{formatLocalDate(runtime.recorded_at)}</p>
        </>
      ) : (
        <EmptyState title="暂无实时运行数据" description="本次诊断没有返回设备运行参数。" />
      )}
    </SectionCard>
  );
}

function EvidenceTable({ facts }: { facts: Array<{ label: string; value: string; source: string }> }) {
  return (
    <SectionCard eyebrow="EVIDENCE CHAIN" title="诊断依据">
      <div className="mt-4 overflow-hidden rounded-2xl border border-white/10">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-950/45 text-xs uppercase tracking-wide text-slate-400">
            <tr>
              <th className="px-4 py-3">数据来源</th>
              <th className="px-4 py-3">结果</th>
              <th className="px-4 py-3">说明</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/10">
            {facts.map((fact) => (
              <tr key={`${fact.label}-${fact.value}`} className="bg-slate-950/20">
                <td className="px-4 py-3 font-semibold text-slate-50">{fact.label}</td>
                <td className="px-4 py-3 text-slate-200">{fact.value}</td>
                <td className="px-4 py-3 text-slate-400">{fact.source}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </SectionCard>
  );
}

function ParameterAnalysis({ runtime, report }: { runtime: ToolRuntimeData | null; report: DiagnosisReportV2 | null }) {
  const observations = report?.parameter_observations?.length
    ? report.parameter_observations.map((item) => `${item.label || item.parameter}：${item.explanation}`)
    : runtime
      ? [
          runtime.temperature > 50 ? '温度接近或超过关注阈值，建议观察温升趋势。' : null,
          runtime.current > 8 ? '电流超过安全范围，可能存在负载过高或机械阻力异常。' : runtime.current > 6 ? '电流偏高，需要结合负载状态复核。' : null,
          runtime.vibration > 0.4 ? '振动超过安全范围，建议检查轴承、固定件和安装基础。' : runtime.vibration > 0.3 ? '振动接近阈值，建议增加巡检频次。' : null,
        ].filter(Boolean) as string[]
      : [];

  return (
    <SectionCard eyebrow="PARAMETER ANALYSIS" title="参数异常分析">
      <div className="mt-4 grid gap-3">
        {observations.length ? observations.map((item, index) => (
          <div key={index} className="rounded-2xl border border-white/10 bg-slate-950/35 p-4 text-sm leading-6 text-slate-300">{item}</div>
        )) : <EmptyState title="暂无参数异常" description="当前返回的运行参数未形成明确异常观察。" />}
      </div>
    </SectionCard>
  );
}

function CauseAnalysis({ causes }: { causes: string[] }) {
  return (
    <SectionCard eyebrow="CAUSE ANALYSIS" title="原因分析">
      <div className="mt-4 grid gap-3">
        {causes.length ? causes.map((cause, index) => (
          <div key={index} className="rounded-2xl border border-white/10 bg-slate-950/35 p-4">
            <div className="flex items-start gap-3">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-sky-500/90 text-sm font-bold text-white">{index + 1}</span>
              <p className="text-sm leading-6 text-slate-300">{cause}</p>
            </div>
          </div>
        )) : <EmptyState title="暂无明确原因" description="建议补充现场数据后再进行深入分析。" />}
      </div>
    </SectionCard>
  );
}

function ActionPlan({ actions }: { actions: string[] }) {
  return (
    <SectionCard eyebrow="ACTION PLAN" title="验证步骤与处理方案">
      <div className="mt-4 grid gap-3">
        {actions.length ? actions.map((action, index) => (
          <div key={index} className="rounded-2xl border border-white/10 bg-slate-950/35 p-4">
            <div className="flex items-start gap-3">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-amber-500/90 text-sm font-bold text-white">{index + 1}</span>
              <div>
                <h3 className="text-sm font-semibold text-slate-50">处理步骤 {index + 1}</h3>
                <p className="mt-1 text-sm leading-6 text-slate-300">{action}</p>
              </div>
            </div>
          </div>
        )) : <EmptyState title="暂无处理建议" description="本次报告未返回明确处理方案。" />}
      </div>
    </SectionCard>
  );
}

function RagEvidence({ trace, citations, sources }: { trace: AgentTrace | null; citations: DiagnosisCitationV2[]; sources: string[] }) {
  const rag = uniqueRagResults(trace?.rag_results ?? []);
  const docs = uniqueDocNames([...rag, ...citations, ...sources]);
  const cards = docs.map((name) => {
    const ragItem = rag.find((item) => docName(item) === name);
    const citation = citations.find((item) => docName(item) === name);
    return {
      name,
      section: citation?.source || ragItem?.source || '企业设备知识库',
      excerpt: knowledgeSummary(ragItem?.content || citation?.excerpt || '', name),
      retrieval: retrievalQuality(ragItem || citation),
    };
  });

  return (
    <SectionCard eyebrow="KNOWLEDGE EVIDENCE" title="企业知识库依据" right={<span className="rounded-full bg-slate-950/45 px-3 py-1 text-xs font-semibold text-slate-300">{cards.length} 份</span>}>
      <div className="mt-4 grid gap-3 lg:grid-cols-2">
        {cards.length ? cards.map((item) => (
          <article key={`${item.name}-${item.section}`} className="rounded-2xl border border-white/10 bg-slate-950/35 p-4">
            <div className="flex items-start justify-between gap-3">
              <h3 className="font-semibold text-slate-50">{item.name}</h3>
              <StatusBadge label={item.retrieval.mode} healthy />
            </div>
            <p className="mt-2 text-xs text-slate-500">来源：{item.section}</p>
            <RetrievalQualityBar quality={item.retrieval} />
            <p className="mt-3 text-sm leading-6 text-slate-300">{item.excerpt}</p>
          </article>
        )) : <EmptyState title="暂无可引用维修资料" description="本次没有匹配到企业知识库文档，系统不会伪造维修资料来源。" />}
      </div>
    </SectionCard>
  );
}

function RetrievalQualityBar({ quality }: { quality: RetrievalQuality }) {
  const percent = formatRetrievalPercent(quality.percent, quality.hasRerank);
  const color = quality.hasRerank
    ? 'from-cyan-400 via-sky-400 to-emerald-400'
    : 'from-slate-500 via-slate-400 to-slate-300';

  return (
    <div className="mt-3 rounded-2xl border border-white/10 bg-slate-900/55 p-3">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-semibold text-slate-300">
          {quality.hasRerank ? '二阶段重排序' : '向量召回排序'}
        </span>
        <span className="rounded-full border border-white/10 bg-black/20 px-2.5 py-1 text-[11px] font-semibold text-slate-300">
          {quality.hasRerank ? `重排相关性 ${percent}%` : '未启用 Rerank'}
        </span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-700/70">
        <div className={`h-full rounded-full bg-gradient-to-r ${color}`} style={{ width: `${Math.max(8, percent)}%` }} />
      </div>
      <p className="mt-2 text-[11px] leading-5 text-slate-500">
        {quality.hasRerank
          ? '先由 Chroma 召回候选片段，再由 Reranker 对 query 与片段进行相关性重排。'
          : '当前按向量距离和故障码规则返回；开启 RERANKER_ENABLED 后会显示重排分数。'}
      </p>
    </div>
  );
}

function AgentProcess({ trace, durationMs, savedReport }: { trace: AgentTrace | null; durationMs: number | null; savedReport?: DiagnosisHistoryItem | null }) {
  const steps = buildAgentLogs(trace, durationMs, true);
  return (
    <aside className="surface-card p-4 xl:sticky xl:top-20 xl:self-start">
      <p className="eyebrow">AGENT PROCESS</p>
      <h2 className="mt-1 text-lg font-semibold text-slate-50">Agent执行链路</h2>
      <div className="mt-5 grid gap-3">
        {steps.map((step, index) => (
          <div key={step.name} className="grid grid-cols-[32px_minmax(0,1fr)] gap-3">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-emerald-500 text-sm font-bold text-white">{index + 1}</span>
            <div className="rounded-2xl border border-white/10 bg-slate-950/35 p-3">
              <div className="flex items-center justify-between gap-2">
                <h3 className="font-semibold text-slate-50">{step.name}</h3>
                <StageBadge label={step.status} />
              </div>
              <p className="mt-2 text-xs leading-5 text-slate-400">{step.detail}</p>
            </div>
          </div>
        ))}
      </div>
      {savedReport?.report_id ? (
        <Link to={`/reports/${savedReport.report_id}`} className="mt-5 inline-flex w-full justify-center rounded-2xl bg-sky-600 px-4 py-3 text-sm font-semibold text-white transition hover:bg-sky-500">
          查看历史报告
        </Link>
      ) : null}
    </aside>
  );
}

function InfoList({ title, items, empty = '暂无数据' }: { title: string; items: string[]; empty?: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-900/55 p-3">
      <h4 className="text-sm font-semibold text-slate-50">{title}</h4>
      <div className="mt-2 grid gap-2">
        {items.length ? items.map((item, index) => <p key={`${item}-${index}`} className="text-xs leading-5 text-slate-300">{index + 1}. {item}</p>) : <p className="text-xs text-slate-500">{empty}</p>}
      </div>
    </div>
  );
}

function findSavedDiagnosisRecord(records: DiagnosisHistoryItem[], options: { deviceCode: string | null; isRiskAnalysis: boolean }): DiagnosisHistoryItem | null {
  if (!records.length) return null;
  if (options.isRiskAnalysis) return records.find((record) => !record.device_code) ?? records[0] ?? null;
  return records.find((record) => record.device_code === options.deviceCode) ?? records[0] ?? null;
}

function buildConfirmedFacts(result: AgentDiagnoseResponse, report: DiagnosisReportV2 | null): Array<{ label: string; value: string; source: string }> {
  if (report?.confirmed_facts?.length) {
    return report.confirmed_facts.map((fact) => ({ label: fact.label, value: fact.value, source: fact.source || '来自诊断证据链' }));
  }
  const facts = [
    result.device ? { label: '设备资产', value: `${result.device.device_code} ${result.device.name}`, source: '来自可信设备数据。' } : null,
    result.device ? { label: '在线状态', value: result.device.is_online ? '在线' : '离线', source: '来自可信设备数据。' } : null,
    result.device_status ? { label: '运行参数', value: runtimeSummary(result.device_status), source: '来自设备最新运行参数。' } : null,
    result.recent_alarms[0] ? { label: `${result.recent_alarms[0].alarm_code} ${alarmName(result.recent_alarms[0].alarm_code)}`, value: result.recent_alarms[0].is_resolved ? '已处理' : '待处理', source: '来自设备报警记录。' } : null,
  ].filter(Boolean) as Array<{ label: string; value: string; source: string }>;
  return facts.length ? facts : [{ label: '诊断上下文', value: '本次未返回完整设备事实', source: '需要补充设备数据。' }];
}

function buildCauses(single: AgentDiagnoseResponse | null, report: DiagnosisReportV2 | null, fleet: FleetRiskReportV2 | null): string[] {
  if (report?.possible_causes?.length) return report.possible_causes.map((item) => `${item.title}：${item.description || item.verification_method}`);
  if (fleet?.devices?.length) return fleet.devices.flatMap((device) => device.possible_causes.map((item) => `${device.device_code}：${item.title}，${item.description}`)).slice(0, 5);
  return single?.possible_causes?.map(cleanText).filter(Boolean) ?? [];
}

function buildActions(single: AgentDiagnoseResponse | null, risk: MultiDeviceRiskResponse | null, report: DiagnosisReportV2 | null, fleet: FleetRiskReportV2 | null): string[] {
  if (report?.action_plan?.length) return report.action_plan.map((item) => `${item.title}：${item.description}`);
  if (fleet?.devices?.length) return fleet.devices.flatMap((device) => device.action_plan.map((item) => `${device.device_code}：${item.title}，${item.description}`)).slice(0, 5);
  if (risk?.recommended_actions?.length) return risk.recommended_actions.map(cleanText);
  return single?.recommended_actions?.map(cleanText).filter(Boolean) ?? [];
}

function buildAgentLogs(trace: AgentTrace | null, durationMs: number | null, showTechnicalTrace: boolean) {
  const tools = trace?.tool_results ?? [];
  const rag = trace?.rag_results ?? [];
  const docs = uniqueDocNames(rag);
  return [
    { name: 'Planner', status: trace ? '已完成' : '待开始', detail: trace ? `识别任务模式：${trace.mode || '诊断'}；规划工具：${trace.router_tools?.map(toolLabel).join('、') || '设备状态、报警记录'}` : '等待用户提交诊断任务。' },
    { name: 'Tool Agent', status: tools.length ? '已完成' : trace ? '未返回' : '待执行', detail: tools.length ? `完成 ${tools.length} 次工具调用：${tools.map((item) => `${toolLabel(item.tool_name)}${item.success ? '成功' : '失败'}`).join('、')}` : '等待设备状态和报警工具返回。' },
    { name: 'RAG Agent', status: docs.length ? '已命中' : trace ? '未命中' : '待执行', detail: docs.length ? `命中文档：${docs.join('、')}；${rerankSummary(rag)}` : '当前任务未返回可引用维修资料。' },
    { name: 'Reasoning Agent', status: trace ? '已完成' : '待执行', detail: showTechnicalTrace && trace?.llm_final_status?.fallback_reason ? `推理完成，但存在降级原因：${trace.llm_final_status.fallback_reason}` : '基于设备事实、报警记录和知识引用完成风险分析。' },
    { name: 'Report Agent', status: trace ? '已生成' : '待生成', detail: durationMs != null ? `结构化诊断报告已生成，本次响应 ${formatMs(durationMs)}。` : '等待生成结构化诊断报告。' },
  ];
}

function toolSummary(tools: TraceToolResult[], riskResult: MultiDeviceRiskResponse | null): string {
  if (tools.length) return tools.map((item) => toolLabel(item.tool_name)).join('、');
  if (riskResult) return '设备列表、设备状态、报警记录、知识检索';
  return '等待工具调用结果';
}

function alarmSummary(alarms: ToolAlarmRecord[], riskResult: MultiDeviceRiskResponse | null): string {
  if (alarms.length) return alarms.map((alarm) => `${alarm.alarm_code} ${alarmName(alarm.alarm_code)}${alarm.is_resolved ? '（已处理）' : '（待处理）'}`).join('、');
  if (riskResult) return `${riskResult.device_risks.reduce((sum, item) => sum + item.unresolved_alarms.length, 0)} 条未处理报警`;
  return '等待报警记录返回';
}

function runtimeSummary(runtime: ToolRuntimeData): string {
  return `温度 ${formatNumber(runtime.temperature)}°C，电压 ${formatNumber(runtime.voltage)}V，电流 ${formatNumber(runtime.current)}A，振动 ${formatNumber(runtime.vibration)}mm/s`;
}

type RetrievalQuality = {
  mode: string;
  percent: number;
  hasRerank: boolean;
};

function retrievalModeFromHealth(health: PlatformHealth | null): {
  label: string;
  description: string;
  className: string;
} {
  if (health?.rag?.reranker_enabled) {
    const model = health.rag.reranker_model?.split('/').pop() || 'Reranker';
    return {
      label: 'Rerank 增强',
      description: `当前采用 Chroma 候选召回 + ${model} 二阶段重排序，优先返回高相关维修资料。`,
      className: 'border-cyan-400/30 bg-cyan-400/12 text-cyan-200',
    };
  }

  if (health?.rag) {
    return {
      label: '向量召回',
      description: '当前采用 Chroma 向量检索与故障码规则排序；开启 RERANKER_ENABLED 后会进入二阶段重排。',
      className: 'border-slate-400/25 bg-slate-400/10 text-slate-300',
    };
  }

  return {
    label: '检索状态读取中',
    description: '正在读取后端知识检索配置。',
    className: 'border-amber-400/30 bg-amber-400/12 text-amber-200',
  };
}

function rerankSummary(items: TraceRagResult[]): string {
  if (!items.length) return '等待知识检索结果';
  const reranked = items.filter((item) => typeof item.rerank_score === 'number');
  if (!reranked.length) return '当前为 Chroma 向量召回排序';
  const best = Math.max(...reranked.map((item) => item.rerank_score ?? 0));
  return `Reranker 已重排序，最高重排相关性 ${formatRetrievalPercent(normalizeRetrievalScore(best), true)}%`;
}

function retrievalQuality(item?: RetrievalSourceLike | null): RetrievalQuality {
  const rerankScore = typeof item?.rerank_score === 'number' ? item.rerank_score : null;
  if (rerankScore !== null) {
    return {
      mode: 'Rerank 已增强',
      percent: normalizeRetrievalScore(rerankScore),
      hasRerank: true,
    };
  }

  const vectorScore = typeof item?.vector_score === 'number'
    ? item.vector_score
    : typeof item?.distance === 'number'
      ? 1 / (1 + Math.max(0, item.distance))
      : 0.56;

  return {
    mode: '向量召回',
    percent: Math.max(0.08, Math.min(1, vectorScore)),
    hasRerank: false,
  };
}

function normalizeRetrievalScore(score: number): number {
  if (score >= 0 && score <= 1) return score;
  return 1 / (1 + Math.exp(-score));
}

function formatRetrievalPercent(score: number, isRerank: boolean): number {
  const normalized = Math.max(0, Math.min(1, score));
  const rounded = Math.round(normalized * 100);
  return isRerank ? Math.min(99, rounded) : rounded;
}

type RetrievalSourceLike = {
  distance?: number | null;
  vector_score?: number | null;
  rerank_score?: number | null;
};

function abnormalMetricSummary(runtime: ToolRuntimeData | null, report: DiagnosisReportV2 | null, fleet: FleetRiskReportV2 | null): string {
  if (report?.parameter_observations?.length) return report.parameter_observations.filter((item) => item.status !== 'normal').map((item) => `${item.label || item.parameter} ${item.value}${item.unit}`).join('、') || '未发现明显参数异常';
  if (fleet?.devices?.length) return fleet.devices.flatMap((device) => device.parameter_observations.filter((item) => item.status !== 'normal').map((item) => `${device.device_code} ${item.label || item.parameter}`)).slice(0, 4).join('、') || '未发现明显参数异常';
  if (!runtime) return '等待运行参数';
  const items = [runtime.temperature > 50 ? '温度接近阈值' : null, runtime.current > 8 ? '电流超过阈值' : null, runtime.vibration > 0.3 ? '振动接近阈值' : null].filter(Boolean);
  return items.join('、') || '未发现明显参数异常';
}

function thresholdSummary(report: DiagnosisReportV2 | null, fleet: FleetRiskReportV2 | null): string {
  const observations = report?.parameter_observations ?? fleet?.devices?.flatMap((device) => device.parameter_observations) ?? [];
  if (!observations.length) return '等待参数阈值比较';
  return observations.slice(0, 3).map((item) => `${item.label || item.parameter}：${item.value}${item.unit}，安全范围 ${item.normal_min}-${item.normal_max}${item.unit}`).join('；');
}

function riskSummary(single: AgentDiagnoseResponse | null, risk: MultiDeviceRiskResponse | null, report: DiagnosisReportV2 | null, fleet: FleetRiskReportV2 | null): string {
  const level = report?.risk.level || fleet?.overall_risk.level || single?.risk_level || risk?.overall_risk_level || 'unknown';
  const reasons = report?.risk.breakdown?.map((item) => item.reason).filter(Boolean) ?? fleet?.overall_risk.breakdown?.map((item) => item.reason).filter(Boolean) ?? [];
  return `${riskText[level] ?? '待确认'}${reasons.length ? `：${reasons.slice(0, 2).join('；')}` : ''}`;
}

function knowledgeExcerpt(rag: TraceRagResult[], citations: DiagnosisCitationV2[]): string {
  const text = rag[0]?.content || citations[0]?.excerpt || '';
  return text ? knowledgeSummary(text, docName(rag[0] || citations[0])) : '等待知识库引用片段';
}

function uniqueRagResults(items: TraceRagResult[]): TraceRagResult[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = `${docName(item)}-${(item.content || '').slice(0, 80)}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function uniqueDocNames(items: Array<string | TraceRagResult | DiagnosisCitationV2 | null | undefined>): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  items.forEach((item) => {
    const name = docName(item);
    const key = name.toLowerCase().replace(/\s+/g, '');
    if (!key || key === '暂无资料' || seen.has(key)) return;
    seen.add(key);
    result.push(name);
  });
  return result;
}

function docName(source: string | TraceRagResult | DiagnosisCitationV2 | null | undefined): string {
  let raw = '';
  if (typeof source === 'string') {
    raw = source;
  } else if (source) {
    const candidate = source as Partial<TraceRagResult & DiagnosisCitationV2>;
    raw = candidate.title || candidate.filename || candidate.source || '';
  }
  const text = raw.split('#')[0].split('/').pop()?.replace(/\.(md|txt|pdf)$/i, '') || raw;
  const normalized = text.replace(/[_-]+/g, ' ').toLowerCase();
  if (normalized.includes('e101')) return 'E101 温度异常维护手册';
  if (normalized.includes('e201')) return 'E201 振动异常维护手册';
  if (normalized.includes('e203')) return 'E203 电机运行异常维护手册';
  if (normalized.includes('e302')) return 'E302 液压压力波动维护手册';
  if (normalized.includes('e404')) return 'E404 通信异常维护手册';
  if (normalized.includes('e501')) return 'E501 润滑异常维护手册';
  return text || '暂无资料';
}

function knowledgeSummary(text: string, name: string): string {
  const value = cleanText(text);
  if (!value) return `${name} 已作为本次诊断的维修资料依据，建议结合现场状态进一步确认。`;
  const lower = `${name} ${value}`.toLowerCase();
  if (lower.includes('e101')) return 'E101 温度异常通常与散热不足、环境温度升高、负载过高或温度传感器异常有关，建议检查散热通道、风扇状态、负载变化和传感器读数。';
  if (lower.includes('e201')) return 'E201 振动异常可能与轴承磨损、机械松动、转轴偏移或安装基础异常有关，建议检查振动值、机械连接状态、轴承运行情况和固定部件。';
  if (lower.includes('e203')) return 'E203 电机运行异常可能与电流偏高、负载异常、轴承阻力增大或控制模块异常有关，建议结合电流趋势、负载状态和电机温升进行排查。';
  if (lower.includes('e404')) return 'E404 通信异常通常与网络连接、通信线缆、控制器超时、地址配置或网关状态有关，建议检查链路、端子、控制器和交换机日志。';
  return value.slice(0, 180);
}

function cleanText(value?: string | null): string {
  if (!value) return '';
  const lower = value.toLowerCase();
  if (lower.includes('mock diagnosis draft')) return '系统已根据设备运行数据、报警记录和维修资料生成辅助诊断结果，请结合现场情况确认。';
  if (lower.includes('please combine equipment data')) return '建议现场检查设备运行状态，并结合报警记录和维修资料确认异常原因。';
  if (lower.includes('prioritize unresolved alarms')) return '优先处理高风险设备中的未关闭报警，建议安排现场检查并确认异常状态。';
  if (lower.includes('schedule inspection')) return '安排中风险设备巡检，确认设备运行参数和异常原因。';
  if (lower.includes('keep routine monitoring')) return '当前设备运行参数正常，继续保持日常监控。';
  if (/analyzed\s+\d+\s+devices/i.test(value)) return '系统已完成多设备风险分析，并汇总异常设备、报警记录和维修资料依据。';
  return value
    .replace(/```[\s\S]*?```/g, '')
    .replace(/^#+\s*/gm, '')
    .replace(/\bchunk[-_\s]?\d+\b/gi, '')
    .replace(/\bembedding\b|\bdistance\b|\bscore\b/gi, '')
    .replace(/\s+/g, ' ')
    .trim();
}

function alarmName(code?: string | null): string {
  if (!code) return '设备异常';
  return alarmNameMap[code.toUpperCase()] ?? '设备异常';
}

function toolLabel(name?: string | null): string {
  if (!name) return '工具调用';
  const labels: Record<string, string> = {
    list_devices: '设备列表',
    get_device_status: '设备状态',
    get_device_alarms: '报警记录',
    search_knowledge: '知识检索',
  };
  return labels[name] ?? name;
}

function formatLocalDate(value?: string | null): string {
  if (!value) return '暂无时间';
  const date = new Date(value.includes('T') ? value : value.replace(' ', 'T'));
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }).format(date);
}

function formatMs(value?: number | null): string {
  if (value == null) return '暂无耗时';
  return value < 1000 ? `${Math.round(value)} 毫秒` : `${(value / 1000).toFixed(2)} 秒`;
}

function formatNumber(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return '--';
  return Number(value).toFixed(Math.abs(value) >= 10 ? 1 : 2).replace(/\.0$/, '');
}
