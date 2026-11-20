// Build the public seed with the same definitions as the workboard.
// Browser-generated timestamps and private localStorage edits have no public source.
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.resolve(__dirname, '../site/third-design');
const records = fs.readFileSync(path.join(root, 'review-records.js'), 'utf8');
const evidence = JSON.parse(fs.readFileSync(path.join(root, 'baseline-evidence.json')));
const board = vm.runInNewContext(records + '\n({...fresh(), recordedHierarchy})', {
  evidence, now: () => undefined, structuredClone
});
console.log(JSON.stringify(board));
