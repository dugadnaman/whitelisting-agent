const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function compile(name) {
  return ts.transpileModule(readFileSync(join(__dirname, name), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
}
const compiledApi = compile('api.ts');
const compiledClient = compile('moengage-click-count.ts');

function sharedApiFor(fetchImpl) {
  const shared = { exports: {} };
  vm.runInNewContext(compiledApi, {
    exports: shared.exports, module: shared, Headers, AbortController, AbortSignal, DOMException, Promise, setTimeout, clearTimeout,
    process: { env: {} }, window: {}, fetch: fetchImpl,
    localStorage: { getItem: () => null },
  });
  return shared.exports;
}

function clientFor(fetchImpl) {
  const shared = sharedApiFor(fetchImpl);
  const client = { exports: {} };
  vm.runInNewContext(compiledClient, {
    exports: client.exports, module: client,
    require: (name) => { assert.equal(name, './api'); return shared; },
    Intl, Date, URLSearchParams,
  });
  return client.exports;
}

const workspace = { id: 'a'.repeat(24), name: 'Tata test', timezone: 'Asia/Kolkata' };
const base = { id: 'b'.repeat(24), name: 'Imported test base' };
const metadata = { ...base, created_at: '2026-01-01T23:00:00+00:00', start_date: '2026-01-02', timezone: workspace.timezone };
const request = { workspace_id: workspace.id, base_id: base.id, end_date: '2026-01-03' };
const query = {
  query_id: 'synthetic.signed.ticket', workspace_id: workspace.id, workspace_name: workspace.name,
  base_id: base.id, base_name: base.name, start_date: metadata.start_date, end_date: request.end_date,
  timezone: workspace.timezone, status: 'queued',
};
const json = (body) => ({ ok: true, status: 200, json: async () => body });
const status = (code) => ({ ok: false, status: code, text: async () => JSON.stringify({ detail: 'Synthetic failure' }) });

function isProtocolError(api) {
  return (error) => error instanceof api.ClickCountApiError && error.status === 0;
}

test('workspace and base lists reject unusable shapes rather than breaking rendering', async () => {
  for (const value of [null, {}, { workspaces: null }, { workspaces: [null] },
    { workspaces: [{ ...workspace, name: 4 }] }, { workspaces: [{ ...workspace, timezone: 'Not/AZone' }] },
    { workspaces: [workspace, workspace] }]) {
    const api = clientFor(async () => json(value));
    await assert.rejects(api.fetchClickCountWorkspaces(), isProtocolError(api));
  }
  for (const value of [null, {}, { bases: null }, { bases: [null] },
    { bases: [{ ...base, name: {} }] }, { bases: [base, base] }]) {
    const api = clientFor(async () => json(value));
    await assert.rejects(api.fetchClickCountBases(workspace.id), isProtocolError(api));
  }
  const api = clientFor(async () => json({ workspaces: [] }));
  assert.equal((await api.fetchClickCountWorkspaces()).workspaces.length, 0);
  const empty = clientFor(async () => json({ bases: [] }));
  assert.equal((await empty.fetchClickCountBases(workspace.id)).bases.length, 0);
});

test('metadata is bound to the selected base and validates dates and timezone', async () => {
  for (const value of [null, { ...metadata, id: 'c'.repeat(24) },
    { ...metadata, start_date: '2026-02-30' }, { ...metadata, created_at: 'not-a-timestamp' },
    { ...metadata, start_date: '2026-01-01' }, { ...metadata, start_date: '2026-01-03' },
    { ...metadata, timezone: 'America/New_York' }, { ...metadata, timezone: 'Invalid/Timezone' }]) {
    const api = clientFor(async () => json(value));
    await assert.rejects(api.fetchClickCountBase(workspace.id, base.id), isProtocolError(api));
  }
  const api = clientFor(async () => json(metadata));
  assert.equal((await api.fetchClickCountBase(workspace.id, base.id)).start_date, '2026-01-02');
});

test('query acceptance is queued and bound to the submitted identity and inclusive end date', async () => {
  for (const value of [null, { ...query, workspace_id: 'c'.repeat(24) },
    { ...query, base_id: 'c'.repeat(24) }, { ...query, end_date: '2026-01-04' },
    { ...query, start_date: '2026-02-30' }, { ...query, status: 'success' },
    { ...query, timezone: 'Invalid/Timezone' }, { ...query, query_id: '' }]) {
    const api = clientFor(async () => json(value));
    await assert.rejects(api.startClickCountQuery(request), isProtocolError(api));
  }
  const api = clientFor(async () => json(query));
  assert.equal((await api.startClickCountQuery(request)).query_id, query.query_id);
});

test('status validates ticket, state and exact nonnegative counts including zero', async () => {
  const success = { query_id: query.query_id, status: 'success', user_count: 0, reachable_users: 0 };
  for (const value of [null, { ...success, query_id: 'another.ticket' }, { ...success, status: 'unknown' }, { ...success, status: ['success'] },
    { ...success, user_count: null }, { ...success, user_count: '0' }, { ...success, user_count: -1 },
    { ...success, user_count: 1.5 }, { ...success, user_count: Number.MAX_SAFE_INTEGER + 1 },
    { ...success, reachable_users: 1 }, { ...success, reachable_users: {} },
    { ...success, status: 'failed', user_count: null, reachable_users: null, error: {} }]) {
    const api = clientFor(async () => json(value));
    await assert.rejects(api.fetchClickCountQuery(workspace.id, query.query_id), isProtocolError(api));
  }
  for (const value of [success, { ...success, user_count: 17, reachable_users: 3 },
    { query_id: query.query_id, status: 'running', user_count: null, reachable_users: null },
    { query_id: query.query_id, status: 'failed', user_count: null, reachable_users: null, error: 'Provider failed' }]) {
    const api = clientFor(async () => json(value));
    assert.equal((await api.fetchClickCountQuery(workspace.id, query.query_id)).status, value.status);
  }
});

test('POST is attempted once on HTTP, transport and malformed-success failures', async () => {
  for (const fetchImpl of [async () => status(503), async () => { throw new Error('Network failed'); },
    async () => ({ ok: true, status: 200, json: async () => { throw new SyntaxError('Bad JSON'); } })]) {
    const calls = [];
    const api = clientFor(async (url, init) => { calls.push({ url, init }); return fetchImpl(); });
    await assert.rejects(api.startClickCountQuery(request));
    assert.equal(calls.length, 1);
  }
});

test('HTTP status remains available to distinguish terminal polling errors from transient errors', async () => {
  for (const code of [400, 401, 403, 404, 408, 429, 500, 502, 503, 504]) {
    let calls = 0;
    const api = clientFor(async () => { calls += 1; return status(code); });
    await assert.rejects(api.fetchClickCountQuery(workspace.id, query.query_id),
      (error) => error instanceof api.ClickCountApiError && error.status === code);
    assert.equal(calls, 1, 'each polling cycle sends exactly one request');
    const error = new api.ClickCountApiError('Synthetic failure', code);
    assert.equal(api.isTerminalClickCountError(error), code >= 400 && code < 500 && code !== 408 && code !== 429);
  }
  const api = clientFor(async () => json(null));
  assert.equal(api.isTerminalClickCountError(new api.ClickCountApiError('Invalid data', 0)), true);
  assert.equal(api.isTerminalClickCountError(new Error('Network failed')), false);
});

test('aborted response-body reads remain transient rather than becoming malformed-schema errors', async () => {
  const aborted = new DOMException('Request aborted', 'AbortError');
  const api = clientFor(async () => ({ ok: true, status: 200, json: async () => { throw aborted; } }));
  await assert.rejects(api.fetchClickCountQuery(workspace.id, query.query_id),
    (error) => error === aborted && !api.isTerminalClickCountError(error));
});

test('cancelling a metadata lookup rejects promptly without attempting further requests', async () => {
  const controller = new AbortController();
  let attempts = 0;
  const { promise: started, resolve: resolveStarted } = Promise.withResolvers();
  const api = clientFor(async (_url, { signal }) => {
    attempts += 1;
    if (signal.aborted) throw signal.reason;
    resolveStarted();
    const { promise, reject } = Promise.withResolvers();
    signal.addEventListener('abort', () => reject(signal.reason), { once: true });
    return promise;
  });
  const pending = api.fetchClickCountBase(workspace.id, base.id, controller.signal);
  await started;
  controller.abort();
  await assert.rejects(pending, (error) => error.name === 'AbortError');
  assert.equal(attempts, 1);
});

test('cancelling during retry backoff stops a metadata lookup without another attempt', async () => {
  const controller = new AbortController();
  const { promise: started, resolve } = Promise.withResolvers();
  let attempts = 0;
  const api = clientFor(async () => { attempts += 1; resolve(); return status(503); });
  const pending = api.fetchClickCountBase(workspace.id, base.id, controller.signal);
  await started;
  controller.abort();
  await assert.rejects(pending, (error) => error.name === 'AbortError');
  assert.equal(attempts, 1);
});

test('an existing caller signal does not disable the request deadline', { timeout: 5000 }, async () => {
  const controller = new AbortController();
  let attempts = 0;
  let transportSignal;
  const api = sharedApiFor(async (_url, { signal }) => {
    attempts += 1;
    transportSignal = signal;
    const { promise, reject } = Promise.withResolvers();
    signal.addEventListener('abort', () => reject(signal.reason), { once: true });
    return promise;
  });
  await assert.rejects(api.fetchWithRetry('/synthetic-deadline', { signal: controller.signal }, 0, 0, 20));
  assert.equal(attempts, 1);
  assert.equal(transportSignal.aborted, true);
  assert.equal(controller.signal.aborted, false);
});

test('calendar validity and today follow the workspace rather than the browser timezone', () => {
  const api = clientFor(async () => { throw new Error('Unexpected request'); });
  const beforeMidnight = new Date('2026-01-01T18:29:59Z');
  const midnight = new Date('2026-01-01T18:30:00Z');
  assert.equal(api.todayInTimezone('Asia/Kolkata', beforeMidnight), '2026-01-01');
  assert.equal(api.todayInTimezone('Asia/Kolkata', midnight), '2026-01-02');
  assert.equal(api.todayInTimezone('America/Los_Angeles', midnight), '2026-01-01');
  assert.equal(api.isValidClickCountRange('2026-01-02', '2026-01-02', 'Asia/Kolkata', beforeMidnight), false);
  assert.equal(api.isValidClickCountRange('2026-01-02', '2026-01-02', 'Asia/Kolkata', midnight), true);
  assert.equal(api.isValidClickCountRange('2024-02-28', '2024-02-29', 'UTC', midnight), true);
  for (const end of ['', '2026-1-02', '2026-02-30', '2026-13-01', '0000-01-01', '2026-01-01', '2026-01-03']) {
    assert.equal(api.isValidClickCountRange('2026-01-02', end, 'Asia/Kolkata', midnight), false, end);
  }
});
