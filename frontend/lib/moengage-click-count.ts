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

function calendarDateFormatter(timezone: string): Intl.DateTimeFormat {
  return new Intl.DateTimeFormat('en-US', { timeZone: timezone, year: 'numeric', month: '2-digit', day: '2-digit', era: 'short' });
}

function calendarDateInTimezone(formatter: Intl.DateTimeFormat, instant: Date): string {
  const parts = formatter.formatToParts(instant);
  // An offset near year 0001 can cross into BC, outside the service's calendar.
  if (parts.find((part) => part.type === 'era')?.value !== 'AD') return '';
  return ['year', 'month', 'day'].map((type) => parts.find((part) => part.type === type)?.value.padStart(type === 'year' ? 4 : 2, '0')).join('-');
}

export function todayInTimezone(timezone: string, now = new Date()): string {
  return calendarDateInTimezone(calendarDateFormatter(timezone), now);
}

export function isValidClickCountRange(startDate: string, endDate: string, timezone: string, now = new Date()): boolean {
  if (!isCalendarDate(startDate) || !isCalendarDate(endDate) || endDate < startDate || !isText(timezone)) return false;
  try {
    const today = todayInTimezone(timezone, now);
    return isCalendarDate(today) && endDate <= today;
  } catch {
    return false;
  }
}

function hasValidBaseDates(value: { created_at?: unknown; start_date?: unknown }, formatter: Intl.DateTimeFormat): value is { created_at: string; start_date: string } {
  if (typeof value.created_at !== 'string' || !isCalendarDate(value.created_at.slice(0, 10)) || !isCalendarDate(value.start_date)
    || !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value.created_at)) return false;
  const instant = new Date(value.created_at);
  return Number.isFinite(instant.getTime()) && value.start_date === calendarDateInTimezone(formatter, instant);
}

function assertResponse(condition: unknown): asserts condition {
  if (!condition) throw new ClickCountApiError('The click-count service returned an invalid response. Reload the data before continuing.', 0);
}

async function readResponse<T>(res: Response, signal?: AbortSignal): Promise<T> {
  signal?.throwIfAborted();
  if (!res.ok) {
    const message = await getErrorMessage(res);
    // The shared error-body reader suppresses read errors; cancellation must still win.
    signal?.throwIfAborted();
    throw new ClickCountApiError(message, res.status);
  }
  try {
    const data = await res.json() as T;
    signal?.throwIfAborted();
    return data;
  } catch (error) {
    signal?.throwIfAborted();
    if (typeof error === 'object' && error !== null && 'name' in error && error.name === 'SyntaxError') {
      throw new ClickCountApiError('The click-count service returned unreadable data. Reload the data before continuing.', 0);
    }
    throw error;
  }
}

export async function fetchClickCountWorkspaces(signal?: AbortSignal): Promise<{ workspaces: ClickCountWorkspace[] }> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/workspaces`), { signal, cache: 'no-store' });
  const data = await readResponse<{ workspaces: ClickCountWorkspace[] }>(res, signal);
  assertResponse(typeof data === 'object' && data !== null && Array.isArray(data.workspaces) && data.workspaces.every(
    (item) => isBase(item) && 'timezone' in item && isTimezone(item.timezone),
  ));
  assertResponse(new Set(data.workspaces.map((item) => item.id)).size === data.workspaces.length);
  return data;
}

export async function fetchClickCountBases(workspaceId: string, signal?: AbortSignal, timezone?: string): Promise<{ bases: ClickCountBase[] }> {
  const qs = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/bases?${qs}`), { signal, cache: 'no-store' });
  const data = await readResponse<{ bases: ClickCountBase[] }>(res, signal);
  assertResponse(typeof data === 'object' && data !== null && Array.isArray(data.bases) && data.bases.every(isBase));
  assertResponse(new Set(data.bases.map((item) => item.id)).size === data.bases.length);
  const formatter = isTimezone(timezone) ? calendarDateFormatter(timezone) : null;
  // Optional list metadata is only an optimization. Invalid pairs require the metadata endpoint.
  return { bases: data.bases.map((base) => formatter && hasValidBaseDates(base, formatter)
    ? { id: base.id, name: base.name, created_at: base.created_at, start_date: base.start_date }
    : { id: base.id, name: base.name }) };
}

export async function fetchClickCountBase(workspaceId: string, baseId: string, signal?: AbortSignal): Promise<ClickCountBaseMetadata> {
  const qs = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/bases/${encodeURIComponent(baseId)}?${qs}`), { signal, cache: 'no-store' });
  const data = await readResponse<ClickCountBaseMetadata>(res, signal);
  assertResponse(isBase(data) && data.id === baseId && isTimezone(data.timezone));
  assertResponse(hasValidBaseDates(data, calendarDateFormatter(data.timezone)));
  return data;
}

export async function startClickCountQuery(payload: StartClickCountRequest, signal?: AbortSignal): Promise<ClickCountQuery> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/queries`), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal,
  }, 0);
  const data = await readResponse<ClickCountQuery>(res, signal);
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
  const data = await readResponse<ClickCountQueryStatus>(res, signal);
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
