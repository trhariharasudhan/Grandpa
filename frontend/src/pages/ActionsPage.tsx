import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { Activity, GitBranch, Layers3, RefreshCw, Route } from 'lucide-react';
import { fetchActionDiagnostics, type ActionDiagnostics } from '../lib/api';

export function ActionsPage() {
  const [data, setData] = useState<ActionDiagnostics | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const refresh = () => {
    setLoading(true);
    setError('');
    fetchActionDiagnostics()
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load action diagnostics'))
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []);

  return (
    <div className="h-full overflow-y-auto px-6 py-6" style={{ color: 'var(--color-text)' }}>
      <div className="mx-auto flex max-w-6xl flex-col gap-5">
        <header className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent-amber)' }}>
            <Route size={16} />
            Local Action Runtime
          </div>
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="text-2xl font-semibold">Action Decomposition</h1>
              <p className="mt-2 max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                Track which local commands have moved from legacy parsing into focused action modules, while Grandpa keeps the old compatibility path available.
              </p>
            </div>
            <button className="flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium" style={secondaryButton} onClick={refresh} disabled={loading}>
              <RefreshCw size={15} />
              Refresh
            </button>
          </div>
        </header>

        {error && (
          <div className="rounded-xl px-4 py-3 text-sm" style={{ border: '1px solid var(--color-danger)', color: 'var(--color-danger)' }}>
            {error}
          </div>
        )}

        <section className="grid gap-3 md:grid-cols-4">
          <Metric icon={Layers3} label="Migrated" value={String(data?.migrated_count ?? 0)} />
          <Metric icon={GitBranch} label="Legacy" value={String(data?.legacy_count ?? 0)} />
          <Metric icon={Activity} label="Coverage" value={`${Math.round((data?.routing_coverage ?? 0) * 100)}%`} />
          <Metric icon={Route} label="Fallbacks" value={String(data?.fallback_count ?? 0)} />
        </section>

        <section className="grid gap-3 lg:grid-cols-2">
          <Panel title="Migrated Handlers">
            {Object.entries(data?.migrated_handlers || {}).map(([domain, count]) => (
              <InfoRow key={domain} label={domain} value={`${count} handlers`} />
            ))}
          </Panel>

          <Panel title="Remaining Legacy Domains">
            {Object.entries(data?.legacy_handlers || {}).map(([domain, detail]) => (
              <InfoRow key={domain} label={domain} value={detail} />
            ))}
          </Panel>
        </section>

        <Panel title="Recent Routes">
          {(data?.recent_routes || []).slice(0, 10).map((route, index) => (
            <InfoRow key={`${route.request}-${index}`} label={`${route.domain} / ${route.source}`} value={route.request || 'empty request'} />
          ))}
          {(data?.recent_routes || []).length === 0 && <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>No local action routes recorded in this backend session yet.</p>}
        </Panel>
      </div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl p-4" style={panelStyle}>
      <h2 className="text-sm font-semibold">{title}</h2>
      <div className="mt-3 flex flex-col gap-2">{children}</div>
    </section>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl px-3 py-2" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
      <div className="text-xs uppercase tracking-[0.18em]" style={{ color: 'var(--color-text-tertiary)' }}>{label}</div>
      <div className="mt-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>{value}</div>
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

const panelStyle = {
  background: 'color-mix(in srgb, var(--color-bg-secondary) 78%, transparent)',
  border: '1px solid var(--color-border)',
  boxShadow: '0 24px 80px -55px var(--color-accent)',
};

const secondaryButton = {
  background: 'var(--color-bg-secondary)',
  border: '1px solid var(--color-border)',
};
