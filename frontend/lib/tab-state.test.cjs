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
          useState: (init) => {
            let value = typeof init === 'function' ? init() : init;
            return [value, (action) => { value = typeof action === 'function' ? action(value) : action; }];
          },
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

test('destination changes detect hidden restored drafts without warning for navigation preferences', () => {
  const { mod, sessionStorage } = createTestHarness();
  mod.setTabState('workspace_open_tabs', ['/', '/submit']);
  mod.setTabState('submit_auto_skip_duplicates', true);
  mod.setTabState('submit_identify_filter', 'MISSING');
  mod.setTabState('submit_state', { step: 'idle' });
  assert.equal(mod.hasWorkspaceDrafts(), false);

  // Restored storage represents a draft on another, currently unmounted workspace tab.
  sessionStorage.set('karix_tab:briefs_wa_templates', JSON.stringify([{ template_name: 'review_me', body: 'Keep my draft' }]));
  assert.equal(mod.hasWorkspaceDrafts(), true);
  mod.clearTabState();
  assert.equal(mod.hasWorkspaceDrafts(), false);
});

test('late callbacks cannot restore or erase work after a destination switch', () => {
  const { mod } = createTestHarness();
  const [, oldResponse, oldReset] = mod.useTabState('submit_state', { step: 'idle' });
  mod.clearTabState();
  const [, newResponse] = mod.useTabState('submit_state', { step: 'idle' });
  const reviewed = { step: 'previewed', account: 'wealth', channel: 'rcs' };
  newResponse(reviewed);
  oldResponse({ step: 'previewed', account: 'tcl_promo', channel: 'whatsapp' });
  assert.deepEqual(mod.getTabState('submit_state', null), reviewed);
  oldReset();
  assert.deepEqual(mod.getTabState('submit_state', null), reviewed);
});
