import { useState } from 'react';
import { CheckCircle2, Loader2, XCircle, Database, Brain, Sparkles, ChevronDown, ChevronUp } from 'lucide-react';
import type { PhaseState, QueryProgress } from '../types';

interface PipelineProgressProps {
  phases: PhaseState[];
  questions: string[];
  queryProgress: QueryProgress[];
  synthesisText: string;
  eventName: string;
  error: string | null;
}

const PHASE_META = [
  { icon: Brain,    label: 'Phase 1 · Plan',         desc: 'Discovers data schema, then Gemini generates targeted queries', color: 'brand-blue'  },
  { icon: Database, label: 'Phase 2 · Batch Query',   desc: 'Runs all queries in parallel against Databricks Genie',       color: 'brand-amber' },
  { icon: Sparkles, label: 'Phase 3 · Synthesize',    desc: 'Gemini synthesizes all data into a structured report',        color: 'brand-green' },
];

function elapsed(phase: PhaseState): string {
  if (phase.status === 'idle') return '';
  const secs = Math.round(((phase.doneAt ?? Date.now()) - (phase.startedAt ?? Date.now())) / 1000);
  return phase.status === 'running' ? `${secs}s…` : `${secs}s`;
}

function StageNode({
  status,
  title,
  subtitle,
}: {
  status: PhaseState['status'];
  title: string;
  subtitle: string;
}) {
  return (
    <div className="flex flex-col items-center min-w-[170px] text-center">
      <div className="relative w-12 h-12 flex items-center justify-center">
        {status === 'running' && (
          <>
            <span className="absolute inset-0 rounded-full border-2 border-brand-blue/30 animate-ping" />
            <span className="absolute inset-[3px] rounded-full border-2 border-brand-blue border-t-transparent animate-spin" />
          </>
        )}

        {status === 'done' && (
          <span className="w-10 h-10 rounded-full bg-brand-green/15 border border-brand-green/30 flex items-center justify-center">
            <CheckCircle2 className="w-5 h-5 text-brand-green" />
          </span>
        )}

        {status === 'running' && (
          <span className="w-10 h-10 rounded-full bg-brand-blue/10 border border-brand-blue/30 flex items-center justify-center">
            <Loader2 className="w-4.5 h-4.5 text-brand-blue animate-spin" />
          </span>
        )}

        {status === 'error' && (
          <span className="w-10 h-10 rounded-full bg-brand-red/10 border border-brand-red/30 flex items-center justify-center">
            <XCircle className="w-5 h-5 text-brand-red" />
          </span>
        )}

        {status === 'idle' && (
          <span className="w-10 h-10 rounded-full bg-slate-100 border border-brand-border" />
        )}
      </div>
      <p className="mt-2 text-sm font-semibold text-slate-900">{title}</p>
      <p className="text-xs text-brand-dgray">{subtitle}</p>
    </div>
  );
}

export default function PipelineProgress({
  phases, questions, queryProgress, synthesisText, eventName, error,
}: PipelineProgressProps) {
  const totalDone = phases.filter(p => p.status === 'done').length;
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});

  const toggleExpanded = (idx: number) => {
    setExpanded(prev => ({ ...prev, [idx]: !prev[idx] }));
  };

  return (
    <div className="animate-slide-up max-w-5xl mx-auto">
      {/* Header */}
      <div className="text-center mb-6">
        <p className="text-brand-dgray text-sm mb-1">Generating report for</p>
        <h2 className="text-4xl font-bold text-slate-900">
          {eventName.trim() || 'Event report'}
        </h2>
        <div className="mt-4 h-2 bg-slate-200 rounded-full overflow-hidden max-w-2xl mx-auto">
          <div
            className="h-full bg-gradient-to-r from-brand-red to-brand-blue transition-all duration-700"
            style={{ width: `${(totalDone / 3) * 100}%` }}
          />
        </div>
        <p className="text-brand-lgray text-xs mt-2">{totalDone} of 3 phases complete</p>
      </div>

      {/* Horizontal pipeline */}
      <div className="bg-white border border-brand-border rounded-2xl p-6 mb-6">
        <div className="flex items-center">
          <StageNode status={phases[0]?.status ?? 'idle'} title="Plan" subtitle={elapsed(phases[0] ?? { status: 'idle', message: '' })} />
          <div className="flex-1 h-1 bg-slate-200 mx-3 rounded-full" />
          <StageNode status={phases[1]?.status ?? 'idle'} title="Batch Query" subtitle={elapsed(phases[1] ?? { status: 'idle', message: '' })} />
          <div className="flex-1 h-1 bg-slate-200 mx-3 rounded-full" />
          <StageNode status={phases[2]?.status ?? 'idle'} title="Synthesize" subtitle={elapsed(phases[2] ?? { status: 'idle', message: '' })} />
        </div>
      </div>

      {/* Per-phase execution panels with expandable results */}
      <div className="space-y-4">
        {PHASE_META.map((meta, i) => {
          const phase = phases[i];
          const isActive = phase.status === 'running';
          const isDone   = phase.status === 'done';
          const isError  = phase.status === 'error';
          const Icon = meta.icon;
          const hasPhaseResults = (
            (i === 0 && questions.length > 0) ||
            (i === 1 && queryProgress.length > 0) ||
            (i === 2 && synthesisText.trim().length > 0)
          );
          const isExpanded = !!expanded[i];

          return (
            <div
              key={i}
              className={`border rounded-2xl p-5 transition-all duration-300 ${
                isActive ? 'border-brand-blue/40 bg-blue-50 shadow-sm'
                : isDone  ? 'border-brand-green/30 bg-brand-surface'
                : isError ? 'border-brand-red/30 bg-brand-surface'
                :          'border-brand-border  bg-brand-surface'
              }`}
            >
              {/* Phase header row */}
              <div className="flex items-start gap-3">
                <div className={`p-2 rounded-lg ${isActive ? 'bg-brand-blue/20' : isDone ? 'bg-brand-green/10' : 'bg-brand-border/20'}`}>
                  <Icon className={`w-4 h-4 ${isActive ? 'text-brand-blue' : isDone ? 'text-brand-green' : 'text-brand-dgray'}`} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-slate-900 font-semibold text-sm">{meta.label}</span>
                    {phase.status !== 'idle' && (
                      <span className="text-brand-dgray text-xs">{elapsed(phase)}</span>
                    )}
                  </div>
                  <p className="text-brand-dgray text-xs mt-0.5">{meta.desc}</p>
                </div>

                <div className="flex flex-col items-end gap-2">
                  {phase.message && phase.status !== 'idle' && (
                    <p className={`text-xs ${phase.status === 'error' ? 'text-brand-red' : 'text-brand-dgray'}`}>
                      {phase.message}
                    </p>
                  )}
                  {hasPhaseResults && (
                    <button
                      onClick={() => toggleExpanded(i)}
                      className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg border border-brand-border text-brand-blue hover:bg-blue-50 transition-all"
                    >
                      {isExpanded ? (
                        <>
                          Hide Result
                          <ChevronUp className="w-3.5 h-3.5" />
                        </>
                      ) : (
                        <>
                          View Result
                          <ChevronDown className="w-3.5 h-3.5" />
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>

              {/* Expanded content: independent per phase */}
              {isExpanded && hasPhaseResults && (
                <div className="mt-4 pt-4 border-t border-brand-border">
                  {/* Phase 1 — planned questions */}
                  {i === 0 && questions.length > 0 && (
                    <div className="space-y-2">
                      {questions.map((q, qi) => (
                        <div key={qi} className="flex items-start gap-2 bg-white border border-brand-border rounded-xl px-3 py-2">
                          <span className="text-brand-blue text-xs font-mono mt-0.5 flex-shrink-0">Q{qi + 1}</span>
                          <span className="text-slate-700 text-xs leading-relaxed">{q}</span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Phase 2 — per-query progress */}
                  {i === 1 && questions.length > 0 && (
                    <div className="space-y-2 max-h-64 overflow-y-auto pr-1">
                      {questions.map((q, qi) => {
                        const prog = queryProgress[qi];
                        const isDoneQ = prog?.status === 'COMPLETED';
                        const isFailQ = prog?.status === 'FAILED';

                        return (
                          <div key={qi} className="bg-white border border-brand-border rounded-xl px-3 py-2">
                            <div className="flex items-center gap-2.5">
                              {isDoneQ ? <CheckCircle2 className="w-3.5 h-3.5 text-brand-green flex-shrink-0" />
                              : isFailQ ? <XCircle className="w-3.5 h-3.5 text-brand-red flex-shrink-0" />
                              : <Loader2 className="w-3.5 h-3.5 text-brand-blue flex-shrink-0 animate-spin" />}
                              <span className="text-slate-700 text-xs flex-1 truncate">{q}</span>
                              {prog && (
                                <span className="text-brand-dgray text-xs flex-shrink-0">
                                  {isDoneQ ? `${prog.rows} rows` : isFailQ ? 'FAILED' : 'Running'}
                                </span>
                              )}
                            </div>
                            {isFailQ && prog?.error && (
                              <p className="pl-6 mt-1 text-brand-red/90 text-xs truncate">{prog.error}</p>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}

                  {/* Phase 3 — live streaming text */}
                  {i === 2 && synthesisText && (
                    <div className="bg-white rounded-xl p-3 border border-brand-border max-h-64 overflow-y-auto">
                      <pre className="text-slate-700 text-xs font-mono whitespace-pre-wrap leading-relaxed">
                        {synthesisText}
                        {isActive && <span className="inline-block w-2 h-3 bg-brand-blue animate-pulse ml-0.5 rounded-sm" />}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {error && (
        <div className="mt-6 bg-brand-red/10 border border-brand-red/30 rounded-xl p-4 text-brand-red text-sm">
          <strong>Error:</strong> {error}
        </div>
      )}
    </div>
  );
}
