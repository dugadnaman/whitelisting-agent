'use client';

import { useState, useEffect, useCallback, useRef, Fragment } from 'react';
import Link from 'next/link';
import {
  fetchStats,
  fetchTemplates,
  pollPending,
  fetchActivityLogs,
  fetchActivityStats,
  deleteTemplates,
  deleteTemplatesFromFile,
  syncKarixRcsToMoEngage,
  syncRcsTemplateToMoEngage,
  fetchRcsSyncWorkspaces,
} from '@/lib/api';
import type { Stats, Template, ActivityLog, ActivityStats, RcsSyncWorkspace } from '@/lib/api';
import { useApp } from '@/lib/context';
import { formatChannel, formatDate, formatError, relativeTime, truncate } from '@/lib/format';
import { normalizeRcsSyncCtas } from '@/lib/cta';

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-amber-100 text-amber-800 border border-amber-200',
    approved: 'bg-green-100 text-green-800 border border-green-200',
    rejected: 'bg-red-100 text-red-800 border border-red-200',
    failed: 'bg-red-100 text-red-800 border border-red-200',
    submitted: 'bg-blue-100 text-blue-800 border border-blue-200',
    duplicate: 'bg-blue-100 text-blue-800 border border-blue-200',
    unknown: 'bg-gray-100 text-gray-800 border border-gray-200',
  };
  const s = (status || 'unknown').toLowerCase();
  return (
    <span className={`inline-flex px-2 py-0.5 rounded-md text-xs font-medium ${colors[s] || colors.unknown}`}>
      {status || 'unknown'}
    </span>
  );
}

function LiveBadge({ live, existsOnWaba, channel }: { live?: boolean; existsOnWaba?: boolean; channel?: string }) {
  if (channel === 'sms' && (live || existsOnWaba)) return <span className="rounded bg-blue-50 px-1.5 py-0.5 text-xs font-medium text-blue-700" title="Found in the VILPOWER DLT inventory; see approval status separately">On DLT portal</span>;
  if (live) {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-200" title="Synced live from the Karix WABA">
        <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
        Live on WABA
      </span>
    );
  }
  if (existsOnWaba) {
    return (
      <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium bg-blue-50 text-blue-700 border border-blue-200" title="Found on Karix WABA">
        <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
        On WABA
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-medium bg-gray-50 text-gray-500 border border-gray-200" title="Recorded locally at submission time">
      Local Log
    </span>
  );
}

function ActivityIcon({ action }: { action: string }) {
  const map: Record<string, { bg: string; icon: string }> = {
    TEMPLATE_SUBMISSION: { bg: 'bg-emerald-50 text-emerald-600', icon: 'M4 5h12M9 3v2m1.048 8.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129' },
    TEMPLATE_PREVIEW: { bg: 'bg-blue-50 text-blue-600', icon: 'M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z' },
    STATUS_POLL: { bg: 'bg-blue-50 text-blue-600', icon: 'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15' },
    CREDENTIALS_UPDATE: { bg: 'bg-amber-50 text-amber-600', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z' },
    CREDENTIALS_TEST: { bg: 'bg-blue-50 text-blue-600', icon: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z' },
  };
  const item = map[action] || { bg: 'bg-gray-50 text-gray-500', icon: 'M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z' };
  return (
    <span className={`w-6 h-6 rounded-lg flex items-center justify-center shrink-0 ${item.bg}`}>
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path d={item.icon} />
      </svg>
    </span>
  );
}

export default function DashboardPage() {
  const { account, channel, user, mounted, getAccountLabel } = useApp();
  const jiraWhitelisting = ['tata', 'tcl_promo', 'tcl_trans', 'tchfl', 'wealth', 'moneyfy'].includes(account);
  const [stats, setStats] = useState<Stats | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [statsLoading, setStatsLoading] = useState(true);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [operatorFilter, setOperatorFilter] = useState('all');
  const [polling, setPolling] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statsError, setStatsError] = useState<string | null>(null);
  const [templatesError, setTemplatesError] = useState<string | null>(null);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [activities, setActivities] = useState<ActivityLog[]>([]);
  const [activityStats, setActivityStats] = useState<ActivityStats | null>(null);
  const [activityLoading, setActivityLoading] = useState(true);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [lastSynced, setLastSynced] = useState<string | null>(null);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);
  const requestVersionRef = useRef(0);
  const [selectedTemplates, setSelectedTemplates] = useState<Set<string>>(new Set());
  const [deleting, setDeleting] = useState(false);
  const [deleteFeedback, setDeleteFeedback] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [showFileDeleteModal, setShowFileDeleteModal] = useState(false);
  const [deleteFile, setDeleteFile] = useState<File | null>(null);
  const [fileDeleting, setFileDeleting] = useState(false);
  const [syncingRcs, setSyncingRcs] = useState(false);
  const [syncRcsFeedback, setSyncRcsFeedback] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [syncingSingleRcs, setSyncingSingleRcs] = useState<Record<string, boolean>>({});
  const [syncedSingleRcs, setSyncedSingleRcs] = useState<Record<string, string>>({});
  const [syncWorkspaces, setSyncWorkspaces] = useState<RcsSyncWorkspace[]>([]);
  const [syncWorkspaceId, setSyncWorkspaceId] = useState('');
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);
  const [workspaceRevision, setWorkspaceRevision] = useState(0);
  const syncBusyRef = useRef(false);
  const selectedWorkspace = syncWorkspaces.find((workspace) => workspace.id === syncWorkspaceId);
  const syncBotId = account === 'apparel' ? selectedWorkspace?.bot_id : undefined;
  const syncDestinationReady = account !== 'apparel' || Boolean(selectedWorkspace && !workspaceLoading && !workspaceError);
  const syncBusy = syncingRcs || Object.values(syncingSingleRcs).some(Boolean);
  const syncDestinationLabel = account === 'apparel' ? selectedWorkspace?.name || 'Select workspace' : 'MoEngage';
  const syncScope = `${account}:${channel}:${syncWorkspaceId}`;
  const syncScopeRef = useRef(syncScope);
  const syncGenerationRef = useRef(0);
  if (syncScopeRef.current !== syncScope) {
    syncScopeRef.current = syncScope;
    syncGenerationRef.current += 1;
  }

  useEffect(() => {
    let ignore = false;
    setSyncWorkspaces([]);
    setSyncWorkspaceId('');
    setWorkspaceError(null);
    setWorkspaceLoading(account === 'apparel' && mounted);
    if (account !== 'apparel' || !mounted) return;
    fetchRcsSyncWorkspaces(account).then((workspaces) => {
      if (!ignore) setSyncWorkspaces(workspaces);
    }).catch((err) => {
      if (!ignore) setWorkspaceError(formatError(err));
    }).finally(() => {
      if (!ignore) setWorkspaceLoading(false);
    });
    return () => { ignore = true; };
  }, [account, mounted, workspaceRevision]);

  useEffect(() => {
    setSyncedSingleRcs({});
    setSyncRcsFeedback(null);
  }, [syncScope]);

  const handleSyncSingleRcsToMoEngage = async (t: Template) => {
    if (!syncDestinationReady || syncBusyRef.current) return;
    if (syncBotId && !t.sender_ids?.includes(syncBotId)) {
      setSyncRcsFeedback({
        message: `Cannot sync '${t.template_name}' to ${syncDestinationLabel}: only templates from Karix Bot ID ${syncBotId} can sync to this workspace. Choose a matching template or destination.`,
        type: 'error',
      });
      return;
    }
    syncBusyRef.current = true;
    const generation = syncGenerationRef.current;
    const tName = t.template_name;
    const isCarousel = (t.template_type || '').toLowerCase().includes('carousel') || Boolean(t.carousel_cards?.length);
    const syncTemplate = normalizeRcsSyncCtas(t, account);
    try {
      setSyncingSingleRcs((prev) => ({ ...prev, [tName]: true }));
      const res = await syncRcsTemplateToMoEngage({
        account,
        workspace_id: account === 'apparel' ? syncWorkspaceId : undefined,
        template_name: tName,
        template_id: tName,
        card_title: t.card_title || tName,
        card_description: t.template_message || tName,
        media_url: t.media_url,
        cta_text: t.cta_text || (account === 'apparel' ? 'Visit Store' : 'Explore Now'),
        cta_url: syncTemplate.cta_url,
        sender_id: syncBotId || t.sender_ids?.[0],
        template_type: isCarousel ? 'carousel' : 'card',
        carousel_cards: syncTemplate.carousel_cards || undefined,
        width: t.width,
        height: t.height,
      });
      if (generation !== syncGenerationRef.current) return;
      setSyncedSingleRcs((prev) => ({ ...prev, [tName]: res.moengage_id }));
      setSyncRcsFeedback({
        message: `Template '${tName}' created in ${syncDestinationLabel} (workspace: ${res.workspace_id}, MoEngage ID: ${res.moengage_id}).`,
        type: 'success',
      });
    } catch (err) {
      if (generation !== syncGenerationRef.current) return;
      setSyncRcsFeedback({
        message: `MoEngage Sync failed for '${tName}' to ${syncDestinationLabel}: ${err instanceof Error ? err.message : String(err)}`,
        type: 'error',
      });
    } finally {
      syncBusyRef.current = false;
      setSyncingSingleRcs((prev) => ({ ...prev, [tName]: false }));
    }
  };

  const handleSyncRcsToMoEngage = async () => {
    if (!syncDestinationReady || syncBusyRef.current) return;
    syncBusyRef.current = true;
    const generation = syncGenerationRef.current;
    try {
      setSyncingRcs(true);
      setSyncRcsFeedback(null);
      const res = await syncKarixRcsToMoEngage(account, account === 'apparel' ? syncWorkspaceId : undefined);
      if (generation !== syncGenerationRef.current) return;
      if (!res.ok) {
        setSyncRcsFeedback({ message: `${syncDestinationLabel}: ${res.error || 'Sync failed'}`, type: 'error' });
        return;
      }
      setSyncRcsFeedback({
        message: `Synced ${res.created_count} RCS template(s) to ${syncDestinationLabel} (workspace: ${res.workspace_id}) · ${res.skipped_count} skipped (already present/not approved)${res.error_count ? ` · ${res.error_count} failed` : ''}.`,
        type: 'success',
      });
    } catch (err) {
      if (generation !== syncGenerationRef.current) return;
      setSyncRcsFeedback({
        message: `${syncDestinationLabel}: ${err instanceof Error ? err.message : 'Failed to sync RCS templates to MoEngage'}`,
        type: 'error',
      });
    } finally {
      syncBusyRef.current = false;
      setSyncingRcs(false);
    }
  };
  const handleSyncSelectedRcsToMoEngage = async () => {
    if (selectedTemplates.size === 0 || !syncDestinationReady || syncBusyRef.current) return;
    const targets = templates.filter((t) => selectedTemplates.has(t.template_name));
    const mismatched = syncBotId ? targets.filter((t) => !t.sender_ids?.includes(syncBotId)) : [];
    if (mismatched.length > 0) {
      setSyncRcsFeedback({
        message: `No templates synced to ${syncDestinationLabel}: ${mismatched.length} selected template(s) do not belong to Karix Bot ID ${syncBotId} (${mismatched.map((t) => t.template_name).join(', ')}). Deselect them or choose a matching destination.`,
        type: 'error',
      });
      return;
    }
    syncBusyRef.current = true;
    const generation = syncGenerationRef.current;
    try {
      setSyncingRcs(true);
      setSyncRcsFeedback(null);
      let successCount = 0;
      let failCount = 0;
      const errors: string[] = [];

      for (const t of targets) {
        if (generation !== syncGenerationRef.current) return;
        try {
          const isCarousel = (t.template_type || '').toLowerCase().includes('carousel') || Boolean(t.carousel_cards?.length);
          const syncTemplate = normalizeRcsSyncCtas(t, account);
          await syncRcsTemplateToMoEngage({
            account,
            workspace_id: account === 'apparel' ? syncWorkspaceId : undefined,
            template_name: t.template_name,
            template_id: t.template_name,
            card_title: t.card_title || t.template_name,
            card_description: t.template_message || t.template_name,
            media_url: t.media_url,
            cta_text: t.cta_text || (account === 'apparel' ? 'Visit Store' : 'Explore Now'),
            cta_url: syncTemplate.cta_url,
            sender_id: syncBotId || t.sender_ids?.[0],
            template_type: isCarousel ? 'carousel' : 'card',
            carousel_cards: syncTemplate.carousel_cards || undefined,
            width: t.width,
            height: t.height,
          });
          if (generation !== syncGenerationRef.current) return;
          setSyncedSingleRcs((prev) => ({ ...prev, [t.template_name]: 'synced' }));
          successCount++;
        } catch (itemErr) {
          failCount++;
          const msg = itemErr instanceof Error ? itemErr.message : String(itemErr);
          if (!errors.includes(msg)) errors.push(msg);
        }
      }

      if (generation !== syncGenerationRef.current) return;
      const errDetail = errors.length > 0 ? ` (${errors.join('; ')})` : '';
      setSyncRcsFeedback({
        message: `Successfully synced ${successCount} selected RCS template(s) to ${syncDestinationLabel}${failCount > 0 ? ` (${failCount} failed${errDetail})` : ''}.`,
        type: successCount > 0 ? 'success' : 'error',
      });
      setSelectedTemplates(new Set());
    } catch (err) {
      if (generation !== syncGenerationRef.current) return;
      setSyncRcsFeedback({
        message: `Failed to sync selected templates to ${syncDestinationLabel}: ${err instanceof Error ? err.message : String(err)}`,
        type: 'error',
      });
    } finally {
      syncBusyRef.current = false;
      setSyncingRcs(false);
    }
  };



  // Debounce search input
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  // Reset filters when switching account or channel
  useEffect(() => {
    requestVersionRef.current += 1;
    setStats(null);
    setTemplates([]);
    setError(null);
    setStatsError(null);
    setTemplatesError(null);
    setLastSynced(null);
    setStatusFilter('');
    setOperatorFilter('all');
    setSearch('');
    setExpandedRow(null);
    setSelectedTemplates(new Set());
    setDeleteFeedback(null);
  }, [account, channel]);

  const loadStats = useCallback(async () => {
    if (!mounted) return;
    const requestVersion = requestVersionRef.current;
    try {
      setStatsLoading(true);
      const data = await fetchStats(account, channel);
      if (requestVersion !== requestVersionRef.current) return;
      setStats(data);
      setLastSynced(data.error ? null : new Date().toISOString());
      setStatsError(data.error ? `${channel === 'sms' ? 'VILPOWER' : 'Karix'} sync degraded: ${formatError(data.error)}` : null);
    } catch (err) {
      if (requestVersion === requestVersionRef.current) {
        setStatsError(err instanceof Error ? err.message : 'Failed to fetch stats');
      }
    } finally {
      if (requestVersion === requestVersionRef.current) setStatsLoading(false);
    }
  }, [account, channel, mounted]);

  const loadTemplates = useCallback(async () => {
    if (!mounted) return;
    const requestVersion = requestVersionRef.current;
    try {
      setTemplatesLoading(true);
      const params: { status?: string; search?: string } = {};
      if (statusFilter) params.status = statusFilter;
      if (debouncedSearch) params.search = debouncedSearch;
      const data = await fetchTemplates({ account, channel, ...params });
      if (requestVersion !== requestVersionRef.current) return;
      setTemplates(data);
      setTemplatesError(null);
    } catch (err) {
      if (requestVersion === requestVersionRef.current) {
        setTemplatesError(err instanceof Error ? err.message : 'Failed to fetch templates');
      }
    } finally {
      if (requestVersion === requestVersionRef.current) setTemplatesLoading(false);
    }
  }, [account, channel, statusFilter, debouncedSearch, mounted]);

  const loadActivity = useCallback(async () => {
    if (!mounted) return;
    const requestVersion = requestVersionRef.current;
    setActivityLoading(true);
    try {
      const [logs, activitySummary] = await Promise.all([
        fetchActivityLogs({ limit: 6 }),
        fetchActivityStats(),
      ]);
      if (requestVersion !== requestVersionRef.current) return;
      setActivities(logs);
      setActivityStats(activitySummary);
      setActivityError(null);
    } catch (err) {
      if (requestVersion === requestVersionRef.current) {
        setActivityError(err instanceof Error ? err.message : 'Activity is unavailable');
      }
    } finally {
      if (requestVersion === requestVersionRef.current) setActivityLoading(false);
    }
  }, [mounted]);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  useEffect(() => {
    loadActivity();
  }, [loadActivity]);

  useEffect(() => {
    if (autoRefresh && mounted) {
      const intervalSec = stats?.sla_insights?.next_recommended_poll_sec || 30;
      const intervalMs = Math.max(15, Math.min(120, intervalSec)) * 1000;
      intervalRef.current = setInterval(() => {
        loadStats();
        loadTemplates();
        loadActivity();
      }, intervalMs);
    }
    return () => {
      clearInterval(intervalRef.current as NodeJS.Timeout);
    };
  }, [autoRefresh, loadStats, loadTemplates, loadActivity, mounted, stats?.sla_insights?.next_recommended_poll_sec]);

  const handlePoll = async () => {
    try {
      setPolling(true);
      await pollPending(account, channel, user);
      await Promise.all([loadStats(), loadTemplates()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to poll pending');
    } finally {
      setPolling(false);
    }
  };
  const handleToggleSelect = (name: string) => {
    setSelectedTemplates(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const handleSelectAll = () => {
    const selectable = visibleTemplates.map(t => t.template_name).filter(Boolean);
    if (selectedTemplates.size === selectable.length && selectable.length > 0) {
      setSelectedTemplates(new Set());
    } else {
      setSelectedTemplates(new Set(selectable));
    }
  };

  const handleDeleteSelected = async () => {
    if (selectedTemplates.size === 0) return;
    const count = selectedTemplates.size;
    const confirmed = window.confirm(
      `Are you sure you want to delete ${count} selected template${count === 1 ? '' : 's'} from ${accountLabel} on Karix/Meta? This action cannot be undone.`
    );
    if (!confirmed) return;

    try {
      setDeleting(true);
      setDeleteFeedback(null);
      const res = await deleteTemplates(Array.from(selectedTemplates), account, channel, user, false);
      const deletedCount = res.deleted.length;
      const failedCount = res.failed.length;
      setSelectedTemplates(new Set());
      setDeleteFeedback({
        type: failedCount > 0 ? 'error' : 'success',
        message: `Deleted ${deletedCount} template${deletedCount === 1 ? '' : 's'}${failedCount > 0 ? ` (${failedCount} failed)` : ''}.`,
      });
      await Promise.all([loadStats(), loadTemplates()]);
    } catch (err) {
      setDeleteFeedback({
        type: 'error',
        message: err instanceof Error ? err.message : 'Delete failed',
      });
    } finally {
      setDeleting(false);
    }
  };

  const handleDeleteFromFile = async () => {
    if (!deleteFile) return;
    try {
      setFileDeleting(true);
      setDeleteFeedback(null);
      const res = await deleteTemplatesFromFile(deleteFile, account, channel, user);
      const deletedCount = res.deleted.length;
      const failedCount = res.failed.length;
      setShowFileDeleteModal(false);
      setDeleteFile(null);
      setDeleteFeedback({
        type: failedCount > 0 ? 'error' : 'success',
        message: `File delete complete: ${deletedCount} template${deletedCount === 1 ? '' : 's'} deleted${failedCount > 0 ? ` (${failedCount} failed)` : ''}.`,
      });
      await Promise.all([loadStats(), loadTemplates()]);
    } catch (err) {
      setDeleteFeedback({
        type: 'error',
        message: err instanceof Error ? err.message : 'File deletion failed',
      });
    } finally {
      setFileDeleting(false);
    }
  };


  const toggleRow = (sourceRef: string) => {
    setExpandedRow(prev => (prev === sourceRef ? null : sourceRef));
  };

  const getCategory = (t: Template): string => {
    if (t.provider_response && typeof t.provider_response === 'object') {
      const resp = t.provider_response as Record<string, unknown>;
      if (typeof resp.category === 'string') return resp.category;
    }
    return '—';
  };

  const accountLabel = getAccountLabel(account);
  const channelLabel = formatChannel(channel);

  // Client-side operator filter (server filters status/search only)
  const operators = Array.from(
    new Set(templates.map(t => t.submitted_by).filter(Boolean) as string[])
  ).sort();
  const visibleTemplates = operatorFilter === 'all'
    ? templates
    : templates.filter(t => (t.submitted_by || '—') === operatorFilter);
  const hasFilters = Boolean(search || statusFilter || operatorFilter !== 'all');
  const resetFilters = () => {
    setSearch('');
    setStatusFilter('');
    setOperatorFilter('all');
  };

  // Distribution bar segments
  const total = stats?.total ?? 0;
  const segs = channel === 'whatsapp'
    ? [
        { key: 'approved', label: 'Approved', value: stats?.approved ?? 0, color: 'bg-emerald-500' },
        { key: 'pending', label: 'Pending', value: stats?.pending ?? 0, color: 'bg-amber-400' },
        { key: 'rejected', label: 'Rejected', value: stats?.rejected ?? 0, color: 'bg-red-500' },
        { key: 'failed', label: 'Pipeline Errors', value: stats?.failed ?? 0, color: 'bg-rose-400' },
      ]
    : [
        { key: 'approved', label: 'Approved', value: stats?.approved ?? 0, color: 'bg-emerald-500' },
        { key: 'pending', label: 'Pending', value: stats?.pending ?? 0, color: 'bg-amber-400' },
        { key: 'failed', label: 'Failed', value: stats?.failed ?? 0, color: 'bg-red-500' },
        { key: 'duplicate', label: 'Duplicate', value: stats?.duplicate ?? 0, color: 'bg-blue-400' },
      ];
  const distTotal = segs.reduce((acc, s) => acc + s.value, 0);

  // Clickable KPI cards set the status filter
  const kpiCards = channel === 'whatsapp'
    ? [
        { key: 'approved', label: 'Approved', value: stats?.approved ?? 0, dot: 'bg-emerald-500', statusValue: 'approved' },
        { key: 'pending', label: 'Pending Review', value: stats?.pending ?? 0, dot: 'bg-amber-500', statusValue: 'pending' },
        { key: 'rejected', label: 'Rejected by Meta', value: stats?.rejected ?? 0, dot: 'bg-red-500', statusValue: 'rejected' },
        { key: 'failed', label: 'Pipeline Errors', value: stats?.failed ?? 0, dot: 'bg-rose-500', statusValue: 'failed' },
      ]
    : [
        { key: 'approved', label: 'Approved', value: stats?.approved ?? 0, dot: 'bg-emerald-500', statusValue: 'approved' },
        { key: 'pending', label: 'Pending', value: stats?.pending ?? 0, dot: 'bg-amber-500', statusValue: 'pending' },
        { key: 'failed', label: 'Failed', value: stats?.failed ?? 0, dot: 'bg-red-500', statusValue: 'failed' },
        { key: 'total', label: 'Total Templates', value: total, dot: 'bg-blue-500', statusValue: '' },
      ];

  return (
    <div className="workspace-page space-y-6">
      <header className="space-y-5 border-b border-gray-200 pb-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="workspace-eyebrow mb-2">Campaign operations</p>
            <h1 className="workspace-heading">Template approvals</h1>
            <p className="mt-2 text-sm text-gray-600">{accountLabel} <span className="mx-1 text-gray-300">/</span> {channelLabel}</p>
          </div>
          {jiraWhitelisting && (
            <Link href="/briefs" className="workspace-button-primary">
              Review Jira briefs <span aria-hidden="true">→</span>
            </Link>
          )}
        </div>
        <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            {stats?.error || statsError || templatesError ? (
              <span className="inline-flex items-center gap-1.5 rounded-md border border-red-200 bg-red-50 px-2 py-1 text-xs font-medium text-red-700" title={formatError(statsError || templatesError || stats?.error || '')}>
                <span className="h-1.5 w-1.5 rounded-full bg-red-500" />
                {templatesError && !stats?.error && !statsError ? 'Dashboard Degraded' : `${channel === 'sms' ? 'VILPOWER' : 'Karix'} Degraded`}
              </span>
            ) : stats ? (
              <span className="inline-flex items-center gap-1.5 rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-700">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
                {channel === 'sms' ? 'VILPOWER' : 'Karix'} Synced{lastSynced ? ` · ${relativeTime(lastSynced)}` : ''}
              </span>
            ) : (
              <span className="text-sm text-gray-500">Checking {channel === 'sms' ? 'VILPOWER' : 'Karix'} connection…</span>
            )}
            {stats?.karix_health && (
              <span
                className={`rounded-md border px-2 py-1 text-xs font-medium ${
                  stats.karix_health.status === 'optimal' ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                    : stats.karix_health.status === 'moderate' ? 'border-blue-200 bg-blue-50 text-blue-800'
                    : stats.karix_health.status === 'degraded' ? 'border-amber-200 bg-amber-50 text-amber-800'
                    : 'border-rose-200 bg-rose-50 text-rose-800'
                }`}
                title={`Average Latency: ${stats.karix_health.avg_latency_sec}s, Optimal Concurrency: ${stats.karix_health.optimal_workers} parallel workers, Pacing: ${stats.karix_health.pacing_delay_sec}s`}
              >
                Karix API: {stats.karix_health.status.toUpperCase()} ({stats.karix_health.avg_latency_sec}s · {stats.karix_health.optimal_workers}w)
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-3">
            {(channel === 'whatsapp' || (channel === 'sms' && account === 'tata')) && (
              <button onClick={handlePoll} disabled={polling} className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50">
                {polling ? 'Polling…' : channel === 'sms' ? 'Refresh DLT Approvals' : 'Poll Pending'}
              </button>
            )}
            {channel === 'rcs' && account !== 'apparel' && (
              <button
                onClick={handleSyncRcsToMoEngage}
                disabled={syncBusy || !syncDestinationReady}
                className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50"
                title="Pull approved RCS templates from Karix and register them in MoEngage Settings"
              >
                {syncingRcs ? `Syncing to ${syncDestinationLabel}…` : `Sync to ${syncDestinationLabel}`}
              </button>
            )}
            <label className="flex cursor-pointer select-none items-center gap-2 text-sm text-gray-600">
              <input type="checkbox" checked={autoRefresh} onChange={(e) => setAutoRefresh(e.target.checked)} className="rounded border-gray-300 text-blue-600 focus:ring-blue-500" />
              Auto-refresh
            </label>
          </div>
        </div>
      </header>

      {/* APPAREL BRAND: DEDICATED KARIX RCS -> MOENGAGE SYNC STUDIO */}
      {account === 'apparel' && (
        <section className="workspace-panel p-5">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-xl">
              <p className="workspace-eyebrow mb-2">Apparel · RCS only</p>
              <h2 className="text-lg font-medium text-gray-900">Sync to MoEngage</h2>
              <p className="mt-2 text-sm leading-relaxed text-gray-600">
                Pull approved Karix RCS templates into one selected destination. Duplicate detection and sender mapping stay scoped to that workspace.
              </p>
              <a href="/settings" className="mt-3 inline-block text-sm font-medium text-blue-700 hover:underline">MoEngage connection settings →</a>
            </div>
            <div className="flex min-w-0 flex-col gap-3 lg:w-96 lg:shrink-0">
              <label className="text-sm font-medium text-gray-700" htmlFor="rcs-sync-workspace">Destination MoEngage workspace</label>
              <select
                id="rcs-sync-workspace"
                value={syncWorkspaceId}
                onChange={(event) => {
                  if (syncBusyRef.current) return;
                  setSyncWorkspaceId(event.target.value);
                  setSyncedSingleRcs({});
                  setSyncRcsFeedback(null);
                }}
                disabled={workspaceLoading || syncBusy}
                className="w-full min-w-0 max-w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 disabled:opacity-60"
              >
                <option value="">{workspaceLoading ? 'Loading workspaces…' : 'Select workspace…'}</option>
                {syncWorkspaces.map((workspace) => (
                  <option key={workspace.id} value={workspace.id}>{workspace.name} ({workspace.id})</option>
                ))}
              </select>
              {syncBotId && (
                <p className="max-w-sm break-words text-sm text-gray-600">
                  Karix Bot ID: <span className="font-mono">{syncBotId}</span>. Only templates from this matching bot sync to this workspace.
                </p>
              )}
              {workspaceError ? (
                <div role="alert" className="max-w-sm text-sm text-red-700">
                  {workspaceError}
                  <button type="button" disabled={syncBusy} onClick={() => setWorkspaceRevision((value) => value + 1)} className="ml-2 underline">Retry workspaces</button>
                </div>
              ) : !workspaceLoading && syncWorkspaces.length === 0 ? (
                <p className="max-w-sm text-sm text-gray-600">
                  No active workspaces available.
                  <button type="button" disabled={syncBusy} onClick={() => setWorkspaceRevision((value) => value + 1)} className="ml-2 underline">Retry workspaces</button>
                </p>
              ) : null}
              <p className="max-w-sm text-sm text-gray-500">Missing a destination? Check the saved Apparel session and organization in <a href="/settings" className="underline">MoEngage connection settings</a>.</p>
              <button
                onClick={handleSyncRcsToMoEngage}
                disabled={syncBusy || !syncDestinationReady}
                className="px-4 py-2.5 rounded-lg text-sm font-medium bg-blue-700 text-white hover:bg-blue-800 transition-colors flex items-center gap-2 disabled:opacity-60"
              >
                {syncingRcs ? (
                  <>
                    <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                    </svg>
                    <span>Syncing Templates to {syncDestinationLabel}...</span>
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2">
                      <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                    <span>Sync Approved RCS to {syncDestinationLabel}</span>
                  </>
                )}
              </button>
            </div>
          </div>

        </section>
      )}
      {(statsError || templatesError || error) && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-start gap-3 text-sm text-red-700">
          <svg className="w-5 h-5 text-red-500 shrink-0 mt-0.5" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
          </svg>
          <div className="flex-1">{formatError(statsError || templatesError || error || '')}</div>
          <button onClick={() => { setStatsError(null); setTemplatesError(null); setError(null); }} className="text-red-400 hover:text-red-600" aria-label="Dismiss error">&times;</button>
        </div>
      )}

      {/* RCS -> MoEngage sync feedback */}
      {syncRcsFeedback && (
        <div className={`p-4 rounded-xl border flex items-start gap-3 text-sm ${
          syncRcsFeedback.type === 'success'
            ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
            : 'bg-red-50 border-red-200 text-red-700'
        }`}>
          <div className="flex-1">{syncRcsFeedback.message}</div>
          <button onClick={() => setSyncRcsFeedback(null)} className="text-gray-400 hover:text-gray-600" aria-label="Dismiss">&times;</button>
        </div>
      )}

      <section aria-labelledby="template-health-heading" className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="template-health-heading" className="text-base font-medium text-gray-900">Approval inventory</h2>
          <p className="text-sm text-gray-500">
            {statsError ? stats ? 'Last available counts · sync degraded' : 'Counts unavailable · sync degraded' : statsLoading ? 'Refreshing counts…' : stats ? `${total.toLocaleString()} templates in this account and channel` : 'Counts unavailable'}
          </p>
        </div>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {kpiCards.map(card => {
            const active = Boolean(card.statusValue) && statusFilter === card.statusValue;
            return (
              <button
                key={card.key}
                type="button"
                onClick={() => setStatusFilter(active ? '' : card.statusValue)}
                aria-pressed={active}
                className={`rounded-xl border bg-white p-4 text-left transition-colors ${
                  active ? 'border-blue-400 bg-blue-50/40 ring-1 ring-blue-200' : 'border-gray-200 hover:border-gray-400'
                }`}
                title={card.statusValue ? `Filter table: ${card.label}` : 'Show all'}
              >
                <span className="flex items-center gap-2 text-sm font-medium text-gray-600">
                  <span className={`h-2 w-2 shrink-0 rounded-full ${card.dot}`} />
                  {card.label}
                </span>
                <span className="workspace-number mt-3 block text-3xl font-medium text-gray-900">
                  {statsLoading ? <span className="block h-9 w-14 rounded bg-gray-100" aria-label="Loading count" /> : stats ? card.value.toLocaleString() : '—'}
                </span>
                <span className={`mt-2 block text-xs ${active ? 'text-blue-700' : 'text-gray-500'}`}>
                  {active ? 'Filter applied' : card.statusValue ? 'View templates →' : 'View all templates →'}
                </span>
              </button>
            );
          })}
        </div>
      </section>
      {/* Predictive Meta Approval SLA Countdown Banner */}
      {!statsLoading && stats?.sla_insights && stats.pending > 0 && Object.keys(stats.sla_insights.categories).length > 0 && (
        <div className="bg-amber-50/70 border border-amber-200/80 rounded-xl p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-2xs">
          <div className="flex items-center gap-2.5 flex-wrap">
            <span className="text-sm font-medium text-amber-950">
              Estimated Meta review time ({stats.pending} pending)
            </span>
            <div className="flex items-center gap-1.5 flex-wrap">
              {Object.entries(stats.sla_insights.categories).map(([cat, count]) => (
                <span
                  key={cat}
                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-white text-amber-900 border border-amber-200"
                >
                  <span className="font-medium text-amber-800">{count}</span> {cat}
                </span>
              ))}
            </div>
          </div>
          <div className="text-xs text-amber-800 font-mono shrink-0">
            Next smart poll in ~{stats.sla_insights.next_recommended_poll_sec}s
          </div>
        </div>
      )}


      {/* Status distribution bar */}
      {!statsLoading && distTotal > 0 && (
        <div className="workspace-panel p-4">
          <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
            <span className="text-sm font-medium text-gray-700">Status distribution</span>
            <span className="text-xs text-gray-500">{distTotal.toLocaleString()} template{distTotal === 1 ? '' : 's'}</span>
          </div>
          <div className="flex h-2.5 w-full rounded-full overflow-hidden bg-gray-100">
            {segs.map(seg =>
              seg.value > 0 ? (
                <div
                  key={seg.key}
                  className={seg.color}
                  style={{ width: `${(seg.value / distTotal) * 100}%` }}
                  title={`${seg.label}: ${seg.value}`}
                />
              ) : null
            )}
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2">
            {segs.map(seg => (
              <span key={seg.key} className="flex items-center gap-1.5 text-xs text-gray-600">
                <span className={`w-2 h-2 rounded-full ${seg.color}`} />
                {seg.label} <span className="font-medium text-gray-900">{seg.value.toLocaleString()}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Main grid: table + activity rail */}
      <div className="grid grid-cols-1 items-start gap-6 2xl:grid-cols-[minmax(0,1fr)_19rem]">
        {/* Left: Templates table */}
        <section aria-labelledby="inventory-heading" className="min-w-0 space-y-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 id="inventory-heading" className="text-base font-medium text-gray-900">Template inventory</h2>
            <span className="text-sm text-gray-500" aria-live="polite">
              {templatesLoading ? 'Refreshing inventory…' : templatesError ? 'Inventory unavailable' : `${visibleTemplates.length.toLocaleString()} shown${operatorFilter !== 'all' ? ` of ${templates.length.toLocaleString()} fetched` : ''}`}
            </span>
          </div>
          <div className="workspace-panel space-y-4 p-4">
            <div className="flex flex-wrap items-end gap-3">
              <div className="min-w-0 flex-[2_1_240px]">
                <label htmlFor="inventory-search" className="mb-1.5 block text-sm font-medium text-gray-700">Search inventory</label>
                <input
                  id="inventory-search"
                  type="search"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder={channel === 'whatsapp' ? 'Template name or reference ID' : channel === 'rcs' ? 'Name, DLT ID, or sender' : 'Sender, ACK ID, or destination'}
                  className="workspace-search w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                />
              </div>
              <div className="min-w-0 flex-1 basis-40">
                <label htmlFor="inventory-status" className="mb-1.5 block text-sm font-medium text-gray-700">Status</label>
                <select id="inventory-status" value={statusFilter} onChange={e => setStatusFilter(e.target.value)} className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100">
                  <option value="">All Statuses</option>
                  {channel === 'whatsapp' ? (
                    <>
                      <option value="pending">Pending Review</option>
                      <option value="approved">Approved</option>
                      <option value="rejected">Rejected</option>
                      <option value="failed">Submission Failed</option>
                    </>
                  ) : (
                    <>
                      <option value="approved">Approved</option>
                      <option value="pending">Pending</option>
                      <option value="submitted">Submitted</option>
                      <option value="failed">Failed</option>
                      <option value="duplicate">Duplicate</option>
                    </>
                  )}
                </select>
              </div>
              <div className="min-w-0 flex-1 basis-40">
                <label htmlFor="inventory-operator" className="mb-1.5 block text-sm font-medium text-gray-700">Submitted by</label>
                <select id="inventory-operator" value={operatorFilter} onChange={e => setOperatorFilter(e.target.value)} className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100">
                  <option value="all">All Operators</option>
                  {operatorFilter !== 'all' && !operators.includes(operatorFilter) && <option value={operatorFilter}>{operatorFilter}</option>}
                  {operators.map(op => <option key={op} value={op}>{op}</option>)}
                </select>
              </div>
            </div>
            {hasFilters && (
              <div className="flex flex-wrap items-center gap-2 border-t border-gray-100 pt-3">
                <span className="text-xs text-gray-500">Active filters</span>
                {search && <button type="button" onClick={() => setSearch('')} className="workspace-filter-chip inline-flex max-w-full items-center gap-2 rounded-md border border-gray-200 bg-gray-50 px-2 py-1 text-sm text-gray-700" aria-label={`Remove search filter: ${search}`}><span className="truncate">Search: {search}</span><span aria-hidden="true">×</span></button>}
                {statusFilter && <button type="button" onClick={() => setStatusFilter('')} className="workspace-filter-chip rounded-md border border-gray-200 bg-gray-50 px-2 py-1 text-sm text-gray-700" aria-label={`Remove status filter: ${statusFilter}`}>Status: {statusFilter} <span aria-hidden="true">×</span></button>}
                {operatorFilter !== 'all' && <button type="button" onClick={() => setOperatorFilter('all')} className="workspace-filter-chip inline-flex max-w-full items-center gap-2 rounded-md border border-gray-200 bg-gray-50 px-2 py-1 text-sm text-gray-700" aria-label={`Remove operator filter: ${operatorFilter}`}><span className="truncate">Submitted by: {operatorFilter}</span><span aria-hidden="true">×</span></button>}
                <button type="button" onClick={resetFilters} className="px-2 py-1 text-sm font-medium text-blue-700 hover:underline">Reset all</button>
              </div>
            )}
          </div>

          {/* Selection Actions & Delete Feedback Banner */}
          {deleteFeedback && (
            <div className={`p-3.5 rounded-xl border text-sm flex items-center justify-between gap-2 ${
              deleteFeedback.type === 'success'
                ? 'bg-emerald-50 border-emerald-200 text-emerald-800'
                : 'bg-red-50 border-red-200 text-red-800'
            }`}>
              <div className="flex items-center gap-2">
                <span className="font-medium">{deleteFeedback.message}</span>
              </div>
              <button onClick={() => setDeleteFeedback(null)} className="text-gray-400 hover:text-gray-600" aria-label="Dismiss delete feedback">&times;</button>
            </div>
          )}

          {(channel === 'whatsapp' || channel === 'rcs') && (
            <div className="workspace-panel flex flex-wrap items-center justify-between gap-3 p-3">
              <div className="flex items-center gap-2 text-sm text-gray-600">
                <span className="font-medium tabular-nums text-gray-900">{selectedTemplates.size}</span>
                <span>of {visibleTemplates.length} selected</span>
                {selectedTemplates.size > 0 && (
                  <button
                    type="button"
                    onClick={() => setSelectedTemplates(new Set())}
                    className="text-blue-600 hover:text-blue-800 font-medium ml-1 cursor-pointer"
                  >
                    Clear
                  </button>
                )}
              </div>

              <div className="flex flex-wrap items-center gap-2">
                {selectedTemplates.size > 0 && channel === 'rcs' && (
                  <button
                    type="button"
                    onClick={handleSyncSelectedRcsToMoEngage}
                    disabled={syncBusy || !syncDestinationReady}
                    className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-sm font-medium text-white bg-blue-700 hover:bg-blue-800 transition-colors cursor-pointer disabled:opacity-50"
                  >
                    {syncingRcs ? (
                      <>
                        <svg className="animate-spin h-3.5 w-3.5 text-white" viewBox="0 0 24 24" fill="none">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                        </svg>
                        <span>Syncing to {syncDestinationLabel} ({selectedTemplates.size})...</span>
                      </>
                    ) : (
                      <>
                        <span>Sync selected to {syncDestinationLabel} ({selectedTemplates.size})</span>
                      </>
                    )}
                  </button>
                )}

                {selectedTemplates.size > 0 && channel === 'whatsapp' && (
                  <button
                    type="button"
                    onClick={handleDeleteSelected}
                    disabled={deleting}
                    className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium bg-red-600 hover:bg-red-700 text-white transition-colors cursor-pointer disabled:opacity-50"
                  >
                    {deleting ? (
                      <>
                        <svg className="animate-spin h-3.5 w-3.5 text-white" viewBox="0 0 24 24" fill="none">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                        </svg>
                        Deleting...
                      </>
                    ) : (
                      <>
                        <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="currentColor">
                          <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
                        </svg>
                        Delete Selected ({selectedTemplates.size})
                      </>
                    )}
                  </button>
                )}

                {channel === 'whatsapp' && (
                  <button
                    type="button"
                    onClick={() => setShowFileDeleteModal(true)}
                    disabled={deleting || fileDeleting}
                    className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium text-gray-700 bg-white hover:bg-gray-50 border border-gray-200 transition-colors cursor-pointer disabled:opacity-50"
                    title="Upload a spreadsheet (CSV/Excel) to delete all templates listed in it"
                  >
                    <svg className="w-3.5 h-3.5 text-red-500" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM6.293 6.707a1 1 0 010-1.414l3-3a1 1 0 011.414 0l3 3a1 1 0 01-1.414 1.414L11 5.414V13a1 1 0 11-2 0V5.414L7.707 6.707a1 1 0 01-1.414 0z" clipRule="evenodd" />
                    </svg>
                    Delete by File (CSV/Excel)
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Table */}
          <div className="workspace-panel overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[840px] text-left">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200 text-xs font-medium text-gray-600">
                    {(channel === 'whatsapp' || channel === 'rcs') && (
                      <th className="w-10 px-3 py-3 text-center">
                        <input
                          type="checkbox"
                          checked={selectedTemplates.size === visibleTemplates.length && visibleTemplates.length > 0}
                          onChange={handleSelectAll}
                          className="rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
                          title="Select all visible templates"
                          aria-label="Select all visible templates"
                        />
                      </th>
                    )}
                    {channel === 'whatsapp' ? (
                      <>
                        <th className="px-4 py-3">Template Name</th>
                        <th className="px-4 py-3">Category</th>
                        <th className="px-4 py-3">Status</th>
                        <th className="px-4 py-3">Approval</th>
                        <th className="px-4 py-3">Submitted By</th>
                        <th className="px-4 py-3">Source</th>
                        <th className="px-4 py-3">Submitted At</th>
                        <th className="px-4 py-3 text-right">Details</th>
                      </>
                    ) : (
                      <>
                        <th className="px-4 py-3">Template Name</th>
                        <th className="px-4 py-3">Type</th>
                        <th className="px-4 py-3">Status</th>
                        <th className="px-4 py-3">Approval</th>
                        <th className="px-4 py-3">Submitted By</th>
                        <th className="px-4 py-3">Submitted At</th>
                        <th className="px-4 py-3 text-right">Details</th>
                      </>
                    )}
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-200 text-sm text-gray-800">
                  {templatesLoading ? (
                    <tr>
                      <td colSpan={channel === 'whatsapp' ? 9 : channel === 'rcs' ? 8 : 7} className="px-6 py-12 text-center text-gray-500">
                        <div className="flex items-center justify-center gap-2">
                          <svg className="animate-spin h-4 w-4 text-blue-600" viewBox="0 0 24 24" fill="none">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                          </svg>
                          Loading templates...
                        </div>
                      </td>
                    </tr>
                  ) : visibleTemplates.length === 0 ? (
                    <tr>
                      <td colSpan={(channel === 'whatsapp' || channel === 'rcs') ? 9 : 8} className="px-6 py-12 text-center">
                        <div className="flex flex-col items-center gap-3">
                          <div className="w-10 h-10 rounded-full bg-gray-100 flex items-center justify-center text-gray-400">
                            <svg className="w-5 h-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
                              <path d="M10 3v10M6 9l4 4 4-4M3 15h14" />
                            </svg>
                          </div>
                          <div className="text-sm font-medium text-gray-700">
                            {templatesError
                              ? 'Template history is unavailable.'
                              : stats?.error
                                ? `${channel === 'sms' ? 'VILPOWER' : 'Karix'} connection degraded — showing local history only`
                                : hasFilters ? 'No templates match these filters.' : `No ${channelLabel} templates found for ${accountLabel}.`}
                          </div>
                          <p className="text-sm text-gray-500 max-w-sm text-center">
                            {templatesError
                              ? 'Refresh after the service recovers.'
                              : stats?.error
                                ? 'Check credentials in Settings, then refresh.'
                                : hasFilters ? 'Try another search or reset the filters to see the full inventory.' : account === 'apparel' ? 'Choose a MoEngage workspace above to sync approved Karix RCS templates.' : jiraWhitelisting ? 'Open a Jira brief to review and whitelist your templates.' : 'Upload a spreadsheet on the Submit Templates page to whitelist your first template.'}
                          </p>
                          {!stats?.error && !templatesError && hasFilters && <button type="button" onClick={resetFilters} className="text-sm font-medium text-blue-700 hover:underline">Reset all filters</button>}
                          {!stats?.error && !templatesError && !hasFilters && account !== 'apparel' && (
                            <a
                              href={jiraWhitelisting ? '/briefs' : '/submit'}
                              className="text-xs font-medium text-blue-600 hover:text-blue-800 mt-1 inline-flex items-center gap-1"
                            >
                              {jiraWhitelisting ? 'Open Jira Briefs →' : 'Go to Submit Templates →'}
                            </a>
                          )}
                        </div>
                      </td>
                    </tr>
                  ) : (
                    visibleTemplates.map((t, idx) => {
                      const key = channel === 'sms'
                        ? (t.template_id || t.provider_ref_id || t.task_id || `sms-row-${idx}`)
                        : (t.source_ref || t.template_name || `row-${idx}`);
                      const isExpanded = expandedRow === key;
                      const rejectionReason = t.approval_reason && String(t.approval_reason) !== 'NONE' ? String(t.approval_reason) : null;
                      const pipelineError = t.status === 'failed' && t.error ? formatError(t.error) : null;

                      return (
                        <Fragment key={key}>
                          <tr
                            onClick={() => toggleRow(key)}
                            role="button"
                            tabIndex={0}
                            aria-expanded={isExpanded}
                            aria-label={`${isExpanded ? 'Hide' : 'Show'} details for ${t.template_name}`}
                            onKeyDown={(e) => {
                              if (e.target !== e.currentTarget) return;
                              if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault();
                                toggleRow(key);
                              }
                            }}
                            className={`hover:bg-gray-50/70 transition-colors cursor-pointer ${isExpanded ? 'bg-blue-50/30' : ''}`}
                          >
                            {(channel === 'whatsapp' || channel === 'rcs') && (
                              <td className="w-10 px-3 py-3 text-center" onClick={(e) => e.stopPropagation()}>
                                <input
                                  type="checkbox"
                                  checked={selectedTemplates.has(t.template_name)}
                                  onChange={() => handleToggleSelect(t.template_name)}
                                  className="rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
                                  title={`Select ${t.template_name}`}
                                  aria-label={`Select ${t.template_name}`}
                                />
                              </td>
                            )}
                            <td className="px-4 py-3">
                              <div className="flex items-center gap-2">
                                <span className="font-medium text-gray-900 font-mono text-sm">{t.template_name}</span>
                                <LiveBadge live={t.live} existsOnWaba={t.exists_on_waba} channel={channel} />
                              </div>
                              <div className="text-xs text-gray-500 font-mono mt-1">
                                {channel === 'whatsapp' ? (t.provider_ref_id ? `ID ${t.provider_ref_id}` : 'Not submitted yet') : ((t.template_id || t.provider_ref_id) ? `DLT ${t.template_id || t.provider_ref_id}` : '')}
                              </div>
                            </td>

                            {channel === 'whatsapp' && (
                              <td className="px-4 py-3 text-gray-600">{getCategory(t)}</td>
                            )}

                            {channel !== 'whatsapp' && (
                              <td className="px-4 py-3 text-gray-600">
                                <div className="font-medium">{t.template_type || '—'}</div>
                                {Array.isArray(t.sender_ids) && t.sender_ids.length > 0 && (
                                  <div className="text-xs text-gray-500">{t.sender_ids.join(', ')}</div>
                                )}
                              </td>
                            )}

                            <td className="px-4 py-3">
                              <StatusBadge status={t.status} />
                            </td>

                            <td className="px-4 py-3">
                              <StatusBadge status={t.approval_status || 'unknown'} />
                              {rejectionReason && (
                                <div className="text-xs text-red-600 mt-1 max-w-[180px] truncate" title={rejectionReason}>
                                  {truncate(rejectionReason, 60)}
                                </div>
                              )}
                              {pipelineError && (
                                <div className="text-xs text-rose-600 mt-1 max-w-[180px] truncate" title={pipelineError}>
                                  {truncate(pipelineError, 60)}
                                </div>
                              )}
                            </td>

                            <td className="px-4 py-3">
                              {t.submitted_by ? (
                                <span className="inline-flex items-center gap-1.5">
                                  <span className="w-6 h-6 rounded-full bg-gray-100 text-gray-600 font-medium text-xs flex items-center justify-center shrink-0">
                                    {t.submitted_by.charAt(0).toUpperCase()}
                                  </span>
                                  <span className="text-sm font-medium text-gray-700 truncate">{t.submitted_by}</span>
                                </span>
                              ) : (
                                <span className="text-sm text-gray-500">{channel === 'sms' ? 'VILPOWER Sync' : 'Karix Sync'}</span>
                              )}
                            </td>

                            {channel === 'whatsapp' && (
                              <td className="px-4 py-3">
                                {t.source_file ? (
                                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-gray-50 border border-gray-200 text-xs font-mono text-gray-600 max-w-[150px] truncate" title={t.source_file}>
                                    {truncate(t.source_file, 20)}
                                  </span>
                                ) : (
                                  <span className="text-sm text-gray-400">—</span>
                                )}
                              </td>
                            )}

                            <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                              {formatDate(t.submitted_at)}
                            </td>

                            <td className="px-4 py-3 text-right font-medium whitespace-nowrap">
                              <div className="flex items-center justify-end gap-2" onClick={(e) => e.stopPropagation()}>
                                {channel === 'rcs' && (
                                  <button
                                    type="button"
                                    onClick={() => handleSyncSingleRcsToMoEngage(t)}
                                    disabled={syncBusy || !syncDestinationReady}
                                    className={`px-2.5 py-1.5 rounded-lg text-sm font-medium border transition-colors flex items-center gap-1 cursor-pointer ${
                                      syncedSingleRcs[t.template_name]
                                        ? 'bg-emerald-50 text-emerald-700 border-emerald-300'
                                        : 'bg-white hover:bg-gray-50 text-gray-700 border-gray-200'
                                    }`}
                                    title={`Sync this template to ${syncDestinationLabel}`}
                                  >
                                    {syncingSingleRcs[t.template_name]
                                      ? 'Syncing...'
                                      : syncedSingleRcs[t.template_name]
                                      ? `Synced to ${syncDestinationLabel}`
                                      : `Sync to ${syncDestinationLabel}`}
                                  </button>
                                )}
                                <button
                                  type="button"
                                  className="rounded px-2 py-1.5 text-sm font-medium text-blue-700 hover:bg-blue-50"
                                  onClick={() => toggleRow(key)}
                                  aria-expanded={isExpanded}
                                  aria-label={`${isExpanded ? 'Hide' : 'Show'} details for ${t.template_name}`}
                                >
                                  {isExpanded ? 'Hide' : 'Details'}
                                </button>
                              </div>
                            </td>
                          </tr>
                          {/* Expandable detail panel */}
                          {isExpanded && (
                            <tr className="bg-gray-50/90 border-b border-gray-200">
                              <td colSpan={channel === 'whatsapp' ? 9 : channel === 'rcs' ? 8 : 7} className="px-6 py-4">
                                <div className="space-y-3">
                                  <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4 text-sm break-words">
                                    <div>
                                      <span className="font-medium text-gray-500">Template ID: </span>
                                      <span className="font-mono text-gray-800">
                                        {channel === 'whatsapp' ? (t.provider_ref_id || '—') : (t.template_id || t.provider_ref_id || '—')}
                                      </span>
                                    </div>
                                    <div>
                                      <span className="font-medium text-gray-500">Operator: </span>
                                      <span className="text-gray-800">{t.submitted_by || (channel === 'sms' ? 'VILPOWER Sync' : 'Karix Sync')}</span>
                                    </div>
                                    <div>
                                      <span className="font-medium text-gray-500">Source File: </span>
                                      <span className="font-mono text-gray-800">{t.source_file || '—'}</span>
                                    </div>
                                    <div>
                                      <span className="font-medium text-gray-500">Record: </span>
                                      <LiveBadge live={t.live} existsOnWaba={t.exists_on_waba} channel={channel} />
                                    </div>
                                  </div>

                                  {pipelineError && (
                                    <div className="p-2.5 bg-red-50 border border-red-200 rounded text-red-700 text-xs">
                                      <span className="font-medium">Pipeline Error: </span>
                                      {pipelineError}
                                    </div>
                                  )}

                                  {rejectionReason && (
                                    <div className="p-2.5 bg-amber-50 border border-amber-200 rounded text-amber-800 text-xs">
                                      <span className="font-medium">Meta Rejection Reason: </span>
                                      {rejectionReason}
                                    </div>
                                  )}

                                  {t.provider_response && Object.keys(t.provider_response).length > 0 && (
                                    <div>
                                      <div className="text-xs font-medium text-gray-500 mb-1">
                                        Raw provider response
                                      </div>
                                      <pre className="bg-gray-900 text-gray-100 p-3 rounded-lg text-xs font-mono overflow-x-auto max-h-48">
                                        {JSON.stringify(t.provider_response, null, 2)}
                                      </pre>
                                    </div>
                                  )}
                                  {channel === 'rcs' && (
                                    <div className="pt-3 mt-2 border-t border-gray-200/80 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                                      <div className="text-sm text-gray-500">
                                        Register this approved Karix RCS template into MoEngage Settings &rarr; RCS Template Management.
                                      </div>
                                      <button
                                        type="button"
                                        onClick={(e) => {
                                          e.stopPropagation();
                                          handleSyncSingleRcsToMoEngage(t);
                                        }}
                                        disabled={syncBusy || !syncDestinationReady}
                                        className={`px-3 py-1.5 rounded-lg text-xs font-semibold border transition flex items-center gap-1.5 cursor-pointer self-start sm:self-auto ${
                                          syncedSingleRcs[t.template_name]
                                            ? 'bg-emerald-50 text-emerald-700 border-emerald-300'
                                            : 'bg-purple-50 hover:bg-purple-100 text-purple-700 border-purple-300'
                                        }`}
                                      >
                                        {syncingSingleRcs[t.template_name] ? (
                                          <>
                                            <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24" fill="none">
                                              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                                              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                                            </svg>
                                            <span>Syncing to {syncDestinationLabel}...</span>
                                          </>
                                        ) : syncedSingleRcs[t.template_name] ? (
                                          <span>In {syncDestinationLabel}</span>
                                        ) : (
                                          <>
                                            <span>Sync to {syncDestinationLabel}</span>
                                          </>
                                        )}
                                      </button>
                                    </div>
                                  )}
                                </div>
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </section>

        {/* Right rail: live team activity */}
        <aside className="min-w-0 space-y-4" aria-label="Workspace activity">
          {activityError && <p role="alert" className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800">{activityError}{activityStats ? ' · Showing last available activity.' : ''}</p>}
          <section className="workspace-panel p-5">
            <div className="flex flex-wrap items-baseline justify-between gap-2 mb-1">
              <h2 className="text-base font-medium text-gray-900">Team activity</h2>
              <span className="text-xs text-gray-500">{activityStats ? `${activityStats.total_users} operators` : '—'}</span>
            </div>
            <p className="mb-4 text-xs text-gray-500">Across workspace accounts and channels</p>
            {activityStats && activityStats.user_activity.length > 0 ? (
              <div className="space-y-3">
                {activityStats.user_activity.slice(0, 4).map(u => (
                  <div key={u.user} className="flex items-center gap-2.5">
                    <span className="w-6 h-6 rounded bg-gray-100 text-gray-600 font-medium text-xs flex items-center justify-center shrink-0">
                      {u.user.charAt(0).toUpperCase()}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <span className="text-sm font-medium text-gray-900 truncate">{u.user}</span>
                        <span className="ml-2 text-xs text-gray-500 whitespace-nowrap">{u.actions} action{u.actions === 1 ? '' : 's'}</span>
                      </div>
                      <div className="h-1 bg-gray-100 rounded-full mt-1">
                        <div
                          className="h-1 bg-gray-400 rounded-full"
                          style={{ width: `${Math.min(100, (u.actions / Math.max(1, activityStats.total_actions)) * 100)}%` }}
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-500">{activityLoading ? 'Loading team activity…' : activityError ? 'Team activity is unavailable.' : 'No team activity recorded yet.'}</p>
            )}
          </section>

          {/* Recent activity feed */}
          <section className="workspace-panel p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-base font-medium text-gray-900">Recent activity</h2>
              <a href="/activity" className="text-sm font-medium text-blue-700 hover:underline">
                View all →
              </a>
            </div>
            {activities.length > 0 ? (
              <div className="space-y-3">
                {activities.map(a => (
                  <div key={a.id} className="flex items-start gap-2.5">
                    <ActivityIcon action={a.action} />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm leading-relaxed text-gray-800">
                        <span className="font-medium">{a.user}</span>{' '}
                        {a.action === 'TEMPLATE_SUBMISSION' && (a.details.count == null ? <>submitted templates</> : <>submitted {a.details.count} template{a.details.count === 1 ? '' : 's'}</>)}
                        {a.action === 'TEMPLATE_PREVIEW' && <>previewed {a.details.filename || 'a file'}</>}
                        {a.action === 'STATUS_POLL' && (a.details.checked_count == null ? <>polled pending templates</> : <>polled {a.details.checked_count} pending</>)}
                        {a.action === 'CREDENTIALS_UPDATE' && <>updated credentials</>}
                        {a.action === 'CREDENTIALS_TEST' && <>tested credentials</>}
                      </p>
                      <p className="text-xs text-gray-500 mt-1">
                        {getAccountLabel(a.account)} • {formatChannel(a.channel)} • {relativeTime(a.timestamp)}
                      </p>
                    </div>
                    <span className={`w-1.5 h-1.5 rounded-full mt-1 shrink-0 ${a.status === 'success' ? 'bg-emerald-500' : 'bg-red-500'}`} />
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-gray-500">{activityLoading ? 'Loading recent activity…' : activityError ? 'Recent activity is unavailable.' : 'No recent activity recorded.'}</p>
            )}
          </section>
        </aside>
      </div>
      {/* Delete from Spreadsheet Modal */}
      {showFileDeleteModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-gray-900/60 backdrop-blur-xs">
          <div role="dialog" aria-modal="true" aria-labelledby="file-delete-heading" className="bg-white rounded-xl border border-gray-200 shadow-xl max-w-lg w-full max-h-[90vh] overflow-y-auto p-6 space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-gray-100">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-red-50 text-red-600 flex items-center justify-center">
                  <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor">
                    <path fillRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                </div>
                <div>
                  <h3 id="file-delete-heading" className="text-base font-medium text-gray-900">Delete templates from spreadsheet</h3>
                  <p className="text-sm text-gray-500">Target account: <span className="font-medium text-gray-800">{accountLabel}</span> · {channelLabel}</p>
                </div>
              </div>
              <button
                onClick={() => { setShowFileDeleteModal(false); setDeleteFile(null); }}
                className="text-gray-400 hover:text-gray-600 text-lg leading-none cursor-pointer"
                disabled={fileDeleting}
                aria-label="Close delete dialog"
              >
                &times;
              </button>
            </div>

            <div className="space-y-4 text-sm">
              <p className="text-gray-600 leading-relaxed">
                Upload the spreadsheet (<strong>.csv</strong>, <strong>.xlsx</strong>, or <strong>.xls</strong>) containing the templates you want to delete. The system will parse every template name from the file and delete only those from Karix/Meta.
              </p>

              <div className="border-2 border-dashed border-gray-300 rounded-xl p-6 text-center hover:border-red-400 transition-colors bg-gray-50/50">
                <input
                  type="file"
                  id="delete-file-input"
                  accept=".csv,.xlsx,.xls"
                  onChange={e => {
                    if (e.target.files && e.target.files[0]) {
                      setDeleteFile(e.target.files[0]);
                    }
                  }}
                  className="peer sr-only"
                  disabled={fileDeleting}
                />
                <label htmlFor="delete-file-input" className="cursor-pointer block space-y-2 rounded-lg peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-blue-500">
                  <div className="w-10 h-10 mx-auto rounded-full bg-red-50 text-red-500 flex items-center justify-center">
                    <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor">
                      <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zM6.293 6.707a1 1 0 010-1.414l3-3a1 1 0 011.414 0l3 3a1 1 0 01-1.414 1.414L11 5.414V13a1 1 0 11-2 0V5.414L7.707 6.707a1 1 0 01-1.414 0z" clipRule="evenodd" />
                    </svg>
                  </div>
                  {deleteFile ? (
                    <div>
                      <span className="font-medium text-gray-900 font-mono text-sm break-all">{deleteFile.name}</span>
                      <p className="text-xs text-gray-500 mt-1">{(deleteFile.size / 1024).toFixed(1)} KB — Click to change file</p>
                    </div>
                  ) : (
                    <div>
                      <span className="font-medium text-blue-600 hover:underline">Choose a file</span>
                      <p className="text-xs text-gray-500 mt-1">CSV or Excel (.xlsx, .xls)</p>
                    </div>
                  )}
                </label>
              </div>

              <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-amber-900 text-sm leading-relaxed">
                <strong>Warning:</strong> This will permanently delete all templates defined in this file from your active WABA on Karix and Meta.
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-gray-100">
              <button
                type="button"
                onClick={() => { setShowFileDeleteModal(false); setDeleteFile(null); }}
                disabled={fileDeleting}
                className="px-4 py-2 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-100 transition-colors cursor-pointer"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleDeleteFromFile}
                disabled={!deleteFile || fileDeleting}
                className="inline-flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium text-white bg-red-600 hover:bg-red-700 transition-colors cursor-pointer disabled:opacity-50"
              >
                {fileDeleting ? (
                  <>
                    <svg className="animate-spin h-3.5 w-3.5 text-white" viewBox="0 0 24 24" fill="none">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                    </svg>
                    Deleting from WABA...
                  </>
                ) : (
                  'Delete Templates from File'
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
