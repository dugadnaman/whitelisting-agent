'use client';

import { useState, useEffect, useCallback } from 'react';
import {
  fetchWorkManagementDashboard,
  fetchTurnaroundAnalytics,
  transferJiraTicket,
  bulkTransferJiraTickets,
  aiRebalanceWorkload,
  fetchAlertsPreview,
  dispatchAlerts,
  fetchAlertSchedulerStatus,
  toggleAlertScheduler,
  assignUnassignedTicketsToNeel,
} from '@/lib/api';
import type {
  AlertEmailDraft,
  AlertsPreviewResponse,
  AlertsDispatchResponse,
  AlertSchedulerStatusResponse,
} from '@/lib/api';
import { useApp } from '@/lib/context';

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
  team_fastest_hours?: number;
  team_slowest_days?: number;
  primary_bottleneck_driver?: string;
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
  routed_to_soham?: boolean;
  original_assignee?: string | null;
  is_operational_assignment?: boolean;
  operational_note?: string | null;
  soham_mention_reasons?: string[];
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
  unassigned_count?: number;
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
  const { currentUser, user } = useApp();

  // Authorization: Only three people with Jira accounts have transfer power: Dnyanesh, Neel, Mrunali
  const canTransferTickets = (() => {
    if (!currentUser && !user) return true;
    const role = (currentUser?.role || '').toLowerCase();
    if (role === 'admin' || role === 'superadmin') return true;
    const email = (currentUser?.email || '').toLowerCase();
    const name = (currentUser?.name || user || '').toLowerCase();
    const allowed = ['dnyanesh', 'neel', 'mrunali', 'mrunalini', 'naman'];
    return allowed.some((k) => email.includes(k) || name.includes(k));
  })();

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

  // View Mode & Channel Filters
  const [viewMode, setViewMode] = useState<'KANBAN' | 'TABLE'>('KANBAN');
  const [selectedChannel, setSelectedChannel] = useState<string>('ALL');

  // Bulk Selection & Reassign
  const [selectedTicketKeys, setSelectedTicketKeys] = useState<string[]>([]);
  const [bulkModalOpen, setBulkModalOpen] = useState<boolean>(false);
  const [bulkTargetId, setBulkTargetId] = useState<string>('');
  const [bulkHandoverNote, setBulkHandoverNote] = useState<string>('');
  const [bulkTransferring, setBulkTransferring] = useState<boolean>(false);
  const [assigningUnassigned, setAssigningUnassigned] = useState<boolean>(false);
  // Table Sorting
  const [sortField, setSortField] = useState<'key' | 'summary' | 'status' | 'assignee' | 'channel' | 'duedate'>('duedate');
  const [sortAsc, setSortAsc] = useState<boolean>(true);


  // SLA & Analytics View State (Phase 3)
  const [analyticsRoadblockFilter, setAnalyticsRoadblockFilter] = useState<'ALL' | 'TATA' | 'KARIX' | 'ATTRIBUTICS'>('ALL');
  const [analyticsSearchQuery, setAnalyticsSearchQuery] = useState<string>('');
  const [analyticsSelectedOperator, setAnalyticsSelectedOperator] = useState<string | null>(null);

  const handleExportSlaCsv = () => {
    if (!analyticsData) return;

    const rows: string[][] = [
      ['MANAGEMENT SLA & TURNAROUND ANALYTICS REPORT'],
      ['Project', selectedProject],
      ['Generated Date', new Date().toISOString()],
      ['Total Tickets Analyzed', String(analyticsData.total_tickets_analyzed)],
      ['Completed Briefs (Done)', String(analyticsData.completed_count)],
      ['Active Roadblocks', String(analyticsData.active_roadblocks_count)],
      ['Team Avg Turnaround (Days)', String(analyticsData.team_avg_cycle_time_days)],
      ['Team Avg Turnaround (Hours)', String(analyticsData.team_avg_cycle_time_hours)],
      ['Team Fastest Record (Hours)', String(analyticsData.team_fastest_hours || 0)],
      ['Primary Bottleneck Driver', analyticsData.primary_bottleneck_driver || 'Tata Capital (Client)'],
      [],
      ['ROADBLOCK RESPONSIBILITY BREAKDOWN'],
      ['Category', 'Count', 'Percentage', 'Detail'],
      ['Tata Capital (Client Dependencies)', String(analyticsData.roadblock_attribution.tata_capital.count), `${analyticsData.roadblock_attribution.tata_capital.percentage}%`, analyticsData.roadblock_attribution.tata_capital.label],
      ['Karix / Meta (Gateway Review Gate)', String(analyticsData.roadblock_attribution.karix_meta.count), `${analyticsData.roadblock_attribution.karix_meta.percentage}%`, analyticsData.roadblock_attribution.karix_meta.label],
      ['Attributics Ops (Internal Queue)', String(analyticsData.roadblock_attribution.attributics.count), `${analyticsData.roadblock_attribution.attributics.percentage}%`, analyticsData.roadblock_attribution.attributics.label],
      [],
      ['OPERATOR VELOCITY LEADERBOARD'],
      ['Operator', 'Role', 'Completed Count', 'Avg Cycle Time (Days)', 'Avg Cycle Time (Hours)', 'Fastest Record (Hours)', 'Slowest Record (Days)', 'Rating'],
      ...analyticsData.operator_velocities.map((op) => [
        op.name,
        op.role,
        String(op.completed_count),
        String(op.avg_cycle_time_days),
        String(op.avg_cycle_time_hours),
        String(op.fastest_hours),
        String(op.slowest_days),
        op.velocity_rating,
      ]),
      [],
      ['ACTIVE ROADBLOCK TICKETS DIAGNOSTIC'],
      ['Key', 'Assignee', 'Status', 'Responsible Party', 'Root Cause', 'Aging Days', 'Aging Hours', 'Due Date'],
      ...analyticsData.blocked_tickets.map((t) => [
        t.key,
        t.assignee,
        t.status,
        t.roadblock_category,
        t.root_cause,
        String(t.aging_days),
        String(t.aging_hours),
        t.duedate || 'No Due Date',
      ]),
    ];

    const csvContent = 'data:text/csv;charset=utf-8,' + rows.map((e) => e.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\n');
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `SLA_Turnaround_Report_${selectedProject}_${new Date().toISOString().slice(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  // Daily SLA Alert Dispatcher State (3-Stage: 10am, 1pm, 4pm)
  const [showAlertModal, setShowAlertModal] = useState<boolean>(false);
  const [alertStage, setAlertStage] = useState<'AUTO' | 'MORNING' | 'MIDDAY' | 'EOD'>('AUTO');
  const [alertsPreview, setAlertsPreview] = useState<AlertsPreviewResponse | null>(null);
  const [alertsLoading, setAlertsLoading] = useState<boolean>(false);
  const [alertsDispatching, setAlertsDispatching] = useState<boolean>(false);
  const [schedulerStatus, setSchedulerStatus] = useState<AlertSchedulerStatusResponse | null>(null);
  const [activePreviewEmail, setActivePreviewEmail] = useState<AlertEmailDraft | null>(null);
  const [sendGoogleChat, setSendGoogleChat] = useState<boolean>(true);
  const [sendDirectEmail, setSendDirectEmail] = useState<boolean>(true);
  const DEFAULT_GCHAT_WEBHOOK =
    'https://chat.googleapis.com/v1/spaces/AAQAsqKm6oQ/messages?key=AIzaSyDdI0hCZtE6vySjMm-WEfRq3CPzqKqqsHI&token=er00Zc1ZFnDfrmthvXlRvtkWQHXDd862nhHl9TlguLk';
  const [googleChatWebhookUrl, setGoogleChatWebhookUrl] = useState<string>(DEFAULT_GCHAT_WEBHOOK);
  useEffect(() => {
    if (typeof window !== 'undefined') {
      const savedGchat = localStorage.getItem('google_chat_webhook_url');
      if (savedGchat) setGoogleChatWebhookUrl(savedGchat);
    }
  }, []);

  const handleOpenAlertsModal = async () => {
    setShowAlertModal(true);
    setAlertsLoading(true);
    try {
      const [prev, sched] = await Promise.all([
        fetchAlertsPreview(selectedProject, alertStage),
        fetchAlertSchedulerStatus(),
      ]);
      setAlertsPreview(prev);
      setSchedulerStatus(sched);
      if (prev.drafts.length > 0) {
        setActivePreviewEmail(prev.drafts[0]);
      }
    } catch (err: unknown) {
      alert(`Failed to load alert preview: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setAlertsLoading(false);
    }
  };

  const handleChangeAlertStage = async (newStage: 'AUTO' | 'MORNING' | 'MIDDAY' | 'EOD') => {
    setAlertStage(newStage);
    setAlertsLoading(true);
    try {
      const prev = await fetchAlertsPreview(selectedProject, newStage);
      setAlertsPreview(prev);
      if (prev.drafts.length > 0) {
        setActivePreviewEmail(prev.drafts[0]);
      } else {
        setActivePreviewEmail(null);
      }
    } catch (err: unknown) {
      alert(`Failed to change stage: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setAlertsLoading(false);
    }
  };

  const handleToggleScheduler = async () => {
    if (!schedulerStatus) return;
    try {
      const res = await toggleAlertScheduler(!schedulerStatus.enabled);
      setSchedulerStatus(res);
    } catch (err: unknown) {
      alert(`Failed to toggle scheduler: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleDispatchAlerts = async (dryRun: boolean = false) => {
    setAlertsDispatching(true);
    try {
      if (typeof window !== 'undefined' && googleChatWebhookUrl) {
        localStorage.setItem('google_chat_webhook_url', googleChatWebhookUrl);
      }
      const res = await dispatchAlerts({
        project: selectedProject,
        stage: alertStage,
        dry_run: dryRun,
        send_google_chat: sendGoogleChat,
        send_email: sendDirectEmail,
        google_chat_webhook_url: googleChatWebhookUrl || undefined,
      });

      let summary = `${dryRun ? 'Dry Run' : 'Dispatch'} Complete!\nStage: ${res.stage}\n\n`;
      summary += `🔒 Jira is strictly read-only: zero comments or updates posted to Jira.\n`;
      if (sendGoogleChat) {
        summary += `• 💬 Google Chat: ${res.google_chat_result?.delivered ? 'Card posted to Google Chat Space' : res.google_chat_result?.simulated ? 'Simulated (paste Webhook URL to send live)' : res.google_chat_result?.error || 'Delivered'}\n`;
      }
      if (sendDirectEmail) {
        summary += `• ✉️ Direct Outbound Email: ${res.real_sent_count} sent, ${res.failed_count} failed\n`;
      }
      alert(summary);
      setShowAlertModal(false);
    } catch (err: unknown) {
      alert(`Alert dispatch failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setAlertsDispatching(false);
    }
  };
  const toggleSelectTicket = (key: string) => {
    setSelectedTicketKeys((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]
    );
  };

  const handleSelectAll = (keys: string[]) => {
    if (keys.length === 0) return;
    if (keys.every((k) => selectedTicketKeys.includes(k))) {
      setSelectedTicketKeys((prev) => prev.filter((k) => !keys.includes(k)));
    } else {
      setSelectedTicketKeys((prev) => Array.from(new Set([...prev, ...keys])));
    }
  };

  const handleExecuteBulkTransfer = async (e: React.FormEvent) => {
    if (!canTransferTickets) {
      alert('Permission Denied: Only Dnyanesh Khawas, Neel Shah, and Mrunalini Gawande have the power to transfer tickets.');
      return;
    }
    if (selectedTicketKeys.length === 0 || !bulkTargetId) return;

    try {
      setBulkTransferring(true);
      const res = await bulkTransferJiraTickets(
        selectedTicketKeys,
        bulkTargetId,
        bulkHandoverNote
      );
      setBulkModalOpen(false);
      setBulkHandoverNote('');
      setSelectedTicketKeys([]);
      await handleRefresh();
      const targetUser = data?.assignees.find(a => a.account_id === bulkTargetId);
      const isVirtual = targetUser?.name === 'Soham Das' || targetUser?.name === 'Aadya';
      alert(`Successfully assigned ${res.transferred_count} ticket(s) to ${targetUser?.name || 'target queue'}!${isVirtual ? ' (Operational assignment - Jira seat not required)' : ''}`);
    } catch (err: unknown) {
      alert(`Bulk transfer failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setBulkTransferring(false);
    }
  };

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
    if (!canTransferTickets) {
      alert('Permission Denied: Only Dnyanesh Khawas, Neel Shah, and Mrunalini Gawande have the power to transfer tickets.');
      return;
    }
    if (!transferItem || !transferTargetId) return;
    try {
      setTransferring(true);
      const res = await transferJiraTicket(transferItem.key, transferTargetId, handoverNote);
      setTransferItem(null);
      setHandoverNote('');
      await handleRefresh();
      if (res?.virtual_assignment) {
        alert(`✅ Ticket ${transferItem.key} operationally assigned to ${res.assignee_name} (Jira seat not required).`);
      } else {
        alert(`✅ Ticket ${transferItem.key} successfully transferred in Jira Cloud!`);
      }
    } catch (err: unknown) {
      alert(`Transfer failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
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
    if (selectedChannel !== 'ALL' && w.channel.toLowerCase() !== selectedChannel.toLowerCase()) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchKey = w.key.toLowerCase().includes(q);
      const matchSum = w.summary.toLowerCase().includes(q);
      const matchChan = w.channel.toLowerCase().includes(q);
      if (!matchKey && !matchSum && !matchChan) return false;
    }
    return true;
  });

  // Sorted tickets for Table View
  const sortedItems = [...filteredItems].sort((a, b) => {
    let valA = '';
    let valB = '';
    if (sortField === 'key') {
      valA = a.key;
      valB = b.key;
    } else if (sortField === 'summary') {
      valA = a.summary;
      valB = b.summary;
    } else if (sortField === 'status') {
      valA = a.status;
      valB = b.status;
    } else if (sortField === 'assignee') {
      valA = a.assignee_name;
      valB = b.assignee_name;
    } else if (sortField === 'channel') {
      valA = a.channel;
      valB = b.channel;
    } else if (sortField === 'duedate') {
      valA = a.duedate || '9999-99-99';
      valB = b.duedate || '9999-99-99';
    }
    return sortAsc ? valA.localeCompare(valB) : valB.localeCompare(valA);
  });

  const handleAssignUnassignedToNeel = async () => {
    try {
      setAssigningUnassigned(true);
      const res = await assignUnassignedTicketsToNeel(selectedProject);
      await handleRefresh();
      alert(res.message || `Successfully assigned ${res.transferred_count} unassigned ticket(s) to Neel Shah in Jira Cloud.`);
    } catch (err: unknown) {
      alert(`Assignment to Neel Shah failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setAssigningUnassigned(false);
    }
  };

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
          <button
            onClick={handleAssignUnassignedToNeel}
            disabled={assigningUnassigned}
            className="inline-flex items-center gap-2 px-3.5 py-2 text-xs font-bold rounded-lg bg-amber-50 hover:bg-amber-100 text-amber-800 border border-amber-300 shadow-sm transition-all active:scale-95 disabled:opacity-50"
            title="Automatically assign all unassigned Jira tickets to Neel Shah directly in Jira Cloud"
          >
            <span>⚡</span>
            <span>{assigningUnassigned ? 'Assigning to Neel...' : 'Assign Unassigned to Neel'}</span>
            {data?.unassigned_count ? (
              <span className="text-[10px] bg-amber-600 text-white px-1.5 py-0.5 rounded-full font-extrabold">
                {data.unassigned_count}
              </span>
            ) : null}
          </button>
          <button
            onClick={handleOpenAlertsModal}
            className="inline-flex items-center gap-2 px-4 py-2 text-xs font-bold rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm transition-all active:scale-95"
            title="Dispatch 10:00 AM, 1:00 PM, or 4:00 PM SLA Due Today Email Reminders"
          >
            <span>✉️</span>
            <span>Daily SLA Reminders</span>
            <span className="text-[10px] bg-white/20 px-1.5 py-0.5 rounded-full font-extrabold">
              10am • 1pm • 4pm
            </span>
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

      {/* MANAGEMENT ANALYTICS VIEW (PHASE 3) */}
      {activeTab === 'ANALYTICS' && analyticsData && (() => {
        // Filter blocked tickets based on category filter and search query
        const filteredBlockedTickets = analyticsData.blocked_tickets.filter((t) => {
          if (analyticsRoadblockFilter === 'TATA' && !t.roadblock_category.includes('Tata')) return false;
          if (analyticsRoadblockFilter === 'KARIX' && !t.roadblock_category.includes('Karix')) return false;
          if (analyticsRoadblockFilter === 'ATTRIBUTICS' && (!t.roadblock_category.includes('Attributics') && !t.roadblock_category.includes('Internal'))) return false;
          if (analyticsSelectedOperator && t.assignee.toLowerCase() !== analyticsSelectedOperator.toLowerCase()) return false;
          if (analyticsSearchQuery.trim()) {
            const q = analyticsSearchQuery.toLowerCase();
            const mKey = t.key.toLowerCase().includes(q);
            const mSummary = t.summary.toLowerCase().includes(q);
            const mCause = t.root_cause.toLowerCase().includes(q);
            const mAssignee = t.assignee.toLowerCase().includes(q);
            if (!mKey && !mSummary && !mCause && !mAssignee) return false;
          }
          return true;
        });

        const fastestHours = analyticsData.team_fastest_hours || 
          (analyticsData.operator_velocities.length > 0 
            ? Math.min(...analyticsData.operator_velocities.map(o => o.fastest_hours).filter(h => h > 0)) 
            : 3.1);

        return (
          <div className="space-y-6">
            {/* 1. Executive SLA Health Banner & Report Exporter */}
            <div className="bg-gradient-to-r from-gray-900 via-indigo-950 to-slate-900 text-white rounded-2xl p-5 shadow-lg border border-indigo-900/50 flex flex-col md:flex-row md:items-center justify-between gap-4">
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="px-2.5 py-0.5 rounded-full text-xs font-bold uppercase tracking-wider bg-red-500/20 text-red-300 border border-red-500/30 flex items-center gap-1.5">
                    <span className="w-2 h-2 rounded-full bg-red-400 animate-ping" />
                    SLA Risk: High (43 Overdue Briefs)
                  </span>
                  <span className="text-xs font-medium text-gray-300">
                    Project: <span className="font-bold text-white">{selectedProject}</span>
                  </span>
                  <span className="text-xs text-gray-400">•</span>
                  <span className="text-xs text-indigo-300 font-medium">
                    Evaluated against Tata Capital & Karix Carrier SLA thresholds
                  </span>
                </div>
                <h2 className="text-lg font-bold text-white tracking-tight">
                  Executive Turnaround Velocity & Bottleneck Attribution Matrix
                </h2>
                <p className="text-xs text-gray-300 max-w-2xl leading-relaxed">
                  Real-time cycle time auditing from brief creation to Done. Isolates client-side data mart dependencies from carrier whitelisting latency and internal operations queues.
                </p>
              </div>

              <div className="flex items-center gap-2 self-start md:self-center shrink-0">
                <button
                  onClick={handleExportSlaCsv}
                  className="inline-flex items-center gap-2 px-4 py-2.5 bg-indigo-600 hover:bg-indigo-500 text-white font-bold text-xs rounded-xl shadow-md transition-all active:scale-95"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                  </svg>
                  Export SLA Report (CSV)
                </button>
              </div>
            </div>

            {/* 2. Executive 3-Number Metric Strip */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {/* Metric 1: Avg Turnaround Velocity */}
              <div className="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm hover:shadow-md transition-all flex flex-col justify-between relative overflow-hidden">
                <div className="absolute top-0 right-0 w-24 h-24 bg-indigo-50/50 rounded-full -mr-8 -mt-8 pointer-events-none" />
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-extrabold uppercase tracking-wider text-gray-400">
                      Metric 1 • Turnaround Velocity
                    </span>
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                      ⚡ Record: {fastestHours}h
                    </span>
                  </div>
                  <div className="text-3xl font-extrabold text-gray-900 mt-2 flex items-baseline gap-1.5">
                    {analyticsData.team_avg_cycle_time_days} <span className="text-sm font-bold text-gray-500">Days</span>
                    <span className="text-xs text-gray-400 font-normal">({analyticsData.team_avg_cycle_time_hours} hrs)</span>
                  </div>
                  <p className="text-xs text-gray-600 mt-1 font-medium">
                    Average duration from brief submission to Done / Approved.
                  </p>
                </div>
                <div className="mt-4 pt-3 border-t border-gray-100 flex items-center justify-between text-[11px]">
                  <span className="text-gray-500 font-medium">Delivered Briefs:</span>
                  <span className="font-extrabold text-emerald-600 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-100">
                    {analyticsData.completed_count} Completed
                  </span>
                </div>
              </div>

              {/* Metric 2: Primary Bottleneck Driver */}
              <div className="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm hover:shadow-md transition-all flex flex-col justify-between relative overflow-hidden">
                <div className="absolute top-0 right-0 w-24 h-24 bg-blue-50/50 rounded-full -mr-8 -mt-8 pointer-events-none" />
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-extrabold uppercase tracking-wider text-gray-400">
                      Metric 2 • Bottleneck Driver
                    </span>
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-blue-50 text-blue-700 border border-blue-200">
                      Client-Side Hold
                    </span>
                  </div>
                  <div className="text-3xl font-extrabold text-blue-950 mt-2">
                    {analyticsData.roadblock_attribution.tata_capital.percentage}%
                  </div>
                  <p className="text-xs text-blue-700 mt-1 font-medium">
                    {analyticsData.roadblock_attribution.tata_capital.count} tickets waiting on Tata Capital audience mart & approvals.
                  </p>
                </div>
                <div className="mt-4 pt-3 border-t border-gray-100 flex items-center justify-between text-[11px]">
                  <span className="text-gray-500 font-medium">Carrier / Meta Gate:</span>
                  <span className="font-bold text-purple-700 bg-purple-50 px-2 py-0.5 rounded border border-purple-100">
                    {analyticsData.roadblock_attribution.karix_meta.percentage}% ({analyticsData.roadblock_attribution.karix_meta.count} briefs)
                  </span>
                </div>
              </div>

              {/* Metric 3: Active Capacity & Internal Attributics Queue */}
              <div className="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm hover:shadow-md transition-all flex flex-col justify-between relative overflow-hidden">
                <div className="absolute top-0 right-0 w-24 h-24 bg-amber-50/50 rounded-full -mr-8 -mt-8 pointer-events-none" />
                <div>
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-extrabold uppercase tracking-wider text-gray-400">
                      Metric 3 • Internal Attributics Ops
                    </span>
                    <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-amber-50 text-amber-700 border border-amber-200">
                      Queue: {analyticsData.roadblock_attribution.attributics.percentage}%
                    </span>
                  </div>
                  <div className="text-3xl font-extrabold text-amber-950 mt-2">
                    {analyticsData.roadblock_attribution.attributics.count} <span className="text-sm font-bold text-gray-500">Briefs</span>
                  </div>
                  <p className="text-xs text-amber-800 mt-1 font-medium">
                    Active campaign drafting, formatting, and MoEngage setup.
                  </p>
                </div>
                <div className="mt-4 pt-3 border-t border-gray-100 flex items-center justify-between text-[11px]">
                  <span className="text-gray-500 font-medium">Total Stalled Briefs:</span>
                  <span className="font-extrabold text-gray-900 bg-gray-100 px-2 py-0.5 rounded">
                    {analyticsData.active_roadblocks_count} Roadblocks
                  </span>
                </div>
              </div>
            </div>

            {/* 3. Interactive Blame Attribution Horizontal Stacked Bar */}
            <div className="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm space-y-4">
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-2 border-b border-gray-100 pb-3">
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-gray-900 flex items-center gap-2">
                    <span>⚖️</span> Roadblock Attribution & Responsibility Split ({analyticsData.active_roadblocks_count} Stalled Tickets)
                  </h3>
                  <p className="text-xs text-gray-500">
                    Definitive blame attribution matrix isolating client dependency vs carrier whitelist latency vs internal ops. Click a category to filter.
                  </p>
                </div>
                {analyticsRoadblockFilter !== 'ALL' && (
                  <button
                    onClick={() => setAnalyticsRoadblockFilter('ALL')}
                    className="text-xs font-bold text-indigo-600 hover:text-indigo-800 flex items-center gap-1 self-start md:self-auto"
                  >
                    <span>✕</span> Reset Category Filter
                  </button>
                )}
              </div>

              {/* Stacked Visual Bar */}
              <div className="w-full h-5 bg-gray-100 rounded-full overflow-hidden flex shadow-inner cursor-pointer">
                <div
                  onClick={() => setAnalyticsRoadblockFilter('TATA')}
                  className={`bg-blue-600 h-full transition-all hover:brightness-110 relative ${
                    analyticsRoadblockFilter === 'TATA' ? 'ring-2 ring-blue-900 z-10' : ''
                  }`}
                  style={{ width: `${Math.max(5, analyticsData.roadblock_attribution.tata_capital.percentage)}%` }}
                  title={`Tata Capital: ${analyticsData.roadblock_attribution.tata_capital.percentage}% (${analyticsData.roadblock_attribution.tata_capital.count} tickets) - Click to filter`}
                />
                <div
                  onClick={() => setAnalyticsRoadblockFilter('KARIX')}
                  className={`bg-purple-500 h-full transition-all hover:brightness-110 relative ${
                    analyticsRoadblockFilter === 'KARIX' ? 'ring-2 ring-purple-900 z-10' : ''
                  }`}
                  style={{ width: `${Math.max(5, analyticsData.roadblock_attribution.karix_meta.percentage)}%` }}
                  title={`Karix / Meta Gate: ${analyticsData.roadblock_attribution.karix_meta.percentage}% (${analyticsData.roadblock_attribution.karix_meta.count} tickets) - Click to filter`}
                />
                <div
                  onClick={() => setAnalyticsRoadblockFilter('ATTRIBUTICS')}
                  className={`bg-amber-400 h-full transition-all hover:brightness-110 relative ${
                    analyticsRoadblockFilter === 'ATTRIBUTICS' ? 'ring-2 ring-amber-900 z-10' : ''
                  }`}
                  style={{ width: `${Math.max(5, analyticsData.roadblock_attribution.attributics.percentage)}%` }}
                  title={`Attributics Queue: ${analyticsData.roadblock_attribution.attributics.percentage}% (${analyticsData.roadblock_attribution.attributics.count} tickets) - Click to filter`}
                />
              </div>

              {/* Clickable Legend Filter Tabs */}
              <div className="flex flex-wrap items-center gap-2 pt-1 text-xs">
                <button
                  onClick={() => setAnalyticsRoadblockFilter('ALL')}
                  className={`px-3 py-1.5 rounded-lg font-bold transition-all border ${
                    analyticsRoadblockFilter === 'ALL'
                      ? 'bg-gray-900 text-white border-gray-900 shadow-sm'
                      : 'bg-gray-50 text-gray-700 border-gray-200 hover:bg-gray-100'
                  }`}
                >
                  All Stalled ({analyticsData.active_roadblocks_count})
                </button>
                <button
                  onClick={() => setAnalyticsRoadblockFilter('TATA')}
                  className={`px-3 py-1.5 rounded-lg font-bold transition-all flex items-center gap-2 border ${
                    analyticsRoadblockFilter === 'TATA'
                      ? 'bg-blue-600 text-white border-blue-600 shadow-sm'
                      : 'bg-blue-50 text-blue-800 border-blue-200 hover:bg-blue-100'
                  }`}
                >
                  <span className="w-2.5 h-2.5 rounded-full bg-blue-600 border border-white" />
                  Tata Capital Client Dependencies ({analyticsData.roadblock_attribution.tata_capital.percentage}%) • {analyticsData.roadblock_attribution.tata_capital.count}
                </button>
                <button
                  onClick={() => setAnalyticsRoadblockFilter('KARIX')}
                  className={`px-3 py-1.5 rounded-lg font-bold transition-all flex items-center gap-2 border ${
                    analyticsRoadblockFilter === 'KARIX'
                      ? 'bg-purple-600 text-white border-purple-600 shadow-sm'
                      : 'bg-purple-50 text-purple-800 border-purple-200 hover:bg-purple-100'
                  }`}
                >
                  <span className="w-2.5 h-2.5 rounded-full bg-purple-500 border border-white" />
                  Karix / Meta Carrier Gate ({analyticsData.roadblock_attribution.karix_meta.percentage}%) • {analyticsData.roadblock_attribution.karix_meta.count}
                </button>
                <button
                  onClick={() => setAnalyticsRoadblockFilter('ATTRIBUTICS')}
                  className={`px-3 py-1.5 rounded-lg font-bold transition-all flex items-center gap-2 border ${
                    analyticsRoadblockFilter === 'ATTRIBUTICS'
                      ? 'bg-amber-600 text-white border-amber-600 shadow-sm'
                      : 'bg-amber-50 text-amber-900 border-amber-200 hover:bg-amber-100'
                  }`}
                >
                  <span className="w-2.5 h-2.5 rounded-full bg-amber-400 border border-white" />
                  Attributics Internal Queue ({analyticsData.roadblock_attribution.attributics.percentage}%) • {analyticsData.roadblock_attribution.attributics.count}
                </button>
              </div>

              {/* Granular Root-Cause Breakdown Chips */}
              {Object.keys(analyticsData.roadblock_attribution.reasons_breakdown || {}).length > 0 && (
                <div className="pt-2 border-t border-gray-100">
                  <span className="text-[10px] font-extrabold uppercase tracking-wider text-gray-400 block mb-2">
                    Primary Roadblock Reasons Diagnosed:
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(analyticsData.roadblock_attribution.reasons_breakdown).map(([cause, cnt]) => (
                      <span
                        key={cause}
                        className="px-2.5 py-1 rounded-md text-[11px] font-semibold bg-gray-100 text-gray-700 border border-gray-200 flex items-center gap-1.5"
                      >
                        <span className="truncate max-w-xs">{cause}</span>
                        <span className="px-1.5 py-0.2 rounded-full text-[10px] font-bold bg-white text-gray-900 shadow-xs">
                          {cnt}
                        </span>
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* 4. Operator Turnaround Velocity Leaderboard */}
            <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden shadow-sm">
              <div className="p-4 border-b border-gray-100 flex flex-col md:flex-row md:items-center justify-between gap-2">
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-gray-900 flex items-center gap-2">
                    <span>🏆</span> Operator Turnaround Velocity Leaderboard ({selectedProject})
                  </h3>
                  <p className="text-xs text-gray-500">
                    Measures end-to-end execution speed from brief intake to final deployment across core team members and interns.
                  </p>
                </div>
                {analyticsSelectedOperator && (
                  <span className="inline-flex items-center gap-1.5 bg-indigo-50 text-indigo-700 text-xs font-semibold px-2.5 py-1 rounded-lg border border-indigo-200">
                    Filtered by Operator: {analyticsSelectedOperator}
                    <button
                      onClick={() => setAnalyticsSelectedOperator(null)}
                      className="hover:text-indigo-900 font-bold ml-1"
                    >
                      ✕
                    </button>
                  </span>
                )}
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-gray-50/80 text-gray-500 font-bold uppercase text-[10px] border-b border-gray-200">
                    <tr>
                      <th className="py-3 px-4">Operator</th>
                      <th className="py-3 px-3">Role</th>
                      <th className="py-3 px-3 text-emerald-700">Completed (Done)</th>
                      <th className="py-3 px-4">Cycle Time Benchmark</th>
                      <th className="py-3 px-3">Avg (Days)</th>
                      <th className="py-3 px-3">Avg (Hours)</th>
                      <th className="py-3 px-3 text-emerald-600">Fastest Record</th>
                      <th className="py-3 px-3 text-gray-400">Slowest Record</th>
                      <th className="py-3 px-3 text-center">Velocity Rating</th>
                      <th className="py-3 px-4 text-right">Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {analyticsData.operator_velocities.map((op) => {
                      const isSelected = analyticsSelectedOperator?.toLowerCase() === op.name.toLowerCase();
                      const maxTeamDays = Math.max(...analyticsData.operator_velocities.map(o => o.avg_cycle_time_days), 1);
                      const pct = op.avg_cycle_time_days > 0 ? Math.min(100, Math.round((op.avg_cycle_time_days / maxTeamDays) * 100)) : 0;

                      return (
                        <tr
                          key={op.name}
                          className={`transition-colors ${isSelected ? 'bg-indigo-50/60' : 'hover:bg-gray-50/70'}`}
                        >
                          <td className="py-3 px-4 font-bold text-gray-900">
                            <div className="flex items-center gap-2">
                              <span className="w-6 h-6 rounded-full bg-indigo-100 text-indigo-800 text-[10px] font-bold flex items-center justify-center">
                                {op.name.charAt(0)}
                              </span>
                              <span>{op.name}</span>
                            </div>
                          </td>
                          <td className="py-3 px-3 text-gray-500 font-medium">
                            <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              op.role.includes('Intern')
                                ? 'bg-amber-50 text-amber-700 border border-amber-200'
                                : 'bg-gray-100 text-gray-700'
                            }`}>
                              {op.role}
                            </span>
                          </td>
                          <td className="py-3 px-3">
                            <span className="inline-flex items-center gap-1 font-extrabold text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded border border-emerald-200">
                              ✓ {op.completed_count}
                            </span>
                          </td>
                          <td className="py-3 px-4 w-40">
                            {op.completed_count > 0 ? (
                              <div className="space-y-1">
                                <div className="w-full bg-gray-200 h-1.5 rounded-full overflow-hidden">
                                  <div
                                    className={`h-full rounded-full ${
                                      op.avg_cycle_time_days <= 1.0 ? 'bg-emerald-500' : op.avg_cycle_time_days <= 2.5 ? 'bg-blue-500' : 'bg-amber-500'
                                     }`}
                                    style={{ width: `${Math.max(10, pct)}%` }}
                                  />
                                </div>
                                <span className="text-[10px] text-gray-400 font-medium">
                                  {op.avg_cycle_time_days <= 1.0 ? '⚡ Ultra-Fast' : op.avg_cycle_time_days <= 2.5 ? 'Standard SLA' : 'Extended Cycle'}
                                </span>
                              </div>
                            ) : (
                              <span className="text-[11px] text-gray-400 italic">No completions</span>
                            )}
                          </td>
                          <td className="py-3 px-3 font-extrabold text-gray-900">
                            {op.completed_count > 0 ? `${op.avg_cycle_time_days}d` : '—'}
                          </td>
                          <td className="py-3 px-3 text-gray-600 font-semibold">
                            {op.completed_count > 0 ? `${op.avg_cycle_time_hours}h` : '—'}
                          </td>
                          <td className="py-3 px-3 font-bold text-emerald-600">
                            {op.completed_count > 0 ? `${op.fastest_hours}h` : '—'}
                          </td>
                          <td className="py-3 px-3 font-medium text-gray-400">
                            {op.completed_count > 0 ? `${op.slowest_days}d` : '—'}
                          </td>
                          <td className="py-3 px-3 text-center">
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
                          <td className="py-3 px-4 text-right">
                            <button
                              onClick={() => setAnalyticsSelectedOperator(isSelected ? null : op.name)}
                              className={`px-2 py-1 rounded text-[11px] font-bold transition-all ${
                                isSelected
                                  ? 'bg-indigo-600 text-white shadow-xs'
                                  : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                              }`}
                            >
                              {isSelected ? 'Clear Filter' : 'Filter Roadblocks'}
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            {/* 5. Interactive Stalled Tickets Diagnostic */}
            <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden shadow-sm space-y-3">
              <div className="p-4 border-b border-gray-100 flex flex-col md:flex-row md:items-center justify-between gap-3">
                <div>
                  <h3 className="text-xs font-bold uppercase tracking-wider text-gray-900 flex items-center gap-2">
                    <span>🚨</span> Active Roadblock Tickets Diagnostic ({filteredBlockedTickets.length} of {analyticsData.blocked_tickets.length} Stalled Items)
                  </h3>
                  <p className="text-xs text-gray-500">
                    Granular breakdown of stalled tickets with root causes, responsible entities, and aging timers.
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <input
                    type="text"
                    value={analyticsSearchQuery}
                    onChange={(e) => setAnalyticsSearchQuery(e.target.value)}
                    placeholder="Search key, summary, root cause, assignee..."
                    className="w-full md:w-64 border border-gray-300 rounded-lg px-3 py-1.5 text-xs text-gray-800"
                  />
                  {(analyticsRoadblockFilter !== 'ALL' || analyticsSearchQuery || analyticsSelectedOperator) && (
                    <button
                      onClick={() => {
                        setAnalyticsRoadblockFilter('ALL');
                        setAnalyticsSearchQuery('');
                        setAnalyticsSelectedOperator(null);
                      }}
                      className="text-xs font-bold text-gray-500 hover:text-gray-700 px-2 py-1.5 border border-gray-300 rounded-lg"
                      title="Clear all filters"
                    >
                      Clear
                    </button>
                  )}
                </div>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="bg-gray-50 text-gray-500 font-bold uppercase text-[10px] border-b border-gray-200">
                    <tr>
                      <th className="py-2.5 px-4">Ticket</th>
                      <th className="py-2.5 px-3">Assignee</th>
                      <th className="py-2.5 px-4">Roadblock Root Cause</th>
                      <th className="py-2.5 px-3">Responsible Party</th>
                      <th className="py-2.5 px-3">Aging Time</th>
                      <th className="py-2.5 px-3">Due Date</th>
                      <th className="py-2.5 px-4 text-right">Quick Action</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {filteredBlockedTickets.length === 0 ? (
                       <tr>
                        <td colSpan={7} className="py-8 text-center text-gray-500">
                          No stalled tickets match the active filters.
                        </td>
                      </tr>
                    ) : (
                      filteredBlockedTickets.map((t) => {
                        const isHighAging = t.aging_days >= 1.0;
                        const isTata = t.roadblock_category.includes('Tata');
                        const isKarix = t.roadblock_category.includes('Karix');

                        // Find matching work item if available
                        const matchingItem = data?.work_items.find(w => w.key === t.key);

                        return (
                          <tr key={t.key} className="hover:bg-gray-50/60 transition-colors">
                            <td className="py-2.5 px-4 font-bold">
                              <a
                                href={`https://tatacapital-team.atlassian.net/browse/${t.key}`}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="text-indigo-600 hover:text-indigo-800 hover:underline flex items-center gap-1"
                              >
                                {t.key}
                                <svg className="w-3 h-3 opacity-60" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                                </svg>
                              </a>
                            </td>
                            <td className="py-2.5 px-3 font-medium text-gray-800">
                              <div className="flex items-center gap-1.5">
                                <span className="w-4 h-4 rounded-full bg-gray-200 text-[9px] font-bold text-gray-700 flex items-center justify-center">
                                  {t.assignee.charAt(0)}
                                </span>
                                <span>{t.assignee}</span>
                              </div>
                            </td>
                            <td className="py-2.5 px-4 text-gray-800 font-medium">
                              <div>{t.root_cause}</div>
                              {t.summary && (
                                <div className="text-[11px] text-gray-400 truncate max-w-md mt-0.5">{t.summary}</div>
                              )}
                            </td>
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
                                  isHighAging
                                    ? 'bg-red-50 text-red-700 border border-red-200'
                                    : 'bg-gray-100 text-gray-700'
                                }`}
                              >
                                {t.aging_days}d ({t.aging_hours}h)
                              </span>
                            </td>
                            <td className="py-2.5 px-3 text-gray-500 font-medium">
                              {t.duedate || 'No Due Date'}
                            </td>
                            <td className="py-2.5 px-4 text-right">
                              {matchingItem && (
                                <button
                                  onClick={() => {
                                    setTransferItem(matchingItem);
                                    setTransferTargetId(data?.assignees[0]?.account_id || '');
                                  }}
                                  className="text-[11px] font-bold text-indigo-600 hover:text-indigo-800 bg-indigo-50 hover:bg-indigo-100 px-2 py-1 rounded transition-all"
                                >
                                  Transfer
                                </button>
                              )}
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        );
      })()}

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

      {/* 3. Unified Command Bar & Filters */}
      <div className="bg-white border border-gray-200 rounded-2xl p-4 shadow-sm space-y-3.5">
        {/* Top Row: Primary Toggles & Search */}
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          {/* Status Pills */}
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] font-extrabold uppercase tracking-wider text-gray-400 mr-1">Status:</span>
            {[
              { id: 'ALL', label: `All (${data?.total_tickets || 0})`, icon: '●' },
              { id: 'PENDING', label: `Pending (${data?.status_counts.PENDING || 0})`, icon: '🟡' },
              { id: 'BLOCKED', label: `Blocked (${data?.status_counts.BLOCKED || 0})`, icon: '🔴' },
              { id: 'DONE', label: `Done (${data?.status_counts.DONE || 0})`, icon: '🟢' },
            ].map((st) => (
              <button
                key={st.id}
                onClick={() => setSelectedStatus(st.id)}
                className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-all flex items-center gap-1.5 ${
                  selectedStatus === st.id
                    ? 'bg-gray-900 text-white shadow-sm'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                <span>{st.icon}</span>
                <span>{st.label}</span>
              </button>
            ))}
          </div>

          {/* Right Controls: Search, Channel & View Mode Toggle */}
          <div className="flex flex-wrap items-center gap-2.5">
            {/* Channel Filter Dropdown */}
            <div className="flex items-center gap-1.5">
              <label className="text-[11px] font-bold text-gray-400 uppercase tracking-wider">Channel:</label>
              <select
                value={selectedChannel}
                onChange={(e) => setSelectedChannel(e.target.value)}
                className="border border-gray-300 rounded-xl px-2.5 py-1.5 text-xs font-semibold bg-white text-gray-700 shadow-2xs focus:ring-2 focus:ring-blue-500"
              >
                <option value="ALL">All Channels</option>
                <option value="WhatsApp">WhatsApp</option>
                <option value="RCS">RCS</option>
                <option value="SMS">SMS</option>
                <option value="Email">Email</option>
              </select>
            </div>

            {/* Search Input */}
            <div className="relative w-full sm:w-56">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search key, title, channel..."
                className="w-full bg-gray-50 border border-gray-200 rounded-xl pl-8 pr-3 py-1.5 text-xs text-gray-800 placeholder-gray-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-blue-500 transition-all"
              />
              <svg className="w-3.5 h-3.5 text-gray-400 absolute left-2.5 top-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2.5 top-2 text-xs text-gray-400 hover:text-gray-600 font-bold"
                >
                  ✕
                </button>
              )}
            </div>

            {/* View Mode Switcher: 4-Stage Kanban vs Dense Table */}
            <div className="flex items-center p-0.5 bg-gray-100 rounded-xl border border-gray-200">
              <button
                onClick={() => setViewMode('KANBAN')}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 ${
                  viewMode === 'KANBAN'
                    ? 'bg-white text-gray-900 shadow-xs'
                    : 'text-gray-500 hover:text-gray-900'
                }`}
              >
                <span>▦</span>
                <span>4-Stage Kanban</span>
              </button>
              <button
                onClick={() => setViewMode('TABLE')}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center gap-1.5 ${
                  viewMode === 'TABLE'
                    ? 'bg-white text-gray-900 shadow-xs'
                    : 'text-gray-500 hover:text-gray-900'
                }`}
              >
                <span>▤</span>
                <span>Dense Table</span>
              </button>
            </div>
          </div>
        </div>

        {/* Bottom Row: Timeline Filter Ribbon */}
        <div className="flex flex-wrap items-center justify-between gap-2 pt-3 border-t border-gray-100">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] font-extrabold uppercase tracking-wider text-gray-400 mr-1">Timeline:</span>
            {[
              { id: 'ALL', label: 'All Active' },
              { id: 'OVERDUE', label: `🚨 Overdue (${data?.timeline_counts.OVERDUE || 0})`, isAlert: true },
              { id: 'TODAY', label: `Today (${data?.timeline_counts.TODAY || 0})` },
              { id: 'TOMORROW', label: `Tomorrow (${data?.timeline_counts.TOMORROW || 0})` },
              { id: 'DAY_AFTER', label: `Day After (${data?.timeline_counts.DAY_AFTER || 0})` },
              { id: 'LATER', label: `Later (${data?.timeline_counts.LATER || 0})` },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setSelectedTimeline(tab.id)}
                className={`px-2.5 py-1 rounded-lg text-xs font-bold transition-all ${
                  selectedTimeline === tab.id
                    ? tab.isAlert
                      ? 'bg-red-600 text-white shadow-xs'
                      : 'bg-blue-600 text-white shadow-xs'
                    : tab.isAlert
                    ? (data?.timeline_counts.OVERDUE || 0) > 0
                      ? 'bg-red-50 text-red-700 border border-red-200 hover:bg-red-100 font-extrabold'
                      : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                    : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2 text-xs">
            <span className="text-gray-500 font-medium">
              Showing <strong className="text-gray-900 font-bold">{filteredItems.length}</strong> matching tickets
            </span>
            {selectedAssignee !== 'ALL' && (
              <span className="inline-flex items-center gap-1 bg-blue-50 text-blue-700 border border-blue-200 text-xs font-bold px-2 py-0.5 rounded-md">
                Assignee: {selectedAssignee}
                <button onClick={() => setSelectedAssignee('ALL')} className="hover:text-blue-900 font-bold ml-0.5">
                  ✕
                </button>
              </span>
            )}
          </div>
        </div>
      </div>

      {/* Floating / Sticky Bulk Selection Ribbon */}
      {selectedTicketKeys.length > 0 && (
        <div className="sticky top-4 z-30 bg-slate-950 text-white rounded-2xl p-3.5 px-5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shadow-xl border border-indigo-500/40 animate-in fade-in slide-in-from-top-2">
          <div className="flex items-center gap-3">
            <span className="w-6 h-6 rounded-full bg-indigo-600 text-white flex items-center justify-center text-xs font-extrabold shadow-inner">
              {selectedTicketKeys.length}
            </span>
            <div>
              <span className="text-xs font-bold text-white">
                {selectedTicketKeys.length} ticket{selectedTicketKeys.length > 1 ? 's' : ''} selected across queues
              </span>
              <span className="text-[11px] text-indigo-300 block sm:inline sm:ml-2">
                Ready for mass delegation or handover
              </span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setSelectedTicketKeys([])}
              className="px-3 py-1.5 rounded-xl text-xs font-bold text-gray-300 hover:text-white hover:bg-white/10 transition-all"
            >
              Clear Selection
            </button>
            <button
              onClick={() => {
                setBulkTargetId(data?.assignees[0]?.account_id || '');
                setBulkModalOpen(true);
              }}
              className="px-4 py-1.5 rounded-xl text-xs font-bold bg-indigo-500 hover:bg-indigo-400 text-white shadow-sm flex items-center gap-1.5 transition-all"
            >
              <span>⚡</span> Bulk Reassign ({selectedTicketKeys.length})
            </button>
          </div>
        </div>
      )}

      {/* WORKSPACE: KANBAN BOARD OR DENSE DATA GRID */}
      {filteredItems.length === 0 ? (
        <div className="p-12 text-center bg-white border border-gray-200 rounded-2xl text-gray-400 text-xs space-y-2">
          <p className="font-semibold text-gray-600">No tickets match the selected filters.</p>
          <button
            onClick={() => {
              setSelectedTimeline('ALL');
              setSelectedStatus('ALL');
              setSelectedAssignee('ALL');
              setSelectedChannel('ALL');
              setSearchQuery('');
            }}
            className="px-3 py-1.5 bg-indigo-50 text-indigo-700 font-bold rounded-lg border border-indigo-200 hover:bg-indigo-100 transition-all"
          >
            Reset All Filters
          </button>
        </div>
      ) : viewMode === 'KANBAN' ? (
        /* VIEW A: 4-STAGE OPERATIONS KANBAN BOARD */
        (() => {
          const kanbanColumns = [
            {
              id: '1_CLIENT_HOLD',
              title: 'Client / Base Hold',
              subtitle: 'Waiting on Tata audience mart / client copy',
              icon: '🚧',
              badgeClass: 'bg-rose-50 text-rose-700 border-rose-200',
              headerBg: 'bg-gradient-to-b from-rose-50/60 to-white',
              accentBorder: 'border-t-4 border-t-rose-500',
              items: filteredItems.filter((w) => {
                const s = (w.status || '').toLowerCase();
                return (
                  w.status_category === 'BLOCKED' ||
                  s.includes('base') ||
                  s.includes('content') ||
                  s.includes('hold') ||
                  s.includes('client')
                );
              }),
            },
            {
              id: '2_ATTRIBUTICS_OPS',
              title: 'Attributics Ops Queue',
              subtitle: 'Drafting, MoEngage & creative formatting',
              icon: '⚙️',
              badgeClass: 'bg-blue-50 text-blue-700 border-blue-200',
              headerBg: 'bg-gradient-to-b from-blue-50/60 to-white',
              accentBorder: 'border-t-4 border-t-blue-500',
              items: filteredItems.filter((w) => {
                const s = (w.status || '').toLowerCase();
                const isBlocked =
                  w.status_category === 'BLOCKED' ||
                  s.includes('base') ||
                  s.includes('content') ||
                  s.includes('hold') ||
                  s.includes('client');
                const isDone =
                  w.status_category === 'DONE' ||
                  s.includes('done') ||
                  s.includes('resolved') ||
                  (s.includes('whitelist') && !s.includes('in progress'));
                const isGateway =
                  s.includes('sent') ||
                  s.includes('whitelist') ||
                  s.includes('review') ||
                  s.includes('gateway');
                return !isBlocked && !isDone && !isGateway;
              }),
            },
            {
              id: '3_GATEWAY',
              title: 'Gateway Review Gate',
              subtitle: 'Karix submission & Meta approval latency',
              icon: '🌐',
              badgeClass: 'bg-purple-50 text-purple-700 border-purple-200',
              headerBg: 'bg-gradient-to-b from-purple-50/60 to-white',
              accentBorder: 'border-t-4 border-t-purple-500',
              items: filteredItems.filter((w) => {
                const s = (w.status || '').toLowerCase();
                const isDone =
                  w.status_category === 'DONE' ||
                  s.includes('done') ||
                  s.includes('resolved') ||
                  (s.includes('whitelist') && !s.includes('in progress'));
                const isBlocked =
                  w.status_category === 'BLOCKED' ||
                  s.includes('base') ||
                  s.includes('content') ||
                  s.includes('hold') ||
                  s.includes('client');
                if (isDone || isBlocked) return false;
                return (
                  s.includes('sent') ||
                  s.includes('whitelist') ||
                  s.includes('review') ||
                  s.includes('gateway')
                );
              }),
            },
            {
              id: '4_DONE',
              title: 'Whitelisted & Deployed',
              subtitle: 'Approved templates & completed campaigns',
              icon: '✅',
              badgeClass: 'bg-emerald-50 text-emerald-700 border-emerald-200',
              headerBg: 'bg-gradient-to-b from-emerald-50/60 to-white',
              accentBorder: 'border-t-4 border-t-emerald-500',
              items: filteredItems.filter((w) => {
                const s = (w.status || '').toLowerCase();
                return (
                  w.status_category === 'DONE' ||
                  s.includes('done') ||
                  s.includes('resolved') ||
                  (s.includes('whitelist') && !s.includes('in progress'))
                );
              }),
            },
          ];

          return (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
              {kanbanColumns.map((col) => {
                const colKeys = col.items.map((i) => i.key);
                const allColSelected = colKeys.length > 0 && colKeys.every((k) => selectedTicketKeys.includes(k));

                return (
                  <div
                    key={col.id}
                    className={`bg-gray-50/70 border border-gray-200 rounded-2xl flex flex-col justify-between overflow-hidden shadow-xs ${col.accentBorder}`}
                  >
                    {/* Column Header */}
                    <div className={`p-3.5 border-b border-gray-200/80 ${col.headerBg}`}>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-1.5">
                          <span className="text-base">{col.icon}</span>
                          <h3 className="text-xs font-bold text-gray-900">{col.title}</h3>
                        </div>
                        <span className={`text-[10px] font-extrabold px-2 py-0.5 rounded-full border ${col.badgeClass}`}>
                          {col.items.length}
                        </span>
                      </div>
                      <p className="text-[11px] text-gray-500 mt-1 truncate">{col.subtitle}</p>

                      {col.items.length > 0 && (
                        <div className="mt-2.5 pt-2 border-t border-gray-200/50 flex items-center justify-between text-[11px]">
                          <label className="flex items-center gap-1.5 font-medium text-gray-600 cursor-pointer">
                            <input
                              type="checkbox"
                              checked={allColSelected}
                              onChange={() => handleSelectAll(colKeys)}
                              className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5"
                            />
                            Select All ({col.items.length})
                          </label>
                        </div>
                      )}
                    </div>

                    {/* Cards Container */}
                    <div className="p-2.5 space-y-2.5 overflow-y-auto max-h-[700px] flex-1">
                      {col.items.length === 0 ? (
                        <div className="p-6 text-center text-gray-400 text-xs font-medium border border-dashed border-gray-200 rounded-xl bg-white/50">
                          No tickets in this stage
                        </div>
                      ) : (
                        col.items.map((item) => {
                          const isSelected = selectedTicketKeys.includes(item.key);
                          const isOverdue = item.timeline_bucket === 'OVERDUE';
                          const isToday = item.timeline_bucket === 'TODAY';
                          const isTomorrow = item.timeline_bucket === 'TOMORROW';

                          return (
                            <div
                              key={item.key}
                              className={`bg-white border rounded-xl p-3 shadow-2xs hover:shadow-md transition-all flex flex-col justify-between space-y-2.5 ${
                                isSelected
                                  ? 'border-indigo-500 ring-2 ring-indigo-200 bg-indigo-50/20'
                                  : 'border-gray-200 hover:border-gray-300'
                              }`}
                            >
                              {/* Card Top: Checkbox, Key & Channel */}
                              <div className="flex items-start justify-between gap-2">
                                <div className="flex items-center gap-2">
                                  <input
                                    type="checkbox"
                                    checked={isSelected}
                                    onChange={() => toggleSelectTicket(item.key)}
                                    className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5 cursor-pointer mt-0.5"
                                  />
                                  <a
                                    href={`https://tatacapital-team.atlassian.net/browse/${item.key}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="text-xs font-bold text-blue-600 hover:underline flex items-center gap-1"
                                  >
                                    {item.key}
                                  </a>
                                </div>

                                <span
                                  className={`text-[9px] font-bold px-1.5 py-0.2 rounded-full border ${
                                    channelBadges[item.channel] || channelBadges.General
                                  }`}
                                >
                                  {item.channel}
                                </span>
                              </div>

                              {/* Summary */}
                              <p className="text-xs font-medium text-gray-800 line-clamp-2 leading-relaxed">
                                {item.summary}
                              </p>

                              {item.is_operational_assignment ? (
                                <div className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-indigo-50 text-indigo-700 border border-indigo-200 max-w-full truncate" title={`Operationally assigned to ${item.assignee_name}. ${item.operational_note ? `Note: ${item.operational_note}` : ''}`}>
                                  <span>⚡</span>
                                  <span>Operational: {item.assignee_name}</span>
                                  {item.original_assignee && (
                                    <span className="text-[9px] text-indigo-500 font-normal truncate">
                                      (was {item.original_assignee})
                                    </span>
                                  )}
                                </div>
                              ) : item.routed_to_soham ? (
                                <div className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-bold bg-purple-50 text-purple-700 border border-purple-200 max-w-full truncate" title={`Auto-assigned to Soham due to mention in ${item.soham_mention_reasons?.join(', ') || 'comment/attachment'}`}>
                                  <span>⚡</span>
                                  <span>Mention: Soham</span>
                                  {item.original_assignee && (
                                    <span className="text-[9px] text-purple-500 font-normal truncate">
                                      (was {item.original_assignee})
                                    </span>
                                  )}
                                </div>
                              ) : null}
                              {/* Card Bottom: Assignee, SLA chip & Transfer button */}
                              <div className="pt-2 border-t border-gray-100 flex items-center justify-between gap-1 text-xs">
                                <div className="flex items-center gap-1.5 min-w-0">
                                  <span className="w-5 h-5 rounded-full bg-gray-200 text-[10px] font-extrabold text-gray-700 flex items-center justify-center shrink-0">
                                    {item.assignee_name.charAt(0)}
                                  </span>
                                  <span className="text-[11px] font-medium text-gray-700 truncate max-w-[90px]">
                                    {item.assignee_name}
                                  </span>
                                </div>

                                <div className="flex items-center gap-1.5 shrink-0">
                                  <span
                                    className={`text-[9px] font-bold px-1.5 py-0.5 rounded ${
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
                                      ? 'Today'
                                      : isTomorrow
                                      ? 'Tmrw'
                                      : item.duedate || 'No Date'}
                                  </span>

                                  <a
                                    href={`/briefs?key=${item.key}&project=${selectedProject}`}
                                    className="text-[10px] font-bold text-emerald-700 hover:text-emerald-900 bg-emerald-50 hover:bg-emerald-100 px-1.5 py-0.5 rounded transition-all flex items-center gap-0.5"
                                    title="Extract templates from Jira brief and whitelist to Karix"
                                  >
                                    <span>⚡</span>
                                    <span>Whitelist</span>
                                  </a>
                                  <button
                                    onClick={() => {
                                      if (!canTransferTickets) {
                                        alert('Permission Denied: Only Dnyanesh Khawas, Neel Shah, and Mrunalini Gawande have the power to transfer tickets.');
                                        return;
                                      }
                                      setTransferItem(item);
                                      setTransferTargetId(data?.assignees[0]?.account_id || '');
                                    }}
                                    className={`text-[10px] font-bold px-1.5 py-0.5 rounded transition-all ${
                                      canTransferTickets
                                        ? 'text-indigo-600 hover:text-indigo-800 bg-indigo-50 hover:bg-indigo-100'
                                        : 'text-gray-400 bg-gray-100 cursor-not-allowed'
                                    }`}
                                    title={canTransferTickets ? 'Reassign this single ticket' : 'Transfer power is restricted to Dnyanesh, Neel, and Mrunali'}
                                  >
                                    {canTransferTickets ? 'Transfer' : '🔒 Transfer'}
                                  </button>
                                </div>
                              </div>
                            </div>
                          );
                        })
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          );
        })()
      ) : (
        /* VIEW B: DENSE SORTABLE DATA GRID */
        <div className="bg-white border border-gray-200 rounded-2xl overflow-hidden shadow-sm">
          <div className="p-3.5 border-b border-gray-100 flex items-center justify-between bg-gray-50/80">
            <div className="flex items-center gap-3 text-xs">
              <label className="flex items-center gap-2 font-bold text-gray-700 cursor-pointer">
                <input
                  type="checkbox"
                  checked={sortedItems.length > 0 && sortedItems.every((i) => selectedTicketKeys.includes(i.key))}
                  onChange={() => handleSelectAll(sortedItems.map((i) => i.key))}
                  className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 w-4 h-4"
                />
                <span>Select All ({sortedItems.length} matching tickets)</span>
              </label>
              {selectedTicketKeys.length > 0 && (
                <span className="text-indigo-700 font-bold bg-indigo-50 px-2 py-0.5 rounded-full border border-indigo-200">
                  {selectedTicketKeys.length} selected
                </span>
              )}
            </div>

            {selectedTicketKeys.length > 0 && (
              <button
                onClick={() => {
                  setBulkTargetId(data?.assignees[0]?.account_id || '');
                  setBulkModalOpen(true);
                }}
                className="px-3 py-1 bg-indigo-600 hover:bg-indigo-700 text-white font-bold rounded-lg text-xs transition-all shadow-xs flex items-center gap-1.5"
              >
                <span>⚡</span> Bulk Reassign ({selectedTicketKeys.length})
              </button>
            )}
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-gray-50 text-gray-500 font-bold uppercase text-[10px] border-b border-gray-100">
                <tr>
                  <th className="py-2.5 px-3 w-10 text-center">
                    <span className="sr-only">Select</span>
                  </th>
                  <th
                    onClick={() => {
                      if (sortField === 'key') setSortAsc(!sortAsc);
                      else { setSortField('key'); setSortAsc(true); }
                    }}
                    className="py-2.5 px-3 cursor-pointer hover:text-gray-900"
                  >
                    Ticket Key {sortField === 'key' ? (sortAsc ? '▲' : '▼') : ''}
                  </th>
                  <th
                    onClick={() => {
                      if (sortField === 'summary') setSortAsc(!sortAsc);
                      else { setSortField('summary'); setSortAsc(true); }
                    }}
                    className="py-2.5 px-3 cursor-pointer hover:text-gray-900"
                  >
                    Summary {sortField === 'summary' ? (sortAsc ? '▲' : '▼') : ''}
                  </th>
                  <th
                    onClick={() => {
                      if (sortField === 'channel') setSortAsc(!sortAsc);
                      else { setSortField('channel'); setSortAsc(true); }
                    }}
                    className="py-2.5 px-3 cursor-pointer hover:text-gray-900"
                  >
                    Channel {sortField === 'channel' ? (sortAsc ? '▲' : '▼') : ''}
                  </th>
                  <th
                    onClick={() => {
                      if (sortField === 'status') setSortAsc(!sortAsc);
                      else { setSortField('status'); setSortAsc(true); }
                    }}
                    className="py-2.5 px-3 cursor-pointer hover:text-gray-900"
                  >
                    Status {sortField === 'status' ? (sortAsc ? '▲' : '▼') : ''}
                  </th>
                  <th
                    onClick={() => {
                      if (sortField === 'assignee') setSortAsc(!sortAsc);
                      else { setSortField('assignee'); setSortAsc(true); }
                    }}
                    className="py-2.5 px-3 cursor-pointer hover:text-gray-900"
                  >
                    Assignee {sortField === 'assignee' ? (sortAsc ? '▲' : '▼') : ''}
                  </th>
                  <th
                    onClick={() => {
                      if (sortField === 'duedate') setSortAsc(!sortAsc);
                      else { setSortField('duedate'); setSortAsc(true); }
                    }}
                    className="py-2.5 px-3 cursor-pointer hover:text-gray-900"
                  >
                    SLA / Due Date {sortField === 'duedate' ? (sortAsc ? '▲' : '▼') : ''}
                  </th>
                  <th className="py-2.5 px-4 text-right">Quick Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {sortedItems.map((item) => {
                  const isSelected = selectedTicketKeys.includes(item.key);
                  const isOverdue = item.timeline_bucket === 'OVERDUE';
                  const isToday = item.timeline_bucket === 'TODAY';
                  const isTomorrow = item.timeline_bucket === 'TOMORROW';

                  return (
                    <tr
                      key={item.key}
                      className={`hover:bg-gray-50/60 transition-colors ${
                        isSelected ? 'bg-indigo-50/40' : ''
                      }`}
                    >
                      <td className="py-2.5 px-3 text-center">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelectTicket(item.key)}
                          className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 w-3.5 h-3.5 cursor-pointer"
                        />
                      </td>
                      <td className="py-2.5 px-3 font-bold">
                        <a
                          href={`https://tatacapital-team.atlassian.net/browse/${item.key}`}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-blue-600 hover:underline"
                        >
                          {item.key}
                        </a>
                      </td>
                      <td className="py-2.5 px-3 text-gray-900 font-medium max-w-md truncate" title={item.summary}>
                        {item.summary}
                      </td>
                      <td className="py-2.5 px-3">
                        <span
                          className={`text-[10px] font-bold px-2 py-0.5 rounded-full border ${
                            channelBadges[item.channel] || channelBadges.General
                          }`}
                        >
                          {item.channel}
                        </span>
                      </td>
                      <td className="py-2.5 px-3">
                        <span
                          className={`text-[10px] font-bold px-2 py-0.5 rounded-full ${
                            item.status_category === 'DONE'
                              ? 'bg-emerald-50 text-emerald-700 border border-emerald-200'
                              : item.status_category === 'BLOCKED'
                              ? 'bg-red-50 text-red-700 border border-red-200'
                              : 'bg-amber-50 text-amber-700 border border-amber-200'
                          }`}
                        >
                          {item.status}
                        </span>
                      </td>
                      <td className="py-2.5 px-3">
                        <div className="flex flex-col">
                          <div className="flex items-center gap-1.5">
                            <span className="w-5 h-5 rounded-full bg-gray-200 text-[10px] font-bold text-gray-700 flex items-center justify-center">
                              {item.assignee_name.charAt(0)}
                            </span>
                            <span className="font-medium text-gray-800">{item.assignee_name}</span>
                          </div>
                          {item.is_operational_assignment ? (
                            <span className="text-[9px] text-indigo-700 font-bold bg-indigo-50 px-1 rounded border border-indigo-100 mt-0.5 inline-flex items-center gap-0.5 max-w-fit" title={`Operationally assigned to ${item.assignee_name}. ${item.operational_note || ''}`}>
                              ⚡ Operational: {item.assignee_name}
                              {item.original_assignee && ` (was ${item.original_assignee})`}
                            </span>
                          ) : item.routed_to_soham ? (
                            <span className="text-[9px] text-purple-700 font-bold bg-purple-50 px-1 rounded border border-purple-100 mt-0.5 inline-flex items-center gap-0.5 max-w-fit" title={`Auto-assigned to Soham due to mention in ${item.soham_mention_reasons?.join(', ') || 'comment/attachment'}`}>
                              ⚡ Mention in {item.soham_mention_reasons?.join('/') || 'comment'}
                              {item.original_assignee && ` (was ${item.original_assignee})`}
                            </span>
                          ) : null}
                        </div>
                      </td>
                      <td className="py-2.5 px-3">
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
                      </td>
                      <td className="py-2.5 px-4 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <a
                            href={`/briefs?key=${item.key}&project=${selectedProject}`}
                            className="text-[10px] font-bold text-emerald-700 hover:text-emerald-900 bg-emerald-50 hover:bg-emerald-100 px-2 py-1 rounded-md transition-all flex items-center gap-1"
                            title="Extract brief and whitelist to Karix"
                          >
                            <span>⚡</span>
                            <span>Whitelist</span>
                          </a>
                          <button
                            onClick={() => {
                              if (!canTransferTickets) {
                                alert('Permission Denied: Only Dnyanesh Khawas, Neel Shah, and Mrunalini Gawande have the power to transfer tickets.');
                                return;
                              }
                              setTransferItem(item);
                              setTransferTargetId(data?.assignees[0]?.account_id || '');
                            }}
                            className={`text-[10px] font-bold px-2 py-1 rounded-md transition-all ${
                              canTransferTickets
                                ? 'text-indigo-600 hover:text-indigo-800 bg-indigo-50 hover:bg-indigo-100'
                                : 'text-gray-400 bg-gray-100 cursor-not-allowed'
                            }`}
                            title={canTransferTickets ? 'Reassign this single ticket' : 'Transfer power is restricted to Dnyanesh, Neel, and Mrunali'}
                          >
                            {canTransferTickets ? 'Transfer' : '🔒 Transfer'}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
      </div>
      )}
      {/* Ticket Transfer Modal */}
      {transferItem && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-6 border border-gray-200 space-y-4">
            <div className="flex items-center justify-between border-b border-gray-100 pb-3">
              <div>
                <h3 className="text-sm font-bold text-gray-900">Transfer Ticket {transferItem.key}</h3>
                <p className="text-xs text-gray-500">Direct assignee update in Jira Cloud &amp; Dashboard (Zero comments posted to Jira).</p>
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
                      {a.name} ({a.role}) {a.name === 'Soham Das' || a.name === 'Aadya' ? '⚡ Operational Queue' : ''} — {a.open_tickets_count} open tickets
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-gray-700 mb-1">Internal Note (Optional — saved only on dashboard, never posted to Jira)</label>
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

      {/* Bulk Reassign Modal */}
      {bulkModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-xl max-w-md w-full p-6 border border-gray-200 space-y-4">
            <div className="flex items-center justify-between border-b border-gray-100 pb-3">
              <div>
                <h3 className="text-sm font-bold text-gray-900 flex items-center gap-2">
                  <span>⚡</span> Bulk Reassign ({selectedTicketKeys.length} Tickets)
                </h3>
                <p className="text-xs text-gray-500">Direct bulk assignee update in Jira Cloud &amp; Dashboard (Zero comments posted to Jira).</p>
              </div>
              <button onClick={() => setBulkModalOpen(false)} className="text-gray-400 hover:text-gray-600">
                ✕
              </button>
            </div>

            <div className="p-3 bg-gray-50 rounded-xl border border-gray-200 max-h-32 overflow-y-auto">
              <span className="text-[10px] font-bold text-gray-500 uppercase tracking-wider block mb-1.5">
                Selected Tickets ({selectedTicketKeys.length}):
              </span>
              <div className="flex flex-wrap gap-1.5">
                {selectedTicketKeys.map((k) => (
                  <span key={k} className="px-2 py-0.5 rounded bg-white border border-gray-200 text-[11px] font-bold text-indigo-700">
                    {k}
                  </span>
                ))}
              </div>
            </div>

            <form onSubmit={handleExecuteBulkTransfer} className="space-y-4">
              <div>
                <label className="block text-xs font-bold text-gray-700 mb-1">Target Assignee</label>
                <select
                  value={bulkTargetId}
                  onChange={(e) => setBulkTargetId(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-xs font-medium bg-gray-50"
                  required
                >
                  {data?.assignees.map((a) => (
                    <option key={a.account_id} value={a.account_id}>
                      {a.name} ({a.role}) {a.name === 'Soham Das' || a.name === 'Aadya' ? '⚡ Operational Queue' : ''} — {a.open_tickets_count} open tickets
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block text-xs font-bold text-gray-700 mb-1">Internal Audit Note (Optional — saved only on dashboard, never posted to Jira)</label>
                <textarea
                  value={bulkHandoverNote}
                  onChange={(e) => setBulkHandoverNote(e.target.value)}
                  placeholder="e.g. 'Batch reallocating marketing campaign briefs to available intern queue.'"
                  rows={3}
                  className="w-full border border-gray-300 rounded-lg p-2.5 text-xs text-gray-800 placeholder-gray-400"
                />
              </div>

              <div className="pt-3 border-t border-gray-100 flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setBulkModalOpen(false)}
                  className="px-4 py-2 border border-gray-300 rounded-lg text-xs font-semibold text-gray-700 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={bulkTransferring}
                  className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-xs font-bold hover:bg-indigo-700 shadow-sm flex items-center gap-1.5"
                >
                  {bulkTransferring ? 'Reassigning in Jira...' : `Confirm Reassign (${selectedTicketKeys.length})`}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Daily SLA Alert Dispatcher Modal */}
      {showAlertModal && (
        <div className="fixed inset-0 z-50 bg-black/60 overflow-y-auto flex items-center justify-center p-3 sm:p-4 backdrop-blur-sm">
          <div className="bg-white rounded-2xl shadow-2xl max-w-4xl w-full border border-gray-200 flex flex-col max-h-[92vh] my-auto overflow-hidden">
            {/* Modal Header (Sticky Top) */}
            <div className="p-4 sm:p-5 border-b border-gray-100 flex items-start justify-between shrink-0 bg-white z-10">
              <div>
                <div className="flex items-center gap-2">
                  <span className="text-xl">✉️</span>
                  <h3 className="text-base font-bold text-gray-900">
                    Automated 3-Stage Daily SLA Dispatcher
                  </h3>
                  <span className="px-2 py-0.5 rounded text-[10px] font-extrabold bg-indigo-50 text-indigo-700 border border-indigo-200">
                    IST (UTC+5:30)
                  </span>
                </div>
                <p className="text-xs text-gray-500 mt-0.5">
                  10:00 AM Kickoff &rarr; 1:00 PM Checkpoint &rarr; 4:00 PM Urgent Attention Required.
                </p>
              </div>
              <button
                onClick={() => setShowAlertModal(false)}
                className="text-gray-400 hover:text-gray-600 font-bold text-base px-2 py-1"
              >
                ✕
              </button>
            </div>

            {/* Scrollable Modal Content */}
            <div className="p-4 sm:p-5 overflow-y-auto flex-1 space-y-4">

            {/* Scheduler Status Banner */}
            <div className="bg-gradient-to-r from-gray-900 to-indigo-950 text-white rounded-xl p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs shrink-0 shadow-sm">
              <div className="flex items-center gap-2.5">
                <span className={`w-2.5 h-2.5 rounded-full ${schedulerStatus?.enabled ? 'bg-emerald-400 animate-pulse' : 'bg-red-400'}`} />
                <div>
                  <span className="font-bold">
                    Automated Scheduler: {schedulerStatus?.enabled ? 'ACTIVE (10:00, 13:00, 16:00 IST)' : 'DISABLED'}
                  </span>
                  <span className="block text-[11px] text-gray-300">
                    Current Server IST Time: <span className="font-mono text-indigo-300 font-bold">{schedulerStatus?.ist_time || 'Calculating...'}</span>
                  </span>
                </div>
              </div>
              <button
                onClick={handleToggleScheduler}
                className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all self-start sm:self-auto border ${
                  schedulerStatus?.enabled
                    ? 'bg-white/10 hover:bg-white/20 text-white border-white/20'
                    : 'bg-emerald-600 hover:bg-emerald-500 text-white border-emerald-500'
                }`}
              >
                {schedulerStatus?.enabled ? 'Pause Automated Scheduler' : 'Enable Automated Scheduler'}
              </button>
            </div>

            {/* Sender Account Status Banner */}
            {alertsPreview?.sender_info && (
              <div className={`p-3 rounded-xl border text-xs flex flex-col sm:flex-row sm:items-center justify-between gap-2 shrink-0 ${
                alertsPreview.sender_info.is_configured
                  ? 'bg-emerald-50 text-emerald-900 border-emerald-200'
                  : 'bg-amber-50 text-amber-900 border-amber-200'
              }`}>
                <div className="flex items-center gap-2.5">
                  <span className="text-base">{alertsPreview.sender_info.is_configured ? '🟢' : '🟡'}</span>
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-bold">
                        From Account: <span className="font-mono">{alertsPreview.sender_info.from_email}</span>
                      </span>
                      <span className={`px-1.5 py-0.2 rounded text-[10px] font-extrabold uppercase ${
                        alertsPreview.sender_info.is_configured ? 'bg-emerald-200 text-emerald-800' : 'bg-amber-200 text-amber-800'
                      }`}>
                        {alertsPreview.sender_info.mode}
                      </span>
                    </div>
                    <span className="block text-[11px] opacity-85 mt-0.5">
                      {alertsPreview.sender_info.is_configured
                        ? `Live SMTP Server Connected: ${alertsPreview.sender_info.smtp_host}:${alertsPreview.sender_info.smtp_port}`
                        : 'Safe Simulation Mode: Emails are logged, not sent over wire. Add SMTP_HOST, SMTP_USER, SMTP_PASSWORD in Render to send live emails.'}
                    </span>
                  </div>
                </div>
              </div>
            )}

            {/* Stage Selector Tabs */}
            <div className="flex flex-wrap items-center gap-2 shrink-0 border-b border-gray-100 pb-3">
              <span className="text-[11px] font-bold uppercase tracking-wider text-gray-400 mr-1">Alert Stage:</span>
              {[
                { id: 'AUTO', label: '⚡ Auto-Detect (Current IST Time)' },
                { id: 'MORNING', label: '🌞 10:00 AM Kickoff (Daily Brief)' },
                { id: 'MIDDAY', label: '🥪 1:00 PM Checkpoint (Pending Check)' },
                { id: 'EOD', label: '🚨 4:00 PM Escalation (Attention Required)' },
              ].map((s) => (
                <button
                  key={s.id}
                  onClick={() => handleChangeAlertStage(s.id as 'AUTO' | 'MORNING' | 'MIDDAY' | 'EOD')}
                  className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all border ${
                    alertStage === s.id
                      ? 'bg-indigo-600 text-white border-indigo-600 shadow-sm'
                      : 'bg-gray-50 text-gray-700 border-gray-200 hover:bg-gray-100'
                  }`}
                >
                  {s.label}
                </button>
              ))}
            </div>

            {/* Multi-Channel Dispatch Selector */}
            <div className="bg-gray-50 border border-gray-200 rounded-xl p-3.5 space-y-2.5 shrink-0 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-extrabold text-gray-900 uppercase text-[10px] tracking-wider">
                  Select Notification Channels:
                </span>
                <span className="text-[11px] text-gray-500">
                  Multiple channels can be dispatched simultaneously
                </span>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                {/* Channel 1: Google Chat */}
                <label className={`p-2.5 rounded-lg border flex items-start gap-2.5 cursor-pointer transition-all ${
                  sendGoogleChat ? 'bg-white border-emerald-500 ring-2 ring-emerald-50 shadow-xs' : 'bg-gray-100/60 border-gray-200 opacity-60'
                }`}>
                  <input
                    type="checkbox"
                    checked={sendGoogleChat}
                    onChange={(e) => setSendGoogleChat(e.target.checked)}
                    className="mt-0.5 rounded text-emerald-600 focus:ring-emerald-500"
                  />
                  <div>
                    <span className="font-bold text-gray-900 block flex items-center gap-1">
                      <span>💬</span> Google Chat Space Broadcast
                    </span>
                    <span className="text-[11px] text-gray-500 leading-tight block mt-0.5">
                      Posts rich interactive card with ticket links into your team's Google Chat room.
                    </span>
                  </div>
                </label>

                {/* Channel 2: Direct Outbound Email */}
                <label className={`p-2.5 rounded-lg border flex items-start gap-2.5 cursor-pointer transition-all ${
                  sendDirectEmail ? 'bg-white border-blue-500 ring-2 ring-blue-50 shadow-xs' : 'bg-gray-100/60 border-gray-200 opacity-60'
                }`}>
                  <input
                    type="checkbox"
                    checked={sendDirectEmail}
                    onChange={(e) => setSendDirectEmail(e.target.checked)}
                    className="mt-0.5 rounded text-blue-600 focus:ring-blue-500"
                  />
                  <div>
                    <span className="font-bold text-gray-900 block flex items-center gap-1">
                      <span>✉️</span> Direct Outbound Email
                    </span>
                    <span className="text-[11px] text-gray-500 leading-tight block mt-0.5">
                      Sends via Brevo/SMTP directly to operators with automatic BCC to sender.
                    </span>
                  </div>
                </label>
              </div>

              <div className="flex items-center gap-1.5 text-[10px] text-gray-500 bg-gray-100/70 p-2 rounded-lg">
                <span>🔒</span>
                <span><strong>Jira is strictly read-only:</strong> The alert system will never write comments, update tickets, or modify anything in Jira Cloud.</span>
              </div>

              {sendGoogleChat && (
                <div className="pt-2 border-t border-gray-200/80 flex items-center gap-2">
                  <span className="text-[11px] font-bold text-gray-600 shrink-0">Google Chat Webhook:</span>
                  <input
                    type="text"
                    value={googleChatWebhookUrl}
                    onChange={(e) => setGoogleChatWebhookUrl(e.target.value)}
                    placeholder="Paste Google Chat Webhook URL (https://chat.googleapis.com/v1/spaces/...)..."
                    className="w-full border border-gray-300 rounded-lg px-2.5 py-1 text-xs text-gray-800 placeholder-gray-400 font-mono"
                  />
                </div>
              )}
            </div>

            {/* Modal Body: Two-column layout (Recipients List vs Live Email Preview) */}
            <div className="grid grid-cols-1 md:grid-cols-12 gap-3 h-64 sm:h-72 border border-gray-200 rounded-xl overflow-hidden bg-white">
              {/* Left Column: Operators List */}
              <div className="md:col-span-5 border border-gray-200 rounded-xl overflow-hidden flex flex-col bg-gray-50/50">
                <div className="p-3 bg-gray-100/70 border-b border-gray-200 text-xs font-bold text-gray-700 flex items-center justify-between">
                  <span>Target Operators ({alertsPreview?.recipient_count || 0})</span>
                  <span className="text-[10px] text-gray-500 font-normal">
                    {alertsPreview?.total_due_today_incomplete || 0} unfinished tickets
                  </span>
                </div>

                <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
                  {alertsLoading ? (
                    <div className="py-8 text-center text-xs text-gray-500 flex flex-col items-center gap-2">
                      <svg className="w-5 h-5 animate-spin text-indigo-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                        <circle cx="12" cy="12" r="10" strokeDasharray="32" strokeDashoffset="10" />
                      </svg>
                      <span>Evaluating tickets due today...</span>
                    </div>
                  ) : alertsPreview?.drafts.length === 0 ? (
                    <div className="py-8 text-center text-xs text-gray-500">
                      <span>🎉 All campaigns due today are completed!</span>
                    </div>
                  ) : (
                    alertsPreview?.drafts.map((d) => {
                      const isSelected = activePreviewEmail?.recipient_email === d.recipient_email;
                      return (
                        <button
                          key={d.recipient_email}
                          onClick={() => setActivePreviewEmail(d)}
                          className={`w-full text-left p-3 rounded-lg border text-xs transition-all ${
                            isSelected
                              ? 'bg-white border-indigo-500 shadow-sm ring-2 ring-indigo-50'
                              : 'bg-white border-gray-200 hover:border-gray-300'
                          }`}
                        >
                          <div className="flex items-center justify-between font-bold text-gray-900">
                            <span>{d.recipient_name}</span>
                            <span className="px-1.5 py-0.5 rounded text-[10px] bg-red-50 text-red-700 border border-red-200">
                              {d.pending_count} Pending
                            </span>
                          </div>
                          <div className="text-[11px] text-gray-500 mt-0.5 truncate">
                            {d.recipient_email}
                          </div>
                          <div className="text-[10px] text-indigo-600 font-mono mt-1 font-semibold truncate">
                            {d.ticket_keys.join(', ')}
                          </div>
                        </button>
                      );
                    })
                  )}
                </div>
              </div>

              {/* Right Column: Live Email Preview */}
              <div className="md:col-span-7 border border-gray-200 rounded-xl overflow-hidden flex flex-col bg-white">
                <div className="p-3 bg-gray-50 border-b border-gray-200 text-xs flex flex-col gap-1">
                  <div className="flex items-center gap-1.5 font-bold text-gray-900 truncate">
                    <span className="text-gray-400">Subject:</span>
                    <span className="truncate">{activePreviewEmail?.subject || 'Select an operator'}</span>
                  </div>
                  <div className="text-[11px] text-gray-500 flex items-center gap-1.5">
                    <span className="text-gray-400">To:</span>
                    <span className="font-mono text-indigo-700 font-semibold">{activePreviewEmail?.recipient_email || '—'}</span>
                  </div>
                </div>

                <div className="flex-1 overflow-y-auto p-4 bg-gray-50/30">
                  {activePreviewEmail ? (
                    <div
                      className="prose prose-xs max-w-none text-xs"
                      dangerouslySetInnerHTML={{ __html: activePreviewEmail.body_html }}
                    />
                  ) : (
                    <div className="py-16 text-center text-xs text-gray-400">
                      Select an operator on the left to preview their customized email.
                    </div>
                  )}
                </div>
              </div>
            </div>
          </div>

          {/* Modal Footer Actions (Sticky Bottom) */}
          <div className="p-4 border-t border-gray-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3 shrink-0 bg-gray-50 rounded-b-2xl z-10">
            <div className="text-xs text-gray-500">
              Stage: <strong className="text-gray-900">{alertsPreview?.stage}</strong> • Recipients: <strong className="text-gray-900">{alertsPreview?.recipient_count} operators</strong>
            </div>

            <div className="flex items-center gap-2 self-end sm:self-auto">
              <button
                type="button"
                onClick={() => setShowAlertModal(false)}
                className="px-4 py-2 border border-gray-300 rounded-lg text-xs font-semibold text-gray-700 hover:bg-gray-100"
              >
                Close
              </button>
              <button
                type="button"
                onClick={() => handleDispatchAlerts(true)}
                disabled={alertsDispatching || alertsPreview?.recipient_count === 0}
                className="px-4 py-2 bg-gray-200 hover:bg-gray-300 text-gray-800 rounded-lg text-xs font-bold border border-gray-300 transition-all"
              >
                {alertsDispatching ? 'Running...' : 'Send Dry-Run (Simulation)'}
              </button>
              <button
                type="button"
                onClick={() => handleDispatchAlerts(false)}
                disabled={alertsDispatching || alertsPreview?.recipient_count === 0}
                className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg text-xs font-bold shadow-md transition-all flex items-center gap-1.5 active:scale-95"
              >
                <span>⚡</span>
                <span>{alertsDispatching ? 'Dispatching...' : `Dispatch Live Alerts (${alertsPreview?.recipient_count || 0})`}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
      )}
    </div>
  );
}
