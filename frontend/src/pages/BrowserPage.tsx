import { useEffect, useState } from 'react';
import { ExternalLink, Globe2, MousePointerClick, RefreshCw, Search, ShieldCheck, Sparkles, Video } from 'lucide-react';
import {
  fetchBrowserAgentDiagnostics,
  fetchBrowserDiagnostics,
  planBrowserAgentTask,
  type BrowserAgentDiagnostics,
  type BrowserAgentTask,
  type BrowserContextSummary,
} from '../lib/api';

type BrowserDiagnostics = Awaited<ReturnType<typeof fetchBrowserDiagnostics>>;

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div
      className="rounded-xl px-3 py-3"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-secondary) 72%, transparent)',
        border: '1px solid color-mix(in srgb, var(--color-accent) 14%, var(--color-border))',
      }}
    >
      <div className="text-[10px] uppercase tracking-[0.14em]" style={{ color: 'var(--color-text-tertiary)' }}>{label}</div>
      <div className="mt-1 text-lg font-semibold" style={{ color: 'var(--color-text)' }}>{value}</div>
    </div>
  );
}

function ListBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <section
      className="rounded-xl p-4"
      style={{
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
      }}
    >
      <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--color-text)' }}>{title}</h3>
      {items.length ? (
        <div className="space-y-2">
          {items.slice(0, 8).map((item, index) => (
            <div key={`${item}-${index}`} className="text-xs leading-5" style={{ color: 'var(--color-text-secondary)' }}>
              {item}
            </div>
          ))}
        </div>
      ) : (
        <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>No visible items in the latest snapshot.</div>
      )}
    </section>
  );
}

export function BrowserPage() {
  const [data, setData] = useState<BrowserDiagnostics | null>(null);
  const [agent, setAgent] = useState<BrowserAgentDiagnostics | null>(null);
  const [goal, setGoal] = useState('summarize this webpage');
  const [plannedTask, setPlannedTask] = useState<BrowserAgentTask | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const [browserDiagnostics, agentDiagnostics] = await Promise.all([
        fetchBrowserDiagnostics(),
        fetchBrowserAgentDiagnostics(),
      ]);
      setData(browserDiagnostics);
      setAgent(agentDiagnostics);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load browser diagnostics');
    } finally {
      setLoading(false);
    }
  };

  const createPlan = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await planBrowserAgentTask(goal);
      setPlannedTask(result.task);
      setAgent(await fetchBrowserAgentDiagnostics());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create browser agent plan');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => window.clearInterval(timer);
  }, []);

  const context: BrowserContextSummary['context'] | undefined = data?.context;
  const counts = data?.details?.counts || {};

  return (
    <div className="flex-1 overflow-y-auto px-6 py-10">
      <div className="max-w-5xl mx-auto">
        <header className="mb-6 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>Browser Control</h1>
            <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
              Visible-page context, safe interaction readiness, and local browser workflow diagnostics.
            </p>
          </div>
          <button
            onClick={refresh}
            className="inline-flex items-center gap-2 rounded-xl px-3 py-2 text-xs"
            style={{ background: 'var(--color-accent)', color: 'white' }}
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </header>

        {error && (
          <div className="mb-4 rounded-xl px-4 py-3 text-sm" style={{ background: 'color-mix(in srgb, var(--color-error) 16%, transparent)', color: 'var(--color-error)' }}>
            {error}
          </div>
        )}

        <section
          className="mb-4 rounded-2xl p-4"
          style={{
            background: 'linear-gradient(135deg, color-mix(in srgb, var(--color-accent) 18%, transparent), color-mix(in srgb, var(--color-bg-secondary) 80%, transparent))',
            border: '1px solid color-mix(in srgb, var(--color-accent) 26%, var(--color-border))',
          }}
        >
          <div className="flex items-center gap-2 mb-2">
            <Globe2 size={16} style={{ color: 'var(--color-accent-amber)' }} />
            <span className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>
              {context?.title || 'No visible browser snapshot'}
            </span>
            <span className="ml-auto text-xs" style={{ color: data?.details.extension_connected ? 'var(--color-success)' : 'var(--color-warning)' }}>
              {agent?.snapshot_connected || data?.details.extension_connected ? 'extension connected' : 'extension offline'}
            </span>
          </div>
          <div className="text-xs truncate" style={{ color: 'var(--color-text-tertiary)' }}>
            {context?.url || 'Load the Grandpa browser extension in Chrome or Edge.'}
          </div>
        </section>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
          <Stat label="Headings" value={counts.headings ?? context?.headings?.length ?? 0} />
          <Stat label="Links" value={counts.links ?? context?.links?.length ?? 0} />
          <Stat label="Buttons" value={counts.buttons ?? context?.buttons?.length ?? 0} />
          <Stat label="Media" value={counts.media ?? context?.media?.length ?? 0} />
        </div>

        <div className="grid md:grid-cols-2 gap-4">
          <ListBlock title="Visible Headings" items={context?.headings || []} />
          <ListBlock title="Visible Buttons" items={context?.buttons || []} />
          <ListBlock title="Visible Links" items={(context?.links || []).map((link) => `${link.text || 'Untitled'} ${link.href ? `· ${link.href}` : ''}`)} />
          <ListBlock title="Form Fields" items={(context?.forms || []).flatMap((form) => form.fields.map((field) => `${form.label}: ${field.label || field.type}`))} />
        </div>

        <section className="mt-4 grid md:grid-cols-3 gap-3">
          <Stat label="Safe Reads" value="Auto" />
          <Stat label="Clicks / Forms" value="Approval" />
          <Stat label="Payments / Passwords" value="Blocked" />
        </section>

        <section
          className="mt-4 rounded-2xl p-4"
          style={{
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
          }}
        >
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                <Sparkles size={16} style={{ color: 'var(--color-accent-amber)' }} />
                Browser Agent
              </div>
              <p className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                Plan safe visible-page workflows. Downloads, forms, and messages stay approval-gated.
              </p>
            </div>
            <span className="text-xs" style={{ color: agent?.ready ? 'var(--color-success)' : 'var(--color-warning)' }}>
              {agent?.ready ? `${agent.task_count} tracked task(s)` : 'checking'}
            </span>
          </div>

          <div className="mt-4 flex flex-col gap-2 md:flex-row">
            <input
              value={goal}
              onChange={(event) => setGoal(event.target.value)}
              className="flex-1 rounded-xl px-3 py-2 text-sm outline-none"
              style={{
                background: 'color-mix(in srgb, var(--color-bg-secondary) 82%, transparent)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
              placeholder="summarize this webpage"
            />
            <button
              onClick={createPlan}
              className="inline-flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm"
              style={{ background: 'var(--color-accent)', color: 'white' }}
            >
              <Search size={14} />
              Plan
            </button>
          </div>

          {plannedTask && <TaskCard task={plannedTask} highlighted />}
        </section>

        <section className="mt-4 grid gap-4 md:grid-cols-2">
          <TaskList title="Recent Browser Agent Tasks" tasks={agent?.recent_tasks || []} />
          <section
            className="rounded-xl p-4"
            style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
          >
            <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--color-text)' }}>Safety Rules</h3>
            <div className="space-y-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
              <div>No hidden tabs or browser history scraping.</div>
              <div>No password, login, or payment field extraction.</div>
              <div>No auto-submit. Form changes require approval.</div>
              <div>Downloads and messaging plans require approval.</div>
            </div>
          </section>
        </section>

        <div className="mt-4 grid md:grid-cols-3 gap-3 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
          <div className="flex items-center gap-2"><ShieldCheck size={14} /> Local snapshots only</div>
          <div className="flex items-center gap-2"><MousePointerClick size={14} /> Visible clicks require approval</div>
          <div className="flex items-center gap-2"><Video size={14} /> Media actions stay visible-page scoped</div>
          <div className="flex items-center gap-2"><ExternalLink size={14} /> Downloads and forms are gated</div>
        </div>
      </div>
    </div>
  );
}

function TaskList({ title, tasks }: { title: string; tasks: BrowserAgentTask[] }) {
  return (
    <section
      className="rounded-xl p-4"
      style={{ background: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
    >
      <h3 className="text-sm font-semibold mb-3" style={{ color: 'var(--color-text)' }}>{title}</h3>
      {tasks.length ? (
        <div className="space-y-2">
          {tasks.slice(0, 6).map((task) => <TaskCard key={task.task_id} task={task} />)}
        </div>
      ) : (
        <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>No browser agent tasks recorded yet.</div>
      )}
    </section>
  );
}

function TaskCard({ task, highlighted = false }: { task: BrowserAgentTask; highlighted?: boolean }) {
  return (
    <div
      className={`rounded-xl p-3 text-xs ${highlighted ? 'mt-3' : ''}`}
      style={{
        background: highlighted ? 'color-mix(in srgb, var(--color-accent) 12%, var(--color-bg-secondary))' : 'var(--color-bg-secondary)',
        border: `1px solid ${task.approval_required ? 'var(--color-accent-amber)' : 'var(--color-border)'}`,
      }}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium" style={{ color: 'var(--color-text)' }}>{task.goal}</span>
        <span style={{ color: task.approval_required ? 'var(--color-accent-amber)' : 'var(--color-success)' }}>
          {task.status}
        </span>
      </div>
      <p className="mt-1" style={{ color: 'var(--color-text-secondary)' }}>{task.result_summary}</p>
      <div className="mt-2 space-y-1" style={{ color: 'var(--color-text-tertiary)' }}>
        {task.steps.slice(0, 3).map((step) => (
          <div key={step.id}>• {step.skill}: {step.title}</div>
        ))}
      </div>
    </div>
  );
}
