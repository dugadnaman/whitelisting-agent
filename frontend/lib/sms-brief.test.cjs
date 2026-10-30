const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function load(name, globals = {}) {
  const exports = {};
  vm.runInNewContext(ts.transpileModule(readFileSync(join(__dirname, name), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, { exports, module: { exports }, ...globals });
  return exports;
}
const { prepareSmsBriefDrafts, applySmsBriefDecisions, smsBriefReady, editSmsBriefDraft } = load('sms-brief.ts');
const row = (id, patch = {}) => ({
  id, sheet: 'Historical SMS', cell: `B${id}`, text: 'Exact offer <Name>.', campaign: 'Historical campaign',
  segment: 'Returning', language: 'English', scope: 'Historical', source_kind: 'SMS',
  suggested_template_name: 'offer_template', suggested_template_type: '', warnings: [], variables: ['<Name>'], ...patch,
});
const plain = (value) => JSON.parse(JSON.stringify(value));

test('source selection starts empty and only selected exact compatible copies collapse with all provenance', () => {
  const candidates = [row('1', { warnings: ['Check language'] }), row('2', { sheet: 'Other SMS', warnings: ['Check scope'] }), row('3', { text: 'Exact offer <Name>. ' })];
  assert.throws(() => prepareSmsBriefDrafts(candidates, [], 'synthetic.xlsx'), /Select between/);
  const drafts = prepareSmsBriefDrafts(candidates, ['1', '2', '3'], 'synthetic.xlsx');
  assert.equal(drafts.length, 2);
  assert.equal(drafts[0].text, candidates[0].text);
  assert.equal(drafts[1].text, candidates[2].text);
  assert.equal(drafts[0].brief.sources.length, 2);
  assert.equal(drafts[0].source_ref, 'Historical SMS!B1; Other SMS!B2');
  assert.ok(drafts[0].brief.warnings.includes('Check language'));
  assert.ok(drafts[0].brief.warnings.includes('Check scope'));
  assert.equal(drafts[0].template_type, '');
  assert.equal(drafts[0].brief.acknowledged, false);
  assert.equal(prepareSmsBriefDrafts(candidates, ['2'], 'synthetic.xlsx')[0].brief.sources.length, 1);
});

test('conflicting hints remain separate and unknown hints do not arbitrarily pick a conflicting source', () => {
  const candidates = [row('1', { suggested_template_type: '1' }), row('2', { suggested_template_type: '3' }), row('3')];
  assert.equal(prepareSmsBriefDrafts(candidates, ['1', '2', '3'], 'synthetic.xls').length, 3);
  assert.equal(prepareSmsBriefDrafts(candidates, ['1', '3'], 'synthetic.xls').length, 1);
});

test('selected source cap precedes duplicate grouping and provider names stay unique and safe', () => {
  const candidates = Array.from({ length: 501 }, (_, i) => row(String(i), { suggested_template_name: 'Long campaign with spaces '.repeat(6) }));
  assert.throws(() => prepareSmsBriefDrafts(candidates, candidates.map((candidate) => candidate.id), 'synthetic.xlsx'), /500/);
  const drafts = prepareSmsBriefDrafts([row('1'), row('2', { text: 'Other body.' })], ['1', '2'], 'synthetic.xlsx');
  assert.notEqual(drafts[0].template_name, drafts[1].template_name);
  const capped = prepareSmsBriefDrafts(candidates, candidates.slice(0, 500).map((candidate) => candidate.id), 'synthetic.xlsx');
  assert.match(capped[0].template_name, /^[A-Za-z0-9_-]{1,60}$/);
});

test('per-occurrence literal and typed decisions preserve every static Unicode byte and repeated variable independently', () => {
  const original_text = '🙂\t<Offer>\r\nHi {#var#}, amount {#var#}! [link]  ';
  const brief = {
    original_text, sources: [{}], warnings: [], acknowledged: false,
    variables: [
      { token: '<Offer>', kind: 'literal', sample: '' },
      { token: '{#var#}', kind: 'alp', sample: 'Reader' },
      { token: '{#var#}', kind: 'num', sample: '123' },
      { token: '[link]', kind: 'urg', sample: 'https://example.test/offer' },
    ],
  };
  assert.deepEqual(plain(applySmsBriefDecisions(brief)), {
    text: '🙂\t<Offer>\r\nHi {#alp#}, amount {#num#}! {#urg#}  ',
    sample_message: '🙂\t<Offer>\r\nHi Reader, amount 123! https://example.test/offer  ',
  });
  assert.equal(brief.original_text, original_text);
  assert.equal(applySmsBriefDecisions({ ...brief, variables: [{ token: '<Missing>', kind: 'literal', sample: '' }] }), null);
});

test('readiness requires decisions, explicit nonempty samples and acknowledgement; every edit resets acknowledgement', () => {
  let draft = prepareSmsBriefDrafts([row('1')], ['1'], 'synthetic.xlsx')[0];
  assert.equal(smsBriefReady(draft), false);
  draft.brief.acknowledged = true;
  assert.equal(smsBriefReady(draft), false);
  draft.brief.variables[0].kind = 'alp';
  draft.brief.variables[0].sample = '   ';
  assert.equal(smsBriefReady(draft), false);
  draft.brief.variables[0].sample = 'Reader';
  assert.equal(smsBriefReady(draft), true);
  for (const patch of [{ text: 'Edited copy' }, { template_name: 'changed' }, { header_id: 'new' }, { brief: { ...draft.brief, sources: [{ ...draft.brief.sources[0], language: 'Reviewed' }] } }]) {
    assert.equal(smsBriefReady(editSmsBriefDraft(draft, patch)), false);
    assert.equal(draft.brief.acknowledged, true);
  }
  assert.equal(smsBriefReady({ text: 'Legacy draft' }), true);
});

test('literal decisions require no invented sample and a manually reviewed body is not overwritten', () => {
  const draft = prepareSmsBriefDrafts([row('1')], ['1'], 'synthetic.xlsx')[0];
  draft.brief.variables[0].kind = 'literal';
  draft.brief.acknowledged = true;
  draft.text = 'Manually reviewed exact copy.';
  assert.equal(smsBriefReady(draft), true);
  assert.equal(draft.text, 'Manually reviewed exact copy.');
  assert.deepEqual(plain(applySmsBriefDecisions(draft.brief)), { text: 'Exact offer <Name>.', sample_message: 'Exact offer <Name>.' });
});

test('native workbook transport sends multipart to Tata without session lookup and never retries failures', async () => {
  const calls = [];
  const api = load('api.ts', {
    fetch: async (url, init) => { calls.push({ url, init }); throw new Error('Offline parse unavailable'); },
    process: { env: {} }, Headers, FormData, URLSearchParams, AbortController, AbortSignal, setTimeout, clearTimeout,
  });
  await assert.rejects(api.parseSmsDltBrief(new Blob(['synthetic workbook']), 'bajaj'), /only for Tata/);
  assert.equal(calls.length, 0);
  await assert.rejects(api.parseSmsDltBrief(new Blob(['synthetic workbook']), 'tata'), /Offline parse unavailable/);
  assert.equal(calls.length, 1);
  assert.equal(new URL(calls[0].url).pathname, '/api/sms-dlt/brief');
  assert.equal(new URL(calls[0].url).searchParams.get('account'), 'tata');
  assert.equal(calls[0].init.method, 'POST');
  assert.ok(calls[0].init.body.get('file') instanceof Blob);
});
