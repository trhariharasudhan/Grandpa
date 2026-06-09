import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router';
import {
  MessageSquare,
  Plus,
  BarChart3,
  Settings,
  Search,
  PanelLeftClose,
  PanelLeft,
  Rocket,
  Bot,
  Sun,
  Moon,
  Monitor,
  ScrollText,
  Database,
  Brain,
  FolderOpen,
  Workflow,
  ShieldCheck,
  Globe2,
  Phone,
  Sparkles,
  Wrench,
  Network,
  Route,
  Boxes,
  CheckCircle2,
  Server,
  Layers3,
  Cpu,
  Flame,
  Zap,
  BrainCircuit,
  BookOpen,
  Mic2,
  Hammer,
  Code2,
  ClipboardCheck,
} from 'lucide-react';
import { ConversationList } from './ConversationList';
import { useAppStore } from '../../lib/store';

export function Sidebar() {
  const navigate = useNavigate();
  const location = useLocation();
  const [searchQuery, setSearchQuery] = useState('');

  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const createConversation = useAppStore((s) => s.createConversation);
  const selectedModel = useAppStore((s) => s.selectedModel);

  const settings = useAppStore((s) => s.settings);
  const updateSettings = useAppStore((s) => s.updateSettings);

  const ThemeIcon = settings.theme === 'light' ? Sun : settings.theme === 'dark' ? Moon : Monitor;
  const nextTheme = settings.theme === 'light' ? 'dark' : settings.theme === 'dark' ? 'system' : 'light';

  const messages = useAppStore((s) => s.messages);
  const handleNewChat = () => {
    // Don't create a new chat if the current one is empty
    if (messages.length === 0) {
      navigate('/');
      return;
    }
    createConversation(selectedModel);
    navigate('/');
  };

  const navItems = [
    { path: '/', icon: MessageSquare, label: 'Chat' },
    { path: '/dashboard', icon: BarChart3, label: 'Assistant Home' },
    { path: '/data-sources', icon: Database, label: 'Context' },
    { path: '/memory', icon: Brain, label: 'Memory' },
    { path: '/files', icon: FolderOpen, label: 'Files' },
    { path: '/routines', icon: Workflow, label: 'Routines' },
    { path: '/safety', icon: ShieldCheck, label: 'Safety' },
    { path: '/browser', icon: Globe2, label: 'Browser' },
    { path: '/desktop', icon: Monitor, label: 'Desktop' },
    { path: '/desktop-kernel', icon: Cpu, label: 'PC Kernel' },
    { path: '/mobile', icon: Phone, label: 'Mobile' },
    { path: '/capabilities', icon: Sparkles, label: 'Capabilities' },
    { path: '/skills', icon: Wrench, label: 'Skills' },
    { path: '/skills-builder', icon: Hammer, label: 'Skill Builder' },
    { path: '/plugins', icon: Boxes, label: 'Plugins' },
    { path: '/services', icon: Server, label: 'Services' },
    { path: '/actions', icon: Layers3, label: 'Actions' },
    { path: '/planner', icon: Network, label: 'Planner' },
    { path: '/router', icon: Route, label: 'Router' },
    { path: '/release-gate', icon: CheckCircle2, label: 'Release Gate' },
    { path: '/burnin', icon: Flame, label: 'Burn-In' },
    { path: '/audit', icon: ClipboardCheck, label: 'Audit' },
    { path: '/agent-mode', icon: Zap, label: 'Agent Mode' },
    { path: '/multi-agent', icon: BrainCircuit, label: 'Multi-Agent' },
    { path: '/knowledge', icon: BookOpen, label: 'Knowledge' },
    { path: '/voice', icon: Mic2, label: 'Voice' },
    { path: '/coding', icon: Code2, label: 'Coding' },
    { path: '/agents', icon: Bot, label: 'Agents' },
    { path: '/settings', icon: Settings, label: 'Settings' },
    { path: '/get-started', icon: Rocket, label: 'Get Started' },
  ];
  const supportItems = [
    { path: '/logs', icon: ScrollText, label: 'Activity Log' },
  ];
  const dailyItems = [
    { path: '/memory', icon: Brain, label: 'Memory' },
    { path: '/files', icon: FolderOpen, label: 'Files' },
    { path: '/routines', icon: Workflow, label: 'Routines' },
  ];

  return (
    <>
      {/* Collapse button when sidebar is closed */}
      {!sidebarOpen && (
        <button
          onClick={toggleSidebar}
          className="fixed top-3 left-3 z-30 p-2 rounded-lg transition-colors cursor-pointer"
          style={{ color: 'var(--color-text-secondary)', background: 'var(--color-bg-secondary)' }}
          onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
          onMouseLeave={(e) => (e.currentTarget.style.background = 'var(--color-bg-secondary)')}
        >
          <PanelLeft size={18} />
        </button>
      )}

      <aside
        className={`
          flex flex-col h-full shrink-0 transition-all duration-200 ease-in-out overflow-hidden
          fixed md:relative z-30
          ${sidebarOpen ? 'w-[260px]' : 'w-0'}
        `}
        style={{
          background: 'color-mix(in srgb, var(--color-sidebar) 86%, transparent)',
          backdropFilter: 'blur(24px) saturate(132%)',
          WebkitBackdropFilter: 'blur(24px) saturate(132%)',
          borderRight: sidebarOpen ? '1px solid color-mix(in srgb, var(--color-accent) 16%, var(--color-border))' : 'none',
          boxShadow: sidebarOpen ? 'inset -1px 0 0 color-mix(in srgb, var(--color-text) 3%, transparent)' : 'none',
        }}
      >
        <div className="flex flex-col h-full w-[260px]">
          {/* Header */}
          <div className="flex items-center justify-between px-3 pt-3 pb-2">
            <button
              onClick={toggleSidebar}
              className="p-2 rounded-lg transition-colors cursor-pointer"
              style={{ color: 'var(--color-text-secondary)' }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
            >
              <PanelLeftClose size={18} />
            </button>
            <div className="flex items-center gap-1">
              <button
                onClick={() => updateSettings({ theme: nextTheme })}
                className="p-2 rounded-lg transition-colors cursor-pointer"
                style={{ color: 'var(--color-text-secondary)' }}
                onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-bg-tertiary)')}
                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                title={`Theme: ${settings.theme} (click for ${nextTheme})`}
              >
                <ThemeIcon size={16} />
              </button>
            </div>
          </div>

          <div className="px-3 pb-3">
            <button
              onClick={handleNewChat}
              className="w-full flex items-center justify-center gap-2 px-3 py-2.5 rounded-xl text-sm font-medium transition-all cursor-pointer"
              style={{
                background: 'linear-gradient(135deg, var(--color-accent), color-mix(in srgb, var(--color-accent) 72%, var(--color-accent-amber)))',
                color: 'var(--color-on-accent)',
                boxShadow: '0 16px 36px -20px var(--color-accent), inset 0 1px 0 rgba(255,255,255,0.14)',
              }}
              onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-accent-hover)')}
              onMouseLeave={(e) => (e.currentTarget.style.background = 'linear-gradient(135deg, var(--color-accent), color-mix(in srgb, var(--color-accent) 72%, var(--color-accent-amber)))')}
            >
              <Plus size={16} />
              New Chat
            </button>
          </div>

          <div className="px-3 pb-3">
            <div className="grid grid-cols-3 gap-1.5">
              {dailyItems.map((item) => {
                const isActive = location.pathname === item.path;
                return (
                  <button
                    key={item.path}
                    type="button"
                    onClick={() => navigate(item.path)}
                    title={`Open ${item.label}`}
                    className="flex flex-col items-center gap-1 rounded-xl px-2 py-2 text-[11px] transition-colors cursor-pointer"
                    style={{
                      background: isActive ? 'var(--color-accent-subtle)' : 'color-mix(in srgb, var(--color-bg-secondary) 74%, transparent)',
                      border: `1px solid ${isActive ? 'var(--color-accent)' : 'var(--color-border)'}`,
                      color: isActive ? 'var(--color-text)' : 'var(--color-text-secondary)',
                    }}
                  >
                    <item.icon size={14} style={{ color: isActive ? 'var(--color-accent)' : 'var(--color-accent-amber)' }} />
                    <span>{item.label}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Search */}
          <div className="px-3 mb-3">
            <div
              className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm"
              style={{
                background: 'color-mix(in srgb, var(--color-bg-secondary) 72%, transparent)',
                border: '1px solid var(--color-border)',
                boxShadow: 'inset 0 1px 0 color-mix(in srgb, var(--color-text) 5%, transparent)',
              }}
            >
              <Search size={14} style={{ color: 'var(--color-text-tertiary)' }} />
              <input
                type="text"
                placeholder="Search chats..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="flex-1 bg-transparent outline-none text-sm"
                style={{ color: 'var(--color-text)' }}
              />
            </div>
          </div>

          {/* Conversation list */}
          <div className="flex-1 overflow-y-auto px-2">
            <ConversationList searchQuery={searchQuery} />
          </div>

          {/* Bottom nav */}
          <nav className="px-2 pb-3 pt-2 flex flex-col gap-1" style={{ borderTop: '1px solid var(--color-border)' }}>
            <div className="px-3 pb-1 text-[10px] uppercase tracking-[0.18em]" style={{ color: 'var(--color-text-tertiary)' }}>
              Assistant
            </div>
            {navItems.map((item) => {
              const isActive = location.pathname === item.path;
              return (
                <button
                  key={item.path}
                  onClick={() => navigate(item.path)}
                  className="relative flex items-center gap-3 px-3 py-2 rounded-xl text-sm transition-colors w-full text-left cursor-pointer"
                  style={{
                    background: isActive ? 'var(--color-accent-subtle)' : 'transparent',
                    color: isActive ? 'var(--color-text)' : 'var(--color-text-secondary)',
                    fontWeight: isActive ? 500 : 400,
                  }}
                  onMouseEnter={(e) => {
                    if (!isActive) e.currentTarget.style.background = 'var(--color-bg-secondary)';
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) e.currentTarget.style.background = 'transparent';
                  }}
                >
                  {isActive && (
                    <span
                      aria-hidden="true"
                      className="absolute left-0 top-1.5 bottom-1.5 w-[2px] rounded-full"
                      style={{
                        background: 'var(--color-accent)',
                        boxShadow: '0 0 8px var(--color-accent-glow)',
                      }}
                    />
                  )}
                  <item.icon size={16} style={isActive ? { color: 'var(--color-accent)' } : undefined} />
                  {item.label}
                </button>
              );
            })}
            <div className="px-3 pb-1 pt-3 text-[10px] uppercase tracking-[0.18em]" style={{ color: 'var(--color-text-tertiary)' }}>
              Support
            </div>
            {supportItems.map((item) => {
              const isActive = location.pathname === item.path;
              return (
                <button
                  key={item.path}
                  onClick={() => navigate(item.path)}
                  className="relative flex items-center gap-3 px-3 py-2 rounded-xl text-sm transition-colors w-full text-left cursor-pointer"
                  style={{
                    background: isActive ? 'var(--color-bg-secondary)' : 'transparent',
                    color: isActive ? 'var(--color-text)' : 'var(--color-text-tertiary)',
                    fontWeight: isActive ? 500 : 400,
                  }}
                  onMouseEnter={(e) => {
                    if (!isActive) e.currentTarget.style.background = 'var(--color-bg-secondary)';
                  }}
                  onMouseLeave={(e) => {
                    if (!isActive) e.currentTarget.style.background = 'transparent';
                  }}
                >
                  <item.icon size={15} style={isActive ? { color: 'var(--color-accent)' } : undefined} />
                  {item.label}
                </button>
              );
            })}
          </nav>
        </div>
      </aside>
    </>
  );
}
