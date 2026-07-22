export type DeviceDisplayLike = {
  device_code: string;
  name?: string | null;
  device_type?: string | null;
  location?: string | null;
};

const DEVICE_NAME_BY_CODE: Record<string, string> = {
  'DEV-001': '一号电机控制单元',
  'DEV-002': '电机驱动单元',
  'DEV-003': '温度传感器',
  'DEV-004': '空气压缩机',
  'DEV-005': '振动电机',
  'DEV-006': '液压泵站',
  'DEV-007': '输送线减速箱',
  'DEV-008': '冷却风机',
  'DEV-009': 'PLC 网关',
};

const DEVICE_NAME_KEYWORDS: Array<[string, string]> = [
  ['Motor Drive', '电机驱动单元'],
  ['Temperature Sensor', '温度传感器'],
  ['Air Compressor', '空气压缩机'],
  ['Vibration Motor', '振动电机'],
  ['Hydraulic Pump', '液压泵站'],
  ['Conveyor Gearbox', '输送线减速箱'],
  ['Cooling Fan', '冷却风机'],
  ['PLC Gateway', 'PLC 网关'],
];

const DEVICE_TYPE_LABELS: Record<string, string> = {
  motor: '电机',
  sensor: '传感器',
  compressor: '压缩机',
  pump: '液压泵',
  gearbox: '减速箱',
  fan: '风机',
  gateway: '网关',
  controller: '控制器',
};

export function formatDeviceName(device: DeviceDisplayLike): string {
  const byCode = DEVICE_NAME_BY_CODE[device.device_code];
  if (byCode) return byCode;

  const rawName = device.name?.trim();
  if (rawName) {
    const matched = DEVICE_NAME_KEYWORDS.find(([keyword]) => rawName.includes(keyword));
    if (matched) return matched[1];
    return rawName;
  }

  if (device.device_type) return DEVICE_TYPE_LABELS[device.device_type] ?? device.device_type;
  return '设备';
}

export function formatDeviceOption(device: DeviceDisplayLike): string {
  return `${device.device_code} · ${formatDeviceName(device)}`;
}

export function formatDeviceType(deviceType?: string | null): string {
  if (!deviceType) return '未登记类型';
  return DEVICE_TYPE_LABELS[deviceType] ?? deviceType;
}

export function sortDevicesByCode<T extends DeviceDisplayLike>(devices: T[]): T[] {
  return [...devices].sort((left, right) =>
    left.device_code.localeCompare(right.device_code, 'zh-CN', { numeric: true }),
  );
}
