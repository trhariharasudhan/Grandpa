import { useEffect, useState } from 'react';
import { AlertTriangle, MonitorCog, RefreshCw, ShieldCheck } from 'lucide-react';
import { fetchDesktopControlDiagnostics, type DesktopControlDiagnostics } from '../lib/api';

export function DesktopServicesPage() {
  const [data, setData] = useState<DesktopControlDiagnostics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchDesktopControlDiagnostics());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load desktop services');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="h-full overflow-y-auto" style={{ background: 'var(--color-bg)' }}>
      <div className="max-w-6xl mx-auto px-6 py-6">
        <div className="flex items-start justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>
              Desktop Services
            </h1>
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
              Readiness for Grandpa's local PC-control domains, approvals, dependencies, and support boundaries.
            </p>
          </div>
          <button
            type="button"
            onClick={load}
            className="inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition-colors"
            style={{
              color: 'var(--color-text)',
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
            }}
          >
            <RefreshCw size={15} />
            Refresh
          </button>
        </div>

        <section
          className="rounded-2xl p-4 mb-5"
          style={{
            background: 'color-mix(in srgb, var(--color-bg-secondary) 82%, transparent)',
            border: '1px solid color-mix(in srgb, var(--color-accent) 20%, var(--color-border))',
          }}
        >
          <div className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="rounded-xl p-2" style={{ color: 'var(--color-accent-amber)', background: 'var(--color-accent-subtle)' }}>
                <MonitorCog size={20} />
              </div>
              <div>
                <div className="text-xs uppercase tracking-[0.18em]" style={{ color: 'var(--color-text-tertiary)' }}>
                  Domain Registry
                </div>
                <div className="text-xl font-semibold mt-1" style={{ color: 'var(--color-text)' }}>
                  {data ? `${data.ready_count}/${data.service_count} services ready` : loading ? 'Checking services' : 'Unavailable'}
                </div>
              </div>
            </div>
            <StatusBadge ready={data?.status === 'ready'}>{data?.status || 'checking'}</StatusBadge>
          </div>
        </section>

        {error && (
          <div
            className="rounded-xl px-4 py-3 mb-5 text-sm flex items-center gap-2"
            style={{ color: 'var(--color-error)', background: 'var(--color-bg-secondary)', border: '1px solid var(--color-error)' }}
          >
            <AlertTriangle size={16} />
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {(data?.services || []).map((service) => (
            <section
              key={service.service}
              className="rounded-2xl p-4"
              style={{
                background: 'color-mix(in srgb, var(--color-bg-secondary) 78%, transparent)',
                border: '1px solid color-mix(in srgb, var(--color-accent) 14%, var(--color-border))',
                boxShadow: '0 18px 44px -38px var(--color-accent)',
              }}
            >
              <div className="flex items-start gap-3">
                <div className="rounded-xl p-2" style={{ color: 'var(--color-accent-amber)', background: 'var(--color-accent-subtle)' }}>
                  <ShieldCheck size={18} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-3">
                    <h2 className="text-sm font-semibold capitalize" style={{ color: 'var(--color-text)' }}>
                      {service.service}
                    </h2>
                    <StatusBadge ready={service.ready}>{service.ready ? 'ready' : 'limited'}</StatusBadge>
                  </div>
                  <div className="mt-3 space-y-1">
                    <Detail label="Actions" value={Object.keys(service.risk_levels || {}).slice(0, 6).join(', ') || 'none'} />
                    <Detail label="Risk" value={Object.values(service.risk_levels || {}).filter((v, i, a) => a.indexOf(v) === i).join(', ') || 'unknown'} />
                    <Detail label="Dependencies" value={formatDependencies(service.dependencies)} />
                  </div>
                </div>
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
      <span style={{ color: 'var(--color-text-tertiary)' }}>{label}: </span>
      {value}
    </div>
  );
}

function StatusBadge({ ready, children }: { ready: boolean; children: string }) {
  const color = ready ? 'var(--color-success)' : 'var(--color-warning)';
  return (
    <span
      className="rounded-full px-2 py-1 text-[10px] uppercase tracking-[0.14em]"
      style={{
        color,
        background: 'color-mix(in srgb, currentColor 12%, transparent)',
        border: '1px solid color-mix(in srgb, currentColor 32%, transparent)',
      }}
    >
      {children}
    </span>
  );
}

function formatDependencies(value: unknown): string {
  if (Array.isArray(value)) return value.join(', ') || 'none';
  if (value && typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => `${key}: ${item ? 'ready' : 'missing'}`)
      .join(', ');
  }
  return 'none';
}
