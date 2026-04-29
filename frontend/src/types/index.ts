export type AppStep = 'form' | 'generating' | 'outline' | 'ppt-generating' | 'complete';
export type PhaseStatus = 'idle' | 'running' | 'done' | 'error';

export interface PhaseState {
  status: PhaseStatus;
  message: string;
  data?: Record<string, unknown>;
  startedAt?: number;
  doneAt?: number;
}

export interface QueryProgress {
  index: number;
  question: string;
  status: string;
  rows: number;
  columns: number;
  completed: number;
  total: number;
  error?: string;
}

export interface SlideOutline {
  id: string;
  number: number;
  title: string;
  subtitle?: string;
  points: string[];
  insight?: string;
  table_data?: Record<string, string>[] | null;
}

export interface ReportOutline {
  event_name: string;
  slides: SlideOutline[];
}

export interface GenerateFormData {
  event_name: string;
  additional_context: string;
  databricks_host: string;
  databricks_token: string;
  genie_space_id: string;
}

export interface SSEEvent {
  type: 'phase_start' | 'phase_progress' | 'phase_done' | 'phase_token' | 'complete' | 'error' | 'ping';
  phase?: 1 | 2 | 3;
  message?: string;
  data?: Record<string, unknown>;
  detail?: string;
}

export interface ApiStatus {
  gemini_configured: boolean;
  databricks_configured: boolean;
  demo_mode: boolean;
  genie_space_id: string;
  databricks_host?: string;
}

export interface SlideProgress {
  slide: number;
  total: number;
  title: string;
}

export interface PPTStreamEvent {
  type: 'slide_done' | 'ppt_complete' | 'ppt_error' | 'ppt_started' | 'ppt_ping';
  slide?: number;
  total?: number;
  title?: string;
  /** Present on ppt_started — cover + content slide count */
  total_slides?: number;
  filename?: string;
  url?: string;
  message?: string;
}

export interface SavedReport {
  id: string;
  event_name: string;
  created_at: string;
  ppt_filename: string | null;
  stats_json: string | null;
}

export interface SavedReportDetail extends SavedReport {
  report_text: string;
  outline: ReportOutline;
  outline_json: string;
  stats: Record<string, unknown>;
}
