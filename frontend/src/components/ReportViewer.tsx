import { useState } from 'react';
import ReactMarkdown from 'react-markdown';
import { X, Copy, Check } from 'lucide-react';
import type { ReportOutline } from '../types';

interface ReportViewerProps {
  report: string;
  outline?: ReportOutline | null;
  onClose: () => void;
  /** Live-streamed synthesis from SSE; if longer or has more slide sections than `report`, it wins */
  streamedText?: string | null;
}

function looksMalformedReport(text: string): boolean {
  if (!text || text.trim().length < 20) return true;
  const compact = text.replace(/\s+/g, '');
  if (/^(\+1)+\+?$/.test(compact)) return true;
  // Trust real markdown from the synthesizer: do not replace with outline-only (loses tables, metrics, Data Gaps)
  if (text.length > 80 && /##\s+Slide\s*\d/i.test(text)) return false;
  const alphaCount = (text.match(/[A-Za-z]/g) || []).length;
  if (text.length > 300) return false;
  return alphaCount < 20;
}

function tableMarkdownFromRows(rows: Record<string, string>[]): string {
  if (!rows.length) return '';
  const keys = Object.keys(rows[0]);
  const header = `| ${keys.join(' | ')} |`;
  const sep = `| ${keys.map(() => '---').join(' | ')} |`;
  const body = rows.map((r) => `| ${keys.map((k) => (r[k] ?? '').toString().replace(/\|/g, '\\|')).join(' | ')} |`).join('\n');
  return [header, sep, body].join('\n');
}

function markdownFromOutline(outline: ReportOutline): string {
  const blocks: string[] = [`# ${outline.event_name} Report`];
  for (const slide of outline.slides) {
    blocks.push(`## Slide ${slide.number}: ${slide.title}`);
    if (slide.subtitle) blocks.push(slide.subtitle);
    for (const p of slide.points || []) blocks.push(`- ${p}`);
    if (slide.table_data?.length) {
      blocks.push(tableMarkdownFromRows(slide.table_data as Record<string, string>[]));
    }
    if (slide.insight) {
      blocks.push('### Key Insight');
      blocks.push(slide.insight);
    }
  }
  return blocks.join('\n\n');
}

function countSlideHeaders(text: string): number {
  const m = text.match(/##\s+Slide\s+(\d+)/gi);
  return m ? m.length : 0;
}

function pickBestReportText(report: string, streamed?: string | null): string {
  const r = (report || '').trim();
  const s = (streamed || '').trim();
  if (!r) return s;
  if (!s) return r;
  const rN = countSlideHeaders(r);
  const sN = countSlideHeaders(s);
  // Prefer more slide sections (complete deck).
  if (sN > rN) return s;
  if (rN > sN) return r;
  // Same structure: longer wins (more bullets/tables per slide); tie-break to saved report.
  if (r.length >= s.length) return r;
  return s;
}

export default function ReportViewer({
  report,
  outline,
  onClose,
  streamedText,
}: ReportViewerProps) {
  const [copied, setCopied] = useState(false);
  const primary = pickBestReportText(report, streamedText);
  const displayReport = looksMalformedReport(primary) && outline ? markdownFromOutline(outline) : primary;
  const slideSections = countSlideHeaders(displayReport);
  const incomplete = slideSections > 0 && slideSections < 7;

  const copyReport = () => {
    navigator.clipboard.writeText(displayReport).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/35 backdrop-blur-sm">
      <div className="w-full max-w-4xl max-h-[90vh] flex flex-col bg-brand-surface border border-brand-border rounded-2xl shadow-xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-brand-border flex-shrink-0">
          <h2 className="text-slate-900 font-semibold text-lg">Full Report</h2>
          <div className="flex items-center gap-3">
            <button
              onClick={copyReport}
              className="flex items-center gap-1.5 text-sm text-brand-dgray hover:text-slate-900
                         border border-brand-border hover:border-brand-blue/50 px-3 py-1.5 rounded-lg transition-all"
            >
              {copied ? (
                <><Check className="w-3.5 h-3.5 text-brand-green" /> Copied!</>
              ) : (
                <><Copy className="w-3.5 h-3.5" /> Copy Markdown</>
              )}
            </button>
            <button
              onClick={onClose}
              className="text-brand-dgray hover:text-slate-900 p-1.5 rounded-lg hover:bg-slate-100 transition-all"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto overflow-x-auto px-8 py-6">
          {incomplete && (
            <p className="mb-4 text-sm text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
              This synthesis lists {slideSections} slide section{slideSections === 1 ? '' : 's'} in markdown;
              the model may have truncated before Slide 7. Try regenerating or check backend logs. The slide deck
              outline still includes seven structured slides.
            </p>
          )}
          <div className="prose prose-sm max-w-none break-words whitespace-pre-wrap
                          prose-headings:text-slate-900 prose-headings:font-bold
                          prose-h1:text-2xl prose-h2:text-xl prose-h2:border-b prose-h2:border-brand-border prose-h2:pb-2
                          prose-h3:text-base prose-h3:text-brand-blue
                          prose-p:text-slate-700 prose-p:leading-relaxed
                          prose-li:text-slate-700
                          prose-strong:text-slate-900
                          prose-code:text-brand-blue prose-code:bg-slate-100 prose-code:px-1 prose-code:rounded
                          prose-table:border-collapse
                          prose-th:bg-slate-100 prose-th:text-slate-900 prose-th:font-semibold
                          prose-td:text-slate-700 prose-td:border prose-td:border-brand-border
                          prose-hr:border-brand-border">
            <ReactMarkdown>{displayReport}</ReactMarkdown>
          </div>
        </div>
      </div>
    </div>
  );
}
