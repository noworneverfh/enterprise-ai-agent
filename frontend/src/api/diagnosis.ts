import { requestJson } from '../api';
import type { DiagnosisHistoryDetail, DiagnosisHistoryItem, RecentAlarm } from '../types';

export function fetchRecentAlarms(): Promise<RecentAlarm[]> {
  return requestJson<RecentAlarm[]>('/alarms/recent');
}

export function fetchDiagnosisHistory(limit = 20): Promise<DiagnosisHistoryItem[]> {
  return requestJson<DiagnosisHistoryItem[]>(`/diagnosis/history?limit=${limit}`);
}

export function fetchDiagnosisReport(reportId: string): Promise<DiagnosisHistoryDetail> {
  return requestJson<DiagnosisHistoryDetail>(`/diagnosis/history/${encodeURIComponent(reportId)}`);
}
