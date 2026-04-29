import type { SlideOutline } from '../types';
import { BarChart3, Users, GitBranch, Building2, DollarSign, TrendingUp, Globe2, FileText } from 'lucide-react';

const SLIDE_ICONS = {
  1: BarChart3,
  2: Users,
  3: GitBranch,
  4: Building2,
  5: DollarSign,
  6: TrendingUp,
  7: Globe2,
};

interface SlidePreviewProps {
  slide: SlideOutline;
  /** Scale factor — default 1 renders at ~640×360px equivalent in CSS */
  scale?: number;
}

/** KPI boxes row for executive summary (slide 1) */
function KpiRow({ points }: { points: string[] }) {
  return (
    <div className="flex gap-1 mt-1">
      {points.slice(0, 4).map((pt, i) => {
        const parts = pt.split(':');
        const label = parts[0]?.trim() ?? `KPI ${i + 1}`;
        const value = parts[1]?.trim().slice(0, 18) ?? pt.slice(0, 18);
        return (
          <div key={i} className="flex-1 bg-[#F8FAFC] border border-[#D8E1EB] rounded relative overflow-hidden">
            <div className="h-[3px] bg-[#FF3621] w-full" />
            <div className="px-1 py-0.5">
              <div className="text-[#111827] font-bold text-[8px] leading-tight truncate">{value}</div>
              <div className="text-[#4B5563] text-[6px] truncate">{label}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Funnel bars for pipeline slide (slide 3) */
function FunnelBars({ points }: { points: string[] }) {
  const stageColors = ['#DBEAFE', '#BFDBFE', '#93C5FD', '#FF3621', '#FF6B50', '#FF9A87'];
  return (
    <div className="space-y-0.5 mt-1">
      {points.slice(0, 6).map((pt, i) => {
        const width = Math.max(15, 100 - i * 12);
        return (
          <div key={i} className="flex items-center gap-1">
            <div
              className="h-[8px] rounded-sm flex items-center px-0.5"
              style={{ width: `${width}%`, backgroundColor: stageColors[i] ?? '#1A3A5C' }}
            />
            <span className="text-[#4B5563] text-[5px] truncate flex-1">{pt.slice(0, 30)}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function SlidePreview({ slide }: SlidePreviewProps) {
  const isExec   = slide.number === 1;
  const isFunnel = slide.number === 3;
  const Icon = SLIDE_ICONS[slide.number as keyof typeof SLIDE_ICONS] ?? FileText;

  return (
    /* Fixed 16:9 aspect ratio wrapper */
    <div className="w-full aspect-[16/9] bg-white rounded-lg overflow-hidden flex flex-col select-none border border-[#D8E1EB]">
      {/* Red accent line */}
      <div className="h-[3px] bg-[#FF3621] flex-shrink-0" />

      {/* Header band */}
      <div className="bg-[#F8FAFC] px-2 py-1 flex items-center gap-1.5 flex-shrink-0 border-b border-[#E2E8F0]">
        <Icon className="w-3 h-3 text-[#2563EB]" />
        <span className="text-[#111827] font-bold text-[8px] truncate flex-1">{slide.title}</span>
        <img
          src="/databricks-logo.png"
          alt=""
          className="h-3 w-auto object-contain shrink-0 opacity-90"
          width={48}
          height={12}
        />
      </div>

      {/* Content */}
      <div className="flex-1 px-2 py-1 overflow-hidden">
        {isExec && <KpiRow points={slide.points} />}
        {isFunnel && <FunnelBars points={slide.points} />}

        {/* Bullets (always shown; for funnel — below bars) */}
        <div className={`space-y-0.5 ${isExec || isFunnel ? 'mt-1' : ''}`}>
          {slide.points.slice(isExec ? 4 : isFunnel ? 0 : 0, isExec ? 8 : isFunnel ? 0 : 8).map((pt, i) => (
            <div key={i} className="flex items-start gap-1">
              <span className="text-[#FF3621] text-[5px] mt-[2px] flex-shrink-0">●</span>
              <span className="text-[#334155] text-[6px] leading-tight truncate">{pt}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Insight footer */}
      {slide.insight && (
        <div className="bg-[#F8FAFC] border-t border-[#BAE6FD] px-2 py-1 flex-shrink-0">
          <span className="text-[#0099C4] text-[5px] line-clamp-1">{slide.insight}</span>
        </div>
      )}
    </div>
  );
}
