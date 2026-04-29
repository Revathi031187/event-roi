interface HeaderProps {
  onReset?: () => void;
  showReset?: boolean;
}

export default function Header({ onReset, showReset }: HeaderProps) {
  return (
    <header className="border-b border-brand-border bg-brand-surface/95 backdrop-blur-sm sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-4 min-w-0">
          <img
            src="/databricks-logo.png"
            alt="Databricks"
            className="h-9 w-auto max-w-[140px] object-contain object-left shrink-0"
            width={140}
            height={36}
          />
          <div className="border-l border-brand-border pl-4 min-w-0">
            <h1 className="text-slate-900 font-bold text-lg leading-none tracking-tight">
              Event ROI Dashboard
            </h1>
            <p className="text-brand-dgray text-xs mt-0.5">
              AI-Powered Post-Event Analytics
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          {showReset && (
            <button
              onClick={onReset}
              className="text-brand-dgray hover:text-slate-900 text-sm px-3 py-1.5 rounded-lg border border-brand-border hover:border-brand-blue/50 transition-all"
            >
              New Report
            </button>
          )}
        </div>
      </div>
    </header>
  );
}
