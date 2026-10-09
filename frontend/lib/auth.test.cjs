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

test('pending identities cannot select or access any company account', () => {
  const { api } = authApi();
  for (const tenant of ['unassigned', 'all']) {
    const pending = user(tenant);
    assert.equal(api.isPendingUser(pending), true);
    for (const account of ['unassigned', 'all', 'bajaj', 'tata', 'wealth', 'apparel']) {
      assert.equal(api.canAccessAccount(pending, account), false);
      assert.equal(api.authorizedAccount(pending, account), '');
    }
  }
  assert.equal(api.canAccessAccount(user('all', 'superadmin'), 'unassigned'), false);
  assert.equal(api.accountOrganization('wealth'), 'tata');
  assert.equal(api.accountOrganization('apparel'), 'apparel');
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

test('signup establishes an authenticated pending session without company access', async () => {
  const pending = { ...user('unassigned'), requested_tenant_id: 'bajaj' };
  const { api, storage } = authApi(async () => ({
    ok: true, status: 201, json: async () => ({ user: pending, token: 'synthetic-pending-token' }),
  }));
  const password = '  Spaces-are-preserved-123  ';
  const response = await api.signupUser('pending@example.com', password, 'Pending User', 'bajaj');
  assert.equal(api.isPendingUser(response.user), true);
  assert.equal(api.canAccessAccount(response.user, 'bajaj'), false);
  assert.equal(api.authorizedAccount(response.user, 'bajaj'), '');
  assert.equal(storage.get('karix_jwt_token'), 'synthetic-pending-token');
  assert.equal(response.user.requested_tenant_id, 'bajaj');
});

test('changing an access request keeps the applicant pending and retains its session', async () => {
  const pending = { ...user('unassigned'), requested_tenant_id: 'tata' };
  const { api, storage } = authApi(async () => ({
    ok: true, status: 200, json: async () => ({ user: pending }),
  }));
  storage.set('karix_jwt_token', 'synthetic-applicant-token');
  const profile = await api.requestCompanyAccess('tata');
  assert.equal(api.isPendingUser(profile), true);
  assert.equal(api.canAccessAccount(profile, 'tata'), false);
  assert.equal(profile.requested_tenant_id, 'tata');
  assert.equal(storage.get('karix_jwt_token'), 'synthetic-applicant-token');
});

test('approval returns an assigned operator while preserving the administrator session', async () => {
  const approved = { ...user('tata'), requested_tenant_id: null };
  const { api, storage } = authApi(async () => ({
    ok: true, status: 200, json: async () => ({ user: approved }),
  }));
  storage.set('karix_jwt_token', 'synthetic-admin-token');
  const profile = await api.approveAccessRequest('applicant-user');
  assert.equal(api.isPendingUser(profile), false);
  assert.equal(api.canAccessAccount(profile, 'wealth'), true);
  assert.equal(api.canAccessAccount(profile, 'bajaj'), false);
  assert.equal(profile.role, 'operator');
  assert.equal(profile.requested_tenant_id, null);
  assert.equal(storage.get('karix_jwt_token'), 'synthetic-admin-token');
});

test('profile refresh transitions approved applicants to their verified company without changing their session', async () => {
  let profile = { ...user('unassigned'), requested_tenant_id: 'apparel' };
  const { api, storage } = authApi(async () => ({
    ok: true, status: 200, json: async () => profile,
  }));
  storage.set('karix_jwt_token', 'synthetic-applicant-token');
  const pending = await api.fetchMe();
  assert.equal(api.authorizedAccount(pending, 'bajaj'), '');
  profile = { ...user('apparel'), requested_tenant_id: null };
  const assigned = await api.fetchMe();
  assert.equal(api.isPendingUser(assigned), false);
  assert.equal(api.authorizedAccount(assigned, 'bajaj'), 'apparel');
  assert.equal(api.canAccessAccount(assigned, 'bajaj'), false);
  assert.equal(storage.get('karix_jwt_token'), 'synthetic-applicant-token');
});

test('signup, request and approval mutations surface conflicts without retries or replacing sessions', async () => {
  let calls = 0;
  const { api, storage } = authApi(async () => {
    calls += 1;
    return { ok: false, status: 409, text: async () => JSON.stringify({ detail: 'Account or access request changed' }) };
  });
  storage.set('karix_jwt_token', 'synthetic-current-token');
  await assert.rejects(api.signupUser('duplicate@example.com', 'Duplicate-password-123', 'Duplicate', 'apparel'), /Account or access request changed/);
  await assert.rejects(api.requestCompanyAccess('bajaj'), /Account or access request changed/);
  await assert.rejects(api.approveAccessRequest('changed-user'), /Account or access request changed/);
  assert.equal(calls, 3);
  assert.equal(storage.get('karix_jwt_token'), 'synthetic-current-token');
});

test('disabled and expired profile sessions clear the token while other failures preserve it', async () => {
  for (const status of [401, 403, 400]) {
    const { api, storage } = authApi(async () => ({
      ok: false, status, text: async () => JSON.stringify({ detail: 'Session unavailable' }),
    }));
    storage.set('karix_jwt_token', 'synthetic-current-token');
    await assert.rejects(api.fetchMe(), /Session unavailable/);
    assert.equal(storage.get('karix_jwt_token'), status === 400 ? 'synthetic-current-token' : undefined);
  }
});
