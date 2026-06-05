import { useEffect, useMemo, useState } from 'react';
import { Brain, ShieldCheck, Sparkles, Wrench } from 'lucide-react';
import { fetchRuntimeSkills, type RuntimeSkillsResponse, type RuntimeSkill } from '../lib/api';

function riskColor(risk: string) {
  if (risk === 'LOW') return 'var(--color-success)';
  if (risk === 'MEDIUM') return 'var(--color-warning)';
  if (risk === 'HIGH') return 'var(--color-accent-amber)';
  return 'var(--color-danger)';
}

export function SkillsPage() {
  const [data, setData] = useState<RuntimeSkillsResponse | null>(null);
  const [error, setError] = useState('');
  const [category, setCategory] = useState('all');

  useEffect(() => {
    fetchRuntimeSkills()
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load skills'));
  }, []);

  const skills = useMemo(() => {
    const items = data?.skills || [];
    if (category === 'all') return items;
    return items.filter((skill) => skill.category === category);
  }, [category, data?.skills]);

  return (
    <div className="h-full overflow-y-auto px-6 py-6" style={{ color: 'var(--color-text)' }}>
      <div className="mx-auto flex max-w-6xl flex-col gap-5">
        <header className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent-amber)' }}>
            <Sparkles size={16} />
            Runtime Tool Registry
          </div>
          <h1 className="text-2xl font-semibold">Skills Runtime</h1>
          <p className="max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            Grandpa routes safe desktop, browser, memory, workflow, and vision capabilities through modular runtime skills.
          </p>
        </header>

        {error && (
          <div className="rounded-xl px-4 py-3 text-sm" style={{ border: '1px solid var(--color-danger)', color: 'var(--color-danger)' }}>
            {error}
          </div>
        )}

        <section className="grid gap-3 md:grid-cols-4">
          <Metric icon={Wrench} label="Loaded Skills" value={String(data?.runtime?.skill_count ?? skills.length)} />
          <Metric icon={Brain} label="Categories" value={String(data?.runtime?.categories?.length ?? 0)} />
          <Metric icon={ShieldCheck} label="Approval Required" value={String(data?.runtime?.approval_required_count ?? 0)} />
          <Metric icon={Sparkles} label="Runtime" value={data?.runtime?.runtime_ready ? 'ready' : 'checking'} />
        </section>

        <section className="flex flex-wrap gap-2">
          <button className="rounded-lg px-3 py-1.5 text-sm" onClick={() => setCategory('all')} style={buttonStyle(category === 'all')}>
            All
          </button>
          {(data?.runtime?.categories || []).map((item) => (
            <button key={item.name} className="rounded-lg px-3 py-1.5 text-sm" onClick={() => setCategory(item.name)} style={buttonStyle(category === item.name)}>
              {item.name} ({item.count})
            </button>
          ))}
        </section>

        <section className="grid gap-3 lg:grid-cols-2">
          {skills.map((skill) => (
            <SkillCard key={skill.name} skill={skill} />
          ))}
        </section>

        <section className="rounded-2xl p-4" style={panelStyle}>
          <h2 className="mb-3 text-sm font-semibold">Execution History</h2>
          {(data?.runtime?.history || []).length === 0 ? (
            <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>No runtime skill executions recorded in this server session yet.</p>
          ) : (
            <div className="flex flex-col gap-2">
              {(data?.runtime?.history || []).slice(0, 8).map((item, index) => (
                <div key={`${item.skill}-${index}`} className="flex items-center justify-between rounded-xl px-3 py-2 text-sm" style={{ background: 'var(--color-bg-secondary)' }}>
                  <span>{item.skill}</span>
                  <span style={{ color: item.ok ? 'var(--color-success)' : 'var(--color-warning)' }}>{item.status}</span>
                </div>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof Wrench; label: string; value: string }) {
  return (
    <div className="rounded-2xl p-4" style={panelStyle}>
      <Icon size={18} style={{ color: 'var(--color-accent)' }} />
      <div className="mt-3 text-xs uppercase tracking-[0.18em]" style={{ color: 'var(--color-text-tertiary)' }}>{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

function SkillCard({ skill }: { skill: RuntimeSkill }) {
  return (
    <article className="rounded-2xl p-4" style={panelStyle}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">{skill.name}</h2>
          <p className="mt-1 text-sm" style={{ color: 'var(--color-text-secondary)' }}>{skill.description}</p>
        </div>
        <span className="rounded-lg px-2 py-1 text-xs font-semibold" style={{ color: riskColor(skill.risk_level), border: `1px solid ${riskColor(skill.risk_level)}` }}>
          {skill.risk_level}
        </span>
      </div>
      <div className="mt-4 flex flex-wrap gap-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
        <span className="rounded-lg px-2 py-1" style={{ background: 'var(--color-bg-secondary)' }}>{skill.category}</span>
        <span className="rounded-lg px-2 py-1" style={{ background: 'var(--color-bg-secondary)' }}>
          {skill.approval_required ? 'approval required' : 'auto-safe'}
        </span>
        <span className="rounded-lg px-2 py-1" style={{ background: 'var(--color-bg-secondary)' }}>
          {skill.dry_run_supported ? 'dry-run ready' : 'no dry-run'}
        </span>
      </div>
    </article>
  );
}

const panelStyle = {
  background: 'color-mix(in srgb, var(--color-bg-secondary) 78%, transparent)',
  border: '1px solid var(--color-border)',
  boxShadow: '0 24px 80px -55px var(--color-accent)',
};

function buttonStyle(active: boolean) {
  return {
    background: active ? 'var(--color-accent-subtle)' : 'var(--color-bg-secondary)',
    border: `1px solid ${active ? 'var(--color-accent)' : 'var(--color-border)'}`,
    color: active ? 'var(--color-text)' : 'var(--color-text-secondary)',
  };
}
