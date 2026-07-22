import { requestJson } from '../api';
import type {
  DeviceContext,
  MaintenanceRecordCreate,
  MaintenanceRecordSummary,
  RiskEventSummary,
} from '../types';

export function fetchDeviceContext(deviceCode: string): Promise<DeviceContext> {
  return requestJson<DeviceContext>(`/devices/${encodeURIComponent(deviceCode)}/context`);
}

export function fetchMaintenanceRecords(deviceCode?: string, limit = 50): Promise<MaintenanceRecordSummary[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (deviceCode) params.set('device_code', deviceCode);
  return requestJson<MaintenanceRecordSummary[]>(`/maintenance/records?${params.toString()}`);
}

export function createMaintenanceRecord(payload: MaintenanceRecordCreate): Promise<MaintenanceRecordSummary> {
  return requestJson<MaintenanceRecordSummary>('/maintenance/records', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function scanRiskEvents(): Promise<RiskEventSummary[]> {
  return requestJson<RiskEventSummary[]>('/agent/risk-monitoring/scan', {
    method: 'POST',
  });
}
