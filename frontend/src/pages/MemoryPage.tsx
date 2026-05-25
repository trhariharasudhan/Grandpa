import { useEffect, useMemo, useState } from 'react';
import { Brain, Clock3, Database, RefreshCw, Trash2 } from 'lucide-react';
import {
  clearPersonalMemory,
  fetchPersonalMemory,
  type PersonalMemorySummary,
} from '../lib/api';

const formatTime = (seconds: number) =>
  new Date(seconds * 1000).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

export function MemoryPage() {
  const [summary, setSummary] = useState<PersonalMemorySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [clearing, setClearing] = useState(false);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setSummary(await fetchPersonalMemory());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load memory');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const groupedMemories = useMemo(() => {
    const groups = new Map<string, NonNullable<PersonalMemorySummary['memories']>>();
    for (const item of summary?.memories || []) {
      const list = groups.get(item.category) || [];
      list.push(item);
      groups.set(item.category, list);
    }
    return Array.from(groups.entries());
  }, [summary]);

  const handleClear = async () => {
    if (!window.confirm('Clear local personal memory and recent activity?')) return;
    setClearing(true);
    try {
      await clearPersonalMemory();
      await load();
    } finally {
      setClearing(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-6xl mx-auto px-6 py-8">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between mb-8">
          <div>
            <div className="flex items-center gap-3 mb-3">
              <div
                className="w-11 h-11 rounded-2xl flex items-center justify-center"
                style={{
                  background: 'var(--color-accent-subtle)',
                  color: 'var(--color-accent)',
                  boxShadow: '0 0 28px var(--color-accent-glow)',
                }}
              >
                <Brain size={22} />
              </div>
              <div>
                <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>
                  Memory
                </h1>
                <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                  Local facts, preferences, and recent activity Grandpa can recall.
                </p>
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={load}
              disabled={loading}
              className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition-colors"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-secondary)',
                opacity: loading ? 0.65 : 1,
              }}
            >
              <RefreshCw size={15} className={loading ? 'animate-spin' : ''} />
              Refresh
            </button>
            <button
              onClick={handleClear}
              disabled={clearing}
              className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition-colors"
              style={{
                background: 'color-mix(in srgb, var(--color-error) 12%, transparent)',
                border: '1px solid color-mix(in srgb, var(--color-error) 38%, transparent)',
                color: 'var(--color-error)',
                opacity: clearing ? 0.55 : 1,
              }}
            >
              <Trash2 size={15} />
              Clear
            </button>
          </div>
        </div>

        {error && (
          <div
            className="mb-5 rounded-2xl px-4 py-3 text-sm"
            style={{
              background: 'color-mix(in srgb, var(--color-error) 12%, transparent)',
              border: '1px solid color-mix(in srgb, var(--color-error) 38%, transparent)',
              color: 'var(--color-error)',
            }}
          >
            {error}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-[1.1fr_0.9fr] gap-5">
          <section
            className="rounded-2xl p-5"
            style={{
              background: 'color-mix(in srgb, var(--color-surface) 86%, transparent)',
              border: '1px solid var(--color-border)',
              boxShadow: '0 20px 60px -40px var(--color-accent)',
            }}
          >
            <div className="flex items-center gap-2 mb-4">
              <Database size={17} style={{ color: 'var(--color-accent)' }} />
              <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                Remembered Facts
              </h2>
            </div>
            {loading ? (
              <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                Loading memory...
              </p>
            ) : groupedMemories.length === 0 ? (
              <div className="text-sm leading-6" style={{ color: 'var(--color-text-secondary)' }}>
                No remembered facts yet. Try saying “remember my project is Grandpa”.
              </div>
            ) : (
              <div className="space-y-5">
                {groupedMemories.map(([category, items]) => (
                  <div key={category}>
                    <div
                      className="text-[11px] uppercase tracking-[0.18em] mb-2"
                      style={{ color: 'var(--color-text-tertiary)' }}
                    >
                      {category.replace(/_/g, ' ')}
                    </div>
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                      {items.map((item) => (
                        <div
                          key={item.id}
                          className="rounded-xl p-4"
                          style={{
                            background: 'var(--color-bg-secondary)',
                            border: '1px solid var(--color-border)',
                          }}
                        >
                          <div className="text-xs mb-1" style={{ color: 'var(--color-text-tertiary)' }}>
                            {item.key.replace(/_/g, ' ')}
                          </div>
                          <div className="text-sm" style={{ color: 'var(--color-text)' }}>
                            {item.value}
                          </div>
                          <div className="text-[11px] mt-3" style={{ color: 'var(--color-text-tertiary)' }}>
                            Updated {formatTime(item.updated_at)}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section
            className="rounded-2xl p-5"
            style={{
              background: 'color-mix(in srgb, var(--color-surface) 86%, transparent)',
              border: '1px solid var(--color-border)',
            }}
          >
            <div className="flex items-center gap-2 mb-4">
              <Clock3 size={17} style={{ color: 'var(--color-accent-amber)' }} />
              <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                Recent Activity
              </h2>
            </div>
            {loading ? (
              <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                Loading activity...
              </p>
            ) : !summary?.recent_activity.length ? (
              <p className="text-sm leading-6" style={{ color: 'var(--color-text-secondary)' }}>
                Grandpa has not recorded local activity yet.
              </p>
            ) : (
              <div className="space-y-3">
                {summary.recent_activity.map((item) => (
                  <div
                    key={item.id}
                    className="rounded-xl px-4 py-3"
                    style={{
                      background: 'var(--color-bg-secondary)',
                      border: '1px solid var(--color-border)',
                    }}
                  >
                    <div className="flex items-center justify-between gap-3 mb-1">
                      <span className="text-sm capitalize" style={{ color: 'var(--color-text)' }}>
                        {item.category} · {item.action}
                      </span>
                      <span className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
                        {formatTime(item.created_at)}
                      </span>
                    </div>
                    <div className="text-xs truncate" style={{ color: 'var(--color-text-secondary)' }}>
                      {item.target || item.detail || item.status}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        {summary?.storage && (
          <div className="mt-5 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            Storage: {summary.storage.backend} · local only
          </div>
        )}
      </div>
    </div>
  );
}
