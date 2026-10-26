'use client';

import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import Link from 'next/link';
import { accountOrganization, canAccessAccount } from '@/lib/api';
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
const input = 'w-full rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm outline-none transition-colors focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:cursor-not-allowed disabled:bg-gray-50 disabled:text-gray-500';
const primary = 'rounded-lg bg-blue-600 px-4 py-3 text-sm font-semibold text-white transition-colors hover:bg-blue-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50';
const secondary = 'rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-semibold text-gray-700 transition-colors hover:bg-gray-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50';

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
  const { currentUser, authLoading, account, getAccountLabel } = useApp();
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
  if (accountOrganization(account) !== 'tata') {
    return <div role="status" className={panel}>Select a Tata account to use its saved MoEngage session.</div>;
  }
  return <ClickCountWorkspacePicker key={`${currentUser.id}:${currentUser.tenant_id}:${currentUser.role}:${account}`} account={account} accountLabel={getAccountLabel(account)} />;
}

function ClickCountWorkspacePicker({ account, accountLabel }: { account: string; accountLabel: string }) {
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
        const data = await fetchClickCountWorkspaces(account, AbortSignal.any([controller.signal, AbortSignal.timeout(60000)]));
        if (!controller.signal.aborted) setWorkspaces(data.workspaces);
      } catch (err) {
        if (!controller.signal.aborted) setError(errorMessage(err));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [account, reload]);

  const workspace = workspaces.find((item) => item.id === workspaceId);
  return (
    <div className="mx-auto max-w-7xl space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="mb-2 text-xs font-semibold uppercase tracking-widest text-blue-700">Tata Capital · Audience analytics</p>
          <h1 className="text-3xl font-bold tracking-tight text-gray-900">Tata Click Counter</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-gray-500">See how many unique users clicked across your channels. Select imported bases and count them in one run.</p>
          <p className="mt-2 text-xs text-gray-500">MoEngage session: {accountLabel}. Manage this account&apos;s connection in <Link href="/settings" className="font-medium text-blue-600 underline">Settings → MoEngage</Link>.</p>
        </div>
        <span className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-xs font-medium text-gray-600">Reporting only · No campaigns sent</span>
      </header>
      <aside className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-blue-100 bg-blue-50/60 px-5 py-4" aria-label="How clicks are counted">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wider text-blue-800">Clicks across any of these channels</p>
          <div className="mt-2 flex flex-wrap gap-2">
            {['WhatsApp', 'Email', 'SMS', 'Android push', 'iOS push'].map((channel) => (
              <span key={channel} className="rounded-md border border-blue-100 bg-white px-2.5 py-1 text-xs font-medium text-gray-700">{channel}</span>
            ))}
          </div>
        </div>
        <p className="max-w-sm text-xs leading-5 text-gray-600">Only users in each selected base are counted, once per base. Results stay separate—overlapping bases are never summed.</p>
      </aside>
      <section className={panel} aria-label="Click count selection" aria-busy={loading || busy}>
        <div className="grid items-center gap-4 md:grid-cols-2">
          <div className="flex items-start gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-sm font-bold text-blue-700" aria-hidden="true">1</span>
            <div>
              <h2 className="text-sm font-semibold text-gray-900">Choose your workspace</h2>
              <p className="mt-1 text-xs leading-5 text-gray-500">Bases and results stay within this MoEngage workspace.</p>
            </div>
          </div>
          <div>
            <label htmlFor="click-workspace" className="mb-1.5 block text-xs font-medium text-gray-600">MoEngage workspace</label>
            <select id="click-workspace" className={input} value={workspaceId} disabled={loading || busy || Boolean(error)} onChange={(event) => setWorkspaceId(event.target.value)}>
              <option value="">Select a workspace</option>
              {workspaces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
            {workspace && <p className="mt-1.5 text-xs text-gray-500">Reporting timezone: {workspace.timezone}</p>}
          </div>
        </div>
        {loading && <p role="status" className="mt-4 text-sm text-gray-500">Loading Tata workspaces…</p>}
        {error && <div className="mt-4"><ErrorNotice message={error} onRetry={() => setReload((value) => value + 1)} /></div>}
        {!loading && !error && workspaces.length === 0 && (
          <div className="mt-4 space-y-2">
            <p role="status" className="text-sm text-gray-500">No Tata MoEngage workspaces are available.</p>
            <button type="button" className={secondary} onClick={() => setReload((value) => value + 1)}>Reload workspaces</button>
          </div>
        )}
      </section>
      {workspace ? <ImportedBasePicker key={`${workspace.id}:${workspace.timezone}`} account={account} workspace={workspace} busy={busy} onBusyChange={setBusy} /> : (
        <div className="rounded-xl border border-dashed border-gray-300 px-6 py-14 text-center">
          <h2 className="text-sm font-semibold text-gray-700">Start with a workspace</h2>
          <p className="mt-2 text-sm text-gray-500">Your imported bases and counting options will appear here.</p>
        </div>
      )}
    </div>
  );
}

function ImportedBasePicker({ account, workspace, busy, onBusyChange }: { account: string; workspace: ClickCountWorkspace; busy: boolean; onBusyChange: (value: boolean) => void }) {
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
        const data = await fetchClickCountBases(account, workspace.id, AbortSignal.any([controller.signal, AbortSignal.timeout(60000)]), workspace.timezone);
        if (!controller.signal.aborted) setBases(data.bases);
      } catch (err) {
        if (!controller.signal.aborted) setError(errorMessage(err));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [account, workspace.id, reload]);

  const selected = new Set(selectedIds);
  const searchTerm = search.trim().toLowerCase();
  const filteredBases = bases.filter((base) => selected.has(base.id) || base.name.toLowerCase().includes(searchTerm));
  const selectedBases = bases.filter((base) => selected.has(base.id));

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
    <div className="grid items-start gap-6 xl:grid-cols-12">
      <section className={`${panel} xl:col-span-7`} aria-label="Imported base selection" aria-busy={loading}>
        <div className="mb-5 flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-sm font-bold text-blue-700" aria-hidden="true">2</span>
            <div>
              <h2 className="text-sm font-semibold text-gray-900">Select imported bases</h2>
              <p className="mt-1 text-xs leading-5 text-gray-500">Choose one or more audiences to compare.</p>
            </div>
          </div>
          <span className="shrink-0 rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700">{selectedIds.length} selected</span>
        </div>
        {loading && <p role="status" className="py-8 text-center text-sm text-gray-500">Loading imported bases…</p>}
        {error && <ErrorNotice message={error} onRetry={() => setReload((value) => value + 1)} />}
        {!loading && !error && bases.length === 0 && (
          <div className="space-y-3 rounded-lg bg-gray-50 px-4 py-8 text-center">
            <p role="status" className="text-sm text-gray-500">This workspace has no imported bases.</p>
            <button type="button" className={secondary} onClick={() => setReload((value) => value + 1)}>Reload imported bases</button>
          </div>
        )}
        {!loading && !error && bases.length > 0 && (
          <fieldset>
            <legend className="sr-only">Imported bases · {selectedIds.length} selected</legend>
            <div className="mb-3">
              <label htmlFor="click-base-search" className="sr-only">Search imported bases</label>
              <input id="click-base-search" type="search" className={input} value={search} disabled={busy} onChange={(event) => setSearch(event.target.value)} placeholder="Search imported bases…" />
            </div>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <p className="text-xs text-gray-500">{filteredBases.length} of {bases.length} bases shown</p>
              <div className="flex gap-2">
                <button type="button" className={secondary} disabled={busy || filteredBases.every((base) => selected.has(base.id))} onClick={selectVisible}>Select visible</button>
                <button type="button" className={secondary} disabled={busy || selectedIds.length === 0} onClick={() => setSelectedIds([])}>Clear</button>
              </div>
            </div>
            <div id="click-bases" className="max-h-80 space-y-2 overflow-y-auto">
              {filteredBases.map((base) => {
                const checked = selected.has(base.id);
                return (
                  <label key={base.id} className={`flex items-center gap-3 rounded-lg border p-3 text-sm transition-colors ${busy ? 'cursor-not-allowed' : 'cursor-pointer'} ${checked ? 'border-blue-200 bg-blue-50/60' : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'}`}>
                    <input type="checkbox" className="h-4 w-4 shrink-0 accent-blue-600 focus-visible:ring-2 focus-visible:ring-blue-500" checked={checked} disabled={busy} onChange={() => toggleBase(base.id)} />
                    <span className={`min-w-0 flex-1 break-words ${checked ? 'font-medium text-blue-900' : 'text-gray-700'}`}>{base.name}</span>
                    {checked && <span className="shrink-0 text-xs font-medium text-blue-700">Selected</span>}
                  </label>
                );
              })}
            </div>
            {filteredBases.length === 0 && <p role="status" className="py-8 text-center text-sm text-gray-500">No bases match your search.</p>}
            <p className="mt-4 border-t border-gray-100 pt-3 text-xs leading-5 text-gray-500">Selected bases stay visible while searching. Each base gets its own result.</p>
          </fieldset>
        )}
      </section>
      {selectedBases.length > 0 ? <MultiBaseCountForm account={account} workspace={workspace} bases={selectedBases} onBusyChange={onBusyChange} /> : (
        <aside className={`${panel} xl:col-span-5`}>
          <div className="flex items-start gap-3">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-sm font-bold text-gray-500" aria-hidden="true">3</span>
            <div>
              <h2 className="text-sm font-semibold text-gray-900">Set your date range</h2>
              <p className="mt-1 text-xs leading-5 text-gray-500">Select a base to load its start date and choose an end date.</p>
            </div>
          </div>
          <div className="mt-5 rounded-lg border border-dashed border-gray-200 px-4 py-8 text-center text-sm text-gray-500">Your counting options will appear here.</div>
        </aside>
      )}
    </div>
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

function MultiBaseCountForm({ account, workspace, bases, onBusyChange }: { account: string; workspace: ClickCountWorkspace; bases: ClickCountBase[]; onBusyChange: (value: boolean) => void }) {
  const [metadata, setMetadata] = useState<Record<string, ClickCountBaseMetadata>>({});
  const [metadataErrors, setMetadataErrors] = useState<Record<string, string>>({});
  const [loadingIds, setLoadingIds] = useState<string[]>([]);
  const [metadataReload, setMetadataReload] = useState(0);
  const [today, setToday] = useState('');
  const [endDate, setEndDate] = useState('');
  const [startOverrides, setStartOverrides] = useState<Record<string, string>>({});
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
          const value = await fetchClickCountBase(account, workspace.id, base.id, AbortSignal.any([controller.signal, AbortSignal.timeout(60000)]));
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
  }, [account, workspace.id, selectedKey, metadataReload]);

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
    const selected = new Set(bases.map((base) => base.id));
    setStartOverrides((current) => Object.fromEntries(Object.entries(current).filter(([id]) => selected.has(id))));
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
        const next = await fetchClickCountQuery(account, query.workspace_id, query.query_id, AbortSignal.any([poller.controller.signal, AbortSignal.timeout(60000)]));
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
        account,
        { workspace_id: workspace.id, base_id: base.id, end_date: endDate, ...(startOverrides[base.id] === undefined ? {} : { start_date: startOverrides[base.id] }) },
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
  const maxStartDate = selectedMetadata.reduce((latest, base) => {
    const start = startOverrides[base.id] ?? base.start_date;
    return start > latest ? start : latest;
  }, '');
  const metadataReady = selectedMetadata.length === bases.length && loadingIds.length === 0 && Object.keys(metadataErrors).length === 0;
  const loading = new Set(loadingIds);
  const validDates = metadataReady && Boolean(today) && selectedMetadata.every((base) => isValidClickCountRange(startOverrides[base.id] ?? base.start_date, endDate, workspace.timezone));

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
    try {
      await Promise.all(selectedMetadata.map(startOne));
    } finally {
      submitLock.current = false;
    }
  }

  function clearResults() {
    pollers.current.forEach((_poller, baseId) => stopPoller(baseId));
    setJobs({});
  }

  function changeEndDate(value: string) {
    if (busy || submitLock.current) return;
    clearResults();
    setEndDate(value);
  }

  function changeStartDate(baseId: string, value?: string) {
    if (busy || submitLock.current) return;
    clearResults();
    setStartOverrides((current) => {
      const next = { ...current };
      if (value === undefined) delete next[baseId];
      else next[baseId] = value;
      return next;
    });
  }

  return (
    <>
      <form onSubmit={submit} className={`${panel} space-y-4 xl:col-span-5`}>
        <div className="flex items-start gap-3">
          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-sm font-bold text-blue-700" aria-hidden="true">3</span>
          <div>
            <h2 className="text-sm font-semibold text-gray-900">Set your date range</h2>
            <p className="mt-1 text-xs leading-5 text-gray-500">Start dates are fetched from each base&apos;s creation time. Edit them for your report, or reset to automatic.</p>
          </div>
        </div>
        <div className="max-h-48 overflow-auto rounded-lg border border-gray-200">
          <table className="min-w-full divide-y divide-gray-200 text-left text-xs">
            <caption className="sr-only">Selected bases and editable report start dates</caption>
            <thead className="sticky top-0 bg-gray-50 text-gray-500">
              <tr><th scope="col" className="px-3 py-2.5 font-medium">Selected base</th><th scope="col" className="whitespace-nowrap px-3 py-2.5 font-medium">Start date</th></tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {bases.map((base) => (
                <tr key={base.id}>
                  <td className="break-words px-3 py-3 text-gray-700">{base.name}</td>
                  <td className="whitespace-nowrap px-3 py-3 tabular-nums text-gray-600">
                    {metadata[base.id] ? (
                      <div className="min-w-40 space-y-2">
                        <label htmlFor={`click-start-${base.id}`} className="sr-only">Report start date for {base.name}</label>
                        <input id={`click-start-${base.id}`} type="date" className={input} value={startOverrides[base.id] ?? metadata[base.id].start_date} min="0001-01-01" max={endDate && endDate < today ? endDate : today} required disabled={busy || !today} onChange={(event) => changeStartDate(base.id, event.target.value)} aria-describedby={`click-start-help-${base.id}`} />
                        <p id={`click-start-help-${base.id}`} className="text-[11px] text-gray-500">{startOverrides[base.id] === undefined ? 'Automatic' : 'Manual'} · Base created {metadata[base.id].start_date}</p>
                        <button type="button" className={secondary} disabled={busy || startOverrides[base.id] === undefined} onClick={() => changeStartDate(base.id)}>Reset to automatic</button>
                      </div>
                    ) : loading.has(base.id) ? 'Loading…' : 'Unavailable'}
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
          <label htmlFor="click-end" className="mb-1.5 block text-sm font-medium text-gray-700">Report end date (inclusive)</label>
          <input id="click-end" type="date" className={input} value={endDate} min={maxStartDate} max={today} required aria-describedby="click-date-help" disabled={busy || !metadataReady || !today || maxStartDate > today} onChange={(event) => changeEndDate(event.target.value)} />
          <p id="click-date-help" className="mt-2 text-xs leading-5 text-gray-500">Includes the whole end date in {workspace.timezone}. One end date applies to every selected base.</p>
        </div>
        {today && maxStartDate > today && <p role="alert" className="text-sm text-red-700">At least one report start date is after today in this workspace. Choose an earlier start date.</p>}
        {endDate && !validDates && metadataReady && <p role="alert" className="text-sm text-red-700">Choose valid start dates on or before the end date, and an end date no later than {today}.</p>}
        <div className="border-t border-gray-100 pt-4">
          <button type="submit" className={`${primary} w-full`} disabled={!validDates || busy} onClick={(event) => { if (event.detail > 1) event.preventDefault(); }}>
            {busy ? `Counting ${bases.length} ${bases.length === 1 ? 'base' : 'bases'}…` : Object.keys(jobs).length ? `Count ${bases.length} ${bases.length === 1 ? 'base' : 'bases'} again` : `Count ${bases.length} selected ${bases.length === 1 ? 'base' : 'bases'}`}
          </button>
          <p className="mt-2 text-center text-xs leading-5 text-gray-500">Runs all selected bases together. No messages are sent.</p>
        </div>
      </form>
      <section className="min-w-0 xl:col-span-12" aria-label="Query results" aria-live="polite">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Results by base</h2>
            <p className="mt-1 text-xs text-gray-500">Unique clickers across channels, deduplicated within each base.</p>
          </div>
          {Object.keys(jobs).length > 0 && <span className="text-xs font-medium text-gray-500">{bases.filter((base) => jobs[base.id]?.status?.status === 'success').length} of {bases.length} complete</span>}
        </div>
        {Object.keys(jobs).length === 0 ? (
          <div className="rounded-xl border border-dashed border-gray-300 px-6 py-10 text-center">
            <p className="text-sm font-medium text-gray-700">Ready when you are</p>
            <p className="mt-2 text-xs text-gray-500">Choose an end date and start counting. Each base will appear here separately.</p>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-gray-200 bg-white shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500" role="region" aria-label="Click count results table" tabIndex={0}>
            <table className="w-full min-w-[960px] text-left text-sm">
              <caption className="sr-only">Click count results for each selected base. Counts are separate and are not summed.</caption>
              <thead className="border-b border-gray-200 bg-gray-50 text-xs text-gray-500">
                <tr>
                  <th scope="col" className="px-4 py-3 font-medium">Imported base</th>
                  <th scope="col" className="whitespace-nowrap px-4 py-3 font-medium">Start date</th>
                  <th scope="col" className="whitespace-nowrap px-4 py-3 font-medium">End date</th>
                  <th scope="col" className="px-4 py-3 font-medium">Status</th>
                  <th scope="col" className="whitespace-nowrap px-4 py-3 text-right font-medium">Unique clickers</th>
                  <th scope="col" className="whitespace-nowrap px-4 py-3 text-right font-medium">Reachable users</th>
                  <th scope="col" className="px-4 py-3 font-medium">Details / actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {bases.map((base) => {
                  const job = jobs[base.id];
                  if (!job) return null;
                  const status = job.status;
                  const failed = status?.status === 'failed' || (!job.submitting && !status && Boolean(job.error) && !job.unknownSubmission);
                  const badge = job.submitting ? 'Starting' : job.unknownSubmission ? 'Outcome unknown' : job.pollingPaused ? 'Checking paused' : status?.status === 'success' ? 'Complete' : failed ? 'Failed' : status?.status === 'running' ? 'Running' : 'Queued';
                  const badgeStyle = status?.status === 'success' ? 'bg-emerald-50 text-emerald-700' : failed ? 'bg-red-50 text-red-700' : job.unknownSubmission || job.pollingPaused ? 'bg-amber-50 text-amber-800' : 'bg-blue-50 text-blue-700';
                  return (
                    <tr key={base.id} className="align-top hover:bg-gray-50/50" aria-label={`${base.name} result`}>
                      <th scope="row" className="min-w-[180px] break-words px-4 py-4 font-semibold text-gray-900">{base.name}</th>
                      <td className="whitespace-nowrap px-4 py-4 text-xs leading-5 text-gray-600">
                        {job.query ? (
                          <>
                            <p className="tabular-nums">{job.query.start_date}</p>
                            <p className="text-gray-500">{job.query.timezone}</p>
                          </>
                        ) : <span className="text-gray-400">Awaiting query</span>}
                      </td>
                      <td className="whitespace-nowrap px-4 py-4 text-xs leading-5 tabular-nums text-gray-600">
                        {job.query ? job.query.end_date : <span className="text-gray-400">Awaiting query</span>}
                      </td>
                      <td className="px-4 py-4">
                        <span className={`inline-block whitespace-nowrap rounded-md px-2 py-1 text-[11px] font-semibold ${badgeStyle}`}>{badge}</span>
                      </td>
                      <td className="px-4 py-4 text-right font-semibold tabular-nums text-gray-900">
                        {status?.status === 'success' ? status.user_count === null ? 'Unavailable' : status.user_count.toLocaleString() : <span aria-label="Not available yet" className="font-normal text-gray-400">—</span>}
                      </td>
                      <td className="px-4 py-4 text-right tabular-nums text-gray-700">
                        {status?.status === 'success' && status.reachable_users !== null ? status.reachable_users.toLocaleString() : <span aria-label="Not available yet" className="text-gray-400">—</span>}
                      </td>
                      <td className="min-w-[240px] px-4 py-4">
                        {job.submitting && <p role="status" className="text-xs font-medium text-blue-700">Starting query…</p>}
                        {job.error && <ErrorNotice message={job.error} />}
                        {job.unknownSubmission && (
                          <button type="button" className={`${secondary} mt-3`} onClick={() => updateJob(base.id, { unknownSubmission: false })}>
                            I understand this query may already exist
                          </button>
                        )}
                        {status?.status === 'failed' && !job.error && <ErrorNotice message={status.error || 'The click count query failed.'} />}
                        {status && (status.status === 'queued' || status.status === 'running') && (
                          <div className="space-y-3">
                            <p role="status" className="text-xs font-medium text-blue-700">
                              {job.pollingPaused ? 'Status checking paused; the final outcome is unknown.' : status.status === 'queued' ? 'Query queued…' : 'Query running…'}
                            </p>
                            <button type="button" className={secondary} onClick={() => job.pollingPaused ? resumePolling(base.id) : pausePolling(base.id)}>
                              {job.pollingPaused ? 'Check status again' : 'Stop checking'}
                            </button>
                          </div>
                        )}
                        {status?.status === 'success' && !job.error && <span className="text-xs text-gray-500">No action needed</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
