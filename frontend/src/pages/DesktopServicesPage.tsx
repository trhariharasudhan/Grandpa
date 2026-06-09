import { useEffect, useState } from 'react';
import { AlertTriangle, BrainCircuit, History, MonitorCog, MousePointer2, RefreshCw, Route, ShieldCheck } from 'lucide-react';
import {
  fetchDesktopControlDiagnostics,
  fetchDesktopOperatorDiagnostics,
  fetchDesktopOperatorTasks,
  planDesktopOperatorTask,
  type DesktopControlDiagnostics,
  type DesktopOperatorDiagnostics,
  type DesktopOperatorPlanResponse,
  type DesktopOperatorTask,
} from '../lib/api';

export function DesktopServicesPage() {
  const [data, setData] = useState<DesktopControlDiagnostics | null>(null);
  const [operator, setOperator] = useState<DesktopOperatorDiagnostics | null>(null);
  const [operatorTasks, setOperatorTasks] = useState<DesktopOperatorTask[]>([]);
  const [operatorRequest, setOperatorRequest] = useState('open terminal in VS Code');
  const [operatorPlan, setOperatorPlan] = useState<DesktopOperatorPlanResponse | null>(null);
  const [planning, setPlanning] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [control, operatorDiagnostics, tasks] = await Promise.all([
        fetchDesktopControlDiagnostics(),
        fetchDesktopOperatorDiagnostics(),
        fetchDesktopOperatorTasks(8),
      ]);
      setData(control);
      setOperator(operatorDiagnostics);
      setOperatorTasks(tasks.tasks || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load desktop services');
    } finally {
      setLoading(false);
    }
  };

  const planOperatorTask = async () => {
    const request = operatorRequest.trim();
    if (!request) return;
    setPlanning(true);
    setError(null);
    try {
      const plan = await planDesktopOperatorTask(request);
      setOperatorPlan(plan);
      const tasks = await fetchDesktopOperatorTasks(8);
      setOperatorTasks(tasks.tasks || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to plan desktop operator task');
    } finally {
      setPlanning(false);
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

        <section
          className="rounded-2xl p-4 mb-5"
          style={{
            background: 'linear-gradient(135deg, color-mix(in srgb, var(--color-accent) 16%, var(--color-bg-secondary)), color-mix(in srgb, var(--color-bg-secondary) 82%, transparent))',
            border: '1px solid color-mix(in srgb, var(--color-accent) 24%, var(--color-border))',
            boxShadow: '0 24px 70px -52px var(--color-accent)',
          }}
        >
          <div className="grid grid-cols-1 xl:grid-cols-[1.05fr_0.95fr] gap-5">
            <div>
              <div className="flex items-center gap-3 mb-4">
                <div className="rounded-xl p-2" style={{ color: 'var(--color-accent-amber)', background: 'var(--color-accent-subtle)' }}>
                  <MousePointer2 size={19} />
                </div>
                <div>
                  <h2 className="text-base font-semibold" style={{ color: 'var(--color-text)' }}>
                    Desktop Operator
                  </h2>
                  <p className="text-xs mt-1" style={{ color: 'var(--color-text-secondary)' }}>
                    Plans visible UI tasks with app profiles, confidence checks, bounded retries, and approval-gated actions.
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-4">
                <Metric label="Profiles" value={String(operator?.profile_count ?? 0)} />
                <Metric label="Min confidence" value={String(operator?.visual_targeting?.minimum_confidence ?? 'n/a')} />
                <Metric label="Retry cap" value={String(operator?.visual_targeting?.max_retries ?? 'n/a')} />
              </div>

              <div className="flex flex-col sm:flex-row gap-2">
                <input
                  value={operatorRequest}
                  onChange={(event) => setOperatorRequest(event.target.value)}
                  className="min-w-0 flex-1 rounded-xl px-3 py-2 text-sm outline-none"
                  style={{
                    color: 'var(--color-text)',
                    background: 'color-mix(in srgb, var(--color-bg) 72%, transparent)',
                    border: '1px solid var(--color-border)',
                  }}
                  placeholder="Plan a desktop task"
                />
                <button
                  type="button"
                  onClick={planOperatorTask}
                  disabled={planning}
                  className="inline-flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm transition-colors disabled:opacity-60"
                  style={{
                    color: 'var(--color-bg)',
                    background: 'var(--color-accent-amber)',
                    border: '1px solid color-mix(in srgb, var(--color-accent-amber) 52%, transparent)',
                  }}
                >
                  <Route size={15} />
                  {planning ? 'Planning' : 'Plan'}
                </button>
              </div>
            </div>

            <div
              className="rounded-xl p-3"
              style={{
                background: 'color-mix(in srgb, var(--color-bg) 52%, transparent)',
                border: '1px solid color-mix(in srgb, var(--color-accent) 18%, var(--color-border))',
              }}
            >
              <div className="flex items-center gap-2 mb-3">
                <BrainCircuit size={16} style={{ color: 'var(--color-accent-amber)' }} />
                <div className="text-xs uppercase tracking-[0.16em]" style={{ color: 'var(--color-text-tertiary)' }}>
                  Current Plan
                </div>
              </div>
              {operatorPlan ? (
                <div className="space-y-2">
                  <div className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
                    {operatorPlan.task.result_summary}
                  </div>
                  {operatorPlan.plan.map((step) => (
                    <div key={step.step_id} className="flex items-start justify-between gap-3 text-xs">
                      <span style={{ color: 'var(--color-text-secondary)' }}>{step.title}</span>
                      <StatusBadge ready={step.risk_level === 'LOW'}>{step.approval_required ? 'approval' : step.risk_level}</StatusBadge>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                  Try planning "open terminal in VS Code" or "detect active app and suggest actions".
                </div>
              )}
            </div>
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

        <section
          className="rounded-2xl p-4 mt-5"
          style={{
            background: 'color-mix(in srgb, var(--color-bg-secondary) 78%, transparent)',
            border: '1px solid color-mix(in srgb, var(--color-accent) 14%, var(--color-border))',
          }}
        >
          <div className="flex items-center gap-2 mb-3">
            <History size={16} style={{ color: 'var(--color-accent-amber)' }} />
            <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
              Operator History
            </h2>
          </div>
          <div className="space-y-2">
            {operatorTasks.length ? (
              operatorTasks.map((task) => (
                <div key={task.task_id} className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 rounded-xl px-3 py-2" style={{ background: 'color-mix(in srgb, var(--color-bg) 48%, transparent)' }}>
                  <div className="min-w-0">
                    <div className="text-sm truncate" style={{ color: 'var(--color-text)' }}>
                      {task.user_request}
                    </div>
                    <div className="text-xs truncate" style={{ color: 'var(--color-text-secondary)' }}>
                      {task.result_summary}
                    </div>
                  </div>
                  <StatusBadge ready={task.status === 'planned' || task.status === 'completed'}>{task.status}</StatusBadge>
                </div>
              ))
            ) : (
              <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                No operator tasks recorded yet.
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div
      className="rounded-xl px-3 py-2"
      style={{
        background: 'color-mix(in srgb, var(--color-bg) 45%, transparent)',
        border: '1px solid color-mix(in srgb, var(--color-border) 80%, transparent)',
      }}
    >
      <div className="text-[10px] uppercase tracking-[0.14em]" style={{ color: 'var(--color-text-tertiary)' }}>
        {label}
      </div>
      <div className="text-sm font-semibold mt-1" style={{ color: 'var(--color-text)' }}>
        {value}
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
