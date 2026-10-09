'use client';

import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import Link from 'next/link';
import { canAccessAccount } from '@/lib/api';
import { useApp } from '@/lib/context';
import {
  fetchClickCountWorkspaces, fetchClickCountBases, fetchClickCountBase,
  startClickCountQuery, fetchClickCountQuery, ClickCountApiError,
  isTerminalClickCountError, isValidClickCountRange, todayInTimezone,
} from '@/lib/moengage-click-count';
import type {
  ClickCountWorkspace, ClickCountBase, ClickCountBaseMetadata,
  ClickCountQuery, ClickCountQueryStatus,
} from '@/lib/moengage-click-count';

const panel = 'rounded-xl border border-gray-200 bg-white p-5 shadow-sm';
const input = 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-gray-50 disabled:text-gray-500';
const primary = 'rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50';
const secondary = 'rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-semibold text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50';

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function ErrorNotice({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
      <p>{message}</p>
      {onRetry && <button type="button" className={`${secondary} mt-2`} onClick={onRetry}>Retry loading</button>}
    </div>
  );
}


export default function TataClickCountPage() {
  const { currentUser, authLoading } = useApp();
  if (authLoading) return <div className="p-8 text-sm text-gray-500" role="status">Checking your access…</div>;
  if (!currentUser || !canAccessAccount(currentUser, 'tata')) {
    return (
      <div className="mx-auto max-w-3xl p-8">
        <div className={`${panel} border-red-200`}>
          <h1 className="text-xl font-bold text-gray-900">Tata Click Counts access denied</h1>
          <p className="mt-2 text-sm text-gray-600">This page is restricted to Tata users and platform superadmins.</p>
          <Link href="/" className="mt-4 inline-block text-sm font-semibold text-blue-600">Return to your dashboard</Link>
        </div>
      </div>
    );
  }
  return <ClickCountWorkspacePicker key={`${currentUser.id}:${currentUser.tenant_id}:${currentUser.role}`} />;
}

function ClickCountWorkspacePicker() {
  const [workspaces, setWorkspaces] = useState<ClickCountWorkspace[]>([]);
  const [workspaceId, setWorkspaceId] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);

  useEffect(() => {
    setLoading(true);
    setError('');
    const controller = new AbortController();
    async function load() {
      try {
        const data = await fetchClickCountWorkspaces(AbortSignal.any([controller.signal, AbortSignal.timeout(60000)]));
        if (!controller.signal.aborted) setWorkspaces(data.workspaces);
      } catch (err) {
        if (!controller.signal.aborted) setError(errorMessage(err));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [reload]);

  const workspace = workspaces.find((item) => item.id === workspaceId);
  return (
    <div className="mx-auto max-w-4xl space-y-5 p-8">
      <header>
        <h1 className="text-2xl font-bold text-gray-900">Tata Click Counts</h1>
        <p className="mt-1 text-sm text-gray-500">Count multiple imported MoEngage bases simultaneously across an inclusive date range.</p>
      </header>
      <div className={panel}>
        <h2 className="text-sm font-semibold text-gray-900">Fixed click criteria</h2>
        <p className="mt-2 text-sm text-gray-600">For each selected base: WhatsApp OR Email OR SMS OR Android push OR iOS push clicks, AND base membership. Users are deduplicated within each base; counts are not summed because the same user may belong to multiple bases.</p>
      </div>
      <section className={`${panel} space-y-4`} aria-label="Click count selection" aria-busy={loading || busy}>
        <div>
          <label htmlFor="click-workspace" className="mb-1 block text-sm font-medium text-gray-700">MoEngage workspace</label>
          <select id="click-workspace" className={input} value={workspaceId} disabled={loading || busy || Boolean(error)} onChange={(event) => setWorkspaceId(event.target.value)}>
            <option value="">Select a workspace</option>
            {workspaces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select>
        </div>
        {loading && <p role="status" className="text-sm text-gray-500">Loading Tata workspaces…</p>}
        {error && <ErrorNotice message={error} onRetry={() => setReload((value) => value + 1)} />}
        {!loading && !error && workspaces.length === 0 && (
          <div className="space-y-2">
            <p role="status" className="text-sm text-gray-500">No Tata MoEngage workspaces are available.</p>
            <button type="button" className={secondary} onClick={() => setReload((value) => value + 1)}>Reload workspaces</button>
          </div>
        )}
        {workspace && <ImportedBasePicker key={workspace.id} workspace={workspace} busy={busy} onBusyChange={setBusy} />}
      </section>
    </div>
  );
}

function ImportedBasePicker({ workspace, busy, onBusyChange }: { workspace: ClickCountWorkspace; busy: boolean; onBusyChange: (value: boolean) => void }) {
  const [bases, setBases] = useState<ClickCountBase[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [reload, setReload] = useState(0);

  useEffect(() => {
    setLoading(true);
    setError('');
    const controller = new AbortController();
    async function load() {
      try {
        const data = await fetchClickCountBases(workspace.id, AbortSignal.any([controller.signal, AbortSignal.timeout(60000)]));
        if (!controller.signal.aborted) setBases(data.bases);
      } catch (err) {
        if (!controller.signal.aborted) setError(errorMessage(err));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [workspace.id, reload]);

  const selected = new Set(selectedIds);
  const searchTerm = search.trim().toLowerCase();
  const filteredBases = bases.filter((base) => selected.has(base.id) || base.name.toLowerCase().includes(searchTerm));
  const selectedBases = selectedIds.map((id) => bases.find((base) => base.id === id)).filter((base): base is ClickCountBase => Boolean(base));

  function toggleBase(baseId: string) {
    setSelectedIds((current) => current.includes(baseId)
      ? current.filter((id) => id !== baseId)
      : [...current, baseId]);
  }

  function selectVisible() {
    setSelectedIds((current) => {
      const next = new Set(current);
      for (const base of filteredBases) next.add(base.id);
      return [...next];
    });
  }

  return (
    <>
      {bases.length > 20 && (
        <div>
          <label htmlFor="click-base-search" className="mb-1 block text-sm font-medium text-gray-700">Search imported bases</label>
          <input id="click-base-search" type="search" className={input} value={search} disabled={busy} onChange={(event) => setSearch(event.target.value)} placeholder="Search by base name" />
        </div>
      )}
      {loading && <p role="status" className="text-sm text-gray-500">Loading imported bases…</p>}
      {error && <ErrorNotice message={error} onRetry={() => setReload((value) => value + 1)} />}
      {!loading && !error && bases.length === 0 && (
        <div className="space-y-2">
          <p role="status" className="text-sm text-gray-500">This workspace has no imported bases.</p>
          <button type="button" className={secondary} onClick={() => setReload((value) => value + 1)}>Reload imported bases</button>
        </div>
      )}
      {!loading && !error && bases.length > 0 && (
        <fieldset>
          <legend className="mb-2 text-sm font-medium text-gray-700">Imported bases · {selectedIds.length} selected</legend>
          <div className="mb-2 flex justify-end gap-2">
            <button type="button" className={secondary} disabled={busy || filteredBases.every((base) => selected.has(base.id))} onClick={selectVisible}>Select visible</button>
            <button type="button" className={secondary} disabled={busy || selectedIds.length === 0} onClick={() => setSelectedIds([])}>Clear</button>
          </div>
          <div id="click-bases" className="max-h-72 space-y-1 overflow-y-auto rounded-lg border border-gray-200 p-2">
            {filteredBases.map((base) => {
              const checked = selected.has(base.id);
              return (
                <label key={base.id} className="flex cursor-pointer items-start gap-2 rounded px-2 py-2 text-sm hover:bg-gray-50">
                  <input type="checkbox" className="mt-0.5 h-4 w-4" checked={checked} disabled={busy} onChange={() => toggleBase(base.id)} />
                  <span className="break-all text-gray-700">{base.name}</span>
                </label>
              );
            })}
          </div>
          {filteredBases.length === 0 && <p role="status" className="mt-2 text-sm text-gray-500">No bases match your search.</p>}
          <p className="mt-2 text-xs text-gray-500">All selected bases start together. Each result remains separate.</p>
        </fieldset>
      )}
      {selectedBases.length > 0 && <MultiBaseCountForm workspace={workspace} bases={selectedBases} onBusyChange={onBusyChange} />}
    </>
  );
}

type BaseJob = {
  query: ClickCountQuery | null;
  status: ClickCountQueryStatus | null;
  submitting: boolean;
  pollingPaused: boolean;
  unknownSubmission: boolean;
  error: string;
};

function MultiBaseCountForm({ workspace, bases, onBusyChange }: { workspace: ClickCountWorkspace; bases: ClickCountBase[]; onBusyChange: (value: boolean) => void }) {
  const [metadata, setMetadata] = useState<Record<string, ClickCountBaseMetadata>>({});
  const [metadataErrors, setMetadataErrors] = useState<Record<string, string>>({});
  const [loadingIds, setLoadingIds] = useState<string[]>([]);
  const [metadataReload, setMetadataReload] = useState(0);
  const [today, setToday] = useState('');
  const [endDate, setEndDate] = useState('');
  const [jobs, setJobs] = useState<Record<string, BaseJob>>({});
  const metadataCache = useRef(new Map<string, ClickCountBaseMetadata>());
  const submitLock = useRef(false);
  const requestControllers = useRef(new Map<string, AbortController>());
  const pollers = useRef(new Map<string, { controller: AbortController; timer?: number }>());
  const selectedKey = bases.map((base) => base.id).join(',');

  const stopPoller = (baseId: string) => {
    const poller = pollers.current.get(baseId);
    if (!poller) return;
    poller.controller.abort();
    clearTimeout(poller.timer);
    pollers.current.delete(baseId);
  };

  useEffect(() => {
    for (const base of bases) {
      if (base.start_date && base.created_at && !metadataCache.current.has(base.id)) {
        metadataCache.current.set(base.id, {
          id: base.id,
          name: base.name,
          start_date: base.start_date,
          created_at: base.created_at,
          timezone: workspace.timezone,
        });
      }
    }
    const selected = new Set(bases.map((base) => base.id));
    setMetadata(Object.fromEntries([...metadataCache.current].filter(([id]) => selected.has(id))));
    setMetadataErrors((current) => Object.fromEntries(Object.entries(current).filter(([id]) => selected.has(id))));
    const missing = bases.filter((base) => !metadataCache.current.has(base.id));
    if (missing.length === 0) {
      setLoadingIds([]);
      return;
    }
    setLoadingIds(missing.map((base) => base.id));
    const controller = new AbortController();
    void (async () => {
      for (const base of missing) {
        if (controller.signal.aborted) break;
        try {
          const value = await fetchClickCountBase(workspace.id, base.id, AbortSignal.any([controller.signal, AbortSignal.timeout(60000)]));
          if (controller.signal.aborted) return;
          metadataCache.current.set(base.id, value);
          setMetadata((current) => ({ ...current, [base.id]: value }));
          setMetadataErrors((current) => {
            const next = { ...current };
            delete next[base.id];
            return next;
          });
        } catch (err) {
          if (!controller.signal.aborted) setMetadataErrors((current) => ({ ...current, [base.id]: errorMessage(err) }));
        } finally {
          if (!controller.signal.aborted) setLoadingIds((current) => current.filter((id) => id !== base.id));
        }
      }
    })();
    return () => controller.abort();
  }, [workspace.id, selectedKey, metadataReload]);

  useEffect(() => {
    const updateToday = () => setToday(todayInTimezone(workspace.timezone));
    let timer: number;
    function tick() {
      updateToday();
      timer = window.setTimeout(tick, 60000 - Date.now() % 60000);
    }
    tick();
    window.addEventListener('focus', updateToday);
    document.addEventListener('visibilitychange', updateToday);
    return () => {
      clearTimeout(timer);
      window.removeEventListener('focus', updateToday);
      document.removeEventListener('visibilitychange', updateToday);
    };
  }, [workspace.timezone]);

  useEffect(() => {
    requestControllers.current.forEach((controller) => controller.abort());
    pollers.current.forEach(({ controller, timer }) => {
      controller.abort();
      clearTimeout(timer);
    });
    requestControllers.current.clear();
    pollers.current.clear();
    setJobs({});
    submitLock.current = false;
  }, [selectedKey]);

  useEffect(() => () => {
    requestControllers.current.forEach((controller) => controller.abort());
    pollers.current.forEach(({ controller, timer }) => {
      controller.abort();
      clearTimeout(timer);
    });
  }, []);

  const busy = Object.values(jobs).some((job) => job.submitting || job.unknownSubmission
    || (job.status?.status === 'queued' || job.status?.status === 'running') && !job.pollingPaused);

  useEffect(() => onBusyChange(busy), [busy, onBusyChange]);
  useEffect(() => () => onBusyChange(false), [onBusyChange]);

  const updateJob = (baseId: string, patch: Partial<BaseJob>) => setJobs((current) => ({
    ...current,
    [baseId]: { ...current[baseId], ...patch },
  }));

  function pollQuery(baseId: string, query: ClickCountQuery) {
    stopPoller(baseId);
    const poller = { controller: new AbortController(), timer: undefined as number | undefined };
    pollers.current.set(baseId, poller);
    async function poll() {
      try {
        const next = await fetchClickCountQuery(query.workspace_id, query.query_id, AbortSignal.any([poller.controller.signal, AbortSignal.timeout(60000)]));
        if (poller.controller.signal.aborted) return;
        updateJob(baseId, { status: next, error: '' });
        if (next.status === 'success' || next.status === 'failed') {
          pollers.current.delete(baseId);
          return;
        }
      } catch (err) {
        if (poller.controller.signal.aborted) return;
        if (isTerminalClickCountError(err)) {
          pollers.current.delete(baseId);
          updateJob(baseId, {
            pollingPaused: true,
            error: `Status checking stopped: ${errorMessage(err)}. This query may still be running on MoEngage.`,
          });
          return;
        }
        updateJob(baseId, { error: `Could not refresh status: ${errorMessage(err)}. Polling will continue.` });
      }
      if (!poller.controller.signal.aborted) poller.timer = window.setTimeout(poll, 2500);
    }
    void poll();
  }

  function pausePolling(baseId: string) {
    stopPoller(baseId);
    updateJob(baseId, {
      pollingPaused: true,
      error: 'Status checking stopped. The query may still be running on MoEngage; stopping checks does not cancel it.',
    });
  }

  function resumePolling(baseId: string) {
    const job = jobs[baseId];
    if (!job?.query || job.status?.status !== 'queued' && job.status?.status !== 'running') return;
    updateJob(baseId, { pollingPaused: false, error: '' });
    pollQuery(baseId, job.query);
  }

  async function startOne(base: ClickCountBaseMetadata) {
    const controller = new AbortController();
    requestControllers.current.set(base.id, controller);
    try {
      const query = await startClickCountQuery(
        { workspace_id: workspace.id, base_id: base.id, end_date: endDate },
        AbortSignal.any([controller.signal, AbortSignal.timeout(60000)]),
      );
      if (controller.signal.aborted) return;
      updateJob(base.id, {
        query,
        status: { query_id: query.query_id, status: query.status, user_count: null, reachable_users: null },
        submitting: false,
      });
      pollQuery(base.id, query);
    } catch (err) {
      if (controller.signal.aborted) return;
      const uncertain = !(err instanceof ClickCountApiError) || err.status === 0 || err.status === 408 || err.status >= 500;
      updateJob(base.id, {
        submitting: false,
        unknownSubmission: uncertain,
        error: `${errorMessage(err)}. This query-start request was not retried.${uncertain ? ' Its outcome is unknown; acknowledge it before running another batch.' : ''}`,
      });
    } finally {
      requestControllers.current.delete(base.id);
    }
  }

  const selectedMetadata = bases.map((base) => metadata[base.id]).filter((base): base is ClickCountBaseMetadata => Boolean(base));
  const maxStartDate = selectedMetadata.reduce((latest, base) => base.start_date > latest ? base.start_date : latest, '');
  const metadataReady = selectedMetadata.length === bases.length && loadingIds.length === 0 && Object.keys(metadataErrors).length === 0;
  const validDates = metadataReady && Boolean(today && isValidClickCountRange(maxStartDate, endDate, workspace.timezone));

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitLock.current || busy || !validDates) return;
    submitLock.current = true;
    setJobs(Object.fromEntries(selectedMetadata.map((base) => [base.id, {
      query: null,
      status: null,
      submitting: true,
      pollingPaused: false,
      unknownSubmission: false,
      error: '',
    }])));
    await Promise.all(selectedMetadata.map(startOne));
  }

  function changeEndDate(value: string) {
    pollers.current.forEach((_poller, baseId) => stopPoller(baseId));
    setEndDate(value);
    setJobs({});
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="min-w-full divide-y divide-gray-200 text-left text-sm">
          <thead className="bg-gray-50 text-xs uppercase text-gray-500">
            <tr><th className="px-3 py-2">Imported base</th><th className="px-3 py-2">Automatic start date</th></tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {bases.map((base) => (
              <tr key={base.id}>
                <td className="px-3 py-2 text-gray-700">{base.name}</td>
                <td className="px-3 py-2 text-gray-600">
                  {loadingIds.includes(base.id) ? 'Loading…' : metadata[base.id]?.start_date || 'Unavailable'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {Object.entries(metadataErrors).map(([baseId, message]) => (
        <ErrorNotice key={baseId} message={`${bases.find((base) => base.id === baseId)?.name || baseId}: ${message}`} />
      ))}
      {Object.keys(metadataErrors).length > 0 && (
        <button type="button" className={secondary} onClick={() => setMetadataReload((value) => value + 1)}>Retry base dates</button>
      )}
      <div>
        <label htmlFor="click-end" className="mb-1 block text-sm font-medium text-gray-700">End date · inclusive for all selected bases</label>
        <input id="click-end" type="date" className={input} value={endDate} min={maxStartDate} max={today} required disabled={busy || !metadataReady || !today || maxStartDate > today} onChange={(event) => changeEndDate(event.target.value)} />
        <p className="mt-1 text-xs text-gray-500">Each base keeps its own automatic start date. The common end date uses {workspace.timezone} and includes the whole selected day.</p>
      </div>
      {today && maxStartDate > today && <p role="alert" className="text-sm text-red-700">At least one selected base was created after today in this workspace; no common date range is available yet.</p>}
      {endDate && !validDates && metadataReady && <p role="alert" className="text-sm text-red-700">Choose an end date from {maxStartDate} through {today}.</p>}
      <button type="submit" className={primary} disabled={!validDates || busy} onClick={(event) => { if (event.detail > 1) event.preventDefault(); }}>
        {busy ? `Counting ${bases.length} bases…` : Object.keys(jobs).length ? `Count ${bases.length} bases again` : `Count ${bases.length} selected ${bases.length === 1 ? 'base' : 'bases'}`}
      </button>
      {Object.keys(jobs).length > 0 && (
        <section className="space-y-3" aria-label="Query results" aria-live="polite">
          {bases.map((base) => {
            const job = jobs[base.id];
            if (!job) return null;
            const status = job.status;
            return (
              <article key={base.id} className="rounded-lg border border-blue-200 bg-blue-50 p-4">
                <h2 className="text-sm font-semibold text-gray-900">{base.name}</h2>
                {job.query && <p className="mt-1 text-xs text-gray-500">{job.query.start_date} – {job.query.end_date} · {job.query.timezone}</p>}
                {job.submitting && <p role="status" className="mt-3 text-sm font-medium text-blue-700">Starting query…</p>}
                {job.error && <div className="mt-3"><ErrorNotice message={job.error} /></div>}
                {job.unknownSubmission && (
                  <button type="button" className={`${secondary} mt-3`} onClick={() => updateJob(base.id, { unknownSubmission: false })}>
                    I understand this query may already exist
                  </button>
                )}
                {status?.status === 'success' && (
                  <>
                    <p className="mt-3 text-4xl font-bold text-blue-800">{status.user_count === null ? 'Count unavailable' : status.user_count.toLocaleString()}</p>
                    <p className="mt-1 text-sm text-gray-600">Unique users who clicked in this imported base.</p>
                    {status.reachable_users !== null && <p className="mt-2 text-xs text-gray-500">Reachable users: {status.reachable_users.toLocaleString()}</p>}
                  </>
                )}
                {status?.status === 'failed' && !job.error && <div className="mt-3"><ErrorNotice message={status.error || 'The click count query failed.'} /></div>}
                {status && (status.status === 'queued' || status.status === 'running') && (
                  <div className="mt-3 space-y-2">
                    <p role="status" className="text-sm font-medium text-blue-700">
                      {job.pollingPaused ? 'Status checking paused; the final outcome is unknown.' : status.status === 'queued' ? 'Query queued…' : 'Query running…'}
                    </p>
                    <button type="button" className={secondary} onClick={() => job.pollingPaused ? resumePolling(base.id) : pausePolling(base.id)}>
                      {job.pollingPaused ? 'Check status again' : 'Stop checking'}
                    </button>
                  </div>
                )}
              </article>
            );
          })}
        </section>
      )}
    </form>
  );
}
