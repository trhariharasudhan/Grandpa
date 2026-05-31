import { useState, useEffect, useCallback } from 'react';
import {
  Zap,
  Activity,
  Thermometer,
  Hash,
  X,
  Gauge,
  Globe2,
  MessageSquare,
  Brain,
  Cpu,
} from 'lucide-react';
import { useAppStore } from '../../lib/store';
import { fetchBrowserContext, getBase, type BrowserContextSummary } from '../../lib/api';

interface EnergyData {
  total_energy_j?: number;
  energy_per_token_j?: number;
  avg_power_w?: number;
  cpu_temp_c?: number | null;
  gpu_temp_c?: number | null;
}

interface TelemetryStats {
  total_requests?: number;
  total_tokens?: number;
}

export function SystemPanel() {
  const runtimeUsage = useAppStore((s) => s.runtimeUsage);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const serverInfo = useAppStore((s) => s.serverInfo);
  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);
  const liveEnergy = useAppStore((s) => s.liveEnergy);
  const [energy, setEnergy] = useState<EnergyData | null>(null);
  const [telemetry, setTelemetry] = useState<TelemetryStats | null>(null);
  const [browserContext, setBrowserContext] = useState<BrowserContextSummary | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const base = getBase();
      const [energyRes, telRes] = await Promise.allSettled([
        fetch(`${base}/v1/telemetry/energy`).then((r) => (r.ok ? r.json() : null)),
        fetch(`${base}/v1/telemetry/stats`).then((r) => (r.ok ? r.json() : null)),
      ]);
      if (energyRes.status === 'fulfilled' && energyRes.value) {
        setEnergy(energyRes.value as EnergyData);
      }
      if (telRes.status === 'fulfilled' && telRes.value) {
        setTelemetry(telRes.value as TelemetryStats);
      }
      fetchBrowserContext()
        .then(setBrowserContext)
        .catch(() => setBrowserContext(null));
    } catch {
      // best-effort
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 3000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Re-fetch energy/telemetry when runtime counters update after a chat turn.
  useEffect(() => {
    if (runtimeUsage) fetchData();
  }, [runtimeUsage, fetchData]);

  return (
    <div
      className="flex flex-col h-full overflow-y-auto"
      style={{
        width: 292,
        minWidth: 292,
        background: 'linear-gradient(180deg, color-mix(in srgb, var(--color-bg) 88%, transparent), color-mix(in srgb, var(--color-surface) 82%, transparent))',
        borderLeft: '1px solid color-mix(in srgb, var(--color-accent) 18%, var(--color-border))',
        backdropFilter: 'blur(22px) saturate(126%)',
        WebkitBackdropFilter: 'blur(22px) saturate(126%)',
        boxShadow: 'inset 1px 0 0 color-mix(in srgb, var(--color-text) 4%, transparent), -18px 0 48px -44px var(--color-accent)',
      }}
    >
      {/* Header */}
      <div
        className="flex items-center justify-between px-4 py-3 shrink-0"
        style={{ borderBottom: '1px solid color-mix(in srgb, var(--color-accent) 14%, var(--color-border))' }}
      >
        <div>
          <span className="text-xs font-semibold tracking-wide uppercase" style={{ color: 'var(--color-text-secondary)' }}>
            Assistant Status
          </span>
          <div className="text-[11px] mt-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
            Local runtime signals
          </div>
        </div>
        <button
          onClick={toggleSystemPanel}
          className="p-1 rounded-md transition-colors cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
          title="Close panel"
        >
          <X size={14} />
        </button>
      </div>

      <div className="flex flex-col gap-4 p-4">
        <section
          className="rounded-xl px-3 py-3"
          style={{
            background:
              'linear-gradient(135deg, color-mix(in srgb, var(--color-accent) 20%, transparent), color-mix(in srgb, var(--color-accent-amber) 10%, transparent))',
            border: '1px solid color-mix(in srgb, var(--color-accent) 28%, var(--color-border))',
            boxShadow: '0 18px 42px -32px var(--color-accent), inset 0 1px 0 color-mix(in srgb, var(--color-text) 8%, transparent)',
          }}
        >
          <div className="flex items-center gap-2 mb-1">
            <span className="hud-heartbeat" />
            <MessageSquare size={14} style={{ color: 'var(--color-accent-amber)' }} />
            <span className="text-xs font-medium" style={{ color: 'var(--color-text)' }}>
              Chat-first workspace
            </span>
          </div>
          <p className="text-[11px] leading-5" style={{ color: 'var(--color-text-secondary)' }}>
            This panel stays quiet unless you need runtime health while Grandpa answers.
          </p>
        </section>

        <section>
          <h4 className="text-[11px] font-medium uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
            Core
          </h4>
          <div className="flex flex-col gap-2">
            <CoreLine icon={Cpu} label="Model" value={selectedModel || serverInfo?.model || 'Select model'} />
            <CoreLine icon={Brain} label="Runtime" value={serverInfo?.engine || 'local'} />
            <CoreLine
              icon={Globe2}
              label="Browser"
              value={
                browserContext?.extension?.connected
                  ? 'Extension connected'
                  : browserContext?.context.supported
                  ? browserContext.context.title || browserContext.context.browser || 'Visible'
                  : 'Extension offline'
              }
            />
          </div>
        </section>

        {(browserContext?.context.supported || browserContext?.extension) && (
          <section
            className="rounded-xl px-3 py-3"
            style={{
              background: 'color-mix(in srgb, var(--color-bg-secondary) 72%, transparent)',
              border: '1px solid color-mix(in srgb, var(--color-accent) 14%, var(--color-border))',
            }}
          >
            <div className="flex items-center gap-2 mb-1">
              <Globe2 size={13} style={{ color: 'var(--color-accent)' }} />
              <span className="text-xs font-medium" style={{ color: 'var(--color-text)' }}>
                Visible Browser
              </span>
              <span
                className="ml-auto text-[10px]"
                style={{
                  color: browserContext.extension?.connected ? 'var(--color-success)' : 'var(--color-warning)',
                }}
              >
                {browserContext.extension?.connected ? 'extension connected' : 'not connected'}
              </span>
            </div>
            <div className="text-[11px] leading-5 truncate" style={{ color: 'var(--color-text-secondary)' }}>
              {browserContext.context.title || browserContext.context.active_window_title || 'Load the browser extension'}
            </div>
            {browserContext.context.url && (
              <div className="text-[10px] leading-5 truncate" style={{ color: 'var(--color-text-tertiary)' }}>
                {browserContext.context.url}
              </div>
            )}
            <div className="text-[10px] mt-1" style={{ color: 'var(--color-text-tertiary)' }}>
              {browserContext.context.headings.length} headings · {browserContext.context.links.length} links · {browserContext.context.buttons.length} buttons · local only
            </div>
          </section>
        )}

        {/* Session Stats */}
        <section>
          <h4 className="text-[11px] font-medium uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
            Session
          </h4>
          <div className="grid grid-cols-2 gap-2">
            <MiniStat icon={Hash} label="Requests" value={String(runtimeUsage?.total_calls ?? telemetry?.total_requests ?? 0)} />
            <MiniStat icon={Hash} label="Output Tokens" value={formatNumber(runtimeUsage?.total_completion_tokens ?? telemetry?.total_tokens ?? 0)} />
          </div>
          <SignalMeter label="Context stream" value={runtimeUsage?.total_tokens ? 72 : 18} />
        </section>

        {/* Device */}
        <section>
          <h4 className="text-[11px] font-medium uppercase tracking-wide mb-2" style={{ color: 'var(--color-text-tertiary)' }}>
            Device
          </h4>
          <div className="grid grid-cols-2 gap-2">
            {energy?.cpu_temp_c != null && (
              <MiniStat icon={Thermometer} label="CPU Temp" value={String(Math.round(energy.cpu_temp_c))} unit="°C" />
            )}
            {energy?.gpu_temp_c != null && (
              <MiniStat icon={Thermometer} label="GPU Temp" value={String(Math.round(energy.gpu_temp_c))} unit="°C" />
            )}
            <MiniStat
              icon={Zap}
              label="Power"
              value={(liveEnergy?.power_w ?? energy?.avg_power_w ?? 0).toFixed(1)}
              unit="W"
            />
            <MiniStat
              icon={Activity}
              label="Energy"
              value={(
                ((liveEnergy?.energy_j ?? energy?.total_energy_j ?? 0) / 1000)
              ).toFixed(1)}
              unit="kJ"
            />
            <MiniStat
              icon={Gauge}
              label="Mode"
              value="Local"
            />
          </div>
          <SignalMeter label="Thermal headroom" value={(energy?.avg_power_w ?? 0) > 0 ? Math.max(12, 100 - (energy?.avg_power_w ?? 0) / 2) : 84} />
        </section>
      </div>
    </div>
  );
}

function CoreLine({
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
      className="flex items-center gap-2 rounded-lg px-3 py-2"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-secondary) 70%, transparent)',
        border: '1px solid color-mix(in srgb, var(--color-accent) 14%, var(--color-border))',
        boxShadow: 'inset 0 1px 0 color-mix(in srgb, var(--color-text) 5%, transparent)',
      }}
    >
      <Icon size={13} style={{ color: 'var(--color-accent-amber)' }} />
      <span className="text-[10px] uppercase tracking-[0.12em]" style={{ color: 'var(--color-text-tertiary)' }}>
        {label}
      </span>
      <span className="ml-auto text-xs truncate max-w-[130px]" style={{ color: 'var(--color-text)' }}>
        {value}
      </span>
    </div>
  );
}

function SignalMeter({ label, value }: { label: string; value: number }) {
  const width = Math.max(0, Math.min(100, value));
  return (
    <div className="mt-3">
      <div className="flex justify-between text-[10px] mb-1" style={{ color: 'var(--color-text-tertiary)' }}>
        <span>{label}</span>
        <span className="hud-mono">{Math.round(width)}%</span>
      </div>
      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--color-bg-tertiary)' }}>
        <div
          className="h-full hud-shimmer"
          style={{
            width: `${width}%`,
            background: 'linear-gradient(90deg, var(--color-accent), var(--color-accent-amber))',
          }}
        />
      </div>
    </div>
  );
}

function MiniStat({
  icon: Icon,
  label,
  value,
  unit,
}: {
  icon: typeof Zap;
  label: string;
  value: string;
  unit?: string;
}) {
  return (
    <div
      className="rounded-lg px-2.5 py-2"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-secondary) 72%, transparent)',
        border: '1px solid color-mix(in srgb, var(--color-accent) 12%, var(--color-border))',
        boxShadow: 'inset 0 1px 0 color-mix(in srgb, var(--color-text) 5%, transparent)',
      }}
    >
      <div className="flex items-center gap-1 mb-0.5">
        <Icon size={10} style={{ color: 'var(--color-accent)' }} />
        <span className="text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
          {label}
        </span>
      </div>
      <div className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
        {value}
        {unit && (
          <span className="text-[10px] font-normal ml-0.5" style={{ color: 'var(--color-text-tertiary)' }}>
            {unit}
          </span>
        )}
      </div>
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}
