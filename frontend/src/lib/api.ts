import type { ModelInfo, RuntimeUsageData, ServerInfo } from '../types';

declare global {
  interface Window {
    __TAURI_INTERNALS__?: unknown;
  }
}

export const isTauri = () => typeof window !== 'undefined' && !!window.__TAURI_INTERNALS__;

// Cached API base URL fetched from the Tauri backend at startup.
// This avoids hardcoding the port — the Rust backend is the single
// source of truth for GRANDPA_PORT.
let _tauriApiBase: string | null = null;

/** Pre-fetch the API base URL from the Tauri backend (call once at init). */
export async function initApiBase(): Promise<void> {
  if (!isTauri()) return;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    _tauriApiBase = await invoke<string>('get_api_base');
  } catch {
    // Command may not exist on older builds; fall through to default.
  }
}

const DESKTOP_API_FALLBACK = 'http://127.0.0.1:8000';

const getSettingsApiUrl = (): string => {
  try {
    const raw = localStorage.getItem('Grandpa-settings');
    if (raw) {
      const parsed = JSON.parse(raw);
      if (parsed.apiUrl) return parsed.apiUrl.replace(/\/+$/, '');
    }
  } catch {}
  return '';
};

export const getBase = (): string => {
  const settingsUrl = getSettingsApiUrl();
  if (settingsUrl) return settingsUrl;
  if (import.meta.env.VITE_API_URL) return import.meta.env.VITE_API_URL;
  if (isTauri()) return _tauriApiBase || DESKTOP_API_FALLBACK;
  return '';
};

async function tauriInvoke<T>(command: string, args: Record<string, unknown> = {}): Promise<T> {
  const { invoke } = await import('@tauri-apps/api/core');
  const apiUrl = getBase();
  return invoke<T>(command, { apiUrl, ...args });
}

// ---------------------------------------------------------------------------
// Setup status (desktop only)
// ---------------------------------------------------------------------------

export interface SetupStatus {
  phase: string;
  detail: string;
  ollama_ready: boolean;
  server_ready: boolean;
  model_ready: boolean;
  error: string | null;
}

export async function getSetupStatus(): Promise<SetupStatus | null> {
  if (!isTauri()) return null;
  try {
    const { invoke } = await import('@tauri-apps/api/core');
    return await invoke<SetupStatus>('get_setup_status');
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export async function fetchModels(): Promise<ModelInfo[]> {
  if (isTauri()) {
    try {
      const result = await tauriInvoke<{ data?: ModelInfo[] }>('fetch_models');
      return result?.data || [];
    } catch {
      // Fall through to fetch
    }
  }
  const res = await fetch(`${getBase()}/v1/models`);
  if (!res.ok) throw new Error(`Failed to fetch models: ${res.status}`);
  const data = await res.json();
  return data.data || [];
}

export async function fetchRecommendedModel(): Promise<{ model: string; reason: string }> {
  const res = await fetch(`${getBase()}/v1/recommended-model`);
  if (!res.ok) return { model: '', reason: 'Failed to fetch' };
  return res.json();
}

export async function pullModel(modelName: string): Promise<void> {
  // In Tauri, go through the Rust backend directly (avoids CORS / timeout
  // issues with long model downloads via fetch).
  if (isTauri()) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('pull_ollama_model', { modelName });
      return;
    } catch (e: any) {
      throw new Error(e?.message || e || 'Download failed');
    }
  }
  const res = await fetch(`${getBase()}/v1/models/pull`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ model: modelName }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`Failed to pull model: ${detail}`);
  }
}

export async function deleteModel(modelName: string): Promise<void> {
  if (isTauri()) {
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      await invoke('delete_ollama_model', { modelName });
      return;
    } catch (e: any) {
      throw new Error(e?.message || e || 'Delete failed');
    }
  }
  const res = await fetch(`${getBase()}/v1/models/${encodeURIComponent(modelName)}`, {
    method: 'DELETE',
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => res.statusText);
    throw new Error(`Failed to delete model: ${detail}`);
  }
}

const _CLOUD_PREFIXES = ['gpt-', 'o1-', 'o3-', 'o4-', 'claude-', 'gemini-', 'openrouter/'];

export async function preloadModel(modelName: string): Promise<void> {
  // Cloud models don't need Ollama preloading
  if (_CLOUD_PREFIXES.some(p => modelName.startsWith(p))) {
    return;
  }
  // Trigger Ollama to load the model into memory (empty prompt, no generation).
  const ollamaUrl = 'http://127.0.0.1:11434';
  try {
    const res = await fetch(`${ollamaUrl}/api/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: modelName, prompt: '', keep_alive: '5m' }),
      signal: AbortSignal.timeout(120_000),
    });
    if (!res.ok) throw new Error(`Preload failed: ${res.status}`);
  } catch (e: any) {
    if (e.name === 'TimeoutError') throw new Error('Model load timed out (120s)');
    throw e;
  }
}

export async function fetchRuntimeUsage(): Promise<RuntimeUsageData> {
  const res = await fetch(`${getBase()}/v1/savings`);
  if (!res.ok) throw new Error(`Failed to fetch runtime usage: ${res.status}`);
  return res.json();
}

export async function fetchServerInfo(): Promise<ServerInfo> {
  const res = await fetch(`${getBase()}/v1/info`);
  if (!res.ok) throw new Error(`Failed to fetch server info: ${res.status}`);
  return res.json();
}

export async function checkHealth(): Promise<boolean> {
  if (isTauri()) {
    try {
      await tauriInvoke('check_health', { apiUrl: getBase() });
      return true;
    } catch {
      return false;
    }
  }
  // In the browser, hit /health relative to the page origin so the request
  // flows through whatever path is already serving the SPA — the Vite
  // proxy in dev, FastAPI's static mount in prod. This avoids the
  // false-negative "Cannot reach backend" banner when getBase() points at
  // an absolute URL the browser can't reach directly.
  //
  // If /health itself fails for any reason (proxy quirk, stale service
  // worker, etc.) fall back to an arbitrary API endpoint we know the rest
  // of the app polls successfully. If THAT also fails we genuinely can't
  // reach the backend.
  const probe = async (url: string): Promise<boolean> => {
    try {
      const res = await fetch(url, { cache: 'no-store' });
      return res.ok;
    } catch {
      return false;
    }
  };
  if (await probe('/health')) return true;
  return probe('/v1/connectors');
}

export async function fetchEnergy(): Promise<unknown> {
  if (isTauri()) {
    try {
      return await tauriInvoke('fetch_energy', { apiUrl: getBase() });
    } catch {}
  }
  const res = await fetch(`${getBase()}/v1/telemetry/energy`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchTelemetry(): Promise<unknown> {
  if (isTauri()) {
    try {
      return await tauriInvoke('fetch_telemetry', { apiUrl: getBase() });
    } catch {}
  }
  const res = await fetch(`${getBase()}/v1/telemetry/stats`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchTraces(limit: number = 50): Promise<unknown> {
  if (isTauri()) {
    try {
      return await tauriInvoke('fetch_traces', { apiUrl: getBase(), limit });
    } catch {}
  }
  const res = await fetch(`${getBase()}/v1/traces?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Speech
// ---------------------------------------------------------------------------

export interface TranscriptionResult {
  text: string;
  language: string | null;
  confidence: number | null;
  duration_seconds: number;
}

export interface SpeechHealth {
  available: boolean;
  backend?: string;
  reason?: string;
}

export async function transcribeAudio(audioBlob: Blob, filename = 'recording.webm'): Promise<TranscriptionResult> {
  if (isTauri()) {
    try {
      const buffer = await audioBlob.arrayBuffer();
      return await tauriInvoke<TranscriptionResult>('transcribe_audio', {
        audioData: Array.from(new Uint8Array(buffer)),
        filename,
      });
    } catch {
      // Fall through to fetch
    }
  }
  const formData = new FormData();
  formData.append('file', audioBlob, filename);
  const res = await fetch(`${getBase()}/v1/speech/transcribe`, {
    method: 'POST',
    body: formData,
  });
  if (!res.ok) throw new Error(`Transcription failed: ${res.status}`);
  return res.json();
}

export async function fetchSpeechHealth(): Promise<SpeechHealth> {
  if (isTauri()) {
    try {
      return await tauriInvoke<SpeechHealth>('speech_health');
    } catch {
      return { available: false };
    }
  }
  const res = await fetch(`${getBase()}/v1/speech/health`);
  if (!res.ok) return { available: false };
  return res.json();
}

// ---------------------------------------------------------------------------
// Agent Manager
// ---------------------------------------------------------------------------

export interface ManagedAgent {
  id: string;
  name: string;
  agent_type: string;
  config: Record<string, unknown>;
  status: 'idle' | 'running' | 'paused' | 'error' | 'archived' | 'needs_attention' | 'budget_exceeded' | 'stalled';
  summary_memory: string;
  created_at: number;
  updated_at: number;
  // Runtime stats
  total_runs?: number;
  total_cost?: number;
  total_tokens?: number;
  input_tokens?: number;
  output_tokens?: number;
  last_run_at?: number | null;
  // Schedule
  schedule_type?: string;
  schedule_value?: string;
  // Budget
  budget?: number;
  // Learning
  learning_enabled?: boolean;
  // Live progress
  current_activity?: string;
}

export interface AgentTask {
  id: string;
  agent_id: string;
  description: string;
  status: 'pending' | 'active' | 'completed' | 'failed';
  progress: Record<string, unknown>;
  findings: unknown[];
  created_at: number;
}

export interface ChannelBinding {
  id: string;
  agent_id: string;
  channel_type: string;
  config: Record<string, unknown>;
  session_id: string;
  routing_mode: string;
}

export interface AgentTemplate {
  id: string;
  name: string;
  description: string;
  source: 'built-in' | 'user';
  agent_type: string;
  [key: string]: unknown;
}

export interface PersistedToolCall {
  tool: string;
  arguments: string;
  result?: string;
  success?: boolean;
  latency?: number;
}

export interface AgentMessage {
  id: string;
  agent_id: string;
  direction: 'user_to_agent' | 'agent_to_user';
  content: string;
  mode: 'immediate' | 'queued';
  status: 'pending' | 'delivered' | 'responded';
  created_at: number;
  tool_calls?: PersistedToolCall[] | null;
}

export async function fetchManagedAgents(): Promise<ManagedAgent[]> {
  const res = await fetch(`${getBase()}/v1/managed-agents`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.agents || [];
}

export async function fetchManagedAgent(agentId: string): Promise<ManagedAgent> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function createManagedAgent(body: {
  name: string;
  agent_type?: string;
  template_id?: string;
  config?: Record<string, unknown>;
}): Promise<ManagedAgent> {
  const res = await fetch(`${getBase()}/v1/managed-agents`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function updateManagedAgent(
  agentId: string,
  body: Partial<{ name: string; agent_type: string; config: Record<string, unknown> }>,
): Promise<ManagedAgent> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function deleteManagedAgent(agentId: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function pauseManagedAgent(agentId: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/pause`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function resumeManagedAgent(agentId: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/resume`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function fetchAgentTasks(agentId: string): Promise<AgentTask[]> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/tasks`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.tasks || [];
}

export async function createAgentTask(agentId: string, description: string): Promise<AgentTask> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ description }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchAgentChannels(agentId: string): Promise<ChannelBinding[]> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/channels`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.bindings || [];
}

export async function bindAgentChannel(
  agentId: string,
  channelType: string,
  config?: Record<string, unknown>,
): Promise<ChannelBinding> {
  const res = await fetch(
    `${getBase()}/v1/managed-agents/${agentId}/channels`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        channel_type: channelType,
        config: config || {},
        routing_mode: 'dedicated',
      }),
    },
  );
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function unbindAgentChannel(
  agentId: string,
  bindingId: string,
): Promise<void> {
  const res = await fetch(
    `${getBase()}/v1/managed-agents/${agentId}/channels/${bindingId}`,
    { method: 'DELETE' },
  );
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

// -- SendBlue auto-setup helpers ------------------------------------------

export async function sendblueVerify(
  apiKeyId: string,
  apiSecretKey: string,
): Promise<{ valid: boolean; numbers: string[]; raw: unknown }> {
  const res = await fetch(`${getBase()}/v1/channels/sendblue/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ api_key_id: apiKeyId, api_secret_key: apiSecretKey }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Verification failed: ${res.status}`);
  }
  return res.json();
}

export async function sendblueRegisterWebhook(
  apiKeyId: string,
  apiSecretKey: string,
  webhookUrl: string,
): Promise<{ registered: boolean; status: number }> {
  const res = await fetch(`${getBase()}/v1/channels/sendblue/register-webhook`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      api_key_id: apiKeyId,
      api_secret_key: apiSecretKey,
      webhook_url: webhookUrl,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Webhook registration failed: ${res.status}`);
  }
  return res.json();
}

export async function sendblueTest(
  apiKeyId: string,
  apiSecretKey: string,
  fromNumber: string,
  toNumber: string,
): Promise<{ sent: boolean; status: number }> {
  const res = await fetch(`${getBase()}/v1/channels/sendblue/test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      api_key_id: apiKeyId,
      api_secret_key: apiSecretKey,
      from_number: fromNumber,
      to_number: toNumber,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `Test message failed: ${res.status}`);
  }
  return res.json();
}

export async function sendblueHealth(): Promise<{ channel_connected: boolean; bridge_wired: boolean; ready: boolean }> {
  const res = await fetch(`${getBase()}/v1/channels/sendblue/health`);
  if (!res.ok) return { channel_connected: false, bridge_wired: false, ready: false };
  return res.json();
}

export async function fetchTemplates(): Promise<AgentTemplate[]> {
  const res = await fetch(`${getBase()}/v1/templates`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.templates || [];
}

export async function runManagedAgent(agentId: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/run`, { method: 'POST' });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Failed: ${res.status}`);
  }
}

export async function recoverManagedAgent(agentId: string): Promise<{ recovered: boolean; checkpoint: unknown }> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/recover`, { method: 'POST' });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(body.detail || `Failed: ${res.status}`);
  }
  return res.json();
}

export async function fetchAgentState(agentId: string): Promise<{
  agent: ManagedAgent;
  tasks: AgentTask[];
  channels: ChannelBinding[];
  messages: AgentMessage[];
  checkpoint: unknown;
}> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/state`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export interface AgentToolCallStart {
  tool: string;
  arguments: string;
}

export interface AgentToolCallEnd {
  tool: string;
  success: boolean;
  latency: number;
  result?: string;
}

export async function sendAgentMessage(
  agentId: string,
  content: string,
  mode: 'immediate' | 'queued' = 'queued',
  callbacks?: {
    onProgress?: (label: string) => void;
    onContentDelta?: (delta: string, fullContent: string) => void;
    onToolCallStart?: (info: AgentToolCallStart) => void;
    onToolCallEnd?: (info: AgentToolCallEnd) => void;
    onDone?: (fullContent: string, usage?: Record<string, number>, telemetry?: Record<string, unknown>) => void;
  },
): Promise<AgentMessage> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, mode, stream: true }),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);

  // If streaming, consume the SSE response so the agent runs
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('text/event-stream') && res.body) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let fullContent = '';
    let buffer = '';
    let lastUsage: Record<string, number> | undefined;
    let lastTelemetry: Record<string, unknown> | undefined;
    let currentEvent: string | undefined;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim();
            continue;
          }
          if (!line.startsWith('data: ')) {
            if (line.trim() === '') currentEvent = undefined;
            continue;
          }
          const data = line.slice(6);
          if (data === '[DONE]') {
            currentEvent = undefined;
            continue;
          }
          const evName = currentEvent;
          currentEvent = undefined;

          if (evName === 'tool_call_start') {
            try {
              const parsed = JSON.parse(data);
              callbacks?.onToolCallStart?.({
                tool: parsed.tool,
                arguments: parsed.arguments ?? '',
              });
            } catch {
              /* skip */
            }
            continue;
          }
          if (evName === 'tool_call_end') {
            try {
              const parsed = JSON.parse(data);
              callbacks?.onToolCallEnd?.({
                tool: parsed.tool,
                success: !!parsed.success,
                latency: typeof parsed.latency === 'number' ? parsed.latency : 0,
                result: parsed.result,
              });
            } catch {
              /* skip */
            }
            continue;
          }

          try {
            const chunk = JSON.parse(data);
            // Deep-research branch still uses tool_progress in a data chunk
            const toolProgress = chunk.choices?.[0]?.tool_progress;
            if (toolProgress) {
              callbacks?.onProgress?.(toolProgress);
            }
            const delta = chunk.choices?.[0]?.delta?.content || '';
            if (delta) {
              fullContent += delta;
              callbacks?.onContentDelta?.(delta, fullContent);
            }
            if (chunk.usage) lastUsage = chunk.usage;
            if (chunk.telemetry) lastTelemetry = chunk.telemetry;
          } catch {
            /* skip malformed chunks */
          }
        }
      }
    } catch { /* stream ended */ }

    callbacks?.onDone?.(fullContent, lastUsage, lastTelemetry);

    return {
      id: '',
      agent_id: agentId,
      direction: 'agent_to_user',
      content: fullContent,
      mode,
      status: 'delivered',
      created_at: Date.now() / 1000,
    };
  }

  return res.json();
}

export async function fetchAgentMessages(agentId: string): Promise<AgentMessage[]> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/messages`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.messages || [];
}

export async function fetchErrorAgents(): Promise<ManagedAgent[]> {
  const res = await fetch(`${getBase()}/v1/agents/errors`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.agents || [];
}

// ---------------------------------------------------------------------------
// Agent Learning + Traces
// ---------------------------------------------------------------------------

export interface LearningLogEntry {
  id: string;
  agent_id: string;
  event_type: string;
  description: string;
  data: Record<string, unknown>;
  created_at: number;
}

export interface AgentTrace {
  id: string;
  outcome: string;
  duration: number;
  started_at: number;
  steps: number;
  error_message?: string;
  metadata?: Record<string, unknown>;
}

export interface ToolInfo {
  name: string;
  description: string;
  category: string;
  source: 'tool' | 'channel';
  requires_credentials: boolean;
  credential_keys: string[];
  configured: boolean;
}

export async function fetchAvailableTools(): Promise<ToolInfo[]> {
  const res = await fetch(`${getBase()}/v1/tools`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.tools || [];
}

export async function saveToolCredentials(
  toolName: string,
  credentials: Record<string, string>,
): Promise<void> {
  const res = await fetch(`${getBase()}/v1/tools/${toolName}/credentials`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(credentials),
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export interface AgentTraceDetail {
  id: string;
  agent: string;
  outcome: string;
  duration: number;
  started_at: number;
  steps: Array<{
    step_type: string;
    input: unknown;
    output: string;
    duration: number;
    metadata: Record<string, unknown>;
  }>;
}

export async function fetchLearningLog(agentId: string): Promise<LearningLogEntry[]> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/learning`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.learning_log || [];
}

export async function triggerLearning(agentId: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/learning/run`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function fetchAgentTraces(agentId: string, limit = 20): Promise<AgentTrace[]> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/traces?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.traces || [];
}

export async function fetchAgentTrace(agentId: string, traceId: string): Promise<AgentTraceDetail> {
  const res = await fetch(`${getBase()}/v1/managed-agents/${agentId}/traces/${traceId}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Memory
// ---------------------------------------------------------------------------

export interface MemorySearchResult {
  content: string;
  score: number;
  metadata: Record<string, unknown>;
}

export interface MemoryStats {
  entries: number;
  backend: string;
  [key: string]: unknown;
}

export interface MemoryConfig {
  backend: string;
  context_from_memory: boolean;
  context_top_k: number;
  context_min_score: number;
  context_max_tokens: number;
}

export interface PersonalMemoryItem {
  id: number;
  created_at: number;
  updated_at: number;
  category: string;
  key: string;
  value: string;
  source: string;
  score?: number;
  relevance_score?: number;
  match_type?: string;
  embedding_model?: string;
}

export interface PersonalActivityItem {
  id: number;
  created_at: number;
  category: string;
  action: string;
  target: string | null;
  detail: string | null;
  status: string;
}

export interface PersonalMemorySummary {
  memories: PersonalMemoryItem[];
  recent_activity: PersonalActivityItem[];
  categories: string[];
  semantic: {
    enabled: boolean;
    backend: string;
    embedding_model: string;
    dimensions: number;
    memories: number;
    embeddings: number;
    local_only: boolean;
  };
  storage: {
    backend: string;
    path: string;
    local_only: boolean;
  };
}

export interface PersonalMemorySearchResponse {
  query: string;
  category: string;
  results: PersonalMemoryItem[];
  uncertain: boolean;
  semantic: PersonalMemorySummary['semantic'];
}

export async function getMemoryStats(): Promise<MemoryStats> {
  const res = await fetch(`${getBase()}/v1/memory/stats`);
  if (!res.ok) throw new Error('Failed to fetch memory stats');
  return res.json();
}

export async function searchMemory(query: string, topK: number = 5): Promise<MemorySearchResult[]> {
  const res = await fetch(`${getBase()}/v1/memory/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, top_k: topK }),
  });
  if (!res.ok) throw new Error('Failed to search memory');
  const data = await res.json();
  return data.results;
}

export async function storeMemory(content: string, metadata?: Record<string, unknown>): Promise<void> {
  const res = await fetch(`${getBase()}/v1/memory/store`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content, metadata }),
  });
  if (!res.ok) throw new Error('Failed to store memory');
}

export async function indexMemoryPath(path: string): Promise<{ chunks_indexed: number }> {
  const res = await fetch(`${getBase()}/v1/memory/index`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) throw new Error('Failed to index path');
  return res.json();
}

export async function getMemoryConfig(): Promise<MemoryConfig> {
  const res = await fetch(`${getBase()}/v1/memory/config`);
  if (!res.ok) throw new Error('Failed to fetch memory config');
  return res.json();
}

export async function fetchPersonalMemory(): Promise<PersonalMemorySummary> {
  const res = await fetch(`${getBase()}/v1/personal-memory`);
  if (!res.ok) throw new Error('Failed to fetch personal memory');
  return res.json();
}

export async function searchPersonalMemory(
  query: string,
  category: string = 'all',
  limit: number = 8,
): Promise<PersonalMemorySearchResponse> {
  const res = await fetch(`${getBase()}/v1/personal-memory/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, category, limit }),
  });
  if (!res.ok) throw new Error('Failed to search personal memory');
  return res.json();
}

export async function clearPersonalMemory(): Promise<void> {
  const res = await fetch(`${getBase()}/v1/personal-memory`, { method: 'DELETE' });
  if (!res.ok) throw new Error('Failed to clear personal memory');
}

export interface LocalActionPending {
  id: string;
  status: string;
  kind: string;
  target: string;
  source_text: string;
  expires_at: number;
}

export interface LocalActionDecisionResponse {
  message: string;
  local_action?: {
    status: string;
    kind: string;
    target: string;
    tts_text?: string;
    permission?: string;
    pending_action?: LocalActionPending;
  };
}

export async function approveLocalAction(actionId: string): Promise<LocalActionDecisionResponse> {
  const res = await fetch(`${getBase()}/v1/local-actions/${encodeURIComponent(actionId)}/approve`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error('Failed to approve local action');
  return res.json();
}

export async function denyLocalAction(actionId: string): Promise<LocalActionDecisionResponse> {
  const res = await fetch(`${getBase()}/v1/local-actions/${encodeURIComponent(actionId)}/deny`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error('Failed to deny local action');
  return res.json();
}

export interface FileAssistantRecentItem {
  id: number;
  created_at: number;
  action: string;
  path: string;
  detail?: string | null;
}

export interface FileAssistantNote {
  path: string;
  name: string;
  type: string;
  size: number;
  size_label: string;
  modified: number;
  modified_label: string;
}

export interface FileAssistantSummary {
  recent_files: FileAssistantRecentItem[];
  notes: FileAssistantNote[];
  safe_roots: string[];
  storage: {
    backend: string;
    path: string;
    local_only: boolean;
  };
}

export interface FileAssistantSearchResponse {
  status: string;
  message: string;
}

export async function fetchFileAssistantSummary(): Promise<FileAssistantSummary> {
  const res = await fetch(`${getBase()}/v1/file-assistant`);
  if (!res.ok) throw new Error('Failed to fetch file assistant summary');
  return res.json();
}

export async function searchFileAssistant(query: string): Promise<FileAssistantSearchResponse> {
  const res = await fetch(`${getBase()}/v1/file-assistant/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query }),
  });
  if (!res.ok) throw new Error('Failed to search files');
  return res.json();
}

export interface RoutineItem {
  id: number;
  created_at: number;
  updated_at: number;
  name: string;
  schedule?: string | null;
  actions: string[];
  enabled: boolean;
  next_run_at?: number | null;
  next_run_label: string;
  last_run_at?: number | null;
  last_run_label: string;
  last_status?: string | null;
  last_message?: string | null;
}

export interface ReminderItem {
  id: number;
  created_at: number;
  updated_at: number;
  text: string;
  schedule: string;
  schedule_label: string;
  enabled: boolean;
  next_run_at?: number | null;
  next_run_label: string;
  last_triggered_at?: number | null;
  last_triggered_label: string;
  last_status?: string | null;
  last_message?: string | null;
}

export interface SchedulerNotification {
  id: number;
  created_at: number;
  kind: string;
  title: string;
  message: string;
  source_id?: number | null;
  read_at?: number | null;
}

export interface SchedulerDaemonStatus {
  running: boolean;
  poll_interval_seconds?: number | null;
  started_at?: number | null;
  last_tick_at?: number | null;
  last_result?: Record<string, unknown> | null;
  last_error?: string | null;
}

export interface RoutinesSummary {
  routines: RoutineItem[];
  reminders: ReminderItem[];
  notifications: SchedulerNotification[];
  daemon: SchedulerDaemonStatus;
  storage: {
    backend: string;
    path: string;
    local_only: boolean;
  };
}

export async function fetchRoutinesSummary(): Promise<RoutinesSummary> {
  const res = await fetch(`${getBase()}/v1/routines`);
  if (!res.ok) throw new Error('Failed to fetch routines');
  return res.json();
}

export interface BrowserContextSummary {
  context: {
    supported: boolean;
    browser: string | null;
    title: string | null;
    url: string | null;
    active_window_title: string | null;
    headings: string[];
    buttons: string[];
    links: Array<{ text: string; href: string }>;
    inputs: Array<{ label: string; type: string }>;
    visible_text: string;
    media: Array<{ kind: string; paused: boolean; muted: boolean; duration: number; current_time: number; label: string }>;
    forms: Array<{ label: string; fields: Array<{ label: string; type: string }>; submit_count: number }>;
    elements: Array<{ id: string; role: string; text: string; visible: boolean }>;
    session: Record<string, unknown>;
    message: string;
    local_only: boolean;
  };
  recent_activity: Array<{
    id: number;
    created_at: number;
    action: string;
    title?: string | null;
    url?: string | null;
    query?: string | null;
    status: string;
  }>;
  extension: {
    connected: boolean;
    snapshot_age_seconds?: number | null;
  };
}

export async function fetchBrowserContext(): Promise<BrowserContextSummary> {
  const res = await fetch(`${getBase()}/v1/browser/context`);
  if (!res.ok) throw new Error('Failed to fetch browser context');
  return res.json();
}

export async function fetchBrowserDiagnostics(): Promise<{
  status: string;
  message: string;
  risk_level: string;
  details: {
    extension_connected?: boolean;
    snapshot_age_seconds?: number | null;
    current_title?: string | null;
    current_url?: string | null;
    counts?: Record<string, number>;
    recent_activity?: BrowserContextSummary['recent_activity'];
    local_only?: boolean;
  };
  context: BrowserContextSummary['context'];
}> {
  const res = await fetch(`${getBase()}/v1/browser/diagnostics`);
  if (!res.ok) throw new Error('Failed to fetch browser diagnostics');
  return res.json();
}

export interface ScreenDiagnostics {
  platform: string;
  supported: boolean;
  active_window: {
    supported: boolean;
    title: string;
    app_name: string;
    message: string;
  };
  screenshot: {
    supported: boolean;
    backends: string[];
    last_path: string;
  };
  ocr: {
    available: boolean;
    text: string;
    confidence: number;
    backend: string;
    lines: string[];
    message: string;
  };
  visible_window_count: number;
  local_only: boolean;
}

export async function fetchScreenDiagnostics(): Promise<ScreenDiagnostics> {
  const res = await fetch(`${getBase()}/v1/screen/diagnostics`);
  if (!res.ok) throw new Error('Failed to fetch screen diagnostics');
  return res.json();
}

export interface AiDiagnostics {
  status: string;
  timestamp: number;
  engine: {
    id: string;
    healthy: boolean | null;
  };
  models: {
    total: number;
    local_chat: number;
    cloud: number;
    embedding: number;
    available: string[];
  };
  planner: {
    enabled: boolean;
    last_plan: {
      task_type: string;
      priority: number;
      complexity: {
        score: number;
        tier: string;
        suggested_max_tokens: number;
      };
      routing: {
        selected_model: string;
        engine_hint: string;
        confidence: number;
        reason: string;
        fallback_used: boolean;
      };
      steps: Array<{ name: string; purpose: string; tool_hint: string; risk: string; status: string }>;
      tool_order: string[];
      self_analysis: string;
    };
  };
  orchestration: {
    tool_routing: boolean;
    workflow_decomposition: boolean;
    semantic_memory: Record<string, unknown>;
    fallback_model: string;
  };
  local_only: boolean;
}

export async function fetchAiDiagnostics(query = ''): Promise<AiDiagnostics> {
  const suffix = query ? `?query=${encodeURIComponent(query)}` : '';
  const res = await fetch(`${getBase()}/v1/ai/diagnostics${suffix}`);
  if (!res.ok) throw new Error('Failed to fetch AI diagnostics');
  return res.json();
}

export interface CapabilityDiagnostics {
  fileIntelligence: {
    status: string;
    supported_types: string[];
    indexed_documents: number;
    type_counts: Record<string, number>;
    storage: { backend: string; path: string; local_only: boolean };
    safety: Record<string, unknown>;
  };
  office: {
    status: string;
    templates: string[];
    features: Record<string, boolean>;
    safety: Record<string, unknown>;
  };
  automation: {
    status: string;
    workflow_count: number;
    enabled_count: number;
    templates: Array<{ name: string; trigger: Record<string, unknown>; steps: Array<Record<string, unknown>> }>;
    history: Array<Record<string, unknown>>;
    features: Record<string, unknown>;
    safety: Record<string, unknown>;
    storage: { backend: string; path: string; local_only: boolean };
  };
  developer: {
    status: string;
    git: Record<string, unknown>;
    project: { checks?: Record<string, boolean>; missing?: string[]; repo?: string };
    docker: Record<string, unknown>;
    allowlist_prefixes: string[];
    templates: string[];
    safety: Record<string, unknown>;
  };
  security: {
    status: string;
    policies: Record<string, unknown>;
    health: { score: number; label: string };
    recent_events: Array<Record<string, unknown>>;
    suspicious_detection: boolean;
    encrypted_sensitive_memory: boolean;
    audit_export_requires_approval: boolean;
    storage: { backend: string; path: string; local_only: boolean };
  };
  mobile: {
    status: string;
    connected_devices: number;
    online_devices?: number;
    devices: Array<Record<string, unknown>>;
    notifications: Array<Record<string, unknown>>;
    features: Record<string, unknown>;
    safety: Record<string, unknown>;
  };
  communication: {
    status: string;
    services: Array<Record<string, unknown>>;
    unread_counts: Record<string, number>;
    pending_replies: Array<Record<string, unknown>>;
    workflow_suggestions: string[];
    safety: Record<string, unknown>;
  };
  realWorld: {
    status: string;
    active_workflows: Array<Record<string, unknown>>;
    features: Record<string, unknown>;
    safety: Record<string, unknown>;
  };
  iot: {
    status: string;
    devices: Array<Record<string, unknown>>;
    raspberry_pi: Record<string, unknown>;
    features: Record<string, unknown>;
    safety: Record<string, unknown>;
  };
  future: {
    status: string;
    avatar: Record<string, unknown>;
    overlay: Record<string, unknown>;
    connectors: Array<Record<string, unknown>>;
    hardware: Record<string, unknown>;
    safety: Record<string, unknown>;
  };
}

export interface MobileDeviceStatus {
  device_name?: string;
  battery?: number | null;
  charging?: boolean | null;
  connectivity?: string;
  platform?: string;
  app_version?: string;
}

export interface MobileDevice {
  device_id: string;
  created_at: number;
  name: string;
  paired: boolean;
  trusted: boolean;
  online: boolean;
  last_seen_at?: number | null;
  status: MobileDeviceStatus;
  permissions: Record<string, boolean>;
}

export interface MobileNotification {
  id: number;
  created_at: number;
  device_id: string;
  kind: string;
  app: string;
  title: string;
  summary: string;
  redacted: boolean | number;
}

export interface MobileEvent {
  id: number;
  created_at: number;
  device_id: string;
  event_type: string;
  summary: string;
  payload: Record<string, unknown>;
}

export interface MobileDiagnostics {
  status: string;
  architecture: Record<string, unknown>;
  devices: MobileDevice[];
  connected_devices: number;
  online_devices: number;
  notifications: MobileNotification[];
  commands: Array<Record<string, unknown>>;
  events: MobileEvent[];
  features: Record<string, unknown>;
  safety: Record<string, unknown>;
  storage: { backend: string; path: string; local_only: boolean };
}

export interface MobilePairingResponse {
  device_id: string;
  pairing_code: string;
  expires_in_seconds: number;
  local_only: boolean;
  websocket_path: string;
}

export async function fetchMobileDiagnostics(): Promise<MobileDiagnostics> {
  const res = await fetch(`${getBase()}/v1/mobile/diagnostics`);
  if (!res.ok) throw new Error('Failed to fetch mobile diagnostics');
  return res.json();
}

export async function createMobilePairing(name: string): Promise<MobilePairingResponse> {
  const res = await fetch(`${getBase()}/v1/mobile/pairing`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error('Failed to create mobile pairing code');
  return res.json();
}

export async function sendMobileRemoteCommand(command: string, deviceId = ''): Promise<Record<string, unknown>> {
  const res = await fetch(`${getBase()}/v1/mobile/remote-command`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ command, device_id: deviceId }),
  });
  if (!res.ok) throw new Error('Failed to send mobile command simulation');
  return res.json();
}

export async function fetchCapabilityDiagnostics(): Promise<CapabilityDiagnostics> {
  const [fileIntelligence, office, automation, developer, security, mobile, communication, realWorld, iot, future] = await Promise.all([
    fetch(`${getBase()}/v1/file-intelligence/diagnostics`).then((r) => {
      if (!r.ok) throw new Error('Failed to fetch file intelligence diagnostics');
      return r.json();
    }),
    fetch(`${getBase()}/v1/office/diagnostics`).then((r) => {
      if (!r.ok) throw new Error('Failed to fetch office diagnostics');
      return r.json();
    }),
    fetch(`${getBase()}/v1/automation/diagnostics`).then((r) => {
      if (!r.ok) throw new Error('Failed to fetch automation diagnostics');
      return r.json();
    }),
    fetch(`${getBase()}/v1/developer/diagnostics`).then((r) => {
      if (!r.ok) throw new Error('Failed to fetch developer diagnostics');
      return r.json();
    }),
    fetch(`${getBase()}/v1/security/diagnostics`).then((r) => {
      if (!r.ok) throw new Error('Failed to fetch security diagnostics');
      return r.json();
    }),
    fetch(`${getBase()}/v1/mobile/diagnostics`).then((r) => {
      if (!r.ok) throw new Error('Failed to fetch mobile diagnostics');
      return r.json();
    }),
    fetch(`${getBase()}/v1/communication/diagnostics`).then((r) => {
      if (!r.ok) throw new Error('Failed to fetch communication diagnostics');
      return r.json();
    }),
    fetch(`${getBase()}/v1/real-world/diagnostics`).then((r) => {
      if (!r.ok) throw new Error('Failed to fetch real-world diagnostics');
      return r.json();
    }),
    fetch(`${getBase()}/v1/iot/diagnostics`).then((r) => {
      if (!r.ok) throw new Error('Failed to fetch smart home diagnostics');
      return r.json();
    }),
    fetch(`${getBase()}/v1/future/diagnostics`).then((r) => {
      if (!r.ok) throw new Error('Failed to fetch future diagnostics');
      return r.json();
    }),
  ]);
  return { fileIntelligence, office, automation, developer, security, mobile, communication, realWorld, iot, future };
}

export async function runRoutine(name: string): Promise<{ status: string; message: string }> {
  const res = await fetch(`${getBase()}/v1/routines/${encodeURIComponent(name)}/run`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error('Failed to run routine');
  return res.json();
}

export async function setRoutineEnabled(name: string, enabled: boolean): Promise<{ status: string }> {
  const action = enabled ? 'enable' : 'disable';
  const res = await fetch(`${getBase()}/v1/routines/${encodeURIComponent(name)}/${action}`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error('Failed to update routine');
  return res.json();
}

// ---------------------------------------------------------------------------
// Structured PC Control Safety Console
// ---------------------------------------------------------------------------

export type PcRiskLevel = 'LOW' | 'MEDIUM' | 'HIGH' | 'BLOCKED';

export interface StructuredLocalActionPending {
  id: string;
  action_id: string;
  action_type: string;
  target: string;
  risk_level: PcRiskLevel;
  status: string;
  decision: string;
  created_at: number;
  expires_at: number;
  decision_timestamp?: number | null;
  dry_run: boolean;
  approval_required: boolean;
  require_approval?: boolean;
}

export interface StructuredLocalActionApprovalsResponse {
  actions: StructuredLocalActionPending[];
  storage: {
    backend: string;
    path: string;
    persistent: boolean;
    local_only: boolean;
  };
  retention: {
    approval_retention_days: number;
    audit_max_bytes: number;
    audit_keep_recent_lines: number;
  };
  maintenance: {
    started_at: number;
    completed_at: number | null;
    storage_healthy: boolean;
    cleanup_completed: boolean;
    errors: string[];
    expired_approvals: number;
    deleted_approval_records: number;
    audit_rotated: boolean;
    audit_archived_path?: string | null;
    audit_kept_lines: number;
  };
  counts: Record<string, number>;
}

export interface StructuredLocalActionAuditEntry {
  timestamp: number;
  action_type: string;
  target: string;
  risk_level: PcRiskLevel;
  status: string;
  decision: string;
  dry_run: boolean;
  ok: boolean;
  action_id?: string | null;
}

export interface StructuredLocalActionResponse {
  ok: boolean;
  action_id: string | null;
  status: string;
  message: string;
  approval_required: boolean;
  risk_level: PcRiskLevel;
  evidence: Record<string, unknown>;
  error: string | null;
}

export async function fetchStructuredLocalActionPending(): Promise<StructuredLocalActionPending[]> {
  const res = await fetch(`${getBase()}/api/local-action/pending`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.actions || [];
}

export async function fetchStructuredLocalActionApprovals(limit = 100): Promise<StructuredLocalActionApprovalsResponse> {
  const res = await fetch(`${getBase()}/api/local-action/approvals?limit=${encodeURIComponent(String(limit))}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function fetchStructuredLocalActionAudit(limit = 100): Promise<StructuredLocalActionAuditEntry[]> {
  const res = await fetch(`${getBase()}/api/local-action/audit?limit=${encodeURIComponent(String(limit))}`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.entries || [];
}

export async function approveStructuredLocalAction(actionId: string): Promise<StructuredLocalActionResponse> {
  const res = await fetch(`${getBase()}/api/local-action/${encodeURIComponent(actionId)}/approve`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function rejectStructuredLocalAction(actionId: string): Promise<StructuredLocalActionResponse> {
  const res = await fetch(`${getBase()}/api/local-action/${encodeURIComponent(actionId)}/reject`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

export async function emergencyStopStructuredLocalActions(): Promise<StructuredLocalActionResponse> {
  const res = await fetch(`${getBase()}/api/local-action/emergency-stop`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Approvals
// ---------------------------------------------------------------------------

export interface PendingApproval {
  id: string;
  action_type: string;
  description: string;
  payload: Record<string, unknown>;
  permission_key: string;
  tier: 'trivial' | 'low' | 'medium' | 'high';
  status: string;
  created_at: string;
  expires_at: string;
}

export async function fetchPendingApprovals(): Promise<PendingApproval[]> {
  const res = await fetch(`${getBase()}/v1/approvals/pending`);
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
  const data = await res.json();
  return data.actions || [];
}

export async function approveAction(actionId: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/approvals/${actionId}/approve`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}

export async function denyAction(actionId: string): Promise<void> {
  const res = await fetch(`${getBase()}/v1/approvals/${actionId}/deny`, { method: 'POST' });
  if (!res.ok) throw new Error(`Failed: ${res.status}`);
}
