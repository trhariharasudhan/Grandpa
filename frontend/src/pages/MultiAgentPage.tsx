import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { BrainCircuit, CheckCircle2, Network, Play, RefreshCw, ShieldCheck, Users } from 'lucide-react';
import {
  fetchMultiAgentDiagnostics,
  fetchMultiAgentTasks,
  orchestrateMultiAgent,
  type MultiAgentDiagnostics,
  type MultiAgentTask,
} from '../lib/api';

const examples = [
  'research Python tutorials',
  'analyze Grandpa health',
  'summarize current webpage',
  'prepare coding environment',
  'collect diagnostics report',
];

export function MultiAgentPage() {
  const [diagnostics, setDiagnostics] = useState<MultiAgentDiagnostics | null>(null);
  const [tasks, setTasks] = useState<MultiAgentTask[]>([]);
  const [selectedTask, setSelectedTask] = useState<MultiAgentTask | null>(null);
  const [request, setRequest] = useState(examples[0]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const refresh = async () => {
    setError('');
    try {
      const [diag, taskList] = await Promise.all([
        fetchMultiAgentDiagnostics(),
        fetchMultiAgentTasks(12),
      ]);
      setDiagnostics(diag);
      setTasks(taskList.tasks || []);
      if (!selectedTask && taskList.tasks?.[0]) setSelectedTask(taskList.tasks[0]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load multi-agent diagnostics.');
    }
  };

  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const run = async () => {
    if (!request.trim()) return;
    setLoading(true);
    setError('');
    try {
      const task = await orchestrateMultiAgent(request.trim());
      setSelectedTask(task);
      setTasks((current) => [task, ...current.filter((item) => item.task_id !== task.task_id)].slice(0, 12));
      void refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Multi-agent orchestration failed.');
    } finally {
      setLoading(false);
    }
  };

  const agents = diagnostics?.registry?.agents || [];
  const successCount = useMemo(
    () => selectedTask?.outputs?.filter((output) => output.ok).length || 0,
    [selectedTask],
  );

  return (
    <main className="h-full overflow-y-auto p-6" style={{ background: 'var(--color-bg)' }}>
      <div className="mx-auto flex max-w-7xl flex-col gap-5">
        <header className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent-amber)' }}>
            <Network size={16} />
            Local multi-agent orchestration
          </div>
          <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
            <div>
              <h1 className="text-3xl font-semibold" style={{ color: 'var(--color-text)' }}>
                Multi-Agent System
              </h1>
              <p className="mt-2 max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                Grandpa coordinates specialized local agents through shared task context. Actions stay deterministic,
                local-first, and approval-safe.
              </p>
            </div>
            <button
              type="button"
              onClick={() => void refresh()}
              className="inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm transition-colors"
              style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
            >
              <RefreshCw size={16} />
              Refresh
            </button>
          </div>
        </header>

        {error && (
          <div className="rounded-2xl px-4 py-3 text-sm" style={{ border: '1px solid var(--color-danger)', color: 'var(--color-danger)' }}>
            {error}
          </div>
        )}

        <section className="grid gap-4 md:grid-cols-4">
          <StatusCard icon={Users} label="Agents" value={String(agents.length)} detail="registered specialists" />
          <StatusCard icon={BrainCircuit} label="Tasks" value={String(diagnostics?.task_count ?? tasks.length)} detail="persisted locally" />
          <StatusCard icon={ShieldCheck} label="Safety" value={diagnostics?.approval_safe ? 'On' : 'Check'} detail="approval bypass disabled" />
          <StatusCard icon={CheckCircle2} label="Mode" value={diagnostics?.local_only ? 'Local' : 'Mixed'} detail="no cloud orchestration" />
        </section>

        <section
          className="rounded-2xl p-4"
          style={{
            background: 'color-mix(in srgb, var(--color-bg-secondary) 82%, transparent)',
            border: '1px solid var(--color-border)',
            boxShadow: '0 18px 50px -36px var(--color-accent)',
          }}
        >
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center">
            <input
              value={request}
              onChange={(event) => setRequest(event.target.value)}
              className="min-w-0 flex-1 rounded-xl px-4 py-3 text-sm outline-none"
              style={{
                background: 'var(--color-bg)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
              placeholder="Give Grandpa a collaborative goal..."
            />
            <button
              type="button"
              onClick={() => void run()}
              disabled={loading}
              className="inline-flex items-center justify-center gap-2 rounded-xl px-5 py-3 text-sm font-medium disabled:opacity-60"
              style={{
                background: 'linear-gradient(135deg, var(--color-accent), var(--color-accent-amber))',
                color: 'var(--color-on-accent)',
              }}
            >
              <Play size={16} />
              {loading ? 'Coordinating...' : 'Run Agents'}
            </button>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {examples.map((example) => (
              <button
                key={example}
                type="button"
                onClick={() => setRequest(example)}
                className="rounded-full px-3 py-1.5 text-xs"
                style={{
                  background: example === request ? 'var(--color-accent-subtle)' : 'var(--color-bg-tertiary)',
                  color: 'var(--color-text-secondary)',
                  border: '1px solid var(--color-border)',
                }}
              >
                {example}
              </button>
            ))}
          </div>
        </section>

        <section className="grid gap-5 xl:grid-cols-[360px_1fr]">
          <div className="flex flex-col gap-4">
            <Panel title="Registered Agents">
              <div className="flex flex-col gap-3">
                {agents.map((agent) => (
                  <div key={agent.agent_id} className="rounded-xl p-3" style={{ background: 'var(--color-bg-tertiary)' }}>
                    <div className="flex items-center justify-between gap-2">
                      <div className="font-medium" style={{ color: 'var(--color-text)' }}>{agent.name}</div>
                      <span className="rounded-full px-2 py-1 text-[10px]" style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent-amber)' }}>
                        {agent.capabilities.length} caps
                      </span>
                    </div>
                    <p className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>{agent.description}</p>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="Recent Tasks">
              <div className="flex flex-col gap-2">
                {tasks.length === 0 && <Empty text="No multi-agent tasks yet." />}
                {tasks.map((task) => (
                  <button
                    key={task.task_id}
                    type="button"
                    onClick={() => setSelectedTask(task)}
                    className="rounded-xl p-3 text-left text-sm"
                    style={{
                      background: selectedTask?.task_id === task.task_id ? 'var(--color-accent-subtle)' : 'var(--color-bg-tertiary)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text)',
                    }}
                  >
                    <div className="truncate font-medium">{task.user_request}</div>
                    <div className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                      {task.status} · {task.participating_agents.length} agents
                    </div>
                  </button>
                ))}
              </div>
            </Panel>
          </div>

          <Panel title="Execution Graph">
            {!selectedTask ? (
              <Empty text="Run a collaboration to see participating agents, observations, and outputs." />
            ) : (
              <div className="flex flex-col gap-5">
                <div className="rounded-xl p-4" style={{ background: 'var(--color-bg-tertiary)' }}>
                  <div className="text-xs uppercase tracking-[0.16em]" style={{ color: 'var(--color-text-tertiary)' }}>Goal</div>
                  <div className="mt-1 text-lg font-medium" style={{ color: 'var(--color-text)' }}>{selectedTask.user_request}</div>
                  <p className="mt-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>{selectedTask.summary}</p>
                </div>

                <div className="grid gap-3 md:grid-cols-3">
                  <MiniMetric label="Status" value={selectedTask.status} />
                  <MiniMetric label="Agents completed" value={`${successCount}/${selectedTask.outputs.length}`} />
                  <MiniMetric label="Task ID" value={selectedTask.task_id} />
                </div>

                <div className="grid gap-3">
                  {selectedTask.outputs.map((output) => (
                    <div key={output.agent_id} className="rounded-xl p-4" style={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}>
                      <div className="flex items-center justify-between gap-3">
                        <div>
                          <div className="font-medium" style={{ color: 'var(--color-text)' }}>{output.name}</div>
                          <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{output.agent_id}</div>
                        </div>
                        <span className="rounded-full px-2.5 py-1 text-xs" style={{
                          background: output.ok ? 'rgba(34,197,94,0.14)' : 'rgba(245,158,11,0.16)',
                          color: output.ok ? '#86efac' : 'var(--color-accent-amber)',
                        }}>
                          {output.status}
                        </span>
                      </div>
                      <p className="mt-3 text-sm" style={{ color: 'var(--color-text-secondary)' }}>{output.message}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </Panel>
        </section>
      </div>
    </main>
  );
}

function StatusCard({ icon: Icon, label, value, detail }: { icon: typeof Users; label: string; value: string; detail: string }) {
  return (
    <div className="rounded-2xl p-4" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
      <Icon size={18} style={{ color: 'var(--color-accent-amber)' }} />
      <div className="mt-3 text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>{value}</div>
      <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{label}</div>
      <div className="mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{detail}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl p-4" style={{ background: 'color-mix(in srgb, var(--color-bg-secondary) 86%, transparent)', border: '1px solid var(--color-border)' }}>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-[0.14em]" style={{ color: 'var(--color-text-secondary)' }}>{title}</h2>
      {children}
    </section>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl p-3" style={{ background: 'var(--color-bg-tertiary)' }}>
      <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{label}</div>
      <div className="mt-1 truncate text-sm font-medium" style={{ color: 'var(--color-text)' }}>{value}</div>
    </div>
  );
}

function Empty({ text }: { text: string }) {
  return <div className="rounded-xl p-4 text-sm" style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}>{text}</div>;
}
