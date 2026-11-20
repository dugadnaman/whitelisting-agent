const assert = require('node:assert/strict');
const {test} = require('node:test');
const {templateOutcome} = require('./test-typescript.cjs')('template-status');

test('registration acceptance never claims provider approval', () => {
  assert.equal(templateOutcome({status:'submitted',approval_status:'unknown'}).label, 'Registration submitted');
  assert.equal(templateOutcome({status:'submitted',approval_status:'pending'}).label, 'Awaiting approval');
  assert.equal(templateOutcome({status:'queued',approval_status:'pending'}).label, 'Queued');
});
test('failed submissions are not mislabelled as awaiting review by a default approval value', () => {
  assert.equal(templateOutcome({status:'failed',approval_status:'pending'}).label, 'Submission failed');
  assert.equal(templateOutcome({status:'failed',approval_status:'unknown',error:'Inventory request timed out before submission'}).unknown, false);
});
test('ambiguous provider writes remain unknown rather than rejected or retryable failures', () => {
  for (const item of [
    {status:'failed',registration_outcome:'unknown'},
    {status:'FAILED',provider_response:{outcome:'unknown'}},
    {status:'failed',error:'Registration outcome unknown. Do not resubmit automatically.'},
  ]) {
    const outcome = templateOutcome(item);
    assert.equal(outcome.label, 'Outcome unknown');
    assert.equal(outcome.unknown, true);
    assert.equal(outcome.tone, 'warning');
  }
});
test('authoritative approval updates settle an earlier unknown write', () => {
  assert.equal(templateOutcome({status:'submitted',registration_outcome:'unknown',approval_status:'approved'}).label, 'Approved');
  assert.equal(templateOutcome({status:'submitted',approval_status:'rejected'}).label, 'Rejected');
});
