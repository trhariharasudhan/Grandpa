import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { BookOpen, Database, FileText, RefreshCw, Search, Sparkles, Tags, Upload } from 'lucide-react';
import {
  fetchKnowledgeDiagnostics,
  fetchKnowledgeDocuments,
  fetchKnowledgeEmbeddingStatus,
  fetchKnowledgeSummary,
  fetchKnowledgeContext,
  fetchRelatedKnowledge,
  importKnowledgeDocument,
  searchKnowledge,
  semanticSearchKnowledge,
  type KnowledgeDiagnostics,
  type KnowledgeDocument,
  type KnowledgeEmbeddingStatus,
  type KnowledgeSummary,
} from '../lib/api';

export function KnowledgePage() {
  const [diagnostics, setDiagnostics] = useState<KnowledgeDiagnostics | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [results, setResults] = useState<KnowledgeDocument[] | null>(null);
  const [summary, setSummary] = useState<KnowledgeSummary | null>(null);
  const [embeddingStatus, setEmbeddingStatus] = useState<KnowledgeEmbeddingStatus | null>(null);
  const [contextChunks, setContextChunks] = useState<Array<Record<string, unknown>>>([]);
  const [truthfulNote, setTruthfulNote] = useState('');
  const [query, setQuery] = useState('');
  const [tag, setTag] = useState('');
  const [title, setTitle] = useState('Grandpa project note');
  const [content, setContent] = useState('Grandpa is a local-first personal AI assistant with memory, workflows, browser control, and desktop automation.');
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = async () => {
    setLoading(true);
    setError('');
    try {
      const [diag, docs, projectSummary] = await Promise.all([
        fetchKnowledgeDiagnostics(),
        fetchKnowledgeDocuments(100),
        fetchKnowledgeSummary({ project: true }).catch(() => null),
      ]);
      setDiagnostics(diag);
      setEmbeddingStatus(diag.embeddings);
      setDocuments(docs.documents || []);
      setSummary(projectSummary);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to load knowledge engine.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
  }, []);

  const tags = useMemo(() => diagnostics?.tags || [], [diagnostics]);
  const visibleDocuments = results ?? documents;

  const runSearch = async () => {
    setBusy(true);
    setError('');
    try {
      const response = await searchKnowledge(query, tag, 30);
      setResults(response.results || []);
      setTruthfulNote(response.truthful_note || '');
      setContextChunks([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Knowledge search failed.');
    } finally {
      setBusy(false);
    }
  };

  const runSemanticSearch = async () => {
    setBusy(true);
    setError('');
    try {
      const response = await semanticSearchKnowledge(query, tag, 20);
      setResults(response.results || []);
      setTruthfulNote(response.truthful_note || '');
      setContextChunks((response.results || []).map((item) => item.chunk || item.matched_chunks?.[0]).filter(Boolean) as Array<Record<string, unknown>>);
      const status = await fetchKnowledgeEmbeddingStatus();
      setEmbeddingStatus(status);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Semantic knowledge search failed.');
    } finally {
      setBusy(false);
    }
  };

  const buildContext = async () => {
    setBusy(true);
    setError('');
    try {
      const response = await fetchKnowledgeContext(query || 'Grandpa project knowledge', 5);
      setResults(response.documents || []);
      setContextChunks(response.chunks || []);
      setTruthfulNote(response.truthful_note || '');
      setSummary(response.summary);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Knowledge context build failed.');
    } finally {
      setBusy(false);
    }
  };

  const loadRelated = async (documentId: string) => {
    setBusy(true);
    setError('');
    try {
      const response = await fetchRelatedKnowledge(documentId, 8);
      setResults(response.results || []);
      setTruthfulNote('Related documents use hybrid local ranking.');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Related knowledge lookup failed.');
    } finally {
      setBusy(false);
    }
  };

  const importNote = async () => {
    setBusy(true);
    setError('');
    try {
      await importKnowledgeDocument({
        source: `manual:${title || 'note'}`,
        title,
        content,
        tags: ['notes', 'project'],
      });
      setResults(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Knowledge import failed.');
    } finally {
      setBusy(false);
    }
  };

  const importDocs = async () => {
    setBusy(true);
    setError('');
    try {
      await importKnowledgeDocument({ import_project_docs: true, path: 'docs' });
      setResults(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Project documentation import failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="h-full overflow-y-auto p-6" style={{ background: 'var(--color-bg)' }}>
      <div className="mx-auto flex max-w-7xl flex-col gap-5">
        <header className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--color-accent-amber)' }}>
              <BookOpen size={16} />
              Local document intelligence
            </div>
            <h1 className="mt-2 text-3xl font-semibold" style={{ color: 'var(--color-text)' }}>Knowledge Engine</h1>
            <p className="mt-2 max-w-3xl text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              Import notes and project docs into a local SQLite knowledge index. Retrieval is keyword/title/tag based in v1.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex items-center gap-2 rounded-xl px-4 py-2 text-sm"
            style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </header>

        {error && (
          <div className="rounded-2xl px-4 py-3 text-sm" style={{ border: '1px solid var(--color-danger)', color: 'var(--color-danger)' }}>
            {error}
          </div>
        )}

        <section className="grid gap-4 md:grid-cols-4">
          <Metric icon={Database} label="Documents" value={String(diagnostics?.document_count ?? documents.length)} />
          <Metric icon={Tags} label="Tags" value={String(tags.length)} />
          <Metric icon={Search} label="Retrieval" value="Hybrid" />
          <Metric icon={Sparkles} label="Embeddings" value={embeddingStatus?.true_semantic_available ? 'Semantic' : 'Fallback'} />
        </section>

        <section className="grid gap-5 xl:grid-cols-[420px_1fr]">
          <div className="flex flex-col gap-5">
            <Panel title="Import">
              <div className="flex flex-col gap-3">
                <input
                  value={title}
                  onChange={(event) => setTitle(event.target.value)}
                  className="rounded-xl px-3 py-2 text-sm outline-none"
                  style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  placeholder="Title"
                />
                <textarea
                  value={content}
                  onChange={(event) => setContent(event.target.value)}
                  rows={6}
                  className="rounded-xl px-3 py-2 text-sm outline-none"
                  style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  placeholder="Paste local note content..."
                />
                <div className="grid gap-2 sm:grid-cols-2">
                  <button type="button" onClick={() => void importNote()} disabled={busy} className="inline-flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm font-medium disabled:opacity-60" style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)' }}>
                    <Upload size={15} />
                    Import Note
                  </button>
                  <button type="button" onClick={() => void importDocs()} disabled={busy} className="inline-flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    <FileText size={15} />
                    Import Docs
                  </button>
                </div>
              </div>
            </Panel>

            <Panel title="Search">
              <div className="flex flex-col gap-3">
                <input
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  className="rounded-xl px-3 py-2 text-sm outline-none"
                  style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                  placeholder="Search local knowledge..."
                />
                <select
                  value={tag}
                  onChange={(event) => setTag(event.target.value)}
                  className="rounded-xl px-3 py-2 text-sm outline-none"
                  style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
                >
                  <option value="">All tags</option>
                  {tags.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
                <button type="button" onClick={() => void runSearch()} disabled={busy} className="inline-flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                  <Search size={15} />
                  Hybrid Search
                </button>
                <div className="grid gap-2 sm:grid-cols-2">
                  <button type="button" onClick={() => void runSemanticSearch()} disabled={busy} className="rounded-xl px-3 py-2 text-sm disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    Semantic Search
                  </button>
                  <button type="button" onClick={() => void buildContext()} disabled={busy} className="rounded-xl px-3 py-2 text-sm disabled:opacity-60" style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}>
                    Build Context
                  </button>
                </div>
              </div>
            </Panel>
          </div>

          <div className="flex flex-col gap-5">
            <Panel title="Summary">
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                {summary?.summary || 'Import documents to generate a deterministic local knowledge summary.'}
              </p>
              <div className="mt-4 grid gap-2 text-xs md:grid-cols-2" style={{ color: 'var(--color-text-secondary)' }}>
                <div className="rounded-xl p-3" style={{ background: 'var(--color-bg-tertiary)' }}>
                  Backend: {embeddingStatus?.ollama_available ? 'Ollama nomic-embed-text' : 'deterministic fallback'}
                </div>
                <div className="rounded-xl p-3" style={{ background: 'var(--color-bg-tertiary)' }}>
                  Vectors: {embeddingStatus?.embedding_count ?? 0}/{embeddingStatus?.expected_chunk_embeddings ?? 0}
                </div>
              </div>
              {truthfulNote && (
                <p className="mt-3 text-xs" style={{ color: 'var(--color-accent-amber)' }}>{truthfulNote}</p>
              )}
            </Panel>

            {contextChunks.length > 0 && (
              <Panel title="Retrieved Chunks">
                <div className="grid gap-3">
                  {contextChunks.slice(0, 5).map((chunk, index) => (
                    <div key={`${chunk.chunk_id || index}`} className="rounded-xl p-3 text-sm" style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}>
                      <div className="mb-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                        {String(chunk.chunk_id || `chunk ${index + 1}`)}
                      </div>
                      {String(chunk.text || '').slice(0, 420)}
                    </div>
                  ))}
                </div>
              </Panel>
            )}

            <Panel title="Embedding Status">
              <div className="grid gap-2 text-sm md:grid-cols-2" style={{ color: 'var(--color-text-secondary)' }}>
                <div>Preferred model: {embeddingStatus?.preferred_model || 'nomic-embed-text'}</div>
                <div>Mode: {embeddingStatus?.true_semantic_available ? 'true semantic' : 'fallback lexical vectors'}</div>
                <div>Stored vectors: {embeddingStatus?.embedding_count ?? 0}</div>
                <div>External vector DB: no</div>
              </div>
            </Panel>

            <Panel title={results ? 'Search Results' : 'Indexed Documents'}>
              <div className="grid gap-3">
                {visibleDocuments.length === 0 && (
                  <div className="rounded-xl p-4 text-sm" style={{ background: 'var(--color-bg-tertiary)', color: 'var(--color-text-secondary)' }}>
                    No knowledge documents indexed yet.
                  </div>
                )}
                {visibleDocuments.map((doc) => (
                  <article key={doc.document_id} className="rounded-xl p-4" style={{ background: 'var(--color-bg-tertiary)', border: '1px solid var(--color-border)' }}>
                    <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
                      <div>
                        <h3 className="font-medium" style={{ color: 'var(--color-text)' }}>{doc.title}</h3>
                        <p className="mt-1 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>{doc.source}</p>
                      </div>
                      {typeof doc.score === 'number' && (
                        <span className="rounded-full px-2 py-1 text-xs" style={{ background: 'var(--color-accent-subtle)', color: 'var(--color-accent-amber)' }}>
                          score {doc.score.toFixed(2)}
                        </span>
                      )}
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {(doc.tags || []).map((item) => (
                        <span key={item} className="rounded-full px-2 py-1 text-[11px]" style={{ background: 'var(--color-bg)', color: 'var(--color-text-secondary)', border: '1px solid var(--color-border)' }}>
                          {item}
                        </span>
                      ))}
                    </div>
                    {doc.matched_terms?.length ? (
                      <p className="mt-3 text-xs" style={{ color: 'var(--color-text-secondary)' }}>
                        Matched: {doc.matched_terms.join(', ')}
                      </p>
                    ) : null}
                    {doc.ranking_explanation && (
                      <p className="mt-2 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
                        Rank: keyword {String(doc.ranking_explanation.keyword_score ?? 0)}, semantic {String(doc.ranking_explanation.semantic_score ?? 0)}, recency {String(doc.ranking_explanation.recency_score ?? 0)}
                      </p>
                    )}
                    <button
                      type="button"
                      onClick={() => void loadRelated(doc.document_id)}
                      className="mt-3 rounded-lg px-2.5 py-1.5 text-xs"
                      style={{ border: '1px solid var(--color-border)', color: 'var(--color-text-secondary)' }}
                    >
                      Related
                    </button>
                  </article>
                ))}
              </div>
            </Panel>
          </div>
        </section>
      </div>
    </main>
  );
}

function Metric({ icon: Icon, label, value }: { icon: typeof Database; label: string; value: string }) {
  return (
    <div className="rounded-2xl p-4" style={{ background: 'var(--color-bg-secondary)', border: '1px solid var(--color-border)' }}>
      <Icon size={18} style={{ color: 'var(--color-accent-amber)' }} />
      <div className="mt-3 text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>{value}</div>
      <div className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>{label}</div>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-2xl p-4" style={{ background: 'color-mix(in srgb, var(--color-bg-secondary) 86%, transparent)', border: '1px solid var(--color-border)' }}>
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-[0.14em]" style={{ color: 'var(--color-text-secondary)' }}>{title}</h2>
      {children}
    </section>
  );
}
