'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useTabState } from '@/lib/tab-state';
import { useApp } from '@/lib/context';
import {
  automateMoEngageWhatsAppBatch,
  createMoEngageDraftRow,
  fetchMoEngageCatalog,
  fetchMoEngageDraftBatch,
  previewMoEngageDraftFile,
  stageMoEngageDraftBatch,
} from '@/lib/api';
import type {
  MoEngageCatalog,
  MoEngageDraftBatch,
  MoEngageDraftPreview,
  MoEngageDraftRow,
} from '@/lib/api';

const MAX_FILE_BYTES = 5 * 1024 * 1024;
const VERIFIED_STATES: Record<string, true> = { VERIFIED: true, VALIDATED: true, NEEDS_FIX: true };


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
}: {
  row: MoEngageDraftRow;
  batch: boolean;
  busy: boolean;
  uncertain: boolean;
  onCreate: (row: MoEngageDraftRow) => void;
}) {
  const candidate = row.candidate_v5_payload;
  const source = row.source_fields || {};
  const content = candidate?.campaign_content?.content;
  const email = content?.email;
  const push = content?.push ? Object.values(content.push)[0]?.basic_details : undefined;
  const segment = candidate?.segmentation_details?.included_filters?.filters?.[0];
  const schedule = candidate?.scheduling_details;
  const issues = [...(row.issues || []), ...(row.issue ? [row.issue] : []), ...validationMessages(row.validation_errors)];
  const status = row.status || 'blocked';
  const ready = status === 'preview_ready';
  const verified = Boolean(VERIFIED_STATES[status]);
  const isWhatsApp = row.channel?.toUpperCase() === 'WHATSAPP';
  const isEmail = row.channel?.toUpperCase() === 'EMAIL';
  const isPush = row.channel?.toUpperCase() === 'PUSH';

  return (
    <article className="rounded-xl border border-gray-200 bg-white p-5 space-y-4 shadow-sm hover:border-gray-300 transition-colors">
      <div className="flex flex-wrap justify-between items-start gap-2">
        <div>
          <div className="text-xs text-gray-500 font-mono">
            Source: {row.source_ref || 'Single Campaign'} · Row {row.row_id}
          </div>
          <h3 className="font-semibold text-gray-900 text-base mt-0.5">
            {source.campaign_name || candidate?.basic_details?.name || 'Campaign name missing'}
          </h3>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs font-semibold">
          <span
            className={`rounded-full px-2.5 py-1 ${
              isWhatsApp
                ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
                : isEmail
                ? 'bg-blue-50 text-blue-800 border border-blue-200'
                : 'bg-purple-50 text-purple-800 border border-purple-200'
            }`}
          >
            {row.channel || 'UNKNOWN'}
          </span>
          <span
            className={`rounded-full px-2.5 py-1 ${
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

      {batch && row.updated_at && (
        <p className="text-xs text-gray-400">
          Last updated: {new Date(row.updated_at * 1000).toLocaleString()} (UTC). Stored draft record; no customer messages sent.
        </p>
      )}

      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="text-xs font-medium text-gray-500 uppercase tracking-wider">Target Audience</dt>
          <dd className="text-gray-900 mt-0.5 break-all">
            {segment ? (
              <span className="inline-flex items-center gap-1 font-medium">
                🎯 {segment.name || 'Custom segment'}
                <span className="text-xs text-gray-500 font-mono">({segment.id})</span>
              </span>
            ) : (
              source.segment_name || source.segment_id || 'Not supplied'
            )}
          </dd>
        </div>

        <div>
          <dt className="text-xs font-medium text-gray-500 uppercase tracking-wider">Schedule & Timezone</dt>
          <dd className="text-gray-900 mt-0.5">
            📅 {schedule?.start_time || [source.scheduled_at, source.timezone].filter(Boolean).join(' · ') || 'Not supplied'}
            {schedule?.timezone ? ` (${schedule.timezone})` : ''}
          </dd>
        </div>

        {isEmail && (
          <>
            <div>
              <dt className="text-xs font-medium text-gray-500 uppercase tracking-wider">Email Sender & Subject</dt>
              <dd className="text-gray-900 mt-0.5 break-words">
                ✉️ {source.from_address || email?.from_address || 'Not set'}
                <span className="text-gray-500"> · </span>
                <span className="font-medium">{source.subject || email?.subject || 'No subject'}</span>
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-gray-500 uppercase tracking-wider">Content Type & Connector</dt>
              <dd className="text-gray-900 mt-0.5">
                {source.content_type || candidate?.basic_details?.content_type || 'PROMOTIONAL'}
                {candidate?.connector?.connector_type ? ` · ${candidate.connector.connector_type} (${candidate.connector.connector_name || 'default'})` : ''}
              </dd>
            </div>
            {(source.html_content || email?.html_content) && (
              <div className="sm:col-span-2">
                <dt className="text-xs font-medium text-gray-500 uppercase tracking-wider mb-1">Email HTML Content</dt>
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
              <dt className="text-xs font-medium text-gray-500 uppercase tracking-wider">Push Title & Platform</dt>
              <dd className="text-gray-900 mt-0.5 font-medium">
                🔔 {source.push_title || push?.title || 'Not set'}
                <span className="text-xs font-normal text-gray-500 ml-1">
                  ({source.push_platform || candidate?.basic_details?.platforms?.join(', ') || 'ANDROID'})
                </span>
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-gray-500 uppercase tracking-wider">Click URL / Deeplink</dt>
              <dd className="text-gray-900 mt-0.5 break-all text-xs font-mono text-blue-700">
                🔗 {source.click_url || push?.default_click_action_value || 'Not set'}
              </dd>
            </div>
            <div className="sm:col-span-2">
              <dt className="text-xs font-medium text-gray-500 uppercase tracking-wider">Push Notification Body</dt>
              <dd className="text-gray-900 mt-0.5 rounded-lg bg-gray-50 border border-gray-200 p-2.5 text-sm">
                {source.push_message || push?.message || 'Not set'}
              </dd>
            </div>
          </>
        )}

        {isWhatsApp && (
          <>
            <div>
              <dt className="text-xs font-medium text-gray-500 uppercase tracking-wider">WhatsApp Sender (Karix BSP)</dt>
              <dd className="text-gray-900 mt-0.5 font-medium">
                💬 {source.whatsapp_sender || 'Tata Capital Financial Services Limited'}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium text-gray-500 uppercase tracking-wider">WhatsApp Template</dt>
              <dd className="text-gray-900 mt-0.5 font-medium flex flex-wrap items-center gap-1.5">
                <span>📋 {source.matched_template_name || source.whatsapp_template_name || source.whatsapp_template_id || 'test_1234 (EN)'}</span>
                {source.matched_template_id && (
                  <span className="text-[11px] font-mono text-gray-500">({source.matched_template_id})</span>
                )}
                {source.matched_template_confidence && (
                  <span className="text-[10px] font-semibold bg-emerald-100 text-emerald-800 px-1.5 py-0.5 rounded">
                    🎯 {source.matched_template_confidence} Match
                  </span>
                )}
              </dd>
            </div>
          </>
        )}
      </dl>

      {issues.length > 0 && (
        <div className="rounded-lg bg-rose-50 border border-rose-200 p-3 text-sm text-rose-900">
          <strong className="block font-semibold">Validation Issues:</strong>
          <ul className="list-disc pl-5 mt-1 space-y-0.5 text-xs">
            {issues.map((issue, index) => (
              <li key={`${index}-${issue}`}>{issue}</li>
            ))}
          </ul>
        </div>
      )}

      {row.campaign_id && (
        <div
          className={`rounded-xl border p-4 text-sm flex flex-wrap items-center justify-between gap-3 shadow-xs ${
            isWhatsApp
              ? 'bg-emerald-50/70 border-emerald-300 text-emerald-950'
              : 'bg-emerald-50 border-emerald-200 text-emerald-900'
          }`}
        >
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold">
                {isWhatsApp ? 'Validated WhatsApp Brief Reference:' : 'Remote MoEngage Campaign ID:'}
              </span>
              <code className="bg-emerald-100 text-emerald-950 px-2 py-0.5 rounded font-mono font-bold text-xs">
                {row.campaign_id}
              </code>
            </div>
            <p className="text-xs text-emerald-800 mt-1 max-w-xl">
              {isWhatsApp
                ? 'WhatsApp draft created and verified for MoEngage. Click "Automate All WhatsApp Drafts" for bulk studio automation, or open directly in studio below.'
                : 'Confirmed draft created in your MoEngage Live workspace via V5 API. View under Campaigns → Drafts.'}
            </p>
          </div>
          {isWhatsApp && (
            <a
              href="https://dashboard-03.moengage.com/v4/whatsapp/create/one-time/"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-emerald-700 text-white font-bold text-xs hover:bg-emerald-800 transition-colors shadow-sm shrink-0"
            >
              Open in MoEngage WhatsApp Studio ↗
            </a>
          )}
        </div>
      )}

      {uncertain && !row.campaign_id && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm font-semibold text-amber-800 bg-amber-50 p-3 rounded-lg border border-amber-200">
          <div>
            <span>⚠️ Previous attempt was unconfirmed.</span>
            <p className="text-xs text-amber-700 font-normal mt-0.5">
              No remote campaign ID was registered yet. You can retry creating this row.
            </p>
          </div>
          {batch && (
            <button
              type="button"
              disabled={busy}
              onClick={() => onCreate(row)}
              className="rounded-lg bg-amber-700 px-3.5 py-1.5 text-xs font-bold text-white hover:bg-amber-800 disabled:opacity-50 transition-colors"
            >
              Retry Create…
            </button>
          )}
        </div>
      )}

      {batch && ready && !uncertain && !row.campaign_id && (
        <button
          type="button"
          disabled={busy}
          onClick={() => onCreate(row)}
          className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-semibold text-white hover:bg-blue-800 disabled:opacity-50 transition-colors shadow-sm"
        >
          Create Only This Draft…
        </button>
      )}
    </article>
  );
}

export default function MoEngageCampaignsPage() {
  const { currentUser, authLoading } = useApp();
  const superadmin = currentUser?.tenant_id === 'all' && currentUser.role === 'superadmin';
  const [selectedAccount, setSelectedAccount] = useState('tata');
  const account = superadmin ? selectedAccount : currentUser?.tenant_id || '';
  const allowed = !!currentUser && (account === 'tata' || account === 'bajaj') && (superadmin || currentUser.tenant_id === account);

  const [activeTab, setActiveTab] = useTabState<'batch' | 'single' | 'templates'>('moe_active_tab', 'single');
  const [catalog, setCatalog] = useState<MoEngageCatalog | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);

  const [automatingWa, setAutomatingWa] = useState(false);
  // Single form builder state
  const [singleChannel, setSingleChannel] = useTabState<'WHATSAPP' | 'EMAIL' | 'PUSH'>('moe_single_channel', 'WHATSAPP');
  const [singleName, setSingleName] = useTabState<string>('moe_single_name', '');
  const [singleSegment, setSingleSegment] = useTabState<string>('moe_single_segment', '');
  const [singleDate, setSingleDate] = useTabState<string>('moe_single_date', '2026-10-15T10:30');
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
  const [singleClickUrl, setSingleClickUrl] = useTabState<string>('moe_single_click_url', 'https://tatacapital.com');
  // WhatsApp fields
  const [singleWaSender, setSingleWaSender] = useTabState<string>('moe_single_wa_sender', '');
  const [singleWaTemplate, setSingleWaTemplate] = useTabState<string>('moe_single_wa_template', '');
  // Batch & Spreadsheet state
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<MoEngageDraftPreview | null>(null);
  const [batch, setBatch] = useState<MoEngageDraftBatch | null>(null);
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
    fetchMoEngageCatalog(account)
      .then((cat) => {
        if (!active) return;
        setCatalog(cat);
        // Pre-populate sensible defaults
        if (cat.segments?.[0]) setSingleSegment(cat.segments[0].id);
        if (cat.email_senders?.[0]) setSingleEmailSender(cat.email_senders[0].from_address);
        if (cat.whatsapp_senders?.[0]) setSingleWaSender(cat.whatsapp_senders[0].sender_name);
        if (cat.whatsapp_templates?.[0]) setSingleWaTemplate(cat.whatsapp_templates[0].id);
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
    const id = urlId || localStorage.getItem(storageKey);
    if (!id) return;
    setLoading(true);
    fetchMoEngageDraftBatch(id, account)
      .then((result) => {
        if (active) showBatch(result, storageKey);
      })
      .catch((cause: unknown) => {
        if (active) {
          localStorage.removeItem(storageKey);
          const url = new URL(window.location.href);
          url.searchParams.delete('batch');
          window.history.replaceState(null, '', url.toString());
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [account, allowed, storageKey, showBatch]);

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
      setNotice('Batch staged successfully. Select any ready row to create a draft in MoEngage.');
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
      setError(`Could not read batch: ${cause instanceof Error ? cause.message : String(cause)}`);
    } finally {
      setBusy(false);
    }
  };

  const createRow = async (row: MoEngageDraftRow) => {
    if (!batch || batchScope !== storageKey || busy || createInFlight.current) return;
    if (row.status !== 'preview_ready' && row.status !== 'UNCERTAIN') return;

    const isRetry = row.status === 'UNCERTAIN';
    const name = row.source_fields?.campaign_name || row.candidate_v5_payload?.basic_details?.name || 'unnamed campaign';
    const confirmPrompt = isRetry
      ? `Retry creating MoEngage ${row.channel} DRAFT for ${account.toUpperCase()}?\n\nCampaign: ${name}\nRow: ${row.row_id}`
      : `Create MoEngage ${row.channel} DRAFT for ${account.toUpperCase()}?\n\nCampaign: ${name}\nPhysical Row: ${row.row_id}\n\nThis will create a confirmed DRAFT in your MoEngage workspace. It will NOT publish, send, or dispatch messages to customers.`;

    if (!window.confirm(confirmPrompt)) return;

    if (isRetry && currentUser) {
      localStorage.removeItem(`moengage_draft_uncertain:${currentUser.id}:${account}:${batch.batch_id}:${row.row_id}`);
      setUncertainRows((rows) => rows.filter((r) => r !== row.row_id));
    }

    createInFlight.current = true;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await createMoEngageDraftRow(batch.batch_id, row.row_id, account);
      showBatch(result, storageKey);
      setNotice(`Created draft successfully! Review the confirmed campaign ID below.`);
    } catch (cause) {
      const errStr = cause instanceof Error ? cause.message : String(cause);
      const isTimeout = errStr.includes('504') || errStr.toLowerCase().includes('timeout') || errStr.toLowerCase().includes('network');
      if (isTimeout) {
        const marker = `moengage_draft_uncertain:${currentUser?.id}:${account}:${batch.batch_id}:${row.row_id}`;
        localStorage.setItem(marker, '1');
        setUncertainRows((rows) => [...rows, row.row_id]);
        setError(`Create result uncertain for row ${row.row_id}: ${errStr}. Re-read the batch to confirm state.`);
      } else {
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
      if (r.status === 'preview_ready' || r.campaign_id) {
        localStorage.removeItem(`moengage_draft_uncertain:${currentUser.id}:${account}:${batch.batch_id}:${r.row_id}`);
      }
    });
    setUncertainRows(
      batch.items
        .filter((r) => r.status === 'UNCERTAIN' || localStorage.getItem(`moengage_draft_uncertain:${currentUser.id}:${account}:${batch.batch_id}:${r.row_id}`) === '1')
        .map((r) => r.row_id)
    );
  }, [batch, currentUser, account]);
  const handleAutomateWhatsApp = async () => {
    if (!batch || busy || automatingWa) return;
    const pendingWa = batch.items.filter(
      (r) => r.channel?.toUpperCase() === 'WHATSAPP' && (!r.campaign_id || r.status !== 'VALIDATED')
    );
    if (pendingWa.length === 0) return;

    if (
      !window.confirm(
        `Start automated creation of ${pendingWa.length} WhatsApp drafts in MoEngage?

The server's background automation worker will open the MoEngage studio, fill in each campaign name, select your Karix sender and template, and save each draft directly in MoEngage.`
      )
    )
      return;

    setAutomatingWa(true);
    setError('');
    setNotice('');
    try {
      const res = await automateMoEngageWhatsAppBatch(batch.batch_id, account);
      showBatch(await fetchMoEngageDraftBatch(batch.batch_id, account), storageKey);
      if (res.failed > 0) {
        setError(`Automated ${res.created} drafts in MoEngage, but ${res.failed} had issues. Check the cards below.`);
      } else {
        setNotice(`Successfully created all ${res.created} WhatsApp drafts in MoEngage! Verified in Drafts.`);
      }
    } catch (err) {
      setError(`WhatsApp automation error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setAutomatingWa(false);
    }
  };

  const handleCreateFromSingleForm = async () => {
    if (busy || !singleName.trim() || !singleSegment) {
      setError('Campaign Name and Target Audience are required.');
      return;
    }

    // Build a CSV file from the form data and stage/create it
    setBusy(true);
    setError('');
    setNotice('');

    try {
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
      ];

      // Format ISO datetime with timezone
      const isoSchedule = `${singleDate}:00+05:30`;

      const values = [
        singleChannel,
        singleName.trim(),
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
        singleChannel === 'PUSH' ? singleClickUrl : '',
        singleChannel === 'WHATSAPP' ? singleWaSender : '',
        singleChannel === 'WHATSAPP' ? singleWaTemplate : '',
      ];

      const csvContent = `${headers.join(',')}\n${values.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(',')}`;
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const syntheticFile = new File([blob], `single_${singleChannel.toLowerCase()}_${Date.now()}.csv`, { type: 'text/csv' });

      const stagedBatch = await stageMoEngageDraftBatch(syntheticFile, account);
      showBatch(stagedBatch, storageKey);
      setActiveTab('batch');
      setNotice(`Campaign staged in workspace queue. Click "Create Only This Draft…" on Row 2 to create the remote draft.`);
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
    ];

    const segId = catalog?.segments?.[0]?.id || '65cf4af4d4c88174e5ad186e';

    if (type === 'all' || type === 'whatsapp') {
      rows.push([
        'WHATSAPP',
        'TATA_TEST_DRAFT_WA_OCT01',
        segId,
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
        'Tata Capital Financial Services Limited',
        'test_1234',
      ]);
    }
    if (type === 'all' || type === 'push') {
      rows.push([
        'PUSH',
        'TATA_TEST_DRAFT_PUSH_OCT01',
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
        'https://tatacapital.com',
        '',
        '',
      ]);
    }
    if (type === 'all' || type === 'email') {
      rows.push([
        'EMAIL',
        'TATA_TEST_DRAFT_EMAIL_OCT01',
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

  if (authLoading) return <p className="p-8 text-center text-gray-500">Checking credentials…</p>;
  if (!allowed) {
    return (
      <div className="max-w-3xl mx-auto rounded-xl bg-rose-50 border border-rose-200 p-8 text-rose-900 shadow-sm mt-8 text-center">
        <h2 className="text-xl font-bold mb-2">Access Denied</h2>
        <p className="text-sm">MoEngage campaign authoring requires a signed-in operator for {account || 'this account'}.</p>
      </div>
    );
  }

  return (
    <main className="max-w-6xl mx-auto space-y-6 pb-24 px-4 sm:px-6">
      {/* Top Header */}
      <header className="space-y-3 border-b border-gray-200 pb-5 pt-2">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center justify-center w-8 h-8 rounded-lg bg-blue-600 text-white font-bold text-sm">
                ME
              </span>
              <h1 className="text-2xl font-bold text-gray-900 tracking-tight">MoEngage Campaign Builder</h1>
            </div>
            <p className="text-sm text-gray-500 mt-1">
              Create and validate WhatsApp, Push & Email drafts in <strong>{account.toUpperCase()}</strong> with zero publishing risk.
            </p>
          </div>

          <div className="flex items-center gap-3">
            {superadmin && (
              <label className="inline-flex items-center gap-2 text-xs font-semibold text-gray-700 bg-gray-50 border border-gray-200 px-3 py-1.5 rounded-lg">
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
                  className="bg-white border border-gray-300 rounded px-2 py-0.5 font-bold text-gray-900"
                >
                  <option value="tata">Tata Capital</option>
                  <option value="bajaj">Bajaj Finserv</option>
                </select>
              </label>
            )}

            <div className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-800 bg-emerald-50 border border-emerald-200 px-3 py-1.5 rounded-lg shadow-xs">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              Connected: {catalog?.workspace_id || '0KYUNUW5WODKX5ZFVAGPVL0U'} (DC03)
            </div>
          </div>
        </div>

        {/* Safety Banner */}
        <div className="rounded-xl border border-blue-200 bg-blue-50/70 p-3.5 text-xs text-blue-950 flex items-start gap-2.5">
          <span className="text-base select-none">🛡️</span>
          <div>
            <strong className="font-semibold text-blue-900">Guaranteed Draft-Only Isolation:</strong> All campaigns are created strictly in
            <code className="mx-1 px-1.5 py-0.5 rounded bg-blue-100 font-mono font-bold text-blue-900">DRAFT</code>
            status. The builder never sends messages to customers, never publishes, and never schedules automated sends. Publishing requires manual review and sign-off in the MoEngage dashboard.
          </div>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-gray-200 gap-6 pt-2 text-sm font-semibold">
          <button
            type="button"
            onClick={() => setActiveTab('single')}
            className={`pb-3 border-b-2 transition-colors flex items-center gap-2 ${
              activeTab === 'single'
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-900'
            }`}
          >
            <span>✨</span> Single Campaign Builder
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('batch')}
            className={`pb-3 border-b-2 transition-colors flex items-center gap-2 ${
              activeTab === 'batch'
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-900'
            }`}
          >
            <span>📊</span> Spreadsheet Batch Upload
            {batch && <span className="ml-1 px-1.5 py-0.5 rounded-full text-xs bg-blue-100 text-blue-800">{batch.items.length}</span>}
          </button>
          <button
            type="button"
            onClick={() => setActiveTab('templates')}
            className={`pb-3 border-b-2 transition-colors flex items-center gap-2 ${
              activeTab === 'templates'
                ? 'border-blue-600 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-900'
            }`}
          >
            <span>📥</span> Sample Templates & CSVs
          </button>
        </div>
      </header>

      {/* Global Alerts */}
      {error && (
        <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900 flex items-start gap-2.5 shadow-xs">
          <span>⚠️</span>
          <div className="flex-1">{error}</div>
          <button type="button" onClick={() => setError('')} className="text-rose-500 hover:text-rose-800 font-bold">✕</button>
        </div>
      )}
      {notice && (
        <div role="status" className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900 flex items-start gap-2.5 shadow-xs">
          <span>✅</span>
          <div className="flex-1 font-medium">{notice}</div>
          <button type="button" onClick={() => setNotice('')} className="text-emerald-500 hover:text-emerald-800 font-bold">✕</button>
        </div>
      )}

      {/* TAB 1: SINGLE CAMPAIGN BUILDER */}
      {activeTab === 'single' && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          {/* Left Form: 7 cols */}
          <div className="lg:col-span-7 space-y-6">
            {/* Step 1: Channel selection */}
            <section className="bg-white rounded-2xl border border-gray-200 p-5 shadow-xs space-y-3">
              <h2 className="text-sm font-bold text-gray-900 uppercase tracking-wider">1. Select Channel</h2>
              <div className="grid grid-cols-3 gap-3">
                <button
                  type="button"
                  onClick={() => setSingleChannel('WHATSAPP')}
                  className={`p-3.5 rounded-xl border text-left transition-all ${
                    singleChannel === 'WHATSAPP'
                      ? 'border-emerald-500 bg-emerald-50/50 shadow-xs ring-2 ring-emerald-400/20'
                      : 'border-gray-200 hover:border-gray-300 bg-white'
                  }`}
                >
                  <div className="text-2xl mb-1">💬</div>
                  <div className="font-bold text-sm text-gray-900">WhatsApp</div>
                  <div className="text-xs text-gray-500 mt-0.5">Karix BSP Templates</div>
                </button>

                <button
                  type="button"
                  onClick={() => setSingleChannel('PUSH')}
                  className={`p-3.5 rounded-xl border text-left transition-all ${
                    singleChannel === 'PUSH'
                      ? 'border-purple-500 bg-purple-50/50 shadow-xs ring-2 ring-purple-400/20'
                      : 'border-gray-200 hover:border-gray-300 bg-white'
                  }`}
                >
                  <div className="text-2xl mb-1">🔔</div>
                  <div className="font-bold text-sm text-gray-900">Push App</div>
                  <div className="text-xs text-gray-500 mt-0.5">Android & iOS Push</div>
                </button>

                <button
                  type="button"
                  onClick={() => setSingleChannel('EMAIL')}
                  className={`p-3.5 rounded-xl border text-left transition-all ${
                    singleChannel === 'EMAIL'
                      ? 'border-blue-500 bg-blue-50/50 shadow-xs ring-2 ring-blue-400/20'
                      : 'border-gray-200 hover:border-gray-300 bg-white'
                  }`}
                >
                  <div className="text-2xl mb-1">✉️</div>
                  <div className="font-bold text-sm text-gray-900">Email</div>
                  <div className="text-xs text-gray-500 mt-0.5">SendGrid / HTML</div>
                </button>
              </div>
            </section>

            {/* Step 2: Campaign basics */}
            <section className="bg-white rounded-2xl border border-gray-200 p-5 shadow-xs space-y-4">
              <h2 className="text-sm font-bold text-gray-900 uppercase tracking-wider">2. Campaign Details & Audience</h2>

              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1">Campaign Name *</label>
                <input
                  type="text"
                  placeholder="e.g. TATA_FESTIVE_SPECIAL_OCT2026"
                  value={singleName}
                  onChange={(e) => setSingleName(e.target.value)}
                  className="w-full rounded-lg border border-gray-300 px-3.5 py-2 text-sm focus:border-blue-500 focus:outline-none"
                />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">Target Audience Segment *</label>
                  <select
                    value={singleSegment}
                    onChange={(e) => setSingleSegment(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  >
                    {catalog?.segments?.map((seg) => (
                      <option key={seg.id} value={seg.id}>
                        {seg.name} ({seg.id.slice(0, 8)}…)
                      </option>
                    ))}
                    <option value="65cf4af4d4c88174e5ad186e">Test_FSTP_Pranav_1602 (Approved Test Base)</option>
                    <option value="6ab60caace27e15e345f59c1">CUG_UAT_25_Jun_26</option>
                    <option value="6a201689e6f094a2d031e478">HL_UAT_03_JUN_2026</option>
                  </select>
                </div>

                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1">Schedule Start Time (IST)</label>
                  <input
                    type="datetime-local"
                    value={singleDate}
                    onChange={(e) => setSingleDate(e.target.value)}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                  />
                </div>
              </div>
            </section>

            {/* Step 3: Channel-specific content */}
            <section className="bg-white rounded-2xl border border-gray-200 p-5 shadow-xs space-y-4">
              <h2 className="text-sm font-bold text-gray-900 uppercase tracking-wider">3. {singleChannel} Content</h2>

              {singleChannel === 'WHATSAPP' && (
                <div className="space-y-4">
                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1">WhatsApp Sender (Karix)</label>
                    <select
                      value={singleWaSender}
                      onChange={(e) => setSingleWaSender(e.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none"
                    >
                      {catalog?.whatsapp_senders?.map((s) => (
                        <option key={s.phone_number} value={s.sender_name}>
                          {s.sender_name} ({s.phone_number}) · {s.provider}
                        </option>
                      ))}
                      <option value="Tata Capital Financial Services Limited">
                        Tata Capital Financial Services Limited (919643789719)
                      </option>
                      <option value="Tata Capital Wealth">Tata Capital Wealth (918657597116)</option>
                      <option value="Tata Capital Housing Finance Limited">Tata Capital Housing Finance Limited (919594951475)</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1">Approved WhatsApp Template ID</label>
                    <input
                      type="text"
                      placeholder="e.g. test_1234"
                      value={singleWaTemplate}
                      onChange={(e) => setSingleWaTemplate(e.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-emerald-500 focus:outline-none"
                    />
                    <p className="text-xs text-gray-500 mt-1">Must be an approved template synced from Karix into MoEngage.</p>
                  </div>
                </div>
              )}

              {singleChannel === 'PUSH' && (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-semibold text-gray-700 mb-1">Platform</label>
                      <select
                        value={singlePushPlatform}
                        onChange={(e) => setSinglePushPlatform(e.target.value)}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
                      >
                        <option value="ANDROID">Android (general channel)</option>
                        <option value="IOS">iOS (APNS)</option>
                      </select>
                    </div>

                    <div>
                      <label className="block text-xs font-semibold text-gray-700 mb-1">Deeplink / Click URL</label>
                      <input
                        type="url"
                        value={singleClickUrl}
                        onChange={(e) => setSingleClickUrl(e.target.value)}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono text-xs focus:border-purple-500 focus:outline-none"
                      />
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1">Notification Title</label>
                    <input
                      type="text"
                      placeholder="e.g. Exclusive Loan Offer Available!"
                      value={singlePushTitle}
                      onChange={(e) => setSinglePushTitle(e.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-purple-500 focus:outline-none"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1">Notification Body</label>
                    <textarea
                      rows={3}
                      placeholder="e.g. Check your pre-qualified offer up to ₹ 90 lacs with instant approval."
                      value={singlePushMessage}
                      onChange={(e) => setSinglePushMessage(e.target.value)}
                      className="w-full rounded-lg border border-gray-300 p-3 text-sm focus:border-purple-500 focus:outline-none"
                    />
                  </div>
                </div>
              )}

              {singleChannel === 'EMAIL' && (
                <div className="space-y-4">
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <label className="block text-xs font-semibold text-gray-700 mb-1">Sender Address (SendGrid)</label>
                      <select
                        value={singleEmailSender}
                        onChange={(e) => setSingleEmailSender(e.target.value)}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
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
                      <label className="block text-xs font-semibold text-gray-700 mb-1">Content Type</label>
                      <select
                        value={singleContentType}
                        onChange={(e) => setSingleContentType(e.target.value)}
                        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                      >
                        <option value="PROMOTIONAL">PROMOTIONAL</option>
                        <option value="TRANSACTIONAL">TRANSACTIONAL</option>
                      </select>
                    </div>
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1">Email Subject Line</label>
                    <input
                      type="text"
                      placeholder="e.g. Your Monthly Financial Statement is Ready"
                      value={singleSubject}
                      onChange={(e) => setSingleSubject(e.target.value)}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                    />
                  </div>

                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1">HTML Email Content</label>
                    <textarea
                      rows={5}
                      value={singleHtml}
                      onChange={(e) => setSingleHtml(e.target.value)}
                      className="w-full rounded-lg border border-gray-300 p-3 font-mono text-xs focus:border-blue-500 focus:outline-none"
                    />
                  </div>
                </div>
              )}

              <div className="pt-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void handleCreateFromSingleForm()}
                  className="w-full rounded-xl bg-blue-600 px-5 py-3 text-sm font-bold text-white hover:bg-blue-700 disabled:opacity-50 transition-colors shadow-sm flex items-center justify-center gap-2"
                >
                  {busy ? 'Preparing Draft…' : `Stage & Create ${singleChannel} Draft →`}
                </button>
              </div>
            </section>
          </div>

          {/* Right Live Preview: 5 cols */}
          <div className="lg:col-span-5 space-y-4 sticky top-6">
            <h2 className="text-sm font-bold text-gray-900 uppercase tracking-wider flex items-center gap-2">
              <span>📱</span> Live Message Preview
            </h2>

            {singleChannel === 'WHATSAPP' && (
              <div className="rounded-3xl border-4 border-gray-800 bg-[#EFEAE2] p-4 shadow-xl max-w-sm mx-auto overflow-hidden">
                <div className="bg-[#075E54] text-white px-3 py-2 rounded-t-xl flex items-center gap-2 -m-4 mb-4">
                  <div className="w-8 h-8 rounded-full bg-white/20 flex items-center justify-center font-bold text-xs">TC</div>
                  <div className="flex-1 min-w-0">
                    <div className="text-xs font-bold truncate">Tata Capital</div>
                    <div className="text-[10px] text-emerald-200">Official Business Account</div>
                  </div>
                </div>

                <div className="bg-white rounded-lg p-3 shadow-xs space-y-2 text-xs text-gray-800 relative max-w-[90%]">
                  <div className="font-semibold text-gray-900">
                    {singleName || 'Tata Capital Notification'}
                  </div>
                  <p className="text-gray-700 whitespace-pre-wrap">
                    Template: <code className="bg-gray-100 px-1 py-0.5 rounded text-[11px] font-mono">{singleWaTemplate || 'test_1234'}</code>
                  </p>
                  <p className="text-[11px] text-gray-600">
                    Thank you for banking with Tata Capital. Your transaction details and verification alerts will be sent through this channel.
                  </p>
                  <div className="text-[10px] text-gray-400 text-right">05:16 PM ✓✓</div>
                </div>
              </div>
            )}

            {singleChannel === 'PUSH' && (
              <div className="rounded-3xl border-4 border-gray-800 bg-gray-100 p-4 shadow-xl max-w-sm mx-auto">
                <div className="text-[11px] text-gray-500 font-semibold mb-2">Notification Center</div>
                <div className="bg-white rounded-xl p-3.5 shadow-sm border border-gray-200 flex items-start gap-3">
                  <div className="w-9 h-9 rounded-lg bg-blue-600 text-white flex items-center justify-center text-xs font-bold shrink-0">
                    TC
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between text-[11px] text-gray-500">
                      <span className="font-bold text-gray-700 uppercase">Tata Capital</span>
                      <span>now</span>
                    </div>
                    <div className="font-semibold text-gray-900 text-xs mt-0.5 truncate">
                      {singlePushTitle || 'Exclusive Offer Available'}
                    </div>
                    <p className="text-xs text-gray-600 mt-0.5 line-clamp-2">
                      {singlePushMessage || 'Check your pre-qualified offer up to ₹ 90 lacs with instant approval.'}
                    </p>
                  </div>
                </div>
              </div>
            )}

            {singleChannel === 'EMAIL' && (
              <div className="rounded-2xl border border-gray-300 bg-white p-4 shadow-sm space-y-3">
                <div className="border-b border-gray-200 pb-2 text-xs space-y-1">
                  <div>
                    <span className="text-gray-500">From:</span>{' '}
                    <span className="font-medium text-gray-900">Tata Capital &lt;{singleEmailSender || 'hello@info.tatacapital.co.in'}&gt;</span>
                  </div>
                  <div>
                    <span className="text-gray-500">Subject:</span>{' '}
                    <span className="font-semibold text-gray-900">{singleSubject || 'Tata Capital Special Announcement'}</span>
                  </div>
                </div>
                <div
                  className="rounded-lg bg-gray-50 border border-gray-200 p-4 min-h-[160px] text-xs text-gray-800 prose prose-sm max-w-none"
                  dangerouslySetInnerHTML={{ __html: singleHtml || '<p>Email preview will appear here.</p>' }}
                />
              </div>
            )}
          </div>
        </div>
      )}

      {/* TAB 2: SPREADSHEET BATCH UPLOAD */}
      {activeTab === 'batch' && (
        <div className="space-y-6">
          <section className="rounded-2xl border border-gray-200 bg-white p-6 shadow-xs space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-bold text-gray-900">Upload Campaign Spreadsheet</h2>
                <p className="text-xs text-gray-500 mt-0.5">
                  Upload a <code>.csv</code> or <code>.xlsx</code> file containing campaigns across WhatsApp, Push, and Email.
                </p>
              </div>

              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => downloadSampleCsv('all')}
                  className="text-xs font-semibold text-blue-700 bg-blue-50 border border-blue-200 px-3 py-1.5 rounded-lg hover:bg-blue-100"
                >
                  📥 Download 3-Channel Sample CSV
                </button>
              </div>
            </div>

            <input
              ref={fileRef}
              type="file"
              accept=".csv,.xlsx"
              disabled={busy}
              onChange={(e) => void chooseFile(e.target.files?.[0])}
              className="block w-full text-sm file:mr-4 file:rounded-xl file:border-0 file:bg-blue-50 file:px-4 file:py-2.5 file:font-semibold file:text-blue-700 hover:file:bg-blue-100"
            />
          </section>

          {/* Preview Section */}
          {preview?.account === account && (
            <section className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3 bg-white p-4 rounded-xl border border-gray-200 shadow-xs">
                <div>
                  <h2 className="text-base font-bold text-gray-900">
                    Spreadsheet Preview · <span className="font-mono text-sm text-gray-600">{file?.name}</span>
                  </h2>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Ready: <strong className="text-emerald-700">{preview.ready}</strong> · Blocked:{' '}
                    <strong className="text-rose-700">{preview.blocked}</strong> · Workspace:{' '}
                    <span className="font-mono">{preview.workspace_id}</span>
                  </p>
                </div>

                <button
                  type="button"
                  disabled={busy}
                  onClick={() => void stage()}
                  className="rounded-xl bg-blue-700 px-5 py-2.5 text-sm font-bold text-white hover:bg-blue-800 disabled:opacity-50 transition-colors shadow-sm"
                >
                  Stage Reviewed File →
                </button>
              </div>

              {/* Channel Filter Chips */}
              <div className="flex gap-2 text-xs font-semibold">
                {(['ALL', 'WHATSAPP', 'EMAIL', 'PUSH'] as const).map((ch) => (
                  <button
                    key={ch}
                    type="button"
                    onClick={() => setFilterChannel(ch)}
                    className={`px-3 py-1.5 rounded-lg border transition-colors ${
                      filterChannel === ch
                        ? 'bg-blue-600 text-white border-blue-600'
                        : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50'
                    }`}
                  >
                    {ch}
                  </button>
                ))}
              </div>

              <div className="space-y-4">
                {filteredPreviewItems.map((row, index) => (
                  <RowCard key={`${row.source_ref}:${row.row_id}:${index}`} row={row} batch={false} busy={busy} uncertain={false} onCreate={createRow} />
                ))}
              </div>
            </section>
          )}

          {/* Staged Batch Queue Section */}
          {loading && <p className="text-center text-sm text-gray-500 py-6">Loading saved batch…</p>}

          {batchScope === storageKey && batch?.account === account && (
            <section className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3 bg-white p-4 rounded-xl border border-gray-200 shadow-xs">
                <div>
                  <h2 className="text-base font-bold text-gray-900">
                    Staged Batch Queue · <span className="font-mono text-xs text-blue-700 bg-blue-50 px-2 py-0.5 rounded">{batch.batch_id}</span>
                  </h2>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Source: <span className="font-mono">{batch.source_ref}</span> · Ready:{' '}
                    <strong className="text-emerald-700">{batch.ready}</strong> · Blocked:{' '}
                    <strong className="text-rose-700">{batch.blocked}</strong>
                  </p>
                </div>

                <div className="flex flex-wrap items-center gap-2">
                  {batch.items.some((r) => r.channel?.toUpperCase() === 'WHATSAPP' && (!r.campaign_id || r.status !== 'VALIDATED')) && (
                    <button
                      type="button"
                      disabled={busy || automatingWa}
                      onClick={() => void handleAutomateWhatsApp()}
                      className="rounded-xl bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 text-xs font-bold disabled:opacity-50 transition-colors shadow-xs flex items-center gap-1.5"
                    >
                      {automatingWa ? '⚡ Automating in MoEngage…' : '⚡ Automate All WhatsApp Drafts in MoEngage'}
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={busy || automatingWa}
                    onClick={() => void refreshBatch()}
                    className="rounded-xl border border-gray-300 px-4 py-2 text-xs font-bold text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                  >
                    🔄 Refresh Stored State
                  </button>
                </div>
              </div>
              {/* Channel Filter Chips */}
              <div className="flex gap-2 text-xs font-semibold">
                {(['ALL', 'WHATSAPP', 'EMAIL', 'PUSH'] as const).map((ch) => (
                  <button
                    key={ch}
                    type="button"
                    onClick={() => setFilterChannel(ch)}
                    className={`px-3 py-1.5 rounded-lg border transition-colors ${
                      filterChannel === ch
                        ? 'bg-blue-600 text-white border-blue-600'
                        : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50'
                    }`}
                  >
                    {ch}
                  </button>
                ))}
              </div>

              <div className="space-y-4">
                {filteredBatchItems.map((row, index) => (
                  <RowCard
                    key={`${row.source_ref}:${row.row_id}:${index}`}
                    row={row}
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
          <section className="bg-white rounded-2xl border border-gray-200 p-6 shadow-xs space-y-4">
            <h2 className="text-base font-bold text-gray-900">One-Click Sample CSV Templates</h2>
            <p className="text-sm text-gray-600">
              Download pre-formatted sample spreadsheets ready to upload. All samples use your approved test segment{' '}
              <code>Test_FSTP_Pranav_1602</code>.
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 pt-2">
              <button
                type="button"
                onClick={() => downloadSampleCsv('all')}
                className="p-4 rounded-xl border border-blue-200 bg-blue-50/50 hover:bg-blue-100/50 text-left transition-colors"
              >
                <div className="text-2xl mb-1">📦</div>
                <div className="font-bold text-sm text-blue-900">Combined 3-Channel</div>
                <div className="text-xs text-blue-700 mt-1">WhatsApp + Push + Email</div>
              </button>

              <button
                type="button"
                onClick={() => downloadSampleCsv('whatsapp')}
                className="p-4 rounded-xl border border-emerald-200 bg-emerald-50/50 hover:bg-emerald-100/50 text-left transition-colors"
              >
                <div className="text-2xl mb-1">💬</div>
                <div className="font-bold text-sm text-emerald-900">WhatsApp Only</div>
                <div className="text-xs text-emerald-700 mt-1">Karix BSP Senders</div>
              </button>

              <button
                type="button"
                onClick={() => downloadSampleCsv('push')}
                className="p-4 rounded-xl border border-purple-200 bg-purple-50/50 hover:bg-purple-100/50 text-left transition-colors"
              >
                <div className="text-2xl mb-1">🔔</div>
                <div className="font-bold text-sm text-purple-900">Push Only</div>
                <div className="text-xs text-purple-700 mt-1">Android App Push</div>
              </button>

              <button
                type="button"
                onClick={() => downloadSampleCsv('email')}
                className="p-4 rounded-xl border border-indigo-200 bg-indigo-50/50 hover:bg-indigo-100/50 text-left transition-colors"
              >
                <div className="text-2xl mb-1">✉️</div>
                <div className="font-bold text-sm text-indigo-900">Email Only</div>
                <div className="text-xs text-indigo-700 mt-1">SendGrid HTML</div>
              </button>
            </div>
          </section>

          <section className="bg-white rounded-2xl border border-gray-200 p-6 shadow-xs space-y-4">
            <h2 className="text-base font-bold text-gray-900">Spreadsheet Column Specifications</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b border-gray-200 bg-gray-50 font-bold text-gray-700">
                    <th className="p-2.5">Column Header</th>
                    <th className="p-2.5">Channel</th>
                    <th className="p-2.5">Required?</th>
                    <th className="p-2.5">Description / Example</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 text-gray-800">
                  <tr>
                    <td className="p-2.5 font-mono font-bold text-blue-700">channel</td>
                    <td className="p-2.5">All</td>
                    <td className="p-2.5 font-bold text-rose-700">Yes</td>
                    <td className="p-2.5"><code>WHATSAPP</code>, <code>PUSH</code>, or <code>EMAIL</code></td>
                  </tr>
                  <tr>
                    <td className="p-2.5 font-mono font-bold text-blue-700">campaign_name</td>
                    <td className="p-2.5">All</td>
                    <td className="p-2.5 font-bold text-rose-700">Yes</td>
                    <td className="p-2.5">Unique campaign name in MoEngage (min 5 chars)</td>
                  </tr>
                  <tr>
                    <td className="p-2.5 font-mono font-bold text-blue-700">segment_id</td>
                    <td className="p-2.5">All</td>
                    <td className="p-2.5 font-bold text-rose-700">Yes</td>
                    <td className="p-2.5">Saved audience ID (e.g. <code>65cf4af4d4c88174e5ad186e</code>)</td>
                  </tr>
                  <tr>
                    <td className="p-2.5 font-mono font-bold text-blue-700">scheduled_at</td>
                    <td className="p-2.5">All</td>
                    <td className="p-2.5 font-bold text-rose-700">Yes</td>
                    <td className="p-2.5">ISO datetime (e.g. <code>2026-10-15T10:30:00+05:30</code>)</td>
                  </tr>
                  <tr>
                    <td className="p-2.5 font-mono font-bold text-blue-700">timezone</td>
                    <td className="p-2.5">All</td>
                    <td className="p-2.5 font-bold text-rose-700">Yes</td>
                    <td className="p-2.5">IANA timezone (e.g. <code>Asia/Kolkata</code>)</td>
                  </tr>
                  <tr>
                    <td className="p-2.5 font-mono">whatsapp_sender</td>
                    <td className="p-2.5">WhatsApp</td>
                    <td className="p-2.5">Yes</td>
                    <td className="p-2.5">e.g. <code>Tata Capital Financial Services Limited</code></td>
                  </tr>
                  <tr>
                    <td className="p-2.5 font-mono">whatsapp_template_id</td>
                    <td className="p-2.5">WhatsApp</td>
                    <td className="p-2.5">Yes</td>
                    <td className="p-2.5">e.g. <code>test_1234</code></td>
                  </tr>
                  <tr>
                    <td className="p-2.5 font-mono">from_address</td>
                    <td className="p-2.5">Email</td>
                    <td className="p-2.5">Yes</td>
                    <td className="p-2.5">e.g. <code>hello@info.tatacapital.co.in</code></td>
                  </tr>
                  <tr>
                    <td className="p-2.5 font-mono">subject</td>
                    <td className="p-2.5">Email</td>
                    <td className="p-2.5">Yes</td>
                    <td className="p-2.5">Subject line for HTML emails</td>
                  </tr>
                  <tr>
                    <td className="p-2.5 font-mono">html_content</td>
                    <td className="p-2.5">Email</td>
                    <td className="p-2.5">Yes</td>
                    <td className="p-2.5">Raw HTML message body</td>
                  </tr>
                  <tr>
                    <td className="p-2.5 font-mono">push_title</td>
                    <td className="p-2.5">Push</td>
                    <td className="p-2.5">Yes</td>
                    <td className="p-2.5">Push notification title text</td>
                  </tr>
                  <tr>
                    <td className="p-2.5 font-mono">push_message</td>
                    <td className="p-2.5">Push</td>
                    <td className="p-2.5">Yes</td>
                    <td className="p-2.5">Notification body text</td>
                  </tr>
                  <tr>
                    <td className="p-2.5 font-mono">click_url</td>
                    <td className="p-2.5">Push</td>
                    <td className="p-2.5">Yes</td>
                    <td className="p-2.5">Target HTTPS click URL or deeplink</td>
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
