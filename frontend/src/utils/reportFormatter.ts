import type { DiagnosisRagSource, RecentAlarm, RiskLevel, TraceRagResult } from '../types';

const alarmNames: Record<string, string> = {
  E101: '温度异常',
  E201: '振动异常',
  E203: '电机运行异常',
  E302: '液压压力波动',
  E404: '通信异常',
  E501: '润滑异常',
};

const riskLabels: Record<RiskLevel, string> = {
  critical: '严重风险',
  high: '高风险',
  medium: '中风险',
  low: '低风险',
  normal: '运行正常',
  unknown: '待确认',
};

const statusLabels: Record<string, string> = {
  completed: '已完成',
  success: '成功',
  failed: '失败',
  warning: '需要关注',
  healthy: '运行正常',
  indexed: '已索引',
  processing: '处理中',
  uploaded: '已上传',
  resolved: '已处理',
  unresolved: '待处理',
  pending: '待确认',
};

export function formatRiskLevel(level?: RiskLevel | string | null): string {
  if (!level) return '待确认';
  return riskLabels[level as RiskLevel] ?? level;
}

export function formatStatus(status?: string | null): string {
  if (!status) return '待确认';
  return statusLabels[status.toLowerCase()] ?? status;
}

export function formatAlarmName(alarmCode?: string | null): string {
  if (!alarmCode) return '设备异常';
  return alarmNames[alarmCode.toUpperCase()] ?? '设备异常';
}

export function formatAlarmLabel(
  alarm?: Pick<RecentAlarm, 'alarm_code' | 'alarm_name'> | { alarm_code?: string | null; message?: string | null } | null,
): string {
  if (!alarm?.alarm_code) return '设备异常';
  const code = alarm.alarm_code.toUpperCase();
  const name = 'alarm_name' in alarm && alarm.alarm_name ? alarm.alarm_name : formatAlarmName(code);
  return `${code} ${sanitizeText(name)}`;
}

export function formatDateTime(value?: string | null): string {
  if (!value) return '暂无时间';
  const date = parseBackendDateTime(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

export function formatDuration(valueMs?: number | null): string {
  if (valueMs == null || Number.isNaN(valueMs)) return '暂无数据';
  if (valueMs < 1000) return `${Math.round(valueMs)} 毫秒`;
  const seconds = valueMs / 1000;
  return `${seconds.toFixed(seconds >= 10 ? 1 : 2)} 秒`;
}

function parseBackendDateTime(value: string): Date {
  const trimmed = value.trim();
  if (!trimmed) return new Date(Number.NaN);
  const hasTimezone = /(?:z|[+-]\d{2}:?\d{2})$/i.test(trimmed);
  const normalized = trimmed.includes('T') ? trimmed : trimmed.replace(' ', 'T');
  return new Date(hasTimezone ? normalized : `${normalized}Z`);
}

export function formatBusinessText(value?: string | null): string {
  if (!value) return '';
  const text = sanitizeText(value);
  const lower = text.toLowerCase();

  if (lower.includes('mock diagnosis draft')) {
    return '系统已根据设备运行数据、报警记录和维修资料生成辅助诊断结果，请结合现场情况确认。';
  }
  if (lower.includes('deterministic fallback') || lower.includes('fallback') || lower.includes('diagnosis unavailable')) {
    return '当前智能分析服务返回保守结果，以下内容基于已获取的设备数据、报警记录和维修资料整理。';
  }
  if (/analyzed\s+\d+\s+devices/.test(lower)) {
    const count = text.match(/analyzed\s+(\d+)\s+devices/i)?.[1] ?? '多台';
    const risk = text.match(/;\s*(\d+)\s+devices?\s+have/i)?.[1];
    return `已完成 ${count} 台设备的风险分析${risk ? `，其中 ${risk} 台设备存在风险信号` : ''}。`;
  }
  if (lower.includes('unresolved alarms') || lower.includes('temperature exceeds safe range') || lower.includes('temperature is near threshold')) {
    return translateRiskSentence(text);
  }
  if (lower.includes('prioritize unresolved alarms')) {
    return '优先处理高风险设备中的未关闭报警，建议安排现场检查并确认异常状态。';
  }
  if (lower.includes('schedule inspection')) {
    return '安排中风险设备巡检，确认设备运行参数和异常原因。';
  }
  if (lower.includes('keep routine monitoring')) {
    return '当前设备运行参数正常，继续保持日常监控。';
  }
  if (lower.includes('please combine equipment data')) {
    return '建议现场检查设备运行状态，并结合报警记录和维修资料确认异常原因。';
  }
  if (lower.includes('unable to complete')) {
    return '当前信息不足，系统无法形成完整诊断结论，请补充设备编号、报警信息或现场检查结果。';
  }

  return text;
}

export function formatDocumentName(source?: string | DiagnosisRagSource | TraceRagResult | null): string {
  const raw = typeof source === 'string' ? source : source?.filename ?? source?.source ?? '';
  const filename = raw.split('#')[0].split('/').pop()?.replace(/\.(md|txt|pdf)$/i, '') ?? raw;
  const normalized = filename.replace(/[_-]+/g, ' ').toLowerCase();
  if (normalized.includes('e101')) return 'E101 温度异常维护手册';
  if (normalized.includes('e201')) return 'E201 振动异常维护手册';
  if (normalized.includes('e203')) return 'E203 电机运行异常维护手册';
  if (normalized.includes('e302')) return 'E302 液压压力波动维护手册';
  if (normalized.includes('e404')) return 'E404 通信异常维护手册';
  if (normalized.includes('e501')) return 'E501 润滑异常维护手册';
  if (normalized.includes('manual')) return filename.replace(/[_-]+/g, ' ');
  return filename || '企业设备维修资料';
}

export function uniqueDocumentNames(
  sources: Array<string | DiagnosisRagSource | TraceRagResult | null | undefined>,
): string[] {
  const result: string[] = [];
  const seen = new Set<string>();
  sources.forEach((source) => {
    const name = formatDocumentName(source);
    const key = name.toLowerCase().replace(/\s+/g, '');
    if (!key || seen.has(key)) return;
    seen.add(key);
    result.push(name);
  });
  return result;
}

export function uniqueKnowledgeEvidence<T extends DiagnosisRagSource | TraceRagResult>(sources: T[]): T[] {
  const result: T[] = [];
  const seen = new Set<string>();
  sources.forEach((source) => {
    const name = formatDocumentName(source);
    const contentKey = source.content ? sanitizeText(source.content).slice(0, 80) : '';
    const key = `${name}-${contentKey}`;
    if (!key || seen.has(key)) return;
    seen.add(key);
    result.push(source);
  });
  return result;
}

export function formatKnowledgeSummary(source?: DiagnosisRagSource | TraceRagResult | null): string {
  const text = sanitizeText(source?.content ?? '');
  const lower = text.toLowerCase();
  const name = formatDocumentName(source);

  if (!text) return `${name} 已作为本次诊断的维修资料依据，建议结合现场状态进一步确认。`;
  if (lower.includes('e101') || text.includes('温度')) {
    return 'E101 温度异常通常与散热不足、环境温度升高、负载过高或温度传感器异常有关，建议检查散热通道、风扇状态、负载变化和传感器读数。';
  }
  if (lower.includes('e201') || text.includes('振动')) {
    return 'E201 振动异常可能与轴承磨损、机械松动、转轴偏移或安装基础异常有关，建议检查振动值、机械连接状态、轴承运行情况和固定部件。';
  }
  if (lower.includes('e203') || text.includes('电机')) {
    return 'E203 电机运行异常可能与电流偏高、负载异常、轴承阻力增大或控制模块异常有关，建议结合电流趋势、负载状态和电机温升进行排查。';
  }
  if (lower.includes('e404') || text.includes('通信')) {
    return 'E404 通信异常通常与网络连接、通信线缆、控制器超时、地址配置或网关状态有关，建议检查链路、端子、控制器和交换机日志。';
  }
  return text.slice(0, 180);
}

export function sanitizeText(value: string): string {
  return value
    .replace(/```[\s\S]*?```/g, '')
    .replace(/^#+\s*/gm, '')
    .replace(/\bchunk[-_\s]?\d+\b/gi, '')
    .replace(/\bembedding\b/gi, '')
    .replace(/\bdistance\b/gi, '')
    .replace(/\bscore\b/gi, '')
    .replace(/\bsource\b/gi, '资料来源')
    .replace(/\bPossible Cause\b/gi, '可能原因')
    .replace(/\bAction\b/gi, '处理建议')
    .replace(/\bReference\b/gi, '参考资料')
    .replace(/\bConfidence\b/gi, '可信程度')
    .replace(/\s+/g, ' ')
    .trim();
}

function translateRiskSentence(text: string): string {
  const device = text.match(/DEV-\d+/i)?.[0]?.toUpperCase();
  const alarmCount = text.match(/(\d+)\s+unresolved alarms/i)?.[1];
  const prefix = device ? `设备 ${device}` : '当前设备';
  const countText = alarmCount ? `${alarmCount} 条未处理报警` : '未处理报警';
  const lower = text.toLowerCase();

  if (lower.includes('temperature exceeds safe range')) {
    return `${prefix} 当前存在 ${countText}，并检测到运行温度超过安全范围，建议结合历史运行数据进一步确认异常原因。`;
  }
  if (lower.includes('temperature is near threshold')) {
    return `${prefix} 当前存在 ${countText}，设备温度接近安全阈值，建议重点关注温度变化趋势。`;
  }
  if (lower.includes('communication')) {
    return `${prefix} 存在通信或运行状态异常，当前检测到报警信息，建议检查设备连接状态。`;
  }
  return `${prefix} 当前存在 ${countText}，建议安排现场复核。`;
}
