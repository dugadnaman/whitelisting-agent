'use strict';
importScripts('config.js');

const AGENT_ORIGIN = globalThis.KARIX_SYNC_CONFIG.agentOrigin;
const agentUrl = new URL(AGENT_ORIGIN);
if (agentUrl.origin !== AGENT_ORIGIN || agentUrl.username || agentUrl.password ||
    (agentUrl.protocol !== 'https:' &&
     !(agentUrl.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(agentUrl.hostname)))) {
  throw new Error('Invalid extension agent origin.');
}
const LOCAL_KEY = 'karixAuthSync';
const SESSION_KEY = 'karixAuthSyncSession';
const REQUEST_FILTER = {
  urls: ['https://rcsgui.karix.solutions/*', 'https://*.moengage.com/*'],
  types: ['xmlhttprequest'],
};
const INTEGRATIONS = ['whatsapp', 'rcs', 'moengage'];
const ERROR_MESSAGES = {
  device_expired: 'This browser’s device pairing expired or was revoked. Reconnect only this account and integration in Settings; your portal login is separate.',
  scope_denied: 'This device is not authorized for the selected account and integration. Check this exact target in Settings; do not copy a session from another account.',
  identity_conflict: 'The captured identity does not match this target’s configured identity. Select its exact configured bot, WABA, or MoEngage workspace and reload its inventory.',
  provider_validation_failed: 'The provider did not validate the captured session. Reload the matching inventory in your already logged-in portal and retry. If that inventory works but sync still fails, ask your administrator to check provider validation; do not re-pair or repeat OTP just to retry.',
  incomplete_session: 'The captured session is incomplete. Reload this exact target’s inventory in the already logged-in portal to capture all required headers together.',
  schema_rejected: 'The agent rejected the captured session format or size. Use extension 2.0.3 and reload this target’s inventory. Credentials are never truncated; ask your administrator if this repeats.',
  capture_invalid: 'The matching request had incomplete, conflicting, or oversized authentication. Reload this exact target’s inventory in the already logged-in portal. Limits: bearer/refresh 16000, session 1000, user 300, cookie 32000, bot 200 characters.',
  inventory_failed: 'The inventory request did not complete with a fresh successful response. Check the portal connection and reload this exact target’s inventory; sign in only if the portal session itself has expired.',
  network_error: 'Could not reach the agent. Check your connection and retry the captured session.',
  request_failed: 'The agent could not complete this request. Retry for this exact target or ask your administrator to check the service.',
};
function failure(code) { return Object.assign(new Error(ERROR_MESSAGES[code]), {code}); }
const requests = new Map();
let devices = {};
let transient = {};
let pairingError = '';
let activeTarget = '';
let operations = Promise.resolve();

function validScope(value) {
  return value && typeof value.account === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value.account) &&
    INTEGRATIONS.includes(value.integration);
}
function scopeKey(value) { return `${value.account}/${value.integration}`; }
function valueString(value) {
  return typeof value === 'string' || Number.isSafeInteger(value) ? String(value) : '';
}
function credential(value, limit = 16000) {
  return typeof value === 'string' && value.length > 0 && value.length <= limit && !/[\r\n]/.test(value);
}
function dashboardOrigin(value) {
  return typeof value === 'string' && /^https:\/\/dashboard(?:-\d+)?\.moengage\.com$/.test(value);
}
function normalizedIdentity(integration, value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  if (integration === 'whatsapp') {
    return /^\d{1,64}$/.test(value.waba_id) && /^\d{1,64}$/.test(value.esmeaddr)
      ? {waba_id: value.waba_id, esmeaddr: value.esmeaddr} : null;
  }
  if (integration === 'rcs') {
    if (!Array.isArray(value.bot_ids) || !value.bot_ids.length || value.bot_ids.length > 100 ||
        !value.bot_ids.every(bot => typeof bot === 'string' && /^[A-Za-z0-9_.@-]{1,200}$/.test(bot)) ||
        (value.esmeaddr !== undefined && !/^\d{1,64}$/.test(value.esmeaddr))) return null;
    return {bot_ids: [...new Set(value.bot_ids)], ...(value.esmeaddr ? {esmeaddr: value.esmeaddr} : {})};
  }
  if (integration === 'moengage' && dashboardOrigin(value.base_url) &&
      typeof value.workspace_id === 'string' && /^[A-Za-z0-9_-]{1,128}$/.test(value.workspace_id)) {
    return {base_url: value.base_url, workspace_id: value.workspace_id};
  }
  return null;
}
function paired(device) { return Boolean(device?.deviceToken && device.deviceExpiresAt > Date.now() / 1000); }
function stateFor(key) {
  return transient[key] ||= {pendingSnapshot: null, lastError: '', lastErrorCode: '', syncing: false};
}
function isSnapshot(value, device) {
  if (!validScope(value) || scopeKey(value) !== scopeKey(device) || !credential(value.bearer_token)) return false;
  const expected = device.identity;
  if (device.integration === 'whatsapp') {
    return value.waba_id === expected.waba_id && value.esmeaddr === expected.esmeaddr &&
      credential(value.session, 1000) && credential(value.user, 300);
  }
  if (device.integration === 'rcs') {
    return credential(value.bot_id, 200) && expected.bot_ids.includes(value.bot_id) &&
      (value.esmeaddr === undefined || value.esmeaddr === expected.esmeaddr) &&
      ['session', 'user'].every(key => value[key] === undefined || credential(value[key], key === 'session' ? 1000 : 300));
  }
  return value.base_url === expected.base_url && value.workspace_id === expected.workspace_id &&
    credential(value.refresh_token) && credential(value.cookie, 32000);
}
function persistLocal() { return chrome.storage.local.set({[LOCAL_KEY]: {version: 2, devices, activeTarget}}); }
function persistSession() { return chrome.storage.session.set({[SESSION_KEY]: {targets: transient, pairingError}}); }
const ready = (async () => {
  await Promise.all([
    chrome.storage.local.setAccessLevel({accessLevel: 'TRUSTED_CONTEXTS'}),
    chrome.storage.session.setAccessLevel({accessLevel: 'TRUSTED_CONTEXTS'}),
  ]);
  const [local, session] = await Promise.all([
    chrome.storage.local.get(LOCAL_KEY), chrome.storage.session.get(SESSION_KEY),
  ]);
  const saved = local[LOCAL_KEY] || {};
  const stored = saved.devices || {};
  for (const [key, device] of Object.entries(stored)) {
    if (validScope(device) && key === scopeKey(device) && credential(device.deviceToken) &&
        Number.isFinite(device.deviceExpiresAt) && normalizedIdentity(device.integration, device.identity)) {
      devices[key] = {
        account: device.account, integration: device.integration, deviceToken: device.deviceToken,
        deviceExpiresAt: device.deviceExpiresAt, identity: normalizedIdentity(device.integration, device.identity),
        lastSyncedAt: Number.isFinite(device.lastSyncedAt) ? device.lastSyncedAt : null,
      };
    }
  }
  // The previous release only ever paired this exact scope. Preserve its token, including expired tokens.
  if (credential(saved.deviceToken) && !devices['bajaj/whatsapp']) {
    devices['bajaj/whatsapp'] = {
      account: 'bajaj', integration: 'whatsapp', deviceToken: saved.deviceToken,
      deviceExpiresAt: Number.isFinite(saved.deviceExpiresAt) ? saved.deviceExpiresAt : 0,
      identity: {waba_id: '286109054585247', esmeaddr: '72148300000000'},
      lastSyncedAt: saved.lastSyncedAt || null,
    };
  }
  activeTarget = typeof saved.activeTarget === 'string' && devices[saved.activeTarget] ? saved.activeTarget : '';
  const previous = session[SESSION_KEY] || {};
  for (const key of Object.keys(devices)) {
    const state = previous.targets?.[key] || (key === 'bajaj/whatsapp' ? previous : {});
    let snapshot = state.pendingSnapshot;
    if (snapshot && !snapshot.account && key === 'bajaj/whatsapp') {
      snapshot = {...snapshot, account: 'bajaj', integration: 'whatsapp'};
    }
    const snapshotAccepted = isSnapshot(snapshot, devices[key]);
    transient[key] = {
      pendingSnapshot: snapshotAccepted ? snapshot : null,
      lastError: snapshot && !snapshotAccepted ? ERROR_MESSAGES.capture_invalid : (typeof state.lastError === 'string' ? state.lastError : ''),
      lastErrorCode: snapshot && !snapshotAccepted ? 'capture_invalid' :
        (Object.hasOwn(ERROR_MESSAGES, state.lastErrorCode) ? state.lastErrorCode : (state.lastError ? 'request_failed' : '')),
      syncing: false,
    };
  }
  pairingError = typeof previous.pairingError === 'string' ? previous.pairingError : '';
  await persistLocal();
  await persistSession();
})();

// One queue owns all device/session writes and network completions; target tokens never share a slot.
function mutate(work) {
  const operation = operations.then(() => ready).then(work);
  operations = operation.catch(() => {});
  return operation;
}
async function api(path, {method = 'POST', body, device} = {}) {
  let response;
  try {
    response = await fetch(`${AGENT_ORIGIN}/api/karix-extension/${path}`, {
      method, credentials: 'omit', redirect: 'error', cache: 'no-store',
      headers: {
        ...(body === undefined ? {} : {'Content-Type': 'application/json'}),
        ...(device ? {Authorization: `Bearer ${device.deviceToken}`} : {}),
      },
      ...(body === undefined ? {} : {body: JSON.stringify(body)}),
      signal: AbortSignal.timeout(20000),
    });
  } catch { throw failure('network_error'); }
  // Inspect only allowlisted codes; never forward provider bodies or Pydantic inputs.
  if (!response.ok) {
    if (response.status === 401) throw failure('device_expired');
    if (response.status === 403) throw failure('scope_denied');
    if (response.status === 409) throw failure('identity_conflict');
    if (response.status === 422) {
      let detail;
      try { detail = (await response.json())?.detail; } catch { /* Untrusted or unreadable detail. */ }
      if (detail && !Array.isArray(detail) && detail.integration === device?.integration &&
          ['provider_validation_failed', 'incomplete_session'].includes(detail.code)) throw failure(detail.code);
      throw failure('schema_rejected');
    }
    throw failure('request_failed');
  }
  try { return await response.json(); } catch {
    throw new Error('The agent returned an unreadable response. Retry.');
  }
}
function nextStep(device) {
  if (device.integration === 'moengage') {
    return 'Select this target in the extension popup and open its configured MoEngage workspace. If already logged in, reload that dashboard; repeat login only if the session has expired. The backend verifies workspace authorization before saving.';
  }
  const destination = device.integration === 'rcs'
    ? (device.identity.bot_ids.length === 1 ? `RCS template list and select Sender ID ${device.identity.bot_ids[0]}` : 'RCS template list and select one of this target’s configured bot IDs')
    : `WhatsApp template list for WABA ${device.identity.waba_id}`;
  return `Open Karix’s ${destination}. If already logged in, reload that list; repeat login and mobile OTP only if the session has expired.`;
}
async function syncPending(key) {
  const device = devices[key];
  if (!device) return {ok: false, message: 'Choose a connected target first.'};
  const state = stateFor(key);
  if (!paired(device)) {
    state.lastErrorCode = 'device_expired';
    state.lastError = ERROR_MESSAGES.device_expired;
    await persistSession();
    return {ok: false, message: state.lastError, error_code: state.lastErrorCode};
  }
  if (!state.pendingSnapshot) return {ok: false, message: `No complete matching request is available. ${nextStep(device)}`};
  state.syncing = true;
  try {
    await persistSession();
    // A historical success is not proof of current authorization or a still-saved session.
    const result = await api('sync', {body: state.pendingSnapshot, device});
    if (result?.ok !== true || result.account !== device.account || result.integration !== device.integration ||
        !Number.isFinite(result.last_synced_at) || result.last_synced_at <= 0) {
      throw new Error('The agent did not confirm validation for this exact account and integration. Retry.');
    }
    device.lastSyncedAt = result.last_synced_at;
    await persistLocal();
    state.pendingSnapshot = null;
    state.lastError = '';
    state.lastErrorCode = '';
    return {ok: true, account: device.account, integration: device.integration,
      message: 'Credentials for this target were validated by the backend and synced.'};
  } catch (error) {
    state.lastErrorCode = Object.hasOwn(ERROR_MESSAGES, error.code) ? error.code : 'request_failed';
    state.lastError = ERROR_MESSAGES[state.lastErrorCode];
    if (state.lastErrorCode === 'device_expired') {
      device.deviceExpiresAt = 0;
      await persistLocal();
    }
    return {ok: false, message: state.lastError, error_code: state.lastErrorCode};
  } finally {
    state.syncing = false;
    await persistSession();
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
  return sender.id === chrome.runtime.id && sender.url === popupUrl && (!sender.tab || sender.tab.url === popupUrl);
}
function status() {
  return {agent_origin: AGENT_ORIGIN, error: pairingError, active_target: activeTarget, targets: Object.entries(devices).map(([key, device]) => {
    const state = stateFor(key);
    return {
      account: device.account, integration: device.integration, paired: paired(device), can_disconnect: true,
      last_synced_at: device.lastSyncedAt || null, pending: Boolean(state.pendingSnapshot), syncing: state.syncing,
      error: state.lastError || (!paired(device) ? 'Pairing expired. Reconnect this target from Settings.' : ''),
      next_step: nextStep(device),
      capture_active: paired(device) && key === activeTarget,
    };
  })};
}
function scopedStatus(scope) {
  const key = scopeKey(scope);
  const device = devices[key];
  const state = device ? stateFor(key) : null;
  return {ok: true, message: 'Current browser capture status.', account: scope.account, integration: scope.integration,
    paired: paired(device), pending: Boolean(state?.pendingSnapshot), syncing: Boolean(state?.syncing),
    last_synced_at: device?.lastSyncedAt || null, capture_active: paired(device) && key === activeTarget,
    error: state?.lastErrorCode || (device && !paired(device) ? 'device_expired' : null)};
}
async function pair(message) {
  try {
    const result = await api('redeem', {body: {code: message.code, agent_origin: AGENT_ORIGIN}});
    const identity = normalizedIdentity(result?.integration, result?.identity);
    if (!validScope(result) || result.account !== message.account || result.integration !== message.integration ||
        !identity || !credential(result.device_token) || !Number.isFinite(result.expires_at) ||
        result.expires_at <= Date.now() / 1000) {
      throw new Error('The agent did not return the requested scope and a complete configured identity. Reconnect this target from Settings.');
    }
    const key = scopeKey(result);
    devices[key] = {
      account: result.account, integration: result.integration, identity, deviceToken: result.device_token,
      deviceExpiresAt: result.expires_at, lastSyncedAt: null,
    };
    // Never reuse a snapshot captured with an older pairing's configured identity.
    transient[key] = {pendingSnapshot: null, lastError: '', lastErrorCode: '', syncing: false};
    activeTarget = key;
    pairingError = '';
    await persistLocal();
    await persistSession();
    return {ok: true, account: result.account, integration: result.integration,
      message: `Target paired. ${nextStep(devices[key])} Nothing is synced until the backend validates it.`};
  } catch (error) {
    pairingError = error.message;
    await persistSession();
    return {ok: false, message: pairingError, error_code: Object.hasOwn(ERROR_MESSAGES, error.code) ? error.code : 'request_failed'};
  }
}
async function disconnect(key) {
  const device = devices[key];
  if (!device) return {ok: false, message: 'Choose a connected target first.'};
  try {
    const query = new URLSearchParams({account: device.account, integration: device.integration});
    const result = await api(`device?${query}`, {method: 'DELETE', device}).catch(error => {
      // An expired/revoked capability cannot be used again; it is safe to forget locally.
      if (error.code === 'device_expired') return {ok: true};
      throw error;
    });
    if (result?.ok !== true || (result.account !== undefined && result.account !== device.account) ||
        (result.integration !== undefined && result.integration !== device.integration)) {
      throw new Error('The agent did not confirm revocation for this target. Retry.');
    }
    delete devices[key];
    delete transient[key];
    if (activeTarget === key) activeTarget = '';
    await persistLocal();
    await persistSession();
    return {ok: true, message: 'Target disconnected and its device token revoked.'};
  } catch (error) {
    stateFor(key).lastError = `${error.message} Local pairing was preserved so you can retry disconnection. You can also revoke it in agent Settings.`;
    await persistSession();
    return {ok: false, message: stateFor(key).lastError};
  }
}
async function selectTarget(key) {
  if (!devices[key]) return {ok: false, message: 'Choose a connected target first.'};
  if (!paired(devices[key])) return {ok: false, message: ERROR_MESSAGES.device_expired, error_code: 'device_expired'};
  activeTarget = key;
  await persistLocal();
  return {ok: true, account: devices[key].account, integration: devices[key].integration,
    message: 'Active capture target selected. Reload this exact target’s inventory in its already logged-in portal.'};
}
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message !== 'object') return false;
  let work;
  if (settingsSender(sender)) {
    if (message.type === 'KARIX_EXTENSION_PING') {
      sendResponse({ok: true, message: 'Auth Sync is installed.'});
      return false;
    }
    if (message.type === 'KARIX_EXTENSION_SCOPED_STATUS' && validScope(message)) {
      work = ready.then(() => scopedStatus(message));
    } else if (message.type === 'KARIX_EXTENSION_SELECT' && validScope(message)) {
      work = mutate(() => selectTarget(scopeKey(message)));
    } else if (message.type === 'KARIX_EXTENSION_RETRY' && validScope(message)) {
      work = mutate(async () => ({...await syncPending(scopeKey(message)),
        account: message.account, integration: message.integration}));
    } else {
      if (message.type !== 'KARIX_EXTENSION_PAIR' || !validScope(message) ||
          typeof message.code !== 'string' || !message.code || message.code.length > 1024) return false;
      work = mutate(() => pair(message));
    }
  } else if (popupSender(sender)) {
    if (message.type === 'KARIX_EXTENSION_STATUS') work = ready.then(status);
    else if (validScope(message) && message.type === 'KARIX_EXTENSION_SELECT') work = mutate(() => selectTarget(scopeKey(message)));
    else if (validScope(message) && message.type === 'KARIX_EXTENSION_RETRY') work = mutate(() => syncPending(scopeKey(message)));
    else if (validScope(message) && message.type === 'KARIX_EXTENSION_DISCONNECT') work = mutate(() => disconnect(scopeKey(message)));
    else return false;
  } else return false;
  work.then(sendResponse).catch(() => sendResponse({ok: false,
    message: 'Extension storage is unavailable. Reload the extension and retry.'}));
  return true;
});

function requestBody(body) {
  if (!body || body.error) return null;
  if (body.formData) {
    if (Object.values(body.formData).some(values => values.length !== 1)) return null;
    return Object.fromEntries(Object.entries(body.formData).map(([key, values]) => [key, values[0]]));
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
    for (const part of body.raw) { bytes.set(new Uint8Array(part.bytes), offset); offset += part.bytes.byteLength; }
    const result = JSON.parse(new TextDecoder('utf-8', {fatal: true}).decode(bytes));
    return result && typeof result === 'object' && !Array.isArray(result) ? result : null;
  } catch { return null; }
}
function knownRequest(details) {
  try {
    const url = new URL(details.url);
    if (url.origin === 'https://rcsgui.karix.solutions') {
      if (details.method === 'POST' && url.pathname === '/v1.0/templates/getAllTemplates') return {integration: 'whatsapp', url};
      if ((details.method === 'GET' && url.pathname === '/api/v1.0/rcstemplate/getTemplatesWithFilter') ||
          (details.method === 'POST' && url.pathname === '/api/rcstemplate/fetchTemplates')) return {integration: 'rcs', url};
    }
    if (dashboardOrigin(url.origin) && details.method === 'GET' &&
        ['/dash/auth/listApps', '/template_metadata', '/appsettings'].includes(url.pathname)) return {integration: 'moengage', url};
  } catch { /* Not a supported portal request. */ }
  return null;
}
function observedValues(url, body, names) {
  const values = [];
  for (const name of names) {
    for (const value of url.searchParams.getAll(name)) values.push(valueString(value));
    if (body && Object.hasOwn(body, name)) values.push(valueString(body[name]));
  }
  return values;
}
function exactObserved(values, expected, required = true) {
  return (!required && !values.length) || (values.length > 0 && values.every(value => value === expected));
}
function matchingIdentity(request, body, device) {
  const {url} = request;
  const expected = device.identity;
  if (device.integration === 'whatsapp') {
    const esmes = observedValues(url, body, ['esmeaddr']);
    // The WhatsApp list uses 0 for an unfiltered ESME. The exact WABA must still match,
    // and the backend independently validates this snapshot against the configured ESME.
    return body && exactObserved(observedValues(url, body, ['wabaId', 'waba_id']), expected.waba_id) &&
      (exactObserved(esmes, expected.esmeaddr) || exactObserved(esmes, '0'))
      ? {waba_id: expected.waba_id, esmeaddr: expected.esmeaddr} : null;
  }
  if (device.integration === 'rcs') {
    const bots = observedValues(url, body, ['senderId', 'botId', 'bot_id', 'sender_id']);
    const esmes = observedValues(url, body, ['esmeaddr']);
    if (!bots.length || !bots.every(bot => bot === bots[0] && expected.bot_ids.includes(bot)) ||
        (esmes.length && (!expected.esmeaddr || !exactObserved(esmes, expected.esmeaddr)))) return null;
    return {bot_id: bots[0], ...(esmes.length ? {esmeaddr: expected.esmeaddr} : {})};
  }
  if (url.origin !== expected.base_url) return null;
  const workspaces = observedValues(url, body, ['workspace_id', 'workspaceId', 'app_id', 'appId', 'account_id', 'accountId']);
  if (workspaces.length ? !exactObserved(workspaces, expected.workspace_id) :
      (scopeKey(device) !== activeTarget || !['/dash/auth/listApps', '/appsettings'].includes(url.pathname))) return null;
  return {base_url: expected.base_url, workspace_id: expected.workspace_id};
}
function tokenIdentityMatches(token, device, snapshot) {
  const parts = token.split('.');
  if (parts.length !== 3) return true; // Opaque tokens are verified by the backend's read-only provider request.
  let payload;
  let decoded;
  try {
    const encoded = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    decoded = atob(encoded.padEnd(Math.ceil(encoded.length / 4) * 4, '='));
  } catch { return false; }
  try {
    payload = JSON.parse(decoded);
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) return false;
  } catch {
    // Karix signs a text payload (<random><ESME><ACCOUNT>), not JSON JWT claims.
    if (device.integration === 'moengage') return false;
    const match = /(\d{14,15})([A-Z_]+)$/.exec(decoded);
    if (!match) return false;
    const esme = match[1].length === 15 ? match[1].slice(1) : match[1];
    return esme === device.identity.esmeaddr;
  }
  const expected = device.identity;
  const compare = (names, value) => names.every(name => !Object.hasOwn(payload, name) || valueString(payload[name]) === value);
  if (device.integration === 'whatsapp') {
    return compare(['wabaId', 'waba_id'], expected.waba_id) && compare(['esmeaddr'], expected.esmeaddr);
  }
  if (device.integration === 'rcs') {
    return compare(['senderId', 'sender_id', 'botId', 'bot_id'], snapshot.bot_id) &&
      (!Object.hasOwn(payload, 'esmeaddr') || Boolean(expected.esmeaddr && valueString(payload.esmeaddr) === expected.esmeaddr));
  }
  return compare(['workspace_id', 'workspaceId', 'app_id', 'appId'], expected.workspace_id);
}
chrome.webRequest.onBeforeRequest.addListener(details => {
  const request = knownRequest(details);
  if (!request) return;
  const now = Date.now();
  for (const [id, record] of requests) if (now - record.startedAt > 120000) requests.delete(id);
  // Read only known inventory bodies, never login, OTP, create/update, or arbitrary portal traffic.
  const body = requestBody(details.requestBody);
  const record = {startedAt: now, url: details.url, candidates: []};
  requests.set(details.requestId, record);
  // MV3 can wake on this request before storage has restored the paired targets.
  // Retain this request's body/headers now; resolve its scope only after restoration.
  record.ready = ready.then(() => {
    const candidates = [];
    for (const [key, device] of Object.entries(devices)) {
      if (!paired(device) || device.integration !== request.integration) continue;
      const identity = matchingIdentity(request, body, device);
      if (identity) candidates.push({key, device, identity, snapshot: null, error: '',
        activeOnly: device.integration === 'moengage' &&
          !observedValues(request.url, body, ['workspace_id', 'workspaceId', 'app_id', 'appId', 'account_id', 'accountId']).length});
    }
    if (candidates.length > 1) {
      // Shared bot/workspace identifiers are ambiguous; never fan credentials out.
      const selected = candidates.find(candidate => candidate.key === activeTarget);
      if (!selected) return;
      selected.activeOnly = true;
      record.candidates = [selected];
    } else record.candidates = candidates;
  });
  void record.ready.catch(() => {});
}, REQUEST_FILTER, ['requestBody']);
chrome.webRequest.onBeforeSendHeaders.addListener(details => {
  const record = requests.get(details.requestId);
  if (!record || record.url !== details.url) return;
  const headers = new Map();
  let ambiguous = false;
  for (const header of details.requestHeaders || []) {
    const name = header.name.toLowerCase();
    if (!['authorization', 'session', 'user', 'refreshtoken', 'cookie'].includes(name)) continue;
    if (headers.has(name)) ambiguous = true;
    headers.set(name, header.value);
  }
  record.ready = record.ready.then(() => {
    const bearer = /^Bearer[\t ]+(\S+)$/i.exec((headers.get('authorization') || '').trim());
    for (const candidate of record.candidates) {
      const device = candidate.device;
      const snapshot = {account: device.account, integration: device.integration,
        ...candidate.identity, bearer_token: bearer?.[1] || ''};
      if (device.integration === 'moengage') {
        snapshot.refresh_token = (headers.get('refreshtoken') || '').trim();
        snapshot.cookie = (headers.get('cookie') || '').trim();
      } else {
        for (const name of ['session', 'user']) {
          if (headers.has(name)) snapshot[name] = (headers.get(name) || '').trim();
        }
      }
      if (ambiguous || !isSnapshot(snapshot, device) || !tokenIdentityMatches(snapshot.bearer_token, device, snapshot)) {
        candidate.error = ERROR_MESSAGES.capture_invalid;
        candidate.snapshot = null;
      } else candidate.snapshot = snapshot;
    }
  });
  void record.ready.catch(() => {});
}, REQUEST_FILTER, ['requestHeaders', 'extraHeaders']);
function finishRequest(details, failure = '') {
  const record = requests.get(details.requestId);
  requests.delete(details.requestId);
  if (!record) return;
  void mutate(async () => {
    await record.ready;
    for (const candidate of record.candidates) {
      // A disconnect/re-pair makes every in-flight snapshot for that old device unusable.
      if (devices[candidate.key] !== candidate.device || (candidate.activeOnly && candidate.key !== activeTarget)) continue;
      const state = stateFor(candidate.key);
      const error = failure || candidate.error || (!candidate.snapshot ? 'No complete matching credentials were observed. Reload this target inventory.' : '');
      if (error) {
        state.lastErrorCode = failure ? 'inventory_failed' : 'capture_invalid';
        state.lastError = error;
        await persistSession();
        continue;
      }
      state.pendingSnapshot = candidate.snapshot;
      state.lastError = '';
      state.lastErrorCode = '';
      await persistSession();
      await syncPending(candidate.key);
    }
  }).catch(() => {});
}
chrome.webRequest.onCompleted.addListener(details => {
  finishRequest(details, details.statusCode < 200 || details.statusCode >= 300 || details.fromCache
    ? ERROR_MESSAGES.inventory_failed : '');
}, REQUEST_FILTER);
chrome.webRequest.onErrorOccurred.addListener(details => {
  finishRequest(details, ERROR_MESSAGES.inventory_failed);
}, REQUEST_FILTER);
chrome.webRequest.onBeforeRedirect.addListener(details => {
  finishRequest(details, ERROR_MESSAGES.inventory_failed);
}, REQUEST_FILTER);
