const assert = require('node:assert/strict');
const { test } = require('node:test');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');
const ts = require('typescript');

const exportsObject = {};
vm.runInNewContext(ts.transpileModule(readFileSync(join(__dirname, 'jira-carousel.ts'), 'utf8'), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { exports: exportsObject, module: { exports: exportsObject } });
const { selectedRcsDraft, carouselSelectionError, carouselCardWarnings } = exportsObject;

function carousel(count = 3) {
  return {
    template_name: 'selected_offers', template_type: 'carousel',
    carousel_cards: Array.from({ length: count }, (_, index) => ({
      card_title: `Offer ${index + 1}`, card_description: `Description ${index + 1}`,
      media_url: `/private/offer_${index + 1}.png`, button_text: 'Review offer',
      button_url: `https://example.com/offer/${index + 1}`,
    })),
  };
}

test('excluding first and middle cards preserves selected content and order without deleting editable cards', () => {
  const draft = { ...carousel(4), excluded_card_indices: [0, 2] };
  const payload = selectedRcsDraft(draft);
  assert.deepEqual(Array.from(payload.carousel_cards), [draft.carousel_cards[1], draft.carousel_cards[3]]);
  assert.equal('excluded_card_indices' in payload, false);
  assert.equal(draft.carousel_cards.length, 4);
  draft.carousel_cards[3] = { ...draft.carousel_cards[3], card_description: 'Edited offer' };
  assert.equal(selectedRcsDraft(draft).carousel_cards[1].card_description, 'Edited offer');
  draft.excluded_card_indices = [];
  assert.deepEqual(Array.from(selectedRcsDraft(draft).carousel_cards), draft.carousel_cards);
});

test('carousel eligibility enforces 2–10 selected cards, including deselecting every card', () => {
  for (const count of [0, 1, 11]) assert.match(carouselSelectionError(carousel(count)), /Select 2–10 cards/);
  for (const count of [2, 10]) assert.equal(carouselSelectionError(carousel(count)), null);
  assert.match(carouselSelectionError(selectedRcsDraft({ ...carousel(), excluded_card_indices: [0, 1, 2] })), /0 selected/);
  assert.equal(carouselSelectionError({ template_type: 'text' }), null);
  assert.equal(carouselSelectionError({ template_type: 'richcard' }), null);
});

test('filtered validation warnings stay on the original card and supersede stale card warnings', () => {
  const draft = { ...carousel(), excluded_card_indices: [0] };
  draft.carousel_cards[1].aspect_ratio_blocked = true;
  draft.carousel_cards[1].aspect_ratio_warnings = [{ component: 'Card 2 Image', blocked: true }];
  const warnings = {
    ...selectedRcsDraft(draft),
    aspect_ratio_warnings: [{ component: 'Card 2 Image', blocked: true, error: 'Invalid image' }],
    compliance_warnings: [{ component: 'Card 2 Title', issue: 'Too long', severity: 'error' }],
    grammar_warnings: [],
  };
  assert.deepEqual(Object.keys(carouselCardWarnings(draft, warnings, 0)), []);
  assert.equal(carouselCardWarnings(draft, warnings, 1).aspect_ratio_blocked, false);
  const third = carouselCardWarnings(draft, warnings, 2);
  assert.equal(third.aspect_ratio_blocked, true);
  assert.equal(third.aspect_ratio_warnings[0].component, 'Card 3 Image');
  assert.equal(third.compliance_warnings[0].component, 'Card 3 Title');
});
