export type RiskLevel = 'normal' | 'low' | 'medium' | 'high' | 'critical' | 'unknown';

export interface AgentDiagnoseRequest {
  query: string;
  device_code?: string | null;
  knowledge_top_k: number;
  include_device_status: boolean;
  include_knowledge: boolean;
}

export interface MultiDeviceRiskRequest {
  query: string;
  include_knowledge?: boolean;
  knowledge_top_k?: number;
}

export interface ToolDeviceInfo {
  id: number;
  device_code: string;
  name: string;
  device_type: string;
  location: string;
  is_online: boolean;
  created_at: string;
}

export interface ToolRuntimeData {
  id: number;
  device_id: number;
  temperature: number;
  voltage: number;
  current: number;
  vibration: number;
  status: string;
  recorded_at: string;
  created_at: string;
}

export interface ToolAlarmRecord {
  id: number;
  device_id: number;
  alarm_code: string;
  alarm_level: RiskLevel;
  message: string;
  is_resolved: boolean;
  occurred_at: string;
  resolved_at: string | null;
  created_at: string;
}

export interface AgentDiagnoseResponse {
  problem_summary: string;
  device: ToolDeviceInfo | null;
  device_status: ToolRuntimeData | null;
  recent_alarms: ToolAlarmRecord[];
  risk_level: RiskLevel;
  possible_causes: string[];
  recommended_actions: string[];
  sources: string[];
  tools_used: string[];
  warnings: string[];
  disclaimer: string;
  report_v2?: DiagnosisReportV2 | null;
}

export interface DeviceStatistics {
  total: number;
  normal: number;
  warning: number;
  maintenance: number;
}

export interface DeviceRiskItem {
  device: ToolDeviceInfo;
  latest_runtime_data: ToolRuntimeData | null;
  unresolved_alarms: ToolAlarmRecord[];
  risk_level: RiskLevel;
  risk_score: number;
  reasons: string[];
  knowledge_sources: string[];
  recommended_actions: string[];
}

export interface MultiDeviceRiskResponse {
  query: string;
  summary: string;
  overall_risk_level: RiskLevel;
  device_risks: DeviceRiskItem[];
  key_findings: string[];
  recommended_actions: string[];
  sources: string[];
  tools_used: string[];
  warnings: string[];
  confidence: number;
  disclaimer: string;
  created_at: string;
  report_v2?: FleetRiskReportV2 | null;
}

export interface AgentTrace {
  trace_id: string;
  created_at: string;
  mode: string;
  query: string;
  device_code: string | null;
  router_tools: string[];
  tool_results: TraceToolResult[];
  rag_results: TraceRagResult[];
  llm_final_status: TraceLlmStatus | null;
}

export interface TraceAlarmResult {
  device_id: string;
  alarm_code: string;
  alarm_name: string;
  level: RiskLevel;
  status: string;
  created_at: string;
}

export interface TraceToolResult {
  tool_name: string;
  success: boolean;
  error: string | null;
  result: Record<string, unknown> & {
    alarms?: TraceAlarmResult[];
    alarm_count?: number;
  };
}

export interface TraceRagResult {
  chunk_id: number;
  document_id: number;
  filename: string;
  chunk_index: number;
  source: string;
  distance: number;
  vector_score?: number | null;
  rerank_score?: number | null;
  content?: string | null;
  device_code?: string | null;
  alarm_code?: string | null;
  query?: string | null;
}

export interface TraceLlmStatus {
  status: string;
  fallback_reason: string | null;
  recorded_at: string;
}

export interface DashboardOverview {
  online_devices: number;
  today_diagnosis_count: number;
  knowledge_documents_count: number;
  agent_status: string;
  avg_response_time: number | null;
}

export interface RecentAlarm {
  device_code: string;
  alarm_code: string;
  alarm_name: string;
  alarm_level: RiskLevel;
  status: string;
  created_at: string;
}

export interface DiagnosisHistoryItem {
  report_id: string;
  device_code: string | null;
  alarm_code: string | null;
  alarm_name: string | null;
  risk_level: RiskLevel;
  status: string;
  created_at: string;
  confidence: number | null;
  problem_summary: string | null;
  sources: string[];
  tools_used: string[];
}

export interface DiagnosisRagSource {
  source: string;
  filename: string | null;
  chunk_id: number | null;
  chunk_index: number | null;
  distance: number | null;
  vector_score?: number | null;
  rerank_score?: number | null;
  content: string | null;
}

export interface ConfirmedFactV2 {
  fact_id: string;
  category: 'device' | 'runtime' | 'alarm' | 'knowledge' | 'history';
  label: string;
  value: string;
  status: 'normal' | 'warning' | 'critical' | 'unknown' | 'info';
  source: string;
}

export interface ParameterObservationV2 {
  parameter: string;
  label: string;
  value: number;
  unit: string;
  normal_min: number;
  normal_max: number;
  status: 'normal' | 'warning' | 'critical' | 'unknown' | 'info';
  explanation: string;
  observed_at?: string | null;
}

export interface DiagnosisCauseV2 {
  title: string;
  description: string;
  confidence: 'high' | 'medium' | 'low' | 'unknown';
  evidence_refs: string[];
  verification_method: string;
}

export interface VerificationStepV2 {
  order: number;
  title: string;
  description: string;
  safety_note?: string | null;
}

export interface MaintenanceActionV2 {
  order: number;
  priority: 'immediate' | 'planned' | 'observe';
  title: string;
  description: string;
  safety_required: boolean;
  evidence_refs: string[];
}

export interface DiagnosisCitationV2 {
  citation_id: string;
  source: string;
  title: string;
  excerpt?: string | null;
  document_id?: number | null;
  chunk_id?: number | null;
  chunk_index?: number | null;
  distance?: number | null;
  vector_score?: number | null;
  rerank_score?: number | null;
}

export interface RiskScoreItemV2 {
  code: string;
  label: string;
  score: number;
  reason: string;
}

export interface RiskAssessmentV2 {
  level: RiskLevel;
  score: number;
  breakdown: RiskScoreItemV2[];
}

export interface DiagnosisReportV2 {
  report_version: '2.0';
  generation_mode: 'llm' | 'mock' | 'fallback' | 'deterministic';
  conclusion: string;
  risk: RiskAssessmentV2;
  confirmed_facts: ConfirmedFactV2[];
  parameter_observations: ParameterObservationV2[];
  possible_causes: DiagnosisCauseV2[];
  verification_steps: VerificationStepV2[];
  action_plan: MaintenanceActionV2[];
  citations: DiagnosisCitationV2[];
  data_gaps: string[];
}

export interface DeviceRiskSummaryV2 {
  device_code: string;
  device_name: string;
  device_type: string;
  risk: RiskAssessmentV2;
  confirmed_facts: ConfirmedFactV2[];
  parameter_observations: ParameterObservationV2[];
  possible_causes: DiagnosisCauseV2[];
  action_plan: MaintenanceActionV2[];
  citations: DiagnosisCitationV2[];
  data_gaps: string[];
}

export interface FleetRiskReportV2 {
  report_version: '2.0';
  generation_mode: 'llm' | 'mock' | 'fallback' | 'deterministic';
  summary: string;
  overall_risk: RiskAssessmentV2;
  devices: DeviceRiskSummaryV2[];
  citations: DiagnosisCitationV2[];
  data_gaps: string[];
}

export interface DiagnosisHistoryDetail {
  report_id: string;
  device_code: string | null;
  alarm_code: string | null;
  alarm_name: string | null;
  risk_level: RiskLevel;
  status: string;
  query: string;
  problem_summary: string;
  response: AgentDiagnoseResponse | null;
  risk_report: MultiDeviceRiskResponse | null;
  tools_used: string[];
  rag_sources: DiagnosisRagSource[];
  confidence: number | null;
  duration_ms: number | null;
  trace: AgentTrace | null;
  report_v2?: DiagnosisReportV2 | FleetRiskReportV2 | null;
  created_at: string;
}

export interface SystemHealth {
  router: string;
  tools: string;
  rag: string;
  llm: string;
}

export type UserRole = 'admin' | 'user';

export interface CurrentUser {
  id: number;
  username: string;
  roles: UserRole[];
  permissions: string[];
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
}

export interface KnowledgeDocument {
  id: number;
  filename: string;
  file_type: string;
  file_size: number | null;
  status: 'uploaded' | 'processing' | 'indexed' | 'failed' | string;
  chunk_count: number;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeChunk {
  id: number;
  document_id: number;
  chunk_index: number;
  content: string;
  content_hash: string | null;
  vector_id: string | null;
  start_char: number | null;
  end_char: number | null;
  created_at: string;
}

export interface DeviceContextDevice {
  id: number;
  device_code: string;
  name: string;
  device_type: string;
  location: string | null;
  is_online: boolean;
  created_at: string;
}

export interface DeviceContextRuntimePoint {
  id: number;
  temperature: number | null;
  voltage: number | null;
  current: number | null;
  vibration: number | null;
  status: string;
  recorded_at: string;
}

export interface DeviceContextAlarm {
  id: number;
  alarm_code: string;
  alarm_name: string;
  alarm_level: RiskLevel | string;
  message: string;
  is_resolved: boolean;
  occurred_at: string;
  resolved_at: string | null;
}

export interface DeviceContextDiagnosisHistory {
  report_id: string;
  query: string;
  risk_level: RiskLevel | string;
  problem_summary: string;
  created_at: string;
}

export interface DeviceContextRiskPoint {
  risk_level: RiskLevel | string;
  risk_score: number;
  alarm_count: number;
  abnormal_parameters: string[];
  report_id: string | null;
  recorded_at: string;
}

export interface DeviceContextMaintenanceMemory {
  id: number;
  report_id: string | null;
  alarm_code: string | null;
  actual_action: string;
  confirmed_root_cause: string | null;
  resolved: boolean;
  result: string | null;
  performed_at: string | null;
  created_at: string;
}

export interface DeviceContextKnowledgeLink {
  fault_code: string;
  fault_name: string;
  severity: string;
  device_type: string | null;
  document_id: number | null;
  cause_count: number;
  case_count: number;
}

export interface DeviceContextSimilarCase {
  id: number;
  device: string;
  fault: string;
  symptom: string;
  root_cause: string;
  solution: string;
  result: string;
  created_at: string;
}

export interface DeviceHealthSummary {
  current_risk_level: RiskLevel | string;
  current_risk_score: number;
  unresolved_alarm_count: number;
  historical_alarm_count: number;
  diagnosis_count: number;
  maintenance_record_count: number;
  abnormal_parameters: string[];
  trend: 'improving' | 'stable' | 'worsening' | 'unknown';
}

export interface DeviceContext {
  exists: boolean;
  device: DeviceContextDevice | null;
  current_runtime: DeviceContextRuntimePoint | null;
  runtime_history: DeviceContextRuntimePoint[];
  current_alarms: DeviceContextAlarm[];
  historical_alarms: DeviceContextAlarm[];
  diagnosis_history: DeviceContextDiagnosisHistory[];
  risk_trend: DeviceContextRiskPoint[];
  maintenance_memory: DeviceContextMaintenanceMemory[];
  related_knowledge: DeviceContextKnowledgeLink[];
  similar_cases: DeviceContextSimilarCase[];
  health_summary: DeviceHealthSummary | null;
}

export interface MaintenanceRecordCreate {
  device_code: string;
  report_id?: string | null;
  alarm_record_id?: number | null;
  ai_recommendation?: Record<string, unknown> | Array<Record<string, unknown>> | null;
  actual_action: string;
  confirmed_root_cause?: string | null;
  resolved: boolean;
  result?: string | null;
  performed_at?: string | null;
}

export interface MaintenanceRecordSummary {
  id: number;
  device_id: number;
  report_id: string | null;
  actual_action: string;
  confirmed_root_cause: string | null;
  resolved: boolean;
  result: string | null;
  performed_at: string | null;
  created_at: string;
}

export interface RiskEventSummary {
  event_id: string;
  device_code: string;
  event_type: string;
  risk_level: RiskLevel | string;
  risk_score: number;
  summary: string;
  evidence: Record<string, unknown> | Array<Record<string, unknown>> | null;
  status: string;
  report_id: string | null;
  created_at: string;
}
