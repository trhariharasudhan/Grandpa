import { useEffect, useMemo, useState } from 'react';
import { GitBranch, Network, Play, ShieldCheck, Workflow } from 'lucide-react';
import {
  analyzePlannerRequest,
  fetchAgentRuntimeTasks,
  fetchMcpTools,
  fetchPlannerDiagnostics,
  runAgentGoal,
  type AgentRuntimeTask,
  type PlannerAnalysis,
} from '../lib/api';

const examples = [
  'set up my coding workspace',
  'research Python tutorials and summarize them',
  'organize my downloads folder',
];

export function PlannerPage() {
  const [request, setRequest] = useState(examples[0]);
  const [analysis, setAnalysis] = useState<PlannerAnalysis | null>(null);
  const [tasks, setTasks] = useState<AgentRuntimeTask[]>([]);
  const [toolCount, setToolCount] = useState(0);
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const refresh = () => {
    fetchPlannerDiagnostics().then(setDiagnostics).catch(() => {});
    fetchAgentRuntimeTasks().then(setTasks).catch(() => {});
    fetchMcpTools().then((items) => setToolCount(items.length)).catch(() => {});
  };

  useEffect(refresh, []);

  const plannerStatus = useMemo(() => {
    const planner = diagnostics?.planner as Record<string, unknown> | undefined;
    return String(planner?.status || 'checking');
  }, [diagnostics]);

  const analyze = async () => {
    setLoading(true);
    setError('');
    try {
      setAnalysis(await analyzePlannerRequest(request));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Planner analysis failed');
    } finally {
      setLoading(false);
    }
  };

  const createTask = async () => {
    setLoading(true);
    setError('');
    try {
      const task = await runAgentGoal(request, false);
      setAnalysis(task.analysis);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Agent task creation failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto px-6 py-6" style={{ color: 'var(--color-text)' }}>
      <div className="mx-auto flex max-w-6xl flex-col gap-5">
        <header className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent-amber)' }}>
            <Network size={16} />
            Native Agent Planner
          </div>
          <h1 className="text-2xl font-semibold">Planner</h1>
          <p className="max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            Inspect how Grandpa maps a request into local skills, approval gates, workflow handoff, and MCP-style tools.
          </p>
        </header>

        <section className="grid gap-3 md:grid-cols-4">
          <Metric icon={Network} label="Planner" value={plannerStatus} />
          <Metric icon={GitBranch} label="MCP Tools" value={String(toolCount)} />
          <Metric icon={Workflow} label="Agent Tasks" value={String(tasks.length)} />
          <Metric icon={ShieldCheck} label="Safety" value="approval gated" />
        </section>

        <section className="rounded-2xl p-4" style={panelStyle}>
          <div className="flex flex-col gap-3 md:flex-row">
            <input
              className="min-w-0 flex-1 rounded-xl px-3 py-2 text-sm outline-none"
              style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
              value={request}
              onChange={(event) => setRequest(event.target.value)}
            />
            <button className="rounded-xl px-4 py-2 text-sm font-medium" style={primaryButton} onClick={analyze} disabled={loading}>
              Analyze
            </button>
            <button className="flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium" style={secondaryButton} onClick={createTask} disabled={loading}>
              <Play size={15} />
              Create Task
            </button>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            {examples.map((item) => (
              <button key={item} className="rounded-lg px-2.5 py-1 text-xs" style={chipStyle} onClick={() => setRequest(item)}>
                {item}
              </button>
            ))}
          </div>
          {error && <p className="mt-3 text-sm" style={{ color: 'var(--color-danger)' }}>{error}</p>}
        </section>

        {analysis && (
          <section className="grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
            <div className="rounded-2xl p-4" style={panelStyle}>
              <h2 className="text-sm font-semibold">Plan Summary</h2>
              <div className="mt-4 grid gap-2 text-sm">
                <Row label="Intent" value={analysis.intent} />
                <Row label="Risk" value={analysis.estimated_risk} />
                <Row label="Confidence" value={`${Math.round(analysis.confidence * 100)}%`} />
                <Row label="Workflow" value={analysis.workflow_suitable ? 'handoff ready' : 'not needed'} />
              </div>
              <p className="mt-4 text-sm" style={{ color: 'var(--color-text-secondary)' }}>{analysis.reasoning_summary}</p>
              {analysis.unsupported_reason && <p className="mt-2 text-sm" style={{ color: 'var(--color-warning)' }}>{analysis.unsupported_reason}</p>}
            </div>

            <div className="rounded-2xl p-4" style={panelStyle}>
              <h2 className="text-sm font-semibold">Execution Graph</h2>
              <div className="mt-4 flex flex-col gap-3">
                {analysis.graph.nodes.map((node) => (
                  <div key={node.id} className="rounded-xl p-3" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
                    <div className="flex items-center justify-between gap-3">
                      <span className="font-medium">{node.skill}</span>
                      <span className="rounded-lg px-2 py-1 text-xs" style={{ border: '1px solid var(--color-border)', color: node.approval_required ? 'var(--color-warning)' : 'var(--color-success)' }}>
                        {node.approval_required ? 'approval' : node.risk_level}
                      </span>
                    </div>
                    {node.dependencies.length > 0 && <p className="mt-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Depends on {node.dependencies.join(', ')}</p>}
                  </div>
                ))}
              </div>
            </div>
          </section>
        )}

        <section className="rounded-2xl p-4" style={panelStyle}>
          <h2 className="text-sm font-semibold">Recent Agent Tasks</h2>
          <div className="mt-3 flex flex-col gap-2">
            {tasks.length === 0 ? (
              <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>No planner-agent tasks created in this session yet.</p>
            ) : (
              tasks.slice(0, 6).map((task) => (
                <div key={task.task_id} className="flex items-center justify-between rounded-xl px-3 py-2 text-sm" style={{ background: 'var(--color-bg-secondary)' }}>
                  <span>{task.request}</span>
                  <span style={{ color: task.status === 'completed' ? 'var(--color-success)' : 'var(--color-accent-amber)' }}>{task.status}</span>
                </div>
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof Network; label: string; value: string }) {
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

const panelStyle = {
  background: 'color-mix(in srgb, var(--color-bg-secondary) 78%, transparent)',
  border: '1px solid var(--color-border)',
  boxShadow: '0 24px 80px -55px var(--color-accent)',
};

const primaryButton = {
  background: 'var(--color-accent)',
  color: 'var(--color-on-accent)',
};

const secondaryButton = {
  background: 'var(--color-bg-secondary)',
  border: '1px solid var(--color-border)',
};

const chipStyle = {
  background: 'var(--color-bg-secondary)',
  border: '1px solid var(--color-border)',
  color: 'var(--color-text-secondary)',
};
