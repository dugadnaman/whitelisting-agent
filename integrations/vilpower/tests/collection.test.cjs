const assert = require('node:assert/strict');
const {test} = require('node:test');
const {readFileSync} = require('node:fs');
const {join} = require('node:path');
const vm = require('node:vm');
const root = join(__dirname, '..');
const collection = JSON.parse(readFileSync(join(root, 'Vi DLT APIs.postman_collection.json')));
const environment = JSON.parse(readFileSync(join(root, 'Vi DLT Testing.postman_environment.json')));
const requests = collection.item.flatMap(folder => folder.item);
function execute(listen, name, values, code = 200, body = {}) {
  const state = new Map(Object.entries(values));
  const failures = [];
  let skipped = false;
  const pm = {
    info: {requestName: name}, variables: {get: key => state.get(key)},
    environment: {set: (key, value) => state.set(key, value), unset: key => state.delete(key)},
    execution: {skipRequest: () => {skipped = true;}},
    response: {code, json: () => {if (body instanceof Error) throw body; return body;}},
    test: (name, run) => {try {run();} catch {failures.push(name);}},
    expect: value => ({to: {eql: expected => assert.equal(value, expected)}}),
  };
  let error;
  try {vm.runInNewContext(collection.event.find(event => event.listen === listen).script.exec.join('\n'), {pm});}
  catch (caught) {error = caught;}
  return {state, failures, skipped, error};
}

test('token generation hands actual response tokens to dependent requests', () => {
  const result = execute('test', 'Generate Token', {}, 200, {access:'new-access',refresh:'new-refresh'});
  assert.deepEqual(result.failures, []);
  assert.equal(result.state.get('access_token'), 'new-access');
  assert.equal(result.state.get('refresh_token'), 'new-refresh');
  for (const item of requests.filter(item => item.request.auth)) {
    assert.equal(item.request.auth.bearer[0].value, '{{access_token}}');
    assert.equal(JSON.parse(item.request.body.raw).eid, '{{entity_id}}');
  }
});
test('refresh preserves the old refresh token unless rotation is returned', () => {
  for (const rotated of [undefined, 'rotated-refresh']) {
    const result = execute('test', 'Refresh Access Token', {refresh_token:'old-refresh'}, 200,
      {access:'new-access', ...(rotated ? {refresh:rotated} : {})});
    assert.deepEqual(result.failures, []);
    assert.equal(result.state.get('refresh_token'), rotated || 'old-refresh');
    assert.equal(result.state.get('access_token'), 'new-access');
  }
});
test('failed malformed and redacted authentication clears stale tokens', () => {
  for (const [code, body] of [[401,{access:'bad',refresh:'bad'}], [200,{}], [200,{access:'[REDACTED]',refresh:'r'}],
    [200,{access:'a',refresh:''}], [200,null], [200,new Error('invalid JSON')]]) {
    const result = execute('test','Generate Token',{access_token:'stale',refresh_token:'stale'},code,body);
    assert.ok(result.failures.length);
    assert.equal(result.state.has('access_token'), false);
    assert.equal(result.state.has('refresh_token'), false);
  }
});
test('HTTP 200 is not registration or linkage success when business status fails', () => {
  for (const status of [412,404,424]) {
    const result = execute('test','Register Content Template',{},200,{status});
    assert.ok(result.failures.length);
  }
});
test('empty credentials and default mutation settings stop requests before networking', () => {
  const defaults = Object.fromEntries(environment.values.map(v => [v.key,v.value]));
  for (const name of ['Generate Token','Refresh Access Token','Register Header','Register Content Template','Link Header','De-link Header']) {
    const result = execute('prerequest',name,defaults);
    assert.equal(result.skipped,true,name);
    assert.ok(result.error,name);
  }
  const configured = {...defaults, username:'local-user',password:'local-password'};
  assert.equal(execute('prerequest','Generate Token',configured).error,undefined);
  const reviewed = {...defaults,allow_mutations:'true',access_token:'local-token',entity_id:'local-entity',header_id:'local-header',template_id:'local-template'};
  assert.equal(execute('prerequest','Link Header',reviewed).error,undefined);
});
test('callback simulations cannot mutate receivers through default runner settings', () => {
  const result = execute('prerequest','Callback – Content Template Approved',{callback_url:'https://receiver.example.test',allow_mutations:'false'});
  assert.equal(result.skipped,true);
  assert.ok(result.error);
});
