import type { ReactNode } from 'react';
import { motion } from 'framer-motion';
import { formatRiskLevel } from '../utils/reportFormatter';
import type { RiskLevel } from '../types';

export function PageShell({ children }: { children: ReactNode }) {
  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: 'easeOut' }}
      className="mx-auto grid w-full max-w-[1760px] gap-4 px-4 py-4 sm:px-5 lg:px-7 2xl:gap-5"
    >
      {children}
    </motion.section>
  );
}

export function ProductHero({
  eyebrow,
  title,
  description,
  side,
}: {
  eyebrow: string;
  title: string;
  description: string;
  side?: ReactNode;
}) {
  return (
    <section className="surface-card overflow-hidden p-5 sm:p-6">
      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="min-w-0">
          <p className="eyebrow">{eyebrow}</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight text-slate-50 sm:text-3xl">{title}</h1>
          <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-400">{description}</p>
        </div>
        {side ? <div className="rounded-2xl border border-white/10 bg-white/[0.035] p-4">{side}</div> : null}
      </div>
    </section>
  );
}

export function SectionCard({
  eyebrow,
  title,
  right,
  children,
  className = '',
}: {
  eyebrow?: string;
  title: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`surface-card p-4 sm:p-5 ${className}`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
          <h2 className="mt-1 text-lg font-semibold text-slate-50">{title}</h2>
        </div>
        {right ? <div className="shrink-0">{right}</div> : null}
      </div>
      {children}
    </section>
  );
}

export function MetricCard({
  label,
  value,
  description,
  trend,
  tone = 'default',
}: {
  label: string;
  value: string;
  description: string;
  trend?: string;
  tone?: 'default' | 'normal' | 'warning' | 'danger';
}) {
  const palette = {
    default: 'border-white/10 bg-white/[0.035]',
    normal: 'border-emerald-400/20 bg-emerald-400/[0.075]',
    warning: 'border-amber-400/22 bg-amber-400/[0.08]',
    danger: 'border-red-400/22 bg-red-400/[0.08]',
  }[tone];
  const dot = {
    default: 'bg-sky-400',
    normal: 'bg-emerald-400',
    warning: 'bg-amber-400',
    danger: 'bg-red-400',
  }[tone];

  return (
    <article className={`interactive-card rounded-2xl border p-4 ${palette}`}>
      <div className="flex items-center gap-2 text-sm font-medium text-slate-400">
        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${dot}`} />
        <span className="min-w-0 truncate">{label}</span>
      </div>
      <div className="mt-3 break-words text-3xl font-semibold tracking-tight text-slate-50">{value}</div>
      <div className="mt-2 text-xs leading-5 text-slate-400">{description}</div>
      {trend ? <div className="mt-4 rounded-full border border-white/10 bg-black/16 px-3 py-1 text-xs font-semibold text-slate-300">{trend}</div> : null}
    </article>
  );
}

export function RiskBadge({ level }: { level?: RiskLevel | string | null }) {
  const normalized = normalizeRiskLevel(level);
  const classes: Record<RiskLevel, string> = {
    critical: 'border-red-400/30 bg-red-500/14 text-red-200',
    high: 'border-red-400/30 bg-red-500/12 text-red-200',
    medium: 'border-amber-400/30 bg-amber-500/12 text-amber-200',
    low: 'border-emerald-400/30 bg-emerald-500/12 text-emerald-200',
    normal: 'border-emerald-400/30 bg-emerald-500/12 text-emerald-200',
    unknown: 'border-slate-400/20 bg-slate-400/10 text-slate-300',
  };
  return (
    <span className={`inline-flex whitespace-nowrap rounded-full border px-3 py-1 text-xs font-semibold ${classes[normalized]}`}>
      {formatRiskLevel(normalized)}
    </span>
  );
}

type RiskBandKey = 'normal' | 'medium' | 'high' | 'critical';

const riskBands: Array<{
  key: RiskBandKey;
  label: string;
  dot: string;
  text: string;
}> = [
  {
    key: 'normal',
    label: '正常',
    dot: 'bg-emerald-400',
    text: '设备运行参数处于安全范围，当前没有需要优先处理的风险信号。',
  },
  {
    key: 'medium',
    label: '关注',
    dot: 'bg-amber-400',
    text: '存在待处理报警或参数接近阈值，建议纳入当班巡检并持续观察。',
  },
  {
    key: 'high',
    label: '较高',
    dot: 'bg-orange-500',
    text: '存在明显异常或多项证据叠加，建议优先安排现场复核。',
  },
  {
    key: 'critical',
    label: '严重',
    dot: 'bg-red-500',
    text: '存在严重报警或关键参数越限，应立即处置并做好安全隔离。',
  },
];

function normalizeRiskLevel(level?: RiskLevel | string | null): RiskLevel {
  if (level === 'critical' || level === 'high' || level === 'medium' || level === 'low' || level === 'normal') return level;
  return 'unknown';
}

function normalizeRiskBand(level?: RiskLevel | string | null): RiskBandKey {
  if (level === 'critical') return 'critical';
  if (level === 'high') return 'high';
  if (level === 'medium') return 'medium';
  return 'normal';
}

export function riskBandLabel(level?: RiskLevel | string | null): string {
  return riskBands.find((item) => item.key === normalizeRiskBand(level))?.label ?? '待确认';
}

export function RiskIntervalScale({
  level,
  title = '风险区间',
  basis,
  className = '',
}: {
  level?: RiskLevel | string | null;
  title?: string;
  basis?: string[];
  className?: string;
}) {
  const current = normalizeRiskBand(level);
  const currentIndex = Math.max(0, riskBands.findIndex((band) => band.key === current));
  const currentBand = riskBands[currentIndex] ?? riskBands[0];
  const stepPercent = riskBands.length > 1 ? currentIndex / (riskBands.length - 1) : 0;
  const progressColor =
    current === 'critical'
      ? 'bg-red-500'
      : current === 'high'
        ? 'bg-orange-500'
        : current === 'medium'
          ? 'bg-amber-400'
          : 'bg-emerald-400';

  return (
    <div className={`rounded-2xl border border-white/10 bg-white/[0.035] p-4 ${className}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-sm font-semibold text-slate-50">{title}</div>
        <span className="rounded-full border border-white/10 bg-black/20 px-3 py-1 text-xs font-semibold text-slate-300">
          当前：{currentBand.label}
        </span>
      </div>
      <div className="mt-5">
        <div className="grid grid-cols-4 text-center text-xs font-semibold text-slate-400">
          {riskBands.map((band) => (
            <span key={band.key}>{band.label}</span>
          ))}
        </div>
        <div className="relative mt-3 h-6">
          <div className="absolute left-[6%] right-[6%] top-1/2 h-2 -translate-y-1/2 rounded-full bg-slate-700/80" />
          <div
            className={`absolute left-[6%] top-1/2 h-2 -translate-y-1/2 rounded-full transition-all ${progressColor}`}
            style={{ width: `calc(${stepPercent * 88}% + 0px)` }}
          />
          {riskBands.map((band, index) => (
            <span
              key={band.key}
              className={`absolute top-1/2 h-4 w-4 -translate-x-1/2 -translate-y-1/2 rounded-full ring-4 ring-[#111c2a] ${
                index <= currentIndex ? band.dot : 'bg-slate-600'
              }`}
              style={{ left: `${6 + index * (88 / (riskBands.length - 1))}%` }}
            />
          ))}
        </div>
        <div className="grid grid-cols-4 text-center text-xs text-slate-500">
          {riskBands.map((band) => (
            <span key={band.key}>{band.key === current ? '当前' : ''}</span>
          ))}
        </div>
      </div>
      <p className="mt-4 text-sm leading-6 text-slate-400">{currentBand.text}</p>
      {basis?.length ? (
        <div className="mt-3 rounded-2xl border border-white/10 bg-black/18 px-4 py-3 text-xs leading-5 text-slate-400">
          <span className="font-semibold text-slate-200">判定依据：</span>
          {basis.filter(Boolean).join('、')}
        </div>
      ) : null}
    </div>
  );
}

export function StatusBadge({ label, healthy = true }: { label: string; healthy?: boolean }) {
  return (
    <span
      className={`inline-flex whitespace-nowrap rounded-full border px-2.5 py-1 text-xs font-semibold ${
        healthy ? 'border-emerald-400/30 bg-emerald-500/12 text-emerald-200' : 'border-amber-400/30 bg-amber-500/12 text-amber-200'
      }`}
    >
      {label}
    </span>
  );
}

export function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-white/14 bg-white/[0.025] p-6 text-center">
      <div className="text-sm font-semibold text-slate-100">{title}</div>
      <p className="mt-2 text-sm leading-6 text-slate-400">{description}</p>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="rounded-2xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm leading-6 text-red-200">
      {message}
    </div>
  );
}

export function LoadingState({ title, steps }: { title: string; steps?: string[] }) {
  return (
    <div className="surface-card p-5">
      <div className="flex items-center gap-3">
        <span className="h-3 w-3 animate-pulse rounded-full bg-sky-400" />
        <span className="font-semibold text-slate-100">{title}</span>
      </div>
      {steps?.length ? (
        <div className="mt-4 grid gap-2 sm:grid-cols-3">
          {steps.map((step) => (
            <div key={step} className="rounded-xl border border-white/10 bg-white/[0.035] px-3 py-2 text-xs font-semibold text-slate-400">
              {step}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

type VisualTone = 'default' | 'normal' | 'warning' | 'danger' | 'emerald' | 'amber' | 'red';

export function TrendLine({ tone = 'default', values }: { tone?: VisualTone; values?: number[] }) {
  const stroke = {
    default: '#38bdf8',
    normal: '#10b981',
    warning: '#f59e0b',
    danger: '#ef4444',
    emerald: '#10b981',
    amber: '#f59e0b',
    red: '#ef4444',
  }[tone];
  const series = values?.filter((value) => Number.isFinite(value)) ?? [];
  const plotted = series.length >= 2 ? series : [42, 46, 44, 50, 55, 54];
  const width = 240;
  const height = 72;
  const paddingX = 10;
  const paddingY = 10;
  const min = Math.min(...plotted);
  const max = Math.max(...plotted);
  const range = max - min || 1;
  const points = plotted.map((value, index) => {
    const x = paddingX + (index * (width - paddingX * 2)) / Math.max(1, plotted.length - 1);
    const y = paddingY + (1 - (value - min) / range) * (height - paddingY * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const area = `${paddingX},${height - paddingY} ${points.join(' ')} ${width - paddingX},${height - paddingY}`;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-20 w-full overflow-visible" role="img" aria-label="趋势示意">
      <polygon points={area} fill={stroke} opacity="0.12" />
      <polyline points={points.join(' ')} fill="none" stroke={stroke} strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

type ProgressTone = 'default' | 'normal' | 'warning' | 'danger' | 'emerald' | 'amber' | 'red';

export function ProgressBar({ value, tone = 'default' }: { value: number; tone?: ProgressTone }) {
  const safeValue = Math.max(0, Math.min(100, value));
  const color = {
    default: 'bg-sky-400',
    normal: 'bg-emerald-400',
    warning: 'bg-amber-400',
    danger: 'bg-red-500',
    emerald: 'bg-emerald-400',
    amber: 'bg-amber-400',
    red: 'bg-red-500',
  }[tone];
  return (
    <div className="h-2 overflow-hidden rounded-full bg-slate-700/80" aria-label={`进度 ${safeValue}%`}>
      <div className={`h-full rounded-full ${color}`} style={{ width: `${safeValue}%` }} />
    </div>
  );
}
