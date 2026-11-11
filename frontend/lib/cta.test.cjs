const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const exportsObject = {};
vm.runInNewContext(ts.transpileModule(readFileSync(join(__dirname, 'cta.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { exports: exportsObject, module: { exports: exportsObject }, URL });
const { TATA_CTA_URL, resolveCtaUrl, normalizeWhatsAppCtas, normalizeRcsCtas, normalizeRcsSyncCtas } = exportsObject;

test('every Tata account replaces MoEngage destinations and retains every dynamic token', () => {
  for (const account of ['tata', 'tcl_promo', 'tcl_trans', 'tchfl', 'wealth', 'moneyfy', ' TATA ']) {
    assert.equal(resolveCtaUrl('', account), TATA_CTA_URL);
    assert.equal(resolveCtaUrl(' https://u3.mnge.co/offer/{{1}}/<offer>/[link]/{code}/#token#/{{1}} ', account),
      `${TATA_CTA_URL}{{1}}<offer>[link]{code}#token#{{1}}`);
    for (const url of ['https://mnge.co/', 'https://offers.mnge.co/', 'http://moengage.com/', 'https://links.moengage.com/']) {
      assert.equal(resolveCtaUrl(url, account), TATA_CTA_URL);
    }
  }
});

test('explicit external destinations and lookalike tracking hosts remain unchanged', () => {
  for (const url of [
    'https://example.com/',
    'https://teams.microsoft.com/l/meetup-join/meeting?context={{1}}',
    'https://mnge.co.evil.test/',
    'https://notmnge.co/',
    'https://moengage.com.evil.test/',
    'https://notmoengage.com/',
    'https://mnge.co@evil.test/',
    'https://tatacapital.com.evil.test/',
    'https://tatacapital.com@evil.test/',
  ]) assert.equal(resolveCtaUrl(url, 'tata'), url);
});

test('missing and placeholder-only destinations default, while invalid input remains available for validation', () => {
  for (const token of ['{{1}}', '<offer>', '[link]', '{code}', '#token#']) {
    assert.equal(resolveCtaUrl(token, 'tata'), TATA_CTA_URL + token);
  }
  for (const url of ['javascript:alert(1)', 'ftp://example.com/{{1}}', 'not a URL', 'https://[broken/{{1}}', 'https:///example.com', 'https:example.com']) {
    assert.equal(resolveCtaUrl(url, 'tata'), url);
  }
});

test('Tata product paths, subdomains, queries and runtime variables remain intact', () => {
  for (const url of [
    'https://www.tatacapital.com/personal-loan.html?source=jira&offer={{1}}',
    'https://offers.tatacapital.com/path/<product>?campaign=[campaign]#cta#',
    'http://tatacapital.com/product/{id}',
  ]) assert.equal(resolveCtaUrl(` ${url} `, 'tata'), url);
  for (const account of ['bajaj', 'apparel']) {
    assert.equal(resolveCtaUrl(' https://u3.mnge.co/{{1}} ', account), 'https://u3.mnge.co/{{1}}');
    assert.equal(resolveCtaUrl('', account), '');
  }
});

test('cached WhatsApp drafts and preview payloads normalize URL buttons without changing source text or phone/reply actions', () => {
  const draft = {
    template_name: 'cached_offer', body: 'Visit https://u3.mnge.co/{{1}}', raw_source: 'Source https://example.com',
    media_file: 'https://cdn.example.com/image.png', button_type: 'URL', button_url: 'https://u3.mnge.co/{{2}}',
    buttons: [
      { type: 'URL', text: 'Explore', url: 'https://example.com/<offer>' },
      { type: 'PHONE_NUMBER', text: 'Call', phone_number: '+911234567890', url: 'unchanged' },
      { type: 'QUICK_REPLY', text: 'Yes', url: 'unchanged' },
    ],
  };
  const normalized = normalizeWhatsAppCtas(draft, 'wealth');
  assert.equal(normalized.button_url, `${TATA_CTA_URL}{{2}}`);
  assert.equal(normalized.buttons[0].url, draft.buttons[0].url);
  assert.equal(normalized.buttons[1], draft.buttons[1]);
  assert.equal(normalized.buttons[2], draft.buttons[2]);
  for (const key of ['body', 'raw_source', 'media_file']) assert.equal(normalized[key], draft[key]);
  assert.equal(draft.button_url, 'https://u3.mnge.co/{{2}}');
  assert.equal(normalizeWhatsAppCtas(normalized, 'wealth').buttons[0].url, normalized.buttons[0].url);
  for (const account of ['apparel', 'bajaj']) assert.equal(normalizeWhatsAppCtas(draft, account), draft);
});

test('RCS draft previews and every carousel card resolve destinations independently', () => {
  const draft = {
    action_type: 'URL', action_label: 'Explore', action_url: 'https://u3.mnge.co/{{1}}',
    body: 'Body https://u3.mnge.co', excluded_card_indices: [1],
    suggestions: [{ type: 'URL', url: 'https://offers.mnge.co/[link]' }, { type: 'REPLY', text: 'Yes' }, { type: 'DIAL', phone_number: '+911234567890' }],
    carousel_cards: [
      { button_url: 'https://example.com/{offer}', media_url: 'https://cdn.example.com/image.png' },
      { button_url: 'https://www.tatacapital.com/home-loan.html?q={{2}}' },
      { button_text: 'Explore' },
    ],
  };
  const normalized = normalizeRcsCtas(draft, 'tcl_promo');
  assert.equal(normalized.action_url, `${TATA_CTA_URL}{{1}}`);
  assert.equal(normalized.suggestions[0].url, `${TATA_CTA_URL}[link]`);
  assert.equal(normalized.suggestions[1], draft.suggestions[1]);
  assert.equal(normalized.suggestions[2], draft.suggestions[2]);
  assert.equal(normalized.carousel_cards[0].button_url, draft.carousel_cards[0].button_url);
  assert.equal(normalized.carousel_cards[1].button_url, draft.carousel_cards[1].button_url);
  assert.equal(normalized.carousel_cards[2].button_url, TATA_CTA_URL);
  assert.equal(normalized.carousel_cards[0].media_url, draft.carousel_cards[0].media_url);
  assert.equal(normalized.body, draft.body);
  assert.equal(normalized.excluded_card_indices, draft.excluded_card_indices);
  const reply = { action_type: 'REPLY', action_label: 'Yes', action_url: 'unchanged' };
  assert.equal(normalizeRcsCtas(reply, 'tata').action_url, 'unchanged');
  assert.equal(normalizeRcsCtas({ action_type: 'URL', action_label: '', action_url: '' }, 'tata').action_url, '');
  for (const account of ['apparel', 'bajaj']) assert.equal(normalizeRcsCtas(draft, account), draft);
});

test('dashboard sync creates normalized copies and never rewrites registered inventory or other accounts', () => {
  const template = {
    cta_url: 'https://u3.mnge.co/{{1}}', media_url: 'https://cdn.example.com/image.png',
    carousel_cards: [{
      suggestions: [
        { suggestionType: 'url_action', url: 'https://links.moengage.com/<link>' },
        { type: 'OPEN_URL', url: 'https://offers.tatacapital.com/product?q={{2}}' },
        { suggestionType: 'dialer_action', phoneNumber: '+911234567890' },
        { type: 'REPLY', text: 'Yes', url: 'unchanged' },
      ],
    }],
  };
  const normalized = normalizeRcsSyncCtas(template, 'tchfl');
  assert.equal(normalized.cta_url, `${TATA_CTA_URL}{{1}}`);
  assert.equal(normalized.carousel_cards[0].suggestions[0].url, `${TATA_CTA_URL}<link>`);
  assert.equal(normalized.carousel_cards[0].suggestions[1].url, template.carousel_cards[0].suggestions[1].url);
  assert.equal(normalized.carousel_cards[0].suggestions[2], template.carousel_cards[0].suggestions[2]);
  assert.equal(normalized.carousel_cards[0].suggestions[3], template.carousel_cards[0].suggestions[3]);
  assert.equal(normalized.media_url, template.media_url);
  assert.equal(template.cta_url, 'https://u3.mnge.co/{{1}}');
  assert.equal(template.carousel_cards[0].suggestions[0].url, 'https://links.moengage.com/<link>');
  assert.equal(normalizeRcsSyncCtas({}, 'moneyfy').cta_url, TATA_CTA_URL);
  for (const account of ['apparel', 'bajaj']) assert.equal(normalizeRcsSyncCtas(template, account), template);
});
