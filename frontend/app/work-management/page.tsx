'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  fetchWorkManagementDashboard,
  fetchTurnaroundAnalytics,
  transferJiraTicket,
  aiRebalanceWorkload,
} from '@/lib/api';

type JiraUserItem = {
  account_id: string;
  name: string;
  email: string;
  role: string;
  open_tickets_count: number;
  completed_tickets_count: number;
  blocked_tickets_count: number;
  total_handled_count: number;
  completion_rate: number;
  due_today_count: number;
  due_tomorrow_count: number;
  due_day_after_count: number;
  overdue_count: number;
};

type OperatorVelocityItem = {
  name: string;
  role: string;
  completed_count: number;
  avg_cycle_time_days: number;
  avg_cycle_time_hours: number;
  fastest_hours: number;
  slowest_days: number;
  velocity_rating: string;
};

type RoadblockTicketItem = {
  key: string;
  summary: string;
  assignee: string;
  status: string;
  roadblock_category: string;
  root_cause: string;
  aging_hours: number;
  aging_days: number;
  duedate: string | null;
};

type TurnaroundAnalyticsData = {
  project: string;
  total_tickets_analyzed: number;
  completed_count: number;
  active_roadblocks_count: number;
  team_avg_cycle_time_days: number;
  team_avg_cycle_time_hours: number;
  operator_velocities: OperatorVelocityItem[];
  roadblock_attribution: {
    total_roadblocks: number;
    tata_capital: {
      count: number;
      percentage: number;
      label: string;
    };
    karix_meta: {
      count: number;
      percentage: number;
      label: string;
    };
    attributics: {
      count: number;
      percentage: number;
      label: string;
    };
    reasons_breakdown: Record<string, number>;
  };
  blocked_tickets: RoadblockTicketItem[];
};

type WorkItem = {
  key: string;
  id: string;
  summary: string;
  status: string;
  status_category: 'PENDING' | 'BLOCKED' | 'DONE';
  assignee_name: string;
  assignee_account_id: string | null;
  assignee_role: string;
  reporter: string;
  duedate: string | null;
  timeline_bucket: 'OVERDUE' | 'TODAY' | 'TOMORROW' | 'DAY_AFTER' | 'LATER' | 'NO_DATE';
  days_relative: number | null;
  channel: string;
  attachment_count: number;
  created: string;
  updated: string;
  labels: string[];
};

type TransferProposal = {
  issue_key: string;
  summary: string;
  current_assignee: string;
  target_assignee: string;
  target_account_id: string;
  reason: string;
  executed: boolean;
};

type WorkManagementData = {
  project: string;
  total_tickets: number;
  status_counts: {
    PENDING: number;
    BLOCKED: number;
    DONE: number;
  };
  timeline_counts: {
    OVERDUE: number;
    TODAY: number;
    TOMORROW: number;
    DAY_AFTER: number;
    LATER: number;
    NO_DATE: number;
  };
  channel_counts: Record<string, number>;
  assignees: JiraUserItem[];
  work_items: WorkItem[];
  last_synced_at: string;
};

export default function WorkManagementPage() {
  const [data, setData] = useState<WorkManagementData | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedProject, setSelectedProject] = useState<string>('SWCM');
  // Tab Switcher
  const [activeTab, setActiveTab] = useState<'OPERATIONS' | 'ANALYTICS'>('OPERATIONS');
  const [analyticsData, setAnalyticsData] = useState<TurnaroundAnalyticsData | null>(null);
  const [analyticsLoading, setAnalyticsLoading] = useState<boolean>(false);

  // Filters
  const [selectedTimeline, setSelectedTimeline] = useState<string>('ALL');
  const [selectedStatus, setSelectedStatus] = useState<string>('ALL');
  const [selectedAssignee, setSelectedAssignee] = useState<string>('ALL');
  const [searchQuery, setSearchQuery] = useState<string>('');

  // Transfer Modal
  const [transferItem, setTransferItem] = useState<WorkItem | null>(null);
  const [transferTargetId, setTransferTargetId] = useState<string>('');
  const [handoverNote, setHandoverNote] = useState<string>('');
  const [transferring, setTransferring] = useState<boolean>(false);

  // AI Rebalance
  const [aiPrompt, setAiPrompt] = useState<string>('');
  const [aiProposals, setAiProposals] = useState<TransferProposal[]>([]);
  const [aiReasoning, setAiReasoning] = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState<boolean>(false);
  const [autoExecute, setAutoExecute] = useState<boolean>(false);
  const [showAiDrawer, setShowAiDrawer] = useState<boolean>(false);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetchWorkManagementDashboard(selectedProject, 100);
      setData(res);
      const aRes = await fetchTurnaroundAnalytics(selectedProject, 100);
      setAnalyticsData(aRes);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load Jira work management');
    } finally {
      setLoading(false);
    }
  }, [selectedProject]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRefresh = async () => {
    try {
      setRefreshing(true);
      setError(null);
      const res = await fetchWorkManagementDashboard(selectedProject, 100);
      setData(res);
      const aRes = await fetchTurnaroundAnalytics(selectedProject, 100);
      setAnalyticsData(aRes);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Refresh failed');
    } finally {
      setRefreshing(false);
    }
  };

  const handleExecuteTransfer = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!transferItem || !transferTargetId) return;

    try {
      setTransferring(true);
      await transferJiraTicket(transferItem.key, transferTargetId, handoverNote);
      setTransferItem(null);
      setHandoverNote('');
      await handleRefresh();
      alert(`Ticket ${transferItem.key} successfully transferred in Jira!`);
    } catch (err: unknown) {
      alert(`Transfer failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setTransferring(false);
    }
  };

  const handleRunAiRebalance = async () => {
    if (!aiPrompt.trim()) return;
    try {
      setAiLoading(true);
      setError(null);
      setShowAiDrawer(true);
      const res = await aiRebalanceWorkload(aiPrompt, selectedProject, autoExecute);
      setAiProposals(res.proposals || []);
      setAiReasoning(res.reasoning || null);
      if (autoExecute) {
        await handleRefresh();
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'AI Rebalance failed');
    } finally {
      setAiLoading(false);
    }
  };

  const channelBadges: Record<string, string> = {
    WhatsApp: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    RCS: 'bg-purple-50 text-purple-700 border-purple-200',
    SMS: 'bg-amber-50 text-amber-700 border-amber-200',
    Email: 'bg-blue-50 text-blue-700 border-blue-200',
    General: 'bg-gray-100 text-gray-700 border-gray-200',
  };

  // Filtered tickets
  const filteredItems = (data?.work_items || []).filter((w) => {
    if (selectedTimeline !== 'ALL' && w.timeline_bucket !== selectedTimeline) return false;
    if (selectedStatus !== 'ALL' && w.status_category !== selectedStatus) return false;
    if (selectedAssignee !== 'ALL' && w.assignee_name.toLowerCase() !== selectedAssignee.toLowerCase()) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchKey = w.key.toLowerCase().includes(q);
      const matchSum = w.summary.toLowerCase().includes(q);
      const matchChan = w.channel.toLowerCase().includes(q);
      if (!matchKey && !matchSum && !matchChan) return false;
    }
    return true;
  });

  return (
    <div className="space-y-8 max-w-7xl mx-auto pb-16">
      {/* Page Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-200 pb-6">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-gray-900">Jira Work Management & Dispatcher</h1>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              Jira Project: {selectedProject}
            </span>
          </div>
          <p className="text-sm text-gray-500 mt-1">
            Track pending tickets by assignee, timeline deadlines, and rebalance campaign workloads across team members and interns.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-2">
            <label className="text-xs font-bold text-gray-500 uppercase tracking-wider">Project:</label>
            <select
              value={selectedProject}
              onChange={(e) => setSelectedProject(e.target.value)}
              className="border border-gray-300 rounded-lg px-3 py-2 text-xs font-bold bg-white text-gray-800 shadow-sm focus:ring-2 focus:ring-blue-500"
            >
              <option value="SWCM">TATA Service and wealth Campaign Manager (SWCM)</option>
              <option value="TCN">Tata Capital New (TCN)</option>
              <option value="ALL">All Tata Projects Combined</option>
              <option value="TM">TCHFL Marketing (TM)</option>
              <option value="TAT">TataCapital (TAT)</option>
              <option value="MON">Moneyfy (MON)</option>
              <option value="COL">Collections (COL)</option>
            </select>
          </div>
          <button
            onClick={handleRefresh}
            disabled={refreshing}
            className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold rounded-lg border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 shadow-sm transition-all"
          >
            <svg
              className={`w-3.5 h-3.5 ${refreshing ? 'animate-spin' : ''}`}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.5"
            >
              <polyline points="23 4 23 10 17 10" />
              <polyline points="1 20 1 14 7 14" />
              <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
            </svg>
            {refreshing ? 'Syncing Jira...' : 'Refresh from Jira'}
          </button>
        </div>
      </div>

      {/* View Mode Switcher */}
      <div className="flex items-center gap-2 border-b border-gray-200 pb-3">
        <button
          onClick={() => setActiveTab('OPERATIONS')}
          className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2 ${
            activeTab === 'OPERATIONS'
              ? 'bg-gray-900 text-white shadow-sm'
              : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
        >
          <span>📋</span> Operational Queues & Dispatcher
        </button>
        <button
          onClick={() => setActiveTab('ANALYTICS')}
          className={`px-4 py-2 rounded-xl text-xs font-bold transition-all flex items-center gap-2 ${
            activeTab === 'ANALYTICS'
              ? 'bg-indigo-600 text-white shadow-sm shadow-indigo-100'
              : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
          }`}
        >
          <span>📊</span> Management Turnaround & Bottleneck Matrix
          <span className="text-[10px] bg-white/20 px-1.5 py-0.5 rounded-full font-semibold">
            SLA View
          </span>
        </button>
      </div>

      {/* MANAGEMENT ANALYTICS VIEW */}
      {activeTab === 'ANALYTICS' && analyticsData && (
        <div className="space-y-6">
          {/* Executive KPI Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* Card 1: Team Avg Turnaround */}
            <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm flex flex-col justify-between">
              <div>
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-400 block">Avg Turnaround Velocity</span>
                <div className="text-3xl font-extrabold text-gray-900 mt-1">
                  {analyticsData.team_avg_cycle_time_days} <span className="text-sm font-semibold text-gray-500">Days</span>
                </div>
                <p className="text-xs text-emerald-600 font-semibold mt-1">
                  {analyticsData.team_avg_cycle_time_hours} hrs average brief-to-done
                </p>
              </div>
              <div className="mt-3 pt-3 border-t border-gray-100 text-[11px] text-gray-500">
                Based on {analyticsData.completed_count} completed briefs
              </div>
            </div>

            {/* Card 2: Roadblock Attribution Ratio */}
            <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm flex flex-col justify-between">
              <div>
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-400 block">Primary Bottleneck Driver</span>
                <div className="text-2xl font-extrabold text-blue-900 mt-1">
                  {analyticsData.roadblock_attribution.tata_capital.percentage}% Client-Side
                </div>
                <p className="text-xs text-blue-600 font-semibold mt-1">
                  {analyticsData.roadblock_attribution.tata_capital.count} tickets waiting on Tata Capital
                </p>
              </div>
              <div className="mt-3 pt-3 border-t border-gray-100 text-[11px] text-gray-500">
                Base & content dependencies
              </div>
            </div>

            {/* Card 3: Gateway Review Gate */}
            <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm flex flex-col justify-between">
              <div>
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-400 block">Gateway Review Gate</span>
                <div className="text-2xl font-extrabold text-purple-900 mt-1">
                  {analyticsData.roadblock_attribution.karix_meta.count} Briefs
                </div>
                <p className="text-xs text-purple-600 font-semibold mt-1">
                  {analyticsData.roadblock_attribution.karix_meta.percentage}% at Karix/Meta gate
                </p>
              </div>
              <div className="mt-3 pt-3 border-t border-gray-100 text-[11px] text-gray-500">
                Awaiting carrier delivery & approvals
              </div>
            </div>

            {/* Card 4: Internal Attributics Queue */}
            <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm flex flex-col justify-between">
              <div>
                <span className="text-[10px] font-bold uppercase tracking-wider text-gray-400 block">Attributics Ops Queue</span>
                <div className="text-2xl font-extrabold text-amber-900 mt-1">
                  {analyticsData.roadblock_attribution.attributics.count} Active
                </div>
                <p className="text-xs text-amber-600 font-semibold mt-1">
                  {analyticsData.roadblock_attribution.attributics.percentage}% in internal drafting
                </p>
              </div>
              <div className="mt-3 pt-3 border-t border-gray-100 text-[11px] text-gray-500">
                Healthy operator throughput
              </div>
            </div>
          </div>

          {/* Bottleneck Responsibility Visual Bar */}
          <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-xs font-bold uppercase tracking-wider text-gray-900">
                  Roadblock Attribution & Responsibility Split ({analyticsData.active_roadblocks_count} Stalled Tickets)
                </h3>
                <p className="text-xs text-gray-500">Where are campaigns getting stuck? Explains delays to executive management.</p>
              </div>
            </div>

            {/* 3-Color Visual Stacked Bar */}
            <div className="w-full h-4 bg-gray-100 rounded-full overflow-hidden flex shadow-inner">
              <div
                className="bg-blue-600 h-full transition-all"
                style={{ width: `${analyticsData.roadblock_attribution.tata_capital.percentage}%` }}
                title={`Tata Capital: ${analyticsData.roadblock_attribution.tata_capital.percentage}%`}
              />
              <div
                className="bg-purple-500 h-full transition-all"
                style={{ width: `${analyticsData.roadblock_attribution.karix_meta.percentage}%` }}
                title={`Karix / Meta Gate: ${analyticsData.roadblock_attribution.karix_meta.percentage}%`}
              />
              <div
                className="bg-amber-400 h-full transition-all"
                style={{ width: `${analyticsData.roadblock_attribution.attributics.percentage}%` }}
                title={`Attributics Queue: ${analyticsData.roadblock_attribution.attributics.percentage}%`}
              />
            </div>

            {/* Legend */}
            <div className="flex flex-wrap items-center gap-5 pt-1 text-xs">
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-blue-600" />
                <span className="font-semibold text-gray-700">Tata Capital Dependencies ({analyticsData.roadblock_attribution.tata_capital.percentage}%)</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-purple-500" />
                <span className="font-semibold text-gray-700">Karix / Meta Gateway Gate ({analyticsData.roadblock_attribution.karix_meta.percentage}%)</span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-3 h-3 rounded-full bg-amber-400" />
                <span className="font-semibold text-gray-700">Attributics Ops Queue ({analyticsData.roadblock_attribution.attributics.percentage}%)</span>
              </div>
            </div>
          </div>

          {/* Operator Turnaround Leaderboard */}
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
            <div className="p-4 border-b border-gray-100">
              <h3 className="text-xs font-bold uppercase tracking-wider text-gray-900">
                Operator Turnaround Velocity Leaderboard ({selectedProject})
              </h3>
              <p className="text-xs text-gray-500">Shows cycle times (hours and days) for each team member from brief creation to Done.</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-gray-50 text-gray-500 font-bold uppercase text-[10px] border-b border-gray-100">
                  <tr>
                    <th className="py-2.5 px-4">Operator</th>
                    <th className="py-2.5 px-3">Role</th>
                    <th className="py-2.5 px-3 text-emerald-700">Completed (Done)</th>
                    <th className="py-2.5 px-3">Avg Turnaround (Days)</th>
                    <th className="py-2.5 px-3">Avg Turnaround (Hours)</th>
                    <th className="py-2.5 px-3">Fastest Record</th>
                    <th className="py-2.5 px-3">Slowest Record</th>
                    <th className="py-2.5 px-4 text-right">Velocity Rating</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {analyticsData.operator_velocities.map((op) => (
                    <tr key={op.name} className="hover:bg-gray-50/50">
                      <td className="py-2.5 px-4 font-bold text-gray-900">{op.name}</td>
                      <td className="py-2.5 px-3 text-gray-500">{op.role}</td>
                      <td className="py-2.5 px-3">
                        <span className="inline-flex items-center gap-1 font-extrabold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                          ✓ {op.completed_count}
                        </span>
                      </td>
                      <td className="py-2.5 px-3 font-extrabold text-gray-900">
                        {op.completed_count > 0 ? `${op.avg_cycle_time_days}d` : '—'}
                      </td>
                      <td className="py-2.5 px-3 text-gray-600 font-medium">
                        {op.completed_count > 0 ? `${op.avg_cycle_time_hours}h` : '—'}
                      </td>
                      <td className="py-2.5 px-3 font-medium text-emerald-600">
                        {op.completed_count > 0 ? `${op.fastest_hours}h` : '—'}
                      </td>
                      <td className="py-2.5 px-3 font-medium text-gray-500">
                        {op.completed_count > 0 ? `${op.slowest_days}d` : '—'}
                      </td>
                      <td className="py-2.5 px-4 text-right">
                        <span
                          className={`inline-flex px-2 py-0.5 rounded-full text-[10px] font-extrabold uppercase tracking-wider ${
                            op.velocity_rating === 'EXCELLENT'
                              ? 'bg-emerald-100 text-emerald-800'
                              : op.velocity_rating === 'FAST'
                              ? 'bg-blue-100 text-blue-800'
                              : op.velocity_rating === 'STANDARD'
                              ? 'bg-amber-100 text-amber-800'
                              : 'bg-gray-100 text-gray-600'
                          }`}
                        >
                          {op.velocity_rating.replace('_', ' ')}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Stalled Tickets Root Cause Diagnostics Table */}
          <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
            <div className="p-4 border-b border-gray-100">
              <h3 className="text-xs font-bold uppercase tracking-wider text-gray-900">
                Active Roadblock Tickets Diagnostic ({analyticsData.blocked_tickets.length} Stalled Items)
              </h3>
              <p className="text-xs text-gray-500">Every stalled ticket classified by root cause and responsible entity.</p>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-gray-50 text-gray-500 font-bold uppercase text-[10px] border-b border-gray-100">
                  <tr>
                    <th className="py-2.5 px-4">Ticket</th>
                    <th className="py-2.5 px-3">Assignee</th>
                    <th className="py-2.5 px-4">Roadblock Root Cause</th>
                    <th className="py-2.5 px-3">Responsible Party</th>
                    <th className="py-2.5 px-3">Aging Time</th>
                    <th className="py-2.5 px-3 text-right">Due Date</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {analyticsData.blocked_tickets.map((t) => {
                    const isHighAging = t.aging_days >= 1.0;
                    const isTata = t.roadblock_category.includes('Tata');
                    const isKarix = t.roadblock_category.includes('Karix');

                    return (
                      <tr key={t.key} className="hover:bg-gray-50/50">
                        <td className="py-2.5 px-4 font-bold">
                          <a
                            href={`https://tatacapital-team.atlassian.net/browse/${t.key}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="text-blue-600 hover:underline"
                          >
                            {t.key}
                          </a>
                        </td>
                        <td className="py-2.5 px-3 font-medium text-gray-800">{t.assignee}</td>
                        <td className="py-2.5 px-4 text-gray-700">{t.root_cause}</td>
                        <td className="py-2.5 px-3">
                          <span
                            className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                              isTata
                                ? 'bg-blue-50 text-blue-700 border-blue-200'
                                : isKarix
                                ? 'bg-purple-50 text-purple-700 border-purple-200'
                                : 'bg-amber-50 text-amber-700 border-amber-200'
                            }`}
                          >
                            {t.roadblock_category}
                          </span>
                        </td>
                        <td className="py-2.5 px-3">
                          <span
                            className={`text-[10px] font-extrabold px-2 py-0.5 rounded ${
                              isHighAging ? 'bg-red-50 text-red-700' : 'bg-gray-100 text-gray-700'
                            }`}
                          >
                            {t.aging_days}d ({t.aging_hours}h)
                          </span>
                        </td>
                        <td className="py-2.5 px-3 text-right text-gray-500 font-medium">
                          {t.duedate || 'No Due Date'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* OPERATIONAL VIEW CONTAINER */}
      {activeTab === 'OPERATIONS' && (
        <div className="space-y-8">

      {error && (
        <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-xs text-red-700 flex items-center gap-3">
          <svg className="w-5 h-5 text-red-500 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
          </svg>
          <div className="flex-1">{error}</div>
        </div>
      )}

      {/* 1. Unified Operator Throughput & Capacity Module */}
      {data && (() => {
        const overloadedCount = data.assignees.filter((u) => u.open_tickets_count >= 8).length;
        const availableCount = data.assignees.filter((u) => u.open_tickets_count < 4).length;
        const maxLoadedUser = [...data.assignees].sort((a, b) => b.open_tickets_count - a.open_tickets_count)[0];

        const getInitials = (name: string) => {
          const parts = name.trim().split(' ');
          if (parts.length >= 2) return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
          return (name.slice(0, 2) || 'OP').toUpperCase();
        };

        return (
          <div className="space-y-4">
            {/* Unified Operator Capacity & Throughput Table */}
            <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
              <div className="p-4 border-b border-gray-100 flex flex-col md:flex-row md:items-center justify-between gap-3 bg-gradient-to-r from-gray-50/80 to-white">
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-xs font-bold uppercase tracking-wider text-gray-900">
                      Team Member Capacity & Delivery Throughput
                    </h2>
                    <span className="text-[11px] font-bold px-2 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
                      {selectedProject}
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Consolidated view of active queues, load capacity limits, SLA delivery, and completion rates. Click any row to filter tickets.
                  </p>
                </div>

                <div className="flex items-center gap-2 text-xs">
                  <span className="px-2.5 py-1 rounded-lg bg-gray-100 font-semibold text-gray-700">
                    Total Operators: <strong>{data.assignees.length}</strong>
                  </span>
                  <span className={`px-2.5 py-1 rounded-lg font-semibold ${overloadedCount > 0 ? 'bg-red-50 text-red-700 border border-red-200' : 'bg-gray-100 text-gray-600'}`}>
                    Overloaded (≥8): <strong>{overloadedCount}</strong>
                  </span>
                  <span className="px-2.5 py-1 rounded-lg bg-emerald-50 text-emerald-700 border border-emerald-200 font-semibold">
                    Available (&lt;4): <strong>{availableCount}</strong>
                  </span>
                  {selectedAssignee !== 'ALL' && (
                    <button
                      onClick={() => setSelectedAssignee('ALL')}
                      className="px-2.5 py-1 rounded-lg bg-blue-600 text-white font-bold hover:bg-blue-700 transition-all flex items-center gap-1 shadow-2xs"
                    >
                      Filtered: {selectedAssignee} ✕
                    </button>
                  )}
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-gray-50/80 text-gray-500 font-bold uppercase text-[10px] border-b border-gray-100">
                    <tr>
                      <th className="py-2.5 px-4">Operator & Role</th>
                      <th className="py-2.5 px-3">Workload Status</th>
                      <th className="py-2.5 px-3 text-amber-700">Pending</th>
                      <th className="py-2.5 px-3 text-purple-700">Blocked</th>
                      <th className="py-2.5 px-3 text-red-600">Overdue SLA</th>
                      <th className="py-2.5 px-3">Today / Tmrw</th>
                      <th className="py-2.5 px-3 text-emerald-700">Completed</th>
                      <th className="py-2.5 px-3">Handled</th>
                      <th className="py-2.5 px-4">Completion %</th>
                      <th className="py-2.5 px-4 text-right">Quick Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {data.assignees.map((u) => {
                      const isSelected = selectedAssignee.toLowerCase() === u.name.toLowerCase();
                      const isOverloaded = u.open_tickets_count >= 8;
                      const isModerate = u.open_tickets_count >= 4 && u.open_tickets_count < 8;
                      const hasUrgentOverdue = u.overdue_count > 0;

                      return (
                        <tr
                          key={u.account_id}
                          onClick={() => setSelectedAssignee(isSelected ? 'ALL' : u.name)}
                          className={`cursor-pointer transition-colors ${
                            isSelected
                              ? 'bg-blue-50/50 font-medium'
                              : 'hover:bg-gray-50/70'
                          }`}
                        >
                          <td className="py-3 px-4">
                            <div className="flex items-center gap-2.5">
                              <div
                                className={`w-8 h-8 rounded-full flex items-center justify-center text-[11px] font-extrabold text-white shadow-xs ${
                                  isOverloaded
                                    ? 'bg-red-600'
                                    : isModerate
                                    ? 'bg-amber-600'
                                    : 'bg-indigo-600'
                                }`}
                              >
                                {getInitials(u.name)}
                              </div>
                              <div>
                                <div className="font-bold text-gray-900 flex items-center gap-1.5">
                                  <span>{u.name}</span>
                                  {isSelected && (
                                    <span className="text-[10px] text-blue-600 bg-blue-100 px-1.5 py-0.2 rounded font-bold">
                                      Active Filter
                                    </span>
                                  )}
                                </div>
                                <span
                                  className={`text-[10px] font-bold px-1.5 py-0.2 rounded-full inline-block mt-0.5 ${
                                    u.role === 'Core Operator'
                                      ? 'bg-blue-50 text-blue-700 border border-blue-200'
                                      : 'bg-purple-50 text-purple-700 border border-purple-200'
                                  }`}
                                >
                                  {u.role}
                                </span>
                              </div>
                            </div>
                          </td>

                          <td className="py-3 px-3">
                            <div className="space-y-1">
                              <span
                                className={`inline-flex items-center gap-1 text-[10px] font-extrabold px-2 py-0.5 rounded-full border ${
                                  isOverloaded
                                    ? 'bg-red-50 text-red-700 border-red-200'
                                    : isModerate
                                    ? 'bg-amber-50 text-amber-700 border-amber-200'
                                    : 'bg-emerald-50 text-emerald-700 border-emerald-200'
                                }`}
                              >
                                <span
                                  className={`w-1.5 h-1.5 rounded-full ${
                                    isOverloaded
                                    ? 'bg-red-500 animate-pulse'
                                    : isModerate
                                    ? 'bg-amber-500'
                                    : 'bg-emerald-500'
                                  }`}
                                />
                                {isOverloaded ? 'Overloaded' : isModerate ? 'Moderate' : 'Available'} ({u.open_tickets_count})
                              </span>
                              <div className="w-24 bg-gray-100 rounded-full h-1.5 overflow-hidden">
                                <div
                                  className={`h-1.5 rounded-full transition-all ${
                                    isOverloaded
                                      ? 'bg-red-500'
                                      : isModerate
                                      ? 'bg-amber-500'
                                      : 'bg-emerald-500'
                                  }`}
                                  style={{ width: `${Math.min(100, (u.open_tickets_count / 15) * 100)}%` }}
                                />
                              </div>
                            </div>
                          </td>

                          <td className="py-3 px-3 font-bold text-amber-800">{u.open_tickets_count}</td>
                          <td className="py-3 px-3 font-bold text-purple-800">
                            {u.blocked_tickets_count > 0 ? (
                              <span className="bg-purple-50 text-purple-700 border border-purple-200 px-1.5 py-0.5 rounded font-bold">
                                {u.blocked_tickets_count}
                              </span>
                            ) : (
                              '0'
                            )}
                          </td>
                          <td className="py-3 px-3">
                            {hasUrgentOverdue ? (
                              <span className="inline-flex items-center gap-1 font-extrabold text-red-700 bg-red-100/80 px-2 py-0.5 rounded border border-red-300 animate-pulse">
                                🚨 {u.overdue_count}
                              </span>
                            ) : (
                              <span className="text-gray-400 font-medium">0</span>
                            )}
                          </td>
                          <td className="py-3 px-3 text-gray-700 font-medium">
                            <span className="text-gray-500">{u.due_today_count} today</span>
                            <span className="mx-1 text-gray-300">/</span>
                            <span className="font-semibold text-gray-800">{u.due_tomorrow_count} tmrw</span>
                          </td>
                          <td className="py-3 px-3">
                            <span className="inline-flex items-center gap-1 font-extrabold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                              ✓ {u.completed_tickets_count}
                            </span>
                          </td>
                          <td className="py-3 px-3 font-extrabold text-gray-900">{u.total_handled_count}</td>
                          <td className="py-3 px-4">
                            {u.total_handled_count > 0 ? (
                              <div className="space-y-1">
                                <div className="flex items-center justify-between text-[10px] text-gray-500 font-semibold">
                                  <span className="font-extrabold text-gray-800">{u.completion_rate}%</span>
                                </div>
                                <div className="w-20 bg-gray-100 rounded-full h-1.5 overflow-hidden">
                                  <div
                                    className="bg-emerald-500 h-1.5 rounded-full transition-all"
                                    style={{ width: `${Math.min(100, u.completion_rate)}%` }}
                                  />
                                </div>
                              </div>
                            ) : (
                              <span className="text-gray-400">—</span>
                            )}
                          </td>
                          <td className="py-3 px-4 text-right">
                            <div className="flex items-center justify-end gap-1.5" onClick={(e) => e.stopPropagation()}>
                              <button
                                onClick={() => setSelectedAssignee(isSelected ? 'ALL' : u.name)}
                                className={`px-2 py-1 rounded text-[11px] font-bold transition-all ${
                                  isSelected
                                    ? 'bg-blue-600 text-white'
                                    : 'bg-gray-100 hover:bg-gray-200 text-gray-700'
                                }`}
                                title="Filter ticket list to this assignee"
                              >
                                {isSelected ? 'Clear' : 'Filter'}
                              </button>
                              {isOverloaded && (
                                <button
                                  onClick={() => {
                                    setAiPrompt(`Relieve ${u.name} by reassigning tickets to available peers and interns`);
                                    setShowAiDrawer(true);
                                  }}
                                  className="px-2 py-1 rounded text-[11px] font-bold bg-indigo-50 hover:bg-indigo-100 text-indigo-700 border border-indigo-200 transition-all flex items-center gap-1"
                                  title="Open AI rebalancing for this operator"
                                >
                                  <span>⚡</span> Rebalance
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* 2. Autonomous AI Workload Balancing Agent - Smart Contextual Banner & Drawer */}
            <div className="bg-gradient-to-r from-slate-900 via-indigo-950 to-slate-900 border border-indigo-500/30 rounded-2xl p-4 sm:p-5 shadow-md text-white">
              {/* Header Row / Quick Alert */}
              <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                <div className="flex items-start gap-3.5">
                  <div className="p-2.5 bg-indigo-600/80 rounded-xl text-white shadow-inner shrink-0 mt-0.5">
                    <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M13 10V3L4 14h7v7l9-11h-7z" />
                    </svg>
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="text-sm font-bold tracking-tight text-white">
                        Autonomous AI Workload Balancing Agent
                      </h3>
                      <span className="text-[10px] uppercase font-extrabold px-2 py-0.5 rounded-full bg-indigo-500/30 text-indigo-300 border border-indigo-400/20">
                        Zero-Click Dispatcher
                      </span>
                    </div>
                    <p className="text-xs text-indigo-200/90 mt-1">
                      {maxLoadedUser && maxLoadedUser.open_tickets_count >= 8 ? (
                        <span>
                          <strong className="text-amber-300">⚠️ Workload Imbalance Detected:</strong>{' '}
                          {maxLoadedUser.name} holds {maxLoadedUser.open_tickets_count} tickets ({maxLoadedUser.overdue_count} overdue).{' '}
                          {availableCount} available team members ready for delegation.
                        </span>
                      ) : (
                        <span>
                          Queue is currently balanced. Use AI Dispatcher to redistribute tickets for tomorrow&apos;s upcoming campaign deadlines.
                        </span>
                      )}
                    </p>
                  </div>
                </div>

                <div className="flex flex-wrap items-center gap-2 shrink-0">
                  {maxLoadedUser && maxLoadedUser.open_tickets_count >= 8 && (
                    <button
                      onClick={() => {
                        setAiPrompt(`Relieve ${maxLoadedUser.name} of active tickets to available team members`);
                        setShowAiDrawer(true);
                      }}
                      className="px-3 py-1.5 rounded-xl text-xs font-bold bg-amber-500 hover:bg-amber-400 text-slate-950 transition-all flex items-center gap-1.5 shadow-sm"
                    >
                      <span>⚡</span> Quick Rebalance ({maxLoadedUser.name})
                    </button>
                  )}
                  <button
                    onClick={() => setShowAiDrawer(!showAiDrawer)}
                    className="px-3.5 py-1.5 rounded-xl text-xs font-bold bg-white/10 hover:bg-white/20 text-white border border-white/15 transition-all flex items-center gap-1.5"
                  >
                    <span>{showAiDrawer ? '▲ Collapse AI Drawer' : '✨ Custom Prompt & Dispatch ▾'}</span>
                  </button>
                </div>
              </div>

              {/* Expandable AI Prompt & Actions Drawer */}
              {showAiDrawer && (
                <div className="mt-5 pt-4 border-t border-indigo-800/60 space-y-4 animate-in fade-in duration-200">
                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
                    <label className="flex items-center gap-2 text-xs font-semibold text-indigo-200 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={autoExecute}
                        onChange={(e) => setAutoExecute(e.target.checked)}
                        className="rounded border-indigo-400 text-indigo-600 focus:ring-indigo-400 bg-indigo-950"
                      />
                      Auto-Execute Reassignments in Jira Cloud
                    </label>

                    <button
                      onClick={handleRunAiRebalance}
                      disabled={aiLoading || !aiPrompt.trim()}
                      className={`px-4 py-2 rounded-xl text-xs font-bold text-white shadow-sm transition-all flex items-center gap-2 ${
                        aiLoading || !aiPrompt.trim()
                          ? 'bg-indigo-700/50 text-indigo-300 cursor-not-allowed'
                          : 'bg-indigo-600 hover:bg-indigo-500 shadow-indigo-500/30'
                      }`}
                    >
                      {aiLoading ? (
                        <>
                          <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                          </svg>
                          <span>Analyzing Workloads...</span>
                        </>
                      ) : (
                        <>
                          <span>⚡</span>
                          <span>Run AI Rebalance</span>
                        </>
                      )}
                    </button>
                  </div>

                  <div className="space-y-2.5">
                    <input
                      type="text"
                      value={aiPrompt}
                      onChange={(e) => setAiPrompt(e.target.value)}
                      placeholder="e.g. 'Mrunalini is overloaded with tickets due this week, transfer 3 to available interns' or 'Dnyanesh is on leave, rebalance to Neel'"
                      className="w-full bg-slate-950/80 border border-indigo-500/40 rounded-xl px-4 py-3 text-xs text-white placeholder-indigo-300/50 focus:outline-none focus:ring-2 focus:ring-indigo-400 shadow-inner"
                    />

                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[11px] font-semibold text-indigo-300/70 uppercase">Quick Suggestions:</span>
                      {[
                        `Relieve ${maxLoadedUser?.name || 'top operator'} to available peers & interns`,
                        'Rebalance tickets due tomorrow evenly across team',
                        'Transfer overdue tickets to available core operators',
                      ].map((qp) => (
                        <button
                          key={qp}
                          onClick={() => setAiPrompt(qp)}
                          className="text-[11px] font-medium bg-white/10 hover:bg-white/20 text-indigo-200 px-2.5 py-1 rounded-lg border border-white/10 transition-all"
                        >
                          {qp}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* AI Output Box */}
                  {aiReasoning && (
                    <div className="mt-4 p-4 bg-slate-950/90 rounded-xl border border-indigo-500/40 shadow-inner space-y-3">
                      <div className="flex items-center gap-2 text-xs font-bold text-indigo-300">
                        <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        <span>AI Dispatch Plan ({aiProposals.length} Rebalancing Proposals)</span>
                      </div>
                      <p className="text-xs text-gray-300">{aiReasoning}</p>

                      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 pt-2">
                        {aiProposals.map((p) => (
                          <div key={p.issue_key} className="p-3 bg-white/5 border border-white/10 rounded-lg text-xs space-y-1.5">
                            <div className="flex items-center justify-between font-bold">
                              <span className="text-indigo-400">{p.issue_key}</span>
                              <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${p.executed ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30' : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'}`}>
                                {p.executed ? 'Reassigned in Jira ✓' : 'Proposed'}
                              </span>
                            </div>
                            <p className="text-gray-300 truncate font-medium">{p.summary}</p>
                            <div className="text-[11px] text-gray-400 flex items-center gap-1.5">
                              <span>{p.current_assignee}</span>
                              <span>→</span>
                              <span className="font-bold text-white">{p.target_assignee}</span>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        );
      })()}

      {/* Filter Ribbons */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm space-y-3">
        {/* Timeline Tabs */}
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs font-bold uppercase tracking-wider text-gray-400 mr-2">Timeline:</span>
            {[
              { id: 'ALL', label: 'All Active' },
              { id: 'TODAY', label: `Today (${data?.timeline_counts.TODAY || 0})` },
              { id: 'TOMORROW', label: `Tomorrow (${data?.timeline_counts.TOMORROW || 0})` },
              { id: 'DAY_AFTER', label: `Day After (${data?.timeline_counts.DAY_AFTER || 0})` },
              { id: 'LATER', label: `Later (${data?.timeline_counts.LATER || 0})` },
              { id: 'OVERDUE', label: `Overdue (${data?.timeline_counts.OVERDUE || 0})`, isAlert: true },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setSelectedTimeline(tab.id)}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
                  selectedTimeline === tab.id
                    ? tab.isAlert
                      ? 'bg-red-600 text-white shadow-sm'
                      : 'bg-blue-600 text-white shadow-sm'
                    : tab.isAlert
                    ? 'bg-red-50 text-red-700 hover:bg-red-100'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Search Box */}
          <div className="w-full md:w-64">
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search key, title, channel..."
              className="w-full border border-gray-300 rounded-lg px-3 py-1.5 text-xs text-gray-800"
            />
          </div>
        </div>

        {/* Status Category Tabs */}
        <div className="flex items-center gap-2 pt-2 border-t border-gray-100">
          <span className="text-xs font-bold uppercase tracking-wider text-gray-400 mr-2">Status:</span>
          {[
            { id: 'ALL', label: `All (${data?.total_tickets || 0})` },
            { id: 'PENDING', label: `Pending (${data?.status_counts.PENDING || 0})`, color: 'text-amber-700' },
            { id: 'BLOCKED', label: `Blocked (${data?.status_counts.BLOCKED || 0})`, color: 'text-red-700' },
            { id: 'DONE', label: `Done (${data?.status_counts.DONE || 0})`, color: 'text-emerald-700' },
          ].map((st) => (
            <button
              key={st.id}
              onClick={() => setSelectedStatus(st.id)}
              className={`px-3 py-1 rounded-md text-xs font-semibold transition-all ${
                selectedStatus === st.id
                  ? 'bg-gray-900 text-white'
                  : 'bg-gray-50 text-gray-600 hover:bg-gray-100'
              }`}
            >
              {st.label}
            </button>
          ))}

          {selectedAssignee !== 'ALL' && (
            <span className="ml-auto inline-flex items-center gap-1.5 bg-blue-50 text-blue-700 border border-blue-200 text-xs font-semibold px-2.5 py-1 rounded-md">
              Assignee: {selectedAssignee}
              <button onClick={() => setSelectedAssignee('ALL')} className="hover:text-blue-900 font-bold ml-1">
                ✕
              </button>
            </span>
          )}
        </div>
      </div>

      {/* Tickets List */}
      <div>
        <div className="flex items-center justify-between mb-3 text-xs text-gray-500 font-medium">
          <span>Showing {filteredItems.length} matching Jira tickets</span>
        </div>

        {filteredItems.length === 0 ? (
          <div className="p-12 text-center bg-white border border-gray-200 rounded-xl text-gray-400 text-xs">
            No tickets match the selected timeline and status filters.
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredItems.map((item) => {
              const isOverdue = item.timeline_bucket === 'OVERDUE';
              const isToday = item.timeline_bucket === 'TODAY';
              const isTomorrow = item.timeline_bucket === 'TOMORROW';

              return (
                <div
                  key={item.key}
                  className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm hover:shadow-md transition-all flex flex-col justify-between"
                >
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <a
                        href={`https://tatacapital-team.atlassian.net/browse/${item.key}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs font-bold text-blue-600 hover:underline flex items-center gap-1"
                      >
                        {item.key}
                        <svg className="w-3 h-3 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                        </svg>
                      </a>

                      <span
                        className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                          channelBadges[item.channel] || channelBadges.General
                        }`}
                      >
                        {item.channel}
                      </span>
                    </div>

                    <h3 className="text-xs font-bold text-gray-900 line-clamp-2 leading-relaxed">
                      {item.summary}
                    </h3>
                  </div>

                  <div className="mt-4 pt-3 border-t border-gray-100 space-y-2.5">
                    <div className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <span className="w-5 h-5 rounded-full bg-gray-200 text-[10px] font-bold text-gray-700 flex items-center justify-center">
                          {item.assignee_name.charAt(0)}
                        </span>
                        <span className="font-medium text-gray-800 truncate max-w-[120px]">
                          {item.assignee_name}
                        </span>
                      </div>

                      <span
                        className={`text-[10px] font-bold px-2 py-0.5 rounded ${
                          isOverdue
                            ? 'bg-red-50 text-red-700 border border-red-200'
                            : isToday
                            ? 'bg-amber-50 text-amber-700 border border-amber-200'
                            : isTomorrow
                            ? 'bg-blue-50 text-blue-700 border border-blue-200'
                            : 'bg-gray-50 text-gray-600 border border-gray-200'
                        }`}
                      >
                        {isOverdue
                          ? `Overdue (${Math.abs(item.days_relative || 0)}d)`
                          : isToday
                          ? 'Due Today'
                          : isTomorrow
                          ? 'Due Tomorrow'
                          : item.duedate || 'No Due Date'}
                      </span>
                    </div>

                    <div className="flex items-center justify-between pt-1">
                      <span className="text-[10px] font-semibold text-gray-400 uppercase">
                        Status: <strong className="text-gray-700">{item.status}</strong>
                      </span>

                      <button
                        onClick={() => {
                          setTransferItem(item);
                          setTransferTargetId(data?.assignees[0]?.account_id || '');
                        }}
                        className="text-[11px] font-bold text-indigo-600 hover:text-indigo-800 bg-indigo-50 hover:bg-indigo-100 px-2.5 py-1 rounded-md transition-all"
                      >
                        Transfer / Handover →
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
      </div>
      )}
      {/* Ticket Transfer Modal */}
      {transferItem && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-6 border border-gray-200 space-y-4">
            <div className="flex items-center justify-between border-b border-gray-100 pb-3">
              <div>
                <h3 className="text-sm font-bold text-gray-900">Transfer Ticket {transferItem.key}</h3>
                <p className="text-xs text-gray-500">Reassign in Jira Cloud and log a handover comment.</p>
              </div>
              <button onClick={() => setTransferItem(null)} className="text-gray-400 hover:text-gray-600">
                ✕
              </button>
            </div>

            <form onSubmit={handleExecuteTransfer} className="space-y-4">
              <div>
                <span className="text-xs font-semibold text-gray-500">Summary:</span>
                <p className="text-xs font-medium text-gray-800 mt-0.5">{transferItem.summary}</p>
              </div>

              <div>
                <span className="text-xs font-semibold text-gray-500">Current Assignee:</span>
                <p className="text-xs font-bold text-gray-900">{transferItem.assignee_name}</p>
              </div>

              <div>
                <label className="block text-xs font-bold text-gray-700 mb-1">Target Assignee</label>
                <select
                  value={transferTargetId}
                  onChange={(e) => setTransferTargetId(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-medium bg-gray-50"
                  required
                >
                  {data?.assignees.map((a) => (
                    <option key={a.account_id} value={a.account_id}>
                      {a.name} ({a.role}) — {a.open_tickets_count} open tickets
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-gray-700 mb-1">Handover Note (Optional)</label>
                <textarea
                  value={handoverNote}
                  onChange={(e) => setHandoverNote(e.target.value)}
                  placeholder="e.g. 'Handing over WhatsApp campaign brief. Creative images approved, needs template creation.'"
                  rows={3}
                  className="w-full border border-gray-300 rounded-lg p-2.5 text-xs text-gray-800 placeholder-gray-400"
                />
              </div>

              <div className="pt-3 border-t border-gray-100 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setTransferItem(null)}
                  className="px-4 py-2 border border-gray-300 rounded-lg text-xs font-semibold text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={transferring}
                  className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-xs font-bold hover:bg-indigo-700 shadow-sm"
                >
                  {transferring ? 'Transferring in Jira...' : 'Confirm Transfer'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
