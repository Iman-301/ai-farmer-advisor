// ── Session / Auth ────────────────────────────────────────────────────────────
export interface SessionData {
  token: string;
  role: 'admin' | 'expert';
  username: string;
  loginTime: number;
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
  // backend
  id: number | string;
  session_id?: string;
  phone_number?: string;
  farmer_name?: string;
  duration?: number;
  timestamp?: string;
  recording_path?: string;
  // legacy / mock
  time?: string;
  date?: string;
  farmer_id?: string;
  question_summary?: string;
  handler?: 'AI' | 'Expert';
  confidence_level?: number;
  response_summary?: string;
  duration_seconds?: number;
}

// ── Knowledge Base — /admin/kb ────────────────────────────────────────────────
export interface KBEntry {
  id: string;
  // backend
  intent?: string;
  response?: string;
  // legacy / mock
  title?: string;
  category?: string;
  content?: string;
  created_at?: string;
  updated_at?: string;
}

// ── Escalation — /admin/escalations ──────────────────────────────────────────
export interface EscalationCase {
  // backend (optional so mock data without id is still valid)
  id?: number;
  query?: string;
  context?: string;
  status: 'pending' | 'resolved' | 'Open' | 'Resolved';
  timestamp?: string;
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
