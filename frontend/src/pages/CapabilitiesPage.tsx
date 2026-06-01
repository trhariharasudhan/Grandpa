import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BriefcaseBusiness,
  Code2,
  FileSearch,
  Home,
  MessageCircle,
  Phone,
  RefreshCw,
  ShieldCheck,
  ShoppingBag,
  Sparkles,
  Workflow,
} from 'lucide-react';
import { fetchCapabilityDiagnostics, type CapabilityDiagnostics } from '../lib/api';

type StatusTone = 'ready' | 'warning' | 'error';

export function CapabilitiesPage() {
  const [data, setData] = useState<CapabilityDiagnostics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchCapabilityDiagnostics());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load capability diagnostics');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const readiness = useMemo(() => {
    if (!data) return { ready: 0, total: 10 };
    const statuses = [
      data.fileIntelligence.status,
      data.office.status,
      data.automation.status,
      data.developer.status,
      data.security.status,
      data.mobile.status,
      data.communication.status,
      data.realWorld.status,
      data.iot.status,
      data.future.status,
    ];
    return { ready: statuses.filter((status) => status === 'ready').length, total: statuses.length };
  }, [data]);

  return (
    <div className="h-full overflow-y-auto" style={{ background: 'var(--color-bg)' }}>
      <div className="max-w-6xl mx-auto px-6 py-6">
        <div className="flex items-start justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>
              Grandpa Capabilities
            </h1>
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
              Unified diagnostics for local intelligence, communication, devices, automation, safety, and future simulation layers.
            </p>
          </div>
          <button
            type="button"
            onClick={load}
            className="inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm transition-colors"
            style={{
              color: 'var(--color-text)',
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
            }}
          >
            <RefreshCw size={15} />
            Refresh
          </button>
        </div>

        <section
          className="rounded-2xl p-4 mb-5"
          style={{
            background:
              'linear-gradient(135deg, color-mix(in srgb, var(--color-accent) 16%, transparent), color-mix(in srgb, var(--color-accent-amber) 8%, transparent))',
            border: '1px solid color-mix(in srgb, var(--color-accent) 24%, var(--color-border))',
          }}
        >
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-xs uppercase tracking-[0.18em]" style={{ color: 'var(--color-text-tertiary)' }}>
                Completion Readiness
              </div>
              <div className="text-xl font-semibold mt-1" style={{ color: 'var(--color-text)' }}>
                {readiness.ready}/{readiness.total} capability systems ready
              </div>
            </div>
            <StatusBadge tone={readiness.ready === readiness.total ? 'ready' : 'warning'}>
              {loading ? 'checking' : readiness.ready === readiness.total ? 'ready' : 'partial'}
            </StatusBadge>
          </div>
        </section>

        {error && (
          <div
            className="rounded-xl px-4 py-3 mb-5 text-sm flex items-center gap-2"
            style={{ color: 'var(--color-error)', background: 'var(--color-bg-secondary)', border: '1px solid var(--color-error)' }}
          >
            <AlertTriangle size={16} />
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <CapabilityCard
            icon={FileSearch}
            title="File Intelligence"
            status={data?.fileIntelligence.status}
            metric={`${data?.fileIntelligence.indexed_documents ?? 0} indexed`}
            details={[
              `Types: ${(data?.fileIntelligence.supported_types || []).slice(0, 8).join(', ') || 'loading'}`,
              `Local storage: ${data?.fileIntelligence.storage?.local_only ? 'yes' : 'unknown'}`,
              `Bulk operations: approval gated`,
            ]}
          />
          <CapabilityCard
            icon={BriefcaseBusiness}
            title="Office Productivity"
            status={data?.office.status}
            metric={`${data?.office.templates?.length ?? 0} templates`}
            details={[
              boolLine('Spreadsheet analysis', data?.office.features?.csv_xlsx_analysis),
              boolLine('Report generation', data?.office.features?.report_generation),
              boolLine('Cloud upload disabled', data?.office.safety?.cloud_upload === false),
            ]}
          />
          <CapabilityCard
            icon={Workflow}
            title="Smart Automation"
            status={data?.automation.status}
            metric={`${data?.automation.workflow_count ?? 0} workflows`}
            details={[
              `${data?.automation.enabled_count ?? 0} enabled`,
              `Triggers: ${Array.isArray(data?.automation.features?.triggers) ? data?.automation.features?.triggers.join(', ') : 'time, app, browser'}`,
              `Dry-run simulation: ${data?.automation.features?.dry_run ? 'ready' : 'unknown'}`,
            ]}
          />
          <CapabilityCard
            icon={Code2}
            title="Developer Tools"
            status={data?.developer.status}
            metric={`${Object.values(data?.developer.project?.checks || {}).filter(Boolean).length}/${Object.values(data?.developer.project?.checks || {}).length || 0} checks`}
            details={[
              `Git branch: ${String(data?.developer.git?.branch || 'unknown')}`,
              `Docker: ${data?.developer.docker?.daemon_reachable ? 'reachable' : 'limited'}`,
              `Risky commands: confirmation gated`,
            ]}
          />
          <CapabilityCard
            icon={ShieldCheck}
            title="Security & Safety"
            status={data?.security.status}
            metric={`${data?.security.health?.score ?? 0}/100`}
            details={[
              `Health: ${data?.security.health?.label || 'checking'}`,
              `Encrypted sensitive memory: ${data?.security.encrypted_sensitive_memory ? 'ready' : 'unknown'}`,
              `Suspicious action detection: ${data?.security.suspicious_detection ? 'ready' : 'unknown'}`,
            ]}
          />
          <CapabilityCard
            icon={Phone}
            title="Mobile Integration"
            status={data?.mobile.status}
            metric={`${data?.mobile.connected_devices ?? 0} paired`}
            details={[
              `Pairing: local LAN WebSocket`,
              `Online: ${data?.mobile.online_devices ?? 0}`,
              `Notifications: ${data?.mobile.notifications?.length ?? 0} synced`,
              `Clipboard sync: approval gated`,
            ]}
          />
          <CapabilityCard
            icon={MessageCircle}
            title="Communication"
            status={data?.communication.status}
            metric={`${data?.communication.pending_replies?.length ?? 0} replies`}
            details={[
              `Services: ${data?.communication.services?.length ?? 0}`,
              `Reply sending: approval gated`,
              `Logs: redacted`,
            ]}
          />
          <CapabilityCard
            icon={ShoppingBag}
            title="Real World Tasks"
            status={data?.realWorld.status}
            metric={`${data?.realWorld.active_workflows?.length ?? 0} active`}
            details={[
              `Shopping research: ${data?.realWorld.features?.shopping_research ? 'ready' : 'unknown'}`,
              `Booking planner: ${Array.isArray(data?.realWorld.features?.booking_planner) ? 'ready' : 'unknown'}`,
              `Auto-purchase: never`,
            ]}
          />
          <CapabilityCard
            icon={Home}
            title="Smart Home"
            status={data?.iot.status}
            metric={`${data?.iot.devices?.length ?? 0} devices`}
            details={[
              `Raspberry Pi: ${String(data?.iot.raspberry_pi?.status || 'not connected')}`,
              `Mode: local LAN / simulation`,
              `Risky controls: approval gated`,
            ]}
          />
          <CapabilityCard
            icon={Sparkles}
            title="Future Features"
            status={data?.future.status}
            metric={`${data?.future.connectors?.length ?? 0} connectors`}
            details={[
              `Avatar: ${String(data?.future.avatar?.state || 'idle')}`,
              `Overlay: simulation-ready`,
              `Real hardware: ${data?.future.hardware?.real_hardware_connected ? 'connected' : 'not connected'}`,
            ]}
          />
        </div>
      </div>
    </div>
  );
}

function CapabilityCard({
  icon: Icon,
  title,
  status,
  metric,
  details,
}: {
  icon: typeof FileSearch;
  title: string;
  status?: string;
  metric: string;
  details: string[];
}) {
  const tone: StatusTone = status === 'ready' ? 'ready' : status ? 'warning' : 'warning';
  return (
    <section
      className="rounded-2xl p-4"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-secondary) 78%, transparent)',
        border: '1px solid color-mix(in srgb, var(--color-accent) 14%, var(--color-border))',
        boxShadow: '0 18px 44px -38px var(--color-accent)',
      }}
    >
      <div className="flex items-start gap-3">
        <div
          className="rounded-xl p-2"
          style={{
            color: 'var(--color-accent-amber)',
            background: 'color-mix(in srgb, var(--color-accent) 14%, transparent)',
          }}
        >
          <Icon size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
              {title}
            </h2>
            <StatusBadge tone={tone}>{status || 'checking'}</StatusBadge>
          </div>
          <div className="text-2xl font-semibold mt-2" style={{ color: 'var(--color-text)' }}>
            {metric}
          </div>
          <div className="mt-3 space-y-1">
            {details.map((detail) => (
              <div key={detail} className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                {detail}
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

function StatusBadge({ tone, children }: { tone: StatusTone; children: string }) {
  const color =
    tone === 'ready'
      ? 'var(--color-success)'
      : tone === 'error'
      ? 'var(--color-error)'
      : 'var(--color-warning)';
  return (
    <span
      className="rounded-full px-2 py-1 text-[10px] uppercase tracking-[0.14em]"
      style={{
        color,
        background: 'color-mix(in srgb, currentColor 12%, transparent)',
        border: '1px solid color-mix(in srgb, currentColor 32%, transparent)',
      }}
    >
      {children}
    </span>
  );
}

function boolLine(label: string, value: unknown): string {
  return `${label}: ${value ? 'ready' : 'unknown'}`;
}
