import type { DraftWarnings, JiraRcsDraft } from './api';

export type SelectableRcsDraft = JiraRcsDraft & { excluded_card_indices?: number[] };

export function selectedRcsDraft(draft: SelectableRcsDraft): JiraRcsDraft {
  const { excluded_card_indices, ...payload } = draft;
  if (!draft.carousel_cards?.length) return payload;
  return {
    ...payload,
    template_type: 'carousel',
    carousel_cards: draft.carousel_cards.filter((_, index) => !excluded_card_indices?.includes(index)),
  };
}

export function carouselSelectionError(draft: JiraRcsDraft): string | null {
  if (draft.template_type !== 'carousel' && draft.template_type !== 'carousal' && !draft.carousel_cards?.length) return null;
  const count = draft.carousel_cards?.length || 0;
  return count < 2 || count > 10
    ? `Select 2–10 cards to whitelist this carousel (${count} selected).`
    : null;
}

export function carouselCardWarnings(draft: SelectableRcsDraft, warnings: DraftWarnings, index: number): DraftWarnings {
  if (draft.excluded_card_indices?.includes(index)) return {};
  const selectedIndex = (draft.carousel_cards || []).slice(0, index)
    .filter((_, cardIndex) => !draft.excluded_card_indices?.includes(cardIndex)).length;
  const context = new RegExp(`^Card ${selectedIndex + 1}(?:\\b|:)`, 'i');
  const label = (component: string) => component.replace(context, `Card ${index + 1}`);
  const card = draft.carousel_cards?.[index];
  const aspectWarnings = warnings.aspect_ratio_warnings?.filter((warning) => context.test(warning.component))
    .map((warning) => ({ ...warning, component: label(warning.component) })) ?? card?.aspect_ratio_warnings;
  return {
    aspect_ratio_warnings: aspectWarnings,
    aspect_ratio_blocked: aspectWarnings ? aspectWarnings.some((warning) => warning.blocked) : card?.aspect_ratio_blocked,
    aspect_ratio_block_reason: card?.aspect_ratio_block_reason,
    compliance_warnings: warnings.compliance_warnings?.filter((warning) => context.test(warning.component || warning.issue))
      .map((warning) => ({ ...warning, component: warning.component ? label(warning.component) : undefined, issue: label(warning.issue) })) ?? card?.compliance_warnings,
    grammar_warnings: warnings.grammar_warnings?.filter((warning) => context.test(warning.component || warning.issue))
      .map((warning) => ({ ...warning, component: warning.component ? label(warning.component) : undefined, issue: label(warning.issue) })) ?? card?.grammar_warnings,
  };
}
