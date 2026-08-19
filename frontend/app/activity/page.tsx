'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { fetchActivityLogs, fetchActivityStats } from '@/lib/api';
import type { ActivityLog, ActivityStats, Account, Channel } from '@/lib/api';
import { useApp } from '@/lib/context';

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
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-semibold border ${item.color}`}>
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
      <div className={`w-7 h-7 rounded-full ${color} text-white font-bold text-xs flex items-center justify-center shrink-0 shadow-xs`}>
        {initial}
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-xs font-semibold text-gray-900 truncate">{name}</span>
          {isCurrentUser && (
            <span className="text-[10px] bg-blue-50 text-blue-700 font-bold px-1.5 py-0.2 rounded border border-blue-200/60">
              You
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ActivityLogsPage() {
  const { user: currentAppUser } = useApp();
  const [logs, setLogs] = useState<ActivityLog[]>([]);
  const [stats, setStats] = useState<ActivityStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
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

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      const [logsData, statsData] = await Promise.all([
        fetchActivityLogs({
          user: filterUser,
          action: filterAction,
          account: filterAccount as Account | 'all',
          channel: filterChannel as Channel | 'all',
          search: debouncedSearch,
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
  }, [filterUser, filterAction, filterAccount, filterChannel, debouncedSearch]);

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

  const usersList = stats?.user_activity.map(u => u.user) || [];

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 pb-2 border-b border-gray-200">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-gray-900">Activity Logs & Team Audit Trail</h1>
            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-100 text-blue-800 border border-blue-200">
              Live Team Audit
            </span>
          </div>
          <p className="text-sm text-gray-500 mt-1">
            Real-time attribution log showing who submitted templates, ran status polls, and updated credentials.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={handleExportCSV}
            disabled={!logs.length}
            className="inline-flex items-center gap-2 bg-white border border-gray-300 hover:bg-gray-50 text-gray-700 px-3.5 py-2 rounded-lg text-xs font-semibold shadow-xs transition-colors disabled:opacity-50"
          >
            <svg className="w-4 h-4 text-gray-500" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M10 3v10M6 9l4 4 4-4M3 15h14" />
            </svg>
            Export CSV
          </button>

          <button
            onClick={() => loadData()}
            disabled={loading}
            className="inline-flex items-center gap-2 bg-blue-600 hover:bg-blue-700 text-white px-3.5 py-2 rounded-lg text-xs font-semibold shadow-xs transition-colors disabled:opacity-50"
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
            <span className="text-2xl font-bold text-gray-900">{stats?.total_actions || 0}</span>
            <span className="text-xs text-gray-400">logged events</span>
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
            <span className="text-2xl font-bold text-gray-900">{stats?.total_users || 0}</span>
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
            <span className="text-2xl font-bold text-gray-900">{stats?.total_templates_submitted || 0}</span>
            <span className="text-xs text-gray-400">across team</span>
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
            <span className="text-base font-bold text-gray-900 truncate">{currentAppUser || 'Namann'}</span>
            <span className="text-[10px] text-gray-400 uppercase font-semibold">Active Profile</span>
          </div>
        </div>
      </div>

      {/* Filter & Search Toolbar */}
      <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs p-4 space-y-3">
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          {/* Search Input */}
          <div className="relative flex-1 max-w-md">
            <svg
              className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400"
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
            >
              <path d="M8.5 15a6.5 6.5 0 100-13 6.5 6.5 0 000 13zM13 13l4 4" />
            </svg>
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search user, action, template name, details..."
              className="w-full pl-9 pr-4 py-2 text-xs border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-blue-500 outline-none"
            />
          </div>

          {/* Filter Selects */}
          <div className="flex flex-wrap items-center gap-2.5">
            {/* User Filter */}
            <select
              value={filterUser}
              onChange={(e) => setFilterUser(e.target.value)}
              className="text-xs bg-white border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:ring-2 focus:ring-blue-500 outline-none font-medium"
            >
              <option value="all">All Team Members</option>
              {usersList.map((u) => (
                <option key={u} value={u}>
                  {u}
                </option>
              ))}
            </select>

            {/* Action Filter */}
            <select
              value={filterAction}
              onChange={(e) => setFilterAction(e.target.value)}
              className="text-xs bg-white border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:ring-2 focus:ring-blue-500 outline-none font-medium"
            >
              <option value="all">All Action Types</option>
              <option value="TEMPLATE_SUBMISSION">Template Submission</option>
              <option value="TEMPLATE_PREVIEW">File Preview</option>
              <option value="STATUS_POLL">Status Poll</option>
              <option value="CREDENTIALS_UPDATE">Credentials Update</option>
              <option value="CREDENTIALS_TEST">Credentials Test</option>
            </select>

            {/* Account Filter */}
            <select
              value={filterAccount}
              onChange={(e) => setFilterAccount(e.target.value)}
              className="text-xs bg-white border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:ring-2 focus:ring-blue-500 outline-none font-medium"
            >
              <option value="all">All Accounts</option>
              <option value="tata">Tata Capital</option>
              <option value="bajaj">Bajaj</option>
            </select>

            {/* Channel Filter */}
            <select
              value={filterChannel}
              onChange={(e) => setFilterChannel(e.target.value)}
              className="text-xs bg-white border border-gray-300 rounded-lg px-3 py-2 text-gray-700 focus:ring-2 focus:ring-blue-500 outline-none font-medium"
            >
              <option value="all">All Channels</option>
              <option value="whatsapp">WhatsApp</option>
              <option value="rcs">RCS (DLT)</option>
            </select>

            {/* Auto-refresh toggle */}
            <label className="flex items-center gap-1.5 text-xs text-gray-600 cursor-pointer pl-1">
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              />
              <span>Live Sync</span>
            </label>
          </div>
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-xs text-red-700">
          <span className="font-semibold">Error: </span>
          {error}
        </div>
      )}

      {/* Activity Table */}
      <div className="bg-white rounded-xl border border-gray-200/80 shadow-xs overflow-hidden">
        <div className="p-4 bg-gray-50/80 border-b border-gray-200 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-blue-600" />
            <h3 className="text-xs font-bold text-gray-900 uppercase tracking-wider">
              Audit Trail ({logs.length} events)
            </h3>
          </div>
          <span className="text-[11px] text-gray-400">Newest events first</span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="bg-gray-50/40 text-gray-500 font-semibold border-b border-gray-200 uppercase tracking-wider text-[11px]">
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
                  <td colSpan={7} className="px-5 py-12 text-center text-gray-400">
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
                  <td colSpan={7} className="px-5 py-12 text-center text-gray-400">
                    No activity logs found matching the selected filters.
                  </td>
                </tr>
              ) : (
                logs.map((log) => {
                  const { relative, exact } = formatTimestamp(log.timestamp);
                  const isCurrent = (log.user || '').toLowerCase() === (currentAppUser || '').toLowerCase();
                  const targetAccount = log.account === 'tata' ? 'Tata Capital' : 'Bajaj';
                  const targetChannel = log.channel === 'whatsapp' ? 'WhatsApp' : 'RCS';

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
                        <div className="text-[10px] text-gray-400">{exact}</div>
                      </td>

                      <td className="px-5 py-3 whitespace-nowrap">
                        <UserAvatar name={log.user || 'Anonymous'} isCurrentUser={isCurrent} />
                      </td>

                      <td className="px-5 py-3 whitespace-nowrap">
                        <ActionBadge action={log.action} />
                      </td>

                      <td className="px-5 py-3 whitespace-nowrap">
                        <span
                          className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-semibold ${
                            log.channel === 'whatsapp'
                              ? 'bg-emerald-50 text-emerald-800 border border-emerald-200/60'
                              : 'bg-blue-50 text-blue-800 border border-blue-200/60'
                          }`}
                        >
                          <span
                            className={`w-1.5 h-1.5 rounded-full ${
                              log.channel === 'whatsapp' ? 'bg-emerald-500' : 'bg-blue-500'
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
                            <div className="text-[11px] text-gray-400 truncate">
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
                          className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
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
                          className="px-2.5 py-1 bg-gray-100 hover:bg-blue-50 text-gray-700 hover:text-blue-700 rounded font-semibold text-[11px] transition-colors"
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
          <div className="bg-white rounded-2xl border border-gray-200 shadow-xl max-w-lg w-full max-h-[85vh] overflow-y-auto p-6 space-y-5">
            <div className="flex items-center justify-between pb-3 border-b border-gray-200">
              <div className="flex items-center gap-2.5">
                <ActionBadge action={selectedLog.action} />
                <h3 className="text-sm font-bold text-gray-900">Event Details (ID: {selectedLog.id})</h3>
              </div>
              <button
                onClick={() => setSelectedLog(null)}
                className="text-gray-400 hover:text-gray-600 text-lg font-bold p-1"
              >
                ✕
              </button>
            </div>

            <div className="grid grid-cols-2 gap-4 text-xs">
              <div>
                <span className="font-semibold text-gray-500">Operator: </span>
                <span className="font-bold text-gray-900">{selectedLog.user}</span>
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
                <span className={`font-bold ${selectedLog.status === 'success' ? 'text-emerald-700' : 'text-red-700'}`}>
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
                className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg font-semibold text-xs transition-colors"
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
