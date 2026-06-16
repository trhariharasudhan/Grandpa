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
  FLOATING_POSITION_SAVE_DELAY_MS,
  getCollapsedAnchorAfterExpand,
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
type FloatingMode = 'collapsed' | 'resizing' | 'expanded';

function debugLog(message: string, data?: unknown) {
  if (!import.meta.env.DEV) return;
  if (data === undefined) {
    console.debug(`[Grandpa floating] ${message}`);
  } else {
    console.debug(`[Grandpa floating] ${message}`, data);
  }
}

export function FloatingApp() {
  const [mode, setMode] = useState<FloatingMode>('collapsed');
  const [status, setStatus] = useState<FloatingBackendStatus | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const modeRef = useRef<FloatingMode>('collapsed');
  const resizeInFlight = useRef(false);
  const pollInFlight = useRef(false);
  const pointerStart = useRef<FloatingPosition | null>(null);
  const dragging = useRef(false);
  const dragStarted = useRef(false);
  const suppressNextClick = useRef(false);
  const collapsedPosition = useRef<FloatingPosition | null>(null);
  const saveTimer = useRef<number | null>(null);
  const dragSaveTimer = useRef<number | null>(null);

  const setFloatingMode = useCallback((next: FloatingMode) => {
    modeRef.current = next;
    setMode(next);
    debugLog(`state: ${next}`);
  }, []);

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
    const monitorsPromise = getMonitorBounds();
    if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(() => {
      void monitorsPromise.then((monitors) => {
        const bounds = boundsForPosition(monitors, position) || monitors[0] || getFallbackBounds();
        const safe = clampPositionToBounds(position, bounds, FLOATING_COLLAPSED_SIZE);
        void invoke('save_floating_position', { position: safe }).catch(() => {});
      });
    }, SAVE_DEBOUNCE_MS);
  }, []);

  const persistActualPositionSoon = useCallback(() => {
    if (dragSaveTimer.current !== null) window.clearTimeout(dragSaveTimer.current);
    dragSaveTimer.current = window.setTimeout(() => {
      void appWindow.outerPosition().then((position) => {
        const next = { x: position.x, y: position.y };
        collapsedPosition.current = next;
        debugLog('actual window position after drag', next);
        saveCurrentPosition(next);
      }).catch((error) => {
        debugLog('position read after drag failed', error);
      });
    }, FLOATING_POSITION_SAVE_DELAY_MS);
  }, [saveCurrentPosition]);

  const resizeNativeWindow = useCallback(async (
    nextMode: 'collapsed' | 'expanded',
    position?: FloatingPosition,
  ): Promise<boolean> => {
    const size = nextMode === 'expanded' ? FLOATING_EXPANDED_SIZE : FLOATING_COLLAPSED_SIZE;
    debugLog('resize requested', { nextMode, size, position });
    try {
      if (position) {
        await appWindow.setPosition(new PhysicalPosition(Math.round(position.x), Math.round(position.y)));
      }
      await appWindow.setSize(new LogicalSize(size.width, size.height));
      const outerSize = await appWindow.outerSize().catch(() => null);
      debugLog('resize completed', { nextMode, outerSize });
      return true;
    } catch (error) {
      console.warn('[Grandpa floating] resize failed', error);
      return false;
    }
  }, []);

  const collapsePanel = useCallback(async () => {
    if (resizeInFlight.current || modeRef.current === 'collapsed') return;
    resizeInFlight.current = true;
    setFloatingMode('resizing');

    const current = await appWindow.outerPosition().catch(() => null);
    const currentPosition = current ? { x: current.x, y: current.y } : null;
    const monitors = await getMonitorBounds();
    const bounds = currentPosition ? boundsForPosition(monitors, currentPosition) || getFallbackBounds() : monitors[0] || getFallbackBounds();
    const previousAnchor = collapsedPosition.current || currentPosition || clampPositionToBounds(null, bounds);
    const collapsePosition = currentPosition
      ? getCollapsedAnchorAfterExpand(currentPosition, previousAnchor, bounds)
      : previousAnchor;

    const resized = await resizeNativeWindow('collapsed', collapsePosition);
    resizeInFlight.current = false;
    if (resized) {
      collapsedPosition.current = collapsePosition;
      saveCurrentPosition(collapsePosition);
      setFloatingMode('collapsed');
    } else {
      setFloatingMode('expanded');
    }
  }, [resizeNativeWindow, saveCurrentPosition, setFloatingMode]);

  const expandPanel = useCallback(async () => {
    if (resizeInFlight.current || modeRef.current === 'expanded') return;
    resizeInFlight.current = true;
    setFloatingMode('resizing');

    const current = await appWindow.outerPosition().catch(() => null);
    const anchor = current ? { x: current.x, y: current.y } : null;
    if (anchor) collapsedPosition.current = anchor;

    const monitors = await getMonitorBounds();
    const fallbackBounds = getFallbackBounds();
    const bounds = anchor ? boundsForPosition(monitors, anchor) || fallbackBounds : monitors[0] || fallbackBounds;
    const safeAnchor = anchor || clampPositionToBounds(null, bounds);
    const expandedPosition = getExpandedPosition(safeAnchor, bounds);

    const resized = await resizeNativeWindow('expanded', expandedPosition);
    resizeInFlight.current = false;
    if (resized) {
      setFloatingMode('expanded');
    } else {
      setFloatingMode('collapsed');
    }
  }, [resizeNativeWindow, setFloatingMode]);

  const toggleExpanded = useCallback(() => {
    if (resizeInFlight.current || modeRef.current === 'resizing') return;
    debugLog('click toggle', modeRef.current);
    if (modeRef.current === 'expanded') {
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
      if (modeRef.current !== 'collapsed') return;
      const next = { x: position.payload.x, y: position.payload.y };
      collapsedPosition.current = next;
      saveCurrentPosition(next);
    }).then((listener) => {
      unlisten = listener;
    }).catch(() => {});
    return () => {
      window.clearInterval(interval);
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
      if (dragSaveTimer.current !== null) window.clearTimeout(dragSaveTimer.current);
      unlisten?.();
    };
  }, [refreshStatus, saveCurrentPosition]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        void collapsePanel();
      }
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

  const startNativeDrag = useCallback(async () => {
    if (dragStarted.current) return;
    dragging.current = true;
    dragStarted.current = true;
    suppressNextClick.current = true;
    debugLog('drag threshold crossed');
    debugLog('startDragging called');
    try {
      await appWindow.startDragging();
      debugLog('native drag completed');
    } catch (error) {
      debugLog('native drag failed', error);
    } finally {
      persistActualPositionSoon();
    }
  }, [persistActualPositionSoon]);

  const onIconPointerDown = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0 || modeRef.current !== 'collapsed' || resizeInFlight.current) return;
    debugLog('pointer down', { x: event.clientX, y: event.clientY });
    event.currentTarget.setPointerCapture(event.pointerId);
    pointerStart.current = { x: event.clientX, y: event.clientY };
    dragging.current = false;
    dragStarted.current = false;
    suppressNextClick.current = false;
  };

  const onIconPointerMove = (event: React.PointerEvent) => {
    if (!pointerStart.current || dragStarted.current) return;
    if (shouldStartFloatingDrag(pointerStart.current, { x: event.clientX, y: event.clientY }, FLOATING_DRAG_THRESHOLD)) {
      void startNativeDrag();
    }
  };

  const onIconPointerUp = (event: React.PointerEvent<HTMLButtonElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    const didDrag = dragging.current || suppressNextClick.current;
    pointerStart.current = null;
    dragging.current = false;
    dragStarted.current = false;
    if (didDrag) {
      persistActualPositionSoon();
      return;
    }
    suppressNextClick.current = true;
    toggleExpanded();
  };

  const onIconClick = (event: React.MouseEvent) => {
    if (suppressNextClick.current) {
      event.preventDefault();
      event.stopPropagation();
      suppressNextClick.current = false;
      return;
    }
  };

  const onToggleKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      toggleExpanded();
    }
  };

  const onHeaderPointerDown = (event: React.PointerEvent) => {
    if (event.button !== 0) return;
    if (event.target instanceof Element && event.target.closest('button')) return;
    debugLog('expanded header drag');
    void appWindow.startDragging().then(() => debugLog('native drag completed')).catch((error) => {
      debugLog('native drag failed', error);
    });
  };

  const stopInteractivePropagation = (event: React.PointerEvent | React.MouseEvent) => {
    event.stopPropagation();
  };

  const isExpanded = mode === 'expanded';
  const isResizing = mode === 'resizing';

  return (
    <main className={`floating-root ${isExpanded ? 'expanded' : 'collapsed'} ${isResizing ? 'resizing' : ''}`}>
      {!isExpanded && (
        <button
          className="floating-orb"
          type="button"
          aria-label="Grandpa Assistant"
          disabled={isResizing}
          title="Grandpa Assistant"
          onPointerDown={onIconPointerDown}
          onPointerMove={onIconPointerMove}
          onPointerUp={onIconPointerUp}
          onPointerCancel={() => {
            if (!dragStarted.current) pointerStart.current = null;
          }}
          onClick={onIconClick}
          onKeyDown={onToggleKeyDown}
        >
          <span className="floating-mark" aria-hidden="true">G</span>
          <span className={`floating-status-dot ${status?.state || 'checking'}`} aria-hidden="true" />
        </button>
      )}

      {isExpanded && (
        <section className="floating-panel" aria-label="Grandpa compact controls">
          <header className="floating-panel-header" data-tauri-drag-region onPointerDown={onHeaderPointerDown}>
            <div className="floating-title-block" data-tauri-drag-region>
              <h1>Grandpa</h1>
              <p>{statusLabel(status)}</p>
            </div>
            <button
              type="button"
              className="floating-icon-button"
              aria-label="Collapse"
              disabled={isResizing}
              onPointerDown={stopInteractivePropagation}
              onClick={(event) => {
                event.stopPropagation();
                void collapsePanel();
              }}
            >
              <Minus size={16} />
            </button>
          </header>

          <div className={`floating-state ${status?.state || 'checking'}`} role="status">
            <span>{status?.detail || 'Checking backend...'}</span>
          </div>

          {message && <div className="floating-message" role="status">{message}</div>}

          <div className="floating-actions">
            <button
              type="button"
              onPointerDown={stopInteractivePropagation}
              onClick={() => invoke('floating_open_main_app')}
              aria-label="Open Full App"
            >
              <ExternalLink size={15} />
              Open Full App
            </button>
            {status?.state === 'running' ? (
              <button
                type="button"
                disabled={busy}
                onPointerDown={stopInteractivePropagation}
                onClick={() => runAction('floating_stop_backend')}
                aria-label="Stop Backend"
              >
                <Square size={15} />
                Stop Backend
              </button>
            ) : (
              <button
                type="button"
                disabled={busy}
                onPointerDown={stopInteractivePropagation}
                onClick={() => runAction('floating_start_backend')}
                aria-label="Start Backend"
              >
                <Play size={15} />
                Start Backend
              </button>
            )}
            <button
              type="button"
              disabled={busy}
              onPointerDown={stopInteractivePropagation}
              onClick={refreshStatus}
              aria-label="Refresh Status"
            >
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
