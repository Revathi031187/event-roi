import { useEffect, useState } from 'react';
import { Clock, Download, Trash2, FolderOpen, RefreshCw, FileText } from 'lucide-react';
import { listReports, deleteReport, downloadUrl } from '../api/client';
import type { SavedReport } from '../types';

interface ReportHistoryProps {
  onOpen: (id: string) => void;
  refreshKey?: number;
}

function formatDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat('en-US', {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit',
    }).format(new Date(iso + 'Z'));
  } catch {
    return iso.slice(0, 16).replace('T', ' ');
  }
}

export default function ReportHistory({ onOpen, refreshKey }: ReportHistoryProps) {
  const [reports, setReports] = useState<SavedReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [deleting, setDeleting] = useState<string | null>(null);

  const savePptWithPicker = async (filename: string, eventName: string) => {
    const pptUrl = downloadUrl(filename);
    const safeEvent = (eventName || 'event-report')
      .replace(/[^\w\- ]/g, '')
      .trim()
      .replace(/\s+/g, '_');
    const defaultName = filename?.endsWith('.pptx')
      ? filename
      : `${safeEvent || 'event-report'}.pptx`;

    try {
      const res = await fetch(pptUrl);
      if (!res.ok) throw new Error('Could not download PPT file');
      const blob = await res.blob();

      const picker = (window as Window & {
        showSaveFilePicker?: (opts?: {
          suggestedName?: string;
          types?: Array<{ description?: string; accept: Record<string, string[]> }>;
        }) => Promise<{
          createWritable: () => Promise<{
            write: (data: Blob) => Promise<void>;
            close: () => Promise<void>;
          }>;
        }>;
      }).showSaveFilePicker;

      if (picker) {
        const handle = await picker({
          suggestedName: defaultName,
          types: [
            {
              description: 'PowerPoint Presentation',
              accept: { 'application/vnd.openxmlformats-officedocument.presentationml.presentation': ['.pptx'] },
            },
          ],
        });
        const writable = await handle.createWritable();
        await writable.write(blob);
        await writable.close();
        return;
      }

      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = defaultName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      if (err instanceof DOMException && err.name === 'AbortError') return;
      console.error('PPT save failed', err);
    }
  };

  const load = () => {
    setLoading(true);
    listReports().then(setReports).finally(() => setLoading(false));
  };

  useEffect(load, [refreshKey]);

  const handleDelete = async (id: string, e: React.MouseEvent) => {
    e.stopPropagation();
    setDeleting(id);
    await deleteReport(id).catch(() => null);
    setReports(prev => prev.filter(r => r.id !== id));
    setDeleting(null);
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-brand-dgray text-sm py-4 justify-center">
        <RefreshCw className="w-3.5 h-3.5 animate-spin" /> Loading history…
      </div>
    );
  }

  if (reports.length === 0) {
    return (
      <div className="text-center py-6 text-brand-dgray text-sm">
        <FileText className="w-8 h-8 mx-auto mb-2 opacity-30" />
        No saved reports yet. Generate your first report above.
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <span className="text-brand-lgray text-sm font-medium flex items-center gap-1.5">
          <Clock className="w-3.5 h-3.5" /> Recent Reports
        </span>
        <button onClick={load} className="text-brand-dgray hover:text-slate-900 transition-colors">
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="space-y-2">
        {reports.map(r => (
          <div
            key={r.id}
            className="group flex items-center gap-3 bg-brand-card border border-brand-border
                       rounded-xl px-4 py-3 hover:border-brand-blue/40 hover:bg-slate-50 transition-all cursor-pointer"
            onClick={() => onOpen(r.id)}
          >
            <div className="flex-1 min-w-0">
              <p className="text-slate-900 text-sm font-medium truncate">{r.event_name}</p>
              <p className="text-brand-dgray text-xs mt-0.5">{formatDate(r.created_at)}</p>
            </div>

            {/* Download badges */}
            <div className="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition-opacity">
              {r.ppt_filename && (
                <a
                  href={downloadUrl(r.ppt_filename)}
                  onClick={e => {
                    e.preventDefault();
                    e.stopPropagation();
                    void savePptWithPicker(r.ppt_filename!, r.event_name);
                  }}
                  className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg bg-brand-red/10
                             text-brand-red border border-brand-red/20 hover:bg-brand-red/20 transition-all"
                  title="Download PPT"
                >
                  <Download className="w-3 h-3" /> PPT
                </a>
              )}
              <button
                onClick={e => handleDelete(r.id, e)}
                disabled={deleting === r.id}
                className="p-1.5 rounded-lg text-brand-dgray hover:text-brand-red
                           hover:bg-brand-red/10 transition-all disabled:opacity-40"
                title="Delete report"
              >
                <Trash2 className="w-3.5 h-3.5" />
              </button>
            </div>

            <FolderOpen className="w-4 h-4 text-brand-dgray opacity-0 group-hover:opacity-100 flex-shrink-0 transition-opacity" />
          </div>
        ))}
      </div>
    </div>
  );
}
