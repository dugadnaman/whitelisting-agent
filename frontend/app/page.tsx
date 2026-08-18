'use client';

import { useState, useEffect, useCallback, useRef, Fragment } from 'react';
import {
  fetchStats,
  fetchTemplates,
  pollPending,
  fetchActivityLogs,
  fetchActivityStats,
} from '@/lib/api';
import type { Stats, Template, ActivityLog, ActivityStats } from '@/lib/api';
import { useApp } from '@/lib/context';
import { formatDate, formatError, relativeTime, truncate } from '@/lib/format';

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
    <span className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${colors[s] || colors.unknown}`}>
      {status || 'unknown'}
    </span>
  );
}

function LiveBadge({ live }: { live?: boolean }) {
  return live ? (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-emerald-50 text-emerald-700 border border-emerald-200" title="Synced live from the Karix WABA">
      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
      Karix Live
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold uppercase tracking-wider bg-gray-50 text-gray-500 border border-gray-200" title="Recorded locally at submission time">
      Local Log
    </span>
  );
}

function ActivityIcon({ action }: { action: string }) {
  const map: Record<string, { bg: string; icon: string }> = {
    TEMPLATE_SUBMISSION: { bg: 'bg-emerald-50 text-emerald-600', icon: 'M4 5h12M9 3v2m1.048 8.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129' },
    TEMPLATE_PREVIEW: { bg: 'bg-blue-50 text-blue-600', icon: 'M15 12a3 3 0 11-6 0 3 3 0 016 0z M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z' },
    STATUS_POLL: { bg: 'bg-purple-50 text-purple-600', icon: 'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15' },
    CREDENTIALS_UPDATE: { bg: 'bg-amber-50 text-amber-600', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z' },
    CREDENTIALS_TEST: { bg: 'bg-indigo-50 text-indigo-600', icon: 'M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z' },
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
  const { account, channel, user } = useApp();
  const [stats, setStats] = useState<Stats | null>(null);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [statsLoading, setStatsLoading] = useState(true);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [polling, setPolling] = useState(false);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [operatorFilter, setOperatorFilter] = useState('all');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [activities, setActivities] = useState<ActivityLog[]>([]);
  const [activityStats, setActivityStats] = useState<ActivityStats | null>(null);
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const [lastSynced, setLastSynced] = useState<string | null>(null);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  // Debounce search input
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);

  const loadStats = useCallback(async () => {
    try {
      const data = await fetchStats(account, channel);
      setStats(data);
      setLastSynced(new Date().toISOString());
      if (data.error) {
        setError(`Karix sync degraded: ${formatError(data.error)}`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch stats');
    } finally {
      setStatsLoading(false);
    }
  }, [account, channel]);

  const loadTemplates = useCallback(async () => {
    try {
      setTemplatesLoading(true);
      const params: { status?: string; search?: string } = {};
      if (statusFilter) params.status = statusFilter;
      if (debouncedSearch) params.search = debouncedSearch;
      const data = await fetchTemplates({ account, channel, ...params });
      setTemplates(data);
      if (data.length > 0 || !debouncedSearch) setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch templates');
    } finally {
      setTemplatesLoading(false);
    }
  }, [account, channel, statusFilter, debouncedSearch]);

  const loadActivity = useCallback(async () => {
    try {
      const [logs, activitySummary] = await Promise.all([
        fetchActivityLogs({ limit: 6 }),
        fetchActivityStats(),
      ]);
      setActivities(logs);
      setActivityStats(activitySummary);
    } catch {
      // Activity feed is non-critical; keep the dashboard alive if it fails
    }
  }, []);

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
    if (autoRefresh) {
      intervalRef.current = setInterval(() => {
        loadStats();
        loadTemplates();
        loadActivity();
      }, 30000);
    }
    return () => {
      clearInterval(intervalRef.current as NodeJS.Timeout);
    };
  }, [autoRefresh, loadStats, loadTemplates, loadActivity]);

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

  // Client-side operator filter (server filters status/search only)
  const operators = Array.from(
    new Set(templates.map(t => t.submitted_by).filter(Boolean) as string[])
  ).sort();
  const visibleTemplates = operatorFilter === 'all'
    ? templates
    : templates.filter(t => (t.submitted_by || '—') === operatorFilter);

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
        { key: 'duplicate', label: 'Duplicate', value: stats?.duplicate ?? 0, color: 'bg-purple-400' },
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
        { key: 'total', label: 'Total Templates', value: total, dot: 'bg-indigo-500', statusValue: '' },
      ];

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-gray-200">
        <div>
          <div className="flex items-center gap-3 flex-wrap">
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
            {/* Connection status chip */}
            {stats?.error ? (
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-red-50 text-red-700 border border-red-200" title={formatError(stats.error)}>
                <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                Karix Degraded
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                Karix Synced{lastSynced ? ` · ${relativeTime(lastSynced)}` : ''}
              </span>
            )}
          </div>
          <p className="text-sm text-gray-500 mt-1">
            Overview of template submission and whitelisting status for {accountLabel} on {channelLabel}.
          </p>
        </div>

        <div className="flex items-center gap-3">
          {channel === 'whatsapp' && (
            <button
              onClick={handlePoll}
              disabled={polling}
              className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold text-indigo-700 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200 transition-colors disabled:opacity-50"
            >
              {polling ? (
                <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                </svg>
              ) : (
                <svg className="w-3.5 h-3.5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
              )}
              {polling ? 'Polling…' : 'Poll Pending'}
            </button>
          )}

          <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(e) => setAutoRefresh(e.target.checked)}
              className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
            />
            Auto-refresh
          </label>
        </div>
      </div>

      {/* Backend error banner */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-start gap-3 text-sm text-red-700">
          <svg className="w-5 h-5 text-red-500 shrink-0 mt-0.5" viewBox="0 0 20 20" fill="currentColor">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" />
          </svg>
          <div className="flex-1">{formatError(error)}</div>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600" aria-label="Dismiss error">&times;</button>
        </div>
      )}

      {/* Clickable KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {kpiCards.map(card => {
          const active = statusFilter === card.statusValue;
          return (
            <button
              key={card.key}
              type="button"
              onClick={() => setStatusFilter(active ? '' : card.statusValue)}
              className={`text-left bg-white rounded-xl border shadow-xs p-4 transition-all cursor-pointer ${
                active ? 'border-indigo-400 ring-2 ring-indigo-100' : 'border-gray-200/80 hover:border-indigo-300 hover:shadow-sm'
              }`}
              title={card.statusValue ? `Filter table: ${card.label}` : 'Show all'}
            >
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2 text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
                  <span className={`w-2 h-2 rounded-full ${card.dot}`} />
                  {card.label}
                </span>
                {active && <span className="text-[10px] font-bold text-indigo-600 uppercase">Filtered</span>}
              </div>
              <div className="text-2xl font-bold text-gray-900 mt-1.5">
                {statsLoading ? <div className="h-8 w-12 bg-gray-200 animate-pulse rounded" /> : card.value}
              </div>
            </button>
          );
        })}
      </div>

      {/* Status distribution bar */}
      {!statsLoading && distTotal > 0 && (
        <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] font-semibold text-gray-500 uppercase tracking-wider">Status Pipeline</span>
            <span className="text-[11px] text-gray-400">{distTotal} template{distTotal === 1 ? '' : 's'}</span>
          </div>
          <div className="flex h-2.5 w-full rounded-full overflow-hidden bg-gray-100">
            {segs.map(seg =>
              seg.value > 0 ? (
                <div
                  key={seg.key}
                  className={`${seg.color} transition-all duration-500`}
                  style={{ width: `${(seg.value / distTotal) * 100}%` }}
                  title={`${seg.label}: ${seg.value}`}
                />
              ) : null
            )}
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2">
            {segs.map(seg => (
              <span key={seg.key} className="flex items-center gap-1.5 text-[11px] text-gray-600">
                <span className={`w-2 h-2 rounded-full ${seg.color}`} />
                {seg.label} <span className="font-bold text-gray-900">{seg.value}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Main grid: table + activity rail */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Left: Templates table */}
        <div className="xl:col-span-2 space-y-4">
          {/* Filters */}
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3 bg-white p-4 rounded-xl border border-gray-200/80 shadow-xs">
            <div className="flex flex-1 items-center gap-3 flex-wrap">
              <div className="relative flex-1 min-w-[200px] max-w-sm">
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

              <select
                value={statusFilter}
                onChange={e => setStatusFilter(e.target.value)}
                className="border border-gray-300 rounded-lg px-3 py-1.5 text-xs font-medium bg-white focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none cursor-pointer"
              >
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
                    <option value="submitted">Submitted</option>
                    <option value="failed">Failed</option>
                    <option value="duplicate">Duplicate</option>
                  </>
                )}
              </select>

              <select
                value={operatorFilter}
                onChange={e => setOperatorFilter(e.target.value)}
                className="border border-gray-300 rounded-lg px-3 py-1.5 text-xs font-medium bg-white focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 outline-none cursor-pointer"
              >
                <option value="all">All Operators</option>
                {operators.map(op => (
                  <option key={op} value={op}>{op}</option>
                ))}
              </select>
            </div>

            <div className="text-xs font-medium text-gray-500 whitespace-nowrap">
              Showing {visibleTemplates.length} of {templates.length}
            </div>
          </div>

          {/* Table */}
          <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="bg-gray-50/80 border-b border-gray-200 text-[11px] font-semibold text-gray-500 uppercase tracking-wider">
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
                <tbody className="divide-y divide-gray-200 text-xs text-gray-800">
                  {templatesLoading ? (
                    <tr>
                      <td colSpan={8} className="px-6 py-12 text-center text-gray-400">
                        <div className="flex items-center justify-center gap-2">
                          <svg className="animate-spin h-4 w-4 text-indigo-600" viewBox="0 0 24 24" fill="none">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                          </svg>
                          Loading templates...
                        </div>
                      </td>
                    </tr>
                  ) : visibleTemplates.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="px-6 py-12 text-center">
                        <div className="flex flex-col items-center gap-3">
                          <div className="w-10 h-10 rounded-full bg-gray-100 flex items-center justify-center text-gray-400">
                            <svg className="w-5 h-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
                              <path d="M10 3v10M6 9l4 4 4-4M3 15h14" />
                            </svg>
                          </div>
                          <div className="text-sm font-semibold text-gray-700">
                            {stats?.error
                              ? 'Karix connection degraded — showing local history only'
                              : `No ${channelLabel} templates found for ${accountLabel}.`}
                          </div>
                          <p className="text-xs text-gray-400 max-w-xs text-center">
                            {stats?.error
                              ? 'Check credentials in Settings, then refresh.'
                              : 'Upload a spreadsheet on the Submit Templates page to whitelist your first template.'}
                          </p>
                          {!stats?.error && (
                            <a
                              href="/submit"
                              className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 mt-1 inline-flex items-center gap-1"
                            >
                              Go to Submit Templates →
                            </a>
                          )}
                        </div>
                      </td>
                    </tr>
                  ) : (
                    visibleTemplates.map((t, idx) => {
                      const key = t.source_ref || t.template_name || `row-${idx}`;
                      const isExpanded = expandedRow === key;
                      const rejectionReason = t.approval_reason && String(t.approval_reason) !== 'NONE' ? String(t.approval_reason) : null;
                      const pipelineError = t.status === 'failed' && t.error ? formatError(t.error) : null;

                      return (
                        <Fragment key={key}>
                          <tr
                            onClick={() => toggleRow(key)}
                            role="button"
                            tabIndex={0}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter' || e.key === ' ') {
                                e.preventDefault();
                                toggleRow(key);
                              }
                            }}
                            className={`hover:bg-gray-50/70 transition-colors cursor-pointer ${isExpanded ? 'bg-indigo-50/30' : ''}`}
                          >
                            <td className="px-4 py-3">
                              <div className="flex items-center gap-2">
                                <span className="font-semibold text-gray-900 font-mono text-[11px]">{t.template_name}</span>
                                <LiveBadge live={t.live} />
                              </div>
                              <div className="text-[10px] text-gray-400 font-mono mt-0.5">
                                {channel === 'whatsapp' ? (t.provider_ref_id ? `ID ${t.provider_ref_id}` : 'Not submitted yet') : (t.template_id ? `DLT ${t.template_id}` : '')}
                              </div>
                            </td>

                            {channel === 'whatsapp' && (
                              <td className="px-4 py-3 text-gray-600">{getCategory(t)}</td>
                            )}

                            {channel !== 'whatsapp' && (
                              <td className="px-4 py-3 text-gray-600">
                                <div className="font-medium">{t.template_type || '—'}</div>
                                {Array.isArray(t.sender_ids) && t.sender_ids.length > 0 && (
                                  <div className="text-[10px] text-gray-400">{t.sender_ids.join(', ')}</div>
                                )}
                              </td>
                            )}

                            <td className="px-4 py-3">
                              <StatusBadge status={t.status} />
                            </td>

                            <td className="px-4 py-3">
                              <StatusBadge status={t.approval_status || 'unknown'} />
                              {rejectionReason && (
                                <div className="text-[10px] text-red-600 mt-1 max-w-[180px] truncate" title={rejectionReason}>
                                  {truncate(rejectionReason, 60)}
                                </div>
                              )}
                              {pipelineError && (
                                <div className="text-[10px] text-rose-600 mt-1 max-w-[180px] truncate" title={pipelineError}>
                                  {truncate(pipelineError, 60)}
                                </div>
                              )}
                            </td>

                            <td className="px-4 py-3">
                              {t.submitted_by ? (
                                <span className="inline-flex items-center gap-1.5">
                                  <span className="w-5 h-5 rounded-full bg-indigo-100 text-indigo-700 font-bold text-[10px] flex items-center justify-center shrink-0">
                                    {t.submitted_by.charAt(0).toUpperCase()}
                                  </span>
                                  <span className="text-[11px] font-semibold text-gray-700 truncate">{t.submitted_by}</span>
                                </span>
                              ) : (
                                <span className="text-[11px] text-gray-400">Karix Sync</span>
                              )}
                            </td>

                            {channel === 'whatsapp' && (
                              <td className="px-4 py-3">
                                {t.source_file ? (
                                  <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-gray-50 border border-gray-200 text-[10px] font-mono text-gray-600 max-w-[130px] truncate" title={t.source_file}>
                                    {truncate(t.source_file, 20)}
                                  </span>
                                ) : (
                                  <span className="text-[11px] text-gray-300">—</span>
                                )}
                              </td>
                            )}

                            <td className="px-4 py-3 text-gray-500 whitespace-nowrap">
                              {formatDate(t.submitted_at)}
                            </td>

                            <td className="px-4 py-3 text-right font-medium text-indigo-600 whitespace-nowrap">
                              {isExpanded ? '▲ Hide' : '▼ Details'}
                            </td>
                          </tr>

                          {/* Expandable detail panel */}
                          {isExpanded && (
                            <tr className="bg-gray-50/90 border-b border-gray-200">
                              <td colSpan={8} className="px-6 py-4">
                                <div className="space-y-3">
                                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-xs">
                                    <div>
                                      <span className="font-semibold text-gray-500">Template ID: </span>
                                      <span className="font-mono text-gray-800">
                                        {channel === 'whatsapp' ? (t.provider_ref_id || '—') : (t.template_id || '—')}
                                      </span>
                                    </div>
                                    <div>
                                      <span className="font-semibold text-gray-500">Operator: </span>
                                      <span className="text-gray-800">{t.submitted_by || 'Karix Sync'}</span>
                                    </div>
                                    <div>
                                      <span className="font-semibold text-gray-500">Source File: </span>
                                      <span className="font-mono text-gray-800">{t.source_file || '—'}</span>
                                    </div>
                                    <div>
                                      <span className="font-semibold text-gray-500">Record: </span>
                                      <LiveBadge live={t.live} />
                                    </div>
                                  </div>

                                  {pipelineError && (
                                    <div className="p-2.5 bg-red-50 border border-red-200 rounded text-red-700 text-xs">
                                      <span className="font-semibold">Pipeline Error: </span>
                                      {pipelineError}
                                    </div>
                                  )}

                                  {rejectionReason && (
                                    <div className="p-2.5 bg-amber-50 border border-amber-200 rounded text-amber-800 text-xs">
                                      <span className="font-semibold">Meta Rejection Reason: </span>
                                      {rejectionReason}
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

        {/* Right rail: live team activity */}
        <div className="space-y-6">
          {/* Operator leaderboard */}
          <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xs font-bold text-gray-900 uppercase tracking-wider">Team Activity</h3>
              <span className="text-[11px] text-gray-400">{activityStats?.total_users ?? 0} operators</span>
            </div>
            {activityStats && activityStats.user_activity.length > 0 ? (
              <div className="space-y-3">
                {activityStats.user_activity.slice(0, 4).map(u => (
                  <div key={u.user} className="flex items-center gap-2.5">
                    <span className="w-6 h-6 rounded-full bg-indigo-600 text-white font-bold text-[11px] flex items-center justify-center shrink-0">
                      {u.user.charAt(0).toUpperCase()}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-gray-900 truncate">{u.user}</span>
                        <span className="text-[10px] text-gray-400 font-medium">{u.actions} action{u.actions === 1 ? '' : 's'}</span>
                      </div>
                      <div className="h-1 bg-gray-100 rounded-full mt-1">
                        <div
                          className="h-1 bg-indigo-500 rounded-full transition-all duration-500"
                          style={{ width: `${Math.min(100, (u.actions / Math.max(1, activityStats.total_actions)) * 100)}%` }}
                        />
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-gray-400">No team activity recorded yet.</p>
            )}
          </div>

          {/* Recent activity feed */}
          <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-5">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-xs font-bold text-gray-900 uppercase tracking-wider">Live Feed</h3>
              <a href="/activity" className="text-[11px] font-semibold text-indigo-600 hover:text-indigo-800">
                View all →
              </a>
            </div>
            {activities.length > 0 ? (
              <div className="space-y-3">
                {activities.map(a => (
                  <div key={a.id} className="flex items-start gap-2.5">
                    <ActivityIcon action={a.action} />
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-gray-800">
                        <span className="font-semibold">{a.user}</span>{' '}
                        {a.action === 'TEMPLATE_SUBMISSION' && <>submitted {a.details.count ?? 0} template{(a.details.count ?? 0) === 1 ? '' : 's'}</>}
                        {a.action === 'TEMPLATE_PREVIEW' && <>previewed {a.details.filename || 'a file'}</>}
                        {a.action === 'STATUS_POLL' && <>polled {a.details.checked_count ?? 0} pending</>}
                        {a.action === 'CREDENTIALS_UPDATE' && <>updated credentials</>}
                        {a.action === 'CREDENTIALS_TEST' && <>tested credentials</>}
                      </p>
                      <p className="text-[10px] text-gray-400 mt-0.5">
                        {a.account === 'tata' ? 'Tata Capital' : 'Bajaj'} • {a.channel === 'whatsapp' ? 'WhatsApp' : 'RCS'} • {relativeTime(a.timestamp)}
                      </p>
                    </div>
                    <span className={`w-1.5 h-1.5 rounded-full mt-1 shrink-0 ${a.status === 'success' ? 'bg-emerald-500' : 'bg-red-500'}`} />
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-gray-400">Waiting for team activity…</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
