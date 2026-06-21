import { useEffect, useMemo, useRef, useState } from 'react';
import type { ElementType, ReactNode } from 'react';
import { Activity, Mic2, Play, RefreshCw, Send, Square, Volume2, Waves } from 'lucide-react';
import {
  clearVoiceHistory,
  commandVoice,
  confirmVoiceAction,
  clearConversation,
  disableWakeWord,
  disableVoiceLoop,
  enableVoiceLoop,
  enableWakeWord,
  fetchConversationContext,
  fetchConversationHistory,
  fetchVoiceHistory,
  fetchVoiceLoopStatus,
  fetchVoiceSttStatus,
  fetchVoiceStatus,
  fetchWakeWordStatus,
  listenFromAudio,
  simulateVoiceLoopCommand,
  simulateVoiceLoopWake,
  speakVoice,
  startVoiceLoop,
  startVoiceSession,
  stopVoiceLoop,
  stopVoiceSession,
  summarizeConversation,
  testWakeWord,
  type ConversationMessage,
  type VoiceLoopStatus,
  type WakeWordStatus,
  type WakeWordTestResponse,
  type VoiceHistoryEntry,
  type VoiceListenResponse,
  type VoiceSttStatus,
  type VoiceStatus,
  voiceCommand,
} from '../lib/api';

export function VoicePage() {
  const [status, setStatus] = useState<VoiceStatus | null>(null);
  const [transcript, setTranscript] = useState('Hey Grandpa desktop summary');
  const [wakeRequired, setWakeRequired] = useState(false);
  const [speakResponse, setSpeakResponse] = useState(false);
  const [lastResult, setLastResult] = useState<VoiceListenResponse | null>(null);
  const [history, setHistory] = useState<VoiceHistoryEntry[]>([]);
  const [conversation, setConversation] = useState<ConversationMessage[]>([]);
  const [conversationSummary, setConversationSummary] = useState('');
  const [conversationContext, setConversationContext] = useState('');
  const [contextMessageCount, setContextMessageCount] = useState(0);
  const [wakeWord, setWakeWord] = useState<WakeWordStatus | null>(null);
  const [wakeTestText, setWakeTestText] = useState('hey grandpa');
  const [wakeTestResult, setWakeTestResult] = useState<WakeWordTestResponse | null>(null);
  const [voiceLoop, setVoiceLoop] = useState<VoiceLoopStatus | null>(null);
  const [loopWakeText, setLoopWakeText] = useState('hey grandpa');
  const [loopCommandText, setLoopCommandText] = useState('what is my voice status');
  const [recording, setRecording] = useState(false);
  const [pttTranscript, setPttTranscript] = useState('');
  const [pttMessage, setPttMessage] = useState('');
  const [pttLanguage, setPttLanguage] = useState<string | null>(null);
  const [pttDuration, setPttDuration] = useState<number | null>(null);
  const [sttStatus, setSttStatus] = useState<VoiceSttStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<BlobPart[]>([]);

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      setStatus(await fetchVoiceStatus());
      setHistory(await fetchVoiceHistory());
      setConversation((await fetchConversationHistory()).messages);
      setWakeWord(await fetchWakeWordStatus());
      setVoiceLoop(await fetchVoiceLoopStatus());
      setSttStatus(await fetchVoiceSttStatus());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load voice status.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    const interval = window.setInterval(() => void load(), 15000);
    return () => {
      window.clearInterval(interval);
      recorderRef.current?.state !== 'inactive' && recorderRef.current?.stop();
      streamRef.current?.getTracks().forEach((track) => track.stop());
    };
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

  const confirmAction = async () => {
    const token = lastResult?.confirmation_token || lastResult?.action?.confirmation_token;
    if (!token) return;
    setBusy(true);
    setError('');
    try {
      const result = await confirmVoiceAction(token);
      setLastResult(result);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voice confirmation failed.');
    } finally {
      setBusy(false);
    }
  };

  const clearHistory = async () => {
    setBusy(true);
    setError('');
    try {
      await clearVoiceHistory();
      setHistory([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to clear voice history.');
    } finally {
      setBusy(false);
    }
  };

  const clearConversationHistory = async () => {
    setBusy(true);
    setError('');
    try {
      await clearConversation();
      setConversation([]);
      setConversationSummary('');
      setConversationContext('');
      setContextMessageCount(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to clear conversation.');
    } finally {
      setBusy(false);
    }
  };

  const loadConversationSummary = async () => {
    setBusy(true);
    setError('');
    try {
      const result = await summarizeConversation();
      setConversationSummary(result.summary);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to summarize conversation.');
    } finally {
      setBusy(false);
    }
  };

  const loadConversationContext = async () => {
    setBusy(true);
    setError('');
    try {
      const result = await fetchConversationContext();
      setConversationContext(result.context_text || 'No recent conversation context yet.');
      setContextMessageCount(result.message_count);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load conversation context.');
    } finally {
      setBusy(false);
    }
  };

  const setWakeEnabled = async (enabled: boolean) => {
    setBusy(true);
    setError('');
    try {
      const next = enabled ? await enableWakeWord() : await disableWakeWord();
      setWakeWord(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Wake word update failed.');
    } finally {
      setBusy(false);
    }
  };

  const runWakeTest = async () => {
    setBusy(true);
    setError('');
    try {
      const result = await testWakeWord(wakeTestText);
      setWakeTestResult(result);
      setWakeWord(await fetchWakeWordStatus());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Wake word test failed.');
    } finally {
      setBusy(false);
    }
  };

  const setLoopEnabled = async (enabled: boolean) => {
    setBusy(true);
    setError('');
    try {
      const next = enabled ? await enableVoiceLoop() : await disableVoiceLoop();
      setVoiceLoop(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voice loop update failed.');
    } finally {
      setBusy(false);
    }
  };

  const setLoopRunning = async (running: boolean) => {
    setBusy(true);
    setError('');
    try {
      const next = running ? await startVoiceLoop() : await stopVoiceLoop();
      setVoiceLoop(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voice loop state change failed.');
    } finally {
      setBusy(false);
    }
  };

  const runLoopWake = async () => {
    setBusy(true);
    setError('');
    try {
      setVoiceLoop(await simulateVoiceLoopWake(loopWakeText));
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voice loop wake simulation failed.');
    } finally {
      setBusy(false);
    }
  };

  const runLoopCommand = async () => {
    setBusy(true);
    setError('');
    try {
      const next = await simulateVoiceLoopCommand(loopCommandText);
      setVoiceLoop(next);
      if (next.command) setLastResult(next.command);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Voice loop command simulation failed.');
    } finally {
      setBusy(false);
    }
  };

  const startRecording = async () => {
    setError('');
    setPttMessage('');
    if (!navigator.mediaDevices?.getUserMedia || typeof window.MediaRecorder === 'undefined') {
      setPttMessage('Browser recording is not available on this device.');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      streamRef.current = stream;
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        chunksRef.current = [];
        stream.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
        recorderRef.current = null;
        setRecording(false);
        void transcribeRecording(blob);
      };
      recorder.start();
      setRecording(true);
      setPttMessage('Recording...');
    } catch (err) {
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      recorderRef.current = null;
      setRecording(false);
      setPttMessage(err instanceof Error ? err.message : 'Could not start browser recording.');
    }
  };

  const stopRecording = () => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === 'inactive') return;
    setPttMessage('Transcribing...');
    recorder.stop();
  };

  const transcribeRecording = async (blob: Blob) => {
    if (blob.size === 0) {
      setPttMessage('No audio was captured.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      const result = await listenFromAudio(blob);
      setPttTranscript(result.transcript || '');
      setTranscript(result.transcript || transcript);
      setPttLanguage(result.language || null);
      setPttDuration(typeof result.duration_seconds === 'number' ? result.duration_seconds : null);
      setPttMessage(result.message || 'Transcript captured.');
    } catch (err) {
      setPttMessage(err instanceof Error ? err.message : 'Could not transcribe recording.');
    } finally {
      setBusy(false);
    }
  };

  const sendPushToTalkCommand = async () => {
    if (!pttTranscript.trim()) return;
    setBusy(true);
    setError('');
    try {
      const result = await voiceCommand(pttTranscript);
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
              <div className="rounded-xl p-3 text-sm" style={{ border: '1px solid var(--color-border)' }}>
                <div className="mb-2 font-medium" style={{ color: 'var(--color-text)' }}>Push to Talk</div>
                <div className="mb-2 grid gap-2 text-xs sm:grid-cols-3">
                  <StatusBlock label="STT Engine" value={sttStatus?.engine || String(status?.speech_input?.engine || 'checking')} />
                  <StatusBlock label="Model" value={sttStatus?.model || String(status?.speech_input?.model || 'base')} />
                  <StatusBlock label="Ready" value={sttStatus?.ready ? 'ready' : 'not ready'} />
                </div>
                <div className="grid gap-2 sm:grid-cols-2">
                  <button type="button" onClick={() => void startRecording()} disabled={busy || recording} className="inline-flex items-center justify-center rounded-xl px-3 py-2 text-sm font-medium disabled:opacity-60" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>
                    Start Recording
                  </button>
                  <button type="button" onClick={stopRecording} disabled={!recording} className="inline-flex items-center justify-center rounded-xl px-3 py-2 text-sm disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    Stop Recording
                  </button>
                </div>
                <textarea
                  value={pttTranscript}
                  onChange={(event) => setPttTranscript(event.target.value)}
                  rows={3}
                  className="mt-2 w-full rounded-xl px-3 py-2 text-sm outline-none"
                  style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  placeholder="Transcript preview..."
                />
                <button type="button" onClick={() => void sendPushToTalkCommand()} disabled={busy || !pttTranscript.trim()} className="mt-2 inline-flex w-full items-center justify-center rounded-xl px-3 py-2 text-sm font-medium disabled:opacity-60" style={{ background: 'var(--color-accent-amber)', color: 'var(--color-bg)' }}>
                  Send as Command
                </button>
                <div className="mt-2 grid gap-2 text-xs sm:grid-cols-2">
                  <div style={{ color: 'var(--color-text-secondary)' }}>Language: {pttLanguage || 'unknown'}</div>
                  <div style={{ color: 'var(--color-text-secondary)' }}>Duration: {pttDuration !== null ? `${pttDuration.toFixed(1)}s` : 'unknown'}</div>
                </div>
                {pttMessage && (
                  <p className="mt-2 text-xs" style={{ color: 'var(--color-text-secondary)' }}>{pttMessage}</p>
                )}
              </div>
            </div>
          </Panel>

          <div className="flex flex-col gap-5">
            <Panel title="Wake Word">
              <div className="grid gap-3 md:grid-cols-2">
                <StatusBlock label="Current Phrase" value={wakeWord?.wake_phrase || 'hey grandpa'} />
                <StatusBlock label="Enabled" value={wakeWord?.enabled ? 'enabled' : 'disabled'} />
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <button type="button" onClick={() => void setWakeEnabled(true)} disabled={busy || wakeWord?.enabled} className="inline-flex items-center justify-center rounded-xl px-3 py-2 text-sm font-medium disabled:opacity-60" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>
                  Enable
                </button>
                <button type="button" onClick={() => void setWakeEnabled(false)} disabled={busy || !wakeWord?.enabled} className="inline-flex items-center justify-center rounded-xl px-3 py-2 text-sm disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                  Disable
                </button>
              </div>
              <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                <input
                  value={wakeTestText}
                  onChange={(event) => setWakeTestText(event.target.value)}
                  className="min-w-0 flex-1 rounded-xl px-3 py-2 text-sm outline-none"
                  style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  placeholder="Test phrase..."
                />
                <button type="button" onClick={() => void runWakeTest()} disabled={busy || !wakeTestText.trim()} className="rounded-xl px-3 py-2 text-sm disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                  Test
                </button>
              </div>
              <div className="mt-3 rounded-xl p-3 text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
                <div>Last detection: {wakeWord?.last_detection_time ? new Date(wakeWord.last_detection_time).toLocaleString() : 'none'}</div>
                <div>Test result: {wakeTestResult ? (wakeTestResult.detected ? 'detected' : 'not detected') : 'not tested'}</div>
                <div>No microphone or always-on listener is started.</div>
              </div>
            </Panel>

            <Panel title="Continuous Voice Loop">
              <div className="grid gap-3 md:grid-cols-3">
                <StatusBlock label="Enabled" value={voiceLoop?.enabled ? 'enabled' : 'disabled'} />
                <StatusBlock label="Running" value={voiceLoop?.running ? 'running' : 'stopped'} />
                <StatusBlock label="Mode" value={voiceLoop?.mode || 'idle'} />
              </div>
              <div className="mt-3 grid gap-2 sm:grid-cols-4">
                <button type="button" onClick={() => void setLoopEnabled(true)} disabled={busy || voiceLoop?.enabled} className="inline-flex items-center justify-center rounded-xl px-3 py-2 text-sm font-medium disabled:opacity-60" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>
                  Enable
                </button>
                <button type="button" onClick={() => void setLoopEnabled(false)} disabled={busy || !voiceLoop?.enabled} className="inline-flex items-center justify-center rounded-xl px-3 py-2 text-sm disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                  Disable
                </button>
                <button type="button" onClick={() => void setLoopRunning(true)} disabled={busy || voiceLoop?.running} className="inline-flex items-center justify-center rounded-xl px-3 py-2 text-sm disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                  Start
                </button>
                <button type="button" onClick={() => void setLoopRunning(false)} disabled={busy || !voiceLoop?.running} className="inline-flex items-center justify-center rounded-xl px-3 py-2 text-sm disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                  Stop
                </button>
              </div>
              <div className="mt-3 flex flex-col gap-2 sm:flex-row">
                <input
                  value={loopWakeText}
                  onChange={(event) => setLoopWakeText(event.target.value)}
                  className="min-w-0 flex-1 rounded-xl px-3 py-2 text-sm outline-none"
                  style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  placeholder="Simulate wake text..."
                />
                <button type="button" onClick={() => void runLoopWake()} disabled={busy || !loopWakeText.trim()} className="rounded-xl px-3 py-2 text-sm disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                  Simulate Wake
                </button>
              </div>
              <div className="mt-2 flex flex-col gap-2 sm:flex-row">
                <input
                  value={loopCommandText}
                  onChange={(event) => setLoopCommandText(event.target.value)}
                  className="min-w-0 flex-1 rounded-xl px-3 py-2 text-sm outline-none"
                  style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  placeholder="Simulate command transcript..."
                />
                <button type="button" onClick={() => void runLoopCommand()} disabled={busy || !loopCommandText.trim()} className="rounded-xl px-3 py-2 text-sm disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                  Simulate Command
                </button>
              </div>
              <div className="mt-3 rounded-xl p-3 text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
                <div>Last wake: {voiceLoop?.last_wake_detected_at ? new Date(voiceLoop.last_wake_detected_at).toLocaleString() : 'none'}</div>
                <div>Last command: {voiceLoop?.last_command_transcript || 'none'}</div>
                <div>Last error: {voiceLoop?.last_error || 'none'}</div>
                <div>No microphone, background thread, or always-on capture is started.</div>
              </div>
            </Panel>

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
                    <button type="button" onClick={() => void confirmAction()} disabled={busy || !(lastResult.confirmation_token || lastResult.action?.confirmation_token)} className="inline-flex w-fit items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm font-medium disabled:opacity-60" style={{ background: 'var(--color-accent-amber)', color: 'var(--color-bg)' }}>
                      Confirm Action
                    </button>
                  )}
                  <div className="rounded-xl p-3 text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
                    <div>Transcript: {lastResult.transcript || 'none'}</div>
                    <div>Assistant: {lastResult.assistant_text || lastResult.message || 'none'}</div>
                    <div>Command: {lastResult.command_text || lastResult.transcript || 'none'}</div>
                    <div>Action: {lastResult.action?.type || 'none'} / {lastResult.action?.status || lastResult.action_status || 'unknown'}</div>
                    <div>Context used: {lastResult.context_used ? 'yes' : 'no'} ({lastResult.context_message_count || 0} messages)</div>
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

            <Panel title="Recent Conversation">
              <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  Latest {conversation.length} short-term messages
                </p>
                <div className="flex gap-2">
                  <button type="button" onClick={() => void loadConversationSummary()} disabled={busy} className="rounded-xl px-3 py-1.5 text-xs disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    Summary
                  </button>
                  <button type="button" onClick={() => void loadConversationContext()} disabled={busy} className="rounded-xl px-3 py-1.5 text-xs disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    View Context
                  </button>
                  <button type="button" onClick={() => void clearConversationHistory()} disabled={busy || conversation.length === 0} className="rounded-xl px-3 py-1.5 text-xs disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    Clear conversation
                  </button>
                </div>
              </div>
              {conversationSummary && (
                <div className="mb-3 rounded-xl px-3 py-2 text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
                  {conversationSummary}
                </div>
              )}
              {conversationContext && (
                <div className="mb-3 whitespace-pre-wrap rounded-xl px-3 py-2 text-xs" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}>
                  <div className="mb-1 font-medium" style={{ color: 'var(--color-text)' }}>Context messages: {contextMessageCount}</div>
                  {conversationContext}
                </div>
              )}
              <div className="flex max-h-[260px] flex-col gap-2 overflow-y-auto">
                {conversation.length === 0 ? (
                  <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>No recent conversation yet.</p>
                ) : (
                  conversation.map((message) => (
                    <div key={`${message.timestamp}-${message.role}-${message.content.slice(0, 12)}`} className="rounded-xl px-3 py-2 text-sm" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
                      <div className="text-[11px] uppercase tracking-[0.14em]" style={{ color: 'var(--color-text-tertiary)' }}>
                        {message.role} · {new Date(message.timestamp).toLocaleString()}
                      </div>
                      <div className="mt-1" style={{ color: 'var(--color-text)' }}>{message.content}</div>
                    </div>
                  ))
                )}
              </div>
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

            <Panel title="Command History">
              <div className="mb-3 flex items-center justify-between gap-3">
                <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  Latest {history.length} voice commands
                </p>
                <button type="button" onClick={() => void clearHistory()} disabled={busy || history.length === 0} className="rounded-xl px-3 py-1.5 text-xs disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                  Clear history
                </button>
              </div>
              <div className="flex max-h-[320px] flex-col gap-2 overflow-y-auto">
                {history.length === 0 ? (
                  <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>No voice command history yet.</p>
                ) : (
                  history.map((entry) => (
                    <div key={entry.id} className="rounded-xl px-3 py-2 text-sm" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
                      <div className="flex flex-wrap items-center gap-2 text-[11px] uppercase tracking-[0.14em]" style={{ color: 'var(--color-text-tertiary)' }}>
                        <span>{new Date(entry.timestamp).toLocaleString()}</span>
                        <span>{entry.action_type}</span>
                        <span>{entry.action_status}</span>
                      </div>
                      <div className="mt-1" style={{ color: 'var(--color-text)' }}>{entry.transcript}</div>
                      <div className="mt-1 text-xs" style={{ color: 'var(--color-text-secondary)' }}>{entry.assistant_response}</div>
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
