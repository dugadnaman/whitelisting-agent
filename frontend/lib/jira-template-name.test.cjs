const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const exportsObject = {};
vm.runInNewContext(ts.transpileModule(readFileSync(join(__dirname, 'jira-template-name.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { exports: exportsObject, module: { exports: exportsObject } });
const { newRcsTemplateName } = exportsObject;

test('generated RCS names remain provider-safe and distinct after truncation and sequence growth', () => {
  for (const variant of ['rcs', 'rcs_manual']) {
    const names = new Set();
    const bases = ['TCN-557 Personal Loan Bulls Eye Campaign', 'TCN-557 Personal Loan Another Campaign'];
    for (let index = 0; index < 110; index += 1) {
      const name = newRcsTemplateName(bases[index % bases.length], names, variant);
      assert.match(name, /^[a-z0-9_]{1,25}$/);
      assert.equal(names.has(name), false);
      names.add(name);
    }
  }
});
