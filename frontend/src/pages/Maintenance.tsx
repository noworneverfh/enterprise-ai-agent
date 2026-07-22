import { FormEvent, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { createMaintenanceRecord, fetchDeviceContext, fetchMaintenanceRecords } from '../api/context';
import { fetchDevices } from '../api/devices';
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
import { formatDeviceName, formatDeviceOption, sortDevicesByCode } from '../utils/deviceDisplay';
import { formatBusinessText, formatDateTime } from '../utils/reportFormatter';
import { getFrontendPermissions } from '../utils/permissions';
import type { CurrentUser, DeviceContext, MaintenanceRecordCreate, MaintenanceRecordSummary, ToolDeviceInfo } from '../types';

export default function MaintenancePage({ currentUser }: { currentUser: CurrentUser | null }) {
  const [devices, setDevices] = useState<ToolDeviceInfo[]>([]);
  const [contexts, setContexts] = useState<DeviceContext[]>([]);
  const [records, setRecords] = useState<MaintenanceRecordSummary[]>([]);
  const [selectedDevice, setSelectedDevice] = useState('');
  const [actualAction, setActualAction] = useState('');
  const [rootCause, setRootCause] = useState('');
  const [result, setResult] = useState('');
  const [resolved, setResolved] = useState(true);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const canWrite = getFrontendPermissions(currentUser).generateReport;

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [deviceList, memoryList] = await Promise.all([fetchDevices(), fetchMaintenanceRecords(undefined, 80)]);
      const contextList = await Promise.all(deviceList.map((device) => fetchDeviceContext(device.device_code).catch(() => null)));
      setDevices(deviceList);
      setRecords(memoryList);
      setContexts(contextList.filter((item): item is DeviceContext => Boolean(item)));
      setSelectedDevice((current) => current || deviceList[0]?.device_code || '');
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : '维修闭环数据加载失败。');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, []);

  const deviceMap = useMemo(() => new Map(devices.map((device) => [device.id, device])), [devices]);
  const contextMemoryCount = contexts.reduce((total, context) => total + context.maintenance_memory.length, 0);
  const resolvedCount = records.filter((record) => record.resolved).length;
  const openCount = records.length - resolvedCount;
  const similarCaseCount = contexts.reduce((total, context) => total + context.similar_cases.length, 0);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canWrite || !selectedDevice || !actualAction.trim() || saving) return;
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const payload: MaintenanceRecordCreate = {
        device_code: selectedDevice,
        actual_action: actualAction.trim(),
        confirmed_root_cause: rootCause.trim() || null,
        resolved,
        result: result.trim() || null,
      };
      await createMaintenanceRecord(payload);
      setActualAction('');
      setRootCause('');
      setResult('');
      setResolved(true);
      setMessage('现场处理结果已保存，并将作为后续诊断的维修记忆。');
      await loadData();
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : '维修记录保存失败。');
    } finally {
      setSaving(false);
    }
  }

  return (
    <PageShell>
      <ProductHero
        eyebrow="Maintenance Memory"
        title="维修闭环中心"
        description="将 AI 诊断建议、现场实际处理、最终根因和处理结果沉淀为企业维修记忆，让后续相似故障能够参考已验证的处理经验。"
        side={
          <div className="grid gap-3 text-sm">
            <InfoLine label="闭环记录" value={`${records.length} 条`} />
            <InfoLine label="已解决" value={`${resolvedCount} 条`} />
            <div className="rounded-2xl bg-slate-100 p-3 text-xs leading-5 text-slate-500">
              {canWrite ? '可提交现场处理结果，形成设备长期维修记忆。' : '当前账号可查看维修闭环记录。'}
            </div>
          </div>
        }
      />

      {error ? <ErrorState message={error} /> : null}
      {message ? <div className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4 text-sm font-semibold text-emerald-700">{message}</div> : null}
      {loading ? <LoadingState title="正在读取维修闭环记录" steps={['设备列表', '维修记录', '历史案例']} /> : null}

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="维修闭环记录" value={loading ? '-' : `${records.length} 条`} description="人工处理结果沉淀" />
        <MetricCard label="已解决问题" value={loading ? '-' : `${resolvedCount} 条`} description="现场确认已恢复" tone="normal" />
        <MetricCard label="待跟进问题" value={loading ? '-' : `${openCount} 条`} description="仍需现场复核" tone={openCount ? 'warning' : 'normal'} />
        <MetricCard label="历史案例" value={loading ? '-' : `${similarCaseCount + contextMemoryCount} 条`} description="可用于相似故障参考" />
      </div>

      <div className="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_420px]">
        <SectionCard eyebrow="Maintenance Records" title="现场处理记录">
          <div className="mt-4 grid max-h-[680px] gap-3 overflow-y-auto pr-1">
            {records.map((record) => {
              const device = deviceMap.get(record.device_id);
              return (
                <article key={record.id} className="rounded-2xl border border-slate-200 bg-slate-50 p-4 transition hover:border-sky-200 hover:bg-white hover:shadow-sm">
                  <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2 text-sm font-semibold text-slate-500">
                        <span>{device?.device_code ?? `设备ID ${record.device_id}`}</span>
                        <span className="text-slate-300">/</span>
                        <span>{device ? formatDeviceName(device) : '设备'}</span>
                        <span className="text-slate-300">/</span>
                        <span>{formatDateTime(record.created_at)}</span>
                      </div>
                      <h3 className="mt-2 line-clamp-2 text-lg font-semibold text-slate-950">{record.confirmed_root_cause ?? '现场处理记录'}</h3>
                    </div>
                    <StatusBadge label={record.resolved ? '已解决' : '待跟进'} healthy={record.resolved} />
                  </div>
                  <div className="mt-4 grid gap-3 md:grid-cols-2">
                    <MemoryBlock label="现场处理" text={formatBusinessText(record.actual_action)} />
                    <MemoryBlock label="处理结果" text={record.result ? formatBusinessText(record.result) : '暂未登记处理结果，建议完成现场复核后补充。'} />
                  </div>
                  <div className="mt-4 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    {record.report_id ? <Link to={`/reports/${record.report_id}`} className="rounded-full border border-sky-200 px-3 py-1 font-semibold text-sky-700 hover:border-sky-300 hover:bg-sky-50">查看关联诊断报告</Link> : null}
                    {device?.device_code ? <Link to={`/devices/${device.device_code}`} className="rounded-full border border-slate-200 px-3 py-1 font-semibold text-slate-700 hover:border-sky-200 hover:bg-sky-50 hover:text-sky-700">查看设备画像</Link> : null}
                  </div>
                </article>
              );
            })}
            {!loading && !records.length ? <MaintenanceEmpty /> : null}
          </div>
        </SectionCard>

        <SectionCard eyebrow="Feedback Loop" title={canWrite ? '登记现场处理结果' : '维修记忆如何沉淀'}>
          {canWrite ? (
            <form onSubmit={submit} className="mt-4 grid gap-4">
              <label className="grid gap-2 text-sm font-semibold text-slate-700">
                设备 <span className="text-xs font-normal text-slate-400">必填</span>
                <select value={selectedDevice} onChange={(event) => setSelectedDevice(event.target.value)} className="field-control">
                  {sortDevicesByCode(devices).map((device) => (
                    <option key={device.device_code} value={device.device_code}>{formatDeviceOption(device)}</option>
                  ))}
                </select>
              </label>
              <label className="grid gap-2 text-sm font-semibold text-slate-700">
                实际处理 <span className="text-xs font-normal text-slate-400">必填，用于沉淀维修经验</span>
                <textarea value={actualAction} onChange={(event) => setActualAction(event.target.value)} rows={4} className="field-control resize-none" placeholder="例如：检查散热风扇并清理滤网，复核温度传感器读数。" />
              </label>
              <label className="grid gap-2 text-sm font-semibold text-slate-700">
                最终根因
                <input value={rootCause} onChange={(event) => setRootCause(event.target.value)} className="field-control" placeholder="例如：散热滤网堵塞" />
              </label>
              <label className="grid gap-2 text-sm font-semibold text-slate-700">
                处理结果
                <textarea value={result} onChange={(event) => setResult(event.target.value)} rows={3} className="field-control resize-none" placeholder="例如：设备恢复正常，连续观察 30 分钟未再次报警。" />
              </label>
              <label className="flex items-center gap-2 text-sm font-semibold text-slate-700">
                <input type="checkbox" checked={resolved} onChange={(event) => setResolved(event.target.checked)} className="h-4 w-4 rounded border-slate-300 text-sky-700" />
                故障已解决
              </label>
              <button type="submit" disabled={saving || !actualAction.trim()} className="primary-button">
                {saving ? '正在保存...' : '保存维修记忆'}
              </button>
              {!actualAction.trim() ? <div className="text-xs text-amber-600">请填写实际处理内容后再保存。</div> : null}
            </form>
          ) : (
            <div className="mt-4 grid gap-3 text-sm leading-6 text-slate-600">
              <p>现场处理结果会沉淀为设备长期记忆，后续诊断会优先参考已验证的根因、处理动作和恢复结果。</p>
              <div className="rounded-2xl bg-slate-50 p-4">
                <div className="font-semibold text-slate-950">闭环流程</div>
                <ol className="mt-3 grid gap-2 text-sm text-slate-600">
                  <li>1. AI 生成诊断建议</li>
                  <li>2. 运维人员现场处理</li>
                  <li>3. 登记实际根因和结果</li>
                  <li>4. 系统形成可复用历史案例</li>
                </ol>
              </div>
            </div>
          )}
        </SectionCard>
      </div>
    </PageShell>
  );
}

function InfoLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-slate-500">{label}</span>
      <span className="font-semibold text-slate-950">{value}</span>
    </div>
  );
}

function MemoryBlock({ label, text }: { label: string; text: string }) {
  return (
    <div className="rounded-2xl bg-white p-4 text-sm leading-6 text-slate-600 ring-1 ring-slate-200">
      <div className="mb-1 text-xs font-bold uppercase tracking-[0.12em] text-sky-700">{label}</div>
      {text}
    </div>
  );
}

function MaintenanceEmpty() {
  return (
    <div className="rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-5">
      <EmptyState title="暂无维修闭环记录" description="提交现场处理结果后，系统会在这里展示企业维修经验沉淀。" />
      <div className="mt-4 grid gap-3 text-sm text-slate-600 md:grid-cols-3">
        {['选择设备', '登记结果', '沉淀经验'].map((item, index) => (
          <div key={item} className="rounded-2xl bg-white p-3">
            <div className="font-semibold text-slate-950">{index + 1}. {item}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
