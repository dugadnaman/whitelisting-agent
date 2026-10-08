'use client';

import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';
import Link from 'next/link';
import { canAccessAccount } from '@/lib/api';
import { useApp } from '@/lib/context';
import {
  fetchClickCountWorkspaces, fetchClickCountBases, fetchClickCountBase,
  startClickCountQuery, fetchClickCountQuery,
} from '@/lib/moengage-click-count';
import type {
  ClickCountWorkspace, ClickCountBase, ClickCountBaseMetadata,
  ClickCountQuery, ClickCountQueryStatus,
} from '@/lib/moengage-click-count';

const panel = 'rounded-xl border border-gray-200 bg-white p-5 shadow-sm';
const input = 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100 disabled:bg-gray-50 disabled:text-gray-500';
const primary = 'rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50';

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function ErrorNotice({ message }: { message: string }) {
  return (
    <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
      <p>{message}</p>
      <p className="mt-1">If the MoEngage session has expired, ask an administrator to reconnect it in <Link href="/settings" className="font-semibold underline">Settings</Link>.</p>
    </div>
  );
}

function todayInTimezone(timezone: string): string {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(new Date());
  return ['year', 'month', 'day'].map((type) => parts.find((part) => part.type === type)?.value).join('-');
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

  useEffect(() => {
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
  }, []);

  const workspace = workspaces.find((item) => item.id === workspaceId);
  return (
    <div className="mx-auto max-w-4xl space-y-5 p-8">
      <header>
        <h1 className="text-2xl font-bold text-gray-900">Tata Click Counts</h1>
        <p className="mt-1 text-sm text-gray-500">Count unique users from an imported MoEngage base across an inclusive date range.</p>
      </header>
      <div className={panel}>
        <h2 className="text-sm font-semibold text-gray-900">Fixed click criteria</h2>
        <p className="mt-2 text-sm text-gray-600">WhatsApp OR Email OR SMS OR Android push OR iOS push clicks, AND membership in the selected imported base. A user is counted once, even if they click multiple times or across channels.</p>
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
        {error && <ErrorNotice message={error} />}
        {!loading && !error && workspaces.length === 0 && <p role="status" className="text-sm text-gray-500">No Tata MoEngage workspaces are available.</p>}
        {workspace && <ImportedBasePicker key={workspace.id} workspace={workspace} busy={busy} onBusyChange={setBusy} />}
      </section>
    </div>
  );
}

function ImportedBasePicker({ workspace, busy, onBusyChange }: { workspace: ClickCountWorkspace; busy: boolean; onBusyChange: (value: boolean) => void }) {
  const [bases, setBases] = useState<ClickCountBase[]>([]);
  const [baseId, setBaseId] = useState('');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
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
  }, [workspace.id]);

  const filteredBases = bases.filter((base) => base.id === baseId || base.name.toLowerCase().includes(search.trim().toLowerCase()));
  return (
    <>
      {bases.length > 20 && (
        <div>
          <label htmlFor="click-base-search" className="mb-1 block text-sm font-medium text-gray-700">Search imported bases</label>
          <input id="click-base-search" type="search" className={input} value={search} disabled={busy} onChange={(event) => setSearch(event.target.value)} placeholder="Search by base name" />
        </div>
      )}
      <div>
        <label htmlFor="click-base" className="mb-1 block text-sm font-medium text-gray-700">Imported base</label>
        <select id="click-base" className={input} value={baseId} disabled={loading || busy || Boolean(error) || !bases.length} onChange={(event) => setBaseId(event.target.value)}>
          <option value="">Select an imported base</option>
          {filteredBases.map((base) => <option key={base.id} value={base.id}>{base.name}</option>)}
        </select>
      </div>
      {loading && <p role="status" className="text-sm text-gray-500">Loading imported bases…</p>}
      {error && <ErrorNotice message={error} />}
      {!loading && !error && bases.length === 0 && <p role="status" className="text-sm text-gray-500">This workspace has no imported bases.</p>}
      {!loading && bases.length > 0 && filteredBases.length === 0 && <p role="status" className="text-sm text-gray-500">No bases match your search.</p>}
      {baseId && <BaseCountForm key={baseId} workspace={workspace} baseId={baseId} onBusyChange={onBusyChange} />}
    </>
  );
}

function BaseCountForm({ workspace, baseId, onBusyChange }: { workspace: ClickCountWorkspace; baseId: string; onBusyChange: (value: boolean) => void }) {
  const [metadata, setMetadata] = useState<ClickCountBaseMetadata | null>(null);
  const [loading, setLoading] = useState(true);
  const [metadataError, setMetadataError] = useState('');
  const [endDate, setEndDate] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [query, setQuery] = useState<ClickCountQuery | null>(null);
  const [status, setStatus] = useState<ClickCountQueryStatus | null>(null);
  const [queryError, setQueryError] = useState('');
  const submitLock = useRef(false);
  const requestController = useRef<AbortController | null>(null);
  const busy = submitting || status?.status === 'queued' || status?.status === 'running';

  useEffect(() => {
    onBusyChange(busy);
    return () => onBusyChange(false);
  }, [busy, onBusyChange]);

  useEffect(() => () => requestController.current?.abort(), []);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const data = await fetchClickCountBase(workspace.id, baseId, AbortSignal.any([controller.signal, AbortSignal.timeout(60000)]));
        if (!controller.signal.aborted) setMetadata(data);
      } catch (err) {
        if (!controller.signal.aborted) setMetadataError(errorMessage(err));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [workspace.id, baseId]);

  useEffect(() => {
    if (!query) return;
    const activeQuery = query;
    const controller = new AbortController();
    let timer: number | undefined;
    async function poll() {
      try {
        const next = await fetchClickCountQuery(activeQuery.workspace_id, activeQuery.query_id, AbortSignal.any([controller.signal, AbortSignal.timeout(60000)]));
        if (controller.signal.aborted) return;
        setStatus(next);
        setQueryError('');
        if (next.status === 'success' || next.status === 'failed') {
          submitLock.current = false;
          return;
        }
      } catch (err) {
        if (controller.signal.aborted) return;
        setQueryError(`Could not refresh the query status: ${errorMessage(err)}. Status polling will continue; another query cannot be started yet.`);
      }
      if (!controller.signal.aborted) timer = window.setTimeout(poll, 2500);
    }
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [query]);

  const today = metadata ? todayInTimezone(metadata.timezone) : '';
  const validDates = Boolean(metadata && endDate && endDate >= metadata.start_date && endDate <= today);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitLock.current || busy || !metadata || !validDates) return;
    submitLock.current = true;
    onBusyChange(true);
    const controller = new AbortController();
    requestController.current = controller;
    setSubmitting(true);
    setQuery(null);
    setStatus(null);
    setQueryError('');
    try {
      const accepted = await startClickCountQuery({ workspace_id: workspace.id, base_id: metadata.id, end_date: endDate }, AbortSignal.any([controller.signal, AbortSignal.timeout(60000)]));
      if (controller.signal.aborted) return;
      setQuery(accepted);
      setStatus({ query_id: accepted.query_id, status: accepted.status, user_count: null, reachable_users: null });
    } catch (err) {
      if (controller.signal.aborted) return;
      submitLock.current = false;
      setQueryError(`${errorMessage(err)}. The query-start request was not automatically retried.`);
    } finally {
      if (!controller.signal.aborted) setSubmitting(false);
    }
  }

  return (
    <>
      {loading && <p role="status" className="text-sm text-gray-500">Loading base creation date…</p>}
      {metadataError && <ErrorNotice message={metadataError} />}
      {metadata && (
        <form onSubmit={submit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="click-start" className="mb-1 block text-sm font-medium text-gray-700">Start date · automatic</label>
              <input id="click-start" type="date" className={input} value={metadata.start_date} disabled readOnly aria-describedby="click-timezone" />
            </div>
            <div>
              <label htmlFor="click-end" className="mb-1 block text-sm font-medium text-gray-700">End date · inclusive</label>
              <input id="click-end" type="date" className={input} value={endDate} min={metadata.start_date} max={today} required disabled={busy || metadata.start_date > today} onChange={(event) => { setEndDate(event.target.value); setQuery(null); setStatus(null); setQueryError(''); }} aria-describedby="click-timezone" />
            </div>
          </div>
          <p id="click-timezone" className="text-xs text-gray-500">Dates use {metadata.timezone}. The start date is derived by the server from this base’s creation timestamp ({metadata.created_at}); the end date includes the whole selected day.</p>
          {metadata.start_date > today && <p role="alert" className="text-sm text-red-700">This base’s creation date is after today in its workspace timezone; no valid date range is available yet.</p>}
          {endDate && !validDates && <p role="alert" className="text-sm text-red-700">Choose an end date from {metadata.start_date} through {today}.</p>}
          <button type="submit" className={primary} disabled={!validDates || busy}>{submitting ? 'Starting query…' : busy ? 'Counting unique users…' : 'Count unique users'}</button>
        </form>
      )}
      {queryError && <ErrorNotice message={queryError} />}
      {query && status && (
        <section className="rounded-lg border border-blue-200 bg-blue-50 p-4" aria-label="Query result" aria-live="polite" aria-atomic="true">
          <h2 className="text-sm font-semibold text-gray-900">{status.status === 'success' ? 'Unique users who clicked' : 'Click count query'}</h2>
          <dl className="mt-2 space-y-1 text-sm text-gray-600">
            <div><dt className="inline font-medium">Workspace: </dt><dd className="inline">{query.workspace_name} ({query.workspace_id})</dd></div>
            <div><dt className="inline font-medium">Imported base: </dt><dd className="inline">{query.base_name} ({query.base_id})</dd></div>
            <div><dt className="inline font-medium">Inclusive range: </dt><dd className="inline">{query.start_date} – {query.end_date} · {query.timezone}</dd></div>
          </dl>
          {status.status === 'success' ? (
            <>
              <p className="mt-4 text-4xl font-bold text-blue-800">{status.user_count === null ? 'Count unavailable' : status.user_count.toLocaleString()}</p>
              <p className="mt-1 text-sm text-gray-600">Deduplicated users matching the five click events and imported-base membership.</p>
              {status.reachable_users !== null && <p className="mt-2 text-xs text-gray-500">Reachable users: {status.reachable_users.toLocaleString()} (a separate metric, not the unique-click count).</p>}
            </>
          ) : status.status === 'failed' ? <ErrorNotice message={status.error || 'The click count query failed.'} /> : <p role="status" className="mt-3 text-sm font-medium text-blue-700">{status.status === 'queued' ? 'Query queued…' : 'Query running…'} Selection is locked until this query finishes.</p>}
        </section>
      )}
    </>
  );
}
