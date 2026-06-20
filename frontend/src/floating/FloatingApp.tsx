import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { ExternalLink, MessageSquare, Mic, Minus, Play, RefreshCw, Square } from 'lucide-react';
import { invoke } from '@tauri-apps/api/core';
import {
  availableMonitors,
  getCurrentWindow,
  LogicalPosition,
  LogicalSize,
} from '@tauri-apps/api/window';
import {
  boundsForPosition,
  clampPositionToBounds,
  FLOATING_COLLAPSED_SIZE,
  FLOATING_EXPANDED_SIZE,
  getCollapsedAnchorAfterExpand,
  getExpandedPosition,
  isValidPosition,
  normalizeApiBase,
  normalizeBackendState,
  statusLabel,
  type FloatingBackendStatus,
  type FloatingBounds,
  type FloatingPosition,
} from './floatingUtils';
import { GrandpaOrb } from './components/GrandpaOrb';

const POLL_MS = 4000;
const SAVE_DEBOUNCE_MS = 250;
type FloatingMode = 'collapsed' | 'resizing' | 'expanded';
type UnlistenFn = () => void;

function logFloating(message: string) {
  console.info(message);
  void invoke('floating_frontend_log', { message }).catch(() => {});
}

interface FloatingVoiceStatus {
  stt_available?: boolean;
  tts_available?: boolean;
  message?: string;
  setup_message?: string;
}

export function FloatingApp() {
  const appWindow = useMemo(() => getCurrentWindow(), []);
  const [mode, setMode] = useState<FloatingMode>('collapsed');
  const [status, setStatus] = useState<FloatingBackendStatus | null>(null);
  const [message, setMessage] = useState('');
  const [voiceStatus, setVoiceStatus] = useState<FloatingVoiceStatus | null>(null);
  const [voiceMessage, setVoiceMessage] = useState('');
  const [busy, setBusy] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [clickCount, setClickCount] = useState(0);
  const modeRef = useRef<FloatingMode>('collapsed');
  const resizeInFlight = useRef(false);
  const pollInFlight = useRef(false);
  const collapsedPosition = useRef<FloatingPosition | null>(null);
  const saveTimer = useRef<number | null>(null);

  useEffect(() => {
    logFloating('BUBBLE RENDERED');
  }, []);

  const setFloatingMode = useCallback((next: FloatingMode) => {
    modeRef.current = next;
    setMode(next);
  }, []);

  const refreshVoiceStatus = useCallback(async (apiBase?: string) => {
    const base = normalizeApiBase(apiBase || status?.api_base || 'http://127.0.0.1:8000');
    setVoiceMessage('Checking voice...');
    try {
      const response = await fetch(`${base}/v1/voice/status`, { cache: 'no-store' });
      if (!response.ok) throw new Error(`Voice status failed: ${response.status}`);
      const next = await response.json() as FloatingVoiceStatus;
      setVoiceStatus(next);
      setVoiceMessage(next.message || next.setup_message || 'Voice status ready.');
    } catch (error) {
      setVoiceStatus(null);
      setVoiceMessage(error instanceof Error ? error.message : 'Voice status is unavailable.');
    }
  }, [status?.api_base]);

  const refreshStatus = useCallback(async () => {
    if (pollInFlight.current) return;
    pollInFlight.current = true;
    try {
      const next = await invoke<FloatingBackendStatus>('floating_backend_status');
      const apiBase = normalizeApiBase(next.api_base || '');
      const normalized = {
        ...next,
        state: normalizeBackendState(next.state),
        api_base: apiBase,
      };
      setStatus(normalized);
      setMessage('');
      void refreshVoiceStatus(apiBase);
    } catch (error) {
      setStatus({ state: 'error', detail: 'Backend status is unavailable.', api_base: '' });
      setMessage(error instanceof Error ? error.message : 'Backend status is unavailable.');
    } finally {
      pollInFlight.current = false;
    }
  }, [refreshVoiceStatus]);

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

  const resizeNativeWindow = useCallback(async (
    nextMode: 'collapsed' | 'expanded',
    position?: FloatingPosition,
  ): Promise<boolean> => {
    const size = nextMode === 'expanded' ? FLOATING_EXPANDED_SIZE : FLOATING_COLLAPSED_SIZE;
    try {
      if (position) {
        await appWindow.setPosition(new LogicalPosition(Math.round(position.x), Math.round(position.y)));
      }
      await appWindow.setSize(new LogicalSize(size.width, size.height));
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

    const currentPosition = await getCurrentLogicalPosition().catch(() => null);
    const monitors = await getMonitorBounds();
    const bounds = currentPosition
      ? boundsForPosition(monitors, currentPosition) || getFallbackBounds()
      : monitors[0] || getFallbackBounds();
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

    const anchor = await getCurrentLogicalPosition().catch(() => null);
    if (anchor) collapsedPosition.current = anchor;
    const monitors = await getMonitorBounds();
    const bounds = anchor ? boundsForPosition(monitors, anchor) || getFallbackBounds() : monitors[0] || getFallbackBounds();
    const safeAnchor = anchor || clampPositionToBounds(null, bounds);
    const expandedPosition = getExpandedPosition(safeAnchor, bounds);

    const resized = await resizeNativeWindow('expanded', expandedPosition);
    resizeInFlight.current = false;
    setFloatingMode(resized ? 'expanded' : 'collapsed');
  }, [resizeNativeWindow, setFloatingMode]);

  useEffect(() => {
    void getCurrentLogicalPosition().then(async (position) => {
      const monitors = await getMonitorBounds();
      const bounds = boundsForPosition(monitors, position) || monitors[0] || getFallbackBounds();
      const safePosition = clampPositionToBounds(position, bounds, FLOATING_COLLAPSED_SIZE);
      collapsedPosition.current = safePosition;
      if (Math.abs(safePosition.x - position.x) > 0.5 || Math.abs(safePosition.y - position.y) > 0.5) {
        await appWindow.setPosition(new LogicalPosition(Math.round(safePosition.x), Math.round(safePosition.y)));
        saveCurrentPosition(safePosition);
      }
    }).catch(() => {});
    void appWindow.show().catch(() => {});
    void appWindow.setAlwaysOnTop(true).catch(() => {});
    void refreshStatus();
    const interval = window.setInterval(refreshStatus, POLL_MS);
    let unlisten: UnlistenFn | undefined;
    appWindow.onMoved((position) => {
      if (modeRef.current !== 'collapsed') return;
      void physicalToLogicalPosition({ x: position.payload.x, y: position.payload.y }).then((next) => {
        collapsedPosition.current = next;
        saveCurrentPosition(next);
      });
    }).then((listener) => {
      unlisten = listener;
    }).catch(() => {});
    return () => {
      window.clearInterval(interval);
      if (saveTimer.current !== null) window.clearTimeout(saveTimer.current);
      unlisten?.();
    };
  }, [appWindow, refreshStatus, saveCurrentPosition]);

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

  const onIconClick = () => {
    console.log('ORB CLICK');
    setClickCount((count) => count + 1);
    console.log('EXPANDING PANEL');
    void expandPanel();
  };

  const onIconMouseEnter = () => {
    setHovered(true);
  };

  const onToggleKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      setClickCount((count) => count + 1);
      void expandPanel();
    }
  };

  const stopInteractivePropagation = (event: React.PointerEvent | React.MouseEvent) => {
    event.stopPropagation();
  };

  const isExpanded = mode === 'expanded';
  const isResizing = mode === 'resizing';

  return (
    <main className={`floating-shell floating-root ${isExpanded ? 'expanded' : 'collapsed'} ${isResizing ? 'resizing' : ''}`}>
      {!isExpanded && (
        <button
          className={`floating-orb-button ${hovered ? 'hovered' : ''}`}
          type="button"
          aria-label="Grandpa Assistant"
          title="Grandpa Assistant"
          disabled={isResizing}
          onMouseEnter={onIconMouseEnter}
          onMouseLeave={() => {
            setHovered(false);
          }}
          onClick={onIconClick}
          onKeyDown={onToggleKeyDown}
        >
          <GrandpaOrb size={48} interactive />
          <span className="floating-click-probe" aria-hidden="true">{clickCount}</span>
        </button>
      )}

      {isExpanded && (
        <section className="floating-panel" aria-label="Grandpa compact controls">
          <header className="floating-panel-header">
            <GrandpaOrb size={34} className="floating-panel-orb" />
            <div className="floating-title-block">
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
              aria-label="Open Grandpa App"
            >
              <ExternalLink size={15} />
              Open Grandpa App
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
            <button
              type="button"
              disabled={busy || status?.state !== 'running'}
              aria-label="Check voice assistant status"
              onPointerDown={stopInteractivePropagation}
              onClick={() => void refreshVoiceStatus()}
            >
              <Mic size={15} />
              Voice: {voiceStatus?.stt_available || voiceStatus?.tts_available ? 'Ready' : 'Coming soon'}
            </button>
            <button type="button" disabled aria-label="Chat coming soon">
              <MessageSquare size={15} />
              Chat: Coming soon
            </button>
          </div>

          {voiceMessage && (
            <div className="floating-voice-note" role="status">
              {voiceMessage}
            </div>
          )}
        </section>
      )}
    </main>
  );
}

async function getCurrentLogicalPosition(): Promise<FloatingPosition> {
  const position = await getCurrentWindow().outerPosition();
  return physicalToLogicalPosition({ x: position.x, y: position.y });
}

async function physicalToLogicalPosition(position: FloatingPosition): Promise<FloatingPosition> {
  const monitors = await availableMonitors().catch(() => []);
  const monitor = monitors.find((candidate) => {
    const bounds = candidate.workArea;
    return (
      position.x >= bounds.position.x &&
      position.y >= bounds.position.y &&
      position.x <= bounds.position.x + bounds.size.width &&
      position.y <= bounds.position.y + bounds.size.height
    );
  }) || monitors[0];
  const scale = monitor?.scaleFactor || 1;
  return {
    x: position.x / scale,
    y: position.y / scale,
  };
}

async function getMonitorBounds(): Promise<FloatingBounds[]> {
  const monitors = await availableMonitors().catch(() => []);
  return monitors.map((monitor) => ({
    x: monitor.workArea.position.x / monitor.scaleFactor,
    y: monitor.workArea.position.y / monitor.scaleFactor,
    width: monitor.workArea.size.width / monitor.scaleFactor,
    height: monitor.workArea.size.height / monitor.scaleFactor,
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
