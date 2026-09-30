'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import Link from 'next/link';
import { useApp } from '@/lib/context';
import {
  fetchJiraProjects,
  fetchJiraIssues,
  fetchJiraBrief,
  submitJiraBrief,
  syncRcsTemplateToMoEngage,
  getJiraCreativeDownloadUrl,
  uploadJiraCreative,
  updateCredentials,
  type JiraProjectItem,
  type JiraIssueItem,
  type JiraBriefData,
  type JiraWhatsAppDraft,
  type JiraRcsDraft,
} from '@/lib/api';
import { formatError, formatDate } from '@/lib/format';

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
    colorClass = 'bg-blue-50 text-blue-800 border-blue-200';
    dotColor = 'bg-blue-500 animate-pulse';
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
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold border shrink-0 ${colorClass}`}>
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${dotColor}`} />
      <span>{label}</span>
    </span>
  );
}
export default function JiraBriefsPage() {
  const { user, accounts, getAccountLabel } = useApp();
  const [issues, setIssues] = useState<JiraIssueItem[]>([]);
  const [loadingIssues, setLoadingIssues] = useState(true);
  const [projectsList, setProjectsList] = useState<JiraProjectItem[]>([
    { key: 'ALL', name: 'All Tata Projects Combined' },
    { key: 'TCN', name: 'Tata Capital New' },
    { key: 'SWCM', name: 'TATA Service and wealth Campaign Manager' },
    { key: 'TM', name: 'Tata Moneyfy' },
    { key: 'TAT', name: 'Tata Capital Marketing' },
    { key: 'MON', name: 'Moneyfy Mobile' },
    { key: 'COL', name: 'Collections & Operations' },
  ]);
  const [project, setProject] = useState<string>('ALL');
  const [selectedKey, setSelectedKey] = useState<string>('');
  const [brief, setBrief] = useState<JiraBriefData | null>(null);
  const [loadingBrief, setLoadingBrief] = useState(false);
  const [campaignTypeFilter, setCampaignTypeFilter] = useState<'all' | 'messaging' | 'email'>('all');
  const [briefStatusFilter, setBriefStatusFilter] = useState<'all' | 'pending' | 'in_progress' | 'completed' | 'failed' | 'not_generated'>('all');
  const [activeTab, setActiveTab] = useState<'whatsapp' | 'rcs' | 'sms' | 'email' | 'comments' | 'moengage'>('whatsapp');
  const [submitting, setSubmitting] = useState(false);
  const [confirmationMode, setConfirmationMode] = useState<'all' | 'whatsapp' | 'rcs' | null>(null);
  const [feedback, setFeedback] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Editable template drafts and selection sets
  const [waTemplates, setWaTemplates] = useState<JiraWhatsAppDraft[]>([]);
  const [rcsTemplates, setRcsTemplates] = useState<JiraRcsDraft[]>([]);
  const [selectedWa, setSelectedWa] = useState<Set<number>>(new Set());
  const [selectedRcs, setSelectedRcs] = useState<Set<number>>(new Set());
  const [syncingRcs, setSyncingRcs] = useState<Record<string, boolean>>({});
  const [syncedRcs, setSyncedRcs] = useState<Record<string, string>>({});
  const [editingCard, setEditingCard] = useState<Record<string, boolean>>({});
  const [targetAccount, setTargetAccount] = useState<string>('tcl_promo');
  const [autoSyncRcsToMoEngage, setAutoSyncRcsToMoEngage] = useState<boolean>(true);
  const [showSessionModal, setShowSessionModal] = useState<boolean>(false);
  const [quickBearerToken, setQuickBearerToken] = useState<string>('');
  const [quickSessionId, setQuickSessionId] = useState<string>('');
  const [quickLoungeCookie, setQuickLoungeCookie] = useState<string>('');
  const [savingQuickSession, setSavingQuickSession] = useState<boolean>(false);
  const activeRequestKey = useRef<string>('');
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

  const loadBrief = useCallback(async (key: string) => {
    if (!key) return;
    const cleanKey = key.trim().toUpperCase();
    activeRequestKey.current = cleanKey;
    try {
      setLoadingBrief(true);
      setFeedback(null);
      const data = await fetchJiraBrief(cleanKey);
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
      const waList = data.whatsapp_templates || [];
      const rcsList = data.rcs_templates || [];
      setWaTemplates(waList);
      setRcsTemplates(rcsList);
      setSelectedWa(new Set(waList.map((_, idx) => idx)));
      setSelectedRcs(new Set(rcsList.map((_, idx) => idx)));
      setEditingCard({});
      const initialAcc = data.account === 'wealth' ? 'tcl_promo' : (data.account || 'tcl_promo');
      setTargetAccount(initialAcc);
      if (data.is_email_campaign) {
        setActiveTab('email');
      } else if (waList.length > 0) {
        setActiveTab('whatsapp');
      } else if (rcsList.length > 0) {
        setActiveTab('rcs');
      } else if (data.sms_templates?.length > 0) {
        setActiveTab('sms');
      } else {
        setActiveTab('moengage');
      }
    } catch (err) {
      if (activeRequestKey.current === cleanKey) {
        setFeedback({ message: `Failed to load brief for ${key}: ${formatError(err)}`, type: 'error' });
      }
    } finally {
      if (activeRequestKey.current === cleanKey) {
        setLoadingBrief(false);
      }
    }
  }, []);

  useEffect(() => {
    if (selectedKey) {
      loadBrief(selectedKey);
    }
  }, [selectedKey, loadBrief]);

  // Submission handler with selective channel filtering
  const handleSubmitChannel = async (channelMode: 'all' | 'whatsapp' | 'rcs') => {
    if (!brief) return;
    try {
      setSubmitting(true);
      setFeedback(null);

      const submitChannels: string[] = [];
      let waToSubmit: JiraWhatsAppDraft[] = [];
      let rcsToSubmit: JiraRcsDraft[] = [];

      if (channelMode === 'all' || channelMode === 'whatsapp') {
        waToSubmit = waTemplates.filter((_, idx) => selectedWa.has(idx));
        if (waToSubmit.length > 0) submitChannels.push('whatsapp');
      }

      if (channelMode === 'all' || channelMode === 'rcs') {
        rcsToSubmit = rcsTemplates.filter((_, idx) => selectedRcs.has(idx));
        if (rcsToSubmit.length > 0) submitChannels.push('rcs');
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
        targetAccount
      );

      const waCount = res.whatsapp_submitted?.length || 0;
      const rcsCount = res.rcs_submitted?.length || 0;

      if (autoSyncRcsToMoEngage && rcsToSubmit.length > 0) {
        for (const rcsItem of rcsToSubmit) {
          try {
            const syncRes = await syncRcsTemplateToMoEngage({
              template_name: rcsItem.template_name,
              template_id: rcsItem.template_name,
              card_title: rcsItem.card_title || brief.summary || 'Tata Capital Offer',
              card_description: rcsItem.body,
              cta_text: rcsItem.action_label || 'Explore Now',
              cta_url: rcsItem.action_url || 'https://u3.mnge.co/',
            });
            setSyncedRcs((prev) => ({ ...prev, [rcsItem.template_name]: syncRes.moengage_id }));
          } catch {}
        }
      }

      setFeedback({
        message: `Successfully submitted ${waCount} WhatsApp and ${rcsCount} RCS templates for ${brief.issue_key}${autoSyncRcsToMoEngage && rcsCount > 0 ? ' (and synced RCS to MoEngage)' : ''}.`,
        type: 'success',
      });
      loadBrief(brief.issue_key);
    } catch (err) {
      const errMsg = formatError(err);
      setFeedback({ message: errMsg, type: 'error' });
      if (/session|cookie|bearer|401|expired|unauthorized/i.test(errMsg)) {
        setShowSessionModal(true);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const requestWhitelist = (channelMode: 'all' | 'whatsapp' | 'rcs') => {
    const count = channelMode === 'whatsapp'
      ? selectedWa.size
      : channelMode === 'rcs'
      ? selectedRcs.size
      : selectedWa.size + selectedRcs.size;
    if (count === 0) {
      setFeedback({ message: 'Please select at least one template to whitelist.', type: 'error' });
      return;
    }
    setConfirmationMode(channelMode);
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

  const updateWaField = <K extends keyof JiraWhatsAppDraft>(idx: number, field: K, val: JiraWhatsAppDraft[K]) => {
    setWaTemplates((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], [field]: val };
      return next;
    });
  };

  const updateRcsField = <K extends keyof JiraRcsDraft>(idx: number, field: K, val: JiraRcsDraft[K]) => {
    setRcsTemplates((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], [field]: val };
      return next;
    });
  };

  const toggleSelectWa = (idx: number) => {
    setSelectedWa((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const toggleSelectRcs = (idx: number) => {
    setSelectedRcs((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });
  };

  const selectAllWa = (select: boolean) => {
    setSelectedWa(select ? new Set(waTemplates.map((_, idx) => idx)) : new Set());
  };

  const selectAllRcs = (select: boolean) => {
    setSelectedRcs(select ? new Set(rcsTemplates.map((_, idx) => idx)) : new Set());
  };
  const [uploadingCreative, setUploadingCreative] = useState<Record<string, boolean>>({});

  const handleReplaceWaCreative = async (idx: number, file: File) => {
    const key = `wa_${idx}`;
    try {
      setUploadingCreative((prev) => ({ ...prev, [key]: true }));
      const res = await uploadJiraCreative(file);
      setWaTemplates((prev) =>
        prev.map((w, i) =>
          i === idx
            ? {
                ...w,
                header_type: 'IMAGE',
                media_file: res.local_path,
                media_filename: res.filename,
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
    try {
      setUploadingCreative((prev) => ({ ...prev, [key]: true }));
      const res = await uploadJiraCreative(file);
      setRcsTemplates((prev) =>
        prev.map((r, i) =>
          i === idx
            ? {
                ...r,
                media_file: res.local_path,
                media_filename: res.filename,
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
  const handleSyncRcsToMoEngage = async (rcs: JiraRcsDraft) => {
    try {
      setSyncingRcs((prev) => ({ ...prev, [rcs.template_name]: true }));
      const res = await syncRcsTemplateToMoEngage({
        template_name: rcs.template_name,
        template_id: rcs.template_name,
        card_title: rcs.card_title || brief?.summary || 'Tata Capital Offer',
        card_description: rcs.body,
        cta_text: rcs.action_label || 'Explore Now',
        cta_url: rcs.action_url || 'https://u3.mnge.co/',
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

  const emailCount = issues.filter((i) => i.is_email).length;
  const messagingCount = issues.length - emailCount;

  const statusCounts = {
    all: issues.length,
    pending: issues.filter((i) => (i.brief_status || 'Pending').toLowerCase().trim() === 'pending').length,
    in_progress: issues.filter((i) => (i.brief_status || '').toLowerCase().trim() === 'in progress').length,
    completed: issues.filter((i) => (i.brief_status || '').toLowerCase().trim() === 'completed').length,
    failed: issues.filter((i) => (i.brief_status || '').toLowerCase().trim() === 'failed').length,
    not_generated: issues.filter((i) => (i.brief_status || '').toLowerCase().trim() === 'not generated').length,
  };

  const filteredIssues = issues.filter((i) => {
    if (campaignTypeFilter === 'messaging' && i.is_email) return false;
    if (campaignTypeFilter === 'email' && !i.is_email) return false;

    if (briefStatusFilter !== 'all') {
      const bStatus = (i.brief_status || 'Pending').toLowerCase().replace(/\s+/g, '_');
      if (bStatus !== briefStatusFilter) return false;
    }

    return (
      i.key.toLowerCase().includes(searchQuery.toLowerCase()) ||
      i.summary.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (i.assignee || '').toLowerCase().includes(searchQuery.toLowerCase())
    );
  });
  const totalSelectedCount = selectedWa.size + selectedRcs.size;

  return (
    <>
      <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-gray-200">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">Jira Campaign Briefing Agent</h1>
            <select
              value={project}
              onChange={(e) => {
                const newP = e.target.value;
                setProject(newP);
                setSelectedKey('');
                setBrief(null);
                if (typeof window !== 'undefined') {
                  localStorage.setItem('briefs_project', newP);
                }
              }}
              className="text-xs font-semibold bg-white border border-blue-200 text-blue-700 rounded-lg px-2.5 py-1.5 outline-none focus:ring-2 focus:ring-blue-500 cursor-pointer"
              aria-label="Jira project"
            >
              {projectsList.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.key} — {p.name}
                </option>
              ))}
            </select>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
              tatacapital-team.atlassian.net
            </span>
          </div>
          <p className="text-sm text-gray-500 mt-1">
            Automated multi-channel intake: review, manually edit, and selectively submit WhatsApp or RCS templates to Karix.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex items-center p-1 bg-gray-100 rounded-lg border border-gray-200 text-xs font-semibold">
            <span className="px-2.5 py-1 rounded-md bg-white text-blue-700 shadow-2xs font-bold">
              📋 Jira Ticket Queue
            </span>
            <Link
              href="/submit"
              className="px-2.5 py-1 rounded-md text-gray-600 hover:text-gray-900 transition"
            >
              📤 File / Paste Upload
            </Link>
            <Link
              href="/"
              className="px-2.5 py-1 rounded-md text-gray-600 hover:text-gray-900 transition"
            >
              ✅ Live Inventory
            </Link>
          </div>
          <button
            onClick={() => setShowSessionModal(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-amber-800 bg-amber-50 hover:bg-amber-100 border border-amber-200 shadow-2xs transition"
            title="Paste fresh Karix Portal or Lounge session cookie without leaving this page"
          >
            🔑 Quick Session Paste
          </button>
          <button
            onClick={() => loadIssues()}
            disabled={loadingIssues}
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold text-gray-700 bg-white hover:bg-gray-50 border border-gray-200 shadow-2xs transition disabled:opacity-50"
          >
            🔄 Refresh
          </button>
        </div>
      </div>

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
            <span>{feedback.type === 'success' ? '✅' : '⚠️'}</span>
            <span>{feedback.message}</span>
          </div>
          <button onClick={() => setFeedback(null)} className="text-gray-400 hover:text-gray-600">
            ✕
          </button>
        </div>
      )}

      {/* Main Grid: Ticket Selector (Left) + Brief Inspector (Right) */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Jira Issues List */}
        <div className="lg:col-span-4 bg-white rounded-xl border border-gray-200/80 shadow-2xs p-4 space-y-3">
          <div className="flex items-center justify-between pb-2 border-b border-gray-100">
            <h2 className="text-xs font-bold text-gray-900 uppercase tracking-wider">Active Jira Briefs</h2>
            <span className="text-[11px] text-gray-400 font-medium font-mono">{issues.length} tickets</span>
          </div>

          {/* Segmented Campaign Filter Pills */}
          <div className="flex items-center gap-1 p-1 bg-gray-100 rounded-lg text-xs font-semibold">
            <button
              onClick={() => setCampaignTypeFilter('all')}
              className={`flex-1 py-1 px-1.5 rounded-md transition text-center text-[11px] ${
                campaignTypeFilter === 'all'
                  ? 'bg-white text-gray-900 shadow-2xs font-bold'
                  : 'text-gray-500 hover:text-gray-900'
              }`}
            >
              All ({issues.length})
            </button>
            <button
              onClick={() => setCampaignTypeFilter('messaging')}
              className={`flex-1 py-1 px-1.5 rounded-md transition text-center text-[11px] ${
                campaignTypeFilter === 'messaging'
                  ? 'bg-white text-emerald-700 shadow-2xs font-bold'
                  : 'text-gray-500 hover:text-gray-900'
              }`}
            >
              🟢 Messaging ({messagingCount})
            </button>
            <button
              onClick={() => setCampaignTypeFilter('email')}
              className={`flex-1 py-1 px-1.5 rounded-md transition text-center text-[11px] ${
                campaignTypeFilter === 'email'
                  ? 'bg-white text-purple-700 shadow-2xs font-bold'
                  : 'text-gray-500 hover:text-gray-900'
              }`}
            >
              📧 Email ({emailCount})
            </button>
          </div>
          {/* Jira Brief Status Filter */}
          <div className="space-y-1.5 pt-1 border-t border-gray-100">
            <div className="flex items-center justify-between text-[11px] font-bold text-gray-500 uppercase tracking-wider">
              <span>Jira Brief Status</span>
              {briefStatusFilter !== 'all' && (
                <button
                  type="button"
                  onClick={() => setBriefStatusFilter('all')}
                  className="text-blue-600 hover:text-blue-800 text-[10px] font-semibold cursor-pointer"
                >
                  Reset
                </button>
              )}
            </div>
            <div className="flex flex-wrap gap-1">
              {[
                { id: 'all', label: 'All', count: statusCounts.all },
                { id: 'pending', label: '🟡 Pending', count: statusCounts.pending },
                { id: 'in_progress', label: '🔵 In Progress', count: statusCounts.in_progress },
                { id: 'completed', label: '🟢 Completed', count: statusCounts.completed },
                { id: 'failed', label: '🔴 Failed', count: statusCounts.failed },
                { id: 'not_generated', label: '⚪ Not Generated', count: statusCounts.not_generated },
              ].map((tab) => {
                const active = briefStatusFilter === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    onClick={() => setBriefStatusFilter(tab.id as typeof briefStatusFilter)}
                    className={`px-2 py-1 rounded-md text-[10px] font-semibold transition border flex items-center gap-1 cursor-pointer ${
                      active
                        ? 'bg-blue-600 text-white border-blue-600 shadow-2xs font-bold'
                        : 'bg-gray-50 hover:bg-gray-100 text-gray-600 border-gray-200'
                    }`}
                  >
                    <span>{tab.label}</span>
                    <span
                      className={`px-1 py-0.2 rounded-full text-[9px] font-bold ${
                        active ? 'bg-white/20 text-white' : 'bg-gray-200/80 text-gray-700'
                      }`}
                    >
                      {tab.count}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
          <input
            type="text"
            placeholder="Search key, title, assignee..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full text-xs px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
          />

          <div className="space-y-2 max-h-[640px] overflow-y-auto pr-1">
            {loadingIssues && issues.length === 0 ? (
              <div className="py-12 text-center text-xs text-gray-400">Loading Jira queue...</div>
            ) : filteredIssues.length === 0 && !selectedKey ? (
              <div className="py-12 text-center text-xs text-gray-400">No matching Jira tickets found.</div>
            ) : (
              (() => {
                const isSelectedInList = filteredIssues.some((i) => i.key === selectedKey);
                const displayIssues = [...filteredIssues];
                if (selectedKey && !isSelectedInList && brief && (brief.issue_key === selectedKey || selectedKey.endsWith(brief.issue_key.split('-')[1] || ''))) {
                  displayIssues.unshift({
                    key: brief.issue_key,
                    id: brief.issue_key,
                    summary: brief.summary,
                    status: brief.status || 'In Progress',
                    assignee: brief.assignee || 'Unassigned',
                    reporter: brief.reporter || 'Anonymous',
                    attachment_count: brief.attachments_mapped?.length || 0,
                    attachments: [],
                    is_email: brief.is_email_campaign,
                  });
                }
                return displayIssues.map((issue) => {
                  const isSelected = issue.key === selectedKey;
                  return (
                    <button
                      key={issue.key}
                      onClick={() => handleSelectIssue(issue.key)}
                      className={`w-full text-left p-3 rounded-lg border transition text-xs space-y-1.5 ${
                        isSelected
                          ? 'bg-blue-50/80 border-blue-300 ring-1 ring-blue-400/40 shadow-xs'
                          : 'bg-white border-gray-200 hover:bg-gray-50/80'
                      }`}
                    >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        <span className="font-bold font-mono text-blue-700">{issue.key}</span>
                        {issue.is_email ? (
                          <span className="text-[9px] px-1.5 py-0.2 rounded font-semibold bg-purple-50 text-purple-700 border border-purple-200">
                            📧 Email
                          </span>
                        ) : (
                          <span className="text-[9px] px-1.5 py-0.2 rounded font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                            🟢 WA/RCS
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-1">
                        <span className="text-[10px] px-1.5 py-0.2 rounded font-semibold bg-gray-100 text-gray-600">
                          {issue.status}
                        </span>
                        <BriefStatusBadge status={issue.brief_status} />
                      </div>
                    </div>
                    <p className="font-semibold text-gray-800 line-clamp-2 leading-snug">{issue.summary}</p>
                    <div className="flex items-center justify-between text-[10px] text-gray-400 pt-1">
                      <span>👤 {issue.assignee}</span>
                      <span>📎 {issue.attachment_count} creatives</span>
                    </div>
                    {/* Channel-Wise Campaign Breakdown */}
                    {(() => {
                      const counts = (isSelected && brief?.channel_counts) ? brief.channel_counts : issue.channel_counts;
                      if (!counts || counts.total === 0) return null;
                      return (
                        <div className="flex flex-wrap items-center gap-1 pt-1.5 border-t border-gray-100">
                          {counts.whatsapp > 0 && (
                            <span className="inline-flex items-center gap-0.5 text-[9px] font-bold px-1.5 py-0.2 rounded bg-emerald-50 text-emerald-700 border border-emerald-200" title={`${counts.whatsapp} WhatsApp campaign(s)`}>
                              <span>WA:</span>
                              <span className="font-extrabold">{counts.whatsapp}</span>
                            </span>
                          )}
                          {counts.rcs > 0 && (
                            <span className="inline-flex items-center gap-0.5 text-[9px] font-bold px-1.5 py-0.2 rounded bg-blue-50 text-blue-700 border border-blue-200" title={`${counts.rcs} RCS campaign(s)`}>
                              <span>RCS:</span>
                              <span className="font-extrabold">{counts.rcs}</span>
                            </span>
                          )}
                          {counts.sms > 0 && (
                            <span className="inline-flex items-center gap-0.5 text-[9px] font-bold px-1.5 py-0.2 rounded bg-purple-50 text-purple-700 border border-purple-200" title={`${counts.sms} SMS campaign(s)`}>
                              <span>SMS:</span>
                              <span className="font-extrabold">{counts.sms}</span>
                            </span>
                          )}
                          {counts.email > 0 && (
                            <span className="inline-flex items-center gap-0.5 text-[9px] font-bold px-1.5 py-0.2 rounded bg-amber-50 text-amber-800 border border-amber-200" title={`${counts.email} Email campaign(s)`}>
                              <span>Email:</span>
                              <span className="font-extrabold">{counts.email}</span>
                            </span>
                          )}
                          {counts.push > 0 && (
                            <span className="inline-flex items-center gap-0.5 text-[9px] font-bold px-1.5 py-0.2 rounded bg-indigo-50 text-indigo-700 border border-indigo-200" title="Push / MoEngage campaign">
                              <span>Push:</span>
                              <span className="font-extrabold">{counts.push}</span>
                            </span>
                          )}
                        </div>
                      );
                    })()}
                    </button>
                  );
                });
              })()
            )}
          </div>
        </div>

        {/* Right Column: Interactive Brief Inspector */}
        <div className="lg:col-span-8 space-y-4">
          {loadingBrief ? (
            <div className="bg-white rounded-xl border border-gray-200/80 shadow-2xs p-16 text-center text-xs text-gray-400 space-y-2">
              <div className="animate-spin text-xl">⏳</div>
              <p>Parsing Jira brief and downloading creative attachments...</p>
            </div>
          ) : !brief ? (
            <div className="bg-white rounded-xl border border-gray-200/80 shadow-2xs p-16 text-center text-xs text-gray-400">
              Select a Jira ticket from the left panel to inspect its campaign brief.
            </div>
          ) : (
            <div className="space-y-4">
              {/* Ticket Overview Card */}
              <div className="bg-white rounded-xl border border-gray-200/80 shadow-2xs p-5 space-y-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-bold font-mono text-blue-700 bg-blue-50 px-2 py-0.5 rounded border border-blue-200">
                        {brief.issue_key}
                      </span>
                      <h2 className="text-base font-bold text-gray-900">{brief.summary}</h2>
                      <BriefStatusBadge status={brief.brief_status} />
                    </div>
                    <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500">
                      <span>🏢 Sub-Account: <strong className="text-gray-800 uppercase">{brief.account}</strong></span>
                      <span>👤 Reporter: <strong>{brief.reporter}</strong></span>
                      <span>🛠️ Assignee: <strong>{brief.assignee}</strong></span>
                      {brief.duedate && <span>📅 Due Date: <strong>{formatDate(brief.duedate)}</strong></span>}
                    </div>
                    {/* Channel-Wise Campaign Count Summary Bar */}
                    <div className="p-3 bg-gradient-to-r from-gray-50 via-blue-50/20 to-indigo-50/15 rounded-xl border border-gray-200/90 space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <span className="text-xs font-bold text-gray-900 uppercase tracking-wide">
                            📊 Total Campaigns in Ticket:
                          </span>
                          <span className="px-2 py-0.5 rounded-full text-xs font-extrabold bg-blue-600 text-white shadow-2xs">
                            {brief.channel_counts?.total ?? (waTemplates.length + rcsTemplates.length + (brief.sms_templates?.length || 0) + (brief.email_templates?.length || 0) + (brief.channel_counts?.push ?? 0))}
                          </span>
                        </div>
                        <span className="text-[11px] text-gray-500 font-medium">Channel-wise Breakdown</span>
                      </div>

                      <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 pt-0.5">
                        {/* WhatsApp */}
                        <div className={`p-2 rounded-lg border text-center transition ${waTemplates.length > 0 ? 'bg-emerald-50/90 border-emerald-200 text-emerald-900 shadow-2xs' : 'bg-gray-50/40 border-gray-200/60 text-gray-400'}`}>
                          <div className="text-[10px] font-bold uppercase tracking-wider">🟢 WhatsApp</div>
                          <div className="text-base font-extrabold">{waTemplates.length}</div>
                          <div className="text-[9px] text-gray-500">{waTemplates.length === 1 ? 'template' : 'templates'}</div>
                        </div>

                        {/* RCS */}
                        <div className={`p-2 rounded-lg border text-center transition ${rcsTemplates.length > 0 ? 'bg-blue-50/90 border-blue-200 text-blue-900 shadow-2xs' : 'bg-gray-50/40 border-gray-200/60 text-gray-400'}`}>
                          <div className="text-[10px] font-bold uppercase tracking-wider">🔵 RCS (DLT)</div>
                          <div className="text-base font-extrabold">{rcsTemplates.length}</div>
                          <div className="text-[9px] text-gray-500">{rcsTemplates.length === 1 ? 'card' : 'cards'}</div>
                        </div>

                        {/* SMS */}
                        <div className={`p-2 rounded-lg border text-center transition ${(brief.sms_templates?.length || 0) > 0 ? 'bg-purple-50/90 border-purple-200 text-purple-900 shadow-2xs' : 'bg-gray-50/40 border-gray-200/60 text-gray-400'}`}>
                          <div className="text-[10px] font-bold uppercase tracking-wider">🟣 SMS (DLT)</div>
                          <div className="text-base font-extrabold">{brief.sms_templates?.length || 0}</div>
                          <div className="text-[9px] text-gray-500">{(brief.sms_templates?.length || 0) === 1 ? 'template' : 'templates'}</div>
                        </div>

                        {/* Email */}
                        <div className={`p-2 rounded-lg border text-center transition ${(brief.email_templates?.length || 0) > 0 ? 'bg-amber-50/90 border-amber-200 text-amber-900 shadow-2xs' : 'bg-gray-50/40 border-gray-200/60 text-gray-400'}`}>
                          <div className="text-[10px] font-bold uppercase tracking-wider">📧 Email</div>
                          <div className="text-base font-extrabold">{brief.email_templates?.length || 0}</div>
                          <div className="text-[9px] text-gray-500">{(brief.email_templates?.length || 0) === 1 ? 'campaign' : 'campaigns'}</div>
                        </div>

                        {/* Push / App is a channel count, not the presence of a MoEngage staging draft. */}
                        <div className={`p-2 rounded-lg border text-center transition ${(brief.channel_counts?.push ?? 0) > 0 ? 'bg-indigo-50/90 border-indigo-200 text-indigo-900 shadow-2xs' : 'bg-gray-50/40 border-gray-200/60 text-gray-400'}`}>
                          <div className="text-[10px] font-bold uppercase tracking-wider">📱 Push / App</div>
                          <div className="text-base font-extrabold">{brief.channel_counts?.push ?? 0}</div>
                          <div className="text-[9px] text-gray-500">campaign</div>
                        </div>
                      </div>
                    </div>
                  </div>
                    <div className="flex flex-wrap items-center gap-2 pt-1.5">
                      <span className="text-xs font-bold text-gray-700">🏢 Whitelist Under Account:</span>
                      <select
                        value={targetAccount}
                        onChange={(e) => setTargetAccount(e.target.value)}
                        className="text-xs font-bold bg-white border border-blue-300 text-blue-900 rounded-lg px-2.5 py-1 shadow-2xs focus:ring-2 focus:ring-blue-500 cursor-pointer"
                        aria-label="Target Account for Karix Whitelisting"
                      >
                        {accounts.map((acc) => (
                          <option key={acc.id} value={acc.id}>
                            {acc.name} ({acc.id.toUpperCase()})
                          </option>
                        ))}
                      </select>
                      <span className="text-[11px] text-gray-400">
                        (Templates & WABA approvals will be registered on Karix under this account)
                      </span>
                    </div>

                  {/* Selective Submission Action Controls */}
                  <div className="flex flex-wrap items-center gap-2">
                    {brief.is_email_campaign ? (
                      <span className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-purple-50 text-purple-800 border border-purple-200 shadow-2xs">
                        <span>📧</span>
                        <span>Direct ESP / MoEngage Deployment (No Karix Whitelisting Needed)</span>
                      </span>
                    ) : (
                      <>
                        {waTemplates.length > 0 && (
                          <button
                            onClick={() => requestWhitelist('whatsapp')}
                            disabled={submitting || selectedWa.size === 0}
                            className="px-3 py-2 bg-emerald-600 hover:bg-emerald-700 disabled:bg-emerald-300 text-white text-xs font-semibold rounded-lg shadow-2xs transition flex items-center gap-1.5"
                            title="Submit only the checked WhatsApp templates"
                          >
                            <span>🟢 Whitelist WhatsApp Only</span>
                            <span className="bg-emerald-500 px-1.5 py-0.2 rounded text-[10px]">
                              {selectedWa.size}
                            </span>
                          </button>
                        )}

                        {rcsTemplates.length > 0 && (
                          <button
                            onClick={() => requestWhitelist('rcs')}
                            disabled={submitting || selectedRcs.size === 0}
                            className="px-3 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-xs font-semibold rounded-lg shadow-2xs transition flex items-center gap-1.5"
                            title="Submit only the checked RCS templates"
                          >
                            <span>🔵 Whitelist RCS Only</span>
                            <span className="bg-blue-500 px-1.5 py-0.2 rounded text-[10px]">
                              {selectedRcs.size}
                            </span>
                          </button>
                        )}

                        <button
                          onClick={() => requestWhitelist('all')}
                          disabled={submitting || totalSelectedCount === 0}
                          className="px-4 py-2 bg-gray-900 hover:bg-black disabled:bg-gray-400 text-white text-xs font-semibold rounded-lg shadow-sm transition flex items-center gap-2"
                        >
                          {submitting ? (
                            <>
                              <span className="w-2.5 h-2.5 rounded-full bg-white animate-pulse" />
                              <span>Submitting...</span>
                            </>
                          ) : (
                            <>
                              <span>🚀 Whitelist All Selected</span>
                              <span className="bg-gray-800 px-1.5 py-0.2 rounded text-[10px]">
                                {totalSelectedCount}
                              </span>
                            </>
                          )}
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {/* Creatives Attachment Strip */}
                {brief.attachments_mapped.length > 0 && (
                  <div className="pt-3 border-t border-gray-100 flex items-center gap-2 overflow-x-auto">
                    <span className="text-[11px] font-semibold text-gray-500 uppercase shrink-0">Creatives Mapped:</span>
                    {brief.attachments_mapped.map((att) => (
                      <div
                        key={att.id || att.filename}
                        className="inline-flex items-center gap-1.5 px-2 py-1 rounded bg-gray-50 border border-gray-200 text-[11px] font-mono text-gray-700 shrink-0"
                        title={att.filename}
                      >
                        <span>{att.target_channel === 'WHATSAPP' ? '🟢 WA' : att.target_channel === 'RCS' ? '🔵 RCS' : '📎'}</span>
                        <span className="max-w-[160px] truncate">{att.filename}</span>
                        {(att.local_path || att.id) && (
                          <a
                            href={getJiraCreativeDownloadUrl({ path: att.local_path, attachmentId: att.id, filename: att.filename })}
                            download={att.filename}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="ml-1 px-1.5 py-0.5 rounded bg-blue-50 hover:bg-blue-100 text-blue-700 border border-blue-200 text-[9px] font-sans font-bold transition"
                            title={`Download ${att.filename}`}
                          >
                            ⬇️ Download
                          </a>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Email Campaign Banner if applicable */}
              {brief.is_email_campaign && (
                <div className="p-4 bg-purple-50/80 border border-purple-200 rounded-xl space-y-2.5">
                  <div className="flex items-center gap-2">
                    <span className="text-base">📧</span>
                    <h3 className="text-xs font-bold text-purple-900 uppercase tracking-wider">
                      Email Mailer Campaign Detected
                    </h3>
                    <span className="text-[10px] bg-purple-100 text-purple-800 font-semibold px-2 py-0.5 rounded">
                      No Karix Whitelisting Required
                    </span>
                  </div>
                  <p className="text-xs text-purple-800 leading-relaxed">
                    <strong>{brief.summary}</strong> is an email newsletter brief containing HTML mailer zip packages and preheaders/subject lines. Email mailers are deployed directly through MoEngage Email or your ESP, and do not require Meta / Karix WhatsApp or RCS approval.
                  </p>
                  {brief.attachments_mapped.some((a) => a.filename.endsWith('.zip') || a.filename.endsWith('.docx')) && (
                    <div className="flex flex-wrap items-center gap-2 pt-1">
                      <span className="text-[11px] text-purple-700 font-medium">Mailer Files:</span>
                      {brief.attachments_mapped
                        .filter((a) => a.filename.endsWith('.zip') || a.filename.endsWith('.docx'))
                        .map((a) => (
                          <span
                            key={a.filename}
                            className="inline-flex items-center gap-1.5 px-2 py-1 rounded bg-white border border-purple-200 text-[11px] font-mono font-semibold text-purple-800 shadow-2xs"
                          >
                            <span>📦</span>
                            <span>{a.filename}</span>
                          </span>
                        ))}
                    </div>
                  )}
                </div>
              )}

              {/* Multi-Channel Content Tabs */}
              <div className="bg-white rounded-xl border border-gray-200/80 shadow-2xs overflow-hidden">
                <div className="flex border-b border-gray-200 bg-gray-50/70">
                  {brief.is_email_campaign ? (
                    <>
                      <button
                        onClick={() => setActiveTab('email')}
                        className={`flex-1 py-3 px-4 text-xs font-bold border-b-2 transition flex items-center justify-center gap-2 ${
                          activeTab === 'email'
                            ? 'border-purple-600 text-purple-700 bg-white'
                            : 'border-transparent text-gray-500 hover:text-gray-700'
                        }`}
                      >
                        <span>📧 Email Packages & Assets</span>
                        <span className="bg-purple-100 text-purple-800 text-[10px] px-1.5 py-0.2 rounded-full font-mono">
                          {brief.email_templates?.length || 0}
                        </span>
                      </button>

                      <button
                        onClick={() => setActiveTab('comments')}
                        className={`flex-1 py-3 px-4 text-xs font-bold border-b-2 transition flex items-center justify-center gap-2 ${
                          activeTab === 'comments'
                            ? 'border-indigo-600 text-indigo-700 bg-white'
                            : 'border-transparent text-gray-500 hover:text-gray-700'
                        }`}
                      >
                        <span>💬 Ticket Comments</span>
                        <span className="bg-indigo-100 text-indigo-800 text-[10px] px-1.5 py-0.2 rounded-full font-mono">
                          {brief.comments?.length || 0}
                        </span>
                      </button>

                      <button
                        onClick={() => setActiveTab('moengage')}
                        className={`flex-1 py-3 px-4 text-xs font-bold border-b-2 transition flex items-center justify-center gap-2 ${
                          activeTab === 'moengage'
                            ? 'border-amber-600 text-amber-700 bg-white'
                            : 'border-transparent text-gray-500 hover:text-gray-700'
                        }`}
                      >
                        <span>🎯 MoEngage Email Staging</span>
                        <span className="bg-amber-100 text-amber-800 text-[10px] px-1.5 py-0.2 rounded-full font-mono">
                          Draft
                        </span>
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        onClick={() => setActiveTab('whatsapp')}
                        className={`flex-1 py-3 px-4 text-xs font-bold border-b-2 transition flex items-center justify-center gap-2 ${
                          activeTab === 'whatsapp'
                            ? 'border-emerald-600 text-emerald-700 bg-white'
                            : 'border-transparent text-gray-500 hover:text-gray-700'
                        }`}
                      >
                        <span>🟢 WhatsApp</span>
                        <span className="bg-emerald-100 text-emerald-800 text-[10px] px-1.5 py-0.2 rounded-full font-mono">
                          {selectedWa.size}/{waTemplates.length}
                        </span>
                      </button>

                      <button
                        onClick={() => setActiveTab('rcs')}
                        className={`flex-1 py-3 px-4 text-xs font-bold border-b-2 transition flex items-center justify-center gap-2 ${
                          activeTab === 'rcs'
                            ? 'border-blue-600 text-blue-700 bg-white'
                            : 'border-transparent text-gray-500 hover:text-gray-700'
                        }`}
                      >
                        <span>🔵 RCS (DLT)</span>
                        <span className="bg-blue-100 text-blue-800 text-[10px] px-1.5 py-0.2 rounded-full font-mono">
                          {selectedRcs.size}/{rcsTemplates.length}
                        </span>
                      </button>

                      <button
                        onClick={() => setActiveTab('sms')}
                        className={`flex-1 py-3 px-4 text-xs font-bold border-b-2 transition flex items-center justify-center gap-2 ${
                          activeTab === 'sms'
                            ? 'border-purple-600 text-purple-700 bg-white'
                            : 'border-transparent text-gray-500 hover:text-gray-700'
                        }`}
                      >
                        <span>🟣 SMS (DLT)</span>
                        <span className="bg-purple-100 text-purple-800 text-[10px] px-1.5 py-0.2 rounded-full font-mono">
                          {brief.sms_templates.length}
                        </span>
                      </button>

                      <button
                        onClick={() => setActiveTab('comments')}
                        className={`flex-1 py-3 px-4 text-xs font-bold border-b-2 transition flex items-center justify-center gap-2 ${
                          activeTab === 'comments'
                            ? 'border-indigo-600 text-indigo-700 bg-white'
                            : 'border-transparent text-gray-500 hover:text-gray-700'
                        }`}
                      >
                        <span>💬 Comments</span>
                        <span className="bg-indigo-100 text-indigo-800 text-[10px] px-1.5 py-0.2 rounded-full font-mono">
                          {brief.comments?.length || 0}
                        </span>
                      </button>

                      <button
                        onClick={() => setActiveTab('moengage')}
                        className={`flex-1 py-3 px-4 text-xs font-bold border-b-2 transition flex items-center justify-center gap-2 ${
                          activeTab === 'moengage'
                            ? 'border-amber-600 text-amber-700 bg-white'
                            : 'border-transparent text-gray-500 hover:text-gray-700'
                        }`}
                      >
                        <span>🎯 MoEngage Staging</span>
                        <span className="bg-amber-100 text-amber-800 text-[10px] px-1.5 py-0.2 rounded-full font-mono">
                          Draft
                        </span>
                      </button>
                    </>
                  )}
                </div>

                {/* Tab Content Panels */}
                <div className="p-5 space-y-4">
                  {/* WhatsApp Panel */}
                  {activeTab === 'whatsapp' && (
                    <div className="space-y-4">
                      {waTemplates.length > 0 && (
                        <div className="flex items-center justify-between pb-2 border-b border-gray-100 text-xs">
                          <div className="flex items-center gap-3">
                            <span className="font-semibold text-gray-700">
                              Selected: {selectedWa.size} of {waTemplates.length}
                            </span>
                            <button
                              onClick={() => selectAllWa(selectedWa.size < waTemplates.length)}
                              className="text-blue-600 hover:underline font-medium"
                            >
                              {selectedWa.size < waTemplates.length ? 'Select All' : 'Deselect All'}
                            </button>
                          </div>
                          <span className="text-gray-400 text-[11px]">
                            💡 Click <strong>✏️ Edit</strong> to tweak copy, variables, or CTA buttons before whitelisting.
                          </span>
                        </div>
                      )}

                      {waTemplates.length === 0 ? (
                        <p className="py-8 text-center text-xs text-gray-400">No WhatsApp templates detected in this brief.</p>
                      ) : (
                        waTemplates.map((wa, idx) => {
                          const isSelected = selectedWa.has(idx);
                          const isEditing = editingCard[`wa-${idx}`] || false;

                          return (
                            <div
                              key={`wa-card-${idx}`}
                              className={`p-4 rounded-xl border transition space-y-3 ${
                                isSelected ? 'bg-white border-emerald-300 shadow-xs' : 'bg-gray-50/70 border-gray-200 opacity-60'
                              }`}
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="flex items-center gap-2.5">
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() => toggleSelectWa(idx)}
                                    className="w-4 h-4 text-emerald-600 rounded border-gray-300 focus:ring-emerald-500 cursor-pointer"
                                  />
                                  {isEditing ? (
                                    <div className="flex flex-wrap items-center gap-2">
                                      <div className="flex items-center gap-1.5">
                                        <label className="text-[10px] uppercase font-bold text-gray-400">Name:</label>
                                        <input
                                          type="text"
                                          value={wa.template_name}
                                          onChange={(e) => updateWaField(idx, 'template_name', e.target.value)}
                                          className="font-mono text-xs font-bold border border-gray-300 rounded px-2 py-1 bg-white"
                                        />
                                      </div>
                                      <select
                                        value={wa.category || 'MARKETING'}
                                        onChange={(e) => updateWaField(idx, 'category', e.target.value)}
                                        className="text-[10px] font-bold border border-gray-300 rounded px-1.5 py-1 bg-white cursor-pointer"
                                      >
                                        <option value="MARKETING">MARKETING</option>
                                        <option value="UTILITY">UTILITY</option>
                                        <option value="AUTHENTICATION">AUTHENTICATION</option>
                                      </select>
                                      <select
                                        value={wa.language || 'en'}
                                        onChange={(e) => updateWaField(idx, 'language', e.target.value)}
                                        className="text-[10px] font-bold border border-gray-300 rounded px-1.5 py-1 bg-white font-mono cursor-pointer"
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
                                    <div className="flex items-center gap-2">
                                      <span className="font-mono font-bold text-xs text-gray-900">{wa.template_name}</span>
                                      <span className={`text-[10px] px-2 py-0.2 rounded-full font-semibold uppercase ${
                                        wa.category === 'UTILITY'
                                          ? 'bg-blue-100 text-blue-800'
                                          : wa.category === 'AUTHENTICATION'
                                          ? 'bg-purple-100 text-purple-800'
                                          : 'bg-emerald-100 text-emerald-800'
                                      }`}>
                                        {wa.category}
                                      </span>
                                      <span className="text-[10px] px-1.5 py-0.2 rounded bg-gray-100 text-gray-700 font-mono font-semibold uppercase">
                                        🌐 {(wa.language || 'en').toUpperCase()}
                                      </span>
                                    </div>
                                  )}
                                </div>

                                <div className="flex items-center gap-2">
                                  {wa.exists_on_waba ? (
                                    <span className="text-[10px] px-2 py-0.5 rounded font-bold uppercase bg-emerald-50 text-emerald-700 border border-emerald-200">
                                      ✓ Live on WABA ({wa.live_status})
                                    </span>
                                  ) : (
                                    <span className="text-[10px] px-2 py-0.5 rounded font-bold uppercase bg-amber-50 text-amber-700 border border-amber-200">
                                      ⚡ Ready to Whitelist
                                    </span>
                                  )}

                                  <button
                                    onClick={() => toggleEditCard(`wa-${idx}`)}
                                    className={`px-2.5 py-1 rounded text-xs font-semibold border transition ${
                                      isEditing
                                        ? 'bg-emerald-50 text-emerald-700 border-emerald-300'
                                        : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50'
                                    }`}
                                  >
                                    {isEditing ? '✓ Done Editing' : '✏️ Edit'}
                                  </button>
                                </div>
                              </div>
                              {/* Side-by-Side: Left = Quick Fix & Controls | Right = Live WhatsApp Phone Preview */}
                              <div className="grid grid-cols-1 xl:grid-cols-12 gap-4 items-start">
                                {/* Left Column (7 cols): Controls & Editable Copy */}
                                <div className="xl:col-span-7 space-y-2.5">
                                  {/* Header Creative (Image / Media) — Download & Replace */}
                                  <div className="p-2.5 bg-gray-50 rounded-lg border border-gray-200 text-[11px] text-gray-700 flex flex-wrap items-center justify-between gap-2">
                                    <span className="flex items-center gap-1.5 font-medium">
                                      <span>🖼️ Header Creative:</span>
                                      {wa.media_filename ? (
                                        <strong className="text-gray-900 font-mono">{wa.media_filename}</strong>
                                      ) : (
                                        <span className="text-gray-400 italic">None (Text-only)</span>
                                      )}
                                    </span>
                                    <div className="flex items-center gap-1.5">
                                      {wa.media_file && (
                                        <a
                                          href={getJiraCreativeDownloadUrl({ path: wa.media_file, filename: wa.media_filename })}
                                          download={wa.media_filename || 'creative.png'}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="px-2 py-1 rounded bg-white hover:bg-gray-100 text-blue-700 border border-blue-200 font-semibold text-[10px] flex items-center gap-1 shadow-2xs transition"
                                        >
                                          <span>⬇️ Download</span>
                                        </a>
                                      )}
                                      <label className="px-2 py-1 rounded bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200 font-semibold text-[10px] flex items-center gap-1 cursor-pointer shadow-2xs transition">
                                        <span>{uploadingCreative[`wa_${idx}`] ? '⏳ Uploading...' : wa.media_filename ? '🔄 Replace Creative' : '📤 Upload Creative'}</span>
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

                                  {/* Text Header (only shown if present or toggled in Edit mode) */}
                                  {wa.header_text ? (
                                    <div className="text-xs font-bold text-gray-900 bg-gray-50 px-3 py-1.5 rounded border border-gray-200/80 flex items-center justify-between gap-2">
                                      <div className="flex items-center gap-1.5">
                                        <span className="text-gray-400 text-[10px] font-semibold uppercase">Text Header:</span>
                                        <span>{wa.header_text}</span>
                                      </div>
                                      <button
                                        type="button"
                                        onClick={() => updateWaField(idx, 'header_text', null)}
                                        className="text-[10px] text-red-600 hover:underline font-medium"
                                      >
                                        ✕ Clear Header
                                      </button>
                                    </div>
                                  ) : isEditing ? (
                                    <button
                                      type="button"
                                      onClick={() => updateWaField(idx, 'header_text', 'Important Update')}
                                      className="text-[11px] text-emerald-700 hover:underline font-semibold"
                                    >
                                      + Add Optional Text Header
                                    </button>
                                  ) : null}

                                  {isEditing ? (
                                    <div className="space-y-2.5">
                                      {wa.header_text !== null && wa.header_text !== undefined && (
                                        <div>
                                          <label className="block text-[11px] text-gray-500 mb-1">Text Header (optional — leave blank if none):</label>
                                          <input
                                            type="text"
                                            value={wa.header_text || ''}
                                            onChange={(e) => updateWaField(idx, 'header_text', e.target.value || null)}
                                            placeholder="Leave blank if no text header"
                                            className="w-full text-xs px-2.5 py-1.5 border border-gray-300 rounded bg-white"
                                          />
                                        </div>
                                      )}

                                      <div className="flex items-center justify-between text-[11px] text-gray-500">
                                        <span>Template Body (T&amp;Cs apply stays in body):</span>
                                        <span>{wa.body.length} chars</span>
                                      </div>
                                      <textarea
                                        value={wa.body}
                                        onChange={(e) => updateWaField(idx, 'body', e.target.value)}
                                        rows={5}
                                        className="w-full p-2.5 font-mono text-xs border border-gray-300 rounded-lg bg-white outline-none focus:ring-2 focus:ring-emerald-500"
                                      />

                                      {/* Button controls */}
                                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2.5 pt-1">
                                        <div>
                                          <label className="block text-[11px] text-gray-500 mb-1">Button Type:</label>
                                          <select
                                            value={wa.button_type || 'NONE'}
                                            onChange={(e) => updateWaField(idx, 'button_type', e.target.value)}
                                            className="w-full text-xs px-2.5 py-1.5 border border-gray-300 rounded bg-white font-semibold cursor-pointer"
                                          >
                                            <option value="NONE">None</option>
                                            <option value="URL">CTA URL Button</option>
                                            <option value="QUICK_REPLY">Quick Reply Button</option>
                                            <option value="PHONE_NUMBER">Call Phone Number</option>
                                          </select>
                                        </div>
                                        <div>
                                          <label className="block text-[11px] text-gray-500 mb-1">Button Text:</label>
                                          <input
                                            type="text"
                                            value={wa.button_text || ''}
                                            onChange={(e) => updateWaField(idx, 'button_text', e.target.value)}
                                            placeholder="e.g. Check Offer"
                                            className="w-full text-xs px-2.5 py-1.5 border border-gray-300 rounded bg-white"
                                          />
                                        </div>
                                        <div>
                                          {wa.button_type === 'PHONE_NUMBER' ? (
                                            <>
                                              <label className="block text-[11px] text-gray-500 mb-1">Phone (+91...):</label>
                                              <input
                                                type="text"
                                                value={wa.button_phone || ''}
                                                onChange={(e) => updateWaField(idx, 'button_phone', e.target.value)}
                                                placeholder="+919876543210"
                                                className="w-full text-xs px-2.5 py-1.5 border border-gray-300 rounded bg-white font-mono"
                                              />
                                            </>
                                          ) : (
                                            <>
                                              <label className="block text-[11px] text-gray-500 mb-1">Destination URL:</label>
                                              <input
                                                type="text"
                                                value={wa.button_url || ''}
                                                onChange={(e) => updateWaField(idx, 'button_url', e.target.value)}
                                                placeholder="https://u3.mnge.co/"
                                                disabled={wa.button_type === 'QUICK_REPLY' || wa.button_type === 'NONE'}
                                                className="w-full text-xs px-2.5 py-1.5 border border-gray-300 rounded bg-white disabled:bg-gray-100"
                                              />
                                            </>
                                          )}
                                        </div>
                                      </div>
                                    </div>
                                  ) : (
                                    <>
                                      <div className="bg-white p-3.5 rounded-lg border border-gray-200/80 font-sans text-xs text-gray-800 whitespace-pre-wrap leading-relaxed">
                                        {wa.body}
                                      </div>

                                      {wa.variables && wa.variables.length > 0 && (
                                        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                                          <span className="text-[10px] font-bold text-gray-400 uppercase">Variables:</span>
                                          {wa.variables.map((v, vIdx) => (
                                            <span key={`var-${vIdx}`} className="px-2 py-0.5 rounded bg-gray-100 text-gray-700 font-mono text-[10px] border border-gray-200">
                                              {`{{${v.replace(/[{}]/g, '')}}}`} = <strong>{wa.sample_values?.[vIdx] || 'Sample'}</strong>
                                            </span>
                                          ))}
                                        </div>
                                      )}
                                    </>
                                  )}
                                </div>

                                {/* Right Column (5 cols): Live WhatsApp Phone Bubble Preview */}
                                <div className="xl:col-span-5 rounded-xl p-3 border border-emerald-200/80 bg-[#efeae2] shadow-inner">
                                  <div className="flex items-center justify-between mb-2 px-1">
                                    <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-900/70 flex items-center gap-1">
                                      <span>📱 Live WhatsApp Preview</span>
                                    </span>
                                    <span className="text-[10px] font-mono text-gray-500">{wa.body.length} chars</span>
                                  </div>
                                  <div className="bg-white rounded-xl shadow-xs overflow-hidden border border-gray-200/60 max-w-sm mx-auto">
                                    {wa.media_file && (
                                      <div className="bg-gray-100 border-b border-gray-100">
                                        <img
                                          src={getJiraCreativeDownloadUrl({ path: wa.media_file, filename: wa.media_filename, inline: true })}
                                          alt={wa.media_filename || 'Header creative'}
                                          className="w-full max-h-40 object-cover"
                                          onError={(e) => {
                                            (e.currentTarget as HTMLImageElement).style.display = 'none';
                                          }}
                                        />
                                      </div>
                                    )}
                                    <div className="p-3 space-y-1.5">
                                      {wa.header_text && (
                                        <div className="text-xs font-bold text-gray-900 leading-snug">
                                          {wa.header_text}
                                        </div>
                                      )}
                                      <div className="text-[11px] text-gray-800 whitespace-pre-wrap leading-relaxed font-sans">
                                        {wa.body}
                                      </div>
                                      <div className="text-[9px] text-gray-400 text-right pt-0.5">
                                        10:42 AM ✓✓
                                      </div>
                                    </div>
                                    {wa.button_type && wa.button_type !== 'NONE' && (
                                      <div className="border-t border-gray-100 py-2 px-3 text-center text-xs font-semibold text-blue-600 bg-gray-50/40 flex items-center justify-center gap-1.5">
                                        <span>{wa.button_type === 'PHONE_NUMBER' ? '📞' : wa.button_type === 'QUICK_REPLY' ? '↩️' : '🔗'}</span>
                                        <span>{wa.button_text || 'Check Offer'}</span>
                                      </div>
                                    )}
                                  </div>
                                </div>
                              </div>
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
                        <div className="flex items-center justify-between pb-2 border-b border-gray-100 text-xs">
                          <div className="flex items-center gap-3">
                            <span className="font-semibold text-gray-700">
                              Selected: {selectedRcs.size} of {rcsTemplates.length}
                            </span>
                            <button
                              onClick={() => selectAllRcs(selectedRcs.size < rcsTemplates.length)}
                              className="text-blue-600 hover:underline font-medium"
                            >
                              {selectedRcs.size < rcsTemplates.length ? 'Select All' : 'Deselect All'}
                            </button>
                          </div>
                          <span className="text-gray-400 text-[11px]">
                            💡 Click <strong>✏️ Edit</strong> to tweak card title, body copy, or CTA action.
                          </span>
                        </div>
                      )}

                      {rcsTemplates.length === 0 ? (
                        <p className="py-8 text-center text-xs text-gray-400">No RCS templates detected in this brief.</p>
                      ) : (
                        rcsTemplates.map((rcs, idx) => {
                          const isSelected = selectedRcs.has(idx);
                          const isEditing = editingCard[`rcs-${idx}`] || false;

                          return (
                            <div
                              key={`rcs-card-${idx}`}
                              className={`p-4 rounded-xl border transition space-y-3 ${
                                isSelected ? 'bg-white border-blue-300 shadow-xs' : 'bg-gray-50/70 border-gray-200 opacity-60'
                              }`}
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="flex items-center gap-2.5">
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() => toggleSelectRcs(idx)}
                                    className="w-4 h-4 text-blue-600 rounded border-gray-300 focus:ring-blue-500 cursor-pointer"
                                  />
                                  {isEditing ? (
                                    <div className="flex items-center gap-1.5">
                                      <label className="text-[10px] uppercase font-bold text-gray-400">Name:</label>
                                      <input
                                        type="text"
                                        value={rcs.template_name}
                                        onChange={(e) => updateRcsField(idx, 'template_name', e.target.value)}
                                        className="font-mono text-xs font-bold border border-gray-300 rounded px-2 py-1 bg-white"
                                      />
                                    </div>
                                  ) : (
                                    <span className="font-mono font-bold text-xs text-gray-900">{rcs.template_name}</span>
                                  )}
                                  <span className="text-[10px] px-2 py-0.2 rounded-full bg-blue-100 text-blue-800 font-semibold uppercase">
                                    Standalone Card
                                  </span>
                                </div>

                                <div className="flex items-center gap-2">
                                  <button
                                    onClick={() => handleSyncRcsToMoEngage(rcs)}
                                    disabled={syncingRcs[rcs.template_name]}
                                    className={`px-2.5 py-1 rounded text-xs font-semibold border transition flex items-center gap-1.5 ${
                                      syncedRcs[rcs.template_name]
                                        ? 'bg-emerald-50 text-emerald-700 border-emerald-300'
                                        : 'bg-purple-50 text-purple-700 border-purple-200 hover:bg-purple-100'
                                    }`}
                                    title="Register this RCS template directly into MoEngage Settings -> RCS template management"
                                  >
                                    {syncingRcs[rcs.template_name]
                                      ? 'Syncing...'
                                      : syncedRcs[rcs.template_name]
                                      ? '✓ In MoEngage'
                                      : '🔄 Sync to MoEngage'}
                                  </button>

                                  <button
                                    onClick={() => toggleEditCard(`rcs-${idx}`)}
                                    className={`px-2.5 py-1 rounded text-xs font-semibold border transition ${
                                      isEditing
                                        ? 'bg-blue-50 text-blue-700 border-blue-300'
                                        : 'bg-white text-gray-700 border-gray-200 hover:bg-gray-50'
                                    }`}
                                  >
                                    {isEditing ? '✓ Done Editing' : '✏️ Edit'}
                                  </button>
                                </div>
                              </div>

                              {/* Side-by-Side: Left = Quick Fix & Controls | Right = Live RCS Rich Card Preview */}
                              <div className="grid grid-cols-1 xl:grid-cols-12 gap-4 items-start">
                                {/* Left Column (7 cols): Controls & Editable Copy */}
                                <div className="xl:col-span-7 space-y-2.5">
                                  <div className="p-2.5 bg-gray-50 rounded-lg border border-gray-200 text-[11px] text-gray-700 flex flex-wrap items-center justify-between gap-2">
                                    <span className="flex items-center gap-1.5 font-medium">
                                      <span>🖼️ Card Creative:</span>
                                      {rcs.media_filename ? (
                                        <strong className="text-gray-900 font-mono">{rcs.media_filename}</strong>
                                      ) : (
                                        <span className="text-gray-400 italic">None attached</span>
                                      )}
                                    </span>
                                    <div className="flex items-center gap-1.5">
                                      {rcs.media_file && (
                                        <a
                                          href={getJiraCreativeDownloadUrl({ path: rcs.media_file, filename: rcs.media_filename })}
                                          download={rcs.media_filename || 'creative.png'}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="px-2 py-1 rounded bg-white hover:bg-gray-100 text-blue-700 border border-blue-200 font-semibold text-[10px] flex items-center gap-1 shadow-2xs transition"
                                        >
                                          <span>⬇️ Download</span>
                                        </a>
                                      )}
                                      <label className="px-2 py-1 rounded bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200 font-semibold text-[10px] flex items-center gap-1 cursor-pointer shadow-2xs transition">
                                        <span>{uploadingCreative[`rcs_${idx}`] ? '⏳ Uploading...' : rcs.media_filename ? '🔄 Replace Creative' : '📤 Upload Creative'}</span>
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

                                  {isEditing ? (
                                    <div className="space-y-2.5">
                                      <div>
                                        <label className="block text-[11px] text-gray-500 mb-1">Card Title:</label>
                                        <input
                                          type="text"
                                          value={rcs.card_title}
                                          onChange={(e) => updateRcsField(idx, 'card_title', e.target.value)}
                                          className="w-full text-xs px-2.5 py-1.5 border border-gray-300 rounded bg-white font-semibold"
                                        />
                                      </div>
                                      <div>
                                        <label className="block text-[11px] text-gray-500 mb-1">Card Body Copy:</label>
                                        <textarea
                                          value={rcs.body}
                                          onChange={(e) => updateRcsField(idx, 'body', e.target.value)}
                                          rows={4}
                                          className="w-full p-2.5 font-mono text-xs border border-gray-300 rounded bg-white"
                                        />
                                      </div>
                                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                                        <div>
                                          <label className="block text-[11px] text-gray-500 mb-1">Button Label (CTA):</label>
                                          <input
                                            type="text"
                                            value={rcs.action_label || ''}
                                            onChange={(e) => updateRcsField(idx, 'action_label', e.target.value)}
                                            placeholder="e.g. Apply Now"
                                            className="w-full text-xs px-2.5 py-1.5 border border-gray-300 rounded bg-white font-medium"
                                          />
                                        </div>
                                        <div>
                                          <label className="block text-[11px] text-gray-500 mb-1">Button Destination URL:</label>
                                          <input
                                            type="text"
                                            value={rcs.action_url || ''}
                                            onChange={(e) => updateRcsField(idx, 'action_url', e.target.value)}
                                            placeholder="https://u3.mnge.co/"
                                            className="w-full text-xs px-2.5 py-1.5 border border-gray-300 rounded bg-white font-mono"
                                          />
                                        </div>
                                      </div>
                                    </div>
                                  ) : (
                                    <div className="bg-white p-3.5 rounded-lg border border-gray-200/80 space-y-2.5">
                                      <h4 className="font-bold text-xs text-gray-900">{rcs.card_title}</h4>
                                      <p className="font-sans text-xs text-gray-800 whitespace-pre-wrap leading-relaxed">
                                        {rcs.body}
                                      </p>
                                      {(rcs.action_label || rcs.action_url) && (
                                        <div className="pt-2 border-t border-gray-100 flex items-center gap-2 text-xs">
                                          <span className="text-gray-400">CTA Button:</span>
                                          <span className="px-2.5 py-1 rounded bg-blue-50 text-blue-700 font-semibold border border-blue-200/60">
                                            🔗 {rcs.action_label || 'Apply Now'} ({rcs.action_url || 'https://u3.mnge.co/'})
                                          </span>
                                        </div>
                                      )}
                                    </div>
                                  )}
                                </div>

                                {/* Right Column (5 cols): Live RCS Rich Card Preview */}
                                <div className="xl:col-span-5 rounded-xl p-3 border border-blue-200/80 bg-slate-100 shadow-inner">
                                  <div className="flex items-center justify-between mb-2 px-1">
                                    <span className="text-[10px] font-bold uppercase tracking-wider text-blue-900/70">
                                      📱 Live RCS Rich Card Preview
                                    </span>
                                    <span className="text-[10px] font-mono text-gray-500">{rcs.body.length} chars</span>
                                  </div>
                                  <div className="bg-white rounded-2xl shadow-xs overflow-hidden border border-gray-200/80 max-w-sm mx-auto">
                                    {rcs.media_file && (
                                      <div className="bg-gray-100 border-b border-gray-100">
                                        <img
                                          src={getJiraCreativeDownloadUrl({ path: rcs.media_file, filename: rcs.media_filename, inline: true })}
                                          alt={rcs.media_filename || 'RCS card creative'}
                                          className="w-full max-h-40 object-cover"
                                          onError={(e) => {
                                            (e.currentTarget as HTMLImageElement).style.display = 'none';
                                          }}
                                        />
                                      </div>
                                    )}
                                    <div className="p-3.5 space-y-1.5">
                                      <h5 className="text-xs font-bold text-gray-900 leading-snug">
                                        {rcs.card_title || 'Rich Card Title'}
                                      </h5>
                                      <div className="text-[11px] text-gray-700 whitespace-pre-wrap leading-relaxed font-sans">
                                        {rcs.body}
                                      </div>
                                      {(rcs.action_label || rcs.action_url) && (
                                        <div className="pt-2">
                                          <div className="w-full py-1.5 px-3 rounded-full border border-blue-200 bg-blue-50/50 text-blue-700 text-xs font-semibold text-center">
                                            🌐 {rcs.action_label || 'Apply Now'}
                                          </div>
                                        </div>
                                      )}
                                    </div>
                                  </div>
                                </div>
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  )}

                  {/* SMS Panel */}
                  {activeTab === 'sms' && (
                    <div className="space-y-4">
                      {brief.sms_templates.length === 0 ? (
                        <p className="py-8 text-center text-xs text-gray-400">No SMS variants detected in this brief.</p>
                      ) : (
                        brief.sms_templates.map((sms) => (
                          <div key={sms.template_name} className="p-4 rounded-xl border border-gray-200 bg-gray-50/50 space-y-2.5">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <span className="font-mono font-bold text-xs text-gray-900">{sms.template_name}</span>
                                <span className="text-[10px] px-2 py-0.2 rounded bg-purple-100 text-purple-800 font-semibold">
                                  {sms.variant}
                                </span>
                              </div>
                              <span
                                className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded ${
                                  sms.char_count <= 160
                                    ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                                    : 'bg-amber-50 text-amber-700 border border-amber-200'
                                }`}
                              >
                                {sms.char_count} chars ({Math.ceil(sms.char_count / 160)} SMS segment)
                              </span>
                            </div>

                            <div className="bg-white p-3.5 rounded-lg border border-gray-200/80 font-mono text-xs text-gray-800 whitespace-pre-wrap leading-relaxed">
                              {sms.text}
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                  )}

                  {/* Email Packages & Templates Panel */}
                  {activeTab === 'email' && (
                    <div className="space-y-4">
                      <div className="flex items-center justify-between pb-2 border-b border-gray-100 text-xs">
                        <span className="font-semibold text-gray-700">
                          Email Campaign Packages & Documents ({brief.email_templates?.length || 0} assets)
                        </span>
                        <span className="text-gray-400 text-[11px]">
                          📦 HTML emailer ZIP packages, preheader documents, and email copy templates.
                        </span>
                      </div>

                      {(!brief.email_templates || brief.email_templates.length === 0) ? (
                        <p className="py-8 text-center text-xs text-gray-400">No email packages detected in this brief.</p>
                      ) : (
                        brief.email_templates.map((em, idx) => (
                          <div key={`email-asset-${idx}`} className="p-4 rounded-xl border border-purple-200 bg-purple-50/30 space-y-3">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2.5">
                                <span className="text-xl">{em.file_type?.includes('ZIP') ? '📦' : em.file_type?.includes('Subject') ? '📝' : '📄'}</span>
                                <div>
                                  <h4 className="font-bold text-xs text-gray-900">{em.filename || em.template_name}</h4>
                                  <span className="text-[10px] text-purple-700 font-semibold">{em.file_type || 'Email Asset'}</span>
                                </div>
                              </div>
                              {em.local_path && (
                                <span className="text-[10px] font-mono bg-white text-emerald-700 px-2 py-0.5 rounded border border-emerald-200 font-semibold">
                                  ✓ Cached Locally
                                </span>
                              )}
                            </div>
                            {em.body && (
                              <div className="bg-white p-3 rounded-lg border border-purple-100 font-sans text-xs text-gray-800 whitespace-pre-wrap leading-relaxed">
                                {em.body}
                              </div>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  )}
                  {/* Comments Panel */}
                  {activeTab === 'comments' && (
                    <div className="space-y-4">
                      <div className="flex items-center justify-between pb-2 border-b border-gray-100 text-xs">
                        <span className="font-semibold text-gray-700">
                          Jira Discussion Thread ({brief.comments?.length || 0} comments)
                        </span>
                        <span className="text-gray-400 text-[11px]">
                          💡 Revisions and copy changes posted by operators/managers in Jira comments.
                        </span>
                      </div>

                      {(!brief.comments || brief.comments.length === 0) ? (
                        <p className="py-8 text-center text-xs text-gray-400">No comments posted on this Jira ticket yet.</p>
                      ) : (
                        brief.comments.map((comment) => (
                          <div key={comment.id} className="p-4 rounded-xl border border-gray-200 bg-white shadow-2xs space-y-2.5">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <span className="w-6 h-6 rounded-full bg-indigo-100 text-indigo-700 flex items-center justify-center text-xs font-bold">
                                  {comment.author.charAt(0).toUpperCase()}
                                </span>
                                <strong className="text-xs font-semibold text-gray-900">{comment.author}</strong>
                              </div>
                              <span className="text-[10px] text-gray-400 font-mono">
                                {comment.created ? formatDate(comment.created) : ''}
                              </span>
                            </div>
                            <div className="bg-gray-50 p-3 rounded-lg border border-gray-100 font-sans text-xs text-gray-800 whitespace-pre-wrap leading-relaxed">
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
                      <div className="p-4 rounded-xl border border-amber-200 bg-amber-50/40 space-y-3">
                        <div className="flex items-center justify-between">
                          <h3 className="text-xs font-bold text-amber-900 uppercase tracking-wider">MoEngage Campaign Staging</h3>
                          <span className="px-2 py-0.5 rounded text-[10px] font-bold uppercase bg-amber-100 text-amber-800">
                            Status: DRAFT
                          </span>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
                          <div>
                            <span className="text-gray-500 font-medium">Campaign Name:</span>
                            <p className="font-semibold text-gray-900">{brief.moengage_campaign.campaign_name}</p>
                          </div>
                          <div>
                            <span className="text-gray-500 font-medium">Scheduled Send Date:</span>
                            <p className="font-semibold text-gray-900">{brief.moengage_campaign.scheduled_date || 'Immediate / Manual'}</p>
                          </div>
                          <div>
                            <span className="text-gray-500 font-medium">WhatsApp Staged Template:</span>
                            <p className="font-mono text-gray-900 font-semibold">{brief.moengage_campaign.whatsapp_template || 'None'}</p>
                          </div>
                          <div>
                            <span className="text-gray-500 font-medium">Push Notification Title:</span>
                            <p className="font-semibold text-gray-900">{brief.moengage_campaign.push_title || 'None'}</p>
                          </div>
                        </div>

                        <div className="pt-2 border-t border-amber-200/60">
                          <span className="text-gray-500 font-medium text-xs">Push Notification Body:</span>
                          <p className="p-2.5 mt-1 bg-white rounded border border-gray-200 text-xs text-gray-800">
                            {brief.moengage_campaign.push_body || 'None'}
                          </p>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              {/* Sticky Bottom 2-Click Whitelist Bar */}
              {!brief.is_email_campaign && (waTemplates.length > 0 || rcsTemplates.length > 0) && (
                <div className="sticky bottom-3 z-20 bg-gray-900/95 backdrop-blur-xs text-white rounded-2xl p-4 shadow-xl border border-gray-700 flex flex-wrap items-center justify-between gap-4">
                  <div className="flex flex-wrap items-center gap-4">
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] font-semibold text-gray-300">Target Account:</span>
                      <select
                        value={targetAccount}
                        onChange={(e) => setTargetAccount(e.target.value)}
                        className="text-xs font-bold bg-gray-800 border border-gray-600 text-white rounded-lg px-2.5 py-1.5 cursor-pointer"
                      >
                        {accounts.map((acc) => (
                          <option key={acc.id} value={acc.id}>
                            {acc.name} ({acc.id.toUpperCase()})
                          </option>
                        ))}
                      </select>
                    </div>

                    <div className="flex items-center gap-3 text-xs">
                      <span className="px-2.5 py-1 rounded-full bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-semibold">
                        🟢 {selectedWa.size} WhatsApp
                      </span>
                      <span className="px-2.5 py-1 rounded-full bg-blue-500/20 text-blue-300 border border-blue-500/30 font-semibold">
                        🔵 {selectedRcs.size} RCS
                      </span>
                    </div>

                    {rcsTemplates.length > 0 && (
                      <label className="flex items-center gap-1.5 text-xs text-gray-300 cursor-pointer select-none">
                        <input
                          type="checkbox"
                          checked={autoSyncRcsToMoEngage}
                          onChange={(e) => setAutoSyncRcsToMoEngage(e.target.checked)}
                          className="rounded border-gray-600 text-emerald-500 focus:ring-0"
                        />
                        <span>+ Auto-sync RCS to MoEngage</span>
                      </label>
                    )}
                  </div>

                  <div className="flex items-center gap-2.5">
                    <button
                      type="button"
                      onClick={() => setShowSessionModal(true)}
                      className="px-3 py-2 rounded-xl bg-gray-800 hover:bg-gray-700 text-amber-300 border border-gray-700 text-xs font-semibold transition"
                    >
                      🔑 Paste Session
                    </button>
                    <button
                      type="button"
                      onClick={() => requestWhitelist('all')}
                      disabled={submitting || totalSelectedCount === 0}
                      className="px-5 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-600 disabled:bg-gray-700 text-white text-xs font-bold shadow-lg transition flex items-center gap-2"
                    >
                      <span>🚀 {submitting ? 'Whitelisting...' : `Whitelist ${totalSelectedCount} Template${totalSelectedCount === 1 ? '' : 's'} to Karix`}</span>
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>

    {/* Inline Session Quick-Paste Modal */}
    {showSessionModal && (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4"
        role="dialog"
        aria-modal="true"
      >
        <div className="w-full max-w-lg rounded-2xl border border-gray-200 bg-white p-6 shadow-2xl space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-base font-bold text-gray-900">🔑 Quick Karix Session Paste</h3>
              <p className="text-xs text-gray-500 mt-0.5">
                Refresh expiring Portal or Lounge session credentials for <strong>{getAccountLabel(targetAccount)}</strong> without leaving this ticket.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setShowSessionModal(false)}
              className="text-gray-400 hover:text-gray-600 font-bold text-lg"
            >
              ✕
            </button>
          </div>

          <div className="space-y-3">
            <div>
              <label className="block text-[11px] font-bold text-gray-700 uppercase mb-1">
                WhatsApp Media Upload — Portal Bearer Token (Optional)
              </label>
              <input
                type="password"
                value={quickBearerToken}
                onChange={(e) => setQuickBearerToken(e.target.value)}
                placeholder="Authorization: Bearer eyJhbGci... from rcsgui.karix.solutions"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono"
              />
            </div>
            <div>
              <label className="block text-[11px] font-bold text-gray-700 uppercase mb-1">
                WhatsApp Media Upload — Portal Session ID (Optional)
              </label>
              <input
                type="password"
                value={quickSessionId}
                onChange={(e) => setQuickSessionId(e.target.value)}
                placeholder="Session header from rcsgui.karix.solutions DevTools"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono"
              />
            </div>
            <div>
              <label className="block text-[11px] font-bold text-gray-700 uppercase mb-1">
                RCS / SMS DLT — Karix Lounge Session Cookie (Optional)
              </label>
              <input
                type="password"
                value={quickLoungeCookie}
                onChange={(e) => setQuickLoungeCookie(e.target.value)}
                placeholder="PHPSESSID=... from lounge.karix.solutions DevTools"
                className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono"
              />
            </div>
          </div>

          <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-gray-100">
            <button
              type="button"
              onClick={() => setShowSessionModal(false)}
              className="px-4 py-2 rounded-lg border border-gray-300 text-xs font-semibold text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              type="button"
              disabled={savingQuickSession}
              onClick={async () => {
                try {
                  setSavingQuickSession(true);
                  if (quickBearerToken.trim() || quickSessionId.trim()) {
                    await updateCredentials({
                      account: targetAccount,
                      channel: 'whatsapp',
                      bearer_token: quickBearerToken.trim() || undefined,
                      session: quickSessionId.trim() || undefined,
                    });
                  }
                  if (quickLoungeCookie.trim()) {
                    await updateCredentials({
                      account: targetAccount,
                      channel: 'rcs',
                      lounge_cookie: quickLoungeCookie.trim(),
                    });
                  }
                  setShowSessionModal(false);
                  setQuickBearerToken('');
                  setQuickSessionId('');
                  setQuickLoungeCookie('');
                  setFeedback({
                    message: `Session credentials updated for ${getAccountLabel(targetAccount)}. Ready to whitelist!`,
                    type: 'success',
                  });
                } catch (err) {
                  setFeedback({ message: formatError(err), type: 'error' });
                } finally {
                  setSavingQuickSession(false);
                }
              }}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold"
            >
              {savingQuickSession ? 'Saving...' : 'Save Session'}
            </button>
          </div>
        </div>
      </div>
    )}
    {confirmationMode && brief && (
      <div
        className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-xs p-4"
        role="dialog"
        aria-modal="true"
        aria-labelledby="whitelist-confirmation-title"
      >
        <div className="w-full max-w-md rounded-2xl border border-gray-200 bg-white p-6 shadow-2xl space-y-5">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl bg-amber-100 text-amber-700 flex items-center justify-center text-lg shrink-0">
              ⚠️
            </div>
            <div>
              <h2 id="whitelist-confirmation-title" className="text-base font-bold text-gray-900">
                Confirm whitelisting
              </h2>
              <p className="text-xs text-gray-500 mt-1">
                Review this action before sending templates to Karix.
              </p>
            </div>
          </div>

          <div className="rounded-xl border border-amber-200 bg-amber-50/70 p-4 space-y-2 text-xs text-amber-900">
            <p>
              You are about to whitelist the selected templates from <strong>{brief.issue_key}</strong>.
            </p>
            <ul className="list-disc list-inside space-y-1">
              {(confirmationMode === 'all' || confirmationMode === 'whatsapp') && (
                <li>{selectedWa.size} WhatsApp template{selectedWa.size === 1 ? '' : 's'}</li>
              )}
              {(confirmationMode === 'all' || confirmationMode === 'rcs') && (
                <li>{selectedRcs.size} RCS template{selectedRcs.size === 1 ? '' : 's'}</li>
              )}
              <li>Target account: <strong>{accounts.find((account) => account.id === targetAccount)?.name || targetAccount}</strong></li>
            </ul>
            <p className="pt-2 border-t border-amber-200/80 font-semibold">
              After you confirm, the application will submit them for whitelisting.
            </p>
          </div>

          <div className="flex items-center justify-end gap-3">
            <button
              type="button"
              onClick={() => setConfirmationMode(null)}
              disabled={submitting}
              className="px-4 py-2 rounded-lg border border-gray-300 text-gray-700 text-xs font-semibold hover:bg-gray-50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={confirmWhitelist}
              disabled={submitting}
              className="px-4 py-2 rounded-lg bg-emerald-600 text-white text-xs font-semibold hover:bg-emerald-700 disabled:opacity-50"
            >
              {submitting ? 'Whitelisting...' : 'Confirm & Whitelist'}
            </button>
          </div>
        </div>
      </div>
    )}
    </>
  );
}
