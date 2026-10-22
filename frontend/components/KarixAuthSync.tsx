'use client';

import { useCallback, useEffect, useId, useRef, useState } from 'react';
import { fetchWithRetry, getApiUrl, getErrorMessage } from '@/lib/api';

type Integration = 'whatsapp' | 'rcs' | 'sms' | 'moengage';
type Scope = { account: string; integration: Integration };
type SyncTarget = Scope & {
  mode: 'browser' | 'static' | 'setup_required';
  identity: { waba_id?: string; esmeaddr?: string; bot_ids?: string[]; base_url?: string; workspace_id?: string };
  message: string;
};
type SyncStatus = Scope & {
  paired: boolean;
  last_synced_at: number | null;
  last_validated_at: number | null;
  validation_state: 'never' | 'valid' | 'invalid';
  message: string;
};
type Action = 'refresh' | 'detect' | 'download' | 'connect' | 'check' | 'disconnect';
type Feedback = { type: 'success' | 'error'; message: string } | null;

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
    'mode' in value && (value.mode === 'browser' || value.mode === 'static' || value.mode === 'setup_required') &&
    'message' in value && typeof value.message === 'string' &&
    'identity' in value && typeof value.identity === 'object' && value.identity !== null;
}

async function request(path: string, signal: AbortSignal, method = 'GET', body?: object) {
  const response = await fetchWithRetry(getApiUrl(`/api/karix-extension/${path}`), {
    method, signal, redirect: 'error', credentials: 'omit', cache: 'no-store',
    ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
  }, 0, 800, 20000);
  if (!response.ok) throw new Error(await getErrorMessage(response));
  return response;
}

function extensionMessage(type: 'KARIX_EXTENSION_PING' | 'KARIX_EXTENSION_PAIR', signal: AbortSignal, pairing?: Scope & { code: string }): Promise<void> {
  signal.throwIfAborted();
  const { promise, resolve, reject } = Promise.withResolvers<void>();
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
    if (data.ok && pairing && (!('account' in data) || data.account !== pairing.account ||
        !('integration' in data) || data.integration !== pairing.integration)) {
      cleanup();
      reject(new Error('The extension confirmed a different account or integration. Refresh scoped status before retrying.'));
      return;
    }
    cleanup();
    if (data.ok) resolve();
    else reject(new Error(data.message || 'The extension could not complete the request.'));
  };
  const timer = window.setTimeout(() => {
    cleanup();
    reject(new Error(type === 'KARIX_EXTENSION_PAIR'
      ? 'Pairing was not confirmed in time. Refresh status before trying Connect again.'
      : 'Auth Sync did not respond. Install this site’s extension and reload Settings.'));
  }, type === 'KARIX_EXTENSION_PAIR' ? 45000 : 2500);
  window.addEventListener('message', onMessage);
  signal.addEventListener('abort', onAbort, { once: true });
  try { window.postMessage({ type, requestId, ...pairing }, origin); }
  catch (error) { cleanup(); reject(error); }
  return promise;
}

export default function KarixAuthSync({ account, integration }: Scope) {
  const titleId = useId();
  const [target, setTarget] = useState<SyncTarget | null>(null);
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [installed, setInstalled] = useState<boolean | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const lifecycle = useRef<AbortController | null>(null);
  const busy = useRef(false);
  const download = useRef<{ url?: string; timer?: number }>({});
  const scopeQuery = new URLSearchParams({ account, integration }).toString();

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
      if (integration !== 'sms') await readStatus(signal);
      else setStatus(null);
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
    setTarget(null);
    setStatus(null);
    setStatusError(null);
    setInstalled(null);
    setFeedback(null);
    const onFocus = () => { void perform('refresh', refresh, false); };
    void perform('refresh', refresh, false);
    window.addEventListener('focus', onFocus);
    return () => {
      controller.abort();
      window.removeEventListener('focus', onFocus);
      window.clearTimeout(download.current.timer);
      if (download.current.url) URL.revokeObjectURL(download.current.url);
      download.current = {};
    };
  }, [perform, refresh]);

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
        await extensionMessage('KARIX_EXTENSION_PING', signal);
        if (!signal.aborted) setInstalled(true);
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
      if (!next.paired) throw new Error('No active scoped device was confirmed. Refresh status before connecting again.');
      return next.validation_state === 'valid'
        ? 'Connected for this account and integration. The saved session passed backend validation.'
        : 'Connected. Log in normally to the matching portal workspace and open its template list to transfer a validated session.';
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

  const disabled = action !== null;
  const browser = target?.mode === 'browser';
  const validated = browser && !statusError && status?.paired && status.validation_state === 'valid';
  const invalid = !statusError && status?.validation_state === 'invalid';
  const statusLabel = statusError ? 'Status unavailable' : !target ? 'Loading capabilities'
    : target.mode === 'static' ? 'One-time setup' : target.mode === 'setup_required' ? 'Setup required'
      : !status ? 'Loading status' : !status.paired ? 'Disconnected / revoked'
        : status.validation_state === 'valid' ? 'Connected · last check passed'
          : status.validation_state === 'invalid' ? 'Paired · session invalid' : 'Paired · awaiting valid session';
  const buttonClass = 'px-3 py-2 rounded-lg border border-gray-200 bg-white text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500';
  const portal = integration === 'moengage' ? 'MoEngage' : 'Karix';

  return (
    <section aria-labelledby={titleId} aria-busy={disabled} className="rounded-xl border border-blue-200 bg-blue-50/40 p-4 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id={titleId} className="text-sm font-bold text-gray-900">{account} · {integration.toUpperCase()} Auth Sync</h3>
          <p className="mt-1 text-xs text-gray-600">Credentials and device pairing are isolated to this account and integration.</p>
        </div>
        <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${validated ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : invalid ? 'border-red-200 bg-red-50 text-red-700' : 'border-gray-200 bg-white text-gray-600'}`}>{statusLabel}</span>
      </div>
      {target && <p className="text-xs text-gray-700">{target.message}</p>}
      <p className="text-xs text-gray-600">Service/API tokens and encryption keys require one-time setup from your provider or administrator and are saved securely on the server. The browser cannot create these keys; Auth Sync only transfers renewable browser sessions. Blank secret fields preserve saved values.</p>
      {target?.mode === 'setup_required' && <p className="text-xs text-amber-800">Configure the required account identity below (or ask your administrator) and save it, then refresh capabilities. Unknown WABAs, bots, and MoEngage workspaces are never adopted automatically.</p>}
      {target?.mode === 'setup_required' && status?.paired && <p className="text-xs text-amber-800">You still have paired devices for this scope. You can revoke them below even while identity setup is incomplete.</p>}
      {target?.mode === 'static' && <p className="text-xs text-gray-600">Enter the existing SMS service/API key, encryption key, and routing details below once, then Save Credentials. No extension pairing or mobile OTP bypass is available for static keys.</p>}
      {browser && <>
        <ol className="list-decimal pl-5 text-xs text-gray-600 space-y-2">
          <li>Download this site’s extension ZIP and unzip it. In <code>chrome://extensions</code>, enable Developer mode, choose Load unpacked, and select the folder containing <code>manifest.json</code>.</li>
          <li>Reload Settings, detect the extension, then connect this account and integration. Pairing sends a single-use code, never your app login token.</li>
          <li>Open {portal}, log in normally{integration !== 'moengage' ? ' with your mobile OTP' : ''}, select the configured workspace, and open its {integration === 'rcs' ? 'RCS' : integration === 'whatsapp' ? 'WhatsApp' : ''} template list.</li>
        </ol>
        <p className="text-xs text-gray-600">Login and OTP remain manual. Only same-request session credentials matching the configured provider identity are transferred and validated. Pair each account/channel separately; WhatsApp and RCS tokens are not shared. For capture errors, use Retry sync for this target in the extension popup.</p>
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={downloadExtension} disabled={disabled} className={buttonClass}>{action === 'download' ? 'Downloading...' : 'Download extension ZIP'}</button>
          <button type="button" onClick={detectExtension} disabled={disabled} className={buttonClass}>{action === 'detect' ? 'Detecting...' : 'Detect extension'}</button>
          <button type="button" onClick={connect} disabled={disabled || installed !== true || Boolean(statusError)} className="px-3 py-2 rounded-lg bg-blue-600 text-white text-xs font-semibold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500">{action === 'connect' ? 'Connecting...' : 'Connect extension'}</button>
        </div>
        <p className="text-[11px] text-gray-500" role="status">{installed === null ? 'Detect the extension after installing this site’s download.' : installed ? 'Extension detected. Pairing and session validation are shown separately below.' : 'Extension not detected. Install this site’s download, reload Settings, then detect again.'}</p>
        <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3 rounded-lg border border-gray-200 bg-white p-3 text-xs">
          <div><dt className="font-semibold text-gray-500">Your scoped devices</dt><dd className="mt-1 text-gray-800">{statusError ? 'Could not confirm pairing' : status?.paired ? 'At least one active device for this scope' : 'No confirmed active devices'}</dd></div>
          <div><dt className="font-semibold text-gray-500">Saved scoped session</dt><dd className={`mt-1 ${invalid ? 'text-red-700' : 'text-gray-800'}`}>{statusError ? 'Could not confirm validation' : status?.validation_state === 'valid' ? 'Passed last backend check' : status?.validation_state === 'invalid' ? 'Invalid or expired — log in and sync again' : 'Not validated yet'}</dd></div>
          <div><dt className="font-semibold text-gray-500">Last successful sync</dt><dd className="mt-1 text-gray-800">{status?.last_synced_at ? new Date(status.last_synced_at * 1000).toLocaleString() : 'No successful sync yet'}</dd></div>
          <div><dt className="font-semibold text-gray-500">Last validation</dt><dd className="mt-1 text-gray-800">{status?.last_validated_at ? new Date(status.last_validated_at * 1000).toLocaleString() : 'Not checked yet'}</dd></div>
        </dl>
        {!statusError && status?.message && <p className="text-xs text-gray-600">{status.message}</p>}
      </>}
      {statusError && <p role="alert" className="text-xs text-red-700">{statusError} Any displayed timestamps are last known values.</p>}
      {feedback && <p role={feedback.type === 'error' ? 'alert' : 'status'} className={`rounded-lg border p-3 text-xs ${feedback.type === 'error' ? 'border-red-200 bg-red-50 text-red-700' : 'border-blue-200 bg-white text-blue-800'}`}>{feedback.message}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => { void perform('refresh', async (signal) => { await refresh(signal); return 'Capabilities and scoped status refreshed.'; }); }} disabled={disabled} className={buttonClass}>{action === 'refresh' ? 'Refreshing...' : 'Refresh capabilities / status'}</button>
        {browser && <button type="button" onClick={checkSession} disabled={disabled} className={buttonClass}>{action === 'check' ? 'Validating...' : 'Check saved session'}</button>}
        {target && integration !== 'sms' && <button type="button" onClick={disconnect} disabled={disabled} className={`${buttonClass} text-red-700`}>{action === 'disconnect' ? 'Revoking...' : 'Disconnect my scoped devices'}</button>}
      </div>
      {target && integration !== 'sms' && <p className="text-[11px] text-gray-500">Status refreshes when you return to this window. Disconnect affects only your devices and pending codes for this account and integration, not other users or the saved session.</p>}
    </section>
  );
}
