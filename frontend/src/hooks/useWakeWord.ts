import { useEffect, useRef, useState } from 'react';

export type WakeWordState = 'idle' | 'wake-listening' | 'active-listening' | 'error';

interface UseWakeWordOptions {
  enabled: boolean;
  onCommand: (command: string) => void;
  onWake?: () => void;
  timeoutMs?: number;
  cooldownMs?: number;
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

interface SpeechRecognitionLike {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  onresult: ((event: SpeechRecognitionEventLike) => void) | null;
  onerror: (() => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
}

interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: ArrayLike<{
    isFinal: boolean;
    0: { transcript: string };
  }>;
}

const WAKE_PATTERN = /\b(?:hey|okay)\s+grandpa\b/i;

function getRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === 'undefined') return null;
  const win = window as typeof window & {
    SpeechRecognition?: SpeechRecognitionCtor;
    webkitSpeechRecognition?: SpeechRecognitionCtor;
  };
  return win.SpeechRecognition || win.webkitSpeechRecognition || null;
}

function commandAfterWake(transcript: string): string {
  return transcript.replace(WAKE_PATTERN, '').trim().replace(/^[,.;:\s]+/, '');
}

export function useWakeWord({
  enabled,
  onCommand,
  onWake,
  timeoutMs = 8000,
  cooldownMs = 1800,
}: UseWakeWordOptions) {
  const [state, setState] = useState<WakeWordState>('idle');
  const [error, setError] = useState<string | null>(null);
  const commandRef = useRef(onCommand);
  const wakeRef = useRef(onWake);
  const activeRef = useRef(false);
  const lastTriggerRef = useRef(0);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);

  useEffect(() => {
    commandRef.current = onCommand;
    wakeRef.current = onWake;
  }, [onCommand, onWake]);

  useEffect(() => {
    if (!enabled) {
      recognitionRef.current?.stop();
      recognitionRef.current = null;
      activeRef.current = false;
      setState('idle');
      setError(null);
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      return;
    }

    const Recognition = getRecognitionCtor();
    if (!Recognition) {
      setState('error');
      setError('Wake word requires browser speech recognition support.');
      return;
    }

    let stopped = false;
    const recognition = new Recognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = 'en-US';
    recognitionRef.current = recognition;

    const returnToWakeListening = () => {
      activeRef.current = false;
      if (!stopped) setState('wake-listening');
    };

    const activate = () => {
      const now = Date.now();
      if (now - lastTriggerRef.current < cooldownMs) return;
      lastTriggerRef.current = now;
      activeRef.current = true;
      setState('active-listening');
      wakeRef.current?.();
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      timeoutRef.current = setTimeout(returnToWakeListening, timeoutMs);
    };

    recognition.onresult = (event) => {
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        const transcript = result[0]?.transcript?.trim() || '';
        if (!transcript) continue;

        if (WAKE_PATTERN.test(transcript)) {
          activate();
          const command = commandAfterWake(transcript);
          if (command && result.isFinal) {
            if (timeoutRef.current) clearTimeout(timeoutRef.current);
            returnToWakeListening();
            commandRef.current(command);
          }
          continue;
        }

        if (activeRef.current && result.isFinal) {
          const command = transcript.trim();
          if (command) {
            if (timeoutRef.current) clearTimeout(timeoutRef.current);
            returnToWakeListening();
            commandRef.current(command);
          }
        }
      }
    };

    recognition.onerror = () => {
      if (stopped) return;
      setState('error');
      setError('Wake listening is unavailable or microphone permission was denied.');
    };

    recognition.onend = () => {
      if (stopped) return;
      window.setTimeout(() => {
        try {
          recognition.start();
          if (!activeRef.current) setState('wake-listening');
        } catch {
          setState('error');
        }
      }, 400);
    };

    try {
      recognition.start();
      setState('wake-listening');
      setError(null);
    } catch {
      setState('error');
      setError('Wake listening could not start.');
    }

    return () => {
      stopped = true;
      activeRef.current = false;
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      try {
        recognition.stop();
      } catch {
        // Optional browser API; ignore stop failures.
      }
    };
  }, [enabled, timeoutMs, cooldownMs]);

  return {
    state,
    error,
    supported: !!getRecognitionCtor(),
  };
}
