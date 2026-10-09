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

function sharedApiFor(fetchImpl, runtime = {}) {
  const shared = { exports: {} };
  vm.runInNewContext(compiledApi, {
    exports: shared.exports, module: shared, Headers, AbortController, AbortSignal, DOMException, Promise, setTimeout, clearTimeout,
    process: { env: {} }, window: {}, fetch: fetchImpl,
    localStorage: { getItem: () => null }, ...runtime,
  });
  return shared.exports;
}

function clientFor(fetchImpl, runtime) {
  const shared = sharedApiFor(fetchImpl, runtime);
  const client = { exports: {} };
  vm.runInNewContext(compiledClient, {
    exports: client.exports, module: client,
    require: (name) => { assert.equal(name, './api'); return shared; },
    Intl, Date, URLSearchParams, ...runtime,
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

function controlledTimers() {
  let nextId = 0;
  const timers = new Map();
  const delays = [];
  return {
    timers, delays,
    setTimeout(callback, ms) {
      const id = ++nextId;
      timers.set(id, { callback, ms });
      delays.push(ms);
      return id;
    },
    clearTimeout(id) { timers.delete(id); },
  };
}

async function flushMicrotasks() {
  for (let i = 0; i < 10; i += 1) await Promise.resolve();
}

function fireTimer(clock, ms) {
  const timer = [...clock.timers].find(([, value]) => value.ms === ms);
  assert.ok(timer, `expected a scheduled ${ms}ms timer`);
  clock.timers.delete(timer[0]);
  timer[1].callback();
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

test('inline dates are trusted only as a complete pair matching the selected workspace timezone', async () => {
  const api = clientFor(async () => json({ bases: [metadata, { ...base, id: 'd'.repeat(24) }] }));
  const values = (await api.fetchClickCountBases(workspace.id, undefined, workspace.timezone)).bases;
  assert.equal(values[0].created_at, metadata.created_at);
  assert.equal(values[0].start_date, metadata.start_date);
  assert.equal(values[1].created_at, undefined);
  assert.equal(values[1].start_date, undefined);

  for (const timezone of [undefined, null, '', {}, 'Invalid/Timezone']) {
    const values = (await api.fetchClickCountBases(workspace.id, undefined, timezone)).bases;
    assert.equal(values[0].created_at, undefined, `untrusted timezone ${String(timezone)}`);
    assert.equal(values[0].start_date, undefined);
    assert.equal(values[0].id, base.id);
    assert.equal(values[0].name, base.name);
  }
});

test('malformed inline metadata cannot reach rendering or enable a range before real creation', async () => {
  const valid = { ...metadata, id: 'c'.repeat(24) };
  for (const partial of [
    { created_at: metadata.created_at },
    { start_date: metadata.start_date },
    { created_at: metadata.created_at, start_date: {} },
    { created_at: metadata.created_at, start_date: ['2026-01-02'] },
    { created_at: metadata.created_at, start_date: 20260102 },
    { created_at: {}, start_date: metadata.start_date },
    { created_at: null, start_date: metadata.start_date },
    { created_at: true, start_date: metadata.start_date },
    { created_at: metadata.created_at, start_date: '2026-01-01' },
    { created_at: metadata.created_at, start_date: '2026-01-03' },
    { created_at: metadata.created_at, start_date: '2026-02-30' },
    { created_at: '2026-02-30T23:00:00Z', start_date: '2026-03-03' },
    { created_at: '2026-01-01T24:00:00Z', start_date: '2026-01-02' },
    { created_at: 'not-a-timestamp', start_date: metadata.start_date },
  ]) {
    const api = clientFor(async () => json({ bases: [{ ...base, ...partial }, valid] }));
    const values = (await api.fetchClickCountBases(workspace.id, undefined, workspace.timezone)).bases;
    assert.equal(values.length, 2, 'invalid optional metadata must not discard usable bases');
    assert.equal(values[0].id, base.id);
    assert.equal(values[0].name, base.name);
    assert.equal(values[0].created_at, undefined, JSON.stringify(partial));
    assert.equal(values[0].start_date, undefined, JSON.stringify(partial));
    assert.equal(values[1].start_date, metadata.start_date, 'valid sibling remains preloaded');
    const preloaded = values.filter((item) => item.start_date && item.created_at);
    assert.equal(preloaded.some((item) => item.id === base.id), false, 'page must load real metadata before enabling a query');
  }
});

test('metadata rejects timestamp normalization that silently changes its calendar date', async () => {
  for (const created_at of ['2026-01-01T24:00:00Z', '2026-01-01T24:00:00+00:00']) {
    const api = clientFor(async () => json({ ...metadata, created_at }));
    await assert.rejects(api.fetchClickCountBase(workspace.id, base.id), isProtocolError(api));
  }
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
    { ...success, user_count: NaN }, { ...success, user_count: Infinity }, { ...success, user_count: -Infinity },
    { ...success, user_count: false }, { ...success, reachable_users: null },
    { ...success, reachable_users: NaN }, { ...success, reachable_users: Infinity }, { ...success, reachable_users: -1 },
    { ...success, reachable_users: 0.5 }, { ...success, reachable_users: '0' },
    { ...success, status: 'queued' }, { ...success, status: 'running' }, { ...success, status: 'failed' },
    { ...success, reachable_users: 1 }, { ...success, reachable_users: {} },
    { ...success, status: 'failed', user_count: null, reachable_users: null, error: {} }]) {
    const api = clientFor(async () => json(value));
    await assert.rejects(api.fetchClickCountQuery(workspace.id, query.query_id), isProtocolError(api));
  }
  for (const value of [success, { ...success, user_count: 17, reachable_users: 3 },
    { ...success, user_count: Number.MAX_SAFE_INTEGER, reachable_users: Number.MAX_SAFE_INTEGER },
    { query_id: query.query_id, status: 'queued', user_count: null, reachable_users: null },
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

test('an aborted HTTP error-body read preserves cancellation rather than a terminal HTTP status', async () => {
  const controller = new AbortController();
  const reason = new DOMException('Caller cancelled body', 'AbortError');
  const api = clientFor(async () => ({
    ok: false, status: 404,
    text: async () => { controller.abort(reason); throw reason; },
  }));
  await assert.rejects(api.fetchClickCountQuery(workspace.id, query.query_id, controller.signal),
    (error) => error === reason && !api.isTerminalClickCountError(error));
});

test('cancellation wins over successful response bodies received after the caller stops waiting', async () => {
  for (const operation of ['bases', 'metadata', 'start', 'poll']) {
    const controller = new AbortController();
    const reason = new DOMException('Caller cancelled body', 'AbortError');
    const bodies = { bases: { bases: [base] }, metadata, start: query,
      poll: { query_id: query.query_id, status: 'running', user_count: null, reachable_users: null } };
    const api = clientFor(async () => ({ ok: true, status: 200, json: async () => {
      controller.abort(reason);
      return bodies[operation];
    } }));
    const calls = {
      bases: () => api.fetchClickCountBases(workspace.id, controller.signal, workspace.timezone),
      metadata: () => api.fetchClickCountBase(workspace.id, base.id, controller.signal),
      start: () => api.startClickCountQuery(request, controller.signal),
      poll: () => api.fetchClickCountQuery(workspace.id, query.query_id, controller.signal),
    };
    await assert.rejects(calls[operation](), (error) => error === reason, operation);
  }
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
  const clock = controlledTimers();
  let attempts = 0;
  const api = clientFor(async () => { attempts += 1; return status(503); }, clock);
  const pending = api.fetchClickCountBase(workspace.id, base.id, controller.signal);
  await flushMicrotasks();
  assert.equal([...clock.timers.values()].some((timer) => timer.ms === 800), true, 'abort occurs during actual backoff');
  controller.abort();
  await assert.rejects(pending, (error) => error.name === 'AbortError');
  assert.equal(attempts, 1);
  assert.equal(clock.timers.size, 0);
});

test('an existing caller signal does not disable the request deadline', { timeout: 5000 }, async () => {
  const controller = new AbortController();
  let attempts = 0;
  const clock = controlledTimers();
  let transportSignal;
  const api = sharedApiFor(async (_url, { signal }) => {
    attempts += 1;
    transportSignal = signal;
    const { promise, reject } = Promise.withResolvers();
    signal.addEventListener('abort', () => reject(signal.reason), { once: true });
    return promise;
  }, clock);
  const pending = api.fetchWithRetry('/synthetic-deadline', { signal: controller.signal }, 0, 0, 60000);
  const rejection = assert.rejects(pending, /Request timed out after 60 seconds/);
  fireTimer(clock, 60000);
  await rejection;
  assert.equal(attempts, 1);
  assert.equal(transportSignal.aborted, true);
  assert.equal(controller.signal.aborted, false);
  assert.equal(clock.timers.size, 0);
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

test('range validation safely rejects malformed timezones and invalid clocks', () => {
  const api = clientFor(async () => { throw new Error('Unexpected request'); });
  for (const timezone of ['Invalid/Timezone', undefined, null, {}, '', ' UTC ']) {
    assert.equal(api.isValidClickCountRange('2026-01-01', '2026-01-02', timezone, new Date('2026-01-03T00:00:00Z')), false);
  }
  assert.equal(api.isValidClickCountRange('2026-01-01', '2026-01-02', 'UTC', new Date(NaN)), false);
});

test('valid inline metadata retains normalized UTC fractions, local midnights and DST dates', async () => {
  for (const [timezone, created_at, start_date] of [
    ['UTC', '2026-01-01T23:00:00Z', '2026-01-01'],
    ['UTC', '2024-02-29T12:34:56.1+00:00', '2024-02-29'],
    ['Asia/Kolkata', '2026-01-01T18:29:59.999999+00:00', '2026-01-01'],
    ['Asia/Kolkata', '2026-01-01T18:30:00+00:00', '2026-01-02'],
    ['America/New_York', '2026-01-02T04:59:59.999999+00:00', '2026-01-01'],
    ['America/New_York', '2026-01-02T05:00:00.000000+00:00', '2026-01-02'],
    ['America/Los_Angeles', '2026-03-08T07:59:59Z', '2026-03-07'],
    ['America/Los_Angeles', '2026-03-08T08:00:00Z', '2026-03-08'],
    ['America/Los_Angeles', '2026-11-01T08:30:00Z', '2026-11-01'],
    ['America/Los_Angeles', '2026-11-01T09:30:00Z', '2026-11-01'],
    ['Pacific/Kiritimati', '2026-01-01T10:00:00Z', '2026-01-02'],
    ['UTC', '0001-01-01T00:00:00+00:00', '0001-01-01'],
    ['UTC', '0099-12-31T23:59:59.999999+00:00', '0099-12-31'],
    ['UTC', '9999-12-31T23:59:59.999999+00:00', '9999-12-31'],
  ]) {
    const value = { ...base, timezone, created_at, start_date };
    const api = clientFor(async (url) => json(url.includes('/bases?') ? { bases: [value] } : value));
    const inline = (await api.fetchClickCountBases(workspace.id, undefined, timezone)).bases[0];
    assert.equal(inline.created_at, created_at);
    assert.equal(inline.start_date, start_date, `${timezone} ${created_at}`);
    const fetched = await api.fetchClickCountBase(workspace.id, base.id);
    assert.equal(fetched.start_date, inline.start_date, 'inline and fallback must agree');
  }
});

test('inline and fallback metadata share strict normalized timestamp rejection', async () => {
  for (const created_at of [
    '2026-01-01T23:00Z', '2026-01-01T23:00:00', '2026-01-01 23:00:00Z',
    '2026-01-01T23:00:00+05:30', '2026-01-01T23:00:00-00:00',
    '2026-01-01T23:60:00Z', '2026-01-01T23:59:60Z', '2026-01-01T24:00:00Z',
    '2026-01-01T23:00:00.1234567+00:00', '2026-01-01T23:00:00.000Zextra',
    '0000-12-31T23:00:00Z', '2026-02-30T23:00:00Z',
  ]) {
    const value = { ...metadata, created_at };
    const api = clientFor(async (url) => json(url.includes('/bases?') ? { bases: [value] } : value));
    const inline = (await api.fetchClickCountBases(workspace.id, undefined, workspace.timezone)).bases[0];
    assert.equal(inline.start_date, undefined, created_at);
    assert.equal(inline.created_at, undefined, created_at);
    await assert.rejects(api.fetchClickCountBase(workspace.id, base.id), isProtocolError(api));
  }
  for (const value of [
    { ...base, timezone: 'America/New_York', created_at: '0001-01-01T00:00:00Z', start_date: '0001-12-31' },
    { ...base, timezone: 'Pacific/Kiritimati', created_at: '9999-12-31T23:59:59Z', start_date: '9999-12-31' },
  ]) {
    const api = clientFor(async (url) => json(url.includes('/bases?') ? { bases: [value] } : value));
    assert.equal((await api.fetchClickCountBases(workspace.id, undefined, value.timezone)).bases[0].start_date, undefined);
    await assert.rejects(api.fetchClickCountBase(workspace.id, base.id), isProtocolError(api));
  }
});

test('large inline lists reuse timezone formatting instead of allocating a formatter per base', async () => {
  let constructions = 0;
  const CountingFormatter = function (locale, options) {
    constructions += 1;
    return new Intl.DateTimeFormat(locale, options);
  };
  const bases = Array.from({ length: 1000 }, (_, index) => ({ ...metadata, id: index.toString(16).padStart(24, '0') }));
  const api = clientFor(async () => json({ bases }), { Intl: { DateTimeFormat: CountingFormatter } });
  const loaded = await api.fetchClickCountBases(workspace.id, undefined, workspace.timezone);
  assert.equal(loaded.bases.length, 1000, 'no selected-base limit');
  assert.equal(loaded.bases.every((value) => value.start_date === metadata.start_date), true);
  assert.equal(constructions <= 2, true, `expected O(1) formatters, received ${constructions}`);
});

test('GET retries transient HTTP and transport failures with bounded cancellable backoff', async () => {
  for (const failure of [
    ...[500, 502, 503, 504].map((code) => async () => status(code)),
    async () => { throw new Error('Synthetic transport failure'); },
  ]) {
    for (const operation of ['workspaces', 'bases', 'metadata']) {
      const clock = controlledTimers();
      const calls = [];
      const success = { workspaces: { workspaces: [workspace] }, bases: { bases: [metadata] }, metadata }[operation];
      const api = clientFor(async (url, init) => {
        calls.push({ url, init });
        return calls.length < 3 ? failure() : json(success);
      }, clock);
      const pending = {
        workspaces: () => api.fetchClickCountWorkspaces(),
        bases: () => api.fetchClickCountBases(workspace.id, undefined, workspace.timezone),
        metadata: () => api.fetchClickCountBase(workspace.id, base.id),
      }[operation]();
      await flushMicrotasks();
      assert.equal(calls.length, 1);
      fireTimer(clock, 800);
      await flushMicrotasks();
      assert.equal(calls.length, 2);
      fireTimer(clock, 1200);
      await pending;
      assert.equal(calls.length, 3);
      assert.deepEqual(clock.delays, [60000, 800, 60000, 1200, 60000]);
      assert.equal(clock.timers.size, 0);
      assert.equal(calls.every(({ init }) => init.cache === 'no-store'), true);
    }
  }
});

test('GET retry exhaustion does not fabricate data or lose the final HTTP status', async () => {
  for (const code of [503, null]) {
    const clock = controlledTimers();
    let attempts = 0;
    const api = clientFor(async () => {
      attempts += 1;
      if (code === null) throw new Error('Synthetic transport failure');
      return status(code);
    }, clock);
    const pending = api.fetchClickCountBase(workspace.id, base.id);
    const rejection = assert.rejects(pending, code === null ? /Synthetic transport failure/
      : (error) => error instanceof api.ClickCountApiError && error.status === 503);
    await flushMicrotasks();
    fireTimer(clock, 800);
    await flushMicrotasks();
    fireTimer(clock, 1200);
    await rejection;
    assert.equal(attempts, 3);
    assert.equal(clock.timers.size, 0);
  }
});

test('GET does not retry terminal HTTP statuses, throttling or malformed successful data', async () => {
  for (const result of [
    ...[400, 401, 403, 404, 408, 429].map((code) => status(code)),
    json(null), { ok: true, status: 200, json: async () => { throw new SyntaxError('Synthetic malformed JSON'); } },
  ]) {
    const clock = controlledTimers();
    let attempts = 0;
    const api = clientFor(async () => { attempts += 1; return result; }, clock);
    await assert.rejects(api.fetchClickCountBase(workspace.id, base.id));
    assert.equal(attempts, 1);
    assert.equal(clock.timers.size, 0);
  }
});

test('already aborted callers never start GET, POST or polling requests', async () => {
  const controller = new AbortController();
  const reason = new DOMException('Precancelled', 'AbortError');
  controller.abort(reason);
  let attempts = 0;
  const api = clientFor(async () => { attempts += 1; throw new Error('Must not fetch'); });
  for (const invoke of [
    () => api.fetchClickCountWorkspaces(controller.signal),
    () => api.fetchClickCountBases(workspace.id, controller.signal, workspace.timezone),
    () => api.fetchClickCountBase(workspace.id, base.id, controller.signal),
    () => api.startClickCountQuery(request, controller.signal),
    () => api.fetchClickCountQuery(workspace.id, query.query_id, controller.signal),
  ]) await assert.rejects(invoke(), (error) => error === reason);
  assert.equal(attempts, 0);
});

test('POST and polling deadlines abort the attempt without an automatic retry', async () => {
  for (const operation of ['start', 'poll']) {
    const clock = controlledTimers();
    const controller = new AbortController();
    let attempts = 0;
    let transportSignal;
    const api = clientFor(async (_url, { signal }) => {
      attempts += 1;
      transportSignal = signal;
      return new Promise((_, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true }));
    }, clock);
    const pending = operation === 'start' ? api.startClickCountQuery(request, controller.signal)
      : api.fetchClickCountQuery(workspace.id, query.query_id, controller.signal);
    const rejection = assert.rejects(pending, (error) => /Request timed out after 60 seconds/.test(error.message)
      && !api.isTerminalClickCountError(error));
    fireTimer(clock, 60000);
    await rejection;
    assert.equal(attempts, 1);
    assert.equal(transportSignal.aborted, true);
    assert.equal(controller.signal.aborted, false);
    assert.equal(clock.timers.size, 0);
  }
});

test('polling tickets and workspace identifiers are encoded without changing endpoint scope', async () => {
  const ticket = 'signed/ticket?scope=#fragment+';
  const urls = [];
  const api = clientFor(async (url, init) => {
    urls.push({ url, init });
    return json({ query_id: ticket, status: 'running', user_count: null, reachable_users: null });
  });
  await api.fetchClickCountQuery(workspace.id, ticket);
  assert.equal(urls[0].url, `/api/moengage/click-count/queries/${encodeURIComponent(ticket)}?workspace_id=${workspace.id}`);
  assert.equal(urls[0].init.cache, 'no-store');
});

test('caller deadlines cover success and error body reads after response headers arrive', async () => {
  for (const ok of [true, false]) {
    const clock = controlledTimers();
    const controller = new AbortController();
    const reason = new DOMException('Caller deadline expired', 'TimeoutError');
    const { promise: reading, resolve: markReading } = Promise.withResolvers();
    let attempts = 0;
    const api = clientFor(async (_url, { signal }) => {
      attempts += 1;
      const readBody = () => {
        markReading();
        return new Promise((_, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true }));
      };
      return { ok, status: ok ? 200 : 404, json: readBody, text: readBody };
    }, clock);
    const pending = api.fetchClickCountQuery(workspace.id, query.query_id, controller.signal);
    const rejection = assert.rejects(pending, (error) => error === reason && !api.isTerminalClickCountError(error));
    await reading;
    assert.equal(clock.timers.size, 0, 'shared transport deadline ends at headers; the caller still covers body consumption');
    controller.abort(reason);
    await rejection;
    assert.equal(attempts, 1);
  }
});

test('GET attempt deadlines remain retryable and each retry receives a fresh transport signal', async () => {
  const clock = controlledTimers();
  const controller = new AbortController();
  const signals = [];
  const api = clientFor(async (_url, { signal }) => {
    signals.push(signal);
    if (signals.length === 3) return json(metadata);
    return new Promise((_, reject) => signal.addEventListener('abort', () => reject(signal.reason), { once: true }));
  }, clock);
  const pending = api.fetchClickCountBase(workspace.id, base.id, controller.signal);
  fireTimer(clock, 60000);
  await flushMicrotasks();
  assert.equal(signals[0].aborted, true);
  fireTimer(clock, 800);
  await flushMicrotasks();
  fireTimer(clock, 60000);
  await flushMicrotasks();
  assert.equal(signals[1].aborted, true);
  fireTimer(clock, 1200);
  const loaded = await pending;
  assert.equal(loaded.start_date, metadata.start_date);
  assert.equal(signals.length, 3);
  assert.notEqual(signals[0], signals[1]);
  assert.notEqual(signals[1], signals[2]);
  assert.equal(signals[2].aborted, false);
  assert.equal(controller.signal.aborted, false);
  assert.equal(clock.timers.size, 0);
});

test('range validation honors Gregorian leap years and the four-digit service calendar', () => {
  const api = clientFor(async () => { throw new Error('Unexpected request'); });
  const now = new Date('9999-12-31T12:00:00Z');
  for (const value of ['0001-01-01', '0099-12-31', '1900-02-28', '2000-02-29', '2024-02-29', '9999-12-31']) {
    assert.equal(api.isValidClickCountRange(value, value, 'UTC', now), true, value);
  }
  for (const value of ['0000-01-01', '1900-02-29', '2001-02-29', '2100-02-29', '2026-04-31', '10000-01-01']) {
    assert.equal(api.isValidClickCountRange(value, value, 'UTC', now), false, value);
  }
  assert.equal(api.isValidClickCountRange('0001-01-01', '0001-12-31', 'America/New_York', new Date('0001-01-01T00:00:00Z')), false);
});
