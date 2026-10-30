'use client';

import { useEffect, useRef, useState } from 'react';
import { useApp } from '@/lib/context';
import { useTabState, setTabState, clearTabState } from '@/lib/tab-state';
import {
  fetchSmsDltSession, saveSmsDltSession, fetchSmsDltOptions, previewSmsDltDrafts,
  submitSmsDltDrafts, previewFile, getSampleCsvUrl, fetchJob, identifyTemplates, parseSmsDltBrief,
  type SmsDltDraft, type SmsDltOptions, type SmsDltSession, type SmsDltSubmission,
  type TemplatePreview, type JobTask, type IdentificationReport, type SmsBriefExtraction, type SmsBriefDecision,
} from '@/lib/api';
import { formatError } from '@/lib/format';
import { prepareSmsBriefDrafts, applySmsBriefDecisions, smsBriefReady, editSmsBriefDraft } from '@/lib/sms-brief';
import KarixAuthSync from '@/components/KarixAuthSync';

const inputClass = 'w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs disabled:bg-gray-100';
const buttonClass = 'rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white disabled:opacity-50';
const emptyOptions: SmsDltOptions = { categories: [], headers: [], brands: [] };
const typeLabels = { '1': 'Promotional', '2': 'Transactional', '3': 'Service' };

export function SmsDltSessionForm({ account, onDirty }: { account: string; onDirty?: (dirty: boolean) => void }) {
  const [session, setSession] = useState<SmsDltSession | null>(null);
  const [cookie, setCookie] = useState('');
  const [entityId, setEntityId] = useState('');
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const active = useRef(true);
  useEffect(() => {
    active.current = true;
    if (account !== 'tata') { setLoading(false); return; }
    fetchSmsDltSession(account).then((value) => {
      if (!active.current) return;
      setSession(value); setEntityId(value.entity_id || '');
    }).catch((err) => { if (active.current) setError(formatError(err)); })
      .finally(() => { if (active.current) setLoading(false); });
    return () => { active.current = false; };
  }, [account]);
  const dirty = Boolean(cookie || entityId !== (session?.entity_id || ''));
  useEffect(() => {
    onDirty?.(dirty);
    return () => onDirty?.(false);
  }, [dirty, onDirty]);
  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (account !== 'tata' || !cookie.trim() || !entityId.trim() || saving) return;
    setSaving(true); setError(''); setSaved(false);
    try {
      const result = await saveSmsDltSession(account, cookie.trim(), entityId.trim());
      if (!active.current) return;
      setSession(result); setEntityId(result.entity_id || entityId.trim()); setCookie(''); setSaved(true);
    } catch (err) { if (active.current) setError(formatError(err)); }
    finally { if (active.current) setSaving(false); }
  }
  if (account !== 'tata') return <p role="alert" className="text-sm text-amber-900">SMS DLT whitelisting is not integrated for this account. Select Tata Capital (tata) and SMS in Whitelisting for. Tata portal credentials are never used for another account.</p>;
  return <div className="space-y-4">
    <KarixAuthSync account={account} integration="sms" />
    <details className="rounded-xl border border-gray-200 bg-white p-4">
      <summary className="cursor-pointer text-xs font-semibold">Manual portal-session override</summary>
      <form onSubmit={save} className="mt-4 space-y-4">
    <h2 className="text-sm font-bold text-gray-900">Tata Capital · VILPOWER DLT portal session</h2>
    <p className="text-xs text-gray-600">Template registration only. This does not send SMS, enable a paid API, or change the portal account.</p>
    <p role="status" className="text-xs font-semibold">{loading ? 'Loading saved session…' : session?.configured ? (session.expired || session.validation_state === 'expired' ? 'Saved session expired. Replace it below.' : 'A portal session is saved. It will be checked when used.') : 'No portal session is configured.'}</p>
    <ol className="list-decimal pl-5 text-xs text-gray-600 space-y-1">
      <li>Sign in to the VILPOWER portal as the Tata Capital entity. Verify the entity ID there.</li>
      <li>Open browser DevTools → Network, then open or refresh Content Templates in the portal.</li>
      <li>Select that portal request → Headers → Request Headers → Cookie. Copy the complete Cookie value, not response Set-Cookie headers or a WhatsApp/Karix token.</li>
      <li>Paste it below. Validation reads the portal without registering a template. Sessions expire: repeat these steps and save a fresh cookie when authentication fails.</li>
    </ol>
    <label className="block text-xs font-semibold">Tata DLT principal entity ID
      <span className="mt-1 block font-normal text-gray-500">Expected entity: TATA CAPITAL LIMITED · 1101637310000019220. Enter the ID explicitly from the portal.</span>
      <input required autoComplete="off" className={`${inputClass} mt-1`} value={entityId} onChange={(e) => { setEntityId(e.target.value); setSaved(false); }} disabled={loading || saving} />
    </label>
    <label className="block text-xs font-semibold">New VILPOWER request Cookie
      <input required type="password" autoComplete="new-password" spellCheck={false} className={`${inputClass} mt-1 font-mono`} value={cookie} onChange={(e) => { setCookie(e.target.value); setSaved(false); }} disabled={saving} />
    </label>
    <p className="text-[11px] text-gray-500">The cookie is masked, sent only to the server for validation and encrypted storage, and never persisted in browser storage or returned to this form.</p>
    {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
    {saved && <p role="status" className="text-xs text-green-800">Session validated and saved for Tata Capital.</p>}
    <button type="submit" disabled={loading || saving || !cookie.trim() || !entityId.trim()} className={buttonClass}>{saving ? 'Validating…' : 'Validate and save portal session'}</button>
      </form>
    </details>
  </div>;
}

export function smsDltDraft(value: { template_name: string; text: string } & Partial<SmsDltDraft>): SmsDltDraft {
  return { template_type: '', category_id: '', header_id: '', header: '', message_type: '', sample_message: '', ...value };
}

function SmsDltEditor({ draft, onChange, disabled, onReady }: {
  draft: SmsDltDraft; onChange: (draft: SmsDltDraft) => void; disabled: boolean; onReady: (ready: boolean, category?: string) => void;
}) {
  const [options, setOptions] = useState<SmsDltOptions>(emptyOptions);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); onReady(false);
    if (!draft.template_type) { setOptions(emptyOptions); setLoading(false); return () => controller.abort(); }
    fetchSmsDltOptions('tata', draft, '', controller.signal).then((result) => {
      if (!controller.signal.aborted) { setOptions(result); setLoading(false); }
    }).catch((err) => { if (!controller.signal.aborted) { setError(formatError(err)); setLoading(false); } });
    return () => controller.abort();
    // Copy edits do not change portal routing options.
  }, [draft.template_type, draft.category_id, draft.service_type, revision]);
  const valid = !loading && !error && options.categories.some((option) => option.id === draft.category_id)
    && options.headers.some((option) => option.id === draft.header_id && option.text === draft.header)
    && (!draft.brand_id || options.brands.some((option) => option.id === draft.brand_id))
    && (draft.template_type !== '3' || !options.service_types?.length || Boolean(draft.service_type && options.service_types.some((option) => option.id === draft.service_type)));
  useEffect(() => { onReady(valid, options.categories.find((option) => option.id === draft.category_id)?.text || ''); }, [valid, onReady, options.categories, draft.category_id]);
  function update(patch: Partial<SmsDltDraft>) { onChange(editSmsBriefDraft(draft, patch)); }
  return <fieldset disabled={disabled} className="rounded-xl border border-gray-200 p-4 space-y-3">
    <legend className="px-1 text-xs font-bold">{draft.template_name || 'Unnamed template'}</legend>
    {draft.brief && <div className="space-y-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs">
      <p className="font-bold">Client brief provenance · {draft.source_file}</p>
      <p className="break-words">{draft.source_ref}</p>
      {draft.brief.sources.map((source, index) => <div key={index} className="space-y-2 border-t border-amber-200 pt-2">
        <p className="font-semibold">{source.sheet}!{source.cell}</p>
        <div className="grid gap-2 sm:grid-cols-3">{(['campaign', 'segment', 'language'] as const).map((field) => <label key={field} className="capitalize">{field}<input className={`${inputClass} mt-1`} value={source[field]} onChange={(event) => update({ brief: { ...draft.brief!, sources: draft.brief!.sources.map((item, idx) => idx === index ? { ...item, [field]: event.target.value } : item) } })} /></label>)}</div>
      </div>)}
      {draft.brief.warnings.map((warning, index) => <p key={index} className="text-amber-900">{warning}</p>)}
      <p className="font-semibold">Immutable original client copy</p>
      <pre className="whitespace-pre-wrap break-words font-mono">{draft.brief.original_text}</pre>
      <p>Decide each occurrence independently. Bracketed text may be literal. Samples must be supplied by you; applying decisions changes only these occurrences, never the surrounding copy.</p>
      {draft.brief.variables.map((decision, index) => <div key={index} className="grid gap-2 rounded border border-amber-200 p-2 sm:grid-cols-3">
        <p className="break-words font-mono">Occurrence {index + 1}: {decision.token}</p>
        <label>Interpretation<select className={`${inputClass} mt-1`} value={decision.kind} onChange={(event) => update({ brief: { ...draft.brief!, variables: draft.brief!.variables.map((item, idx) => idx === index ? { ...item, kind: event.target.value as SmsBriefDecision['kind'] } : item) } })}>
          <option value="">Choose literal or variable</option><option value="literal">Keep exact literal text</option><option value="num">num · number</option><option value="alp">alp · alphanumeric text</option><option value="urg">urg · URL</option><option value="uro">uro · URL</option><option value="cbn">cbn · callback number</option><option value="eml">eml · email</option>
        </select></label>
        {decision.kind && decision.kind !== 'literal' && <label>Explicit sample value<input className={`${inputClass} mt-1`} value={decision.sample} onChange={(event) => update({ brief: { ...draft.brief!, variables: draft.brief!.variables.map((item, idx) => idx === index ? { ...item, sample: event.target.value } : item) } })} /></label>}
      </div>)}
      <button type="button" className={buttonClass} disabled={!applySmsBriefDecisions(draft.brief)} onClick={() => {
        const generated = applySmsBriefDecisions(draft.brief!);
        if (generated && (draft.text === draft.brief!.original_text || window.confirm('Apply decisions from the immutable original? This replaces the current edited body and sample.'))) update(generated);
      }}>Apply occurrence decisions to body and sample</button>
      <p>You may edit the final body and sample below. The original and every matching source remain visible; review again after any edit. Encoding is only a suggestion based on the exact original copy.</p>
    </div>}
    <div className="grid gap-3 sm:grid-cols-2">
      <label className="text-xs font-semibold">Template name<input className={`${inputClass} mt-1`} value={draft.template_name} onChange={(e) => update({ template_name: e.target.value })} /></label>
      <label className="text-xs font-semibold">Template type<select className={`${inputClass} mt-1`} value={draft.template_type} onChange={(e) => update({ template_type: e.target.value as SmsDltDraft['template_type'], category_id: '', header_id: '', header: '', brand_id: '', service_type: '' })}><option value="">Choose template type</option>{Object.entries(typeLabels).map(([id, text]) => <option key={id} value={id}>{text}</option>)}</select></label>
      {draft.template_type === '3' && Boolean(options.service_types?.length) && <label className="text-xs font-semibold">Service type<select className={`${inputClass} mt-1`} value={draft.service_type || ''} onChange={(e) => update({ service_type: e.target.value, category_id: '', header_id: '', header: '', brand_id: '' })} disabled={loading}><option value="">Choose service type</option>{options.service_types?.map((option) => <option key={option.id} value={option.id}>{option.text}</option>)}</select></label>}
      <label className="text-xs font-semibold">DLT category<select className={`${inputClass} mt-1`} value={draft.category_id} onChange={(e) => update({ category_id: e.target.value, header_id: '', header: '', brand_id: '' })} disabled={loading}><option value="">Choose category</option>{options.categories.map((option) => <option key={option.id} value={option.id}>{option.text}</option>)}</select></label>
      <label className="text-xs font-semibold">Sender header<select className={`${inputClass} mt-1`} value={draft.header_id} onChange={(e) => update({ header_id: e.target.value, header: options.headers.find((option) => option.id === e.target.value)?.text || '' })} disabled={loading}><option value="">Choose header</option>{options.headers.map((option) => <option key={option.id} value={option.id}>{option.text}</option>)}</select></label>
      <label className="text-xs font-semibold">Brand (optional)<select className={`${inputClass} mt-1`} value={draft.brand_id || ''} onChange={(e) => update({ brand_id: e.target.value })} disabled={loading}><option value="">No brand selected</option>{options.brands.map((option) => <option key={option.id} value={option.id}>{option.text}</option>)}</select></label>
      <label className="text-xs font-semibold">Message encoding<select className={`${inputClass} mt-1`} value={draft.message_type} onChange={(e) => update({ message_type: e.target.value as SmsDltDraft['message_type'] })}><option value="">Choose message encoding</option><option value="1">ASCII / English</option><option value="2">Regional / Unicode</option></select></label>
    </div>
    <label className="block text-xs font-semibold">Exact DLT template body<textarea rows={4} className={`${inputClass} mt-1 font-mono`} value={draft.text} onChange={(e) => update({ text: e.target.value })} /></label>
    <p className="text-[11px] text-gray-500">Text is preserved exactly. Use VILPOWER typed variables only: {'{#num#}, {#alp#}, {#urg#}, {#uro#}, {#cbn#}, {#eml#}'} (maximum 15). Replace Jira/WhatsApp placeholders yourself; no normalization or grammar correction is applied.</p>
    <label className="block text-xs font-semibold">Sample message (required when the body has typed variables)<textarea rows={3} className={`${inputClass} mt-1 font-mono`} value={draft.sample_message} onChange={(e) => update({ sample_message: e.target.value })} /></label>
    {draft.brief && <label className="flex gap-2 text-xs font-semibold"><input type="checkbox" checked={draft.brief.acknowledged} disabled={!applySmsBriefDecisions(draft.brief)} onChange={(event) => onChange({ ...draft, brief: { ...draft.brief!, acknowledged: event.target.checked } })} />I reviewed every source, campaign, language, warning and token decision, and the exact final body and explicit sample. These selected sources are intended for SMS; no month or approval status was inferred.</label>}
    {loading && <p role="status" className="text-xs text-gray-500">Loading Tata portal options…</p>}
    {error && <p role="alert" className="text-xs text-red-700">{error} <a href="/settings" className="underline">Refresh the Tata SMS portal session in Settings</a>. <button type="button" className="underline" onClick={() => setRevision((value) => value + 1)}>Retry options</button></p>}
    {!loading && !error && !valid && <p className="text-xs text-amber-800">Choose valid portal category, header and service type (if applicable) before review. Imported IDs must match current Tata options.</p>}
  </fieldset>;
}

export function SmsDltReview({ initialDrafts, storageKey, onClose }: {
  initialDrafts: SmsDltDraft[]; storageKey: string; onClose?: () => void;
}) {
  const { account, channel, user } = useApp();
  const [drafts, setDrafts] = useTabState<SmsDltDraft[]>(`${storageKey}_drafts`, initialDrafts);
  const [batch, setBatch] = useTabState<SmsDltSubmission | null>(`${storageKey}_job`, null);
  const [ready, setReady] = useState<Record<number, boolean>>({});
  const [categoryLabels, setCategoryLabels] = useState<Record<number, string>>({});
  const [reviewed, setReviewed] = useState<{ signature: string; previews: TemplatePreview[] } | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [tasks, setTasks] = useState<JobTask[]>([]);
  const [jobStatus, setJobStatus] = useState('');
  const [pollRevision, setPollRevision] = useState(0);
  const active = useRef(true);
  const requestVersion = useRef(0);
  const signature = JSON.stringify(drafts);
  const scope = useRef({ account, channel, signature });
  scope.current = { account, channel, signature };
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  useEffect(() => { requestVersion.current++; setBusy(false); setReviewed(null); }, [account, channel]);
  const destinationValid = account === 'tata' && channel === 'sms';
  const reviewedCurrent = reviewed?.signature === signature;
  const hasErrors = reviewed?.previews.some((preview) => preview.compliance_warnings?.some((warning) => warning.severity === 'error'));
  const fieldsValid = drafts.length > 0 && drafts.length <= 500 && drafts.every((draft, index) => ready[index]
    && draft.template_type && draft.message_type && draft.template_name.trim() && draft.text.trim()
    && (!draft.text.includes('{#') || draft.sample_message.trim()) && smsBriefReady(draft));
  useEffect(() => { setConfirmed(false); }, [signature, account, channel]);
  useEffect(() => {
    if (!batch?.job_id || !destinationValid) return;
    let cancelled = false;
    let timer: NodeJS.Timeout;
    async function poll() {
      try {
        const snapshot = await fetchJob(batch!.job_id!);
        if (cancelled) return;
        setTasks(snapshot.tasks); setJobStatus(snapshot.job.status);
        if (snapshot.job.error_message) setError(snapshot.job.error_message);
        if (!['COMPLETED', 'PARTIALLY_COMPLETED', 'FAILED'].includes(snapshot.job.status)) timer = setTimeout(poll, 2500);
      } catch (err) { if (!cancelled) setError(`Job status unavailable: ${formatError(err)}. The batch may still be processing; do not resubmit it. Check History or retry status.`); }
    }
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [batch?.job_id, destinationValid, pollRevision]);
  async function review() {
    if (!destinationValid || !fieldsValid || busy) return;
    const requested = signature;
    const version = ++requestVersion.current;
    setBusy(true); setError(''); setConfirmed(false);
    try {
      const previews = await previewSmsDltDrafts(account, drafts);
      if (!active.current || version !== requestVersion.current || scope.current.account !== 'tata' || scope.current.channel !== 'sms' || scope.current.signature !== requested) return;
      if (previews.length !== drafts.length) throw new Error('The preview did not return every draft. Nothing has been submitted.');
      setReviewed({ signature: requested, previews });
    } catch (err) { if (active.current && version === requestVersion.current) setError(formatError(err)); }
    finally { if (active.current && version === requestVersion.current) setBusy(false); }
  }
  async function submit() {
    if (!destinationValid || !fieldsValid || !reviewedCurrent || !confirmed || hasErrors || busy || batch) return;
    const requested = signature;
    const version = ++requestVersion.current;
    setBusy(true); setError('');
    try {
      const result = await submitSmsDltDrafts(account, drafts, user);
      if (!active.current || version !== requestVersion.current || scope.current.account !== 'tata' || scope.current.channel !== 'sms' || scope.current.signature !== requested) return;
      setBatch(result); setJobStatus(result.status);
    } catch (err) { if (active.current && version === requestVersion.current) { setError(`${formatError(err)} Drafts are retained. If the request timed out, check History before retrying: the queue may already contain this batch.`); setConfirmed(false); } }
    finally { if (active.current && version === requestVersion.current) setBusy(false); }
  }
  if (!destinationValid) return <p role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-900">SMS DLT whitelisting requires the explicit Tata Capital (tata) · SMS destination. Select it in Whitelisting for. Other accounts are not integrated and cannot use Tata credentials.</p>;
  return <section className="space-y-4 rounded-xl border border-gray-200 bg-white p-5">
    <div className="flex flex-wrap justify-between gap-3"><h2 className="text-sm font-bold">Review Tata Capital · SMS DLT · VILPOWER</h2><a href="/" className="text-xs text-blue-700 underline">Template history and approval status</a></div>
    <p className="text-xs text-gray-600">Register templates only; no recipients or SMS sending. Select provider fields explicitly, then validate and confirm the exact message and sample. A queued or pending template is not approved.</p>
    {!batch && drafts.map((draft, index) => <SmsDltEditor key={index} draft={draft} disabled={busy} onReady={(value, category = '') => {
      setReady((prev) => prev[index] === value ? prev : { ...prev, [index]: value });
      setCategoryLabels((prev) => prev[index] === category ? prev : { ...prev, [index]: category });
    }} onChange={(value) => { setReviewed(null); setDrafts((prev) => prev.map((item, idx) => idx === index ? value : item)); }} />)}
    {error && <div role="alert" className="rounded-lg bg-red-50 p-3 text-xs text-red-800"><p>{error}</p><p className="mt-1">For portal authentication errors, <a href="/settings" className="underline">replace the Tata SMS session in Settings</a>. Check <a href="/" className="underline">History</a> before retrying a submission.</p></div>}
    {!batch && <>
      <div className="flex flex-wrap gap-3"><button type="button" disabled={busy || !fieldsValid} onClick={review} className={buttonClass}>{busy ? 'Processing…' : 'Validate and review DLT drafts'}</button>{onClose && <button type="button" disabled={busy} onClick={onClose} className="text-xs font-semibold text-gray-600 underline">Back to source drafts</button>}</div>
      {reviewedCurrent && <div className="rounded-xl border border-blue-200 bg-blue-50 p-4 space-y-4">
        <p className="text-xs font-bold">Destination: Tata Capital (tata) · SMS · VILPOWER</p>
        {drafts.map((draft, index) => <div key={index} className="space-y-2 rounded-lg border border-blue-100 bg-white p-3 text-xs">
          <p className="font-bold">{draft.template_name} · {draft.template_type ? typeLabels[draft.template_type] : ''}</p>
          <p>Header: {draft.header} (ID {draft.header_id}) · Category: {categoryLabels[index]} (ID {draft.category_id}) · Encoding: {draft.message_type === '1' ? 'ASCII' : 'Regional'}{draft.service_type ? ` · Service type: ${draft.service_type}` : ''}{draft.brand_id ? ` · Brand ID: ${draft.brand_id}` : ''}</p>
          {draft.brief && <div className="space-y-1"><p className="font-semibold">Sources: {draft.source_file} · {draft.source_ref}</p>{draft.brief.sources.map((source, idx) => <p key={idx}>{source.sheet}!{source.cell} · Campaign: {source.campaign || 'Not specified'} · Segment: {source.segment || 'Not specified'} · Language: {source.language || 'Not specified'}</p>)}{draft.brief.warnings.map((warning, idx) => <p key={idx} className="text-amber-800">{warning}</p>)}</div>}
          <p className="font-semibold">Exact body</p><pre className="whitespace-pre-wrap break-words font-mono">{draft.text}</pre>
          <p className="font-semibold">Sample message</p><pre className="whitespace-pre-wrap break-words font-mono">{draft.sample_message || '(No variables; no sample supplied)'}</pre>
          {reviewed.previews[index]?.already_exists_on_waba && <p className="text-amber-800">Already registered; duplicate skipping is enabled.</p>}
          {reviewed.previews[index]?.compliance_warnings?.map((warning, idx) => <p key={idx} role={warning.severity === 'error' ? 'alert' : undefined} className={warning.severity === 'error' ? 'text-red-700' : 'text-amber-800'}>{warning.severity}: {warning.issue}</p>)}
        </div>)}
        <label className="flex gap-2 text-xs font-semibold"><input type="checkbox" checked={confirmed} disabled={busy || hasErrors} onChange={(e) => setConfirmed(e.target.checked)} />I confirm Tata Capital / VILPOWER, the selected header and category, and every exact body and sample above. Register these DLT templates; do not send SMS.</label>
        <button type="button" className={buttonClass} disabled={busy || hasErrors || !confirmed || !fieldsValid} onClick={submit}>Confirm and queue DLT whitelisting</button>
      </div>}
    </>}
    {batch && <div className="space-y-3 text-xs">
      <p role="status" className="font-bold">Tata Capital · VILPOWER · {jobStatus || batch.status}{batch.job_id ? ` · Job ${batch.job_id}` : ''}</p>
      <p>Registration and approval are separate. Pending does not mean approved. Refresh approval status in History. Expired portal sessions must be replaced in <a href="/settings" className="underline text-blue-700">Settings</a>; failed templates require a new review, not automatic replay.</p>
      <button type="button" className="underline text-blue-700" onClick={() => { setError(''); setPollRevision((value) => value + 1); }}>Refresh job status</button>
      <div className="overflow-x-auto"><table className="w-full text-left"><thead><tr><th className="p-2">Template</th><th className="p-2">Queue status</th><th className="p-2">DLT approval</th><th className="p-2">DLT template ID</th><th className="p-2">Error / reason</th></tr></thead><tbody>{tasks.length ? tasks.map((task) => <tr key={task.id} className="border-t border-gray-100"><td className="p-2">{task.template_name}</td><td className="p-2">{task.status}</td><td className="p-2">{task.approval_status}</td><td className="p-2 font-mono">{task.provider_ref_id || '—'}</td><td className="p-2 text-red-700">{task.error || task.approval_reason || '—'}</td></tr>) : batch.results.map((result, index) => <tr key={result.task_id || index} className="border-t border-gray-100"><td className="p-2">{result.template_name}</td><td className="p-2">{result.status}</td><td className="p-2">{result.approval_status || 'pending'}</td><td className="p-2 font-mono">{result.provider_ref_id || '—'}</td><td className="p-2 text-red-700">{result.error || result.approval_reason || '—'}</td></tr>)}</tbody></table></div>
      {onClose && <button type="button" className="underline" onClick={onClose}>Return to source drafts</button>}
    </div>}
  </section>;
}

export function SmsDltUpload() {
  const { account, channel } = useApp();
  const [drafts, setDrafts] = useTabState<SmsDltDraft[] | null>('submit_sms_dlt_source', null);
  const [filename, setFilename] = useTabState('submit_sms_dlt_filename', '');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [revision, setRevision] = useTabState('submit_sms_dlt_revision', 0);
  const [identification, setIdentification] = useTabState<IdentificationReport | null>('submit_sms_dlt_identification', null);
  const [brief, setBrief] = useTabState<SmsBriefExtraction | null>('submit_sms_dlt_brief', null);
  const [selectedSources, setSelectedSources] = useTabState<string[]>('submit_sms_dlt_brief_selected', []);
  const [sheetFilter, setSheetFilter] = useTabState('submit_sms_dlt_brief_sheet', '');
  const [scopeFilter, setScopeFilter] = useTabState('submit_sms_dlt_brief_scope', '');
  const [campaignFilter, setCampaignFilter] = useTabState('submit_sms_dlt_brief_campaign', '');
  const scope = useRef({ account, channel });
  scope.current = { account, channel };
  const requestVersion = useRef(0);
  useEffect(() => () => { requestVersion.current++; }, []);
  useEffect(() => { requestVersion.current++; setBusy(false); setError(''); }, [account, channel]);
  async function uploadBrief(file: File) {
    if (account !== 'tata' || channel !== 'sms' || busy || drafts) return;
    const version = ++requestVersion.current;
    setBusy(true); setError('');
    try {
      if (!/\.(xlsx|xls)$/i.test(file.name)) throw new Error('Choose a native .xlsx or .xls client workbook. Flat DLT files use the separate upload.');
      if (file.size > 20 * 1024 * 1024) throw new Error('Client workbooks must be no larger than 20 MiB.');
      const result = await parseSmsDltBrief(file, account);
      if (version !== requestVersion.current || scope.current.account !== 'tata' || scope.current.channel !== 'sms') return;
      setBrief(result); setSelectedSources([]); setSheetFilter(''); setScopeFilter(''); setCampaignFilter('');
    } catch (err) { if (version === requestVersion.current) setError(formatError(err)); }
    finally { if (version === requestVersion.current) setBusy(false); }
  }
  async function upload(file: File) {
    if (account !== 'tata' || channel !== 'sms' || busy || drafts) return;
    const version = ++requestVersion.current;
    setBusy(true); setError('');
    try {
      const previews = await previewFile(file, account, 'sms');
      if (version !== requestVersion.current || scope.current.account !== 'tata' || scope.current.channel !== 'sms') return;
      if (!previews.length || previews.some((preview) => !preview.sms_dlt)) throw new Error('The file did not return DLT drafts. Use the SMS DLT sample columns; no recipient phone numbers are needed.');
      setDrafts(previews.map((preview) => smsDltDraft(preview.sms_dlt!))); setFilename(file.name); setRevision((value) => value + 1);
      setTabState('submit_state', { step: 'previewed', previews });
    } catch (err) { if (version === requestVersion.current) setError(formatError(err)); }
    finally { if (version === requestVersion.current) setBusy(false); }
  }
  async function identify(file: File) {
    if (account !== 'tata' || channel !== 'sms' || busy) return;
    const version = ++requestVersion.current;
    setBusy(true); setError('');
    try {
      const result = await identifyTemplates(file, account, 'sms');
      if (version !== requestVersion.current || scope.current.account !== 'tata' || scope.current.channel !== 'sms') return;
      setIdentification(result);
    } catch (err) { if (version === requestVersion.current) setError(formatError(err)); }
    finally { if (version === requestVersion.current) setBusy(false); }
  }
  if (account !== 'tata' || channel !== 'sms') return <div className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-sm text-amber-900">SMS DLT whitelisting is available only for Tata Capital (tata) · SMS. Select it in Whitelisting for. Other accounts are not integrated; Tata credentials cannot be reused.</div>;
  return <div className="space-y-5">
    <div className="flex flex-wrap justify-between gap-3"><div><h1 className="text-2xl font-bold">Tata SMS DLT Whitelisting</h1><p className="mt-1 text-xs text-gray-600">VILPOWER portal · exact template registration, not SMS sending</p></div><a href={getSampleCsvUrl('sms')} download className="text-xs font-semibold text-blue-700 underline">Download SMS DLT sample CSV</a></div>
    <p className="text-xs text-gray-600">Connect your <a href="/settings" className="text-blue-700 underline">Tata VILPOWER session in Settings</a>. Upload CSV or Excel with template_name and text plus any DLT fields; choose missing fields during review. No phone numbers, grammar correction, or placeholder substitution.</p>
    {!drafts && <label className="block rounded-xl border-2 border-dashed border-gray-300 bg-white p-8 text-sm font-semibold">Upload DLT CSV / Excel<input type="file" accept=".csv,.xlsx,.xls" disabled={busy} className="mt-3 block text-xs" onChange={(e) => { const file = e.target.files?.[0]; if (file) void upload(file); e.target.value = ''; }} /></label>}
    {!drafts && <section className="space-y-4 rounded-xl border border-gray-200 bg-white p-5">
      <h2 className="text-sm font-bold">Import native client brief · choose SMS source candidates</h2>
      <p className="text-xs text-gray-600">Upload the original multi-sheet .xlsx / .xls workbook without reshaping it. Extraction is offline: no portal session, registration or SMS sending. Historical and matching sources stay visible; nothing is selected automatically, and neither current month nor approval is inferred.</p>
      <label className="block text-xs font-semibold">Upload client brief workbook<input type="file" accept=".xlsx,.xls" disabled={busy} className="mt-2 block" onChange={(event) => { const file = event.target.files?.[0]; if (file) void uploadBrief(file); event.target.value = ''; }} /></label>
      {brief && <>
        <p className="text-xs font-semibold">Workbook: {brief.filename} · {brief.candidates.length} candidates · {selectedSources.length} selected (maximum 500)</p>
        {brief.warnings.map((warning, index) => <p key={index} role="status" className="text-xs text-amber-900">{warning}</p>)}
        <p className="text-xs text-gray-600">{brief.sheets.map((sheet) => `${sheet.name}: ${sheet.candidate_count}`).join(' · ')}</p>
        <div className="grid gap-3 sm:grid-cols-3">
          <label className="text-xs">Sheet<select className={`${inputClass} mt-1`} disabled={busy} value={sheetFilter} onChange={(event) => setSheetFilter(event.target.value)}><option value="">All sheets</option>{brief.sheets.map((sheet) => <option key={sheet.name} value={sheet.name}>{sheet.name} ({sheet.candidate_count})</option>)}</select></label>
          <label className="text-xs">Campaign scope<select className={`${inputClass} mt-1`} disabled={busy} value={scopeFilter} onChange={(event) => setScopeFilter(event.target.value)}><option value="">All scopes</option>{[...new Set(brief.candidates.map((candidate) => candidate.scope).filter(Boolean))].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
          <label className="text-xs">Campaign<select className={`${inputClass} mt-1`} disabled={busy} value={campaignFilter} onChange={(event) => setCampaignFilter(event.target.value)}><option value="">All campaigns</option>{[...new Set(brief.candidates.map((candidate) => candidate.campaign).filter(Boolean))].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
        </div>
        <p className="text-xs text-gray-600">Filters do not change selections. Only explicitly selected, exact-body duplicates with compatible type hints are grouped; all selected references and warnings are retained.</p>
        <button type="button" className="text-xs underline" disabled={busy || !selectedSources.length} onClick={() => setSelectedSources([])}>Clear all source selections</button>
        <div className="max-h-[36rem] space-y-3 overflow-y-auto">
          {brief.candidates.filter((candidate) => (!sheetFilter || candidate.sheet === sheetFilter) && (!scopeFilter || candidate.scope === scopeFilter) && (!campaignFilter || candidate.campaign === campaignFilter)).map((candidate) => <label key={candidate.id} className="flex gap-3 rounded-lg border border-gray-200 p-3 text-xs">
            <input type="checkbox" className="mt-1" checked={selectedSources.includes(candidate.id)} disabled={busy || (selectedSources.length >= 500 && !selectedSources.includes(candidate.id))} onChange={(event) => {
              const checked = event.target.checked;
              setSelectedSources((previous) => checked ? (previous.includes(candidate.id) || previous.length >= 500 ? previous : [...previous, candidate.id]) : previous.filter((id) => id !== candidate.id));
            }} />
            <div className="min-w-0 space-y-2"><p className="font-semibold">{candidate.sheet}!{candidate.cell} · {candidate.source_kind || 'SMS candidate'}</p>
              <p>Scope: {candidate.scope || 'Not specified'} · Campaign: {candidate.campaign || 'Not specified'} · Segment: {candidate.segment || 'Not specified'} · Language: {candidate.language || 'Not specified'}</p>
              <p>Source template type hint: {candidate.suggested_template_type ? typeLabels[candidate.suggested_template_type] : 'None; choose explicitly during review'}</p>
              <pre className="whitespace-pre-wrap break-words font-mono">{candidate.text}</pre>
              {candidate.warnings.map((warning, index) => <p key={index} className="text-amber-900">{warning}</p>)}
            </div>
          </label>)}
        </div>
        <button type="button" className={buttonClass} disabled={busy || !selectedSources.length || selectedSources.length > 500} onClick={() => {
          if (account !== 'tata' || channel !== 'sms') return;
          try {
            const prepared = prepareSmsBriefDrafts(brief.candidates, selectedSources, brief.filename);
            requestVersion.current++;
            setDrafts(prepared); setFilename(brief.filename); setRevision((value) => value + 1); setError('');
            setTabState('submit_state', { step: 'previewed', previews: [] });
          } catch (err) { setError(formatError(err)); }
        }}>Prepare DLT review from {selectedSources.length} selected source candidates</button>
      </>}
    </section>}
    {busy && <p role="status" className="text-xs">Reading DLT templates…</p>}
    {error && <p role="alert" className="text-xs text-red-700">{error}</p>}
    {drafts && <><p className="text-xs font-semibold">Source file: {filename}</p><SmsDltReview key={revision} initialDrafts={drafts} storageKey={`submit_sms_dlt_${revision}`} onClose={() => { if (!window.confirm('Clear this review? Any queued batch remains available in History.')) return; clearTabState(`submit_sms_dlt_${revision}`); setDrafts(null); setTabState('submit_state', { step: 'idle' }); }} /></>}
    <details className="rounded-xl border border-gray-200 bg-white p-4 text-xs">
      <summary className="cursor-pointer font-semibold">Identify templates against Tata VILPOWER inventory</summary>
      <p className="mt-3 text-gray-600">Read-only comparison of exact SMS text and typed variables. This does not register or send messages.</p>
      <label className="mt-3 block font-semibold">Upload DLT CSV / Excel to compare<input type="file" accept=".csv,.xlsx,.xls" disabled={busy} className="mt-2 block" onChange={(event) => { const file = event.target.files?.[0]; if (file) void identify(file); event.target.value = ''; }} /></label>
      {identification && <div className="mt-4 space-y-3">
        <p>{identification.summary_notes}</p>
        <p>{identification.whitelisted_count} approved / whitelisted · {identification.pending_count} pending · {identification.rejected_count} rejected · {identification.missing_count} missing · {identification.drift_count} different</p>
        <button type="button" className={buttonClass} disabled={busy || Boolean(drafts) || identification.missing_templates.length === 0} onClick={() => {
          const missing = identification.missing_templates.map((row) => smsDltDraft({
            template_name: typeof row.template_name === 'string' ? row.template_name : '',
            text: typeof row.text === 'string' ? row.text : '',
            template_type: row.template_type === '1' || row.template_type === '2' || row.template_type === '3' ? row.template_type : '',
            message_type: row.message_type === '1' || row.message_type === '2' ? row.message_type : '',
            category_id: typeof row.category_id === 'string' ? row.category_id : '',
            header_id: typeof row.header_id === 'string' ? row.header_id : '',
            header: typeof row.header === 'string' ? row.header : '',
            brand_id: typeof row.brand_id === 'string' ? row.brand_id : '',
            service_type: typeof row.service_type === 'string' ? row.service_type : '',
            sample_message: typeof row.sample_message === 'string' ? row.sample_message : '',
          }));
          setDrafts(missing); setFilename('Missing templates from DLT identification'); setRevision((value) => value + 1);
          setTabState('submit_state', { step: 'previewed', previews: [] });
        }}>Review missing DLT templates ({identification.missing_templates.length})</button>
        {drafts && identification.missing_templates.length > 0 && <p className="text-gray-500">Clear the current review before loading missing templates. Queued jobs remain in History.</p>}
        <div className="overflow-x-auto"><table className="w-full text-left"><thead><tr><th className="p-2">Template</th><th className="p-2">Status</th><th className="p-2">DLT ID</th><th className="p-2">Details</th></tr></thead><tbody>{identification.items.map((item, index) => <tr key={index} className="border-t"><td className="p-2">{item.template_name}</td><td className="p-2">{item.status}</td><td className="p-2 font-mono">{item.live_fb_id || '—'}</td><td className="p-2">{item.diff_summary}</td></tr>)}</tbody></table></div>
      </div>}
    </details>
  </div>;
}
