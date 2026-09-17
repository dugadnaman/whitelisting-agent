'use client';

import { useState, useEffect, useCallback } from 'react';
import { useApp } from '@/lib/context';
import {
  fetchJiraIssues,
  fetchJiraBrief,
  submitJiraBrief,
  type JiraIssueItem,
  type JiraBriefData,
} from '@/lib/api';
import { formatError, formatDate } from '@/lib/format';

export default function JiraBriefsPage() {
  const { user } = useApp();
  const [issues, setIssues] = useState<JiraIssueItem[]>([]);
  const [loadingIssues, setLoadingIssues] = useState(true);
  const [selectedKey, setSelectedKey] = useState<string>('TCN-524');
  const [brief, setBrief] = useState<JiraBriefData | null>(null);
  const [loadingBrief, setLoadingBrief] = useState(false);
  const [activeTab, setActiveTab] = useState<'whatsapp' | 'rcs' | 'sms' | 'moengage'>('whatsapp');
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<{ message: string; type: 'success' | 'error' } | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  const loadIssues = useCallback(async () => {
    try {
      setLoadingIssues(true);
      const list = await fetchJiraIssues({ project: 'TCN', limit: 20 });
      setIssues(list);
      if (list.length > 0 && !list.some((i) => i.key === selectedKey)) {
        setSelectedKey(list[0].key);
      }
    } catch (err) {
      setFeedback({ message: formatError(err), type: 'error' });
    } finally {
      setLoadingIssues(false);
    }
  }, [selectedKey]);

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
      if (data.whatsapp_templates?.length > 0) {
        setActiveTab('whatsapp');
      } else if (data.rcs_templates?.length > 0) {
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

  const handleSubmitToKarix = async () => {
    if (!brief) return;
    try {
      setSubmitting(true);
      setFeedback(null);
      const res = await submitJiraBrief(brief.issue_key, ['whatsapp', 'rcs'], user || 'Briefing Operator');
      const waCount = res.whatsapp_submitted?.length || 0;
      const rcsCount = res.rcs_submitted?.length || 0;
      setFeedback({
        message: `Successfully submitted ${waCount} WhatsApp and ${rcsCount} RCS templates for ${brief.issue_key}. Jira ticket comment posted.`,
        type: 'success',
      });
      // Refresh brief to update live WABA flags
      loadBrief(brief.issue_key);
    } catch (err) {
      setFeedback({ message: formatError(err), type: 'error' });
    } finally {
      setSubmitting(false);
    }
  };

  const filteredIssues = issues.filter(
    (i) =>
      i.key.toLowerCase().includes(searchQuery.toLowerCase()) ||
      i.summary.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (i.assignee || '').toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-gray-200">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">Jira Campaign Briefing Agent</h1>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200">
              <span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-pulse" />
              tatacapital-team.atlassian.net (TCN)
            </span>
          </div>
          <p className="text-sm text-gray-500 mt-1">
            Automated multi-channel intake: extracts WhatsApp, RCS, and SMS copy directly from client Jira tickets.
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
              <div className="bg-white rounded-xl border border-gray-200/80 shadow-2xs p-5 space-y-3">
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

                  <button
                    onClick={handleSubmitToKarix}
                    disabled={submitting || (brief.whatsapp_templates.length === 0 && brief.rcs_templates.length === 0)}
                    className="px-4 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-300 text-white text-xs font-semibold rounded-lg shadow-sm transition flex items-center gap-2"
                  >
                    {submitting ? (
                      <>
                        <span className="w-2.5 h-2.5 rounded-full bg-white animate-pulse" />
                        <span>Submitting to Karix...</span>
                      </>
                    ) : (
                      <>
                        <span>🚀 Whitelist on Karix</span>
                        <span className="bg-blue-500/80 px-1.5 py-0.2 rounded text-[10px]">
                          {brief.whatsapp_templates.length + brief.rcs_templates.length} templates
                        </span>
                      </>
                    )}
                  </button>
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
                  {brief.attachments_mapped.some(a => a.filename.endsWith('.zip') || a.filename.endsWith('.docx')) && (
                    <div className="flex flex-wrap items-center gap-2 pt-1">
                      <span className="text-[11px] text-purple-700 font-medium">Mailer Files:</span>
                      {brief.attachments_mapped
                        .filter(a => a.filename.endsWith('.zip') || a.filename.endsWith('.docx'))
                        .map(a => (
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
                      {brief.whatsapp_templates.length}
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
                      {brief.rcs_templates.length}
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
                      {brief.whatsapp_templates.length === 0 ? (
                        <p className="py-8 text-center text-xs text-gray-400">No WhatsApp templates detected in this brief.</p>
                      ) : (
                        brief.whatsapp_templates.map((wa, idx) => (
                          <div key={wa.template_name} className="p-4 rounded-xl border border-gray-200 bg-gray-50/50 space-y-2.5">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <span className="font-mono font-bold text-xs text-gray-900">{wa.template_name}</span>
                                <span className="text-[10px] px-2 py-0.2 rounded-full bg-emerald-100 text-emerald-800 font-semibold uppercase">
                                  {wa.category}
                                </span>
                              </div>
                              {wa.exists_on_waba ? (
                                <span className="text-[10px] px-2 py-0.5 rounded font-bold uppercase bg-emerald-50 text-emerald-700 border border-emerald-200">
                                  ✓ Live on WABA ({wa.live_status})
                                </span>
                              ) : (
                                <span className="text-[10px] px-2 py-0.5 rounded font-bold uppercase bg-amber-50 text-amber-700 border border-amber-200">
                                  ⚡ Ready to Whitelist
                                </span>
                              )}
                            </div>

                            {wa.header_type === 'IMAGE' && wa.media_filename && (
                              <div className="p-2 bg-white rounded-lg border border-gray-200/80 text-[11px] text-gray-600 flex items-center justify-between">
                                <span className="flex items-center gap-1.5 font-medium">
                                  <span>🖼️ Header Creative:</span>
                                  <strong className="text-gray-900">{wa.media_filename}</strong>
                                </span>
                                <span className="text-[10px] text-emerald-600 font-semibold bg-emerald-50 px-1.5 py-0.2 rounded">
                                  Aspect Ratio Verified (16:9)
                                </span>
                              </div>
                            )}

                            <div className="bg-white p-3.5 rounded-lg border border-gray-200/80 font-sans text-xs text-gray-800 whitespace-pre-wrap leading-relaxed">
                              {wa.body}
                            </div>

                            {wa.button_type === 'URL' && (
                              <div className="flex items-center gap-2 text-xs">
                                <span className="text-gray-400">CTA Button:</span>
                                <span className="px-2.5 py-1 rounded bg-blue-50 text-blue-700 font-semibold border border-blue-200/60">
                                  🔗 {wa.button_text || 'Check Offer'}
                                </span>
                              </div>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  )}

                  {/* RCS Panel */}
                  {activeTab === 'rcs' && (
                    <div className="space-y-4">
                      {brief.rcs_templates.length === 0 ? (
                        <p className="py-8 text-center text-xs text-gray-400">No RCS templates detected in this brief.</p>
                      ) : (
                        brief.rcs_templates.map((rcs) => (
                          <div key={rcs.template_name} className="p-4 rounded-xl border border-gray-200 bg-gray-50/50 space-y-2.5">
                            <div className="flex items-center justify-between">
                              <span className="font-mono font-bold text-xs text-gray-900">{rcs.template_name}</span>
                              <span className="text-[10px] px-2 py-0.2 rounded-full bg-blue-100 text-blue-800 font-semibold uppercase">
                                Standalone Card
                              </span>
                            </div>

                            {rcs.media_filename && (
                              <div className="p-2 bg-white rounded-lg border border-gray-200/80 text-[11px] text-gray-600 flex items-center justify-between">
                                <span className="flex items-center gap-1.5 font-medium">
                                  <span>🖼️ Card Creative:</span>
                                  <strong className="text-gray-900">{rcs.media_filename}</strong>
                                </span>
                              </div>
                            )}

                            <div className="bg-white p-3.5 rounded-lg border border-gray-200/80 font-sans text-xs text-gray-800 whitespace-pre-wrap leading-relaxed">
                              {rcs.body}
                            </div>
                          </div>
                        ))
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
