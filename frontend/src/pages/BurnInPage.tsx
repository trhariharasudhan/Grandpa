import { useEffect, useMemo, useState } from 'react';
import { Activity, AlertTriangle, CheckCircle2, Clock3, Flame, Gauge, RefreshCw } from 'lucide-react';
import { fetchBurnInLatest, type BurnInReport, type BurnInResult } from '../lib/api';

export function BurnInPage() {
  const [report, setReport] = useState<BurnInReport | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const refresh = () => {
    setLoading(true);
    setError('');
    fetchBurnInLatest()
      .then(setReport)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load burn-in report'))
      .finally(() => setLoading(false));
  };

  useEffect(refresh, []);

  const results = report?.results || [];
  const categories = useMemo(() => Object.entries(report?.category_scores || {}), [report]);
  const statusColor = report?.pass ? 'var(--color-success)' : report?.overall_status === 'not_run' ? 'var(--color-warning)' : 'var(--color-danger)';

  return (
    <div className="h-full overflow-y-auto px-6 py-6" style={{ color: 'var(--color-text)' }}>
      <div className="mx-auto flex max-w-6xl flex-col gap-5">
        <header className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent-amber)' }}>
              <Flame size={16} />
              Daily-Use Burn-In
            </div>
            <h1 className="mt-2 text-2xl font-semibold">Production Stability Dashboard</h1>
            <p className="mt-2 max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              Measured daily-assistant validation for commands, workflows, memory, mobile, voice, browser, desktop control, and planner behavior.
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
              <div className="text-xs uppercase tracking-[0.2em]" style={{ color: 'var(--color-text-tertiary)' }}>Burn-in status</div>
              <div className="mt-2 text-3xl font-semibold" style={{ color: statusColor }}>{report?.overall_status || 'checking'}</div>
              <p className="mt-2 max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {report?.recommendation || report?.message || 'Run scripts/burnin_daily_use.py to generate a measured report.'}
              </p>
            </div>
            <div className="grid gap-2 text-sm">
              <Row label="Finished" value={report?.finished_at || 'not run'} />
              <Row label="Report" value={report?.report_path || 'runtime/burnin/burnin-report.json'} />
              <Row label="Duration" value={report?.duration_seconds ? `${report.duration_seconds}s` : 'unmeasured'} />
            </div>
          </div>
        </section>

        <section className="grid gap-3 md:grid-cols-4">
          <Metric icon={Gauge} label="Score" value={`${report?.score ?? 0}`} />
          <Metric icon={CheckCircle2} label="Passed" value={String(report?.summary?.passed ?? 0)} />
          <Metric icon={AlertTriangle} label="Warnings" value={String(report?.summary?.warnings ?? 0)} />
          <Metric icon={Clock3} label="Pending" value={String(report?.summary?.pending ?? 0)} />
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <section className="rounded-2xl p-4" style={panelStyle}>
            <h2 className="text-sm font-semibold">Category Scores</h2>
            <div className="mt-3 flex flex-col gap-2">
              {categories.length === 0 ? (
                <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>No category data recorded yet.</p>
              ) : (
                categories.map(([name, score]) => (
                  <div key={name} className="rounded-xl px-3 py-2 text-sm" style={rowStyle}>
                    <div className="flex items-center justify-between">
                      <span className="capitalize">{name}</span>
                      <span style={{ color: score.score >= 80 ? 'var(--color-success)' : 'var(--color-warning)' }}>{score.score}%</span>
                    </div>
                    <p className="mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                      {score.passed} pass · {score.warnings} warn · {score.failed} fail · {score.pending} pending
                      {score.skipped_optional ? ` · ${score.skipped_optional} skipped` : ''}
                    </p>
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="rounded-2xl p-4" style={panelStyle}>
            <h2 className="text-sm font-semibold">Performance Metrics</h2>
            <div className="mt-3 flex flex-col gap-2">
              {Object.entries(report?.performance?.latencies || {}).length === 0 ? (
                <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>No performance metrics recorded yet.</p>
              ) : (
                Object.entries(report?.performance?.latencies || {}).map(([name, value]) => (
                  <Row key={name} label={name} value={`${Number(value).toFixed(2)}s`} />
                ))
              )}
            </div>
          </section>
        </section>

        <section className="rounded-2xl p-4" style={panelStyle}>
          <h2 className="flex items-center gap-2 text-sm font-semibold">
            <Activity size={16} style={{ color: 'var(--color-accent)' }} />
            Scenario Results
          </h2>
          <div className="mt-3 flex flex-col gap-2">
            {results.length === 0 ? (
              <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>No burn-in scenarios have been recorded.</p>
            ) : (
              results.map((item) => <ResultRow key={`${item.category}-${item.name}`} item={item} />)
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function ResultRow({ item }: { item: BurnInResult }) {
  return (
    <div className="rounded-xl px-3 py-2 text-sm" style={rowStyle}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="rounded-full px-2 py-0.5 text-[11px] uppercase" style={{ background: 'var(--color-bg-tertiary)', color: statusColor(item.status) }}>
            {item.status}
          </span>
          <span>{item.name}</span>
        </div>
        <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{item.category} · {item.duration_seconds}s</span>
      </div>
      <p className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>{item.summary}</p>
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
    <div className="flex items-center justify-between gap-3 rounded-xl px-3 py-2 text-sm" style={rowStyle}>
      <span style={{ color: 'var(--color-text-tertiary)' }}>{label}</span>
      <span className="text-right">{value}</span>
    </div>
  );
}

function statusColor(status: string) {
  if (status === 'pass') return 'var(--color-success)';
  if (status === 'pending') return 'var(--color-accent-amber)';
  if (status === 'warn' || status === 'skipped_optional') return 'var(--color-warning)';
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
