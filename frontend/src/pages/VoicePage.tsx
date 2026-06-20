import { useEffect, useMemo, useState } from 'react';
import type { ElementType, ReactNode } from 'react';
import { Activity, Mic2, Play, RefreshCw, Send, Square, Volume2, Waves } from 'lucide-react';
import {
  commandVoice,
  fetchVoiceStatus,
  speakVoice,
  startVoiceSession,
  stopVoiceSession,
  type VoiceListenResponse,
  type VoiceStatus,
} from '../lib/api';

export function VoicePage() {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [transcript, setTranscript] = useState('Hey Grandpa desktop summary');
  const [wakeRequired, setWakeRequired] = useState(false);
  const [speakResponse, setSpeakResponse] = useState(false);
  const [lastResult, setLastResult] = useState<VoiceListenResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      setStatus(await fetchVoiceStatus());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load voice status.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    const interval = window.setInterval(() => void load(), 15000);
    return () => window.clearInterval(interval);
  }, []);

  const sessionState = status?.session?.state || 'idle';
  const stateColor = useMemo(() => {
    if (sessionState === 'listening') return 'var(--color-accent-amber)';
    if (sessionState === 'thinking') return 'var(--color-accent)';
    if (sessionState === 'speaking') return 'var(--color-success)';
    if (sessionState === 'error') return 'var(--color-danger)';
    return 'var(--color-text-tertiary)';
  }, [sessionState]);

  const runListen = async (confirmed = false) => {
    if (!transcript.trim()) return;
    setBusy(true);
    setError('');
    try {
      const result = await commandVoice({
        transcript,
        speak: speakResponse,
        speak_response: speakResponse,
        require_wake_word: wakeRequired,
        confirmed,
      });
      setLastResult(result);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voice command failed.');
    } finally {
      setBusy(false);
    }
  };

  const start = async () => {
    setBusy(true);
    setError('');
    try {
      await startVoiceSession();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voice start failed.');
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    setBusy(true);
    setError('');
    try {
      await stopVoiceSession();
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voice stop failed.');
    } finally {
      setBusy(false);
    }
  };

  const testSpeak = async () => {
    setBusy(true);
    setError('');
    try {
      await speakVoice('Grandpa voice output is ready when a local speech engine is available.', true, false);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Speech output failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="h-full overflow-y-auto p-6" style={{ background: 'var(--color-bg)' }}>
      <div className="mx-auto flex max-w-7xl flex-col gap-5">
        <header className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent-amber)' }}>
              <Waves size={16} />
              Voice-first assistant runtime
            </div>
            <h1 className="mt-2 text-3xl font-semibold" style={{ color: 'var(--color-text)' }}>Voice Assistant</h1>
            <p className="mt-2 max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              Push-to-talk and transcript-based wake phrases route through Grandpa's planner, knowledge, memory, agents, and skills while preserving approval safety.
            </p>
          </div>
          <button type="button" onClick={() => void load()} className="inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </header>

        {error && (
          <div className="rounded-2xl px-4 py-3 text-sm" style={{ border: '1px solid var(--color-danger)', color: 'var(--color-danger)' }}>
            {error}
          </div>
        )}

        <section className="grid gap-4 md:grid-cols-4">
          <Metric icon={Mic2} label="Session" value={status?.session?.active ? 'Active' : 'Idle'} />
          <Metric icon={Activity} label="State" value={sessionState} color={stateColor} />
          <Metric icon={Waves} label="Input" value={String(status?.speech_input?.engine || 'checking')} />
          <Metric icon={Volume2} label="Output" value={String(status?.speech_output?.engine || 'checking')} />
        </section>

        <section className="grid gap-5 xl:grid-cols-[420px_1fr]">
          <Panel title="Voice Control">
            <div className="flex flex-col gap-3">
              <div className="grid grid-cols-2 gap-2">
                <button type="button" onClick={() => void start()} disabled={busy} className="inline-flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm font-medium disabled:opacity-60" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>
                  <Play size={15} />
                  Start
                </button>
                <button type="button" onClick={() => void stop()} disabled={busy} className="inline-flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                  <Square size={15} />
                  Stop
                </button>
              </div>
              <textarea
                value={transcript}
                onChange={(event) => setTranscript(event.target.value)}
                rows={5}
                className="rounded-xl px-3 py-2 text-sm outline-none"
                style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                placeholder="Type a transcript to simulate push-to-talk..."
              />
              <label className="flex items-center justify-between gap-3 rounded-xl px-3 py-2 text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
                Require wake phrase
                <input type="checkbox" checked={wakeRequired} onChange={(event) => setWakeRequired(event.target.checked)} />
              </label>
              <label className="flex items-center justify-between gap-3 rounded-xl px-3 py-2 text-sm" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
                Speak response when possible
                <input type="checkbox" checked={speakResponse} onChange={(event) => setSpeakResponse(event.target.checked)} />
              </label>
              <div className="grid gap-2 sm:grid-cols-2">
                <button type="button" onClick={() => void runListen()} disabled={busy || !transcript.trim()} className="inline-flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm font-medium disabled:opacity-60" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>
                  <Send size={15} />
                  Run Command
                </button>
                <button type="button" onClick={() => void testSpeak()} disabled={busy} className="inline-flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                  <Volume2 size={15} />
                  Test Speak
                </button>
              </div>
            </div>
          </Panel>

          <div className="flex flex-col gap-5">
            <Panel title="Runtime State">
              <div className="grid gap-3 md:grid-cols-3">
                <StatusBlock label="Wake Mode" value={String(status?.wake_word?.mode || 'checking')} />
                <StatusBlock label="Local Whisper" value={String(status?.speech_input?.local_whisper_available ? 'available' : 'not installed')} />
                <StatusBlock label="High-Risk Voice Block" value={status?.high_risk_voice_block ? 'enabled' : 'unknown'} />
              </div>
              <p className="mt-4 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                {String(status?.wake_word?.truthful_note || 'Wake readiness is detected locally.')}
              </p>
            </Panel>

            <Panel title="Last Voice Result">
              {lastResult ? (
                <div className="flex flex-col gap-3 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                  <div className="flex flex-wrap gap-2">
                    <Badge>{lastResult.status}</Badge>
                    <Badge>{lastResult.risk_level || 'LOW'}</Badge>
                    {lastResult.approval_required && <Badge>Approval required</Badge>}
                  </div>
                  <p style={{ color: 'var(--color-text)' }}>{lastResult.message}</p>
                  {lastResult.action?.status === 'needs_confirmation' && (
                    <button type="button" onClick={() => void runListen(true)} disabled={busy || !transcript.trim()} className="inline-flex w-fit items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm font-medium disabled:opacity-60" style={{ background: 'var(--color-accent-amber)', color: 'var(--color-bg)' }}>
                      Confirm Action
                    </button>
                  )}
                  <div className="rounded-xl p-3 text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
                    <div>Transcript: {lastResult.transcript || 'none'}</div>
                    <div>Command: {lastResult.command_text || lastResult.transcript || 'none'}</div>
                    <div>Action: {lastResult.action?.type || 'none'} / {lastResult.action?.status || lastResult.action_status || 'unknown'}</div>
                    {lastResult.action?.detail && <div>Detail: {lastResult.action.detail}</div>}
                    <div>Latency: {Math.round(lastResult.latency_ms || 0)} ms</div>
                  </div>
                </div>
              ) : (
                <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                  Send a transcript like "Hey Grandpa desktop summary" or "Hey Grandpa summarize this webpage" to test the voice route without microphone hardware.
                </p>
              )}
            </Panel>

            <Panel title="Speech History">
              <div className="flex max-h-[280px] flex-col gap-2 overflow-y-auto">
                {(status?.session?.last_messages || []).length === 0 ? (
                  <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>No voice messages yet.</p>
                ) : (
                  status?.session?.last_messages?.map((message) => (
                    <div key={`${message.timestamp}-${message.role}`} className="rounded-xl px-3 py-2 text-sm" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
                      <div className="text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--color-text-tertiary)' }}>{message.role}</div>
                      <div style={{ color: 'var(--color-text)' }}>{message.content}</div>
                    </div>
                  ))
                )}
              </div>
            </Panel>
          </div>
        </section>
      </div>
    </main>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl p-4" style={{ background: 'color-mix(in srgb, var(--color-bg-secondary) 82%, transparent)', border: '1px solid var(--color-border)', boxShadow: '0 20px 60px -36px var(--color-accent-glow)' }}>
      <h2 className="mb-4 text-sm font-semibold" style={{ color: 'var(--color-text)' }}>{title}</h2>
      {children}
    </section>
  );
}

function Metric({ icon: Icon, label, value, color }: { icon: ElementType; label: string; value: string; color?: string }) {
  return (
    <div className="rounded-2xl p-4" style={{ background: 'color-mix(in srgb, var(--color-bg-secondary) 82%, transparent)', border: '1px solid var(--color-border)' }}>
      <div className="flex items-center gap-2 text-xs uppercase tracking-[0.16em]" style={{ color: 'var(--color-text-tertiary)' }}>
        <Icon size={14} />
        {label}
      </div>
      <div className="mt-3 text-lg font-semibold capitalize" style={{ color: color || 'var(--color-text)' }}>{value}</div>
    </div>
  );
}

function StatusBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl p-3" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
      <div className="text-[11px] uppercase tracking-[0.14em]" style={{ color: 'var(--color-text-tertiary)' }}>{label}</div>
      <div className="mt-1 text-sm" style={{ color: 'var(--color-text)' }}>{value}</div>
    </div>
  );
}

function Badge({ children }: { children: ReactNode }) {
  return (
    <span className="rounded-full px-2 py-1 text-xs" style={{ border: '1px solid var(--color-border)', color: 'var(--color-accent-amber)' }}>
      {children}
    </span>
  );
}
