import { useEffect, useMemo, useState } from 'react';
import { X, ChevronLeft, ChevronRight, MonitorPlay, FileUp, Loader2 } from 'lucide-react';
import type { ReportOutline } from '../types';
import * as api from '../api/client';

interface SlideDeckPreviewProps {
  outline: ReportOutline;
  onClose: () => void;
}

function DataTable({ rows }: { rows: Record<string, string>[] }) {
  if (!rows?.length) return null;
  const cols = Object.keys(rows[0]);
  return (
    <div className="overflow-x-auto rounded-xl border border-brand-border bg-white mb-3">
      <table className="w-full text-xs text-slate-800">
        <thead>
          <tr className="bg-slate-100 border-b border-brand-border">
            {cols.map((c) => (
              <th key={c} className="text-left p-2 font-semibold text-teal-700 whitespace-nowrap">
                {c.replace(/_/g, ' ')}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={i % 2 ? 'bg-slate-50' : 'bg-white'}>
              {cols.map((c) => (
                <td key={c} className="p-2 border-t border-slate-200 align-top">
                  {String(r[c] ?? '')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SlideCanvas({
  title,
  subtitle,
  points,
  insight,
  tableData,
  slideNumber,
  total,
}: {
  title: string;
  subtitle?: string;
  points: string[];
  insight?: string;
  tableData?: Record<string, string>[] | null;
  slideNumber: number;
  total: number;
}) {
  const hasBullets = (points?.length ?? 0) > 0;

  return (
    <div className="w-full aspect-[16/9] bg-white border border-brand-border rounded-2xl overflow-hidden shadow-sm">
      <div className="h-1 bg-brand-red" />
      <div className="flex items-center justify-between px-6 py-3 border-b border-brand-border bg-slate-50">
        <h3 className="text-slate-900 font-semibold text-lg truncate">{title}</h3>
        <span className="text-xs text-brand-dgray font-mono">
          {slideNumber} / {total}
        </span>
      </div>

      <div className="px-6 py-4 h-[calc(100%-4.5rem)] flex flex-col gap-3 min-h-0">
        {subtitle && <p className="text-xs text-brand-dgray">{subtitle}</p>}

        <div className="flex-1 min-h-0 overflow-y-auto flex flex-col gap-3">
          {tableData && tableData.length > 0 && <DataTable rows={tableData} />}

          {hasBullets && (
            <div className="bg-slate-50 rounded-xl border border-brand-border p-4">
              <div className="space-y-2">
                {points.slice(0, 8).map((pt, idx) => (
                  <div key={idx} className="flex items-start gap-2">
                    <span className="w-1.5 h-1.5 mt-2 rounded-full bg-brand-red flex-shrink-0" />
                    <span className="text-sm text-slate-700 leading-relaxed">{pt}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Matches ppt_service _insight: yellow panel + KEY INSIGHT label */}
          <div className="rounded-xl bg-amber-50 flex-shrink-0 border border-amber-300 border-l-4 border-l-amber-500 px-4 py-3">
            <p className="text-xs uppercase tracking-wide text-amber-900 font-semibold">Key Insight</p>
            <p className="text-sm text-slate-900 mt-1.5 leading-relaxed">
              {insight?.trim() ||
                '[Data Not Available] Insight is not available for this slide.'}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function SlideDeckPreview({ outline, onClose }: SlideDeckPreviewProps) {
  const [activeIdx, setActiveIdx] = useState(0);
  const [displayOutline, setDisplayOutline] = useState<ReportOutline | null>(null);
  const [loading, setLoading] = useState(true);
  const [fallback, setFallback] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setFallback(false);
    setActiveIdx(0);
    api
      .getPptPreviewOutline(outline)
      .then((normalized) => {
        if (!cancelled) {
          setDisplayOutline(normalized);
          setLoading(false);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setDisplayOutline(outline);
          setFallback(true);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [outline]);

  const slides = displayOutline?.slides ?? [];
  const active = useMemo(() => slides[activeIdx], [slides, activeIdx]);
  const total = slides.length;

  const prev = () => setActiveIdx((v) => Math.max(0, v - 1));
  const next = () => setActiveIdx((v) => Math.min(total - 1, v + 1));

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/35 backdrop-blur-sm p-5">
      <div className="max-w-7xl mx-auto h-full bg-white rounded-2xl border border-brand-border shadow-xl flex flex-col">
        <div className="px-5 py-3 border-b border-brand-border flex items-center justify-between">
          <div className="flex items-center gap-2">
            <MonitorPlay className="w-5 h-5 text-brand-blue" />
            <h2 className="text-slate-900 font-semibold">Slideshow Preview</h2>
            {loading && <Loader2 className="w-4 h-4 animate-spin text-brand-dgray" />}
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg border border-brand-border hover:bg-slate-50 text-brand-dgray hover:text-slate-900"
          >
            <X className="w-4.5 h-4.5" />
          </button>
        </div>

        {fallback && (
          <div className="px-5 py-2 text-xs text-amber-900 bg-amber-50 border-b border-amber-200">
            Could not align preview with the export pipeline (backend unreachable). Showing raw outline text.
          </div>
        )}

        <div className="flex-1 min-h-0 grid grid-cols-[220px_1fr] gap-0">
          <div className="border-r border-brand-border p-3 overflow-y-auto">
            <p className="text-xs text-brand-dgray font-medium uppercase tracking-wide mb-2">Slides</p>
            <div className="space-y-1.5">
              {slides.map((s, idx) => (
                <button
                  key={s.id}
                  onClick={() => setActiveIdx(idx)}
                  className={`w-full text-left rounded-lg border px-3 py-2 transition-all ${
                    idx === activeIdx
                      ? 'border-brand-blue/50 bg-blue-50'
                      : 'border-brand-border hover:border-brand-blue/30 hover:bg-slate-50'
                  }`}
                >
                  <p className="text-[11px] text-brand-dgray font-mono">Slide {s.number}</p>
                  <p className="text-xs text-slate-800 truncate mt-0.5">{s.title}</p>
                </button>
              ))}
            </div>
          </div>

          <div className="p-4 flex flex-col gap-3 min-h-0">
            {loading || !active ? (
              <div className="flex items-center justify-center aspect-[16/9] border border-dashed border-brand-border rounded-2xl text-brand-dgray text-sm">
                Loading preview…
              </div>
            ) : (
              <SlideCanvas
                title={active.title}
                subtitle={active.subtitle}
                points={active.points ?? []}
                insight={active.insight}
                tableData={active.table_data as Record<string, string>[] | null | undefined}
                slideNumber={active.number}
                total={total}
              />
            )}

            <div className="flex items-center justify-between">
              <button
                onClick={prev}
                disabled={activeIdx === 0 || loading}
                className="inline-flex items-center gap-1.5 px-3 py-2 text-sm border border-brand-border rounded-lg text-brand-dgray hover:text-slate-900 hover:bg-slate-50 disabled:opacity-40"
              >
                <ChevronLeft className="w-4 h-4" />
                Previous
              </button>
              <button
                onClick={next}
                disabled={activeIdx >= total - 1 || loading}
                className="inline-flex items-center gap-1.5 px-3 py-2 text-sm border border-brand-border rounded-lg text-brand-dgray hover:text-slate-900 hover:bg-slate-50 disabled:opacity-40"
              >
                Next
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        </div>

        <div className="px-5 py-3 border-t border-brand-border bg-slate-50 text-xs text-brand-dgray flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <FileUp className="w-3.5 h-3.5 flex-shrink-0" />
            <span>
              Preview uses the same text rules as the downloaded PPTX (including funnel summaries and
              tables promoted from pipe-separated bullets).
            </span>
          </div>
          <span className="text-[11px] text-slate-500 pl-5">
            Exported PPTX is editable and can be imported into Google Slides for further editing.
          </span>
        </div>
      </div>
    </div>
  );
}
