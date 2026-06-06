import { useEffect, useState } from 'react';
import { Boxes, RefreshCw, ShieldCheck, Wrench } from 'lucide-react';
import {
  fetchPluginDiagnostics,
  reloadPlugins,
  setPluginEnabled,
  type PluginDiagnostics,
  type PluginInfo,
} from '../lib/api';

export function PluginsPage() {
  const [data, setData] = useState<PluginDiagnostics | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');

  const refresh = () => {
    fetchPluginDiagnostics()
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load plugins'));
  };

  useEffect(refresh, []);

  const toggle = async (plugin: PluginInfo) => {
    setBusy(plugin.name);
    setError('');
    try {
      await setPluginEnabled(plugin.name, !plugin.enabled);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Plugin update failed');
    } finally {
      setBusy('');
    }
  };

  const reload = async () => {
    setBusy('reload');
    setError('');
    try {
      const result = await reloadPlugins();
      setData(result.diagnostics);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Plugin reload failed');
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="h-full overflow-y-auto px-6 py-6" style={{ color: 'var(--color-text)' }}>
      <div className="mx-auto flex max-w-6xl flex-col gap-5">
        <header className="flex flex-col gap-2">
          <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent-amber)' }}>
            <Boxes size={16} />
            Dynamic Runtime Packages
          </div>
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <h1 className="text-2xl font-semibold">Plugins</h1>
              <p className="mt-2 max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                Manage local manifest-driven skill packages. Plugins can provide skills, but they cannot run arbitrary code or bypass approvals.
              </p>
            </div>
            <button className="flex items-center justify-center gap-2 rounded-xl px-4 py-2 text-sm font-medium" style={secondaryButton} onClick={reload} disabled={busy === 'reload'}>
              <RefreshCw size={15} />
              Reload
            </button>
          </div>
        </header>

        {error && (
          <div className="rounded-xl px-4 py-3 text-sm" style={{ border: '1px solid var(--color-danger)', color: 'var(--color-danger)' }}>
            {error}
          </div>
        )}

        <section className="grid gap-3 md:grid-cols-4">
          <Metric icon={Boxes} label="Plugins" value={String(data?.plugin_count ?? 0)} />
          <Metric icon={Wrench} label="Plugin Skills" value={String(data?.plugin_skill_count ?? 0)} />
          <Metric icon={ShieldCheck} label="Enabled" value={String(data?.enabled_count ?? 0)} />
          <Metric icon={RefreshCw} label="Runtime" value={data?.status || 'checking'} />
        </section>

        <section className="grid gap-3 lg:grid-cols-2">
          {(data?.plugins || []).map((plugin) => (
            <PluginCard key={plugin.name} plugin={plugin} busy={busy === plugin.name} onToggle={() => toggle(plugin)} />
          ))}
        </section>

        <section className="rounded-2xl p-4" style={panelStyle}>
          <h2 className="text-sm font-semibold">Discovery Roots</h2>
          <div className="mt-3 flex flex-col gap-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
            {(data?.roots || []).map((root) => <span key={root}>{root}</span>)}
          </div>
        </section>
      </div>
    </div>
  );
}

function PluginCard({ plugin, busy, onToggle }: { plugin: PluginInfo; busy: boolean; onToggle: () => void }) {
  const valid = plugin.status !== 'invalid';
  return (
    <article className="rounded-2xl p-4" style={panelStyle}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold">{plugin.name}</h2>
          <p className="mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>v{plugin.version}</p>
          <p className="mt-2 text-sm" style={{ color: 'var(--color-text-secondary)' }}>{plugin.description}</p>
        </div>
        <span className="rounded-lg px-2 py-1 text-xs font-semibold" style={{ color: statusColor(plugin), border: `1px solid ${statusColor(plugin)}` }}>
          {plugin.status}
        </span>
      </div>

      {plugin.error && <p className="mt-3 text-sm" style={{ color: 'var(--color-danger)' }}>{plugin.error}</p>}

      <div className="mt-4 flex flex-wrap gap-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
        {plugin.permissions.map((permission) => (
          <span key={permission} className="rounded-lg px-2 py-1" style={{ background: 'var(--color-bg-secondary)' }}>{permission}</span>
        ))}
      </div>

      <div className="mt-4 flex flex-col gap-2">
        {plugin.skills.map((skill) => (
          <div key={skill.name} className="rounded-xl px-3 py-2 text-sm" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
            <div className="flex items-center justify-between gap-3">
              <span>{skill.name}</span>
              <span style={{ color: skill.approval_required ? 'var(--color-warning)' : 'var(--color-success)' }}>{skill.risk_level}</span>
            </div>
            <p className="mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{skill.description}</p>
          </div>
        ))}
      </div>

      <button
        className="mt-4 rounded-xl px-4 py-2 text-sm font-medium"
        style={plugin.enabled ? secondaryButton : primaryButton}
        disabled={!valid || busy}
        onClick={onToggle}
      >
        {plugin.enabled ? 'Disable' : 'Enable'}
      </button>
    </article>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof Boxes; label: string; value: string }) {
  return (
    <div className="rounded-2xl p-4" style={panelStyle}>
      <Icon size={18} style={{ color: 'var(--color-accent)' }} />
      <div className="mt-3 text-xs uppercase tracking-[0.18em]" style={{ color: 'var(--color-text-tertiary)' }}>{label}</div>
      <div className="mt-1 text-lg font-semibold">{value}</div>
    </div>
  );
}

function statusColor(plugin: PluginInfo) {
  if (plugin.status === 'invalid') return 'var(--color-danger)';
  return plugin.enabled ? 'var(--color-success)' : 'var(--color-warning)';
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
