import { fetchWithRetry, getApiUrl, getErrorMessage } from './api';
import type { AuthUser } from './api';

const PREFIX = '/api/apparel/attribution';

export type AttributionChannel = 'WhatsApp' | 'SMS' | 'RCS';
export const ATTRIBUTION_CHANNELS: AttributionChannel[] = ['WhatsApp', 'SMS', 'RCS'];

export function canUseApparelAttribution(user: AuthUser | null, account: string): boolean {
  return account === 'apparel' && Boolean(user && (
    user.role === 'superadmin' ||
    (user.tenant_id === 'apparel' && (user.role === 'operator' || user.role === 'admin'))
  ));
}

export function canManageApparelAttribution(user: AuthUser | null): boolean {
  return Boolean(user && (user.role === 'superadmin' || (user.tenant_id === 'apparel' && user.role === 'admin')));
}

export type AttributionHealth = {
  status: string;
  moengage_mode: string;
  configured_brands: string[];
  google_configured: boolean;
  moengage_connected: boolean;
  mock_writes_enabled: boolean;
  worker_configured?: boolean;
};

export type GoogleConfiguration = {
  configured: boolean;
  service_account_email: string | null;
  spreadsheet_url: string;
  worksheet_name: string;
};

export type CampaignPreviewRow = {
  excel_row: number;
  brand: string;
  channel: string;
  campaign_type: string;
  campaign_id: string;
  campaign_name: string;
  sent_date: string;
  date_range: string;
};

export type CampaignPreview = {
  row_count: number;
  preview: CampaignPreviewRow[];
  warnings: string[];
  warning_sent_date_from: string;
  warning_sent_date_to: string;
};

export type SheetConnection = CampaignPreview & {
  connection_id: string;
  spreadsheet_title: string;
  worksheet_title: string;
  brands: string[];
  channels: string[];
  campaign_types: string[];
  sent_dates: string[];
};

export type MoEngageSession = {
  status: 'connected' | 'waiting_for_login' | 'disconnected' | 'not_configured';
  message: string;
  profile_id: string;
  profiles: string[];
  login_url?: string | null;
};

export type AttributionSetup = {
  spreadsheet_url: string;
  worksheet_name: string;
  ui_config: Record<string, unknown>;
  google_configured: boolean;
  service_account_email: string | null;
  browser_login_url?: string | null;
};

export type AttributionSetupRequest = Pick<AttributionSetup, 'spreadsheet_url' | 'worksheet_name' | 'ui_config'>;

export type AttributionSelection = {
  brands: string[];
  channels: AttributionChannel[];
  sent_date_from: string;
  sent_date_to: string;
  row_limit?: number;
  agipl_attribution_brand?: string;
};

export type StartAttributionJobRequest = AttributionSelection & {
  sheet_connection_id: string;
  overwrite_existing: boolean;
};

export type StartAttributionJobResponse = { job_id: string; status: string };

export type AttributionRowResult = {
  excel_row: number;
  brand: string;
  channel: string;
  campaign_type: string;
  campaign_id: string;
  campaign_name: string;
  date_range: string;
  status: string;
  unique_users: number | null;
  total_revenue: number | null;
  online_unique_users: number | null;
  offline_unique_users: number | null;
  online_revenue: number | null;
  offline_revenue: number | null;
  message: string | null;
};

export type AttributionJob = {
  job_id: string;
  filename: string;
  status: string;
  progress: number;
  total_rows: number;
  processed_rows: number;
  successful_rows: number;
  failed_rows: number;
  skipped_rows: number;
  current_row: number | null;
  current_brand: string | null;
  error: string | null;
  download_ready: boolean;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  results: AttributionRowResult[];
};

export function isAttributionJobActive(status: string): boolean {
  return status === 'queued' || status === 'processing' || status === 'cancelling';
}

export class AttributionApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = 'AttributionApiError';
  }
}

export async function fetchAttributionHealth(signal?: AbortSignal): Promise<AttributionHealth> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/health`), { signal, cache: 'no-store' });
  if (!res.ok) throw new AttributionApiError(await getErrorMessage(res), res.status);
  return res.json();
}

export async function fetchAttributionGoogleConfig(signal?: AbortSignal): Promise<GoogleConfiguration> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/google/config`), { signal, cache: 'no-store' });
  if (!res.ok) throw new AttributionApiError(await getErrorMessage(res), res.status);
  return res.json();
}

export async function connectAttributionSheet(payload: Pick<GoogleConfiguration, 'spreadsheet_url' | 'worksheet_name'>): Promise<SheetConnection> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/google/connect`), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }, 0);
  if (!res.ok) throw new AttributionApiError(await getErrorMessage(res), res.status);
  return res.json();
}

export async function fetchAttributionPreview(connectionId: string, selection: AttributionSelection, signal?: AbortSignal): Promise<CampaignPreview> {
  const qs = new URLSearchParams({
    sent_date_from: selection.sent_date_from, sent_date_to: selection.sent_date_to,
    limit: String(Math.min(selection.row_limit ?? 100, 100)),
  });
  selection.brands.forEach((brand) => qs.append('brands', brand));
  selection.channels.forEach((channel) => qs.append('channels', channel));
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/google/connections/${encodeURIComponent(connectionId)}/campaigns?${qs}`), { signal, cache: 'no-store' });
  if (!res.ok) throw new AttributionApiError(await getErrorMessage(res), res.status);
  return res.json();
}

export async function fetchAttributionSession(signal?: AbortSignal): Promise<MoEngageSession> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/moengage/session`), { signal, cache: 'no-store' });
  if (!res.ok) throw new AttributionApiError(await getErrorMessage(res), res.status);
  return res.json();
}

export async function startAttributionSession(profileId: string): Promise<MoEngageSession> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/moengage/session/start`), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ profile_id: profileId }),
  }, 0);
  if (!res.ok) throw new AttributionApiError(await getErrorMessage(res), res.status);
  return res.json();
}

export async function resetAttributionSession(profileId: string): Promise<MoEngageSession> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/moengage/session/reset`), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ profile_id: profileId }),
  }, 0);
  if (!res.ok) throw new AttributionApiError(await getErrorMessage(res), res.status);
  return res.json();
}

export async function fetchAttributionJobs(signal?: AbortSignal): Promise<{ jobs: AttributionJob[] }> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/jobs`), { signal, cache: 'no-store' });
  if (!res.ok) throw new AttributionApiError(await getErrorMessage(res), res.status);
  return res.json();
}

export async function fetchAttributionJob(jobId: string, signal?: AbortSignal): Promise<AttributionJob> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/jobs/${encodeURIComponent(jobId)}`), { signal, cache: 'no-store' });
  if (!res.ok) throw new AttributionApiError(await getErrorMessage(res), res.status);
  return res.json();
}

export async function startAttributionJob(payload: StartAttributionJobRequest): Promise<StartAttributionJobResponse> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/jobs`), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }, 0);
  if (!res.ok) throw new AttributionApiError(await getErrorMessage(res), res.status);
  return res.json();
}

export async function cancelAttributionJob(jobId: string): Promise<AttributionJob> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/jobs/${encodeURIComponent(jobId)}/cancel`), { method: 'POST' }, 0);
  if (!res.ok) throw new AttributionApiError(await getErrorMessage(res), res.status);
  return res.json();
}

export async function retryFailedAttributionJob(jobId: string): Promise<StartAttributionJobResponse> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/jobs/${encodeURIComponent(jobId)}/retry-failed`), { method: 'POST' }, 0);
  if (!res.ok) throw new AttributionApiError(await getErrorMessage(res), res.status);
  return res.json();
}

export async function downloadAttributionCsv(jobId: string): Promise<void> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/jobs/${encodeURIComponent(jobId)}/results.csv`), { cache: 'no-store' });
  if (!res.ok) throw new AttributionApiError(await getErrorMessage(res), res.status);
  const blob = await res.blob();
  const disposition = res.headers.get('Content-Disposition') || '';
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1]?.split(/[\\/]/).pop() || `attribution-results-${jobId.slice(0, 8)}.csv`;
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function fetchAttributionSetup(signal?: AbortSignal): Promise<AttributionSetup> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/setup`), { signal, cache: 'no-store' });
  if (!res.ok) throw new AttributionApiError(await getErrorMessage(res), res.status);
  return res.json();
}

export async function saveAttributionSetup(payload: AttributionSetupRequest): Promise<AttributionSetup> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/setup`), {
    method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  }, 0);
  if (!res.ok) throw new AttributionApiError(await getErrorMessage(res), res.status);
  return res.json();
}

export async function uploadAttributionGoogleKey(credential: File): Promise<GoogleConfiguration> {
  const form = new FormData();
  form.append('credential', credential);
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/google/credentials`), { method: 'POST', body: form }, 0);
  if (!res.ok) throw new AttributionApiError(await getErrorMessage(res), res.status);
  return res.json();
}
