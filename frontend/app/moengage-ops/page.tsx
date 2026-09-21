'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  fetchMoEngageOpsDashboard,
  syncMoEngageOps,
  fetchMoEngageWorkspaces,
  updateMoEngageWorkspace,
} from '@/lib/api';

type ChannelCounts = {
  SMS: number;
  RCS: number;
  WhatsApp: number;
  Email: number;
  Push: number;
};

type VerticalData = {
  campaigns_total: number;
  flows_total: number;
  flow_nodes_total: number;
  channels: ChannelCounts;
  in_account_total: boolean;
};

type DashboardData = {
  date_filter: {
    mode: string;
    start_date: string;
    end_date: string;
  };
  account_overview: {
    title: string;
    total_campaigns: number;
    total_flows: number;
    total_flow_nodes: number;
    channel_breakdown: ChannelCounts;
  };
  vertical_breakdown: Record<string, VerticalData>;
  total_records_ingested: number;
  in_scope_active_count: number;
};

type WorkspaceItem = {
  workspace_name: string;
  vertical: string;
  workspace_id: string;
  api_key: string;
  data_center: string;
  is_active: boolean;
};

export default function MoEngageOpsPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [mode, setMode] = useState<'last_week' | 'last_month' | 'custom'>('last_week');
  const [customStart, setCustomStart] = useState('');
  const [customEnd, setCustomEnd] = useState('');
  const [showWorkspacesModal, setShowWorkspacesModal] = useState(false);
  const [workspaces, setWorkspaces] = useState<WorkspaceItem[]>([]);
  const [selectedWs, setSelectedWs] = useState<WorkspaceItem | null>(null);
  const [savingWs, setSavingWs] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadDashboard = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetchMoEngageOpsDashboard(mode, customStart, customEnd);
      setData(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  }, [mode, customStart, customEnd]);

  useEffect(() => {
    loadDashboard();
  }, [loadDashboard]);

  const handleSync = async () => {
    try {
      setSyncing(true);
      setError(null);
      await syncMoEngageOps();
      await loadDashboard();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to sync MoEngage workspaces');
    } finally {
      setSyncing(false);
    }
  };

  const openWorkspaces = async () => {
    try {
      const list = await fetchMoEngageWorkspaces();
      setWorkspaces(list);
      setSelectedWs(list[0] || null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Could not fetch workspaces');
    }
  };

  const handleSaveWorkspace = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedWs) return;
    try {
      setSavingWs(true);
      await updateMoEngageWorkspace(selectedWs);
      const list = await fetchMoEngageWorkspaces();
      setWorkspaces(list);
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Unknown error';
      alert(`Error saving workspace: ${msg}`);
    } finally {
      setSavingWs(false);
    }
  };

  const channelColors: Record<string, { bg: string; text: string; bar: string }> = {
    Push: { bg: 'bg-indigo-50 text-indigo-700 border-indigo-200', text: 'text-indigo-600', bar: 'bg-indigo-500' },
    WhatsApp: { bg: 'bg-emerald-50 text-emerald-700 border-emerald-200', text: 'text-emerald-600', bar: 'bg-emerald-500' },
    SMS: { bg: 'bg-amber-50 text-amber-700 border-amber-200', text: 'text-amber-600', bar: 'bg-amber-500' },
    Email: { bg: 'bg-blue-50 text-blue-700 border-blue-200', text: 'text-blue-600', bar: 'bg-blue-500' },
    RCS: { bg: 'bg-purple-50 text-purple-700 border-purple-200', text: 'text-purple-600', bar: 'bg-purple-500' },
  };

  return (
    <div className="space-y-8 max-w-7xl mx-auto pb-16">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-200 pb-6">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-gray-900">MoEngage Operations Dashboard</h1>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200">
              <span className="w-2 h-2 rounded-full bg-blue-500 animate-pulse" />
              Live API
            </span>
          </div>
          <p className="text-sm text-gray-500 mt-1">
            Campaigns, flows, and flow nodes built by Attributics across Tata Capital verticals.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2.5">
          <button
            onClick={openWorkspaces}
            className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-semibold rounded-lg border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 shadow-sm transition-all"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
              <line x1="8" y1="21" x2="16" y2="21" />
              <line x1="12" y1="17" x2="12" y2="21" />
            </svg>
            Manage Workspaces
          </button>

          <a
            href="/api/moengage/ops/export-excel"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-semibold rounded-lg border border-emerald-300 bg-emerald-50 text-emerald-800 hover:bg-emerald-100 shadow-sm transition-all"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            Export to Excel
          </a>

          <button
            onClick={handleSync}
            disabled={syncing}
            className={`inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold rounded-lg text-white shadow-sm transition-all ${
              syncing ? 'bg-blue-400 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-700'
            }`}
          >
            <svg
              className={`w-3.5 h-3.5 ${syncing ? 'animate-spin' : ''}`}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <polyline points="23 4 23 10 17 10" />
              <polyline points="1 20 1 14 7 14" />
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
            </svg>
            {syncing ? 'Syncing...' : 'Sync from MoEngage'}
          </button>
        </div>
      </div>

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700 flex items-center gap-3">
          <svg className="w-5 h-5 text-red-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <div className="flex-1">{error}</div>
        </div>
      )}

      {/* Date Filter Bar */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider mr-2">Date Range:</span>
          {(['last_week', 'last_month', 'custom'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`px-3 py-1.5 rounded-lg text-xs font-semibold capitalize transition-all ${
                mode === m
                  ? 'bg-blue-600 text-white shadow-sm'
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {m.replace('_', ' ')}
            </button>
          ))}
        </div>

        {mode === 'custom' && (
          <div className="flex items-center gap-2 text-xs">
            <input
              type="date"
              value={customStart}
              onChange={(e) => setCustomStart(e.target.value)}
              className="border border-gray-300 rounded-lg px-2.5 py-1 text-gray-800"
            />
            <span className="text-gray-400">to</span>
            <input
              type="date"
              value={customEnd}
              onChange={(e) => setCustomEnd(e.target.value)}
              className="border border-gray-300 rounded-lg px-2.5 py-1 text-gray-800"
            />
          </div>
        )}

        {data?.date_filter && (
          <div className="text-xs text-gray-500 bg-gray-50 px-3 py-1.5 rounded-lg border border-gray-200">
            Showing:{' '}
            <span className="font-semibold text-gray-800">
              {data.date_filter.start_date}
            </span>{' '}
            to{' '}
            <span className="font-semibold text-gray-800">
              {data.date_filter.end_date}
            </span>{' '}
            <span className="text-gray-400 ml-1">({mode})</span>
          </div>
        )}
      </div>

      {loading && !data ? (
        <div className="py-24 text-center">
          <div className="w-8 h-8 border-2 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-xs text-gray-500">Loading MoEngage operations metrics...</p>
        </div>
      ) : data ? (
        <>
          {/* Executive Overview Cards */}
          <div>
            <div className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-3">
              Account Overview ({data.account_overview.title})
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
              {/* Card 1: Total Campaigns */}
              <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Total Campaigns</span>
                  <span className="p-2 rounded-lg bg-indigo-50 text-indigo-600">
                    <svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M11 5.882V19.24a1.76 1.76 0 01-3.417.592l-2.147-6.15M18 13a3 3 0 100-6M5.436 13.683A4.001 4.001 0 017 6h1.832c4.1 0 7.625-1.234 9.168-3v14c-1.543-1.766-5.067-3-9.168-3H7a3.988 3.988 0 01-1.564-.317z" />
                    </svg>
                  </span>
                </div>
                <div className="text-3xl font-extrabold text-gray-900 mt-2">
                  {data.account_overview.total_campaigns}
                </div>
                <div className="mt-4 pt-4 border-t border-gray-100 flex flex-wrap gap-1.5">
                  {Object.entries(data.account_overview.channel_breakdown).map(([ch, count]) => (
                    <span
                      key={ch}
                      className={`text-[11px] font-semibold px-2 py-0.5 rounded-md border ${
                        channelColors[ch]?.bg || 'bg-gray-50 text-gray-700 border-gray-200'
                      }`}
                    >
                      {ch}: {count}
                    </span>
                  ))}
                </div>
              </div>

              {/* Card 2: Total Flows */}
              <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Total Flows</span>
                  <span className="p-2 rounded-lg bg-emerald-50 text-emerald-600">
                    <svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                  </span>
                </div>
                <div className="text-3xl font-extrabold text-gray-900 mt-2">
                  {data.account_overview.total_flows}
                </div>
                <p className="text-xs text-gray-500 mt-4 pt-4 border-t border-gray-100">
                  Multi-channel journeys (SMS, RCS, WhatsApp, Email, Push)
                </p>
              </div>

              {/* Card 3: Total Flow Nodes */}
              <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">Total Flow Nodes</span>
                  <span className="p-2 rounded-lg bg-blue-50 text-blue-600">
                    <svg width="18" height="18" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                    </svg>
                  </span>
                </div>
                <div className="text-3xl font-extrabold text-gray-900 mt-2">
                  {data.account_overview.total_flow_nodes}
                </div>
                <p className="text-xs text-gray-500 mt-4 pt-4 border-t border-gray-100">
                  Discrete channel steps executed inside active flows
                </p>
              </div>
            </div>
          </div>

          {/* Vertical Breakdown Grid */}
          <div>
            <div className="text-xs font-bold uppercase tracking-wider text-gray-500 mb-3">
              Vertical Breakdown (Tata Capital Business Units)
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
              {Object.entries(data.vertical_breakdown).map(([verticalName, vdata]) => (
                <div
                  key={verticalName}
                  className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm flex flex-col justify-between"
                >
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-base font-bold text-gray-900">{verticalName}</h3>
                      <span
                        className={`text-[10px] font-bold uppercase px-2 py-0.5 rounded-full ${
                          vdata.in_account_total
                            ? 'bg-blue-50 text-blue-700 border border-blue-200'
                            : 'bg-amber-50 text-amber-700 border border-amber-200'
                        }`}
                      >
                        {vdata.in_account_total ? 'In Overview Total' : 'Reported Separately'}
                      </span>
                    </div>

                    <div className="grid grid-cols-3 gap-2 py-3 bg-gray-50 rounded-lg text-center mb-3">
                      <div>
                        <div className="text-lg font-bold text-gray-900">{vdata.campaigns_total}</div>
                        <div className="text-[10px] text-gray-500 uppercase font-semibold">Campaigns</div>
                      </div>
                      <div>
                        <div className="text-lg font-bold text-gray-900">{vdata.flows_total}</div>
                        <div className="text-[10px] text-gray-500 uppercase font-semibold">Flows</div>
                      </div>
                      <div>
                        <div className="text-lg font-bold text-gray-900">{vdata.flow_nodes_total}</div>
                        <div className="text-[10px] text-gray-500 uppercase font-semibold">Nodes</div>
                      </div>
                    </div>
                  </div>

                  <div>
                    <div className="text-[11px] font-semibold text-gray-400 mb-1.5 uppercase">Channel Breakdown:</div>
                    <div className="flex flex-wrap gap-1.5">
                      {Object.entries(vdata.channels).map(([ch, count]) => (
                        <span
                          key={ch}
                          className={`text-[11px] font-semibold px-2 py-0.5 rounded border ${
                            channelColors[ch]?.bg || 'bg-gray-50 text-gray-700 border-gray-200'
                          }`}
                        >
                          {ch}: {count}
                        </span>
                      ))}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </>
      ) : null}

      {/* Workspace Management Modal */}
      {showWorkspacesModal && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-xl max-w-2xl w-full p-6 border border-gray-200 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-gray-100 pb-4 mb-4">
              <div>
                <h3 className="text-lg font-bold text-gray-900">MoEngage Workspaces</h3>
                <p className="text-xs text-gray-500">Configure Workspace IDs and API Keys for each Tata Capital vertical.</p>
              </div>
              <button
                onClick={() => setShowWorkspacesModal(false)}
                className="p-1 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600"
              >
                ✕
              </button>
            </div>

            <div className="flex gap-2 border-b border-gray-100 pb-3 mb-4 overflow-x-auto">
              {workspaces.map((ws) => (
                <button
                  key={ws.vertical}
                  onClick={() => setSelectedWs(ws)}
                  className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all ${
                    selectedWs?.vertical === ws.vertical
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {ws.workspace_name} {ws.is_active && '✓'}
                </button>
              ))}
            </div>

            {selectedWs && (
              <form onSubmit={handleSaveWorkspace} className="space-y-4">
                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Workspace Name</label>
                  <input
                    type="text"
                    value={selectedWs.workspace_name}
                    onChange={(e) => setSelectedWs({ ...selectedWs, workspace_name: e.target.value })}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs"
                    required
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">Workspace ID (App ID)</label>
                  <input
                    type="text"
                    value={selectedWs.workspace_id}
                    onChange={(e) => setSelectedWs({ ...selectedWs, workspace_id: e.target.value })}
                    placeholder="e.g. PLBRDCVUS0YE8ME3E8XSHV5D"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono"
                    required
                  />
                </div>

                <div>
                  <label className="block text-xs font-bold text-gray-700 mb-1">API Key</label>
                  <input
                    type="text"
                    value={selectedWs.api_key}
                    onChange={(e) => setSelectedWs({ ...selectedWs, api_key: e.target.value })}
                    placeholder="e.g. F9ED1AC8BB3449E8B6D94E5C"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-mono"
                    required
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs font-bold text-gray-700 mb-1">Data Center</label>
                    <select
                      value={selectedWs.data_center}
                      onChange={(e) => setSelectedWs({ ...selectedWs, data_center: e.target.value })}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs"
                    >
                      <option value="03">DC-03 (India - api-03.moengage.com)</option>
                      <option value="01">DC-01 (US - api-01.moengage.com)</option>
                      <option value="02">DC-02 (EU - api-02.moengage.com)</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-xs font-bold text-gray-700 mb-1">Status</label>
                    <select
                      value={selectedWs.is_active ? 'active' : 'inactive'}
                      onChange={(e) => setSelectedWs({ ...selectedWs, is_active: e.target.value === 'active' })}
                      className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs"
                    >
                      <option value="active">Active (Include in Ops Sync)</option>
                      <option value="inactive">Inactive</option>
                    </select>
                  </div>
                </div>

                <div className="pt-4 border-t border-gray-100 flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => setShowWorkspacesModal(false)}
                    className="px-4 py-2 border border-gray-300 rounded-lg text-xs font-semibold text-gray-700 hover:bg-gray-50"
                  >
                    Close
                  </button>
                  <button
                    type="submit"
                    disabled={savingWs}
                    className="px-4 py-2 bg-blue-600 text-white rounded-lg text-xs font-semibold hover:bg-blue-700 shadow-sm"
                  >
                    {savingWs ? 'Saving...' : 'Save Workspace'}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
