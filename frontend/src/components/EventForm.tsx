import { useState, useEffect } from 'react';
import { Search, CheckCircle2, AlertCircle, Info, AlertTriangle, ChevronDown, X } from 'lucide-react';
import type { GenerateFormData, ApiStatus } from '../types';

interface EventFormProps {
  onSubmit: (data: GenerateFormData) => void;
  status: ApiStatus | null;
  loading?: boolean;
}

const EXAMPLE_EVENTS = [
  'AI Days 2026', 'NRF 2026', 'AWS re:Invent 2025',
  'Data + AI Summit 2026', 'Gartner Data & Analytics', 'Microsoft Ignite 2025',
];

function maskHost(host: string): string {
  // Show only the subdomain portion: https://adb-123...net
  return host.replace(/^(https?:\/\/[^.]{0,12})[^/]*/, '$1…');
}

export default function EventForm({ onSubmit, status, loading }: EventFormProps) {
  const [eventName, setEventName] = useState('');
  const [context, setContext] = useState('');

  // Override credentials (empty = use .env values)
  const [showCredentials, setShowCredentials] = useState(false);
  const [dbHost, setDbHost] = useState('');
  const [dbToken, setDbToken] = useState('');
  const [genieId, setGenieId] = useState('');

  // Pre-fill space ID from backend status once it loads
  useEffect(() => {
    if (status?.genie_space_id && !genieId) {
      setGenieId(status.genie_space_id);
    }
    // Auto-expand credential form when Databricks is NOT configured
    if (status && !status.databricks_configured) {
      setShowCredentials(true);
    }
  }, [status?.genie_space_id, status?.databricks_configured]); // eslint-disable-line

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!eventName.trim()) return;
    onSubmit({
      event_name: eventName.trim(),
      additional_context: context.trim(),
      databricks_host: dbHost.trim(),
      databricks_token: dbToken.trim(),
      genie_space_id: genieId.trim(),
    });
  };

  const cancelOverride = () => {
    setDbHost('');
    setDbToken('');
    if (status?.genie_space_id) setGenieId(status.genie_space_id);
    setShowCredentials(false);
  };

  const isConfigured = !!status?.databricks_configured;
  const isLoading   = status === null;
  const isDemoMode  = !isLoading && !isConfigured && !dbHost;
  const isGeminiMissing = status !== null && !status.gemini_configured;

  const shortSpaceId = genieId ? `…${genieId.slice(-8)}` : '—';

  return (
    <div className="animate-slide-up max-w-2xl mx-auto">
      {/* Hero */}
      <div className="text-center mb-10">
        <div className="inline-flex items-center gap-2 bg-brand-red/10 border border-brand-red/30 text-brand-red text-sm px-4 py-1.5 rounded-full mb-4">
          <span className="w-2 h-2 rounded-full bg-brand-red animate-pulse" />
          Agent Pipeline · Plan → Query → Synthesize
        </div>
        <h2 className="text-4xl font-bold text-slate-900 mb-3">
          Generate Event ROI Report
        </h2>
        <p className="text-brand-dgray text-lg max-w-xl mx-auto">
          Consolidates registration, attendance, pipeline, and cost data into a
          structured deck — automatically, in under 30 seconds.
        </p>
      </div>

      {/* Gemini missing alert */}
      {isGeminiMissing && (
        <div className="mb-4 flex items-start gap-3 bg-amber-500/10 border border-amber-500/30 text-amber-400 text-sm px-4 py-3 rounded-xl">
          <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <span>
            Gemini API key is not configured. Set{' '}
            <code className="font-mono bg-amber-500/20 px-1 rounded">GEMINI_API_KEY</code>{' '}
            in <code className="font-mono bg-amber-500/20 px-1 rounded">backend/.env</code>.
          </span>
        </div>
      )}

      {/* Form card */}
      <form onSubmit={handleSubmit} className="bg-brand-surface border border-brand-border rounded-2xl p-8 shadow-sm">

        {/* Event name */}
        <div className="mb-6">
          <label className="block text-slate-900 font-medium mb-2 text-sm">
            Event Name <span className="text-brand-red">*</span>
          </label>
          <div className="relative">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-brand-dgray" />
            <input
              type="text"
              value={eventName}
              onChange={e => setEventName(e.target.value)}
              placeholder="e.g. AI Days 2026, NRF 2026"
              required
              className="w-full bg-white border border-brand-border rounded-xl py-3 pl-10 pr-4
                         text-slate-900 placeholder-brand-dgray focus:outline-none focus:border-brand-blue
                         focus:ring-1 focus:ring-brand-blue/30 transition-all"
            />
          </div>
          <div className="flex flex-wrap gap-2 mt-3">
            {EXAMPLE_EVENTS.map(ev => (
              <button
                key={ev}
                type="button"
                onClick={() => setEventName(ev)}
                className="text-xs px-2.5 py-1 rounded-lg bg-brand-card border border-brand-border
                           text-brand-dgray hover:text-slate-900 hover:border-brand-blue/50 transition-all"
              >
                {ev}
              </button>
            ))}
          </div>
        </div>

        {/* Additional context */}
        <div className="mb-6">
          <label className="block text-slate-900 font-medium mb-2 text-sm">
            Additional Context
            <span className="text-brand-dgray font-normal ml-1">(optional)</span>
          </label>
          <textarea
            value={context}
            onChange={e => setContext(e.target.value)}
            rows={2}
            placeholder="e.g. Focus on EMEA results. Highlight the executive roundtable segment."
            className="w-full bg-white border border-brand-border rounded-xl py-3 px-4
                       text-slate-900 placeholder-brand-dgray focus:outline-none focus:border-brand-blue
                       focus:ring-1 focus:ring-brand-blue/30 transition-all resize-none"
          />
        </div>

        {/* ── Connection Status ─────────────────────────────────────────────── */}
        <div className="mb-6">

          {/* Loading state */}
          {isLoading && (
            <div className="flex items-center gap-2 text-brand-dgray text-sm py-2">
              <span className="w-3 h-3 border-2 border-brand-dgray/40 border-t-brand-dgray rounded-full animate-spin" />
              Checking Databricks connection…
            </div>
          )}

          {/* Connected — show compact status row */}
          {!isLoading && isConfigured && !showCredentials && (
            <div className="flex items-center gap-3 bg-brand-green/5 border border-brand-green/20 rounded-xl px-4 py-3">
              <CheckCircle2 className="w-4 h-4 text-brand-green flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-brand-green text-sm font-medium">Connected to Databricks</p>
                <p className="text-brand-dgray text-xs mt-0.5 font-mono truncate">
                  {maskHost(status?.databricks_host || '')} &nbsp;·&nbsp; Space: {shortSpaceId}
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowCredentials(true)}
                className="flex items-center gap-1.5 text-xs text-brand-dgray hover:text-slate-900
                           border border-brand-border hover:border-brand-blue/50 px-3 py-1.5
                           rounded-lg transition-all flex-shrink-0"
              >
                <ChevronDown className="w-3 h-3" />
                Change
              </button>
            </div>
          )}

          {/* Demo mode — not configured, no override entered */}
          {isDemoMode && !showCredentials && (
            <div className="flex items-center gap-3 bg-brand-blue/5 border border-brand-blue/20 rounded-xl px-4 py-3">
              <Info className="w-4 h-4 text-brand-blue flex-shrink-0" />
              <div className="flex-1 min-w-0">
                <p className="text-brand-blue text-sm font-medium">Demo Mode</p>
                <p className="text-brand-dgray text-xs mt-0.5">
                  No Databricks credentials in <code className="font-mono">.env</code> — report will use sample data.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowCredentials(true)}
                className="flex items-center gap-1.5 text-xs text-brand-dgray hover:text-slate-900
                           border border-brand-border hover:border-brand-blue/50 px-3 py-1.5
                           rounded-lg transition-all flex-shrink-0"
              >
                <ChevronDown className="w-3 h-3" />
                Configure
              </button>
            </div>
          )}

          {/* Override credential form */}
          {showCredentials && (
            <div className="border border-brand-border rounded-xl p-4 bg-brand-card space-y-3">
              <div className="flex items-center justify-between mb-1">
                <p className="text-slate-900 text-sm font-medium">
                  {isConfigured ? 'Override Databricks Credentials' : 'Configure Databricks'}
                </p>
                {isConfigured && (
                  <button
                    type="button"
                    onClick={cancelOverride}
                    className="flex items-center gap-1 text-xs text-brand-dgray hover:text-slate-900 transition-colors"
                  >
                    <X className="w-3.5 h-3.5" />
                    Cancel — use .env
                  </button>
                )}
              </div>

              <div>
                <label className="block text-brand-lgray text-xs font-medium mb-1">Databricks Host</label>
                <input
                  type="url"
                  value={dbHost}
                  onChange={e => setDbHost(e.target.value)}
                  placeholder={status?.databricks_host || 'https://your-workspace.azuredatabricks.net'}
                  className="w-full bg-white border border-brand-border rounded-lg py-2.5 px-3
                             text-slate-900 text-sm placeholder-brand-dgray focus:outline-none
                             focus:border-brand-blue transition-all"
                />
                {isConfigured && !dbHost && (
                  <p className="text-brand-dgray text-xs mt-1">Leave blank to use .env value</p>
                )}
              </div>

              <div>
                <label className="block text-brand-lgray text-xs font-medium mb-1">Personal Access Token</label>
                <input
                  type="password"
                  value={dbToken}
                  onChange={e => setDbToken(e.target.value)}
                  placeholder={isConfigured ? '•••••••• (leave blank to use .env value)' : 'dapi••••••••••••••••'}
                  className="w-full bg-white border border-brand-border rounded-lg py-2.5 px-3
                             text-slate-900 text-sm placeholder-brand-dgray focus:outline-none
                             focus:border-brand-blue transition-all font-mono"
                />
              </div>

              <div>
                <label className="block text-brand-lgray text-xs font-medium mb-1">
                  Genie Space ID
                  {isConfigured && <span className="text-brand-dgray font-normal ml-1">(pre-filled from .env)</span>}
                </label>
                <input
                  type="text"
                  value={genieId}
                  onChange={e => setGenieId(e.target.value)}
                  placeholder={status?.genie_space_id || 'space-id'}
                  className="w-full bg-white border border-brand-border rounded-lg py-2.5 px-3
                             text-slate-900 text-sm placeholder-brand-dgray focus:outline-none
                             focus:border-brand-blue transition-all font-mono"
                />
              </div>

              {!isConfigured && (
                <div className="flex items-start gap-2 text-brand-dgray text-xs bg-white rounded-lg px-3 py-2 border border-brand-border">
                  <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                  <span>
                    You can also set credentials permanently in{' '}
                    <code className="font-mono">backend/.env</code> — they'll auto-load on restart and won't need re-entry here.
                  </span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Submit */}
        <button
          type="submit"
          disabled={loading || !eventName.trim() || !!isGeminiMissing}
          className="w-full py-4 rounded-xl font-semibold text-white text-base
                     bg-gradient-to-r from-brand-red to-orange-500
                     hover:from-red-600 hover:to-orange-600
                     disabled:opacity-40 disabled:cursor-not-allowed
                     transition-all shadow-lg shadow-brand-red/20
                     flex items-center justify-center gap-2"
        >
          {loading ? (
            <>
              <span className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Starting…
            </>
          ) : isDemoMode ? (
            <>Generate Report (Demo Data) →</>
          ) : (
            <>Generate ROI Report →</>
          )}
        </button>
      </form>

      {/* Stats row */}
      <div className="grid grid-cols-3 gap-4 mt-6">
        {[
          { label: 'Time Saved', value: '4–6 hrs', sub: 'per event' },
          { label: 'Data Sources', value: '3+', sub: 'reg · pipeline · spend' },
          { label: 'Output Slides', value: '7', sub: 'standardized deck' },
        ].map(m => (
          <div key={m.label} className="text-center bg-brand-surface border border-brand-border rounded-xl p-4">
            <div className="text-2xl font-bold text-brand-red">{m.value}</div>
            <div className="text-slate-900 text-sm font-medium mt-0.5">{m.label}</div>
            <div className="text-brand-dgray text-xs mt-0.5">{m.sub}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
