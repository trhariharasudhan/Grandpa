import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import { ErrorBoundary } from './components/ErrorBoundary';
import App from './App';
import { initApiBase } from './lib/api';
import { initAnalytics } from './lib/analytics';
import './index.css';

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
  } catch { /* use system default */ }
}

applyTheme();

const searchParams = new URLSearchParams(window.location.search);

if (searchParams.has('floating')) {
  document.documentElement.style.width = '100%';
  document.documentElement.style.height = '100%';
  document.body.style.width = '100%';
  document.body.style.height = '100%';
  document.body.style.margin = '0';
  document.body.style.overflow = 'hidden';
  document.body.style.background = '#ff0000';
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <ErrorBoundary>
        <div
          style={{
            alignItems: 'center',
            background: '#ff0000',
            color: '#ffea00',
            display: 'flex',
            flexDirection: 'column',
            fontFamily: 'Arial, sans-serif',
            fontWeight: 900,
            gap: 8,
            height: '100vh',
            justifyContent: 'center',
            lineHeight: 1,
            width: '100vw',
          }}
        >
          <div style={{ fontSize: 144 }}>G</div>
          <div style={{ color: '#ffffff', fontSize: 24 }}>FLOATING ROUTE OK</div>
        </div>
      </ErrorBoundary>
    </StrictMode>,
  );
} else {
// Fetch the API base URL from the Tauri backend before rendering.
// This ensures GRANDPA_PORT is defined in one place (the Rust backend).
// In non-Tauri environments this is a no-op.
initApiBase().finally(() => {
  // Kick off analytics init in the background — it's never awaited so
  // a slow/failed identity fetch never delays UI render.
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
}
