import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, Database, KeyRound, RefreshCw, ShieldCheck, Zap } from 'lucide-react';
import { fetchDesktopKernelDiagnostics, type DesktopKernelDiagnostics } from '../lib/api';

export function DesktopKernelPage() {
  const [data, setData] = useState<DesktopKernelDiagnostics | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const refresh = () => {
    setLoading(true);
    setError('');
    fetchDesktopKernelDiagnostics()
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load desktop kernel diagnostics'))
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []);

  return (
    <div className="h-full overflow-y-auto px-6 py-6" style={{ color: 'var(--color-text)' }}>
      <div className="mx-auto flex max-w-6xl flex-col gap-5">
        <header className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent-amber)' }}>
            <ShieldCheck size={16} />
            PC Control Kernel
          </div>
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="text-2xl font-semibold">Desktop Kernel</h1>
              <p className="mt-2 max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                Approval lifecycle, audit retention, risk policy, request normalization, execution readiness, and emergency stop state for Grandpa PC control.
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
          <Metric icon={CheckCircle2} label="Status" value={data?.status || 'checking'} />
          <Metric icon={KeyRound} label="Pending" value={String((data?.approvals?.counts as Record<string, number> | undefined)?.pending ?? 0)} />
          <Metric icon={Zap} label="Emergency" value={data?.emergency?.active ? 'active' : 'clear'} />
          <Metric icon={Database} label="Local Only" value={data?.local_only === false ? 'no' : 'yes'} />
        </section>

        <section className="grid gap-3 lg:grid-cols-2">
          <KernelCard title="Approvals" icon={KeyRound} data={data?.approvals} />
          <KernelCard title="Audits" icon={Database} data={data?.audits} />
          <KernelCard title="Risk Engine" icon={AlertTriangle} data={data?.risk} />
          <KernelCard title="Execution" icon={Zap} data={data?.execution} />
          <KernelCard title="Requests" icon={ShieldCheck} data={data?.requests} />
          <KernelCard title="Emergency Stop" icon={AlertTriangle} data={data?.emergency} />
        </section>
      </div>
    </div>
  );
}

function KernelCard({ title, icon: Icon, data }: { title: string; icon: typeof ShieldCheck; data?: Record<string, unknown> }) {
  return (
    <article className="rounded-2xl p-4" style={panelStyle}>
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Icon size={18} style={{ color: 'var(--color-accent)' }} />
          <h2 className="font-semibold">{title}</h2>
        </div>
        <span className="rounded-lg px-2 py-1 text-xs font-semibold" style={{ color: statusColor(data), border: `1px solid ${statusColor(data)}` }}>
          {String(data?.status || 'unknown')}
        </span>
      </div>
      <pre className="mt-4 max-h-52 overflow-auto whitespace-pre-wrap rounded-xl p-3 text-xs" style={{ background: 'var(--color-bg-secondary)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}>
        {JSON.stringify(data || {}, null, 2)}
      </pre>
    </article>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof ShieldCheck; label: string; value: string }) {
  return (
    <div className="rounded-2xl p-4" style={panelStyle}>
      <Icon size={18} style={{ color: 'var(--color-accent)' }} />
      <div className="mt-3 text-xs uppercase tracking-[0.18em]" style={{ color: 'var(--color-text-tertiary)' }}>{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

function statusColor(data?: Record<string, unknown>) {
  return data?.status === 'failed' ? 'var(--color-danger)' : 'var(--color-success)';
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
