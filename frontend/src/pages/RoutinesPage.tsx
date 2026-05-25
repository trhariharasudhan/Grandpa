import { useEffect, useState } from 'react';
import { Bell, CalendarClock, Play, Power, RefreshCw, Workflow } from 'lucide-react';
import {
  fetchRoutinesSummary,
  runRoutine,
  setRoutineEnabled,
  type RoutinesSummary,
} from '../lib/api';

export function RoutinesPage() {
  const [summary, setSummary] = useState<RoutinesSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<string | null>(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      setSummary(await fetchRoutinesSummary());
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load routines');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handleRun = async (name: string) => {
    setBusy(`run:${name}`);
    setLastResult(null);
    try {
      const result = await runRoutine(name);
      setLastResult(result.message);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to run routine');
    } finally {
      setBusy(null);
    }
  };

  const handleToggle = async (name: string, enabled: boolean) => {
    setBusy(`toggle:${name}`);
    try {
      await setRoutineEnabled(name, !enabled);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update routine');
    } finally {
      setBusy(null);
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
              <Workflow size={22} />
            </div>
            <div>
              <h1 className="text-2xl font-semibold" style={{ color: 'var(--color-text)' }}>
                Routines
              </h1>
              <p className="text-sm" style={{ color: 'var(--color-text-secondary)' }}>
                Local routines and reminders Grandpa can remember and run safely.
              </p>
            </div>
          </div>
          <button
            onClick={load}
            className="flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition-colors self-start md:self-auto"
            style={{
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-secondary)',
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

        {lastResult && (
          <pre
            className="mb-5 rounded-2xl px-4 py-3 text-sm whitespace-pre-wrap"
            style={{
              background: 'var(--color-bg-secondary)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text-secondary)',
            }}
          >
            {lastResult}
          </pre>
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
              <CalendarClock size={17} style={{ color: 'var(--color-accent)' }} />
              <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                Routine Deck
              </h2>
            </div>
            {loading ? (
              <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                Loading routines...
              </p>
            ) : !summary?.routines.length ? (
              <p className="text-sm leading-6" style={{ color: 'var(--color-text-secondary)' }}>
                No routines yet. Try “create a morning routine”.
              </p>
            ) : (
              <div className="space-y-3">
                {summary.routines.map((routine) => (
                  <div
                    key={routine.id}
                    className="rounded-xl p-4"
                    style={{
                      background: 'var(--color-bg-secondary)',
                      border: '1px solid var(--color-border)',
                    }}
                  >
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <div className="flex items-center gap-2">
                          <h3 className="text-sm font-medium capitalize" style={{ color: 'var(--color-text)' }}>
                            {routine.name}
                          </h3>
                          <span
                            className="text-[11px] px-2 py-0.5 rounded-full"
                            style={{
                              color: routine.enabled ? 'var(--color-success)' : 'var(--color-text-tertiary)',
                              background: routine.enabled
                                ? 'color-mix(in srgb, var(--color-success) 12%, transparent)'
                                : 'var(--color-bg-tertiary)',
                            }}
                          >
                            {routine.enabled ? 'enabled' : 'disabled'}
                          </span>
                        </div>
                        <div className="text-xs mt-1" style={{ color: 'var(--color-text-secondary)' }}>
                          Next: {routine.next_run_label}
                        </div>
                        <div className="flex flex-wrap gap-2 mt-3">
                          {routine.actions.map((action) => (
                            <span
                              key={action}
                              className="text-[11px] px-2 py-1 rounded-lg"
                              style={{
                                background: 'var(--color-bg-tertiary)',
                                color: 'var(--color-text-secondary)',
                              }}
                            >
                              {action}
                            </span>
                          ))}
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          onClick={() => handleRun(routine.name)}
                          disabled={busy === `run:${routine.name}`}
                          className="p-2 rounded-xl transition-opacity"
                          title="Run routine"
                          style={{
                            background: 'var(--color-accent-subtle)',
                            color: 'var(--color-accent)',
                            opacity: busy === `run:${routine.name}` ? 0.55 : 1,
                          }}
                        >
                          <Play size={16} />
                        </button>
                        <button
                          onClick={() => handleToggle(routine.name, routine.enabled)}
                          disabled={busy === `toggle:${routine.name}`}
                          className="p-2 rounded-xl transition-opacity"
                          title={routine.enabled ? 'Disable routine' : 'Enable routine'}
                          style={{
                            background: 'var(--color-bg-tertiary)',
                            color: routine.enabled ? 'var(--color-accent-amber)' : 'var(--color-text-tertiary)',
                            opacity: busy === `toggle:${routine.name}` ? 0.55 : 1,
                          }}
                        >
                          <Power size={16} />
                        </button>
                      </div>
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
              <Bell size={17} style={{ color: 'var(--color-accent-amber)' }} />
              <h2 className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                Reminders
              </h2>
            </div>
            {loading ? (
              <p className="text-sm" style={{ color: 'var(--color-text-tertiary)' }}>
                Loading reminders...
              </p>
            ) : !summary?.reminders.length ? (
              <p className="text-sm leading-6" style={{ color: 'var(--color-text-secondary)' }}>
                No reminders yet. Try “remind me every hour to drink water”.
              </p>
            ) : (
              <div className="space-y-3">
                {summary.reminders.map((reminder) => (
                  <div
                    key={reminder.id}
                    className="rounded-xl px-4 py-3"
                    style={{
                      background: 'var(--color-bg-secondary)',
                      border: '1px solid var(--color-border)',
                    }}
                  >
                    <div className="text-sm" style={{ color: 'var(--color-text)' }}>
                      {reminder.text}
                    </div>
                    <div className="text-xs mt-1" style={{ color: 'var(--color-text-secondary)' }}>
                      {reminder.schedule_label} · next {reminder.next_run_label}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>

        {summary?.storage && (
          <div className="mt-5 text-xs" style={{ color: 'var(--color-text-tertiary)' }}>
            Scheduler storage: {summary.storage.backend}, local only
          </div>
        )}
      </div>
    </div>
  );
}
