import type { GenerateFormData, ReportOutline, SavedReport, SavedReportDetail } from '../types';

const BASE = '/api';

export async function checkStatus() {
  const res = await fetch(`${BASE}/generate/status`);
  if (!res.ok) throw new Error('Backend not reachable');
  return res.json();
}

export async function startGeneration(form: GenerateFormData): Promise<{ job_id: string }> {
  const res = await fetch(`${BASE}/generate/start`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      event_name: form.event_name,
      additional_context: form.additional_context,
      databricks_host: form.databricks_host || undefined,
      databricks_token: form.databricks_token || undefined,
      genie_space_id: form.genie_space_id || undefined,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || 'Failed to start generation');
  }
  return res.json();
}

export function openStream(jobId: string): EventSource {
  return new EventSource(`${BASE}/generate/stream/${jobId}`);
}

export async function generatePPT(
  jobId: string,
  outline: ReportOutline
): Promise<{ filename: string; url: string }> {
  const res = await fetch(`${BASE}/generate/generate-ppt`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId, event_name: outline.event_name, outline }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || 'PPT generation failed');
  }
  return res.json();
}

export async function queuePPT(
  jobId: string,
  outline: ReportOutline
): Promise<{ ppt_id: string }> {
  const res = await fetch(`${BASE}/generate/queue-ppt`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ job_id: jobId, event_name: outline.event_name, outline }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || 'Failed to queue PPT');
  }
  return res.json();
}

export function openPPTStream(pptId: string): EventSource {
  return new EventSource(`${BASE}/generate/ppt-stream/${pptId}`);
}

export function downloadUrl(filename: string): string {
  return `${BASE}/download/${filename}`;
}

/** Same outline transforms as server-side PPTX (tables, funnel summaries, number formatting). */
export async function getPptPreviewOutline(outline: ReportOutline): Promise<ReportOutline> {
  const res = await fetch(`${BASE}/generate/ppt-preview-outline`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(outline),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error((err as { detail?: string }).detail || 'Preview normalization failed');
  }
  return res.json();
}

// ── Report history ────────────────────────────────────────────────────────────

export async function listReports(): Promise<SavedReport[]> {
  const res = await fetch(`${BASE}/generate/reports`);
  if (!res.ok) return [];
  return res.json();
}

export async function getReport(id: string): Promise<SavedReportDetail> {
  const res = await fetch(`${BASE}/generate/reports/${id}`);
  if (!res.ok) throw new Error('Report not found');
  return res.json();
}

export async function deleteReport(id: string): Promise<void> {
  await fetch(`${BASE}/generate/reports/${id}`, { method: 'DELETE' });
}
