import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  Octagon,
  RefreshCw,
  ShieldCheck,
  ShieldAlert,
  XCircle,
  ZapOff,
} from 'lucide-react';
import {
  approveStructuredLocalAction,
  emergencyStopStructuredLocalActions,
  fetchStructuredLocalActionAudit,
  fetchStructuredLocalActionPending,
  rejectStructuredLocalAction,
  type PcRiskLevel,
  type StructuredLocalActionAuditEntry,
  type StructuredLocalActionPending,
} from '../lib/api';

const RISK_STYLES: Record<PcRiskLevel, { color: string; background: string; border: string }> = {
  LOW: {
    color: 'var(--color-success)',
    background: 'color-mix(in srgb, var(--color-success) 12%, transparent)',
    border: 'color-mix(in srgb, var(--color-success) 28%, transparent)',
  },
  MEDIUM: {
    color: 'var(--color-accent-amber)',
    background: 'var(--color-accent-amber-subtle)',
    border: 'color-mix(in srgb, var(--color-accent-amber) 32%, transparent)',
  },
  HIGH: {
    color: 'var(--color-error)',
    background: 'color-mix(in srgb, var(--color-error) 12%, transparent)',
    border: 'color-mix(in srgb, var(--color-error) 32%, transparent)',
  },
  BLOCKED: {
    color: 'var(--color-text)',
    background: 'color-mix(in srgb, var(--color-text) 10%, transparent)',
    border: 'color-mix(in srgb, var(--color-text) 22%, transparent)',
  },
};

function formatTime(seconds: number): string {
  if (!seconds) return 'Unknown';
  return new Date(seconds * 1000).toLocaleString([], {
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function RiskBadge({ level }: { level: PcRiskLevel | string }) {
  const style = RISK_STYLES[(level as PcRiskLevel) || 'LOW'] || RISK_STYLES.LOW;
  return (
    <span
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold"
      style={{ color: style.color, background: style.background, border: `1px solid ${style.border}` }}
    >
      {level || 'LOW'}
    </span>
  );
}

function StatusPill({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const color =
    normalized.includes('blocked') || normalized.includes('failed')
      ? 'var(--color-error)'
      : normalized.includes('approval') || normalized.includes('pending')
        ? 'var(--color-accent-amber)'
        : 'var(--color-success)';
  return (
    <span className="inline-flex items-center gap-1 text-xs" style={{ color }}>
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {status || 'unknown'}
    </span>
  );
}

function SafetyCard({
  icon: Icon,
  title,
  copy,
}: {
  icon: typeof ShieldCheck;
  title: string;
  copy: string;
}) {
  return (
    <div
      className="rounded-xl p-4"
      style={{
        background: 'color-mix(in srgb, var(--color-surface) 82%, transparent)',
        border: '1px solid var(--color-border)',
        boxShadow: 'var(--shadow-sm)',
      }}
    >
      <div className="flex items-start gap-3">
        <div
          className="rounded-lg p-2"
          style={{
            background: 'var(--color-accent-subtle)',
            color: 'var(--color-accent)',
          }}
        >
          <Icon size={17} />
        </div>
        <div>
          <div className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
            {title}
          </div>
          <p className="mt-1 text-xs leading-relaxed" style={{ color: 'var(--color-text-secondary)' }}>
            {copy}
          </p>
        </div>
      </div>
    </div>
  );
}

export function SafetyPage() {
  const [pending, setPending] = useState<StructuredLocalActionPending[]>([]);
  const [audit, setAudit] = useState<StructuredLocalActionAuditEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setError(null);
    try {
      const [pendingActions, auditEntries] = await Promise.all([
        fetchStructuredLocalActionPending(),
        fetchStructuredLocalActionAudit(100),
      ]);
      setPending(pendingActions);
      setAudit(auditEntries.slice().reverse());
    } catch {
      setError('Could not load the safety console. Check that the Grandpa backend is running.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = window.setInterval(refresh, 10000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  const counts = useMemo(() => {
    return audit.reduce(
      (acc, entry) => {
        acc.total += 1;
        if (entry.risk_level === 'HIGH') acc.high += 1;
        if (entry.risk_level === 'BLOCKED' || entry.status === 'blocked') acc.blocked += 1;
        return acc;
      },
      { total: 0, high: 0, blocked: 0 },
    );
  }, [audit]);

  const decide = async (actionId: string, decision: 'approve' | 'reject') => {
    setBusyId(actionId);
    setNotice(null);
    setError(null);
    try {
      const result =
        decision === 'approve'
          ? await approveStructuredLocalAction(actionId)
          : await rejectStructuredLocalAction(actionId);
      setNotice(result.message);
      await refresh();
    } catch {
      setError(`Could not ${decision} that action.`);
    } finally {
      setBusyId(null);
    }
  };

  const emergencyStop = async () => {
    setBusyId('emergency-stop');
    setNotice(null);
    setError(null);
    try {
      const result = await emergencyStopStructuredLocalActions();
      setNotice(result.message);
      await refresh();
    } catch {
      setError('Emergency stop could not be activated.');
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto px-6 py-8">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">
        <header className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="flex items-center gap-3">
              <div
                className="rounded-xl p-2.5"
                style={{
                  color: 'var(--color-accent-amber)',
                  background: 'var(--color-accent-amber-subtle)',
                  boxShadow: '0 0 28px -16px var(--color-accent-amber)',
                }}
              >
                <ShieldCheck size={22} />
              </div>
              <div>
                <h1 className="text-xl font-semibold" style={{ color: 'var(--color-text)' }}>
                  Safety Console
                </h1>
                <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                  Inspect PC-control requests, approvals, and redacted local action history.
                </p>
              </div>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={refresh}
              className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm transition-colors"
              style={{ color: 'var(--color-text-secondary)', background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
            >
              <RefreshCw size={14} /> Refresh
            </button>
            <button
              type="button"
              onClick={emergencyStop}
              disabled={busyId === 'emergency-stop'}
              className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold transition-colors disabled:opacity-60"
              style={{
                color: 'var(--color-error)',
                background: 'color-mix(in srgb, var(--color-error) 10%, transparent)',
                border: '1px solid color-mix(in srgb, var(--color-error) 28%, transparent)',
              }}
            >
              <ZapOff size={14} /> Emergency Stop
            </button>
          </div>
        </header>

        <div className="grid gap-3 md:grid-cols-3">
          <SafetyCard icon={CheckCircle2} title="Safe actions" copy="Low-risk actions, such as opening an allowlisted app, can run automatically and are recorded." />
          <SafetyCard icon={ShieldAlert} title="Risky actions" copy="Medium and high-risk actions can be staged for review before Grandpa executes them." />
          <SafetyCard icon={Octagon} title="Blocked actions" copy="Dangerous actions and protected paths are blocked by policy and never run directly." />
        </div>

        {(error || notice) && (
          <div
            className="rounded-xl px-4 py-3 text-sm"
            style={{
              color: error ? 'var(--color-error)' : 'var(--color-success)',
              background: error ? 'color-mix(in srgb, var(--color-error) 10%, transparent)' : 'color-mix(in srgb, var(--color-success) 10%, transparent)',
              border: `1px solid ${error ? 'color-mix(in srgb, var(--color-error) 24%, transparent)' : 'color-mix(in srgb, var(--color-success) 24%, transparent)'}`,
            }}
          >
            {error || notice}
          </div>
        )}

        <section
          className="rounded-xl p-5"
          style={{
            background: 'color-mix(in srgb, var(--color-surface) 88%, transparent)',
            border: '1px solid var(--color-border)',
            boxShadow: 'var(--shadow-md)',
          }}
        >
          <div className="mb-4 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                Pending Approvals
              </h2>
              <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                Review staged PC actions before they run.
              </p>
            </div>
            <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              {pending.length} waiting
            </span>
          </div>

          {loading ? (
            <div className="py-8 text-sm" style={{ color: 'var(--color-text-secondary)' }}>Loading safety state...</div>
          ) : pending.length === 0 ? (
            <div
              className="rounded-xl px-4 py-8 text-center text-sm"
              style={{ color: 'var(--color-text-tertiary)', background: 'var(--color-bg-secondary)', border: '1px dashed var(--color-border)' }}
            >
              No PC-control approvals are waiting right now.
            </div>
          ) : (
            <div className="space-y-3">
              {pending.map((item) => (
                <div
                  key={item.id}
                  className="flex flex-col gap-3 rounded-xl p-4 lg:flex-row lg:items-center lg:justify-between"
                  style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                >
                  <div className="min-w-0">
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <RiskBadge level={item.risk_level} />
                      <StatusPill status={item.status} />
                      <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                        expires {formatTime(item.expires_at)}
                      </span>
                    </div>
                    <div className="font-mono text-sm" style={{ color: 'var(--color-text)' }}>
                      {item.action_type}
                    </div>
                    <div className="mt-1 truncate text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                      {item.target || 'current target'}
                    </div>
                  </div>
                  <div className="flex shrink-0 items-center gap-2">
                    <button
                      type="button"
                      onClick={() => decide(item.action_id, 'reject')}
                      disabled={busyId === item.action_id}
                      className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold disabled:opacity-60"
                      style={{ color: 'var(--color-text-secondary)', background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}
                    >
                      <XCircle size={13} /> Reject
                    </button>
                    <button
                      type="button"
                      onClick={() => decide(item.action_id, 'approve')}
                      disabled={busyId === item.action_id}
                      className="inline-flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold disabled:opacity-60"
                      style={{ color: 'var(--color-on-accent)', background: 'var(--color-accent)', border: '1px solid var(--color-accent)' }}
                    >
                      <CheckCircle2 size={13} /> Approve
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        <section
          className="rounded-xl p-5"
          style={{
            background: 'color-mix(in srgb, var(--color-surface) 88%, transparent)',
            border: '1px solid var(--color-border)',
            boxShadow: 'var(--shadow-md)',
          }}
        >
          <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                Recent Local Actions
              </h2>
              <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                Redacted audit history from Grandpa's structured PC-control layer.
              </p>
            </div>
            <div className="flex gap-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
              <span>{counts.total} entries</span>
              <span>{counts.high} high-risk</span>
              <span>{counts.blocked} blocked</span>
            </div>
          </div>

          <div className="overflow-hidden rounded-xl" style={{ border: '1px solid var(--color-border)' }}>
            <div className="grid grid-cols-[130px_1fr_100px_110px_100px] gap-3 px-4 py-2 text-[11px] uppercase tracking-[0.14em]" style={{ color: 'var(--color-text-tertiary)', background: 'var(--color-bg-tertiary)' }}>
              <span>Time</span>
              <span>Action</span>
              <span>Risk</span>
              <span>Status</span>
              <span>Decision</span>
            </div>
            {audit.length === 0 ? (
              <div className="px-4 py-10 text-center text-sm" style={{ color: 'var(--color-text-tertiary)', background: 'var(--color-bg-secondary)' }}>
                No structured local action audit entries yet.
              </div>
            ) : (
              <div className="max-h-[420px] overflow-y-auto">
                {audit.map((entry, index) => (
                  <div
                    key={`${entry.timestamp}-${entry.action_type}-${index}`}
                    className="grid grid-cols-[130px_1fr_100px_110px_100px] gap-3 px-4 py-3 text-sm"
                    style={{
                      color: 'var(--color-text-secondary)',
                      background: index % 2 === 0 ? 'var(--color-bg-secondary)' : 'color-mix(in srgb, var(--color-bg-secondary) 70%, transparent)',
                      borderTop: index === 0 ? 'none' : '1px solid var(--color-border-subtle)',
                    }}
                  >
                    <span className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{formatTime(entry.timestamp)}</span>
                    <span className="min-w-0">
                      <span className="block font-mono" style={{ color: 'var(--color-text)' }}>{entry.action_type}</span>
                      <span className="block truncate text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{entry.target || 'current target'}</span>
                    </span>
                    <RiskBadge level={entry.risk_level} />
                    <StatusPill status={entry.status} />
                    <span className="truncate text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{entry.decision || 'none'}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </section>

        <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          <AlertTriangle size={13} />
          Clipboard content and secret-like targets are redacted before they appear in this console.
        </div>
      </div>
    </div>
  );
}
