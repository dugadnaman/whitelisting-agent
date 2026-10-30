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
  const statusLabel = statusError ? 'Status unavailable' : !target ? 'Loading capabilities'
    : target.mode === 'unsupported' ? 'Not integrated' : target.mode === 'setup_required' ? 'Setup required'
      : !status ? 'Loading saved session status'
        : status.validation_state === 'valid' ? 'Saved session · last check passed'
          : status.validation_state === 'invalid' ? 'Saved session · last check failed' : 'No validated saved session';
  const buttonClass = 'px-3 py-2 rounded-lg border border-gray-200 bg-white text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500';
  const portal = integration === 'moengage' ? 'MoEngage' : integration === 'sms' ? 'VILPOWER' : 'Karix';
  const moeOrigin = typeof target?.identity.base_url === 'string' && /^https:\/\/dashboard(?:-\d{2})?\.moengage\.com\/?$/.test(target.identity.base_url)
    ? target.identity.base_url.replace(/\/$/, '') : null;
  const portalUrl = integration === 'moengage' ? moeOrigin && `${moeOrigin}/v4/campaigns/all?view=all`
    : integration === 'sms' ? 'https://www.vilpower.in/content_templates/contentIndex/'
      : 'https://www.karix.solutions/lounge/LoungePage/index.php';

  return (
    <section aria-labelledby={titleId} aria-busy={disabled} className="rounded-xl border border-blue-200 bg-blue-50/40 p-4 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id={titleId} className="text-sm font-bold text-gray-900">{accountTitle} · {integrationTitle} Auth Sync</h3>
          <p className="mt-1 text-xs text-gray-600">Credentials and device pairing are isolated to this account and integration.</p>
        </div>
        <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${validated ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : invalid ? 'border-red-200 bg-red-50 text-red-700' : 'border-gray-200 bg-white text-gray-600'}`}>{statusLabel}</span>
      </div>
      {target && <p className="text-xs text-gray-700">{target.message}</p>}
      <p className="text-xs text-gray-600">Service/API tokens and encryption keys require one-time setup from your provider or administrator and are saved securely on the server. The browser cannot create these keys; Auth Sync only transfers renewable browser sessions. Blank secret fields preserve saved values.</p>
      {target?.mode === 'setup_required' && <p className="text-xs text-amber-800">Configure the required account identity below (or ask your administrator) and save it, then refresh capabilities. Unknown WABAs, bots, and MoEngage workspaces are never adopted automatically.</p>}
      {target?.mode === 'setup_required' && status?.paired && <p className="text-xs text-amber-800">You still have paired devices for this scope. You can revoke them below even while identity setup is incomplete.</p>}
      {integration === 'sms' && target?.identity.entity_id && <p className="text-xs text-gray-700">Expected principal entity: TATA CAPITAL LIMITED · {target.identity.entity_id}. The backend verifies the live portal profile before saving the captured cookie. This connection registers templates; it never sends SMS.</p>}
      {browser && <>
        <details open={installed !== true} className="rounded-lg border border-blue-100 bg-white/70 p-3">
          <summary className="cursor-pointer text-xs font-semibold text-blue-800">Installation, login and account-switching steps</summary>
        <ol className="mt-3 list-decimal pl-5 text-xs text-gray-600 space-y-2">
          <li>Download this site’s extension ZIP and unzip it. In <code>chrome://extensions</code>, enable Developer mode, choose Load unpacked, and select the folder containing <code>manifest.json</code>.</li>
          <li>Reload Settings, detect the extension, then connect this account and integration. Pairing sends a single-use code, never your app login token.</li>
          <li>Open the configured {integration === 'rcs' ? 'RCS bot' : integration === 'whatsapp' ? 'WhatsApp WABA' : integration === 'sms' ? 'Tata principal entity’s Content Templates' : 'MoEngage workspace'} in {portal} and reload its inventory. If already paired, use “Use this target in browser” below to switch capture without reconnecting.</li>
        </ol>
        <p className="mt-3 text-xs text-gray-600">Sign in manually only if the provider portal session has expired; mobile OTP is not repeated just to sync. Only same-request credentials matching this configured target are transferred. Each account/channel is paired separately; an RCS popup target does not connect MoEngage.</p>
        </details>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={downloadExtension} disabled={disabled} className={buttonClass}>{action === 'download' ? 'Downloading...' : 'Download extension ZIP'}</button>
          <button type="button" onClick={detectExtension} disabled={disabled} className={buttonClass}>{action === 'detect' ? 'Detecting...' : 'Detect extension'}</button>
          <button type="button" onClick={connect} disabled={disabled || installed !== true || Boolean(statusError)} className="px-3 py-2 rounded-lg bg-blue-600 text-white text-xs font-semibold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">{action === 'connect' ? 'Connecting...' : 'Connect extension'}</button>
          {portalUrl && <a href={portalUrl} target="_blank" rel="noopener noreferrer" className={buttonClass}>Open {portal} portal</a>}
        </div>
        <p className="text-[11px] text-gray-500" role="status">{installed === null ? 'Detect the extension after installing this site’s download.' : installed ? 'Extension detected. Pairing and session validation are shown separately below.' : 'Extension not detected. Install this site’s download, reload Settings, then detect again.'}</p>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3 rounded-lg border border-gray-200 bg-white p-3 text-xs">
          <div><dt className="font-semibold text-gray-500">Backend device registrations</dt><dd className="mt-1 text-gray-800">{statusError ? 'Could not confirm pairing' : status?.paired ? 'At least one active device for this scope (not necessarily this browser)' : 'No confirmed active devices'}</dd></div>
          <div><dt className="font-semibold text-gray-500">Saved backend session</dt><dd className={`mt-1 ${invalid ? 'text-red-700' : 'text-gray-800'}`}>{statusError ? 'Could not confirm validation' : status?.validation_state === 'valid' ? 'Passed last backend check' : status?.validation_state === 'invalid' ? 'Last validation failed — reload the matching logged-in inventory and sync again' : 'Not validated yet'}</dd></div>
          <div><dt className="font-semibold text-gray-500">Last successful sync</dt><dd className="mt-1 text-gray-800">{status?.last_synced_at ? new Date(status.last_synced_at * 1000).toLocaleString() : 'No successful sync yet'}</dd></div>
          <div><dt className="font-semibold text-gray-500">Last validation</dt><dd className="mt-1 text-gray-800">{status?.last_validated_at ? new Date(status.last_validated_at * 1000).toLocaleString() : 'Not checked yet'}</dd></div>
        </dl>
        <div className="rounded-lg border border-gray-200 bg-white p-3 text-xs space-y-2" role="status" aria-live="polite">
          <p className="font-semibold text-gray-700">Current browser · {accountTitle} · {integrationTitle}</p>
          <p>{!browserStatus ? 'Current browser capture unavailable. Reload Auth Sync and this Settings page.' : !browserStatus.paired ? 'This browser is not paired for this account and integration.' : browserStatus.syncing ? 'Captured session is being validated by the backend.' : browserStatus.pending ? 'Matching session captured and pending sync. Retry below without reconnecting.' : 'This browser is paired; no captured session is waiting to sync.'}</p>
          {!statusError && status?.paired && browserStatus && !browserStatus.paired && <p className="text-amber-800">The server has an active device registration, but this browser has no active pairing for this scope. Connect this browser separately; another device’s session is not adopted.</p>}
          {browserStatus?.paired && !browserStatus.capture_active && <p className="text-amber-800">This target is not active for capture. Use this target below, then reload its matching portal inventory. Saved credentials for other targets stay separate.</p>}
          {browserStatus?.last_synced_at && <p className="text-gray-500">This browser’s last validated sync: {new Date(browserStatus.last_synced_at * 1000).toLocaleString()} (historical).</p>}
          {browserStatus?.error && <p className="text-red-700" role="alert">{syncError(browserStatus.error)}</p>}
          {browserStatus?.paired && !browserStatus.capture_active && <button type="button" onClick={selectTarget} disabled={disabled || browserStatus.syncing} className={buttonClass}>{action === 'select' ? 'Switching capture...' : 'Use this target in browser'}</button>}
          {browserStatus?.pending && browserStatus.paired && <button type="button" onClick={retryCapturedSession} disabled={disabled || browserStatus.syncing} className={buttonClass}>{action === 'retry' ? 'Retrying captured session...' : 'Retry captured session'}</button>}
        </div>
        {!statusError && status?.message && <p className="text-xs text-gray-600">{status.message}</p>}
      </>}
      {statusError && <p role="alert" className="text-xs text-red-700">{statusError} Any displayed timestamps are last known values.</p>}
      {feedback && <p role={feedback.type === 'error' ? 'alert' : 'status'} className={`rounded-lg border p-3 text-xs ${feedback.type === 'error' ? 'border-red-200 bg-red-50 text-red-700' : 'border-blue-200 bg-white text-blue-800'}`}>{feedback.message}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => { void perform('refresh', async (signal) => { await refresh(signal); return 'Capabilities and scoped status refreshed.'; }); }} disabled={disabled} className={buttonClass}>{action === 'refresh' ? 'Refreshing...' : 'Refresh capabilities / status'}</button>
        {browser && <button type="button" onClick={checkSession} disabled={disabled} className={buttonClass}>{action === 'check' ? 'Validating...' : 'Check saved session'}</button>}
        {target && target.mode !== 'unsupported' && <button type="button" onClick={disconnect} disabled={disabled} className={`${buttonClass} text-red-700`}>{action === 'disconnect' ? 'Revoking...' : 'Disconnect my scoped devices'}</button>}
      </div>
      {target && target.mode !== 'unsupported' && <p className="text-[11px] text-gray-500">Status refreshes when you return to this window. Disconnect affects only your devices and pending codes for this account and integration, not other users or the saved session.</p>}
    </section>
  );
}
