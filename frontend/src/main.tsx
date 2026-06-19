import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { invoke } from '@tauri-apps/api/core';
import { getCurrentWindow } from '@tauri-apps/api/window';
import { FloatingApp } from './floating/FloatingApp';

declare global {
  interface Window {
    __GRANDPA_FLOATING_WINDOW__?: boolean;
  }
}

function currentTauriWindowLabel(): string | null {
  try {
    return getCurrentWindow().label;
  } catch {
    return null;
  }
}

function isFloatingRoute(): boolean {
  const searchParams = new URLSearchParams(window.location.search);
  return Boolean(window.__GRANDPA_FLOATING_WINDOW__)
    || searchParams.has('floating')
    || currentTauriWindowLabel() === 'grandpa-floating';
}

function applyFloatingShellStyles() {
  const root = document.getElementById('root');
  for (const element of [document.documentElement, document.body, root].filter(Boolean) as HTMLElement[]) {
    element.style.width = '100%';
    element.style.height = '100%';
    element.style.margin = '0';
    element.style.padding = '0';
    element.style.overflow = 'hidden';
    element.style.background = '#020617';
  }
}

function logFloating(message: string) {
  console.info(message);
  void invoke('floating_frontend_log', { message }).catch(() => {});
}

function renderFallbackBubble() {
  createRoot(document.getElementById('root')!).render(
    <button
      type="button"
      aria-label="Grandpa Assistant"
      title="Grandpa Assistant"
      style={{
        width: 48,
        height: 48,
        border: 0,
        borderRadius: 999,
        background: '#0f172a',
        color: '#f8fafc',
        fontSize: 23,
        fontWeight: 850,
      }}
    >
      G
    </button>,
  );
}

if (isFloatingRoute()) {
  logFloating('FLOATING ROUTE DETECTED');
  document.title = 'Grandpa Assistant';
  applyFloatingShellStyles();
  void import('./floating/floating.css').catch((error) => {
    console.error('[Grandpa bootstrap] Floating CSS failed to load', error);
  });
  try {
    logFloating('FLOATING APP MOUNTED');
    createRoot(document.getElementById('root')!).render(
      <StrictMode>
        <FloatingApp />
      </StrictMode>,
    );
  } catch (error) {
    console.error('[Grandpa bootstrap] Floating UI failed to render', error);
    renderFallbackBubble();
  }
} else {
  void import('./index.css').then(async () => {
    const [{ BrowserRouter }, { ErrorBoundary }, { default: App }, { initApiBase }, { initAnalytics }] =
      await Promise.all([
        import('react-router'),
        import('./components/ErrorBoundary'),
        import('./App'),
        import('./lib/api'),
        import('./lib/analytics'),
      ]);

    function applyTheme() {
      try {
        const raw = localStorage.getItem('Grandpa-settings');
        const settings = raw ? JSON.parse(raw) : {};
        const theme = settings.theme || 'system';
        if (theme === 'dark') {
          document.documentElement.classList.add('dark');
          document.documentElement.classList.remove('light');
        } else if (theme === 'light') {
          document.documentElement.classList.add('light');
          document.documentElement.classList.remove('dark');
        }
      } catch {
        // Use system default.
      }
    }

    applyTheme();
    initApiBase().finally(() => {
      void initAnalytics();
      createRoot(document.getElementById('root')!).render(
        <StrictMode>
          <ErrorBoundary>
            <BrowserRouter>
              <App />
            </BrowserRouter>
          </ErrorBoundary>
        </StrictMode>,
      );
    });
  });
}
