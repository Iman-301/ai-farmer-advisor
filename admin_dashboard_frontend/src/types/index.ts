// ── Session / Auth ────────────────────────────────────────────────────────────
export type UserRole = "admin" | "da" | "expert";

export interface SessionData {
  token: string;
  userId?: string;
  username: string; // kept for backwards compat (mirrors email)
  email?: string;
  fullName?: string;
  role: UserRole;
  loginTime: number;
  expiresAt?: number;
}

// ── Dashboard Users ──────────────────────────────────────────────────────────
export interface DashboardUser {
  user_id: string;
  full_name: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  created_at?: string;
  last_login_at?: string | null;
}

// ── Farmer —  /admin/farmers ──────────────────────────────────────────────────
export interface FarmerProfile {
  // backend fields
  id?: number;
  phone_number: string;
  name?: string;
  location?: string;
  language?: string;
  registered_at?: string;
  // optional richer fields
  crops?: string[] | null;
  farm_size?: number | null;
  notes?: string | null;
  // legacy / mock fields kept for compatibility
  farmer_id?: string;
  region?: string;
  zone?: string;
  woreda?: string;
  last_interaction?: string;
  total_calls?: number;
  primary_crops?: string[];
}

// ── Call Record — /admin/calls ────────────────────────────────────────────────
export interface CallLog {
  id: number | string;
  session_id?: string;
  phone_number?: string;
  farmer_name?: string;
  duration?: number;
  timestamp?: string;
  recording_path?: string;
  // legacy
  time?: string;
  date?: string;
  farmer_id?: string;
  question_summary?: string;
  handler?: 'AI' | 'Expert';
  confidence_level?: number;
  response_summary?: string;
  duration_seconds?: number;
}

// ── Call Detail — /admin/calls/{session_id} ──────────────────────────────────
export interface TranscriptMessage {
  role: 'user' | 'assistant';
  message: string;
  timestamp?: string;
}

export interface CallDetail {
  session_id: string;
  record: CallLog | null;
  farmer: {
    phone_number: string;
    name?: string;
    location?: string;
    language?: string;
  } | null;
  transcript: TranscriptMessage[];
}

// ── Interaction records — /admin/interaction-records ─────────────────────────
export interface InteractionRecord {
  id: number;
  phone_number?: string | null;
  session_id?: string | null;
  intent?: string | null;
  response_type?: string | null;
  entities?: unknown;
  confidence?: number | null;
  created_at?: string | null;
}

// ── Knowledge Base — /admin/kb ────────────────────────────────────────────────
export interface KBEntry {
  id: string;
  intent?: string;
  response?: string;
  // legacy / mock
  title?: string;
  category?: string;
  content?: string;
  source?: 'rag_pgvector' | 'legacy_chroma' | string;
  filename?: string | null;
  status?: string | null;
  chunk_count?: number;
  created_at?: string;
  updated_at?: string;
}

// ── KB Documents — /admin/kb/documents ───────────────────────────────────────
export type KBDocStatus = 'uploaded' | 'approved' | 'rejected';
export type KBDocIndexStatus = 'pending' | 'indexing' | 'indexed' | 'failed';

export interface KBDocument {
  id: string;
  filename: string;
  title?: string | null;
  description?: string | null;
  topic?: string | null;
  crop?: string | null;
  region?: string | null;
  category?: string | null;
  status: KBDocStatus;
  indexing_status: KBDocIndexStatus;
  indexing_error?: string | null;
  chroma_doc_count: number;
  uploaded_at?: string;
  approved_at?: string | null;
  last_indexed_at?: string | null;
}

// ── Escalation — /admin/escalations ──────────────────────────────────────────
export type EscalationStatus =
  | 'pending'
  | 'assigned'
  | 'answered'
  | 'closed'
  | 'resolved'
  | 'Open'
  | 'Resolved';

export interface EscalationCase {
  id?: number;
  query?: string;
  context?: string;
  status: EscalationStatus;
  timestamp?: string;
  phone_number?: string | null;
  session_id?: string | null;
  assigned_to?: { user_id: string; full_name: string; email: string } | null;
  assigned_at?: string | null;
  expert_response?: string | null;
  expert_audio_url?: string | null;
  transcript_messages?: TranscriptMessage[];
  session_record?: {
    session_id?: string;
    status?: string | null;
    duration_seconds?: number | null;
    timestamp?: string | null;
    recording_path?: string | null;
    audio_url?: string | null;
  } | null;
  session_recording_url?: string | null;
  session_recording_path?: string | null;
  answered_at?: string | null;
  closed_at?: string | null;
  // legacy / mock
  case_id?: string;
  farmer_id?: string;
  topic?: string;
  created_at?: string;
  resolved_at?: string;
  transcript?: string;
  entities?: string[];
  da_response?: string;
}

// ── Market Price — /admin/market-prices ───────────────────────────────────────
export interface MarketPrice {
  id: number;
  crop_name: string;
  region: string;
  price: number;
  unit: string;
  updated_at: string;
}

// ── Alert — /admin/alerts ─────────────────────────────────────────────────────
export interface Alert {
  id: number;
  target_region: string;
  alert_message: string;
  severity: 'info' | 'warning' | 'critical';
  category?: string | null;
  scheduled_at?: string | null;
  published_at?: string | null;
  call_notification_count?: number;
  created_at: string;
}

// ── Dashboard stats — /admin/stats ────────────────────────────────────────────
export interface AdminStats {
  total_farmers: number;
  calls_today: number;
  total_calls: number;
  pending_escalations: number;
  total_alerts: number;
  calls_per_day: { date: string; count: number }[];
  escalation_breakdown: Record<string, number>;
  kb_count: number;
}

// ── System status — /admin/system-status ─────────────────────────────────────
export interface ServiceProbe {
  url?: string;
  status: 'online' | 'degraded' | 'down' | string;
  http_status?: number;
  error?: string;
  chroma_docs?: number;
  chroma_status?: string;
}

export interface SystemStatus {
  services: {
    vad: ServiceProbe;
    asr: ServiceProbe;
    tts: ServiceProbe;
    phone_gateway: ServiceProbe;
    logic_service: ServiceProbe;
    rag: ServiceProbe;
    database: ServiceProbe;
  };
  recent_errors: {
    id: number;
    service: string;
    endpoint?: string;
    method?: string;
    status_code?: number;
    error: string;
    created_at?: string;
  }[];
}

// ── Analytics ────────────────────────────────────────────────────────────────
export interface AnalyticsSummary {
  total_calls: number;
  calls_30d: number;
  total_farmers: number;
  new_farmers_30d: number;
  open_escalations: number;
  answered_escalations: number;
}

export interface ExpertPerformance {
  user_id: string;
  full_name: string;
  email: string;
  assigned: number;
  resolved: number;
}

export interface DAPerformance {
  user_id: string;
  full_name: string;
  email: string;
  alerts_created: number;
}

// ── Legacy mock-data shapes (kept to avoid breaking existing imports) ─────────
export interface DashboardStats {
  total_calls_today: number;
  ai_answered: number;
  escalated_to_experts: number;
  active_helpdesk_cases: number;
}

export interface SystemOverview {
  ai_confidence_average: number;
  average_response_time: number;
  farmer_satisfaction_rate: number;
  knowledge_base_entries: number;
}
