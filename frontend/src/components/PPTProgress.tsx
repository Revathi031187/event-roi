import { Check, Palette, BarChart3, Users, GitBranch, Building2, DollarSign, TrendingUp, Globe2, FileText, Lightbulb } from 'lucide-react';
import type { SlideProgress } from '../types';

interface PPTProgressProps {
  completedSlides: SlideProgress[];
  totalSlides: number;
  eventName: string;
}

const ICONS = [Palette, BarChart3, Users, GitBranch, Building2, DollarSign, TrendingUp, Globe2, FileText, Lightbulb];

export default function PPTProgress({ completedSlides, totalSlides, eventName }: PPTProgressProps) {
  const done = completedSlides.length;
  const pct = totalSlides > 0 ? Math.round((done / totalSlides) * 100) : 0;

  return (
    <div className="animate-slide-up max-w-3xl mx-auto">
      {/* Header */}
      <div className="text-center mb-8">
        <div className="inline-flex items-center gap-2 bg-brand-red/10 border border-brand-red/30
                        text-brand-red text-sm px-4 py-1.5 rounded-full mb-4">
          <span className="w-2 h-2 rounded-full bg-brand-red animate-pulse" />
          Generating PowerPoint
        </div>
        <h2 className="text-3xl font-bold text-slate-900 mb-1">Building Your Deck</h2>
        <p className="text-brand-dgray">{eventName}</p>
      </div>

      {/* Progress bar */}
      <div className="bg-brand-surface border border-brand-border rounded-2xl p-6 mb-6">
        <div className="flex items-center justify-between mb-3">
          <span className="text-brand-lgray text-sm">
            {done >= totalSlides && totalSlides > 0
              ? 'All slides built — saving file…'
              : `Building slides…`}
          </span>
          <span className="font-mono text-sm text-slate-900">{done} / {totalSlides}</span>
        </div>
        <div className="h-2 bg-slate-200 rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-brand-red to-orange-500 rounded-full
                       transition-all duration-700 ease-out"
            style={{ width: `${pct}%` }}
          />
        </div>
        <div className="flex items-center justify-between mt-2">
          <span className="text-brand-dgray text-xs">{pct}%</span>
          {done >= totalSlides && totalSlides > 0 && (
            <span className="text-brand-green text-xs font-medium flex items-center gap-1">
              <Check className="w-3 h-3" /> Finalizing…
            </span>
          )}
        </div>
      </div>

      {/* Slide cards grid */}
      <div className="grid grid-cols-4 gap-3">
        {Array.from({ length: totalSlides }).map((_, idx) => {
          const built = completedSlides.find(s => s.slide === idx);
          const isDone = !!built;
          const title = built?.title ?? (idx === 0 ? 'Cover Slide' : `Slide ${idx}`);
          const Icon = ICONS[idx] ?? FileText;

          return (
            <div
              key={idx}
              className={`relative rounded-xl border overflow-hidden transition-all duration-500 ${
                isDone
                  ? 'border-brand-red/40 opacity-100 shadow-lg shadow-brand-red/10'
                  : 'border-brand-border opacity-45'
              }`}
              style={{ transitionDelay: `${idx * 40}ms` }}
            >
              {/* Mini slide mockup */}
              <div className="bg-white p-2" style={{ aspectRatio: '4/3' }}>
                {/* Red header bar */}
                <div className={`h-1 rounded-sm mb-1.5 transition-colors duration-500 ${
                  isDone ? 'bg-brand-red' : 'bg-brand-dgray/40'
                }`} />
                {/* Title line */}
                <div className={`h-1.5 rounded-sm mb-1 w-3/4 transition-colors duration-500 ${
                  isDone ? 'bg-slate-400/40' : 'bg-slate-300'
                }`} />
                {/* Content lines */}
                {[1, 0.8, 0.6].map((w, i) => (
                  <div key={i} className={`h-1 rounded-sm mb-1 transition-colors duration-500 ${
                    isDone ? 'bg-slate-300/60' : 'bg-slate-200'
                  }`} style={{ width: `${w * 100}%` }} />
                ))}
                <div className="flex-1" />
                {/* Footer bar */}
                <div className={`h-1 rounded-sm w-full mt-auto transition-colors duration-500 ${
                  isDone ? 'bg-slate-300' : 'bg-slate-200'
                }`} />
              </div>

              {/* Label */}
              <div className={`px-2.5 py-1.5 transition-colors duration-500 ${
                isDone ? 'bg-brand-surface' : 'bg-slate-50'
              }`}>
                <div className="flex items-center justify-between">
                  <span className="text-[10px] font-mono text-brand-dgray">
                    {idx === 0 ? 'Cover' : `Slide ${idx}`}
                  </span>
                  {isDone
                    ? <Check className="w-3 h-3 text-brand-green" />
                    : <Icon className="w-3 h-3 text-brand-dgray" />}
                </div>
                <div className={`text-[10px] truncate mt-0.5 transition-colors duration-500 ${
                  isDone ? 'text-brand-lgray' : 'text-brand-dgray'
                }`}>{title}</div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
