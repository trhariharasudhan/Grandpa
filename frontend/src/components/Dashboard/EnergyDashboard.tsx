import { useState, useEffect, useCallback } from 'react';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import { Zap, Activity, Thermometer, Hash, Gauge, Cpu, Radio } from 'lucide-react';
import { fetchEnergy, fetchTelemetry } from '../../lib/api';
import { useAppStore } from '../../lib/store';

interface EnergySample {
  timestamp: string;
  power_w: number;
  energy_j: number;
}

interface EnergyData {
  total_energy_j?: number;
  energy_per_token_j?: number;
  avg_power_w?: number;
  samples?: EnergySample[];
}

interface TelemetryStats {
  total_requests?: number;
  total_tokens?: number;
}

interface ChartPoint {
  time: string;
  power: number;
}

function StatCard({
  icon: Icon,
  label,
  value,
  unit,
  accent = 'var(--color-accent)',
}: {
  icon: typeof Zap;
  label: string;
  value: string;
  unit?: string;
  accent?: string;
}) {
  return (
    <div className="hud-panel p-4">
      <div className="flex items-center gap-2 mb-2">
        <Icon size={12} style={{ color: accent }} />
        <span className="hud-label">{label}</span>
      </div>
      <div className="hud-mono text-2xl font-semibold truncate" style={{ color: 'var(--color-text)' }}>
        {value}
        {unit && (
          <span className="hud-label ml-1" style={{ fontSize: '0.625rem', letterSpacing: '0.18em' }}>
            {unit}
          </span>
        )}
      </div>
    </div>
  );
}

export function EnergyDashboard() {
  const runtimeUsage = useAppStore((s) => s.runtimeUsage);
  const [energy, setEnergy] = useState<EnergyData | null>(null);
  const [telemetry, setTelemetry] = useState<TelemetryStats | null>(null);
  const [chartData, setChartData] = useState<ChartPoint[]>([]);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [energyRes, telRes] = await Promise.allSettled([
        fetchEnergy().catch(() => null),
        fetchTelemetry().catch(() => null),
      ]);

      if (energyRes.status === 'fulfilled' && energyRes.value) {
        const data = energyRes.value as EnergyData;
        setEnergy(data);
        if (data.samples) {
          setChartData(
            data.samples.map((s) => ({
              time: new Date(s.timestamp).toLocaleTimeString(),
              power: Math.round(s.power_w * 10) / 10,
            })),
          );
        }
        setError(null);
      }
      if (telRes.status === 'fulfilled' && telRes.value) {
        setTelemetry(telRes.value as TelemetryStats);
      }
    } catch {
      setError('Cannot connect to server');
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 5000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const thermalStatus = (energy?.avg_power_w ?? 0) < 50
    ? { label: 'Cool', color: 'var(--color-success)' }
    : (energy?.avg_power_w ?? 0) < 150
    ? { label: 'Warm', color: 'var(--color-warning)' }
    : { label: 'Hot', color: 'var(--color-error)' };

  if (error || !energy) {
    return (
      <div className="hud-panel p-6">
        <h3 className="hud-label flex items-center gap-2 mb-4">
          <Zap size={12} style={{ color: 'var(--color-accent)' }} />
          Energy Monitoring
        </h3>
        <div className="h-48 flex items-center justify-center text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
          <span className="hud-mono">{error || 'awaiting telemetry stream…'}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="hud-panel p-6">
      <div className="hud-panel-head flex flex-col md:flex-row md:items-center justify-between gap-4 mb-5">
        <div>
          <h3 className="hud-label flex items-center gap-2">
            <span className="hud-heartbeat" />
            <Zap size={12} style={{ color: 'var(--color-accent-amber)' }} />
            Runtime Matrix
          </h3>
          <p className="text-xs mt-2" style={{ color: 'var(--color-text-secondary)' }}>
            Local engine activity, energy draw, and assistant throughput.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <RuntimeBadge icon={Cpu} label="Engine" value="On-device" />
          <RuntimeBadge icon={Radio} label="Signal" value={error ? 'Offline' : 'Stable'} />
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-3 gap-3 mb-5">
        <StatCard
          icon={Zap}
          label="Total Energy"
          value={((energy.total_energy_j ?? 0) / 1000).toFixed(1)}
          unit="kJ"
          accent="var(--color-accent-amber)"
        />
        <StatCard
          icon={Activity}
          label="Energy / Token"
          value={(energy.energy_per_token_j ?? 0).toFixed(3)}
          unit="J"
          accent="var(--color-accent)"
        />
        <StatCard
          icon={Thermometer}
          label="Avg Power"
          value={(energy.avg_power_w ?? 0).toFixed(1)}
          unit="W"
          accent={thermalStatus.color}
        />
        <StatCard
          icon={Hash}
          label="Total Requests"
          value={String(runtimeUsage?.total_calls ?? telemetry?.total_requests ?? 0)}
        />
        <StatCard
          icon={Gauge}
          label="Thermal"
          value={thermalStatus.label}
          accent={thermalStatus.color}
        />
        <StatCard
          icon={Hash}
          label="Tokens Processed"
          value={formatNumber(runtimeUsage?.total_tokens ?? telemetry?.total_tokens ?? 0)}
        />
      </div>

      <div
        className="rounded-2xl p-4"
        style={{
          background: 'color-mix(in srgb, var(--color-bg-secondary) 74%, transparent)',
          border: '1px solid var(--color-border-subtle)',
        }}
      >
        <div className="flex items-center justify-between mb-3">
          <span className="hud-label">Power Curve</span>
          <span className="hud-mono text-[10px]" style={{ color: 'var(--color-text-tertiary)' }}>
            {chartData.length > 1 ? `${chartData.length} samples` : 'awaiting stream'}
          </span>
        </div>
        <div className="h-52">
          {chartData.length > 1 ? (
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border)" />
                <XAxis dataKey="time" tick={{ fontSize: 10, fill: 'var(--color-text-tertiary)' }} />
                <YAxis tick={{ fontSize: 10, fill: 'var(--color-text-tertiary)' }} unit="W" />
                <Tooltip
                  contentStyle={{
                    background: 'var(--color-surface)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 'var(--radius-md)',
                    fontSize: 12,
                    color: 'var(--color-text)',
                  }}
                />
                <Line type="monotone" dataKey="power" stroke="var(--color-accent)" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-full grid grid-cols-12 items-end gap-1.5 opacity-80">
              {Array.from({ length: 24 }).map((_, i) => (
                <div
                  key={i}
                  className="rounded-t-sm hud-shimmer"
                  style={{
                    height: `${18 + ((i * 17) % 62)}%`,
                    background: i % 5 === 0 ? 'var(--color-accent-amber-subtle)' : 'var(--color-accent-subtle)',
                  }}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function RuntimeBadge({
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
      className="rounded-xl px-3 py-2 min-w-[92px]"
      style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
    >
      <div className="flex items-center gap-1.5">
        <Icon size={12} style={{ color: 'var(--color-accent)' }} />
        <span className="text-[9px] uppercase tracking-[0.14em]" style={{ color: 'var(--color-text-tertiary)' }}>
          {label}
        </span>
      </div>
      <div className="hud-mono text-xs mt-1" style={{ color: 'var(--color-text)' }}>{value}</div>
    </div>
  );
}

function formatNumber(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
  return String(n);
}
