'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/navigation';
import { canUseApparelAttribution } from '@/lib/apparel-attribution';
import { clearTabState, setTabState, useTabState } from '@/lib/tab-state';
import { useApp } from '@/lib/context';
import {
  MoEngageDraftRequestError,
  createMoEngageDraftRow,
  fetchMoEngageCatalog,
  fetchMoEngageDraftWorkspaces,
  fetchMoEngageDraftBatch,
  previewMoEngageDraftFile,
  removeMoEngageDraftBatch,
  stageMoEngageDraftBatch,
} from '@/lib/api';
import type {
  MoEngageCatalog,
  MoEngageDraftBatch,
  MoEngageDraftPreview,
  MoEngageDraftRow,
} from '@/lib/api';
import { TATA_CTA_URL, resolveCtaUrl } from '@/lib/cta';
import { CAMPAIGN_NAME_HINT, CAMPAIGN_NAME_RULE, campaignRowName, normalizeCampaignName, requireCampaignName } from '@/lib/campaign-name';

const MAX_FILE_BYTES = 5 * 1024 * 1024;
function isCompletedDraft(row: MoEngageDraftRow): boolean {
  return Boolean(row.campaign_id && /^[a-f0-9]{24}$/i.test(row.campaign_id)) &&
    (row.channel?.toUpperCase() === 'WHATSAPP' ? row.status === 'VERIFIED' : row.status === 'VALIDATED');
}


function validationMessages(value: unknown): string[] {
  if (!value) return [];
  if (Array.isArray(value)) {
    return value.map((entry) => {
      if (typeof entry === 'string') return entry;
      if (entry && typeof entry === 'object') {
        const item = entry as { field?: string; issue?: string };
        if (item.field || item.issue) return [item.field, item.issue].filter(Boolean).join(': ');
      }
      return JSON.stringify(entry);
    });
  }
  return [typeof value === 'string' ? value : JSON.stringify(value)];
}

function RowCard({
  row,
  batch,
  busy,
  uncertain,
  onCreate,
  templateBody,
}: {
  row: MoEngageDraftRow;
  batch: boolean;
  busy: boolean;
  uncertain: boolean;
  onCreate: (row: MoEngageDraftRow) => void;
  templateBody?: string;
}) {
  const candidate = row.candidate_v5_payload;
  const source = row.source_fields || {};
  const content = candidate?.campaign_content?.content;
  const email = content?.email;
  const whatsapp = content?.whatsapp;
  const push = content?.push ? Object.values(content.push)[0]?.basic_details : undefined;
  const segment = candidate?.segmentation_details?.included_filters?.filters?.[0];
  const schedule = candidate?.scheduling_details;
  const issues = [...(row.issues || []), ...(row.issue ? [row.issue] : []), ...validationMessages(row.validation_errors)];
  const status = row.status || 'blocked';
  const ready = status === 'preview_ready';
  const verified = isCompletedDraft(row);
  const isWhatsApp = row.channel?.toUpperCase() === 'WHATSAPP';
  const isEmail = row.channel?.toUpperCase() === 'EMAIL';
  const isPush = row.channel?.toUpperCase() === 'PUSH';
  const message = source['Message Body'] || source.whatsapp_message || source.body || source.message ||
    templateBody?.replace(/\{\{\d+\}\}/g, (slot) => whatsapp?.body_placeholders?.[slot] || whatsapp?.body_placeholders?.[slot.slice(2, -2)] || slot);

  return (
    <article className="workspace-panel min-w-0 space-y-4 p-5 sm:p-6">
      <div className="flex flex-wrap justify-between items-start gap-3">
        <div className="min-w-0">
          <h3 className="break-words text-base font-medium text-gray-900 [overflow-wrap:anywhere]">
            {campaignRowName(row) || 'Campaign name missing'}
          </h3>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs font-medium">
          <span className="font-mono text-xs font-normal text-gray-600">
            {row.channel || 'UNKNOWN'}
          </span>
          <span
            className={`rounded-md px-2.5 py-1 ${
              verified
                ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
                : ready
                ? 'bg-amber-50 text-amber-800 border border-amber-200'
                : 'bg-gray-100 text-gray-700'
            }`}
          >
            {batch ? 'Status: ' : 'Preview: '}
            {status}
          </span>
        </div>
      </div>
      <p className="text-sm text-gray-600">
        {row.workspace_name || source.workspace_name || source.workspace || 'Destination needs review'}
        {' · '}{segment?.name || source.segment_name || 'Audience needs review'}
      </p>
      <div className="rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm leading-relaxed whitespace-pre-wrap [overflow-wrap:anywhere]">
        {message || push?.message ||
          (isWhatsApp ? `Template: ${whatsapp?.template_name || source.whatsapp_template_name || source.whatsapp_template_id || 'Not selected'}. Message preview unavailable; review the template in MoEngage.` : email?.subject || 'No message preview supplied.')}
      </div>
      {verified && <p className="text-sm font-medium text-emerald-800">Draft saved and verified. Not published or sent.</p>}
      <details className="text-sm">
        <summary className="cursor-pointer font-medium text-gray-600">Details — source, IDs and configuration</summary>
        <p className="mt-3 break-all font-mono text-xs leading-relaxed text-gray-600">{row.source_ref} · Row {row.row_id} · Workspace {row.workspace_id}</p>

      {batch && row.updated_at && (
        <p className="mt-2 text-sm text-gray-600">
          Last updated: {new Date(row.updated_at * 1000).toLocaleString(undefined, { timeZone: 'UTC', timeZoneName: 'short' })}. Stored draft record; no customer messages sent.
        </p>
      )}

      <dl className="mt-4 grid gap-4 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs font-medium text-gray-500">Target audience</dt>
          <dd className="text-gray-900 mt-0.5 break-all">
            {segment ? (
              <span className="inline-flex items-center gap-1 font-medium">
                {segment.name || 'Custom segment'}
                <span className="text-xs text-gray-500 font-mono">({segment.id})</span>
              </span>
            ) : (
              source.segment_name || source.segment_id || 'Not supplied'
            )}
          </dd>
        </div>

        <div>
          <dt className="text-xs font-medium text-gray-500">{isWhatsApp ? 'Planned time and timezone — confirm in MoEngage' : 'Schedule and timezone'}</dt>
          <dd className="text-gray-900 mt-0.5">
            {schedule?.start_time || [source.scheduled_at, source.timezone].filter(Boolean).join(' · ') || 'Not supplied'}
            {schedule?.timezone ? ` (${schedule.timezone})` : ''}
          </dd>
        </div>

        {isEmail && (
          <>
            <div>
              <dt className="text-xs font-medium text-gray-500">Email sender and subject</dt>
              <dd className="text-gray-900 mt-0.5 break-words">
                {source.from_address || email?.from_address || 'Not set'}
                <span className="text-gray-500"> · </span>
                <span className="font-medium">{source.subject || email?.subject || 'No subject'}</span>
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-gray-500">Content type and connector</dt>
              <dd className="text-gray-900 mt-0.5">
                {source.content_type || candidate?.basic_details?.content_type || 'PROMOTIONAL'}
                {candidate?.connector?.connector_type ? ` · ${candidate.connector.connector_type} (${candidate.connector.connector_name || 'default'})` : ''}
              </dd>
            </div>
            {(source.html_content || email?.html_content) && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-gray-500 mb-1">Email HTML content</dt>
                <dd className="rounded-lg bg-gray-50 border border-gray-200 p-3 font-mono text-xs max-h-36 overflow-auto text-gray-800 whitespace-pre-wrap">
                  {source.html_content || email?.html_content}
                </dd>
              </div>
            )}
          </>
        )}

        {isPush && (
          <>
            <div>
              <dt className="text-xs font-medium text-gray-500">Push title and platform</dt>
              <dd className="text-gray-900 mt-0.5 font-medium">
                {source.push_title || push?.title || 'Not set'}
                <span className="text-xs font-normal text-gray-500 ml-1">
                  ({source.push_platform || candidate?.basic_details?.platforms?.join(', ') || 'ANDROID'})
                </span>
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-gray-500">Click URL / deeplink</dt>
              <dd className="text-gray-900 mt-0.5 break-all text-xs font-mono text-gray-700">
                {push?.default_click_action_value || source.click_url || 'Not set'}
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-xs font-medium text-gray-500">Push notification body</dt>
              <dd className="mt-1 whitespace-pre-wrap rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm text-gray-900 [overflow-wrap:anywhere]">
                {source.push_message || push?.message || 'Not set'}
              </dd>
            </div>
          </>
        )}

        {isWhatsApp && (
          <>
            <div>
              <dt className="text-xs font-medium text-gray-500">WhatsApp sender</dt>
              <dd className="text-gray-900 mt-0.5 font-medium">
                {whatsapp?.sender_name || source.whatsapp_sender || source.whatsapp_sender_id || 'Not supplied'}
                {whatsapp?.sender_id && <span className="block text-xs font-mono font-normal">{whatsapp.sender_id}{whatsapp.provider ? ` · ${whatsapp.provider}` : ''}</span>}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-gray-500">WhatsApp template</dt>
              <dd className="text-gray-900 mt-0.5 font-medium flex flex-wrap items-center gap-1.5">
                <span>{whatsapp?.template_name || source.whatsapp_template_name || source.whatsapp_template_id || 'Not supplied'}</span>
                {(whatsapp?.template_id || source.matched_template_id) && (
                  <span className="text-xs font-mono text-gray-500">({whatsapp?.template_id || source.matched_template_id})</span>
                )}
                {source.matched_template_confidence && (
                  <span className="text-xs font-medium font-mono text-gray-600">
                    {source.matched_template_confidence} Match
                  </span>
                )}
              </dd>
            </div>
            {whatsapp?.body_placeholders && Object.keys(whatsapp.body_placeholders).length > 0 && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-gray-500">Template variables</dt>
                <dd className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm space-y-2">
                  {Object.entries(whatsapp.body_placeholders).map(([slot, value]) => (
                    <div key={slot} className="whitespace-pre-wrap break-words">
                      <code className="text-xs font-medium">{slot}</code>: {value}
                    </div>
                  ))}
                </dd>
              </div>
            )}
          </>
        )}
      </dl>
      {row.campaign_id && (
        <div
          className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-200 pt-4 text-sm"
        >
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">
                Reported MoEngage campaign ID
              </span>
              <code className="break-all font-mono text-xs font-normal text-gray-900">
                {row.campaign_id}
              </code>
            </div>
            <p className="mt-2 max-w-xl text-sm leading-relaxed text-gray-600">
              {verified
                ? 'Draft read-back completed. Review in MoEngage before any human publish action.'
                : `State: ${status}. This ID alone does not confirm a verified draft. Review the issues and reconcile in MoEngage before taking further action.`}
            </p>
          </div>
        </div>
      )}
      </details>

      {issues.length > 0 && (
        <div className="rounded-lg bg-rose-50 border border-rose-200 p-3 text-sm text-rose-900">
          <strong className="block font-medium">Validation issues</strong>
          <ul className="list-disc pl-5 mt-2 space-y-1 text-sm">
            {issues.map((issue, index) => (
              <li key={`${index}-${issue}`}>{issue}</li>
            ))}
          </ul>
        </div>
      )}


      {(uncertain || status === 'UNCERTAIN' || status === 'UNKNOWN') && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm font-medium text-amber-800 bg-amber-50 p-3 rounded-lg border border-amber-200">
          <div>
            <span>Previous attempt was unconfirmed</span>
            <p className="text-sm text-amber-800 font-normal mt-1">
              Refresh stored state and manually reconcile the campaign in MoEngage with an operator. Do not create it again: the previous request may already have saved a draft.
            </p>
          </div>
        </div>
      )}

      {batch && ready && !uncertain && !row.campaign_id && (
        <button
          type="button"
          disabled={busy}
          onClick={() => onCreate(row)}
          className="workspace-button-primary"
        >
          Save this draft…
        </button>
      )}
      {batch && isWhatsApp && status === 'CREATED' && row.campaign_id && /^[a-f0-9]{24}$/i.test(row.campaign_id) && (
        <button
          type="button"
          disabled={busy}
          onClick={() => onCreate(row)}
          className="workspace-button"
        >
          Recheck saved draft…
        </button>
      )}
    </article>
  );
}

export default function MoEngageCampaignsPage() {
  const { account, currentUser, authLoading } = useApp();
  const router = useRouter();
  const apparel = currentUser?.tenant_id === 'apparel' || canUseApparelAttribution(currentUser, account);
  useEffect(() => {
    if (!authLoading && apparel) router.replace('/apparel/campaigns');
  }, [authLoading, apparel, router]);
  if (authLoading || apparel) return <p role="status" className="workspace-page p-6 text-sm text-gray-600">Opening the authorized campaign workspace…</p>;
  return <GeneralCampaignsPage />;
}

function GeneralCampaignsPage() {
  const { currentUser, authLoading } = useApp();
  const superadmin = currentUser?.tenant_id === 'all' && currentUser.role === 'superadmin';
  const [selectedAccount, setSelectedAccount] = useState('tata');
  const account = superadmin ? selectedAccount : currentUser?.tenant_id || '';
  const allowed = !!currentUser && (account === 'tata' || account === 'bajaj') && (superadmin || currentUser.tenant_id === account);

  const [activeTab, setActiveTab] = useState<'batch' | 'single' | 'templates'>('batch');
  const [catalog, setCatalog] = useState<MoEngageCatalog | null>(null);
  const [waWorkspaces, setWaWorkspaces] = useState<{ id: string; name: string }[]>([]);
  const [waWorkspace, setWaWorkspace] = useState('');
  const [waCatalog, setWaCatalog] = useState<MoEngageCatalog | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);

  const [automatingWa, setAutomatingWa] = useState(false);
  // Single form builder state
  const [singleChannel, setSingleChannel] = useTabState<'WHATSAPP' | 'EMAIL' | 'PUSH'>('moe_single_channel', 'WHATSAPP');
  const formCatalog = singleChannel === 'WHATSAPP' ? waCatalog : catalog;
  const [singleName, setSingleName] = useTabState<string>('moe_single_name', '');
  const [singleSegment, setSingleSegment] = useTabState<string>('moe_single_segment', '');
  const [singleDate, setSingleDate] = useTabState<string>('moe_single_date', '');
  const [singleTimezone, setSingleTimezone] = useTabState<string>('moe_single_timezone', 'Asia/Kolkata');
  // Email fields
  const [singleEmailSender, setSingleEmailSender] = useTabState<string>('moe_single_email_sender', '');
  const [singleSubject, setSingleSubject] = useTabState<string>('moe_single_subject', '');
  const [singleHtml, setSingleHtml] = useTabState<string>('moe_single_html', '<p>Special festive offer for valued customers. Do not publish.</p>');
  const [singleContentType, setSingleContentType] = useTabState<string>('moe_single_content_type', 'PROMOTIONAL');
  // Push fields
  const [singlePushPlatform, setSinglePushPlatform] = useTabState<string>('moe_single_push_platform', 'ANDROID');
  const [singlePushTitle, setSinglePushTitle] = useTabState<string>('moe_single_push_title', '');
  const [singlePushMessage, setSinglePushMessage] = useTabState<string>('moe_single_push_message', '');
  const [singleClickUrl, setSingleClickUrl] = useTabState<string>('moe_single_click_url', TATA_CTA_URL);
  // WhatsApp fields
  const [singleWaSender, setSingleWaSender] = useTabState<string>('moe_single_wa_sender', '');
  const [singleWaTemplate, setSingleWaTemplate] = useTabState<string>('moe_single_wa_template', '');
  const [singleWaPlaceholders, setSingleWaPlaceholders] = useState<Record<string, string>>({});
  const selectedWaSender = waCatalog?.workspace_id === waWorkspace
    ? waCatalog.whatsapp_senders?.find((sender) => sender.sender_id === singleWaSender)
    : undefined;
  const selectedWaTemplate = selectedWaSender
    ? waCatalog?.whatsapp_templates?.find((template) => template.id === singleWaTemplate && template.sender_ids.includes(singleWaSender))
    : undefined;
  const selectedWaSlots = [...new Set(
    Array.from((selectedWaTemplate?.body || '').matchAll(/\{\{\d+\}\}/g), (match) => match[0])
  )];
  useEffect(() => {
    setSingleWaPlaceholders({});
  }, [account, waWorkspace, singleWaSender, singleWaTemplate]);
  // Batch & Spreadsheet state
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<MoEngageDraftPreview | null>(null);
  useEffect(() => {
    setTabState('moe_unsaved_preview', Boolean(file || preview));
  }, [file, preview]);
  useEffect(() => () => clearTabState('moe_unsaved_preview'), []);
  const [batch, setBatch] = useState<MoEngageDraftBatch | null>(null);
  const [reviewBodies, setReviewBodies] = useState<Record<string, string>>({});
  useEffect(() => {
    let active = true;
    setReviewBodies({});
    const rows = [...(preview?.account === account ? preview.items : []), ...(batch?.account === account ? batch.items : [])];
    const workspaces = [...new Set(rows.filter(row => row.channel === 'WHATSAPP').map(row => row.workspace_id).filter(Boolean))];
    void Promise.all(workspaces.map(async workspace => {
      try { return await fetchMoEngageCatalog(account, workspace); } catch { return null; }
    })).then(catalogs => {
      if (active) setReviewBodies(Object.fromEntries(catalogs.flatMap(catalog =>
        catalog?.whatsapp_templates?.map(template => [`${catalog.workspace_id}:${template.id}`, template.body || '']) || []
      )));
    });
    return () => { active = false; };
  }, [account, batch?.batch_id, preview]);
  const [batchScope, setBatchScope] = useState('');
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [filterChannel, setFilterChannel] = useState<'ALL' | 'WHATSAPP' | 'EMAIL' | 'PUSH'>('ALL');
  const [uncertainRows, setUncertainRows] = useState<string[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);
  const createInFlight = useRef(false);
  const storageKey = currentUser && allowed ? `moengage_draft_batch:${currentUser.id}:${account}` : '';

  // Load catalog on mount/account change
  useEffect(() => {
    if (!allowed) return;
    let active = true;
    setCatalogLoading(true);
    setCatalog(null);
    setWaWorkspace('');
    setWaCatalog(null);
    setWaWorkspaces([]);
    fetchMoEngageDraftWorkspaces(account).then((result) => {
      if (active) setWaWorkspaces(result.workspaces);
    }).catch((err) => { if (active) setError(String(err)); });
    setSingleSegment('');
    setSingleWaSender('');
    setSingleWaTemplate('');
    fetchMoEngageCatalog(account)
      .then((cat) => {
        if (!active) return;
        setCatalog(cat);
        // Keep audience and WhatsApp selections explicit and scoped to this account.
        if (cat.email_senders?.[0]) setSingleEmailSender(cat.email_senders[0].from_address);
      })
      .catch((err) => {
        if (active) console.warn('Could not load server catalog:', err);
      })
      .finally(() => {
        if (active) setCatalogLoading(false);
      });
    return () => {
      active = false;
    };
  }, [account, allowed]);

  useEffect(() => {
    let active = true;
    setWaCatalog(null);
    setSingleSegment('');
    setSingleWaSender('');
    setSingleWaTemplate('');
    if (allowed && singleChannel === 'WHATSAPP' && waWorkspace) {
      fetchMoEngageCatalog(account, waWorkspace).then((cat) => {
        if (active) setWaCatalog(cat);
      }).catch((err) => { if (active) setError(String(err)); });
    }
    return () => { active = false; };
  }, [account, allowed, singleChannel, waWorkspace]);

  const showBatch = useCallback(
    (result: MoEngageDraftBatch, key: string) => {
      if (result.account !== account) throw new Error('Batch belongs to a different account; it will not be displayed.');
      setBatch(result);
      setBatchScope(key);
      localStorage.setItem(key, result.batch_id);
      const url = new URL(window.location.href);
      url.searchParams.set('batch', result.batch_id);
      url.searchParams.set('account', account);
      window.history.replaceState(null, '', url.toString());
    },
    [account]
  );

  const clearSavedBatch = useCallback((id: string, key: string) => {
    if (localStorage.getItem(key) === id) localStorage.removeItem(key);
    setBatch(null);
    setBatchScope('');
    setPreview(null);
    setFile(null);
    setUncertainRows([]);
    if (fileRef.current) fileRef.current.value = '';
    const url = new URL(window.location.href);
    if (url.searchParams.get('batch') === id && url.searchParams.get('account') === account) {
      url.searchParams.delete('batch');
      window.history.replaceState(null, '', url.toString());
    }
  }, [account]);

  useEffect(() => {
    if (!superadmin) return;
    const requested = new URLSearchParams(window.location.search).get('account');
    if (requested === 'tata' || requested === 'bajaj') setSelectedAccount(requested);
  }, [superadmin]);

  useEffect(() => {
    if (!allowed || !storageKey) return;
    let active = true;
    const query = new URLSearchParams(window.location.search);
    const urlId = query.get('account') === account ? query.get('batch') : null;
    const id = urlId;
    if (!urlId) { setBatch(null); setBatchScope(''); }
    if (!id) return;
    setLoading(true);
    fetchMoEngageDraftBatch(id, account)
      .then((result) => {
        if (active) showBatch(result, storageKey);
      })
      .catch((cause: unknown) => {
        if (!active) return;
        if (cause instanceof MoEngageDraftRequestError && cause.status === 404) {
          clearSavedBatch(id, storageKey);
          setNotice('This saved batch is no longer available. Upload a spreadsheet to begin.');
        } else {
          setError(`Could not open saved batch: ${cause instanceof Error ? cause.message : String(cause)}`);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [account, allowed, storageKey, showBatch, clearSavedBatch]);

  const chooseFile = async (selected: File | undefined) => {
    setFile(null);
    setPreview(null);
    setError('');
    setNotice('');
    if (!selected) return;
    if (!/\.(csv|xlsx)$/i.test(selected.name) || selected.size === 0 || selected.size > MAX_FILE_BYTES) {
      setError('Choose a non-empty .csv or .xlsx file of at most 5 MiB.');
      if (fileRef.current) fileRef.current.value = '';
      return;
    }
    setBusy(true);
    try {
      const result = await previewMoEngageDraftFile(selected, account);
      if (result.account !== account) throw new Error('Preview account mismatch.');
      setFile(selected);
      setPreview(result);
    } catch (cause) {
      setError(`Preview failed: ${cause instanceof Error ? cause.message : String(cause)}`);
      if (fileRef.current) fileRef.current.value = '';
    } finally {
      setBusy(false);
    }
  };

  const stage = async () => {
    if (!file || !preview || !allowed || busy) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await stageMoEngageDraftBatch(file, account);
      showBatch(result, storageKey);
      setNotice('Batch staged successfully. Review the destinations below, then use Save ready WhatsApp drafts sequentially to process the ready rows.');
      setFile(null);
      setPreview(null);
      if (fileRef.current) fileRef.current.value = '';
    } catch (cause) {
      setError(`Staging failed: ${cause instanceof Error ? cause.message : String(cause)}.`);
      setFile(null);
      setPreview(null);
      if (fileRef.current) fileRef.current.value = '';
    } finally {
      setBusy(false);
    }
  };

  const refreshBatch = async () => {
    if (!batch || batchScope !== storageKey || busy) return;
    setBusy(true);
    setError('');
    try {
      showBatch(await fetchMoEngageDraftBatch(batch.batch_id, account), storageKey);
    } catch (cause) {
      if (cause instanceof MoEngageDraftRequestError && cause.status === 404) {
        clearSavedBatch(batch.batch_id, storageKey);
      }
      setError(`Could not read batch: ${cause instanceof Error ? cause.message : String(cause)}`);
    } finally {
      setBusy(false);
    }
  };

  const removeBatch = async () => {
    if (!batch || batchScope !== storageKey || busy || loading || automatingWa || createInFlight.current) return;
    if (!window.confirm(
      `Remove this batch from local app history for ${account.toUpperCase()}?\n\nThis only archives the saved batch in this app. It does not delete, publish, send, or cancel any MoEngage drafts. Audit records and duplicate-prevention reservations are retained; the same source cannot be recreated.`
    )) return;
    createInFlight.current = true;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await removeMoEngageDraftBatch(batch.batch_id, account);
      clearSavedBatch(batch.batch_id, storageKey);
      setNotice('Batch removed from app history. MoEngage drafts were not changed.');
    } catch (cause) {
      setError(`Could not remove batch: ${cause instanceof Error ? cause.message : String(cause)}`);
    } finally {
      createInFlight.current = false;
      setBusy(false);
    }
  };

  const createRow = async (row: MoEngageDraftRow) => {
    if (!batch || batchScope !== storageKey || busy || automatingWa || createInFlight.current) return;
    const readBackOnly = row.channel?.toUpperCase() === 'WHATSAPP' && row.status === 'CREATED' &&
      Boolean(row.campaign_id && /^[a-f0-9]{24}$/i.test(row.campaign_id));
    if (!readBackOnly && (row.status !== 'preview_ready' || row.campaign_id || uncertainRows.includes(row.row_id))) return;

    const name = campaignRowName(row) || 'unnamed campaign';
    const prompt = readBackOnly
      ? `Recheck saved MoEngage draft ${row.campaign_id}?\n\nCampaign: ${name}\n\nThis only reads back the existing draft to verify its configuration and Drafts membership. It will not create another draft, publish or send.`
      : `Request a MoEngage ${row.channel} DRAFT for ${account.toUpperCase()}?\n\nCampaign: ${name}\nPhysical Row: ${row.row_id}\n\nThis requests draft-only creation and read-back. It does not publish or send. Review the returned state before human publishing in MoEngage.`;
    if (!window.confirm(prompt)) return;

    createInFlight.current = true;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      localStorage.setItem(`moengage_draft_uncertain:${currentUser?.id}:${account}:${batch.batch_id}:${row.row_id}`, '1');
      const result = await createMoEngageDraftRow(batch.batch_id, row.row_id, account);
      if (result.batch_id !== batch.batch_id) throw new Error('Returned batch identity does not match the requested batch.');
      showBatch(result, storageKey);
      const returnedRow = result.items.find((item) => item.row_id === row.row_id && item.source_ref === row.source_ref && item.workspace_id === row.workspace_id);
      if (returnedRow && isCompletedDraft(returnedRow)) {
        localStorage.removeItem(`moengage_draft_uncertain:${currentUser?.id}:${account}:${batch.batch_id}:${row.row_id}`);
        setNotice(`Draft ${returnedRow.campaign_id} completed with state ${returnedRow.status}. Human review is required before publishing.`);
      } else {
        if (returnedRow && !['preview_ready', 'UNCERTAIN', 'UNKNOWN', 'MAYBE_SENT'].includes(returnedRow.status)) {
          localStorage.removeItem(`moengage_draft_uncertain:${currentUser?.id}:${account}:${batch.batch_id}:${row.row_id}`);
        } else {
          setUncertainRows((rows) => [...new Set([...rows, row.row_id])]);
        }
        const issues = returnedRow
          ? [...(returnedRow.issues || []), ...(returnedRow.issue ? [returnedRow.issue] : []), ...validationMessages(returnedRow.validation_errors)]
          : ['The requested row was not returned. Refresh stored state and reconcile before any further create.'];
        setError(`Row ${row.row_id}: ${returnedRow?.status || 'unconfirmed'}. ${issues.join('; ') || 'Draft completion has not been confirmed. Review the stored state and reconcile in MoEngage.'}`);
      }
    } catch (cause) {
      const errStr = cause instanceof Error ? cause.message : String(cause);
      const ambiguous = !(cause instanceof MoEngageDraftRequestError) || cause.status >= 500 || cause.status === 408;
      if (ambiguous) {
        const marker = `moengage_draft_uncertain:${currentUser?.id}:${account}:${batch.batch_id}:${row.row_id}`;
        localStorage.setItem(marker, '1');
        setUncertainRows((rows) => [...rows, row.row_id]);
        setError(`Create result uncertain for row ${row.row_id}: ${errStr}. Re-read the batch to confirm state.`);
      } else {
        localStorage.removeItem(`moengage_draft_uncertain:${currentUser?.id}:${account}:${batch.batch_id}:${row.row_id}`);
        setError(`Create failed for row ${row.row_id}: ${errStr}`);
      }
    } finally {
      createInFlight.current = false;
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!batch || !currentUser) return;
    batch.items.forEach((r) => {
      if (isCompletedDraft(r)) {
        localStorage.removeItem(`moengage_draft_uncertain:${currentUser.id}:${account}:${batch.batch_id}:${r.row_id}`);
      }
    });
    setUncertainRows(
      batch.items
        .filter((r) => r.status === 'UNCERTAIN' || r.status === 'UNKNOWN' || localStorage.getItem(`moengage_draft_uncertain:${currentUser.id}:${account}:${batch.batch_id}:${r.row_id}`) === '1')
        .map((r) => r.row_id)
    );
  }, [batch, currentUser, account]);
  const handleAutomateWhatsApp = async () => {
    if (!batch || batchScope !== storageKey || busy || automatingWa || createInFlight.current) return;
    const eligible = (row: MoEngageDraftRow) => row.channel?.toUpperCase() === 'WHATSAPP' &&
      row.status === 'preview_ready' && !row.campaign_id &&
      !uncertainRows.includes(row.row_id) &&
      localStorage.getItem(`moengage_draft_uncertain:${currentUser?.id}:${account}:${batch.batch_id}:${row.row_id}`) !== '1';
    const pendingWa = batch.items.filter(eligible);
    if (!pendingWa.length || !window.confirm(
      `Create up to ${pendingWa.length} ready WhatsApp drafts sequentially for ${account.toUpperCase()}?\n\nEach row uses its explicit destination workspace. Only VERIFIED drafts count as completed. The batch stops on the first HTTP error or unverified result. Remaining rows stay ready for a deliberate resume. No publishing, scheduling sends or customer messages.`
    )) return;

    createInFlight.current = true;
    setBusy(true);
    setAutomatingWa(true);
    setError('');
    setNotice('');
    let verified = 0;
    let attemptedRow: MoEngageDraftRow | null = null;
    try {
      let latest = await fetchMoEngageDraftBatch(batch.batch_id, account);
      showBatch(latest, storageKey);
      for (const row of pendingWa) {
        const current = latest.items.find((item) => item.row_id === row.row_id &&
          item.source_ref === row.source_ref && item.workspace_id === row.workspace_id);
        if (!current || !eligible(current)) continue;
        setNotice(`Creating WhatsApp draft ${verified + 1} of up to ${pendingWa.length} · Row ${row.row_id}. ${verified} verified this run. Results are stored below.`);
        attemptedRow = row;
        const marker = `moengage_draft_uncertain:${currentUser?.id}:${account}:${batch.batch_id}:${row.row_id}`;
        // Persist before writing so reload/navigation cannot silently enable a replay.
        localStorage.setItem(marker, '1');
        latest = await createMoEngageDraftRow(batch.batch_id, row.row_id, account);
        if (latest.batch_id !== batch.batch_id) throw new Error('Returned batch identity does not match the requested batch.');
        showBatch(latest, storageKey);
        const returned = latest.items.find((item) => item.row_id === row.row_id &&
          item.source_ref === row.source_ref && item.workspace_id === row.workspace_id);
        if (!returned || !isCompletedDraft(returned)) {
          if (returned && !['preview_ready', 'UNCERTAIN', 'UNKNOWN', 'MAYBE_SENT'].includes(returned.status)) {
            localStorage.removeItem(marker);
            attemptedRow = null;
          } else {
            setUncertainRows((rows) => [...new Set([...rows, row.row_id])]);
          }
          throw new Error(`Row ${row.row_id} returned ${returned?.status || 'no matching stored result'}. Review this row before continuing; CREATED drafts may be rechecked read-only.`);
        }
        localStorage.removeItem(marker);
        attemptedRow = null;
        verified += 1;
      }
      setNotice(`${verified} WhatsApp drafts VERIFIED this run. Stored results are shown below. No publishing or sending was requested.`);
    } catch (cause) {
      if (attemptedRow && cause instanceof MoEngageDraftRequestError &&
          cause.status < 500 && cause.status !== 408) {
        localStorage.removeItem(`moengage_draft_uncertain:${currentUser?.id}:${account}:${batch.batch_id}:${attemptedRow.row_id}`);
      } else if (attemptedRow) {
        setUncertainRows((rows) => [...new Set([...rows, attemptedRow!.row_id])]);
      }
      setNotice(`${verified} WhatsApp drafts VERIFIED this run before stopping.`);
      setError(`Bulk creation stopped: ${cause instanceof Error ? cause.message : String(cause)}. No later rows were attempted. Refresh stored state; resume ready rows deliberately after resolving the issue.`);
      try {
        showBatch(await fetchMoEngageDraftBatch(batch.batch_id, account), storageKey);
      } catch {
        // Keep the last persisted response and local uncertainty markers visible.
      }
    } finally {
      createInFlight.current = false;
      setBusy(false);
      setAutomatingWa(false);
    }
  };

  const handleCreateFromSingleForm = async () => {
    const campaignName = normalizeCampaignName(singleName);
    setSingleName(campaignName);
    if (busy || !campaignName.slice(4).trim() || !singleSegment) {
      setError(`${CAMPAIGN_NAME_RULE} Target Audience is also required.`);
      return;
    }
    if (singleChannel === 'WHATSAPP' && (!waWorkspace || !waCatalog || waCatalog.workspace_id !== waWorkspace ||
        !waCatalog.segments.some((segment) => segment.id === singleSegment) ||
        !waCatalog.whatsapp_senders?.some((sender) => sender.sender_id === singleWaSender) ||
        !waCatalog.whatsapp_templates?.some((template) => template.id === singleWaTemplate && template.sender_ids.includes(singleWaSender)))) {
      setError('Select a WhatsApp workspace, audience, sender and approved template before staging.');
      return;
    }
    if (!singleDate || (singleChannel === 'WHATSAPP' &&
        selectedWaSlots.some((slot) => !singleWaPlaceholders[slot]?.trim()))) {
      setError('Choose a planning date and fill every required WhatsApp template variable.');
      return;
    }

    // Build a CSV file from the form data for local staging and review.
    setBusy(true);
    setError('');
    setNotice('');

    try {
      requireCampaignName(campaignName);
      const headers = [
        'channel',
        'campaign_name',
        'segment_id',
        'scheduled_at',
        'timezone',
        'content_type',
        'subscription_category',
        'from_address',
        'subject',
        'html_content',
        'push_platform',
        'push_title',
        'push_message',
        'click_url',
        'whatsapp_sender',
        'whatsapp_template_id',
        'workspace_id',
        'whatsapp_placeholders',
      ];

      // Format ISO datetime with timezone
      const isoSchedule = `${singleDate}:00+05:30`;

      const values = [
        singleChannel,
        campaignName,
        singleSegment,
        isoSchedule,
        singleTimezone,
        singleChannel === 'EMAIL' ? singleContentType : '',
        '',
        singleChannel === 'EMAIL' ? singleEmailSender : '',
        singleChannel === 'EMAIL' ? singleSubject : '',
        singleChannel === 'EMAIL' ? singleHtml : '',
        singleChannel === 'PUSH' ? singlePushPlatform : '',
        singleChannel === 'PUSH' ? singlePushTitle : '',
        singleChannel === 'PUSH' ? singlePushMessage : '',
        singleChannel === 'PUSH' ? resolveCtaUrl(singleClickUrl, account) : '',
        singleChannel === 'WHATSAPP' ? singleWaSender : '',
        singleChannel === 'WHATSAPP' ? singleWaTemplate : '',
        singleChannel === 'WHATSAPP' ? waWorkspace : '',
        singleChannel === 'WHATSAPP' ? JSON.stringify(Object.fromEntries(
          selectedWaSlots.map((slot) => [slot, singleWaPlaceholders[slot]])
        )) : '',
      ];

      const csvContent = `${headers.join(',')}\n${values.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')}`;
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const syntheticFile = new File([blob], `single_${singleChannel.toLowerCase()}_${Date.now()}.csv`, { type: 'text/csv' });

      const stagedBatch = await stageMoEngageDraftBatch(syntheticFile, account);
      showBatch(stagedBatch, storageKey);
      const stagedName = stagedBatch.items[0] && campaignRowName(stagedBatch.items[0]);
      if (stagedName) setSingleName(stagedName);
      setActiveTab('batch');
      setNotice('Campaign staged locally for review; no remote draft has been confirmed. Only preview_ready rows can be selected for draft creation.');
    } catch (err) {
      setError(`Failed to process campaign: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const downloadSampleCsv = (type: 'all' | 'whatsapp' | 'email' | 'push') => {
    let rows: string[][] = [];
    const headers = [
      'channel',
      'campaign_name',
      'segment_id',
      'scheduled_at',
      'timezone',
      'content_type',
      'subscription_category',
      'from_address',
      'subject',
      'html_content',
      'push_platform',
      'push_title',
      'push_message',
      'click_url',
      'whatsapp_sender',
      'whatsapp_template_id',
      'workspace',
      'workspace_id',
    ];

    const segId = catalog?.segments?.[0]?.id || '65cf4af4d4c88174e5ad186e';

    if (type === 'all' || type === 'whatsapp') {
      rows.push([
        'WHATSAPP',
        'att_TATA_TEST_DRAFT_WA_OCT01',
        'REPLACE_WITH_WORKSPACE_SEGMENT_ID',
        '2026-10-15T11:00:00+05:30',
        'Asia/Kolkata',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        'REPLACE_WITH_WORKSPACE_SENDER_ID',
        'REPLACE_WITH_APPROVED_TEMPLATE_ID',
        'REQUIRED_EXACT_WORKSPACE_NAME_OR_USE_WORKSPACE_ID',
        '',
      ]);
    }
    if (type === 'all' || type === 'push') {
      rows.push([
        'PUSH',
        'att_TATA_TEST_DRAFT_PUSH_OCT01',
        segId,
        '2026-10-15T10:30:00+05:30',
        'Asia/Kolkata',
        '',
        '',
        '',
        '',
        '',
        'ANDROID',
        'Tata Capital Test Draft',
        'Test verification draft. Do not publish.',
        TATA_CTA_URL,
        '',
        '',
        '',
        '',
        '',
        '',
      ]);
    }
    if (type === 'all' || type === 'email') {
      rows.push([
        'EMAIL',
        'att_TATA_TEST_DRAFT_EMAIL_OCT01',
        segId,
        '2026-10-15T10:00:00+05:30',
        'Asia/Kolkata',
        'PROMOTIONAL',
        '',
        'hello@info.tatacapital.co.in',
        'Tata Capital Verification Test',
        '<p>Test verification draft. Do not publish.</p>',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
        '',
      ]);
    }

    const csvContent = `${headers.join(',')}\n${rows.map((r) => r.map((c) => `"${c.replace(/"/g, '""')}"`).join(',')).join('\n')}`;
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', `moengage_campaigns_${type}_sample.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  const filteredPreviewItems = useMemo(() => {
    if (!preview?.items) return [];
    if (filterChannel === 'ALL') return preview.items;
    return preview.items.filter((item) => item.channel?.toUpperCase() === filterChannel);
  }, [preview, filterChannel]);

  const filteredBatchItems = useMemo(() => {
    if (!batch?.items) return [];
    if (filterChannel === 'ALL') return batch.items;
    return batch.items.filter((item) => item.channel?.toUpperCase() === filterChannel);
  }, [batch, filterChannel]);

  if (authLoading) return <p role="status" className="workspace-page p-6 text-sm text-gray-600">Checking credentials…</p>;
  if (!allowed) {
    return (
      <div className="max-w-3xl mx-auto rounded-xl bg-rose-50 border border-rose-200 p-8 text-rose-900 mt-8 text-center">
        <h2 className="text-xl font-medium mb-2">Access denied</h2>
        <p className="text-sm">MoEngage campaign authoring requires a signed-in operator for {account || 'this account'}.</p>
      </div>
    );
  }

  return (
    <main className="workspace-page mx-auto min-w-0 max-w-6xl space-y-6 pb-12">
      {/* Top Header */}
      <header className="space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 max-w-3xl">
            <p className="workspace-eyebrow mb-2">{account === 'tata' ? 'Tata Capital' : 'Bajaj Finserv'} · MoEngage</p>
            <h1 className="workspace-heading">Campaign drafts</h1>
            <p className="workspace-description mt-2">
              Upload a campaign spreadsheet, review every row, and save verified drafts in <strong>{account.toUpperCase()}</strong>. Publishing remains a human action in MoEngage.
            </p>
          </div>

          <div className="flex min-w-0 flex-wrap items-center gap-3">
            {superadmin && (
              <label className="inline-flex flex-wrap items-center gap-2 text-sm font-medium text-gray-700">
                Account:
                <select
                  value={selectedAccount}
                  disabled={busy}
                  onChange={(e) => {
                    setSelectedAccount(e.target.value);
                    setFile(null);
                    setPreview(null);
                    setBatch(null);
                  }}
                  className="workspace-select"
                >
                  <option value="tata">Tata Capital</option>
                  <option value="bajaj">Bajaj Finserv</option>
                </select>
              </label>
            )}

            <div className="max-w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 [overflow-wrap:anywhere]">
              {activeTab !== 'single' ? 'WhatsApp destinations: explicit per spreadsheet row' : singleChannel === 'WHATSAPP' ? `WhatsApp destination: ${waWorkspaces.find((workspace) => workspace.id === waWorkspace)?.name || waCatalog?.workspace_name || 'Select workspace'}${waWorkspace ? ` (${waWorkspace})` : ''}` : `Account workspace: ${catalog?.workspace_name || catalog?.workspace_id || (catalogLoading ? 'Loading account catalog…' : 'Catalog unavailable')}`}
            </div>
          </div>
        </div>

        {/* Safety Banner */}
        <div className="workspace-guide flex items-start gap-3 text-sm leading-relaxed text-gray-700">
          <div>
            <strong className="font-medium text-gray-900">Draft only · No sending</strong> Creation requests target
            <code className="mx-1 rounded border border-gray-200 bg-white px-1.5 py-0.5 font-mono text-xs text-gray-900">DRAFT</code>
            status. The builder never sends messages to customers, never publishes, and never schedules automated sends. Publishing requires manual review and sign-off in the MoEngage dashboard.
          </div>
        </div>

        {/* Tabs */}
        <nav aria-label="Campaign builder views" className="flex flex-wrap gap-x-5 gap-y-2 border-b border-gray-200 text-sm font-medium">
          <button
            type="button"
            onClick={() => setActiveTab('batch')}
            aria-pressed={activeTab === 'batch'}
            className={`flex items-center gap-2 border-b-2 pb-3 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
              activeTab === 'batch'
                ? 'border-indigo-600 text-gray-700'
                : 'border-transparent text-gray-500 hover:text-gray-900'
            }`}
          >
            Bulk upload
            {batch && <span className="ml-1 font-mono text-xs text-gray-600">{batch.items.length}</span>}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('single')}
            aria-pressed={activeTab === 'single'}
            className={`flex items-center gap-2 border-b-2 pb-3 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
              activeTab === 'single'
                ? 'border-indigo-600 text-gray-700'
                : 'border-transparent text-gray-500 hover:text-gray-900'
            }`}
          >
            Single campaign
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('templates')}
            aria-pressed={activeTab === 'templates'}
            className={`flex items-center gap-2 border-b-2 pb-3 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
              activeTab === 'templates'
                ? 'border-indigo-600 text-gray-700'
                : 'border-transparent text-gray-500 hover:text-gray-900'
            }`}
          >
            Templates &amp; setup
          </button>
        </nav>
      </header>

      {/* Global Alerts */}
      {error && (
        <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900 flex items-start gap-3">
          <div className="flex-1">{error}</div>
          <button type="button" aria-label="Dismiss error" onClick={() => setError('')} className="shrink-0 rounded p-1 text-rose-700 hover:bg-rose-100">✕</button>
        </div>
      )}
      {notice && (
        <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900 flex items-start gap-3">
          <div className="flex-1 font-medium">{notice}</div>
          <button type="button" aria-label="Dismiss notice" onClick={() => setNotice('')} className="shrink-0 rounded p-1 text-emerald-700 hover:bg-emerald-100">✕</button>
        </div>
      )}
      {busy && <p role="status" className="workspace-guide flex items-center gap-3 text-sm text-gray-700"><span aria-hidden="true" className="h-4 w-4 shrink-0 animate-spin rounded-full border-2 border-gray-200 border-t-indigo-600" />{automatingWa ? 'Saving and verifying WhatsApp drafts sequentially. Results appear below.' : 'Processing your request. Keep this page open until the result is confirmed.'}</p>}

      {/* TAB 1: SINGLE CAMPAIGN BUILDER */}
      {activeTab === 'single' && (
        <div className="grid min-w-0 grid-cols-1 items-start gap-6 lg:grid-cols-12">
          {/* Left Form: 7 cols */}
          <div className="min-w-0 space-y-6 lg:col-span-7">
            {/* Step 1: Channel selection */}
            <section className="workspace-panel min-w-0 space-y-4 p-5 sm:p-6">
              <h2 className="text-base font-medium text-gray-900">1. Select a channel</h2>
              <div className="grid grid-cols-3 gap-2 sm:gap-3">
                <button
                  type="button"
                  onClick={() => setSingleChannel('WHATSAPP')}
                  aria-pressed={singleChannel === 'WHATSAPP'}
                  className={`rounded-lg border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                    singleChannel === 'WHATSAPP'
                      ? 'border-gray-200 bg-gray-50'
                      : 'border-gray-200 hover:border-gray-300 bg-white'
                  }`}
                >
                  <div className="font-medium text-sm text-gray-900">WhatsApp</div>
                  <div className="mt-2 text-xs leading-relaxed text-gray-600">Workspace-approved templates</div>
                </button>

                <button
                  type="button"
                  onClick={() => setSingleChannel('PUSH')}
                  aria-pressed={singleChannel === 'PUSH'}
                  className={`rounded-lg border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                    singleChannel === 'PUSH'
                      ? 'border-gray-200 bg-gray-50'
                      : 'border-gray-200 hover:border-gray-300 bg-white'
                  }`}
                >
                  <div className="font-medium text-sm text-gray-900">Push app</div>
                  <div className="mt-2 text-xs leading-relaxed text-gray-600">Android &amp; iOS push</div>
                </button>

                <button
                  type="button"
                  onClick={() => setSingleChannel('EMAIL')}
                  aria-pressed={singleChannel === 'EMAIL'}
                  className={`rounded-lg border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 ${
                    singleChannel === 'EMAIL'
                      ? 'border-gray-200 bg-gray-50'
                      : 'border-gray-200 hover:border-gray-300 bg-white'
                  }`}
                >
                  <div className="font-medium text-sm text-gray-900">Email</div>
                  <div className="mt-2 text-xs leading-relaxed text-gray-600">SendGrid / HTML</div>
                </button>
              </div>
            </section>

            {/* Step 2: Campaign basics */}
            <section className="workspace-panel min-w-0 space-y-5 p-5 sm:p-6">
              <h2 className="text-base font-medium text-gray-900">2. Campaign details &amp; audience</h2>

              {singleChannel === 'WHATSAPP' && (
                <div>
                  <label htmlFor="single-workspace" className="mb-2 block text-sm font-medium text-gray-700">WhatsApp destination workspace *</label>
                  <select id="single-workspace" value={waWorkspace} onChange={(e) => { setWaWorkspace(e.target.value); setWaCatalog(null); setSingleSegment(''); setSingleWaSender(''); setSingleWaTemplate(''); }} className="workspace-select w-full">
                    <option value="">Select destination — required</option>
                    {waWorkspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name} ({workspace.id})</option>)}
                  </select>
                </div>
              )}
              <div>
                <label htmlFor="single-name" className="mb-2 block text-sm font-medium text-gray-700">Campaign name *</label>
                <input id="single-name"
                  type="text"
                  placeholder="e.g. att_TATA_FESTIVE_SPECIAL_OCT2026"
                  value={singleName}
                  onChange={(e) => setSingleName(e.target.value)}
                  onBlur={() => setSingleName(normalizeCampaignName(singleName))}
                  aria-describedby="single-campaign-name-rule"
                  className="workspace-input w-full"
                />
                <p id="single-campaign-name-rule" className="mt-2 text-sm text-gray-600">{CAMPAIGN_NAME_HINT}</p>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label htmlFor="single-segment" className="mb-2 block text-sm font-medium text-gray-700">Target audience segment *</label>
                  <select id="single-segment"
                    value={singleSegment}
                    onChange={(e) => setSingleSegment(e.target.value)}
                    className="workspace-select w-full"
                  >
                    <option value="" disabled>Select an account audience</option>
                    {formCatalog?.segments?.map((seg) => (
                      <option key={seg.id} value={seg.id}>
                        {seg.name} ({seg.id.slice(0, 8)}…)
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label htmlFor="single-planning-date" className="mb-2 block text-sm font-medium text-gray-700">Planned start time (IST)</label>
                  <input id="single-planning-date"
                    type="datetime-local"
                    value={singleDate}
                    onChange={(e) => setSingleDate(e.target.value)}
                    className="workspace-input w-full"
                  />
                  <p className="mt-2 text-sm leading-relaxed text-gray-600">Planning time only. Confirm delivery settings in MoEngage before publishing.</p>
                </div>
              </div>
            </section>

            {/* Step 3: Channel-specific content */}
            <section className="workspace-panel min-w-0 space-y-5 p-5 sm:p-6">
              <h2 className="text-base font-medium text-gray-900">3. {singleChannel} content</h2>

              {singleChannel === 'WHATSAPP' && (
                <div className="space-y-4">
                  <div>
                    <label htmlFor="single-wa-sender" className="mb-2 block text-sm font-medium text-gray-700">WhatsApp sender{selectedWaSender?.provider ? ` (${selectedWaSender.provider})` : ''}</label>
                    <select id="single-wa-sender"
                      value={singleWaSender}
                      disabled={!waCatalog || waCatalog.workspace_id !== waWorkspace}
                      onChange={(e) => { setSingleWaSender(e.target.value); setSingleWaTemplate(''); }}
                      className="workspace-select w-full"
                    >
                      <option value="" disabled>Select an account sender</option>
                      {waCatalog?.whatsapp_senders?.map((s) => (
                        <option key={s.sender_id} value={s.sender_id}>
                          {s.name} ({s.number}) · {s.provider}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label htmlFor="single-wa-template" className="mb-2 block text-sm font-medium text-gray-700">Approved WhatsApp template ID</label>
                    <select id="single-wa-template" value={singleWaTemplate} disabled={!selectedWaSender} onChange={(e) => setSingleWaTemplate(e.target.value)} className="workspace-select w-full disabled:bg-gray-50 disabled:text-gray-500">
                      <option value="">Select an approved sender template</option>
                      {waCatalog?.whatsapp_templates?.filter((template) => template.sender_ids.includes(singleWaSender)).map((template) => (
                        <option key={template.id} value={template.id}>{template.name} ({template.id})</option>
                      ))}
                    </select>
                    <p className="mt-2 text-sm leading-relaxed text-gray-600">{!selectedWaSender ? 'Select a workspace and sender first: approved templates are scoped to that sender.' : 'Only approved templates available to this workspace and sender are shown.'}</p>
                  </div>
                  {selectedWaSlots.map((slot) => (
                    <div key={slot}>
                      <label htmlFor={`wa-variable-${slot.replace(/\D/g, '')}`} className="mb-2 block text-sm font-medium text-gray-700">
                        Template variable {slot} *
                      </label>
                      <textarea
                        id={`wa-variable-${slot.replace(/\D/g, '')}`}
                        value={singleWaPlaceholders[slot] || ''}
                        onChange={(event) => setSingleWaPlaceholders((values) => ({ ...values, [slot]: event.target.value }))}
                        rows={2}
                        className="workspace-input w-full"
                      />
                    </div>
                  ))}
                </div>
              )}

              {singleChannel === 'PUSH' && (
                <div className="space-y-4">
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <div>
                      <label htmlFor="single-push-platform" className="mb-2 block text-sm font-medium text-gray-700">Platform</label>
                      <select id="single-push-platform"
                        value={singlePushPlatform}
                        onChange={(e) => setSinglePushPlatform(e.target.value)}
                        className="workspace-select w-full"
                      >
                        <option value="ANDROID">Android (general channel)</option>
                        <option value="IOS">iOS (APNS)</option>
                      </select>
                    </div>

                    <div>
                      <label htmlFor="single-push-url" className="mb-2 block text-sm font-medium text-gray-700">Deeplink / click URL</label>
                      <input id="single-push-url"
                        type="url"
                        value={singleClickUrl}
                        onChange={(e) => setSingleClickUrl(e.target.value)}
                        className="workspace-input w-full font-mono"
                      />
                    </div>
                  </div>

                  <div>
                    <label htmlFor="single-push-title" className="mb-2 block text-sm font-medium text-gray-700">Notification title</label>
                    <input id="single-push-title"
                      type="text"
                      placeholder="e.g. Exclusive Loan Offer Available!"
                      value={singlePushTitle}
                      onChange={(e) => setSinglePushTitle(e.target.value)}
                      className="workspace-input w-full"
                    />
                  </div>

                  <div>
                    <label htmlFor="single-push-body" className="mb-2 block text-sm font-medium text-gray-700">Notification body</label>
                    <textarea id="single-push-body"
                      rows={3}
                      placeholder="e.g. Check your pre-qualified offer up to ₹ 90 lacs with instant approval."
                      value={singlePushMessage}
                      onChange={(e) => setSinglePushMessage(e.target.value)}
                      className="workspace-input w-full"
                    />
                  </div>
                </div>
              )}

              {singleChannel === 'EMAIL' && (
                <div className="space-y-4">
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <div>
                      <label htmlFor="single-email-sender" className="mb-2 block text-sm font-medium text-gray-700">Sender address (SendGrid)</label>
                      <select id="single-email-sender"
                        value={singleEmailSender}
                        onChange={(e) => setSingleEmailSender(e.target.value)}
                        className="workspace-select w-full"
                      >
                        {catalog?.email_senders?.map((s) => (
                          <option key={s.from_address} value={s.from_address}>
                            {s.from_address} ({s.sender_name})
                          </option>
                        ))}
                        <option value="hello@info.tatacapital.co.in">hello@info.tatacapital.co.in (Tata Capital)</option>
                      </select>
                    </div>

                    <div>
                      <label htmlFor="single-email-type" className="mb-2 block text-sm font-medium text-gray-700">Content type</label>
                      <select id="single-email-type"
                        value={singleContentType}
                        onChange={(e) => setSingleContentType(e.target.value)}
                        className="workspace-select w-full"
                      >
                        <option value="PROMOTIONAL">PROMOTIONAL</option>
                        <option value="TRANSACTIONAL">TRANSACTIONAL</option>
                      </select>
                    </div>
                  </div>

                  <div>
                    <label htmlFor="single-email-subject" className="mb-2 block text-sm font-medium text-gray-700">Email subject line</label>
                    <input id="single-email-subject"
                      type="text"
                      placeholder="e.g. Your Monthly Financial Statement is Ready"
                      value={singleSubject}
                      onChange={(e) => setSingleSubject(e.target.value)}
                      className="workspace-input w-full"
                    />
                  </div>

                  <div>
                    <label htmlFor="single-email-html" className="mb-2 block text-sm font-medium text-gray-700">HTML email content</label>
                    <textarea id="single-email-html"
                      rows={5}
                      value={singleHtml}
                      onChange={(e) => setSingleHtml(e.target.value)}
                      className="workspace-input w-full font-mono"
                    />
                  </div>
                </div>
              )}

              <div className="pt-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void handleCreateFromSingleForm()}
                  className="workspace-button-primary flex w-full items-center justify-center gap-2"
                >
                  {busy ? 'Staging campaign…' : `Stage ${singleChannel} campaign for review`}
                </button>
              </div>
            </section>
          </div>

          {/* Right Live Preview: 5 cols */}
          <aside aria-labelledby="message-preview-heading" className="min-w-0 space-y-4 lg:sticky lg:top-6 lg:col-span-5">
            <h2 id="message-preview-heading" className="text-base font-medium text-gray-900">Message preview</h2>
            <p className="text-sm leading-relaxed text-gray-600">Preview only. Staging saves a review queue in this app; a separate confirmation is required to save a MoEngage draft.</p>

            {singleChannel === 'WHATSAPP' && (
              <div className="workspace-panel min-w-0 overflow-hidden p-5">
                <div className="mb-4 flex items-center gap-3 border-b border-gray-200 pb-4 text-gray-900">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-xs font-medium text-gray-700">WA</div>
                  <div className="flex-1 min-w-0">
                    <div className="break-words text-sm font-medium">{selectedWaSender?.name || 'Select a WhatsApp sender'}</div>
                    <div className="text-sm text-gray-600">{selectedWaSender?.provider || 'Workspace-scoped preview'}</div>
                  </div>
                </div>

                <div className="space-y-3 rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm leading-relaxed text-gray-800 [overflow-wrap:anywhere]">
                  {selectedWaTemplate ? (
                    <>
                      <div className="font-medium text-gray-900">{selectedWaTemplate.display_name || selectedWaTemplate.name}</div>
                      <p className="text-gray-700">Template: <code className="rounded bg-white px-1 py-0.5 font-mono text-xs">{selectedWaTemplate.id}</code></p>
                      <p className="whitespace-pre-wrap text-sm text-gray-800">{selectedWaTemplate.body?.replace(/\{\{\d+\}\}/g, (slot) => singleWaPlaceholders[slot] || slot) || 'The live template has no body text available for preview.'}</p>
                      <p className="text-xs text-gray-600">Live template copy · Preview only, not sent</p>
                    </>
                  ) : (
                    <p className="text-gray-500">Select a workspace, sender and approved template to preview its actual message body. No template selected.</p>
                  )}
                </div>
              </div>
            )}

            {singleChannel === 'PUSH' && (
              <div className="workspace-panel min-w-0 space-y-3 p-5">
                <div className="text-sm font-medium text-gray-600">Notification preview</div>
                <div className="bg-white rounded-xl p-4 border border-gray-200 flex items-start gap-3">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-gray-100 text-xs font-medium text-gray-700">
                    {account === 'tata' ? 'TC' : 'BF'}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-gray-500">
                      <span className="font-medium text-gray-700">{account === 'tata' ? 'Tata Capital' : 'Bajaj Finserv'}</span>
                      <span>now</span>
                    </div>
                    <div className="mt-1 whitespace-pre-wrap break-words text-sm font-medium text-gray-900">
                      {singlePushTitle || 'Exclusive Offer Available'}
                    </div>
                    <p className="mt-1 whitespace-pre-wrap break-words text-sm leading-relaxed text-gray-600">
                      {singlePushMessage || 'Check your pre-qualified offer up to ₹ 90 lacs with instant approval.'}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {singleChannel === 'EMAIL' && (
              <div className="workspace-panel min-w-0 space-y-4 p-5 [overflow-wrap:anywhere]">
                <div className="space-y-2 border-b border-gray-200 pb-4 text-sm">
                  <div>
                    <span className="text-gray-500">From:</span>{' '}
                    <span className="font-medium text-gray-900">{singleEmailSender || 'No sender selected'}</span>
                  </div>
                  <div>
                    <span className="text-gray-500">Subject:</span>{' '}
                    <span className="font-medium text-gray-900">{singleSubject || 'No subject entered'}</span>
                  </div>
                </div>
                <div
                  className="min-h-[160px] overflow-auto rounded-lg border border-gray-200 bg-gray-50 p-4 text-sm text-gray-800 prose prose-sm max-w-none"
                  dangerouslySetInnerHTML={{ __html: singleHtml || '<p>Email preview will appear here.</p>' }}
                />
              </div>
            )}
          </aside>
        </div>
      )}

      {/* TAB 2: SPREADSHEET BATCH UPLOAD */}
      {activeTab === 'batch' && (
        <div className="space-y-6">
          <section className="workspace-panel min-w-0 space-y-4 p-5 sm:p-6">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-medium text-gray-900">1. Upload and preview your brief</h2>
                <p className="mt-2 max-w-3xl text-sm leading-relaxed text-gray-600">
                  Upload a <code>.csv</code> or <code>.xlsx</code> file. Every WhatsApp row requires its own exact <code>workspace</code> name or portal <code>workspace_id</code>; review each destination before creating.
                </p>
              </div>

              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => downloadSampleCsv('all')}
                  className="workspace-button"
                >
                  Download 3-channel sample CSV
                </button>
              </div>
            </div>

            <label htmlFor="campaign-brief" className="block text-sm font-medium text-gray-700">Campaign brief · CSV or XLSX, up to 5 MiB</label>
            <input id="campaign-brief"
              ref={fileRef}
              type="file"
              accept=".csv,.xlsx"
              disabled={busy}
              onChange={(e) => void chooseFile(e.target.files?.[0])}
              className="workspace-input block w-full min-w-0 text-sm file:mr-3 file:rounded-md file:border-0 file:bg-gray-100 file:px-3 file:py-2 file:font-medium file:text-gray-800 hover:file:bg-gray-200"
            />
            <button type="button" disabled={busy || loading || automatingWa} className="workspace-button"
              onClick={async () => {
                if (busy || loading || automatingWa || createInFlight.current) return;
                const id = localStorage.getItem(storageKey);
                if (!id) { setNotice('No saved batch yet. Upload a spreadsheet to begin.'); return; }
                setBusy(true);
                setError('');
                setNotice('');
                try { showBatch(await fetchMoEngageDraftBatch(id, account), storageKey); }
                catch (cause) {
                  if (cause instanceof MoEngageDraftRequestError && cause.status === 404) {
                    clearSavedBatch(id, storageKey);
                    setNotice('This saved batch is no longer available. Upload a spreadsheet to begin.');
                  } else {
                    setError(`Could not open saved batch: ${cause instanceof Error ? cause.message : String(cause)}`);
                  }
                }
                finally { setBusy(false); }
              }}>Open last saved batch</button>
          </section>

          {/* Preview Section */}
          {preview?.account === account && (
            <section className="space-y-4">
              <div className="workspace-panel flex min-w-0 flex-wrap items-center justify-between gap-4 p-5">
                <div>
                  <h2 className="break-words text-base font-medium text-gray-900">
                    2. Review spreadsheet · <span className="font-mono text-sm text-gray-600">{file?.name}</span>
                  </h2>
                  <p className="mt-2 text-sm text-gray-600">
                    Ready: <strong className="text-emerald-700">{preview.ready}</strong> · Blocked:{' '}
                    <strong className="text-rose-700">{preview.blocked}</strong> · WhatsApp destinations are shown per row.
                  </p>
                </div>

                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void stage()}
                  className="workspace-button-primary"
                >
                  Stage reviewed file
                </button>
              </div>

              {/* Channel Filter Chips */}
              <div aria-label="Preview channel filter" className="flex flex-wrap gap-2 text-sm font-medium">
                {(['ALL', 'WHATSAPP', 'EMAIL', 'PUSH'] as const).map((ch) => (
                  <button
                    key={ch}
                    type="button"
                    onClick={() => setFilterChannel(ch)}
                    aria-pressed={filterChannel === ch}
                    className={`workspace-filter-chip ${
                      filterChannel === ch
                        ? 'border-gray-200 bg-gray-50 text-gray-900'
                        : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50'
                    }`}
                  >
                    {ch === 'ALL' ? 'All' : ch === 'WHATSAPP' ? 'WhatsApp' : ch === 'EMAIL' ? 'Email' : 'Push'}
                  </button>
                ))}
                {filterChannel !== 'ALL' && <button type="button" className="workspace-button" onClick={() => setFilterChannel('ALL')}>Reset filter</button>}
                <p className="self-center text-sm font-normal text-gray-600">{filteredPreviewItems.length} of {preview.items.length} rows</p>
              </div>

              <div className="space-y-4">
                {filteredPreviewItems.length === 0 && <div className="workspace-empty"><p className="font-medium text-gray-900">{preview.items.length ? `No ${filterChannel.toLowerCase()} campaigns in this preview.` : 'No campaign rows found in this brief.'}</p><p className="mt-2 text-sm text-gray-600">{preview.items.length ? 'Choose another channel or show all rows.' : 'Check the sample format and upload a brief containing campaign rows.'}</p>{filterChannel !== 'ALL' && <button type="button" className="workspace-button mt-4" onClick={() => setFilterChannel('ALL')}>Reset channel filter</button>}</div>}
                {filteredPreviewItems.map((row, index) => (
                  <RowCard key={`${row.source_ref}:${row.row_id}:${index}`} row={row} batch={false} busy={busy} uncertain={false} onCreate={createRow} templateBody={reviewBodies[`${row.workspace_id}:${row.candidate_v5_payload?.campaign_content?.content?.whatsapp?.template_id}`]} />
                ))}
              </div>
            </section>
          )}

          {/* Staged Batch Queue Section */}
          {loading && <p role="status" className="workspace-guide py-5 text-sm text-gray-600">Loading saved batch…</p>}

          {batchScope === storageKey && batch?.account === account && (
            <section className="space-y-4">
              <div className="workspace-panel flex min-w-0 flex-wrap items-center justify-between gap-4 p-5">
                <div>
                  <h2 className="text-base font-medium text-gray-900">
                    3. Save and verify drafts
                  </h2>
                  <p className="mt-2 break-words text-sm text-gray-600">
                    Source: <span className="font-mono">{batch.source_ref}</span> · Ready:{' '}
                    <strong className="text-emerald-700">{batch.ready}</strong> · Blocked:{' '}
                    <strong className="text-rose-700">{batch.blocked}</strong>
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  <button type="button" disabled={busy || automatingWa} className="workspace-button"
                    onClick={() => {
                      setBatch(null); setBatchScope(''); setPreview(null); setFile(null); setNotice(''); setError('');
                      const url = new URL(window.location.href); url.searchParams.delete('batch');
                      window.history.replaceState(null, '', url.toString());
                      window.scrollTo({ top: 0, behavior: 'auto' });
                    }}>New bulk upload</button>
                  <button
                    type="button"
                    disabled={busy || loading || automatingWa}
                    onClick={() => void removeBatch()}
                    className="workspace-button border-rose-200 text-rose-700 hover:bg-rose-50"
                  >
                    Remove batch
                  </button>
                  {batch.items.some((r) => r.channel?.toUpperCase() === 'WHATSAPP' && r.status === 'preview_ready' && !r.campaign_id && !uncertainRows.includes(r.row_id)) && (
                    <button
                      type="button"
                      disabled={busy || automatingWa}
                      onClick={() => void handleAutomateWhatsApp()}
                      className="workspace-button-primary"
                    >
                      {automatingWa ? 'Saving and verifying sequentially…' : 'Save ready WhatsApp drafts sequentially'}
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={busy || automatingWa}
                    onClick={() => void refreshBatch()}
                    className="workspace-button"
                  >
                    Refresh stored state
                  </button>
                </div>
              </div>
              {/* Channel Filter Chips */}
              <p className="workspace-guide text-sm leading-relaxed text-gray-700">Staged rows are not yet remote drafts. Save only reviewed, ready rows. If a result is uncertain, refresh stored state and reconcile in MoEngage before any further creation; a refresh never retries creation.</p>
              <div aria-label="Saved batch channel filter" className="flex flex-wrap gap-2 text-sm font-medium">
                {(['ALL', 'WHATSAPP', 'EMAIL', 'PUSH'] as const).map((ch) => (
                  <button
                    key={ch}
                    type="button"
                    onClick={() => setFilterChannel(ch)}
                    aria-pressed={filterChannel === ch}
                    className={`workspace-filter-chip ${
                      filterChannel === ch
                        ? 'border-gray-200 bg-gray-50 text-gray-900'
                        : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50'
                    }`}
                  >
                    {ch === 'ALL' ? 'All' : ch === 'WHATSAPP' ? 'WhatsApp' : ch === 'EMAIL' ? 'Email' : 'Push'}
                  </button>
                ))}
                {filterChannel !== 'ALL' && <button type="button" className="workspace-button" onClick={() => setFilterChannel('ALL')}>Reset filter</button>}
                <p className="self-center text-sm font-normal text-gray-600">{filteredBatchItems.length} of {batch.items.length} rows</p>
              </div>

              <div className="space-y-4">
                {filteredBatchItems.length === 0 && <div className="workspace-empty"><p className="font-medium text-gray-900">{batch.items.length ? `No ${filterChannel.toLowerCase()} campaigns in this batch.` : 'No campaigns in this saved batch.'}</p><p className="mt-2 text-sm text-gray-600">{batch.items.length ? 'The other channel rows are unchanged. Show all rows to continue reviewing.' : 'Start a new bulk upload to review a campaign brief.'}</p>{filterChannel !== 'ALL' && <button type="button" className="workspace-button mt-4" onClick={() => setFilterChannel('ALL')}>Reset channel filter</button>}</div>}
                {filteredBatchItems.map((row, index) => (
                  <RowCard
                    key={`${row.source_ref}:${row.row_id}:${index}`}
                    row={row}
                    templateBody={reviewBodies[`${row.workspace_id}:${row.candidate_v5_payload?.campaign_content?.content?.whatsapp?.template_id}`]}
                    batch
                    busy={busy}
                    uncertain={uncertainRows.includes(row.row_id)}
                    onCreate={createRow}
                  />
                ))}
              </div>
            </section>
          )}
        </div>
      )}

      {/* TAB 3: SAMPLE TEMPLATES & DOCUMENTATION */}
      {activeTab === 'templates' && (
        <div className="space-y-6">
          <section className="workspace-panel min-w-0 space-y-4 p-5 sm:p-6">
            <h2 className="text-base font-medium text-gray-900">Sample CSV templates</h2>
            <p className="text-sm text-gray-600">
              Replace all sample placeholders before upload. Every WhatsApp row requires an explicit workspace and that workspace&apos;s audience, sender and approved template IDs; there is no default destination.
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 pt-2">
              <button
                type="button"
                onClick={() => downloadSampleCsv('all')}
                className="workspace-button flex-col items-start whitespace-normal p-4 text-left"
              >
                <div className="text-sm font-medium text-gray-900">Combined 3-channel</div>
                <div className="mt-2 text-sm font-normal text-gray-600">WhatsApp + Push + Email</div>
              </button>

              <button
                type="button"
                onClick={() => downloadSampleCsv('whatsapp')}
                className="workspace-button flex-col items-start whitespace-normal p-4 text-left"
              >
                <div className="text-sm font-medium text-gray-900">WhatsApp only</div>
                <div className="mt-2 text-sm font-normal text-gray-600">Workspace-approved senders</div>
              </button>

              <button
                type="button"
                onClick={() => downloadSampleCsv('push')}
                className="workspace-button flex-col items-start whitespace-normal p-4 text-left"
              >
                <div className="text-sm font-medium text-gray-900">Push only</div>
                <div className="mt-2 text-sm font-normal text-gray-600">Android app push</div>
              </button>

              <button
                type="button"
                onClick={() => downloadSampleCsv('email')}
                className="workspace-button flex-col items-start whitespace-normal p-4 text-left"
              >
                <div className="text-sm font-medium text-gray-900">Email only</div>
                <div className="mt-2 text-sm font-normal text-gray-600">SendGrid HTML</div>
              </button>
            </div>
          </section>

          <section className="workspace-panel min-w-0 space-y-4 p-5 sm:p-6">
            <h2 className="text-base font-medium text-gray-900">Spreadsheet column specifications</h2>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse text-left text-sm">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50 font-medium text-gray-700">
                    <th className="font-medium p-3">Column header</th>
                    <th className="font-medium p-3">Channel</th>
                    <th className="font-medium p-3">Required?</th>
                    <th className="font-medium p-3">Description / example</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 text-gray-800">
                  <tr>
                    <td className="p-3 font-mono font-medium text-gray-700">channel</td>
                    <td className="p-3">All</td>
                    <td className="p-3 font-medium text-rose-700">Yes</td>
                    <td className="p-3"><code>WHATSAPP</code>, <code>PUSH</code>, or <code>EMAIL</code></td>
                  </tr>
                  <tr>
                    <td className="p-3 font-mono font-medium text-gray-700">campaign_name</td>
                    <td className="p-3">All</td>
                    <td className="p-3 font-medium text-rose-700">Yes</td>
                    <td className="p-3">Unique campaign name starting with lowercase <code>att_</code> and a nonempty suffix. Preview adds the prefix automatically; template names and IDs are unchanged.</td>
                  </tr>
                  <tr>
                    <td className="p-3 font-mono font-medium text-gray-700">segment_id</td>
                    <td className="p-3">All</td>
                    <td className="p-3 font-medium text-rose-700">Yes</td>
                    <td className="p-3">Saved audience ID (e.g. <code>65cf4af4d4c88174e5ad186e</code>)</td>
                  </tr>
                  <tr>
                    <td className="p-3 font-mono font-medium text-gray-700">scheduled_at</td>
                    <td className="p-3">All</td>
                    <td className="p-3 font-medium text-rose-700">Yes</td>
                    <td className="p-3">ISO datetime (e.g. <code>2026-10-15T10:30:00+05:30</code>)</td>
                  </tr>
                  <tr>
                    <td className="p-3 font-mono font-medium text-gray-700">timezone</td>
                    <td className="p-3">All</td>
                    <td className="p-3 font-medium text-rose-700">Yes</td>
                    <td className="p-3">IANA timezone (e.g. <code>Asia/Kolkata</code>)</td>
                  </tr>
                  <tr>
                    <td className="p-3 font-mono">whatsapp_sender</td>
                    <td className="p-3">WhatsApp</td>
                    <td className="p-3">Yes</td>
                    <td className="p-3">e.g. <code>Tata Capital Financial Services Limited</code></td>
                  </tr>
                  <tr>
                    <td className="p-3 font-mono">whatsapp_template_id</td>
                    <td className="p-3">WhatsApp</td>
                    <td className="p-3">Yes</td>
                    <td className="p-3">Exact approved template ID from the selected workspace</td>
                  </tr>
                  <tr>
                    <td className="p-3 font-mono">from_address</td>
                    <td className="p-3">Email</td>
                    <td className="p-3">Yes</td>
                    <td className="p-3">e.g. <code>hello@info.tatacapital.co.in</code></td>
                  </tr>
                  <tr>
                    <td className="p-3 font-mono">subject</td>
                    <td className="p-3">Email</td>
                    <td className="p-3">Yes</td>
                    <td className="p-3">Subject line for HTML emails</td>
                  </tr>
                  <tr>
                    <td className="p-3 font-mono">html_content</td>
                    <td className="p-3">Email</td>
                    <td className="p-3">Yes</td>
                    <td className="p-3">Raw HTML message body</td>
                  </tr>
                  <tr>
                    <td className="p-3 font-mono">push_title</td>
                    <td className="p-3">Push</td>
                    <td className="p-3">Yes</td>
                    <td className="p-3">Push notification title text</td>
                  </tr>
                  <tr>
                    <td className="p-3 font-mono">push_message</td>
                    <td className="p-3">Push</td>
                    <td className="p-3">Yes</td>
                    <td className="p-3">Notification body text</td>
                  </tr>
                  <tr>
                    <td className="p-3 font-mono">click_url</td>
                    <td className="p-3">Push</td>
                    <td className="p-3">Yes</td>
                    <td className="p-3">Target HTTPS click URL or deeplink</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}
