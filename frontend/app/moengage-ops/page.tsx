'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import {
  fetchMoEngageOpsDashboard,
  syncMoEngageOps,
  fetchMoEngageWorkspaces,
  updateMoEngageWorkspace,
  uploadMoEngageExportFile,
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
    total_touchpoints: number;
    channel_breakdown: ChannelCounts;
    campaigns_channel_breakdown: ChannelCounts;
    nodes_channel_breakdown: ChannelCounts;
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
  const [workspaceFilter, setWorkspaceFilter] = useState('all');
  const [showWorkspacesModal, setShowWorkspacesModal] = useState(false);
  const [workspaces, setWorkspaces] = useState<WorkspaceItem[]>([]);
  const [selectedWs, setSelectedWs] = useState<WorkspaceItem | null>(null);
  const [savingWs, setSavingWs] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      setUploading(true);
      setError(null);
      const json = await uploadMoEngageExportFile(file, {
        vertical: 'TCL',
        mode,
        customStart,
        customEnd,
        workspaceFilter,
      });

      const filesCount = json.result?.files_parsed || 1;
      const count = json.result?.new_records_parsed || 0;
      const camps = json.result?.campaigns_count || 0;
      const flows = json.result?.flows_count || 0;
      const nodes = json.result?.nodes_count || 0;
      const partsSummary =
        filesCount > 1
          ? `across ${filesCount} CSV files (${camps} campaigns, ${flows} flows, ${nodes} action nodes)`
          : `(${camps} campaigns, ${flows} flows, ${nodes} action nodes)`;
      alert(`Successfully imported ${count} items ${partsSummary} from ${file.name}!`);
      await loadDashboard();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Upload failed');
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const loadDashboard = useCallback(async () => {
    try {
      setLoading(true);
      const res = await fetchMoEngageOpsDashboard(mode, customStart, customEnd, workspaceFilter);
      setData(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  }, [mode, customStart, customEnd, workspaceFilter]);

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
      setShowWorkspacesModal(true);
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
    Push: { bg: 'bg-gray-50 text-gray-700 border-gray-200', text: 'text-gray-600', bar: 'bg-gray-500' },
    WhatsApp: { bg: 'bg-gray-50 text-gray-700 border-gray-200', text: 'text-gray-600', bar: 'bg-gray-500' },
    SMS: { bg: 'bg-gray-50 text-gray-700 border-gray-200', text: 'text-gray-600', bar: 'bg-gray-500' },
    Email: { bg: 'bg-gray-50 text-gray-700 border-gray-200', text: 'text-gray-600', bar: 'bg-gray-500' },
    RCS: { bg: 'bg-gray-50 text-gray-700 border-gray-200', text: 'text-gray-600', bar: 'bg-gray-500' },
  };

  return (
    <div className="workspace-page min-w-0 tabular-nums space-y-6 pb-16">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-200 pb-6">
        <div>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="workspace-heading">MoEngage operations</h1>
            <span className="inline-flex flex-wrap items-center gap-2 px-2.5 py-0.5 rounded-md text-sm font-medium bg-gray-50 text-gray-700 border border-gray-200">
              <span className="w-2 h-2 rounded-full bg-blue-500 " />
              Tata Capital
            </span>
          </div>
          <p className="workspace-description mt-2">
            Campaigns, flows, and flow nodes built by Attributics across Tata Capital verticals.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <button
            onClick={openWorkspaces}
            className="workspace-button"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
              <line x1="8" y1="21" x2="16" y2="21" />
              <line x1="12" y1="17" x2="12" y2="21" />
            </svg>
            Manage workspaces
          </button>

          <a
            href="/api/moengage/ops/export-excel"
            target="_blank"
            rel="noopener noreferrer"
            className="workspace-button"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="7 10 12 15 17 10" />
              <line x1="12" y1="15" x2="12" y2="3" />
            </svg>
            Export Excel
          </a>
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileUpload}
            accept=".zip,.csv,.xlsx,.xls"
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="workspace-button"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
            {uploading ? 'Importing...' : 'Import MoEngage Export (ZIP / CSV)'}
          </button>

          <button
            onClick={handleSync}
            disabled={syncing}
            className={`workspace-button-primary ${
              syncing ? 'cursor-wait' : ''
            }`}
          >
            <svg
              className={`w-4 h-4 ${syncing ? 'animate-spin' : ''}`}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
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
        <div role="alert" className="p-4 bg-red-50 border border-red-200 rounded-xl text-sm text-red-700 flex flex-wrap items-center gap-3">
          <svg className="w-5 h-5 text-red-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <div className="flex-1">{error}</div>
        </div>
      )}

      {/* Date Filter Bar */}
      <div className="bg-white border border-gray-200 rounded-xl p-4  flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div className="workspace-toolbar min-w-0">
          <span className="text-sm font-medium text-gray-500   mr-2">Date range:</span>
          {(['last_week', 'last_month', 'custom'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMode(m)}
              aria-pressed={mode === m}
              className={`focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 px-3 py-1.5 rounded-lg text-sm font-medium capitalize transition-colors ${
                mode === m
                  ? 'bg-blue-600 text-white '
                  : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
              }`}
            >
              {m.replace('_', ' ')}
            </button>
          ))}
          <div className="flex flex-wrap items-center gap-2 border-l border-gray-200 pl-3 ml-1">
            <span className="text-sm font-medium text-gray-500  ">Workspace:</span>
            <select
              value={workspaceFilter}
              aria-label="MoEngage workspace scope"
              onChange={(e) => setWorkspaceFilter(e.target.value)}
              className="min-w-0 max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 workspace-select max-w-full"
            >
              <option value="all">All combined</option>
              <option value="TCL">Tata Capital (TCL)</option>
              <option value="Services">Services</option>
              <option value="Wealth">Wealth</option>
              <option value="Moneyfy">Moneyfy</option>
              <option value="TCHFL">TCHFL</option>
              <option value="Collections">Collections</option>
            </select>
          </div>
        </div>

        {mode === 'custom' && (
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <input
              type="date"
              aria-label="MoEngage start date"
              value={customStart}
              onChange={(e) => setCustomStart(e.target.value)}
              className="min-w-0 max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 border border-gray-300 rounded-lg px-2.5 py-1 text-gray-800"
            />
            <span className="text-gray-500">to</span>
            <input
              type="date"
              aria-label="MoEngage end date"
              value={customEnd}
              onChange={(e) => setCustomEnd(e.target.value)}
              className="min-w-0 max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 border border-gray-300 rounded-lg px-2.5 py-1 text-gray-800"
            />
          </div>
        )}

        {data?.date_filter && (
          <div className="text-sm text-gray-500 bg-gray-50 px-3 py-1.5 rounded-lg border border-gray-200">
            Showing:{' '}
            <span className="font-medium text-gray-800">
              {data.date_filter.start_date}
            </span>{' '}
            to{' '}
            <span className="font-medium text-gray-800">
              {data.date_filter.end_date}
            </span>{' '}
            <span className="text-gray-500 ml-1">({mode})</span>
          </div>
        )}
        {(mode !== 'last_week' || workspaceFilter !== 'all' || customStart || customEnd) && (
          <button type="button" className="workspace-button" onClick={() => { setMode('last_week'); setCustomStart(''); setCustomEnd(''); setWorkspaceFilter('all'); }}>Reset filters</button>
        )}
      </div>
      <div className="workspace-guide text-sm text-gray-600">
        Scope: Tata Capital · {workspaceFilter === 'all' ? 'all combined workspaces' : workspaceFilter}. Counts reflect the selected period and available imported or synced records. Sync availability depends on workspace configuration.
      </div>

      {loading && data && <p className="text-sm text-gray-600" role="status">Updating the selected operations view…</p>}
      {loading && !data ? (
        <div className="py-24 text-center">
          <div className="w-8 h-8 border-2 border-gray-600 border-t-transparent rounded-full animate-spin mx-auto mb-3" />
          <p className="text-sm text-gray-500">Loading MoEngage operations metrics...</p>
        </div>
      ) : data ? (
        <>
          {data.in_scope_active_count === 0 && (
            <div className="workspace-empty space-y-2">
              <h2 className="text-base font-medium text-gray-900">No records in this view</h2>
              <p>Try another period or workspace. Import an existing export or sync configured workspaces to load operations data.</p>
              <button type="button" className="workspace-button" onClick={() => { setMode('last_week'); setCustomStart(''); setCustomEnd(''); setWorkspaceFilter('all'); }}>Reset filters</button>
            </div>
          )}
          {/* Executive Overview Cards */}
          <div>
            <div className="text-sm font-medium   text-gray-500 mb-3">
              Account overview ({data.account_overview.title})
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
              {/* Card 1: Total Campaigns */}
              <div className="bg-white border border-gray-200 rounded-xl p-4  flex flex-col justify-between">
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-gray-500  ">Standalone campaigns</span>
                  </div>
                  <div className="text-3xl font-medium text-gray-900 mt-2">
                    {data.account_overview.total_campaigns}
                  </div>
                </div>
                <div className="mt-3 pt-3 border-t border-gray-100 flex flex-wrap gap-1">
                  {Object.entries(data.account_overview.campaigns_channel_breakdown || {}).filter(([_, count]) => count > 0).map(([ch, count]) => (
                    <span
                      key={ch}
                      className={`text-sm font-medium px-1.5 py-0.5 rounded border ${
                        channelColors[ch]?.bg || 'bg-gray-50 text-gray-700 border-gray-200'
                      }`}
                    >
                      {ch}: {count}
                    </span>
                  ))}
                </div>
              </div>

              {/* Card 2: Total Flows */}
              <div className="bg-white border border-gray-200 rounded-xl p-4  flex flex-col justify-between">
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-gray-500  ">Active flows</span>
                  </div>
                  <div className="text-3xl font-medium text-gray-900 mt-2">
                    {data.account_overview.total_flows}
                  </div>
                </div>
                <p className="text-sm text-gray-500 mt-3 pt-3 border-t border-gray-100">
                  Multi-step customer journeys & automations
                </p>
              </div>

              {/* Card 3: Total Flow Nodes (WhatsApp & RCS) */}
              <div className="bg-white border border-gray-200 rounded-xl p-4  flex flex-col justify-between">
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-gray-500  ">Flow action nodes</span>
                  </div>
                  <div className="text-3xl font-medium text-gray-900 mt-2">
                    {data.account_overview.total_flow_nodes}
                  </div>
                </div>
                <div className="mt-3 pt-3 border-t border-gray-100 flex flex-wrap gap-1">
                  {Object.entries(data.account_overview.nodes_channel_breakdown || {}).filter(([_, count]) => count > 0).map(([ch, count]) => (
                    <span
                      key={ch}
                      className={`text-sm font-medium px-1.5 py-0.5 rounded border ${
                        channelColors[ch]?.bg || 'bg-gray-50 text-gray-700 border-gray-200'
                      }`}
                    >
                      {ch}: {count}
                    </span>
                  ))}
                </div>
              </div>

              {/* Card 4: Total Omnichannel Delivery */}
              <div className="bg-white border border-gray-200 rounded-xl p-4  flex flex-col justify-between">
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-gray-700  ">Total touchpoints</span>
                  </div>
                  <div className="text-3xl font-medium text-gray-900 mt-2">
                    {data.account_overview.total_touchpoints || (data.account_overview.total_campaigns + data.account_overview.total_flow_nodes)}
                  </div>
                </div>
                <div className="mt-3 pt-3 border-t border-gray-100 flex flex-wrap gap-1">
                  {Object.entries(data.account_overview.channel_breakdown || {}).filter(([_, count]) => count > 0).map(([ch, count]) => (
                    <span
                      key={ch}
                      className={`text-sm font-medium px-1.5 py-0.5 rounded border ${
                        channelColors[ch]?.bg || 'bg-gray-50 text-gray-700 border-gray-200'
                      }`}
                    >
                      {ch}: {count}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Vertical Breakdown Grid */}
          <div>
            <div className="text-sm font-medium   text-gray-500 mb-3">
              Vertical breakdown · Tata Capital business units
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
              {Object.entries(data.vertical_breakdown).map(([verticalName, vdata]) => (
                <div
                  key={verticalName}
                  className="bg-white border border-gray-200 rounded-xl p-5  flex flex-col justify-between"
                >
                  <div>
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-base font-medium text-gray-900">{verticalName}</h3>
                      <span
                        className={`text-sm font-medium  px-2 py-0.5 rounded-md ${
                          vdata.in_account_total
                            ? 'bg-gray-50 text-gray-700 border border-gray-200'
                            : 'bg-amber-50 text-amber-700 border border-amber-200'
                        }`}
                      >
                        {vdata.in_account_total ? 'In overview total' : 'Reported separately'}
                      </span>
                    </div>

                    <div className="grid grid-cols-3 gap-2 py-3 bg-gray-50 rounded-lg text-center mb-3">
                      <div>
                        <div className="text-lg font-medium text-gray-900">{vdata.campaigns_total}</div>
                        <div className="text-sm text-gray-500  font-medium">Campaigns</div>
                      </div>
                      <div>
                        <div className="text-lg font-medium text-gray-900">{vdata.flows_total}</div>
                        <div className="text-sm text-gray-500  font-medium">Flows</div>
                      </div>
                      <div>
                        <div className="text-lg font-medium text-gray-900">{vdata.flow_nodes_total}</div>
                        <div className="text-sm text-gray-500  font-medium">Nodes</div>
                      </div>
                    </div>
                  </div>

                  <div>
                    <div className="text-sm font-medium text-gray-500 mb-1.5 ">Channel breakdown:</div>
                    <div className="flex flex-wrap gap-2">
                      {Object.entries(vdata.channels).filter(([_, count]) => count > 0).map(([ch, count]) => (
                        <span
                          key={ch}
                          className={`text-sm font-medium px-2 py-0.5 rounded border ${
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
          <div role="dialog" aria-modal="true" aria-label="MoEngage workspaces" className="bg-white rounded-xl shadow-xl max-w-2xl min-w-0 w-full p-6 border border-gray-200 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-gray-100 pb-4 mb-4">
              <div>
                <h3 className="text-lg font-medium text-gray-900">MoEngage workspaces</h3>
                <p className="text-sm text-gray-500">Configure Workspace IDs and API Keys for each Tata Capital vertical.</p>
              </div>
              <button
                onClick={() => setShowWorkspacesModal(false)}
                aria-label="Close workspaces"
                className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 p-1 rounded-lg hover:bg-gray-100 text-gray-500 hover:text-gray-600"
              >
                <svg aria-hidden="true" className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="m6 6 12 12M18 6 6 18" /></svg>
              </button>
            </div>

            <div className="flex gap-2 border-b border-gray-100 pb-3 mb-4 overflow-x-auto">
              {workspaces.map((ws) => (
                <button
                  key={ws.vertical}
                  onClick={() => setSelectedWs(ws)}
                  className={`focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 px-3 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap transition-colors ${
                    selectedWs?.vertical === ws.vertical
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                  }`}
                >
                  {ws.workspace_name} {ws.is_active && '· Active'}
                </button>
              ))}
            </div>

            {workspaces.length === 0 && <div className="workspace-empty">No workspaces are available to configure.</div>}
            {selectedWs && (
              <form onSubmit={handleSaveWorkspace} className="space-y-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Workspace name</label>
                  <input
                    type="text"
                    value={selectedWs.workspace_name}
                    aria-label="Workspace name"
                    onChange={(e) => setSelectedWs({ ...selectedWs, workspace_name: e.target.value })}
                    className="min-w-0 max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                    required
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Workspace ID (App ID)</label>
                  <input
                    type="text"
                    value={selectedWs.workspace_id}
                    aria-label="Workspace ID"
                    onChange={(e) => setSelectedWs({ ...selectedWs, workspace_id: e.target.value })}
                    placeholder="e.g. PLBRDCVUS0YE8ME3E8XSHV5D"
                    className="min-w-0 max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono"
                    required
                  />
                </div>

                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">API Key</label>
                  <input
                    type="text"
                    value={selectedWs.api_key}
                    aria-label="Workspace API key"
                    onChange={(e) => setSelectedWs({ ...selectedWs, api_key: e.target.value })}
                    placeholder="e.g. F9ED1AC8BB3449E8B6D94E5C"
                    className="min-w-0 max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 w-full border border-gray-300 rounded-lg px-3 py-2 text-sm font-mono"
                    required
                  />
                </div>

                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Data center</label>
                    <select
                      value={selectedWs.data_center}
                    aria-label="Workspace data center"
                      onChange={(e) => setSelectedWs({ ...selectedWs, data_center: e.target.value })}
                      className="min-w-0 max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
                    >
                      <option value="03">DC-03 (India - api-03.moengage.com)</option>
                      <option value="01">DC-01 (US - api-01.moengage.com)</option>
                      <option value="02">DC-02 (EU - api-02.moengage.com)</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">Status</label>
                    <select
                      value={selectedWs.is_active ? 'active' : 'inactive'}
                    aria-label="Workspace sync status"
                      onChange={(e) => setSelectedWs({ ...selectedWs, is_active: e.target.value === 'active' })}
                      className="min-w-0 max-w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 w-full border border-gray-300 rounded-lg px-3 py-2 text-sm"
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
                    className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-2 px-4 py-2 border border-gray-300 rounded-lg text-sm font-medium text-gray-700 hover:bg-gray-50"
                  >
                    Close
                  </button>
                  <button
                    type="submit"
                    disabled={savingWs}
                    className="workspace-button-primary"
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
