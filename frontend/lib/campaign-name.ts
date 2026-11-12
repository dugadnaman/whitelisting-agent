import type { MoEngageDraftRow } from './api';

export const CAMPAIGN_NAME_RULE = 'Campaign names require lowercase att_ followed by a nonempty name.';
export const CAMPAIGN_NAME_HINT = 'Lowercase att_ is added automatically on blur or preview. New WhatsApp/RCS whitelisting names also use att_; existing approved template references and IDs stay unchanged.';

export function normalizeCampaignName(value: string): string {
  const name = value.trim();
  if (!name) return '';
  return /^att_/i.test(name) ? `att_${name.slice(4)}` : `att_${name}`;
}

export function requireCampaignName(value: unknown): string {
  if (typeof value !== 'string' || value !== value.trim() || !value.startsWith('att_') || !value.slice(4).trim()) {
    throw new Error(CAMPAIGN_NAME_RULE);
  }
  return value;
}

export function normalizeCampaignFields<T extends { campaign_name: string }>(fields: T): T {
  return { ...fields, campaign_name: normalizeCampaignName(fields.campaign_name) };
}

export function campaignRowName(row: Pick<MoEngageDraftRow, 'candidate_v5_payload' | 'source_fields'>): string {
  // Display the server's actual candidate; never rewrite saved/read-back identities.
  return row.candidate_v5_payload?.basic_details?.name || row.source_fields?.campaign_name || '';
}
