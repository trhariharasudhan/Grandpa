import { useState, useCallback, useRef, useEffect } from 'react';
import { transcribeAudio, fetchSpeechHealth } from '../lib/api';

export type SpeechState = 'idle' | 'listening' | 'transcribing' | 'error';

type SpeechMode = 'browser' | 'backend' | 'none';

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

export function useSpeech() {
  const [state, setState] = useState<SpeechState>('idle');
  const [error, setError] = useState<string | null>(null);
  const [available, setAvailable] = useState(false);
  const [mode, setMode] = useState<SpeechMode>('none');
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const browserTranscriptRef = useRef('');
  const browserResolveRef = useRef<((text: string) => void) | null>(null);
  const browserRejectRef = useRef<((error: Error) => void) | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);

  // Prefer browser speech input for daily desktop use. Fall back to the
  // backend transcription endpoint when browser SpeechRecognition is missing.
  useEffect(() => {
    const browserSupported = !!getBrowserRecognitionCtor();
    fetchSpeechHealth()
      .then((health) => {
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
        setMode(browserSupported ? 'browser' : 'none');
        setAvailable(browserSupported);
      });
  }, [mode, state]);

  const startRecording = useCallback(async (): Promise<void> => {
    setError(null);

    if (mode === 'browser') {
      const Recognition = getBrowserRecognitionCtor();
      if (!Recognition) {
        setError('Voice input is not supported in this browser. Try Chrome/Edge or enable speech settings.');
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
          if (text.trim()) {
            browserTranscriptRef.current = `${browserTranscriptRef.current} ${text}`.trim();
          }
        };
        recognition.onerror = (event) => {
          const message = event.error === 'not-allowed'
            ? 'Microphone access denied. Allow microphone permission in the browser.'
            : event.error === 'no-speech'
              ? 'No speech was detected. Try again.'
              : 'Voice input error. Try Chrome/Edge or enable speech settings.';
          setError(message);
          setState('error');
          browserRejectRef.current?.(new Error(message));
          browserRejectRef.current = null;
          browserResolveRef.current = null;
        };
        recognition.onend = () => {
          if (browserResolveRef.current) {
            const text = browserTranscriptRef.current.trim();
            browserResolveRef.current(text);
            browserResolveRef.current = null;
            browserRejectRef.current = null;
            setState('idle');
          } else if (state === 'listening') {
            setState('idle');
          }
        };
        recognition.start();
        recognitionRef.current = recognition;
        setState('listening');
      } catch {
        setError('Voice input is not supported in this browser. Try Chrome/Edge or enable speech settings.');
        setState('error');
      }
      return;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      setError('Voice input is not supported in this browser. Try Chrome/Edge or enable speech settings.');
      setState('error');
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.start();
      mediaRecorderRef.current = recorder;
      setState('listening');
    } catch (err) {
      setError('Microphone access denied');
      setState('error');
    }
  }, [mode]);

  const stopRecording = useCallback(async (): Promise<string> => {
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
          setState('idle');
          resolve(result.text);
        } catch (err) {
          setState('error');
          const msg = err instanceof Error ? err.message : 'Transcription failed';
          setError(msg);
          reject(err);
        }
      };

      recorder.stop();
    });
  }, []);

  return {
    state,
    error,
    available,
    mode,
    startRecording,
    stopRecording,
    isRecording: state === 'listening',
    isTranscribing: state === 'transcribing',
  };
}
