const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const exportsObject = {};
vm.runInNewContext(ts.transpileModule(readFileSync(join(__dirname, 'campaign-name.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { exports: exportsObject, module: { exports: exportsObject } });
const { normalizeCampaignName, requireCampaignName, normalizeCampaignFields, campaignRowName } = exportsObject;

test('campaign prefixes are lowercase and idempotent while suffix text keeps its case', () => {
  for (const [raw, expected] of [
    ['  Festive Offer OCT26  ', 'att_Festive Offer OCT26'],
    ['ATT_TCN-546 - Personal Loan', 'att_TCN-546 - Personal Loan'],
    ['Att_Mixed_CASE', 'att_Mixed_CASE'],
    ['att_Already_Canonical', 'att_Already_Canonical'],
    ['att_Keep att_ inside suffix', 'att_Keep att_ inside suffix'],
  ]) {
    const normalized = normalizeCampaignName(raw);
    assert.equal(normalized, expected);
    assert.equal(normalizeCampaignName(normalized), expected);
    assert.equal(requireCampaignName(normalized), expected);
  }
});

test('blank and prefix-only names stay blocked after normalization', () => {
  for (const raw of ['', '  \n\t ', 'att_', ' ATT_  ', 'att_\t']) {
    assert.throws(() => requireCampaignName(normalizeCampaignName(raw)), /nonempty name/);
  }
  assert.equal(normalizeCampaignName('  \n\t '), '');
  for (const raw of ['Unprefixed', 'ATT_Name', ' att_Name', 'att_Name ', null, undefined, 123, {}]) {
    assert.throws(() => requireCampaignName(raw), /lowercase att_/);
  }
});

test('new campaign fields normalize across accounts and channels without renaming source or template identities', () => {
  for (const account of ['tata', 'bajaj']) {
    for (const channel of ['WHATSAPP', 'EMAIL', 'PUSH']) {
      const source = Object.freeze({
        account,
        channel,
        campaign_name: '  TCN-546 - Personal Loan  ',
        source_ref: 'TCN-546 Original Filename.csv',
        summary: 'TCN-546 - Personal Loan',
        template_name: 'approved_template',
        whatsapp_template_name: 'Approved WhatsApp Name',
        whatsapp_template_id: 'template-id-123',
        email_template_id: 'email-template-id-456',
        whatsapp_sender: 'Tata Capital Financial Services Limited',
      });
      const normalized = normalizeCampaignFields(source);
      assert.notEqual(normalized, source);
      assert.equal(normalized.campaign_name, 'att_TCN-546 - Personal Loan');
      assert.equal(requireCampaignName(normalized.campaign_name), normalized.campaign_name);
      for (const key of Object.keys(source).filter((key) => key !== 'campaign_name')) {
        assert.equal(normalized[key], source[key]);
      }
      assert.equal(source.campaign_name, '  TCN-546 - Personal Loan  ');
    }
  }
});

test('preview labels prefer the actual server candidate over a stale raw source name', () => {
  const source = Object.freeze({ campaign_name: 'Raw Jira summary', whatsapp_template_id: 'unchanged-template-id' });
  const candidate = Object.freeze({ basic_details: Object.freeze({ name: 'att_Raw Jira summary' }) });
  const row = Object.freeze({ source_fields: source, candidate_v5_payload: candidate });
  assert.equal(campaignRowName(row), 'att_Raw Jira summary');
  assert.equal(source.campaign_name, 'Raw Jira summary');
  assert.equal(source.whatsapp_template_id, 'unchanged-template-id');
});

test('saved campaign and read-back identities are displayed verbatim, never prefixed retroactively', () => {
  const candidate = { basic_details: { name: 'Legacy saved Campaign' } };
  const row = { campaign_id: 'existing-id', source_fields: { campaign_name: 'Legacy source name' }, candidate_v5_payload: candidate };
  assert.equal(campaignRowName(row), 'Legacy saved Campaign');
  assert.equal(candidate.basic_details.name, 'Legacy saved Campaign');
  assert.equal(row.campaign_id, 'existing-id');
  assert.equal(campaignRowName({ source_fields: row.source_fields }), 'Legacy source name');
  assert.equal(campaignRowName({}), '');
});
