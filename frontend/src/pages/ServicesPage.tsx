import { useEffect, useState } from 'react';
import { Activity, CheckCircle2, RefreshCw, Server, ShieldAlert } from 'lucide-react';
import { fetchApiServices, type ApiServiceDiagnostic, type ApiServicesResponse } from '../lib/api';

export function ServicesPage() {
  const [data, setData] = useState<ApiServicesResponse | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const refresh = () => {
    setLoading(true);
    setError('');
    fetchApiServices()
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load services'))
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []);

  return (
    <div className="h-full overflow-y-auto px-6 py-6" style={{ color: 'var(--color-text)' }}>
      <div className="mx-auto flex max-w-6xl flex-col gap-5">
        <header className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent-amber)' }}>
            <Server size={16} />
            Service Layer
          </div>
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="text-2xl font-semibold">API Services</h1>
              <p className="mt-2 max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                Grandpa routes now call focused service facades before reaching domain runtimes. This view shows which facades are ready and what they depend on.
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
          <Metric icon={Server} label="Services" value={String(data?.service_count ?? 0)} />
          <Metric icon={CheckCircle2} label="Ready" value={String(data?.ready_count ?? 0)} />
          <Metric icon={Activity} label="Status" value={data?.status || 'checking'} />
          <Metric icon={ShieldAlert} label="Local Only" value={data?.local_only === false ? 'no' : 'yes'} />
        </section>

        <section className="grid gap-3 lg:grid-cols-2">
          {(data?.services || []).map((service) => (
            <ServiceCard key={service.name} service={service} />
          ))}
        </section>
      </div>
    </div>
  );
}

function ServiceCard({ service }: { service: ApiServiceDiagnostic }) {
  const status = String(service.health?.status || (service.ready ? 'ready' : 'partial'));
  return (
    <article className="rounded-2xl p-4" style={panelStyle}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">{service.name}</h2>
          <p className="mt-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>{service.description}</p>
        </div>
        <span className="rounded-lg px-2 py-1 text-xs font-semibold" style={{ color: statusColor(service), border: `1px solid ${statusColor(service)}` }}>
          {status}
        </span>
      </div>

      <div className="mt-4 grid gap-2 text-sm">
        <InfoRow label="Readiness" value={service.ready ? 'ready' : 'partial'} />
        <InfoRow label="Dependencies" value={compactJson(service.dependencies)} />
        <InfoRow label="Last diagnostics" value={compactJson(service.diagnostics)} />
      </div>
    </article>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl px-3 py-2" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
      <div className="text-xs uppercase tracking-[0.18em]" style={{ color: 'var(--color-text-tertiary)' }}>{label}</div>
      <div className="mt-1 break-words text-sm" style={{ color: 'var(--color-text-secondary)' }}>{value}</div>
    </div>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof Server; label: string; value: string }) {
  return (
    <div className="rounded-2xl p-4" style={panelStyle}>
      <Icon size={18} style={{ color: 'var(--color-accent)' }} />
      <div className="mt-3 text-xs uppercase tracking-[0.18em]" style={{ color: 'var(--color-text-tertiary)' }}>{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

function statusColor(service: ApiServiceDiagnostic) {
  return service.ready ? 'var(--color-success)' : 'var(--color-warning)';
}

function compactJson(value: unknown): string {
  if (!value || (typeof value === 'object' && Object.keys(value as Record<string, unknown>).length === 0)) {
    return 'none reported';
  }
  const text = JSON.stringify(value);
  return text.length > 180 ? `${text.slice(0, 177)}...` : text;
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
