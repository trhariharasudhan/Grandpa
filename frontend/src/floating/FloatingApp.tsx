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
  boundsForPosition,
  clampPositionToBounds,
  FLOATING_COLLAPSED_SIZE,
  FLOATING_DRAG_THRESHOLD,
  FLOATING_EXPANDED_SIZE,
  getExpandedPosition,
  isValidPosition,
  normalizeApiBase,
  normalizeBackendState,
  shouldStartFloatingDrag,
  statusLabel,
  type FloatingBackendStatus,
  type FloatingBounds,
  type FloatingPosition,
} from './floatingUtils';
import './floating.css';

const appWindow = getCurrentWindow();
const POLL_MS = 4000;
const SAVE_DEBOUNCE_MS = 250;
type UnlistenFn = () => void;

export function FloatingApp() {
  const [expanded, setExpandedState] = useState(false);
  const [status, setStatus] = useState<FloatingBackendStatus | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const expandedRef = useRef(false);
  const pollInFlight = useRef(false);
  const dragged = useRef(false);
  const dragStarted = useRef(false);
  const pointerStart = useRef<FloatingPosition | null>(null);
  const collapsedPosition = useRef<FloatingPosition | null>(null);
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

  const saveCurrentPosition = useCallback((position: FloatingPosition) => {
    if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      void invoke('save_floating_position', { position }).catch(() => {});
    }, SAVE_DEBOUNCE_MS);
  }, []);

  const collapsePanel = useCallback(async () => {
    expandedRef.current = false;
    setExpandedState(false);
    await appWindow.setSize(new LogicalSize(FLOATING_COLLAPSED_SIZE.width, FLOATING_COLLAPSED_SIZE.height)).catch(() => {});
    if (collapsedPosition.current) {
      await appWindow
        .setPosition(new PhysicalPosition(Math.round(collapsedPosition.current.x), Math.round(collapsedPosition.current.y)))
        .catch(() => {});
      saveCurrentPosition(collapsedPosition.current);
    }
  }, [saveCurrentPosition]);

  const expandPanel = useCallback(async () => {
    const current = await appWindow.outerPosition().catch(() => null);
    const anchor = current ? { x: current.x, y: current.y } : null;
    if (anchor) collapsedPosition.current = anchor;

    const monitors = await getMonitorBounds();
    const fallbackBounds = getFallbackBounds();
    const bounds = anchor ? boundsForPosition(monitors, anchor) || fallbackBounds : fallbackBounds;
    const position = getExpandedPosition(anchor || clampPositionToBounds(null, bounds), bounds);

    await appWindow.setPosition(new PhysicalPosition(Math.round(position.x), Math.round(position.y))).catch(() => {});
    await appWindow.setSize(new LogicalSize(FLOATING_EXPANDED_SIZE.width, FLOATING_EXPANDED_SIZE.height)).catch(() => {});
    expandedRef.current = true;
    setExpandedState(true);
  }, []);

  const toggleExpanded = useCallback(() => {
    if (expandedRef.current) {
      void collapsePanel();
    } else {
      void expandPanel();
    }
  }, [collapsePanel, expandPanel]);

  useEffect(() => {
    void restorePosition();
    void appWindow.show().catch(() => {});
    void appWindow.setAlwaysOnTop(true).catch(() => {});
    void refreshStatus();
    const interval = window.setInterval(refreshStatus, POLL_MS);
    let unlisten: UnlistenFn | undefined;
    appWindow.onMoved((position) => {
      if (expandedRef.current) return;
      const next = { x: position.payload.x, y: position.payload.y };
      collapsedPosition.current = next;
      saveCurrentPosition(next);
    }).then((listener) => {
      unlisten = listener;
    }).catch(() => {});
    return () => {
      window.clearInterval(interval);
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
      unlisten?.();
    };
  }, [refreshStatus, saveCurrentPosition]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') void collapsePanel();
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [collapsePanel]);

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

  const onIconPointerDown = (event: React.PointerEvent) => {
    if (event.button !== 0) return;
    pointerStart.current = { x: event.clientX, y: event.clientY };
    dragged.current = false;
    dragStarted.current = false;
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onIconPointerMove = (event: React.PointerEvent) => {
    if (!pointerStart.current || dragStarted.current) return;
    if (shouldStartFloatingDrag(pointerStart.current, { x: event.clientX, y: event.clientY }, FLOATING_DRAG_THRESHOLD)) {
      dragged.current = true;
      dragStarted.current = true;
      void appWindow.startDragging().catch(() => {});
    }
  };

  const onIconPointerUp = (event: React.PointerEvent) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    pointerStart.current = null;
  };

  const onIconClick = (event: React.MouseEvent) => {
    if (dragged.current) {
      event.preventDefault();
      event.stopPropagation();
      dragged.current = false;
      dragStarted.current = false;
      return;
    }
    toggleExpanded();
  };

  const onToggleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      toggleExpanded();
    }
  };

  const onHeaderPointerDown = (event: React.PointerEvent) => {
    if (event.target instanceof Element && event.target.closest('button')) return;
    if (event.button === 0) void appWindow.startDragging().catch(() => {});
  };

  return (
    <main className={`floating-root ${expanded ? 'is-expanded' : 'is-collapsed'}`}>
      {!expanded && (
        <button
          className="floating-orb"
          type="button"
          aria-label="Grandpa Assistant"
          title="Grandpa Assistant"
          onPointerDown={onIconPointerDown}
          onPointerMove={onIconPointerMove}
          onPointerUp={onIconPointerUp}
          onPointerCancel={onIconPointerUp}
          onClick={onIconClick}
          onKeyDown={onToggleKeyDown}
        >
          <span className="floating-mark" aria-hidden="true">G</span>
          <span className={`floating-status-dot ${status?.state || 'checking'}`} aria-hidden="true" />
        </button>
      )}

      {expanded && (
        <section className="floating-panel" aria-label="Grandpa compact controls">
          <header className="floating-panel-header" onPointerDown={onHeaderPointerDown}>
            <div>
              <h1>Grandpa</h1>
              <p>{statusLabel(status)}</p>
            </div>
            <button type="button" className="floating-icon-button" aria-label="Collapse" onClick={() => void collapsePanel()}>
              <Minus size={16} />
            </button>
          </header>

          <div className={`floating-state ${status?.state || 'checking'}`} role="status">
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
              Chat: Coming soon
            </button>
          </div>
        </section>
      )}
    </main>
  );
}

async function restorePosition() {
  const monitors = await getMonitorBounds();
  const saved = await invoke<FloatingPosition | null>('get_floating_position').catch(() => null);
  const savedPosition = isValidPosition(saved) ? saved : null;
  const bounds = savedPosition ? boundsForPosition(monitors, savedPosition) || getFallbackBounds() : monitors[0] || getFallbackBounds();
  const safe = clampPositionToBounds(savedPosition, bounds, FLOATING_COLLAPSED_SIZE);
  await appWindow.setSize(new LogicalSize(FLOATING_COLLAPSED_SIZE.width, FLOATING_COLLAPSED_SIZE.height)).catch(() => {});
  await appWindow.setPosition(new PhysicalPosition(Math.round(safe.x), Math.round(safe.y))).catch(() => {});
}

async function getMonitorBounds(): Promise<FloatingBounds[]> {
  const monitors = await availableMonitors().catch(() => []);
  return monitors.map((monitor) => ({
    x: monitor.position.x,
    y: monitor.position.y,
    width: monitor.size.width,
    height: monitor.size.height,
  }));
}

function getFallbackBounds(): FloatingBounds {
  return {
    x: 0,
    y: 0,
    width: window.screen.availWidth || 1280,
    height: window.screen.availHeight || 720,
  };
}
