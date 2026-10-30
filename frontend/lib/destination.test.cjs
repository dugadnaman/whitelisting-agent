const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const compiled = ts.transpileModule(readFileSync(join(__dirname, 'destination.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const destination = {};
vm.runInNewContext(compiled, { exports: destination, module: { exports: destination } });

test('Karix sub-accounts without channel metadata do not offer unintegrated SMS', () => {
  const channels = destination.destinationChannels('tcl_promo', [{ id: 'tcl_promo' }]);
  assert.equal(channels.includes('sms'), false);
  assert.equal(channels.includes('whatsapp'), true);
  assert.equal(channels.includes('rcs'), true);
});

test('Tata VILPOWER stays SMS-only even with stale Karix account metadata', () => {
  const channels = destination.destinationChannels('tata', [{ id: 'tata', channels: ['whatsapp', 'rcs'] }]);
  assert.deepEqual(Array.from(channels), ['sms']);
});
