import { useState, useRef, useCallback } from 'react';
import type {
  AppStep, PhaseState, QueryProgress,
  ReportOutline, GenerateFormData, SSEEvent,
  SlideProgress, PPTStreamEvent,
} from '../types';
import * as api from '../api/client';

const DEFAULT_PHASE = (): PhaseState => ({ status: 'idle', message: '' });

export function useEventReport() {
  const [step, setStep] = useState<AppStep>('form');
  const [jobId, setJobId] = useState<string | null>(null);
  const [phases, setPhases] = useState<PhaseState[]>([
    DEFAULT_PHASE(), DEFAULT_PHASE(), DEFAULT_PHASE(),
  ]);
  const [questions, setQuestions] = useState<string[]>([]);
  const [queryProgress, setQueryProgress] = useState<QueryProgress[]>([]);
  const [synthesisText, setSynthesisText] = useState('');  // streaming text
  const [report, setReport] = useState<string | null>(null);
  const [outline, setOutline] = useState<ReportOutline | null>(null);
  const [pptUrl, setPptUrl] = useState<string | null>(null);
  const [pptFilename, setPptFilename] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [generatingPPT, setGeneratingPPT] = useState(false);
  const [pptSlides, setPptSlides] = useState<SlideProgress[]>([]);
  /** Event name from the form while pipeline runs (outline not loaded yet). */
  const [activeEventName, setActiveEventName] = useState('');
  const esRef = useRef<EventSource | null>(null);
  const pptEsRef = useRef<EventSource | null>(null);
  // Tracks whether a real pipeline error was already received so we don't
  // overwrite it with the generic "connection lost" message when SSE closes.
  const pipelineErrorRef = useRef(false);
  // Tracks successful completion so we ignore onerror when the server closes
  // the connection right after sending the complete event.
  const pipelineCompleteRef = useRef(false);

  const updatePhase = useCallback(
    (idx: number, patch: Partial<PhaseState>) =>
      setPhases(prev => {
        const next = [...prev];
        next[idx] = { ...next[idx], ...patch };
        return next;
      }),
    []
  );

  const handleSSEEvent = useCallback(
    (evt: SSEEvent) => {
      if (evt.type === 'ping') return;

      if (evt.type === 'complete') {
        pipelineCompleteRef.current = true;
        esRef.current?.close();
        setStep('outline');
        return;
      }

      if (evt.type === 'error') {
        pipelineErrorRef.current = true;
        // Show the real backend error, not the generic connection message
        const msg = evt.message || 'Pipeline error';
        const detail = evt.detail ? `\n\n${evt.detail.split('\n').slice(-3).join('\n')}` : '';
        setError(msg + detail);
        esRef.current?.close();
        return;
      }

      if (!evt.phase) return;
      const idx = evt.phase - 1;

      if (evt.type === 'phase_start') {
        updatePhase(idx, { status: 'running', message: evt.message || '', startedAt: Date.now() });
      }

      if (evt.type === 'phase_progress' && evt.phase === 2) {
        const d = evt.data as unknown as QueryProgress;
        setQueryProgress(prev => {
          const next = [...prev];
          next[d.index] = d;
          return next;
        });
        updatePhase(idx, { message: `${d.completed}/${d.total} queries complete` });
      }

      // Streaming tokens from Phase 3
      if (evt.type === 'phase_token' && evt.phase === 3) {
        const token = (evt.data as { token?: string })?.token ?? '';
        setSynthesisText(prev => prev + token);
      }

      if (evt.type === 'phase_done') {
        updatePhase(idx, { status: 'done', message: evt.message || '', doneAt: Date.now(), data: evt.data });

        if (evt.phase === 1 && evt.data?.questions) {
          setQuestions(evt.data.questions as string[]);
        }
        if (evt.phase === 3 && evt.data) {
          const d = evt.data as { report?: string; outline?: ReportOutline };
          if (d.report) {
            setReport(d.report);
            // Authoritative full text from the server (avoids streamed state lag vs phase_done).
            setSynthesisText(d.report);
          }
          if (d.outline) setOutline(d.outline as ReportOutline);
        }
      }

    },
    [updatePhase]
  );

  const startGeneration = useCallback(async (form: GenerateFormData) => {
    setError(null);
    pipelineErrorRef.current = false;
    pipelineCompleteRef.current = false;
    setActiveEventName((form.event_name || '').trim());
    setStep('generating');
    setPhases([DEFAULT_PHASE(), DEFAULT_PHASE(), DEFAULT_PHASE()]);
    setQuestions([]);
    setQueryProgress([]);
    setSynthesisText('');
    setReport(null);
    setOutline(null);
    setPptUrl(null);
    setPptFilename(null);

    try {
      const { job_id } = await api.startGeneration(form);
      setJobId(job_id);

      const es = api.openStream(job_id);
      esRef.current = es;
      es.onmessage = (e: MessageEvent) => {
        try { handleSSEEvent(JSON.parse(e.data) as SSEEvent); } catch { /* ignore */ }
      };
      es.onerror = () => {
        // Ignore if pipeline completed (server closes connection right after complete event)
        if (pipelineCompleteRef.current) { es.close(); return; }
        // Only show the generic message if no real pipeline error arrived first
        if (!pipelineErrorRef.current) {
          setError('Connection to server lost. Check that the backend is running on port 8000.');
        }
        es.close();
      };
    } catch (err) {
      setActiveEventName('');
      setError(err instanceof Error ? err.message : 'Failed to start');
      setStep('form');
    }
  }, [handleSSEEvent]);

  const generatePPT = useCallback(async (editedOutline: ReportOutline) => {
    if (!jobId) return;
    setGeneratingPPT(true);
    setPptSlides([]);
    setOutline(editedOutline);
    try {
      const { ppt_id } = await api.queuePPT(jobId, editedOutline);
      setStep('ppt-generating');

      const es = api.openPPTStream(ppt_id);
      pptEsRef.current = es;

      es.onmessage = (e: MessageEvent) => {
        try {
          const evt = JSON.parse(e.data) as PPTStreamEvent;
          if (evt.type === 'slide_done') {
            setPptSlides(prev => [...prev, {
              slide: evt.slide!,
              total: evt.total!,
              title: evt.title!,
            }]);
          }
          if (evt.type === 'ppt_complete') {
            setPptFilename(evt.filename!);
            setPptUrl(evt.url ?? null);
            es.close();
            setStep('complete');
            setGeneratingPPT(false);
          }
          if (evt.type === 'ppt_error') {
            setError(evt.message || 'PPT generation failed');
            es.close();
            setStep('outline');
            setGeneratingPPT(false);
          }
        } catch { /* ignore parse errors */ }
      };
      es.onerror = () => {
        setError('PPT stream connection lost');
        es.close();
        setStep('outline');
        setGeneratingPPT(false);
      };
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start PPT generation');
      setStep('outline');
      setGeneratingPPT(false);
    }
  }, [jobId]);

  const loadSavedReport = useCallback(async (reportId: string) => {
    try {
      const data = await api.getReport(reportId);
      setJobId(reportId);
      setActiveEventName((data.event_name || '').trim());
      setReport(data.report_text);
      if (data.outline) setOutline(data.outline);
      if (data.ppt_filename) { setPptFilename(data.ppt_filename); setPptUrl(`/api/download/${data.ppt_filename}`); }
      setStep('outline');
    } catch (err) {
      setError('Could not load saved report');
    }
  }, []);

  const reset = useCallback(() => {
    esRef.current?.close();
    pptEsRef.current?.close();
    pipelineErrorRef.current = false;
    pipelineCompleteRef.current = false;
    setStep('form');
    setJobId(null);
    setPhases([DEFAULT_PHASE(), DEFAULT_PHASE(), DEFAULT_PHASE()]);
    setQuestions([]);
    setQueryProgress([]);
    setSynthesisText('');
    setReport(null);
    setOutline(null);
    setPptUrl(null);
    setPptFilename(null);
    setPptSlides([]);
    setError(null);
    setActiveEventName('');
  }, []);

  const setStepFromRoute = useCallback((nextStep: AppStep) => {
    setStep(prev => (prev === nextStep ? prev : nextStep));
  }, []);

  return {
    step, jobId, phases, questions, queryProgress, synthesisText,
    report, outline, pptUrl, pptFilename, activeEventName,
    error, generatingPPT, pptSlides,
    startGeneration, generatePPT, loadSavedReport, reset, setStepFromRoute,
  };
}
