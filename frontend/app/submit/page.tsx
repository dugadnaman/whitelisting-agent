'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { useTabState, getTabState, clearTabState } from '@/lib/tab-state';
import { loadUploadDraft, saveUploadDraft, saveUploadReview, uploadDraftScope } from '@/lib/upload-draft';
import { useWhitelistingConnection } from '@/components/connection-workflow';
import { previewFile, submitFile, getSampleCsvUrl, fetchJob, resumeJob, identifyTemplates } from '@/lib/api';
import type { TemplatePreview, Template, JobTask, IdentificationReport, TemplateDiscrepancyItem } from '@/lib/api';
import { useApp, getRcsDetails } from '@/lib/context';
import { formatChannel, formatError } from '@/lib/format';
import { destinationLabel } from '@/lib/destination';
import type { Channel } from '@/lib/api';
import { SmsDltUpload } from '@/components/sms-dlt';
import { WHITELIST_NAME_HINT } from '@/lib/jira-template-name';
import { templateOutcome, type TemplateOutcomeInput } from '@/lib/template-status';

function StatusBadge({ item }: { item: TemplateOutcomeInput }) {
  const outcome = templateOutcome(item);
  const colors = {
    success: 'bg-green-100 text-green-800 border-green-200',
    warning: 'bg-amber-100 text-amber-800 border-amber-200',
    error: 'bg-red-100 text-red-800 border-red-200',
    neutral: 'bg-gray-100 text-gray-800 border-gray-200',
  };
  return <span className={`inline-flex rounded-md border px-2 py-1 text-xs font-medium ${colors[outcome.tone]}`}>{outcome.label}</span>;
}

function previewIdentity(preview: TemplatePreview): string {
  return JSON.stringify([preview.source_file, preview.source_ref, preview.source_sheet, preview.source_cell,
    preview.template_name, preview.language, preview.components, preview.text_message,
    preview.template_message, preview.card_title, preview.card_description, preview.carousel_cards]);
}

function PreviewSource({ preview }: { preview: TemplatePreview }) {
  const location = [preview.source_sheet, preview.source_cell].filter(Boolean).join('!');
  const source = [preview.source_file, location, preview.source_ref !== location ? preview.source_ref : null].filter(Boolean).join(' · ');
  return source ? <p className="break-words text-xs text-gray-500">Source: {source}</p> : null;
}

function mergeJobResults(results: Template[], tasks: JobTask[]): Template[] {
  const byId = new Map<string, Template>();
  const bySource = new Map<string, Template | null>();
  for (const result of results) {
    if (result.task_id) byId.set(result.task_id, result);
    const key = `${result.source_ref ?? ''}\0${result.template_name.toLowerCase()}`;
    bySource.set(key, bySource.has(key) ? null : result);
  }
  return tasks.map((task) => {
    const result = byId.get(task.id)
      ?? bySource.get(`${task.source_ref ?? ''}\0${task.template_name.toLowerCase()}`);
    return {
      ...result,
      task_id: task.id, source_ref: task.source_ref || task.template_name, template_name: task.template_name,
      status: task.status.toLowerCase() as Template['status'],
      approval_status: task.approval_status.toLowerCase() as Template['approval_status'],
      provider_ref_id: task.provider_ref_id ?? result?.provider_ref_id,
      registration_outcome: task.registration_outcome ?? result?.registration_outcome,
      provider_response: { ...result?.provider_response, outcome: task.registration_outcome ?? result?.provider_response?.outcome },
      error: task.error ?? null, approval_reason: task.approval_reason ?? null,
      retry_count: task.retry_count, submitted_at: result?.submitted_at || task.created_at,
      client: task.tenant_id, channel: task.channel,
    };
  });
}


type State =
  | { step: 'idle' }
  | { step: 'previewing' }
  | { step: 'previewed'; previews: TemplatePreview[]; uploadId?: string; submissionUncertain?: boolean }
  | { step: 'submitting'; previews: TemplatePreview[]; uploadId?: string }
  | {
      step: 'submitted';
      submitted: number;
      account: string;
      channel: Channel;
      results: Template[];
      jobId?: string;
      isStreaming?: boolean;
      authPaused?: boolean;
      authPausedMessage?: string;
    }
  | { step: 'error'; message: string; previews: TemplatePreview[] | null; uploadId?: string; submissionUncertain?: boolean };


type UploadSelection = { scope: string; id: string; botId?: string; persisted?: boolean };
type SavedReview = { state: State; botId?: string };
function formatBytes(bytes: number): string {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

const ACCEPTED_EXTENSIONS = ['.csv', '.xlsx', '.xls'];

function isAcceptedFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => name.endsWith(ext));
}

export default function SubmitPage() {
  const { account, channel, user, currentUser, setDestination, getAccountLabel, accounts } = useApp();
  const { ensureConnected, reconnect } = useWhitelistingConnection();
  const uploadScope = currentUser && account && account !== 'all'
    ? uploadDraftScope({ userId: currentUser.id, tenant: currentUser.tenant_id, account, channel }) : '';
  const activeRcs = getRcsDetails(account, accounts);
  const [state, setState] = useTabState<State>('submit_state', { step: 'idle' });
  const [review, setReview] = useState<{ account: string; channel: Channel; botId?: string; file: File } | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploadSelection, setUploadSelection] = useTabState<UploadSelection | null>('submit_upload', null);
  const [storageNotice, setStorageNotice] = useState('');
  const [checkingConnection, setCheckingConnection] = useState(false);
  const [inventoryCheck, setInventoryCheck] = useState<{ uploadId: string; checking: boolean; error?: string } | null>(null);
  const [jobRefresh, setJobRefresh] = useState(0);
  const [jobError, setJobError] = useState('');
  const [refreshingJob, setRefreshingJob] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [autoFixGrammar, setAutoFixGrammar] = useTabState<boolean>('submit_auto_fix_grammar', true);
  const [autoSkipDuplicates, setAutoSkipDuplicates] = useTabState<boolean>('submit_auto_skip_duplicates', true);
  const [showBlockedModal, setShowBlockedModal] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const inventoryVersionRef = useRef(0);
  const jobRequestRef = useRef(false);
  const selectionVersionRef = useRef(0);
  const identifyVersionRef = useRef(0);
  const scopeRef = useRef({ account, channel, uploadScope });
  scopeRef.current = { account, channel, uploadScope };
  const previousScopeRef = useRef(uploadScope);
  const mountedRef = useRef(true);

  // Phase 1 Identification Mode
  const [activeTab, setActiveTab] = useTabState<'SUBMIT' | 'IDENTIFY'>('submit_active_tab', 'SUBMIT');
  const [identifyFile, setIdentifyFile] = useState<File | null>(null);
  const [identifying, setIdentifying] = useState<boolean>(false);
  const [identifyReport, setIdentifyReport] = useTabState<IdentificationReport | null>('submit_identify_report', null);
  const [identifyError, setIdentifyError] = useState<string | null>(null);
  const [identifyFilter, setIdentifyFilter] = useTabState<'ALL' | 'MISSING' | 'WHITELISTED' | 'DRIFT' | 'PENDING' | 'REJECTED'>('submit_identify_filter', 'ALL');
  const [identifySearch, setIdentifySearch] = useTabState<string>('submit_identify_search', '');
  const identifyInputRef = useRef<HTMLInputElement>(null);

  const handleIdentifyFileSelect = async (selected: File) => {
    if (!account || account === 'all') return;
    const version = ++identifyVersionRef.current;
    const requestedScope = { account, channel };
    setIdentifyFile(selected);
    setIdentifying(true);
    setIdentifyError(null);
    try {
      const rep = await identifyTemplates(selected, account, channel);
      if (!mountedRef.current || version !== identifyVersionRef.current || scopeRef.current.account !== requestedScope.account || scopeRef.current.channel !== requestedScope.channel) return;
      setIdentifyReport(rep);
    } catch (err: unknown) {
      if (!mountedRef.current || version !== identifyVersionRef.current || scopeRef.current.account !== requestedScope.account || scopeRef.current.channel !== requestedScope.channel) return;
      setIdentifyError(err instanceof Error ? err.message : 'Identification failed');
    } finally {
      if (mountedRef.current && version === identifyVersionRef.current) setIdentifying(false);
    }
  };

  type RawTemplateComponent = {
    type?: string;
    text?: string;
    buttons?: Array<{ text?: string; url?: string }>;
  };
  type RawTemplateRow = {
    template_name?: string;
    category?: string;
    language?: string;
    components?: RawTemplateComponent[];
  };

  const formatMissingRows = (templates: Array<Record<string, unknown>>) => [
    ['template_name', 'category', 'language', 'body_text', 'header_text', 'cta_button_text', 'cta_button_url'],
    ...templates.map((item) => {
      const t = item as unknown as RawTemplateRow;
      const comps = t.components || [];
      const bodyComp = comps.find((c) => c.type === 'BODY');
      const headerComp = comps.find((c) => c.type === 'HEADER');
      const btnComp = comps.find((c) => c.type === 'BUTTONS');
      const firstBtn = btnComp?.buttons?.[0];
      return [
        t.template_name || '',
        t.category || 'MARKETING',
        t.language || 'en',
        bodyComp?.text || '',
        headerComp?.text || '',
        firstBtn?.text || '',
        firstBtn?.url || '',
      ];
    }),
  ];

  const handleHandoffMissingToSubmit = () => {
    if (!identifyReport || identifyReport.missing_templates.length === 0) return;
    const rows = formatMissingRows(identifyReport.missing_templates);
    const csvContent = rows.map((r) => r.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const missingFile = new File([blob], `Missing_${account}_Templates_${new Date().toISOString().slice(0, 10)}.csv`, { type: 'text/csv' });
    // handleFile retains the exact generated bytes before checking the connection.
    setActiveTab('SUBMIT');
    handleFile(missingFile);
  };

  const handleExportMissingCsv = () => {
    if (!identifyReport || identifyReport.missing_templates.length === 0) return;
    const rows = formatMissingRows(identifyReport.missing_templates);
    const csvContent = 'data:text/csv;charset=utf-8,' + rows.map((r) => r.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `Missing_${account}_Templates_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };
  const submittedJobId = state.step === 'submitted' && state.account === account && state.channel === channel ? state.jobId : undefined;
  useEffect(() => {
    if (!submittedJobId || channel === 'sms') return;
    const requestedScope = scopeRef.current;
    let cancelled = false;
    let timer: NodeJS.Timeout | undefined;
    let needsRefresh = true;
    const current = () => !cancelled && mountedRef.current
      && scopeRef.current.uploadScope === requestedScope.uploadScope;
    async function refresh() {
      clearTimeout(timer);
      if (!current() || document.visibilityState !== 'visible' || !needsRefresh) return;
      if (jobRequestRef.current) { timer = setTimeout(refresh, 250); return; }
      jobRequestRef.current = true;
      setRefreshingJob(true);
      try {
        const snapshot = await fetchJob(submittedJobId!);
        if (!current()) return;
        const terminal = ['COMPLETED', 'PARTIALLY_COMPLETED', 'FAILED'].includes(snapshot.job.status);
        const awaitingApproval = snapshot.tasks.some((task) => !templateOutcome(task).unknown
          && ['SUBMITTED', 'DUPLICATE'].includes(task.status)
          && !['approved', 'rejected', 'blocked_aspect_ratio'].includes(task.approval_status));
        needsRefresh = !terminal || awaitingApproval;
        setJobError('');
        setState((previous) => previous.step === 'submitted' && previous.jobId === submittedJobId ? {
          ...previous, results: mergeJobResults(previous.results, snapshot.tasks), isStreaming: !terminal,
          authPaused: snapshot.job.status === 'PAUSED_FOR_AUTH', authPausedMessage: snapshot.job.error_message,
        } : previous);
        if (needsRefresh && document.visibilityState === 'visible') timer = setTimeout(refresh, terminal ? 10000 : 2500);
      } catch (error) {
        if (current()) setJobError(`Could not read stored job status. ${formatError(error)} Your queued batch is unchanged; retry status or open History, not submission.`);
      } finally {
        jobRequestRef.current = false;
        if (current()) setRefreshingJob(false);
      }
    }
    const visibilityChanged = () => {
      clearTimeout(timer);
      if (document.visibilityState === 'visible') void refresh();
    };
    void refresh();
    document.addEventListener('visibilitychange', visibilityChanged);
    return () => { cancelled = true; clearTimeout(timer); document.removeEventListener('visibilitychange', visibilityChanged); };
  }, [submittedJobId, uploadScope, channel, jobRefresh]);

  useEffect(() => {
    mountedRef.current = true;
    inventoryVersionRef.current++;
    return () => {
      mountedRef.current = false;
      identifyVersionRef.current++;
      selectionVersionRef.current++;
      inventoryVersionRef.current++;
    };
  }, []);
  useEffect(() => {
    const previousScope = previousScopeRef.current;
    previousScopeRef.current = uploadScope;
    if (previousScope === uploadScope || !previousScope) return;
    selectionVersionRef.current++;
    identifyVersionRef.current++;
    setIdentifyReport(null);
    setIdentifyFile(null);
    setIdentifying(false);
    setReview(null);
    setShowBlockedModal(false);
    setCheckingConnection(false);
    setStorageNotice('');
    inventoryVersionRef.current++;
    setInventoryCheck(null);
    setJobError('');
    setRefreshingJob(false);
    setState({ step: 'idle' });
    setFile(null);
    setUploadSelection(null);
  }, [uploadScope]);

  useEffect(() => {
    const failedClear = () => setStorageNotice('Browser storage could not delete the saved file. Close other workspace tabs and retry Remove before leaving this device.');
    window.addEventListener('karix-upload-storage-error', failedClear);
    return () => window.removeEventListener('karix-upload-storage-error', failedClear);
  }, []);

  useEffect(() => {
    if (!uploadScope || channel === 'sms') return;
    let cancelled = false;
    const version = selectionVersionRef.current;
    const saved = getTabState<UploadSelection | null>('submit_upload', null);
    const cached = getTabState<State>('submit_state', { step: 'idle' });
    if (cached.step === 'submitted') {
      if (cached.account !== account || cached.channel !== channel) setState({ step: 'idle' });
      return;
    }
    if (!saved || saved.scope !== uploadScope) {
      if (cached.step !== 'idle') setStorageNotice('The original upload is unavailable. Select it again to validate these templates; no file will be reconstructed from previews.');
      return;
    }
    void loadUploadDraft<SavedReview>(uploadScope, saved.id).then((restored) => {
      if (cancelled || version !== selectionVersionRef.current || scopeRef.current.uploadScope !== uploadScope) return;
      if (!restored) throw new Error('The original saved file is unavailable. Select it again; no templates have been resubmitted.');
      setFile(restored.file);
      setUploadSelection({ ...saved, persisted: true });
      const restoredState = cached.step === 'idle' ? restored.review?.state || cached : cached;
      if ((restoredState.step === 'previewed' || restoredState.step === 'error' || restoredState.step === 'submitting') && restoredState.uploadId === saved.id) {
        setReview({ account, channel, botId: restored.review?.botId ?? saved.botId, file: restored.file });
        setState(restoredState.step === 'submitting'
          ? { step: 'error', message: 'The submission response was lost. Check History before submitting again: the queue may already contain this upload.', previews: restoredState.previews, uploadId: restoredState.uploadId, submissionUncertain: true }
          : restoredState);
      }
      if (cached.step === 'previewing') setState({ step: 'idle' });
    }).catch((error) => {
      if (!cancelled && version === selectionVersionRef.current) setStorageNotice(formatError(error));
    });
    return () => { cancelled = true; };
  }, [uploadScope]);

  useEffect(() => {
    if (!uploadSelection || uploadSelection.scope !== uploadScope || !review || review.file !== file) return;
    if (state.step !== 'previewed' && state.step !== 'error') return;
    if (state.uploadId !== uploadSelection.id) return;
    const version = selectionVersionRef.current;
    void saveUploadReview(uploadScope, uploadSelection.id, { state, botId: review.botId }).catch((error) => {
      if (mountedRef.current && version === selectionVersionRef.current && scopeRef.current.uploadScope === uploadScope) {
        setStorageNotice(`The file review could not be saved. Keep this page open. ${formatError(error)}`);
      }
    });
  }, [state, uploadSelection, uploadScope, review, file]);

  const verifyInventory = useCallback(async (selected: File, uploadId: string, baseline: TemplatePreview[]) => {
    const version = ++inventoryVersionRef.current;
    const selectionVersion = selectionVersionRef.current;
    const requestedScope = uploadScope;
    const current = () => mountedRef.current && version === inventoryVersionRef.current
      && selectionVersion === selectionVersionRef.current && scopeRef.current.uploadScope === requestedScope;
    setInventoryCheck({ uploadId, checking: true });
    try {
      const verified = await previewFile(selected, account, channel, { verifyInventory: true });
      if (!current()) return;
      if (verified.length !== baseline.length || verified.some((preview, index) => previewIdentity(preview) !== previewIdentity(baseline[index]))) {
        throw new Error('Inventory returned a different set of messages. Your original preview is retained; retry the inventory check.');
      }
      if (verified.some((preview) => preview.inventory_status !== 'verified')) {
        throw new Error(verified.find((preview) => preview.inventory_error)?.inventory_error || 'Inventory is unavailable. Existing templates are unknown, not missing.');
      }
      setState((previous) => {
        if (previous.step !== 'previewed' || previous.uploadId !== uploadId
          || previous.previews.length !== baseline.length
          || previous.previews.some((preview, index) => previewIdentity(preview) !== previewIdentity(baseline[index]))) return previous;
        return { ...previous, previews: previous.previews.map((preview, index) => ({
          ...preview, inventory_status: verified[index].inventory_status, inventory_error: verified[index].inventory_error,
          submission_ready: verified[index].submission_ready, already_exists_on_waba: verified[index].already_exists_on_waba,
          exists_on_waba: verified[index].exists_on_waba, duplicate_warning: verified[index].duplicate_warning,
        })) };
      });
      setInventoryCheck({ uploadId, checking: false });
    } catch (error) {
      if (current()) setInventoryCheck({ uploadId, checking: false, error: formatError(error) });
    }
  }, [account, channel, uploadScope]);

  const handleFile = useCallback(
    async (selected: File) => {
      if (!uploadScope) return;
      const version = ++selectionVersionRef.current;
      const requestedScope = { account, channel };
      if (!account || account === 'all') {
        setState({ step: 'error', message: 'Choose an account in “Whitelisting for” before uploading.', previews: null });
        return;
      }
      inventoryVersionRef.current++;
      setInventoryCheck(null);
      if (!isAcceptedFile(selected)) {
        setState({ step: 'error', message: 'Please upload a .csv, .xlsx, or .xls file.', previews: null });
        return;
      }
      const sameFile = file === selected;
      setFile(selected);
      setStorageNotice('');
      if (!sameFile) { setReview(null); setState({ step: 'idle' }); }
      const uploadId = sameFile && uploadSelection?.scope === uploadScope ? uploadSelection.id : crypto.randomUUID();
      const selection = { scope: uploadScope, id: uploadId, botId: activeRcs.botId || undefined };
      // Publish the identity before the async write so route navigation can restore it.
      setUploadSelection({ ...selection, persisted: sameFile && uploadSelection?.persisted });
      if (!sameFile || !uploadSelection?.persisted) {
        try {
          await saveUploadDraft(uploadScope, selected, uploadId);
          if (!mountedRef.current || version !== selectionVersionRef.current || scopeRef.current.uploadScope !== uploadScope) return;
          setUploadSelection({ ...selection, persisted: true });
        } catch (error) {
          if (!mountedRef.current || version !== selectionVersionRef.current || scopeRef.current.uploadScope !== uploadScope) return;
          setStorageNotice(`This file is available in this page only; browser storage failed. Keep this page open or select the original file again after navigation. ${formatError(error)}`);
        }
      }
      if (!mountedRef.current || version !== selectionVersionRef.current || scopeRef.current.uploadScope !== uploadScope) return;
      setState({ step: 'previewing' });
      try {
        const parsed = await previewFile(selected, account, channel, { verifyInventory: false });
        const previews = parsed.map((preview) => ({ ...preview, inventory_status: 'unverified' as const, submission_ready: false }));
        if (!mountedRef.current || version !== selectionVersionRef.current || scopeRef.current.account !== account || scopeRef.current.channel !== channel) return;
        setReview({ ...requestedScope, botId: activeRcs.botId || undefined, file: selected });
        setState({ step: 'previewed', previews, uploadId });
        void verifyInventory(selected, uploadId, previews);
      } catch (err) {
        if (!mountedRef.current || version !== selectionVersionRef.current || scopeRef.current.account !== account || scopeRef.current.channel !== channel) return;
        setState({
          step: 'error',
          message: err instanceof Error ? err.message : 'Failed to parse template file.',
          previews: null,
          uploadId,
        });
      }
    },
    [account, channel, activeRcs.botId, uploadScope, file, uploadSelection, verifyInventory]
  );

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDragging(false);
      const dropped = e.dataTransfer.files?.[0];
      if (dropped) handleFile(dropped);
    },
    [handleFile]
  );

  const handleInputChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const selected = e.target.files?.[0];
      if (selected) handleFile(selected);
    },
    [handleFile]
  );

  const handleClear = useCallback(() => {
    selectionVersionRef.current++;
    inventoryVersionRef.current++;
    setInventoryCheck(null);
    setJobError('');
    clearTabState('submit_upload');
    setUploadSelection(null);
    setStorageNotice('');
    setCheckingConnection(false);
    setReview(null);
    setRefreshingJob(false);
    setFile(null);
    setState({ step: 'idle' });
    if (inputRef.current) inputRef.current.value = '';
  }, [setUploadSelection]);
  const currentPreviews = state.step === 'previewed' ? state.previews : null;
  const executeSubmit = useCallback(async (fixGrammar: boolean) => {
    if (!file || !currentPreviews?.length || state.step !== 'previewed' || state.submissionUncertain || !review || review.file !== file || review.account !== account || review.channel !== channel) return;
    if (inventoryCheck?.checking || currentPreviews.some((preview) => preview.inventory_status !== 'verified' || preview.submission_ready === false)) return;
    if (channel === 'rcs' && (!review.botId || review.botId !== activeRcs.botId)) {
      setState({
        step: 'error',
        message: `RCS bot is not configured for ${account}. Refresh account settings before submitting.`,
        previews: currentPreviews,
        uploadId: uploadSelection?.id,
      });
      return;
    }
    setShowBlockedModal(false);
    const version = selectionVersionRef.current;
    setCheckingConnection(true);
    const connected = await ensureConnected();
    if (!mountedRef.current || version !== selectionVersionRef.current || scopeRef.current.uploadScope !== uploadScope) return;
    setCheckingConnection(false);
    if (!connected) return;
    const submitting: State = { step: 'submitting', previews: currentPreviews, uploadId: uploadSelection?.id };
    setState(submitting);
    if (uploadSelection) {
      try { await saveUploadReview(uploadScope, uploadSelection.id, { state: submitting, botId: review.botId }); }
      catch (error) {
        if (mountedRef.current && version === selectionVersionRef.current && scopeRef.current.uploadScope === uploadScope) setStorageNotice(`The submission status could not be saved in browser storage. Check History if this page closes. ${formatError(error)}`);
      }
    }
    if (!mountedRef.current || version !== selectionVersionRef.current || scopeRef.current.uploadScope !== uploadScope) return;
    try {
      const res = await submitFile(
        file, account, channel, user, fixGrammar, autoSkipDuplicates,
        review, channel === 'rcs' ? review.botId : undefined
      );
      if (!mountedRef.current || version !== selectionVersionRef.current || scopeRef.current.account !== account || scopeRef.current.channel !== channel) return;
      const isComplete = !res.job_id || ['COMPLETED', 'PARTIALLY_COMPLETED', 'FAILED'].includes(res.status || '');
      setState({
        step: 'submitted',
        account: res.account,
        channel: res.channel,
        submitted: res.submitted,
        results: res.results,
        jobId: res.job_id,
        isStreaming: !isComplete,
      });
    } catch (err) {
      if (!mountedRef.current || version !== selectionVersionRef.current || scopeRef.current.account !== account || scopeRef.current.channel !== channel) return;
      // Preserve the parsed previews so a transient failure doesn't force a re-upload.
      setState({
        step: 'error',
        message: `${err instanceof Error ? err.message : 'Submission failed.'} Check History before trying again: if the response was lost, this upload may already be queued. Nothing will be retried automatically.`,
        previews: currentPreviews,
        uploadId: uploadSelection?.id,
        submissionUncertain: true,
      });
    }
  }, [file, account, channel, user, currentPreviews, state, review, autoSkipDuplicates, activeRcs.botId, ensureConnected, uploadScope, uploadSelection, inventoryCheck]);

  const handleInitiateSubmit = useCallback(async () => {
    if (checkingConnection || inventoryCheck?.checking || state.step !== 'previewed' || state.submissionUncertain || !file || !currentPreviews?.length || currentPreviews.some((preview) => preview.inventory_status !== 'verified' || preview.submission_ready === false)) return;
    const version = selectionVersionRef.current;
    setCheckingConnection(true);
    const connected = await ensureConnected();
    if (!mountedRef.current || version !== selectionVersionRef.current || scopeRef.current.uploadScope !== uploadScope) return;
    setCheckingConnection(false);
    if (!connected) return;
    const blocked = channel === 'rcs' ? currentPreviews.filter(
      p => p.aspect_ratio_blocked || (p.aspect_ratio_warnings && p.aspect_ratio_warnings.some(w => w.blocked))
    ) : [];
    if (blocked.length === currentPreviews.length) {
      alert(
        `Cannot submit: All ${blocked.length} templates have invalid image aspect ratios and will NOT be created. Auto-resizing has been removed. Please update the images in your spreadsheet to the recommended aspect ratio (e.g. 16:9 or 1:1).`
      );
      return;
    }
    if (blocked.length > 0) {
      setShowBlockedModal(true);
      return;
    }
    executeSubmit(autoFixGrammar);
  }, [file, currentPreviews, state, channel, autoFixGrammar, executeSubmit, ensureConnected, uploadScope, checkingConnection, inventoryCheck]);
  const handleReset = useCallback(() => {
    handleClear();
  }, [handleClear]);

  const accountLabel = getAccountLabel(account);
  const channelLabel = formatChannel(channel);
  const reviewedLabel = review ? destinationLabel(review.account, review.channel, getAccountLabel(review.account)) : '';

  if (channel === 'sms') return <SmsDltUpload key={`${account}:${channel}`} />;

  return (
    <div className="workspace-page min-w-0 space-y-6">
      {account === 'all' && <p role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">Choose a specific account in “Whitelisting for” before previewing or submitting templates.</p>}
      {storageNotice && <p role="alert" className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">{storageNotice}</p>}
      {checkingConnection && <p role="status" className="text-sm text-gray-600">Checking this destination’s provider connection…</p>}
      {/* Page Header */}
      <header className="flex flex-col sm:flex-row sm:items-start sm:justify-between gap-4 pb-6 border-b border-gray-200">
        <div className="min-w-0">
          <p className="workspace-eyebrow mb-2">Template library</p>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="workspace-heading">Upload templates</h1>
            <span className="text-sm text-gray-600">
              {accountLabel} &bull; {channelLabel}
            </span>
            {channel === 'rcs' && (
              <span className="inline-flex max-w-full flex-wrap items-center gap-2 text-xs text-gray-600">
                <span>Bot: <strong>{activeRcs.botName}</strong></span>
                <span className="font-mono text-xs text-gray-700">({activeRcs.botId || 'Not configured'})</span>
              </span>
            )}
          </div>
          <p className="text-sm text-gray-500 mt-1">
            Upload a spreadsheet of {channelLabel} templates to validate, preview, and submit for {accountLabel}.
          </p>
          {channel === 'whatsapp' && (
            <p className="mt-2 text-sm leading-relaxed text-gray-600">
              Flexible format: message/copy/content columns are detected automatically. Template name, category, language, header, and CTA columns are optional.
            </p>
          )}
        </div>

        {/* Sample download */}
        <a
          href={getSampleCsvUrl(channel)}
          download
          className="workspace-button shrink-0"
        >
          <svg className="w-4 h-4 text-gray-500" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path d="M10 3v10M6 9l4 4 4-4M3 15h14" />
          </svg>
          Download sample CSV ({channelLabel})
        </a>
      </header>


      {/* APPAREL ACCOUNT: EXCLUSIVELY SYNC TO MOENGAGE */}
      {account === 'apparel' ? (
        <div className="workspace-panel max-w-2xl p-6 space-y-4">
          <div className="space-y-2">
            <p className="workspace-eyebrow">Apparel · RCS only</p>
            <h2 className="text-xl font-medium text-gray-900">Sync approved templates to MoEngage</h2>
            <p className="workspace-description">
              Pull approved Karix RCS templates into your selected Apparel MoEngage workspace.
              Manual spreadsheet submissions are disabled for this account.
            </p>
          </div>
          <div className="pt-2">
            <a href="/" className="workspace-button-primary">
              Open template sync <span aria-hidden="true">→</span>
            </a>
          </div>
        </div>
      ) : (
        <>
      {/* Two-Phase Architecture Switcher */}
      <div className="workspace-toolbar border-b border-gray-200 pb-3" aria-label="Template upload workflow">
        <button
          onClick={() => setActiveTab('SUBMIT')}
          aria-pressed={activeTab === 'SUBMIT'}
          className={activeTab === 'SUBMIT' ? 'workspace-button-primary' : 'workspace-button'}
        >
          Upload &amp; whitelist
        </button>
        <button
          onClick={() => setActiveTab('IDENTIFY')}
          aria-pressed={activeTab === 'IDENTIFY'}
          className={activeTab === 'IDENTIFY' ? 'workspace-button-primary' : 'workspace-button'}
        >
          Compare master catalog
        </button>
      </div>

      {activeTab === 'SUBMIT' && (
        <div className="space-y-6">
          <ol aria-label="Upload progress" className="flex gap-4 overflow-x-auto border-b border-gray-200 pb-3 text-sm">
            {['Upload file', 'Review templates', 'Confirm & track'].map((label, index) => {
              const step = state.step === 'submitted' || state.step === 'submitting' ? 2 : state.step === 'previewed' ? 1 : 0;
              return <li key={label} aria-current={step === index ? 'step' : undefined} className={`shrink-0 ${step === index ? 'font-medium text-gray-900' : 'text-gray-500'}`}><span className="mr-2 font-mono tabular-nums">{index + 1}.</span>{label}</li>;
            })}
          </ol>
          <details className="workspace-guide">
            <summary className="cursor-pointer font-medium text-gray-800">Before you upload</summary>
            <p className="mt-3">Check the account and channel above, then upload your spreadsheet. <button type="button" onClick={reconnect} className="text-gray-700 underline">Reconnect this destination</button> here if needed. Review copy, creatives and validation before confirming. Uploading alone does not whitelist templates.</p>
          </details>

      {/* STEP 1: Upload Dropzone (Visible when idle, error, previewing, previewed) */}
      {state.step !== 'submitted' && (
        <div className="bg-white rounded-xl border border-gray-200/80 p-6">
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
            role="button"
            tabIndex={0}
            aria-label="Choose template spreadsheet"
            onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); inputRef.current?.click(); } }}
            className={`border-2 border-dashed rounded-xl p-6 sm:p-10 text-center transition-colors cursor-pointer ${
              dragging
                ? 'border-blue-500 bg-gray-50/50 ring-4 ring-blue-50'
                : file
                ? 'border-gray-400 bg-gray-50/20'
                : 'border-gray-300 hover:border-gray-400 hover:bg-gray-50/50'
            }`}
          >
            <input
              ref={inputRef}
              type="file"
              accept=".csv,.xlsx,.xls"
              onChange={handleInputChange}
              className="hidden"
            />
            <div className="flex flex-col items-center">
              <div className="mb-3 flex h-8 w-8 items-center justify-center text-gray-500">
                <svg className="h-4 w-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
                  <path d="M10 14V3M5 7l5-5 5 5M3 17h14" />
                </svg>
              </div>
              <p className="text-sm font-medium text-gray-900">
                Drop your {channelLabel} CSV or Excel spreadsheet here
              </p>
              <p className="text-xs text-gray-500 mt-1">
                Supports <span className="font-medium text-gray-700">.xlsx, .xls, .csv</span> files
              </p>
            </div>
          </div>

          {/* Selected File Info */}
          {file && (
            <div className="mt-4 flex min-w-0 items-center justify-between gap-3 rounded-lg border border-gray-200 bg-gray-50 p-3">
              <div className="flex min-w-0 items-center gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-gray-100 font-mono text-xs text-gray-600">
                  {file.name.split('.').pop() || 'file'}
                </div>
                <div className="min-w-0">
                  <p className="break-words text-sm text-gray-900 [overflow-wrap:anywhere]">{file.name}</p>
                  <p className="text-xs text-gray-500">{formatBytes(file.size)}</p>
                  {state.step === 'idle' && <button type="button" disabled={checkingConnection} className="mt-1 text-xs underline" onClick={(event) => { event.stopPropagation(); void handleFile(file); }}>Validate retained file</button>}
                </div>
              </div>
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  handleClear();
                }}
                className="text-xs font-medium text-red-600 hover:text-red-800 transition-colors"
              >
                Remove
              </button>
            </div>
          )}
        </div>
      )}

      {/* Error state */}
      {state.step === 'error' && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-5 text-sm text-red-700 flex flex-wrap items-start gap-3">
          <svg className="w-5 h-5 text-red-500 shrink-0 mt-0.5" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
          </svg>
          <div className="flex-1">
            <h4 className="font-medium text-red-800">{state.submissionUncertain ? 'Submission outcome unknown' : state.previews ? 'Review needs attention' : 'Could not read this file'}</h4>
            <p className="mt-1 text-xs">{formatError(state.message)}</p>
            {state.previews && state.previews.length > 0 && (
              <p className="mt-2 text-xs text-red-500">
                Your parsed templates are still loaded. Check History for any uncertain submission before trying again.
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {state.previews && state.previews.length > 0 && (
              <button
                onClick={() => setState({ step: 'previewed', previews: state.previews as TemplatePreview[], uploadId: state.uploadId, submissionUncertain: state.submissionUncertain })}
                className="text-xs font-medium text-gray-700 underline"
              >
                Back to preview
              </button>
            )}
            {!state.previews && file && <button type="button" onClick={() => void handleFile(file)} className="text-xs font-medium underline">Retry retained file</button>}
            {state.submissionUncertain && <a href="/" className="text-xs font-medium underline">Check History</a>}
            <button type="button" onClick={reconnect} className="text-xs font-medium underline">Reconnect here</button>
            <button onClick={handleReset} className="text-xs font-medium text-red-700 underline">
              Reset
            </button>
          </div>
        </div>
      )}

      {/* Loading state: Previewing */}
      {state.step === 'previewing' && (
        <div className="bg-white rounded-xl border border-gray-200/80 p-12 text-center text-gray-500">
          <div className="flex flex-col items-center gap-3">
            <svg className="animate-spin h-8 w-8 text-gray-700" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
            </svg>
            <p className="text-sm font-medium text-gray-800">Parsing and validating templates…</p>
            <p className="text-xs text-gray-500">Verifying columns and component format</p>
          </div>
        </div>
      )}

      {/* STEP 2: Preview Table */}
      {state.step === 'previewed' && (
        <div className="space-y-4">
          {/* Smart Routing Account Auto-Detection Banner */}
          {(() => {
            const detection = state.previews[0]?.account_detection;
            if (!detection || !detection.is_mismatch) return null;
            return (
              <div className="p-4 bg-gray-50/90 border border-gray-200 rounded-xl space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="flex items-start gap-3">
                    <div>
                      <h4 className="text-xs font-medium text-gray-900 flex items-center gap-2">
                        <span>Suggested account</span>
                        <span className="font-mono text-xs font-normal text-gray-600">
                          {(detection.confidence * 100).toFixed(0)}% match
                        </span>
                      </h4>
                      <p className="text-xs text-gray-900/90 mt-0.5 leading-relaxed">
                        This spreadsheet contains <strong>{detection.detected_account_name}</strong> templates ({detection.matched_reasons.join(', ')}), but your active context is <strong>{accountLabel}</strong>.
                      </p>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      type="button"
                      onClick={() => {
                        if (!setDestination(detection.detected_account_id, channel)) return;
                        handleClear();
                      }}
                      className="px-3 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-medium transition-colors flex items-center gap-1.5"
                    >
                      <span>Switch to {detection.detected_account_name} and preview again</span>
                    </button>
                  </div>
                </div>
              </div>
            );
          })()}

          {/* Live WABA Duplicate Conflict Alert Banner if templates already exist on WABA */}
          {(() => {
            const dupes = state.previews.filter(p => p.already_exists_on_waba || p.exists_on_waba || p.duplicate_warning);
            if (!dupes.length) return null;
            const netNewCount = state.previews.length - dupes.length;
            return (
              <div className="p-4 bg-rose-50 border border-rose-200 rounded-xl space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="flex items-start gap-3">
                    <div>
                      <h4 className="text-xs font-medium text-rose-950">
                        {dupes.length} of {state.previews.length} template{dupes.length === 1 ? '' : 's'} already exist on {accountLabel}&apos;s WABA
                      </h4>
                      <p className="text-xs text-rose-800/90 mt-0.5 leading-relaxed">
                        Meta will reject new submissions with <span>&quot;There is already English content for this template&quot;</span>.
                      </p>
                    </div>
                  </div>

                  {/* Auto-Skip Toggle */}
                  <label className="flex items-center gap-2 bg-white px-3 py-1.5 rounded-lg border border-rose-300 text-xs font-medium text-rose-900 cursor-pointer shrink-0 hover:bg-rose-50/50 transition-colors">
                    <input
                      type="checkbox"
                      checked={autoSkipDuplicates}
                      onChange={(e) => setAutoSkipDuplicates(e.target.checked)}
                      className="rounded border-gray-300 text-rose-600 focus:ring-rose-500"
                    />
                    <span>Skip existing templates (recommended)</span>
                  </label>
                </div>

                {autoSkipDuplicates ? (
                  <div className="text-xs text-rose-900 bg-rose-100/70 p-3 rounded-lg border border-rose-200/80 flex items-center gap-2">
                    <span>
                      <strong>Existing templates skipped:</strong> Only the <strong>{netNewCount} net-new template{netNewCount === 1 ? '' : 's'}</strong> will be submitted to Meta. The {dupes.length} existing template{dupes.length === 1 ? '' : 's'} will be safely skipped to prevent Meta rejections.
                    </span>
                  </div>
                ) : (
                  <div className="text-xs text-rose-900 bg-white/80 p-3 rounded-lg border border-rose-200 flex items-center gap-2">
                    <span>
                      <strong>All templates selected:</strong> All {state.previews.length} templates will be sent to Meta. Templates that already exist will likely receive a duplicate rejection.
                    </span>
                  </div>
                )}
              </div>
            );
          })()}
          {/* Meta Technical Compliance Alert Banner if word-ratio or length violations are detected */}
          {(() => {
            const compWarned = state.previews.filter(p => p.compliance_warnings && p.compliance_warnings.length > 0);
            if (!compWarned.length) return null;
            return (
              <div className="p-4 bg-amber-50/90 border border-amber-200 rounded-xl space-y-2">
                <div className="flex items-start gap-3">
                  <div>
                    <h4 className="text-xs font-medium text-amber-950">
                      Technical compliance review ({compWarned.length} of {state.previews.length} template{compWarned.length === 1 ? '' : 's'})
                    </h4>
                    <p className="text-xs text-amber-800/90 mt-0.5 leading-relaxed">
                      Meta enforces strict technical parameters (e.g. minimum fixed words per variable placeholder, 60-char header limits, 25-char button limits). Review the flagged rows below to prevent rejection.
                    </p>
                  </div>
                </div>
              </div>
            );
          })()}

          {channel === 'whatsapp' && (
            <p className="text-xs text-gray-600">
              WhatsApp whitelisting has no image dimension or aspect ratio requirements. A placeholder sample is used for an IMAGE header when no creative is provided.
            </p>
          )}

          {/* RCS Aspect Ratio Block Banner */}
          {(() => {
            if (channel !== 'rcs') return null;
            const blocked = state.previews.filter(
              p => p.aspect_ratio_blocked || (p.aspect_ratio_warnings && p.aspect_ratio_warnings.some(w => w.blocked))
            );
            if (!blocked.length) return null;
            return (
              <div className="p-4 bg-red-50 border border-red-200 rounded-xl space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="flex items-start gap-3">
                    <div>
                      <h4 className="text-xs font-medium text-red-950">
                        {blocked.length} of {state.previews.length} template{blocked.length === 1 ? '' : 's'} blocked by image aspect ratio
                      </h4>
                      <p className="text-xs text-red-800/90 mt-0.5 leading-relaxed">
                        Auto-resizing has been removed to preserve creative design. Templates with non-compliant image dimensions are strictly blocked from creation.
                        <> Required for RCS: <strong>16:9 (1280x720)</strong>, <strong>1:1 (770x720)</strong>, or <strong>3:4 (Portrait)</strong> for carousel cards; <strong>2:1 (1200x600)</strong> for rich cards.</>
                      </p>
                    </div>
                  </div>

                  <span className="px-2.5 py-1 rounded-lg bg-red-100 text-red-800 border border-red-200 text-xs font-medium shrink-0">
                    {blocked.length} blocked
                  </span>
                </div>
              </div>
            );
          })()}

          {/* Grammar & Content Quality Alert Banner if typos/rejection rules are detected */}
          {(() => {
            const grammarWarned = state.previews.filter(p => p.grammar_warnings && p.grammar_warnings.length > 0);
            if (!grammarWarned.length) return null;
            return (
              <div className="p-4 bg-gray-50/80 border border-gray-200 rounded-xl space-y-3">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="flex items-start gap-3">
                    <div>
                      <h4 className="text-xs font-medium text-gray-900">
                        Grammar and formatting suggestions ({grammarWarned.length} of {state.previews.length} template{grammarWarned.length === 1 ? '' : 's'} flagged)
                      </h4>
                      <p className="text-xs text-gray-900/90 mt-0.5 leading-relaxed">
                        Spelling typos, repeated words, punctuation spacing, or Meta variable formatting rules detected in template text.
                      </p>
                    </div>
                  </div>

                  {/* Auto-fix Toggle */}
                  <label className="flex items-center gap-2 bg-white px-3 py-1.5 rounded-lg border border-gray-200 text-xs font-medium text-gray-900 cursor-pointer shrink-0 hover:bg-gray-50/50 transition-colors">
                    <input
                      type="checkbox"
                      checked={autoFixGrammar}
                      onChange={(e) => setAutoFixGrammar(e.target.checked)}
                      className="rounded border-gray-300 text-gray-700 focus:ring-blue-500"
                    />
                    <span>Fix grammar and typos (recommended)</span>
                  </label>
                </div>

                {autoFixGrammar ? (
                  <div className="text-xs text-gray-900 bg-gray-100/70 p-3 rounded-lg border border-gray-200/80 flex items-center gap-2">
                    <span>
                      <strong>Corrections enabled:</strong> Typos (e.g. &ldquo;recieved&rdquo; &rarr; &ldquo;received&rdquo;), repeated words and spacing will be corrected before submission.
                    </span>
                  </div>
                ) : (
                  <div className="text-xs text-gray-900 bg-white/80 p-3 rounded-lg border border-gray-200 flex items-center gap-2">
                    <span>
                      <strong>Original text:</strong> Text will be submitted exactly as written in your spreadsheet without typo corrections.
                    </span>
                  </div>
                )}
              </div>
            );
          })()}

          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
            <div className="flex flex-col gap-4 border-b border-gray-200 bg-gray-50 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <h3 className="text-sm font-medium text-gray-900">
                    {state.previews.length} template{state.previews.length === 1 ? '' : 's'} found
                  </h3>
                </div>
                <p className="text-xs text-gray-700/80 mt-0.5">
                  Reviewed destination: <strong>{reviewedLabel}</strong>
                  {review?.channel === 'rcs' && <> (Bot ID: <code>{review.botId || 'Not configured'}</code>)</>}. Review before final submission.
                </p>
                {state.submissionUncertain && <p role="alert" className="mt-2 text-xs text-amber-900">Submission outcome unknown. This upload cannot be submitted again here. <a href="/" className="underline">Check History</a>; reconnecting does not replay it.</p>}
                {state.previews.some((preview) => preview.inventory_status !== 'verified') && <div role={inventoryCheck?.checking ? 'status' : 'alert'} className="mt-2 space-y-1 text-xs text-amber-900">
                  <p>{inventoryCheck?.checking ? 'Checking live inventory in the background. Your messages and sources are available now; submission waits for verification.' : 'Inventory is not verified. Existing templates are unknown, not missing; submission is blocked. Your file and review are retained.'}</p>
                  <p>{inventoryCheck?.error || state.previews.find((preview) => preview.inventory_error)?.inventory_error}</p>
                  <button type="button" onClick={reconnect} className="underline">Reconnect this destination</button>
                  <button type="button" disabled={!file || inventoryCheck?.checking} className="ml-3 underline disabled:opacity-50" onClick={() => { if (file && state.uploadId) void verifyInventory(file, state.uploadId, state.previews); }}>Retry inventory check</button>
                </div>}
                {channel === 'rcs' && !activeRcs.botId && (
                  <p role="alert" className="mt-1 text-xs font-medium text-amber-800">
                    RCS submission is unavailable: this account has no verified Karix bot. Refresh account settings.
                  </p>
                )}
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <button
                  onClick={handleClear}
                  className="px-4 py-2 rounded-lg text-xs font-medium text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 transition-colors"
                >
                  Clear
                </button>
                <button
                  onClick={handleInitiateSubmit}
                  disabled={checkingConnection || inventoryCheck?.checking || state.submissionUncertain || !state.previews.length || !review || review.account !== account || review.channel !== channel || account === 'all' || state.previews.some((preview) => preview.inventory_status !== 'verified' || preview.submission_ready === false) || (channel === 'rcs' && (!review.botId || review.botId !== activeRcs.botId))}
                  className="px-4 py-2 rounded-lg text-xs font-medium text-white bg-blue-600 hover:bg-blue-700 disabled:bg-gray-400 disabled:cursor-not-allowed transition-colors flex items-center gap-2"
                >
                  {(() => {
                    const blocked = channel === 'rcs' ? state.previews.filter(p => p.aspect_ratio_blocked || (p.aspect_ratio_warnings && p.aspect_ratio_warnings.some(w => w.blocked))) : [];
                    const dupes = state.previews.filter(p => p.already_exists_on_waba || p.exists_on_waba || p.duplicate_warning);
                    const compliant = Math.max(0, state.previews.length - blocked.length);
                    if (blocked.length > 0) {
                      return (
                        <span>
                          Submit {compliant} {compliant === 1 ? 'template' : 'templates'} to {reviewedLabel} ({blocked.length} blocked)
                        </span>
                      );
                    }
                    const netNew = state.previews.length - dupes.length;
                    if (dupes.length > 0 && autoSkipDuplicates) {
                      return (
                        <span>
                          Submit {netNew} {netNew === 1 ? 'template' : 'templates'} to {reviewedLabel}
                          {dupes.length > 0 && ` (${dupes.length} Skipped)`}
                        </span>
                      );
                    }
                    return <span>Submit {state.previews.length} {state.previews.length === 1 ? 'template' : 'templates'} to {reviewedLabel}</span>;
                  })()}
                  <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M10.293 3.293a1 1 0 011.414 0l6 6a1 1 0 010 1.414l-6 6a1 1 0 01-1.414-1.414L14.586 11H3a1 1 0 110-2h11.586l-4.293-4.293a1 1 0 010-1.414z" clipRule="evenodd" />
                  </svg>
                </button>
              </div>
            </div>
          <p className="px-5 py-3 text-xs text-blue-900 bg-blue-50/30 border-b border-blue-100">{WHITELIST_NAME_HINT} Preview shows the names returned for submission.</p>
          {state.previews[0]?.import_notes?.length ? <details className="border-b border-gray-200 px-5 py-3 text-xs text-amber-900">
            <summary className="cursor-pointer font-medium">Workbook scope and excluded sections</summary>
            <ul className="mt-2 list-disc space-y-1 pl-4">{state.previews[0].import_notes.map((note, index) => <li key={index}>{note}</li>)}</ul>
          </details> : null}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead>
                <tr className="bg-gray-50/30 text-gray-900 font-medium border-b border-gray-200">
                  {channel === 'whatsapp' ? (
                    <>
                      <th className="font-medium px-5 py-3">#</th>
                      <th className="font-medium px-5 py-3">Template name</th>
                      <th className="font-medium px-5 py-3">Category</th>
                      <th className="font-medium px-5 py-3">Language</th>
                      <th className="font-medium px-5 py-3">Components</th>
                    </>
                  ) : (
                    <>
                      <th className="font-medium px-5 py-3">#</th>
                      <th className="font-medium px-5 py-3">Template name</th>
                      <th className="font-medium px-5 py-3">Type</th>
                      <th className="font-medium px-5 py-3">Content / title</th>
                      <th className="font-medium px-5 py-3">Buttons / cards</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200">
                {state.previews.map((p, idx) => (
                  <tr key={idx} className="hover:bg-gray-50/50">
                    <td className="px-5 py-3 text-gray-500 font-mono">{idx + 1}</td>
                    <td className="px-5 py-3 font-medium text-gray-900 font-mono">
                      <div className="flex items-center gap-2">
                        <span>{p.template_name}</span>
                        {(p.already_exists_on_waba || p.exists_on_waba) && (
                          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium bg-rose-100 text-rose-800 border border-rose-200 shrink-0" title="Already exists on this WABA">
                            Already on WABA
                          </span>
                        )}
                      </div>
                    </td>
                    {channel === 'whatsapp' ? (
                      <>
                        <td className="px-5 py-3 text-gray-700">{p.category || 'MARKETING'}</td>
                        <td className="px-5 py-3 text-gray-700">{p.language || 'en'}</td>
                        <td className="px-5 py-3 text-gray-600">
                          {p.components?.length ? (
                            <div className="space-y-1">
                              <div className="flex flex-wrap gap-1">
                                {p.components.map((c, cIdx) => {
                                  const isHeader = c.type === 'HEADER';
                                  const format = c.format ? ` (${c.format})` : '';
                                  const color = isHeader
                                    ? 'bg-gray-100 text-gray-900 border border-gray-200'
                                    : c.type === 'BODY'
                                    ? 'bg-gray-100 text-gray-900 border border-gray-200'
                                    : c.type === 'BUTTONS'
                                    ? 'bg-emerald-100 text-emerald-800 border-emerald-200'
                                    : 'bg-gray-100 text-gray-700 border-gray-200';
                                  return (
                                    <span
                                      key={cIdx}
                                      className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium border ${color}`}
                                    >
                                      {c.type}{format}
                                    </span>
                                  );
                                })}
                              </div>
                              <details open className="max-w-lg">
                                <summary className="cursor-pointer font-medium text-blue-700">Review message and buttons</summary>
                                <PreviewSource preview={p} />
                                {p.components.filter((component) => component.text).map((component, index) => <pre key={index} className="mt-2 whitespace-pre-wrap break-words font-sans">{component.text}</pre>)}
                                {p.components.filter((component) => component.type === 'BUTTONS').map((component, index) => <pre key={index} className="mt-2 whitespace-pre-wrap break-all">{JSON.stringify(component.buttons, null, 2)}</pre>)}
                              </details>

                              {p.grammar_warnings && p.grammar_warnings.length > 0 && (
                                <div className="flex flex-wrap gap-1 mt-1">
                                  {p.grammar_warnings.slice(0, 3).map((gw, gIdx) => (
                                    <span
                                      key={gIdx}
                                      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium bg-gray-50 text-gray-900 border border-gray-200"
                                      title={gw.issue}
                                    >
                                      <span>{gw.suggestion}</span>
                                      <span className={`px-1 py-0.5 rounded font-medium ${autoFixGrammar ? 'bg-emerald-100 text-emerald-800' : 'bg-gray-100 text-gray-700'}`}>
                                        {autoFixGrammar ? 'Fix enabled' : 'Raw'}
                                      </span>
                                    </span>
                                  ))}
                                  {p.grammar_warnings.length > 3 && (
                                    <span className="text-xs font-medium text-gray-700 px-1">
                                      +{p.grammar_warnings.length - 3} more
                                    </span>
                                  )}
                                </div>
                              )}

                              {p.compliance_warnings && p.compliance_warnings.length > 0 && (
                                <div className="flex flex-wrap gap-1 mt-1">
                                  {p.compliance_warnings.map((cw, cIdx) => (
                                    <span
                                      key={cIdx}
                                      className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium border ${
                                        cw.severity === 'error'
                                          ? 'bg-rose-100 text-rose-800 border-rose-200'
                                          : 'bg-amber-100 text-amber-800 border-amber-200'
                                      }`}
                                      title={cw.recommendation}
                                    >
                                      <span>{cw.issue}</span>
                                    </span>
                                  ))}
                                </div>
                              )}
                            </div>
                          ) : (
                            'Standard'
                          )}
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="px-5 py-3 font-medium text-gray-800 text-xs">
                          {p.template_type || (p.carousel_cards?.length ? 'carousel' : (p.media_url ? 'richcard' : 'text'))}
                        </td>
                        <td className="max-w-lg space-y-2 px-5 py-3 text-gray-700">
                          <PreviewSource preview={p} />
                          {p.card_title && <p className="font-medium">{p.card_title}</p>}
                          {[p.text_message, p.template_message, p.card_description].filter((text, index, values) => text && values.indexOf(text) === index).map((text, index) => <pre key={index} className="whitespace-pre-wrap break-words font-sans">{text}</pre>)}
                          {p.carousel_cards?.map((card, index) => <div key={index} className="space-y-1 border-t border-gray-100 pt-2">
                            <p className="text-xs font-medium">Card {index + 1}</p>
                            {['cardTitle', 'card_title', 'title', 'cardDescription', 'card_description', 'description', 'text', 'text_message'].map((field) => typeof card[field] === 'string' && card[field] ? <pre key={field} className="whitespace-pre-wrap break-words font-sans">{String(card[field])}</pre> : null)}
                          </div>)}
                        </td>
                        <td className="px-5 py-3 text-gray-600 text-xs">
                          {p.carousel_cards?.length
                            ? `${p.carousel_cards.length} card(s)`
                            : p.suggestions?.length
                            ? `${p.suggestions.length} button(s)`
                            : 'No buttons'}
                        </td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        </div>
      )}
      {/* Loading state: Submitting */}
      {state.step === 'submitting' && (
        <div className="bg-white rounded-xl border border-gray-200/80 p-10 text-center text-gray-500 space-y-4">
          <div className="flex flex-col items-center gap-3">
            <svg className="animate-spin h-8 w-8 text-gray-700" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
            </svg>
            <p className="text-sm font-medium text-gray-800">Submitting templates to Karix API…</p>
            <p className="text-xs text-gray-500">Processing concurrent batch submission for {accountLabel}</p>
          </div>
        </div>
      )}

      {/* STEP 3: Results */}
      {state.step === 'submitted' && (
        <div className="space-y-6">
          {/* PAUSED_FOR_AUTH Banner if session expired */}
          {jobError && <div role="alert" className="space-y-2 rounded-xl border border-amber-200 bg-amber-50 p-4 text-xs text-amber-900"><p>{jobError}</p><button type="button" disabled={refreshingJob} onClick={() => setJobRefresh((value) => value + 1)} className="underline">Retry status</button><button type="button" onClick={reconnect} className="ml-3 underline">Reconnect here</button><a href="/" className="ml-3 underline">History</a></div>}
          {state.authPaused && (
            <div className="p-4 bg-amber-50 border border-amber-300 rounded-xl space-y-3">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="flex items-start gap-3">
                  <div>
                    <h4 className="text-xs font-medium text-amber-950">
                      Karix session expired (401) · Queue paused
                    </h4>
                    <p className="text-xs text-amber-900/90 mt-0.5 leading-relaxed">
                      {state.authPausedMessage ||
                        `Portal session token has expired for ${accountLabel}. Your remaining templates are safely paused in the queue. Reconnect here, then explicitly resume the queue.`}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={reconnect}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium text-amber-900 bg-amber-100 hover:bg-amber-200 border border-amber-300 transition-colors"
                  >
                    Reconnect here
                  </button>
                  <button
                    type="button"
                    onClick={async () => {
                      if (state.jobId) {
                        const version = selectionVersionRef.current;
                        if (!await ensureConnected()) return;
                        if (!mountedRef.current || version !== selectionVersionRef.current || scopeRef.current.uploadScope !== uploadScope) return;
                        await resumeJob(state.jobId);
                        if (!mountedRef.current || version !== selectionVersionRef.current || scopeRef.current.uploadScope !== uploadScope) return;
                        setState((prev) => (prev.step === 'submitted' && prev.jobId === state.jobId ? { ...prev, authPaused: false } : prev));
                      }
                    }}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium text-white bg-amber-600 hover:bg-amber-700 transition-colors"
                  >
                    Resume queue
                  </button>
                </div>
              </div>
            </div>
          )}

          <div className="bg-white rounded-xl border border-gray-200/80 p-6">
            <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
              <div className="flex items-center gap-3">
                <div
                  className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-md font-medium ${
                    state.isStreaming
                      ? 'bg-gray-100 text-gray-700'
                      : state.results.some((result) => templateOutcome(result).unknown) ? 'bg-amber-100 text-amber-800'
                      : state.results.some((result) => templateOutcome(result).tone === 'error')
                        ? 'bg-red-100 text-red-600' : 'bg-gray-100 text-gray-700'
                  }`}
                >
                  {state.isStreaming ? (
                    <svg aria-hidden="true" className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" /></svg>
                  ) : state.results.some((result) => ['error', 'warning'].includes(templateOutcome(result).tone)) ? (
                    <svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.75"><path strokeLinecap="round" d="M10 6v5m0 3.5h.01" /></svg>
                  ) : (
                    <svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.75"><path strokeLinecap="round" strokeLinejoin="round" d="M5 10.5l3 3 7-7" /></svg>
                  )}
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-base font-medium text-gray-900">
                      {state.isStreaming ? 'Processing registrations…'
                        : state.results.some((result) => templateOutcome(result).unknown) ? 'Registration outcome unknown — check History'
                        : state.results.some((result) => templateOutcome(result).tone === 'error') ? 'Registration finished — review results'
                        : state.results.some((result) => templateOutcome(result).label === 'Awaiting approval') ? 'Registration submitted · Awaiting approval'
                        : 'Registration results'}
                    </h3>
                    {state.isStreaming && (
                      <span className="inline-flex items-center gap-2 text-xs font-normal text-gray-600">
                        <span aria-hidden="true" className="h-1.5 w-1.5 rounded-full bg-gray-500" />
                        Reading stored queue updates
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Processed {state.results.filter(r => r.status !== 'pending' && r.status !== 'processing').length} of {state.results.length} templates for {destinationLabel(state.account, state.channel, getAccountLabel(state.account))}.
                    {state.jobId && <span className="font-mono text-xs ml-2 text-gray-500">({state.jobId})</span>}
                    {state.jobId && <> Approval updates refresh automatically while this page is visible. Registration never repeats.</>}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                {state.jobId && <button type="button" disabled={refreshingJob} onClick={() => setJobRefresh((value) => value + 1)} className="text-xs underline disabled:opacity-50">{refreshingJob ? 'Reading status…' : 'Refresh status'}</button>}
                {(() => {
                  const failed = state.results.filter((r) => r.status === 'failed' && !templateOutcome(r).unknown);
                  if (!failed.length) return null;
                  return (
                    <button
                      type="button"
                      onClick={() => {
                        const headers = ['template_name', 'status', 'approval_status', 'error'];
                        const rows = failed.map((r) =>
                          [
                            `"${(r.template_name || '').replace(/"/g, '""')}"`,
                            `"${(r.status || '').replace(/"/g, '""')}"`,
                            `"${(r.approval_status || '').replace(/"/g, '""')}"`,
                            `"${(r.error || '').replace(/"/g, '""')}"`,
                          ].join(',')
                        );
                        const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows].join('\n');
                        const link = document.createElement('a');
                        link.href = encodeURI(csvContent);
                        link.download = `failed_templates_${state.jobId || 'batch'}.csv`;
                        document.body.appendChild(link);
                        link.click();
                        document.body.removeChild(link);
                      }}
                      className="px-3 py-2 rounded-lg text-xs font-medium text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 transition-colors"
                    >
                      Download failed rows ({failed.length} CSV)
                    </button>
                  );
                })()}
                <button
                  type="button"
                  onClick={handleReset}
                  className="px-4 py-2 rounded-lg text-xs font-medium text-gray-700 bg-gray-50 hover:bg-gray-100 transition-colors"
                >
                  Submit another file
                </button>
              </div>
            </div>
          </div>

          {/* Results Table */}
          <div className="bg-white rounded-xl border border-gray-200/80 overflow-hidden">
            <div className="p-4 bg-gray-50/80 border-b border-gray-200 font-medium text-xs text-gray-700">
              Batch submission results
            </div>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead>
                  <tr className="bg-gray-50/50 text-gray-500 font-medium border-b border-gray-200 text-xs">
                    <th className="font-medium px-5 py-3">#</th>
                    <th className="font-medium px-5 py-3">Template name</th>
                    {channel === 'whatsapp' ? (
                      <>
                        <th className="font-medium px-5 py-3">Submission status</th>
                        <th className="font-medium px-5 py-3">Approval</th>
                        <th className="font-medium px-5 py-3">Notes</th>
                        <th className="font-medium px-5 py-3">Submitted by</th>
                      </>
                    ) : (
                      <>
                        <th className="font-medium px-5 py-3">Karix template ID</th>
                        <th className="font-medium px-5 py-3">Status</th>
                        <th className="font-medium px-5 py-3">Details / response</th>
                      </>
                    )}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200">
                  {state.results.map((r, idx) => (
                    <tr
                      key={idx}
                      className={templateOutcome(r).unknown ? 'bg-amber-50/40' : templateOutcome(r).tone === 'error' ? 'bg-red-50/40' : 'hover:bg-gray-50/50'}
                    >
                      <td className="px-5 py-3 text-gray-500 font-mono">{idx + 1}</td>
                      <td className="px-5 py-3 font-medium text-gray-900 font-mono">{r.template_name}</td>
                      {channel === 'whatsapp' ? (
                        <>
                          <td className="px-5 py-3">
                            <StatusBadge item={{ ...r, approval_status: undefined }} />
                          </td>
                          <td className="px-5 py-3">
                            <StatusBadge item={r} />
                          </td>
                          <td className="px-5 py-3 text-gray-500">
                            {r.status === 'duplicate' ? (
                              <span className="text-gray-700 font-medium">{r.error || 'Already active on WABA — skipped duplicate submission.'}</span>
                            ) : r.error ? (
                              <span className="text-red-600 font-medium">{formatError(r.error)}</span>
                            ) : (
                              templateOutcome(r).label
                            )}
                          </td>
                          <td className="px-5 py-3">
                            <span className="inline-flex items-center gap-1.5">
                              <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-gray-100 text-xs text-gray-600">
                                {(r.submitted_by || user || 'U').charAt(0).toUpperCase()}
                              </span>
                              <span className="text-xs font-medium text-gray-700">
                                {r.submitted_by || user || '—'}
                              </span>
                            </span>
                          </td>
                        </>
                      ) : (
                        <>
                          <td className="px-5 py-3 font-mono font-medium text-gray-700 text-xs">
                            {r.template_id || r.provider_ref_id || '—'}
                          </td>
                          <td className="px-5 py-3">
                            <StatusBadge item={r} />
                          </td>
                          <td className="px-5 py-3 text-gray-600">
                            {r.error ? (
                              <span className="text-red-600 font-medium">{formatError(r.error)}</span>
                            ) : (
                              <span className="font-medium">{templateOutcome(r).label}</span>
                            )}
                          </td>
                        </>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}
        </div>
      )}

      {/* PHASE 1: MASTER CATALOG IDENTIFICATION & WABA RECONCILIATION */}
      {activeTab === 'IDENTIFY' && (
        <div className="space-y-6">
          {/* Phase 1 Upload & Controller Card */}
          <div className="bg-white rounded-xl border border-gray-200 p-6 space-y-4">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-100 pb-4">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-lg font-medium text-gray-900">
                    Compare your master catalog
                  </h2>
                </div>
                <p className="text-xs text-gray-500 mt-1">
                  Upload your master template catalog (CSV, XLSX, XLS, or JSON). Reconciles against live {accountLabel} Karix WABA templates to classify what is Whitelisted, what is Missing, and where copy has drifted.
                </p>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <input
                  ref={identifyInputRef}
                  type="file"
                  accept=".csv,.xlsx,.xls,.json"
                  onChange={(e) => {
                    const sel = e.target.files?.[0];
                    if (sel) handleIdentifyFileSelect(sel);
                  }}
                  className="hidden"
                />
                <button
                  type="button"
                  onClick={() => identifyInputRef.current?.click()}
                  disabled={identifying}
                  className="px-4 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white font-medium text-xs rounded-xl transition-colors flex items-center gap-2"
                >
                  {identifying ? (
                    <>
                      <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                        <circle cx="12" cy="12" r="10" strokeDasharray="32" strokeDashoffset="10" />
                      </svg>
                      <span>Comparing with Karix WABA…</span>
                    </>
                  ) : (
                    <>
                      <span>Upload and compare catalog</span>
                    </>
                  )}
                </button>
              </div>
            </div>

            {identifyFile && (
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-3 rounded-lg border border-gray-200 bg-gray-50 p-3 text-sm">
                <div className="flex min-w-0 flex-wrap items-center gap-2">
                  <span className="font-medium text-gray-700">Master catalog file:</span>
                  <span className="break-all font-mono text-gray-700 font-medium">{identifyFile.name}</span>
                  <span className="text-gray-500">({formatBytes(identifyFile.size)})</span>
                </div>
                <button
                  onClick={() => {
                    setIdentifyFile(null);
                    setIdentifyReport(null);
                    setIdentifyError(null);
                    if (identifyInputRef.current) identifyInputRef.current.value = '';
                  }}
                  aria-label="Clear master catalog file"
                  className="text-gray-500 hover:text-gray-700 p-1 rounded"
                >
                  <svg aria-hidden="true" className="h-4 w-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><path strokeLinecap="round" d="M5 5l10 10M15 5L5 15" /></svg>
                </button>
              </div>
            )}

            {identifyError && (
              <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700 flex items-center gap-2">
                <span>{identifyError}</span>
              </div>
            )}
          </div>

          {/* Identification Report Results */}
          {identifyReport && (() => {
            const filteredItems = identifyReport.items.filter((item) => {
              if (identifyFilter === 'MISSING' && item.status !== 'NOT_WHITELISTED') return false;
              if (identifyFilter === 'WHITELISTED' && item.status !== 'WHITELISTED') return false;
              if (identifyFilter === 'DRIFT' && item.status !== 'CONTENT_DRIFT') return false;
              if (identifyFilter === 'PENDING' && item.status !== 'PENDING') return false;
              if (identifyFilter === 'REJECTED' && item.status !== 'REJECTED') return false;
              if (identifySearch.trim()) {
                const q = identifySearch.toLowerCase();
                const mName = item.template_name.toLowerCase().includes(q);
                const mMaster = item.master_body.toLowerCase().includes(q);
                const mLive = item.live_body.toLowerCase().includes(q);
                const mDiff = item.diff_summary.toLowerCase().includes(q);
                if (!mName && !mMaster && !mLive && !mDiff) return false;
              }
              return true;
            });

            return (
              <div className="space-y-6">
                {/* 1. Summary Cards */}
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
                  <div className="rounded-xl border border-gray-200 bg-white p-4">
                    <span className="text-xs font-medium text-gray-500 block">Total templates</span>
                    <div className="text-2xl font-medium text-gray-900 mt-1 tabular-nums">{identifyReport.total_master}</div>
                    <span className="text-xs text-gray-500 font-medium">Catalog templates</span>
                  </div>

                  <div className="rounded-xl border border-gray-200 bg-white p-4">
                    <span className="text-xs font-medium text-emerald-700 block">Whitelisted</span>
                    <div className="text-2xl font-medium text-emerald-700 mt-1 tabular-nums">{identifyReport.whitelisted_count}</div>
                    <span className="text-xs text-emerald-600 font-medium">Approved on WABA</span>
                  </div>

                  <div className="rounded-xl border border-gray-200 bg-white p-4">
                    <span className="text-xs font-medium text-rose-700 block">Missing</span>
                    <div className="text-2xl font-medium text-rose-700 mt-1 tabular-nums">{identifyReport.missing_count}</div>
                    <span className="text-xs text-rose-600 font-medium">Needs submission</span>
                  </div>

                  <div className="rounded-xl border border-gray-200 bg-white p-4">
                    <span className="text-xs font-medium text-amber-700 block">Content drift</span>
                    <div className="text-2xl font-medium text-amber-800 mt-1 tabular-nums">{identifyReport.drift_count}</div>
                    <span className="text-xs text-amber-600 font-medium">Modified copy</span>
                  </div>

                  <div className="rounded-xl border border-gray-200 bg-white p-4">
                    <span className="text-xs font-medium text-gray-700 block">Pending</span>
                    <div className="text-2xl font-medium text-gray-900 mt-1 tabular-nums">{identifyReport.pending_count}</div>
                    <span className="text-xs text-gray-700 font-medium">In carrier review</span>
                  </div>

                  <div className="rounded-xl border border-gray-200 bg-white p-4">
                    <span className="text-xs font-medium text-gray-500 block">Rejected</span>
                    <div className="text-2xl font-medium text-red-600 mt-1 tabular-nums">{identifyReport.rejected_count}</div>
                    <span className="text-xs text-red-500 font-medium">Failed Meta review</span>
                  </div>
                </div>

                {/* 2. Automated Action Bar */}
                <div className="workspace-panel p-4 flex flex-col md:flex-row md:items-center justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-medium text-gray-900">
                      Prepare missing templates
                    </h3>
                    <p className="text-sm text-gray-600 mt-1">
                      {identifyReport.missing_count + identifyReport.rejected_count} templates require submission to Karix Meta WABA.
                    </p>
                  </div>
                  <div className="workspace-toolbar">
                    <button
                      onClick={handleExportMissingCsv}
                      disabled={identifyReport.missing_templates.length === 0}
                      className="workspace-button"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                      </svg>
                      <span>Export missing (CSV)</span>
                    </button>
                    <button
                      onClick={handleHandoffMissingToSubmit}
                      disabled={identifyReport.missing_templates.length === 0}
                      className="workspace-button-primary"
                    >
                      <span>Review {identifyReport.missing_count + identifyReport.rejected_count} missing templates &rarr;</span>
                    </button>
                  </div>
                </div>

                {/* 3. Filterable Discrepancy Table */}
                <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden space-y-3">
                  <div className="p-4 border-b border-gray-100 flex flex-col md:flex-row md:items-center justify-between gap-3">
                    {/* Filter Pills */}
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-xs font-medium text-gray-500 mr-1">Filter:</span>
                      {[
                        { id: 'ALL', label: `All (${identifyReport.items.length})` },
                        { id: 'MISSING', label: `Missing (${identifyReport.missing_count})`, alert: true },
                        { id: 'WHITELISTED', label: `Whitelisted (${identifyReport.whitelisted_count})` },
                        { id: 'DRIFT', label: `Drift (${identifyReport.drift_count})` },
                        { id: 'PENDING', label: `Pending (${identifyReport.pending_count})` },
                        { id: 'REJECTED', label: `Rejected (${identifyReport.rejected_count})` },
                      ].map((f) => (
                        <button
                          key={f.id}
                          onClick={() => setIdentifyFilter(f.id as 'ALL' | 'MISSING' | 'WHITELISTED' | 'DRIFT' | 'PENDING' | 'REJECTED')}
                          className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                            identifyFilter === f.id
                              ? f.alert
                                ? 'bg-rose-600 text-white'
                                : 'bg-gray-900 text-white'
                              : f.alert
                              ? 'bg-rose-50 text-rose-700 hover:bg-rose-100'
                              : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                          }`}
                        >
                          {f.label}
                        </button>
                      ))}
                    </div>

                    {/* Search */}
                    <div className="w-full md:w-64">
                      <input
                        aria-label="Search catalog comparison"
                        type="search"
                        value={identifySearch}
                        onChange={(e) => setIdentifySearch(e.target.value)}
                        placeholder="Search template or copy"
                        className="workspace-search"
                      />
                    </div>
                  </div>
                  {(identifySearch || identifyFilter !== 'ALL') && <div className="workspace-toolbar px-4" aria-label="Active catalog filters">
                    {identifySearch && <button type="button" className="workspace-filter-chip" onClick={() => setIdentifySearch('')}>Search: {identifySearch} ×</button>}
                    {identifyFilter !== 'ALL' && <button type="button" className="workspace-filter-chip" onClick={() => setIdentifyFilter('ALL')}>Status: {identifyFilter} ×</button>}
                    <button type="button" className="workspace-button" onClick={() => { setIdentifySearch(''); setIdentifyFilter('ALL'); }}>Reset filters</button>
                  </div>}

                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[1040px] text-left text-sm">
                      <thead className="bg-gray-50 text-gray-500 font-medium text-xs border-b border-gray-200">
                        <tr>
                          <th className="font-medium py-2.5 px-4">Template name</th>
                          <th className="font-medium py-2.5 px-3">Category</th>
                          <th className="font-medium py-2.5 px-3">Whitelisting status</th>
                          <th className="font-medium py-2.5 px-3">Equivalence</th>
                          <th className="font-medium py-2.5 px-4">Master body vs live WABA body</th>
                          <th className="font-medium py-2.5 px-4">Diagnosis / action</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {filteredItems.length === 0 ? (
                          <tr>
                            <td colSpan={6} className="py-8 text-center text-gray-500">
                              <p>No templates match these filters.</p>
                              {(identifySearch || identifyFilter !== 'ALL') && <button type="button" className="workspace-button mt-3" onClick={() => { setIdentifySearch(''); setIdentifyFilter('ALL'); }}>Show all comparison results</button>}
                            </td>
                          </tr>
                        ) : (
                          filteredItems.map((item) => {
                            const isMissing = item.status === 'NOT_WHITELISTED';
                            const isWhitelisted = item.status === 'WHITELISTED';
                            const isDrift = item.status === 'CONTENT_DRIFT';
                            const isPending = item.status === 'PENDING';
                            const isRejected = item.status === 'REJECTED';

                            return (
                              <tr key={item.template_name} className="hover:bg-gray-50/60 transition-colors">
                                <td className="py-2.5 px-4 font-medium text-gray-900">
                                  <div className="font-mono text-gray-900">{item.template_name}</div>
                                  <div className="text-xs text-gray-500 font-normal">{item.language}</div>
                                </td>
                                <td className="py-2.5 px-3">
                                  <span className="px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-700">
                                    {item.category}
                                  </span>
                                </td>
                                <td className="py-2.5 px-3">
                                  <span
                                    className={`inline-flex px-2 py-0.5 rounded-md text-xs font-medium ${
                                      isWhitelisted
                                        ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                                        : isMissing
                                        ? 'bg-rose-100 text-rose-800 border border-rose-200'
                                        : isDrift
                                        ? 'bg-amber-100 text-amber-800 border border-amber-200'
                                        : isPending
                                        ? 'bg-gray-100 text-gray-900 border border-gray-200'
                                        : isRejected
                                        ? 'bg-red-100 text-red-800 border border-red-200'
                                        : 'bg-gray-100 text-gray-700'
                                    }`}
                                  >
                                    {isMissing ? 'NOT WHITELISTED' : item.status}
                                  </span>
                                </td>
                                <td className="py-2.5 px-3">
                                  {item.match_confidence > 0 ? (
                                    <div className="space-y-0.5">
                                      <span className="font-medium text-gray-900">
                                        {Math.round(item.match_confidence * 100)}%
                                      </span>
                                      <span className="block text-xs text-gray-500">
                                        {item.match_method}
                                      </span>
                                    </div>
                                  ) : (
                                    <span className="text-gray-500">—</span>
                                  )}
                                </td>
                                <td className="py-2.5 px-4 max-w-md">
                                  <div className="space-y-1">
                                    <div>
                                      <span className="text-xs font-medium text-gray-500 block">Master brief:</span>
                                      <p className="text-xs text-gray-800 line-clamp-2">{item.master_body || '—'}</p>
                                    </div>
                                    {item.live_body && (
                                      <div>
                                        <span className="text-xs font-medium text-emerald-600 block">Live WABA:</span>
                                        <p className="text-xs text-gray-600 line-clamp-2">{item.live_body}</p>
                                      </div>
                                    )}
                                  </div>
                                </td>
                                <td className="py-2.5 px-4 text-xs text-gray-600">
                                  <div>{item.diff_summary}</div>
                                  <span className={`inline-block mt-1 px-1.5 py-0.5 rounded text-xs font-medium ${
                                    item.action_required === 'SUBMIT'
                                      ? 'bg-rose-50 text-rose-700'
                                      : item.action_required === 'REMEDIATE'
                                      ? 'bg-amber-50 text-amber-700'
                                      : item.action_required === 'WAIT'
                                      ? 'bg-gray-50 text-gray-700'
                                      : 'bg-gray-50 text-gray-500'
                                  }`}>
                                    Action: {item.action_required}
                                  </span>
                                </td>
                              </tr>
                            );
                          })
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            );
          })()}
        </div>
      )}

        </>
      )}
      {/* Aspect Ratio Adjustment Confirmation Modal */}
      {/* Aspect Ratio Block Confirmation Modal */}
      {channel === 'rcs' && showBlockedModal && currentPreviews && (
        <div role="dialog" aria-modal="true" className="fixed inset-0 bg-black/40 flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-xl max-h-[calc(100dvh-2rem)] max-w-lg w-full overflow-y-auto p-6 shadow-xl border border-gray-200 space-y-5">
            <div className="flex items-start justify-between pb-3 border-b border-gray-100">
              <div className="flex items-start gap-3">
                <div>
                  <h3 className="text-base font-medium text-gray-900">
                    Aspect ratio blocked:  {currentPreviews.filter(p => p.aspect_ratio_blocked || (p.aspect_ratio_warnings && p.aspect_ratio_warnings.some(w => w.blocked))).length} templates will not be created
                  </h3>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Auto-resizing has been removed to preserve creative design. Templates with non-compliant image dimensions are strictly blocked from creation.
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowBlockedModal(false)}
                className="text-gray-500 hover:text-gray-600 font-medium p-1"
              >
                &times;
              </button>
            </div>

            <div className="p-4 rounded-xl bg-red-50 border border-red-200 text-xs text-red-900 space-y-2">
              <p className="font-medium">
                Only compliant templates ({currentPreviews.filter(p => !p.aspect_ratio_blocked && (!p.aspect_ratio_warnings || !p.aspect_ratio_warnings.some(w => w.blocked))).length}) will be submitted to {reviewedLabel}.
              </p>
              <p className="text-xs text-red-700 leading-relaxed">
                Blocked templates will be clearly distinguished in the results table as <strong>Blocked (invalid aspect ratio)</strong> so you can correct their dimensions and re-upload.
              </p>
            </div>

            <div className="flex flex-wrap items-center justify-end gap-3 border-t border-gray-100 pt-2">
              <button
                type="button"
                onClick={() => setShowBlockedModal(false)}
                className="px-4 py-2 bg-gray-100 hover:bg-gray-200 text-gray-700 text-xs font-medium rounded-lg transition-colors"
              >
                Cancel and fix file
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowBlockedModal(false);
                  executeSubmit(autoFixGrammar);
                }}
                className="px-5 py-2 text-xs font-medium text-white bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors flex items-center gap-1.5"
              >
                <span>Submit compliant templates only</span>
                <span>&rarr;</span>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
