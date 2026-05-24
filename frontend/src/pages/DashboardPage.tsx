import { useNavigate } from 'react-router';
import { Activity, Database, GitBranch, MessageSquare, Settings, Sparkles } from 'lucide-react';
import { EnergyDashboard } from '../components/Dashboard/EnergyDashboard';
import { TraceDebugger } from '../components/Dashboard/TraceDebugger';

export function DashboardPage() {
  const navigate = useNavigate();
  const now = new Date();
  const stamp = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  return (
    <div className="flex-1 overflow-y-auto px-4 py-6 md:px-8 md:py-10">
      <div className="max-w-5xl mx-auto">
        <header className="hud-panel overflow-hidden mb-5">
          <div className="p-6 md:p-8">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="hud-label mb-3 flex items-center gap-2">
                  <Sparkles size={13} style={{ color: 'var(--color-accent-amber)' }} />
                  Personal assistant
                </div>
                <h1 className="text-2xl md:text-3xl font-semibold" style={{ color: 'var(--color-text)' }}>
                  What should Grandpa help with?
                </h1>
                <p className="text-sm mt-3 max-w-2xl leading-6" style={{ color: 'var(--color-text-secondary)' }}>
                  Start with chat, connect your context, or open diagnostics when you need to understand the local assistant runtime.
                </p>
              </div>
              <div className="hidden sm:block text-xs hud-mono" style={{ color: 'var(--color-text-tertiary)' }}>
                {stamp}
              </div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-7">
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

        <section className="mb-4">
          <div className="flex items-center justify-between gap-3 mb-3">
            <div>
              <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                Assistant Runtime
              </h2>
              <p className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
                Quiet local health signals. Open these when something feels slow or unavailable.
              </p>
            </div>
            <Activity size={16} style={{ color: 'var(--color-accent)' }} />
          </div>
          <EnergyDashboard />
        </section>

        <section>
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
        background: primary ? 'var(--color-accent)' : 'var(--color-bg-secondary)',
        border: primary ? '1px solid var(--color-accent)' : '1px solid var(--color-border)',
        color: primary ? 'var(--color-on-accent)' : 'var(--color-text)',
        boxShadow: primary ? '0 14px 32px -18px var(--color-accent)' : 'none',
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
