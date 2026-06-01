import { useEffect, useMemo, useState } from 'react';
import {
  BatteryCharging,
  Bell,
  CheckCircle2,
  Copy,
  Link2,
  Phone,
  RefreshCw,
  Send,
  ShieldCheck,
  Wifi,
} from 'lucide-react';
import {
  createMobilePairing,
  fetchMobileDiagnostics,
  sendMobileRemoteCommand,
  type MobileDiagnostics,
  type MobileDevice,
} from '../lib/api';

export function MobileCompanionPage() {
  const [data, setData] = useState<MobileDiagnostics | null>(null);
  const [pairingName, setPairingName] = useState('Android Companion');
  const [pairing, setPairing] = useState<{ device_id: string; pairing_code: string; websocket_path: string } | null>(null);
  const [command, setCommand] = useState('desktop status');
  const [message, setMessage] = useState('');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      setData(await fetchMobileDiagnostics());
      setMessage('');
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Failed to load mobile diagnostics');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    const interval = window.setInterval(load, 10000);
    return () => window.clearInterval(interval);
  }, []);

  const wsUrl = useMemo(() => {
    const host = window.location.hostname || '127.0.0.1';
    const port = window.location.port || '8000';
    return `ws://${host}:${port}/v1/mobile/ws`;
  }, []);

  const createPairing = async () => {
    setBusy(true);
    try {
      const result = await createMobilePairing(pairingName);
      setPairing(result);
      setMessage('Pairing code created. Enter it in the Android companion app.');
      await load();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Failed to create pairing');
    } finally {
      setBusy(false);
    }
  };

  const simulateCommand = async () => {
    setBusy(true);
    try {
      const result = await sendMobileRemoteCommand(command);
      setMessage(String(result.message || 'Remote command simulation queued.'));
      await load();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Failed to queue command');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto" style={{ background: 'var(--color-bg)' }}>
      <div className="max-w-6xl mx-auto px-6 py-6">
        <div className="flex items-start justify-between gap-4 mb-6">
          <div>
            <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>
              Mobile Companion
            </h1>
            <p className="text-sm mt-1" style={{ color: 'var(--color-text-secondary)' }}>
              Pair Android devices over your local LAN, relay voice commands, sync redacted notifications, and monitor device health.
            </p>
          </div>
          <button
            type="button"
            onClick={load}
            className="inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm"
            style={{ color: 'var(--color-text)', background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          >
            <RefreshCw size={15} />
            Refresh
          </button>
        </div>

        {message && (
          <div
            className="rounded-xl px-4 py-3 mb-5 text-sm"
            style={{ color: 'var(--color-text)', background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}
          >
            {message}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-5">
          <StatCard icon={Phone} label="Paired Devices" value={String(data?.connected_devices ?? 0)} />
          <StatCard icon={Wifi} label="Online Now" value={String(data?.online_devices ?? 0)} />
          <StatCard icon={Bell} label="Synced Notifications" value={String(data?.notifications?.length ?? 0)} />
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-[1fr_1.25fr] gap-5">
          <section className="rounded-2xl p-4" style={panelStyle}>
            <div className="flex items-center gap-2 mb-3">
              <Link2 size={18} style={{ color: 'var(--color-accent-amber)' }} />
              <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Secure LAN Pairing</h2>
            </div>
            <label className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>Device name</label>
            <input
              value={pairingName}
              onChange={(event) => setPairingName(event.target.value)}
              className="w-full mt-1 mb-3 rounded-xl px-3 py-2 bg-transparent text-sm outline-none"
              style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
            />
            <button
              type="button"
              onClick={createPairing}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm"
              style={{ color: 'var(--color-on-accent)', background: 'var(--color-accent)' }}
            >
              <ShieldCheck size={15} />
              Create Pairing Code
            </button>
            <div className="mt-4 rounded-xl p-3" style={{ background: 'var(--color-bg)' }}>
              <div className="text-xs uppercase tracking-[0.16em]" style={{ color: 'var(--color-text-tertiary)' }}>WebSocket</div>
              <div className="font-mono text-xs mt-1 break-all" style={{ color: 'var(--color-text-secondary)' }}>{wsUrl}</div>
            </div>
            {pairing && (
              <div className="mt-3 rounded-xl p-3" style={{ background: 'color-mix(in srgb, var(--color-accent) 14%, transparent)' }}>
                <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>Pairing code</div>
                <div className="text-3xl font-semibold tracking-[0.18em]" style={{ color: 'var(--color-text)' }}>{pairing.pairing_code}</div>
                <div className="text-xs mt-1" style={{ color: 'var(--color-text-tertiary)' }}>Expires in 10 minutes. Pairing remains local to your LAN.</div>
              </div>
            )}
          </section>

          <section className="rounded-2xl p-4" style={panelStyle}>
            <div className="flex items-center justify-between gap-3 mb-3">
              <div className="flex items-center gap-2">
                <Phone size={18} style={{ color: 'var(--color-accent-amber)' }} />
                <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Devices</h2>
              </div>
              <StatusPill>{loading ? 'checking' : 'live'}</StatusPill>
            </div>
            {!data?.devices?.length ? (
              <EmptyState text="No Android companion is paired yet." />
            ) : (
              <div className="space-y-3">
                {data.devices.map((device) => <DeviceCard key={device.device_id} device={device} />)}
              </div>
            )}
          </section>
        </div>

        <div className="grid grid-cols-1 xl:grid-cols-2 gap-5 mt-5">
          <section className="rounded-2xl p-4" style={panelStyle}>
            <div className="flex items-center gap-2 mb-3">
              <Send size={18} style={{ color: 'var(--color-accent-amber)' }} />
              <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Remote Command Simulation</h2>
            </div>
            <input
              value={command}
              onChange={(event) => setCommand(event.target.value)}
              className="w-full rounded-xl px-3 py-2 bg-transparent text-sm outline-none"
              style={{ color: 'var(--color-text)', border: '1px solid var(--color-border)' }}
            />
            <button
              type="button"
              onClick={simulateCommand}
              disabled={busy}
              className="mt-3 inline-flex items-center gap-2 rounded-xl px-3 py-2 text-sm"
              style={{ color: 'var(--color-on-accent)', background: 'var(--color-accent)' }}
            >
              <Send size={15} />
              Queue Command
            </button>
            <p className="text-xs mt-3" style={{ color: 'var(--color-text-secondary)' }}>
              Safe requests queue normally. Messaging, clipboard, payment, call, and destructive commands are approval-gated.
            </p>
          </section>

          <section className="rounded-2xl p-4" style={panelStyle}>
            <div className="flex items-center gap-2 mb-3">
              <Bell size={18} style={{ color: 'var(--color-accent-amber)' }} />
              <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>Recent Mobile Events</h2>
            </div>
            {!data?.events?.length ? (
              <EmptyState text="No mobile events yet." />
            ) : (
              <div className="space-y-2">
                {data.events.slice(0, 8).map((event) => (
                  <div key={event.id} className="rounded-xl px-3 py-2" style={{ background: 'var(--color-bg)' }}>
                    <div className="text-xs font-medium" style={{ color: 'var(--color-text)' }}>{event.event_type}</div>
                    <div className="text-xs mt-1" style={{ color: 'var(--color-text-secondary)' }}>{event.summary}</div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

const panelStyle = {
  background: 'color-mix(in srgb, var(--color-bg-secondary) 78%, transparent)',
  border: '1px solid color-mix(in srgb, var(--color-accent) 14%, var(--color-border))',
  boxShadow: '0 18px 44px -38px var(--color-accent)',
} as const;

function StatCard({ icon: Icon, label, value }: { icon: typeof Phone; label: string; value: string }) {
  return (
    <section className="rounded-2xl p-4" style={panelStyle}>
      <Icon size={18} style={{ color: 'var(--color-accent-amber)' }} />
      <div className="text-2xl font-semibold mt-2" style={{ color: 'var(--color-text)' }}>{value}</div>
      <div className="text-xs mt-1" style={{ color: 'var(--color-text-secondary)' }}>{label}</div>
    </section>
  );
}

function DeviceCard({ device }: { device: MobileDevice }) {
  return (
    <div className="rounded-xl p-3" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="font-medium text-sm" style={{ color: 'var(--color-text)' }}>{device.name}</div>
          <div className="font-mono text-[11px] mt-1" style={{ color: 'var(--color-text-tertiary)' }}>{device.device_id}</div>
        </div>
        <StatusPill>{device.online ? 'online' : device.paired ? 'paired' : 'pending'}</StatusPill>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-3">
        <MiniMetric icon={BatteryCharging} label="Battery" value={device.status?.battery == null ? 'unknown' : `${device.status.battery}%`} />
        <MiniMetric icon={CheckCircle2} label="Charging" value={device.status?.charging ? 'yes' : 'no'} />
        <MiniMetric icon={Wifi} label="Network" value={device.status?.connectivity || 'unknown'} />
        <MiniMetric icon={Copy} label="Clipboard" value={device.permissions?.clipboard_sync ? 'allowed' : 'approval'} />
      </div>
    </div>
  );
}

function MiniMetric({ icon: Icon, label, value }: { icon: typeof Phone; label: string; value: string }) {
  return (
    <div className="rounded-lg px-2 py-2" style={{ background: 'color-mix(in srgb, var(--color-bg-secondary) 72%, transparent)' }}>
      <Icon size={14} style={{ color: 'var(--color-accent)' }} />
      <div className="text-[11px] mt-1" style={{ color: 'var(--color-text-tertiary)' }}>{label}</div>
      <div className="text-xs" style={{ color: 'var(--color-text)' }}>{value}</div>
    </div>
  );
}

function StatusPill({ children }: { children: string }) {
  return (
    <span
      className="rounded-full px-2 py-1 text-[10px] uppercase tracking-[0.14em]"
      style={{
        color: children === 'online' || children === 'live' ? 'var(--color-success)' : 'var(--color-warning)',
        background: 'color-mix(in srgb, currentColor 12%, transparent)',
        border: '1px solid color-mix(in srgb, currentColor 32%, transparent)',
      }}
    >
      {children}
    </span>
  );
}

function EmptyState({ text }: { text: string }) {
  return <div className="py-6 text-sm" style={{ color: 'var(--color-text-secondary)' }}>{text}</div>;
}
