'use client';

import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { fetchWithRetry, getApiUrl } from '@/lib/api';
import { useApp } from '@/lib/context';
import { destinationAccountLabel } from '@/lib/destination';

type Integration = 'whatsapp' | 'rcs' | 'sms' | 'moengage';
type Scope = { account: string; integration: Integration };
type SyncTarget = Scope & {
  mode: 'browser' | 'unsupported' | 'setup_required';
  identity: { waba_id?: string; esmeaddr?: string; bot_ids?: string[]; base_url?: string; workspace_id?: string; entity_id?: string };
  message: string;
};
type SyncStatus = Scope & {
  paired: boolean;
  last_synced_at: number | null;
  last_validated_at: number | null;
  validation_state: 'never' | 'valid' | 'invalid';
  message: string;
};
type Action = 'refresh' | 'detect' | 'download' | 'connect' | 'select' | 'check' | 'disconnect' | 'retry';
type Feedback = { type: 'success' | 'error'; message: string } | null;
type BrowserStatus = Scope & {
  paired: boolean;
  pending: boolean;
  syncing: boolean;
  capture_active: boolean;
  last_synced_at: number | null;
  error: string | null;
};
const SYNC_ERRORS: Record<string, string> = {
  device_expired: 'This browser’s device pairing expired or was revoked. Reconnect only this account and integration; your portal login is separate.',
  scope_denied: 'This device is not authorized for this account and integration. Check the exact configured target in Settings; do not copy credentials from another account.',
  identity_conflict: 'The captured identity conflicts with this configured target. Select its exact bot, WABA, MoEngage workspace, or VILPOWER principal entity and reload its inventory.',
  provider_validation_failed: 'The provider did not validate the captured session. Reload this exact target’s inventory in the already logged-in portal, then retry. If the inventory works but sync still fails, ask your administrator to check provider validation. Re-pairing or repeating OTP is not required just to retry.',
  incomplete_session: 'The captured session is incomplete. Reload this exact target’s inventory in the already logged-in portal to capture all required headers together.',
  schema_rejected: 'The agent rejected the captured session format or size. Update Auth Sync from this site’s extension download and reload this exact target’s inventory. Credentials are never truncated; contact your administrator if this repeats.',
  capture_invalid: 'The matching request had incomplete, conflicting, or oversized authentication. Reload this exact target’s inventory in the already logged-in portal. Supported lengths: bearer/refresh 16000, session 1000, user 300, cookie 32000, bot 200 characters.',
  inventory_failed: 'The inventory request was not a fresh successful response. Check the portal connection and reload this exact target’s inventory. Sign in only if the portal session itself has expired.',
  network_error: 'Could not reach the agent. Check your connection and retry the captured session.',
  request_failed: 'Auth Sync could not complete this request. Retry for this exact target or ask your administrator to check the service.',
};
function syncError(code: unknown): string {
  return typeof code === 'string' && Object.hasOwn(SYNC_ERRORS, code) ? SYNC_ERRORS[code] : SYNC_ERRORS.request_failed;
}

function isBrowserStatus(value: unknown, scope: Scope): value is BrowserStatus {
  return typeof value === 'object' && value !== null &&
    'account' in value && value.account === scope.account &&
    'integration' in value && value.integration === scope.integration &&
    'paired' in value && typeof value.paired === 'boolean' &&
    'pending' in value && typeof value.pending === 'boolean' &&
    'syncing' in value && typeof value.syncing === 'boolean' &&
    'capture_active' in value && typeof value.capture_active === 'boolean' &&
    'last_synced_at' in value && isTimestamp(value.last_synced_at) &&
    'error' in value && (value.error === null || (typeof value.error === 'string' && Object.hasOwn(SYNC_ERRORS, value.error)));
}

function isTimestamp(value: unknown): value is number | null {
  return value === null || (typeof value === 'number' && Number.isFinite(value) && value > 0);
}

function isSyncStatus(value: unknown, scope: Scope): value is SyncStatus {
  return typeof value === 'object' && value !== null &&
    'account' in value && value.account === scope.account &&
    'integration' in value && value.integration === scope.integration &&
    'paired' in value && typeof value.paired === 'boolean' &&
    'last_synced_at' in value && isTimestamp(value.last_synced_at) &&
    'last_validated_at' in value && isTimestamp(value.last_validated_at) &&
    'validation_state' in value && (value.validation_state === 'never' || value.validation_state === 'valid' || value.validation_state === 'invalid') &&
    'message' in value && typeof value.message === 'string';
}

function isSyncTarget(value: unknown, scope: Scope): value is SyncTarget {
  return typeof value === 'object' && value !== null &&
    'account' in value && value.account === scope.account &&
    'integration' in value && value.integration === scope.integration &&
    'mode' in value && (value.mode === 'browser' || value.mode === 'unsupported' || value.mode === 'setup_required') &&
    'message' in value && typeof value.message === 'string' &&
    'identity' in value && typeof value.identity === 'object' && value.identity !== null;
}

async function request(path: string, signal: AbortSignal, method = 'GET', body?: object) {
  const response = await fetchWithRetry(getApiUrl(`/api/karix-extension/${path}`), {
    method, signal, redirect: 'error', credentials: 'omit', cache: 'no-store',
    ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
  }, 0, 800, 20000);
  if (!response.ok) {
    if (response.status === 401) throw new Error('Your agent sign-in expired or is unavailable. Sign in to the agent again; this is separate from the provider portal and extension pairing.');
    if (response.status === 403) throw new Error(syncError('scope_denied'));
    if (response.status === 409) throw new Error(syncError('identity_conflict'));
    if (response.status === 422) {
      let detail: unknown;
      try { detail = (await response.json())?.detail; } catch { /* Never display untrusted response text. */ }
      const expected = body && 'integration' in body ? body.integration : new URLSearchParams(path.split('?')[1]).get('integration');
      if (typeof detail === 'object' && detail !== null && 'integration' in detail && detail.integration === expected &&
          'code' in detail && (detail.code === 'provider_validation_failed' || detail.code === 'incomplete_session')) {
        throw new Error(syncError(detail.code));
      }
      throw new Error(syncError('schema_rejected'));
    }
    throw new Error(syncError('request_failed'));
  }
  return response;
}

function extensionMessage(type: 'KARIX_EXTENSION_PING' | 'KARIX_EXTENSION_PAIR' | 'KARIX_EXTENSION_SELECT' | 'KARIX_EXTENSION_SCOPED_STATUS' | 'KARIX_EXTENSION_RETRY', signal: AbortSignal, scope?: Scope & { code?: string }): Promise<unknown> {
  signal.throwIfAborted();
  const { promise, resolve, reject } = Promise.withResolvers<unknown>();
  const requestId = crypto.randomUUID();
  const origin = window.location.origin;
  const cleanup = () => {
    window.clearTimeout(timer);
    window.removeEventListener('message', onMessage);
    signal.removeEventListener('abort', onAbort);
  };
  const onAbort = () => { cleanup(); reject(signal.reason); };
  const onMessage = (event: MessageEvent<unknown>) => {
    if (event.source !== window || event.origin !== origin) return;
    const data = event.data;
    if (typeof data !== 'object' || data === null ||
        !('type' in data) || data.type !== 'KARIX_EXTENSION_RESULT' ||
        !('requestId' in data) || data.requestId !== requestId ||
        !('ok' in data) || typeof data.ok !== 'boolean' ||
        !('message' in data) || typeof data.message !== 'string') return;
    if (data.ok && scope && (!('account' in data) || data.account !== scope.account ||
        !('integration' in data) || data.integration !== scope.integration)) {
      cleanup();
      reject(new Error('The extension confirmed a different account or integration. Refresh scoped status before retrying.'));
      return;
    }
    cleanup();
    if (data.ok) resolve(data);
    else reject(new Error(syncError('error_code' in data ? data.error_code : null)));
  };
  const timer = window.setTimeout(() => {
    cleanup();
    reject(new Error(type === 'KARIX_EXTENSION_PAIR'
      ? 'Pairing was not confirmed in time. Refresh status before trying Connect again.'
      : type === 'KARIX_EXTENSION_RETRY'
        ? 'Retry was not confirmed in time. Refresh browser capture status before retrying; the existing device was preserved.'
        : type === 'KARIX_EXTENSION_SELECT'
          ? 'The capture switch was not confirmed in time. Refresh browser capture status before trying again; saved sessions were not changed.'
          : 'Auth Sync did not respond. Install or reload this site’s extension and reload Settings.'));
  }, type === 'KARIX_EXTENSION_PAIR' || type === 'KARIX_EXTENSION_RETRY' || type === 'KARIX_EXTENSION_SELECT' ? 45000 : 2500);
  window.addEventListener('message', onMessage);
  signal.addEventListener('abort', onAbort, { once: true });
  try { window.postMessage({ type, requestId, ...scope }, origin); }
  catch (error) { cleanup(); reject(error); }
  return promise;
}

export default function KarixAuthSync({ account, integration }: Scope) {
  const { getAccountLabel } = useApp();
  const accountTitle = destinationAccountLabel(account, getAccountLabel(account));
  const integrationTitle = integration === 'moengage' ? 'MoEngage' : integration === 'whatsapp' ? 'WhatsApp' : integration === 'sms' ? 'SMS DLT · VILPOWER' : integration.toUpperCase();
  const titleId = useId();
  const [target, setTarget] = useState<SyncTarget | null>(null);
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [installed, setInstalled] = useState<boolean | null>(null);
  const [browserStatus, setBrowserStatus] = useState<BrowserStatus | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const lifecycle = useRef<AbortController | null>(null);
  const busy = useRef(false);
  const observedSync = useRef<number | null>(null);
  const download = useRef<{ url?: string; timer?: number }>({});
  const scopeQuery = new URLSearchParams({ account, integration }).toString();

  const readBrowserStatus = useCallback(async (signal: AbortSignal) => {
    try {
      const next = await extensionMessage('KARIX_EXTENSION_SCOPED_STATUS', signal, { account, integration });
      if (!isBrowserStatus(next, { account, integration })) throw new Error('Reload Auth Sync and Settings to read current browser capture status.');
      signal.throwIfAborted();
      setBrowserStatus(next);
      setInstalled(true);
      return next;
    } catch (error) {
      if (!signal.aborted) { setBrowserStatus(null); setInstalled(false); }
      throw error;
    }
  }, [account, integration]);
  const readStatus = useCallback(async (signal: AbortSignal, path = 'status', method = 'GET') => {
    try {
      const response = await request(`${path}?${scopeQuery}`, signal, method);
      const next: unknown = await response.json();
      if (!isSyncStatus(next, { account, integration })) throw new Error('The server returned an unexpected scoped auth sync status.');
      signal.throwIfAborted();
      setStatus(next);
      setStatusError(null);
      return next;
    } catch (error) {
      if (!signal.aborted) setStatusError(error instanceof Error ? error.message : 'Could not refresh auth sync status.');
      throw error;
    }
  }, [account, integration, scopeQuery]);

  const refresh = useCallback(async (signal: AbortSignal) => {
    try {
      const response = await request(`targets?${new URLSearchParams({ account })}`, signal);
      const data: unknown = await response.json();
      if (typeof data !== 'object' || data === null || !('targets' in data) || !Array.isArray(data.targets)) {
        throw new Error('The server returned unexpected auth sync capabilities.');
      }
      const next = data.targets.find((candidate): candidate is SyncTarget => isSyncTarget(candidate, { account, integration }));
      if (!next) throw new Error('No auth sync capability was returned for this account and integration.');
      signal.throwIfAborted();
      setTarget(next);
      setStatusError(null);
      await readStatus(signal);
    } catch (error) {
      if (!signal.aborted) setStatusError(error instanceof Error ? error.message : 'Could not load auth sync capabilities.');
      throw error;
    }
  }, [account, integration, readStatus]);

  const perform = useCallback(async (nextAction: Action, work: (signal: AbortSignal) => Promise<string | void>, announce = true) => {
    const controller = lifecycle.current;
    if (!controller || controller.signal.aborted || busy.current) return;
    busy.current = true;
    setAction(nextAction);
    setFeedback(null);
    try {
      const message = await work(controller.signal);
      if (!controller.signal.aborted && message) setFeedback({ type: 'success', message });
    } catch (error) {
      if (!controller.signal.aborted && announce) setFeedback({ type: 'error', message: error instanceof Error ? error.message : 'The request failed. Please try again.' });
    } finally {
      if (!controller.signal.aborted) { busy.current = false; setAction(null); }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    lifecycle.current = controller;
    busy.current = false;
    observedSync.current = null;
    setTarget(null);
    setStatus(null);
    setStatusError(null);
    setInstalled(null);
    setBrowserStatus(null);
    setFeedback(null);
    const onFocus = () => { void perform('refresh', refresh, false); };
    void perform('refresh', refresh, false);
    let readingBrowser = false;
    const pollBrowser = async () => {
      if (readingBrowser || controller.signal.aborted) return;
      readingBrowser = true;
      try {
        const next = await readBrowserStatus(controller.signal);
        if (next?.last_synced_at && next.last_synced_at !== observedSync.current && !busy.current) {
          await readStatus(controller.signal);
          observedSync.current = next.last_synced_at;
        }
      } catch { /* Detection and backend status failures are shown separately. */ }
      finally { readingBrowser = false; }
    };
    void pollBrowser();
    const browserTimer = window.setInterval(() => { void pollBrowser(); }, 3000);
    window.addEventListener('focus', onFocus);
    return () => {
      controller.abort();
      window.clearInterval(browserTimer);
      window.removeEventListener('focus', onFocus);
      window.clearTimeout(download.current.timer);
      if (download.current.url) URL.revokeObjectURL(download.current.url);
      download.current = {};
    };
  }, [perform, refresh, readBrowserStatus, readStatus]);

  function downloadExtension() {
    void perform('download', async (signal) => {
      const response = await request('download', signal, 'POST', { agent_origin: window.location.origin });
      const blob = await response.blob();
      signal.throwIfAborted();
      window.clearTimeout(download.current.timer);
      if (download.current.url) URL.revokeObjectURL(download.current.url);
      const url = URL.createObjectURL(blob);
      download.current.url = url;
      const link = document.createElement('a');
      link.href = url;
      link.download = 'karix-auth-sync-extension.zip';
      document.body.appendChild(link);
      link.click();
      link.remove();
      download.current.timer = window.setTimeout(() => {
        URL.revokeObjectURL(url);
        if (download.current.url === url) download.current.url = undefined;
      }, 1000);
      return 'ZIP downloaded for this Settings site. Unzip it, load it in Chrome, then reload Settings.';
    });
  }

  function detectExtension() {
    void perform('detect', async (signal) => {
      try {
        await readBrowserStatus(signal);
        return 'Auth Sync is installed for this site.';
      } catch (error) {
        if (!signal.aborted) setInstalled(false);
        throw error;
      }
    });
  }

  function connect() {
    if (target?.mode !== 'browser' || statusError) return;
    void perform('connect', async (signal) => {
      const response = await request('pairing', signal, 'POST', { agent_origin: window.location.origin, account, integration });
      const pairing = await response.json();
      if (typeof pairing?.code !== 'string' || !pairing.code || typeof pairing.expires_at !== 'number' ||
          !Number.isFinite(pairing.expires_at) || pairing.expires_at <= Date.now() / 1000) {
        throw new Error('The server did not issue a valid pairing code. Please try again.');
      }
      signal.throwIfAborted();
      await extensionMessage('KARIX_EXTENSION_PAIR', signal, { code: pairing.code, account, integration });
      const next = await readStatus(signal);
      await readBrowserStatus(signal);
      if (!next.paired) throw new Error('No active scoped device was confirmed. Refresh status before connecting again.');
      return next.validation_state === 'valid'
        ? 'Connected for this account and integration. The saved session passed backend validation.'
        : 'Connected for this exact target. Reload its inventory in your already logged-in portal. Sign in only if the portal session has expired; no credential copying is needed.';
    });
  }

  function selectTarget() {
    if (!browserStatus?.paired) return;
    void perform('select', async (signal) => {
      await extensionMessage('KARIX_EXTENSION_SELECT', signal, { account, integration });
      await readBrowserStatus(signal);
      return `This browser is now capturing ${accountTitle} · ${integrationTitle}. Reload its matching portal inventory to sync. Other accounts’ saved sessions were not changed.`;
    });
  }

  function checkSession() {
    void perform('check', async (signal) => {
      const next = await readStatus(signal, 'check', 'POST');
      if (next.validation_state !== 'valid') throw new Error(next.message || 'The saved session could not be validated. Log in and open the matching template list to sync again.');
      return 'Saved session validated by the backend. No credentials were changed by this check.';
    });
  }

  function disconnect() {
    void perform('disconnect', async (signal) => {
      const response = await request(`pairing?${scopeQuery}`, signal, 'DELETE');
      const result = await response.json();
      if (result?.ok !== true) throw new Error('Device revocation was not confirmed. Refresh status and try again.');
      signal.throwIfAborted();
      setStatus((previous) => previous ? { ...previous, paired: false } : previous);
      await readStatus(signal);
      return 'Your devices and pending pairing codes for this account and integration were revoked. Other scopes and the saved session were not changed.';
    });
  }

  function retryCapturedSession() {
    if (!browserStatus?.paired || !browserStatus.pending || browserStatus.syncing) return;
    void perform('retry', async (signal) => {
      try {
        await extensionMessage('KARIX_EXTENSION_RETRY', signal, { account, integration });
        await readStatus(signal);
        return 'The captured session for this account and integration was validated and synced. The existing device pairing was preserved.';
      } finally {
        await readBrowserStatus(signal).catch(() => {});
      }
    });
  }

  const disabled = action !== null;
  const browser = target?.mode === 'browser';
  const validated = browser && !statusError && status?.validation_state === 'valid';
  const invalid = !statusError && status?.validation_state === 'invalid';
  const statusLabel = statusError ? 'Unable to check' : !target || (browser && !status) ? 'Checking…'
    : target.mode === 'unsupported' ? 'Not available' : target.mode === 'setup_required' ? 'Setup needed'
      : validated ? 'Session verified' : invalid ? 'Login needs updating' : 'Not verified yet';
  const buttonClass = 'px-3 py-2 rounded-lg border border-gray-200 bg-white text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500';
  const portal = integration === 'moengage' ? 'MoEngage' : integration === 'sms' ? 'VILPOWER' : 'Karix';
  const moeOrigin = typeof target?.identity.base_url === 'string' && /^https:\/\/dashboard(?:-\d{2})?\.moengage\.com\/?$/.test(target.identity.base_url)
    ? target.identity.base_url.replace(/\/$/, '') : null;
  const portalUrl = integration === 'moengage' ? moeOrigin && `${moeOrigin}/v4/campaigns/all?view=all`
    : integration === 'sms' ? 'https://www.vilpower.in/content_templates/contentIndex/'
      : integration === 'rcs' ? 'https://rcmui.instaalerts.zone/bot_builder_gui/#/campaign-management/templates-list'
        : 'https://www.karix.solutions/lounge/LoungePage/index.php';

  const primaryClass = 'px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500';
  const refreshStatus = () => { void perform('refresh', refresh); };
  let primary = { label: 'Refresh status', onClick: refreshStatus };
  if (browser && !statusError) {
    if (installed !== true) primary = { label: 'Download extension', onClick: downloadExtension };
    else if (!browserStatus?.paired) primary = { label: 'Connect this browser', onClick: connect };
    else if (browserStatus.pending) primary = { label: 'Retry sync', onClick: retryCapturedSession };
    else if (!browserStatus.capture_active) primary = { label: 'Enable auto-sync here', onClick: selectTarget };
    else primary = { label: 'Check connection', onClick: checkSession };
  }
  const openPortal = browser && !statusError && installed === true && browserStatus?.paired &&
    browserStatus.capture_active && !browserStatus.pending && !browserStatus.syncing && !validated && portalUrl;

  return (
    <section aria-labelledby={titleId} aria-busy={disabled} className="rounded-xl border border-gray-200 bg-white p-5 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id={titleId} className="text-base font-bold text-gray-900">{portal} connection</h3>
          <p className="mt-1 text-xs text-gray-500">{accountTitle} · {integrationTitle}</p>
        </div>
        <span role="status" className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${validated ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : invalid ? 'border-amber-200 bg-amber-50 text-amber-800' : 'border-gray-200 bg-gray-50 text-gray-600'}`}>{statusLabel}</span>
      </div>

      {browser && <div className="text-sm text-gray-600 space-y-1">
        <p>{validated
          ? `Saved session last verified${status?.last_validated_at ? ` ${new Date(status.last_validated_at * 1000).toLocaleString()}` : ''}.`
          : invalid ? `Open ${portal}, sign in if needed, and reload this account’s template list to update the session.`
            : `Connect this browser, then open this account’s ${integration === 'moengage' ? 'workspace' : 'template list'} in ${portal} to sync your login.`}</p>
        <p className="text-xs text-gray-500">{installed === null ? 'Checking the browser extension…'
          : !installed ? 'For automatic updates, install the extension and reload this page.'
            : !browserStatus?.paired ? 'This browser is not connected for automatic updates.'
              : browserStatus.syncing ? 'Syncing and verifying your session…'
                : browserStatus.pending ? 'A session is waiting to sync. Retry without reconnecting.'
                  : !browserStatus.capture_active ? 'Auto-sync is set to another account. Enable it here to switch.'
                    : 'Auto-sync is enabled for this account in this browser.'}</p>
      </div>}
      {target && !browser && <p className="text-sm text-gray-600">{target.message}{target.mode === 'setup_required' && ' Ask your administrator to complete the account settings below.'}</p>}

      {target?.mode !== 'unsupported' && <div>
        {openPortal ? <a href={portalUrl!} target="_blank" rel="noopener noreferrer" className={`${primaryClass} inline-block`}>Open {portal} to sync</a>
          : <button type="button" onClick={primary.onClick} disabled={disabled || (browser && !statusError && (!status || installed === null || Boolean(browserStatus?.syncing)))} className={primaryClass}>{disabled ? 'Working…' : primary.label}</button>}
      </div>}
      {statusError && <p role="alert" className="text-sm text-red-700">{statusError}</p>}
      {browserStatus?.error && <p role="alert" className="text-sm text-red-700">{syncError(browserStatus.error)}</p>}
      {feedback && <p role={feedback.type === 'error' ? 'alert' : 'status'} className={`rounded-lg border p-3 text-xs ${feedback.type === 'error' ? 'border-red-200 bg-red-50 text-red-700' : 'border-blue-200 bg-blue-50 text-blue-800'}`}>{feedback.message}</p>}

      {browser && <details className="border-t border-gray-100 pt-3">
        <summary className="cursor-pointer text-xs font-semibold text-gray-600">Setup help</summary>
        <ol className="mt-3 list-decimal pl-5 text-xs text-gray-600 space-y-2">
          <li>Download and unzip the extension. Open <code>chrome://extensions</code>, enable Developer mode, choose <strong>Load unpacked</strong>, and select the folder containing <code>manifest.json</code>.</li>
          <li>Reload this page and choose <strong>Connect this browser</strong>. Each account and channel needs its own connection.</li>
          <li>In {portal}, select this account’s {integration === 'rcs' ? 'configured Sender ID' : integration === 'whatsapp' ? 'configured WABA' : integration === 'sms' ? 'Content Templates' : 'configured workspace'} and reload its {integration === 'moengage' ? 'dashboard' : 'template list'}. Sign in manually, including OTP, only if the portal asks.</li>
        </ol>
        {integration === 'sms' && target?.identity.entity_id && <p className="mt-3 text-xs text-gray-600">Expected entity: TATA CAPITAL LIMITED · {target.identity.entity_id}. This connection registers templates; it never sends SMS.</p>}
        <div className="mt-3 flex flex-wrap gap-2">
          <button type="button" onClick={downloadExtension} disabled={disabled} className={buttonClass}>Download extension ZIP</button>
          <button type="button" onClick={detectExtension} disabled={disabled} className={buttonClass}>Detect extension</button>
          {portalUrl && <a href={portalUrl} target="_blank" rel="noopener noreferrer" className={buttonClass}>Open {portal} portal</a>}
        </div>
      </details>}

      <details className="border-t border-gray-100 pt-3">
        <summary className="cursor-pointer text-xs font-semibold text-gray-600">Advanced connection details</summary>
        <div className="mt-3 space-y-3">
          {browser && <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
            <div><dt className="font-semibold text-gray-500">Saved session</dt><dd className="mt-1 text-gray-800">{statusError ? 'Unable to check' : status?.validation_state === 'valid' ? 'Passed last check (not a live guarantee)' : status?.validation_state === 'invalid' ? 'Last check failed' : 'Not checked yet'}</dd></div>
            <div><dt className="font-semibold text-gray-500">This browser</dt><dd className="mt-1 text-gray-800">{!browserStatus ? 'Extension unavailable' : !browserStatus.paired ? 'Not connected for this account' : browserStatus.capture_active ? 'Connected · capture active' : 'Connected · capture inactive'}</dd></div>
            <div><dt className="font-semibold text-gray-500">Last successful sync</dt><dd className="mt-1 text-gray-800">{status?.last_synced_at ? new Date(status.last_synced_at * 1000).toLocaleString() : 'No successful sync yet'}</dd></div>
            <div><dt className="font-semibold text-gray-500">Registered devices</dt><dd className="mt-1 text-gray-800">{statusError ? 'Unable to check' : status?.paired ? 'At least one device (may be another browser)' : 'No confirmed devices'}</dd></div>
          </dl>}
          <p className="text-xs text-gray-500">Connections are separate for each account and channel. API tokens and encryption keys require administrator setup; the extension only syncs browser sessions. Blank secret fields below keep their saved values.</p>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={refreshStatus} disabled={disabled} className={buttonClass}>Refresh status</button>
            {browser && <button type="button" onClick={checkSession} disabled={disabled} className={buttonClass}>Check saved session</button>}
            {target && target.mode !== 'unsupported' && <button type="button" onClick={disconnect} disabled={disabled} className={`${buttonClass} text-red-700`}>Disconnect my devices</button>}
          </div>
          {target && target.mode !== 'unsupported' && <p className="text-xs text-gray-500">Disconnect removes only your device connections for this account and channel. It does not remove the saved session or affect other users.</p>}
        </div>
      </details>
    </section>
  );
}
