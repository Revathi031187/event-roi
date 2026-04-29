import { useState, useEffect } from 'react';
import { Download, BarChart3, RefreshCw, Clock, MonitorPlay, FileUp } from 'lucide-react';
import Header from '../components/Header';
import EventForm from '../components/EventForm';
import PipelineProgress from '../components/PipelineProgress';
import OutlineEditor from '../components/OutlineEditor';
import ReportViewer from '../components/ReportViewer';
import ReportHistory from '../components/ReportHistory';
import PPTProgress from '../components/PPTProgress';
import SlideDeckPreview from '../components/SlideDeckPreview';
import { useEventReport } from '../hooks/useEventReport';
import { checkStatus } from '../api/client';
import type { ApiStatus } from '../types';

export default function Dashboard() {
  const FALLBACK_STATUS: ApiStatus = {
    gemini_configured: false,
    databricks_configured: false,
    demo_mode: true,
    genie_space_id: '',
    databricks_host: '',
  };
  const [apiStatus, setApiStatus] = useState<ApiStatus | null>(null);
  const [showReport, setShowReport] = useState(false);
  const [showSlideshow, setShowSlideshow] = useState(false);
  const [showSlidesExportHelp, setShowSlidesExportHelp] = useState(false);
  const [historyRefresh, setHistoryRefresh] = useState(0);

  const {
    step, phases, questions, queryProgress, synthesisText,
    report, outline, pptUrl, pptFilename, activeEventName,
    error, generatingPPT, pptSlides,
    startGeneration, generatePPT, loadSavedReport, reset,
  } = useEventReport();

  useEffect(() => {
    let active = true;

    const loadStatus = async (attempt = 0) => {
      try {
        const status = await checkStatus();
        if (active) setApiStatus(status);
      } catch {
        // During backend reload, this can fail once; retry briefly then fall back.
        if (attempt < 1) {
          setTimeout(() => {
            void loadStatus(attempt + 1);
          }, 800);
          return;
        }
        if (active) setApiStatus(FALLBACK_STATUS);
      }
    };

    void loadStatus();
    return () => {
      active = false;
    };
  }, []);

  // Refresh history when a new report is complete
  useEffect(() => {
    if (step === 'complete') setHistoryRefresh(n => n + 1);
  }, [step]);

  const eventName = (outline?.event_name || activeEventName || '').trim();

  const savePptWithPicker = async () => {
    if (!pptUrl) return;

    const defaultName = (pptFilename && pptFilename.endsWith('.pptx'))
      ? pptFilename
      : `${(eventName || 'event-report').replace(/[^\w\- ]/g, '').trim().replace(/\s+/g, '_') || 'event-report'}.pptx`;

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

      // Preferred path: ask user for filename and save location.
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

      // Fallback: browser-managed download.
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = defaultName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      // User cancel should be silent.
      if (err instanceof DOMException && err.name === 'AbortError') return;
      console.error('PPT save failed', err);
    }
  };

  return (
    <div className="min-h-screen bg-brand-bg text-slate-900">
      <Header onReset={reset} showReset={step !== 'form'} />

      {/* Background glow */}
      <div className="fixed inset-0 pointer-events-none overflow-hidden">
        <div className="absolute -top-40 -right-40 w-96 h-96 bg-brand-blue/5 rounded-full blur-3xl" />
        <div className="absolute -bottom-40 -left-40 w-96 h-96 bg-brand-red/5 rounded-full blur-3xl" />
      </div>

      <main className="relative max-w-5xl mx-auto px-6 py-12">

        {/* ── FORM ─────────────────────────────────────────────────────────── */}
        {step === 'form' && (
          <>
            <EventForm onSubmit={startGeneration} status={apiStatus} />
            {/* History */}
            <div className="mt-10 bg-brand-surface border border-brand-border rounded-2xl p-6">
              <ReportHistory
                onOpen={loadSavedReport}
                refreshKey={historyRefresh}
              />
            </div>
          </>
        )}

        {/* ── GENERATING ───────────────────────────────────────────────────── */}
        {step === 'generating' && (
          <PipelineProgress
            phases={phases}
            questions={questions}
            queryProgress={queryProgress}
            synthesisText={synthesisText}
            eventName={eventName}
            error={error}
          />
        )}

        {/* ── PPT GENERATING ───────────────────────────────────────────────── */}
        {step === 'ppt-generating' && outline && (
          <PPTProgress
            completedSlides={pptSlides}
            totalSlides={(outline.slides.length ?? 0) + 1}
            eventName={outline.event_name}
          />
        )}

        {/* ── OUTLINE EDITOR ───────────────────────────────────────────────── */}
        {step === 'outline' && outline && (
          <>
            <OutlineEditor
              outline={outline}
              onGenerate={generatePPT}
              onViewReport={() => setShowReport(true)}
              generating={generatingPPT}
            />
            {showReport && report && (
              <ReportViewer
                report={report}
                outline={outline}
                streamedText={synthesisText}
                onClose={() => setShowReport(false)}
              />
            )}
          </>
        )}

        {/* ── COMPLETE ─────────────────────────────────────────────────────── */}
        {step === 'complete' && (
          <div className="animate-slide-up max-w-xl mx-auto text-center">
            <div className="w-20 h-20 mx-auto mb-6 rounded-full bg-brand-green/10 border border-brand-green/30
                            flex items-center justify-center">
              <BarChart3 className="w-10 h-10 text-brand-green" />
            </div>
            <h2 className="text-3xl font-bold text-slate-900 mb-2">Deck Ready</h2>
            <p className="text-brand-dgray mb-8">
              Your {outline?.slides.length ?? 7}-slide report for{' '}
              <strong className="text-slate-900">{eventName}</strong> is ready to download.
            </p>

            {/* Download cards */}
            <div className="space-y-3 mb-6">
              {pptFilename && (
                <div className="bg-brand-surface border border-brand-border rounded-2xl p-5 text-left">
                  <div className="flex items-center gap-4">
                    <div className="p-3 rounded-xl bg-brand-red/10 border border-brand-red/20 flex-shrink-0">
                      <BarChart3 className="w-5 h-5 text-brand-red" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-slate-900 font-medium truncate">{pptFilename}</p>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="text-brand-dgray text-xs">{outline?.slides.length ?? 7} slides</span>
                        <span className="text-brand-dgray text-xs flex items-center gap-1"><Clock className="w-3 h-3" /> Just now</span>
                      </div>
                    </div>
                    <button
                      onClick={savePptWithPicker}
                      className="flex items-center gap-2 px-4 py-2 rounded-xl font-semibold text-white text-sm
                                 bg-gradient-to-r from-brand-red to-orange-500 hover:from-red-600 hover:to-orange-600
                                 transition-all shadow-lg shadow-brand-red/20 flex-shrink-0">
                      <Download className="w-4 h-4" /> PPT
                    </button>
                  </div>
                  <div className="mt-3 flex items-center gap-2">
                    <button
                      onClick={() => setShowSlideshow(true)}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-brand-border text-brand-blue hover:bg-blue-50 transition-all"
                    >
                      <MonitorPlay className="w-3.5 h-3.5" />
                      Preview Slideshow
                    </button>
                    <button
                      onClick={() => setShowSlidesExportHelp(true)}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs rounded-lg border border-brand-border text-brand-dgray hover:text-slate-900 hover:bg-slate-50 transition-all"
                    >
                      <FileUp className="w-3.5 h-3.5" />
                      Export to Slides
                    </button>
                  </div>
                </div>
              )}

            </div>

            <div className="flex gap-3 justify-center">
              {outline && (
                <button
                  onClick={() => setShowSlideshow(true)}
                  className="flex items-center gap-2 px-4 py-2 rounded-xl border border-brand-border
                           text-brand-dgray hover:text-slate-900 hover:border-brand-blue/50 text-sm transition-all"
                >
                  <MonitorPlay className="w-4 h-4" />
                  Full Slideshow Preview
                </button>
              )}
              <button onClick={() => setShowReport(true)}
                className="flex items-center gap-2 px-4 py-2 rounded-xl border border-brand-border
                           text-brand-dgray hover:text-slate-900 hover:border-brand-blue/50 text-sm transition-all">
                View Full Report
              </button>
              <button onClick={reset}
                className="flex items-center gap-2 px-4 py-2 rounded-xl border border-brand-border
                           text-brand-dgray hover:text-slate-900 hover:border-brand-blue/50 text-sm transition-all">
                <RefreshCw className="w-4 h-4" /> New Report
              </button>
            </div>

            {showReport && report && (
              <ReportViewer
                report={report}
                outline={outline}
                streamedText={synthesisText}
                onClose={() => setShowReport(false)}
              />
            )}
            {showSlideshow && outline && (
              <SlideDeckPreview outline={outline} onClose={() => setShowSlideshow(false)} />
            )}
            {showSlidesExportHelp && (
              <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/35 backdrop-blur-sm">
                <div className="w-full max-w-lg bg-white border border-brand-border rounded-2xl shadow-xl">
                  <div className="px-5 py-4 border-b border-brand-border flex items-center justify-between">
                    <h3 className="text-slate-900 font-semibold">Export to Google Slides</h3>
                    <button
                      onClick={() => setShowSlidesExportHelp(false)}
                      className="text-brand-dgray hover:text-slate-900 text-sm"
                    >
                      Close
                    </button>
                  </div>
                  <div className="px-5 py-4 text-sm text-slate-700 space-y-3">
                    <p>
                      Google Slides import requires selecting the PPTX file in Google Slides.
                      Use the actions below.
                    </p>
                    <ol className="list-decimal ml-5 space-y-1">
                      <li>Download the generated PPTX file.</li>
                      <li>Open Google Slides in a new tab.</li>
                      <li>Use <strong>File → Import slides</strong> and upload the PPTX.</li>
                    </ol>
                  </div>
                  <div className="px-5 py-4 border-t border-brand-border flex items-center gap-2 justify-end">
                    <a
                      href={pptUrl ?? '#'}
                      onClick={e => {
                        e.preventDefault();
                        void savePptWithPicker();
                      }}
                      className="inline-flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg bg-gradient-to-r from-brand-red to-orange-500 text-white hover:from-red-600 hover:to-orange-600 transition-all"
                    >
                      <Download className="w-4 h-4" />
                      Download PPTX
                    </a>
                    <a
                      href="https://docs.google.com/presentation/u/0/"
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg border border-brand-border text-brand-blue hover:bg-blue-50 transition-all"
                    >
                      <FileUp className="w-4 h-4" />
                      Open Google Slides
                    </a>
                    <a
                      href="https://drive.google.com/drive/my-drive"
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1.5 px-3 py-2 text-sm rounded-lg border border-brand-border text-brand-dgray hover:text-slate-900 hover:bg-slate-50 transition-all"
                    >
                      <FileUp className="w-4 h-4" />
                      Open Google Drive
                    </a>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
