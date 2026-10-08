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

export async function fetchClickCountWorkspaces(signal?: AbortSignal): Promise<{ workspaces: ClickCountWorkspace[] }> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/workspaces`), { signal, cache: 'no-store' });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchClickCountBases(workspaceId: string, signal?: AbortSignal): Promise<{ bases: ClickCountBase[] }> {
  const qs = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/bases?${qs}`), { signal, cache: 'no-store' });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchClickCountBase(workspaceId: string, baseId: string, signal?: AbortSignal): Promise<ClickCountBaseMetadata> {
  const qs = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/bases/${encodeURIComponent(baseId)}?${qs}`), { signal, cache: 'no-store' });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function startClickCountQuery(payload: StartClickCountRequest, signal?: AbortSignal): Promise<ClickCountQuery> {
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/queries`), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal,
  }, 0);
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchClickCountQuery(workspaceId: string, queryId: string, signal?: AbortSignal): Promise<ClickCountQueryStatus> {
  const qs = new URLSearchParams({ workspace_id: workspaceId });
  const res = await fetchWithRetry(getApiUrl(`${PREFIX}/queries/${encodeURIComponent(queryId)}?${qs}`), { signal, cache: 'no-store' });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}
