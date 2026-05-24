import { useRef, useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router';
import { MessageBubble } from './MessageBubble';
import { InputArea } from './InputArea';
import { StreamingDots } from './StreamingDots';
import { useAppStore } from '../../lib/store';
import { Sparkles, PanelRightOpen, PanelRightClose, Database, MessageSquare, X, Brain, Zap } from 'lucide-react';
import { listConnectors } from '../../lib/connectors-api';

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}

export function ChatArea() {
  const messages = useAppStore((s) => s.messages);
  const streamState = useAppStore((s) => s.streamState);
  const systemPanelOpen = useAppStore((s) => s.systemPanelOpen);
  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);
  const navigate = useNavigate();
  const listRef = useRef<HTMLDivElement>(null);
  const shouldAutoScroll = useRef(true);

  // Check if any data sources are connected
  const [hasConnectedSources, setHasConnectedSources] = useState<boolean | null>(null);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  useEffect(() => {
    listConnectors()
      .then((list) => setHasConnectedSources(list.some((c) => c.connected)))
      .catch(() => setHasConnectedSources(null));
  }, []);

  useEffect(() => {
    if (shouldAutoScroll.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, streamState.content]);

  const handleScroll = () => {
    if (!listRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = listRef.current;
    shouldAutoScroll.current = scrollHeight - scrollTop - clientHeight < 100;
  };

  const isEmpty = messages.length === 0 && !streamState.isStreaming;

  const PanelIcon = systemPanelOpen ? PanelRightClose : PanelRightOpen;
  const usePrompt = (prompt: string) => {
    window.dispatchEvent(new CustomEvent('grandpa:set-draft', { detail: prompt }));
  };

  return (
    <div className="flex flex-col h-full">
      {/* Toggle bar */}
      <div className="flex items-center justify-end px-4 pt-3 pb-1 shrink-0">
        <button
          onClick={toggleSystemPanel}
          className="p-2 rounded-xl transition-colors cursor-pointer"
          style={{
            color: systemPanelOpen ? 'var(--color-accent)' : 'var(--color-text-tertiary)',
            background: systemPanelOpen ? 'var(--color-accent-subtle)' : 'var(--color-bg-secondary)',
            border: '1px solid var(--color-border)',
          }}
          title={`${systemPanelOpen ? 'Hide' : 'Show'} system panel (${navigator.platform.includes('Mac') ? '⌘' : 'Ctrl'}+I)`}
        >
          <PanelIcon size={16} />
        </button>
      </div>

      {/* Data sources banner */}
      {hasConnectedSources === false && !bannerDismissed && (
        <div
          className="mx-4 mb-2 flex items-center gap-3 px-4 py-3 rounded-lg text-sm shrink-0"
          style={{
            background: 'var(--color-accent-subtle)',
            border: '1px solid var(--color-border)',
          }}
        >
          <Database size={16} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />
          <span style={{ color: 'var(--color-text-secondary)', flex: 1 }}>
            Connect your data sources (Gmail, iMessage, Slack, etc.) to get personalized answers.
          </span>
          <button
            onClick={() => navigate('/data-sources')}
            className="px-3 py-1 rounded text-xs font-medium cursor-pointer"
            style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)', border: 'none' }}
          >
            Connect
          </button>
          <button
            onClick={() => setBannerDismissed(true)}
            className="p-1 rounded cursor-pointer"
            style={{ color: 'var(--color-text-tertiary)', background: 'transparent', border: 'none' }}
          >
            <X size={14} />
          </button>
        </div>
      )}
      <div
        ref={listRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto"
      >
        {isEmpty ? (
          <div className="flex flex-col items-center justify-center min-h-full px-4 py-10">
            <div
              className="w-16 h-16 rounded-2xl flex items-center justify-center mb-5 relative"
              style={{
                background: 'linear-gradient(135deg, var(--color-accent-subtle), var(--color-accent-amber-subtle))',
                color: 'var(--color-accent-amber)',
                boxShadow: '0 22px 60px -30px var(--color-accent)',
                border: '1px solid var(--color-border)',
              }}
            >
              <span className="hud-reticle absolute inset-auto" />
              <Sparkles size={26} />
            </div>
            <h2 className="text-2xl font-semibold mb-2 text-center" style={{ color: 'var(--color-text)' }}>
              {getGreeting()}. I&apos;m Grandpa.
            </h2>
            <p className="text-sm text-center max-w-xl mb-7 leading-6" style={{ color: 'var(--color-text-secondary)' }}>
              Ask a question, draft a message, search your connected context, or think through a problem with a local assistant.
            </p>

            {/* Quick action hints */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-2xl">
              <PromptCard
                icon={Brain}
                title="Think through a plan"
                detail="Break down a task or decision"
                prompt="Help me think through a practical plan for today. Ask me one question at a time if you need context."
                onUse={usePrompt}
              />
              <PromptCard
                icon={Zap}
                title="Draft something"
                detail="Write, rewrite, summarize"
                prompt="Draft a clear, friendly message for me. Start by asking who it is for and what tone I want."
                onUse={usePrompt}
              />
              <button
                onClick={() => navigate('/data-sources')}
                className="flex items-center gap-3 px-4 py-3 rounded-xl text-xs cursor-pointer transition-colors text-left"
                style={{
                  background: 'var(--color-bg-secondary)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text-secondary)',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-accent)')}
                onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--color-border)')}
              >
                <Database size={14} style={{ color: 'var(--color-accent)' }} />
                <span>
                  <span className="block font-medium" style={{ color: 'var(--color-text)' }}>
                    Connect context
                  </span>
                  <span style={{ color: 'var(--color-text-tertiary)' }}>Use personal sources in answers</span>
                </span>
              </button>
              <button
                onClick={() => { navigate('/data-sources'); setTimeout(() => window.dispatchEvent(new CustomEvent('switch-tab', { detail: 'messaging' })), 100); }}
                className="flex items-center gap-3 px-4 py-3 rounded-xl text-xs cursor-pointer transition-colors text-left"
                style={{
                  background: 'var(--color-bg-secondary)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text-secondary)',
                }}
                onMouseEnter={(e) => (e.currentTarget.style.borderColor = 'var(--color-accent)')}
                onMouseLeave={(e) => (e.currentTarget.style.borderColor = 'var(--color-border)')}
              >
                <MessageSquare size={14} style={{ color: 'var(--color-accent)' }} />
                <span>
                  <span className="block font-medium" style={{ color: 'var(--color-text)' }}>
                    Set up messaging
                  </span>
                  <span style={{ color: 'var(--color-text-tertiary)' }}>Bring channels into Grandpa</span>
                </span>
              </button>
            </div>
          </div>
        ) : (
          <div className="max-w-[var(--chat-max-width)] mx-auto px-4 pb-8 pt-4">
            {messages.map((msg, i) => {
              const isLastAssistant =
                i === messages.length - 1 && msg.role === 'assistant';
              return (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  isLive={isLastAssistant && streamState.isStreaming}
                />
              );
            })}
            {(() => {
              if (!streamState.isStreaming || streamState.content !== '') return null;
              // For research messages the ResearchTimeline handles its own
              // pre-content loading state — suppress the generic dots.
              const last = messages[messages.length - 1];
              if (last?.role === 'assistant' && last.isResearch) return null;
              return (
                <div className="flex justify-start mb-4">
                  <StreamingDots phase={streamState.phase} />
                </div>
              );
            })()}
          </div>
        )}
      </div>
      <InputArea />
    </div>
  );
}

function PromptCard({
  icon: Icon,
  title,
  detail,
  prompt,
  onUse,
}: {
  icon: typeof Brain;
  title: string;
  detail: string;
  prompt: string;
  onUse: (prompt: string) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => onUse(prompt)}
      className="flex items-center gap-3 px-4 py-3 rounded-xl text-xs text-left cursor-pointer transition-all"
      style={{
        background: 'color-mix(in srgb, var(--color-bg-secondary) 74%, transparent)',
        border: '1px solid color-mix(in srgb, var(--color-accent) 16%, var(--color-border))',
        color: 'var(--color-text-secondary)',
        boxShadow: 'inset 0 1px 0 color-mix(in srgb, var(--color-text) 6%, transparent)',
        backdropFilter: 'blur(14px)',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = 'color-mix(in srgb, var(--color-accent) 48%, var(--color-border))';
        e.currentTarget.style.transform = 'translateY(-1px)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = 'color-mix(in srgb, var(--color-accent) 16%, var(--color-border))';
        e.currentTarget.style.transform = 'translateY(0)';
      }}
    >
      <Icon size={14} style={{ color: 'var(--color-accent-amber)' }} />
      <span>
        <span className="block font-medium" style={{ color: 'var(--color-text)' }}>
          {title}
        </span>
        <span style={{ color: 'var(--color-text-tertiary)' }}>{detail}</span>
      </span>
    </button>
  );
}
