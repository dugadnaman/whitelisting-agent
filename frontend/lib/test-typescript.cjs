const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const modules = new Map();
module.exports = function load(name) {
  if (modules.has(name)) return modules.get(name);
  const module = { exports: {} };
  const compiled = ts.transpileModule(readFileSync(resolve(__dirname, `${name}.ts`), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  vm.runInNewContext(compiled, { module, exports: module.exports, require: load });
  modules.set(name, module.exports);
  return module.exports;
};
