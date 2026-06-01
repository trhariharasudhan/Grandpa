import { useState, useCallback, useRef, useEffect } from 'react';
import { transcribeAudio, fetchSpeechHealth } from '../lib/api';

export type SpeechState = 'idle' | 'listening' | 'transcribing' | 'error';

type SpeechMode = 'browser' | 'backend' | 'none';

export interface SpeechDiagnostics {
  browserSupported: boolean;
  backendAvailable: boolean | null;
  permission: PermissionState | 'unknown';
  lastTranscriptLength: number;
  rejectedNoiseCount: number;
  lastError: string | null;
  mode: SpeechMode;
}

interface UseSpeechOptions {
  noiseFiltering?: boolean;
  silenceTimeoutMs?: number;
  onAutoTranscript?: (text: string) => void;
}

interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: {
    length: number;
    [index: number]: {
      isFinal: boolean;
      [index: number]: { transcript: string };
    };
  };
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function getBrowserRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === 'undefined') return null;
  const win = window as typeof window & {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return win.SpeechRecognition || win.webkitSpeechRecognition || null;
}

function normalizeTranscript(text: string): string {
  return text.replace(/\s+/g, ' ').trim();
}

function isLikelyNoise(text: string): boolean {
  const normalized = normalizeTranscript(text).toLowerCase();
  if (!normalized) return true;
  if (normalized.length < 2) return true;
  if (/^(uh|um|hmm|mmm|ah|er|noise|background noise)$/i.test(normalized)) return true;
  if (/^(.)\1{4,}$/.test(normalized.replace(/\s/g, ''))) return true;
  const alpha = normalized.replace(/[^a-z0-9\u0B80-\u0BFF]/gi, '');
  return alpha.length < Math.max(2, normalized.length * 0.35);
}

async function getMicrophonePermission(): Promise<PermissionState | 'unknown'> {
  try {
    if (!navigator.permissions?.query) return 'unknown';
    const status = await navigator.permissions.query({ name: 'microphone' as PermissionName });
    return status.state;
  } catch {
    return 'unknown';
  }
}

export function useSpeech(options: UseSpeechOptions = {}) {
  const [state, setState] = useState<SpeechState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [available, setAvailable] = useState(false);
  const [mode, setMode] = useState<SpeechMode>('none');
  const [diagnostics, setDiagnostics] = useState<SpeechDiagnostics>({
    browserSupported: false,
    backendAvailable: null,
    permission: 'unknown',
    lastTranscriptLength: 0,
    rejectedNoiseCount: 0,
    lastError: null,
    mode: 'none',
  });
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const browserTranscriptRef = useRef('');
  const browserResolveRef = useRef<((text: string) => void) | null>(null);
  const browserRejectRef = useRef<((error: Error) => void) | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const silenceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const optionsRef = useRef(options);

  useEffect(() => {
    optionsRef.current = options;
  }, [options.noiseFiltering, options.silenceTimeoutMs]);

  // Prefer browser speech input for daily desktop use. Fall back to the
  // backend transcription endpoint when browser SpeechRecognition is missing.
  useEffect(() => {
    const browserSupported = !!getBrowserRecognitionCtor();
    let mounted = true;
    getMicrophonePermission().then((permission) => {
      if (mounted) setDiagnostics((d) => ({ ...d, permission }));
    });
    fetchSpeechHealth()
      .then((health) => {
        if (!mounted) return;
        const nextMode = browserSupported ? 'browser' : health.available ? 'backend' : 'none';
        setDiagnostics((d) => ({
          ...d,
          browserSupported,
          backendAvailable: health.available,
          mode: nextMode,
        }));
        if (browserSupported) {
          setMode('browser');
          setAvailable(true);
        } else if (health.available) {
          setMode('backend');
          setAvailable(true);
        } else {
          setMode('none');
          setAvailable(false);
        }
      })
      .catch(() => {
        if (!mounted) return;
        const nextMode = browserSupported ? 'browser' : 'none';
        setDiagnostics((d) => ({
          ...d,
          browserSupported,
          backendAvailable: false,
          mode: nextMode,
        }));
        setMode(browserSupported ? 'browser' : 'none');
        setAvailable(browserSupported);
      });
    return () => {
      mounted = false;
    };
  }, []);

  const setVoiceError = useCallback((message: string) => {
    setError(message);
    setDiagnostics((d) => ({ ...d, lastError: message }));
  }, []);

  const clearSilenceTimer = useCallback(() => {
    if (silenceTimerRef.current) {
      clearTimeout(silenceTimerRef.current);
      silenceTimerRef.current = null;
    }
  }, []);

  const scheduleSilenceStop = useCallback(() => {
    clearSilenceTimer();
    const timeout = optionsRef.current.silenceTimeoutMs ?? 8000;
    if (!optionsRef.current.onAutoTranscript) return;
    if (timeout <= 0) return;
    silenceTimerRef.current = setTimeout(() => {
      try {
        recognitionRef.current?.stop();
      } catch {
        // Browser speech recognition stop is best-effort.
      }
    }, timeout);
  }, [clearSilenceTimer]);

  const startRecording = useCallback(async (): Promise<void> => {
    setError(null);
    setDiagnostics((d) => ({ ...d, lastError: null }));

    if (mode === 'browser') {
      const Recognition = getBrowserRecognitionCtor();
      if (!Recognition) {
        setVoiceError('Voice input is not supported in this browser. Try Chrome/Edge or enable speech settings.');
        setState('error');
        return;
      }
      try {
        const recognition = new Recognition();
        browserTranscriptRef.current = '';
        recognition.continuous = true;
        recognition.interimResults = false;
        recognition.lang = navigator.language || 'en-US';
        recognition.onresult = (event) => {
          let text = '';
          for (let i = event.resultIndex; i < event.results.length; i += 1) {
            const result = event.results[i];
            if (result?.isFinal) text += result[0]?.transcript || '';
          }
          const cleaned = normalizeTranscript(text);
          if (cleaned) {
            if (optionsRef.current.noiseFiltering !== false && isLikelyNoise(cleaned)) {
              setDiagnostics((d) => ({ ...d, rejectedNoiseCount: d.rejectedNoiseCount + 1 }));
              return;
            }
            browserTranscriptRef.current = normalizeTranscript(`${browserTranscriptRef.current} ${cleaned}`);
            setDiagnostics((d) => ({
              ...d,
              lastTranscriptLength: browserTranscriptRef.current.length,
              permission: 'granted',
            }));
            scheduleSilenceStop();
          }
        };
        recognition.onerror = (event) => {
          const message = event.error === 'not-allowed'
            ? 'Microphone access denied. Allow microphone permission in the browser.'
            : event.error === 'no-speech'
              ? 'No speech was detected. Try again.'
              : 'Voice input error. Try Chrome/Edge or enable speech settings.';
          setVoiceError(message);
          setState('error');
          browserRejectRef.current?.(new Error(message));
          browserRejectRef.current = null;
          browserResolveRef.current = null;
        };
        recognition.onend = () => {
          clearSilenceTimer();
          if (browserResolveRef.current) {
            const text = browserTranscriptRef.current.trim();
            browserResolveRef.current(text);
            browserResolveRef.current = null;
            browserRejectRef.current = null;
            setState('idle');
          } else if (browserTranscriptRef.current.trim()) {
            const text = browserTranscriptRef.current.trim();
            browserTranscriptRef.current = '';
            optionsRef.current.onAutoTranscript?.(text);
            setState('idle');
          } else if (state === 'listening') {
            setState('idle');
          }
        };
        recognition.start();
        recognitionRef.current = recognition;
        setState('listening');
      } catch {
        setVoiceError('Voice input is not supported in this browser. Try Chrome/Edge or enable speech settings.');
        setState('error');
      }
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      setVoiceError('Voice input is not supported in this browser. Try Chrome/Edge or enable speech settings.');
      setState('error');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      setDiagnostics((d) => ({ ...d, permission: 'granted' }));

      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.start();
      mediaRecorderRef.current = recorder;
      setState('listening');
    } catch (err) {
      setVoiceError('Microphone access denied. Allow microphone permission in the browser or desktop shell.');
      setState('error');
    }
  }, [mode, scheduleSilenceStop, setVoiceError, clearSilenceTimer]);

  const stopRecording = useCallback(async (): Promise<string> => {
    clearSilenceTimer();
    if (mode === 'browser') {
      return new Promise((resolve, reject) => {
        const recognition = recognitionRef.current;
        if (!recognition) {
          reject(new Error('Voice input is not currently listening.'));
          return;
        }
        setState('transcribing');
        browserResolveRef.current = resolve;
        browserRejectRef.current = reject;
        recognition.stop();
        recognitionRef.current = null;
      });
    }

    return new Promise((resolve, reject) => {
      const recorder = mediaRecorderRef.current;
      if (!recorder || recorder.state !== 'recording') {
        reject(new Error('Not recording'));
        return;
      }

      recorder.onstop = async () => {
        setState('transcribing');

        // Stop all audio tracks
        streamRef.current?.getTracks().forEach((track) => track.stop());
        streamRef.current = null;

        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' });
        chunksRef.current = [];

        try {
          const result = await transcribeAudio(blob);
          const text = normalizeTranscript(result.text);
          if (optionsRef.current.noiseFiltering !== false && isLikelyNoise(text)) {
            setDiagnostics((d) => ({ ...d, rejectedNoiseCount: d.rejectedNoiseCount + 1, lastTranscriptLength: 0 }));
            setState('idle');
            resolve('');
            return;
          }
          setDiagnostics((d) => ({ ...d, lastTranscriptLength: text.length }));
          setState('idle');
          resolve(text);
        } catch (err) {
          setState('error');
          const msg = err instanceof Error ? err.message : 'Transcription failed';
          setVoiceError(msg);
          reject(err);
        }
      };

      recorder.stop();
    });
  }, [mode, clearSilenceTimer, setVoiceError]);

  return {
    state,
    error,
    available,
    mode,
    diagnostics,
    startRecording,
    stopRecording,
    isRecording: state === 'listening',
    isTranscribing: state === 'transcribing',
  };
}
