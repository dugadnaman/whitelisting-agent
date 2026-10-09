const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const compiled = ts.transpileModule(readFileSync(join(__dirname, 'tab-state.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function createTestHarness() {
  const sessionStorageMap = new Map();
  const sessionStorage = {
    getItem: (key) => (sessionStorageMap.has(key) ? sessionStorageMap.get(key) : null),
    setItem: (key, val) => sessionStorageMap.set(key, String(val)),
    removeItem: (key) => sessionStorageMap.delete(key),
    get length() {
      return sessionStorageMap.size;
    },
    key: (index) => Array.from(sessionStorageMap.keys())[index] || null,
  };

  const sandbox = {
    module: { exports: {} },
    exports: {},
    require: (mod) => {
      if (mod === 'react') {
        return {
          useState: (init) => [typeof init === 'function' ? init() : init, () => {}],
          useCallback: (fn) => fn,
          useRef: (val) => ({ current: val }),
        };
      }
      return require(mod);
    },
    window: {},
    sessionStorage,
    Map,
    Set,
    Array,
    JSON,
  };

  vm.runInNewContext(compiled, sandbox);
  return { mod: sandbox.exports, sessionStorage: sessionStorageMap };
}

test('getTabState and setTabState persist primitives and objects', () => {
  const { mod, sessionStorage } = createTestHarness();
  assert.equal(mod.getTabState('search_query', ''), '');

  mod.setTabState('search_query', 'TCN-524');
  assert.equal(mod.getTabState('search_query', ''), 'TCN-524');
  assert.equal(sessionStorage.get('karix_tab:search_query'), JSON.stringify('TCN-524'));

  const draft = { template_name: 'test_wa_1', body: 'Hello world' };
  mod.setTabState('wa_draft', draft);
  assert.deepEqual(mod.getTabState('wa_draft', null), draft);
  assert.equal(sessionStorage.get('karix_tab:wa_draft'), JSON.stringify(draft));
});

test('setTabState and getTabState seamlessly serialize and restore Set instances', () => {
  const { mod, sessionStorage } = createTestHarness();
  const defaultSet = new Set();
  assert.equal(mod.getTabState('selected_indices', defaultSet).size, 0);

  const activeSet = new Set([0, 2, 5]);
  mod.setTabState('selected_indices', activeSet);
  assert.equal(sessionStorage.get('karix_tab:selected_indices'), JSON.stringify([0, 2, 5]));

  const restored = mod.getTabState('selected_indices', new Set());
  assert.ok(restored instanceof Set);
  assert.equal(restored.size, 3);
  assert.ok(restored.has(0));
  assert.ok(restored.has(2));
  assert.ok(restored.has(5));
});

test('clearTabState selectively clears by prefix or wipes completely', () => {
  const { mod, sessionStorage } = createTestHarness();
  mod.setTabState('briefs_key', 'TCN-100');
  mod.setTabState('briefs_search', 'query');
  mod.setTabState('submit_file', 'data.csv');

  mod.clearTabState('briefs_');
  assert.equal(mod.getTabState('briefs_key', null), null);
  assert.equal(mod.getTabState('briefs_search', null), null);
  assert.equal(mod.getTabState('submit_file', null), 'data.csv');

  mod.clearTabState();
  assert.equal(mod.getTabState('submit_file', null), null);
  assert.equal(sessionStorage.size, 0);
});
