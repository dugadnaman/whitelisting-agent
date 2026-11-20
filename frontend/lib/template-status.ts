export type TemplateOutcomeInput = {
  status?: string | null;
  approval_status?: string | null;
  registration_outcome?: string | null;
  provider_response?: Record<string, unknown> | null;
  error?: string | null;
};
export type TemplateOutcome = { label: string; tone: 'success' | 'warning' | 'error' | 'neutral'; unknown: boolean };

/** Registration acceptance is not provider approval; unknown writes must never invite a retry. */
export function templateOutcome(item: TemplateOutcomeInput): TemplateOutcome {
  const status = (item.status || '').toLowerCase();
  const approval = (item.approval_status || '').toLowerCase();
  if (approval === 'approved') return { label: 'Approved', tone: 'success', unknown: false };
  if (approval === 'rejected') return { label: 'Rejected', tone: 'error', unknown: false };
  if (item.registration_outcome === 'unknown' || item.provider_response?.outcome === 'unknown'
      || /^(?:Registration|Submission) outcome unknown\./i.test(item.error || '')) {
    return { label: 'Outcome unknown', tone: 'warning', unknown: true };
  }
  if (status === 'failed') return { label: 'Submission failed', tone: 'error', unknown: false };
  if (status === 'blocked' || status === 'blocked_aspect_ratio' || approval === 'blocked' || approval === 'blocked_aspect_ratio') {
    return { label: 'Blocked — review required', tone: 'error', unknown: false };
  }
  if (status === 'submitted' || status === 'duplicate') {
    return { label: approval === 'pending' ? 'Awaiting approval' : status === 'duplicate' ? 'Already registered' : 'Registration submitted', tone: 'neutral', unknown: false };
  }
  if (status === 'processing') return { label: 'Submitting', tone: 'neutral', unknown: false };
  if (status === 'pending' || status === 'queued') return { label: 'Queued', tone: 'neutral', unknown: false };
  return { label: 'Status unverified', tone: 'neutral', unknown: false };
}
