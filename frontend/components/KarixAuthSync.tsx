'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { fetchWithRetry, getApiUrl, getErrorMessage } from '@/lib/api';

type SyncStatus = {
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

function isSyncStatus(value: unknown): value is SyncStatus {
  return typeof value === 'object' && value !== null &&
    'paired' in value && typeof value.paired === 'boolean' &&
    'last_synced_at' in value && isTimestamp(value.last_synced_at) &&
    'last_validated_at' in value && isTimestamp(value.last_validated_at) &&
    'validation_state' in value && (value.validation_state === 'never' || value.validation_state === 'valid' || value.validation_state === 'invalid') &&
    'message' in value && typeof value.message === 'string';
}

async function request(path: string, signal: AbortSignal, method = 'GET', body?: object) {
  const response = await fetchWithRetry(getApiUrl(`/api/karix-extension/${path}`), {
    method,
    signal,
    redirect: 'error',
    credentials: 'omit',
    cache: 'no-store',
    ...(body ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : {}),
  }, 0, 800, 20000);
  if (!response.ok) throw new Error(await getErrorMessage(response));
  return response;
}

function extensionMessage(type: 'KARIX_EXTENSION_PING' | 'KARIX_EXTENSION_PAIR', signal: AbortSignal, code?: string): Promise<void> {
  signal.throwIfAborted();
  const { promise, resolve, reject } = Promise.withResolvers<void>();
  const requestId = crypto.randomUUID();
  const origin = window.location.origin;
  const cleanup = () => {
    window.clearTimeout(timer);
    window.removeEventListener('message', onMessage);
    signal.removeEventListener('abort', onAbort);
  };
  const onAbort = () => {
    cleanup();
    reject(signal.reason);
  };
  const onMessage = (event: MessageEvent<unknown>) => {
    if (event.source !== window || event.origin !== origin) return;
    const data = event.data;
    if (typeof data !== 'object' || data === null ||
        !('type' in data) || data.type !== 'KARIX_EXTENSION_RESULT' ||
        !('requestId' in data) || data.requestId !== requestId ||
        !('ok' in data) || typeof data.ok !== 'boolean' ||
        !('message' in data) || typeof data.message !== 'string') return;
    cleanup();
    if (data.ok) resolve();
    else reject(new Error(data.message || 'The extension could not complete the request.'));
  };
  const timer = window.setTimeout(() => {
    cleanup();
    reject(new Error(type === 'KARIX_EXTENSION_PAIR'
      ? 'The extension did not confirm pairing in time. Refresh status before trying Connect again.'
      : 'Karix Auth Sync did not respond. Install the extension downloaded from this site and reload Settings.'));
  }, type === 'KARIX_EXTENSION_PAIR' ? 45000 : 2500);
  window.addEventListener('message', onMessage);
  signal.addEventListener('abort', onAbort, { once: true });
  try {
    window.postMessage({ type, requestId, ...(code ? { code } : {}) }, origin);
  } catch (error) {
    cleanup();
    reject(error);
  }
  return promise;
}

export default function KarixAuthSync() {
  const [status, setStatus] = useState<SyncStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [installed, setInstalled] = useState<boolean | null>(null);
  const [action, setAction] = useState<Action | null>(null);
  const [feedback, setFeedback] = useState<Feedback>(null);
  const lifecycle = useRef<AbortController | null>(null);
  const busy = useRef(false);
  const download = useRef<{ url?: string; timer?: number }>({});

  const readStatus = useCallback(async (signal: AbortSignal, path = 'status', method = 'GET') => {
    try {
      const response = await request(path, signal, method);
      const next: unknown = await response.json();
      if (!isSyncStatus(next)) throw new Error('The server returned an unexpected auth sync status.');
      signal.throwIfAborted();
      setStatus(next);
      setStatusError(null);
      return next;
    } catch (error) {
      if (!signal.aborted) setStatusError(error instanceof Error ? error.message : 'Could not refresh auth sync status.');
      throw error;
    }
  }, []);

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
      if (!controller.signal.aborted && announce) {
        setFeedback({ type: 'error', message: error instanceof Error ? error.message : 'The request failed. Please try again.' });
      }
    } finally {
      if (!controller.signal.aborted) {
        busy.current = false;
        setAction(null);
      }
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    lifecycle.current = controller;
    busy.current = false;
    const refresh = () => { void perform('refresh', async (signal) => { await readStatus(signal); }, false); };
    void perform('refresh', async (signal) => {
      await Promise.all([
        readStatus(signal).then(() => undefined).catch(() => undefined),
        extensionMessage('KARIX_EXTENSION_PING', signal)
          .then(() => { if (!signal.aborted) setInstalled(true); })
          .catch(() => { if (!signal.aborted) setInstalled(false); }),
      ]);
    }, false);
    window.addEventListener('focus', refresh);
    return () => {
      controller.abort();
      window.removeEventListener('focus', refresh);
      window.clearTimeout(download.current.timer);
      if (download.current.url) URL.revokeObjectURL(download.current.url);
      download.current = {};
    };
  }, [perform, readStatus]);

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
      return 'Extension ZIP downloaded for this site. Unzip it, install it in Chrome, then reload Settings.';
    });
  }

  function detectExtension() {
    void perform('detect', async (signal) => {
      try {
        await extensionMessage('KARIX_EXTENSION_PING', signal);
        if (!signal.aborted) setInstalled(true);
        return 'Karix Auth Sync is installed for this site.';
      } catch (error) {
        if (!signal.aborted) setInstalled(false);
        throw error;
      }
    });
  }

  function connect() {
    void perform('connect', async (signal) => {
      const response = await request('pairing', signal, 'POST', { agent_origin: window.location.origin });
      const pairing = await response.json();
      if (typeof pairing?.code !== 'string' || !pairing.code ||
          typeof pairing.expires_at !== 'number' || !Number.isFinite(pairing.expires_at) ||
          pairing.expires_at <= Date.now() / 1000) {
        throw new Error('The server did not issue a valid pairing code. Please try again.');
      }
      signal.throwIfAborted();
      await extensionMessage('KARIX_EXTENSION_PAIR', signal, pairing.code);
      const next = await readStatus(signal);
      if (!next.paired) throw new Error('The server has not confirmed an active extension device. Refresh status before trying Connect again.');
      return next.validation_state === 'valid'
        ? 'Extension connected. The saved Bajaj session has passed backend validation; future captures are validated before saving.'
        : 'Extension connected, but a valid session is still required. Log in to Karix with mobile OTP and open the Bajaj WhatsApp template list. Captures are successful only after backend validation.';
    });
  }

  function checkSession() {
    void perform('check', async (signal) => {
      const next = await readStatus(signal, 'check', 'POST');
      if (next.validation_state !== 'valid') throw new Error(next.message || 'The saved Bajaj session could not be validated. Log in to Karix and open the template list to sync again.');
      return 'The backend validated the saved Bajaj session. No credentials were changed by this check.';
    });
  }

  function disconnect() {
    void perform('disconnect', async (signal) => {
      const response = await request('pairing', signal, 'DELETE');
      const result = await response.json();
      if (result?.ok !== true) throw new Error('The server did not confirm device revocation. Refresh status and try again.');
      signal.throwIfAborted();
      setStatus((previous) => previous ? { ...previous, paired: false } : previous);
      try {
        await readStatus(signal);
      } catch (error) {
        throw new Error(`Your devices were revoked, but status could not be refreshed. ${error instanceof Error ? error.message : 'Please refresh status.'}`);
      }
      return 'Your extension devices and pending pairing codes were revoked. The shared Bajaj session was not deleted. Use Connect to pair this browser again.';
    });
  }

  const disabled = action !== null;
  const validated = !statusError && status?.paired && status.validation_state === 'valid';
  const invalid = !statusError && status?.validation_state === 'invalid';
  const statusLabel = statusError ? 'Status unavailable' : !status ? 'Loading status' : !status.paired
    ? 'Disconnected / revoked' : status.validation_state === 'valid'
      ? 'Connected · last check passed' : status.validation_state === 'invalid'
        ? 'Paired · session invalid' : 'Paired · awaiting valid session';
  const buttonClass = 'px-3 py-2 rounded-lg border border-gray-200 bg-white text-xs font-semibold text-gray-700 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500';

  return (
    <section aria-labelledby="karix-auth-sync-title" aria-busy={disabled} className="rounded-xl border border-blue-200 bg-blue-50/40 p-4 space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 id="karix-auth-sync-title" className="text-sm font-bold text-gray-900">Bajaj WhatsApp · Karix Chrome Auth Sync</h3>
          <p className="mt-1 text-xs text-gray-600">Sync a complete Karix portal session from Chrome without copying credentials into Settings.</p>
        </div>
        <span className={`rounded-full border px-2.5 py-1 text-[11px] font-semibold ${validated ? 'border-emerald-200 bg-emerald-50 text-emerald-700' : invalid ? 'border-red-200 bg-red-50 text-red-700' : 'border-gray-200 bg-white text-gray-600'}`}>{statusLabel}</span>
      </div>

      <ol className="list-decimal pl-5 text-xs text-gray-600 space-y-2">
        <li>Download the extension ZIP below and unzip it into a folder you will keep on this computer. This download is configured only for this Settings site.</li>
        <li>In Chrome, open <code className="font-mono text-gray-800">chrome://extensions</code>, enable <strong>Developer mode</strong>, choose <strong>Load unpacked</strong>, and select the unzipped folder containing <code>manifest.json</code>.</li>
        <li>Reload this Settings page, detect the extension, then choose <strong>Connect extension</strong>. Pairing uses a single-use code that expires in five minutes, not your app login token.</li>
        <li>Open your usual Karix portal, log in normally with your mobile OTP, and open the <strong>Bajaj WhatsApp template list</strong> (WABA <code>286109054585247</code>). Return here to refresh status.</li>
      </ol>
      <p className="text-xs text-gray-600">Login and OTP entry remain manual. The extension does not automate login or capture other accounts. Only complete same-request credentials are synced, and the backend validates them before saving. If a sync fails, open the extension popup for the error and Retry sync.</p>

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={downloadExtension} disabled={disabled} className={buttonClass}>{action === 'download' ? 'Downloading...' : 'Download extension ZIP'}</button>
        <button type="button" onClick={detectExtension} disabled={disabled} className={buttonClass}>{action === 'detect' ? 'Detecting...' : 'Detect extension'}</button>
        <button type="button" onClick={connect} disabled={disabled || installed !== true} className="px-3 py-2 rounded-lg bg-blue-600 text-white text-xs font-semibold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2">{action === 'connect' ? 'Connecting...' : 'Connect extension'}</button>
      </div>
      <p className="text-[11px] text-gray-500" role="status">{installed === null ? 'Checking for the extension...' : installed ? 'Extension detected for this site. Device pairing and session validation are shown separately below.' : 'Extension not detected. Install this site’s download and reload Settings, then detect again.'}</p>

      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-3 rounded-lg border border-gray-200 bg-white p-3 text-xs">
        <div><dt className="font-semibold text-gray-500">Your device pairing</dt><dd className="mt-1 text-gray-800">{statusError ? 'Could not confirm current pairing' : status ? status.paired ? 'At least one active device for your account' : 'No active devices; not paired or revoked' : 'Loading...'}</dd></div>
        <div><dt className="font-semibold text-gray-500">Shared Bajaj session</dt><dd className={`mt-1 ${invalid ? 'text-red-700' : 'text-gray-800'}`}>{statusError ? 'Could not confirm current validation' : status?.validation_state === 'valid' ? 'Passed the last backend validation check' : status?.validation_state === 'invalid' ? 'Invalid or expired — log in and sync again' : 'Not validated yet'}</dd></div>
        <div><dt className="font-semibold text-gray-500">Last successful sync</dt><dd className="mt-1 text-gray-800">{status?.last_synced_at ? new Date(status.last_synced_at * 1000).toLocaleString() : 'No successful extension sync yet'}</dd></div>
        <div><dt className="font-semibold text-gray-500">Last backend validation check</dt><dd className="mt-1 text-gray-800">{status?.last_validated_at ? new Date(status.last_validated_at * 1000).toLocaleString() : 'Not checked yet'}</dd></div>
      </dl>
      {!statusError && status?.message && <p className="text-xs text-gray-600">{status.message}</p>}
      {statusError && <p role="alert" className="text-xs text-red-700">Status could not be refreshed: {statusError} Any timestamps above are last known values.</p>}
      {feedback && <p role={feedback.type === 'error' ? 'alert' : 'status'} className={`rounded-lg border p-3 text-xs ${feedback.type === 'error' ? 'border-red-200 bg-red-50 text-red-700' : 'border-blue-200 bg-white text-blue-800'}`}>{feedback.message}</p>}
      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={() => { void perform('refresh', async (signal) => { await readStatus(signal); return 'Auth sync status refreshed.'; }); }} disabled={disabled} className={buttonClass}>{action === 'refresh' ? 'Refreshing...' : 'Refresh status'}</button>
        <button type="button" onClick={checkSession} disabled={disabled} className={buttonClass}>{action === 'check' ? 'Validating with backend...' : 'Check saved session'}</button>
        <button type="button" onClick={disconnect} disabled={disabled} className={`${buttonClass} text-red-700`}>{action === 'disconnect' ? 'Revoking devices...' : 'Disconnect my devices'}</button>
      </div>
      <p className="text-[11px] text-gray-500">Status refreshes when you return to this window. Disconnect revokes all of your paired devices and pending codes, not other users’ devices or the shared session. The extension popup also has a local Disconnect option.</p>
    </section>
  );
}
