import type { SmsBriefCandidate, SmsBriefReview, SmsDltDraft } from './api';

/** Select first, then collapse only exact copy with unambiguous compatible hints. */
export function prepareSmsBriefDrafts(candidates: SmsBriefCandidate[], selectedIds: string[], filename: string): SmsDltDraft[] {
  const selected = new Set(selectedIds);
  const rows = candidates.filter((candidate) => selected.has(candidate.id));
  if (!rows.length || rows.length > 500) throw new Error('Select between 1 and 500 source candidates.');
  const hints = new Map<string, Set<string>>();
  for (const row of rows) {
    if (!hints.has(row.text)) hints.set(row.text, new Set());
    if (row.suggested_template_type) hints.get(row.text)!.add(row.suggested_template_type);
  }
  const groups = new Map<string, SmsBriefCandidate[]>();
  for (const row of rows) {
    const compatible = hints.get(row.text)!;
    const hint = row.suggested_template_type || (compatible.size === 1 ? [...compatible][0] : '');
    const key = JSON.stringify([row.text, hint]);
    const group = groups.get(key);
    if (group) group.push(row); else groups.set(key, [row]);
  }
  const names = new Set<string>();
  return [...groups.values()].map((group) => {
    const first = group[0];
    const base = first.suggested_template_name.replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 60) || 'sms_brief';
    let name = base;
    for (let suffix = 2; names.has(name); suffix++) {
      const ending = `_${suffix}`;
      name = `${base.slice(0, 60 - ending.length)}${ending}`;
    }
    names.add(name);
    return {
      template_name: name, text: first.text, template_type: '', category_id: '', header_id: '', header: '',
      message_type: /[^\x00-\x7F]/.test(first.text) ? '2' : '1', sample_message: '',
      source_file: filename, source_ref: group.map((row) => `${row.sheet}!${row.cell}`).join('; '),
      brief: {
        original_text: first.text,
        sources: group.map(({ sheet, cell, campaign, segment, language }) => ({ sheet, cell, campaign, segment, language })),
        warnings: [...new Set(group.flatMap((row) => [
          ...row.warnings,
          ...(row.suggested_template_type ? [`Source type hint: ${row.suggested_template_type} (${row.sheet}!${row.cell}); choose the provider template type explicitly.`] : []),
          ...(row.scope ? [`Source scope: ${row.scope}`] : []),
          ...(row.source_kind ? [`Source kind: ${row.source_kind}`] : []),
        ]))],
        variables: first.variables.map((token) => ({ token, kind: '', sample: '' })), acknowledged: false,
      },
    };
  });
}

/** Sequential matching keeps Unicode and repeated occurrences independent, without touching static copy. */
export function applySmsBriefDecisions(brief: SmsBriefReview): { text: string; sample_message: string } | null {
  let offset = 0;
  let text = '';
  let sample = '';
  for (const decision of brief.variables) {
    if (!decision.token || !decision.kind || (decision.kind !== 'literal' && !decision.sample.trim())) return null;
    const position = brief.original_text.indexOf(decision.token, offset);
    if (position < 0) return null;
    const staticCopy = brief.original_text.slice(offset, position);
    text += staticCopy + (decision.kind === 'literal' ? decision.token : `{#${decision.kind}#}`);
    sample += staticCopy + (decision.kind === 'literal' ? decision.token : decision.sample);
    offset = position + decision.token.length;
  }
  return { text: text + brief.original_text.slice(offset), sample_message: sample + brief.original_text.slice(offset) };
}

export function smsBriefReady(draft: SmsDltDraft): boolean {
  return !draft.brief || Boolean(draft.brief.acknowledged && draft.brief.sources.length && applySmsBriefDecisions(draft.brief));
}

export function editSmsBriefDraft(draft: SmsDltDraft, patch: Partial<SmsDltDraft>): SmsDltDraft {
  const next = { ...draft, ...patch };
  if (next.brief) next.brief = { ...next.brief, acknowledged: false };
  return next;
}
