'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { useTabState } from '@/lib/tab-state';
import Link from 'next/link';
import { useApp } from '@/lib/context';
import {
  ATTRIBUTION_CHANNELS, AttributionApiError, canManageApparelAttribution, canUseApparelAttribution,
  cancelAttributionJob, connectAttributionSheet, downloadAttributionCsv, fetchAttributionGoogleConfig,
  fetchAttributionHealth, fetchAttributionJob, fetchAttributionJobs, fetchAttributionPreview,
  fetchAttributionSession, fetchAttributionSetup, isAttributionJobActive,
  retryFailedAttributionJob, saveAttributionSetup, startAttributionJob,
  uploadAttributionGoogleKey,
} from '@/lib/apparel-attribution';
import type {
  AttributionChannel, AttributionHealth, AttributionJob, AttributionSelection, AttributionSetup,
  CampaignPreview, GoogleConfiguration, MoEngageSession, SheetConnection, StartAttributionJobResponse,
} from '@/lib/apparel-attribution';

const panel = 'workspace-panel min-w-0 p-5 sm:p-6';
const input = 'workspace-input w-full tabular-nums disabled:bg-gray-50 disabled:text-gray-500';
const button = 'workspace-button';
const primary = 'workspace-button-primary';
type Resource = 'health' | 'google' | 'session' | 'jobs' | 'setup';

function StatusBadge({ value }: { value: string }) {
  const good = ['ok', 'connected', 'completed', 'success', 'configured'].includes(value);
  const bad = ['failed', 'disconnected', 'not_configured', 'unavailable'].includes(value);
  return <span className={`inline-flex rounded-md px-2 py-1 text-sm font-normal ${good ? 'bg-emerald-50 text-emerald-700' : bad ? 'bg-red-50 text-red-700' : 'bg-amber-50 text-amber-800'}`}>{value.replaceAll('_', ' ')}</span>;
}

export default function ApparelAttributionPage() {
  const { account, currentUser, authLoading, mounted } = useApp();
  if (!mounted || authLoading) return <div className="p-8 text-sm text-gray-500" role="status">Checking your access…</div>;
  if (!canUseApparelAttribution(currentUser, account)) {
    return (
      <div className="mx-auto max-w-3xl p-8">
        <div className={`${panel} border-red-200`}>
          <h1 className="text-xl font-medium text-gray-900">Apparel Attribution access denied</h1>
          <p className="mt-2 text-sm text-gray-600">This workspace is restricted to authorised Apparel operators and admins. A platform superadmin must select Apparel in the account selector before opening it.</p>
          <Link href="/" className="mt-4 inline-block text-sm font-medium text-blue-600">Return to your dashboard</Link>
        </div>
      </div>
    );
  }
  return <AttributionWorkspace key={`${currentUser?.id}:${currentUser?.role}:${account}`} isAdmin={canManageApparelAttribution(currentUser)} />;
}

function AttributionWorkspace({ isAdmin }: { isAdmin: boolean }) {
  const [health, setHealth] = useState<AttributionHealth | null>(null);
  const [google, setGoogle] = useState<GoogleConfiguration | null>(null);
  const [session, setSession] = useState<MoEngageSession | null>(null);
  const [setup, setSetup] = useState<AttributionSetup | null>(null);
  const [resourceErrors, setResourceErrors] = useState<Partial<Record<Resource, string>>>({});
  const [loading, setLoading] = useState(true);
  const [pending, setPending] = useState('');
  const [actionError, setActionError] = useState('');
  const [notice, setNotice] = useState('');
  const [requiresRefresh, setRequiresRefresh] = useState(false);
  const [connection, setConnection] = useState<SheetConnection | null>(null);
  const [brands, setBrands] = useTabState<string[]>('attr_brands', []);
  const [channels, setChannels] = useTabState<AttributionChannel[]>('attr_channels', []);
  const [dateFrom, setDateFrom] = useTabState<string>('attr_date_from', '');
  const [dateTo, setDateTo] = useTabState<string>('attr_date_to', '');
  const [rowLimit, setRowLimit] = useTabState<string>('attr_row_limit', '');
  const [agiplTarget, setAgiplTarget] = useTabState<string>('attr_agipl_target', '');
  const [overwrite, setOverwrite] = useTabState<boolean>('attr_overwrite', false);
  const [preview, setPreview] = useState<{ key: string; data: CampaignPreview } | null>(null);
  const [jobs, setJobs] = useState<AttributionJob[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedJob, setSelectedJob] = useState<AttributionJob | null>(null);
  const [accepted, setAccepted] = useState<StartAttributionJobResponse | null>(null);
  const [pollError, setPollError] = useState('');
  const [jobRefresh, setJobRefresh] = useState(0);
  const [setupUrl, setSetupUrl] = useState('');
  const [setupWorksheet, setSetupWorksheet] = useState('');
  const [reportJson, setReportJson] = useState('');
  const [credential, setCredential] = useState<File | null>(null);
  const live = useRef(false);
  const lifetime = useRef<AbortController | null>(null);
  const pendingRef = useRef(false);
  const selectedRef = useRef<string | null>(null);
  const setupLoaded = useRef(false);
  const connectionRef = useRef<SheetConnection | null>(null);
  const selectJob = useCallback((jobId: string) => {
    selectedRef.current = jobId;
    setSelectedId(jobId);
    setSelectedJob((old) => old?.job_id === jobId ? old : null);
    setPollError('');
  }, []);

  const storeJob = useCallback((job: AttributionJob) => {
    setJobs((old) => [job, ...old.filter((item) => item.job_id !== job.job_id)].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 30));
    if (selectedRef.current === job.job_id) setSelectedJob(job);
    if (!isAttributionJobActive(job.status)) setAccepted((old) => old?.job_id === job.job_id ? null : old);
  }, []);

  const refreshDashboard = useCallback(async (): Promise<boolean> => {
    const controller = lifetime.current;
    if (!controller || controller.signal.aborted) return false;
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(60000)]);
    const [healthResult, googleResult, sessionResult, jobsResult, setupResult] = await Promise.allSettled([
      fetchAttributionHealth(signal), fetchAttributionGoogleConfig(signal), fetchAttributionSession(signal),
      fetchAttributionJobs(signal), isAdmin ? fetchAttributionSetup(signal) : Promise.resolve(null),
    ]);
    if (!live.current || controller.signal.aborted) return false;
    const errors: Partial<Record<Resource, string>> = {};
    if (healthResult.status === 'fulfilled') setHealth(healthResult.value);
    else { setHealth(null); errors.health = String(healthResult.reason?.message || healthResult.reason); }
    if (googleResult.status === 'fulfilled') {
      const gValue = googleResult.value;
      setGoogle(gValue);
      if (connectionRef.current && (
        connectionRef.current.spreadsheet_url !== gValue.spreadsheet_url ||
        connectionRef.current.worksheet_title !== gValue.worksheet_name
      )) {
        connectionRef.current = null;
        setConnection(null);
        setPreview(null);
      }
      if (!connectionRef.current && gValue?.configured && gValue.spreadsheet_url && gValue.worksheet_name) {
        try {
          const connValue = await connectAttributionSheet({
            spreadsheet_url: gValue.spreadsheet_url,
            worksheet_name: gValue.worksheet_name,
          });
          if (live.current) {
            connectionRef.current = connValue;
            setConnection(connValue);
            setBrands((old) => (old.length ? old.filter((brand) => connValue.brands.includes(brand)) : connValue.brands));
          }
        } catch (err) {
          errors.google = `Could not connect the approved sheet: ${err instanceof Error ? err.message : String(err)}`;
        }
      }
    } else { setGoogle(null); errors.google = String(googleResult.reason?.message || googleResult.reason); }
    if (sessionResult.status === 'fulfilled') {
      setSession(sessionResult.value);
    } else { setSession(null); errors.session = String(sessionResult.reason?.message || sessionResult.reason); }
    if (jobsResult.status === 'fulfilled') {
      const history = jobsResult.value.jobs;
      setJobs(history);
      const active = history.find((job) => isAttributionJobActive(job.status));
      if (active) selectJob(active.job_id);
      else if (!selectedRef.current && history.length) selectJob(history[0].job_id);
      setAccepted((old) => old && history.some((job) => job.job_id === old.job_id && isAttributionJobActive(job.status)) ? old : null);
      setJobRefresh((old) => old + 1);
    } else errors.jobs = String(jobsResult.reason?.message || jobsResult.reason);
    if (setupResult.status === 'fulfilled' && setupResult.value) {
      const value = setupResult.value;
      setSetup(value);
      if (!setupLoaded.current) {
        setSetupUrl(value.spreadsheet_url || '');
        setSetupWorksheet(value.worksheet_name || '');
        setReportJson(JSON.stringify(value.ui_config, null, 2));
        setupLoaded.current = true;
      }
    } else if (setupResult.status === 'rejected') errors.setup = String(setupResult.reason?.message || setupResult.reason);
    setResourceErrors(errors);
    setLoading(false);
    const confirmed = !errors.health && !errors.google && !errors.session && !errors.jobs && (!isAdmin || !errors.setup);
    if (confirmed) setRequiresRefresh(false);
    return confirmed;
  }, [isAdmin, selectJob]);

  useEffect(() => {
    live.current = true;
    const controller = new AbortController();
    lifetime.current = controller;
    void refreshDashboard();
    return () => { live.current = false; controller.abort(); };
  }, [refreshDashboard]);
  // Poll only session readiness; query execution happens over HTTP on the server.
  useEffect(() => {
    if (session?.status === 'connected') return;
    const controller = new AbortController();
    let timer: number | undefined;
    const poll = async () => {
      try {
        const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]);
        const next = await fetchAttributionSession(signal);
        if (controller.signal.aborted || !live.current) return;
        setSession(next);
        setResourceErrors((old) => { const errors = { ...old }; delete errors.session; return errors; });
        if (next.status === 'connected') { void refreshDashboard(); return; }
      } catch (error) {
        if (controller.signal.aborted || !live.current) return;
        setResourceErrors((old) => ({ ...old, session: error instanceof Error ? error.message : String(error) }));
      }
      timer = window.setTimeout(poll, 3000);
    };
    timer = window.setTimeout(poll, 3000);
    return () => { controller.abort(); clearTimeout(timer); };
  }, [session?.status, refreshDashboard]);

  const loseJob = useCallback((jobId: string) => {
    setJobs((old) => old.filter((job) => job.job_id !== jobId));
    setAccepted((old) => old?.job_id === jobId ? null : old);
    if (selectedRef.current === jobId) {
      selectedRef.current = null;
      setSelectedId(null);
      setSelectedJob(null);
    }
    setConnection(null);
    connectionRef.current = null;
    setPreview(null);
    setPollError('');
    setRequiresRefresh(true);
    setNotice('This job is no longer available. The worker may have restarted; history and sheet connections are held in memory. Existing sheet results are retained. Refresh status, reconnect the approved sheet, preview again, and rerun with overwrite unchecked to preserve completed rows.');
    void refreshDashboard();
  }, [refreshDashboard]);

  const activeHistoryJob = jobs.find((job) => isAttributionJobActive(job.status));
  const pollingId = accepted && isAttributionJobActive(accepted.status) ? accepted.job_id : activeHistoryJob?.job_id || (selectedJob && isAttributionJobActive(selectedJob.status) ? selectedJob.job_id : null);

  useEffect(() => {
    if (!pollingId) return;
    const controller = new AbortController();
    let timer: number | undefined;
    const poll = async () => {
      try {
        const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]);
        const job = await fetchAttributionJob(pollingId, signal);
        if (controller.signal.aborted || !live.current) return;
        storeJob(job);
        setPollError('');
        if (!isAttributionJobActive(job.status)) { void refreshDashboard(); return; }
      } catch (error) {
        if (controller.signal.aborted || !live.current) return;
        if (error instanceof AttributionApiError && error.status === 404) { loseJob(pollingId); return; }
        setPollError(`Connection to the job was lost: ${error instanceof Error ? error.message : String(error)}. Polling will continue; no replacement run is allowed until its status is known.`);
      }
      if (!controller.signal.aborted) timer = window.setTimeout(poll, 2500);
    };
    void poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [pollingId, storeJob, refreshDashboard, loseJob]);

  useEffect(() => {
    if (!selectedId || selectedId === pollingId) return;
    const controller = new AbortController();
    const load = async () => {
      try {
        const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(30000)]);
        const job = await fetchAttributionJob(selectedId, signal);
        if (!controller.signal.aborted && live.current) { storeJob(job); setPollError(''); }
      } catch (error) {
        if (controller.signal.aborted || !live.current) return;
        if (error instanceof AttributionApiError && error.status === 404) loseJob(selectedId);
        else setPollError(`Could not load this job: ${error instanceof Error ? error.message : String(error)}. Refresh status to try again.`);
      }
    };
    void load();
    return () => controller.abort();
  }, [selectedId, pollingId, jobRefresh, storeJob, loseJob]);

  async function perform(name: string, action: () => Promise<void>, mutating = true) {
    if (pendingRef.current) return;
    pendingRef.current = true;
    setPending(name);
    setActionError('');
    try {
      await action();
    } catch (error) {
      if (!live.current) return;
      const uncertain = mutating && (!(error instanceof AttributionApiError) || error.status >= 500);
      setActionError(`${error instanceof Error ? error.message : String(error)}${uncertain ? ' The request outcome is not confirmed. Refresh status before submitting again; it was not automatically retried.' : ''}`);
      if (uncertain) setRequiresRefresh(true);
      if (error instanceof AttributionApiError && error.status === 404) {
        if ((name === 'retry' || name === 'cancel') && selectedRef.current) loseJob(selectedRef.current);
        else if (name === 'run' || name === 'connect') {
          setConnection(null); connectionRef.current = null; setPreview(null);
          setNotice('The approved sheet connection is unavailable. Reconnect the sheet and preview again before running.');
        }
      }
      if (error instanceof AttributionApiError && error.status === 409) void refreshDashboard();
    } finally {
      pendingRef.current = false;
      if (live.current) setPending('');
    }
  }

  const supportedBrands = health?.configured_brands || [];
  const targetBrands = supportedBrands.filter((brand) => brand.toLowerCase() !== 'agipl');
  const hasAgipl = brands.some((brand) => brand.toLowerCase() === 'agipl');
  const selection: AttributionSelection = {
    brands, channels, sent_date_from: dateFrom, sent_date_to: dateTo,
    ...(rowLimit ? { row_limit: Number(rowLimit) } : {}),
    ...(hasAgipl ? { agipl_attribution_brand: agiplTarget } : {}),
  };
  const selectionKey = JSON.stringify([connection?.connection_id, brands, channels, dateFrom, dateTo, rowLimit, hasAgipl ? agiplTarget : '']);
  const currentPreview = preview?.key === selectionKey ? preview.data : null;
  const selectionErrors: string[] = [];
  if (!connection) selectionErrors.push('Connect the approved Apparel sheet first.');
  if (!brands.length) selectionErrors.push('Select at least one brand.');
  if (brands.some((brand) => !supportedBrands.some((supported) => supported.toLowerCase() === brand.toLowerCase()))) selectionErrors.push('A selected brand has no configured MoEngage report; ask an Apparel admin to configure it.');
  if (!channels.length) selectionErrors.push('Select at least one channel.');
  if (!dateFrom || !dateTo) selectionErrors.push('Choose both sent-date bounds.');
  else if (dateFrom > dateTo) selectionErrors.push('The end date must be on or after the start date.');
  else if ((Date.parse(dateTo) - Date.parse(dateFrom)) / 86400000 > 366) selectionErrors.push('Choose a sent-date range no longer than 366 days.');
  if (rowLimit && (!Number.isInteger(Number(rowLimit)) || Number(rowLimit) < 1 || Number(rowLimit) > 10000)) selectionErrors.push('Row limit must be a whole number from 1 to 10,000, or left blank.');
  if (hasAgipl && !targetBrands.includes(agiplTarget)) selectionErrors.push('Choose a supported attribution brand for AGIPL, excluding AGIPL itself.');
  const locked = loading || Boolean(pending || pollingId || requiresRefresh || resourceErrors.jobs);
  const ready = Boolean(health && health.moengage_mode === 'api' && google?.configured && session?.status === 'connected' && !resourceErrors.health && !resourceErrors.google && !resourceErrors.session);
  const approvedUrl = google?.spreadsheet_url && /^https:\/\/docs\.google\.com\/spreadsheets\//i.test(google.spreadsheet_url) ? google.spreadsheet_url : null;

  async function connectSheet() {
    if (locked || !google?.configured || !google.spreadsheet_url || !google.worksheet_name) return;
    await perform('connect', async () => {
      setPreview(null);
      const value = await connectAttributionSheet({ spreadsheet_url: google.spreadsheet_url, worksheet_name: google.worksheet_name });
      if (!live.current) return;
      connectionRef.current = value;
      setConnection(value);
      setBrands((old) => (old.length ? old.filter((brand) => value.brands.includes(brand)) : value.brands));
      setNotice(`Connected to ${value.spreadsheet_title} / ${value.worksheet_title}.`);
    });
  }

  async function previewCampaigns() {
    if (locked || selectionErrors.length || !connection) return;
    await perform('preview', async () => {
      setPreview(null);
      try {
        const value = await fetchAttributionPreview(connection.connection_id, selection);
        if (live.current) setPreview({ key: selectionKey, data: value });
      } catch (error) {
        if (live.current && error instanceof AttributionApiError && error.status === 404) {
          setConnection(null); connectionRef.current = null; setPreview(null);
          setNotice('The sheet connection was lost, possibly after a worker restart. Reconnect the approved sheet and preview again.');
        }
        throw error;
      }
    }, false);
  }

  function acceptJob(value: StartAttributionJobResponse) {
    if (!live.current) return;
    setAccepted(value);
    selectJob(value.job_id);
    setNotice('The worker accepted the job. Results below come from the live job; sheet writes happen as rows complete.');
    if (!isAttributionJobActive(value.status)) setJobRefresh((old) => old + 1);
  }

  async function runJob() {
    if (locked || !ready || selectionErrors.length || !currentPreview?.row_count || !connection) return;
    if (overwrite && !window.confirm('Replace existing attribution metrics for the selected campaigns in the approved Apparel sheet? Leave overwrite unchecked to preserve completed rows.')) return;
    await perform('run', async () => {
      const history = await fetchAttributionJobs();
      if (!live.current) return;
      setJobs(history.jobs);
      const active = history.jobs.find((job) => isAttributionJobActive(job.status));
      if (active) { selectJob(active.job_id); throw new AttributionApiError('Another attribution job is already active. Its progress is shown below; wait or cancel it before running.', 409); }
      acceptJob(await startAttributionJob({ ...selection, sheet_connection_id: connection.connection_id, overwrite_existing: overwrite }));
    });
  }

  async function retryFailed() {
    if (locked || !ready || !selectedJob?.failed_rows) return;
    await perform('retry', async () => {
      const history = await fetchAttributionJobs();
      if (!live.current) return;
      setJobs(history.jobs);
      const active = history.jobs.find((job) => isAttributionJobActive(job.status));
      if (active) { selectJob(active.job_id); throw new AttributionApiError('Another attribution job is already active. Wait or cancel it before retrying.', 409); }
      acceptJob(await retryFailedAttributionJob(selectedJob.job_id));
    });
  }

  async function saveSetup() {
    if (locked || !isAdmin || !setup) return;
    await perform('setup', async () => {
      let uiConfig: unknown;
      try { uiConfig = JSON.parse(reportJson); }
      catch { throw new AttributionApiError('Enter valid MoEngage report configuration JSON.', 422); }
      if (!uiConfig || typeof uiConfig !== 'object' || Array.isArray(uiConfig)) throw new AttributionApiError('MoEngage report configuration must be a JSON object.', 422);
      const value = await saveAttributionSetup({ spreadsheet_url: setupUrl.trim(), worksheet_name: setupWorksheet.trim(), ui_config: uiConfig as Record<string, unknown> });
      if (!live.current) return;
      setSetup(value);
      setSetupUrl(value.spreadsheet_url);
      setSetupWorksheet(value.worksheet_name);
      setReportJson(JSON.stringify(value.ui_config, null, 2));
      setConnection(null); connectionRef.current = null; setPreview(null); setBrands([]); setAgiplTarget('');
      setNotice('Approved source and report configuration saved. Reconnect the sheet and preview before running.');
      await refreshDashboard();
    });
  }

  return (
    <div className="workspace-page mx-auto w-full min-w-0 max-w-7xl space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="workspace-eyebrow">Apparel · Reporting</div>
          <h1 className="workspace-heading mt-1">Campaign attribution</h1>
          <p className="workspace-description mt-2 max-w-3xl">Read real MoEngage reports and update the approved Google sheet. Attribution channels are independent of the template channel in the sidebar.</p>
        </div>
        <button className={button} disabled={Boolean(pending)} onClick={() => void perform('refresh', async () => { await refreshDashboard(); }, false)}>{pending === 'refresh' ? 'Refreshing…' : 'Refresh status and history'}</button>
      </header>
      <aside className="workspace-guide" aria-label="Attribution workflow">
        <h2 className="text-sm font-medium text-gray-900">Connect, preview, then run</h2>
        <p className="mt-1 text-sm leading-6 text-gray-600">Confirm the Apparel Google sheet and MoEngage session separately below. Choose your source campaigns and review a fresh preview before running. Completed sheet rows are preserved unless you explicitly enable overwrite.</p>
      </aside>

      {loading && <p role="status" className="text-sm text-gray-500">Checking the attribution worker, sheet configuration and MoEngage session…</p>}
      {Object.entries(resourceErrors).map(([resource, message]) => <div key={resource} role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800"><strong className="font-medium">{resource === 'health' ? 'Attribution worker' : resource === 'google' ? 'Google configuration' : resource === 'session' ? 'MoEngage session' : resource === 'jobs' ? 'Job history' : 'Admin setup'}:</strong> {message}</div>)}
      {actionError && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">{actionError}</div>}
      {notice && <div role="status" className="workspace-guide text-sm text-gray-700">{notice}</div>}
      {requiresRefresh && <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">Actions are paused until a successful status refresh confirms the worker state. Do not repeat an unconfirmed write.</div>}

      <section aria-label="Integration status" className="grid gap-4 md:grid-cols-3">
        <div className={panel}>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2"><h2 className="font-medium text-gray-900">Attribution worker</h2><StatusBadge value={health ? health.worker_configured === false ? 'not_configured' : health.status : resourceErrors.health ? 'unavailable' : 'checking'} /></div>
          {health ? <><p className="text-sm text-gray-600">Report mode: <strong className="font-medium">Direct MoEngage HTTP</strong></p><p className="mt-1 text-sm text-gray-500">Configured brands: {supportedBrands.length ? supportedBrands.join(', ') : 'None'}</p>{!supportedBrands.length && <p className="mt-2 text-sm text-amber-800">Ask an Apparel admin to configure the workspace mappings.</p>}</> : <p className="text-sm text-gray-500">{resourceErrors.health ? 'Attribution is unavailable in the main application. Refresh status or contact an administrator.' : 'Waiting for a live response.'}</p>}
        </div>
        <div className={panel}>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-medium text-gray-900">Google sheet</h2>
            <StatusBadge value={connection ? 'connected' : resourceErrors.google ? 'unavailable' : loading ? 'checking' : google?.configured ? 'not_connected' : 'not_configured'} />
          </div>
          {connection ? (
            <>
              <p className="break-words text-sm font-medium text-gray-900">{connection.spreadsheet_title}</p>
              <p className="mt-1 text-sm text-gray-600">Tab: <strong className="font-medium">{connection.worksheet_title}</strong> · {connection.row_count.toLocaleString()} campaigns loaded</p>
              <p className="mt-2 text-sm text-gray-500">Setup is saved server-side. Reconnect after an application restart.</p>
            </>
          ) : (
            <>
              <p className="text-sm text-gray-600">{loading ? 'Checking the approved sheet connection…' : google?.configured ? 'Google credentials are configured. The approved sheet connection is not confirmed.' : 'Google credentials and an approved sheet must be configured by an Apparel admin.'}</p>
              {google?.worksheet_name && <p className="mt-1 break-words text-sm text-gray-500">Worksheet: {google.worksheet_name}</p>}
              <button className={`${button} mt-3`} disabled={locked || !google?.configured || !approvedUrl || !google.worksheet_name} onClick={() => void connectSheet()}>
                {pending === 'connect' ? 'Connecting…' : 'Reconnect sheet'}
              </button>
            </>
          )}
          {approvedUrl && (
            <a href={approvedUrl} target="_blank" rel="noopener noreferrer" className="mt-3 inline-block break-all text-sm font-medium text-indigo-700 underline">
              Open approved sheet
            </a>
          )}
        </div>
        <div className={panel}>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-2"><h2 className="font-medium text-gray-900">MoEngage</h2><StatusBadge value={session?.status || (resourceErrors.session ? 'unavailable' : 'checking')} /></div>
          <p className="text-sm text-gray-600">{session?.message || 'Checking the Apparel MoEngage HTTP session.'}</p>
          {session && session.status !== 'connected' && <p className="mt-2 text-sm text-amber-800">{isAdmin ? 'Connect Apparel Auth Sync or refresh the Apparel session in Settings → MoEngage, then refresh status.' : 'Ask an Apparel admin to reconnect Apparel Auth Sync, then refresh status.'}</p>}
        </div>
      </section>

      <section className={panel} aria-labelledby="selection-heading">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="workspace-eyebrow">Campaign selection</p>
            <h2 id="selection-heading" className="mt-1 text-lg font-medium text-gray-900">Choose source rows</h2>
          </div>
          {(brands.length > 0 || channels.length > 0 || dateFrom || dateTo || rowLimit || agiplTarget) && <button className={button} disabled={locked} onClick={() => { setBrands([]); setChannels([]); setDateFrom(''); setDateTo(''); setRowLimit(''); setAgiplTarget(''); setOverwrite(false); }}>Reset selection</button>}
        </div>
        <p className="mt-2 text-sm leading-6 text-gray-600">Sent dates select source rows; each row retains its own goal/reporting date range. A preview is required after any selection change.</p>
        <details className="mt-3 rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-600">
          <summary className="cursor-pointer font-medium text-gray-700">How customers and revenue are counted</summary>
          <p className="mt-2 leading-6">Customers are counted once across each row’s entire goal range. Overall deduplicates Online/Offline overlap, so the split customer counts can add up to more than the total. Revenue is summed across the range. Previously completed rows require an intentional overwrite run to recalculate.</p>
        </details>
        <fieldset disabled={locked} className="mt-5 space-y-5">
          <fieldset className="rounded-lg border border-gray-200 p-4">
            <legend className="px-1 text-sm font-medium text-gray-700">Attribution channels · {channels.length} selected</legend>
            <div className="flex flex-wrap gap-4">{ATTRIBUTION_CHANNELS.map((value) => <label key={value} className="flex items-center gap-2 text-sm text-gray-700"><input type="checkbox" checked={channels.includes(value)} onChange={(event) => setChannels((old) => event.target.checked ? [...old, value] : old.filter((item) => item !== value))} className="h-4 w-4 accent-indigo-600" />{value}</label>)}</div>
          </fieldset>
          <fieldset className="rounded-lg border border-gray-200 p-4">
            <legend className="px-1 text-sm font-medium text-gray-700">Brands from the approved sheet · {brands.length} selected</legend>
            {connection ? <div className="flex flex-wrap gap-x-6 gap-y-4">{connection.brands.map((value) => {
              const supported = supportedBrands.some((brand) => brand.toLowerCase() === value.toLowerCase());
              return <label key={value} className={`flex items-center gap-2 text-sm ${supported ? 'text-gray-700' : 'text-gray-400'}`}><input type="checkbox" checked={brands.includes(value)} disabled={!supported} onChange={(event) => setBrands((old) => event.target.checked ? [...old, value] : old.filter((item) => item !== value))} className="h-4 w-4 accent-blue-600" />{value}{!supported && <span className="text-sm">(report not configured)</span>}</label>;
            })}</div> : <p className="text-sm text-gray-500">Connect the approved sheet to load its actual brands.</p>}
          </fieldset>
          <div className="grid gap-4 sm:grid-cols-3">
            <label className="text-sm font-medium text-gray-700">Sent date from<input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} className={`${input} mt-1`} /></label>
            <label className="text-sm font-medium text-gray-700">Sent date to<input type="date" value={dateTo} min={dateFrom || undefined} onChange={(event) => setDateTo(event.target.value)} className={`${input} mt-1`} /></label>
            <label className="text-sm font-medium text-gray-700">Optional row limit<input type="number" min="1" max="10000" step="1" value={rowLimit} onChange={(event) => setRowLimit(event.target.value)} className={`${input} mt-1`} /><span className="mt-1 block text-sm font-normal text-gray-500">Blank processes all matching rows.</span></label>
          </div>
          {connection?.sent_dates.length ? <p className="text-sm text-gray-500">Parsed sent dates in this sheet: {[...connection.sent_dates].sort()[0]} to {[...connection.sent_dates].sort().at(-1)}.</p> : null}
          {hasAgipl && <label className="block max-w-md text-sm font-medium text-gray-700">AGIPL attribution target<select value={agiplTarget} onChange={(event) => setAgiplTarget(event.target.value)} className={`${input} mt-1`}><option value="">Choose a supported brand</option>{targetBrands.map((brand) => <option key={brand} value={brand}>{brand}</option>)}</select><span className="mt-1 block text-sm font-normal text-gray-500">AGIPL cannot attribute to itself. Choices are the worker’s genuinely configured brands.</span></label>}
          <label className="flex items-start gap-2 text-sm text-gray-700"><input type="checkbox" checked={overwrite} onChange={(event) => setOverwrite(event.target.checked)} className="mt-0.5 h-4 w-4 accent-blue-600" /><span>Overwrite existing attribution metrics<span className="mt-1 block text-sm text-gray-500">Unchecked by default: preserve complete existing results. Checked: intentional replacements require confirmation before the run.</span></span></label>
        </fieldset>
        {selectionErrors.length > 0 && <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-gray-600">{selectionErrors.map((message) => <li key={message}>{message}</li>)}</ul>}
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <button className={button} disabled={locked || Boolean(selectionErrors.length) || !google?.configured} onClick={() => void previewCampaigns()}>{pending === 'preview' ? 'Loading preview…' : 'Preview selected campaigns'}</button>
          <button className={primary} disabled={locked || !ready || Boolean(selectionErrors.length) || !currentPreview?.row_count} onClick={() => void runJob()}>{pending === 'run' ? 'Starting…' : 'Run attribution'}</button>
          {pollingId && <span className="text-sm text-amber-800">One job is active. Selection, setup and new runs are locked until it finishes or is cancelled.</span>}
          {!ready && !loading && <span className="text-sm text-gray-600">Running requires configured Google credentials and a verified Apparel MoEngage HTTP session. No hosted browser is used.</span>}
        </div>
      </section>

      {currentPreview && <section className={panel} aria-labelledby="preview-heading">
        <h2 id="preview-heading" className="text-lg font-medium text-gray-900">Selected campaign preview</h2>
        <p className="mt-1 text-sm text-gray-600">{currentPreview.row_count.toLocaleString()} matching campaigns; {rowLimit ? `at most ${Math.min(Number(rowLimit), currentPreview.row_count).toLocaleString()} rows will be processed` : 'all matching rows will be processed'}. Showing the first {currentPreview.preview.length} rows.</p>
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
          <strong className="font-medium">Input warnings for sent dates {currentPreview.warning_sent_date_from} to {currentPreview.warning_sent_date_to}</strong>
          {currentPreview.warnings?.length ? <ul className="mt-2 list-disc space-y-1 pl-5">{currentPreview.warnings.map((warning, index) => <li key={`${index}:${warning}`}>{warning}</li>)}</ul> : <p className="mt-1">No parsing warnings were reported for the selected dates.</p>}
          <p className="mt-2 text-sm">Malformed source rows may be excluded from the parsed campaign count. Correct source inputs before running if these warnings affect your selection.</p>
        </div>
        {!currentPreview.row_count && <p className="workspace-empty mt-3 text-sm">No campaigns match this selection. Change the dates, brands or channels and preview again.</p>}
        <div className="mt-4 overflow-x-auto rounded-lg border border-gray-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500" role="region" aria-label="Selected campaign preview table" tabIndex={0}><table className="w-full text-left text-sm tabular-nums"><caption className="sr-only">Source campaigns matching the current selection</caption><thead className="border-b border-gray-200 bg-gray-50 text-gray-500"><tr>{['Sheet row', 'Campaign', 'Campaign ID', 'Brand', 'Channel', 'Type', 'Sent date', 'Goal range'].map((title) => <th key={title} scope="col" className={`whitespace-nowrap px-3 py-3 font-medium ${['Sheet row'].includes(title) ? 'text-right' : ''}`}>{title}</th>)}</tr></thead><tbody>{currentPreview.preview.map((row) => <tr key={row.excel_row} className="border-b border-gray-100"><td className="px-3 py-3 text-right">{row.excel_row}</td><td className="min-w-48 px-3 py-3">{row.campaign_name}</td><td className="px-3 py-3 font-mono">{row.campaign_id}</td><td className="px-3 py-3">{row.brand}</td><td className="px-3 py-3">{row.channel}</td><td className="px-3 py-3">{row.campaign_type}</td><td className="whitespace-nowrap px-3 py-3">{row.sent_date}</td><td className="whitespace-nowrap px-3 py-3">{row.date_range}</td></tr>)}</tbody></table></div>
      </section>}
      {preview && !currentPreview && <p className="text-sm text-amber-800">Selection changed. Load a fresh preview before starting a run.</p>}

      <section className={panel} aria-labelledby="job-heading">
        <div className="flex flex-wrap items-center justify-between gap-3"><h2 id="job-heading" className="text-lg font-medium text-gray-900">Job progress and results</h2>{selectedJob && <StatusBadge value={selectedJob.status} />}</div>
        {pollError && <p role="alert" className="mt-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900">{pollError}</p>}
        {selectedId && !selectedJob && <p role="status" className="mt-3 text-sm text-gray-500">Loading actual job details for {selectedId}…</p>}
        {!selectedId && <div className="workspace-empty mt-4"><h3 className="text-sm font-medium text-gray-800">No run selected</h3><p className="mt-1 text-sm text-gray-600">Start a valid previewed run, or open a job from history below. Progress and recorded results will appear here.</p></div>}
        {selectedJob && <>
          <p className="mt-2 break-all font-mono text-sm text-gray-500">{selectedJob.filename} · Job {selectedJob.job_id} · Created {new Date(selectedJob.created_at).toLocaleString()}</p>
          <div className="mt-4 flex items-center gap-3"><progress aria-label="Attribution job progress" value={selectedJob.progress} max="100" className="h-3 w-full accent-indigo-600" /><span className="workspace-number text-sm font-medium text-gray-700">{selectedJob.progress}%</span></div>
          <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-5">{[['Total', selectedJob.total_rows], ['Processed', selectedJob.processed_rows], ['Successful', selectedJob.successful_rows], ['Failed', selectedJob.failed_rows], ['Skipped', selectedJob.skipped_rows]].map(([label, value]) => <div key={label} className="rounded-lg border border-gray-200 bg-gray-50 p-3"><dt className="text-sm text-gray-600">{label}</dt><dd className="workspace-number mt-1 text-2xl font-medium text-gray-900">{Number(value).toLocaleString()}</dd></div>)}</dl>
          {selectedJob.current_row !== null && <p role="status" className="mt-3 text-sm text-gray-600">Processing sheet row {selectedJob.current_row}{selectedJob.current_brand ? ` · ${selectedJob.current_brand}` : ''}</p>}
          {selectedJob.error && <p role="alert" className="mt-3 rounded-lg bg-red-50 p-3 text-sm text-red-800">{selectedJob.error}</p>}
          <div className="mt-4 flex flex-wrap gap-3">
            <button className={button} disabled={Boolean(pending) || !selectedJob.results.length || isAttributionJobActive(selectedJob.status)} onClick={() => void perform('download', async () => { await downloadAttributionCsv(selectedJob.job_id); }, false)}>{pending === 'download' ? 'Downloading…' : 'Download results CSV'}</button>
            <button className={button} disabled={locked || !ready || !selectedJob.failed_rows || !['completed', 'failed', 'cancelled'].includes(selectedJob.status)} onClick={() => void retryFailed()}>{pending === 'retry' ? 'Retrying…' : 'Retry failed rows'}</button>
          </div>
          <p className="mt-3 text-sm text-gray-500">The worker returns the latest 250 row results below. The CSV contains all recorded results for this job, including skipped and failed rows; blank metrics are not converted to zero.</p>
          <div className="mt-4 overflow-x-auto rounded-lg border border-gray-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500" role="region" aria-label="Attribution row results table" tabIndex={0}><table className="w-full text-left text-sm tabular-nums"><caption className="sr-only">Latest recorded attribution row results, including failed and skipped rows</caption><thead className="border-b border-gray-200 bg-gray-50 text-gray-500"><tr>{['Row', 'Campaign / ID', 'Brand / channel / type', 'Goal range', 'Status', 'Users total / online / offline', 'Revenue total / online / offline', 'Message'].map((title) => <th key={title} scope="col" className={`whitespace-nowrap px-3 py-3 font-medium ${['Row', 'Users total / online / offline', 'Revenue total / online / offline'].includes(title) ? 'text-right' : ''}`}>{title}</th>)}</tr></thead><tbody>{selectedJob.results.map((row) => <tr key={`${row.excel_row}:${row.campaign_id}`} className="border-b border-gray-100"><td className="px-3 py-3 text-right">{row.excel_row}</td><td className="min-w-48 px-3 py-3">{row.campaign_name}<div className="mt-1 font-mono text-gray-500">{row.campaign_id}</div></td><td className="px-3 py-3">{row.brand}<div className="mt-1 whitespace-nowrap text-gray-500">{row.channel} / {row.campaign_type}</div></td><td className="whitespace-nowrap px-3 py-3">{row.date_range}</td><td className="px-3 py-3"><StatusBadge value={row.status} /></td><td className="whitespace-nowrap px-3 py-3 text-right tabular-nums">{[row.unique_users, row.online_unique_users, row.offline_unique_users].map((value) => value === null ? '—' : value.toLocaleString()).join(' / ')}</td><td className="whitespace-nowrap px-3 py-3 text-right tabular-nums">{[row.total_revenue, row.online_revenue, row.offline_revenue].map((value) => value === null ? '—' : value.toLocaleString(undefined, { maximumFractionDigits: 2 })).join(' / ')}</td><td className="min-w-56 px-3 py-3 text-gray-600">{row.message || '—'}</td></tr>)}</tbody></table></div>
          {!selectedJob.results.length && <p className="workspace-empty mt-3 text-sm">No row results have been recorded for this job yet.</p>}
        </>}
        {pollingId && <button className={`${button} mt-4 border-red-200 text-red-700`} disabled={Boolean(pending) || requiresRefresh} onClick={() => {
          if (!window.confirm('Cancel the active attribution job? Rows already written to the sheet will remain.')) return;
          void perform('cancel', async () => { const job = await cancelAttributionJob(pollingId); if (live.current) { storeJob(job); setNotice('Cancellation returned from the worker. Completed sheet writes are retained.'); await refreshDashboard(); } });
        }}>{pending === 'cancel' ? 'Stopping…' : 'Stop active job'}</button>}
      </section>

      <section className={panel} aria-labelledby="history-heading">
        <h2 id="history-heading" className="text-lg font-medium text-gray-900">Run history</h2>
        <p className="mt-1 text-sm text-gray-500">History is kept in the worker’s memory (latest 30 jobs), not a durable audit store. Worker restarts clear jobs and downloadable CSVs, but do not erase results already written to the sheet.</p>
        {!jobs.length && !loading && !resourceErrors.jobs && <p className="workspace-empty mt-4 text-sm">The worker reports no job history. Preview your campaigns above to prepare a new run.</p>}
        <div className="mt-4 overflow-x-auto rounded-lg border border-gray-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500" role="region" aria-label="Attribution run history table" tabIndex={0}><table className="w-full text-left text-sm tabular-nums"><caption className="sr-only">Latest attribution jobs held in worker memory</caption><thead className="border-b border-gray-200 bg-gray-50 text-gray-500"><tr>{['Created', 'Source / job', 'Status', 'Processed', 'Success / failed / skipped', 'Results'].map((title) => <th key={title} scope="col" className={`whitespace-nowrap px-3 py-3 font-medium ${['Processed', 'Success / failed / skipped'].includes(title) ? 'text-right' : ''}`}>{title}</th>)}</tr></thead><tbody>{jobs.map((job) => <tr key={job.job_id} className={`border-b border-gray-100 ${selectedId === job.job_id ? 'bg-gray-50' : ''}`}><td className="whitespace-nowrap px-3 py-3">{new Date(job.created_at).toLocaleString()}</td><td className="px-3 py-3">{job.filename}<div className="mt-1 font-mono text-gray-500">{job.job_id.slice(0, 8)}</div></td><td className="px-3 py-3"><StatusBadge value={job.status} /></td><td className="px-3 py-3 text-right tabular-nums">{job.processed_rows} / {job.total_rows}</td><td className="px-3 py-3 text-right tabular-nums">{job.successful_rows} / {job.failed_rows} / {job.skipped_rows}</td><td className="px-3 py-3"><button className={button} aria-pressed={selectedId === job.job_id} disabled={Boolean(pending) || Boolean(pollingId && pollingId !== job.job_id)} onClick={() => { selectJob(job.job_id); setJobRefresh((old) => old + 1); }}>View results</button></td></tr>)}</tbody></table></div>
      </section>

      {isAdmin && (
        <section className={panel} aria-labelledby="setup-heading">
          <h2 id="setup-heading" className="text-lg font-medium text-gray-900">Admin setup</h2>
          <p className="mt-1 text-sm text-gray-500">Attribution uses Apparel-only credentials in the main application. Server files and the credential database need durable storage across deployments.</p>
          <div className="mt-5 grid gap-6 md:grid-cols-2">
            <div className="min-w-0 space-y-4 rounded-lg border border-gray-200 p-4">
              <label className="block text-sm font-medium text-gray-700">Approved Google sheet URL<input value={setupUrl} onChange={(event) => setSetupUrl(event.target.value)} disabled={locked} className={`${input} mt-1`} /></label>
              <label className="block text-sm font-medium text-gray-700">Worksheet title<input value={setupWorksheet} onChange={(event) => setSetupWorksheet(event.target.value)} disabled={locked} className={`${input} mt-1`} /></label>
              <label className="block text-sm font-medium text-gray-700">Apparel workspace mappings<textarea value={reportJson} onChange={(event) => setReportJson(event.target.value)} disabled={locked} rows={10} spellCheck={false} className={`${input} mt-1 font-mono`} /></label>
              <button className={primary} disabled={locked || !setup} onClick={() => void saveSetup()}>{pending === 'setup' ? 'Saving…' : 'Save approved setup'}</button>
            </div>
            <div className="space-y-5">
              <div className="space-y-3 rounded-lg border border-gray-200 p-4">
                <h3 className="font-medium text-gray-900">Google service account</h3>
                <p className="break-all text-sm text-gray-600">{google?.service_account_email || 'No service account configured'}. Share the approved sheet with this account as Editor.</p>
                <label className="block text-sm font-medium text-gray-700">Google service-account JSON<input type="file" accept=".json,application/json" disabled={locked} onChange={(event) => setCredential(event.target.files?.[0] || null)} className={`${input} mt-2 block file:mr-3 file:rounded-md file:border-0 file:bg-gray-100 file:px-3 file:py-1 file:text-sm file:text-gray-700`} /></label>
                <button className={button} disabled={locked || !credential} onClick={() => void perform('credentials', async () => {
                  if (!credential) return;
                  await uploadAttributionGoogleKey(credential);
                  if (live.current) { setCredential(null); setConnection(null); connectionRef.current = null; setPreview(null); }
                  await refreshDashboard();
                })}>{pending === 'credentials' ? 'Installing…' : 'Install Google key'}</button>
              </div>
              <div className="space-y-3 rounded-lg border border-gray-200 p-4">
                <h3 className="font-medium text-gray-900">Apparel MoEngage session</h3>
                <p className="text-sm text-gray-500">Use the existing Apparel Auth Sync connection, or update its bearer token, refresh token and cookie in Settings → MoEngage. Sessions can expire; no browser server or CDP configuration is required.</p>
                <Link href="/settings" className="inline-block text-sm font-medium text-indigo-700">Open Apparel settings →</Link>
              </div>
              <p className="text-sm text-amber-800">Crocs is offline-only: Offline rows use all purchases; Overall rows have zero Online metrics and all purchases Offline. Correct Crocs rows marked Online before running.</p>
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
