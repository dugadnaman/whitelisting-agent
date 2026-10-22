'use strict';
importScripts('config.js');

const AGENT_ORIGIN = globalThis.KARIX_SYNC_CONFIG.agentOrigin;
const agentUrl = new URL(AGENT_ORIGIN);
if (agentUrl.origin !== AGENT_ORIGIN || agentUrl.username || agentUrl.password ||
    (agentUrl.protocol !== 'https:' &&
     !(agentUrl.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(agentUrl.hostname)))) {
  throw new Error('Invalid extension agent origin.');
}
const WABA_ID = '286109054585247';
const ESMEADDR = '72148300000000';
const LOCAL_KEY = 'karixAuthSync';
const SESSION_KEY = 'karixAuthSyncSession';
const REQUEST_FILTER = {
  urls: ['https://rcsgui.karix.solutions/v1.0/templates/getAllTemplates*'],
  types: ['xmlhttprequest'],
};
const requests = new Map();
let deviceToken = null;
let deviceExpiresAt = 0;
let lastSuccessHash = null;
let lastSyncedAt = null;
let pendingSnapshot = null;
let lastError = '';
let syncing = false;
let generation = 0;
let operations = Promise.resolve();

function isSnapshot(value) {
  return value && value.waba_id === WABA_ID && value.esmeaddr === ESMEADDR &&
    ['bearer_token', 'session', 'user'].every(key =>
      typeof value[key] === 'string' && value[key].length > 0 &&
      value[key].length <= 16384 && !/[\r\n]/.test(value[key]));
}

const ready = (async () => {
  await Promise.all([
    chrome.storage.local.setAccessLevel({accessLevel: 'TRUSTED_CONTEXTS'}),
    chrome.storage.session.setAccessLevel({accessLevel: 'TRUSTED_CONTEXTS'}),
  ]);
  const [local, session] = await Promise.all([
    chrome.storage.local.get(LOCAL_KEY), chrome.storage.session.get(SESSION_KEY),
  ]);
  const saved = local[LOCAL_KEY] || {};
  deviceToken = typeof saved.deviceToken === 'string' ? saved.deviceToken : null;
  deviceExpiresAt = Number.isFinite(saved.deviceExpiresAt) ? saved.deviceExpiresAt : 0;
  lastSuccessHash = typeof saved.lastSuccessHash === 'string' ? saved.lastSuccessHash : null;
  lastSyncedAt = Number.isFinite(saved.lastSyncedAt) ? saved.lastSyncedAt : null;
  const transient = session[SESSION_KEY] || {};
  pendingSnapshot = isSnapshot(transient.pendingSnapshot) ? transient.pendingSnapshot : null;
  lastError = typeof transient.lastError === 'string' ? transient.lastError : '';
})();

// One queue owns all state writes, including network completions and disconnects.
function mutate(work) {
  const operation = operations.then(() => ready).then(work);
  operations = operation.catch(() => {});
  return operation;
}

function paired() {
  return Boolean(deviceToken && deviceExpiresAt > Date.now() / 1000);
}

function persistLocal() {
  return chrome.storage.local.set({[LOCAL_KEY]: {
    deviceToken, deviceExpiresAt, lastSuccessHash, lastSyncedAt,
  }});
}

function persistSession() {
  return chrome.storage.session.set({[SESSION_KEY]: {pendingSnapshot, lastError}});
}

function safeMessage(message, extraSecrets = []) {
  let text = typeof message === 'string' ? message : 'The request failed. Please retry.';
  const secrets = [deviceToken, pendingSnapshot?.bearer_token,
    pendingSnapshot?.session, pendingSnapshot?.user, ...extraSecrets];
  for (const secret of secrets) {
    if (typeof secret === 'string' && secret) text = text.split(secret).join('[redacted]');
  }
  return text.slice(0, 600);
}

async function api(path, {method = 'POST', body, authenticated = false, secrets = []} = {}) {
  let response;
  try {
    response = await fetch(`${AGENT_ORIGIN}/api/karix-extension/${path}`, {
      method,
      credentials: 'omit',
      redirect: 'error',
      cache: 'no-store',
      headers: {
        ...(body === undefined ? {} : {'Content-Type': 'application/json'}),
        ...(authenticated ? {Authorization: `Bearer ${deviceToken}`} : {}),
      },
      ...(body === undefined ? {} : {body: JSON.stringify(body)}),
      signal: AbortSignal.timeout(20000),
    });
  } catch {
    throw new Error('Could not reach the agent. Check your connection and retry.');
  }
  let result;
  try { result = await response.json(); } catch {
    throw new Error(`The agent returned an unreadable response (HTTP ${response.status}). Retry.`);
  }
  if (!response.ok) {
    throw new Error(safeMessage(result?.detail || `Agent request failed (HTTP ${response.status}).`, secrets));
  }
  return result;
}

async function snapshotHash(snapshot) {
  const bytes = new TextEncoder().encode(JSON.stringify([
    snapshot.bearer_token, snapshot.session, snapshot.user, snapshot.waba_id, snapshot.esmeaddr,
  ]));
  const digest = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  return Array.from(digest, byte => byte.toString(16).padStart(2, '0')).join('');
}

async function syncPending() {
  if (!paired()) {
    lastError = deviceToken ? 'Pairing expired. Reconnect from the agent Settings page.' : '';
    await persistSession();
    return {ok: false, message: lastError || 'Connect this extension from the agent Settings page first.'};
  }
  if (!pendingSnapshot) {
    return {ok: false, message: 'No complete Bajaj request is available. Log into Karix with your mobile OTP and open the Bajaj WhatsApp template list.'};
  }
  syncing = true;
  try {
    const hash = await snapshotHash(pendingSnapshot);
    if (hash !== lastSuccessHash) {
      const result = await api('sync', {body: pendingSnapshot, authenticated: true});
      if (result?.ok !== true || result.account !== 'bajaj' ||
          !Number.isFinite(result.last_synced_at) || result.last_synced_at <= 0) {
        throw new Error('The agent did not confirm Bajaj credential validation. Retry sync.');
      }
      lastSuccessHash = hash;
      lastSyncedAt = result.last_synced_at;
      await persistLocal();
    }
    pendingSnapshot = null;
    lastError = '';
    await persistSession();
    return {ok: true, message: 'Bajaj credentials were validated by the backend and synced.'};
  } catch (error) {
    lastError = safeMessage(error.message);
    await persistSession();
    return {ok: false, message: lastError};
  } finally {
    syncing = false;
  }
}

function isSettingsUrl(value) {
  try {
    const url = new URL(value);
    return url.origin === AGENT_ORIGIN && url.pathname === '/settings';
  } catch { return false; }
}

function settingsSender(sender) {
  return sender.id === chrome.runtime.id && sender.frameId === 0 &&
    isSettingsUrl(sender.url) && isSettingsUrl(sender.tab?.url);
}

function popupSender(sender) {
  const popupUrl = chrome.runtime.getURL('popup.html');
  return sender.id === chrome.runtime.id && sender.url === popupUrl &&
    (!sender.tab || sender.tab.url === popupUrl);
}

function status() {
  return {
    paired: paired(), can_disconnect: Boolean(deviceToken), last_synced_at: lastSyncedAt,
    error: lastError || (deviceToken && !paired() ? 'Pairing expired. Reconnect from Settings.' : ''),
    pending: Boolean(pendingSnapshot), syncing, agent_origin: AGENT_ORIGIN,
  };
}

async function pair(code) {
  try {
    const result = await api('redeem', {body: {code, agent_origin: AGENT_ORIGIN}, secrets: [code]});
    if (result?.account !== 'bajaj' || typeof result.device_token !== 'string' ||
        !result.device_token || !Number.isFinite(result.expires_at) ||
        result.expires_at <= Date.now() / 1000) {
      throw new Error('The agent did not return a valid Bajaj device pairing. Reconnect from Settings.');
    }
    deviceToken = result.device_token;
    deviceExpiresAt = result.expires_at;
    lastSuccessHash = null;
    lastSyncedAt = null;
    lastError = '';
    await persistLocal();
    await persistSession();
    if (pendingSnapshot) {
      const synced = await syncPending();
      return {ok: true, message: synced.ok ? synced.message : `Extension paired, but credentials have not been validated: ${synced.message}`};
    }
    return {ok: true, message: 'Extension paired. Log into Karix normally with your mobile OTP and open the Bajaj WhatsApp template list. Credentials are not synced until the backend validates them.'};
  } catch (error) {
    lastError = safeMessage(error.message, [code]);
    await persistSession();
    return {ok: false, message: lastError};
  }
}

async function disconnect() {
  let error = '';
  const hadDevice = Boolean(deviceToken);
  if (deviceToken) {
    try {
      const result = await api('device', {method: 'DELETE', authenticated: true});
      if (result?.ok !== true) throw new Error('The agent did not confirm device revocation.');
    } catch (failure) { error = safeMessage(failure.message); }
  }
  generation += 1;
  requests.clear();
  deviceToken = null;
  deviceExpiresAt = 0;
  lastSuccessHash = null;
  lastSyncedAt = null;
  pendingSnapshot = null;
  lastError = error ? `Disconnected locally. Server revocation failed: ${error} Revoke devices in agent Settings.` : '';
  await persistLocal();
  await persistSession();
  return {ok: !error, message: lastError || (hadDevice ? 'Disconnected locally and device revoked.' : 'Disconnected locally. Device revocation is available in agent Settings.')};
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message !== 'object') return false;
  let work;
  if (settingsSender(sender)) {
    if (message.type === 'KARIX_EXTENSION_PING') {
      sendResponse({ok: true, message: 'Karix Auth Sync is installed.'});
      return false;
    }
    if (message.type !== 'KARIX_EXTENSION_PAIR' || typeof message.code !== 'string' ||
        !message.code || message.code.length > 1024) return false;
    work = mutate(() => pair(message.code));
  } else if (popupSender(sender)) {
    if (message.type === 'KARIX_EXTENSION_STATUS') {
      work = ready.then(status);
    } else if (message.type === 'KARIX_EXTENSION_RETRY') {
      work = mutate(syncPending);
    } else if (message.type === 'KARIX_EXTENSION_DISCONNECT') {
      work = mutate(disconnect);
    } else return false;
  } else return false;
  work.then(sendResponse).catch(() => sendResponse({
    ok: false, message: 'Extension storage is unavailable. Reload the extension and retry.',
  }));
  return true;
});

function isTemplateRequest(details) {
  try {
    const url = new URL(details.url);
    return details.method === 'POST' && url.origin === 'https://rcsgui.karix.solutions' &&
      url.pathname === '/v1.0/templates/getAllTemplates';
  } catch { return false; }
}

function requestIdentity(body) {
  if (!body || body.error) return null;
  if (body.formData) {
    const waba = body.formData.wabaId;
    const esme = body.formData.esmeaddr;
    return waba?.length === 1 && esme?.length === 1 ? {wabaId: waba[0], esmeaddr: esme[0]} : null;
  }
  if (!body.raw?.length) return null;
  try {
    let length = 0;
    for (const part of body.raw) {
      if (!part.bytes || part.file) return null;
      length += part.bytes.byteLength;
    }
    if (!length || length > 262144) return null;
    const bytes = new Uint8Array(length);
    let offset = 0;
    for (const part of body.raw) {
      bytes.set(new Uint8Array(part.bytes), offset);
      offset += part.bytes.byteLength;
    }
    return JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes));
  } catch { return null; }
}

chrome.webRequest.onBeforeRequest.addListener(details => {
  if (!isTemplateRequest(details)) return;
  // Discard stale metadata without retaining portal headers indefinitely.
  const now = Date.now();
  for (const [id, record] of requests) {
    if (now - record.startedAt > 120000) requests.delete(id);
  }
  const identity = requestIdentity(details.requestBody);
  const validIdentityValue = value => typeof value === 'string' || Number.isSafeInteger(value);
  const valid = identity && validIdentityValue(identity.wabaId) && validIdentityValue(identity.esmeaddr) &&
    String(identity.wabaId) === WABA_ID && String(identity.esmeaddr) === ESMEADDR;
  requests.set(details.requestId, {
    generation, startedAt: now, snapshot: null,
    error: valid ? '' : 'Ignored a template request without the exact Bajaj WABA and ESME identity. Open the Bajaj WhatsApp template list.',
  });
}, REQUEST_FILTER, ['requestBody']);

chrome.webRequest.onBeforeSendHeaders.addListener(details => {
  const record = requests.get(details.requestId);
  if (!record || record.error || !isTemplateRequest(details)) return;
  const headers = new Map();
  for (const header of details.requestHeaders || []) {
    const name = header.name.toLowerCase();
    if (!['authorization', 'session', 'user'].includes(name)) continue;
    if (headers.has(name)) {
      record.error = 'The Karix request had ambiguous authentication headers. Reload the Bajaj template list.';
      record.snapshot = null;
      return;
    }
    headers.set(name, header.value);
  }
  const bearer = /^Bearer[\t ]+(\S+)$/i.exec((headers.get('authorization') || '').trim());
  const snapshot = {
    bearer_token: bearer?.[1] || '', session: (headers.get('session') || '').trim(),
    user: (headers.get('user') || '').trim(), waba_id: WABA_ID, esmeaddr: ESMEADDR,
  };
  if (!isSnapshot(snapshot)) {
    record.error = 'The Karix request did not contain complete Authorization, Session and User headers. Log in normally and reload the Bajaj template list.';
    record.snapshot = null;
    return;
  }
  record.snapshot = snapshot;
}, REQUEST_FILTER, ['requestHeaders', 'extraHeaders']);

function captureFailure(message, captureGeneration) {
  return mutate(async () => {
    if (captureGeneration !== generation) return;
    lastError = message;
    await persistSession();
  });
}

chrome.webRequest.onCompleted.addListener(details => {
  const record = requests.get(details.requestId);
  requests.delete(details.requestId);
  if (!record || !isTemplateRequest(details)) return;
  if (details.statusCode < 200 || details.statusCode >= 300 || details.fromCache) {
    void captureFailure('Karix did not complete a fresh successful template-list request. Log in normally and reload the Bajaj WhatsApp template list.', record.generation).catch(() => {});
    return;
  }
  if (record.error || !record.snapshot) {
    void captureFailure(record.error || 'No complete Karix credentials were observed. Reload the Bajaj WhatsApp template list.', record.generation).catch(() => {});
    return;
  }
  void mutate(async () => {
    if (record.generation !== generation) return;
    pendingSnapshot = record.snapshot;
    lastError = '';
    await persistSession();
    await syncPending();
  }).catch(() => {});
}, REQUEST_FILTER);

chrome.webRequest.onErrorOccurred.addListener(details => {
  const record = requests.get(details.requestId);
  requests.delete(details.requestId);
  if (record) {
    void captureFailure('The Karix template request failed. Check your connection, log in normally and reload the Bajaj WhatsApp template list.', record.generation).catch(() => {});
  }
}, REQUEST_FILTER);

chrome.webRequest.onBeforeRedirect.addListener(details => {
  const record = requests.get(details.requestId);
  requests.delete(details.requestId);
  if (record) {
    void captureFailure('Karix redirected the template request. Log in normally and reload the Bajaj WhatsApp template list.', record.generation).catch(() => {});
  }
}, REQUEST_FILTER);
