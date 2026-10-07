const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const compiled = ts.transpileModule(readFileSync(join(__dirname, 'api.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function authApi(fetchImpl = async () => { throw new Error('Unexpected request'); }) {
  const storage = new Map();
  const exports = {};
  vm.runInNewContext(compiled, {
    exports, module: { exports }, Headers, AbortController, Promise, setTimeout, clearTimeout,
    process: { env: {} }, window: {}, fetch: fetchImpl,
    localStorage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: (key) => storage.delete(key),
    },
  });
  return { api: exports, storage };
}

const user = (tenant_id, role = 'operator') => ({ id: 'test-user', name: 'Test User', email: 'test@example.com', tenant_id, role });

test('saved Apparel and company accounts are clamped to verified tenant permissions', () => {
  const { api } = authApi();
  assert.equal(api.authorizedAccount(user('apparel'), 'bajaj'), 'apparel');
  assert.equal(api.authorizedAccount(user('bajaj'), 'apparel'), 'bajaj');
  assert.equal(api.authorizedAccount(user('tata'), 'bajaj'), 'tcl_promo');
  assert.equal(api.authorizedAccount(user('tata'), 'wealth'), 'wealth');
  assert.equal(api.canAccessAccount(user('apparel'), 'all'), false);
  assert.equal(api.canAccessAccount(user('all', 'operator'), 'apparel'), false);
  assert.equal(api.canAccessAccount(user('tata'), 'all'), false);
  assert.equal(api.canAccessAccount(null, 'apparel'), false);
  assert.equal(api.authorizedAccount(user('all', 'superadmin'), 'apparel'), 'apparel');
});

test('staff provisioning retains inviter JWT and sends explicit company scope', async () => {
  const requests = [];
  const colleague = user('apparel');
  const { api, storage } = authApi(async (url, init) => {
    requests.push({ url, init });
    return { ok: true, status: 200, json: async () => ({ user: colleague }) };
  });
  storage.set('karix_jwt_token', 'synthetic-admin-token');
  const result = await api.inviteColleague('colleague@example.com', 'Colleague-password-123', 'Colleague', 'operator', 'apparel');
  assert.equal(result, colleague);
  assert.equal(storage.get('karix_jwt_token'), 'synthetic-admin-token');
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, '/api/auth/team/invite');
  assert.equal(requests[0].init.headers.get('Authorization'), 'Bearer synthetic-admin-token');
  assert.equal(JSON.parse(requests[0].init.body).tenant_id, 'apparel');
  assert.equal(api.signupUser, undefined);
  assert.equal(api.registerUser, undefined);
});

test('login and invite mutations do not retry failures or change the existing token', async () => {
  let calls = 0;
  const { api, storage } = authApi(async () => {
    calls += 1;
    return { ok: false, status: 503, text: async () => JSON.stringify({ detail: 'Authentication unavailable' }) };
  });
  storage.set('karix_jwt_token', 'synthetic-admin-token');
  await assert.rejects(api.loginUser('admin@example.com', 'Incorrect-password'), /Authentication unavailable/);
  assert.equal(calls, 1);
  await assert.rejects(api.inviteColleague('colleague@example.com', 'Colleague-password-123', 'Colleague'), /Authentication unavailable/);
  assert.equal(calls, 2);
  assert.equal(storage.get('karix_jwt_token'), 'synthetic-admin-token');
});
