import { lazy, Suspense, useEffect, useState, useCallback, useRef } from 'react';
import { Routes, Route } from 'react-router';
import { Layout } from './components/Layout';
import { ChatPage } from './pages/ChatPage';
import { CommandPalette } from './components/CommandPalette';
import { SetupScreen } from './components/SetupScreen';
import { Toaster } from './components/ui/sonner';
import { useAppStore } from './lib/store';
import { fetchModels, fetchServerInfo, fetchRuntimeUsage, isTauri } from './lib/api';
import { UpdateChecker } from './components/Desktop/UpdateChecker';
import { track, hashId } from './lib/analytics';

const DashboardPage = lazy(() => import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })));
const SettingsPage = lazy(() => import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })));
const GetStartedPage = lazy(() => import('./pages/GetStartedPage').then((m) => ({ default: m.GetStartedPage })));
const AgentsPage = lazy(() => import('./pages/AgentsPage').then((m) => ({ default: m.AgentsPage })));
const DataSourcesPage = lazy(() => import('./pages/DataSourcesPage').then((m) => ({ default: m.DataSourcesPage })));
const LogsPage = lazy(() => import('./pages/LogsPage').then((m) => ({ default: m.LogsPage })));
const MemoryPage = lazy(() => import('./pages/MemoryPage').then((m) => ({ default: m.MemoryPage })));
const FileAssistantPage = lazy(() => import('./pages/FileAssistantPage').then((m) => ({ default: m.FileAssistantPage })));
const RoutinesPage = lazy(() => import('./pages/RoutinesPage').then((m) => ({ default: m.RoutinesPage })));
const SafetyPage = lazy(() => import('./pages/SafetyPage').then((m) => ({ default: m.SafetyPage })));
const BrowserPage = lazy(() => import('./pages/BrowserPage').then((m) => ({ default: m.BrowserPage })));
const DesktopServicesPage = lazy(() => import('./pages/DesktopServicesPage').then((m) => ({ default: m.DesktopServicesPage })));
const DesktopKernelPage = lazy(() => import('./pages/DesktopKernelPage').then((m) => ({ default: m.DesktopKernelPage })));
const MobileCompanionPage = lazy(() => import('./pages/MobileCompanionPage').then((m) => ({ default: m.MobileCompanionPage })));
const CapabilitiesPage = lazy(() => import('./pages/CapabilitiesPage').then((m) => ({ default: m.CapabilitiesPage })));
const SkillsPage = lazy(() => import('./pages/SkillsPage').then((m) => ({ default: m.SkillsPage })));
const SkillsBuilderPage = lazy(() => import('./pages/SkillsBuilderPage').then((m) => ({ default: m.SkillsBuilderPage })));
const PluginsPage = lazy(() => import('./pages/PluginsPage').then((m) => ({ default: m.PluginsPage })));
const ServicesPage = lazy(() => import('./pages/ServicesPage').then((m) => ({ default: m.ServicesPage })));
const ActionsPage = lazy(() => import('./pages/ActionsPage').then((m) => ({ default: m.ActionsPage })));
const PlannerPage = lazy(() => import('./pages/PlannerPage').then((m) => ({ default: m.PlannerPage })));
const RouterDiagnosticsPage = lazy(() => import('./pages/RouterDiagnosticsPage').then((m) => ({ default: m.RouterDiagnosticsPage })));
const ReleaseGatePage = lazy(() => import('./pages/ReleaseGatePage').then((m) => ({ default: m.ReleaseGatePage })));
const BurnInPage = lazy(() => import('./pages/BurnInPage').then((m) => ({ default: m.BurnInPage })));
const AuditPage = lazy(() => import('./pages/AuditPage').then((m) => ({ default: m.AuditPage })));
const AgentModePage = lazy(() => import('./pages/AgentModePage').then((m) => ({ default: m.AgentModePage })));
const MultiAgentPage = lazy(() => import('./pages/MultiAgentPage').then((m) => ({ default: m.MultiAgentPage })));
const KnowledgePage = lazy(() => import('./pages/KnowledgePage').then((m) => ({ default: m.KnowledgePage })));
const VoicePage = lazy(() => import('./pages/VoicePage').then((m) => ({ default: m.VoicePage })));
const CodingPage = lazy(() => import('./pages/CodingPage').then((m) => ({ default: m.CodingPage })));

export default function App() {
  const [setupDone, setSetupDone] = useState(!isTauri());
  const handleSetupReady = useCallback(() => {
    setSetupDone(true);
    track('setup_completed', { preset: 'default' });
  }, []);
  const prevModelRef = useRef<string>('');
  const setModels = useAppStore((s) => s.setModels);
  const setModelsLoading = useAppStore((s) => s.setModelsLoading);
  const setSelectedModel = useAppStore((s) => s.setSelectedModel);
  const selectedModel = useAppStore((s) => s.selectedModel);
  const setServerInfo = useAppStore((s) => s.setServerInfo);
  const setRuntimeUsage = useAppStore((s) => s.setRuntimeUsage);
  const settings = useAppStore((s) => s.settings);
  const commandPaletteOpen = useAppStore((s) => s.commandPaletteOpen);
  const setCommandPaletteOpen = useAppStore((s) => s.setCommandPaletteOpen);

  // Apply theme class to <html>
  useEffect(() => {
    const root = document.documentElement;
    root.classList.remove('dark', 'light');
    if (settings.theme === 'dark') root.classList.add('dark');
    else if (settings.theme === 'light') root.classList.add('light');
  }, [settings.theme]);

  // Sync overlay conversations into the main app
  const importOverlay = useAppStore((s) => s.importOverlayConversation);
  useEffect(() => {
    if (!isTauri()) return;
    importOverlay();
    const interval = setInterval(importOverlay, 5000);
    return () => clearInterval(interval);
  }, [importOverlay]);

  // Fetch models on mount
  useEffect(() => {
    fetchModels()
      .then((m) => {
        setModels(m);
        if (!selectedModel && m.length > 0) setSelectedModel(m[0].id);
      })
      .catch(() => setModels([]))
      .finally(() => setModelsLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch server info
  useEffect(() => {
    fetchServerInfo().then(setServerInfo).catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Poll lightweight runtime counters used by assistant diagnostics.
  useEffect(() => {
    const refresh = () =>
      fetchRuntimeUsage()
        .then(setRuntimeUsage)
        .catch(() => {});
    refresh();
    const interval = setInterval(refresh, 30000);
    return () => clearInterval(interval);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fire model_changed when the user switches models. First mount is
  // not a "change" — only emit when both prev and current are real and
  // differ.
  useEffect(() => {
    const prev = prevModelRef.current;
    const curr = selectedModel || '';
    prevModelRef.current = curr;
    if (!prev || !curr || prev === curr) return;
    void (async () => {
      const [fromHash, toHash] = await Promise.all([
        hashId(prev),
        hashId(curr),
      ]);
      track('model_changed', {
        from_model_hash: fromHash,
        to_model_hash: toHash,
      });
    })();
  }, [selectedModel]);

  // app_opened — one-shot per app launch, fires after analytics has had
  // a chance to initialize. platform + version are super-properties
  // registered in analytics.ts initAnalytics, so no per-call props needed.
  useEffect(() => {
    const t = setTimeout(() => {
      track('app_opened', {});
    }, 500);
    return () => clearTimeout(t);
  }, []);

  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);

  // Global keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setCommandPaletteOpen(!commandPaletteOpen);
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'i') {
        e.preventDefault();
        toggleSystemPanel();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [commandPaletteOpen, setCommandPaletteOpen, toggleSystemPanel]);


  if (!setupDone) {
    return <SetupScreen onReady={handleSetupReady} />;
  }

  return (
    <>
      <UpdateChecker />
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<ChatPage />} />
            <Route path="dashboard" element={<DashboardPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="get-started" element={<GetStartedPage />} />
            <Route path="data-sources" element={<DataSourcesPage />} />
            <Route path="memory" element={<MemoryPage />} />
            <Route path="files" element={<FileAssistantPage />} />
            <Route path="routines" element={<RoutinesPage />} />
            <Route path="safety" element={<SafetyPage />} />
            <Route path="browser" element={<BrowserPage />} />
            <Route path="desktop" element={<DesktopServicesPage />} />
            <Route path="desktop-kernel" element={<DesktopKernelPage />} />
            <Route path="mobile" element={<MobileCompanionPage />} />
            <Route path="capabilities" element={<CapabilitiesPage />} />
            <Route path="skills" element={<SkillsPage />} />
            <Route path="skills-builder" element={<SkillsBuilderPage />} />
            <Route path="plugins" element={<PluginsPage />} />
            <Route path="services" element={<ServicesPage />} />
            <Route path="actions" element={<ActionsPage />} />
            <Route path="planner" element={<PlannerPage />} />
            <Route path="router" element={<RouterDiagnosticsPage />} />
            <Route path="release-gate" element={<ReleaseGatePage />} />
            <Route path="burnin" element={<BurnInPage />} />
            <Route path="audit" element={<AuditPage />} />
            <Route path="agent-mode" element={<AgentModePage />} />
            <Route path="multi-agent" element={<MultiAgentPage />} />
            <Route path="knowledge" element={<KnowledgePage />} />
            <Route path="voice" element={<VoicePage />} />
            <Route path="coding" element={<CodingPage />} />
            <Route path="agents" element={<AgentsPage />} />
            <Route path="logs" element={<LogsPage />} />
          </Route>
        </Routes>
      </Suspense>
      <Toaster position="bottom-right" />
      {commandPaletteOpen && <CommandPalette />}
    </>
  );
}

function RouteFallback() {
  return (
    <div
      className="h-screen w-screen flex items-center justify-center"
      style={{ background: 'var(--color-bg)', color: 'var(--color-text-secondary)' }}
    >
      <div
        className="rounded-2xl px-4 py-3 text-sm"
        style={{
          background: 'var(--color-bg-secondary)',
          border: '1px solid var(--color-border)',
        }}
      >
        Loading Grandpa workspace...
      </div>
    </div>
  );
}
