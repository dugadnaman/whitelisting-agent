'use client';

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useTabState } from '@/lib/tab-state';
import { useApp, getRcsDetails } from '@/lib/context';
import {
  fetchJiraProjects,
  fetchJiraIssues,
  fetchJiraBrief,
  submitJiraBrief,
  syncRcsTemplateToMoEngage,
  previewJiraDrafts,
  reportJiraValidation,
  uploadJiraCreative,
  fetchMoEngageCatalog,
  fetchMoEngageDraftWorkspaces,
  stageMoEngageDraftBatch,
  createMoEngageDraft,
  type MoEngageCatalog,
  type MoEngageDraftBatch,
  type AccountItem,
  type JiraProjectItem,
  type JiraIssueItem,
  type JiraBriefData,
  type JiraWhatsAppDraft,
  type JiraRcsDraft,
  type JiraSmsDraft,
  type DraftWarnings,
  type JiraCreativeSource,
  type JiraDraftPreviewRequest,
  type JiraDraftPreview,
} from '@/lib/api';
import { formatError, formatDate } from '@/lib/format';
import { JiraCreativeImage, JiraCreativeDownload } from '@/components/jira-creative';
import { carouselCardWarnings, carouselSelectionError, selectedRcsDraft, type SelectableRcsDraft } from '@/lib/jira-carousel';
import { newRcsTemplateName, normalizeNewTemplateName, WHITELIST_NAME_HINT } from '@/lib/jira-template-name';
import { destinationAccountLabel, destinationLabel } from '@/lib/destination';
import { SmsDltReview, smsDltDraft } from '@/components/sms-dlt';
import { TATA_CTA_URL, isUrlCta, normalizeWhatsAppCtas, normalizeRcsCtas, resolveCtaUrl } from '@/lib/cta';
import { CAMPAIGN_NAME_HINT, campaignRowName, normalizeCampaignFields, normalizeCampaignName, requireCampaignName } from '@/lib/campaign-name';
import type { SmsDltDraft } from '@/lib/api';
import { BRIEF_SMS_PAGE_SIZE, BRIEF_SMS_REVIEW_LIMIT, matchingBriefSmsIndices, briefSmsPage, selectBriefSmsIndices, selectedBriefSmsDrafts } from '@/lib/brief-sms';

const UNCHECKED_WARNINGS: DraftWarnings = {
  aspect_ratio_warnings: [],
  compliance_warnings: [],
  grammar_warnings: [],
};

function isAspectBlocked(draft: DraftWarnings) {
  return Boolean(draft.aspect_ratio_blocked || draft.aspect_ratio_warnings?.some((warning) => warning.blocked));
}

function DraftWarningList({ draft, showAspectWarnings = true }: { draft: DraftWarnings; showAspectWarnings?: boolean }) {
  const suggestions = draft.compliance_warnings?.filter((warning) => warning.severity !== 'error') || [];
  const suggestionCount = suggestions.length + (draft.grammar_warnings?.length || 0);
  return (
    <div className="space-y-2 text-xs">
      {showAspectWarnings && isAspectBlocked(draft) && (
        <p role="alert" className="font-medium text-rose-800">
          Whitelisting blocked: {draft.aspect_ratio_block_reason || 'Replace the creative with a compliant image.'}
        </p>
      )}
      {showAspectWarnings && draft.aspect_ratio_warnings?.map((warning, index) => (
        <div key={`aspect-${index}`} className="p-2 rounded-lg border border-rose-200 bg-rose-50 text-rose-900">
          <p className="font-medium">{warning.component}: {warning.error || warning.action || 'Image aspect ratio warning'}</p>
          <p>Original: {warning.original_size || 'Unknown'} · Current ratio: {warning.current_ratio || 'Unknown'} · Required: {warning.recommended_ratio || 'See recommendation'}</p>
          {warning.error && warning.action && <p>{warning.action}</p>}
        </div>
      ))}
      {draft.compliance_warnings?.filter((warning) => warning.severity === 'error').map((warning, index) => (
        <div role="alert" key={`compliance-${index}`} className="p-2 rounded-lg border border-rose-200 bg-rose-50 text-rose-900">
          <p className="font-medium">{warning.component ? `${warning.component}: ` : ''}{warning.severity === 'error' ? 'Compliance error' : 'Compliance warning'}: {warning.issue}</p>
          {warning.recommendation && <p>{warning.recommendation}</p>}
        </div>
      ))}
      {suggestionCount > 0 && <details className="rounded-lg border border-gray-200 p-2 text-gray-600">
        <summary className="cursor-pointer font-medium">Suggestions ({suggestionCount})</summary>
        <div className="mt-2 space-y-2">
        {suggestions.map((warning, index) => <div key={`suggestion-${index}`} className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-amber-900">
          <p>{warning.component ? `${warning.component}: ` : ''}{warning.issue}</p>
          {warning.recommendation && <p>{warning.recommendation}</p>}
        </div>)}
      {draft.grammar_warnings?.map((warning, index) => (
        <div key={`grammar-${index}`} className="p-2 rounded-lg border border-gray-200 bg-gray-50 text-gray-800">
          <p className="font-medium">{warning.component ? `${warning.component}: ` : ''}Grammar: {warning.issue}</p>
          {warning.suggestion && <p>{warning.suggestion}</p>}
          {warning.original && <p>Original: {warning.original}</p>}
          {warning.replacement && <p>Suggested: {warning.replacement}</p>}
        </div>
      ))}
        </div>
      </details>}
      {draft.duplicate_warning && (
        <p className="p-2 rounded-lg border border-amber-200 bg-amber-50 text-amber-900">
          Duplicate: {draft.duplicate_warning.message}
        </p>
      )}
    </div>
  );
}

type JiraPreviewSnapshot = {
  selectedKey: string;
  issueKey?: string;
  payload: JiraDraftPreviewRequest;
  attempt: number;
};

function BriefStatusBadge({ status }: { status?: string }) {
  const s = (status || 'Pending').toLowerCase().trim();
  let colorClass = 'bg-amber-50 text-amber-800 border-amber-200';
  let dotColor = 'bg-amber-500';
  let label = status || 'Pending';

  if (s === 'completed' || s === 'done' || s === 'approved' || s === 'whitelisted') {
    colorClass = 'bg-emerald-50 text-emerald-800 border-emerald-200';
    dotColor = 'bg-emerald-500';
    label = 'Completed';
  } else if (s === 'in progress' || s === 'in_progress' || s === 'review' || s === 'test sent' || s === 'submitted') {
    colorClass = 'bg-sky-50 text-sky-800 border-sky-200';
    dotColor = 'bg-sky-500';
    label = 'In Progress';
  } else if (s === 'failed' || s === 'rejected' || s === 'error') {
    colorClass = 'bg-rose-50 text-rose-800 border-rose-200';
    dotColor = 'bg-rose-500';
    label = 'Failed';
  } else if (s === 'not generated' || s === 'not_generated' || s === 'unparsed') {
    colorClass = 'bg-slate-100 text-slate-700 border-slate-300';
    dotColor = 'bg-slate-400';
    label = 'Not Generated';
  } else {
    colorClass = 'bg-amber-50 text-amber-800 border-amber-200';
    dotColor = 'bg-amber-500';
    label = 'Pending';
  }

  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-xs font-medium border shrink-0 ${colorClass}`}>
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotColor}`} />
      <span>{label}</span>
    </span>
  );
}

export default function JiraBriefsPage() {
  const { account, channel, user, accounts, getAccountLabel, setDestination } = useApp();
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);
  const [issues, setIssues] = useState<JiraIssueItem[]>([]);
  const [loadingIssues, setLoadingIssues] = useState(true);
  const [showTicketPicker, setShowTicketPicker] = useState(false);
  const [projectsList, setProjectsList] = useState<JiraProjectItem[]>([
    { key: 'ALL', name: 'All Tata Projects Combined' },
    { key: 'TCN', name: 'Tata Capital New' },
    { key: 'SWCM', name: 'TATA Service and wealth Campaign Manager' },
    { key: 'TM', name: 'Tata Moneyfy' },
    { key: 'TAT', name: 'Tata Capital Marketing' },
    { key: 'MON', name: 'Moneyfy Mobile' },
    { key: 'COL', name: 'Collections & Operations' },
  ]);
  const [project, setProject] = useTabState<string>('briefs_project', 'ALL');
  const [selectedKey, setSelectedKey] = useTabState<string>('briefs_selected_key', '');
  const [brief, setBrief] = useTabState<JiraBriefData | null>('briefs_data', null);
  const [loadingBrief, setLoadingBrief] = useState(false);
  const [campaignTypeFilter, setCampaignTypeFilter] = useTabState<'all' | 'messaging' | 'email'>('briefs_campaign_type', 'all');
  const [briefStatusFilter, setBriefStatusFilter] = useTabState<'all' | 'pending' | 'in_progress' | 'completed' | 'failed' | 'not_generated'>('briefs_status_filter', 'all');
  const [activeTab, setActiveTab] = useTabState<'whatsapp' | 'rcs' | 'sms' | 'email' | 'comments' | 'moengage'>('briefs_active_tab', channel);
  const [submitting, setSubmitting] = useState(false);
  const [confirmationMode, setConfirmationMode] = useState<'all' | 'whatsapp' | 'rcs' | null>(null);
  const [feedback, setFeedback] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [searchQuery, setSearchQuery] = useTabState('briefs_search', '');

  // Editable template drafts and selection sets
  const [waTemplates, setWaTemplates] = useTabState<JiraWhatsAppDraft[]>('briefs_wa_templates', []);
  const [rcsTemplates, setRcsTemplates] = useTabState<SelectableRcsDraft[]>('briefs_rcs_templates', []);
  const [smsTemplates, setSmsTemplates] = useTabState<JiraSmsDraft[]>('briefs_sms_templates', []);
  const [smsSearch, setSmsSearch] = useState('');
  const [smsPageNumber, setSmsPageNumber] = useState(1);
  const matchingSmsIndices = useMemo(() => matchingBriefSmsIndices(smsTemplates, smsSearch), [smsTemplates, smsSearch]);
  const smsPage = useMemo(() => briefSmsPage(matchingSmsIndices, smsPageNumber), [matchingSmsIndices, smsPageNumber]);
  useEffect(() => {
    // Migrate cached editable drafts once, without rewriting name/URL keystrokes.
    setWaTemplates((drafts) => drafts.map((draft) => normalizeWhatsAppCtas({ ...draft, template_name: normalizeNewTemplateName(draft.template_name) }, account)));
    setRcsTemplates((drafts) => drafts.map((draft) => normalizeRcsCtas({ ...draft, template_name: normalizeNewTemplateName(draft.template_name) }, account)));
  }, []);
  const [selectedWa, setSelectedWa] = useTabState<Set<number>>('briefs_selected_wa', new Set());
  const [selectedRcs, setSelectedRcs] = useTabState<Set<number>>('briefs_selected_rcs', new Set());
  const [selectedSms, setSelectedSms] = useTabState<Set<number>>('briefs_selected_sms', new Set());
  const selectedSmsDrafts = useMemo(() => selectedBriefSmsDrafts(smsTemplates, selectedSms), [smsTemplates, selectedSms]);
  const selectedSmsCount = selectedSmsDrafts.length;
  const smsPageSelected = smsPage.indices.length > 0 && smsPage.indices.every((index) => selectedSms.has(index));
  const smsPageAdditionCount = smsPage.indices.filter((index) => !selectedSms.has(index)).length;
  const [smsReview, setSmsReview] = useTabState<{ issueKey: string; drafts: SmsDltDraft[]; revision: number } | null>('briefs_sms_dlt_review', null);
  const [editingCard, setEditingCard] = useTabState<Record<string, boolean>>('briefs_editing_card', {});
  const [syncingRcs, setSyncingRcs] = useState<Record<string, boolean>>({});
  const [syncedRcs, setSyncedRcs] = useState<Record<string, string>>({});
  const [previewCreativeModal, setPreviewCreativeModal] = useState<(JiraCreativeSource & { filename: string; channel?: string }) | null>(null);
  const targetAccount = account;
  const selectedDestinationLabel = destinationLabel(account, channel, getAccountLabel(account));
  const briefRef = useRef(brief);
  briefRef.current = brief;
  const waTemplatesRef = useRef(waTemplates);
  waTemplatesRef.current = waTemplates;
  const rcsTemplatesRef = useRef(rcsTemplates);
  rcsTemplatesRef.current = rcsTemplates;
  const currentRcs = getRcsDetails(targetAccount, accounts);
  const activeRequestKey = useRef<string>('');
  const [uploadingCreative, setUploadingCreative] = useState<Record<string, boolean>>({});
  const [previewAttempt, setPreviewAttempt] = useState(0);
  const [validation, setValidation] = useState<{
    signature: JiraPreviewSnapshot | null;
    status: 'pending' | 'ready' | 'error';
    data?: JiraDraftPreview;
    error?: string;
  }>({ signature: null, status: 'pending' });
  const [commentReview, setCommentReview] = useState<{
    signature: JiraPreviewSnapshot;
    issueKey: string;
    payload: JiraDraftPreviewRequest;
    text: string;
  } | null>(null);
  const [commentBusy, setCommentBusy] = useState(false);
  const commentBusyRef = useRef(false);
  const [commentError, setCommentError] = useState<string | null>(null);
  const effectiveWaTemplates = useMemo(() => waTemplates.map((draft) => normalizeWhatsAppCtas(draft, targetAccount)), [waTemplates, targetAccount]);
  const effectiveRcsTemplates = useMemo(() => rcsTemplates.map((draft) => normalizeRcsCtas(selectedRcsDraft(draft), targetAccount)), [rcsTemplates, targetAccount]);
  const previewPayload = useMemo(() => ({
    account: targetAccount,
    whatsapp_templates: channel === 'whatsapp' ? effectiveWaTemplates : [],
    rcs_templates: channel === 'rcs' ? effectiveRcsTemplates : [],
  }), [targetAccount, channel, effectiveWaTemplates, effectiveRcsTemplates]);
  const previewSignature = useMemo<JiraPreviewSnapshot>(
    () => ({ selectedKey, issueKey: brief?.issue_key, payload: previewPayload, attempt: previewAttempt }),
    [selectedKey, brief?.issue_key, previewPayload, previewAttempt]
  );
  const previewSignatureRef = useRef(previewSignature);
  previewSignatureRef.current = previewSignature;
  const validationReady = validation.signature === previewSignature && validation.status === 'ready'
    && !loadingBrief && selectedKey === brief?.issue_key && !Object.values(uploadingCreative).some(Boolean);
  const destinationAvailable = Boolean(account && account !== 'all' && (channel === 'whatsapp' || channel === 'rcs'));
  const getWaWarnings = (index: number): DraftWarnings => (channel === 'whatsapp' && validationReady ? validation.data?.whatsapp_templates[index] : undefined) ?? UNCHECKED_WARNINGS;
  const validationError = validation.signature === previewSignature && validation.status === 'error' ? validation.error : undefined;
  const getRcsWarnings = (index: number): DraftWarnings => (channel === 'rcs' && validationReady ? validation.data?.rcs_templates[index] : undefined) ?? UNCHECKED_WARNINGS;
  const isRcsEligible = (index: number) => !carouselSelectionError(effectiveRcsTemplates[index]) && !isAspectBlocked(getRcsWarnings(index));
  const creativeSource = (path?: string | null, filename?: string | null, attachmentId?: string | null): JiraCreativeSource => ({
    path,
    filename,
    attachmentId: attachmentId || brief?.attachments_mapped.find((attachment) => path ? attachment.local_path === path : filename && attachment.filename === filename)?.id,
  });
  // MoEngage Campaign Staging State
  const [moeCatalog, setMoeCatalog] = useState<MoEngageCatalog | null>(null);
  const [moeWorkspaces, setMoeWorkspaces] = useState<{ id: string; name: string }[]>([]);
  const [moeWorkspace, setMoeWorkspace] = useState('');
  const [loadingCatalog, setLoadingCatalog] = useState<boolean>(false);
  const [moeCampaignName, setMoeCampaignName] = useState<string>('');
  const [moeChannel, setMoeChannel] = useState<'WHATSAPP' | 'EMAIL' | 'PUSH'>('WHATSAPP');
  const [moeSegmentId, setMoeSegmentId] = useState<string>('');
  const [moeScheduledAt, setMoeScheduledAt] = useState<string>('');
  const [moeTimezone, setMoeTimezone] = useState<string>('Asia/Kolkata');
  const [moeWaTemplateId, setMoeWaTemplateId] = useState<string>('');
  const [moeWaSender, setMoeWaSender] = useState<string>('');
  const [moeEmailFrom, setMoeEmailFrom] = useState<string>('contact@tatacapital.com');
  const [moeEmailSubject, setMoeEmailSubject] = useState<string>('');
  const [moeEmailContent, setMoeEmailContent] = useState<string>('<p>Exclusive Offer from Tata Capital</p>');
  const [moePushTitle, setMoePushTitle] = useState<string>('');
  const [moePushBody, setMoePushBody] = useState<string>('');
  const [moePushPlatform, setMoePushPlatform] = useState<'ANDROID' | 'IOS'>('ANDROID');

  const [moeStagingStatus, setMoeStagingStatus] = useState<'DRAFT' | 'STAGING' | 'STAGED' | 'CREATING' | 'CREATED' | 'ERROR'>('DRAFT');
  const [moeResultCampaignId, setMoeResultCampaignId] = useState<string | null>(null);
  const [moeBatchId, setMoeBatchId] = useState<string | null>(null);
  const [moeError, setMoeError] = useState<string | null>(null);
  const [moeBusy, setMoeBusy] = useState<boolean>(false);
  const [moeCreateAttempted, setMoeCreateAttempted] = useState(false);
  const [moeRemoteState, setMoeRemoteState] = useState('');

  useEffect(() => {
    let active = true;
    setMoeWorkspace('');
    setMoeCatalog(null);
    setMoeWorkspaces([]);
    if (targetAccount) fetchMoEngageDraftWorkspaces(targetAccount).then((result) => {
      if (active) setMoeWorkspaces(result.workspaces);
    }).catch((err) => { if (active) setMoeError(formatError(err)); });
    return () => { active = false; };
  }, [targetAccount]);

  useEffect(() => {
    const explicit = brief?.moengage_campaign?.workspace_id || brief?.moengage_campaign?.workspace;
    setMoeWorkspace(explicit ? moeWorkspaces.find((item) => item.id === explicit || item.name === explicit)?.id || '' : '');
  }, [brief, moeWorkspaces]);

  useEffect(() => {
    let active = true;
    setMoeCatalog(null);
    setMoeSegmentId('');
    setMoeWaSender('');
    setMoeWaTemplateId('');
    setMoeBatchId(null);
    setMoeStagingStatus('DRAFT');
    setLoadingCatalog(false);
    if (activeTab !== 'moengage' || !targetAccount || (moeChannel === 'WHATSAPP' && !moeWorkspace)) return;
    setLoadingCatalog(true);
    fetchMoEngageCatalog(targetAccount, moeChannel === 'WHATSAPP' ? moeWorkspace : undefined).then((cat) => {
      if (active) {
        setMoeCatalog(cat);
        if (moeChannel !== 'WHATSAPP') {
          if (cat.segments?.[0]) setMoeSegmentId(cat.segments[0].id);
          if (cat.email_senders?.[0] && !moeEmailFrom) setMoeEmailFrom(cat.email_senders[0].from_address);
        }
      }
    }).catch((err) => { if (active) setMoeError(formatError(err)); })
      .finally(() => { if (active) setLoadingCatalog(false); });
    return () => { active = false; };
  }, [activeTab, targetAccount, moeChannel, moeWorkspace]);

  const requireMoeWorkspace = () => {
    if (moeChannel !== 'WHATSAPP') return;
    if (!moeWorkspace || !moeCatalog || moeCatalog.workspace_id !== moeWorkspace ||
        !moeCatalog.segments.some((segment) => segment.id === moeSegmentId) ||
        !moeCatalog.whatsapp_senders?.some((sender) => sender.sender_id === moeWaSender) ||
        !moeCatalog.whatsapp_templates?.some((template) => template.id === moeWaTemplateId && template.sender_ids.includes(moeWaSender))) {
      throw new Error('Review an explicit WhatsApp workspace and select its audience, sender and approved template before staging or creating.');
    }
  };

  const moeSchedule = () => {
    if (!moeScheduledAt) return new Date(Date.now() + 86400000).toISOString();
    if (/(?:Z|[+-]\d{2}:\d{2})$/i.test(moeScheduledAt)) return moeScheduledAt;
    if (moeTimezone !== 'Asia/Kolkata') throw new Error('A schedule without an offset requires Asia/Kolkata; supply an explicit ISO offset for another timezone.');
    return `${moeScheduledAt.length === 16 ? `${moeScheduledAt}:00` : moeScheduledAt}+05:30`;
  };

  const moeBriefWhatsAppFields = (): Record<string, string> => {
    const template = moeCatalog?.whatsapp_templates?.find((item) => item.id === moeWaTemplateId);
    const draft = waTemplates.find((item) => item.template_name === template?.name) || (waTemplates.length === 1 ? waTemplates[0] : undefined);
    if (!draft?.body) throw new Error('Select a template matching one unambiguous WhatsApp brief body before staging or creating.');
    const fields: Record<string, string> = { whatsapp_message: draft.body };
    if (draft.whatsapp_placeholders) fields.whatsapp_placeholders = JSON.stringify(draft.whatsapp_placeholders);
    return fields;
  };

  const handleMoeStageBatch = async () => {
    if (!brief) return;
    try {
      requireMoeWorkspace();
      setMoeBusy(true);
      setMoeError(null);
      setMoeStagingStatus('STAGING');
      const scheduledVal = moeSchedule();

      const rowDict: Record<string, string> = normalizeCampaignFields({
        campaign_name: moeCampaignName,
        channel: moeChannel,
        segment_id: moeChannel === 'WHATSAPP' ? moeSegmentId : moeSegmentId || 'Test_FSTP_Pranav_1602',
        scheduled_at: scheduledVal,
        timezone: moeTimezone || 'Asia/Kolkata',
      });
      setMoeCampaignName(requireCampaignName(rowDict.campaign_name));

      if (moeChannel === 'WHATSAPP') {
        rowDict.workspace_id = moeWorkspace;
        rowDict.whatsapp_sender = moeWaSender;
        rowDict.whatsapp_template_id = moeWaTemplateId;
        Object.assign(rowDict, moeBriefWhatsAppFields());
      } else if (moeChannel === 'EMAIL') {
        rowDict.from_address = moeEmailFrom || 'contact@tatacapital.com';
        rowDict.subject = moeEmailSubject || brief.summary || 'Exclusive Offer';
        rowDict.html_content = moeEmailContent || '<p>Exclusive Offer</p>';
        rowDict.content_type = 'PROMOTIONAL';
        rowDict.subscription_category = 'Offers';
      } else if (moeChannel === 'PUSH') {
        rowDict.push_platform = moePushPlatform;
        rowDict.push_title = moePushTitle || brief.summary?.slice(0, 30) || 'Tata Capital Offer';
        rowDict.push_message = moePushBody || brief.summary || 'Click to explore offer';
      }

      const headers = Object.keys(rowDict);
      const csvLine = headers.map(h => `"${(rowDict[h] || '').replace(/"/g, '""')}"`).join(',');
      const csvData = `${headers.join(',')}\n${csvLine}\n`;
      const file = new File([csvData], `${brief.issue_key}_moengage_draft.csv`, { type: 'text/csv' });

      const batch = await stageMoEngageDraftBatch(file, targetAccount);
      const stagedName = batch.items[0] && campaignRowName(batch.items[0]);
      if (stagedName) setMoeCampaignName(stagedName);
      setMoeBatchId(batch.batch_id);
      setMoeStagingStatus(batch.ready > 0 && batch.blocked === 0 ? 'STAGED' : 'ERROR');
      const stageIssues = batch.items.flatMap((item) => item.issues || []).join('; ');
      if (batch.blocked > 0) setMoeError(stageIssues || 'Staged rows require correction before creation.');
      setFeedback({
        message: `Batch ${batch.batch_id} staged: ${batch.ready} ready, ${batch.blocked} blocked.${stageIssues ? ` ${stageIssues}` : ''} Review the queue before creating.`,
        type: batch.blocked > 0 ? 'error' : 'success',
      });
    } catch (err) {
      const msg = formatError(err);
      setMoeError(msg);
      setMoeStagingStatus('ERROR');
      setFeedback({ message: `Failed to stage batch: ${msg}`, type: 'error' });
    } finally {
      setMoeBusy(false);
    }
  };

  const handleMoeCreateDraft = async () => {
    if (!brief || moeBusy || moeCreateAttempted) return;
    try {
      requireMoeWorkspace();
      setMoeBusy(true);
      setMoeError(null);
      setMoeStagingStatus('CREATING');
      const scheduledVal = moeSchedule();

      const rowDict: Record<string, any> = normalizeCampaignFields({
        account: targetAccount,
        source_ref: `jira_${brief.issue_key}.csv`,
        row_id: '1',
        channel: moeChannel,
        campaign_name: moeCampaignName,
        segment_id: moeChannel === 'WHATSAPP' ? moeSegmentId : moeSegmentId || 'Test_FSTP_Pranav_1602',
        scheduled_at: scheduledVal,
        timezone: moeTimezone || 'Asia/Kolkata',
      });
      setMoeCampaignName(requireCampaignName(rowDict.campaign_name));

      if (moeChannel === 'WHATSAPP') {
        rowDict.workspace_id = moeWorkspace;
        rowDict.whatsapp_sender = moeWaSender;
        rowDict.whatsapp_template_id = moeWaTemplateId;
        Object.assign(rowDict, moeBriefWhatsAppFields());
      } else if (moeChannel === 'EMAIL') {
        rowDict.from_address = moeEmailFrom || 'contact@tatacapital.com';
        rowDict.subject = moeEmailSubject || brief.summary || 'Exclusive Offer';
        rowDict.html_content = moeEmailContent || '<p>Exclusive Offer</p>';
        rowDict.content_type = 'PROMOTIONAL';
        rowDict.subscription_category = 'Offers';
      } else if (moeChannel === 'PUSH') {
        rowDict.push_platform = moePushPlatform;
        rowDict.push_title = moePushTitle || brief.summary?.slice(0, 30) || 'Tata Capital Offer';
        rowDict.push_message = moePushBody || brief.summary || 'Click to explore offer';
      }

      setMoeCreateAttempted(true);
      setMoeRemoteState('UNKNOWN');
      const res = await createMoEngageDraft(targetAccount, rowDict);
      setMoeRemoteState(res.state);
      if (res.campaign_id) setMoeResultCampaignId(res.campaign_id);
      const confirmed = /^[a-f0-9]{24}$/i.test(res.campaign_id || '') && res.state === (moeChannel === 'WHATSAPP' ? 'VERIFIED' : 'VALIDATED');
      if (!confirmed) {
        const issues = (res.validation_errors || []).map((issue) => `${issue.field || ''}: ${issue.issue || ''}`).join('; ');
        throw new Error(`Draft state ${res.state || 'UNKNOWN'}${res.campaign_id ? ` (${res.campaign_id})` : ''}: ${issues || res.issue || 'Creation not confirmed'}. Do not create again; reconcile the existing attempt in MoEngage.`);
      }
      setMoeStagingStatus('CREATED');
      setFeedback({ message: `Draft ${res.campaign_id} confirmed ${res.state}. Human review is required before publishing.`, type: 'success' });
    } catch (err) {
      const msg = formatError(err);
      setMoeError(msg);
      setMoeStagingStatus('ERROR');
      setFeedback({ message: `Draft request not confirmed: ${msg} If a request was submitted, reconcile it in MoEngage rather than creating again.`, type: 'error' });
    } finally {
      setMoeBusy(false);
    }
  };

  const loadIssues = useCallback(async (queryParam?: string, bStatusParam?: string) => {
    try {
      setLoadingIssues(true);
      const activeBStatus = bStatusParam !== undefined ? bStatusParam : briefStatusFilter;
      const list = await fetchJiraIssues({
        project,
        search: queryParam?.trim() || undefined,
        brief_status: activeBStatus !== 'all' ? activeBStatus : undefined,
        limit: 50,
      });
      setIssues(list);
      if (list.length > 0) {
        setSelectedKey((prev) => {
          // Preserve already-selected ticket! Never randomly clobber user selection with list[0]!
          if (prev) return prev;
          return list[0].key;
        });
      }
    } catch (err) {
      setFeedback({ message: formatError(err), type: 'error' });
    } finally {
      setLoadingIssues(false);
    }
  }, [project, briefStatusFilter]);

  useEffect(() => {
    fetchJiraProjects().then((projs) => {
      if (projs && projs.length > 0) setProjectsList(projs);
    });
  }, []);

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search);
      const urlKey = params.get('key');
      const urlProj = params.get('project');
      if (urlKey) {
        const cleanK = urlKey.toUpperCase().trim();
        setSelectedKey(cleanK);
        const prefix = cleanK.split('-')[0];
        if (prefix && ['TCN', 'SWCM', 'TM', 'TAT', 'MON', 'COL'].includes(prefix)) {
          setProject(prefix);
        }
      } else if (urlProj) {
        setProject(urlProj.toUpperCase().trim());
      } else {
        const saved = localStorage.getItem('briefs_project');
        if (saved) setProject(saved);
      }
    }
  }, []);

  // Server-side debounced search for tickets
  useEffect(() => {
    const timer = setTimeout(() => {
      loadIssues(searchQuery, briefStatusFilter);
    }, 350);
    return () => clearTimeout(timer);
  }, [searchQuery, briefStatusFilter, loadIssues]);

  const handleSelectIssue = (key: string) => {
    const cleanKey = key.trim().toUpperCase();
    setSelectedKey(cleanKey);
    setShowTicketPicker(false);
    if (typeof window !== 'undefined') {
      const url = new URL(window.location.href);
      url.searchParams.set('key', cleanKey);
      window.history.replaceState({}, '', url.toString());
    }
    // Auto-align project dropdown if user selected a ticket from another project
    const prefix = cleanKey.split('-')[0];
    if (prefix && prefix !== project && project !== 'ALL' && ['TCN', 'SWCM', 'TM', 'TAT', 'MON', 'COL'].includes(prefix)) {
      setProject(prefix);
      if (typeof window !== 'undefined') {
        localStorage.setItem('briefs_project', prefix);
      }
    }
  };

  const loadBrief = useCallback(async (key: string, force = false) => {
    if (!key) return;
    const cleanKey = key.trim().toUpperCase();
    activeRequestKey.current = cleanKey;
    if (!force && briefRef.current && briefRef.current.issue_key === cleanKey && waTemplatesRef.current.length > 0) {
      // Retain active working drafts when returning to this tab
      return;
    }
    try {
      setLoadingBrief(true);
      setFeedback(null);
      const data = await fetchJiraBrief(cleanKey, account);
      if (!mountedRef.current) return;
      // Discard stale response if user already switched to another ticket
      if (activeRequestKey.current !== cleanKey && activeRequestKey.current !== (data.issue_key || '')) {
        return;
      }
      setBrief(data);
      // If the backend resolved a numeric key (e.g. 524 -> TCN-524), sync selectedKey to the canonical key
      if (data.issue_key && data.issue_key !== cleanKey) {
        setSelectedKey(data.issue_key);
        activeRequestKey.current = data.issue_key;
        if (typeof window !== 'undefined') {
          const url = new URL(window.location.href);
          url.searchParams.set('key', data.issue_key);
          window.history.replaceState({}, '', url.toString());
        }
      }
      const waList = (data.whatsapp_templates || []).map((draft) => normalizeWhatsAppCtas(draft, account));
      const rcsList = (data.rcs_templates || []).map((draft) => normalizeRcsCtas(draft, account));
      const smsList = data.sms_templates || [];
      setWaTemplates(waList);
      setRcsTemplates(rcsList);
      setSmsTemplates(smsList);
      setSelectedSms(new Set());
      setSmsReview(null);
      setSmsSearch('');
      setSmsPageNumber(1);
      setSelectedWa(new Set(waList.map((_, idx) => idx)));
      setSelectedRcs(new Set(rcsList.map((_, idx) => idx)));
      setEditingCard({});
      setMoeCampaignName(normalizeCampaignName(data.moengage_campaign?.campaign_name || `${data.issue_key} - ${data.summary}`));
      if (data.moengage_campaign) {
        setMoePushTitle(data.moengage_campaign.push_title || `Tata Capital: ${data.summary?.slice(0, 30)}`);
        setMoePushBody(data.moengage_campaign.push_body || data.summary || '');
        setMoeScheduledAt(data.moengage_campaign.scheduled_date || '');
        if (waList.length > 0) {
          setMoeChannel('WHATSAPP');
          setMoeWaTemplateId('');
        } else if (data.is_email_campaign || (data.email_templates?.length || 0) > 0) {
          setMoeChannel('EMAIL');
          setMoeEmailSubject(data.moengage_campaign?.email_subject || data.summary || '');
          if (data.email_templates?.[0]?.html_content) {
            setMoeEmailContent(data.email_templates[0].html_content);
          }
        } else {
          setMoeChannel('PUSH');
        }
        setMoeResultCampaignId(null);
        setMoeCreateAttempted(false);
        setMoeRemoteState('');
        setMoeBatchId(null);
        setMoeError(null);
      }
      if (data.is_email_campaign) {
        setActiveTab('email');
      } else {
        setActiveTab(channel);
      }
    } catch (err) {
      if (mountedRef.current && activeRequestKey.current === cleanKey) {
        setFeedback({ message: `Failed to load brief for ${key}: ${formatError(err)}`, type: 'error' });
      }
    } finally {
      if (mountedRef.current && activeRequestKey.current === cleanKey) {
        setLoadingBrief(false);
      }
    }
  }, [account, channel, setActiveTab]);

  useEffect(() => {
    if (selectedKey) {
      loadBrief(selectedKey);
    }
  }, [selectedKey, loadBrief]);

  useEffect(() => {
    if (!destinationAvailable || !brief || loadingBrief || selectedKey !== brief.issue_key) return;
    const controller = new AbortController();
    let disposed = false;
    setValidation({ signature: previewSignature, status: 'pending' });
    const timer = setTimeout(() => {
      previewJiraDrafts(previewPayload, controller.signal)
        .then((data) => {
          if (!disposed && previewSignatureRef.current === previewSignature) {
            setValidation({ signature: previewSignature, status: 'ready', data });
          }
        })
        .catch((error) => {
          if (!disposed && previewSignatureRef.current === previewSignature) {
            setValidation({ signature: previewSignature, status: 'error', error: formatError(error) });
          }
        });
    }, 350);
    return () => {
      disposed = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [destinationAvailable, brief?.issue_key, loadingBrief, selectedKey, previewPayload, previewSignature, previewAttempt]);

  useEffect(() => {
    setCommentReview((current) => current?.signature === previewSignature && validationReady ? current : null);
    setCommentError(null);
  }, [previewSignature, validationReady]);

  const prepareValidationComment = async () => {
    if (!brief || !validationReady || submitting || commentBusyRef.current || !hasValidationErrors) return;
    const signature = previewSignature;
    const issueKey = brief.issue_key;
    const payload = previewPayload;
    commentBusyRef.current = true;
    setCommentBusy(true);
    setCommentError(null);
    try {
      const result = await reportJiraValidation(issueKey, { ...payload, confirmed: false });
      if (previewSignatureRef.current !== signature) return;
      setCommentReview({ signature, issueKey, payload, text: result.comment_text });
    } catch (error) {
      if (previewSignatureRef.current === signature) {
        setFeedback({ message: `Could not prepare Jira validation comment: ${formatError(error)}`, type: 'error' });
      }
    } finally {
      commentBusyRef.current = false;
      setCommentBusy(false);
    }
  };

  const confirmValidationComment = async () => {
    if (!commentReview || !validationReady || submitting || commentBusyRef.current) return;
    if (commentReview.signature !== previewSignatureRef.current) {
      setCommentReview(null);
      return;
    }
    const review = commentReview;
    commentBusyRef.current = true;
    setCommentBusy(true);
    setCommentError(null);
    try {
      await reportJiraValidation(review.issueKey, {
        ...review.payload,
        confirmed: true,
        expected_comment: review.text,
      });
      setCommentReview(null);
      setFeedback({ message: `Validation errors reported as a comment on ${review.issueKey}.`, type: 'success' });
    } catch (error) {
      const message = formatError(error);
      setCommentError(message);
      setFeedback({ message: `Could not confirm posting to ${review.issueKey}: ${message}`, type: 'error' });
    } finally {
      commentBusyRef.current = false;
      setCommentBusy(false);
    }
  };

  const validateSelectedTemplateNames = () => {
    const drafts = channel === 'whatsapp'
      ? waTemplates.filter((_, index) => selectedWa.has(index))
      : rcsTemplates.filter((_, index) => selectedRcs.has(index));
    try {
      for (const draft of drafts) requireCampaignName(draft.template_name);
      return true;
    } catch {
      setFeedback({ message: 'New whitelisting names require lowercase att_ followed by a nonempty name. Finish editing the template name before submitting.', type: 'error' });
      return false;
    }
  };

  // Submission handler with selective channel filtering
  const handleSubmitChannel = async (channelMode: 'all' | 'whatsapp' | 'rcs') => {
    if (!brief) return;
    if (!destinationAvailable || (channelMode !== 'all' && channelMode !== channel)) {
      setFeedback({ message: `Choose the matching account and channel in “Whitelisting for” before submitting. Current destination: ${selectedDestinationLabel}.`, type: 'error' });
      return;
    }
    if (!validateSelectedTemplateNames()) return;
    const signature = previewSignature;
    if (!validationReady) {
      setFeedback({ message: 'Wait for current creative and copy validation, or retry failed validation, before whitelisting.', type: 'error' });
      return;
    }
    try {
      setSubmitting(true);
      setFeedback(null);

      const submitChannels: Array<'whatsapp' | 'rcs'> = [];
      let waToSubmit: JiraWhatsAppDraft[] = [];
      let rcsToSubmit: JiraRcsDraft[] = [];

      if (channel === 'whatsapp' && (channelMode === 'all' || channelMode === 'whatsapp')) {
        waToSubmit = effectiveWaTemplates.filter((_, idx) => selectedWa.has(idx));
        if (waToSubmit.length > 0) submitChannels.push('whatsapp');
      }

      if (channel === 'rcs' && (channelMode === 'all' || channelMode === 'rcs')) {
        rcsToSubmit = effectiveRcsTemplates.filter((_, idx) => selectedRcs.has(idx) && isRcsEligible(idx));
        if (rcsToSubmit.length > 0) submitChannels.push('rcs');
      }

      if (rcsToSubmit.length > 0 && !currentRcs.botId) {
        setFeedback({ message: `RCS bot is not configured for ${targetAccount.toUpperCase()}. Refresh account settings before submitting.`, type: 'error' });
        return;
      }

      if (submitChannels.length === 0) {
        setFeedback({ message: 'Please select at least one template to whitelist.', type: 'error' });
        setSubmitting(false);
        return;
      }

      const res = await submitJiraBrief(
        brief.issue_key,
        submitChannels,
        user || 'Briefing Operator',
        waToSubmit,
        rcsToSubmit,
        targetAccount,
        rcsToSubmit.length > 0 ? currentRcs.botId : undefined
      );
      if (!mountedRef.current || previewSignatureRef.current !== signature) return;

      const waResults = res.whatsapp_submitted || [];
      const rcsResults = res.rcs_submitted || [];
      const waCount = waResults.filter((result) => result.status === 'submitted').length;
      const rcsCount = rcsResults.filter((result) => result.status === 'submitted').length;
      const outcomes = [...waResults, ...rcsResults];
      const errors = outcomes.filter((result) => result.status !== 'submitted' && result.status !== 'duplicate');
      const duplicateCount = outcomes.filter((result) => result.status === 'duplicate').length;
      setFeedback({
        message: `Submitted ${waCount + rcsCount} templates to ${destinationLabel(res.account, res.channels[0], getAccountLabel(res.account))} for ${brief.issue_key}.`
          + (duplicateCount ? ` ${duplicateCount} already registered.` : '')
          + (errors.length ? ` ${errors.length} blocked or failed: ${errors.map((result) => `${result.template_name}: ${result.error || result.status}`).join('; ')}.` : '')
          + ' No Jira comment was posted.',
        type: errors.length ? 'error' : 'success',
      });
      loadBrief(brief.issue_key);
    } catch (err) {
      if (mountedRef.current && previewSignatureRef.current === signature) setFeedback({ message: formatError(err), type: 'error' });
    } finally {
      if (mountedRef.current) setSubmitting(false);
    }
  };

  const requestWhitelist = (channelMode: 'all' | 'whatsapp' | 'rcs') => {
    if (!destinationAvailable || (channelMode !== 'all' && channelMode !== channel)) {
      setFeedback({ message: `Use “Whitelisting for” to select the matching destination. Current destination: ${selectedDestinationLabel}.`, type: 'error' });
      return;
    }
    if (!validateSelectedTemplateNames()) return;
    if (!validationReady) {
      setFeedback({ message: 'Wait for current creative and copy validation, or retry failed validation, before whitelisting.', type: 'error' });
      return;
    }
    const count = channel === 'whatsapp' ? selectedWaCount : selectedRcsCount;
    if (count === 0) {
      setFeedback({ message: 'Please select at least one template to whitelist.', type: 'error' });
      return;
    }
    if (channel === 'rcs' && selectedRcsCount > 0 && !currentRcs.botId) {
      setFeedback({ message: `RCS bot is not configured for ${targetAccount.toUpperCase()}. Refresh account settings before submitting.`, type: 'error' });
      return;
    }
    setConfirmationMode(channel === 'whatsapp' ? 'whatsapp' : 'rcs');
  };

  const confirmWhitelist = async () => {
    if (!confirmationMode) return;
    const channelMode = confirmationMode;
    setConfirmationMode(null);
    await handleSubmitChannel(channelMode);
  };

  // Editing helpers
  const toggleEditCard = (cardId: string) => {
    setEditingCard((prev) => ({ ...prev, [cardId]: !prev[cardId] }));
  };

  const addTemplate = (channel: 'whatsapp' | 'rcs' | 'sms') => {
    if (!brief) return;
    const names = new Set([...waTemplates, ...rcsTemplates, ...smsTemplates].map((template) => template.template_name.toLowerCase()));
    let templateName: string;
    if (channel === 'rcs') {
      templateName = newRcsTemplateName(brief.issue_key, names, 'rcs_manual');
    } else {
      const suffix = channel === 'whatsapp' ? 'wa' : channel;
      const base = `${brief.issue_key.toLowerCase().replace(/[^a-z0-9_]/g, '_')}_${suffix}_manual`;
      const prefix = channel === 'whatsapp' ? normalizeNewTemplateName(base) : base;
      let sequence = 1;
      while (names.has(`${prefix}_${sequence}`)) sequence += 1;
      templateName = `${prefix}_${sequence}`;
    }
    let cardId: string;

    if (channel === 'whatsapp') {
      cardId = `wa-${waTemplates.length}`;
      setWaTemplates((prev) => [...prev, {
        template_name: templateName,
        category: waTemplates[0]?.category || 'MARKETING',
        language: waTemplates[0]?.language || 'en',
        header_type: 'TEXT',
        body: '',
        button_type: 'NONE',
        variables: [],
        sample_values: [],
        raw_source: '',
      }]);
    } else if (channel === 'rcs') {
      cardId = `rcs-${rcsTemplates.length}`;
      setRcsTemplates((prev) => [...prev, {
        template_name: templateName,
        card_title: '',
        body: '',
        action_type: 'URL',
        action_label: '',
        action_url: '',
        variables: [],
        raw_source: '',
        template_type: 'text',
      }]);
    } else {
      cardId = `sms-${smsTemplates.length}`;
      setSmsTemplates((prev) => [...prev, {
        template_name: templateName,
        text: '',
        char_count: 0,
        variant: 'Manual',
        variables: [],
        raw_source: '',
      }]);
      setSmsSearch('');
      setSmsPageNumber(Math.floor(smsTemplates.length / BRIEF_SMS_PAGE_SIZE) + 1);
    }

    setEditingCard((prev) => ({ ...prev, [cardId]: true }));
    setBrief((prev) => {
      if (!prev) return prev;
      const whatsapp = waTemplates.length + (channel === 'whatsapp' ? 1 : 0);
      const rcs = rcsTemplates.length + (channel === 'rcs' ? 1 : 0);
      const sms = smsTemplates.length + (channel === 'sms' ? 1 : 0);
      const email = prev.channel_counts?.email ?? 0;
      const push = prev.channel_counts?.push ?? 0;
      return { ...prev, channel_counts: { whatsapp, rcs, sms, email, push, total: whatsapp + rcs + sms + email + push } };
    });
    setFeedback({
      message: `Added '${templateName}'. Enter one message in the new editor and remove it from the original template. New templates are not selected for whitelisting automatically.`,
      type: 'success',
    });
  };

  const updateWaField = <K extends keyof JiraWhatsAppDraft>(idx: number, field: K, val: JiraWhatsAppDraft[K]) => {
    setWaTemplates((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], [field]: val };
      const draft = next[idx];
      if (field === 'button_type' && val === 'NONE') {
        draft.buttons = [];
      } else if (draft.buttons?.length && ['button_type', 'button_text', 'button_url', 'button_phone'].includes(field)) {
        const first = { ...draft.buttons[0] };
        if (field === 'button_type') {
          first.type = String(val);
          first.url = val === 'URL' ? draft.button_url || undefined : undefined;
          first.phone_number = val === 'PHONE_NUMBER' ? draft.button_phone || undefined : undefined;
        }
        if (field === 'button_text') first.text = String(val || '');
        if (field === 'button_url') first.url = String(val || '');
        if (field === 'button_phone') first.phone_number = String(val || '');
        draft.buttons = [first, ...draft.buttons.slice(1)];
      }
      return next;
    });
  };

  const updateRcsField = <K extends keyof JiraRcsDraft>(idx: number, field: K, val: JiraRcsDraft[K]) => {
    setRcsTemplates((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], [field]: val };
      const draft = next[idx];
      if (draft.suggestions?.length && ['action_label', 'action_url', 'action_type'].includes(field)) {
        const first = { ...draft.suggestions[0] };
        if (field === 'action_label') first.label = first.text = String(val || '');
        if (field === 'action_url') first.url = String(val || '');
        if (field === 'action_type') first.type = String(val || '');
        draft.suggestions = [first, ...draft.suggestions.slice(1)];
      }
      if (draft.carousel_cards?.length) {
        const first = { ...draft.carousel_cards[0] };
        if (field === 'card_title') first.card_title = String(val || '');
        if (field === 'body') first.card_description = String(val || '');
        if (field === 'action_label') first.button_text = String(val || '');
        if (field === 'action_url') first.button_url = String(val || '');
        draft.carousel_cards = [first, ...draft.carousel_cards.slice(1)];
      }
      return next;
    });
  };
  const removeWaButton = (waIdx: number, btnIdx: number) => {
    setWaTemplates((prev) => {
      const next = [...prev];
      const draft = { ...next[waIdx] };
      const currentButtons: NonNullable<JiraWhatsAppDraft['buttons']>[number][] = draft.buttons && draft.buttons.length > 0
        ? [...draft.buttons]
        : (draft.button_type && draft.button_type !== 'NONE'
            ? [{ type: draft.button_type, text: draft.button_text || '', url: draft.button_url || undefined, phone_number: draft.button_phone || undefined }]
            : []);
      currentButtons.splice(btnIdx, 1);
      draft.buttons = currentButtons;
      if (currentButtons.length === 0) {
        draft.button_type = 'NONE';
        draft.button_text = '';
        draft.button_url = '';
        draft.button_phone = '';
      } else {
        const first = currentButtons[0];
        draft.button_type = first.type || 'URL';
        draft.button_text = first.text || ('label' in first && typeof first.label === 'string' ? first.label : '');
        draft.button_url = first.url || '';
        draft.button_phone = first.phone_number || '';
      }
      next[waIdx] = draft;
      return next;
    });
  };

  const updateWaButton = (
    waIdx: number,
    btnIdx: number,
    patch: Partial<{ type: string; text: string; label: string; url: string; phone_number: string }>
  ) => {
    setWaTemplates((prev) => {
      const next = [...prev];
      const draft = { ...next[waIdx] };
      const currentButtons: NonNullable<JiraWhatsAppDraft['buttons']>[number][] = draft.buttons && draft.buttons.length > 0
        ? [...draft.buttons]
        : (draft.button_type && draft.button_type !== 'NONE'
            ? [{ type: draft.button_type, text: draft.button_text || '', url: draft.button_url || undefined, phone_number: draft.button_phone || undefined }]
            : []);
      if (!currentButtons[btnIdx]) {
        currentButtons[btnIdx] = { type: 'URL', text: 'Explore Now', url: TATA_CTA_URL };
      }
      currentButtons[btnIdx] = { ...currentButtons[btnIdx], ...patch };
      const waBtnText = patch.text ?? patch.label;
      if (waBtnText !== undefined) currentButtons[btnIdx].text = waBtnText;
      draft.buttons = currentButtons;
      if (btnIdx === 0) {
        if (patch.type) draft.button_type = patch.type;
        if (patch.text || patch.label) draft.button_text = patch.text || patch.label || '';
        if (patch.url !== undefined) draft.button_url = patch.url;
        if (patch.phone_number !== undefined) draft.button_phone = patch.phone_number;
      }
      next[waIdx] = draft;
      return next;
    });
  };

  const addWaButton = (waIdx: number) => {
    setWaTemplates((prev) => {
      const next = [...prev];
      const draft = { ...next[waIdx] };
      const currentButtons: NonNullable<JiraWhatsAppDraft['buttons']>[number][] = draft.buttons && draft.buttons.length > 0
        ? [...draft.buttons]
        : (draft.button_type && draft.button_type !== 'NONE'
            ? [{ type: draft.button_type, text: draft.button_text || '', url: draft.button_url || undefined, phone_number: draft.button_phone || undefined }]
            : []);
      if (currentButtons.length < 3) {
        currentButtons.push({ type: 'URL', text: 'Explore Now', url: TATA_CTA_URL });
      }
      draft.buttons = currentButtons;
      if (currentButtons.length === 1) {
        draft.button_type = 'URL';
        draft.button_text = 'Explore Now';
        draft.button_url = TATA_CTA_URL;
      }
      next[waIdx] = draft;
      return next;
    });
  };

  const removeRcsSuggestion = (rcsIdx: number, sIdx: number) => {
    setRcsTemplates((prev) => {
      const next = [...prev];
      const draft = { ...next[rcsIdx] };
      const currentSuggestions: NonNullable<JiraRcsDraft['suggestions']>[number][] = draft.suggestions && draft.suggestions.length > 0
        ? [...draft.suggestions]
        : ((draft.action_label || draft.action_url)
            ? [{ type: draft.action_type || 'URL', label: draft.action_label || '', text: draft.action_label || '', url: draft.action_url || '' }]
            : []);
      currentSuggestions.splice(sIdx, 1);
      draft.suggestions = currentSuggestions;
      if (currentSuggestions.length === 0) {
        draft.action_label = '';
        draft.action_url = '';
        draft.action_type = 'URL';
      } else {
        const first = currentSuggestions[0];
        draft.action_label = first.label || first.text || '';
        draft.action_url = first.url || '';
        draft.action_type = first.type || 'URL';
      }
      next[rcsIdx] = draft;
      return next;
    });
  };

  const updateRcsSuggestion = (
    rcsIdx: number,
    sIdx: number,
    patch: Partial<{ type: string; label: string; text: string; url: string; phone_number: string }>
  ) => {
    setRcsTemplates((prev) => {
      const next = [...prev];
      const draft = { ...next[rcsIdx] };
      const currentSuggestions: NonNullable<JiraRcsDraft['suggestions']>[number][] = draft.suggestions && draft.suggestions.length > 0
        ? [...draft.suggestions]
        : ((draft.action_label || draft.action_url)
            ? [{ type: draft.action_type || 'URL', label: draft.action_label || '', text: draft.action_label || '', url: draft.action_url || '' }]
            : []);
      if (!currentSuggestions[sIdx]) {
        currentSuggestions[sIdx] = { type: 'URL', label: 'Explore Now', text: 'Explore Now', url: TATA_CTA_URL };
      }
      currentSuggestions[sIdx] = { ...currentSuggestions[sIdx], ...patch };
      const rcsBtnLabel = patch.label ?? patch.text;
      if (rcsBtnLabel !== undefined) {
        currentSuggestions[sIdx].label = rcsBtnLabel;
        currentSuggestions[sIdx].text = rcsBtnLabel;
      }
      draft.suggestions = currentSuggestions;
      if (sIdx === 0) {
        if (patch.label || patch.text) draft.action_label = patch.label || patch.text || '';
        if (patch.url !== undefined) draft.action_url = patch.url;
        if (patch.type) draft.action_type = patch.type;
      }
      next[rcsIdx] = draft;
      return next;
    });
  };

  const addRcsSuggestion = (rcsIdx: number) => {
    setRcsTemplates((prev) => {
      const next = [...prev];
      const draft = { ...next[rcsIdx] };
      const currentSuggestions: NonNullable<JiraRcsDraft['suggestions']>[number][] = draft.suggestions && draft.suggestions.length > 0
        ? [...draft.suggestions]
        : ((draft.action_label || draft.action_url)
            ? [{ type: draft.action_type || 'URL', label: draft.action_label || '', text: draft.action_label || '', url: draft.action_url || '' }]
            : []);
      if (currentSuggestions.length < 4) {
        currentSuggestions.push({ type: 'URL', label: 'Explore Now', text: 'Explore Now', url: TATA_CTA_URL });
      }
      draft.suggestions = currentSuggestions;
      if (currentSuggestions.length === 1) {
        draft.action_label = 'Explore Now';
        draft.action_url = TATA_CTA_URL;
        draft.action_type = 'URL';
      }
      next[rcsIdx] = draft;
      return next;
    });
  };

  const updateCarouselCardField = (
    rcsIdx: number,
    cardIdx: number,
    field: 'card_title' | 'card_description' | 'button_text' | 'button_url',
    val: string
  ) => {
    setRcsTemplates((prev) => {
      const next = [...prev];
      const rcs = { ...next[rcsIdx] };
      if (rcs.carousel_cards) {
        const nextCards = [...rcs.carousel_cards];
        nextCards[cardIdx] = {
          ...nextCards[cardIdx],
          [field]: val,
        };
        rcs.carousel_cards = nextCards;
        if (cardIdx === 0) {
          if (field === 'card_title') rcs.card_title = val;
          if (field === 'card_description') rcs.body = val;
          if (field === 'button_text') rcs.action_label = val;
          if (field === 'button_url') rcs.action_url = val;
        }
      }
      next[rcsIdx] = rcs;
      return next;
    });
  };

  const updateSmsField = <K extends keyof JiraSmsDraft>(idx: number, field: K, val: JiraSmsDraft[K]) => {
    setSmsTemplates((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], [field]: val };
      if (field === 'text') {
        next[idx].char_count = String(val || '').length;
      }
      return next;
    });
  };

  const moveTemplate = (
    fromChannel: 'whatsapp' | 'rcs' | 'sms',
    fromIndex: number,
    toChannel: 'whatsapp' | 'rcs' | 'sms'
  ) => {
    if (fromChannel === toChannel) return;

    let templateName = '';

    if (fromChannel === 'whatsapp') {
      const wa = effectiveWaTemplates[fromIndex];
      if (!wa) return;
      templateName = wa.template_name;
      setWaTemplates((prev) => prev.filter((_, i) => i !== fromIndex));
      setSelectedWa((prev) => {
        const next = new Set<number>();
        prev.forEach((idx) => {
          if (idx < fromIndex) next.add(idx);
          else if (idx > fromIndex) next.add(idx - 1);
        });
        return next;
      });

      if (toChannel === 'rcs') {
        const newRcs: JiraRcsDraft = {
          template_name: newRcsTemplateName(
            wa.template_name.replace(/_wa(?:_[a-z]{2})?_\d+$|_wa$/, ''),
            new Set(rcsTemplates.map((draft) => draft.template_name.toLowerCase())),
          ),
          card_title: wa.header_text || wa.body.split('\n')[0].slice(0, 32) || 'Special Offer',
          body: wa.body,
          media_file: wa.media_file,
          media_filename: wa.media_filename,
          media_attachment_id: wa.media_attachment_id,
          action_type: wa.button_type || 'URL',
          action_label: wa.button_text || 'Check Offer',
          action_url: wa.button_url || TATA_CTA_URL,
          variables: wa.variables || [],
          raw_source: wa.raw_source || wa.body,
          template_type: wa.media_file ? 'richcard' : 'text',
        };
        setRcsTemplates((prev) => {
          const next = [...prev, newRcs];
          setSelectedRcs((s) => new Set(s).add(next.length - 1));
          return next;
        });
        setActiveTab('rcs');
      } else if (toChannel === 'sms') {
        const newSms: JiraSmsDraft = {
          template_name: wa.template_name.replace(/_wa(?:_[a-z]{2})?_\d+$/, '_sms_1').replace(/_wa$/, '_sms') || `${wa.template_name}_sms`,
          text: wa.body,
          char_count: wa.body.length,
          variant: 'Converted from WA',
          variables: wa.variables || [],
          raw_source: wa.raw_source || wa.body,
        };
        setSmsTemplates((prev) => [...prev, newSms]);
        setActiveTab('sms');
      }
    } else if (fromChannel === 'rcs') {
      const rcs = effectiveRcsTemplates[fromIndex];
      if (!rcs) return;
      templateName = rcs.template_name;
      setRcsTemplates((prev) => prev.filter((_, i) => i !== fromIndex));
      setSelectedRcs((prev) => {
        const next = new Set<number>();
        prev.forEach((idx) => {
          if (idx < fromIndex) next.add(idx);
          else if (idx > fromIndex) next.add(idx - 1);
        });
        return next;
      });

      if (toChannel === 'whatsapp') {
        const newWa: JiraWhatsAppDraft = {
          template_name: normalizeNewTemplateName(rcs.template_name.replace(/_rcs(?:_carousel)?_\d+$/, '_wa_1').replace(/_rcs$/, '_wa') || `${rcs.template_name}_wa`),
          category: 'MARKETING',
          language: 'en',
          header_type: rcs.media_file ? 'IMAGE' : (rcs.card_title ? 'TEXT' : 'NONE'),
          header_text: rcs.media_file ? null : (rcs.card_title || null),
          body: rcs.body,
          footer_text: null,
          media_file: rcs.media_file,
          media_filename: rcs.media_filename,
          media_attachment_id: rcs.media_attachment_id,
          button_type: isUrlCta(rcs.action_type) ? (rcs.action_url ? 'URL' : 'NONE') : rcs.action_type,
          button_text: rcs.action_label || 'Check Offer',
          button_url: isUrlCta(rcs.action_type) ? resolveCtaUrl(rcs.action_url, targetAccount) : rcs.action_url,
          variables: rcs.variables || [],
          sample_values: [],
          raw_source: rcs.raw_source || rcs.body,
        };
        setWaTemplates((prev) => {
          const next = [...prev, newWa];
          setSelectedWa((s) => new Set(s).add(next.length - 1));
          return next;
        });
        setActiveTab('whatsapp');
      } else if (toChannel === 'sms') {
        const newSms: JiraSmsDraft = {
          template_name: rcs.template_name.replace(/_rcs(?:_carousel)?_\d+$/, '_sms_1').replace(/_rcs$/, '_sms') || `${rcs.template_name}_sms`,
          text: rcs.body,
          char_count: rcs.body.length,
          variant: 'Converted from RCS',
          variables: rcs.variables || [],
          raw_source: rcs.raw_source || rcs.body,
        };
        setSmsTemplates((prev) => [...prev, newSms]);
        setActiveTab('sms');
      }
    } else if (fromChannel === 'sms') {
      const sms = smsTemplates[fromIndex];
      if (!sms) return;
      templateName = sms.template_name;
      setSmsTemplates((prev) => prev.filter((_, i) => i !== fromIndex));
      setSelectedSms((previous) => new Set(Array.from(previous).filter((index) => index !== fromIndex).map((index) => index > fromIndex ? index - 1 : index)));

      if (toChannel === 'whatsapp') {
        const newWa: JiraWhatsAppDraft = {
          template_name: normalizeNewTemplateName(sms.template_name.replace(/_sms_\d+$/, '_wa_1').replace(/_sms$/, '_wa') || `${sms.template_name}_wa`),
          category: 'MARKETING',
          language: 'en',
          header_type: 'NONE',
          header_text: null,
          body: sms.text,
          footer_text: null,
          button_type: 'NONE',
          variables: sms.variables || [],
          sample_values: [],
          raw_source: sms.raw_source || sms.text,
        };
        setWaTemplates((prev) => {
          const next = [...prev, newWa];
          setSelectedWa((s) => new Set(s).add(next.length - 1));
          return next;
        });
        setActiveTab('whatsapp');
      } else if (toChannel === 'rcs') {
        const newRcs: JiraRcsDraft = {
          template_name: newRcsTemplateName(
            sms.template_name.replace(/_sms_\d+$|_sms$/, ''),
            new Set(rcsTemplates.map((draft) => draft.template_name.toLowerCase())),
          ),
          card_title: sms.text.split('\n')[0].slice(0, 32) || 'Special Offer',
          body: sms.text,
          action_type: 'URL',
          action_label: 'Check Offer',
          action_url: TATA_CTA_URL,
          variables: sms.variables || [],
          raw_source: sms.raw_source || sms.text,
          template_type: 'text',
        };
        setRcsTemplates((prev) => {
          const next = [...prev, newRcs];
          setSelectedRcs((s) => new Set(s).add(next.length - 1));
          return next;
        });
        setActiveTab('rcs');
      }
    }

    setBrief((prev) => {
      if (!prev) return prev;
      const curWa = fromChannel === 'whatsapp' ? waTemplates.length - 1 : (toChannel === 'whatsapp' ? waTemplates.length + 1 : waTemplates.length);
      const curRcs = fromChannel === 'rcs' ? rcsTemplates.length - 1 : (toChannel === 'rcs' ? rcsTemplates.length + 1 : rcsTemplates.length);
      const curSms = fromChannel === 'sms' ? smsTemplates.length - 1 : (toChannel === 'sms' ? smsTemplates.length + 1 : smsTemplates.length);
      return {
        ...prev,
        channel_counts: {
          whatsapp: Math.max(0, curWa),
          rcs: Math.max(0, curRcs),
          sms: Math.max(0, curSms),
          email: prev.channel_counts?.email ?? 0,
          push: prev.channel_counts?.push ?? 0,
          total: Math.max(0, curWa) + Math.max(0, curRcs) + Math.max(0, curSms) + (prev.channel_counts?.email ?? 0) + (prev.channel_counts?.push ?? 0),
        },
      };
    });

    setFeedback({
      message: `Successfully moved template '${templateName}' from ${fromChannel.toUpperCase()} to ${toChannel.toUpperCase()}.`,
      type: 'success',
    });
  };

  const toggleSelectWa = (idx: number) => {
    if (!validationReady) return;
    setSelectedWa((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const toggleSelectRcs = (idx: number) => {
    if (!validationReady || (!selectedRcs.has(idx) && !isRcsEligible(idx))) return;
    setSelectedRcs((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const toggleCarouselCard = (rcsIdx: number, cardIdx: number) => {
    if (submitting) return;
    setRcsTemplates((prev) => prev.map((draft, index) => {
      if (index !== rcsIdx) return draft;
      const excluded = new Set(draft.excluded_card_indices || []);
      if (excluded.has(cardIdx)) excluded.delete(cardIdx);
      else excluded.add(cardIdx);
      return { ...draft, excluded_card_indices: [...excluded] };
    }));
  };

  const selectAllWa = (select: boolean) => {
    if (!validationReady) return;
    setSelectedWa(select ? new Set(waTemplates.map((_, idx) => idx)) : new Set());
  };

  const selectAllRcs = (select: boolean) => {
    if (!validationReady) return;
    setSelectedRcs(select ? new Set(rcsTemplates.flatMap((_, idx) => isRcsEligible(idx) ? [idx] : [])) : new Set());
  };

  const removeWaCreative = (idx: number) => {
    if (submitting || uploadingCreative[`wa_${idx}`]) return;
    setWaTemplates((prev) => prev.map((draft, index) => index === idx ? {
      ...draft,
      header_type: 'NONE',
      header_text: null,
      media_file: null,
      media_filename: null,
      media_attachment_id: null,
    } : draft));
    setFeedback({ message: 'Creative removed. Header is None; no header will be submitted.', type: 'success' });
  };

  const handleReplaceWaCreative = async (idx: number, file: File) => {
    const key = `wa_${idx}`;
    const issueKey = brief?.issue_key;
    const templateName = waTemplates[idx]?.template_name;
    try {
      setUploadingCreative((prev) => ({ ...prev, [key]: true }));
      const res = await uploadJiraCreative(file);
      if (!mountedRef.current || briefRef.current?.issue_key !== issueKey || activeRequestKey.current !== issueKey
          || !waTemplatesRef.current.some((draft) => draft.template_name === templateName)) return;
      setWaTemplates((prev) =>
        prev.map((w) =>
          w.template_name === templateName
            ? {
                ...w,
                header_type: 'IMAGE',
                media_file: res.local_path,
                media_filename: res.filename,
                media_attachment_id: null,
              }
            : w
        )
      );
      setFeedback({
        message: `Replaced WhatsApp creative with '${res.filename}'${res.dimensions ? ` (${res.dimensions}${res.aspect_ratio ? `, ${res.aspect_ratio}` : ''})` : ''}.`,
        type: 'success',
      });
    } catch (err) {
      setFeedback({
        message: `Failed to upload replacement creative: ${formatError(err)}`,
        type: 'error',
      });
    } finally {
      setUploadingCreative((prev) => ({ ...prev, [key]: false }));
    }
  };

  const handleReplaceRcsCreative = async (idx: number, file: File) => {
    const key = `rcs_${idx}`;
    const issueKey = brief?.issue_key;
    const templateName = rcsTemplates[idx]?.template_name;
    try {
      setUploadingCreative((prev) => ({ ...prev, [key]: true }));
      const res = await uploadJiraCreative(file);
      if (!mountedRef.current || briefRef.current?.issue_key !== issueKey || activeRequestKey.current !== issueKey
          || !rcsTemplatesRef.current.some((draft) => draft.template_name === templateName)) return;
      setRcsTemplates((prev) =>
        prev.map((r) =>
          r.template_name === templateName
            ? {
                ...r,
                media_file: res.local_path,
                media_filename: res.filename,
                media_attachment_id: null,
                carousel_cards: r.carousel_cards?.map((card, cardIndex) => cardIndex === 0 ? {
                  ...card,
                  media_url: res.local_path,
                  media_filename: res.filename,
                  media_attachment_id: null,
                } : card),
              }
            : r
        )
      );
      setFeedback({
        message: `Replaced RCS creative with '${res.filename}'${res.dimensions ? ` (${res.dimensions})` : ''}.`,
        type: 'success',
      });
    } catch (err) {
      setFeedback({
        message: `Failed to upload replacement creative: ${formatError(err)}`,
        type: 'error',
      });
    } finally {
      setUploadingCreative((prev) => ({ ...prev, [key]: false }));
    }
  };
  const handleReplaceCarouselCardCreative = async (rcsIdx: number, cardIdx: number, file: File) => {
    const key = `rcs_${rcsIdx}_card_${cardIdx}`;
    const issueKey = brief?.issue_key;
    const templateName = rcsTemplates[rcsIdx]?.template_name;
    try {
      setUploadingCreative((prev) => ({ ...prev, [key]: true }));
      const res = await uploadJiraCreative(file);
      if (!mountedRef.current || briefRef.current?.issue_key !== issueKey || activeRequestKey.current !== issueKey
          || !rcsTemplatesRef.current.some((draft) => draft.template_name === templateName && draft.carousel_cards?.[cardIdx])) return;
      setRcsTemplates((prev) => {
        const next = [...prev];
        const currentIndex = next.findIndex((draft) => draft.template_name === templateName);
        if (currentIndex < 0) return prev;
        const rcs = { ...next[currentIndex] };
        if (rcs.carousel_cards) {
          const nextCards = [...rcs.carousel_cards];
          nextCards[cardIdx] = {
            ...nextCards[cardIdx],
            media_url: res.local_path,
            media_filename: res.filename,
            media_attachment_id: null,
          };
          rcs.carousel_cards = nextCards;
          if (cardIdx === 0) {
            rcs.media_file = res.local_path;
            rcs.media_filename = res.filename;
            rcs.media_attachment_id = null;
          }
        }
        next[currentIndex] = rcs;
        return next;
      });
      setFeedback({
        message: `Replaced creative for Carousel Card ${cardIdx + 1} with '${res.filename}'${res.dimensions ? ` (${res.dimensions})` : ''}.`,
        type: 'success',
      });
    } catch (err) {
      setFeedback({
        message: `Failed to upload creative for Card ${cardIdx + 1}: ${formatError(err)}`,
        type: 'error',
      });
    } finally {
      setUploadingCreative((prev) => ({ ...prev, [key]: false }));
    }
  };

  const handleSyncRcsToMoEngage = async (rcs: JiraRcsDraft) => {
    try {
      setSyncingRcs((prev) => ({ ...prev, [rcs.template_name]: true }));
      const res = await syncRcsTemplateToMoEngage({
        account: targetAccount,
        template_name: rcs.template_name,
        template_id: rcs.template_name,
        card_title: rcs.card_title || brief?.summary || 'Tata Capital Offer',
        card_description: rcs.body,
        cta_text: rcs.action_label || 'Explore Now',
        cta_url: isUrlCta(rcs.action_type) ? resolveCtaUrl(rcs.action_url, targetAccount) : rcs.action_url,
      });
      setSyncedRcs((prev) => ({ ...prev, [rcs.template_name]: res.moengage_id }));
      setFeedback({
        message: `Template '${rcs.template_name}' successfully created in MoEngage Settings (MoEngage ID: ${res.moengage_id}). It is now available in MoEngage RCS campaigns.`,
        type: 'success',
      });
    } catch (err) {
      setFeedback({ message: `MoEngage Sync failed: ${formatError(err)}`, type: 'error' });
    } finally {
      setSyncingRcs((prev) => ({ ...prev, [rcs.template_name]: false }));
    }
  };


  const normalizedTicketSearch = searchQuery.trim().toLowerCase();
  const filteredIssues = issues.filter((i) => {
    if (campaignTypeFilter === 'messaging' && i.is_email) return false;
    if (campaignTypeFilter === 'email' && !i.is_email) return false;

    if (briefStatusFilter !== 'all') {
      const bStatus = (i.brief_status || 'Pending').toLowerCase().replace(/\s+/g, '_');
      if (bStatus !== briefStatusFilter) return false;
    }

    return (
      i.key.toLowerCase().includes(normalizedTicketSearch) ||
      i.summary.toLowerCase().includes(normalizedTicketSearch) ||
      (i.assignee || '').toLowerCase().includes(normalizedTicketSearch)
    );
  });
  const selectedWaCount = waTemplates.filter((_, index) => selectedWa.has(index)).length;
  const selectedRcsCount = rcsTemplates.filter((_, index) => selectedRcs.has(index) && isRcsEligible(index)).length;
  const eligibleWaCount = waTemplates.length;
  const eligibleRcsCount = rcsTemplates.filter((_, index) => isRcsEligible(index)).length;
  const totalSelectedCount = channel === 'whatsapp' ? selectedWaCount : channel === 'rcs' ? selectedRcsCount : 0;
  const hasValidationErrors = rcsTemplates.some((_, index) => isAspectBlocked(getRcsWarnings(index)))
    || [...waTemplates.map((_, index) => getWaWarnings(index)), ...rcsTemplates.map((_, index) => getRcsWarnings(index))]
      .some((draft) => draft.compliance_warnings?.some((warning) => warning.severity === 'error'));
  const loadedCurrentBrief = Boolean(brief && selectedKey === brief.issue_key && !loadingBrief);
  const workflowStep = !loadedCurrentBrief ? 1 : confirmationMode ? 3 : 2;
  const ticketFiltersActive = Boolean(searchQuery || project !== 'ALL' || campaignTypeFilter !== 'all' || briefStatusFilter !== 'all');
  const resetTicketFilters = () => {
    setSearchQuery('');
    setCampaignTypeFilter('all');
    setBriefStatusFilter('all');
    setProject('ALL');
    if (typeof window !== 'undefined') localStorage.setItem('briefs_project', 'ALL');
  };

  return (
    <>
      <div className="workspace-page space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-2">
          <p className="workspace-eyebrow">Campaign operations</p>
          <h1 className="workspace-heading">Jira briefs</h1>
          <p className="max-w-2xl text-sm leading-relaxed text-gray-500">From ticket to reviewed template. Keep the source in view and confirm only what you choose.</p>
        </div>
        <button type="button" onClick={() => loadIssues(searchQuery, briefStatusFilter)} disabled={loadingIssues}
          className="inline-flex shrink-0 items-center justify-center rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50">
          {loadingIssues ? 'Refreshing…' : 'Refresh tickets'}
        </button>
      </header>

      <nav aria-label="Jira review progress" className="rounded-xl border border-gray-200 bg-white px-3 py-4 sm:px-5">
        <ol className="flex items-start">
          {[
            { label: 'Choose ticket', detail: loadedCurrentBrief ? brief?.issue_key : loadingBrief ? 'Loading brief…' : 'Find your source' },
            { label: 'Review', detail: workflowStep === 3 ? 'Review prepared' : loadedCurrentBrief ? (smsReview?.issueKey === brief?.issue_key && activeTab === 'sms' ? 'DLT review open' : 'Check copy & selection') : 'After loading' },
            { label: 'Confirm', detail: workflowStep === 3 ? 'Awaiting your confirmation' : brief?.is_email_campaign && loadedCurrentBrief ? 'No whitelisting required' : smsReview?.issueKey === brief?.issue_key && activeTab === 'sms' ? 'Within DLT review' : 'Final approval required' },
          ].map((step, index) => (
            <li key={step.label} aria-current={workflowStep === index + 1 ? 'step' : undefined} className="relative flex min-w-0 flex-1 gap-2 sm:gap-3">
              {index < 2 && <span aria-hidden="true" className={`absolute left-8 right-2 top-4 h-px ${workflowStep > index + 1 ? 'bg-blue-300' : 'bg-gray-200'}`} />}
              <span aria-hidden="true" className={`relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full border text-sm font-medium ${workflowStep >= index + 1 ? 'border-gray-200 bg-gray-50 text-blue-800' : 'border-gray-200 bg-white text-gray-400'}`}>{index + 1}</span>
              <div className="relative min-w-0 bg-white pr-2 pt-1.5">
                <p className={`text-xs sm:text-sm font-medium ${workflowStep === index + 1 ? 'text-blue-800' : workflowStep > index + 1 ? 'text-gray-800' : 'text-gray-500'}`}>{step.label}</p>
                <p className="mt-1 hidden text-xs leading-relaxed text-gray-500 sm:block">{step.detail}</p>
              </div>
            </li>
          ))}
        </ol>
      </nav>

      <details className="rounded-xl border border-gray-200 bg-white px-4 py-3 text-sm text-gray-600">
        <summary className="cursor-pointer font-medium text-gray-700">New to Jira review? A quick guide</summary>
        <ol className="mt-4 grid list-inside list-decimal gap-3 leading-relaxed sm:grid-cols-2">
          <li><strong className="text-gray-900">Choose a destination.</strong> Use “Whitelisting for” to explicitly select the account and channel. A ticket’s detected account is only a suggestion.</li>
          <li><strong className="text-gray-900">Check the connection.</strong> Open <a href="/settings" className="font-medium text-blue-700 underline underline-offset-2">Settings</a> for the matching provider session. A selected destination does not mean it is connected.</li>
          <li><strong className="text-gray-900">Select and review.</strong> Find a ticket, check exact copy and creatives, then select templates. SMS uses shared DLT settings in the next review.</li>
          <li><strong className="text-gray-900">Confirm deliberately.</strong> Resolve blocking errors and review the destination. Whitelisting requires a final confirmation; SMS registration does not send messages.</li>
        </ol>
      </details>

      {/* Feedback Banner */}
      {feedback && (
        <div
          className={`p-4 rounded-xl border text-xs font-medium flex items-start justify-between ${
            feedback.type === 'success'
              ? 'bg-emerald-50 text-emerald-800 border-emerald-200'
              : 'bg-red-50 text-red-800 border-red-200'
          }`}
        >
          <div className="flex items-center gap-2">
            
            <span>{feedback.message}</span>
          </div>
          <button aria-label="Dismiss feedback" onClick={() => setFeedback(null)} className="text-gray-400 hover:text-gray-600 p-1 rounded">
            <svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" d="M5 5l10 10M15 5L5 15" /></svg>
          </button>
        </div>
      )}

      {/* Main Grid: Ticket Selector (Left) + Brief Inspector (Right) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
        {/* Left Column: Jira Issues List */}
        <section className="min-w-0 rounded-xl border border-gray-200 bg-white p-4 space-y-4 lg:col-span-4 xl:col-span-3" aria-labelledby="ticket-picker-heading">
          <div className="flex items-center justify-between gap-2 border-b border-gray-100 pb-3">
            <h2 id="ticket-picker-heading" className="text-sm font-medium text-gray-900">Choose a ticket</h2>
            <button type="button" aria-expanded={showTicketPicker || !selectedKey} aria-controls="jira-ticket-picker" onClick={() => setShowTicketPicker((open) => !open)} className="rounded-lg px-2 py-1 text-sm font-medium text-blue-700 hover:bg-gray-50 lg:hidden">{showTicketPicker ? 'Hide tickets' : 'Change ticket'}</button>
          </div>
          <div id="jira-ticket-picker" className={`${showTicketPicker || !selectedKey ? 'block' : 'hidden'} lg:block space-y-3`}>

          <label className="block text-sm font-medium text-gray-700">Jira project
            <select value={project} onChange={(event) => {
              const nextProject = event.target.value;
              setProject(nextProject);
              setSelectedKey('');
              setBrief(null);
              if (typeof window !== 'undefined') localStorage.setItem('briefs_project', nextProject);
            }} className="mt-2 w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm">
              {projectsList.map((item) => <option key={item.key} value={item.key}>{item.key === 'ALL' ? 'All projects' : `${item.key} — ${item.name}`}</option>)}
            </select>
          </label>
          <label className="block text-sm font-medium text-gray-700">Search tickets
            <input type="search" placeholder="Key, title or assignee" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)}
              className="mt-2 w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500" />
          </label>
          <details className="text-sm text-gray-600" open={campaignTypeFilter !== 'all' || briefStatusFilter !== 'all' || undefined}>
            <summary className="cursor-pointer font-medium">Filter tickets{campaignTypeFilter !== 'all' || briefStatusFilter !== 'all' ? ' · active' : ''}</summary>
            <div className="grid gap-3 pt-3">
              <label>Campaign type
                <select value={campaignTypeFilter} onChange={(event) => setCampaignTypeFilter(event.target.value as typeof campaignTypeFilter)} className="mt-1 w-full rounded-lg border border-gray-300 bg-white p-2">
                  <option value="all">All campaigns</option><option value="messaging">Messaging</option><option value="email">Email</option>
                </select>
              </label>
              <label>Ticket status
                <select value={briefStatusFilter} onChange={(event) => setBriefStatusFilter(event.target.value as typeof briefStatusFilter)} className="mt-1 w-full rounded-lg border border-gray-300 bg-white p-2">
                  <option value="all">All statuses</option><option value="pending">Pending</option><option value="in_progress">In progress</option><option value="completed">Completed</option><option value="failed">Failed</option><option value="not_generated">Not generated</option>
                </select>
              </label>
            </div>
          </details>
          {ticketFiltersActive && <div className="flex flex-wrap gap-2" aria-label="Active ticket filters">
            {project !== 'ALL' && <button type="button" aria-label={`Remove project filter ${project}`} onClick={() => { setProject('ALL'); localStorage.setItem('briefs_project', 'ALL'); }} className="workspace-filter-chip inline-flex items-center gap-2 rounded-lg border border-gray-200 px-2 py-1 text-sm text-gray-700">Project: {project}<span aria-hidden="true">×</span></button>}
            {searchQuery && <button type="button" aria-label="Clear ticket search" onClick={() => setSearchQuery('')} className="workspace-filter-chip inline-flex max-w-full items-center gap-2 rounded-lg border border-gray-200 px-2 py-1 text-sm text-gray-700"><span className="truncate">Search: {searchQuery}</span><span aria-hidden="true">×</span></button>}
            {campaignTypeFilter !== 'all' && <button type="button" aria-label="Remove campaign type filter" onClick={() => setCampaignTypeFilter('all')} className="workspace-filter-chip inline-flex items-center gap-2 rounded-lg border border-gray-200 px-2 py-1 text-sm capitalize text-gray-700">{campaignTypeFilter}<span aria-hidden="true">×</span></button>}
            {briefStatusFilter !== 'all' && <button type="button" aria-label="Remove ticket status filter" onClick={() => setBriefStatusFilter('all')} className="workspace-filter-chip inline-flex items-center gap-2 rounded-lg border border-gray-200 px-2 py-1 text-sm capitalize text-gray-700">{briefStatusFilter.replace(/_/g, ' ')}<span aria-hidden="true">×</span></button>}
            <button type="button" onClick={resetTicketFilters} className="px-1 py-1 text-sm font-medium text-blue-700 hover:underline">Reset filters</button>
          </div>}
          <p role="status" className="text-xs text-gray-500">{loadingIssues ? 'Updating results…' : `${filteredIssues.length} matching ticket${filteredIssues.length === 1 ? '' : 's'} in this queue`}<span className="block mt-1">Up to 50 tickets loaded. Search Jira to narrow results.</span></p>
          {selectedKey && !filteredIssues.some((issue) => issue.key === selectedKey) && <p className="rounded-lg bg-gray-50 px-3 py-2 text-xs leading-relaxed text-gray-600">Open ticket <strong>{selectedKey}</strong> is outside these results. Its review stays open.</p>}

          <div className="space-y-2 max-h-[640px] overflow-y-auto pr-1">
            {loadingIssues && issues.length === 0 ? (
              <div className="py-12 text-center text-xs text-gray-400">Loading Jira queue...</div>
            ) : filteredIssues.length === 0 ? (
              <div className="space-y-3 rounded-lg bg-gray-50 px-4 py-8 text-center text-sm text-gray-600">
                <p className="font-medium text-gray-900">No matching tickets</p>
                <p>Try a ticket key, a different project, or fewer filters.</p>
                {ticketFiltersActive && <button type="button" onClick={resetTicketFilters} className="rounded-lg border border-gray-200 bg-white px-3 py-2 font-medium text-gray-700 hover:bg-gray-100">Clear search &amp; filters</button>}
              </div>
            ) : (
              filteredIssues.map((issue) => {
                  const isSelected = issue.key === selectedKey;
                  return (
                    <button
                      key={issue.key}
                      onClick={() => handleSelectIssue(issue.key)}
                      className={`w-full text-left p-3 rounded-lg border transition-colors text-sm space-y-2 ${
                        isSelected
                          ? 'bg-gray-50 border-gray-900 ring-1 ring-gray-900/15'
                          : 'bg-white border-gray-200 hover:bg-gray-50/80'
                      }`}
                    >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-medium font-mono text-blue-700">{issue.key}</span>
                        {issue.is_email ? (
                          <span className="rounded-md bg-sky-50 border border-sky-200 px-1.5 py-0.5 text-xs font-medium text-sky-800">
                            Email
                          </span>
                        ) : (
                          <span className="rounded-lg bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-gray-600">
                            Messaging
                          </span>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded-lg bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-gray-600">
                          {issue.status}
                        </span>
                        <BriefStatusBadge status={issue.brief_status} />
                      </div>
                    </div>
                    <p className="font-medium text-gray-800 line-clamp-2 leading-snug">{issue.summary}</p>
                    <div className="flex flex-wrap items-center justify-between gap-1 pt-1 text-xs text-gray-500">
                      <span>{issue.assignee || 'Unassigned'}</span>
                      <span>{issue.attachment_count} creatives</span>
                    </div>
                    {/* Channel-Wise Campaign Breakdown */}
                    {(() => {
                      const counts = (isSelected && brief?.channel_counts) ? brief.channel_counts : issue.channel_counts;
                      if (!counts || counts.total === 0) return null;
                      return (
                        <div className="flex flex-wrap items-center gap-1 pt-2 border-t border-gray-100">
                          {counts.whatsapp > 0 && (
                            <span className="inline-flex items-center gap-0.5 text-xs font-medium px-1.5 py-1 rounded-lg bg-gray-100 text-gray-600 border border-gray-200" title={`${counts.whatsapp} WhatsApp campaign(s)`}>
                              <span>WA:</span>
                              <span className="font-medium">{counts.whatsapp}</span>
                            </span>
                          )}
                          {counts.rcs > 0 && (
                            <span className="inline-flex items-center gap-0.5 text-xs font-medium px-1.5 py-1 rounded-lg bg-gray-50 text-gray-600 border border-gray-200" title={`${counts.rcs} RCS campaign(s)`}>
                              <span>RCS:</span>
                              <span className="font-medium">{counts.rcs}</span>
                            </span>
                          )}
                          {counts.sms > 0 && (
                            <span className="inline-flex items-center gap-0.5 text-xs font-medium px-1.5 py-1 rounded-lg bg-gray-50 text-gray-600 border border-gray-200" title={`${counts.sms} SMS campaign(s)`}>
                              <span>SMS:</span>
                              <span className="font-medium">{counts.sms}</span>
                            </span>
                          )}
                          {counts.email > 0 && (
                            <span className="inline-flex items-center gap-0.5 text-xs font-medium px-1.5 py-1 rounded-lg bg-gray-100 text-gray-600 border border-gray-200" title={`${counts.email} Email campaign(s)`}>
                              <span>Email:</span>
                              <span className="font-medium">{counts.email}</span>
                            </span>
                          )}
                          {counts.push > 0 && (
                            <span className="inline-flex items-center gap-0.5 text-xs font-medium px-1.5 py-1 rounded-lg bg-gray-50 text-gray-600 border border-gray-200" title="Push / MoEngage campaign">
                              <span>Push:</span>
                              <span className="font-medium">{counts.push}</span>
                            </span>
                          )}
                        </div>
                      );
                    })()}
                    </button>
                  );
                })
            )}
          </div>
          </div>
        </section>

        {/* Right Column: Interactive Brief Inspector */}
        <div className="min-w-0 space-y-4 lg:col-span-8 xl:col-span-9">
          {loadingBrief ? (
            <div className="bg-white rounded-xl border border-gray-200/80  p-16 text-center text-xs text-gray-400 space-y-2">
              <p role="status" className="text-sm text-gray-500">Loading brief…</p>
              <p>Parsing Jira brief and downloading creative attachments...</p>
            </div>
          ) : !brief ? (
            <div className="bg-white rounded-xl border border-gray-200/80  p-16 text-center text-xs text-gray-400">
              Select a Jira ticket from the left panel to inspect its campaign brief.
            </div>
          ) : (
            <div className="space-y-4">
              {/* Ticket Overview Card */}
              <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="space-y-1">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                      <span className="text-sm font-medium font-mono text-blue-700 bg-gray-50 px-2 py-0.5 rounded-lg border border-gray-200">
                        {brief.issue_key}
                      </span>
                      <h2 className="min-w-0 break-words text-base font-medium text-gray-900">{brief.summary}</h2>
                      <BriefStatusBadge status={brief.brief_status} />
                    </div>
                    <details className="text-xs text-gray-500">
                      <summary className="cursor-pointer font-medium">Ticket details</summary>
                      <div className="mt-2 flex flex-wrap gap-3">
                      <span>Detected account (suggestion): <strong className="text-gray-800">{destinationAccountLabel(brief.account, getAccountLabel(brief.account))}</strong></span>
                      <span>Reporter: <strong>{brief.reporter}</strong></span>
                      <span>Assignee: <strong>{brief.assignee}</strong></span>
                      {brief.duedate && <span>Due date: <strong>{formatDate(brief.duedate)}</strong></span>}
                      </div>
                    </details>
                  </div>
                    <div className="flex flex-wrap items-center gap-2 pt-2">
                      <span className="text-xs font-medium text-gray-700">Destination: {selectedDestinationLabel}</span>
                    </div>

                    {/* Dedicated RCS Destination Card when RCS templates are present */}
                    {channel === 'rcs' && rcsTemplates.length > 0 && (
                      <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-xs text-gray-800 space-y-2">
                        <p className="font-medium">RCS bot: {currentRcs.botName}</p>
                        <details>
                          <summary className="cursor-pointer text-gray-700 font-medium">Connection details</summary>
                          <p className="mt-2 break-words">Bot ID: {currentRcs.botId || 'Not configured'} · User: {currentRcs.rcsUser} · Entity: {currentRcs.entity}</p>
                        </details>
                        {!currentRcs.botId && (
                          <p role="alert" className="font-medium text-amber-800">
                            RCS submission is unavailable: this account has no verified Karix bot. Refresh account settings.
                          </p>
                        )}
                        {brief.account && brief.account !== targetAccount && (
                          <div className="mt-1 pt-2 border-t border-gray-200/80 flex flex-wrap items-center justify-between gap-2 text-xs bg-amber-50/90 p-2 rounded-lg border border-amber-200 text-amber-900">
                            <span>
                              <strong>Suggested account:</strong> {destinationAccountLabel(brief.account, getAccountLabel(brief.account))}. Your reviewed destination remains <strong>{selectedDestinationLabel}</strong>.
                            </span>
                            <button
                              type="button"
                              onClick={() => { if (!setDestination(brief.account, channel)) return; }}
                              className="px-3 py-1 rounded-lg bg-amber-600 hover:bg-amber-700 text-white font-medium text-xs transition-colors "
                            >
                              Use {destinationLabel(brief.account, channel, getAccountLabel(brief.account))}
                            </button>
                          </div>
                        )}
                      </div>
                    )}

                  {(waTemplates.length > 0 || rcsTemplates.length > 0) && !validationReady && (
                    <div role={validationError ? 'alert' : 'status'} className={`p-3 rounded-lg border text-xs ${validationError ? 'bg-rose-50 border-rose-200 text-rose-900' : 'bg-amber-50 border-amber-200 text-amber-900'}`}>
                      <p>{validationError ? `Creative and copy validation failed: ${validationError}` : 'Checking current creative and copy. Whitelisting is paused until validation completes.'}</p>
                      {validationError && (
                        <button type="button" className="mt-1 font-medium underline" onClick={() => {
                          setValidation({ signature: previewSignature, status: 'pending' });
                          setPreviewAttempt((value) => value + 1);
                        }}>
                          Retry validation
                        </button>
                      )}
                    </div>
                  )}
                  {hasValidationErrors && (
                    <button
                      type="button"
                      onClick={prepareValidationComment}
                      disabled={!validationReady || submitting || commentBusy}
                      className="px-3 py-2 rounded-lg border border-rose-300 bg-rose-50 text-rose-800 text-xs font-medium hover:bg-rose-100 disabled:opacity-50"
                    >
                      {commentBusy ? 'Preparing Jira report…' : 'Report validation errors to Jira…'}
                    </button>
                  )}

                  {brief.is_email_campaign && <p className="text-xs text-gray-700">Email campaigns do not need Karix whitelisting. Open More tools for MoEngage staging.</p>}
                </div>

                {/* Creatives Attachment Strip & Image Preview Gallery */}
                {brief.attachments_mapped.length > 0 && (
                  <details className="pt-3 border-t border-gray-100 text-xs">
                    <summary className="cursor-pointer font-medium text-gray-600">Source attachments ({brief.attachments_mapped.length})</summary>

                    <div className="flex items-center gap-3 overflow-x-auto pb-2 scrollbar-thin">
                      {brief.attachments_mapped.map((att) => {
                        const fn = att.filename || '';
                        const isImg = Boolean(
                          att.mime?.startsWith('image/') ||
                          /\.(png|jpe?g|webp|gif|svg)$/i.test(fn)
                        );
                        const source = creativeSource(att.local_path, att.filename, att.id);

                        if (isImg) {
                          return (
                            <div
                              key={att.id || att.filename}
                              className="group relative flex flex-col w-36 shrink-0 rounded-xl border border-gray-200 bg-white overflow-hidden   hover:border-blue-400 transition-colors"
                            >
                              <div className="relative min-h-24 w-full bg-gray-50 flex items-center justify-center">
                                <JiraCreativeImage
                                  source={source}
                                  className="max-h-24 w-full object-contain transition-colors duration-200"
                                  onPreview={() => setPreviewCreativeModal({ ...source, filename: fn, channel: att.target_channel })}
                                />
                                <span className="absolute top-1.5 left-1.5 px-1.5 py-0.5 rounded-lg text-xs font-medium bg-white/90 text-gray-800 ">
                                  {att.target_channel === 'WHATSAPP'
                                    ? 'WhatsApp'
                                    : att.target_channel === 'RCS'
                                    ? 'RCS'
                                    : 'Mapped'}
                                </span>
                              </div>

                              <div className="p-2 flex flex-col justify-between gap-1 text-xs">
                                <span
                                  className="font-mono text-gray-900 truncate font-medium"
                                  title={fn}
                                >
                                  {fn}
                                </span>
                                <div className="flex items-center justify-between gap-1 pt-1 border-t border-gray-100">
                                  <button
                                    type="button"
                                    onClick={() => setPreviewCreativeModal({ ...source, filename: fn, channel: att.target_channel })}
                                    className="text-gray-600 hover:text-gray-600 font-medium"
                                  >
                                    View
                                  </button>
                                  <JiraCreativeDownload
                                    source={source}
                                    className="text-gray-500 hover:text-gray-900 font-medium"
                                  />
                                </div>
                              </div>
                            </div>
                          );
                        }

                        // Non-image file (e.g. spreadsheet, docx brief, mailer zip)
                        const isSpreadsheet = /\.(xlsx|xls|csv)$/i.test(fn);
                        const isDocx = /\.(docx|doc)$/i.test(fn);
                        const isZip = /\.zip$/i.test(fn);
                        return (
                          <div
                            key={att.id || att.filename}
                            className="flex flex-col justify-between w-40 shrink-0 p-3 rounded-xl border border-gray-200 bg-gray-50/70 text-xs  hover:bg-gray-100/70 transition-colors space-y-1.5"
                          >
                            <div className="flex items-center gap-2">
                              <span className="text-base">
                                {isSpreadsheet ? 'XLS' : isDocx ? 'DOC' : isZip ? 'ZIP' : 'File'}
                              </span>
                              <span
                                className="font-mono font-medium text-gray-800 truncate"
                                title={fn}
                              >
                                {fn}
                              </span>
                            </div>
                            <span className="text-xs text-gray-500 font-sans">
                              {isSpreadsheet
                                ? 'Spreadsheet Brief'
                                : isDocx
                                ? 'Document Copy'
                                : isZip
                                ? 'HTML Mailer ZIP'
                                : att.target_channel || 'Attachment'}
                            </span>
                            <div className="pt-1 border-t border-gray-200/80 flex items-center justify-between">
                              <span className="text-xs px-1.5 py-1 rounded-lg font-medium bg-white text-gray-600 border">
                                {att.target_channel || 'BRIEF'}
                              </span>
                              <JiraCreativeDownload
                                source={source}
                                className="px-2 py-0.5 rounded-lg bg-gray-50 hover:bg-gray-100 text-gray-600 font-medium text-xs border border-gray-200"
                              />
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </details>
                )}
              </div>

              {/* Email Campaign Banner if applicable */}
              {brief.is_email_campaign && (
                <div className="p-4 bg-gray-50/80 border border-gray-200 rounded-xl space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    
                    <h3 className="text-xs font-medium text-gray-900 normal-case tracking-normal">
                      Email campaign
                    </h3>
                    <span className="text-xs bg-gray-100 text-gray-600 font-medium px-2 py-0.5 rounded-lg">
                      No Karix whitelisting required
                    </span>
                  </div>
                  <p className="text-xs text-gray-600 leading-relaxed">
                    <strong>{brief.summary}</strong> is an email newsletter brief containing HTML mailer zip packages and preheaders/subject lines. Email mailers are deployed directly through MoEngage Email or your ESP, and do not require Meta / Karix WhatsApp or RCS approval.
                  </p>
                  {brief.attachments_mapped.some((a) => a.filename.endsWith('.zip') || a.filename.endsWith('.docx')) && (
                    <div className="flex flex-wrap items-center gap-2 pt-1">
                      <span className="text-xs text-gray-600 font-medium">Mailer Files:</span>
                      {brief.attachments_mapped
                        .filter((a) => a.filename.endsWith('.zip') || a.filename.endsWith('.docx'))
                        .map((a) => (
                          <span
                            key={a.filename}
                            className="inline-flex items-center gap-2 px-2 py-1 rounded-lg bg-white border border-gray-200 text-sm font-mono font-medium text-gray-600 "
                          >
                            
                            <span>{a.filename}</span>
                          </span>
                        ))}
                    </div>
                  )}
                </div>
              )}

              {/* Multi-Channel Content Tabs */}
              <div className="bg-white rounded-xl border border-gray-200/80  overflow-hidden">
                <div className="flex flex-wrap items-center border-b border-gray-200 bg-gray-50/70">
                  <p className="w-full px-4 pt-4 pb-1 text-sm font-medium text-gray-900">2. Review templates</p>
                  {brief.is_email_campaign ? (
                    <>
                      <button
                        onClick={() => setActiveTab('email')}
                        className={`flex-1 py-3 px-4 text-xs font-medium border-b-2 transition-colors flex items-center justify-center gap-2 ${
                          activeTab === 'email'
                            ? 'border-blue-600 text-gray-900 bg-white'
                            : 'border-transparent text-gray-500 hover:text-gray-700'
                        }`}
                      >
                        <span>Email packages & assets</span>
                        <span className="bg-gray-100 text-gray-600 text-xs px-1.5 py-1 rounded-md font-mono">
                          {brief.email_templates?.length || 0}
                        </span>
                      </button>

                      <button
                        onClick={() => setActiveTab('comments')}
                        className={`flex-1 py-3 px-4 text-xs font-medium border-b-2 transition-colors flex items-center justify-center gap-2 ${
                          activeTab === 'comments'
                            ? 'border-blue-600 text-gray-900 bg-white'
                            : 'border-transparent text-gray-500 hover:text-gray-700'
                        }`}
                      >
                        <span>Comments</span>
                        <span className="bg-gray-100 text-gray-600 text-xs px-1.5 py-1 rounded-md font-mono">
                          {brief.comments?.length || 0}
                        </span>
                      </button>

                      <details className="relative px-3 text-xs">
                        <summary className="cursor-pointer py-3 text-gray-600 hover:text-gray-900 font-medium">More tools</summary>
                        <div className="mt-1 sm:absolute sm:right-0 sm:top-full z-20 min-w-[200px] rounded-lg border border-gray-200 bg-white p-1 shadow-lg">
                          <button
                            type="button"
                            onClick={(e) => {
                              (e.currentTarget.closest('details') as HTMLDetailsElement | null)?.removeAttribute('open');
                              setActiveTab('moengage');
                            }}
                            className={`w-full rounded-md py-2 px-3 text-left text-xs font-medium transition-colors flex items-center justify-between gap-2 ${
                              activeTab === 'moengage'
                                ? 'bg-gray-100 text-gray-900'
                                : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                            }`}
                          >
                            <span>MoEngage email staging</span>
                            <span className="bg-gray-100 text-gray-600 text-xs px-1.5 py-0.5 rounded font-mono">
                              Draft
                            </span>
                          </button>
                        </div>
                      </details>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={() => setActiveTab('whatsapp')}
                        className={`flex-1 py-3 px-4 text-xs font-medium border-b-2 transition-colors flex items-center justify-center gap-2 ${
                          activeTab === 'whatsapp'
                            ? 'border-blue-600 text-gray-900 bg-white'
                            : 'border-transparent text-gray-500 hover:text-gray-700'
                        }`}
                      >
                        <span>WhatsApp</span>
                        <span className="bg-gray-100 text-gray-600 text-xs px-1.5 py-1 rounded-md font-mono">
                          {selectedWaCount}/{waTemplates.length}
                        </span>
                      </button>

                      <button
                        onClick={() => setActiveTab('rcs')}
                        className={`flex-1 py-3 px-4 text-xs font-medium border-b-2 transition-colors flex items-center justify-center gap-2 ${
                          activeTab === 'rcs'
                            ? 'border-blue-600 text-gray-900 bg-white'
                            : 'border-transparent text-gray-500 hover:text-gray-700'
                        }`}
                      >
                        <span>RCS</span>
                        <span className="bg-gray-100 text-gray-600 text-xs px-1.5 py-1 rounded-md font-mono">
                          {selectedRcsCount}/{rcsTemplates.length}
                        </span>
                      </button>

                      <button
                        onClick={() => setActiveTab('sms')}
                        className={`flex-1 py-3 px-4 text-xs font-medium border-b-2 transition-colors flex items-center justify-center gap-2 ${
                          activeTab === 'sms'
                            ? 'border-blue-600 text-gray-900 bg-white'
                            : 'border-transparent text-gray-500 hover:text-gray-700'
                        }`}
                      >
                        <span>SMS</span>
                        <span className="bg-gray-100 text-gray-600 text-xs px-1.5 py-1 rounded-md font-mono">
                          {smsTemplates.length}
                        </span>
                      </button>

                      <button
                        onClick={() => setActiveTab('comments')}
                        className={`flex-1 py-3 px-4 text-xs font-medium border-b-2 transition-colors flex items-center justify-center gap-2 ${
                          activeTab === 'comments'
                            ? 'border-blue-600 text-gray-900 bg-white'
                            : 'border-transparent text-gray-500 hover:text-gray-700'
                        }`}
                      >
                        <span>Comments</span>
                        <span className="bg-gray-100 text-gray-600 text-xs px-1.5 py-1 rounded-md font-mono">
                          {brief.comments?.length || 0}
                        </span>
                      </button>

                      <details className="relative px-3 text-xs">
                        <summary className="cursor-pointer py-3 text-gray-600 hover:text-gray-900 font-medium">More tools</summary>
                        <div className="mt-1 sm:absolute sm:right-0 sm:top-full z-20 min-w-[200px] rounded-lg border border-gray-200 bg-white p-1 shadow-lg">
                          <button
                            type="button"
                            onClick={(e) => {
                              (e.currentTarget.closest('details') as HTMLDetailsElement | null)?.removeAttribute('open');
                              setActiveTab('moengage');
                            }}
                            className={`w-full rounded-md py-2 px-3 text-left text-xs font-medium transition-colors flex items-center justify-between gap-2 ${
                              activeTab === 'moengage'
                                ? 'bg-gray-100 text-gray-900'
                                : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                            }`}
                          >
                            <span>MoEngage staging</span>
                            <span className="bg-gray-100 text-gray-600 text-xs px-1.5 py-0.5 rounded font-mono">
                              Draft
                            </span>
                          </button>
                        </div>
                      </details>
                    </>
                  )}
                </div>

                {/* Tab Content Panels */}
                <div className="p-4 space-y-4">
                  {(activeTab === 'whatsapp' || activeTab === 'rcs') && (
                    <p className="text-xs text-blue-900 bg-blue-50 border border-blue-100 rounded-lg px-3 py-2">{WHITELIST_NAME_HINT}</p>
                  )}
                  {(activeTab === 'whatsapp' || activeTab === 'rcs' || activeTab === 'sms') && (
                    <div className="flex flex-wrap items-center justify-end gap-3">
                      <button
                        type="button"
                        onClick={() => addTemplate(activeTab)}
                        disabled={submitting}
                        className="px-3 py-1.5 rounded-lg text-sm font-medium border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                      >
                        Add template
                      </button>
                    </div>
                  )}
                  {/* WhatsApp Panel */}
                  {activeTab === 'whatsapp' && (
                    <div className="space-y-4">
                      {waTemplates.length > 0 && (
                        <div className="flex flex-wrap items-start justify-between gap-3 pb-2 border-b border-gray-100 text-xs">
                          <div className="flex items-center gap-3">
                            <span className="font-medium text-gray-700">
                              Selected: {selectedWaCount} of {waTemplates.length}
                            </span>
                            <button
                              onClick={() => selectAllWa(selectedWaCount < eligibleWaCount)}
                              disabled={!validationReady || eligibleWaCount === 0}
                              className="text-blue-600 hover:underline font-medium"
                            >
                              {selectedWaCount < eligibleWaCount ? 'Select all eligible' : 'Deselect all'}
                            </button>
                          </div>
                          <span className="text-gray-400 text-xs">
                            Edit copy, variables and CTA buttons before whitelisting.
                          </span>
                        </div>
                      )}

                      {waTemplates.length === 0 ? (
                        <p className="py-8 text-center text-xs text-gray-400">No WhatsApp templates detected in this brief.</p>
                      ) : (
                        waTemplates.map((wa, idx) => {
                          const warnings = getWaWarnings(idx);
                          const isSelected = selectedWa.has(idx);
                          const source = creativeSource(wa.media_file, wa.media_filename, wa.media_attachment_id);
                          const isEditing = editingCard[`wa-${idx}`] || false;
                          const waButtons = (wa.buttons && wa.buttons.length > 0)
                            ? wa.buttons
                            : (wa.button_type && wa.button_type !== 'NONE'
                                ? [{ type: wa.button_type, text: wa.button_text || 'Check Offer', label: wa.button_text || 'Check Offer', url: wa.button_url || '', phone_number: wa.button_phone || '' }]
                                : []);

                          return (
                            <div
                              key={`wa-card-${idx}`}
                              className={`p-4 rounded-xl border transition-colors space-y-3 ${
                                isSelected ? 'bg-white border-gray-300 shadow-xs' : `bg-gray-50/70 border-gray-200${isEditing ? '' : ' opacity-60'}`
                              }`}
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="flex min-w-0 flex-wrap items-center gap-3">
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() => toggleSelectWa(idx)}
                                    disabled={!validationReady}
                                    aria-label={`Select ${wa.template_name} for whitelisting`}
                                    className="w-4 h-4 text-blue-600 rounded-lg border-gray-300 focus:ring-blue-500 cursor-pointer"
                                  />
                                  {isEditing ? (
                                    <div className="flex flex-wrap items-center gap-2">
                                      <div className="flex items-center gap-2">
                                        <label className="text-xs normal-case font-medium text-gray-400">Name:</label>
                                        <input
                                          type="text"
                                          value={wa.template_name}
                                          onChange={(e) => updateWaField(idx, 'template_name', e.target.value)}
                                          onBlur={(e) => updateWaField(idx, 'template_name', normalizeNewTemplateName(e.target.value))}
                                          className="break-all max-w-full font-mono text-sm font-medium border border-gray-300 rounded-lg px-2 py-1 bg-white"
                                        />
                                      </div>
                                      <select
                                        value={wa.category || 'MARKETING'}
                                        onChange={(e) => updateWaField(idx, 'category', e.target.value)}
                                        className="text-sm font-medium border border-gray-300 rounded-lg px-1.5 py-1 bg-white cursor-pointer"
                                      >
                                        <option value="MARKETING">MARKETING</option>
                                        <option value="UTILITY">UTILITY</option>
                                        <option value="AUTHENTICATION">AUTHENTICATION</option>
                                      </select>
                                      <select
                                        value={wa.language || 'en'}
                                        onChange={(e) => updateWaField(idx, 'language', e.target.value)}
                                        className="text-sm font-medium border border-gray-300 rounded-lg px-1.5 py-1 bg-white font-mono cursor-pointer"
                                      >
                                        <option value="en">en (English)</option>
                                        <option value="hi">hi (Hindi)</option>
                                        <option value="gu">gu (Gujarati)</option>
                                        <option value="pa">pa (Punjabi)</option>
                                        <option value="mr">mr (Marathi)</option>
                                        <option value="bn">bn (Bengali)</option>
                                        <option value="ta">ta (Tamil)</option>
                                        <option value="te">te (Telugu)</option>
                                        <option value="kn">kn (Kannada)</option>
                                        <option value="ml">ml (Malayalam)</option>
                                      </select>
                                    </div>
                                  ) : (
                                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                                      <span className="break-all max-w-full font-mono font-medium text-xs text-gray-900">{wa.template_name}</span>
                                      <span className={`text-sm px-2 py-1 rounded-md font-medium normal-case ${
                                        wa.category === 'UTILITY'
                                          ? 'bg-gray-100 text-gray-600'
                                          : wa.category === 'AUTHENTICATION'
                                          ? 'bg-gray-100 text-gray-600'
                                          : 'bg-gray-100 text-gray-600'
                                      }`}>
                                        {wa.category}
                                      </span>
                                      <span className="text-xs px-1.5 py-1 rounded-lg bg-gray-100 text-gray-700 font-mono font-medium normal-case">
                                        {(wa.language || 'en').toUpperCase()}
                                      </span>
                                    </div>
                                  )}
                                </div>

                                <div className="flex items-center gap-2">
                                  {wa.exists_on_waba ? (
                                    <span className="text-xs px-2 py-0.5 rounded-lg font-medium normal-case bg-emerald-50 text-emerald-700 border border-emerald-200">
                                      Live on WABA ({wa.live_status})
                                    </span>
                                  ) : (
                                    <span className="text-xs px-2 py-0.5 rounded-lg font-medium normal-case bg-amber-50 text-amber-700 border border-amber-200">
                                      {warnings.compliance_warnings?.some((warning) => warning.severity === 'error') ? 'Needs attention' : validationReady ? 'Ready for review' : 'Checking…'}
                                    </span>
                                  )}

                                  <button
                                    onClick={() => toggleEditCard(`wa-${idx}`)}
                                    className={`px-3 py-1 rounded-lg text-xs font-medium border transition-colors ${
                                      isEditing
                                        ? 'bg-emerald-50 text-emerald-700 border-emerald-300'
                                        : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50'
                                    }`}
                                  >
                                    {isEditing ? 'Done editing' : 'Edit'}
                                  </button>
                                  {isEditing && <select
                                    defaultValue=""
                                    onChange={(e) => {
                                      const target = e.target.value as 'rcs' | 'sms';
                                      if (target) {
                                        moveTemplate('whatsapp', idx, target);
                                        e.target.value = '';
                                      }
                                    }}
                                    className="text-sm font-medium bg-gray-50 hover:bg-gray-100 border border-gray-300 rounded-lg px-2 py-1 text-gray-700 outline-none cursor-pointer transition-colors "
                                    title="Move this template to another channel"
                                  >
                                    <option value="" disabled>Move channel</option>
                                    <option value="rcs">Move to RCS (DLT)</option>
                                    <option value="sms">Move to SMS (DLT)</option>
                                  </select>}
                                </div>
                              </div>
                              <DraftWarningList draft={warnings} showAspectWarnings={false} />

                              {/* Header Creative — Download, Replace or Remove */}
                              <div className="p-3 bg-gray-50 rounded-lg border border-gray-200 text-xs text-gray-700 space-y-2">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <span className="flex items-center gap-2 font-medium">
                                    <span>Header creative:</span>
                                    {wa.media_filename ? (
                                      <strong className="text-gray-900 font-mono">{wa.media_filename}</strong>
                                    ) : (
                                      <span className="text-gray-400">{wa.header_type === 'NONE' ? 'Header: None' : 'None attached'}</span>
                                    )}
                                  </span>
                                  <div className="flex items-center gap-2">
                                    {(wa.media_file || wa.media_attachment_id) && (
                                      <JiraCreativeDownload
                                        source={source}
                                        className="px-2 py-1 rounded-lg bg-white hover:bg-gray-100 text-blue-700 border border-gray-200 font-medium text-sm  transition-colors"
                                      />
                                    )}
                                    {(wa.header_type && wa.header_type !== 'NONE' || wa.header_text || wa.media_file || wa.media_filename || wa.media_attachment_id) && (
                                      <button
                                        type="button"
                                        onClick={() => removeWaCreative(idx)}
                                        disabled={submitting || uploadingCreative[`wa_${idx}`]}
                                        aria-label={`Remove creative from ${wa.template_name}`}
                                        className="px-2 py-1 rounded-lg bg-white hover:bg-rose-50 text-rose-700 border border-rose-200 font-medium text-sm disabled:opacity-50"
                                      >
                                        Remove creative
                                      </button>
                                    )}
                                    <label className="px-2 py-1 rounded-lg bg-gray-50 hover:bg-gray-100 text-indigo-700 border border-gray-200 font-medium text-sm flex items-center gap-1 cursor-pointer  transition-colors">
                                      <span>{uploadingCreative[`wa_${idx}`] ? 'Uploading…' : wa.media_filename ? 'Replace creative' : 'Upload creative'}</span>
                                      <input
                                        type="file"
                                        accept="image/png,image/jpeg,image/webp,video/mp4,application/pdf"
                                        className="hidden"
                                        disabled={uploadingCreative[`wa_${idx}`]}
                                        onChange={(e) => {
                                          const f = e.target.files?.[0];
                                          if (f) handleReplaceWaCreative(idx, f);
                                          e.target.value = '';
                                        }}
                                      />
                                    </label>
                                  </div>
                                </div>
                                <details className="text-gray-500">
                                  <summary className="cursor-pointer">Header help</summary>
                                  <p className="pt-1">{wa.header_type === 'NONE' ? 'No header will be submitted. Upload a creative to add an image header again.' : 'WhatsApp whitelisting has no image dimension or aspect ratio requirements. A placeholder sample is used for an IMAGE header when no creative is attached. Remove creative sets the header to None instead.'}</p>
                                </details>
                                {(wa.media_file || wa.media_attachment_id) && (
                                  <div className="pt-1">
                                    <JiraCreativeImage
                                      source={source}
                                      className="max-h-36 rounded-lg border border-gray-200 object-contain bg-white hover:opacity-90 transition-opacity "
                                      onPreview={() => setPreviewCreativeModal({ ...source, filename: wa.media_filename || 'whatsapp_creative.jpg', channel: 'WhatsApp' })}
                                    />
                                  </div>
                                )}
                              </div>

                              {/* Text Header */}
                              {wa.header_text && (
                                <div className="text-sm font-medium text-gray-900 bg-gray-50 px-3 py-1.5 rounded-lg border border-gray-200/80 flex items-center gap-2">
                                  <span className="text-gray-400 text-xs font-medium normal-case">Header:</span>
                                  <span>{wa.header_text}</span>
                                </div>
                              )}

                              {isEditing ? (
                                <div className="space-y-3">
                                  {/* Header text edit */}
                                  <div>
                                    <label className="block text-xs text-gray-500 mb-1">Header text (optional)</label>
                                    <input
                                      type="text"
                                      value={wa.header_text || ''}
                                      onChange={(e) => updateWaField(idx, 'header_text', e.target.value)}
                                      placeholder="e.g. Special Festive Offer"
                                      className="w-full text-sm px-3 py-1.5 border border-gray-300 rounded-lg bg-white"
                                    />
                                  </div>

                                  <div className="flex items-center justify-between text-xs text-gray-500">
                                    <span>Template body (use {'{{1}}'}, {'{{2}}'} for variables):</span>
                                    <span>{wa.body.length} chars</span>
                                  </div>
                                  <textarea
                                    value={wa.body}
                                    onChange={(e) => updateWaField(idx, 'body', e.target.value)}
                                    rows={5}
                                    className="w-full p-3 text-sm border border-gray-300 rounded-lg bg-white outline-none focus:ring-2 focus:ring-blue-500"
                                  />

                                  {/* Button controls */}
                                  <div className="space-y-2 pt-2 border-t border-gray-100">
                                    <div className="flex items-center justify-between">
                                      <label className="text-xs font-medium text-gray-700">CTA buttons ({waButtons.length}/3):</label>
                                      {waButtons.length < 3 && (
                                        <button
                                          type="button"
                                          onClick={() => addWaButton(idx)}
                                          className="text-sm font-medium text-blue-600 hover:text-blue-800 flex items-center gap-1 cursor-pointer"
                                        >
                                          + Add CTA button
                                        </button>
                                      )}
                                    </div>
                                    {waButtons.length === 0 ? (
                                      <div className="p-3 bg-gray-50 rounded-lg border border-dashed border-gray-300 flex items-center justify-between text-xs text-gray-500">
                                        <span>No buttons configured.</span>
                                        <button
                                          type="button"
                                          onClick={() => addWaButton(idx)}
                                          className="px-2 py-1 bg-white border border-gray-300 rounded-lg text-sm font-medium text-blue-600 hover:bg-gray-50 cursor-pointer"
                                        >
                                          + Add CTA button
                                        </button>
                                      </div>
                                    ) : (
                                      waButtons.map((btn, bIdx) => (
                                        <div key={bIdx} className="p-3 bg-gray-50 rounded-lg border border-gray-200 space-y-2">
                                          <div className="flex items-center justify-between">
                                            <span className="text-xs font-medium text-gray-700">Button {bIdx + 1}</span>
                                            <button
                                              type="button"
                                              onClick={() => removeWaButton(idx, bIdx)}
                                              className="text-sm font-medium text-red-600 hover:text-red-800 cursor-pointer"
                                            >
                                              Remove CTA
                                            </button>
                                          </div>
                                          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
                                            <div>
                                              <label className="block text-xs text-gray-500 mb-0.5">Type:</label>
                                              <select
                                                value={btn.type || 'URL'}
                                                onChange={(e) => updateWaButton(idx, bIdx, { type: e.target.value })}
                                                className="w-full text-sm px-2 py-1.5 border border-gray-300 rounded-lg bg-white font-medium cursor-pointer"
                                              >
                                                <option value="URL">CTA URL</option>
                                                <option value="QUICK_REPLY">Quick Reply</option>
                                                <option value="PHONE_NUMBER">Phone Call</option>
                                              </select>
                                            </div>
                                            <div>
                                              <label className="block text-xs text-gray-500 mb-0.5">Button text</label>
                                              <input
                                                type="text"
                                                value={btn.text || ('label' in btn && typeof btn.label === 'string' ? btn.label : '')}
                                                onChange={(e) => updateWaButton(idx, bIdx, { text: e.target.value, label: e.target.value })}
                                                placeholder="e.g. Explore Now"
                                                className="w-full text-sm px-2 py-1.5 border border-gray-300 rounded-lg bg-white"
                                              />
                                            </div>
                                            <div>
                                              {btn.type === 'PHONE_NUMBER' ? (
                                                <>
                                                  <label className="block text-xs text-gray-500 mb-0.5">Phone (+91...):</label>
                                                  <input
                                                    type="text"
                                                    value={btn.phone_number || ''}
                                                    onChange={(e) => updateWaButton(idx, bIdx, { phone_number: e.target.value })}
                                                    placeholder="+919876543210"
                                                    className="w-full text-sm px-2 py-1.5 border border-gray-300 rounded-lg bg-white font-mono"
                                                  />
                                                </>
                                              ) : (
                                                <>
                                                  <label className="block text-xs text-gray-500 mb-0.5">Destination URL</label>
                                                  <input
                                                    type="text"
                                                    value={btn.url || ''}
                                                    onChange={(e) => updateWaButton(idx, bIdx, { url: e.target.value })}
                                                    placeholder={TATA_CTA_URL}
                                                    disabled={btn.type === 'QUICK_REPLY'}
                                                    className="w-full text-sm px-2 py-1.5 border border-gray-300 rounded-lg bg-white disabled:bg-gray-100 font-mono text-sm"
                                                  />
                                                </>
                                              )}
                                            </div>
                                          </div>
                                        </div>
                                      ))
                                    )}
                                  </div>
                                </div>
                              ) : (
                                <>
                                  <div className="bg-white p-4 rounded-lg border border-gray-200/80 font-sans text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">
                                    {wa.body}
                                  </div>

                                  {((wa.buttons && wa.buttons.length > 0) ? wa.buttons : (wa.button_type === 'URL' ? [{ type: 'URL', label: wa.button_text, text: wa.button_text, url: wa.button_url }] : [])).map((btn, bIdx) => (
                                    <div key={bIdx} className="flex flex-wrap items-center gap-2 text-xs">
                                      <span className="text-gray-400 font-medium">{(wa.buttons && wa.buttons.length > 1) ? `CTA ${bIdx + 1}:` : 'CTA Button:'}</span>
                                      <span className="px-3 py-1 rounded-lg bg-gray-50 text-blue-700 font-medium border border-gray-200/60 break-all">
                                        {('label' in btn && btn.label) || btn.text || 'Check Offer'} {isUrlCta(btn.type) ? `(${resolveCtaUrl(btn.url, targetAccount)})` : btn.type === 'PHONE_NUMBER' && 'phone_number' in btn ? `(${btn.phone_number || ''})` : ''}
                                      </span>
                                    </div>
                                  ))}

                                  {wa.button_type === 'QUICK_REPLY' && (
                                    <div className="flex items-center gap-2 text-xs">
                                      <span className="text-gray-400">Quick Reply:</span>
                                      <span className="px-3 py-1 rounded-lg bg-emerald-50 text-emerald-700 font-medium border border-emerald-200/60">
                                        {wa.button_text || 'Interested'}
                                      </span>
                                    </div>
                                  )}

                                  {wa.button_type === 'PHONE_NUMBER' && (
                                    <div className="flex items-center gap-2 text-xs">
                                      <span className="text-gray-400">Call Button:</span>
                                      <span className="px-3 py-1 rounded-lg bg-gray-50 text-purple-700 font-medium border border-gray-200/60 font-mono">
                                        {wa.button_text || 'Call Us'} ({wa.button_phone || '+919876543210'})
                                      </span>
                                    </div>
                                  )}
                                </>
                              )}
                            </div>
                          );
                        })
                      )}
                    </div>
                  )}

                  {/* RCS Panel */}
                  {activeTab === 'rcs' && (
                    <div className="space-y-4">
                      {rcsTemplates.length > 0 && (
                        <div className="flex flex-wrap items-start justify-between gap-3 pb-2 border-b border-gray-100 text-xs">
                          <div className="flex items-center gap-3">
                            <span className="font-medium text-gray-700">
                              Selected: {selectedRcsCount} of {rcsTemplates.length}
                            </span>
                            <button
                              onClick={() => selectAllRcs(selectedRcsCount < eligibleRcsCount)}
                              disabled={!validationReady || eligibleRcsCount === 0}
                              className="text-blue-600 hover:underline font-medium"
                            >
                              {selectedRcsCount < eligibleRcsCount ? 'Select all eligible' : 'Deselect all'}
                            </button>
                          </div>
                          <span className="text-gray-400 text-xs">
                            Edit the card title, copy and CTA before whitelisting.
                          </span>
                        </div>
                      )}

                      {rcsTemplates.length === 0 ? (
                        <p className="py-8 text-center text-xs text-gray-400">No RCS templates detected in this brief.</p>
                      ) : (
                        rcsTemplates.map((rcs, idx) => {
                          const warnings = getRcsWarnings(idx);
                          const blocked = isAspectBlocked(warnings);
                          const selectionError = carouselSelectionError(effectiveRcsTemplates[idx]);
                          const isSelected = selectedRcs.has(idx) && !blocked && !selectionError;
                          const source = creativeSource(rcs.media_file, rcs.media_filename, rcs.media_attachment_id);
                          const isEditing = editingCard[`rcs-${idx}`] || false;
                          const rcsSuggestions = (rcs.suggestions && rcs.suggestions.length > 0)
                            ? rcs.suggestions
                            : ((rcs.action_label || rcs.action_url)
                                ? [{ type: rcs.action_type || 'URL', label: rcs.action_label || 'Explore Now', text: rcs.action_label || 'Explore Now', url: rcs.action_url || '' }]
                                : []);

                          return (
                            <div
                              key={`rcs-card-${idx}`}
                              className={`p-4 rounded-xl border transition-colors space-y-3 ${
                                isSelected ? 'bg-white border-gray-300 shadow-xs' : `bg-gray-50/70 border-gray-200${isEditing ? '' : ' opacity-60'}`
                              }`}
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="flex min-w-0 flex-wrap items-center gap-3">
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() => toggleSelectRcs(idx)}
                                    disabled={!validationReady || submitting || (!selectedRcs.has(idx) && (blocked || Boolean(selectionError)))}
                                    aria-label={`Select ${rcs.template_name} for whitelisting`}
                                    className="w-4 h-4 text-blue-600 rounded-lg border-gray-300 focus:ring-blue-500 cursor-pointer"
                                  />
                                  {isEditing ? (
                                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                                      <label className="text-xs normal-case font-medium text-gray-400">Name:</label>
                                      <input
                                        type="text"
                                        value={rcs.template_name}
                                        onChange={(e) => updateRcsField(idx, 'template_name', e.target.value)}
                                        onBlur={(e) => updateRcsField(idx, 'template_name', normalizeNewTemplateName(e.target.value))}
                                        className="break-all max-w-full font-mono text-sm font-medium border border-gray-300 rounded-lg px-2 py-1 bg-white"
                                      />
                                    </div>
                                  ) : (
                                    <span className="break-all max-w-full font-mono font-medium text-xs text-gray-900">{rcs.template_name}</span>
                                  )}
                                  {rcs.template_type === 'carousel' || (rcs.carousel_cards && rcs.carousel_cards.length > 0) ? (
                                    <span className="text-xs px-3 py-0.5 rounded-md bg-gray-100 text-gray-600 font-medium normal-case flex items-center gap-1">
                                      Carousel template ({rcs.carousel_cards?.length || 0} cards)
                                    </span>
                                  ) : (
                                    <span className="text-sm px-2 py-1 rounded-md bg-gray-100 text-gray-600 font-medium normal-case">
                                      Standalone card
                                    </span>
                                  )}
                                </div>

                                <div className="flex items-center gap-2">
                                  {isEditing && <button
                                    onClick={() => handleSyncRcsToMoEngage(rcs)}
                                    disabled={syncingRcs[rcs.template_name]}
                                    className={`px-3 py-1 rounded-lg text-xs font-medium border transition-colors flex items-center gap-2 ${
                                      syncedRcs[rcs.template_name]
                                        ? 'bg-emerald-50 text-emerald-700 border-emerald-300'
                                        : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50'
                                    }`}
                                    title="Register this RCS template directly into MoEngage Settings -> RCS template management"
                                  >
                                    {syncingRcs[rcs.template_name]
                                      ? 'Syncing...'
                                      : syncedRcs[rcs.template_name]
                                      ? 'In MoEngage'
                                      : 'Sync to MoEngage'}
                                  </button>}

                                  <button
                                    onClick={() => toggleEditCard(`rcs-${idx}`)}
                                    className={`px-3 py-1 rounded-lg text-xs font-medium border transition-colors ${
                                      isEditing
                                        ? 'bg-gray-50 text-blue-700 border-blue-300'
                                        : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50'
                                    }`}
                                  >
                                    {isEditing ? 'Done editing' : 'Edit'}
                                  </button>
                                  {isEditing && <select
                                    defaultValue=""
                                    onChange={(e) => {
                                      const target = e.target.value as 'whatsapp' | 'sms';
                                      if (target) {
                                        moveTemplate('rcs', idx, target);
                                        e.target.value = '';
                                      }
                                    }}
                                    className="text-sm font-medium bg-gray-50 hover:bg-gray-100 border border-gray-300 rounded-lg px-2 py-1 text-gray-700 outline-none cursor-pointer transition-colors "
                                    title="Move this template to another channel"
                                  >
                                    <option value="" disabled>Move channel</option>
                                    <option value="whatsapp">Move to WhatsApp</option>
                                    <option value="sms">Move to SMS (DLT)</option>
                                  </select>}
                                </div>
                              </div>
                              <DraftWarningList draft={warnings} />
                              {selectionError && <p role="alert" className="text-xs font-medium text-rose-800">{selectionError}</p>}

                              <div className="p-3 bg-gray-50 rounded-lg border border-gray-200 text-xs text-gray-700 space-y-2">
                                <div className="flex flex-wrap items-center justify-between gap-2">
                                  <span className="flex items-center gap-2 font-medium">
                                    <span>Card creative:</span>
                                    {rcs.media_filename ? (
                                      <strong className="text-gray-900 font-mono">{rcs.media_filename}</strong>
                                    ) : (
                                      <span className="text-gray-400">None attached</span>
                                    )}
                                  </span>
                                  <div className="flex items-center gap-2">
                                    {(rcs.media_file || rcs.media_attachment_id) && (
                                      <JiraCreativeDownload
                                        source={source}
                                        className="px-2 py-1 rounded-lg bg-white hover:bg-gray-100 text-blue-700 border border-gray-200 font-medium text-sm  transition-colors"
                                      />
                                    )}
                                    <label className="px-2 py-1 rounded-lg bg-gray-50 hover:bg-gray-100 text-indigo-700 border border-gray-200 font-medium text-sm flex items-center gap-1 cursor-pointer  transition-colors">
                                      <span>{uploadingCreative[`rcs_${idx}`] ? 'Uploading…' : rcs.media_filename ? 'Replace creative' : 'Upload creative'}</span>
                                      <input
                                        type="file"
                                        accept="image/png,image/jpeg,image/webp,video/mp4"
                                        className="hidden"
                                        disabled={uploadingCreative[`rcs_${idx}`]}
                                        onChange={(e) => {
                                          const f = e.target.files?.[0];
                                          if (f) handleReplaceRcsCreative(idx, f);
                                          e.target.value = '';
                                        }}
                                      />
                                    </label>
                                  </div>
                                </div>
                                {(rcs.media_file || rcs.media_attachment_id) && (
                                  <div className="pt-1">
                                    <JiraCreativeImage
                                      source={source}
                                      className="max-h-36 rounded-lg border border-gray-200 object-contain bg-white hover:opacity-90 transition-opacity "
                                      onPreview={() => setPreviewCreativeModal({ ...source, filename: rcs.media_filename || 'rcs_creative.jpg', channel: 'RCS (2:1 / 1440x720)' })}
                                    />
                                  </div>
                                )}
                              </div>

                              {isEditing ? (
                                <div className="space-y-3">
                                  <div>
                                    <label className="block text-xs text-gray-500 mb-1">Card title</label>
                                    <input
                                      type="text"
                                      value={rcs.card_title}
                                      onChange={(e) => updateRcsField(idx, 'card_title', e.target.value)}
                                      className="w-full text-sm px-3 py-1.5 border border-gray-300 rounded-lg bg-white font-medium"
                                    />
                                  </div>
                                  <div>
                                    <label className="block text-xs text-gray-500 mb-1">Card copy</label>
                                    <textarea
                                      value={rcs.body}
                                      onChange={(e) => updateRcsField(idx, 'body', e.target.value)}
                                      rows={4}
                                      className="w-full p-3 text-sm border border-gray-300 rounded-lg bg-white"
                                    />
                                  </div>
                                  {/* RCS Suggestions / Button controls */}
                                  <div className="space-y-2 pt-2 border-t border-gray-100">
                                    <div className="flex items-center justify-between">
                                      <label className="text-xs font-medium text-gray-700">CTA suggestions ({rcsSuggestions.length}/4):</label>
                                      {rcsSuggestions.length < 4 && (
                                        <button
                                          type="button"
                                          onClick={() => addRcsSuggestion(idx)}
                                          className="text-sm font-medium text-blue-600 hover:text-blue-800 flex items-center gap-1 cursor-pointer"
                                        >
                                          + Add CTA button
                                        </button>
                                      )}
                                    </div>
                                    {rcsSuggestions.length === 0 ? (
                                      <div className="p-3 bg-gray-50 rounded-lg border border-dashed border-gray-300 flex items-center justify-between text-xs text-gray-500">
                                        <span>No CTA buttons configured.</span>
                                        <button
                                          type="button"
                                          onClick={() => addRcsSuggestion(idx)}
                                          className="px-2 py-1 bg-white border border-gray-300 rounded-lg text-sm font-medium text-blue-600 hover:bg-gray-50 cursor-pointer"
                                        >
                                          + Add CTA button
                                        </button>
                                      </div>
                                    ) : (
                                      rcsSuggestions.map((sugg, sIdx) => (
                                        <div key={sIdx} className="p-3 bg-gray-50 rounded-lg border border-gray-200 space-y-2">
                                          <div className="flex items-center justify-between">
                                            <span className="text-xs font-medium text-gray-700">CTA {sIdx + 1}</span>
                                            <button
                                              type="button"
                                              onClick={() => removeRcsSuggestion(idx, sIdx)}
                                              className="text-sm font-medium text-red-600 hover:text-red-800 cursor-pointer"
                                            >
                                              Remove CTA
                                            </button>
                                          </div>
                                          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                            <div>
                                              <label className="block text-xs text-gray-500 mb-0.5">Button label</label>
                                              <input
                                                type="text"
                                                value={sugg.label || sugg.text || ''}
                                                onChange={(e) => updateRcsSuggestion(idx, sIdx, { label: e.target.value, text: e.target.value })}
                                                placeholder="e.g. Apply Now"
                                                className="w-full text-sm px-3 py-1.5 border border-gray-300 rounded-lg bg-white font-medium"
                                              />
                                            </div>
                                            <div>
                                              <label className="block text-xs text-gray-500 mb-0.5">Button Destination URL</label>
                                              <input
                                                type="text"
                                                value={sugg.url || ''}
                                                onChange={(e) => updateRcsSuggestion(idx, sIdx, { url: e.target.value })}
                                                placeholder={TATA_CTA_URL}
                                                className="w-full text-sm px-3 py-1.5 border border-gray-300 rounded-lg bg-white font-mono text-sm"
                                              />
                                            </div>
                                          </div>
                                        </div>
                                      ))
                                    )}
                                  </div>
                                </div>
                              ) : (
                                <div className="bg-white p-4 rounded-lg border border-gray-200/80 space-y-3">
                                  <h4 className="font-medium text-sm text-gray-900">{rcs.card_title}</h4>
                                  <p className="font-sans text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">
                                    {rcs.body}
                                  </p>
                                  {((rcs.suggestions && rcs.suggestions.length > 0) ? rcs.suggestions : ((rcs.action_label || rcs.action_url) ? [{ type: rcs.action_type, label: rcs.action_label, text: rcs.action_label, url: rcs.action_url }] : [])).map((sugg, sIdx) => (
                                    <div key={sIdx} className="pt-2 border-t border-gray-100 flex flex-wrap items-center gap-2 text-xs">
                                      <span className="text-gray-400 font-medium">
                                        {(rcs.suggestions && rcs.suggestions.length > 1) ? `CTA ${sIdx + 1}:` : 'CTA Button:'}
                                      </span>
                                      <span className="px-3 py-1 rounded-lg bg-gray-50 text-blue-700 font-medium border border-gray-200/60 break-all">
                                        {sugg.label || sugg.text || 'Explore Now'} {isUrlCta(sugg.type) ? `(${resolveCtaUrl(sugg.url, targetAccount)})` : 'phone_number' in sugg ? `(${sugg.phone_number || ''})` : ''}
                                      </span>
                                    </div>
                                  ))}
                                </div>
                              )}
                                  {rcs.carousel_cards && rcs.carousel_cards.length > 0 && (
                                    <div className="pt-3 border-t border-gray-100 space-y-2">
                                      <div className="flex items-center justify-between text-xs font-medium text-gray-700">
                                        <span>Carousel cards ({effectiveRcsTemplates[idx].carousel_cards?.length || 0}/{rcs.carousel_cards.length} selected):</span>
                                      </div>
                                      <p className="text-xs text-gray-500">Only checked cards are whitelisted, in their original order. Keep 2–10 cards selected.</p>
                                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                                        {rcs.carousel_cards.map((card, cIdx) => {
                                          const isCardEditing = isEditing || editingCard[`rcs_${idx}_card_${cIdx}`] || false;
                                          const cardSource = creativeSource(card.media_url, card.media_filename, card.media_attachment_id);
                                          const cardIncluded = !rcs.excluded_card_indices?.includes(cIdx);
                                          return (
                                            <div key={`card-${cIdx}`} className={`p-3 rounded-xl border text-xs space-y-3  transition-colors ${cardIncluded ? 'bg-white' : 'bg-gray-50'} ${isCardEditing ? 'border-indigo-400 ring-2 ring-indigo-50' : cardIncluded ? 'border-indigo-200' : 'border-gray-200'}`}>
                                              <div className="flex items-center justify-between gap-2">
                                                <label className="flex items-center gap-2 text-sm font-medium text-indigo-700 cursor-pointer">
                                                  <input
                                                    type="checkbox"
                                                    checked={cardIncluded}
                                                    onChange={() => toggleCarouselCard(idx, cIdx)}
                                                    disabled={submitting}
                                                    aria-label={`Include Card ${cIdx + 1} of ${rcs.template_name} for whitelisting`}
                                                    className="w-4 h-4 text-indigo-600 rounded-lg border-gray-300 focus:ring-indigo-500"
                                                  />
                                                  Card {cIdx + 1}
                                                </label>
                                                <button
                                                  type="button"
                                                  onClick={() => toggleEditCard(`rcs_${idx}_card_${cIdx}`)}
                                                  className={`px-2 py-0.5 rounded-lg text-xs font-medium border transition-colors ${
                                                    isCardEditing
                                                      ? 'bg-gray-50 text-indigo-700 border-indigo-300'
                                                      : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50'
                                                  }`}
                                                >
                                                  {isCardEditing ? 'Done' : 'Edit card'}
                                                </button>
                                              </div>
                                              {cardIncluded
                                                ? <DraftWarningList draft={carouselCardWarnings(rcs, warnings, cIdx)} />
                                                : <p className="text-xs font-medium text-gray-500">Excluded from whitelisting</p>}

                                              {/* Card Creative Image Preview & Individual Upload */}
                                              <div className="rounded-lg overflow-hidden border border-gray-200 bg-gray-50 flex flex-col">
                                                {(card.media_url || card.media_attachment_id) ? (
                                                  <div className="relative min-h-28 w-full bg-white flex items-center justify-center">
                                                    <JiraCreativeImage
                                                      source={cardSource}
                                                      className="w-full max-h-28 object-contain transition-colors"
                                                      onPreview={() => setPreviewCreativeModal({
                                                        ...cardSource,
                                                        filename: card.media_filename || `rcs_card_${cIdx + 1}.jpg`,
                                                        channel: `RCS Card ${cIdx + 1}`,
                                                      })}
                                                    />
                                                  </div>
                                                ) : (
                                                  <div className="h-16 flex items-center justify-center text-xs text-gray-400 bg-gray-50">
                                                    No creative attached
                                                  </div>
                                                )}

                                                <div className="p-1.5 bg-gray-100/70 border-t border-gray-200 flex items-center justify-between text-xs">
                                                  <span className="font-mono text-gray-600 truncate max-w-[120px]" title={card.media_filename || ''}>
                                                    {card.media_filename || 'None'}
                                                  </span>
                                                  <div className="flex items-center gap-2">
                                                    {(card.media_url || card.media_attachment_id) && (
                                                      <JiraCreativeDownload
                                                        source={cardSource}
                                                        className="px-1.5 py-0.5 rounded-lg bg-white hover:bg-gray-50 text-blue-700 border border-gray-200 font-medium text-xs"
                                                      />
                                                    )}
                                                    <label className="px-1.5 py-0.5 rounded-lg bg-gray-50 hover:bg-gray-100 text-indigo-700 border border-gray-200 font-medium text-sm cursor-pointer transition-colors flex items-center gap-0.5">
                                                      <span>{uploadingCreative[`rcs_${idx}_card_${cIdx}`] ? 'Uploading…' : card.media_url ? 'Replace' : 'Upload'}</span>
                                                      <input
                                                        type="file"
                                                        accept="image/png,image/jpeg,image/webp"
                                                        className="hidden"
                                                        disabled={uploadingCreative[`rcs_${idx}_card_${cIdx}`]}
                                                        onChange={(e) => {
                                                          const f = e.target.files?.[0];
                                                          if (f) handleReplaceCarouselCardCreative(idx, cIdx, f);
                                                          e.target.value = '';
                                                        }}
                                                      />
                                                    </label>
                                                  </div>
                                                </div>
                                              </div>

                                              {isCardEditing ? (
                                                <div className="space-y-2 pt-1">
                                                  <div>
                                                    <label className="block text-xs normal-case font-medium text-gray-500 mb-0.5">Card title</label>
                                                    <input
                                                      type="text"
                                                      value={card.card_title}
                                                      onChange={(e) => updateCarouselCardField(idx, cIdx, 'card_title', e.target.value)}
                                                      className="w-full text-sm px-3 py-1.5 border border-gray-300 rounded-lg bg-white font-medium outline-none focus:ring-1 focus:ring-indigo-500"
                                                      placeholder="Card Title"
                                                    />
                                                  </div>
                                                  <div>
                                                    <label className="block text-xs normal-case font-medium text-gray-500 mb-0.5">Card description</label>
                                                    <textarea
                                                      rows={3}
                                                      value={card.card_description}
                                                      onChange={(e) => updateCarouselCardField(idx, cIdx, 'card_description', e.target.value)}
                                                      className="w-full p-2 text-sm border border-gray-300 rounded-lg bg-white outline-none focus:ring-1 focus:ring-indigo-500"
                                                      placeholder="Card Description / Body copy"
                                                    />
                                                  </div>
                                                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                                    <div>
                                                      <label className="block text-xs normal-case font-medium text-gray-500 mb-0.5">CTA Button label</label>
                                                      <input
                                                        type="text"
                                                        value={card.button_text || ''}
                                                        onChange={(e) => updateCarouselCardField(idx, cIdx, 'button_text', e.target.value)}
                                                        placeholder="e.g. Apply Now"
                                                        className="w-full text-sm px-2 py-1 border border-gray-300 rounded-lg bg-white font-medium outline-none focus:ring-1 focus:ring-indigo-500"
                                                      />
                                                    </div>
                                                    <div>
                                                      <label className="block text-xs normal-case font-medium text-gray-500 mb-0.5">CTA URL:</label>
                                                      <input
                                                        type="text"
                                                        value={card.button_url || ''}
                                                        onChange={(e) => updateCarouselCardField(idx, cIdx, 'button_url', e.target.value)}
                                                        placeholder={TATA_CTA_URL}
                                                        className="w-full text-sm px-2 py-1 border border-gray-300 rounded-lg bg-white font-mono outline-none focus:ring-1 focus:ring-indigo-500"
                                                      />
                                                    </div>
                                                  </div>
                                                </div>
                                              ) : (
                                                <div className="space-y-1.5 pt-0.5">
                                                  <h5 className="font-medium text-sm text-gray-900">{card.card_title}</h5>
                                                  <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">{card.card_description}</p>
                                                  <div className="text-xs text-blue-700 font-medium bg-gray-50/50 p-1.5 rounded-lg border border-gray-100 flex flex-wrap items-center gap-1">
                                                    <span>{card.button_text || 'Explore'}</span>
                                                    <span className="text-gray-400 font-mono break-all font-normal">({resolveCtaUrl(card.button_url, targetAccount)})</span>
                                                  </div>
                                                </div>
                                              )}
                                            </div>
                                          );
                                        })}
                                      </div>
                                    </div>
                                  )}
                            </div>
                          );
                        })
                      )}
                    </div>
                  )}

                  {/* SMS Panel */}
                  {activeTab === 'sms' && (
                    <div className="space-y-4">
                      {smsReview?.issueKey === brief.issue_key ? (
                        <SmsDltReview key={smsReview.revision} initialDrafts={smsReview.drafts} storageKey={`briefs_sms_dlt_${smsReview.revision}`} onClose={() => {
                          if (window.confirm('Discard this DLT review and return to source drafts? Provider-field and body edits made in this review will be cleared; any queued batch remains in History.')) setSmsReview(null);
                        }} />
                      ) : <>
                      <div className="rounded-xl border border-gray-200 bg-gray-50 p-4 text-sm">
                        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                          <div className="space-y-1">
                            <h3 className="font-medium text-gray-900">Prepare an SMS review</h3>
                            <p className="max-w-xl leading-relaxed text-gray-600">Select source messages here. Next, apply shared DLT settings once and review exact copy before confirming registration. No SMS is sent.</p>
                            <p className="font-medium text-gray-800">{selectedSmsCount.toLocaleString()} selected across all pages · maximum {BRIEF_SMS_REVIEW_LIMIT} per review</p>
                          </div>
                          <button type="button" className="shrink-0 rounded-lg bg-blue-700 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-800 disabled:bg-gray-200 disabled:text-gray-500" disabled={account !== 'tata' || channel !== 'sms' || loadingBrief || selectedKey !== brief.issue_key || selectedSmsCount === 0 || selectedSmsCount > BRIEF_SMS_REVIEW_LIMIT} onClick={() => {
                            if (account !== 'tata' || channel !== 'sms' || loadingBrief || selectedKey !== brief.issue_key || selectedSmsCount === 0 || selectedSmsCount > BRIEF_SMS_REVIEW_LIMIT) return;
                            setSmsReview({ issueKey: brief.issue_key, drafts: selectedSmsDrafts.map((draft) => smsDltDraft({ template_name: draft.template_name, text: draft.text })), revision: Date.now() });
                          }}>Review selected SMS ({selectedSmsCount})</button>
                        </div>
                        {(account !== 'tata' || channel !== 'sms') && <p role="alert" className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-amber-900">Select Tata Capital (tata) · SMS in Whitelisting for. Other SMS accounts are not integrated; no Tata credentials or Bajaj routing will be inferred.</p>}
                        {selectedSmsCount > BRIEF_SMS_REVIEW_LIMIT && <p role="alert" className="mt-3 text-rose-800">This saved selection exceeds {BRIEF_SMS_REVIEW_LIMIT} messages. Deselect messages or clear the selection before opening a review. No drafts have been removed.</p>}
                      </div>
                      {smsTemplates.length > 0 && <div className="space-y-3 rounded-xl border border-gray-200 p-4">
                        <label className="block text-sm font-medium text-gray-700" htmlFor="sms-draft-search">Search all SMS drafts</label>
                        <input id="sms-draft-search" type="search" value={smsSearch} onChange={(event) => { setSmsSearch(event.target.value); setSmsPageNumber(1); }} placeholder="Template name, exact copy or variant"
                          className="w-full rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-blue-500" />
                        <div className="flex flex-wrap items-center justify-between gap-3">
                          <p role="status" className="text-sm text-gray-600">{matchingSmsIndices.length.toLocaleString()} of {smsTemplates.length.toLocaleString()} messages match{matchingSmsIndices.length > 0 ? ` · showing ${(smsPage.start + 1).toLocaleString()}–${(smsPage.start + smsPage.indices.length).toLocaleString()}` : ''}</p>
                          {smsSearch && <button type="button" onClick={() => { setSmsSearch(''); setSmsPageNumber(1); }} className="text-sm font-medium text-blue-700 hover:underline">Clear SMS search</button>}
                        </div>
                        <div className="flex flex-wrap items-center gap-x-5 gap-y-3 border-t border-gray-100 pt-3 text-sm">
                          <label className="flex items-center gap-2 font-medium text-gray-700">
                            <input type="checkbox" checked={smsPageSelected} disabled={smsPage.indices.length === 0 || (!smsPageSelected && selectedSmsCount + smsPageAdditionCount > BRIEF_SMS_REVIEW_LIMIT)}
                              onChange={(event) => { const select = event.target.checked; setSelectedSms((previous) => selectBriefSmsIndices(previous, smsPage.indices, select)); }} className="h-4 w-4 rounded-lg border-gray-300 text-blue-700" />
                            Select this page ({smsPage.indices.length})
                          </label>
                          {smsTemplates.length <= BRIEF_SMS_REVIEW_LIMIT && <label className="flex items-center gap-2 text-gray-700">
                            <input type="checkbox" checked={selectedSmsCount === smsTemplates.length} onChange={(event) => { const select = event.target.checked; setSelectedSms((previous) => select ? selectBriefSmsIndices(previous, smsTemplates.map((_, index) => index), true) : new Set()); }} className="h-4 w-4 rounded-lg border-gray-300 text-blue-700" />
                            Select entire brief ({smsTemplates.length})
                          </label>}
                          {selectedSmsCount > 0 && <button type="button" onClick={() => setSelectedSms(new Set())} className="font-medium text-gray-600 hover:text-gray-900 hover:underline">Clear all selections ({selectedSmsCount})</button>}
                        </div>
                        <p className="text-xs leading-relaxed text-gray-500">Page selection affects only the {BRIEF_SMS_PAGE_SIZE} or fewer visible messages. Search and paging keep other selections. {smsTemplates.length > BRIEF_SMS_REVIEW_LIMIT ? `Select up to ${BRIEF_SMS_REVIEW_LIMIT} messages across pages for each review; entire-brief selection is unavailable above that limit.` : 'Entire-brief selection includes messages hidden by search.'}</p>
                        {!smsPageSelected && selectedSmsCount + smsPageAdditionCount > BRIEF_SMS_REVIEW_LIMIT && <p role="status" className="text-sm text-amber-800">Selecting this whole page would exceed {BRIEF_SMS_REVIEW_LIMIT}. Select individual messages within the remaining capacity, or clear other selections.</p>}
                        <nav aria-label="SMS draft pages" className="flex flex-wrap items-center justify-between gap-3 border-t border-gray-100 pt-3">
                          <label className="flex items-center gap-2 text-sm text-gray-600">Page
                            <input type="number" min={1} max={smsPage.pageCount} value={smsPage.page} aria-label="SMS draft page number" onChange={(event) => { const page = Number(event.target.value); if (Number.isInteger(page) && page >= 1) setSmsPageNumber(Math.min(page, smsPage.pageCount)); }} className="w-20 rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-sm" />
                            of {smsPage.pageCount.toLocaleString()}
                          </label>
                          <div className="flex gap-2">
                            <button type="button" disabled={smsPage.page <= 1} onClick={() => setSmsPageNumber(smsPage.page - 1)} className="rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40">Previous</button>
                            <button type="button" disabled={smsPage.page >= smsPage.pageCount} onClick={() => setSmsPageNumber(smsPage.page + 1)} className="rounded-lg border border-gray-200 px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40">Next</button>
                          </div>
                        </nav>
                      </div>}
                      {smsTemplates.length === 0 ? (
                        <p className="py-8 text-center text-sm text-gray-500">No SMS variants detected in this brief.</p>
                      ) : matchingSmsIndices.length === 0 ? (
                        <div className="space-y-3 rounded-xl border border-dashed border-gray-200 px-4 py-10 text-center text-sm text-gray-600">
                          <p className="font-medium text-gray-900">No SMS messages match this search</p>
                          <p>Try another name or phrase. All source drafts and selections are unchanged.</p>
                          <button type="button" onClick={() => { setSmsSearch(''); setSmsPageNumber(1); }} className="rounded-lg border border-gray-200 bg-white px-3 py-2 font-medium text-gray-700 hover:bg-gray-50">Show all SMS drafts</button>
                        </div>
                      ) : (
                        smsPage.indices.map((idx) => {
                          const sms = smsTemplates[idx];
                          const isEditing = editingCard[`sms-${idx}`] || false;
                          return (
                            <div key={`sms-card-${idx}`} className="p-4 rounded-xl border border-gray-200 bg-white space-y-3 ">
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="flex min-w-0 flex-wrap items-center gap-2">
                                  <input type="checkbox" aria-label={`Select source message ${idx + 1}: ${sms.template_name} for SMS DLT whitelisting`} checked={selectedSms.has(idx)} disabled={!selectedSms.has(idx) && selectedSmsCount >= BRIEF_SMS_REVIEW_LIMIT}
                                    onChange={(event) => { const select = event.target.checked; setSelectedSms((previous) => selectBriefSmsIndices(previous, [idx], select)); }} className="h-4 w-4 rounded-lg border-gray-300 text-blue-700" />
                                  <span className="text-xs tabular-nums text-gray-500">#{idx + 1}</span>
                                  {isEditing ? (
                                    <input
                                      type="text"
                                      value={sms.template_name}
                                      onChange={(e) => updateSmsField(idx, 'template_name', e.target.value)}
                                      aria-label={`Template name for source message ${idx + 1}`} className="min-w-0 max-w-full rounded-lg border border-gray-300 bg-white px-2 py-1 font-mono text-sm"
                                    />
                                  ) : (
                                    <span className="break-all font-mono text-sm font-medium text-gray-900">{sms.template_name}</span>
                                  )}
                                  <span className="rounded-lg bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600">
                                    {sms.variant}
                                  </span>
                                </div>
                                <div className="flex flex-wrap items-center gap-2">
                                  <span
                                    className={`rounded-lg px-2 py-0.5 font-mono text-xs font-medium ${
                                      sms.char_count <= 160
                                        ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                                        : 'bg-amber-50 text-amber-700 border border-amber-200'
                                    }`}
                                  >
                                    {sms.char_count} chars ({Math.ceil(sms.char_count / 160)} SMS segment)
                                  </span>
                                  <button
                                    onClick={() => toggleEditCard(`sms-${idx}`)}
                                    className={`rounded-lg border px-3 py-1.5 text-sm font-medium transition-colors ${
                                      isEditing
                                        ? 'bg-gray-50 text-purple-700 border-purple-300'
                                        : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50'
                                    }`}
                                  >
                                    {isEditing ? 'Done editing' : 'Edit'}
                                  </button>
                                  {isEditing && <select
                                    defaultValue=""
                                    onChange={(e) => {
                                      const target = e.target.value as 'whatsapp' | 'rcs';
                                      if (target) {
                                        moveTemplate('sms', idx, target);
                                        e.target.value = '';
                                      }
                                    }}
                                    className="rounded-lg border border-gray-200 bg-white px-2 py-1.5 text-sm font-medium text-gray-700"
                                    title="Move this template to another channel"
                                  >
                                    <option value="" disabled>Move channel</option>
                                    <option value="whatsapp">Move to WhatsApp</option>
                                    <option value="rcs">Move to RCS (DLT)</option>
                                  </select>}
                                </div>
                              </div>

                              {isEditing ? (
                                <textarea
                                  rows={4}
                                  value={sms.text}
                                  onChange={(e) => updateSmsField(idx, 'text', e.target.value)}
                                  aria-label={`Message body for source message ${idx + 1}`} className="w-full rounded-lg border border-gray-300 bg-white p-3 font-mono text-sm outline-none focus:ring-2 focus:ring-blue-500"
                                />
                              ) : (
                                <div className="whitespace-pre-wrap break-words rounded-lg border border-gray-200 bg-gray-50 p-4 font-mono text-sm leading-relaxed text-gray-800">
                                  {sms.text}
                                </div>
                              )}
                            </div>
                          );
                        })
                      )}
                      </>}
                    </div>
                  )}
                  {/* Email Packages & Templates Panel */}
                  {activeTab === 'email' && (
                    <div className="space-y-4">
                      <div className="flex flex-wrap items-start justify-between gap-3 pb-2 border-b border-gray-100 text-xs">
                        <span className="font-medium text-gray-700">
                          Email packages & documents ({brief.email_templates?.length || 0} assets)
                        </span>
                        <span className="text-gray-400 text-xs">
                          HTML email packages, preheader documents and exact email copy
                        </span>
                      </div>

                      {(!brief.email_templates || brief.email_templates.length === 0) ? (
                        <p className="py-8 text-center text-xs text-gray-400">No email packages detected in this brief.</p>
                      ) : (
                        brief.email_templates.map((em, idx) => (
                          <div key={`email-asset-${idx}`} className="p-4 rounded-xl border border-gray-200 bg-gray-50/30 space-y-3">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-3">
                                
                                <div>
                                  <h4 className="font-medium text-xs text-gray-900">{em.filename || em.template_name}</h4>
                                  <span className="text-xs text-gray-600 font-medium">{em.file_type || 'Email Asset'}</span>
                                </div>
                              </div>
                              {em.local_path && (
                                <span className="text-xs font-mono bg-white text-emerald-700 px-2 py-0.5 rounded-lg border border-emerald-200 font-medium">
                                  Cached locally
                                </span>
                              )}
                            </div>
                            {em.body && (
                              <div className="bg-white p-3 rounded-lg border border-gray-100 font-sans text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">
                                {em.body}
                              </div>
                            )}
                            {(em.local_path || em.attachment_id) && (
                              <JiraCreativeDownload
                                source={creativeSource(em.local_path, em.filename, em.attachment_id)}
                                className="px-2 py-1 rounded-lg bg-white hover:bg-gray-50 text-purple-700 border border-gray-200 font-medium text-sm"
                              >
                                Download email asset
                              </JiraCreativeDownload>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  )}
                  {/* Comments Panel */}
                  {activeTab === 'comments' && (
                    <div className="space-y-4">
                      <div className="flex flex-wrap items-start justify-between gap-3 pb-2 border-b border-gray-100 text-xs">
                        <span className="font-medium text-gray-700">
                          Jira comments ({brief.comments?.length || 0} comments)
                        </span>
                        <span className="text-gray-400 text-xs">
                          Revisions and copy changes from Jira
                        </span>
                      </div>

                      {(!brief.comments || brief.comments.length === 0) ? (
                        <p className="py-8 text-center text-xs text-gray-400">No comments posted on this Jira ticket yet.</p>
                      ) : (
                        brief.comments.map((comment) => (
                          <div key={comment.id} className="p-4 rounded-xl border border-gray-200 bg-white  space-y-3">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <span className="w-6 h-6 rounded-full bg-gray-100 text-indigo-700 flex items-center justify-center text-xs font-medium">
                                  {comment.author.charAt(0).toUpperCase()}
                                </span>
                                <strong className="text-xs font-medium text-gray-900">{comment.author}</strong>
                              </div>
                              <span className="text-xs text-gray-400 font-mono">
                                {comment.created ? formatDate(comment.created) : ''}
                              </span>
                            </div>
                            <div className="bg-gray-50 p-3 rounded-lg border border-gray-100 font-sans text-sm text-gray-800 whitespace-pre-wrap leading-relaxed">
                              {comment.body_text}
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  )}

                  {/* MoEngage Staging Panel */}
                  {activeTab === 'moengage' && (
                    <div className="space-y-4">
                      {/* Success Banner if created */}
                      {moeResultCampaignId && (
                        <div className="p-4 rounded-xl border border-emerald-300 bg-emerald-50/90 text-emerald-900 space-y-2 ">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              
                              <span className="text-xs font-medium normal-case tracking-normal">
                                {moeStagingStatus === 'CREATED' ? 'Draft confirmed in MoEngage' : 'Draft attempt requires reconciliation'}
                              </span>
                            </div>
                            <span className="px-2 py-0.5 rounded-lg text-xs font-mono font-medium bg-emerald-200 text-emerald-800">
                              {moeRemoteState || 'UNKNOWN'}
                            </span>
                          </div>
                          <div className="flex min-w-0 flex-wrap items-center gap-2 text-xs">
                            <span className="text-gray-600">Campaign ID:</span>
                            <code className="px-2 py-0.5 rounded-lg bg-white border border-emerald-200 font-mono font-medium text-gray-900 select-all">
                              {moeResultCampaignId}
                            </code>
                            <button
                              type="button"
                              onClick={() => {
                                navigator.clipboard.writeText(moeResultCampaignId);
                                setFeedback({ message: `Copied Campaign ID: ${moeResultCampaignId}`, type: 'success' });
                              }}
                              className="px-2 py-0.5 rounded-lg text-xs font-medium bg-emerald-600 hover:bg-emerald-700 text-white"
                            >
                              Copy ID
                            </button>
                            <a
                              href="/moengage-campaigns"
                              className="text-xs font-medium text-emerald-700 hover:underline ml-2"
                            >
                              View in MoEngage Campaigns Builder →
                            </a>
                          </div>
                        </div>
                      )}

                      {/* Error Banner */}
                      {moeError && (
                        <div className="p-3 rounded-xl border border-rose-300 bg-rose-50 text-rose-900 text-xs flex items-center justify-between">
                          <span>{moeError}</span>
                          <button
                            type="button"
                            onClick={() => setMoeError(null)}
                            className="text-rose-600 font-medium hover:text-rose-800"
                          >
                            Dismiss
                          </button>
                        </div>
                      )}

                      {/* Main Interactive Form Card */}
                      <div className="p-4 rounded-xl border border-gray-200 bg-gray-50/40 space-y-4 ">
                        <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-gray-200/60">
                          <div>
                            <div className="flex items-center gap-2">
                              
                              <h3 className="text-xs font-medium text-gray-900 normal-case tracking-normal">
                                MoEngage campaign drafts
                              </h3>
                            </div>
                            <p className="text-xs text-gray-500 mt-0.5">
                              Configure required campaign parameters and stage or create real V5 drafts in MoEngage.
                            </p>
                          </div>
                          <div className="flex items-center gap-2">
                            {loadingCatalog && (
                              <span className="text-xs text-gray-400">Loading catalog...</span>
                            )}
                            <span
                              className={`px-3 py-0.5 rounded-lg text-xs font-medium normal-case ${
                                moeStagingStatus === 'CREATED'
                                  ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                                  : moeStagingStatus === 'STAGED'
                                  ? 'bg-gray-100 text-blue-800 border border-blue-200'
                                  : moeStagingStatus === 'CREATING'
                                  ? 'bg-gray-100 text-indigo-800 border border-indigo-200'
                                  : moeStagingStatus === 'ERROR'
                                  ? 'bg-rose-100 text-rose-800 border border-rose-200'
                                  : 'bg-amber-100 text-amber-800 border border-amber-200'
                              }`}
                            >
                              Status: {moeStagingStatus}
                            </span>
                          </div>
                        </div>

                        {/* Core Form Fields Grid */}
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                          {/* Campaign Name */}
                          <div>
                            <label className="block text-gray-600 font-medium mb-1">
                              Campaign name <span className="text-rose-500">*</span>:
                            </label>
                            <input
                              type="text"
                              value={moeCampaignName}
                              onChange={(e) => setMoeCampaignName(e.target.value)}
                              onBlur={() => setMoeCampaignName(normalizeCampaignName(moeCampaignName))}
                              aria-describedby="jira-campaign-name-rule"
                              placeholder="e.g. att_TCN-546 - Personal Loan Blast"
                              className="w-full px-3 py-1.5 rounded-lg border border-gray-300 text-sm font-medium text-gray-900 bg-white focus:ring-2 focus:ring-amber-500 outline-none"
                            />
                            <p id="jira-campaign-name-rule" className="mt-1 text-xs text-gray-500">{CAMPAIGN_NAME_HINT}</p>
                          </div>

                          {/* Channel Selector */}
                          <div>
                            <label className="block text-gray-600 font-medium mb-1">
                              Campaign channel <span className="text-rose-500">*</span>:
                            </label>
                            <select
                              value={moeChannel}
                              onChange={(e) => setMoeChannel(e.target.value as 'WHATSAPP' | 'EMAIL' | 'PUSH')}
                              className="w-full px-3 py-1.5 rounded-lg border border-gray-300 text-sm font-medium text-gray-900 bg-white focus:ring-2 focus:ring-amber-500 outline-none cursor-pointer"
                            >
                              <option value="WHATSAPP">WhatsApp</option>
                              <option value="EMAIL">Email</option>
                              <option value="PUSH">Push notification</option>
                            </select>
                          </div>
                          {moeChannel === 'WHATSAPP' && (
                            <div>
                              <label className="block text-gray-600 font-medium mb-1">WhatsApp destination workspace (required):</label>
                              <select value={moeWorkspace} onChange={(e) => setMoeWorkspace(e.target.value)} className="w-full px-3 py-1.5 rounded-lg border border-gray-300 text-sm">
                                <option value="">Select and review destination — no default</option>
                                {moeWorkspaces.map((workspace) => <option key={workspace.id} value={workspace.id}>{workspace.name} ({workspace.id})</option>)}
                              </select>
                              <p className="text-xs text-gray-500 mt-1">Only explicit brief workspace fields are carried forward. Review this destination before staging or creating; the queued CSV retains its workspace ID.</p>
                            </div>
                          )}

                          {/* Target Audience / Segment */}
                          <div>
                            <label className="block text-gray-600 font-medium mb-1">
                              Target audience <span className="text-rose-500">*</span>:
                            </label>
                            {moeCatalog?.segments && moeCatalog.segments.length > 0 ? (
                              <select
                                value={moeSegmentId}
                                onChange={(e) => setMoeSegmentId(e.target.value)}
                                className="w-full px-3 py-1.5 rounded-lg border border-gray-300 text-sm font-medium text-gray-900 bg-white focus:ring-2 focus:ring-amber-500 outline-none cursor-pointer"
                              >
                                <option value="">Select workspace audience</option>
                                {moeCatalog.segments.map((seg) => (
                                  <option key={seg.id} value={seg.id}>
                                    {seg.name} ({seg.id})
                                  </option>
                                ))}
                              </select>
                            ) : (
                              <input
                                type="text"
                                value={moeSegmentId}
                                onChange={(e) => setMoeSegmentId(e.target.value)}
                                placeholder="Segment ID, e.g. Test_FSTP_Pranav_1602"
                                className="w-full px-3 py-1.5 rounded-lg border border-gray-300 text-sm font-medium text-gray-900 bg-white focus:ring-2 focus:ring-amber-500 outline-none"
                              />
                            )}
                          </div>

                          {/* Scheduled Date */}
                          <div>
                            <label className="block text-gray-600 font-medium mb-1">
                              Scheduled send time
                            </label>
                            <input
                              type="datetime-local"
                              value={moeScheduledAt ? moeScheduledAt.slice(0, 16) : ''}
                              onChange={(e) => setMoeScheduledAt(e.target.value)}
                              className="w-full px-3 py-1.5 rounded-lg border border-gray-300 text-sm font-medium text-gray-900 bg-white focus:ring-2 focus:ring-amber-500 outline-none"
                            />
                          </div>

                          {/* Channel-Specific Parameters */}
                          {moeChannel === 'WHATSAPP' && (
                            <>
                              <div>
                                <label className="block text-gray-600 font-medium mb-1">
                                  WhatsApp template ID
                                </label>
                                <select value={moeWaTemplateId} onChange={(e) => setMoeWaTemplateId(e.target.value)} className="w-full px-3 py-1.5 rounded-lg border border-gray-300 text-sm">
                                  <option value="">Select approved sender template</option>
                                  {moeCatalog?.whatsapp_templates?.filter((template) => template.sender_ids.includes(moeWaSender)).map((template) => <option key={template.id} value={template.id}>{template.name} ({template.id})</option>)}
                                </select>
                              </div>
                              <div>
                                <label className="block text-gray-600 font-medium mb-1">
                                  WhatsApp sender
                                </label>
                                <select value={moeWaSender} onChange={(e) => { setMoeWaSender(e.target.value); setMoeWaTemplateId(''); }} className="w-full px-3 py-1.5 rounded-lg border border-gray-300 text-sm">
                                  <option value="">Select workspace sender</option>
                                  {moeCatalog?.whatsapp_senders?.map((sender) => <option key={sender.sender_id} value={sender.sender_id}>{sender.name} ({sender.number}) · {sender.provider}</option>)}
                                </select>
                              </div>
                            </>
                          )}

                          {moeChannel === 'EMAIL' && (
                            <>
                              <div>
                                <label className="block text-gray-600 font-medium mb-1">
                                  From address
                                </label>
                                <input
                                  type="email"
                                  value={moeEmailFrom}
                                  onChange={(e) => setMoeEmailFrom(e.target.value)}
                                  placeholder="e.g. contact@tatacapital.com"
                                  className="w-full px-3 py-1.5 rounded-lg border border-gray-300 text-sm font-medium text-gray-900 bg-white focus:ring-2 focus:ring-amber-500 outline-none"
                                />
                              </div>
                              <div>
                                <label className="block text-gray-600 font-medium mb-1">
                                  Email subject
                                </label>
                                <input
                                  type="text"
                                  value={moeEmailSubject}
                                  onChange={(e) => setMoeEmailSubject(e.target.value)}
                                  placeholder="e.g. Festive Loan Offer"
                                  className="w-full px-3 py-1.5 rounded-lg border border-gray-300 text-sm font-medium text-gray-900 bg-white focus:ring-2 focus:ring-amber-500 outline-none"
                                />
                              </div>
                            </>
                          )}

                          {moeChannel === 'PUSH' && (
                            <>
                              <div>
                                <label className="block text-gray-600 font-medium mb-1">
                                  Push title
                                </label>
                                <input
                                  type="text"
                                  value={moePushTitle}
                                  onChange={(e) => setMoePushTitle(e.target.value)}
                                  placeholder="e.g. Tata Capital Offer"
                                  className="w-full px-3 py-1.5 rounded-lg border border-gray-300 text-sm font-medium text-gray-900 bg-white focus:ring-2 focus:ring-amber-500 outline-none"
                                />
                              </div>
                              <div>
                                <label className="block text-gray-600 font-medium mb-1">
                                  Push platform
                                </label>
                                <select
                                  value={moePushPlatform}
                                  onChange={(e) => setMoePushPlatform(e.target.value as 'ANDROID' | 'IOS')}
                                  className="w-full px-3 py-1.5 rounded-lg border border-gray-300 text-sm font-medium text-gray-900 bg-white focus:ring-2 focus:ring-amber-500 outline-none cursor-pointer"
                                >
                                  <option value="ANDROID">Android</option>
                                  <option value="IOS">iOS</option>
                                </select>
                              </div>
                            </>
                          )}
                        </div>

                        {/* Content text area for Push / Email */}
                        {moeChannel === 'PUSH' && (
                          <div>
                            <label className="block text-gray-600 font-medium mb-1 text-xs">
                              Push message body
                            </label>
                            <textarea
                              rows={2}
                              value={moePushBody}
                              onChange={(e) => setMoePushBody(e.target.value)}
                              placeholder="Message body"
                              className="w-full px-3 py-2 rounded-lg border border-gray-300 text-sm text-gray-900 bg-white focus:ring-2 focus:ring-amber-500 outline-none"
                            />
                          </div>
                        )}

                        {moeChannel === 'EMAIL' && (
                          <div>
                            <label className="block text-gray-600 font-medium mb-1 text-xs">
                              Email HTML content
                            </label>
                            <textarea
                              rows={3}
                              value={moeEmailContent}
                              onChange={(e) => setMoeEmailContent(e.target.value)}
                              placeholder="<p>HTML content</p>"
                              className="w-full px-3 py-2 rounded-lg border border-gray-300 font-mono text-sm text-gray-900 bg-white focus:ring-2 focus:ring-amber-500 outline-none"
                            />
                          </div>
                        )}

                        {/* Action Buttons Row */}
                        <div className="pt-3 border-t border-gray-200/80 flex flex-wrap items-center justify-between gap-3">
                          <div className="flex items-center gap-2">
                            <button
                              type="button"
                              onClick={handleMoeCreateDraft}
                              disabled={moeBusy || moeCreateAttempted || !normalizeCampaignName(moeCampaignName).slice(4).trim()}
                              className="px-4 py-2 rounded-lg text-xs font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-300  transition-colors flex items-center gap-2"
                              title="Create real audited V5 draft in MoEngage Live workspace"
                            >
                              
                              <span>{moeBusy && moeStagingStatus === 'CREATING' ? 'Creating Draft...' : 'Create Draft in MoEngage'}</span>
                            </button>

                            <button
                              type="button"
                              onClick={handleMoeStageBatch}
                              disabled={moeBusy || !normalizeCampaignName(moeCampaignName).slice(4).trim()}
                              className="px-4 py-2 rounded-lg text-xs font-medium text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 disabled:opacity-50  transition-colors flex items-center gap-2"
                              title="Stage campaign in local workspace batch queue"
                            >
                              
                              <span>{moeBusy && moeStagingStatus === 'STAGING' ? 'Staging...' : 'Stage in Queue'}</span>
                            </button>
                          </div>

                          {/* Direct Links to MoEngage Studio */}
                          <div className="flex items-center gap-2">
                            <a
                              href={
                                moeChannel === 'WHATSAPP'
                                  ? 'https://dashboard-03.moengage.com/v4/whatsapp/create/one-time/'
                                  : moeChannel === 'EMAIL'
                                  ? 'https://dashboard-03.moengage.com/v4/email/create/one-time/'
                                  : 'https://dashboard-03.moengage.com/v4/push/create/one-time/'
                              }
                              target="_blank"
                              rel="noreferrer"
                              className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm font-medium text-gray-600 bg-white border border-gray-200 hover:bg-gray-50 hover:text-gray-900 transition-colors"
                            >
                              
                              <span>Open in MoEngage {moeChannel === 'WHATSAPP' ? 'WhatsApp' : moeChannel === 'EMAIL' ? 'Email' : 'Push'} Studio ↗</span>
                            </a>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
              {!brief.is_email_campaign && channel !== 'sms' && (activeTab === 'whatsapp' || activeTab === 'rcs') && (
                <div className="sticky bottom-4 z-10 flex flex-wrap items-center gap-3 rounded-xl border border-gray-200 bg-white p-4 sm:pr-44 shadow-lg" aria-label="Whitelisting review">
                  <button
                    type="button"
                    onClick={() => requestWhitelist(channel === 'rcs' ? 'rcs' : 'whatsapp')}
                    disabled={activeTab !== channel || !destinationAvailable || submitting || !validationReady || totalSelectedCount === 0 || (channel === 'rcs' && !currentRcs.botId)}
                    className="rounded-lg bg-blue-700 px-4 py-2 text-sm font-medium text-white hover:bg-blue-800 disabled:bg-gray-300 disabled:text-gray-600"
                  >
                    {submitting ? 'Submitting…' : `Review & whitelist (${totalSelectedCount})`}
                  </button>
                  <div className="min-w-0 text-xs text-gray-600">
                    <p className="font-medium text-gray-900">3. Confirm · {selectedDestinationLabel}</p>
                    <p>{activeTab !== channel ? 'This tab is read-only. Change the whitelisting destination to submit this channel.' : !validationReady ? 'Waiting for current validation.' : totalSelectedCount === 0 ? 'Select at least one template.' : hasValidationErrors ? 'Review the highlighted issues before continuing.' : 'Only checked templates are included. Nothing is sent before confirmation.'}</p>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
    {commentReview && commentReview.signature === previewSignature && validationReady && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" role="dialog" aria-modal="true" aria-labelledby="jira-report-confirmation-title">
        <div className="max-h-[90vh] overflow-y-auto w-full max-w-2xl rounded-2xl border border-gray-200 bg-white p-6 shadow-xl space-y-4">
          <h2 id="jira-report-confirmation-title" className="text-base font-medium text-gray-900">Report validation errors on {commentReview.issueKey}?</h2>
          <p className="text-xs text-gray-600">Review the exact comment below. Nothing is posted until you choose “Yes, post comment”.</p>
          <pre className="max-h-[55vh] overflow-auto whitespace-pre-wrap break-words p-3 rounded-lg border border-gray-200 bg-gray-50 text-sm text-gray-800 font-sans">{commentReview.text}</pre>
          {commentError && <p role="alert" className="text-xs text-rose-800">{commentError}</p>}
          <div className="flex justify-end gap-3">
            <button type="button" onClick={() => setCommentReview(null)} disabled={commentBusy} className="px-4 py-2 rounded-lg border border-gray-300 text-xs font-medium text-gray-700 disabled:opacity-50">Cancel</button>
            <button type="button" onClick={confirmValidationComment} disabled={commentBusy || submitting || !validationReady} className="px-4 py-2 rounded-lg bg-rose-700 hover:bg-rose-800 text-white text-xs font-medium disabled:opacity-50">{commentBusy ? 'Posting comment…' : 'Yes, post comment'}</button>
          </div>
        </div>
      </div>
    )}
    {confirmationMode && brief && (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
        role="dialog"
        aria-modal="true"
        aria-labelledby="whitelist-confirmation-title"
      >
        <div className="max-h-[90vh] overflow-y-auto w-full max-w-md rounded-2xl border border-gray-200 bg-white p-6 shadow-xl space-y-5">
          <div className="flex items-start gap-3">
            <div className="text-sm font-medium text-amber-800 shrink-0">

            </div>
            <div>
              <h2 id="whitelist-confirmation-title" className="text-base font-medium text-gray-900">
                Confirm whitelisting
              </h2>
              <p className="text-xs text-gray-500 mt-1">
                Review this action before sending templates to Karix.
              </p>
            </div>
          </div>

          <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-4 space-y-3 text-xs text-amber-900">
            <p>
              You are about to whitelist the selected templates from <strong>{brief.issue_key}</strong>.
            </p>
            <ul className="list-disc list-inside space-y-1">
              {(confirmationMode === 'all' || confirmationMode === 'whatsapp') && (
                <li>{selectedWaCount} WhatsApp template{selectedWaCount === 1 ? '' : 's'}</li>
              )}
              {(confirmationMode === 'all' || confirmationMode === 'rcs') && (
                <li>{selectedRcsCount} RCS template{selectedRcsCount === 1 ? '' : 's'}</li>
              )}
              {(confirmationMode === 'all' || confirmationMode === 'rcs') && effectiveRcsTemplates.map((draft, index) => (
                selectedRcs.has(index) && isRcsEligible(index) && draft.carousel_cards?.length ? (
                  <li key={`carousel-confirm-${index}`}>
                    {draft.template_name}: {draft.carousel_cards.length} of {rcsTemplates[index].carousel_cards?.length} cards
                    {' '}(Cards {rcsTemplates[index].carousel_cards?.flatMap((_, cardIndex) => rcsTemplates[index].excluded_card_indices?.includes(cardIndex) ? [] : [cardIndex + 1]).join(', ')})
                  </li>
                ) : null
              ))}
            </ul>
            {(confirmationMode === 'all' || confirmationMode === 'whatsapp') && selectedWaCount > 0 && (
              <p className="font-medium text-gray-800">
                WhatsApp destination: <strong>{selectedDestinationLabel}</strong> — WABA
              </p>
            )}

            {/* Dedicated RCS whitelisting destination breakdown inside modal */}
            {(confirmationMode === 'all' || confirmationMode === 'rcs') && selectedRcsCount > 0 && (
              <div className="rounded-xl border border-gray-200 bg-gray-50/90 p-4 space-y-3 text-gray-900">
                <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                  <span className="font-medium text-xs normal-case tracking-normal text-gray-800 flex items-center gap-2">
                    <span>RCS whitelisting destination</span>
                  </span>
                  <span className="font-mono text-xs bg-white px-2 py-0.5 rounded-lg text-gray-800 font-medium border border-gray-300">
                    Bot ID: {currentRcs.botId}
                  </span>
                </div>

                <div className="grid grid-cols-2 gap-2 bg-white/95 p-3 rounded-lg border border-gray-200/80 text-xs">
                  <div>
                    <span className="text-xs text-gray-500 normal-case block font-medium">Target Karix account</span>
                    <span className="font-medium text-gray-900">{currentRcs.name} ({targetAccount.toUpperCase()})</span>
                  </div>
                  <div>
                    <span className="text-xs text-gray-500 normal-case block font-medium">RCS bot name</span>
                    <span className="font-medium text-gray-900">{currentRcs.botName}</span>
                  </div>
                  <div>
                    <span className="text-xs text-gray-500 normal-case block font-medium">Karix portal user</span>
                    <span className="font-mono font-medium text-gray-800">{currentRcs.rcsUser}</span>
                  </div>
                  <div>
                    <span className="text-xs text-gray-500 normal-case block font-medium">DLT entity</span>
                    <span className="font-medium text-gray-800">{currentRcs.entity}</span>
                  </div>
                </div>

                <p className="pt-2 border-t border-gray-200/80 text-gray-600 text-xs">To change destination, close this review and use “Whitelisting for”. Switching clears drafts after confirmation and requires a new preview.</p>
              </div>
            )}

            <p className="pt-2 border-t border-amber-200/80 font-medium">
              After you confirm, the application will submit them to Karix for whitelisting.
            </p>
          </div>

          <div className="flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={() => setConfirmationMode(null)}
              disabled={submitting}
              className="px-4 py-2 rounded-lg border border-gray-300 text-gray-700 text-xs font-medium hover:bg-gray-50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={confirmWhitelist}
              disabled={!destinationAvailable || confirmationMode !== channel || submitting || !validationReady || totalSelectedCount === 0 || (channel === 'rcs' && !currentRcs.botId)}
              className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-xs font-medium hover:bg-emerald-700 disabled:opacity-50"
            >
              {submitting ? 'Whitelisting...' : `Confirm & Whitelist to ${selectedDestinationLabel}`}
            </button>
          </div>
        </div>
      </div>
    )}
    {/* Full-Resolution Creative Lightbox Modal */}
    {previewCreativeModal && (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-4"
        onClick={() => setPreviewCreativeModal(null)}
        role="dialog"
        aria-modal="true"
        aria-labelledby="creative-lightbox-title"
      >
        <div
          className="relative max-w-4xl max-h-[92vh] w-full bg-gray-900 border border-gray-700 rounded-2xl overflow-hidden shadow-xl flex flex-col"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="p-4 bg-gray-950/90 border-b border-gray-800 flex items-center justify-between text-white text-xs">
            <div className="flex min-w-0 flex-wrap items-center gap-2 font-mono">
              
              <span id="creative-lightbox-title" className="font-medium truncate max-w-full sm:max-w-md">
                {previewCreativeModal.filename}
              </span>
              {previewCreativeModal.channel && (
                <span className="px-2 py-0.5 rounded-lg text-xs bg-white/10 font-sans font-medium text-gray-200">
                  {previewCreativeModal.channel}
                </span>
              )}
            </div>
            <div className="flex items-center gap-2">
              <JiraCreativeDownload
                source={previewCreativeModal}
                className="px-3 py-1 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-sans text-sm font-medium  transition-colors"
              >
                Download Creative
              </JiraCreativeDownload>
              <button
                onClick={() => setPreviewCreativeModal(null)}
                className="p-2 rounded-lg text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
                title="Close preview"
                aria-label="Close creative preview"
              >
                <svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" d="M5 5l10 10M15 5L5 15" /></svg>
              </button>
            </div>
          </div>
          <div className="p-4 overflow-auto flex items-center justify-center bg-black/50 min-h-[300px]">
            <JiraCreativeImage
              source={previewCreativeModal}
              className="max-h-[75vh] max-w-full object-contain rounded-lg shadow-md"
            />
          </div>
        </div>
      </div>
    )}
    </>
  );
}
