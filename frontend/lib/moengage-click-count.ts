import { fetchWithRetry, getApiUrl, getErrorMessage } from './api';

const PREFIX = '/api/moengage/click-count';

export interface ClickCountWorkspace {
  id: string;
  name: string;
  timezone: string;
}

export interface ClickCountBase {
  id: string;
  name: string;
  created_at?: string;
  start_date?: string;
}

export interface ClickCountBaseMetadata extends ClickCountBase {
  created_at: string;
  start_date: string;
  timezone: string;
}

export interface StartClickCountRequest {
  workspace_id: string;
  base_id: string;
  end_date: string;
}

export interface ClickCountQuery {
  query_id: string;
  workspace_id: string;
  workspace_name: string;
  base_id: string;
  base_name: string;
  start_date: string;
  end_date: string;
  timezone: string;
  status: 'queued';
}

export interface ClickCountQueryStatus {
  query_id: string;
  status: 'queued' | 'running' | 'success' | 'failed';
  user_count: number | null;
  reachable_users: number | null;
  error?: string;
}

export class ClickCountApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = 'ClickCountApiError';
  }
}

export function isTerminalClickCountError(error: unknown): boolean {
  return error instanceof ClickCountApiError && (
    error.status === 0 || error.status >= 400 && error.status < 500 && error.status !== 408 && error.status !== 429
  );
}

function isText(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function isBase(value: unknown): value is ClickCountBase {
  return typeof value === 'object' && value !== null && 'id' in value && 'name' in value
    && typeof value.id === 'string' && /^[a-fA-F0-9]{24}$/.test(value.id) && isText(value.name);
}

function isTimezone(value: unknown): value is string {
  if (!isText(value)) return false;
  try {
    new Intl.DateTimeFormat('en-US', { timeZone: value });
    return true;
  } catch {
    return false;
  }
}

function isCalendarDate(value: unknown): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value < '0001-01-01') return false;
  const instant = new Date(`${value}T00:00:00.000Z`);
  return Number.isFinite(instant.getTime()) && instant.toISOString().slice(0, 10) === value;
}

export function todayInTimezone(timezone: string, now = new Date()): string {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
  return ['year', 'month', 'day'].map((type) => parts.find((part) => part.type === type)?.value.padStart(type === 'year' ? 4 : 2, '0')).join('-');
}

export function isValidClickCountRange(startDate: string, endDate: string, timezone: string, now = new Date()): boolean {
  return isCalendarDate(startDate) && isCalendarDate(endDate) && endDate >= startDate && endDate <= todayInTimezone(timezone, now);
}

function assertResponse(condition: unknown): asserts condition {
  if (!condition) throw new ClickCountApiError('The click-count service returned an invalid response. Reload the data before continuing.', 0);
}

async function readResponse<T>(res: Response): Promise<T> {
  if (!res.ok) throw new ClickCountApiError(await getErrorMessage(res), res.status);
  try {
    return await res.json() as T;
  } catch (error) {
    if (typeof error === 'object' && error !== null && 'name' in error && error.name === 'SyntaxError') {
      throw new ClickCountApiError('The click-count service returned unreadable data. Reload the data before continuing.', 0);
    }
    throw error;
  }
}

export async function fetchClickCountWorkspaces(signal?: AbortSignal): Promise<{ workspaces: ClickCountWorkspace[] }> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/workspaces`), { signal, cache: 'no-store' });
  const data = await readResponse<{ workspaces: ClickCountWorkspace[] }>(res);
  assertResponse(typeof data === 'object' && data !== null && Array.isArray(data.workspaces) && data.workspaces.every(
    (item) => isBase(item) && 'timezone' in item && isTimezone(item.timezone),
  ));
  assertResponse(new Set(data.workspaces.map((item) => item.id)).size === data.workspaces.length);
  return data;
}

export async function fetchClickCountBases(workspaceId: string, signal?: AbortSignal): Promise<{ bases: ClickCountBase[] }> {
  const qs = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/bases?${qs}`), { signal, cache: 'no-store' });
  const data = await readResponse<{ bases: ClickCountBase[] }>(res);
  assertResponse(typeof data === 'object' && data !== null && Array.isArray(data.bases) && data.bases.every(isBase));
  assertResponse(new Set(data.bases.map((item) => item.id)).size === data.bases.length);
  return data;
}

export async function fetchClickCountBase(workspaceId: string, baseId: string, signal?: AbortSignal): Promise<ClickCountBaseMetadata> {
  const qs = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/bases/${encodeURIComponent(baseId)}?${qs}`), { signal, cache: 'no-store' });
  const data = await readResponse<ClickCountBaseMetadata>(res);
  assertResponse(isBase(data) && data.id === baseId && isCalendarDate(data.start_date) && isTimezone(data.timezone)
    && typeof data.created_at === 'string' && isCalendarDate(data.created_at.slice(0, 10))
    && /^\d{4}-\d{2}-\d{2}T.+(?:Z|\+00:00)$/.test(data.created_at) && Number.isFinite(Date.parse(data.created_at)));
  assertResponse(data.start_date === todayInTimezone(data.timezone, new Date(data.created_at)));
  return data;
}

export async function startClickCountQuery(payload: StartClickCountRequest, signal?: AbortSignal): Promise<ClickCountQuery> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/queries`), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal,
  }, 0);
  const data = await readResponse<ClickCountQuery>(res);
  assertResponse(typeof data === 'object' && data !== null && isText(data.query_id) && data.query_id.length <= 4096 && data.status === 'queued'
    && data.workspace_id === payload.workspace_id && data.base_id === payload.base_id && data.end_date === payload.end_date
    && isText(data.workspace_name) && isText(data.base_name) && isTimezone(data.timezone)
    && isCalendarDate(data.start_date) && isCalendarDate(data.end_date) && data.start_date <= data.end_date);
  return data;
}

export async function fetchClickCountQuery(workspaceId: string, queryId: string, signal?: AbortSignal): Promise<ClickCountQueryStatus> {
  const qs = new URLSearchParams({ workspace_id: workspaceId });
  // The serialized polling loop handles transient failures; do not multiply each poll with retries.
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/queries/${encodeURIComponent(queryId)}?${qs}`), { signal, cache: 'no-store' }, 0);
  const data = await readResponse<ClickCountQueryStatus>(res);
  assertResponse(typeof data === 'object' && data !== null && data.query_id === queryId
    && typeof data.status === 'string' && ['queued', 'running', 'success', 'failed'].includes(data.status)
    && (data.error === undefined || typeof data.error === 'string'));
  if (data.status === 'success') {
    assertResponse(typeof data.user_count === 'number' && Number.isSafeInteger(data.user_count) && data.user_count >= 0
      && typeof data.reachable_users === 'number' && Number.isSafeInteger(data.reachable_users)
      && data.reachable_users >= 0 && data.reachable_users <= data.user_count);
  } else {
    assertResponse(data.user_count === null && data.reachable_users === null);
  }
  return data;
}
