import { useEffect, useMemo, useState } from 'react';
import { Activity, Play, Plus, RefreshCw, ShieldCheck, Trash2, Workflow } from 'lucide-react';
import {
  createUserSkill,
  deleteUserSkill,
  fetchUserSkillDiagnostics,
  fetchUserSkills,
  runUserSkill,
  type UserSkill,
} from '../lib/api';

export function SkillsBuilderPage() {
  const [skills, setSkills] = useState<UserSkill[]>([]);
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown> | null>(null);
  const [name, setName] = useState('start coding session');
  const [description, setDescription] = useState('Prepare a safe coding-session readiness workflow.');
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const [items, diag] = await Promise.all([fetchUserSkills(query), fetchUserSkillDiagnostics()]);
      setSkills(items.skills || []);
      setDiagnostics(diag);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load user skills');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const storage = (diagnostics?.storage || {}) as Record<string, unknown>;
  const successRate = useMemo(() => {
    const value = Number(storage.success_rate || 0);
    return `${Math.round(value * 100)}%`;
  }, [storage.success_rate]);

  const createSkill = async () => {
    setError('');
    setStatus('');
    try {
      const created = await createUserSkill({ name, description });
      setStatus(`Saved "${created.skill.name}".`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create skill');
    }
  };

  const runSkill = async (skill: UserSkill) => {
    setError('');
    setStatus('');
    try {
      const result = await runUserSkill(skill.skill_id);
      setStatus(String(result.message || `Ran ${skill.name}.`));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to run skill');
    }
  };

  const removeSkill = async (skill: UserSkill) => {
    setError('');
    setStatus('');
    try {
      await deleteUserSkill(skill.skill_id);
      setStatus(`Deleted "${skill.name}".`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete skill');
    }
  };

  return (
    <div className="h-full overflow-y-auto px-6 py-6" style={{ color: 'var(--color-text)' }}>
      <div className="mx-auto flex max-w-6xl flex-col gap-5">
        <header className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent-amber)' }}>
            <Workflow size={16} />
            Self-Learning Skill Builder
          </div>
          <h1 className="text-2xl font-semibold">User Skills</h1>
          <p className="max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            Create reusable Grandpa workflows without source-code changes. Skills are declarative, local-only, and run through the existing safety and approval layers.
          </p>
        </header>

        <section className="grid gap-3 md:grid-cols-4">
          <Metric icon={Workflow} label="Saved Skills" value={String(storage.skill_count ?? skills.length)} />
          <Metric icon={Activity} label="Runs" value={String(storage.usage_count ?? 0)} />
          <Metric icon={ShieldCheck} label="Success Rate" value={successRate} />
          <Metric icon={RefreshCw} label="Runtime" value={diagnostics?.status ? String(diagnostics.status) : loading ? 'checking' : 'ready'} />
        </section>

        <section className="rounded-2xl p-4" style={panelStyle}>
          <div className="grid gap-3 lg:grid-cols-[1fr_1.4fr_auto]">
            <input className="rounded-xl px-3 py-2 text-sm outline-none" style={inputStyle} value={name} onChange={(event) => setName(event.target.value)} placeholder="Skill name" />
            <input className="rounded-xl px-3 py-2 text-sm outline-none" style={inputStyle} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Description" />
            <button onClick={createSkill} className="inline-flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm" style={primaryButtonStyle}>
              <Plus size={15} />
              Create
            </button>
          </div>
          <div className="mt-3 flex gap-2">
            <input className="min-w-0 flex-1 rounded-xl px-3 py-2 text-sm outline-none" style={inputStyle} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search custom skills" />
            <button onClick={load} className="inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm" style={secondaryButtonStyle}>
              <RefreshCw size={15} />
              Refresh
            </button>
          </div>
        </section>

        {error && <Banner tone="error">{error}</Banner>}
        {status && <Banner tone="success">{status}</Banner>}

        <section className="grid gap-3 lg:grid-cols-2">
          {skills.length ? (
            skills.map((skill) => <SkillCard key={skill.skill_id} skill={skill} onRun={() => runSkill(skill)} onDelete={() => removeSkill(skill)} />)
          ) : (
            <div className="rounded-2xl p-4 text-sm" style={panelStyle}>
              No custom skills saved yet. Create one like "start coding session".
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function SkillCard({ skill, onRun, onDelete }: { skill: UserSkill; onRun: () => void; onDelete: () => void }) {
  const approvalCount = skill.workflow_steps.filter((step) => step.approval_required).length;
  return (
    <article className="rounded-2xl p-4" style={panelStyle}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="font-semibold">{skill.name}</h2>
          <p className="mt-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>{skill.description}</p>
        </div>
        <span className="rounded-lg px-2 py-1 text-xs" style={{ color: approvalCount ? 'var(--color-warning)' : 'var(--color-success)', border: '1px solid currentColor' }}>
          {approvalCount ? `${approvalCount} approval` : 'safe'}
        </span>
      </div>
      <div className="mt-4 flex flex-wrap gap-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
        {skill.trigger_phrases.map((trigger) => (
          <span key={trigger} className="rounded-lg px-2 py-1" style={{ background: 'var(--color-bg-secondary)' }}>{trigger}</span>
        ))}
      </div>
      <div className="mt-4 space-y-2">
        {skill.workflow_steps.slice(0, 4).map((step) => (
          <div key={`${step.skill}-${step.title}`} className="flex items-center justify-between rounded-xl px-3 py-2 text-xs" style={{ background: 'var(--color-bg-secondary)' }}>
            <span>{step.title || step.skill}</span>
            <span style={{ color: step.approval_required ? 'var(--color-warning)' : 'var(--color-success)' }}>{step.risk_level}</span>
          </div>
        ))}
      </div>
      <div className="mt-4 flex items-center justify-between gap-3">
        <div className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
          {skill.usage_count} run(s), {Math.round((skill.success_rate || 0) * 100)}% success
        </div>
        <div className="flex gap-2">
          <button onClick={onRun} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs" style={secondaryButtonStyle}>
            <Play size={13} />
            Run
          </button>
          <button onClick={onDelete} className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs" style={dangerButtonStyle}>
            <Trash2 size={13} />
            Delete
          </button>
        </div>
      </div>
    </article>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof Workflow; label: string; value: string }) {
  return (
    <div className="rounded-2xl p-4" style={panelStyle}>
      <Icon size={18} style={{ color: 'var(--color-accent)' }} />
      <div className="mt-3 text-xs uppercase tracking-[0.18em]" style={{ color: 'var(--color-text-tertiary)' }}>{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

function Banner({ children, tone }: { children: string; tone: 'success' | 'error' }) {
  return (
    <div className="rounded-xl px-4 py-3 text-sm" style={{ border: `1px solid ${tone === 'success' ? 'var(--color-success)' : 'var(--color-danger)'}`, color: tone === 'success' ? 'var(--color-success)' : 'var(--color-danger)' }}>
      {children}
    </div>
  );
}

const panelStyle = {
  background: 'color-mix(in srgb, var(--color-bg-secondary) 78%, transparent)',
  border: '1px solid var(--color-border)',
  boxShadow: '0 24px 80px -55px var(--color-accent)',
};

const inputStyle = {
  color: 'var(--color-text)',
  background: 'var(--color-bg-secondary)',
  border: '1px solid var(--color-border)',
};

const primaryButtonStyle = {
  color: 'var(--color-bg)',
  background: 'var(--color-accent-amber)',
  border: '1px solid color-mix(in srgb, var(--color-accent-amber) 62%, transparent)',
};

const secondaryButtonStyle = {
  color: 'var(--color-text)',
  background: 'var(--color-bg-secondary)',
  border: '1px solid var(--color-border)',
};

const dangerButtonStyle = {
  color: 'var(--color-danger)',
  background: 'var(--color-bg-secondary)',
  border: '1px solid color-mix(in srgb, var(--color-danger) 45%, var(--color-border))',
};
