import { useState } from 'react';
import type { SpeechState } from '../../hooks/useSpeech';

export type VoiceStatus = SpeechState | 'wake-listening' | 'active-listening' | 'thinking' | 'speaking';

interface MicButtonProps {
  state: VoiceStatus;
  onClick: () => void;
  onStopSpeaking?: () => void;
  disabled?: boolean;
  reason?: 'not-enabled' | 'unsupported' | 'streaming';
  error?: string | null;
}

export function MicButton({ state, onClick, onStopSpeaking, disabled, reason, error }: MicButtonProps) {
  const [showTooltip, setShowTooltip] = useState(false);

  const tooltipText =
    reason === 'not-enabled'
      ? 'Click to enable voice input'
      : reason === 'unsupported'
        ? 'Voice input is not supported in this browser. Try Chrome/Edge or enable speech settings.'
        : reason === 'streaming'
          ? 'Wait for response'
          : state === 'wake-listening'
            ? 'Wake mode listening for Hey Grandpa'
          : state === 'active-listening'
            ? 'Wake phrase heard - listening for command'
          : state === 'listening'
            ? 'Listening - click to stop'
            : state === 'transcribing'
              ? 'Transcribing...'
              : state === 'thinking'
                ? 'Grandpa is thinking...'
                : state === 'speaking'
                  ? 'Speaking - click to stop'
                  : state === 'error'
                    ? error || 'Voice input error'
                    : 'Voice input';

  const isInactive = disabled || state === 'transcribing' || state === 'thinking';
  const active = state === 'listening' || state === 'active-listening' || state === 'speaking';
  const passive = state === 'wake-listening';
  const handleClick = () => {
    if (state === 'speaking') {
      onStopSpeaking?.();
      onClick();
      return;
    }
    onClick();
  };

  return (
    <div
      className="relative"
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      <button
        onClick={handleClick}
        disabled={isInactive}
        aria-label={tooltipText}
        className="relative p-2 rounded-xl transition-all shrink-0"
        style={{
          background: active
            ? 'color-mix(in srgb, var(--color-accent) 82%, var(--color-accent-amber))'
            : passive
              ? 'color-mix(in srgb, var(--color-bg-secondary) 82%, transparent)'
            : state === 'error'
              ? 'color-mix(in srgb, var(--color-error) 18%, transparent)'
            : 'transparent',
          color: active
            ? 'white'
            : passive
              ? 'var(--color-accent-amber)'
            : isInactive
              ? 'var(--color-text-tertiary)'
              : state === 'error'
                ? 'var(--color-error)'
              : 'var(--color-text-secondary)',
          cursor: isInactive ? 'default' : 'pointer',
          opacity: isInactive ? 0.35 : 1,
          animation: active ? 'pulse 1.5s ease-in-out infinite' : 'none',
          boxShadow: active
            ? '0 0 24px var(--color-accent-glow)'
            : passive
              ? '0 0 18px color-mix(in srgb, var(--color-accent-amber) 28%, transparent)'
              : 'none',
          pointerEvents: 'auto',
          zIndex: 2,
        }}
        title={tooltipText}
      >
        {(state === 'listening' || state === 'active-listening') && (
          <span
            aria-hidden="true"
            className="absolute inset-0 rounded-xl"
            style={{
              boxShadow: '0 0 0 0 color-mix(in srgb, var(--color-accent) 45%, transparent)',
              animation: 'pulse 1.4s ease-out infinite',
            }}
          />
        )}
        {state === 'transcribing' ? (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="28" strokeDashoffset="10">
              <animateTransform attributeName="transform" type="rotate" from="0 8 8" to="360 8 8" dur="1s" repeatCount="indefinite" />
            </circle>
          </svg>
        ) : (
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
            <path d="M5 3a3 3 0 0 1 6 0v5a3 3 0 0 1-6 0V3z" />
            <path d="M3.5 6.5A.5.5 0 0 1 4 7v1a4 4 0 0 0 8 0V7a.5.5 0 0 1 1 0v1a5 5 0 0 1-4.5 4.975V15h3a.5.5 0 0 1 0 1h-7a.5.5 0 0 1 0-1h3v-2.025A5 5 0 0 1 3 8V7a.5.5 0 0 1 .5-.5z" />
          </svg>
        )}
      </button>
      {showTooltip && (
        <div
          className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-2.5 py-1.5 rounded-lg text-xs whitespace-nowrap pointer-events-none"
          style={{
            background: 'var(--color-text)',
            color: 'var(--color-bg)',
            boxShadow: '0 2px 8px rgba(0,0,0,0.15)',
          }}
        >
          {tooltipText}
        </div>
      )}
    </div>
  );
}
