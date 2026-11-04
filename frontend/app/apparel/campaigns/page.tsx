'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { useApp } from '@/lib/context';
import { canUseApparelAttribution } from '@/lib/apparel-attribution';
import {
  fetchApparelWhatsAppCatalog, previewApparelWhatsAppBrief, stageApparelWhatsAppBrief,
  fetchMoEngageDraftBatch, createMoEngageDraftRow, uploadApparelWhatsAppImage, MoEngageDraftRequestError,
  type ApparelWhatsAppCatalog, type ApparelWhatsAppOptions, type ApparelWhatsAppImageResult,
  type MoEngageDraftPreview, type MoEngageDraftBatch, type MoEngageDraftRow,
} from '@/lib/api';

const panel = 'rounded-xl border border-gray-200 bg-white p-5 shadow-sm';
const input = 'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm disabled:bg-gray-50';
const button = 'rounded-lg border border-gray-300 px-4 py-2 text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed';
const editableFields = ['campaign_name', 'segment_name', 'exclude_segment_name', 'scheduled_at', 'whatsapp_template_id', 'whatsapp_placeholders', 'whatsapp_image_url', 'whatsapp_cta_links'] as const;
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
  const [copyExisting, setCopyExisting] = useState(false);
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
  const revision = useRef(0);
  const previewRevision = useRef(-1);
  const alive = useRef(true);
  const pending = useRef(false);
  const storageKey = `apparel_whatsapp_batch:${userId}:apparel`;
  const marker = (batchId: string, rowId: string) => `${storageKey}:uncertain:${batchId}:${rowId}`;
  const noGoals = ['CROCS', 'AGIPL', 'RB_IN', 'CK'].includes(brand.toUpperCase()) || Boolean(catalog?.brands.find((item) => item.brand === brand)?.no_goals);
  const source = sourceType === 'file' ? { file } : { spreadsheet_url: sheet.trim() };
  const options: ApparelWhatsAppOptions = {
    brand, columns: columns.trim() ? columns.toUpperCase().split(/[\s,]+/).filter(Boolean) : undefined,
    reference_campaign_id: noGoals ? undefined : reference || undefined,
    name_attribute: nameAttribute || undefined, allow_existing_campaign_copy: copyExisting, overrides,
  };
  const invalidate = () => {
    revision.current += 1;
    setReviewed(false); setBatch(null); setConfirmed(false); setHalted(false); setError(''); setNotice('');
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
  }, [brand, reference]);

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
  const readyForPreview = Boolean(brand && catalog && catalog.brand === brand && (sourceType === 'file' ? file : sheet.trim()));
  const canStage = reviewed && previewRevision.current === revision.current && preview?.catalog_verified && preview.blocked === 0 && preview.ready > 0 && Boolean(preview.source_digest);

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

  async function createReady() {
    if (!batch || !confirmed || halted || batch.blocked > 0) return;
    const snapshot = batch;
    await run('Creating drafts sequentially', async (version) => {
      let latest = validateBatch(await fetchMoEngageDraftBatch(snapshot.batch_id, 'apparel'), snapshot.batch_id);
      if (!current(version)) return;
      setBatch(latest);
      if (latest.blocked > 0 || latest.items.some((row) => !complete(row) && (row.status !== 'preview_ready' || row.issues.length > 0))) throw new Error('Batch contains blocked or ambiguous rows. Review a fresh preview.');
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
          if (!returned || !complete(returned)) throw new Error(`${row.row_id}: ${returned?.status || 'unknown result'}. Stopped; no automatic POST retry.`);
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

  return <div className="mx-auto max-w-7xl space-y-5 p-4 md:p-8">
    <header><h1 className="text-2xl font-bold text-gray-900">Apparel · WhatsApp draft campaigns</h1>
      <p className="mt-2 text-sm text-gray-600">One-time drafts only. No publish, send, schedule activation, or SMS fallback creation. Planned times are draft metadata.</p>
      <p className="mt-2 text-sm text-gray-600">Goal tracking uses elapsed end − start days, relative to delivery, not inclusive calendar dates. Existing per-brand conversion goals are retained. Crocs, AGIPL, RB_IN and CK have no goals.</p>
    </header>
    {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</div>}
    {notice && <div role="status" className="rounded-lg bg-green-50 p-4 text-sm text-green-800">{notice}</div>}
    {busy && <p role="status" className="text-sm text-blue-700">{busy}…</p>}
    <fieldset disabled={Boolean(busy)} className={`${panel} space-y-4`}>
      <legend className="font-semibold">1. Brand and verified reference</legend>
      <label className="block text-sm">Brand<select className={input} value={brand} onChange={(event) => {
        const nextBrand = event.target.value;
        invalidate(); setBrand(nextBrand); setReference(''); setNameAttribute(''); setOverrides({}); setImageFiles({}); setDriveChoices({}); setSelectedDriveFiles({}); setCatalog(null); setPreview(null);
        const found = brands.find((item) => item.brand === nextBrand);
        if (found?.spreadsheet_url) { setSheet(found.spreadsheet_url); setSourceType('sheet'); }
      }}>
        <option value="">Select brand</option>{brands.map((item) => <option key={item.brand} value={item.brand}>{item.brand} · {item.workspace_name}</option>)}
      </select></label>
      {brand && <p className="text-sm">Workspace: {catalog?.workspace_name || catalog?.workspace_id || 'Loading…'}</p>}
      {brand && !noGoals && <label className="block text-sm">Existing campaign goal reference<select className={input} value={reference} onChange={(event) => { invalidate(); setReference(event.target.value); }}>
        <option value="">Select existing per-brand goal reference</option>{catalog?.reference_campaigns?.filter((item) => item.has_goals).map((item) => <option key={item.id} value={item.id}>{item.name} · {item.id} · {item.status}</option>)}
      </select></label>}
      {noGoals ? <p className="text-sm">This brand has no conversion goals. No goal configuration will be created.</p> : catalog?.goal_reference && <div className="text-sm"><p>Fetched conversion: {catalog.goal_reference.name} ({catalog.goal_reference.id})</p><pre className="mt-2 overflow-auto rounded bg-gray-50 p-3 text-xs">{JSON.stringify(catalog.goal_reference.conversion, null, 2)}</pre></div>}
      <label className="block text-sm">Real user name attribute<select className={input} value={nameAttribute} onChange={(event) => { invalidate(); setNameAttribute(event.target.value); }}>
        <option value="">Select a verified user attribute if personalization requires it</option>{catalog?.user_attributes?.map((attribute) => <option key={attribute} value={attribute}>{attribute}</option>)}
      </select></label>
    </fieldset>
    <fieldset disabled={Boolean(busy)} className={`${panel} space-y-4`}>
      <legend className="font-semibold">2. Source and options</legend>
      <label className="block text-sm">Source<select className={input} value={sourceType} onChange={(event) => { invalidate(); setSourceType(event.target.value); }}><option value="file">XLSX / CSV upload</option><option value="sheet">Google Sheet URL</option></select></label>
      {sourceType === 'file' ? <label className="block text-sm">Brief file<input className={input} type="file" accept=".xlsx,.csv" onChange={(event) => { invalidate(); setFile(event.target.files?.[0]); }} /></label> : <>
        <label className="block text-sm">Google Sheet URL<input className={input} type="url" value={sheet} onChange={(event) => { invalidate(); setSheet(event.target.value); }} /></label>
        <p className="text-sm text-gray-600">Share the Google Sheet with Viewer access to {catalog?.google_service_account_email ? <strong>{catalog.google_service_account_email}</strong> : 'the configured Google service account (ask your administrator for its address)'}. Do not make the sheet public.</p>
      </>}
      <label className="block text-sm">Optional physical campaign columns (for example ON, OO, OP, OQ)<input className={input} value={columns} onChange={(event) => { invalidate(); setColumns(event.target.value); }} placeholder="Blank selects detected campaign columns" /></label>
      <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={copyExisting} onChange={(event) => { invalidate(); setCopyExisting(event.target.checked); }} />Allow an explicit copy when a source column already has an existing campaign ID. Off by default.</label>
      <button type="button" className={`${button} bg-blue-600 text-white`} disabled={!readyForPreview} onClick={() => void run('Previewing brief', async (version) => {
        setReviewed(false); setBatch(null); setConfirmed(false);
        previewRevision.current = -1;
        const result = await previewApparelWhatsAppBrief(source, options);
        if (!current(version)) return;
        if (result.account !== 'apparel' || !isSelectedBrand(result.items) || !result.source_digest) throw new Error('Preview account, workspace or source digest is invalid.');
        previewRevision.current = version; setPreview(result); setHalted(false);
      })}>Preview current source</button>
    </fieldset>
    {preview && <section className={`${panel} space-y-4`}>
      <h2 className="font-semibold">3. Review every physical column</h2>
      <p className="break-all text-xs text-gray-500">Source digest: {preview.source_digest}</p>
      <p className="text-sm">Ready: {preview.ready} · Blocked: {preview.blocked} · Catalog verified: {String(preview.catalog_verified)}</p>
      {previewRevision.current !== revision.current && <p className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm font-semibold text-amber-900" role="status">This preview is out of date. Run Preview current source again before reviewing or staging.</p>}
      <p className="text-sm text-amber-800">Edits invalidate this preview and any staged batch. Preview again after resolving issues; no blocked or ambiguous input can auto-create.</p>
      <fieldset disabled={Boolean(busy)} className="space-y-4">
        {preview.items.map((row) => {
          const column = row.row_id;
          const fields = row.source_fields || {};
          const creativeUrl = overrides[column]?.whatsapp_image_url ?? fields.whatsapp_image_url ?? '';
          const choices = driveChoices[column];
          const showChoices = choices?.brand === brand && choices.source === creativeUrl;
          return <details key={`${row.source_ref}:${row.row_id}`} open className="rounded-lg border border-gray-200 p-4">
            <summary className="cursor-pointer font-semibold">{row.row_id} · {fields.campaign_name || 'Unnamed campaign'} · {row.status}</summary>
            <dl className="my-3 grid gap-2 text-sm md:grid-cols-2">{[
              ['Physical column', column.split('!').pop() || column], ['Template', fields.whatsapp_template_id], ['Sender phone', fields.whatsapp_sender],
              ['Include', fields.segment_name], ['Exclude', fields.exclude_segment_name], ['Planned time', fields.scheduled_at],
              ['Goal', fields.tracking_goal], ['Creative / image', fields.whatsapp_image_url], ['CTA links', fields.whatsapp_cta_links],
              ['Existing CID', fields.existing_campaign_id], ['Existing status', fields.existing_campaign_status], ['Name fallback', fields.whatsapp_name_fallback],
              ['Variable instructions', fields.whatsapp_variable_instructions],
              ['Template body', catalog?.whatsapp_templates?.find((template) => template.id === fields.whatsapp_template_id)?.body],
              ['Resolved placeholders', fields.whatsapp_placeholders],
            ].map(([label, value]) => <div key={label}><dt className="font-medium text-gray-500">{label}</dt><dd className="break-all whitespace-pre-wrap">{value || '—'}</dd></div>)}</dl>
            {row.issues.length > 0 && <ul className="mb-3 list-inside list-disc text-sm text-red-700">{row.issues.map((issue, index) => <li key={index}>{issue}</li>)}</ul>}
            <details><summary className="cursor-pointer text-sm font-semibold">Resolve this column with string overrides</summary><div className="mt-3 grid gap-3 md:grid-cols-2">
              {editableFields.map((field) => <label key={field} className="block text-xs">{field}{field.endsWith('links') || field.endsWith('placeholders') ? ' (JSON)' : ''}
                <textarea className={input} rows={2} value={overrides[column]?.[field] ?? fields[field] ?? ''} onChange={(event) => { const value = event.target.value; invalidate(); setOverrides((old) => ({ ...old, [column]: { ...old[column], [field]: value } })); }} />
              </label>)}
              <div className="space-y-3 rounded-lg border border-gray-200 p-3 text-sm md:col-span-2">
                <p className="font-semibold">Explicit creative upload / Drive resolution</p>
                <p className="text-xs text-gray-600">Uploads only image media to MoEngage, never a campaign. A successful upload replaces this column’s image override with a durable CDN URL and requires a fresh preview.</p>
                <label className="block text-xs">Choose JPG or PNG<input className={input} type="file" accept=".jpg,.jpeg,.png,image/jpeg,image/png" onChange={(event) => { invalidate(); const chosen = event.target.files?.[0]; setImageFiles((old) => ({ ...old, [column]: chosen })); }} /></label>
                <button type="button" className={button} disabled={!brand || !imageFiles[column]} onClick={() => void uploadCreative(column, { file: imageFiles[column] })}>Upload selected image</button>
                <p className="break-all text-xs">Current image / Drive URL: {creativeUrl || 'Not set — enter a Drive file or folder URL in whatsapp_image_url above.'}</p>
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
        <label className="flex gap-2 text-sm"><input type="checkbox" disabled={previewRevision.current !== revision.current} checked={reviewed} onChange={(event) => setReviewed(event.target.checked)} />I reviewed this current preview, including sender, template, audiences, planned time, creative, CTA links, goals and existing IDs.</label>
        <button type="button" className={button} disabled={!canStage} onClick={() => void run('Staging reviewed preview', async (version) => {
          if (!preview?.source_digest || !canStage) return;
          const result = validateBatch(await stageApparelWhatsAppBrief(source, { ...options, expected_source_digest: preview.source_digest }));
          if (!current(version)) return;
          if (result.blocked || !result.items.length || result.items.some((row) => row.status !== 'preview_ready' || row.issues.length || row.campaign_id)) throw new Error('Staged batch is not fully ready. Review a fresh preview before creating.');
          setBatch(result); setConfirmed(false); setHalted(false); localStorage.setItem(storageKey, result.batch_id);
        })}>Stage current reviewed preview</button>
      </fieldset>
    </section>}
    <section className={`${panel} space-y-4`}>
      <h2 className="font-semibold">4. Stored batch and explicit draft creation</h2>
      <button type="button" className={button} disabled={Boolean(busy) || !brand || catalog?.brand !== brand} onClick={() => void loadOwnBatch()}>Read my saved Apparel batch</button>
      {batch && <>
        <p className="break-all text-sm">Batch: {batch.batch_id} · Account: {batch.account} · Workspace: {batch.workspace_id}</p>
        {halted && <p role="alert" className="text-sm text-amber-800">Creation stopped after an uncertain or unknown result. Reconcile with MoEngage before any further action. Reading the batch does not retry creation.</p>}
        <div className="overflow-x-auto"><table className="w-full text-left text-sm"><thead><tr><th className="p-2">Column / campaign</th><th className="p-2">Status / issues</th><th className="p-2">Real campaign ID</th><th className="p-2">Readback</th></tr></thead><tbody>{batch.items.map((row) => <tr key={row.row_id} className="border-t">
          <td className="p-2">{row.row_id}<br />{row.source_fields?.campaign_name}</td><td className="p-2">{row.status}<br />{row.issue || row.issues.join('; ')}</td><td className="break-all p-2">{row.campaign_id || '—'}</td>
          <td className="p-2">{row.status === 'CREATED' && row.campaign_id && <button type="button" className={button} disabled={Boolean(busy)} onClick={() => void run('Rechecking saved draft read-only', async (version) => {
            const result = validateBatch(await createMoEngageDraftRow(batch.batch_id, row.row_id, 'apparel'), batch.batch_id);
            if (!current(version)) return;
            setBatch(result);
            const saved = result.items.find((item) => item.row_id === row.row_id);
            if (saved && complete(saved)) localStorage.removeItem(marker(batch.batch_id, row.row_id));
            setHalted(result.items.some((item) => ['UNCERTAIN', 'UNKNOWN', 'MAYBE_SENT'].includes(item.status) || localStorage.getItem(marker(batch.batch_id, item.row_id)) === '1'));
            setConfirmed(false);
            setNotice('Saved draft readback completed; no new draft was requested.');
          })}>Recheck saved draft only</button>}</td>
        </tr>)}</tbody></table></div>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" disabled={Boolean(busy) || halted} checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />I explicitly authorise creating only the ready WhatsApp drafts in this batch. Nothing may be published, sent, activated, or created as SMS fallback.</label>
        <button type="button" className={`${button} bg-blue-600 text-white`} disabled={Boolean(busy) || !confirmed || halted || batch.blocked > 0 || !batch.items.some((row) => row.status === 'preview_ready' && !row.campaign_id && row.issues.length === 0)} onClick={() => void createReady()}>Create ready drafts sequentially</button>
      </>}
    </section>
  </div>;
}
