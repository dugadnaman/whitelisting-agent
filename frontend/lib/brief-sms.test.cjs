const assert = require('node:assert/strict');
const { test } = require('node:test');
const {
  BRIEF_SMS_PAGE_SIZE, BRIEF_SMS_REVIEW_LIMIT, matchingBriefSmsIndices,
  briefSmsPage, selectBriefSmsIndices, selectedBriefSmsDrafts,
} = require('./test-typescript.cjs')('brief-sms');

test('all 15,679 drafts remain reachable with original identity and exact copy across search and pages', () => {
  const drafts = Array.from({ length: 15679 }, (_, index) => ({
    template_name: `sms_${index}`, text: `  Message ${index}\r\n₹500 — {#var#}  `, variant: 'Original',
  }));
  // Equal names and bodies must still be independent source rows.
  drafts[15678] = { ...drafts[15677] };
  const original = JSON.stringify(drafts);
  const all = matchingBriefSmsIndices(drafts, '');
  const reached = [];
  for (let number = 1; number <= Math.ceil(drafts.length / BRIEF_SMS_PAGE_SIZE); number += 1) {
    const page = briefSmsPage(all, number);
    assert.ok(page.indices.length <= BRIEF_SMS_PAGE_SIZE);
    reached.push(...page.indices);
  }
  assert.deepEqual(reached, Array.from({ length: drafts.length }, (_, index) => index));
  const matches = matchingBriefSmsIndices(drafts, 'MESSAGE 15677');
  assert.deepEqual(Array.from(matches), [15677, 15678]);
  let selected = selectBriefSmsIndices(new Set([3]), briefSmsPage(matches, 1).indices, true);
  assert.deepEqual([...selected], [3, 15677, 15678]);
  const firstPage = briefSmsPage(all, 1);
  selected = selectBriefSmsIndices(selected, firstPage.indices, true);
  selected = selectBriefSmsIndices(selected, firstPage.indices, false);
  const review = selectedBriefSmsDrafts(drafts, selected);
  assert.equal(review.length, 2);
  assert.equal(review[0], drafts[15677]);
  assert.equal(review[1], drafts[15678]);
  assert.notEqual(review[0], review[1]);
  assert.equal(JSON.stringify(drafts), original);
  assert.equal(briefSmsPage(matches, 600).page, 1);
  assert.equal(briefSmsPage([], 2).indices.length, 0);
});

test('page and full-batch selection respect the 500-row review limit without partial additions', () => {
  const first475 = new Set(Array.from({ length: 475 }, (_, index) => index));
  const page = Array.from({ length: 25 }, (_, index) => index + 475);
  const full = selectBriefSmsIndices(first475, page, true);
  assert.equal(full.size, BRIEF_SMS_REVIEW_LIMIT);
  assert.equal(selectBriefSmsIndices(full, [500], true), full);
  assert.equal(selectBriefSmsIndices(first475, [...page, 500], true), first475);
  assert.equal(selectBriefSmsIndices(new Set(), Array.from({ length: 15679 }, (_, index) => index), true).size, 0);
  const deselected = selectBriefSmsIndices(full, page, false);
  assert.equal(deselected.size, 475);
  assert.equal(full.size, 500);
  const small = [0, 1, 2];
  assert.equal(selectBriefSmsIndices(new Set(), small, true).size, 3);
  const oldOversizedSelection = new Set(Array.from({ length: 501 }, (_, index) => index));
  assert.equal(selectBriefSmsIndices(oldOversizedSelection, [500], false).size, 500);
});
