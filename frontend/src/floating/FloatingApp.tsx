import { useCallback, useEffect, useRef, useState } from 'react';
import { ExternalLink, MessageSquare, Mic, Minus, Play, RefreshCw, Square } from 'lucide-react';
import { invoke } from '@tauri-apps/api/core';
import {
  availableMonitors,
  getCurrentWindow,
  LogicalSize,
  PhysicalPosition,
} from '@tauri-apps/api/window';
import {
  clampPositionToBounds,
  FLOATING_COLLAPSED_SIZE,
  FLOATING_EXPANDED_SIZE,
  isValidPosition,
  normalizeApiBase,
  normalizeBackendState,
  statusLabel,
  type FloatingBackendStatus,
  type FloatingBounds,
  type FloatingPosition,
} from './floatingUtils';
import './floating.css';

const appWindow = getCurrentWindow();
const POLL_MS = 4000;
type UnlistenFn = () => void;

export function FloatingApp() {
  const [expanded, setExpanded] = useState(false);
  const [status, setStatus] = useState<FloatingBackendStatus | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const pollInFlight = useRef(false);
  const dragged = useRef(false);
  const pointerStart = useRef<{ x: number; y: number } | null>(null);
  const saveTimer = useRef<number | null>(null);

  const refreshStatus = useCallback(async () => {
    if (pollInFlight.current) return;
    pollInFlight.current = true;
    try {
      const next = await invoke<FloatingBackendStatus>('floating_backend_status');
      setStatus({
        ...next,
        state: normalizeBackendState(next.state),
        api_base: normalizeApiBase(next.api_base || ''),
      });
      setMessage('');
    } catch (error) {
      setStatus({ state: 'error', detail: 'Backend status is unavailable.', api_base: '' });
      setMessage(error instanceof Error ? error.message : 'Backend status is unavailable.');
    } finally {
      pollInFlight.current = false;
    }
  }, []);

  useEffect(() => {
    void restorePosition();
    void refreshStatus();
    const interval = window.setInterval(refreshStatus, POLL_MS);
    let unlisten: UnlistenFn | undefined;
    appWindow.onMoved((position) => {
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
      saveTimer.current = window.setTimeout(() => {
        void invoke('save_floating_position', {
          position: { x: position.payload.x, y: position.payload.y },
        }).catch(() => {});
      }, 250);
    }).then((listener) => {
      unlisten = listener;
    }).catch(() => {});
    return () => {
      window.clearInterval(interval);
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
      unlisten?.();
    };
  }, [refreshStatus]);

  useEffect(() => {
    const size = expanded ? FLOATING_EXPANDED_SIZE : FLOATING_COLLAPSED_SIZE;
    void appWindow.setSize(new LogicalSize(size.width, size.height));
  }, [expanded]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setExpanded(false);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const runAction = async (command: 'floating_start_backend' | 'floating_stop_backend') => {
    setBusy(true);
    setStatus((current) => current ? { ...current, state: 'checking', detail: 'Updating backend...' } : current);
    try {
      const next = await invoke<FloatingBackendStatus>(command);
      setStatus({
        ...next,
        state: normalizeBackendState(next.state),
        api_base: normalizeApiBase(next.api_base || ''),
      });
      setMessage(next.detail);
    } catch (error) {
      setStatus({ state: 'error', detail: 'Backend action failed.', api_base: status?.api_base || '' });
      setMessage(error instanceof Error ? error.message : 'Backend action failed.');
    } finally {
      setBusy(false);
    }
  };

  const onPointerDown = (event: React.PointerEvent) => {
    pointerStart.current = { x: event.clientX, y: event.clientY };
    dragged.current = false;
  };

  const onPointerMove = (event: React.PointerEvent) => {
    if (!pointerStart.current || dragged.current) return;
    const dx = Math.abs(event.clientX - pointerStart.current.x);
    const dy = Math.abs(event.clientY - pointerStart.current.y);
    if (dx > 4 || dy > 4) {
      dragged.current = true;
      void appWindow.startDragging().catch(() => {});
    }
  };

  const onToggleClick = () => {
    if (dragged.current) {
      dragged.current = false;
      return;
    }
    setExpanded((value) => !value);
  };

  const onToggleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      setExpanded((value) => !value);
    }
  };

  return (
    <main className={`floating-root ${expanded ? 'is-expanded' : 'is-collapsed'}`}>
      <button
        className="floating-orb"
        type="button"
        aria-label="Grandpa Assistant"
        title="Grandpa Assistant"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onClick={onToggleClick}
        onKeyDown={onToggleKeyDown}
      >
        <span className="floating-mark" aria-hidden="true">G</span>
        <span className={`floating-status-dot ${status?.state || 'checking'}`} aria-hidden="true" />
      </button>

      {expanded && (
        <section className="floating-panel" aria-label="Grandpa compact controls">
          <header className="floating-panel-header">
            <div>
              <h1>Grandpa</h1>
              <p>{statusLabel(status)}</p>
            </div>
            <button type="button" className="floating-icon-button" aria-label="Collapse" onClick={() => setExpanded(false)}>
              <Minus size={16} />
            </button>
          </header>

          <div className={`floating-state ${status?.state || 'checking'}`}>
            <span>{status?.detail || 'Checking backend...'}</span>
          </div>

          {message && <div className="floating-message" role="status">{message}</div>}

          <div className="floating-actions">
            <button type="button" onClick={() => invoke('floating_open_main_app')} aria-label="Open Full App">
              <ExternalLink size={15} />
              Open Full App
            </button>
            {status?.state === 'running' ? (
              <button type="button" disabled={busy} onClick={() => runAction('floating_stop_backend')} aria-label="Stop Backend">
                <Square size={15} />
                Stop Backend
              </button>
            ) : (
              <button type="button" disabled={busy} onClick={() => runAction('floating_start_backend')} aria-label="Start Backend">
                <Play size={15} />
                Start Backend
              </button>
            )}
            <button type="button" disabled={busy} onClick={refreshStatus} aria-label="Refresh Status">
              <RefreshCw size={15} />
              Refresh Status
            </button>
          </div>

          <div className="floating-placeholders">
            <button type="button" disabled aria-label="Microphone coming soon">
              <Mic size={15} />
              Microphone: Coming soon
            </button>
            <button type="button" disabled aria-label="Chat coming soon">
              <MessageSquare size={15} />
              Chat coming soon
            </button>
          </div>
        </section>
      )}
    </main>
  );
}

async function restorePosition() {
  const monitors = await availableMonitors().catch(() => []);
  const primary = monitors[0];
  const bounds: FloatingBounds = primary
    ? {
        x: primary.position.x,
        y: primary.position.y,
        width: primary.size.width,
        height: primary.size.height,
      }
    : { x: 0, y: 0, width: window.screen.availWidth || 1280, height: window.screen.availHeight || 720 };
  const saved = await invoke<FloatingPosition | null>('get_floating_position').catch(() => null);
  const safe = clampPositionToBounds(isValidPosition(saved) ? saved : null, bounds, FLOATING_COLLAPSED_SIZE);
  await appWindow.setPosition(new PhysicalPosition(Math.round(safe.x), Math.round(safe.y))).catch(() => {});
}
