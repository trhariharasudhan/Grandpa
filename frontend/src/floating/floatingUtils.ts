export type FloatingBackendState = 'running' | 'stopped' | 'checking' | 'error';

export interface FloatingBackendStatus {
  state: FloatingBackendState;
  detail: string;
  api_base: string;
}

export interface FloatingPosition {
  x: number;
  y: number;
}

export interface FloatingBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export const FLOATING_COLLAPSED_SIZE = { width: 64, height: 64 };
export const FLOATING_EXPANDED_SIZE = { width: 300, height: 340 };
export const FLOATING_EDGE_GAP = 24;
export const FLOATING_DRAG_THRESHOLD = 5;
export const FLOATING_POSITION_SAVE_DELAY_MS = 180;

export function normalizeBackendState(value: unknown): FloatingBackendState {
  return value === 'running' || value === 'stopped' || value === 'error' ? value : 'checking';
}

export function statusLabel(status: FloatingBackendStatus | null): string {
  if (!status) return 'Checking backend...';
  if (status.state === 'running') return 'Backend running';
  if (status.state === 'stopped') return 'Backend stopped';
  if (status.state === 'error') return 'Backend needs attention';
  return 'Checking backend...';
}

export function normalizeApiBase(url: string): string {
  return url.replace('0.0.0.0', '127.0.0.1').replace('[::]', '127.0.0.1').replace(/\/+$/, '');
}

export function isValidPosition(position: unknown): position is FloatingPosition {
  if (!position || typeof position !== 'object') return false;
  const candidate = position as FloatingPosition;
  return (
    Number.isFinite(candidate.x) &&
    Number.isFinite(candidate.y) &&
    Math.abs(candidate.x) < 100000 &&
    Math.abs(candidate.y) < 100000
  );
}

export function clampPositionToBounds(
  position: FloatingPosition | null,
  bounds: FloatingBounds,
  windowSize = FLOATING_COLLAPSED_SIZE,
): FloatingPosition {
  const fallback = {
    x: bounds.x + Math.max(FLOATING_EDGE_GAP, bounds.width - windowSize.width - FLOATING_EDGE_GAP),
    y: bounds.y + Math.max(FLOATING_EDGE_GAP, bounds.height - windowSize.height - 72),
  };
  if (!position || !isValidPosition(position)) return fallback;
  const minX = bounds.x + FLOATING_EDGE_GAP;
  const minY = bounds.y + FLOATING_EDGE_GAP;
  const maxX = bounds.x + Math.max(FLOATING_EDGE_GAP, bounds.width - windowSize.width - FLOATING_EDGE_GAP);
  const maxY = bounds.y + Math.max(FLOATING_EDGE_GAP, bounds.height - windowSize.height - FLOATING_EDGE_GAP);
  const screenMaxX = bounds.x + Math.max(0, bounds.width - windowSize.width);
  const screenMaxY = bounds.y + Math.max(0, bounds.height - windowSize.height);
  const onScreen =
    position.x >= bounds.x &&
    position.y >= bounds.y &&
    position.x <= screenMaxX &&
    position.y <= screenMaxY;
  if (!onScreen) return fallback;
  return {
    x: Math.min(Math.max(position.x, minX), maxX),
    y: Math.min(Math.max(position.y, minY), maxY),
  };
}

export function shouldStartFloatingDrag(
  start: FloatingPosition | null,
  current: FloatingPosition,
  threshold = FLOATING_DRAG_THRESHOLD,
): boolean {
  if (!start) return false;
  return Math.hypot(current.x - start.x, current.y - start.y) > threshold;
}

export function boundsForPosition(
  monitors: FloatingBounds[],
  position: FloatingPosition,
): FloatingBounds | null {
  return monitors.find((bounds) => (
    position.x >= bounds.x &&
    position.y >= bounds.y &&
    position.x <= bounds.x + bounds.width &&
    position.y <= bounds.y + bounds.height
  )) || monitors[0] || null;
}

export function getExpandedPosition(
  anchor: FloatingPosition,
  bounds: FloatingBounds,
): FloatingPosition {
  const opensLeft = anchor.x + FLOATING_EXPANDED_SIZE.width > bounds.x + bounds.width;
  const opensUp = anchor.y + FLOATING_EXPANDED_SIZE.height > bounds.y + bounds.height;
  const preferred = {
    x: opensLeft ? anchor.x + FLOATING_COLLAPSED_SIZE.width - FLOATING_EXPANDED_SIZE.width : anchor.x,
    y: opensUp ? anchor.y + FLOATING_COLLAPSED_SIZE.height - FLOATING_EXPANDED_SIZE.height : anchor.y,
  };
  return clampPositionToBounds(preferred, bounds, FLOATING_EXPANDED_SIZE);
}

export function getCollapsedAnchorAfterExpand(
  expandedPosition: FloatingPosition,
  previousAnchor: FloatingPosition,
  bounds: FloatingBounds,
): FloatingPosition {
  const expandedRight = expandedPosition.x + FLOATING_EXPANDED_SIZE.width;
  const expandedBottom = expandedPosition.y + FLOATING_EXPANDED_SIZE.height;
  const wasNearRight = previousAnchor.x + FLOATING_EXPANDED_SIZE.width > bounds.x + bounds.width;
  const wasNearBottom = previousAnchor.y + FLOATING_EXPANDED_SIZE.height > bounds.y + bounds.height;
  return clampPositionToBounds({
    x: wasNearRight ? expandedRight - FLOATING_COLLAPSED_SIZE.width : expandedPosition.x,
    y: wasNearBottom ? expandedBottom - FLOATING_COLLAPSED_SIZE.height : expandedPosition.y,
  }, bounds, FLOATING_COLLAPSED_SIZE);
}
