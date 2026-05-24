import { useState, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import rehypeHighlight from 'rehype-highlight';
import rehypeKatex from 'rehype-katex';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import 'katex/dist/katex.min.css';
import { Copy, Check, ShieldCheck, X } from 'lucide-react';
import { AudioPlayer } from './AudioPlayer';
import { ToolCallCard } from './ToolCallCard';
import { ResearchTimeline } from './ResearchTimeline';
import { rehypeCitations } from '../../lib/rehype-citations';
import { XRayFooter } from './XRayFooter';
import type { ChatMessage } from '../../types';
import { approveLocalAction, denyLocalAction } from '../../lib/api';
import { useAppStore } from '../../lib/store';

function stripThinkTags(text: string): string {
  let cleaned = text.replace(/<think>[\s\S]*?<\/think>\s*/gi, '');
  cleaned = cleaned.replace(/^[\s\S]*?<\/think>\s*/i, '');
  return cleaned.trim();
}

interface Props {
  message: ChatMessage;
  isLive?: boolean;
}

function getTextContent(node: any): string {
  if (typeof node === 'string' || typeof node === 'number') {
    return String(node);
  }
  if (Array.isArray(node)) {
    return node.map(getTextContent).join('');
  }
  if (node?.props?.children) {
    return getTextContent(node.props.children);
  }
  return '';
}

function CodeBlockPre({ children, ...props }: any) {
  const [copied, setCopied] = useState(false);
  const codeElement = Array.isArray(children) ? children[0] : children;
  const className = codeElement?.props?.className || '';
  const match = /language-([\w-]+)/.exec(className);
  const lang = match ? match[1] : '';
  const code = getTextContent(codeElement?.props?.children).replace(/\n$/, '');

  const handleCopy = () => {
    navigator.clipboard.writeText(code);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      className="code-block-wrapper relative my-3"
      style={{ borderRadius: 'var(--radius-md)', overflow: 'hidden' }}
    >
      <div
        className="flex items-center justify-between px-4 py-1.5 text-xs"
        style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-tertiary)' }}
      >
        <span className="font-mono">{lang || 'code'}</span>
        <button
          onClick={handleCopy}
          className="flex items-center gap-1 px-2 py-0.5 rounded transition-colors cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
          onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--color-text-secondary)')}
          onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--color-text-tertiary)')}
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre {...props} style={{ margin: 0, borderRadius: 0 }}>
        {children}
      </pre>
    </div>
  );
}

function CopyMessageButton({ content }: { content: string }) {
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className="p-1 rounded opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer"
      style={{ color: 'var(--color-text-tertiary)' }}
      title="Copy message"
    >
      {copied ? <Check size={14} /> : <Copy size={14} />}
    </button>
  );
}

function LocalActionConfirmationCard({ content }: { content: string }) {
  const [busy, setBusy] = useState<'approve' | 'deny' | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const activeId = useAppStore((s) => s.activeId);
  const addMessage = useAppStore((s) => s.addMessage);
  const match = content.match(/Action ID:\s*([a-f0-9]{32})/i);
  const actionMatch = content.match(/Action:\s*(.+)/i);
  const actionId = match?.[1];
  if (!actionId) return null;

  const finish = async (decision: 'approve' | 'deny') => {
    if (!activeId || busy || done) return;
    setBusy(decision);
    try {
      const result = decision === 'approve'
        ? await approveLocalAction(actionId)
        : await denyLocalAction(actionId);
      addMessage(activeId, {
        id: Date.now().toString(36) + Math.random().toString(36).slice(2, 8),
        role: 'assistant',
        content: result.message,
        timestamp: Date.now(),
      });
      setDone(decision === 'approve' ? 'Approved' : 'Denied');
    } catch (err) {
      addMessage(activeId, {
        id: Date.now().toString(36) + Math.random().toString(36).slice(2, 8),
        role: 'assistant',
        content: err instanceof Error ? err.message : 'Could not update local action.',
        timestamp: Date.now(),
      });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      className="mt-3 rounded-2xl p-4"
      style={{
        background: 'color-mix(in srgb, var(--color-accent) 10%, var(--color-bg-secondary))',
        border: '1px solid color-mix(in srgb, var(--color-accent) 34%, var(--color-border))',
        boxShadow: '0 18px 44px -32px var(--color-accent)',
      }}
    >
      <div className="flex items-start gap-3">
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0"
          style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent)' }}
        >
          <ShieldCheck size={18} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-sm font-medium mb-1" style={{ color: 'var(--color-text)' }}>
            Confirm local action
          </div>
          <div className="text-xs mb-3" style={{ color: 'var(--color-text-secondary)' }}>
            {actionMatch?.[1] || 'Grandpa wants to run a medium-risk local action.'}
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => finish('approve')}
              disabled={!!busy || !!done}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium"
              style={{
                background: 'var(--color-accent)',
                color: 'var(--color-on-accent)',
                opacity: busy || done ? 0.6 : 1,
              }}
            >
              <ShieldCheck size={14} />
              {busy === 'approve' ? 'Approving...' : 'Approve'}
            </button>
            <button
              onClick={() => finish('deny')}
              disabled={!!busy || !!done}
              className="inline-flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-medium"
              style={{
                background: 'var(--color-bg-tertiary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-secondary)',
                opacity: busy || done ? 0.6 : 1,
              }}
            >
              <X size={14} />
              {busy === 'deny' ? 'Denying...' : 'Deny'}
            </button>
            {done && (
              <span className="text-xs self-center" style={{ color: 'var(--color-text-tertiary)' }}>
                {done}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

export function MessageBubble({ message, isLive = false }: Props) {
  const isUser = message.role === 'user';

  if (isUser) {
    return (
      <div className="flex justify-end mb-5">
        <div
          className="max-w-[85%] px-4 py-3 text-sm leading-relaxed"
          style={{
            background: 'linear-gradient(135deg, color-mix(in srgb, var(--color-user-bubble) 92%, var(--color-bg)), color-mix(in srgb, var(--color-accent) 72%, var(--color-accent-amber)))',
            color: 'var(--color-user-bubble-text)',
            border: '1px solid color-mix(in srgb, var(--color-text) 12%, transparent)',
            borderRadius: 'var(--radius-xl) var(--radius-xl) var(--radius-sm) var(--radius-xl)',
            boxShadow: '0 14px 34px -24px var(--color-accent), inset 0 1px 0 rgba(255,255,255,0.12)',
            backdropFilter: 'blur(14px)',
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-word',
          }}
        >
          {message.content}
        </div>
      </div>
    );
  }

  const cleanContent = useMemo(() => stripThinkTags(message.content), [message.content]);

  // Build a ref→source lookup once per render. Memoized so the rehype plugin
  // identity stays stable until the source list actually changes.
  const sourcesMap = useMemo(() => {
    const m = new Map<number, NonNullable<ChatMessage['researchSources']>[number]>();
    for (const s of message.researchSources ?? []) {
      if (typeof s.ref === 'number') m.set(s.ref, s);
    }
    return m;
  }, [message.researchSources]);

  const rehypePlugins = useMemo(() => {
    const base: any[] = [[rehypeHighlight, { detect: true }], rehypeKatex];
    if (sourcesMap.size > 0) base.push([rehypeCitations, { sources: sourcesMap }]);
    return base;
  }, [sourcesMap]);

  return (
    <div className="group mb-6">
      {/* Deep Research timeline (steps + status) */}
      {(message.isResearch || (message.researchTraces && message.researchTraces.length > 0)) && (
        <ResearchTimeline
          traces={message.researchTraces ?? []}
          isLive={isLive}
          hasContent={cleanContent.length > 0}
        />
      )}

      {/* Tool calls */}
      {message.toolCalls && message.toolCalls.length > 0 && (
        <div className="mb-3 flex flex-col gap-2">
          {message.toolCalls.map((tc) => (
            <ToolCallCard key={tc.id} toolCall={tc} />
          ))}
        </div>
      )}

      {/* Audio player (e.g. morning digest) */}
      {message.audio?.url && <AudioPlayer src={message.audio.url} />}

      {/* Assistant message */}
      {cleanContent && (
        <div
          className="rounded-2xl px-4 py-3"
          style={{
            background: 'color-mix(in srgb, var(--color-bg-secondary) 46%, transparent)',
            border: '1px solid var(--color-border-subtle)',
            boxShadow: 'inset 0 1px 0 color-mix(in srgb, var(--color-text) 4%, transparent)',
            backdropFilter: 'blur(10px)',
          }}
        >
          <div className="prose max-w-none">
            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkMath]}
              rehypePlugins={rehypePlugins}
              components={{
                pre: CodeBlockPre,
              }}
            >
              {cleanContent}
            </ReactMarkdown>
          </div>
          <LocalActionConfirmationCard content={cleanContent} />
        </div>
      )}

      {/* Footer: copy + x-ray */}
      <div className="flex items-center gap-2 mt-1.5">
        <CopyMessageButton content={cleanContent} />
      </div>
      <XRayFooter
        usage={message.usage}
        telemetry={message.telemetry}
        isResearch={message.isResearch}
      />
    </div>
  );
}
