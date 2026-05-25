import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import {
  Clock3,
  FileSearch,
  FolderOpen,
  NotebookPen,
  RefreshCw,
  Search,
} from 'lucide-react';
import {
  fetchFileAssistantSummary,
  searchFileAssistant,
  type FileAssistantSummary,
} from '../lib/api';

const formatTime = (seconds: number) =>
  new Date(seconds * 1000).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });

export function FileAssistantPage() {
  const [summary, setSummary] = useState<FileAssistantSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [searching, setSearching] = useState(false);
  const [searchResult, setSearchResult] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setSummary(await fetchFileAssistantSummary());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load file assistant');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleSearch = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = query.trim();
    if (!trimmed) return;
    setSearching(true);
    setSearchResult(null);
    setError(null);
    try {
      const result = await searchFileAssistant(trimmed);
      setSearchResult(result.message);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'File search failed');
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-6xl mx-auto px-6 py-8">
        <div className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between mb-8">
          <div className="flex items-center gap-3">
            <div
              className="w-11 h-11 rounded-2xl flex items-center justify-center"
              style={{
                background: 'var(--color-accent-subtle)',
                color: 'var(--color-accent)',
                boxShadow: '0 0 28px var(--color-accent-glow)',
              }}
            >
              <FolderOpen size={22} />
            </div>
            <div>
              <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>
                File Assistant
              </h1>
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                Local files, notes, and document context Grandpa can use safely.
              </p>
            </div>
          </div>
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition-colors self-start md:self-auto"
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

        <section
          className="rounded-2xl p-5 mb-5"
          style={{
            background: 'color-mix(in srgb, var(--color-surface) 86%, transparent)',
            border: '1px solid var(--color-border)',
            boxShadow: '0 20px 60px -40px var(--color-accent)',
          }}
        >
          <div className="flex items-center gap-2 mb-4">
            <FileSearch size={17} style={{ color: 'var(--color-accent)' }} />
            <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
              Quick Search
            </h2>
          </div>
          <form onSubmit={handleSearch} className="flex flex-col sm:flex-row gap-3">
            <div
              className="flex items-center gap-2 px-3 py-2.5 rounded-xl flex-1"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
              }}
            >
              <Search size={15} style={{ color: 'var(--color-text-tertiary)' }} />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search files about FastAPI"
                className="bg-transparent outline-none flex-1 text-sm"
                style={{ color: 'var(--color-text)' }}
              />
            </div>
            <button
              type="submit"
              disabled={searching || !query.trim()}
              className="px-4 py-2.5 rounded-xl text-sm font-medium transition-opacity"
              style={{
                background: 'linear-gradient(135deg, var(--color-accent), color-mix(in srgb, var(--color-accent) 76%, var(--color-accent-amber)))',
                color: 'var(--color-on-accent)',
                opacity: searching || !query.trim() ? 0.55 : 1,
              }}
            >
              {searching ? 'Searching' : 'Search'}
            </button>
          </form>
          {searchResult && (
            <pre
              className="mt-4 rounded-xl p-4 text-sm whitespace-pre-wrap"
              style={{
                background: 'var(--color-bg-secondary)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-secondary)',
              }}
            >
              {searchResult}
            </pre>
          )}
        </section>

        <div className="grid grid-cols-1 lg:grid-cols-[1fr_0.9fr] gap-5">
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
                Recent Files
              </h2>
            </div>
            {loading ? (
              <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                Loading file activity...
              </p>
            ) : !summary?.recent_files.length ? (
              <p className="text-sm leading-6" style={{ color: 'var(--color-text-secondary)' }}>
                No file activity recorded yet. Try “create a note called ideas” or “find PDF files”.
              </p>
            ) : (
              <div className="space-y-3">
                {summary.recent_files.map((item) => (
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
                        {item.action}
                      </span>
                      <span className="text-[11px]" style={{ color: 'var(--color-text-tertiary)' }}>
                        {formatTime(item.created_at)}
                      </span>
                    </div>
                    <div className="text-xs truncate" style={{ color: 'var(--color-text-secondary)' }}>
                      {item.path}
                    </div>
                    {item.detail && (
                      <div className="text-[11px] mt-2" style={{ color: 'var(--color-text-tertiary)' }}>
                        {item.detail}
                      </div>
                    )}
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
              <NotebookPen size={17} style={{ color: 'var(--color-accent)' }} />
              <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                Notes
              </h2>
            </div>
            {loading ? (
              <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                Loading notes...
              </p>
            ) : !summary?.notes.length ? (
              <p className="text-sm leading-6" style={{ color: 'var(--color-text-secondary)' }}>
                No local notes yet. Notes are stored locally and never uploaded.
              </p>
            ) : (
              <div className="space-y-3">
                {summary.notes.map((note) => (
                  <div
                    key={note.path}
                    className="rounded-xl px-4 py-3"
                    style={{
                      background: 'var(--color-bg-secondary)',
                      border: '1px solid var(--color-border)',
                    }}
                  >
                    <div className="text-sm mb-1" style={{ color: 'var(--color-text)' }}>
                      {note.name}
                    </div>
                    <div className="text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                      {note.size_label} · modified {note.modified_label}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        {summary?.storage && (
          <div className="mt-5 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            File assistant storage: {summary.storage.backend}, local only
          </div>
        )}
      </div>
    </div>
  );
}
