'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { fetchActivityLogs, fetchActivityStats } from '@/lib/api';
import type { ActivityLog, ActivityStats, Account, Channel } from '@/lib/api';
import { useApp } from '@/lib/context';
import { formatChannel } from '@/lib/format';

function formatTimestamp(iso: string): { relative: string; exact: string } {
  if (!iso) return { relative: '—', exact: '—' };
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffSec = Math.floor((now.getTime() - d.getTime()) / 1000);

    let relative = '';
    if (diffSec < 60) relative = 'Just now';
    else if (diffSec < 3600) relative = `${Math.floor(diffSec / 60)}m ago`;
    else if (diffSec < 86400) relative = `${Math.floor(diffSec / 3600)}h ago`;
    else relative = `${Math.floor(diffSec / 86400)}d ago`;

    const exact = d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      second: '2-digit',
      hour12: true,
    });

    return { relative, exact };
  } catch {
    return { relative: iso, exact: iso };
  }
}

function ActionBadge({ action }: { action: string }) {
  const map: Record<string, { label: string; color: string }> = {
    TEMPLATE_SUBMISSION: { label: 'Template Submit', color: 'bg-emerald-100 text-emerald-800 border-emerald-200' },
    TEMPLATE_PREVIEW: { label: 'File Preview', color: 'bg-blue-100 text-blue-800 border-blue-200' },
    STATUS_POLL: { label: 'Status Poll', color: 'bg-blue-100 text-blue-800 border-blue-200' },
    CREDENTIALS_UPDATE: { label: 'Credentials Update', color: 'bg-amber-100 text-amber-800 border-amber-200' },
    CREDENTIALS_TEST: { label: 'Credentials Test', color: 'bg-blue-100 text-blue-800 border-blue-200' },
  };

  const item = map[action] || { label: action.replace(/_/g, ' '), color: 'bg-gray-100 text-gray-800 border-gray-200' };

  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold border ${item.color}`}>
      {item.label}
    </span>
  );
}

function UserAvatar({ name, isCurrentUser }: { name: string; isCurrentUser?: boolean }) {
  const initial = (name || 'U').charAt(0).toUpperCase();
  const colors = [
    'bg-blue-600', 'bg-sky-600', 'bg-emerald-600', 'bg-teal-600',
    'bg-pink-600', 'bg-amber-600', 'bg-teal-600', 'bg-cyan-600',
  ];
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash);
  const color = colors[Math.abs(hash) % colors.length];

  return (
    <div className="flex items-center gap-2">
      <div className={`w-7 h-7 rounded-full ${color} text-white font-semibold text-xs flex items-center justify-center shrink-0 shadow-xs`}>
        {initial}
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-semibold text-gray-900 truncate">{name}</span>
          {isCurrentUser && (
            <span className="text-xs bg-blue-50 text-blue-700 font-semibold px-1.5 py-0.2 rounded border border-blue-200/60">
              You
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ActivityLogsPage() {
  const { user: currentAppUser, users, accounts, getAccountLabel } = useApp();
  const [logs, setLogs] = useState<ActivityLog[]>([]);
  const [stats, setStats] = useState<ActivityStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [filterDateRange, setFilterDateRange] = useState<string>('today');
  const [customStartDate, setCustomStartDate] = useState<string>('');
  const [customEndDate, setCustomEndDate] = useState<string>('');
  const [filterUser, setFilterUser] = useState<string>('all');
  const [filterAction, setFilterAction] = useState<string>('all');
  const [filterAccount, setFilterAccount] = useState<string>('all');
  const [filterChannel, setFilterChannel] = useState<string>('all');
  const [search, setSearch] = useState<string>('');
  const [debouncedSearch, setDebouncedSearch] = useState<string>('');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [selectedLog, setSelectedLog] = useState<ActivityLog | null>(null);
  const timerRef = useRef<NodeJS.Timeout | null>(null);

  // Debounce search
  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 300);
    return () => clearTimeout(t);
  }, [search]);
  const getDateFilterParams = useCallback(() => {
    if (filterDateRange === 'all') {
      return { date_range: 'all' };
    }
    if (filterDateRange === 'custom') {
      return {
        date_range: 'custom',
        start_date: customStartDate ? `${customStartDate}T00:00:00` : undefined,
        end_date: customEndDate ? `${customEndDate}T23:59:59` : undefined,
      };
    }
    const now = new Date();
    if (filterDateRange === 'today') {
      const start = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 0, 0, 0, 0).toISOString();
      const end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59, 999).toISOString();
      return { date_range: 'today', start_date: start, end_date: end };
    }
    if (filterDateRange === 'yesterday') {
      const yest = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1);
      const start = new Date(yest.getFullYear(), yest.getMonth(), yest.getDate(), 0, 0, 0, 0).toISOString();
      const end = new Date(yest.getFullYear(), yest.getMonth(), yest.getDate(), 23, 59, 59, 999).toISOString();
      return { date_range: 'yesterday', start_date: start, end_date: end };
    }
    if (filterDateRange === '7d') {
      const past = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 7, 0, 0, 0, 0).toISOString();
      return { date_range: '7d', start_date: past };
    }
    if (filterDateRange === '30d') {
      const past = new Date(now.getFullYear(), now.getMonth(), now.getDate() - 30, 0, 0, 0, 0).toISOString();
      return { date_range: '30d', start_date: past };
    }
    return { date_range: filterDateRange };
  }, [filterDateRange, customStartDate, customEndDate]);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      const dateParams = getDateFilterParams();
      const [logsData, statsData] = await Promise.all([
        fetchActivityLogs({
          user: filterUser,
          action: filterAction,
          account: filterAccount as Account | 'all',
          channel: filterChannel as Channel | 'all',
          search: debouncedSearch,
          ...dateParams,
          limit: 250,
        }),
        fetchActivityStats(),
      ]);
      setLogs(logsData);
      setStats(statsData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch activity logs');
    } finally {
      setLoading(false);
    }
  }, [filterUser, filterAction, filterAccount, filterChannel, debouncedSearch, getDateFilterParams]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Auto-refresh interval
  useEffect(() => {
    if (autoRefresh) {
      timerRef.current = setInterval(() => {
        loadData();
      }, 15000);
    }
    return () => {
      clearInterval(timerRef.current as NodeJS.Timeout);
    };
  }, [autoRefresh, loadData]);

  // Export CSV
  const handleExportCSV = () => {
    if (!logs.length) return;
    const headers = ['ID', 'Timestamp', 'User', 'Action', 'Account', 'Channel', 'Status', 'Details'];
    const rows = logs.map(l => [
      l.id,
      l.timestamp,
      `"${l.user}"`,
      l.action,
      l.account,
      l.channel,
      l.status,
      `"${JSON.stringify(l.details || {}).replace(/"/g, '""')}"`,
    ]);
    const csvContent = 'data:text/csv;charset=utf-8,' + [headers.join(','), ...rows.map(e => e.join(','))].join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `activity_audit_logs_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const hasActiveFilters = search.trim() !== '' || filterDateRange !== 'today' || filterUser !== 'all' || filterAction !== 'all' || filterAccount !== 'all' || filterChannel !== 'all';
  const resetFilters = () => {
    setSearch('');
    setDebouncedSearch('');
    setFilterDateRange('today');
    setCustomStartDate('');
    setCustomEndDate('');
    setFilterUser('all');
    setFilterAction('all');
    setFilterAccount('all');
    setFilterChannel('all');
  };

  return (
    <div className="workspace-page min-w-0 space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-gray-200">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="workspace-heading">Activity Logs & Team Audit Trail</h1>
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-100 text-blue-800 border border-blue-200">
              Team audit trail
            </span>
          </div>
          <p className="workspace-description mt-2">
            Real-time attribution log showing who submitted templates, ran status polls, and updated credentials.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={handleExportCSV}
            disabled={!logs.length}
            className="workspace-button"
          >
            <svg className="w-4 h-4 text-gray-500" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M10 3v10M6 9l4 4 4-4M3 15h14" />
            </svg>
            Export CSV
          </button>

          <button
            onClick={() => loadData()}
            disabled={loading}
            className="workspace-button-primary"
          >
            <svg
              className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`}
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path d="M4 10a6 6 0 106-6M4 4v6h6" />
            </svg>
            Refresh
          </button>
        </div>
      </div>

      {/* KPI Stats Cards */}
      <p className="workspace-eyebrow">Team overview · all recorded activity</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="bg-white p-5 rounded-xl border border-gray-200/80 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Total Actions</span>
            <span className="p-2 rounded-lg bg-blue-50 text-blue-600">
              <svg className="w-5 h-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
                <circle cx="10" cy="10" r="7" />
                <polyline points="10 6 10 10 13 13" />
              </svg>
            </span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-semibold text-gray-900">{stats?.total_actions || 0}</span>
            <span className="text-xs text-gray-500">logged events</span>
          </div>
        </div>

        <div className="bg-white p-5 rounded-xl border border-gray-200/80 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Active Operators</span>
            <span className="p-2 rounded-lg bg-emerald-50 text-emerald-600">
              <svg className="w-5 h-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M13 16h-6a4 4 0 01-4-4V7a4 4 0 014-4h6a4 4 0 014 4v5a4 4 0 01-4 4z" />
                <circle cx="10" cy="8" r="2" />
              </svg>
            </span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-semibold text-gray-900">{stats?.total_users || 0}</span>
            <span className="text-xs text-emerald-600 font-semibold truncate">
              Top: {stats?.top_user || 'None'}
            </span>
          </div>
        </div>

        <div className="bg-white p-5 rounded-xl border border-gray-200/80 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Templates Submitted</span>
            <span className="p-2 rounded-lg bg-blue-50 text-blue-600">
              <svg className="w-5 h-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
                <rect x="3" y="3" width="14" height="14" rx="2" />
                <path d="M7 8h6M7 12h4" />
              </svg>
            </span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-semibold text-gray-900">{stats?.total_templates_submitted || 0}</span>
            <span className="text-xs text-gray-500">across team</span>
          </div>
        </div>

        <div className="bg-white p-5 rounded-xl border border-gray-200/80 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Current Operator</span>
            <span className="p-2 rounded-lg bg-blue-50 text-blue-600">
              <svg className="w-5 h-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M10 2a5 5 0 00-5 5v1a5 5 0 0010 0V7a5 5 0 00-5-5zM3 18a7 7 0 0114 0" />
              </svg>
            </span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-base font-semibold text-gray-900 truncate">{currentAppUser || 'Namann'}</span>
            <span className="text-xs text-gray-500 uppercase font-semibold">Active Profile</span>
          </div>
        </div>
      </div>

      {/* Filter & Search Toolbar */}
      <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-4 space-y-3">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          {/* Search Input */}
          <div className="relative flex-1 max-w-md">
            <svg
              className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500"
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            >
              <path d="M8.5 15a6.5 6.5 0 100-13 6.5 6.5 0 000 13zM13 13l4 4" />
            </svg>
            <input
              type="text"
              aria-label="Search activity"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search user, action, template name, details..."
              className="min-w-0 max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 w-full pl-9 pr-4 py-2 text-sm border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
            />
          </div>

          {/* Filter Selects */}
          <div className="flex flex-wrap items-center gap-2.5">
            {/* Date Range Filter (Default: Today to save memory/load) */}
            <select
              value={filterDateRange}
              aria-label="Activity date range"
              onChange={(e) => setFilterDateRange(e.target.value)}
              className={`min-w-0 max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 text-sm border rounded-lg px-3 py-2 outline-none font-semibold transition-colors ${
                filterDateRange === 'today'
                  ? 'bg-blue-50 border-blue-300 text-blue-800'
                  : 'bg-white border-gray-300 text-gray-700'
              }`}
            >
              <option value="today">Today (Default)</option>
              <option value="yesterday">Yesterday</option>
              <option value="7d">Past 7 Days</option>
              <option value="30d">Past 30 Days</option>
              <option value="all">All Past Activity</option>
              <option value="custom">Custom Date Range...</option>
            </select>

            {filterDateRange === 'custom' && (
              <div className="flex flex-wrap items-center gap-1.5 bg-gray-50 border border-gray-200 rounded-lg px-2.5 py-1">
                <span className="text-xs text-gray-500 uppercase font-semibold">From:</span>
                <input
                  type="date"
              aria-label="Activity start date"
                  value={customStartDate}
                  onChange={(e) => setCustomStartDate(e.target.value)}
                  className="min-w-0 max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 text-sm bg-white border border-gray-300 rounded px-1.5 py-0.5 text-gray-700"
                />
                <span className="text-sm text-gray-500 uppercase font-semibold">To:</span>
                <input
                  type="date"
              aria-label="Activity end date"
                  value={customEndDate}
                  onChange={(e) => setCustomEndDate(e.target.value)}
                  className="min-w-0 max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 text-sm bg-white border border-gray-300 rounded px-1.5 py-0.5 text-gray-700"
                />
              </div>
            )}

            {/* User Filter */}
            <select
              value={filterUser}
              aria-label="Filter by team member"
              onChange={(e) => setFilterUser(e.target.value)}
              className="min-w-0 max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 text-sm bg-white border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:ring-2 focus:ring-blue-500 outline-none font-medium"
            >
              <option value="all">All Team Members</option>
              {users.map((u) => (
                <option key={u.id || u.name} value={u.name}>
                  {u.name}
                </option>
              ))}
            </select>

            {/* Action Filter */}
            <select
              value={filterAction}
              aria-label="Filter by action"
              onChange={(e) => setFilterAction(e.target.value)}
              className="min-w-0 max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 text-sm bg-white border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:ring-2 focus:ring-blue-500 outline-none font-medium"
            >
              <option value="all">All Action Types</option>
              <option value="TEMPLATE_SUBMISSION">Template Submission</option>
              <option value="TEMPLATE_PREVIEW">File Preview</option>
              <option value="STATUS_POLL">Status Poll</option>
              <option value="CREDENTIALS_UPDATE">Credentials Update</option>
              <option value="CREDENTIALS_TEST">Credentials Test</option>
              <option value="ACCOUNT_CREATE">Account Created</option>
              <option value="ACCOUNT_DELETE">Account Deleted</option>
              <option value="USER_LOGIN">User Active</option>
            </select>

            {/* Account Filter */}
            <select
              value={filterAccount}
              aria-label="Filter by account"
              onChange={(e) => setFilterAccount(e.target.value)}
              className="min-w-0 max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 text-sm bg-white border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:ring-2 focus:ring-blue-500 outline-none font-medium"
            >
              <option value="all">All Accounts</option>
              {accounts.map((acc) => (
                <option key={acc.id} value={acc.id}>
                  {acc.name}
                </option>
              ))}
            </select>
            {/* Channel Filter */}
            <select
              value={filterChannel}
              aria-label="Filter by channel"
              onChange={(e) => setFilterChannel(e.target.value)}
              className="min-w-0 max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 text-sm bg-white border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:ring-2 focus:ring-blue-500 outline-none font-medium"
            >
              <option value="all">All Channels</option>
              <option value="whatsapp">WhatsApp</option>
              <option value="rcs">RCS (DLT)</option>
              <option value="sms">SMS (Karix)</option>
            </select>

            {/* Auto-refresh toggle */}
            <label className="flex flex-wrap items-center gap-1.5 text-xs text-gray-600 cursor-pointer pl-1">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="min-w-0 max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <span>Auto-refresh · 15 seconds</span>
            </label>
          </div>
        </div>
        <div className="workspace-toolbar border-t border-gray-100 pt-3 text-sm text-gray-600" aria-live="polite">
          <span>{loading ? 'Loading events…' : 'Showing ' + logs.length + ' events (up to 250)'}</span>
          {filterUser !== 'all' && <span className="workspace-filter-chip">Operator: {filterUser}</span>}
          {filterAction !== 'all' && <span className="workspace-filter-chip">Action: {filterAction.replace(/_/g, ' ')}</span>}
          {filterAccount !== 'all' && <span className="workspace-filter-chip">Account: {getAccountLabel(filterAccount)}</span>}
          {filterChannel !== 'all' && <span className="workspace-filter-chip">Channel: {formatChannel(filterChannel)}</span>}
          {search.trim() && <span className="workspace-filter-chip break-all">Search: {search}</span>}
          {hasActiveFilters && <button type="button" onClick={resetFilters} className="workspace-button">Reset to today</button>}
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div role="alert" className="bg-red-50 border border-red-200 rounded-xl p-4 text-xs text-red-700">
          <span className="font-semibold">Error: </span>
          {error}
        </div>
      )}

      {/* Activity Table */}
      <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs overflow-hidden">
        <div className="p-4 bg-gray-50/80 border-b border-gray-200 flex items-center justify-between flex-wrap gap-2">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="w-2 h-2 rounded-full bg-blue-600" />
            <h3 className="text-base font-semibold text-gray-900 uppercase tracking-wider">
              Audit Trail ({logs.length} events)
            </h3>
            {filterDateRange === 'today' ? (
              <span className="inline-flex flex-wrap items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-blue-100 text-blue-800 border border-blue-200">
                
                <span>Today&apos;s Activity</span>
              </span>
            ) : (
              <span className="inline-flex flex-wrap items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-amber-50 text-amber-800 border border-amber-200">
                
                <span>
                  {filterDateRange === 'yesterday'
                    ? 'Yesterday'
                    : filterDateRange === '7d'
                    ? 'Past 7 Days'
                    : filterDateRange === '30d'
                    ? 'Past 30 Days'
                    : filterDateRange === 'custom'
                    ? 'Custom Range'
                    : 'All Past Activity'}
                </span>
              </span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-gray-500">
            {filterDateRange === 'today' ? (
              <span className="text-gray-600 font-medium">Scope: today only · up to 250 events</span>
            ) : (
              <span>Newest events first</span>
            )}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead>
              <tr className="bg-gray-50/40 text-gray-500 font-semibold border-b border-gray-200 uppercase tracking-wider text-xs">
                <th className="px-5 py-3">Timestamp</th>
                <th className="px-5 py-3">Team Member</th>
                <th className="px-5 py-3">Action</th>
                <th className="px-5 py-3">Target</th>
                <th className="px-5 py-3">Details / Summary</th>
                <th className="px-5 py-3">Status</th>
                <th className="px-5 py-3 text-right">Inspect</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-200">
              {loading && logs.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-5 py-12 text-center text-gray-500">
                    <div className="flex flex-col items-center gap-2">
                      <svg className="animate-spin h-5 w-5 text-blue-600" viewBox="0 0 24 24" fill="none">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                      </svg>
                      <span>Loading activity audit logs...</span>
                    </div>
                  </td>
                </tr>
              ) : logs.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-5 py-12 text-center text-gray-500">
                    {filterDateRange === 'today' && !hasActiveFilters ? (
                      <div className="flex flex-col items-center gap-2 max-w-sm mx-auto">
                        <span className="workspace-eyebrow">Audit trail</span>
                        <p className="text-xs font-semibold text-gray-700">No activity recorded today yet</p>
                        <p className="text-xs text-gray-500 leading-relaxed">
                          Start with today’s activity, or choose a wider period to inspect earlier events.
                        </p>
                        <div className="flex flex-wrap items-center gap-2 mt-2">
                          <button
                            type="button"
                            onClick={() => setFilterDateRange('7d')}
                            className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 px-3 py-1.5 text-sm font-semibold bg-white hover:bg-gray-50 text-gray-700 rounded-lg border border-gray-300 shadow-2xs transition"
                          >
                            View Past 7 Days
                          </button>
                          <button
                            type="button"
                            onClick={() => setFilterDateRange('all')}
                            className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 px-3 py-1.5 text-sm font-semibold bg-blue-50 hover:bg-blue-100 text-blue-700 rounded-lg border border-blue-200 shadow-2xs transition"
                          >
                            View All Past Activity
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="space-y-3"><p>No activity matches the selected filters.</p><button type="button" onClick={resetFilters} className="workspace-button">Reset to today</button></div>
                    )}
                  </td>
                </tr>
              ) : (
                logs.map((log) => {
                  const { relative, exact } = formatTimestamp(log.timestamp);
                  const isCurrent = (log.user || '').toLowerCase() === (currentAppUser || '').toLowerCase();
                  const targetAccount = getAccountLabel(log.account);
                  const targetChannel = formatChannel(log.channel);

                  return (
                    <tr
                      key={log.id}
                      className={
                        log.status === 'failed'
                          ? 'bg-red-50/20 hover:bg-red-50/40 transition-colors'
                          : 'hover:bg-gray-50/60 transition-colors'
                      }
                    >
                      <td className="px-5 py-3 font-mono text-gray-500 whitespace-nowrap">
                        <div className="font-semibold text-gray-800">{relative}</div>
                        <div className="text-xs text-gray-500">{exact}</div>
                      </td>

                      <td className="px-5 py-3 whitespace-nowrap">
                        <UserAvatar name={log.user || 'Anonymous'} isCurrentUser={isCurrent} />
                      </td>

                      <td className="px-5 py-3 whitespace-nowrap">
                        <ActionBadge action={log.action} />
                      </td>

                      <td className="px-5 py-3 whitespace-nowrap">
                        <span
                          className={`inline-flex flex-wrap items-center gap-1.5 px-2 py-0.5 rounded text-xs font-semibold ${
                            log.channel === 'whatsapp'
                              ? 'bg-emerald-50 text-emerald-800 border border-emerald-200/60'
                              : log.channel === 'sms'
                              ? 'bg-purple-50 text-purple-800 border-purple-200/60'
                              : 'bg-blue-50 text-blue-800 border-blue-200/60'
                          }`}
                        >
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${
                              log.channel === 'whatsapp' ? 'bg-emerald-500' : log.channel === 'sms' ? 'bg-purple-500' : 'bg-blue-500'
                            }`}
                          />
                          {targetAccount} &bull; {targetChannel}
                        </span>
                      </td>

                      <td className="px-5 py-3 text-gray-600 max-w-xs truncate">
                        {log.action === 'TEMPLATE_SUBMISSION' && (
                          <div className="space-y-0.5">
                            <div className="font-semibold text-gray-900 text-xs">
                              Submitted {log.details.count || 0} template{log.details.count === 1 ? '' : 's'}
                            </div>
                            <div className="text-xs text-gray-500 truncate">
                              File: {log.details.filename || 'upload.csv'}
                              {Array.isArray(log.details.templates) && log.details.templates.length > 0 && (
                                <> &bull; {log.details.templates.join(', ')}</>
                              )}
                            </div>
                          </div>
                        )}

                        {log.action === 'STATUS_POLL' && (
                          <span className="text-xs text-gray-700 font-medium">
                            Polled {log.details.checked_count || 0} pending template(s)
                          </span>
                        )}

                        {log.action === 'CREDENTIALS_UPDATE' && (
                          <span className="text-xs text-gray-700 font-medium">
                            Updated keys: {Array.isArray(log.details.keys_updated) ? log.details.keys_updated.join(', ') : 'API credentials'}
                          </span>
                        )}

                        {log.action === 'CREDENTIALS_TEST' && (
                          <span className="text-xs text-gray-700 font-medium truncate block max-w-xs">
                            {log.details.message || (log.details.valid ? 'Credentials Valid' : 'Test Failed')}
                          </span>
                        )}

                        {log.action === 'TEMPLATE_PREVIEW' && (
                          <span className="text-xs text-gray-700 font-medium truncate">
                            Previewed {log.details.filename || 'file'}
                          </span>
                        )}
                      </td>

                      <td className="px-5 py-3 whitespace-nowrap">
                        <span
                          className={`inline-flex px-2 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wider ${
                            log.status === 'success'
                              ? 'bg-emerald-100 text-emerald-800'
                              : 'bg-red-100 text-red-800'
                          }`}
                        >
                          {log.status}
                        </span>
                      </td>

                      <td className="px-5 py-3 text-right whitespace-nowrap">
                        <button
                          onClick={() => setSelectedLog(log)}
                          className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 px-2.5 py-1 bg-gray-100 hover:bg-blue-50 text-gray-700 hover:text-blue-700 rounded font-semibold text-sm transition-colors"
                        >
                          Inspect
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Inspect Modal Drawer */}
      {selectedLog && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div role="dialog" aria-modal="true" aria-label="Event details" className="bg-white rounded-xl border border-gray-200 shadow-xl max-w-lg min-w-0 w-full max-h-[85vh] overflow-y-auto p-6 space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-gray-200">
              <div className="flex flex-wrap items-center gap-2.5">
                <ActionBadge action={selectedLog.action} />
                <h3 className="text-sm font-semibold text-gray-900">Event Details (ID: {selectedLog.id})</h3>
              </div>
              <button
                onClick={() => setSelectedLog(null)}
                aria-label="Close event details"
                className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 text-gray-500 hover:text-gray-600 text-lg font-semibold p-1"
              >
                ✕
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm break-words">
              <div>
                <span className="font-semibold text-gray-500">Operator: </span>
                <span className="font-semibold text-gray-900">{selectedLog.user}</span>
              </div>
              <div>
                <span className="font-semibold text-gray-500">Timestamp: </span>
                <span className="font-mono text-gray-800">{formatTimestamp(selectedLog.timestamp).exact}</span>
              </div>
              <div>
                <span className="font-semibold text-gray-500">Account: </span>
                <span className="font-semibold text-gray-900 uppercase">{selectedLog.account}</span>
              </div>
              <div>
                <span className="font-semibold text-gray-500">Channel: </span>
                <span className="font-semibold text-gray-900 uppercase">{selectedLog.channel}</span>
              </div>
              <div>
                <span className="font-semibold text-gray-500">Outcome: </span>
                <span className={`font-semibold ${selectedLog.status === 'success' ? 'text-emerald-700' : 'text-red-700'}`}>
                  {selectedLog.status.toUpperCase()}
                </span>
              </div>
              <div>
                <span className="font-semibold text-gray-500">IP: </span>
                <span className="font-mono text-gray-600">{selectedLog.ip_address || '127.0.0.1'}</span>
              </div>
            </div>

            <div>
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">
                Event Payload & Details
              </div>
              <pre className="bg-gray-900 text-gray-100 p-4 rounded-xl text-xs font-mono overflow-x-auto max-h-60">
                {JSON.stringify(selectedLog.details, null, 2)}
              </pre>
            </div>

            <div className="pt-2 flex justify-end">
              <button
                onClick={() => setSelectedLog(null)}
                className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-semibold text-sm transition-colors"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
