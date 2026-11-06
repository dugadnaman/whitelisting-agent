'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useApp } from '@/lib/context';
import { canUseApparelAttribution } from '@/lib/apparel-attribution';
import {
  fetchApparelWhatsAppCatalog, previewApparelWhatsAppBrief, stageApparelWhatsAppBrief,
  fetchMoEngageDraftBatch, createMoEngageDraftRow, reconcileMoEngageDraftRow, uploadApparelWhatsAppImage, MoEngageDraftRequestError,
  type ApparelWhatsAppCatalog, type ApparelWhatsAppOptions, type ApparelWhatsAppImageResult,
  type MoEngageDraftPreview, type MoEngageDraftBatch, type MoEngageDraftRow,
} from '@/lib/api';

const panel = 'rounded-xl border border-gray-200 bg-white p-5 shadow-sm';
const input = 'mt-1 w-full rounded-lg border border-gray-300 bg-white px-3 py-2.5 text-sm text-gray-900 disabled:bg-gray-50 disabled:text-gray-500 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100';
const button = 'rounded-lg border border-gray-300 px-4 py-2.5 text-sm font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed';
const editableFields = ['campaign_name', 'segment_name', 'exclude_segment_name', 'scheduled_at', 'whatsapp_template_id', 'whatsapp_placeholders', 'whatsapp_image_url', 'whatsapp_cta_links'] as const;
const fieldLabels: Record<typeof editableFields[number], string> = {
  campaign_name: 'Campaign name', segment_name: 'Include segment', exclude_segment_name: 'Exclude segment',
  scheduled_at: 'Planned time (IST)', whatsapp_template_id: 'Approved template ID',
  whatsapp_placeholders: 'Template variables', whatsapp_image_url: 'Image or Drive URL', whatsapp_cta_links: 'Button links',
};
type Preview = MoEngageDraftPreview & { source_digest: string };
const complete = (row: MoEngageDraftRow) => row.status === 'VERIFIED' && Boolean(row.campaign_id && /^[a-f0-9]{24}$/i.test(row.campaign_id));

export default function ApparelCampaignsPage() {
  const { account, currentUser, mounted, authLoading } = useApp();
  if (!mounted || authLoading) return <div className="p-8" role="status">Checking your access…</div>;
  if (!canUseApparelAttribution(currentUser, account)) return <div className="p-8"><div className={panel}>
    <h1 className="text-xl font-bold">Apparel campaigns access denied</h1>
    <p className="my-3">Authorised Apparel operators and admins only. Platform superadmins must select Apparel in the account selector.</p>
    <Link href="/" className="text-blue-600">Return to dashboard</Link>
  </div></div>;
  return <Workspace key={`${currentUser?.id}:${currentUser?.role}:${account}`} userId={String(currentUser?.id)} />;
}

function Workspace({ userId }: { userId: string }) {
  const [catalog, setCatalog] = useState<ApparelWhatsAppCatalog | null>(null);
  const [brands, setBrands] = useState<ApparelWhatsAppCatalog['brands']>([]);
  const [brand, setBrand] = useState('');
  const [reference, setReference] = useState('');
  const [nameAttribute, setNameAttribute] = useState('');
  const [file, setFile] = useState<File>();
  const [sheet, setSheet] = useState('');
  const [sourceType, setSourceType] = useState('file');
  const [columns, setColumns] = useState('');
  const [overrides, setOverrides] = useState<Record<string, Record<string, string>>>({});
  const [imageFiles, setImageFiles] = useState<Record<string, File | undefined>>({});
  const [driveChoices, setDriveChoices] = useState<Record<string, { brand: string; source: string; files: NonNullable<ApparelWhatsAppImageResult['files']> }>>({});
  const [selectedDriveFiles, setSelectedDriveFiles] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [batch, setBatch] = useState<MoEngageDraftBatch | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [halted, setHalted] = useState(false);
  const [catalogRevision, setCatalogRevision] = useState(0);
  const errorRef = useRef<HTMLDivElement>(null);
  const reviewRef = useRef<HTMLElement>(null);
  const batchRef = useRef<HTMLElement>(null);
  const revision = useRef(0);
  const previewRevision = useRef(-1);
  const alive = useRef(true);
  const pending = useRef(false);
  const storageKey = `apparel_whatsapp_batch:${userId}:apparel`;
  const marker = (batchId: string, rowId: string) => `${storageKey}:uncertain:${batchId}:${rowId}`;
  const noGoals = Boolean(brands.find((item) => item.brand === brand)?.no_goals);
  const source = sourceType === 'file' ? { file } : { spreadsheet_url: sheet.trim() };
  const options: ApparelWhatsAppOptions = {
    brand, columns: columns.trim() ? columns.toUpperCase().split(/[\s,]+/).filter(Boolean) : undefined,
    reference_campaign_id: noGoals ? undefined : reference || undefined,
    name_attribute: nameAttribute || undefined, overrides,
  };
  const invalidate = () => {
    revision.current += 1;
    setReviewed(false); setBatch(null); setConfirmed(false); setHalted(false); setError(''); setNotice('');
  };
  const resetSourceReview = () => {
    invalidate(); setPreview(null); setOverrides({}); setImageFiles({});
    setDriveChoices({}); setSelectedDriveFiles({});
  };
  // A routed batch's top-level workspace is its account ledger, not each row's destination.
  const isSelectedBrand = (items: Array<Pick<MoEngageDraftRow, 'workspace_id' | 'source_fields'>>) =>
    Boolean(brand && catalog?.brand === brand && items.length) &&
    items.every((row) => row.workspace_id === catalog?.workspace_id && row.source_fields?.brand === brand);
  const validateBatch = (value: MoEngageDraftBatch, expectedId?: string) => {
    if (value.account !== 'apparel' || (expectedId && value.batch_id !== expectedId)) throw new Error('Batch identity or account mismatch. No further writes allowed.');
    if (!isSelectedBrand(value.items)) throw new Error('Batch rows differ from the selected brand or workspace.');
    return value;
  };
  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; revision.current += 1; };
  }, []);
  useEffect(() => { if (error) { errorRef.current?.focus({ preventScroll: true }); errorRef.current?.scrollIntoView({ block: 'start' }); } }, [error]);
  useEffect(() => { if (preview) { reviewRef.current?.focus({ preventScroll: true }); reviewRef.current?.scrollIntoView({ block: 'start' }); } }, [preview]);
  useEffect(() => { if (batch) { batchRef.current?.focus({ preventScroll: true }); batchRef.current?.scrollIntoView({ block: 'start' }); } }, [batch?.batch_id]);
  useEffect(() => {
    const version = revision.current;
    let cancelled = false;
    pending.current = true; setBusy('Loading live catalog'); setError('');
    fetchApparelWhatsAppCatalog(brand || undefined, reference || undefined).then((value) => {
      if (cancelled || !alive.current || revision.current !== version) return;
      if (value.account !== 'apparel' || (brand && value.brand && value.brand !== brand)) throw new Error('Catalog account or brand mismatch.');
      setCatalog({ ...value, brand: brand || value.brand }); setBrands(value.brands);
    }).catch((err: unknown) => { if (!cancelled && alive.current && revision.current === version) { setCatalog(null); setError(err instanceof Error ? err.message : String(err)); } })
      .finally(() => { if (!cancelled && alive.current) { pending.current = false; setBusy(''); } });
    return () => { cancelled = true; };
  }, [brand, reference, catalogRevision]);

  async function run(label: string, action: (version: number) => Promise<void>) {
    if (pending.current) return;
    pending.current = true; setBusy(label); setError(''); setNotice('');
    const version = revision.current;
    try { await action(version); }
    catch (err) { if (alive.current && version === revision.current) setError(err instanceof Error ? err.message : String(err)); }
    finally { if (alive.current) { pending.current = false; setBusy(''); } }
  }
  const current = (version: number) => alive.current && revision.current === version;

  async function uploadCreative(column: string, imageSource: { file?: File; drive_url?: string }) {
    if (pending.current) return;
    invalidate();
    await run(`Uploading or resolving creative for ${column}`, async (version) => {
      const result = await uploadApparelWhatsAppImage(brand, imageSource);
      if (!current(version)) return;
      const url = result.url;
      const files = result.files;
      const driveUrl = imageSource.drive_url;
      if (url) {
        invalidate();
        setOverrides((old) => ({ ...old, [column]: { ...old[column], whatsapp_image_url: url } }));
        setDriveChoices((old) => { const next = { ...old }; delete next[column]; return next; });
        setImageFiles((old) => ({ ...old, [column]: undefined }));
        setNotice(`${column}: durable creative URL saved. Preview and review the source again before staging. No campaign was published or sent.`);
      } else if (files?.length && driveUrl) {
        setDriveChoices((old) => ({ ...old, [column]: { brand, source: driveUrl, files } }));
        setSelectedDriveFiles((old) => ({ ...old, [column]: '' }));
        setNotice(`${column}: choose the exact Drive creative, then explicitly upload it. No file was selected automatically.`);
      } else throw new Error('Media response contained neither a durable image URL nor selectable Drive files.');
    });
  }
  const validColumns = !options.columns || (options.columns.length > 0 && options.columns.length <= 100 && options.columns.every((column) => /^[A-Z]{1,3}$/.test(column)));
  const previewHelp = !brand ? 'Choose a brand to start.' : !catalog ? 'Wait for verified brand details, or reload them if loading failed.' : !(sourceType === 'file' ? file : sheet.trim()) ? 'Upload a brief or enter its Google Sheet URL.' : !validColumns ? 'Use up to 100 column letters separated by commas, for example ON, OO.' : '';
  const readyForPreview = !previewHelp && catalog?.brand === brand;
  const readyRows = batch?.items.filter((row) => row.status === 'preview_ready' && !row.campaign_id && row.issues.length === 0).length || 0;
  const allVerified = Boolean(batch?.items.length && batch.items.every(complete));
  const canStage = reviewed && previewRevision.current === revision.current && preview?.catalog_verified && preview.ready > 0 && Boolean(preview.source_digest);

  async function loadOwnBatch() {
    await run('Reading saved batch', async (version) => {
      const id = localStorage.getItem(storageKey);
      if (!id) throw new Error('No saved Apparel batch for this signed-in user.');
      const value = await fetchMoEngageDraftBatch(id, 'apparel');
      if (!current(version)) return;
      if (value.account !== 'apparel' || value.batch_id !== id) throw new Error('Saved batch identity mismatch.');
      if (!isSelectedBrand(value.items)) throw new Error('Select the saved batch’s brand before restoring it.');
      setBatch(value); setConfirmed(false);
      for (const row of value.items) if (complete(row)) localStorage.removeItem(marker(id, row.row_id));
      setHalted(value.items.some((row) => ['UNCERTAIN', 'UNKNOWN', 'MAYBE_SENT'].includes(row.status) || localStorage.getItem(marker(id, row.row_id)) === '1'));
    });
  }

  async function reconcileRow(row: MoEngageDraftRow) {
    if (!batch) return;
    const snapshot = batch;
    await run('Checking MoEngage read-only; no new draft request', async (version) => {
      const key = marker(snapshot.batch_id, row.row_id);
      localStorage.setItem(key, '1');
      setHalted(true); setConfirmed(false);
      const response = await reconcileMoEngageDraftRow(snapshot.batch_id, row.row_id, 'apparel');
      if (!current(version)) return;
      const result = validateBatch(response, snapshot.batch_id);
      const saved = result.items.find((item) => item.row_id === row.row_id && item.source_ref === row.source_ref && item.workspace_id === row.workspace_id);
      if (!saved || (row.campaign_id && saved.campaign_id !== row.campaign_id)) throw new Error('Reconciliation row identity mismatch. Creation remains stopped.');
      setBatch(result);
      const verified = response.reconciliation?.state === 'verified' && complete(saved);
      if (verified) localStorage.removeItem(key);
      setHalted(!verified || result.items.some((item) => ['UNCERTAIN', 'UNKNOWN', 'MAYBE_SENT'].includes(item.status) || localStorage.getItem(marker(result.batch_id, item.row_id)) === '1'));
      setNotice(response.reconciliation?.message || 'Read-only check completed without verified recovery. Creation remains stopped; no new draft was requested.');
    });
  }

  async function createReady() {
    if (!batch || !confirmed || halted) return;
    const snapshot = batch;
    await run('Creating drafts sequentially', async (version) => {
      let latest = validateBatch(await fetchMoEngageDraftBatch(snapshot.batch_id, 'apparel'), snapshot.batch_id);
      if (!current(version)) return;
      setBatch(latest);
      if (latest.items.some((row) => !complete(row) && !['preview_ready', 'blocked'].includes(row.status))) throw new Error('Batch contains an unverified attempt. Reconcile its saved state before creating.');
      if (latest.items.some((row) => ['UNCERTAIN', 'UNKNOWN', 'MAYBE_SENT'].includes(row.status) || localStorage.getItem(marker(latest.batch_id, row.row_id)) === '1')) {
        setHalted(true); throw new Error('An unconfirmed attempt exists. Stop and reconcile with MoEngage; do not retry creation.');
      }
      for (const row of latest.items.filter((item) => item.status === 'preview_ready' && !item.campaign_id && item.issues.length === 0)) {
        if (!current(version)) return;
        const key = marker(latest.batch_id, row.row_id);
        localStorage.setItem(key, '1');
        try {
          const result = validateBatch(await createMoEngageDraftRow(latest.batch_id, row.row_id, 'apparel'), latest.batch_id);
          if (!current(version)) return;
          latest = result; setBatch(result);
          const returned = result.items.find((item) => item.row_id === row.row_id && item.source_ref === row.source_ref && item.workspace_id === row.workspace_id);
          if (!returned || !complete(returned)) {
            const issue = returned?.issue?.replace(/[\u0000-\u001f\u007f]/g, ' ').slice(0, 400);
            throw new Error(`${row.row_id}: ${returned?.status || 'unknown result'}${issue ? ` — ${issue}` : ''}. Stopped; check MoEngage read-only before any further action. No new draft will be requested automatically.`);
          }
          localStorage.removeItem(key);
        } catch (err) {
          let verifiedAfterInterruption = false;
          if (current(version)) {
            try {
              const observed = validateBatch(await fetchMoEngageDraftBatch(latest.batch_id, 'apparel'), latest.batch_id);
              if (current(version)) {
                const saved = observed.items.find((item) => item.row_id === row.row_id && item.source_ref === row.source_ref && item.workspace_id === row.workspace_id);
                const preflightDenied = err instanceof MoEngageDraftRequestError && err.status === 423 && saved?.status === 'preview_ready' && !saved.campaign_id;
                if (saved && (complete(saved) || preflightDenied)) {
                  localStorage.removeItem(key); setBatch(observed); setConfirmed(false);
                  setHalted(observed.items.some((item) => ['UNCERTAIN', 'UNKNOWN', 'MAYBE_SENT'].includes(item.status) || localStorage.getItem(marker(observed.batch_id, item.row_id)) === '1'));
                  verifiedAfterInterruption = complete(saved);
                } else setHalted(true);
              }
            } catch {
              // An unavailable authoritative read cannot establish a safe retry.
              if (current(version)) setHalted(true);
            }
          }
          if (verifiedAfterInterruption) {
            setNotice('The saved draft is VERIFIED after a delayed response. No duplicate was requested. Review the batch before continuing; nothing was published or activated.');
            return;
          }
          throw err;
        }
      }
      if (current(version)) { setConfirmed(false); setNotice('Draft creation finished. Review the returned IDs and statuses below. Nothing was published or activated.'); }
    });
  }

  return <div className="mx-auto max-w-6xl space-y-5">
    <header className="space-y-2">
      <div className="flex flex-wrap items-center gap-3"><h1 className="text-2xl font-bold text-gray-900">WhatsApp campaign drafts</h1><span className="rounded-full border border-emerald-200 bg-emerald-50 px-3 py-1 text-xs font-semibold text-emerald-800">Draft only · No sending</span></div>
      <p className="text-sm text-gray-600">Save the supplied content as MoEngage drafts, then complete missing details directly in MoEngage. Missing launch settings do not block draft saving.</p>
      <details className="text-sm text-gray-600"><summary className="cursor-pointer font-medium">Scheduling and goal-tracking rules</summary><p className="mt-2">Planned IST times are draft metadata, not activated schedules. Goal tracking uses elapsed end − start from delivery: 29 October to 1 November is 3 days. Crocs, AGIPL, R&amp;B and CK have no conversion goals. No publishing, test sends or SMS fallback creation.</p></details>
    </header>
    <ol aria-label="Draft workflow progress" className="grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
      {['Brand & brief', 'Review campaigns', 'Stage for approval', 'Save drafts'].map((label, index) => {
        const step = batch ? 3 : reviewed ? 2 : preview ? 1 : 0;
        return <li key={label} aria-current={step === index ? 'step' : undefined} className={`rounded-lg border px-3 py-2 ${step === index ? 'border-blue-200 bg-blue-50 font-semibold text-blue-800' : 'border-gray-200 text-gray-500'}`}>{index + 1}. {label}{allVerified && index === 3 ? ' · Complete' : ''}</li>;
      })}
    </ol>
    {error && <div ref={errorRef} tabIndex={-1} role="alert" className="scroll-mt-40 rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800"><p className="font-semibold">Action needed</p><p className="mt-1">{error}</p></div>}
    {notice && <div role="status" className="rounded-lg bg-green-50 p-4 text-sm text-green-800">{notice}</div>}
    {busy && <p role="status" className="flex items-center gap-2 rounded-lg border border-blue-100 bg-blue-50 p-3 text-sm text-blue-800"><span aria-hidden="true" className="h-4 w-4 animate-spin rounded-full border-2 border-blue-200 border-t-blue-700" />{busy}… {brand ? 'Live MoEngage checks may take up to 3 minutes. Please keep this page open.' : ''}</p>}
    <fieldset disabled={Boolean(busy)} className={`${panel} space-y-4`}>
      <legend className="px-1 text-base font-semibold">1. Choose your brand</legend>
      <label className="block text-sm">Brand<select className={input} value={brand} onChange={(event) => {
        const nextBrand = event.target.value;
        invalidate(); setBrand(nextBrand); setReference(''); setNameAttribute(''); setOverrides({}); setImageFiles({}); setDriveChoices({}); setSelectedDriveFiles({}); setCatalog(null); setPreview(null);
        setFile(undefined); setColumns('');
        const found = brands.find((item) => item.brand === nextBrand);
        setSheet(found?.spreadsheet_url || ''); setSourceType('sheet');
      }}>
        <option value="">Select brand</option>{brands.map((item) => <option key={item.brand} value={item.brand}>{item.brand} · {item.workspace_name}</option>)}
      </select></label>
      {brand && <p className="text-sm">Workspace: {catalog?.workspace_name || catalog?.workspace_id || 'Loading…'}</p>}
      {!busy && !catalog && <button type="button" className={button} onClick={() => setCatalogRevision((old) => old + 1)}>Reload brand details</button>}
      {brand && !noGoals && <label className="block text-sm">Existing campaign goal reference (optional)<select className={input} value={reference} onChange={(event) => { invalidate(); setReference(event.target.value); }}>
        <option value="">Set goals later in MoEngage</option>{catalog?.reference_campaigns?.filter((item) => item.has_goals).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.status.replace(/<br\s*\/?>/gi, ' ')}</option>)}
      </select></label>}
      {noGoals ? <p className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-800">No conversion goals are needed for {brand}.</p> : catalog?.goal_reference && <details className="text-sm"><summary className="cursor-pointer font-medium">Goal settings from {catalog.goal_reference.name}</summary><pre className="mt-2 overflow-auto rounded bg-gray-50 p-3 text-xs">{JSON.stringify(catalog.goal_reference.conversion, null, 2)}</pre></details>}
      {brand && <details className="text-sm"><summary className="cursor-pointer font-medium">Customer-name personalization{ nameAttribute ? ` · ${nameAttribute}` : ' (when the template needs it)'}</summary>
        <label className="mt-3 block text-sm">Customer name field<select className={input} value={nameAttribute} onChange={(event) => { invalidate(); setNameAttribute(event.target.value); }}>
          <option value="">Choose a verified name field, if required</option>{catalog?.user_attributes?.map((attribute) => <option key={attribute} value={attribute}>{attribute}</option>)}
        </select></label><p className="mt-2 text-xs text-gray-500">Choose First Name or the correct name attribute for this brand. The brief must explicitly provide a fallback for missing names.</p>
      </details>}
    </fieldset>
    {brand && <fieldset disabled={Boolean(busy) || !catalog} className={`${panel} space-y-4`}>
      <legend className="px-1 text-base font-semibold">2. Choose your brief</legend>
      <label className="block text-sm">Source<select className={input} value={sourceType} onChange={(event) => { resetSourceReview(); setColumns(''); setSourceType(event.target.value); }}><option value="file">XLSX / CSV upload</option><option value="sheet">Google Sheet URL</option></select></label>
      {sourceType === 'file' ? <label className="block text-sm">Brief file<input className={input} type="file" accept=".xlsx,.csv" onChange={(event) => { resetSourceReview(); setFile(event.target.files?.[0]); }} /></label> : <>
        <label className="block text-sm">Google Sheet URL<input className={input} type="url" value={sheet} onChange={(event) => { resetSourceReview(); setSheet(event.target.value); }} /></label>
        {/^https:\/\/docs\.google\.com\/spreadsheets\//.test(sheet) && <a href={sheet} target="_blank" rel="noopener noreferrer" className="inline-block text-sm font-semibold text-blue-700 underline">Open source sheet ↗</a>}
        <p className="text-sm text-gray-600">Share the Google Sheet with Viewer access to {catalog?.google_service_account_email ? <strong>{catalog.google_service_account_email}</strong> : 'the configured Google service account (ask your administrator for its address)'}. Do not make the sheet public.</p>
      </>}
      <label className="block text-sm">Campaign columns (up to 100)<input className={input} value={columns} aria-describedby="campaign-columns-help" aria-invalid={!validColumns} onChange={(event) => { invalidate(); setColumns(event.target.value); }} placeholder={sourceType === 'file' ? 'For example C, D — use the columns in your uploaded file' : 'For example ON, OO — use the columns in your brand sheet'} /></label>
      <p id="campaign-columns-help" className={`text-xs ${validColumns ? 'text-gray-500' : 'text-red-700'}`}>{validColumns ? 'Use spreadsheet column letters, not row numbers. Blank reads detected columns; yearly briefs can exceed the 100-campaign limit, so choose only the campaigns you need. Uploaded samples may use C rather than ON.' : 'Enter 1–100 column letters separated by spaces or commas; ranges such as C:F are not supported.'}</p>
      <p className="text-sm text-gray-500">Saving always creates a new draft. Existing campaign IDs are kept for reference; existing campaigns are not changed.</p>
      {previewHelp && <p className="text-sm text-amber-800">{previewHelp}</p>}
      <button type="button" className={`${button} bg-blue-600 text-white`} disabled={!readyForPreview} onClick={() => void run('Previewing brief', async (version) => {
        setReviewed(false); setBatch(null); setConfirmed(false);
        previewRevision.current = -1;
        const result = await previewApparelWhatsAppBrief(source, options);
        if (!current(version)) return;
        if (result.account !== 'apparel' || !isSelectedBrand(result.items) || !result.source_digest) throw new Error('Preview account, workspace or source digest is invalid.');
        previewRevision.current = version; setPreview(result); setHalted(false);
      })}>Preview campaigns</button>
    </fieldset>}
    {preview && <section ref={reviewRef} tabIndex={-1} aria-labelledby="campaign-review-heading" className={`${panel} scroll-mt-40 space-y-4 outline-none`}>
      <h2 id="campaign-review-heading" className="text-base font-semibold">3. Review campaigns</h2>
      <details className="text-xs text-gray-500"><summary className="cursor-pointer">Source verification details</summary><p className="mt-2 break-all">Digest: {preview.source_digest} · Catalog verified: {String(preview.catalog_verified)}</p></details>
      <p className={`rounded-lg p-3 text-sm font-semibold ${preview.blocked ? 'bg-amber-50 text-amber-900' : 'bg-emerald-50 text-emerald-800'}`}>{preview.ready} ready to save as drafts · {preview.blocked} cannot be saved{preview.blocked ? ' — these rows are skipped; other drafts can proceed.' : ' — unfinished details can be completed in MoEngage.'}</p>
      {previewRevision.current !== revision.current && <p className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm font-semibold text-amber-900" role="status">This preview is out of date. Select Preview campaigns again before reviewing or staging.</p>}
      <p className="text-sm text-amber-800">Warnings do not block saving. Nothing is published or sent. Edits require a fresh preview; complete unfinished settings in MoEngage before launch.</p>
      <fieldset disabled={Boolean(busy)} className="space-y-4">
        {preview.items.map((row) => {
          const column = row.row_id;
          const fields = row.source_fields || {};
          const creativeUrl = overrides[column]?.whatsapp_image_url ?? fields.whatsapp_image_url ?? '';
          const choices = driveChoices[column];
          const showChoices = choices?.brand === brand && choices.source === creativeUrl;
          return <details key={`${row.source_ref}:${row.row_id}`} open className="rounded-lg border border-gray-200 p-4">
            <summary className="cursor-pointer font-semibold">{row.row_id} · {fields.campaign_name || 'Unnamed campaign'} · {row.status === 'preview_ready' ? 'Ready to save as draft' : 'Cannot save this row'}</summary>
            <dl className="my-3 grid gap-2 text-sm md:grid-cols-2">{[
              ['Physical column', column.split('!').pop() || column], ['Template', fields.whatsapp_template_id], ['Sender phone', fields.whatsapp_sender],
              ['Include', fields.segment_name], ['Exclude', fields.exclude_segment_name], ['Planned time', fields.scheduled_at || [fields.send_date, fields.send_time].filter(Boolean).join(' · ')],
              ['Goal', fields.tracking_goal], ['Creative / image', fields.whatsapp_image_url], ['CTA links', fields.whatsapp_cta_links || fields.cta_raw],
              ['Existing CID', fields.existing_campaign_id], ['Existing status', fields.existing_campaign_status], ['Name fallback', fields.whatsapp_name_fallback],
              ['Variable instructions', fields.whatsapp_variable_instructions],
              ['Template body', catalog?.whatsapp_templates?.find((template) => template.id === fields.whatsapp_template_id)?.body],
              ['Resolved placeholders', fields.whatsapp_placeholders],
            ].map(([label, value]) => <div key={label} className="min-w-0"><dt className="font-medium text-gray-500">{label}</dt><dd className="break-words whitespace-pre-wrap [overflow-wrap:anywhere]">{value || '—'}</dd></div>)}</dl>
            {row.issues.length > 0 && <ul className="mb-3 list-inside list-disc text-sm text-red-700">{row.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>}
            {Boolean(row.warnings?.length) && <div className="mb-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-900"><p className="font-semibold">Complete in MoEngage — draft saving is allowed</p><ul className="mt-1 list-inside list-disc">{row.warnings?.map((warning, index) => <li key={index}>{warning}</li>)}</ul></div>}
            <details><summary className="cursor-pointer text-sm font-semibold">Edit campaign details and creative</summary><div className="mt-3 grid gap-3 md:grid-cols-2">
              {editableFields.map((field) => <label key={field} className="block text-xs">{fieldLabels[field]}{field.endsWith('links') || field.endsWith('placeholders') ? ' (JSON)' : ''}
                <textarea className={input} rows={2} value={overrides[column]?.[field] ?? fields[field] ?? ''} onChange={(event) => { const value = event.target.value; invalidate(); setOverrides((old) => ({ ...old, [column]: { ...old[column], [field]: value } })); }} />
              </label>)}
              <div className="space-y-3 rounded-lg border border-gray-200 p-3 text-sm md:col-span-2">
                <p className="font-semibold">Explicit creative upload / Drive resolution</p>
                <p className="text-xs text-gray-600">Uploads only image media to MoEngage, never a campaign. A successful upload replaces this column’s image override with a durable CDN URL and requires a fresh preview.</p>
                <label className="block text-xs">Choose JPG or PNG<input className={input} type="file" accept=".jpg,.jpeg,.png,image/jpeg,image/png" onChange={(event) => { invalidate(); const chosen = event.target.files?.[0]; setImageFiles((old) => ({ ...old, [column]: chosen })); }} /></label>
                <button type="button" className={button} disabled={!brand || !imageFiles[column]} onClick={() => void uploadCreative(column, { file: imageFiles[column] })}>Upload selected image</button>
                <p className="break-all text-xs">Current image / Drive URL: {creativeUrl || 'Not set — enter a Drive file or folder URL in Image or Drive URL above.'}</p>
                <button type="button" className={button} disabled={!brand || !creativeUrl} onClick={() => void uploadCreative(column, { drive_url: creativeUrl })}>Resolve Drive creative</button>
                {showChoices && <div className="space-y-2">
                  <label className="block text-xs">Choose the exact Drive file<select className={input} value={selectedDriveFiles[column] || ''} onChange={(event) => { invalidate(); const id = event.target.value; setSelectedDriveFiles((old) => ({ ...old, [column]: id })); }}>
                    <option value="">Select a creative — no default</option>
                    {choices.files.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.mime_type} · {item.id}</option>)}
                  </select></label>
                  <button type="button" className={button} disabled={!selectedDriveFiles[column] || !choices.files.some((item) => item.id === selectedDriveFiles[column])} onClick={() => void uploadCreative(column, { drive_url: `https://drive.google.com/file/d/${encodeURIComponent(selectedDriveFiles[column])}/view` })}>Upload chosen Drive creative</button>
                </div>}
              </div>
            </div></details>
            <details className="mt-3"><summary className="cursor-pointer text-sm">Resolved creative and draft payload</summary><pre className="overflow-auto bg-gray-50 p-3 text-xs">{JSON.stringify(row.candidate_v5_payload, null, 2)}</pre></details>
          </details>;
        })}
        <label className="flex gap-2 text-sm"><input type="checkbox" disabled={previewRevision.current !== revision.current} checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} />I reviewed the supplied content. Save ready rows as new drafts; I will complete unfinished settings directly in MoEngage.</label>
        <button type="button" className={button} disabled={!canStage} onClick={() => void run('Staging reviewed preview', async (version) => {
          if (!preview?.source_digest || !canStage) return;
          const result = validateBatch(await stageApparelWhatsAppBrief(source, { ...options, expected_source_digest: preview.source_digest }));
          if (!current(version)) return;
          if (!result.items.length || !result.ready || result.items.some((row) => row.campaign_id)) throw new Error('No ready drafts in this batch. Review a fresh preview before creating.');
          setBatch(result); setConfirmed(false); setHalted(false); localStorage.setItem(storageKey, result.batch_id);
        })}>Stage current reviewed preview</button>
      </fieldset>
    </section>}
    {brand && <section ref={batchRef} tabIndex={-1} aria-labelledby="saved-batch-heading" className={`${panel} scroll-mt-40 space-y-4 outline-none`}>
      <h2 id="saved-batch-heading" className="text-base font-semibold">{batch ? '4. Save and verify drafts' : 'Resume previous work'}</h2>
      <button type="button" className={button} disabled={Boolean(busy) || !brand || catalog?.brand !== brand} onClick={() => void loadOwnBatch()}>Read my saved Apparel batch</button>
      {!batch && <p className="text-sm text-gray-500">Already staged a batch? Select its brand above, then restore it here. This only reads saved work; it does not create a campaign.</p>}
      {batch && <>
        <p className="text-sm font-semibold">{batch.items.length} campaigns · {brand} · {catalog?.workspace_name}</p>
        <details className="text-xs text-gray-500"><summary className="cursor-pointer">Batch verification details</summary><p className="mt-2 break-all">Batch: {batch.batch_id} · Account: {batch.account} · Workspace: {batch.workspace_id}</p></details>
        {allVerified && <p role="status" className="rounded-lg bg-emerald-50 p-4 text-sm font-semibold text-emerald-800">All {batch.items.length} drafts are saved and verified in MoEngage. Nothing was published, sent or activated.</p>}
        {halted && <p role="alert" className="text-sm text-amber-800">Creation stopped after an uncertain or unknown result. Reconcile with MoEngage before any further action. Reading the batch does not retry creation.</p>}
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th className="p-2">Column / campaign</th><th className="p-2">Status / issues</th><th className="p-2">Real campaign ID</th><th className="p-2">Readback</th></tr></thead><tbody>{batch.items.map((row) => <tr key={row.row_id} className="border-t">
          <td className="p-2">{row.row_id}<br />{row.source_fields?.campaign_name}</td><td className="p-2">{row.status}<br />{row.issue || row.issues.join('; ')}{Boolean(row.warnings?.length) && <p className="mt-1 text-amber-800">Complete in MoEngage: {row.warnings?.join('; ')}</p>}</td><td className="break-all p-2">{row.campaign_id || '—'}</td>
          <td className="p-2">{row.status === 'CREATED' && row.campaign_id && <button type="button" className={button} disabled={Boolean(busy)} onClick={() => void run('Rechecking saved draft read-only', async (version) => {
            const result = validateBatch(await createMoEngageDraftRow(batch.batch_id, row.row_id, 'apparel'), batch.batch_id);
            if (!current(version)) return;
            setBatch(result);
            const saved = result.items.find((item) => item.row_id === row.row_id);
            if (saved && complete(saved)) localStorage.removeItem(marker(batch.batch_id, row.row_id));
            setHalted(result.items.some((item) => ['UNCERTAIN', 'UNKNOWN', 'MAYBE_SENT'].includes(item.status) || localStorage.getItem(marker(batch.batch_id, item.row_id)) === '1'));
            setConfirmed(false);
            setNotice('Saved draft readback completed; no new draft was requested.');
          })}>Recheck saved draft only</button>}{['UNCERTAIN', 'UNKNOWN', 'MAYBE_SENT'].includes(row.status) && <div className="space-y-1">
            <button type="button" className={button} disabled={Boolean(busy)} onClick={() => void reconcileRow(row)}>Check MoEngage for this draft</button>
            <p className="text-xs text-gray-500">Read-only check. No new draft request.</p>
          </div>}</td>
        </tr>)}</tbody></table></div>
        {!allVerified && <><label className="flex items-start gap-2 text-sm"><input type="checkbox" disabled={Boolean(busy) || halted || !readyRows} checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />I authorise saving only the {readyRows} ready WhatsApp drafts. Nothing may be published, sent, activated or created as SMS fallback.</label>
        <button type="button" className={`${button} bg-blue-600 text-white`} disabled={Boolean(busy) || !confirmed || halted || !readyRows} onClick={() => void createReady()}>Save {readyRows} drafts to MoEngage</button></>}
      </>}
    </section>}
  </div>;
}
