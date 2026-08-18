'use client';

import { useState, useEffect, useCallback, useRef, Fragment } from 'react';
import { fetchStats, fetchTemplates, pollPending } from '@/lib/api';
import type { Stats, Template } from '@/lib/api';
import { useApp } from '@/lib/context';

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: 'bg-amber-100 text-amber-800 border border-amber-200',
    approved: 'bg-green-100 text-green-800 border border-green-200',
    rejected: 'bg-red-100 text-red-800 border border-red-200',
    failed: 'bg-red-100 text-red-800 border border-red-200',
    submitted: 'bg-blue-100 text-blue-800 border border-blue-200',
    duplicate: 'bg-purple-100 text-purple-800 border border-purple-200',
    unknown: 'bg-gray-100 text-gray-800 border border-gray-200',
  };
  const s = (status || 'unknown').toLowerCase();
  return (
    <span className={`inline-flex px-2.5 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wider ${colors[s] || colors.unknown}`}>
      {status}
    </span>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    });
  } catch {
    return iso;
  }
}

function formatError(err: unknown): string {
  if (!err) return '';
  if (typeof err === 'string') {
    const s = err.trim();
    if (s.startsWith('HTTP ') && s.includes(':')) {
      const rest = s.split(':').slice(1).join(':').trim();
      const cleaned = formatError(rest);
      if (cleaned && cleaned !== rest) return cleaned;
    }
    const matchUser = s.match(/"error_user_msg"\s*:\s*"([^"]+)"/);
    if (matchUser) return matchUser[1];
    const matchMsg = s.match(/"message"\s*:\s*"([^"]+)"/);
    if (matchMsg && !matchMsg[1].includes('Invalid parameter')) return matchMsg[1];
    return s;
  }
  if (typeof err === 'object') {
    const anyErr = err as Record<string, unknown>;
    if (anyErr.error_user_msg) return String(anyErr.error_user_msg);
    if (anyErr.errorMessage) return formatError(anyErr.errorMessage);
    if (anyErr.error && typeof anyErr.error === 'object') {
      const nested = anyErr.error as Record<string, unknown>;
      return String(nested.error_user_msg || nested.message || JSON.stringify(nested));
    }
    if (anyErr.error) return formatError(anyErr.error);
    if (anyErr.message) return String(anyErr.message);
    if (anyErr.reason) return formatError(anyErr.reason);
    try {
      return JSON.stringify(err);
    } catch {
      return String(err);
    }
  }
  return String(err);
}

export default function DashboardPage() {
  const { account, channel } = useApp();
  const [stats, setStats] = useState<Stats | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [statsLoading, setStatsLoading] = useState(true);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [polling, setPolling] = useState(false);
  const [search, setSearch] = useState('');
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Debounce search input
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(timer);
  }, [search]);

  // Reset status filter when channel changes
  useEffect(() => {
    setStatusFilter('');
    setExpandedRow(null);
  }, [account, channel]);

  // Fetch stats
  const loadStats = useCallback(async () => {
    try {
      setStatsLoading(true);
      const data = await fetchStats(account, channel);
      setStats(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch stats');
    } finally {
      setStatsLoading(false);
    }
  }, [account, channel]);

  // Fetch templates
  const loadTemplates = useCallback(async () => {
    try {
      setTemplatesLoading(true);
      const params: { status?: string; search?: string } = {};
      if (statusFilter) params.status = statusFilter;
      if (debouncedSearch) params.search = debouncedSearch;
      const data = await fetchTemplates({
        account,
        channel,
        ...params,
      });
      setTemplates(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch templates');
    } finally {
      setTemplatesLoading(false);
    }
  }, [account, channel, statusFilter, debouncedSearch]);

  // Initial load + refetch on filter/context changes
  useEffect(() => {
    loadStats();
  }, [loadStats]);

  useEffect(() => {
    loadTemplates();
  }, [loadTemplates]);

  // Auto-refresh
  useEffect(() => {
    if (autoRefresh) {
      intervalRef.current = setInterval(() => {
        loadStats();
        loadTemplates();
      }, 30000);
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [autoRefresh, loadStats, loadTemplates]);

  // Poll pending handler (WhatsApp only)
  const handlePoll = async () => {
    try {
      setPolling(true);
      await pollPending(account, channel);
      await Promise.all([loadStats(), loadTemplates()]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to poll pending');
    } finally {
      setPolling(false);
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

  const accountLabel = account === 'bajaj' ? 'Bajaj' : 'Tata Capital';
  const channelLabel = channel === 'whatsapp' ? 'WhatsApp' : 'RCS (DLT)';

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-gray-200">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
            <span
              className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                channel === 'whatsapp'
                  ? 'bg-emerald-100 text-emerald-800 border border-emerald-200'
                  : 'bg-blue-100 text-blue-800 border border-blue-200'
              }`}
            >
              {accountLabel} &bull; {channelLabel}
            </span>
          </div>
          <p className="text-sm text-gray-500 mt-1">
            Overview of template submission and whitelisting status for {accountLabel} on {channelLabel}.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Auto-refresh toggle */}
          <label className="inline-flex items-center gap-2 text-xs font-medium text-gray-600 cursor-pointer select-none bg-white px-3 py-2 rounded-lg border border-gray-200 shadow-xs">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={e => setAutoRefresh(e.target.checked)}
              className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 h-3.5 w-3.5"
            />
            Auto-refresh (30s)
          </label>

          {/* Poll Pending Button (WhatsApp only) */}
          {channel === 'whatsapp' && (
            <button
              onClick={handlePoll}
              disabled={polling}
              className="inline-flex items-center gap-2 bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 px-3.5 py-2 rounded-lg text-xs font-semibold shadow-xs transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {polling ? (
                <>
                  <svg className="animate-spin h-3.5 w-3.5 text-gray-500" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                  </svg>
                  Polling Karix...
                </>
              ) : (
                <>
                  <svg className="w-3.5 h-3.5 text-gray-500" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
                    <path d="M4 4v5h5M16 16v-5h-5" />
                    <path d="M4.5 9A7 7 0 0 1 16 7.5M15.5 11A7 7 0 0 1 4 12.5" />
                  </svg>
                  Poll Pending
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Error Alert */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-start gap-3 text-sm text-red-700">
          <svg className="w-5 h-5 text-red-500 shrink-0 mt-0.5" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
          </svg>
          <div className="flex-1">
            <span className="font-semibold">Error: </span>
            {error}
          </div>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600">
            &times;
          </button>
        </div>
      )}

      {/* Stats Cards Row */}
      {channel === 'whatsapp' ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {/* Card 1: Total Submitted */}
          <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-5">
            <div className="flex items-center gap-2 text-xs font-semibold text-gray-500 uppercase tracking-wider">
              <span className="w-2 h-2 rounded-full bg-indigo-600" />
              Total Logged
            </div>
            <div className="text-3xl font-bold text-gray-900 mt-2">
              {statsLoading ? <div className="h-9 w-16 bg-gray-200 animate-pulse rounded" /> : stats?.total ?? 0}
            </div>
          </div>

          {/* Card 2: Pending Review */}
          <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-5">
            <div className="flex items-center gap-2 text-xs font-semibold text-gray-500 uppercase tracking-wider">
              <span className="w-2 h-2 rounded-full bg-amber-500" />
              Pending Review
            </div>
            <div className="text-3xl font-bold text-gray-900 mt-2">
              {statsLoading ? <div className="h-9 w-16 bg-gray-200 animate-pulse rounded" /> : stats?.pending ?? 0}
            </div>
          </div>

          {/* Card 3: Approved */}
          <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-5">
            <div className="flex items-center gap-2 text-xs font-semibold text-gray-500 uppercase tracking-wider">
              <span className="w-2 h-2 rounded-full bg-green-500" />
              Approved
            </div>
            <div className="text-3xl font-bold text-gray-900 mt-2">
              {statsLoading ? <div className="h-9 w-16 bg-gray-200 animate-pulse rounded" /> : stats?.approved ?? 0}
            </div>
          </div>

          {/* Card 4: Rejected / Failed */}
          <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-5">
            <div className="flex items-center gap-2 text-xs font-semibold text-gray-500 uppercase tracking-wider">
              <span className="w-2 h-2 rounded-full bg-red-500" />
              Rejected / Failed
            </div>
            <div className="text-3xl font-bold text-gray-900 mt-2">
              {statsLoading ? (
                <div className="h-9 w-16 bg-gray-200 animate-pulse rounded" />
              ) : (
                (stats?.rejected ?? 0) + (stats?.failed ?? 0)
              )}
            </div>
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-5">
          {/* Card 1: Total Registered */}
          <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-5">
            <div className="flex items-center gap-2 text-xs font-semibold text-gray-500 uppercase tracking-wider">
              <span className="w-2 h-2 rounded-full bg-indigo-600" />
              Total Logged
            </div>
            <div className="text-3xl font-bold text-gray-900 mt-2">
              {statsLoading ? <div className="h-9 w-16 bg-gray-200 animate-pulse rounded" /> : stats?.total ?? 0}
            </div>
          </div>

          {/* Card 2: Submitted / Active */}
          <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-5">
            <div className="flex items-center gap-2 text-xs font-semibold text-gray-500 uppercase tracking-wider">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              Submitted
            </div>
            <div className="text-3xl font-bold text-gray-900 mt-2">
              {statsLoading ? <div className="h-9 w-16 bg-gray-200 animate-pulse rounded" /> : stats?.submitted ?? 0}
            </div>
          </div>

          {/* Card 3: Duplicates */}
          <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-5">
            <div className="flex items-center gap-2 text-xs font-semibold text-gray-500 uppercase tracking-wider">
              <span className="w-2 h-2 rounded-full bg-purple-500" />
              Duplicate
            </div>
            <div className="text-3xl font-bold text-gray-900 mt-2">
              {statsLoading ? <div className="h-9 w-16 bg-gray-200 animate-pulse rounded" /> : stats?.duplicate ?? 0}
            </div>
          </div>

          {/* Card 4: Failed */}
          <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-5">
            <div className="flex items-center gap-2 text-xs font-semibold text-gray-500 uppercase tracking-wider">
              <span className="w-2 h-2 rounded-full bg-red-500" />
              Failed
            </div>
            <div className="text-3xl font-bold text-gray-900 mt-2">
              {statsLoading ? <div className="h-9 w-16 bg-gray-200 animate-pulse rounded" /> : stats?.failed ?? 0}
            </div>
          </div>
        </div>
      )}

      {/* Filters Row */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 bg-white p-4 rounded-xl border border-gray-200/80 shadow-xs">
        <div className="flex flex-1 items-center gap-3">
          {/* Search Input */}
          <div className="relative flex-1 max-w-sm">
            <svg className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
              <circle cx="9" cy="9" r="6" />
              <path d="M13.5 13.5L17 17" />
            </svg>
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={channel === 'whatsapp' ? 'Search templates or ref IDs...' : 'Search by name, DLT ID, or sender...'}
              className="w-full pl-9 pr-3 py-1.5 text-xs bg-gray-50/50 border border-gray-300 rounded-lg focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none transition-colors"
            />
          </div>

          {/* Status Filter */}
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="border border-gray-300 rounded-lg px-3 py-1.5 text-xs font-medium bg-white focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none cursor-pointer"
          >
            {channel === 'whatsapp' ? (
              <>
                <option value="">All Statuses</option>
                <option value="pending">Pending Review</option>
                <option value="approved">Approved</option>
                <option value="rejected">Rejected</option>
                <option value="failed">Submission Failed</option>
              </>
            ) : (
              <>
                <option value="">All Statuses</option>
                <option value="submitted">Submitted</option>
                <option value="failed">Failed</option>
                <option value="duplicate">Duplicate</option>
              </>
            )}
          </select>
        </div>

        <div className="text-xs font-medium text-gray-500">
          Showing {templates.length} template{templates.length === 1 ? '' : 's'}
        </div>
      </div>

      {/* Templates Table */}
      <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-gray-50/80 border-b border-gray-200 text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
                {channel === 'whatsapp' ? (
                  <>
                    <th className="px-5 py-3.5">Template Name</th>
                    <th className="px-5 py-3.5">Category</th>
                    <th className="px-5 py-3.5">Submit Status</th>
                    <th className="px-5 py-3.5">Approval</th>
                    <th className="px-5 py-3.5">Submitted At</th>
                    <th className="px-5 py-3.5 text-right">Details</th>
                  </>
                ) : (
                  <>
                    <th className="px-5 py-3.5">Template Name</th>
                    <th className="px-5 py-3.5">DLT Template ID</th>
                    <th className="px-5 py-3.5">Type</th>
                    <th className="px-5 py-3.5">Sender IDs</th>
                    <th className="px-5 py-3.5">Status</th>
                    <th className="px-5 py-3.5">Submitted At</th>
                    <th className="px-5 py-3.5 text-right">Details</th>
                  </>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200 text-xs text-gray-800">
              {templatesLoading ? (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center text-gray-400">
                    <div className="flex items-center justify-center gap-2">
                      <svg className="animate-spin h-4 w-4 text-indigo-600" viewBox="0 0 24 24" fill="none">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                      </svg>
                      Loading templates...
                    </div>
                  </td>
                </tr>
              ) : templates.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-6 py-12 text-center text-gray-400">
                    No {channelLabel} templates found for {accountLabel}.
                  </td>
                </tr>
              ) : (
                templates.map((t, idx) => {
                  const key = t.source_ref || t.template_name || `row-${idx}`;
                  const isExpanded = expandedRow === key;

                  return (
                    <Fragment key={key}>
                      <tr
                        onClick={() => toggleRow(key)}
                        className={`hover:bg-gray-50/70 transition-colors cursor-pointer ${isExpanded ? 'bg-indigo-50/30' : ''}`}
                      >
                        {channel === 'whatsapp' ? (
                          <>
                            <td className="px-5 py-3.5 font-semibold text-gray-900 font-mono text-[11px]">
                              {t.template_name}
                            </td>
                            <td className="px-5 py-3.5 text-gray-600">
                              {getCategory(t)}
                            </td>
                            <td className="px-5 py-3.5">
                              <StatusBadge status={t.status} />
                            </td>
                            <td className="px-5 py-3.5">
                              <StatusBadge status={t.approval_status || 'unknown'} />
                            </td>
                            <td className="px-5 py-3.5 text-gray-500">
                              {formatDate(t.submitted_at)}
                            </td>
                          </>
                        ) : (
                          <>
                            <td className="px-5 py-3.5 font-semibold text-gray-900 font-mono text-[11px]">
                              {t.template_name}
                            </td>
                            <td className="px-5 py-3.5 font-mono text-gray-600 text-[11px]">
                              {t.template_id || '—'}
                            </td>
                            <td className="px-5 py-3.5 text-gray-600">
                              {t.template_type || '—'}
                            </td>
                            <td className="px-5 py-3.5 text-gray-600">
                              {Array.isArray(t.sender_ids) ? t.sender_ids.join(', ') : t.sender_ids || '—'}
                            </td>
                            <td className="px-5 py-3.5">
                              <StatusBadge status={t.status} />
                            </td>
                            <td className="px-5 py-3.5 text-gray-500">
                              {formatDate(t.submitted_at)}
                            </td>
                          </>
                        )}
                        <td className="px-5 py-3.5 text-right font-medium text-indigo-600">
                          {isExpanded ? '▲ Hide' : '▼ Details'}
                        </td>
                      </tr>

                      {/* Expandable Detail Panel */}
                      {isExpanded && (
                        <tr className="bg-gray-50/90 border-b border-gray-200">
                          <td colSpan={7} className="px-6 py-4">
                            <div className="space-y-3">
                              {channel === 'whatsapp' ? (
                                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                                  <div>
                                    <span className="font-semibold text-gray-500">Source Ref: </span>
                                    <span className="font-mono text-gray-800">{t.source_ref || '—'}</span>
                                  </div>
                                  <div>
                                    <span className="font-semibold text-gray-500">Provider Ref ID: </span>
                                    <span className="font-mono text-gray-800">{t.provider_ref_id || '—'}</span>
                                  </div>
                                  <div>
                                    <span className="font-semibold text-gray-500">Retries: </span>
                                    <span className="text-gray-800">{t.retry_count}</span>
                                  </div>
                                </div>
                              ) : (
                                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
                                  <div>
                                    <span className="font-semibold text-gray-500">DLT Template ID: </span>
                                    <span className="font-mono text-gray-800">{t.template_id || '—'}</span>
                                  </div>
                                  <div>
                                    <span className="font-semibold text-gray-500">Entity ID: </span>
                                    <span className="font-mono text-gray-800">{t.entity_id || '110100001654'}</span>
                                  </div>
                                  <div>
                                    <span className="font-semibold text-gray-500">Message Type: </span>
                                    <span className="text-gray-800">{t.template_message_type || 'Text'}</span>
                                  </div>
                                </div>
                              )}

                              {t.error && (
                                <div className="p-2.5 bg-red-50 border border-red-200 rounded text-red-700 text-xs">
                                  <span className="font-semibold">Error: </span>
                                  {formatError(t.error)}
                                </div>
                              )}

                              {t.approval_reason && (
                                <div className="p-2.5 bg-amber-50 border border-amber-200 rounded text-amber-800 text-xs">
                                  <span className="font-semibold">Approval Reason: </span>
                                  {formatError(t.approval_reason)}
                                </div>
                              )}

                              {t.template_message && (
                                <div>
                                  <div className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-1">
                                    DLT Template Content
                                  </div>
                                  <div className="p-3 bg-white border border-gray-200 rounded-lg text-xs font-mono text-gray-800 whitespace-pre-wrap">
                                    {t.template_message}
                                  </div>
                                </div>
                              )}

                              {t.provider_response && Object.keys(t.provider_response).length > 0 && (
                                <div>
                                  <div className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider mb-1">
                                    Raw Provider Response
                                  </div>
                                  <pre className="bg-gray-900 text-gray-100 p-3 rounded-lg text-[11px] font-mono overflow-x-auto max-h-48">
                                    {JSON.stringify(t.provider_response, null, 2)}
                                  </pre>
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
    </div>
  );
}
