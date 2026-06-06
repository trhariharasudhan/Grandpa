import { useEffect, useMemo, useState } from 'react';
import { GitBranch, Network, Route, ShieldCheck, Wrench } from 'lucide-react';
import {
  analyzeIntentRoute,
  fetchIntentRouterDiagnostics,
  type IntentRoute,
  type IntentRouterDiagnostics,
} from '../lib/api';

const examples = [
  'desktop summary',
  'list monitors',
  'clipboard history',
  'browser diagnostics',
  'visual targeting diagnostics',
  'start my coding workspace',
];

export function RouterDiagnosticsPage() {
  const [diagnostics, setDiagnostics] = useState<IntentRouterDiagnostics | null>(null);
  const [request, setRequest] = useState(examples[0]);
  const [analysis, setAnalysis] = useState<IntentRoute | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const refresh = () => {
    fetchIntentRouterDiagnostics().then(setDiagnostics).catch(() => {});
  };

  useEffect(refresh, []);

  const routeCount = useMemo(() => Object.keys(diagnostics?.skill_routes || {}).length, [diagnostics]);

  const analyze = async () => {
    setLoading(true);
    setError('');
    try {
      setAnalysis(await analyzeIntentRoute(request));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Router analysis failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto px-6 py-6" style={{ color: 'var(--color-text)' }}>
      <div className="mx-auto flex max-w-6xl flex-col gap-5">
        <header className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent-amber)' }}>
            <Route size={16} />
            Intent Router
          </div>
          <h1 className="text-2xl font-semibold">Router Diagnostics</h1>
          <p className="max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            Inspect how Grandpa maps local requests into skills, planner handoff, or the legacy compatibility path.
          </p>
        </header>

        <section className="grid gap-3 md:grid-cols-5">
          <Metric icon={Route} label="Routes" value={String(routeCount)} />
          <Metric icon={Wrench} label="Skill Routed" value={String(diagnostics?.skill_routed_count ?? 0)} />
          <Metric icon={GitBranch} label="Planner" value={String(diagnostics?.planner_routed_count ?? 0)} />
          <Metric icon={Network} label="Fallback" value={String(diagnostics?.fallback_count ?? 0)} />
          <Metric icon={ShieldCheck} label="Risky" value={String(diagnostics?.risky_route_count ?? 0)} />
        </section>

        <section className="rounded-2xl p-4" style={panelStyle}>
          <div className="flex flex-col gap-3 md:flex-row">
            <input
              className="min-w-0 flex-1 rounded-xl px-3 py-2 text-sm outline-none"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
              value={request}
              onChange={(event) => setRequest(event.target.value)}
            />
            <button className="rounded-xl px-4 py-2 text-sm font-medium" style={primaryButton} onClick={analyze} disabled={loading}>
              Analyze Route
            </button>
            <button className="rounded-xl px-4 py-2 text-sm font-medium" style={secondaryButton} onClick={refresh}>
              Refresh
            </button>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {examples.map((item) => (
              <button key={item} className="rounded-lg px-2.5 py-1 text-xs" style={chipStyle} onClick={() => setRequest(item)}>
                {item}
              </button>
            ))}
          </div>
          {error && <p className="mt-3 text-sm" style={{ color: 'var(--color-danger)' }}>{error}</p>}
        </section>

        {analysis && (
          <section className="grid gap-4 lg:grid-cols-[0.85fr_1.15fr]">
            <div className="rounded-2xl p-4" style={panelStyle}>
              <h2 className="text-sm font-semibold">Route Decision</h2>
              <div className="mt-4 grid gap-2 text-sm">
                <Row label="Intent" value={analysis.intent} />
                <Row label="Category" value={analysis.category} />
                <Row label="Source" value={analysis.execution_source} />
                <Row label="Confidence" value={`${Math.round(analysis.confidence * 100)}%`} />
                <Row label="Risk" value={analysis.risk_level} />
                <Row label="Approval" value={analysis.approval_required ? 'required' : 'not required'} />
              </div>
              {analysis.fallback_reason && (
                <p className="mt-4 text-sm" style={{ color: 'var(--color-warning)' }}>{analysis.fallback_reason}</p>
              )}
            </div>

            <div className="rounded-2xl p-4" style={panelStyle}>
              <h2 className="text-sm font-semibold">Skill / Planner Target</h2>
              <div className="mt-4 rounded-xl p-3 text-sm" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
                <div className="font-medium">{analysis.skill_name || (analysis.planner_suitable ? 'Planner handoff' : 'Legacy fallback')}</div>
                <pre className="mt-3 max-h-48 overflow-auto text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                  {JSON.stringify(analysis.params || {}, null, 2)}
                </pre>
              </div>
            </div>
          </section>
        )}

        <section className="rounded-2xl p-4" style={panelStyle}>
          <h2 className="text-sm font-semibold">Recent Routes</h2>
          <div className="mt-3 flex flex-col gap-2">
            {(diagnostics?.recent_routes || []).length === 0 ? (
              <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>No routed local requests recorded in this backend session yet.</p>
            ) : (
              diagnostics!.recent_routes.slice(0, 8).map((route, index) => (
                <div key={`${route.created_at}-${index}`} className="rounded-xl px-3 py-2 text-sm" style={{ background: 'var(--color-bg-secondary)' }}>
                  <div className="flex items-center justify-between gap-3">
                    <span>{route.request_text}</span>
                    <span style={{ color: route.route_source === 'skill' ? 'var(--color-success)' : 'var(--color-accent-amber)' }}>{route.route_source || route.execution_source}</span>
                  </div>
                  <div className="mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                    {route.intent} {'->'} {route.skill_name || route.execution_source} ({Math.round(route.confidence * 100)}%)
                  </div>
                </div>
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof Route; label: string; value: string }) {
  return (
    <div className="rounded-2xl p-4" style={panelStyle}>
      <Icon size={18} style={{ color: 'var(--color-accent)' }} />
      <div className="mt-3 text-xs uppercase tracking-[0.18em]" style={{ color: 'var(--color-text-tertiary)' }}>{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span style={{ color: 'var(--color-text-tertiary)' }}>{label}</span>
      <span>{value}</span>
    </div>
  );
}

const panelStyle = {
  background: 'color-mix(in srgb, var(--color-bg-secondary) 78%, transparent)',
  border: '1px solid var(--color-border)',
  boxShadow: '0 24px 80px -55px var(--color-accent)',
};

const primaryButton = {
  background: 'var(--color-accent)',
  color: 'var(--color-on-accent)',
};

const secondaryButton = {
  background: 'var(--color-bg-secondary)',
  border: '1px solid var(--color-border)',
};

const chipStyle = {
  background: 'var(--color-bg-secondary)',
  border: '1px solid var(--color-border)',
  color: 'var(--color-text-secondary)',
};
