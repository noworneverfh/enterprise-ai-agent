import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { fetchDeviceContext } from '../api/context';
import { fetchDevices } from '../api/devices';
import {
  EmptyState,
  ErrorState,
  LoadingState,
  MetricCard,
  PageShell,
  ProductHero,
  ProgressBar,
  RiskBadge,
  RiskIntervalScale,
  riskBandLabel,
  SectionCard,
  StatusBadge,
  TrendLine,
} from '../components/IndustrialUI';
import { formatDeviceName, formatDeviceOption, formatDeviceType, sortDevicesByCode } from '../utils/deviceDisplay';
import { formatAlarmName, formatBusinessText, formatDateTime } from '../utils/reportFormatter';
import type { DeviceContext, DeviceContextAlarm, DeviceContextRuntimePoint, ToolDeviceInfo } from '../types';

export default function DeviceDetailPage() {
  const { deviceCode } = useParams<{ deviceCode: string }>();
  const navigate = useNavigate();
  const [devices, setDevices] = useState<ToolDeviceInfo[]>([]);
  const [context, setContext] = useState<DeviceContext | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const selectedCode = deviceCode || devices[0]?.device_code || 'DEV-003';

  useEffect(() => {
    let cancelled = false;
    async function loadDevices() {
      try {
        const list = await fetchDevices();
        if (!cancelled) {
          setDevices(list);
          if (!deviceCode && list[0]?.device_code) navigate(`/devices/${list[0].device_code}`, { replace: true });
        }
      } catch {
        if (!cancelled) setDevices([]);
      }
    }
    void loadDevices();
    return () => {
      cancelled = true;
    };
  }, [deviceCode, navigate]);

  useEffect(() => {
    if (!selectedCode) return;
    let cancelled = false;
    async function loadContext() {
      setLoading(true);
      setError(null);
      try {
        const data = await fetchDeviceContext(selectedCode);
        if (!cancelled) setContext(data);
      } catch (loadError) {
        if (!cancelled) {
          setError(loadError instanceof Error ? loadError.message : '设备画像加载失败，请稍后重试。');
          setContext(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void loadContext();
    return () => {
      cancelled = true;
    };
  }, [selectedCode]);

  const health = context?.health_summary;
  const runtime = context?.current_runtime ?? null;
  const currentAlarms = context?.current_alarms ?? [];
  const trendValues = useMemo(() => buildTrendValues(context), [context]);

  return (
    <PageShell>
      <ProductHero
        eyebrow="Device Context"
        title="设备详情中心"
        description="汇总设备基础信息、实时状态、历史报警、诊断报告、维修记忆和关联知识，帮助运维人员理解设备过去发生过什么、现在为什么异常、下一步如何处理。"
        side={
          <label className="grid gap-2 text-sm font-semibold text-slate-300">
            切换设备
            <select value={selectedCode} onChange={(event) => navigate(`/devices/${event.target.value}`)} className="field-control">
              {sortDevicesByCode(devices).map((device) => (
                <option key={device.device_code} value={device.device_code}>{formatDeviceOption(device)}</option>
              ))}
            </select>
          </label>
        }
      />

      {error ? <ErrorState message={error} /> : null}
      {loading ? <LoadingState title="正在生成设备长期画像" steps={['基础信息', '运行状态', '历史记录', '维修记忆']} /> : null}

      {!loading && context?.device ? (
        <>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
            <MetricCard label="设备编号" value={context.device.device_code} description={formatDeviceName(context.device)} />
            <MetricCard label="当前风险区间" value={riskBandLabel(health?.current_risk_level)} description={riskTrendText(health?.trend)} tone={riskTone(health?.current_risk_level)} />
            <MetricCard label="当前报警" value={`${health?.unresolved_alarm_count ?? 0} 条`} description="未关闭报警记录" tone={health?.unresolved_alarm_count ? 'warning' : 'normal'} />
            <MetricCard label="历史诊断" value={`${health?.diagnosis_count ?? 0} 次`} description="已沉淀诊断报告" />
            <MetricCard label="维修记忆" value={`${health?.maintenance_record_count ?? 0} 条`} description="现场处理结果沉淀" />
          </div>

          <HealthScorePanel context={context} trendValues={trendValues} />

          <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
            <SectionCard eyebrow="Device Profile" title="设备画像" right={<StatusBadge label={context.device.is_online ? '在线' : '离线'} healthy={context.device.is_online} />}>
              <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <ProfileItem label="设备名称" value={formatDeviceName(context.device)} />
                <ProfileItem label="设备类型" value={formatDeviceType(context.device.device_type)} />
                <ProfileItem label="安装位置" value={context.device.location ?? '未登记'} />
                <ProfileItem label="建档时间" value={formatDateTime(context.device.created_at)} />
              </div>
              <div className="mt-5">
                <RiskIntervalScale
                  level={health?.current_risk_level}
                  title="当前设备风险区间"
                  basis={['当前报警', '运行参数', '历史诊断', '维修记忆']}
                />
              </div>
            </SectionCard>

            <SectionCard eyebrow="AI Insight" title="AI 设备理解">
              <div className="mt-4 grid gap-3">
                <InsightRow title="当前状态" text={buildCurrentStatus(context)} />
                <InsightRow title="风险原因" text={buildRiskReason(context)} />
                <InsightRow title="关键证据" text={buildEvidenceText(context)} />
                <InsightRow title="推荐动作" text={buildDeviceAction(context)} />
              </div>
            </SectionCard>
          </div>

          <SectionCard eyebrow="Telemetry" title="当前运行状态" right={<span className="text-xs text-slate-500">数据时间：{formatDateTime(runtime?.recorded_at)}</span>}>
            {runtime ? <RuntimeGrid runtime={runtime} /> : <div className="mt-4"><EmptyState title="暂无运行数据" description="系统未读取到该设备的实时运行参数。" /></div>}
          </SectionCard>

          <SectionCard
            eyebrow="Device Memory"
            title="设备历史上下文"
            right={<StatusBadge label={`${context.diagnosis_history.length} 份诊断报告`} />}
          >
            <div className="mt-4 grid gap-4 xl:grid-cols-3">
              <ContextPanel title="当前与历史报警" count={`${currentAlarms.length || context.historical_alarms.length} 条`}>
                <div className="grid gap-3">
                  {(currentAlarms.length ? currentAlarms : context.historical_alarms.slice(0, 2)).map((alarm) => (
                    <AlarmCard key={alarm.id} alarm={alarm} deviceRiskLevel={health?.current_risk_level ?? 'unknown'} />
                  ))}
                  {!currentAlarms.length && !context.historical_alarms.length ? <EmptyState title="暂无报警记录" description="该设备当前没有报警，也没有历史报警记录。" /> : null}
                </div>
              </ContextPanel>

              <ContextPanel title="维修闭环记忆" count={`${context.maintenance_memory.length} 条`}>
                <div className="grid gap-3">
                  {context.maintenance_memory.slice(0, 2).map((item) => (
                    <div key={item.id} className="rounded-2xl border border-white/10 bg-slate-950/35 p-4">
                      <div className="flex items-start justify-between gap-3">
                        <div className="font-semibold text-slate-50">{item.confirmed_root_cause ?? '现场处理记录'}</div>
                        <StatusBadge label={item.resolved ? '已解决' : '待跟进'} healthy={item.resolved} />
                      </div>
                      <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-300">{formatBusinessText(item.actual_action)}</p>
                      {item.result ? <p className="mt-2 line-clamp-1 text-xs text-slate-500">处理结果：{formatBusinessText(item.result)}</p> : null}
                    </div>
                  ))}
                  {!context.maintenance_memory.length ? <EmptyState title="暂无维修闭环记录" description="现场处理结果提交后会沉淀为该设备的维修记忆。" /> : null}
                </div>
              </ContextPanel>

              <ContextPanel title="关联知识与类似案例" count={`${context.related_knowledge.length + context.similar_cases.length} 项`}>
                <div className="grid gap-3">
                  {context.related_knowledge.slice(0, 2).map((item) => (
                    <div key={`${item.fault_code}-${item.fault_name}`} className="rounded-2xl border border-white/10 bg-slate-950/35 p-4">
                      <div className="font-semibold text-slate-50">{item.fault_code} {item.fault_name || formatAlarmName(item.fault_code)}</div>
                      <div className="mt-2 text-xs text-slate-500">适用设备：{formatDeviceType(item.device_type)} · 原因 {item.cause_count} 条 · 案例 {item.case_count} 条</div>
                    </div>
                  ))}
                  {context.similar_cases.slice(0, Math.max(0, 2 - context.related_knowledge.slice(0, 2).length)).map((item) => (
                    <div key={`case-${item.id}`} className="rounded-2xl border border-white/10 bg-slate-950/35 p-4">
                      <div className="font-semibold text-slate-50">类似案例：{formatBusinessText(item.fault)}</div>
                      <p className="mt-2 line-clamp-2 text-sm leading-6 text-slate-300">{formatBusinessText(item.solution)}</p>
                    </div>
                  ))}
                  {!context.related_knowledge.length && !context.similar_cases.length ? <EmptyState title="暂无关联知识" description="当前设备暂未匹配到结构化故障知识或历史案例。" /> : null}
                </div>
              </ContextPanel>
            </div>

            <div className="mt-4 rounded-3xl border border-white/10 bg-slate-950/35 p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <div className="text-sm font-semibold text-slate-50">历史诊断</div>
                  <div className="mt-1 text-xs text-slate-500">最近诊断报告按生成时间展示，点击可查看完整报告。</div>
                </div>
                <span className="rounded-full border border-white/10 bg-slate-950/45 px-3 py-1 text-xs font-semibold text-slate-300">{context.diagnosis_history.length} 条</span>
              </div>
              <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {context.diagnosis_history.slice(0, 6).map((item) => (
                  <Link key={item.report_id} to={`/reports/${item.report_id}`} className="rounded-2xl border border-white/10 bg-slate-950/35 p-4 transition hover:border-sky-400/40 hover:bg-sky-400/10">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="line-clamp-2 text-sm font-semibold leading-6 text-slate-50">{diagnosisHistoryTitle(item.problem_summary, item.query)}</div>
                        <div className="mt-2 text-xs text-slate-500">{formatDateTime(item.created_at)}</div>
                      </div>
                      <RiskBadge level={item.risk_level} />
                    </div>
                  </Link>
                ))}
                {!context.diagnosis_history.length ? <EmptyState title="暂无历史诊断" description="该设备尚未形成诊断报告。" /> : null}
              </div>
            </div>
          </SectionCard>
        </>
      ) : !loading && !error ? (
        <EmptyState title="未找到设备画像" description="请选择已有设备或确认设备编号是否正确。" />
      ) : null}
    </PageShell>
  );
}

function ProfileItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-950/35 p-4">
      <div className="text-xs font-semibold text-slate-500">{label}</div>
      <div className="mt-2 font-semibold text-slate-50">{value}</div>
    </div>
  );
}

function HealthScorePanel({ context, trendValues }: { context: DeviceContext; trendValues: number[] }) {
  const healthScore = calculateHealthScore(context);
  const tone = healthScore.score >= 80 ? 'normal' : healthScore.score >= 60 ? 'warning' : 'danger';
  return (
    <SectionCard eyebrow="AI Health Score" title="AI 健康评分" right={<StatusBadge label={healthScore.label} healthy={healthScore.score >= 80} />}>
      <div className="mt-4 grid items-center gap-5 xl:grid-cols-[260px_minmax(0,1fr)]">
        <div className="rounded-3xl border border-white/10 bg-slate-950/45 p-5 shadow-[0_18px_48px_rgba(0,0,0,0.2)]">
          <div className="text-sm font-semibold text-slate-400">综合健康分</div>
          <div className="mt-3 text-5xl font-semibold text-slate-50">{healthScore.score}</div>
          <div className="mt-1 text-sm text-slate-400">满分 100，基于设备画像实时计算</div>
          <div className="mt-5">
            <ProgressBar value={healthScore.score} tone={tone} />
          </div>
          <div className="mt-4">
            <TrendLine values={trendValues} tone={tone === 'danger' ? 'red' : tone === 'warning' ? 'amber' : 'emerald'} />
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {healthScore.factors.map((factor) => (
            <div key={factor.title} className="rounded-2xl border border-white/10 bg-slate-950/35 p-4 shadow-[0_14px_34px_rgba(0,0,0,0.14)]">
              <div className="text-sm font-semibold text-slate-300">{factor.title}</div>
              <div className="mt-2 text-2xl font-semibold text-slate-50">{factor.value}</div>
              <p className="mt-2 text-xs leading-5 text-slate-400">{factor.description}</p>
            </div>
          ))}
        </div>
      </div>
      <p className="mt-4 rounded-2xl border border-white/10 bg-white/[0.035] px-4 py-3 text-xs leading-5 text-slate-400">
        评分依据来自设备在线状态、当前报警、参数异常、风险趋势和维修闭环记录；用于运维优先级参考，不替代现场最终确认。
      </p>
    </SectionCard>
  );
}

function ContextPanel({ title, count, children }: { title: string; count: string; children: ReactNode }) {
  return (
    <div className="rounded-3xl border border-white/10 bg-white/[0.035] p-4">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div className="font-semibold text-slate-50">{title}</div>
        <span className="rounded-full border border-white/10 bg-slate-950/35 px-3 py-1 text-xs font-semibold text-slate-300">{count}</span>
      </div>
      {children}
    </div>
  );
}

function InsightRow({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-950/35 p-4">
      <div className="text-xs font-semibold text-sky-700">{title}</div>
      <p className="mt-2 text-sm leading-6 text-slate-300">{text}</p>
    </div>
  );
}

function RuntimeGrid({ runtime }: { runtime: DeviceContextRuntimePoint }) {
  const items = [
    { label: '温度', value: runtime.temperature, unit: '℃', min: 0, max: 60 },
    { label: '电压', value: runtime.voltage, unit: 'V', min: 220, max: 240 },
    { label: '电流', value: runtime.current, unit: 'A', min: 0, max: 8 },
    { label: '振动', value: runtime.vibration, unit: 'mm/s', min: 0, max: 0.4 },
  ];
  return (
    <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => {
        const value = item.value ?? 0;
        const warning = value > item.max || value < item.min;
        const near = !warning && value >= item.max * 0.85;
        return (
          <div key={item.label} className="rounded-2xl border border-white/10 bg-slate-950/35 p-5">
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold text-slate-300">{item.label}</div>
              <span className={`h-2.5 w-2.5 rounded-full ${warning ? 'bg-red-500' : near ? 'bg-amber-500' : 'bg-emerald-500'}`} />
            </div>
            <div className="mt-3 text-3xl font-semibold text-slate-50">{value}<span className="ml-1 text-sm text-slate-500">{item.unit}</span></div>
            <div className="mt-2 text-xs leading-5 text-slate-500">安全范围：{item.min}-{item.max}{item.unit}</div>
            <div className="mt-1 text-xs text-slate-500">状态解释：{warning ? '超过安全范围' : near ? '接近阈值' : '参数正常'}</div>
          </div>
        );
      })}
    </div>
  );
}

function AlarmCard({ alarm, deviceRiskLevel }: { alarm: DeviceContextAlarm; deviceRiskLevel: string }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-slate-950/35 p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="font-semibold text-slate-50">{alarm.alarm_code} {alarm.alarm_name || formatAlarmName(alarm.alarm_code)}</div>
          <p className="mt-2 text-sm leading-6 text-slate-300">{formatBusinessText(alarm.message)}</p>
          <div className="mt-2 text-xs text-slate-500">{formatDateTime(alarm.occurred_at)}</div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          <RiskBadge level={alarm.alarm_level || deviceRiskLevel} />
        </div>
      </div>
    </div>
  );
}

function buildTrendValues(context: DeviceContext | null): number[] {
  const values = (context?.risk_trend ?? []).slice(-8).map((item) => item.risk_score);
  if (values.length >= 3) return values;
  const current = context?.health_summary?.current_risk_score ?? 20;
  return [Math.max(5, current - 20), Math.max(8, current - 12), Math.max(10, current - 6), current];
}

function calculateHealthScore(context: DeviceContext): {
  score: number;
  label: string;
  factors: Array<{ title: string; value: string; description: string }>;
} {
  const health = context.health_summary;
  const unresolvedAlarms = health?.unresolved_alarm_count ?? context.current_alarms.filter((alarm) => !alarm.is_resolved).length;
  const abnormalParameters = health?.abnormal_parameters ?? [];
  const unresolvedMaintenance = context.maintenance_memory.filter((item) => !item.resolved).length;
  const riskPenalty = Math.min(35, Math.max(0, health?.current_risk_score ?? 0) * 0.35);
  const alarmPenalty = Math.min(25, unresolvedAlarms * 10);
  const parameterPenalty = Math.min(20, abnormalParameters.length * 7);
  const maintenancePenalty = Math.min(10, unresolvedMaintenance * 5);
  const onlinePenalty = context.device?.is_online ? 0 : 20;
  const trendPenalty = health?.trend === 'worsening' ? 8 : health?.trend === 'improving' ? -5 : 0;
  const score = Math.max(0, Math.min(100, Math.round(100 - riskPenalty - alarmPenalty - parameterPenalty - maintenancePenalty - onlinePenalty - trendPenalty)));
  const label = score >= 85 ? '健康' : score >= 70 ? '关注' : score >= 55 ? '较高风险' : '高风险';
  return {
    score,
    label,
    factors: [
      {
        title: '在线状态',
        value: context.device?.is_online ? '在线' : '离线',
        description: context.device?.is_online ? '设备当前可读取运行状态。' : '设备离线会降低健康评分。',
      },
      {
        title: '当前报警',
        value: `${unresolvedAlarms} 条`,
        description: unresolvedAlarms ? '未关闭报警会提高巡检优先级。' : '当前未返回未关闭报警。',
      },
      {
        title: '异常参数',
        value: `${abnormalParameters.length} 项`,
        description: abnormalParameters.length ? abnormalParameters.map(formatParameterName).join('、') : '运行参数处于安全范围。',
      },
      {
        title: '维修闭环',
        value: `${context.maintenance_memory.length} 条`,
        description: unresolvedMaintenance ? `${unresolvedMaintenance} 条仍待跟进。` : '已记录的维修结果均为已解决或无需跟进。',
      },
    ],
  };
}

function buildCurrentStatus(context: DeviceContext): string {
  const device = context.device?.device_code ?? '该设备';
  const online = context.device?.is_online ? '在线' : '离线或未确认';
  const alarmCount = context.health_summary?.unresolved_alarm_count ?? 0;
  return `${device} 当前处于${online}状态，存在 ${alarmCount} 条未处理报警。`;
}

function buildRiskReason(context: DeviceContext): string {
  const health = context.health_summary;
  if (!health) return '当前缺少健康摘要，建议补充运行数据和报警记录。';
  const params = health.abnormal_parameters.map(formatParameterName);
  if (health.unresolved_alarm_count || params.length) {
    return [
      health.unresolved_alarm_count ? `${health.unresolved_alarm_count} 条未处理报警` : '',
      params.length ? `异常参数包括 ${params.join('、')}` : '',
    ].filter(Boolean).join('，') + '。';
  }
  return '当前未发现明显报警或参数越限，保持日常监控即可。';
}

function buildEvidenceText(context: DeviceContext): string {
  const evidence = [];
  if (context.current_runtime) evidence.push('实时运行参数');
  if (context.current_alarms.length) evidence.push('当前报警记录');
  if (context.diagnosis_history.length) evidence.push('历史诊断报告');
  if (context.maintenance_memory.length) evidence.push('维修闭环记录');
  if (context.related_knowledge.length || context.similar_cases.length) evidence.push('关联知识与类似案例');
  return evidence.length ? evidence.join('、') : '当前证据不足，建议补充现场检查结果。';
}

function buildDeviceAction(context: DeviceContext): string {
  const level = context.health_summary?.current_risk_level;
  if (level === 'critical' || level === 'high') return '建议立即安排现场复核，优先处理未关闭报警，并记录处置结果形成维修闭环。';
  if (level === 'medium') return '建议纳入当班重点巡检，复核报警状态和关键运行参数。';
  return '继续保持日常监控，若出现重复报警再生成诊断报告。';
}

function diagnosisHistoryTitle(summary?: string | null, query?: string | null): string {
  const text = formatBusinessText(summary || query || '');
  if (/E101|温度/.test(text)) return '温度超过安全阈值';
  if (/E201|振动/.test(text)) return '振动参数超过标准';
  if (/E404|通信/.test(text)) return '通信异常持续发生';
  if (/E203|电机/.test(text)) return '电机运行异常';
  return text || '设备诊断报告';
}

function riskTrendText(trend?: string): string {
  if (trend === 'worsening') return '风险趋势上升';
  if (trend === 'improving') return '风险趋势改善';
  if (trend === 'stable') return '风险趋势稳定';
  return '趋势待确认';
}

function riskTone(level?: string | null): 'default' | 'normal' | 'warning' | 'danger' {
  if (level === 'critical' || level === 'high') return 'danger';
  if (level === 'medium') return 'warning';
  if (level === 'low' || level === 'normal') return 'normal';
  return 'default';
}

function formatParameterName(value: string): string {
  const labels: Record<string, string> = {
    temperature: '温度',
    voltage: '电压',
    current: '电流',
    vibration: '振动',
  };
  return labels[value] ?? value;
}


