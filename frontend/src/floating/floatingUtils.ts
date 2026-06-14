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

export const FLOATING_COLLAPSED_SIZE = { width: 72, height: 72 };
export const FLOATING_EXPANDED_SIZE = { width: 320, height: 360 };

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
    x: bounds.x + Math.max(16, bounds.width - windowSize.width - 24),
    y: bounds.y + Math.max(16, bounds.height - windowSize.height - 72),
  };
  if (!position || !isValidPosition(position)) return fallback;
  const maxX = bounds.x + Math.max(0, bounds.width - windowSize.width);
  const maxY = bounds.y + Math.max(0, bounds.height - windowSize.height);
  const visible =
    position.x >= bounds.x &&
    position.y >= bounds.y &&
    position.x <= maxX &&
    position.y <= maxY;
  if (!visible) return fallback;
  return {
    x: Math.min(Math.max(position.x, bounds.x), maxX),
    y: Math.min(Math.max(position.y, bounds.y), maxY),
  };
}
