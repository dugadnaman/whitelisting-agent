export const BRIEF_SMS_PAGE_SIZE = 25;
export const BRIEF_SMS_REVIEW_LIMIT = 500;

type SearchableSmsDraft = { template_name: string; text: string; variant?: string };

// Navigation holds source indices only; names and exact message bytes stay in the source array.
export function matchingBriefSmsIndices(drafts: readonly SearchableSmsDraft[], query: string): number[] {
  const search = query.trim().toLowerCase();
  const indices: number[] = [];
  drafts.forEach((draft, index) => {
    if (!search || draft.template_name.toLowerCase().includes(search) || draft.text.toLowerCase().includes(search)
      || draft.variant?.toLowerCase().includes(search)) indices.push(index);
  });
  return indices;
}

export function briefSmsPage(indices: readonly number[], requestedPage: number) {
  const pageCount = Math.max(1, Math.ceil(indices.length / BRIEF_SMS_PAGE_SIZE));
  const page = Math.max(1, Math.min(requestedPage, pageCount));
  const start = (page - 1) * BRIEF_SMS_PAGE_SIZE;
  return { indices: indices.slice(start, start + BRIEF_SMS_PAGE_SIZE), page, pageCount, start };
}

// Refuse the whole addition rather than silently selecting a partial page or oversized batch.
export function selectBriefSmsIndices(previous: Set<number>, indices: readonly number[], select: boolean): Set<number> {
  const next = new Set(previous);
  indices.forEach((index) => { if (select) next.add(index); else next.delete(index); });
  return select && next.size > BRIEF_SMS_REVIEW_LIMIT ? previous : next;
}

export function selectedBriefSmsDrafts<T>(drafts: readonly T[], selected: ReadonlySet<number>): T[] {
  return drafts.filter((_, index) => selected.has(index));
}
