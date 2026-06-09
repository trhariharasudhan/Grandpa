import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Activity, Brain, CheckCircle2, PauseCircle, Play, RefreshCw, ShieldAlert, XCircle, Zap } from 'lucide-react';
import {
  cancelAutonomousGoal,
  continueAutonomousGoal,
  createAutonomousGoal,
  fetchAutonomousAgentDiagnostics,
  fetchAutonomousGoalEvents,
  fetchAutonomousGoals,
  type AutonomousAgentEvent,
  type AutonomousAgentGoal,
} from '../lib/api';

const examples = [
  'check Grandpa readiness and report issues',
  'research Python tutorials and summarize them',
  'prepare my coding workspace',
  'organize my downloads folder',
  'summarize current webpage and save notes',
];

const statusColor = (status: string) => {
  if (status === 'completed') return 'var(--color-success)';
  if (status === 'failed' || status === 'cancelled') return 'var(--color-error)';
  if (status === 'waiting_approval') return 'var(--color-warning)';
  if (status === 'running' || status === 'planning' || status === 'observing' || status === 'reflecting') return 'var(--color-accent)';
  return 'var(--color-text-tertiary)';
};

const formatTime = (seconds?: number | null) =>
  seconds
    ? new Date(seconds * 1000).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
    : 'Not yet';

export function AgentModePage() {
  const [goals, setGoals] = useState<AutonomousAgentGoal[]>([]);
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown> | null>(null);
  const [selectedId, setSelectedId] = useState<string>('');
  const [events, setEvents] = useState<AutonomousAgentEvent[]>([]);
  const [goalText, setGoalText] = useState(examples[0]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(() => goals.find((goal) => goal.goal_id === selectedId) || goals[0], [goals, selectedId]);

  const load = async () => {
    setError(null);
    try {
      const [goalList, diag] = await Promise.all([
        fetchAutonomousGoals(),
        fetchAutonomousAgentDiagnostics().catch(() => null),
      ]);
      setGoals(goalList);
      setDiagnostics(diag);
      if (!selectedId && goalList.length) setSelectedId(goalList[0].goal_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load autonomous goals');
    }
  };

  useEffect(() => {
    load();
  }, []);

  useEffect(() => {
    if (!selected?.goal_id) {
      setEvents([]);
      return;
    }
    fetchAutonomousGoalEvents(selected.goal_id).then(setEvents).catch(() => setEvents([]));
  }, [selected?.goal_id]);

  const createGoal = async () => {
    const text = goalText.trim();
    if (!text) return;
    setLoading(true);
    setError(null);
    try {
      const goal = await createAutonomousGoal(text, true);
      await load();
      setSelectedId(goal.goal_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create goal');
    } finally {
      setLoading(false);
    }
  };

  const continueGoal = async (goal: AutonomousAgentGoal) => {
    setLoading(true);
    try {
      await continueAutonomousGoal(goal.goal_id);
      await load();
    } finally {
      setLoading(false);
    }
  };

  const cancelGoal = async (goal: AutonomousAgentGoal) => {
    setLoading(true);
    try {
      await cancelAutonomousGoal(goal.goal_id);
      await load();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between mb-6">
          <div>
            <div className="flex items-center gap-3 mb-3">
              <div
                className="w-11 h-11 rounded-2xl flex items-center justify-center"
                style={{
                  background: 'var(--color-accent-subtle)',
                  color: 'var(--color-accent)',
                  boxShadow: '0 0 28px var(--color-accent-glow)',
                }}
              >
                <Zap size={22} />
              </div>
              <div>
                <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>
                  Autonomous Agent Mode
                </h1>
                <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                  Observe, plan, act, reflect, and remember with approval-safe local execution.
                </p>
              </div>
            </div>
          </div>
          <button onClick={load} className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm" style={buttonStyle(false)}>
            <RefreshCw size={15} />
            Refresh
          </button>
        </div>

        {error && (
          <div className="mb-4 rounded-xl px-4 py-3 text-sm" style={{ background: 'color-mix(in srgb, var(--color-error) 12%, transparent)', border: '1px solid color-mix(in srgb, var(--color-error) 35%, transparent)', color: 'var(--color-error)' }}>
            {error}
          </div>
        )}

        <section className="rounded-2xl p-5 mb-5" style={panelStyle}>
          <div className="grid grid-cols-1 lg:grid-cols-[1fr_auto] gap-3">
            <div>
              <label className="text-xs uppercase tracking-[0.16em]" style={{ color: 'var(--color-text-tertiary)' }}>
                Goal
              </label>
              <input
                value={goalText}
                onChange={(event) => setGoalText(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') createGoal();
                }}
                className="mt-2 w-full rounded-xl px-4 py-3 text-sm outline-none"
                style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              />
            </div>
            <button onClick={createGoal} disabled={loading} className="self-end flex items-center justify-center gap-2 px-4 py-3 rounded-xl text-sm font-medium" style={buttonStyle(true)}>
              <Play size={16} />
              Start Goal
            </button>
          </div>
          <div className="flex flex-wrap gap-2 mt-3">
            {examples.map((item) => (
              <button key={item} onClick={() => setGoalText(item)} className="px-3 py-1.5 rounded-full text-xs" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
                {item}
              </button>
            ))}
          </div>
        </section>

        <div className="grid grid-cols-1 xl:grid-cols-[0.9fr_1.2fr_0.9fr] gap-5">
          <section className="rounded-2xl p-5" style={panelStyle}>
            <Header icon={<Activity size={17} />} title="Goals" />
            <div className="space-y-3">
              {goals.length ? goals.map((goal) => (
                <button
                  key={goal.goal_id}
                  onClick={() => setSelectedId(goal.goal_id)}
                  className="w-full text-left rounded-xl p-3"
                  style={{ background: selected?.goal_id === goal.goal_id ? 'var(--color-accent-subtle)' : 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
                >
                  <div className="flex items-center justify-between gap-3 mb-1">
                    <span className="text-sm font-medium line-clamp-1" style={{ color: 'var(--color-text)' }}>{goal.user_request}</span>
                    <StatusBadge status={goal.status} />
                  </div>
                  <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                    {goal.current_phase} · {formatTime(goal.updated_at)}
                  </div>
                </button>
              )) : (
                <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>No autonomous goals yet.</p>
              )}
            </div>
          </section>

          <section className="rounded-2xl p-5" style={panelStyle}>
            <Header icon={<Brain size={17} />} title="Goal Detail" />
            {selected ? (
              <div className="space-y-4">
                <div>
                  <div className="flex items-center justify-between gap-3">
                    <h2 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>{selected.user_request}</h2>
                    <StatusBadge status={selected.status} />
                  </div>
                  <p className="text-sm mt-2" style={{ color: 'var(--color-text-secondary)' }}>
                    {selected.result_summary || 'Goal is waiting for execution output.'}
                  </p>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                  <Metric label="Phase" value={selected.current_phase} />
                  <Metric label="Steps" value={String(selected.steps.length)} />
                  <Metric label="Actions" value={String(selected.actions_taken.length)} />
                  <Metric label="Memory" value={String(selected.memory_updates.length)} />
                </div>
                <MiniList title="Plan" items={selected.steps.map((step) => `${step.title || step.skill || step.id} · ${step.risk_level || 'LOW'}`)} />
                <MiniList title="Actions Taken" items={selected.actions_taken.map((item) => `${item.skill || item.step_id}: ${item.message || item.status}`)} />
                <MiniList title="Memory Updates" items={selected.memory_updates.map((item) => `${item.category || item.status}: ${item.value || item.error || item.key}`)} />
                <div className="flex gap-2">
                  <button onClick={() => continueGoal(selected)} disabled={loading || ['completed', 'failed', 'cancelled'].includes(selected.status)} className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm" style={buttonStyle(false)}>
                    <Play size={15} />
                    Continue
                  </button>
                  <button onClick={() => cancelGoal(selected)} disabled={loading || ['completed', 'failed', 'cancelled'].includes(selected.status)} className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm" style={{ ...buttonStyle(false), color: 'var(--color-error)' }}>
                    <XCircle size={15} />
                    Cancel
                  </button>
                </div>
              </div>
            ) : (
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>Select or create a goal to inspect it.</p>
            )}
          </section>

          <section className="rounded-2xl p-5" style={panelStyle}>
            <Header icon={<ShieldAlert size={17} />} title="Events & Safety" />
            <div className="mb-4 rounded-xl p-3 text-xs leading-5" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
              Safe steps run as dry-run/local plans. Risky actions pause for approval. No password, payment, hidden browser, or destructive automation is allowed.
            </div>
            <div className="space-y-2 mb-5">
              {events.length ? events.slice(-8).reverse().map((event) => (
                <div key={event.id} className="rounded-xl px-3 py-2 text-xs" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
                  <div className="flex items-center justify-between gap-2">
                    <span style={{ color: 'var(--color-text)' }}>{event.phase}</span>
                    <span style={{ color: statusColor(event.status) }}>{event.status}</span>
                  </div>
                  <div className="mt-1" style={{ color: 'var(--color-text-secondary)' }}>{event.message}</div>
                </div>
              )) : (
                <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>No events for this goal yet.</p>
              )}
            </div>
            <Header icon={<CheckCircle2 size={17} />} title="Diagnostics" />
            <pre className="mt-3 rounded-xl p-3 text-xs overflow-auto max-h-56" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
              {JSON.stringify(diagnostics || {}, null, 2)}
            </pre>
          </section>
        </div>
      </div>
    </div>
  );
}

function Header({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <div className="flex items-center gap-2 mb-4" style={{ color: 'var(--color-accent)' }}>
      {icon}
      <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>{title}</h2>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className="px-2 py-0.5 rounded-full text-[11px] font-medium" style={{ background: `${statusColor(status)}22`, color: statusColor(status) }}>
      {status.replace(/_/g, ' ')}
    </span>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl p-3" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
      <div className="text-[10px] uppercase tracking-[0.14em]" style={{ color: 'var(--color-text-tertiary)' }}>{label}</div>
      <div className="text-sm font-semibold mt-1 truncate" style={{ color: 'var(--color-text)' }}>{value}</div>
    </div>
  );
}

function MiniList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="text-xs font-semibold mb-2" style={{ color: 'var(--color-text)' }}>{title}</div>
      {items.length ? (
        <div className="space-y-1">
          {items.slice(0, 5).map((item, index) => (
            <div key={`${title}-${index}`} className="text-xs rounded-lg px-3 py-2" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
              {item}
            </div>
          ))}
        </div>
      ) : (
        <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>No entries yet.</p>
      )}
    </div>
  );
}

const panelStyle = {
  background: 'color-mix(in srgb, var(--color-surface) 86%, transparent)',
  border: '1px solid var(--color-border)',
  boxShadow: '0 20px 60px -46px var(--color-accent)',
};

const buttonStyle = (primary: boolean) => ({
  background: primary ? 'var(--color-accent)' : 'var(--color-bg-secondary)',
  border: primary ? '1px solid var(--color-accent)' : '1px solid var(--color-border)',
  color: primary ? 'white' : 'var(--color-text-secondary)',
  opacity: 1,
});
