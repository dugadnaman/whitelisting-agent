const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function apiFor(fetch) {
  const exportsObject = {};
  vm.runInNewContext(ts.transpileModule(readFileSync(join(__dirname, 'api.ts'), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, {
    exports: exportsObject, module: { exports: exportsObject }, fetch,
    process: { env: {} }, Headers, FormData, URLSearchParams,
    AbortController, AbortSignal, setTimeout, clearTimeout,
  });
  return exportsObject;
}

const json = (body) => ({ ok: true, status: 200, json: async () => body });

test('WhatsApp draft validation does not require image inspection flags', async () => {
  const draft = { template_name: 'whatsapp_sample', header_type: 'IMAGE' };
  const api = apiFor(async () => json({ whatsapp_templates: [draft], rcs_templates: [] }));
  const result = await api.previewJiraDrafts({ account: 'tata', whatsapp_templates: [draft], rcs_templates: [] });
  assert.equal(result.whatsapp_templates[0], draft);
});

test('RCS draft validation still requires image inspection flags and preserves blocking', async () => {
  const draft = { template_name: 'rcs_sample' };
  const request = { account: 'tata', whatsapp_templates: [], rcs_templates: [draft] };
  const unchecked = apiFor(async () => json({ whatsapp_templates: [], rcs_templates: [draft] }));
  await assert.rejects(unchecked.previewJiraDrafts(request), /Creative validation is unavailable/);

  const blockedDraft = { ...draft, aspect_ratio_blocked: true };
  const checked = apiFor(async () => json({ whatsapp_templates: [], rcs_templates: [blockedDraft] }));
  const result = await checked.previewJiraDrafts(request);
  assert.equal(result.rcs_templates[0].aspect_ratio_blocked, true);
});

test('WhatsApp draft validation still rejects missing drafts', async () => {
  const api = apiFor(async () => json({ whatsapp_templates: [null], rcs_templates: [] }));
  await assert.rejects(api.previewJiraDrafts({
    account: 'tata', whatsapp_templates: [{ template_name: 'sample' }], rcs_templates: [],
  }), /Creative validation is unavailable/);
});

test('submission no longer sends an aspect-ratio option and retains the other options', async () => {
  for (const channel of ['whatsapp', 'rcs']) {
    let submittedUrl;
    const api = apiFor(async (url) => {
      submittedUrl = new URL(url);
      return json({ account: 'tata', channel, submitted: 1, results: [] });
    });
    await api.submitFile(new Blob(['sample']), 'tata', channel, 'Operator', false, true,
      { account: 'tata', channel }, channel === 'rcs' ? 'bot-123' : undefined);
    assert.equal(submittedUrl.searchParams.has('fix_aspect_ratio'), false);
    assert.equal(submittedUrl.searchParams.get('fix_grammar'), 'false');
    assert.equal(submittedUrl.searchParams.get('skip_duplicates'), 'true');
    assert.equal(submittedUrl.searchParams.get('expected_account'), 'tata');
    assert.equal(submittedUrl.searchParams.get('expected_channel'), channel);
    assert.equal(submittedUrl.searchParams.get('expected_rcs_bot_id'), channel === 'rcs' ? 'bot-123' : null);
  }
});
