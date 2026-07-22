import { requestJson } from '../api';
import type { DeviceStatistics, ToolDeviceInfo } from '../types';

export function fetchDevices(): Promise<ToolDeviceInfo[]> {
  return requestJson<ToolDeviceInfo[]>('/devices');
}

export function fetchDeviceStatistics(): Promise<DeviceStatistics> {
  return requestJson<DeviceStatistics>('/devices/statistics');
}
