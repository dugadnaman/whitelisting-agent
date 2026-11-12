const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

function loadHelper(filename, dependencies = {}) {
  const exportsObject = {};
  vm.runInNewContext(ts.transpileModule(readFileSync(join(__dirname, filename), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText, {
    exports: exportsObject,
    module: { exports: exportsObject },
    require: (name) => {
      if (!(name in dependencies)) throw new Error(`Unexpected dependency: ${name}`);
      return dependencies[name];
    },
  });
  return exportsObject;
}
const { newRcsTemplateName, normalizeNewTemplateName } = loadHelper('jira-template-name.ts', {
  './campaign-name': loadHelper('campaign-name.ts'),
});

test('generated RCS names remain provider-safe and distinct after truncation and sequence growth', () => {
  for (const variant of ['rcs', 'rcs_manual']) {
    const names = new Set();
    const bases = ['TCN-557 Personal Loan Bulls Eye Campaign', 'TCN-557 Personal Loan Another Campaign'];
    for (let index = 0; index < 110; index += 1) {
      const name = newRcsTemplateName(bases[index % bases.length], names, variant);
      assert.match(name, /^[a-z0-9_]{1,25}$/);
      assert.ok(name.startsWith('att_'));
      assert.equal(names.has(name), false);
      names.add(name);
    }
  }
});

test('new whitelisting names canonicalize only the prefix', () => {
  assert.equal(normalizeNewTemplateName(' offer_wa '), 'att_offer_wa');
  assert.equal(normalizeNewTemplateName('ATT_offer_rcs'), 'att_offer_rcs');
  assert.equal(normalizeNewTemplateName('att_offer'), 'att_offer');
  assert.equal(normalizeNewTemplateName(''), '');
  const names = new Set(['att_offer_rcs_1']);
  assert.equal(newRcsTemplateName('att_offer', names), 'att_offer_rcs_2');
});
