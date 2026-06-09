import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Brain, Clock3, Database, GitBranch, RefreshCw, Search, Sparkles, Star, Tags, Trash2 } from 'lucide-react';
import {
  clearPersonalMemory,
  fetchPersonalMemory,
  fetchMemoryRelationships,
  fetchMemoryTopics,
  searchPersonalMemory,
  type PersonalMemorySummary,
  type PersonalMemoryItem,
  type MemoryRelationshipGraph,
  type MemoryTopic,
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
  const [searchQuery, setSearchQuery] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [searching, setSearching] = useState(false);
  const [searchResults, setSearchResults] = useState<PersonalMemoryItem[] | null>(null);
  const [searchUncertain, setSearchUncertain] = useState(false);
  const [relationships, setRelationships] = useState<MemoryRelationshipGraph | null>(null);
  const [topics, setTopics] = useState<MemoryTopic[]>([]);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [memory, graph, topicData] = await Promise.all([
        fetchPersonalMemory(),
        fetchMemoryRelationships().catch(() => null),
        fetchMemoryTopics().catch(() => ({ topics: [] })),
      ]);
      setSummary(memory);
      setRelationships(graph);
      setTopics(topicData.topics || []);
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
    const visible = searchResults ?? (summary?.memories || []);
    for (const item of visible) {
      if (!searchResults && categoryFilter !== 'all' && item.category !== categoryFilter) continue;
      const list = groups.get(item.category) || [];
      list.push(item);
      groups.set(item.category, list);
    }
    return Array.from(groups.entries());
  }, [summary, searchResults, categoryFilter]);

  const categories = useMemo(() => {
    const fromSummary = summary?.categories?.length
      ? summary.categories
      : Array.from(new Set((summary?.memories || []).map((item) => item.category)));
    return ['all', ...fromSummary.sort()];
  }, [summary]);

  const intelligence = summary?.intelligence;
  const preferences = intelligence?.top_preferences || [];
  const promoted = intelligence?.promoted_memories || [];
  const visibleTopics = topics.length ? topics : intelligence?.topics || [];

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

  const handleSemanticSearch = async () => {
    const query = searchQuery.trim();
    if (!query) {
      setSearchResults(null);
      setSearchUncertain(false);
      return;
    }
    setSearching(true);
    setError(null);
    try {
      const response = await searchPersonalMemory(query, categoryFilter, 8);
      setSearchResults(response.results);
      setSearchUncertain(response.uncertain);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to search memory');
    } finally {
      setSearching(false);
    }
  };

  const clearSearch = () => {
    setSearchQuery('');
    setSearchResults(null);
    setSearchUncertain(false);
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
              <div className="flex-1">
                <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                  Remembered Facts
                </h2>
                {summary?.semantic && (
                  <div className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
                    Semantic recall · {summary.semantic.embedding_model} · local only
                  </div>
                )}
              </div>
            </div>
            <div className="mb-4 grid grid-cols-1 md:grid-cols-[1fr_auto] gap-2">
              <div
                className="flex items-center gap-2 rounded-xl px-3 py-2"
                style={{
                  background: 'var(--color-bg-secondary)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <Search size={15} style={{ color: 'var(--color-text-tertiary)' }} />
                <input
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') handleSemanticSearch();
                  }}
                  placeholder="Search by meaning, like “what editor do I prefer?”"
                  className="w-full bg-transparent text-sm outline-none"
                  style={{ color: 'var(--color-text)' }}
                />
              </div>
              <div className="flex gap-2">
                <select
                  value={categoryFilter}
                  onChange={(event) => {
                    setCategoryFilter(event.target.value);
                    setSearchResults(null);
                    setSearchUncertain(false);
                  }}
                  className="rounded-xl px-3 py-2 text-sm outline-none"
                  style={{
                    background: 'var(--color-bg-secondary)',
                    border: '1px solid var(--color-border)',
                    color: 'var(--color-text-secondary)',
                  }}
                >
                  {categories.map((category) => (
                    <option key={category} value={category}>
                      {category === 'all' ? 'All categories' : category.replace(/_/g, ' ')}
                    </option>
                  ))}
                </select>
                <button
                  onClick={handleSemanticSearch}
                  disabled={searching}
                  className="px-3 py-2 rounded-xl text-sm"
                  style={{
                    background: 'var(--color-accent)',
                    color: 'white',
                    opacity: searching ? 0.65 : 1,
                  }}
                >
                  {searching ? 'Searching' : 'Search'}
                </button>
              </div>
            </div>
            {searchResults && (
              <div className="mb-4 flex items-center justify-between gap-3 text-xs">
                <span style={{ color: searchUncertain ? 'var(--color-warning)' : 'var(--color-text-secondary)' }}>
                  {searchUncertain
                    ? 'Low-confidence semantic match. Grandpa will avoid guessing.'
                    : `${searchResults.length} semantic match${searchResults.length === 1 ? '' : 'es'} found.`}
                </span>
                <button onClick={clearSearch} style={{ color: 'var(--color-accent)' }}>
                  Show all
                </button>
              </div>
            )}
            {loading ? (
              <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                Loading memory...
              </p>
            ) : groupedMemories.length === 0 ? (
              <div className="text-sm leading-6" style={{ color: 'var(--color-text-secondary)' }}>
                {searchResults
                  ? 'No semantic memory matched that search.'
                  : 'No remembered facts yet. Try saying “remember my project is Grandpa”.'}
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
                          <div
                            className="flex items-center justify-between gap-3 text-[11px] mt-3"
                            style={{ color: 'var(--color-text-tertiary)' }}
                          >
                            <span>Updated {formatTime(item.updated_at)}</span>
                            {typeof item.score === 'number' && (
                              <span style={{ color: 'var(--color-accent-amber)' }}>
                                {Math.round(item.score * 100)}% match
                              </span>
                            )}
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

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-5 mt-5">
          <section
            className="rounded-2xl p-5 xl:col-span-2"
            style={{
              background: 'color-mix(in srgb, var(--color-surface) 86%, transparent)',
              border: '1px solid var(--color-border)',
              boxShadow: '0 20px 60px -44px var(--color-accent)',
            }}
          >
            <div className="flex items-center gap-2 mb-4">
              <Sparkles size={17} style={{ color: 'var(--color-accent)' }} />
              <div>
                <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                  Memory Intelligence
                </h2>
                <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                  Ranking, preferences, topics, and promoted long-term context.
                </p>
              </div>
            </div>
            <p className="text-sm leading-6 mb-4" style={{ color: 'var(--color-text-secondary)' }}>
              {intelligence?.summary || 'Grandpa will build a local profile as you save memories.'}
            </p>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              <MetricCard label="Memories" value={String(intelligence?.memory_count ?? summary?.memories.length ?? 0)} />
              <MetricCard label="Preferences" value={String(intelligence?.preference_count ?? preferences.length)} />
              <MetricCard label="Promoted" value={String(promoted.length)} />
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-5">
              <MiniPanel icon={<Star size={15} />} title="Learned Preferences">
                {preferences.length ? (
                  preferences.slice(0, 5).map((item) => (
                    <div key={`${item.subject}-${item.value}`} className="flex items-center justify-between gap-3 text-xs py-1">
                      <span style={{ color: 'var(--color-text-secondary)' }}>{item.subject}</span>
                      <span className="text-right" style={{ color: 'var(--color-text)' }}>
                        {item.value} · {Math.round(item.confidence * 100)}%
                      </span>
                    </div>
                  ))
                ) : (
                  <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                    No clear preferences learned yet.
                  </p>
                )}
              </MiniPanel>
              <MiniPanel icon={<Tags size={15} />} title="Topic Clusters">
                {visibleTopics.length ? (
                  visibleTopics.slice(0, 5).map((topic) => (
                    <div key={topic.name} className="flex items-center justify-between gap-3 text-xs py-1">
                      <span style={{ color: 'var(--color-text-secondary)' }}>{topic.name}</span>
                      <span style={{ color: 'var(--color-accent-amber)' }}>
                        {topic.count} · {Math.round(topic.average_importance * 100)}%
                      </span>
                    </div>
                  ))
                ) : (
                  <p className="text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                    Topic clusters appear after memories are saved.
                  </p>
                )}
              </MiniPanel>
            </div>
          </section>

          <section
            className="rounded-2xl p-5"
            style={{
              background: 'color-mix(in srgb, var(--color-surface) 86%, transparent)',
              border: '1px solid var(--color-border)',
            }}
          >
            <div className="flex items-center gap-2 mb-4">
              <GitBranch size={17} style={{ color: 'var(--color-accent-amber)' }} />
              <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                Relationship Graph
              </h2>
            </div>
            {!relationships?.nodes?.length ? (
              <p className="text-sm leading-6" style={{ color: 'var(--color-text-secondary)' }}>
                Relationship links will appear as Grandpa learns projects, tools, and devices.
              </p>
            ) : (
              <div className="space-y-2">
                {relationships.edges.slice(0, 8).map((edge) => (
                  <div
                    key={`${edge.source}-${edge.target}-${edge.relation}`}
                    className="rounded-xl px-3 py-2 text-xs"
                    style={{
                      background: 'var(--color-bg-secondary)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text-secondary)',
                    }}
                  >
                    <span style={{ color: 'var(--color-text)' }}>{edge.source}</span>
                    {' -> '}
                    <span style={{ color: 'var(--color-accent-amber)' }}>{edge.target}</span>
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

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <div
      className="rounded-xl px-4 py-3"
      style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
      }}
    >
      <div className="text-[11px] uppercase tracking-[0.16em]" style={{ color: 'var(--color-text-tertiary)' }}>
        {label}
      </div>
      <div className="text-xl font-semibold mt-1" style={{ color: 'var(--color-text)' }}>
        {value}
      </div>
    </div>
  );
}

function MiniPanel({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div
      className="rounded-xl p-4"
      style={{
        background: 'var(--color-bg-secondary)',
        border: '1px solid var(--color-border)',
      }}
    >
      <div className="flex items-center gap-2 mb-3" style={{ color: 'var(--color-accent)' }}>
        {icon}
        <h3 className="text-xs font-semibold" style={{ color: 'var(--color-text)' }}>
          {title}
        </h3>
      </div>
      {children}
    </div>
  );
}
