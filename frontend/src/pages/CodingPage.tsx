import { useEffect, useState } from 'react';
import type React from 'react';
import { Code2, FileCode2, GitBranch, PackageCheck, RefreshCw, ShieldCheck } from 'lucide-react';
import {
  fetchCodingDiagnostics,
  fetchCodingProjectSummary,
  type CodingProjectSummary,
} from '../lib/api';

export function CodingPage() {
  const [summary, setSummary] = useState<CodingProjectSummary | null>(null);
  const [diagnostics, setDiagnostics] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const [project, diag] = await Promise.all([fetchCodingProjectSummary(), fetchCodingDiagnostics()]);
      setSummary(project);
      setDiagnostics(diag);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load coding agent diagnostics');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  return (
    <div className="h-full overflow-y-auto px-6 py-6" style={{ color: 'var(--color-text)' }}>
      <div className="mx-auto flex max-w-6xl flex-col gap-5">
        <header className="flex items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent-amber)' }}>
              <Code2 size={16} />
              Coding Agent
            </div>
            <h1 className="mt-2 text-2xl font-semibold">Project Intelligence</h1>
            <p className="mt-1 max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              Read-only inspection for repositories, dependencies, architecture layers, and local project health.
            </p>
          </div>
          <button onClick={load} className="inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm" style={secondaryButtonStyle}>
            <RefreshCw size={15} />
            {loading ? 'Scanning' : 'Refresh'}
          </button>
        </header>

        {error && <div className="rounded-xl px-4 py-3 text-sm" style={{ border: '1px solid var(--color-danger)', color: 'var(--color-danger)' }}>{error}</div>}

        <section className="grid gap-3 md:grid-cols-4">
          <Metric icon={GitBranch} label="Project Type" value={(summary?.project.types || []).join(', ') || 'unknown'} />
          <Metric icon={FileCode2} label="Modules" value={String(summary?.repository.module_count ?? 0)} />
          <Metric icon={PackageCheck} label="Dependencies" value={String(summary?.dependencies.dependency_count ?? 0)} />
          <Metric icon={ShieldCheck} label="Mode" value={diagnostics?.read_only ? 'read-only' : 'checking'} />
        </section>

        <section className="rounded-2xl p-4" style={panelStyle}>
          <h2 className="mb-2 text-sm font-semibold">Repository Summary</h2>
          <p className="text-sm leading-6" style={{ color: 'var(--color-text-secondary)' }}>
            {summary?.summary || 'Scanning repository...'}
          </p>
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <Panel title="Architecture Layers">
            <div className="space-y-2">
              {(summary?.architecture.layers || []).map((layer) => (
                <div key={layer.name} className="flex items-center justify-between rounded-xl px-3 py-2 text-sm" style={{ background: 'var(--color-bg-secondary)' }}>
                  <span>{layer.name.replace(/_/g, ' ')}</span>
                  <span style={{ color: layer.present ? 'var(--color-success)' : 'var(--color-text-tertiary)' }}>
                    {layer.present ? 'present' : 'missing'}
                  </span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Dependency Manifests">
            <div className="space-y-2">
              {(summary?.dependencies.manifests || []).map((manifest) => (
                <div key={manifest.path} className="rounded-xl px-3 py-2 text-sm" style={{ background: 'var(--color-bg-secondary)' }}>
                  <div className="flex items-center justify-between gap-3">
                    <span>{manifest.file}</span>
                    <span style={{ color: 'var(--color-accent-amber)' }}>{manifest.dependency_count}</span>
                  </div>
                  <div className="mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                    {manifest.ecosystem}
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        </section>

        <section className="grid gap-4 lg:grid-cols-2">
          <Panel title="Language Breakdown">
            <div className="space-y-2">
              {(summary?.repository.language_breakdown || []).slice(0, 8).map((item) => (
                <div key={item.language} className="flex items-center justify-between rounded-xl px-3 py-2 text-sm" style={{ background: 'var(--color-bg-secondary)' }}>
                  <span>{item.language}</span>
                  <span>{item.files} file(s)</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Safety">
            <div className="space-y-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              <div>Executes code: {diagnostics?.capabilities && (diagnostics.capabilities as Record<string, unknown>).code_execution ? 'yes' : 'no'}</div>
              <div>Modifies repositories: {diagnostics?.capabilities && (diagnostics.capabilities as Record<string, unknown>).code_modification ? 'yes' : 'no'}</div>
              <div>Analysis mode: read-only</div>
            </div>
          </Panel>
        </section>
      </div>
    </div>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof Code2; label: string; value: string }) {
  return (
    <div className="rounded-2xl p-4" style={panelStyle}>
      <Icon size={18} style={{ color: 'var(--color-accent)' }} />
      <div className="mt-3 text-xs uppercase tracking-[0.18em]" style={{ color: 'var(--color-text-tertiary)' }}>{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl p-4" style={panelStyle}>
      <h2 className="mb-3 text-sm font-semibold">{title}</h2>
      {children}
    </section>
  );
}

const panelStyle = {
  background: 'color-mix(in srgb, var(--color-bg-secondary) 78%, transparent)',
  border: '1px solid var(--color-border)',
  boxShadow: '0 24px 80px -55px var(--color-accent)',
};

const secondaryButtonStyle = {
  color: 'var(--color-text)',
  background: 'var(--color-bg-secondary)',
  border: '1px solid var(--color-border)',
};
