import { normalizeCampaignName } from './campaign-name';

export const WHITELIST_NAME_HINT = 'New WhatsApp/RCS whitelisting names automatically start with lowercase att_. Edited names are normalized on blur. Existing approved template references and SMS IDs stay unchanged.';

export function normalizeNewTemplateName(value: string): string {
  return normalizeCampaignName(value);
}

export function newRcsTemplateName(
  base: string,
  existingNames: ReadonlySet<string>,
  variant: 'rcs' | 'rcs_manual' = 'rcs',
): string {
  const clean = normalizeNewTemplateName(base.toLowerCase().replace(/[^a-z0-9_]/g, '_').replace(/_+/g, '_').replace(/^_+|_+$/g, '')).slice(4);
  for (let sequence = 1; ; sequence += 1) {
    const suffix = `_${variant}_${sequence}`;
    const prefix = clean.slice(0, 25 - 'att_'.length - suffix.length).replace(/_+$/g, '');
    const candidate = `att_${prefix}${suffix}`;
    if (!existingNames.has(candidate)) return candidate;
  }
}
