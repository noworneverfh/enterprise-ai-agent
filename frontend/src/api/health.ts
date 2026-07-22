import { requestJson } from '../api';
import type { SystemHealth } from '../types';

export function fetchSystemHealth(): Promise<SystemHealth> {
  return requestJson<SystemHealth>('/system/health');
}

export interface PlatformHealth {
  status: string;
  database: string;
  vector_db: string;
  rag?: {
    retriever: string;
    reranker_enabled: boolean;
    reranker_model: string | null;
    candidate_k: number | null;
    mode: string;
  };
  llm: {
    provider: string;
    provider_class: string | null;
    model: string | null;
    base_url_domain: string | null;
    configured: boolean;
    reachable: boolean;
    mode: string;
    error_type: string | null;
  };
}

export function fetchPlatformHealth(): Promise<PlatformHealth> {
  return requestJson<PlatformHealth>('/health');
}
