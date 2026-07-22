import type {
  AgentDiagnoseRequest,
  AgentDiagnoseResponse,
  AgentTrace,
  MultiDeviceRiskRequest,
  MultiDeviceRiskResponse,
} from './types';

const TOKEN_STORAGE_KEY = 'enterprise_ai_agent_token';

export function getAuthToken(): string | null {
  return window.localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setAuthToken(token: string): void {
  window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearAuthToken(): void {
  window.localStorage.removeItem(TOKEN_STORAGE_KEY);
}

export async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), 30_000);
  const isFormData = options?.body instanceof FormData;
  const authToken = getAuthToken();
  const headers = new Headers(options?.headers);

  if (!isFormData && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  if (authToken && !headers.has('Authorization')) {
    headers.set('Authorization', `Bearer ${authToken}`);
  }

  try {
    const response = await fetch(path, {
      ...options,
      headers,
      signal: controller.signal,
    });

    if (!response.ok) {
      let detail =
        response.status === 401
          ? '登录状态已过期，请重新登录。'
          : response.status === 403
            ? '当前账号暂无操作权限。'
            : response.status === 404
              ? '请求接口不存在，请确认后端服务已启动并加载最新路由。'
              : `请求失败，HTTP ${response.status}`;

      try {
        const contentType = response.headers.get('content-type') ?? '';
        if (contentType.includes('application/json')) {
          const payload = (await response.json()) as { detail?: string };
          if (payload.detail) {
            detail = translateBackendError(payload.detail);
          }
        }
      } catch {
        // Keep the safe status message when the server returns invalid JSON.
      }

      throw new Error(detail);
    }

    if (response.status === 204) {
      return undefined as T;
    }

    const contentType = response.headers.get('content-type') ?? '';
    if (!contentType.includes('application/json')) {
      throw new Error('后端返回了非 JSON 响应，请检查 API 代理或服务路由配置。');
    }

    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('请求超时，请确认后端服务运行正常后重试。');
    }
    throw error;
  } finally {
    window.clearTimeout(timeoutId);
  }
}

export function diagnose(payload: AgentDiagnoseRequest): Promise<AgentDiagnoseResponse> {
  return requestJson<AgentDiagnoseResponse>('/agent/diagnose', {
    method: 'POST',
    headers: { 'X-Report-Version': '2.0' },
    body: JSON.stringify(payload),
  });
}

export function analyzeAllDeviceRisk(payload: MultiDeviceRiskRequest): Promise<MultiDeviceRiskResponse> {
  return requestJson<MultiDeviceRiskResponse>('/agent/risk-analysis', {
    method: 'POST',
    headers: { 'X-Report-Version': '2.0' },
    body: JSON.stringify(payload),
  });
}

export function fetchLatestTrace(): Promise<AgentTrace> {
  return requestJson<AgentTrace>('/agent/debug/trace/latest');
}

function translateBackendError(message: string): string {
  const lower = message.toLowerCase();
  if (lower.includes('permission denied') || lower.includes('forbidden')) return '当前账号暂无操作权限。';
  if (lower.includes('not authenticated') || lower.includes('unauthorized')) return '登录状态已过期，请重新登录。';
  if (lower.includes('not found')) return '请求的资源不存在。';
  return message;
}
