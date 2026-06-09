import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, ClipboardCheck, Gauge, RefreshCw, ShieldCheck, Smartphone } from 'lucide-react';
import { fetchProductionAuditLatest, type ProductionAuditCheck, type ProductionAuditReport } from '../lib/api';

export function AuditPage() {
  const [report, setReport] = useState<ProductionAuditReport | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const refresh = () => {
    setLoading(true);
    setError('');
    fetchProductionAuditLatest()
      .then(setReport)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load production audit'))
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []);

  const checks = report?.feature_matrix || [];
  const grouped = useMemo(() => {
    const map = new Map<string, ProductionAuditCheck[]>();
    checks.forEach((check) => {
      const list = map.get(check.feature_area) || [];
      list.push(check);
      map.set(check.feature_area, list);
    });
    return Array.from(map.entries());
  }, [checks]);

  const statusColor = report?.pass ? 'var(--color-success)' : report?.overall_status === 'not_run' ? 'var(--color-warning)' : 'var(--color-danger)';

  return (
    <div className="h-full overflow-y-auto px-6 py-6" style={{ color: 'var(--color-text)' }}>
      <div className="mx-auto flex max-w-6xl flex-col gap-5">
        <header className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent-amber)' }}>
              <ClipboardCheck size={16} />
              Real-Device Production Audit
            </div>
            <h1 className="mt-2 text-2xl font-semibold">Production Readiness Audit</h1>
            <p className="mt-2 max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              Hardware-aware validation for browser extension, voice, desktop operator, mobile companion, agents, knowledge, and memory.
            </p>
          </div>
          <button className="flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-medium" style={secondaryButton} onClick={refresh}>
            <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </header>

        {error && (
          <div className="rounded-xl px-4 py-3 text-sm" style={{ border: '1px solid var(--color-danger)', color: 'var(--color-danger)' }}>
            {error}
          </div>
        )}

        <section className="rounded-2xl p-5" style={{ ...panelStyle, borderColor: statusColor }}>
          <div className="grid gap-5 md:grid-cols-[1.5fr_1fr]">
            <div>
              <div className="text-xs uppercase tracking-[0.2em]" style={{ color: 'var(--color-text-tertiary)' }}>Readiness verdict</div>
              <div className="mt-2 text-3xl font-semibold" style={{ color: statusColor }}>{report?.overall_status || 'checking'}</div>
              <p className="mt-2 max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {report?.readiness_verdict || report?.recommendation || report?.message || 'Run scripts/production_audit.py to generate a measured report.'}
              </p>
            </div>
            <div className="grid gap-2 text-sm">
              <Row label="Finished" value={report?.finished_at || 'not run'} />
              <Row label="Report" value={report?.report_path || 'runtime/reports/production-audit.json'} />
              <Row label="Duration" value={report?.duration_seconds ? `${report.duration_seconds}s` : 'unmeasured'} />
            </div>
          </div>
        </section>

        <section className="grid gap-3 md:grid-cols-5">
          <Metric icon={Gauge} label="Score" value={`${report?.score ?? 0}`} />
          <Metric icon={ShieldCheck} label="Core Score" value={`${report?.core_score ?? 0}`} />
          <Metric icon={ClipboardCheck} label="Validated" value={String(report?.summary?.validated ?? 0)} />
          <Metric icon={AlertTriangle} label="Partial / Pending" value={String((report?.summary?.partially_validated ?? 0) + (report?.summary?.unvalidated ?? 0))} />
          <Metric icon={Smartphone} label="Hardware Dep." value={String(report?.summary?.hardware_dependent ?? 0)} />
        </section>

        <section className="rounded-2xl p-4" style={panelStyle}>
          <h2 className="text-sm font-semibold">Feature Matrix</h2>
          <div className="mt-3 grid gap-4 lg:grid-cols-2">
            {grouped.length === 0 ? (
              <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>No audit checks have been recorded yet.</p>
            ) : (
              grouped.map(([area, items]) => (
                <div key={area} className="rounded-2xl p-4" style={rowStyle}>
                  <div className="flex items-center justify-between gap-3">
                    <h3 className="text-sm font-semibold">{area}</h3>
                    <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{items.length} checks</span>
                  </div>
                  <div className="mt-3 flex flex-col gap-2">
                    {items.map((item) => <CheckRow key={`${area}-${item.name}`} check={item} />)}
                  </div>
                </div>
              ))
            )}
          </div>
        </section>

        <section className="rounded-2xl p-4" style={panelStyle}>
          <h2 className="text-sm font-semibold">Limitations and Recommendations</h2>
          <div className="mt-3 flex flex-col gap-2">
            {(report?.known_limitations || []).length === 0 ? (
              <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>No limitations recorded.</p>
            ) : (
              (report?.known_limitations || []).map((item) => (
                <div key={`${item.feature_area}-${item.name}`} className="rounded-xl px-3 py-2 text-sm" style={rowStyle}>
                  <div className="font-medium">{item.name}</div>
                  <p className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>{(item.limitations || []).join(' ')}</p>
                  {item.recommendation && <p className="mt-1 text-xs" style={{ color: 'var(--color-accent-amber)' }}>{item.recommendation}</p>}
                </div>
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function CheckRow({ check }: { check: ProductionAuditCheck }) {
  return (
    <div className="rounded-xl px-3 py-2 text-sm" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>{check.name}</span>
        <span className="rounded-full px-2 py-0.5 text-[11px] uppercase" style={{ color: statusColor(check.status), background: 'var(--color-bg-tertiary)' }}>
          {check.status.replace(/_/g, ' ')}
        </span>
      </div>
      <p className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>{check.summary}</p>
      {check.hardware_dependent && <p className="mt-1 text-xs" style={{ color: 'var(--color-accent-amber)' }}>Requires real hardware/session validation.</p>}
    </div>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof Gauge; label: string; value: string }) {
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
    <div className="flex items-center justify-between gap-3 rounded-xl px-3 py-2" style={rowStyle}>
      <span style={{ color: 'var(--color-text-tertiary)' }}>{label}</span>
      <span className="text-right">{value}</span>
    </div>
  );
}

function statusColor(status: string) {
  if (status === 'validated') return 'var(--color-success)';
  if (status === 'partially_validated') return 'var(--color-warning)';
  if (status === 'unvalidated') return 'var(--color-accent-amber)';
  return 'var(--color-danger)';
}

const panelStyle = {
  background: 'color-mix(in srgb, var(--color-bg-secondary) 78%, transparent)',
  border: '1px solid var(--color-border)',
  boxShadow: '0 24px 80px -55px var(--color-accent)',
};

const rowStyle = {
  background: 'var(--color-bg-secondary)',
  border: '1px solid var(--color-border)',
};

const secondaryButton = {
  background: 'var(--color-bg-secondary)',
  border: '1px solid var(--color-border)',
};
