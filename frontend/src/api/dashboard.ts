import { requestJson } from '../api';
import type { DashboardOverview } from '../types';

export function fetchDashboardOverview(): Promise<DashboardOverview> {
  return requestJson<DashboardOverview>('/dashboard/overview');
}
