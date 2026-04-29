import { useState, useCallback, useEffect } from 'react';
import {
  Edit3, Plus, Trash2, ChevronUp, ChevronDown,
  Presentation, Eye, Lightbulb, Check, X, Layout,
  BarChart3, Users, GitBranch, Building2, DollarSign, TrendingUp, Globe2, FileText,
} from 'lucide-react';
import type { ReportOutline, SlideOutline } from '../types';
import SlidePreview from './SlidePreview';

interface OutlineEditorProps {
  outline: ReportOutline;
  onGenerate: (outline: ReportOutline) => void;
  onViewReport: () => void;
  generating: boolean;
}

const SLIDE_ICONS = {
  1: BarChart3,
  2: Users,
  3: GitBranch,
  4: Building2,
  5: DollarSign,
  6: TrendingUp,
  7: Globe2,
};

// ── Inline editable field ─────────────────────────────────────────────────────

function InlineEdit({
  value, onSave, className = '', multiline = false, placeholder = '',
}: {
  value: string; onSave: (v: string) => void;
  className?: string; multiline?: boolean; placeholder?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  const commit = () => { onSave(draft); setEditing(false); };
  const cancel = () => { setDraft(value); setEditing(false); };

  if (!editing) {
    return (
      <span onClick={() => { setDraft(value); setEditing(true); }}
        className={`cursor-text group relative ${className}`} title="Click to edit">
        {value || <span className="text-brand-dgray italic">{placeholder}</span>}
        <Edit3 className="inline-block w-3 h-3 ml-1 text-brand-dgray opacity-0 group-hover:opacity-100 transition-opacity" />
      </span>
    );
  }

  return (
    <span className="flex items-start gap-1 w-full">
      {multiline ? (
        <textarea autoFocus value={draft} onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === 'Escape') cancel(); }} rows={2}
          className={`bg-white border border-brand-blue rounded-lg px-2 py-1 text-slate-900
                      focus:outline-none resize-none w-full ${className}`} />
      ) : (
        <input autoFocus type="text" value={draft} onChange={e => setDraft(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') cancel(); }}
          className={`bg-white border border-brand-blue rounded-lg px-2 py-1 text-slate-900
                      focus:outline-none w-full ${className}`} />
      )}
      <button onClick={commit} className="text-brand-green hover:text-green-400 flex-shrink-0 mt-0.5"><Check className="w-4 h-4" /></button>
      <button onClick={cancel} className="text-brand-dgray hover:text-slate-900 flex-shrink-0 mt-0.5"><X className="w-4 h-4" /></button>
    </span>
  );
}

// ── Main component ────────────────────────────────────────────────────────────

export default function OutlineEditor({
  outline: initialOutline, onGenerate, onViewReport,
  generating,
}: OutlineEditorProps) {
  const [outline, setOutline] = useState<ReportOutline>(() => ensureSevenSlides(initialOutline));
  const [activeSlide, setActiveSlide] = useState(0);
  const [showPreview, setShowPreview] = useState(true);

  useEffect(() => {
    setOutline(ensureSevenSlides(initialOutline));
    setActiveSlide(0);
  }, [initialOutline]);

  const slide = outline.slides[activeSlide];

  const updateSlide = useCallback((idx: number, patch: Partial<SlideOutline>) => {
    setOutline(prev => ({
      ...prev,
      slides: prev.slides.map((s, i) => i === idx ? { ...s, ...patch } : s),
    }));
  }, []);

  const updatePoint = (pi: number, value: string) => {
    const points = [...slide.points];
    points[pi] = value;
    updateSlide(activeSlide, { points });
  };

  const addPoint = () => updateSlide(activeSlide, { points: [...slide.points, 'New bullet point'] });

  const removePoint = (pi: number) =>
    updateSlide(activeSlide, { points: slide.points.filter((_, i) => i !== pi) });

  const movePoint = (pi: number, dir: -1 | 1) => {
    const points = [...slide.points];
    const t = pi + dir;
    if (t < 0 || t >= points.length) return;
    [points[pi], points[t]] = [points[t], points[pi]];
    updateSlide(activeSlide, { points });
  };

  return (
    <div className="animate-slide-up">
      {/* Toolbar */}
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div>
                <h2 className="text-2xl font-bold text-slate-900">Review &amp; Edit Outline</h2>
                <p className="text-brand-dgray text-sm mt-1">Edit slides before generating your deck</p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button onClick={() => setShowPreview(v => !v)}
            className={`flex items-center gap-2 px-3 py-2 rounded-xl border text-sm transition-all
              ${showPreview ? 'border-brand-blue/50 bg-brand-blue/10 text-brand-blue' : 'border-brand-border text-brand-dgray hover:text-slate-900'}`}>
            <Layout className="w-4 h-4" /> {showPreview ? 'Hide Preview' : 'Show Preview'}
          </button>
          <button onClick={onViewReport}
            className="flex items-center gap-2 px-3 py-2 rounded-xl border border-brand-border
                       text-brand-dgray hover:text-slate-900 hover:border-brand-blue/50 text-sm transition-all">
            <Eye className="w-4 h-4" /> Full Report
          </button>
          <button onClick={() => onGenerate(outline)} disabled={generating}
            className="flex items-center gap-2 px-4 py-2 rounded-xl font-semibold text-white text-sm
                       bg-gradient-to-r from-brand-red to-orange-500
                       hover:from-red-600 hover:to-orange-600 disabled:opacity-50 transition-all shadow-lg shadow-brand-red/20">
            {generating
              ? <><span className="w-3.5 h-3.5 border-2 border-white/30 border-t-white rounded-full animate-spin" /> PPT…</>
              : <><Presentation className="w-4 h-4" /> PPT</>}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-[220px_1fr] gap-5">
        {/* Slide list */}
        <div className="space-y-1.5 overflow-y-auto max-h-[70vh]">
          {outline.slides.map((s, i) => (
            <button key={s.id} onClick={() => setActiveSlide(i)}
              className={`w-full text-left px-3 py-2.5 rounded-xl border transition-all ${
                i === activeSlide
                  ? 'border-brand-blue/50 bg-brand-blue/10 text-slate-900'
                  : 'border-brand-border bg-brand-surface text-brand-dgray hover:border-brand-blue/30 hover:text-slate-900'
              }`}>
              <div className="flex items-center gap-2">
                {(() => {
                  const Icon = SLIDE_ICONS[s.number as keyof typeof SLIDE_ICONS] ?? FileText;
                  return <Icon className="w-4 h-4 text-brand-blue flex-shrink-0" />;
                })()}
                <div className="min-w-0">
                  <div className="text-xs text-brand-dgray font-mono">Slide {s.number}</div>
                  <div className="text-xs font-medium truncate">{s.title}</div>
                  <div className="text-xs text-brand-dgray">{s.points.length} pts</div>
                </div>
              </div>
            </button>
          ))}
        </div>

        {/* Right panel: editor + preview */}
        <div className="space-y-5 overflow-y-auto max-h-[70vh] pr-1">
          {/* ── Live Preview ── */}
          {showPreview && slide && (
            <div>
              <p className="text-brand-dgray text-xs font-medium mb-2 uppercase tracking-wide">Live Preview</p>
              <SlidePreview slide={slide} />
            </div>
          )}

          {/* ── Editor ── */}
          {slide && (
            <div className="bg-brand-surface border border-brand-border rounded-2xl p-5">
              {/* Slide title */}
              <div className="mb-5">
                <div className="flex items-center gap-2 mb-1">
                  {(() => {
                    const Icon = SLIDE_ICONS[slide.number as keyof typeof SLIDE_ICONS] ?? FileText;
                    return <Icon className="w-5 h-5 text-brand-blue" />;
                  })()}
                  <span className="text-brand-dgray text-xs font-mono">Slide {slide.number}</span>
                </div>
                <h3 className="text-lg font-bold text-slate-900">
                  <InlineEdit value={slide.title}
                    onSave={v => updateSlide(activeSlide, { title: v })}
                    placeholder="Slide title" />
                </h3>
              </div>

              {/* Bullet points */}
              <div className="mb-5">
                <div className="flex items-center justify-between mb-3">
                  <span className="text-brand-lgray text-sm font-medium">Content Points</span>
                  <button onClick={addPoint}
                    className="flex items-center gap-1.5 text-xs text-brand-blue hover:text-slate-900
                               border border-brand-blue/30 hover:border-brand-blue px-2.5 py-1 rounded-lg transition-all">
                    <Plus className="w-3 h-3" /> Add point
                  </button>
                </div>
                <div className="space-y-2">
                  {slide.points.map((pt, pi) => (
                    <div key={pi}
                      className="group flex items-start gap-2 bg-white border border-brand-border
                                 rounded-xl p-3 hover:border-brand-blue/30 transition-all">
                      <span className="w-1.5 h-1.5 rounded-full bg-brand-red flex-shrink-0 mt-2" />
                      <span className="flex-1 text-sm text-brand-lgray">
                        <InlineEdit value={pt} onSave={v => updatePoint(pi, v)}
                          multiline placeholder="Enter bullet point" />
                      </span>
                      <div className="flex flex-col gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button onClick={() => movePoint(pi, -1)} disabled={pi === 0}
                        className="text-brand-dgray hover:text-slate-900 disabled:opacity-30">
                          <ChevronUp className="w-3.5 h-3.5" />
                        </button>
                        <button onClick={() => movePoint(pi, 1)} disabled={pi === slide.points.length - 1}
                        className="text-brand-dgray hover:text-slate-900 disabled:opacity-30">
                          <ChevronDown className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <button onClick={() => removePoint(pi)}
                        className="text-brand-dgray hover:text-brand-red transition-colors opacity-0 group-hover:opacity-100">
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  ))}
                  {slide.points.length === 0 && (
                    <div className="text-center py-6 text-brand-dgray text-sm border border-dashed border-brand-border rounded-xl">
                      No content points. Click "Add point" to add one.
                    </div>
                  )}
                </div>
              </div>

              {/* Key Insight */}
              <div>
                <div className="flex items-center gap-2 mb-2">
                  <Lightbulb className="w-4 h-4 text-brand-amber" />
                  <span className="text-brand-lgray text-sm font-medium">Key Insight</span>
                </div>
                <div className="bg-white border border-brand-amber/30 rounded-xl p-4 text-sm text-brand-lgray">
                  <InlineEdit value={slide.insight || ''} onSave={v => updateSlide(activeSlide, { insight: v })}
                    multiline placeholder="Add a key takeaway for this slide…"
                    className="w-full leading-relaxed" />
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ensureSevenSlides(input: ReportOutline): ReportOutline {
  const targetTitles = [
    'Executive Summary',
    'Pipeline and Revenue Performance',
    'Funnel and Conversion Health',
    'Audience and Segment Performance',
    'Platform and Data Quality',
    'Financial Efficiency and ROI',
    'Risks, Actions, and Next Steps',
  ];

  const slides = [...input.slides].slice(0, 7);
  while (slides.length < 7) {
    const number = slides.length + 1;
    slides.push({
      id: `slide-${number}`,
      number,
      title: targetTitles[number - 1],
      subtitle: '',
      points: ['Add supporting metrics and insights for this section.'],
      insight: '',
      table_data: null,
    });
  }

  return {
    ...input,
    slides: slides.map((s, i) => ({
      ...s,
      id: `slide-${i + 1}`,
      number: i + 1,
      title: s.title?.trim() || targetTitles[i],
      points: s.points ?? [],
      insight: s.insight ?? '',
      subtitle: s.subtitle ?? '',
      table_data: s.table_data ?? null,
    })),
  };
}
