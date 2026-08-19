export type Account = string;
export type Channel = "whatsapp" | "rcs";

export type AccountItem = {
  id: string;
  name: string;
  is_builtin?: boolean;
};
export type Template = {
  source_ref: string;
  template_name: string;
  status: "submitted" | "failed" | "duplicate";
  provider_ref_id?: string | null;
  approval_status?: "pending" | "approved" | "rejected" | "unknown";
  approval_reason?: string | null;
  error?: string | null;
  retry_count: number;
  submitted_at: string;
  submitted_by?: string | null;
  source_file?: string | null;
  live?: boolean;
  updated_at?: string | null;
  provider_response?: Record<string, unknown> | null;
  client?: string;
  channel?: string;
  template_id?: string;
  template_type?: string;
  sender_ids?: string[];
  template_message_type?: string;
  template_message?: string;
  entity_id?: string;
};

export type Stats = {
  total: number;
  submitted: number;
  failed: number;
  pending: number;
  approved: number;
  rejected: number;
  duplicate: number;
  error?: string | null;
};
export type TemplatePreview = {
  template_name: string;
  category?: string;
  language?: string;
  client?: string;
  channel?: string;
  waba_id?: string;
  source_ref?: string;
  components?: Array<{
    type: string;
    text?: string;
    format?: string;
    [key: string]: unknown;
  }>;
  // RCS preview fields
  template_id?: string;
  template_type?: string;
  text_message?: string;
  card_title?: string;
  card_description?: string;
  media_url?: string;
  suggestions?: Array<Record<string, unknown>>;
  carousel_cards?: Array<Record<string, unknown>>;
  sender_ids?: string[];
  template_message_type?: string;
  template_message?: string;
  entity_id?: string;
};

export type ActivityLog = {
  id: string;
  timestamp: string;
  user: string;
  action: string;
  account: Account;
  channel: Channel;
  status: string;
  details: {
    filename?: string;
    count?: number;
    templates?: string[];
    successful?: number;
    failed?: number;
    checked_count?: number;
    keys_updated?: string[];
    message?: string;
    valid?: boolean;
    [key: string]: unknown;
  };
  ip_address?: string;
};

export type ActivityStats = {
  total_actions: number;
  total_users: number;
  total_templates_submitted: number;
  top_user: string;
  user_activity: Array<{ user: string; actions: number; templates: number }>;
  action_breakdown: Record<string, number>;
  recent_activities: ActivityLog[];
};
function getApiUrl(path: string): string {
  if (typeof window !== "undefined") {
    // In browser: relative URL (proxied by Next.js rewrites to backend)
    return path;
  }
  const base = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
  return `${base}${path}`;
}

async function getErrorMessage(res: Response): Promise<string> {
  // Read the body ONCE — calling res.json() then res.text() on a failed
  // parse consumes the stream and loses the real server error.
  const text = await res.text().catch(() => "");
  if (!text) return `Request failed (${res.status})`;
  try {
    const data = JSON.parse(text);
    if (typeof data === "string") return data;
    if (data?.detail) {
      if (typeof data.detail === "string") return data.detail;
      if (Array.isArray(data.detail)) {
        return data.detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join(", ");
      }
      return JSON.stringify(data.detail);
    }
    if (data?.message) return String(data.message);
    return JSON.stringify(data);
  } catch {
    if (text.startsWith('<!DOCTYPE') || text.startsWith('<html') || (text.includes('<title>') && text.includes('</title>'))) {
      const titleMatch = text.match(/<title>([^<]+)<\/title>/i);
      const code = titleMatch ? titleMatch[1].trim() : String(res.status);
      return `Server is restarting or temporarily unavailable (${code}). Please try again in a few moments.`;
    }
    return text;
  }
}


export async function fetchStats(
  account: Account = "bajaj",
  channel: Channel = "whatsapp"
): Promise<Stats> {
  const qs = new URLSearchParams({ account, channel }).toString();
  const res = await fetch(getApiUrl(`/api/stats?${qs}`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchTemplates(params?: {
  account?: Account;
  channel?: Channel;
  status?: string;
  search?: string;
}): Promise<Template[]> {
  const qs = new URLSearchParams();
  qs.set("account", params?.account || "bajaj");
  qs.set("channel", params?.channel || "whatsapp");
  if (params?.status) qs.set("status", params.status);
  if (params?.search) qs.set("search", params.search);

  const res = await fetch(getApiUrl(`/api/templates?${qs.toString()}`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function previewFile(
  file: File,
  account: Account = "bajaj",
  channel: Channel = "whatsapp"
): Promise<TemplatePreview[]> {
  const form = new FormData();
  form.append("file", file);
  const qs = new URLSearchParams({ account, channel }).toString();
  const res = await fetch(getApiUrl(`/api/preview?${qs}`), {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function submitFile(
  file: File,
  account: Account = "bajaj",
  channel: Channel = "whatsapp",
  user: string = "Namann"
): Promise<{ submitted: number; results: Template[] }> {
  const form = new FormData();
  form.append("file", file);
  const qs = new URLSearchParams({ account, channel, user }).toString();
  const res = await fetch(getApiUrl(`/api/submit?${qs}`), {
    method: "POST",
    headers: { "X-User": user },
    body: form,
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function pollPending(
  account: Account = "bajaj",
  channel: Channel = "whatsapp",
  user: string = "Namann"
): Promise<{ checked: number }> {
  const qs = new URLSearchParams({ account, channel, user }).toString();
  const res = await fetch(getApiUrl(`/api/poll?${qs}`), {
    method: "POST",
    headers: { "X-User": user },
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function updateCredentials(creds: {
  account: Account;
  channel: Channel;
  waba_auth_token?: string;
  waba_id?: string;
  bearer_token?: string;
  session?: string;
  user?: string;
  user_name?: string;
  entity_id?: string;
  lounge_cookie?: string;
}): Promise<{ ok: boolean }> {
  const res = await fetch(getApiUrl(`/api/credentials`), {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      "X-User": creds.user_name || "Namann",
    },
    body: JSON.stringify(creds),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function testCredentials(
  account: Account = "bajaj",
  channel: Channel = "whatsapp",
  creds?: {
    waba_auth_token?: string;
    waba_id?: string;
    bearer_token?: string;
    session?: string;
    user?: string;
    user_name?: string;
    entity_id?: string;
    lounge_cookie?: string;
  }
): Promise<{
  ok: boolean;
  message: string;
}> {
  const qs = new URLSearchParams({ account, channel, user: creds?.user_name || "Namann" }).toString();
  const res = await fetch(getApiUrl(`/api/test-credentials?${qs}`), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-User": creds?.user_name || "Namann",
    },
    body: JSON.stringify({ account, channel, ...creds }),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchActivityLogs(params?: {
  user?: string;
  action?: string;
  account?: Account | "all";
  channel?: Channel | "all";
  search?: string;
  limit?: number;
}): Promise<ActivityLog[]> {
  const qs = new URLSearchParams();
  if (params?.user) qs.set("user", params.user);
  if (params?.action) qs.set("action", params.action);
  if (params?.account) qs.set("account", params.account);
  if (params?.channel) qs.set("channel", params.channel);
  if (params?.search) qs.set("search", params.search);
  if (params?.limit) qs.set("limit", String(params.limit));

  const res = await fetch(getApiUrl(`/api/activity?${qs.toString()}`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchActivityStats(): Promise<ActivityStats> {
  const res = await fetch(getApiUrl(`/api/activity/stats`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export function getSampleCsvUrl(channel: Channel = "whatsapp"): string {
  return getApiUrl(`/api/sample-csv?channel=${channel}`);
}

export async function fetchAccounts(): Promise<AccountItem[]> {
  const res = await fetch(getApiUrl("/api/accounts"));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function createAccount(name: string, id?: string, user?: string): Promise<AccountItem> {
  const qs = user ? `?user=${encodeURIComponent(user)}` : '';
  const res = await fetch(getApiUrl(`/api/accounts${qs}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, id }),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function deleteAccount(id: string, user?: string): Promise<{ ok: boolean }> {
  const qs = user ? `?user=${encodeURIComponent(user)}` : '';
  const res = await fetch(getApiUrl(`/api/accounts/${encodeURIComponent(id)}${qs}`), {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}
