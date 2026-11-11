import type { JiraRcsDraft, JiraWhatsAppDraft } from './api';

export const TATA_CTA_URL = 'https://www.tatacapital.com/';
const TATA_ACCOUNTS: Record<string, true> = { tata: true, tcl_promo: true, tcl_trans: true, tchfl: true, wealth: true, moneyfy: true };
const CTA_VARIABLE_PATTERN = /\{\{[^{}]+\}\}|<[^<>]+>|\[[^\[\]]+\]|\{[^{}]+\}|#[a-zA-Z0-9_\-]+#/g;

function isTataAccount(account: string): boolean {
  return TATA_ACCOUNTS[account.trim().toLowerCase()] === true;
}

export function resolveCtaUrl(url: string | null | undefined, account: string): string {
  const value = (url || '').trim();
  if (!isTataAccount(account)) return value;
  const tokens = value.match(CTA_VARIABLE_PATTERN) || [];
  if (!value || (tokens.length === 1 && tokens[0] === value)) return TATA_CTA_URL + value;
  if (!/^https?:\/\/[^/?#]+/i.test(value)) return value;
  try {
    const parsed = new URL(value);
    const host = parsed.hostname.toLowerCase();
    if (host === 'mnge.co' || host.endsWith('.mnge.co') || host === 'moengage.com' || host.endsWith('.moengage.com')) {
      return TATA_CTA_URL + tokens.join('');
    }
    return value;
  } catch {
    // Keep invalid input visible so destination validation can reject it.
    return value;
  }
}

export function isUrlCta(type?: string): boolean {
  return ['URL', 'OPEN_URL', 'URL_ACTION'].includes((type || 'URL').toUpperCase());
}

export function normalizeWhatsAppCtas<T extends JiraWhatsAppDraft>(draft: T, account: string): T {
  if (!isTataAccount(account)) return draft;
  return {
    ...draft,
    ...(isUrlCta(draft.button_type) ? { button_url: resolveCtaUrl(draft.button_url, account) } : {}),
    ...(draft.buttons ? { buttons: draft.buttons.map((button) => isUrlCta(button.type)
      ? { ...button, url: resolveCtaUrl(button.url, account) } : button) } : {}),
  };
}

export function normalizeRcsCtas<T extends JiraRcsDraft>(draft: T, account: string): T {
  if (!isTataAccount(account)) return draft;
  return {
    ...draft,
    ...(isUrlCta(draft.action_type) && (draft.action_label || draft.action_url) ? { action_url: resolveCtaUrl(draft.action_url, account) } : {}),
    ...(draft.suggestions ? { suggestions: draft.suggestions.map((suggestion) => isUrlCta(suggestion.type)
      ? { ...suggestion, url: resolveCtaUrl(suggestion.url, account) } : suggestion) } : {}),
    ...(draft.carousel_cards ? { carousel_cards: draft.carousel_cards.map((card) => ({
      ...card, button_url: resolveCtaUrl(card.button_url, account),
    })) } : {}),
  };
}

// Dashboard cards use the provider's suggestion schema, not Jira's button fields.
export function normalizeRcsSyncCtas<T extends { cta_url?: string; carousel_cards?: Array<Record<string, unknown>> }>(template: T, account: string): T {
  if (!isTataAccount(account)) return template;
  return {
    ...template,
    cta_url: resolveCtaUrl(template.cta_url, account),
    ...(template.carousel_cards ? { carousel_cards: template.carousel_cards.map((card) => ({
      ...card,
      ...(typeof card.button_url === 'string' ? { button_url: resolveCtaUrl(card.button_url, account) } : {}),
      ...(Array.isArray(card.suggestions) ? { suggestions: card.suggestions.map((suggestion: Record<string, unknown>) =>
        isUrlCta(String(suggestion.suggestionType || suggestion.type || 'URL'))
          ? { ...suggestion, url: resolveCtaUrl(typeof suggestion.url === 'string' ? suggestion.url : '', account) }
          : suggestion) } : {}),
    })) } : {}),
  };
}
