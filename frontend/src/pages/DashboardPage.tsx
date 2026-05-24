import { useNavigate } from 'react-router';
import type { CSSProperties } from 'react';
import {
  Activity,
  Brain,
  Cpu,
  Database,
  GitBranch,
  MessageSquare,
  Radio,
  Settings,
  Sparkles,
  Zap,
} from 'lucide-react';
import { EnergyDashboard } from '../components/Dashboard/EnergyDashboard';
import { TraceDebugger } from '../components/Dashboard/TraceDebugger';

export function DashboardPage() {
  const navigate = useNavigate();
  const now = new Date();
  const stamp = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 md:px-8 md:py-10">
      <div className="max-w-6xl mx-auto">
        <header className="hud-panel overflow-hidden mb-5">
          <div
            className="absolute inset-0 pointer-events-none"
            style={{
              background:
                'radial-gradient(circle at 18% 0%, var(--color-accent-subtle), transparent 36%), radial-gradient(circle at 92% 20%, var(--color-accent-amber-subtle), transparent 34%)',
            }}
          />
          <div className="relative p-6 md:p-8">
            <div className="flex flex-col lg:flex-row lg:items-start justify-between gap-6">
              <div>
                <div className="hud-label mb-3 flex items-center gap-2">
                  <span className="hud-heartbeat" />
                  <Sparkles size={13} style={{ color: 'var(--color-accent-amber)' }} />
                  Grandpa personal assistant
                </div>
                <h1 className="text-3xl md:text-4xl font-semibold" style={{ color: 'var(--color-text)' }}>
                  Assistant command center<span className="hud-caret" />
                </h1>
                <p className="text-sm mt-3 max-w-2xl leading-6" style={{ color: 'var(--color-text-secondary)' }}>
                  A focused home for chat, context, local runtime health, and the reasoning signals that keep Grandpa useful on your machine.
                </p>
              </div>
              <div
                className="min-w-[220px] rounded-2xl p-4"
                style={{
                  background: 'color-mix(in srgb, var(--color-bg-secondary) 72%, transparent)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <div className="flex items-center justify-between mb-3">
                  <span className="hud-label">Live Runtime</span>
                  <span className="hud-mono text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{stamp}</span>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  <SignalPill icon={Cpu} label="Engine" value="Local" />
                  <SignalPill icon={Brain} label="Mode" value="Assist" />
                  <SignalPill icon={Radio} label="Link" value="Ready" />
                </div>
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-8">
              <AssistantAction
                icon={MessageSquare}
                title="Open Chat"
                description="Ask, draft, search, and reason with Grandpa."
                primary
                onClick={() => navigate('/')}
              />
              <AssistantAction
                icon={Database}
                title="Connect Context"
                description="Let Grandpa answer from your own sources."
                onClick={() => navigate('/data-sources')}
              />
              <AssistantAction
                icon={Settings}
                title="Tune Assistant"
                description="Adjust model, voice, memory, and defaults."
                onClick={() => navigate('/settings')}
              />
            </div>
          </div>
        </header>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-5">
          <HudStatusCard icon={Zap} label="Assistant Flow" value="Chat-first" detail="Prompt, research, answer" accent="var(--color-accent)" />
          <HudStatusCard icon={Database} label="Context Layer" value="Memory-ready" detail="Sources, channels, recall" accent="var(--color-accent-amber)" />
          <HudStatusCard icon={GitBranch} label="Reasoning Trace" value="On demand" detail="Routes, tools, generation" accent="var(--color-accent-purple)" />
        </div>

        <section className="mb-5">
          <div className="flex items-center justify-between gap-3 mb-3">
            <div>
              <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                Assistant Runtime
              </h2>
              <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
                Local health, energy, throughput, and session signals for the personal assistant runtime.
              </p>
            </div>
            <Activity size={16} style={{ color: 'var(--color-accent)' }} />
          </div>
          <EnergyDashboard />
        </section>

        <section className="mb-2">
          <div className="flex items-center gap-2 mb-3">
            <GitBranch size={14} style={{ color: 'var(--color-accent)' }} />
            <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
              Recent Reasoning Trace
            </h2>
          </div>
          <TraceDebugger />
        </section>
      </div>
    </div>
  );
}

function AssistantAction({
  icon: Icon,
  title,
  description,
  primary,
  onClick,
}: {
  icon: typeof MessageSquare;
  title: string;
  description: string;
  primary?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="text-left rounded-xl p-4 transition-all cursor-pointer"
      style={{
        background: primary
          ? 'linear-gradient(135deg, var(--color-accent), var(--color-accent-purple-hover))'
          : 'color-mix(in srgb, var(--color-bg-secondary) 86%, transparent)',
        border: primary ? '1px solid var(--color-accent)' : '1px solid var(--color-border)',
        color: primary ? 'var(--color-on-accent)' : 'var(--color-text)',
        boxShadow: primary ? '0 18px 44px -24px var(--color-accent)' : 'none',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.transform = 'translateY(-1px)';
        if (!primary) e.currentTarget.style.borderColor = 'var(--color-accent)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.transform = 'translateY(0)';
        if (!primary) e.currentTarget.style.borderColor = 'var(--color-border)';
      }}
    >
      <Icon size={18} style={{ color: primary ? 'var(--color-on-accent)' : 'var(--color-accent-amber)' }} />
      <div className="font-medium text-sm mt-3">{title}</div>
      <div
        className="text-xs mt-1 leading-5"
        style={{ color: primary ? 'rgba(255,255,255,0.78)' : 'var(--color-text-secondary)' }}
      >
        {description}
      </div>
    </button>
  );
}

function SignalPill({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Cpu;
  label: string;
  value: string;
}) {
  return (
    <div
      className="rounded-xl px-2.5 py-2"
      style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border-subtle)' }}
    >
      <Icon size={13} style={{ color: 'var(--color-accent-amber)' }} />
      <div className="text-[9px] uppercase tracking-[0.14em] mt-2" style={{ color: 'var(--color-text-tertiary)' }}>
        {label}
      </div>
      <div className="text-xs font-semibold hud-mono" style={{ color: 'var(--color-text)' }}>
        {value}
      </div>
    </div>
  );
}

function HudStatusCard({
  icon: Icon,
  label,
  value,
  detail,
  accent,
}: {
  icon: typeof Cpu;
  label: string;
  value: string;
  detail: string;
  accent: string;
}) {
  return (
    <div className="hud-panel p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="hud-label">{label}</div>
          <div className="text-lg font-semibold mt-1" style={{ color: 'var(--color-text)' }}>
            {value}
          </div>
        </div>
        <div
          className="hud-reticle"
          style={{ color: accent } as CSSProperties}
        >
          <Icon size={15} style={{ color: accent }} />
        </div>
      </div>
      <div className="text-xs mt-3" style={{ color: 'var(--color-text-secondary)' }}>{detail}</div>
      <div className="h-1 rounded-full mt-4 overflow-hidden" style={{ background: 'var(--color-bg-tertiary)' }}>
        <div className="hud-shimmer h-full w-2/3" />
      </div>
    </div>
  );
}
