'use client';

import { useState, useEffect, useCallback } from 'react';
import { useApp } from '@/lib/context';
import {
  fetchJiraProjects,
  fetchJiraIssues,
  fetchJiraBrief,
  submitJiraBrief,
  syncRcsTemplateToMoEngage,
  type JiraProjectItem,
  type JiraIssueItem,
  type JiraBriefData,
  type JiraWhatsAppDraft,
  type JiraRcsDraft,
} from '@/lib/api';
import { formatError, formatDate } from '@/lib/format';

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
  const [activeTab, setActiveTab] = useState<'whatsapp' | 'rcs' | 'sms' | 'moengage'>('whatsapp');
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Editable template drafts and selection sets
  const [waTemplates, setWaTemplates] = useState<JiraWhatsAppDraft[]>([]);
  const [rcsTemplates, setRcsTemplates] = useState<JiraRcsDraft[]>([]);
  const [selectedWa, setSelectedWa] = useState<Set<string>>(new Set());
  const [selectedRcs, setSelectedRcs] = useState<Set<string>>(new Set());
  const [syncingRcs, setSyncingRcs] = useState<Record<string, boolean>>({});
  const [syncedRcs, setSyncedRcs] = useState<Record<string, string>>({});
  const [editingCard, setEditingCard] = useState<Record<string, boolean>>({});
  const [targetAccount, setTargetAccount] = useState<string>('tcl_promo');

  const loadIssues = useCallback(async () => {
    try {
      setLoadingIssues(true);
      const list = await fetchJiraIssues({ project, limit: 30 });
      setIssues(list);
      if (list.length > 0) {
        setSelectedKey((prev) => {
          if (prev && list.some((i) => i.key === prev)) return prev;
          return list[0].key;
        });
      } else {
        setSelectedKey('');
        setBrief(null);
      }
    } catch (err) {
      setFeedback({ message: formatError(err), type: 'error' });
    } finally {
      setLoadingIssues(false);
    }
  }, [project]);

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
      if (urlKey) setSelectedKey(urlKey.toUpperCase().trim());
      if (urlProj) {
        setProject(urlProj.toUpperCase().trim());
      } else {
        const saved = localStorage.getItem('briefs_project');
        if (saved) setProject(saved);
      }
    }
  }, []);

  useEffect(() => {
    loadIssues();
  }, [loadIssues]);

  const loadBrief = useCallback(async (key: string) => {
    if (!key) return;
    try {
      setLoadingBrief(true);
      setFeedback(null);
      const data = await fetchJiraBrief(key);
      setBrief(data);
      const waList = data.whatsapp_templates || [];
      const rcsList = data.rcs_templates || [];
      setWaTemplates(waList);
      setRcsTemplates(rcsList);
      setSelectedWa(new Set(waList.map((w) => w.template_name)));
      setSelectedRcs(new Set(rcsList.map((r) => r.template_name)));
      setEditingCard({});
      const initialAcc = data.account === 'wealth' ? 'tcl_promo' : (data.account || 'tcl_promo');
      setTargetAccount(initialAcc);
      if (waList.length > 0) {
        setActiveTab('whatsapp');
      } else if (rcsList.length > 0) {
        setActiveTab('rcs');
      } else if (data.sms_templates?.length > 0) {
        setActiveTab('sms');
      } else {
        setActiveTab('moengage');
      }
    } catch (err) {
      setFeedback({ message: `Failed to load brief for ${key}: ${formatError(err)}`, type: 'error' });
    } finally {
      setLoadingBrief(false);
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
        waToSubmit = waTemplates.filter((w) => selectedWa.has(w.template_name));
        if (waToSubmit.length > 0) submitChannels.push('whatsapp');
      }

      if (channelMode === 'all' || channelMode === 'rcs') {
        rcsToSubmit = rcsTemplates.filter((r) => selectedRcs.has(r.template_name));
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
      setFeedback({
        message: `Successfully submitted ${waCount} WhatsApp and ${rcsCount} RCS templates for ${brief.issue_key}. Jira ticket comment posted.`,
        type: 'success',
      });
      loadBrief(brief.issue_key);
    } catch (err) {
      setFeedback({ message: formatError(err), type: 'error' });
    } finally {
      setSubmitting(false);
    }
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

  const toggleSelectWa = (name: string) => {
    setSelectedWa((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const toggleSelectRcs = (name: string) => {
    setSelectedRcs((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const selectAllWa = (select: boolean) => {
    setSelectedWa(select ? new Set(waTemplates.map((w) => w.template_name)) : new Set());
  };

  const selectAllRcs = (select: boolean) => {
    setSelectedRcs(select ? new Set(rcsTemplates.map((r) => r.template_name)) : new Set());
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
        cta_url: rcs.action_url || 'https://www.tatacapital.com',
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

  const filteredIssues = issues.filter(
    (i) =>
      i.key.toLowerCase().includes(searchQuery.toLowerCase()) ||
      i.summary.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (i.assignee || '').toLowerCase().includes(searchQuery.toLowerCase())
  );

  const totalSelectedCount = selectedWa.size + selectedRcs.size;

  return (
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

        <div className="flex items-center gap-3">
          <button
            onClick={loadIssues}
            disabled={loadingIssues}
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold text-gray-700 bg-white hover:bg-gray-50 border border-gray-200 shadow-2xs transition disabled:opacity-50"
          >
            🔄 Refresh Tickets
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

          <input
            type="text"
            placeholder="Search key, title, assignee..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full text-xs px-3 py-2 bg-gray-50 border border-gray-200 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
          />

          <div className="space-y-2 max-h-[640px] overflow-y-auto pr-1">
            {loadingIssues ? (
              <div className="py-12 text-center text-xs text-gray-400">Loading Jira queue...</div>
            ) : filteredIssues.length === 0 ? (
              <div className="py-12 text-center text-xs text-gray-400">No matching Jira tickets found.</div>
            ) : (
              filteredIssues.map((issue) => {
                const isSelected = issue.key === selectedKey;
                return (
                  <button
                    key={issue.key}
                    onClick={() => setSelectedKey(issue.key)}
                    className={`w-full text-left p-3 rounded-lg border transition text-xs space-y-1.5 ${
                      isSelected
                        ? 'bg-blue-50/80 border-blue-300 ring-1 ring-blue-400/40 shadow-xs'
                        : 'bg-white border-gray-200 hover:bg-gray-50/80'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-bold font-mono text-blue-700">{issue.key}</span>
                      <span className="text-[10px] px-1.5 py-0.2 rounded font-semibold bg-gray-100 text-gray-600">
                        {issue.status}
                      </span>
                    </div>
                    <p className="font-semibold text-gray-800 line-clamp-2 leading-snug">{issue.summary}</p>
                    <div className="flex items-center justify-between text-[10px] text-gray-400 pt-1">
                      <span>👤 {issue.assignee}</span>
                      <span>📎 {issue.attachment_count} creatives</span>
                    </div>
                  </button>
                );
              })
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
                    </div>
                    <div className="flex flex-wrap items-center gap-3 text-xs text-gray-500">
                      <span>🏢 Sub-Account: <strong className="text-gray-800 uppercase">{brief.account}</strong></span>
                      <span>👤 Reporter: <strong>{brief.reporter}</strong></span>
                      <span>🛠️ Assignee: <strong>{brief.assignee}</strong></span>
                      {brief.duedate && <span>📅 Due Date: <strong>{formatDate(brief.duedate)}</strong></span>}
                    </div>
                  </div>
                    {/* Target Account Selector */}
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
                    {/* Channel-Specific Submit Buttons */}
                    {waTemplates.length > 0 && (
                      <button
                        onClick={() => handleSubmitChannel('whatsapp')}
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
                        onClick={() => handleSubmitChannel('rcs')}
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

                    {/* Master Submit All Button */}
                    <button
                      onClick={() => handleSubmitChannel('all')}
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
                  </div>
                </div>

                {/* Creatives Attachment Strip */}
                {brief.attachments_mapped.length > 0 && (
                  <div className="pt-3 border-t border-gray-100 flex items-center gap-2 overflow-x-auto">
                    <span className="text-[11px] font-semibold text-gray-500 uppercase shrink-0">Creatives Mapped:</span>
                    {brief.attachments_mapped.map((att) => (
                      <span
                        key={att.id || att.filename}
                        className="inline-flex items-center gap-1.5 px-2 py-1 rounded bg-gray-50 border border-gray-200 text-[11px] font-mono text-gray-700 shrink-0"
                        title={att.filename}
                      >
                        <span>{att.target_channel === 'WHATSAPP' ? '🟢 WA' : att.target_channel === 'RCS' ? '🔵 RCS' : '📎'}</span>
                        <span className="max-w-[160px] truncate">{att.filename}</span>
                      </span>
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
                          const isSelected = selectedWa.has(wa.template_name);
                          const isEditing = editingCard[wa.template_name] || false;

                          return (
                            <div
                              key={wa.template_name}
                              className={`p-4 rounded-xl border transition space-y-3 ${
                                isSelected ? 'bg-white border-emerald-300 shadow-xs' : 'bg-gray-50/70 border-gray-200 opacity-60'
                              }`}
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="flex items-center gap-2.5">
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() => toggleSelectWa(wa.template_name)}
                                    className="w-4 h-4 text-emerald-600 rounded border-gray-300 focus:ring-emerald-500 cursor-pointer"
                                  />
                                  {isEditing ? (
                                    <div className="flex items-center gap-1.5">
                                      <label className="text-[10px] uppercase font-bold text-gray-400">Name:</label>
                                      <input
                                        type="text"
                                        value={wa.template_name}
                                        onChange={(e) => updateWaField(idx, 'template_name', e.target.value)}
                                        className="font-mono text-xs font-bold border border-gray-300 rounded px-2 py-1 bg-white"
                                      />
                                    </div>
                                  ) : (
                                    <span className="font-mono font-bold text-xs text-gray-900">{wa.template_name}</span>
                                  )}
                                  <span className="text-[10px] px-2 py-0.2 rounded-full bg-emerald-100 text-emerald-800 font-semibold uppercase">
                                    {wa.category}
                                  </span>
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
                                    onClick={() => toggleEditCard(wa.template_name)}
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

                              {/* Header Creative (Image) */}
                              {wa.header_type === 'IMAGE' && wa.media_filename && (
                                <div className="p-2 bg-gray-50 rounded-lg border border-gray-200 text-[11px] text-gray-600 flex items-center justify-between">
                                  <span className="flex items-center gap-1.5 font-medium">
                                    <span>🖼️ Header Creative:</span>
                                    <strong className="text-gray-900">{wa.media_filename}</strong>
                                  </span>
                                  <span className="text-[10px] text-emerald-600 font-semibold bg-emerald-50 px-1.5 py-0.2 rounded">
                                    Aspect Ratio Verified (16:9)
                                  </span>
                                </div>
                              )}

                              {/* Text Header */}
                              {wa.header_text && (
                                <div className="text-xs font-bold text-gray-900 bg-gray-50 px-3 py-1.5 rounded border border-gray-200/80 flex items-center gap-1.5">
                                  <span className="text-gray-400 text-[10px] font-semibold uppercase">Header:</span>
                                  <span>{wa.header_text}</span>
                                </div>
                              )}

                              {isEditing ? (
                                <div className="space-y-2.5">
                                  {/* Header text edit */}
                                  <div>
                                    <label className="block text-[11px] text-gray-500 mb-1">Header Text (optional):</label>
                                    <input
                                      type="text"
                                      value={wa.header_text || ''}
                                      onChange={(e) => updateWaField(idx, 'header_text', e.target.value)}
                                      placeholder="e.g. Special Festive Offer"
                                      className="w-full text-xs px-2.5 py-1.5 border border-gray-300 rounded bg-white"
                                    />
                                  </div>

                                  <div className="flex items-center justify-between text-[11px] text-gray-500">
                                    <span>Template Body (use {'{{1}}'}, {'{{2}}'} for variables):</span>
                                    <span>{wa.body.length} chars</span>
                                  </div>
                                  <textarea
                                    value={wa.body}
                                    onChange={(e) => updateWaField(idx, 'body', e.target.value)}
                                    rows={5}
                                    className="w-full p-2.5 font-mono text-xs border border-gray-300 rounded-lg bg-white outline-none focus:ring-2 focus:ring-emerald-500"
                                  />

                                  {/* Footer text edit */}
                                  <div>
                                    <label className="block text-[11px] text-gray-500 mb-1">Footer / Disclaimer Text (optional):</label>
                                    <input
                                      type="text"
                                      value={wa.footer_text || ''}
                                      onChange={(e) => updateWaField(idx, 'footer_text', e.target.value)}
                                      placeholder="e.g. *T&C apply. Tata Capital Financial Services Ltd."
                                      className="w-full text-xs px-2.5 py-1.5 border border-gray-300 rounded bg-white"
                                    />
                                  </div>

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
                                            placeholder="https://www.tatacapital.com"
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

                                  {wa.footer_text && (
                                    <div className="text-[11px] text-gray-500 italic px-1">
                                      {wa.footer_text}
                                    </div>
                                  )}

                                  {wa.button_type === 'URL' && (
                                    <div className="flex items-center gap-2 text-xs">
                                      <span className="text-gray-400">CTA Button:</span>
                                      <span className="px-2.5 py-1 rounded bg-blue-50 text-blue-700 font-semibold border border-blue-200/60">
                                        🔗 {wa.button_text || 'Check Offer'} ({wa.button_url || 'https://www.tatacapital.com'})
                                      </span>
                                    </div>
                                  )}

                                  {wa.button_type === 'QUICK_REPLY' && (
                                    <div className="flex items-center gap-2 text-xs">
                                      <span className="text-gray-400">Quick Reply:</span>
                                      <span className="px-2.5 py-1 rounded bg-emerald-50 text-emerald-700 font-semibold border border-emerald-200/60">
                                        ⚡ {wa.button_text || 'Interested'}
                                      </span>
                                    </div>
                                  )}

                                  {wa.button_type === 'PHONE_NUMBER' && (
                                    <div className="flex items-center gap-2 text-xs">
                                      <span className="text-gray-400">Call Button:</span>
                                      <span className="px-2.5 py-1 rounded bg-purple-50 text-purple-700 font-semibold border border-purple-200/60 font-mono">
                                        📞 {wa.button_text || 'Call Us'} ({wa.button_phone || '+919876543210'})
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
                          const isSelected = selectedRcs.has(rcs.template_name);
                          const isEditing = editingCard[rcs.template_name] || false;

                          return (
                            <div
                              key={rcs.template_name}
                              className={`p-4 rounded-xl border transition space-y-3 ${
                                isSelected ? 'bg-white border-blue-300 shadow-xs' : 'bg-gray-50/70 border-gray-200 opacity-60'
                              }`}
                            >
                              <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="flex items-center gap-2.5">
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() => toggleSelectRcs(rcs.template_name)}
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
                                    onClick={() => toggleEditCard(rcs.template_name)}
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

                              {rcs.media_filename && (
                                <div className="p-2 bg-gray-50 rounded-lg border border-gray-200 text-[11px] text-gray-600 flex items-center justify-between">
                                  <span className="flex items-center gap-1.5 font-medium">
                                    <span>🖼️ Card Creative:</span>
                                    <strong className="text-gray-900">{rcs.media_filename}</strong>
                                  </span>
                                </div>
                              )}

                              {isEditing ? (
                                <div className="space-y-2">
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
                                </div>
                              ) : (
                                <div className="bg-white p-3.5 rounded-lg border border-gray-200/80 space-y-1">
                                  <h4 className="font-bold text-xs text-gray-900">{rcs.card_title}</h4>
                                  <p className="font-sans text-xs text-gray-800 whitespace-pre-wrap leading-relaxed">
                                    {rcs.body}
                                  </p>
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
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
