import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, CheckCircle2, Rocket, ShieldCheck, SkipForward } from 'lucide-react';
import { fetchReleaseGateLatest, type ReleaseGateCheck, type ReleaseGateReport } from '../lib/api';

export function ReleaseGatePage() {
  const [report, setReport] = useState<ReleaseGateReport | null>(null);
  const [error, setError] = useState('');

  const refresh = () => {
    fetchReleaseGateLatest()
      .then(setReport)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load release gate report'));
  };

  useEffect(refresh, []);

  const checks = report?.checks || [];
  const statusColor = report?.pass ? 'var(--color-success)' : report?.status === 'not_run' ? 'var(--color-warning)' : 'var(--color-danger)';
  const commitText = useMemo(() => {
    if (!report) return 'checking';
    if (report.status === 'not_run') return 'run gate first';
    if (report.ready_to_push) return 'ready to push';
    if (report.ready_to_commit) return 'commit first';
    return 'blocked';
  }, [report]);

  return (
    <div className="h-full overflow-y-auto px-6 py-6" style={{ color: 'var(--color-text)' }}>
      <div className="mx-auto flex max-w-6xl flex-col gap-5">
        <header className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent-amber)' }}>
            <Rocket size={16} />
            Production Release Gate
          </div>
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="text-2xl font-semibold">Final Health Dashboard</h1>
              <p className="mt-2 max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                Latest release-readiness report for daily use, packaging, commit, and push decisions.
              </p>
            </div>
            <button className="rounded-xl px-4 py-2 text-sm font-medium" style={secondaryButton} onClick={refresh}>
              Refresh
            </button>
          </div>
        </header>

        {error && (
          <div className="rounded-xl px-4 py-3 text-sm" style={{ border: '1px solid var(--color-danger)', color: 'var(--color-danger)' }}>
            {error}
          </div>
        )}

        <section className="rounded-2xl p-5" style={{ ...panelStyle, borderColor: statusColor }}>
          <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="text-xs uppercase tracking-[0.2em]" style={{ color: 'var(--color-text-tertiary)' }}>Overall readiness</div>
              <div className="mt-2 text-3xl font-semibold" style={{ color: statusColor }}>{report?.overall_status || 'checking'}</div>
              <p className="mt-2 max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {report?.recommendation || report?.message || 'Run the final release gate script to generate a report.'}
              </p>
            </div>
            <div className="grid gap-2 text-sm">
              <Row label="Last run" value={report?.finished_at || 'not run'} />
              <Row label="Commit / push" value={commitText} />
              <Row label="Report" value={report?.report_path || 'runtime/reports/final-release-gate.json'} />
            </div>
          </div>
        </section>

        <section className="grid gap-3 md:grid-cols-4">
          <Metric icon={CheckCircle2} label="Passed" value={String(report?.summary?.passed ?? 0)} />
          <Metric icon={AlertTriangle} label="Warnings" value={String(report?.summary?.warnings ?? 0)} />
          <Metric icon={ShieldCheck} label="Blockers" value={String(report?.summary?.blockers ?? 0)} />
          <Metric icon={SkipForward} label="Optional Skipped" value={String(report?.summary?.skipped_optional ?? 0)} />
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <ListPanel title="Blockers" items={report?.blockers || []} empty="No blocking release issues." danger />
          <ListPanel title="Warnings / Known Non-Blockers" items={report?.warnings || []} empty="No warnings recorded." />
        </section>

        <section className="rounded-2xl p-4" style={panelStyle}>
          <h2 className="text-sm font-semibold">Validation Matrix</h2>
          <div className="mt-3 flex flex-col gap-2">
            {checks.length === 0 ? (
              <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>No gate checks have been recorded yet.</p>
            ) : (
              checks.map((check) => <CheckRow key={check.name} check={check} />)
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function ListPanel({ title, items, empty, danger = false }: { title: string; items: ReleaseGateCheck[]; empty: string; danger?: boolean }) {
  return (
    <section className="rounded-2xl p-4" style={panelStyle}>
      <h2 className="text-sm font-semibold">{title}</h2>
      <div className="mt-3 flex flex-col gap-2">
        {items.length === 0 ? (
          <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>{empty}</p>
        ) : (
          items.map((item) => (
            <div key={item.name} className="rounded-xl p-3 text-sm" style={{ background: 'var(--color-bg-secondary)', border: `1px solid ${danger ? 'var(--color-danger)' : 'var(--color-border)'}` }}>
              <div className="font-medium">{item.name}</div>
              <p className="mt-1" style={{ color: 'var(--color-text-secondary)' }}>{item.summary}</p>
              {item.warning_classification && <p className="mt-1 text-xs" style={{ color: 'var(--color-accent-amber)' }}>{item.warning_classification}</p>}
            </div>
          ))
        )}
      </div>
    </section>
  );
}

function CheckRow({ check }: { check: ReleaseGateCheck }) {
  return (
    <div className="rounded-xl px-3 py-2 text-sm" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
      <div className="flex items-center justify-between gap-3">
        <span>{check.name}</span>
        <span style={{ color: statusColor(check.status) }}>{check.status}</span>
      </div>
      <p className="mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{check.summary}</p>
    </div>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof CheckCircle2; label: string; value: string }) {
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

function statusColor(status: string) {
  if (status === 'pass') return 'var(--color-success)';
  if (status === 'warn' || status === 'skipped') return 'var(--color-warning)';
  return 'var(--color-danger)';
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
