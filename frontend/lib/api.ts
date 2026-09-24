export type Account = string;
export type Channel = "whatsapp" | "rcs" | "sms";

export type AccountItem = {
  id: string;
  name: string;
  is_builtin?: boolean;
};

export type AuthUser = {
  id: string;
  email: string;
  name: string;
  tenant_id: string;
  role: string;
  created_at?: string;
  last_login?: string;
};

export type AuthResponse = {
  user: AuthUser;
  token: string;
};

export type UserItem = {
  id: string;
  name: string;
  email?: string;
  tenant_id?: string;
  role?: string;
  created_at?: string;
  last_active?: string;
  actions_count?: number;
};
export type Template = {
  source_ref: string;
  template_name: string;
  status: "submitted" | "failed" | "duplicate" | "blocked_aspect_ratio" | "blocked";
  provider_ref_id?: string | null;
  approval_status?: "pending" | "approved" | "rejected" | "unknown" | "blocked" | "blocked_aspect_ratio";
  approval_reason?: string | null;
  error?: string | null;
  retry_count: number;
  submitted_at: string;
  submitted_by?: string | null;
  source_file?: string | null;
  live?: boolean;
  exists_on_waba?: boolean;
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

export type KarixHealth = {
  status: 'optimal' | 'moderate' | 'degraded' | 'throttled';
  avg_latency_sec: number;
  error_rate: number;
  optimal_workers: number;
  pacing_delay_sec: number;
  sample_count: number;
};
export type SlaInsight = {
  template_name?: string;
  category_tier?: string;
  category_label?: string;
  age_sec?: number;
  estimated_remaining_sec?: number;
  is_due_for_poll?: boolean;
};

export type SlaInsights = {
  pending_count: number;
  due_for_poll_count: number;
  categories: Record<string, number>;
  next_recommended_poll_sec: number;
  templates_status?: SlaInsight[];
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
  karix_health?: KarixHealth;
  sla_insights?: SlaInsights;
};
export type AspectRatioWarning = {
  component: string;
  original_size: string;
  current_ratio: string;
  recommended_ratio: string;
  action: string;
  error?: string;
  blocked?: boolean;
};

export type GrammarWarning = {
  type: string;
  issue: string;
  suggestion: string;
  original: string;
  replacement: string;
};
export type ComplianceWarning = {
  type: string;
  severity: 'error' | 'warning';
  issue: string;
  recommendation: string;
};
export type AccountDetection = {
  detected_account_id: string;
  detected_account_name: string;
  confidence: number;
  matched_reasons: string[];
  is_mismatch: boolean;
  current_account: string;
};

export type TemplatePreview = {
  template_name: string;
  category?: string;
  language?: string;
  client?: string;
  channel?: string;
  waba_id?: string;
  source_ref?: string;
  aspect_ratio_warnings?: AspectRatioWarning[];
  aspect_ratio_blocked?: boolean;
  aspect_ratio_block_reason?: string;
  grammar_warnings?: GrammarWarning[];
  compliance_warnings?: ComplianceWarning[];
  already_exists_on_waba?: boolean;
  exists_on_waba?: boolean;
  duplicate_warning?: {
    template_name: string;
    message: string;
  };
  account_detection?: AccountDetection;
  components?: Array<{
    type: string;
    text?: string;
    format?: string;
    suggested_text?: string;
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

function delay(ms: number): Promise<void> {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, ms);
  return promise;
}

export function getAuthToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("karix_jwt_token");
}

export function setAuthToken(token: string): void {
  if (typeof window !== "undefined") {
    localStorage.setItem("karix_jwt_token", token);
  }
}

export function clearAuthToken(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem("karix_jwt_token");
    localStorage.removeItem("karix_user_profile");
  }
}

async function fetchWithRetry(
  input: RequestInfo | URL,
  init?: RequestInit,
  retries = 2,
  delayMs = 800,
  timeoutMs = 60000
): Promise<Response> {
  let lastError: unknown;
  for (let i = 0; i <= retries; i++) {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => {
      controller.abort(new Error(`Request timed out after ${Math.round(timeoutMs / 1000)} seconds. The server may still be processing your batch.`));
    }, timeoutMs);

    try {
      const headers = new Headers(init?.headers || {});
      const token = getAuthToken();
      if (token && !headers.has("Authorization")) {
        headers.set("Authorization", `Bearer ${token}`);
      }

      const customInit: RequestInit = {
        ...init,
        headers,
        signal: init?.signal || controller.signal,
      };

      const res = await fetch(input, customInit);
      clearTimeout(timeoutId);
      // If server returned 500/502/503/504 (cold start, proxy blip, or temporary container swap), retry
      if ((res.status === 500 || res.status === 502 || res.status === 503 || res.status === 504) && i < retries) {
        await delay(delayMs * Math.pow(1.5, i));
        continue;
      }
      return res;
    } catch (err) {
      clearTimeout(timeoutId);
      if (controller.signal.aborted) {
        lastError =
          controller.signal.reason instanceof Error
            ? controller.signal.reason
            : new Error(`Request timed out after ${Math.round(timeoutMs / 1000)} seconds. The server may still be processing your batch.`);
      } else {
        lastError = err;
      }
      if (i < retries) {
        await delay(delayMs * Math.pow(1.5, i));
        continue;
      }
    }
  }
  throw lastError instanceof Error ? lastError : new Error(String(lastError || "Network request timed out or failed"));
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
  const res = await fetchWithRetry(getApiUrl(`/api/stats?${qs}`));
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

  const res = await fetchWithRetry(getApiUrl(`/api/templates?${qs.toString()}`));
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
  const res = await fetchWithRetry(
    getApiUrl(`/api/preview?${qs}`),
    {
      method: "POST",
      body: form,
    },
    1,
    800,
    180000 // 3 minutes timeout for previewing large spreadsheets
  );
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function submitFile(
  file: File,
  account: Account = "bajaj",
  channel: Channel = "whatsapp",
  user: string = "Operator",
  fixAspectRatio: boolean = true,
  fixGrammar: boolean = true,
  skipDuplicates: boolean = true,
  autoRoute: boolean = true
): Promise<{ submitted: number; skipped_duplicates?: number; results: Template[]; job_id?: string; status?: string }> {
  const form = new FormData();
  form.append("file", file);
  const qs = new URLSearchParams({
    account,
    channel,
    user,
    fix_aspect_ratio: String(fixAspectRatio),
    fix_grammar: String(fixGrammar),
    skip_duplicates: String(skipDuplicates),
    auto_route: String(autoRoute),
  }).toString();
  const res = await fetchWithRetry(
    getApiUrl(`/api/submit?${qs}`),
    {
      method: "POST",
      headers: { "X-User": user },
      body: form,
    },
    0, // 0 retries on submit to prevent duplicate batch processing
    800,
    600000 // 10 minutes timeout for batch submissions
  );
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export type IngestionJob = {
  id: string;
  tenant_id: string;
  channel: string;
  filename: string;
  total_count: number;
  submitted_count: number;
  duplicate_count: number;
  failed_count: number;
  status: "QUEUED" | "RUNNING" | "PAUSED_FOR_AUTH" | "COMPLETED" | "PARTIALLY_COMPLETED" | "FAILED";
  submitted_by?: string;
  error_message?: string;
  created_at: string;
  updated_at: string;
};

export type JobTask = {
  id: string;
  job_id: string;
  tenant_id: string;
  channel: string;
  source_ref?: string;
  template_name: string;
  category?: string;
  language?: string;
  status: "PENDING" | "SUBMITTED" | "DUPLICATE" | "FAILED";
  approval_status: "pending" | "approved" | "rejected" | "unknown";
  provider_ref_id?: string;
  error?: string;
  approval_reason?: string;
};

export async function fetchJob(jobId: string): Promise<{ job: IngestionJob; tasks: JobTask[] }> {
  const res = await fetchWithRetry(getApiUrl(`/api/jobs/${encodeURIComponent(jobId)}`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function resumeJob(jobId: string): Promise<{ ok: boolean; resumed_jobs?: number }> {
  const res = await fetchWithRetry(getApiUrl(`/api/jobs/${encodeURIComponent(jobId)}/resume`), {
    method: "POST",
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
  const res = await fetchWithRetry(getApiUrl(`/api/poll?${qs}`), {
    method: "POST",
    headers: { "X-User": user },
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchCredentials(
  account: Account = "bajaj",
  channel: Channel = "whatsapp"
): Promise<{
  account: string;
  channel: string;
  waba_id: string;
  waba_auth_token: string;
  bearer_token: string;
  session: string;
  user: string;
  portal_username?: string;
  portal_password?: string;
  template_namespace_id?: string;
  entity_id: string;
  lounge_cookie: string;
  sms_key?: string;
  sms_username?: string;
  sms_encryption_key?: string;
  sms_sender_id?: string;
  sms_dlr_auth_token?: string;
  rcs_bot_id?: string;
  rcs_auth_token?: string;
  esmeaddr?: string;
  rcs_esmeaddr?: string;
  gemini_api_key?: string;
  is_configured: boolean;
}> {
  const qs = new URLSearchParams({ account, channel }).toString();
  const res = await fetchWithRetry(getApiUrl(`/api/credentials?${qs}`));
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
  portal_username?: string;
  portal_password?: string;
  template_namespace_id?: string;
  entity_id?: string;
  lounge_cookie?: string;
  sms_key?: string;
  sms_username?: string;
  sms_encryption_key?: string;
  sms_sender_id?: string;
  sms_dlr_auth_token?: string;
  rcs_bot_id?: string;
  rcs_auth_token?: string;
  esmeaddr?: string;
  rcs_esmeaddr?: string;
  gemini_api_key?: string;
}): Promise<{ ok: boolean }> {
  const res = await fetchWithRetry(getApiUrl(`/api/credentials`), {
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
export async function testGemini(apiKey?: string): Promise<{
  ok: boolean;
  model?: string;
  result?: Record<string, unknown>;
  error?: string;
}> {
  const res = await fetchWithRetry(getApiUrl("/api/gemini/test"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(apiKey ? { api_key: apiKey } : {}),
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
  sms_key?: string;
  sms_username?: string;
  sms_encryption_key?: string;
  sms_sender_id?: string;
  sms_dlr_auth_token?: string;
  rcs_bot_id?: string;
  rcs_auth_token?: string;
  esmeaddr?: string;
  rcs_esmeaddr?: string;
  }
): Promise<{
  ok: boolean;
  message: string;
}> {
  const qs = new URLSearchParams({ account, channel, user: creds?.user_name || "Namann" }).toString();
  const res = await fetchWithRetry(getApiUrl(`/api/test-credentials?${qs}`), {
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

export async function sendSms(payload: {
  dest?: string[] | string;
  text?: string;
  send?: string;
  type?: string;
  dlt_entity_id?: string;
  dlt_template_id?: string;
  messages?: Array<Record<string, unknown>>;
  account?: Account;
  user?: string;
  encrypt_pii?: boolean;
  schedule_at?: string;
}): Promise<{
  ackid: string;
  time: string;
  status_code: string;
  status_desc: string;
  success: boolean;
  raw: Record<string, unknown>;
}> {
  const res = await fetchWithRetry(getApiUrl("/api/sms/send"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchSmsStats(account: Account = "all"): Promise<Record<string, unknown>> {
  const qs = new URLSearchParams({ account }).toString();
  const res = await fetchWithRetry(getApiUrl(`/api/sms/stats?${qs}`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchSmsLogs(params?: {
  account?: Account;
  type?: "submissions" | "dlr" | "clicks" | "all";
  limit?: number;
}): Promise<{
  account: string;
  submissions: Array<Record<string, unknown>>;
  dlrs: Array<Record<string, unknown>>;
  clicks: Array<Record<string, unknown>>;
}> {
  const qs = new URLSearchParams();
  if (params?.account) qs.set("account", params.account);
  if (params?.type) qs.set("type", params.type);
  if (params?.limit) qs.set("limit", String(params.limit));
  const res = await fetchWithRetry(getApiUrl(`/api/sms/logs?${qs.toString()}`));
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

  const res = await fetchWithRetry(getApiUrl(`/api/activity?${qs.toString()}`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchActivityStats(): Promise<ActivityStats> {
  const res = await fetchWithRetry(getApiUrl(`/api/activity/stats`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export function getSampleCsvUrl(channel: Channel = "whatsapp"): string {
  return getApiUrl(`/api/sample-csv?channel=${channel}`);
}

export async function fetchAccounts(): Promise<AccountItem[]> {
  const res = await fetchWithRetry(getApiUrl("/api/accounts"));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function createAccount(name: string, id?: string, user?: string): Promise<AccountItem> {
  const qs = user ? `?user=${encodeURIComponent(user)}` : '';
  const res = await fetchWithRetry(getApiUrl(`/api/accounts${qs}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, id }),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function deleteAccount(id: string, user?: string): Promise<{ ok: boolean }> {
  const qs = user ? `?user=${encodeURIComponent(user)}` : '';
  const res = await fetchWithRetry(getApiUrl(`/api/accounts/${encodeURIComponent(id)}${qs}`), {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchUsers(): Promise<UserItem[]> {
  const res = await fetchWithRetry(getApiUrl("/api/users"));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function registerUser(name: string, role: string = "Operator"): Promise<UserItem> {
  const res = await fetchWithRetry(getApiUrl("/api/users"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, role }),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export type AgentChatAction = {
  tool: string;
  target?: string;
  result?: unknown;
  [key: string]: unknown;
};

export type AgentChatResponse = {
  reply: string;
  actions_taken: AgentChatAction[];
  suggested_actions: string[];
  data?: unknown;
};

export async function sendAgentMessage(
  message: string,
  account: Account = "bajaj",
  channel: Channel = "whatsapp",
  user: string = "Operator",
  history: Array<{ role: string; content: string }> = []
): Promise<AgentChatResponse> {
  const res = await fetchWithRetry(getApiUrl("/api/agent/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, account, channel, user, history }),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}


export async function loginUser(email: string, password: string): Promise<AuthResponse> {
  const res = await fetchWithRetry(getApiUrl("/api/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  const data: AuthResponse = await res.json();
  if (data.token) {
    setAuthToken(data.token);
  }
  return data;
}

export async function signupUser(
  email: string,
  password: string,
  name: string,
  tenant_id: string = "bajaj"
): Promise<AuthResponse> {
  const res = await fetchWithRetry(getApiUrl("/api/auth/signup"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, name, tenant_id }),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  const data: AuthResponse = await res.json();
  if (data.token) {
    setAuthToken(data.token);
  }
  return data;
}

export async function fetchMe(): Promise<AuthUser> {
  const res = await fetchWithRetry(getApiUrl("/api/auth/me"));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchTeam(): Promise<AuthUser[]> {
  const res = await fetchWithRetry(getApiUrl("/api/auth/team"));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function inviteColleague(
  email: string,
  password: string,
  name: string,
  role: string = "operator"
): Promise<AuthUser> {
  const res = await fetchWithRetry(getApiUrl("/api/auth/team/invite"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, name, role }),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export type DeleteTemplatesResult = {
  deleted: Array<{ ok: boolean; template_name: string; detail: string }>;
  failed: Array<{ ok: boolean; template_name: string; detail: string }>;
  total: number;
  error?: string;
};

export async function deleteTemplates(
  templateNames: string[],
  account: Account = "bajaj",
  channel: Channel = "whatsapp",
  user: string = "Operator",
  deleteAll: boolean = false
): Promise<DeleteTemplatesResult> {
  const qs = new URLSearchParams({ account, channel, user });
  const res = await fetchWithRetry(getApiUrl(`/api/templates/delete?${qs}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      template_names: deleteAll ? null : templateNames,
      delete_all: deleteAll,
    }),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function deleteTemplatesFromFile(
  file: File,
  account: Account = "bajaj",
  channel: Channel = "whatsapp",
  user: string = "Operator"
): Promise<DeleteTemplatesResult> {
  const form = new FormData();
  form.append("file", file);
  const qs = new URLSearchParams({ account, channel, user });
  const res = await fetchWithRetry(getApiUrl(`/api/templates/delete-file?${qs}`), {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}
// ---------------------------------------------------------------------------
// Jira Briefing Agent Client APIs
// ---------------------------------------------------------------------------

export type JiraIssueItem = {
  key: string;
  id: string;
  summary: string;
  status: string;
  assignee: string;
  reporter: string;
  duedate?: string | null;
  attachment_count: number;
  attachments: Array<{
    id: string;
    filename: string;
    size: number;
    mimeType: string;
  }>;
  labels?: string[];
  created?: string;
  updated?: string;
  is_email?: boolean;
  campaign_type?: 'email' | 'messaging';
};

export type JiraWhatsAppDraft = {
  template_name: string;
  category: string;
  body: string;
  language: string;
  header_type: string;
  header_text?: string | null;
  footer_text?: string | null;
  media_file?: string | null;
  media_filename?: string | null;
  button_type: string;
  button_text?: string | null;
  button_url?: string | null;
  button_phone?: string | null;
  variables: string[];
  sample_values?: string[];
  buttons?: Array<{ type: string; text: string; url?: string; phone_number?: string }>;
  raw_source: string;
  exists_on_waba?: boolean;
  live_status?: string;
  live_ref_id?: string | null;
};

export type JiraRcsDraft = {
  template_name: string;
  card_title: string;
  body: string;
  media_file?: string | null;
  media_filename?: string | null;
  action_type: string;
  action_label: string;
  action_url: string;
  variables: string[];
  raw_source: string;
};

export type JiraSmsDraft = {
  template_name: string;
  text: string;
  char_count: number;
  variant: string;
  variables: string[];
  raw_source: string;
};

export type JiraBriefData = {
  issue_key: string;
  summary: string;
  account: string;
  status: string;
  assignee: string;
  reporter: string;
  duedate?: string | null;
  is_email_campaign?: boolean;
  campaign_type_label?: string;
  whatsapp_templates: JiraWhatsAppDraft[];
  rcs_templates: JiraRcsDraft[];
  sms_templates: JiraSmsDraft[];
  email_templates?: Array<{
    template_name: string;
    filename?: string;
    file_type?: string;
    body?: string;
    local_path?: string | null;
    target_channel?: string;
  }>;
  moengage_campaign: {
    campaign_name: string;
    target_account: string;
    scheduled_date?: string | null;
    whatsapp_template?: string | null;
    sms_content?: string | null;
    push_title?: string;
    push_body?: string;
    status: string;
  };
  attachments_mapped: Array<{
    id: string;
    filename: string;
    local_path?: string | null;
    mime: string;
    target_channel: string;
  }>;
  comments?: Array<{
    id: string;
    author: string;
    created: string;
    updated?: string;
    body_text: string;
  }>;
  comment_updates?: Array<{
    channel: string;
    text: string;
    variant: string;
    source: string;
  }>;
};

export type JiraProjectItem = {
  key: string;
  name: string;
};

export async function fetchJiraProjects(): Promise<JiraProjectItem[]> {
  try {
    const res = await fetchWithRetry(getApiUrl("/api/jira/projects"));
    if (res.ok) {
      return await res.json();
    }
  } catch {
    // Fall back to static catalog
  }
  return [
    { key: "ALL", name: "All Tata Projects Combined" },
    { key: "TCN", name: "Tata Capital New" },
    { key: "SWCM", name: "TATA Service and wealth Campaign Manager" },
    { key: "TM", name: "Tata Moneyfy" },
    { key: "TAT", name: "Tata Capital Marketing" },
    { key: "MON", name: "Moneyfy Mobile" },
    { key: "COL", name: "Collections & Operations" },
  ];
}

export async function fetchJiraIssues(params?: {
  project?: string;
  status?: string;
  search?: string;
  limit?: number;
}): Promise<JiraIssueItem[]> {
  const qs = new URLSearchParams();
  if (params?.project) qs.set("project", params.project);
  if (params?.status) qs.set("status", params.status);
  if (params?.search) qs.set("search", params.search);
  if (params?.limit) qs.set("limit", String(params.limit));

  const res = await fetchWithRetry(getApiUrl(`/api/jira/issues?${qs.toString()}`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  const data = await res.json();
  return data.issues || [];
}

export async function fetchJiraBrief(issueKey: string, account?: string): Promise<JiraBriefData> {
  const cleanKey = encodeURIComponent(issueKey.trim().toUpperCase());
  const qs = account ? `?account=${encodeURIComponent(account)}` : "";
  const res = await fetchWithRetry(getApiUrl(`/api/jira/brief/${cleanKey}${qs}`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  const data = await res.json();
  return data.brief;
}

export async function submitJiraBrief(
  issueKey: string,
  channels: string[] = ["whatsapp", "rcs"],
  user: string = "Briefing Operator",
  whatsappTemplates?: JiraWhatsAppDraft[],
  rcsTemplates?: JiraRcsDraft[],
  account?: string
): Promise<{
  ok: boolean;
  issue_key: string;
  account: string;
  whatsapp_submitted: Array<{ template_name: string; status: string; approval_status: string; error?: string }>;
  rcs_submitted: Array<{ template_name: string; status: string; template_id?: string; error?: string }>;
}> {
  const cleanKey = encodeURIComponent(issueKey.trim().toUpperCase());
  const res = await fetchWithRetry(getApiUrl(`/api/jira/submit/${cleanKey}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      account,
      channels,
      user,
      whatsapp_templates: whatsappTemplates || null,
      rcs_templates: rcsTemplates || null,
    }),
  }, 0, 800, 300000);
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}
export async function syncRcsTemplateToMoEngage(params: {
  template_name: string;
  template_id: string;
  card_title: string;
  card_description: string;
  media_url?: string | null;
  cta_text?: string;
  cta_url?: string;
  sender_id?: string;
}): Promise<{ ok: boolean; name: string; template_id: string; moengage_id: string }> {
  const res = await fetchWithRetry(getApiUrl("/api/moengage/rcs/sync"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export type MoEngageCredentials = {
  ok: boolean;
  account: string;
  base_url?: string;
  sender_id?: string;
  has_token: boolean;
  has_cookie: boolean;
  bearer_token: string;
  cookie: string;
  expired?: boolean;
  expires_at?: number | null;
  remaining_min?: number | null;
};

export async function fetchMoEngageCredentials(account: string = "tata"): Promise<MoEngageCredentials> {
  const qs = new URLSearchParams({ account });
  const res = await fetchWithRetry(getApiUrl(`/api/moengage/credentials?${qs}`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function saveMoEngageCredentials(
  account: string,
  bearerToken: string,
  cookie: string,
  baseUrl?: string,
  senderId?: string
): Promise<{ ok: boolean; account: string; updated_keys: string[]; expired?: boolean; remaining_min?: number | null }> {
  const res = await fetchWithRetry(getApiUrl("/api/moengage/credentials"), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      account,
      base_url: baseUrl || null,
      bearer_token: bearerToken,
      cookie,
      sender_id: senderId || null,
    }),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function testMoEngageConnection(account: string = "tata"): Promise<{
  ok: boolean;
  error?: string;
  template_count?: number;
  expired?: boolean;
  remaining_min?: number | null;
}> {
  const res = await fetchWithRetry(getApiUrl(`/api/moengage/test?account=${encodeURIComponent(account)}`), {
    method: "POST",
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function syncKarixRcsToMoEngage(account: string = "tata"): Promise<{
  ok: boolean;
  account: string;
  error?: string;
  karix_total: number;
  created: Array<{ template_name: string; template_id: string; moengage_id: string }>;
  created_count: number;
  skipped: string[];
  skipped_count: number;
  errors: Array<{ template_name: string; error: string }>;
  error_count: number;
}> {
  const res = await fetchWithRetry(getApiUrl(`/api/moengage/rcs/sync-karix?account=${encodeURIComponent(account)}`), {
    method: "POST",
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchMoEngageOpsDashboard(mode: string = "last_week", customStart?: string, customEnd?: string, workspace?: string) {
  const qs = new URLSearchParams({ mode });
  if (customStart) qs.set("custom_start", customStart);
  if (customEnd) qs.set("custom_end", customEnd);
  if (workspace && workspace !== "all") qs.set("workspace", workspace);
  const res = await fetchWithRetry(getApiUrl(`/api/moengage/ops/dashboard?${qs.toString()}`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function syncMoEngageOps() {
  const res = await fetchWithRetry(getApiUrl(`/api/moengage/ops/sync`), {
    method: "POST",
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchMoEngageWorkspaces() {
  const res = await fetchWithRetry(getApiUrl(`/api/moengage/ops/workspaces`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function updateMoEngageWorkspace(data: {
  workspace_name: string;
  vertical: string;
  workspace_id: string;
  api_key: string;
  data_center?: string;
  is_active?: boolean;
}) {
  const res = await fetchWithRetry(getApiUrl(`/api/moengage/ops/workspaces`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchWorkManagementDashboard(project: string = "TCN", limit: number = 100) {
  const qs = new URLSearchParams({ project, limit: limit.toString() });
  const res = await fetchWithRetry(getApiUrl(`/api/work-management/dashboard?${qs.toString()}`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchWorkManagementAssignees(project: string = "TCN") {
  const qs = new URLSearchParams({ project });
  const res = await fetchWithRetry(getApiUrl(`/api/work-management/assignees?${qs.toString()}`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function transferJiraTicket(issue_key: string, to_account_id: string, handover_note?: string, transferred_by?: string) {
  const res = await fetchWithRetry(getApiUrl(`/api/work-management/transfer`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ issue_key, to_account_id, handover_note: handover_note || "", transferred_by }),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function bulkTransferJiraTickets(
  issue_keys: string[],
  to_account_id: string,
  handover_note?: string,
  transferred_by?: string
) {
  const res = await fetchWithRetry(getApiUrl(`/api/work-management/bulk-transfer`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ issue_keys, to_account_id, handover_note: handover_note || "", transferred_by }),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function aiRebalanceWorkload(prompt: string, project: string = "TCN", auto_execute: boolean = false) {
  const res = await fetchWithRetry(getApiUrl(`/api/work-management/ai-rebalance`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt, project, auto_execute }),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchWorkManagementProjects() {
  const res = await fetchWithRetry(getApiUrl(`/api/work-management/projects`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchTurnaroundAnalytics(project: string = "SWCM", limit: number = 100) {
  const qs = new URLSearchParams({ project, limit: limit.toString() });
  const res = await fetchWithRetry(getApiUrl(`/api/work-management/turnaround-analytics?${qs.toString()}`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export type TemplateDiscrepancyItem = {
  template_name: string;
  status: 'WHITELISTED' | 'NOT_WHITELISTED' | 'PENDING' | 'REJECTED' | 'CONTENT_DRIFT' | 'PAUSED' | string;
  category: string;
  language: string;
  master_body: string;
  live_body: string;
  match_confidence: number;
  match_method: string;
  diff_summary: string;
  live_fb_id?: string | null;
  live_status_raw?: string | null;
  action_required: 'SUBMIT' | 'REMEDIATE' | 'WAIT' | 'NONE';
};

export type IdentificationReport = {
  account: string;
  total_master: number;
  whitelisted_count: number;
  missing_count: number;
  pending_count: number;
  rejected_count: number;
  drift_count: number;
  summary_notes: string;
  items: TemplateDiscrepancyItem[];
  missing_templates: Array<Record<string, unknown>>;
};

export async function identifyTemplates(file: File, account: string = 'bajaj'): Promise<IdentificationReport> {
  const form = new FormData();
  form.append('file', file);
  const qs = new URLSearchParams({ account });
  const res = await fetchWithRetry(getApiUrl(`/api/templates/identify?${qs.toString()}`), {
    method: 'POST',
    body: form,
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function identifyTemplatesJson(templates: Array<Record<string, unknown>>, account: string = 'bajaj'): Promise<IdentificationReport> {
  const res = await fetchWithRetry(getApiUrl('/api/templates/identify-json'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ templates, account }),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export type AlertEmailDraft = {
  stage: 'MORNING' | 'MIDDAY' | 'EOD' | string;
  recipient_email: string;
  recipient_name: string;
  subject: string;
  body_text: string;
  body_html: string;
  pending_count: number;
  ticket_keys: string[];
};

export type SmtpSenderInfo = {
  is_configured: boolean;
  from_email: string;
  smtp_host: string;
  smtp_port: number;
  smtp_user: string;
  mode: 'LIVE_SMTP' | 'SIMULATION' | string;
};

export type AlertsPreviewResponse = {
  ok: boolean;
  project: string;
  stage: string;
  ist_time: string;
  sender_info?: SmtpSenderInfo;
  total_due_today_incomplete: number;
  recipient_count: number;
  drafts: AlertEmailDraft[];
};

export type AlertsDispatchResponse = {
  ok: boolean;
  stage: string;
  date: string;
  sender_info?: SmtpSenderInfo;
  total_tickets: number;
  recipients_count: number;
  delivered_count: number;
  real_sent_count: number;
  simulated_count: number;
  failed_count: number;
  google_chat_result?: { delivered?: boolean; simulated?: boolean; message?: string; error?: string };
  dry_run: boolean;
  dispatched_by: string;
  results: Array<{
    delivered: boolean;
    simulated: boolean;
    recipient: string;
    subject: string;
    message?: string;
    error?: string;
  }>;
};

export type AlertsDispatchOptions = {
  project?: string;
  stage?: string;
  dry_run?: boolean;
  send_google_chat?: boolean;
  send_email?: boolean;
  google_chat_webhook_url?: string;
};
export type AlertSchedulerStatusResponse = {
  enabled: boolean;
  ist_time: string;
  current_stage: string;
  last_sent: Record<string, string>;
  history: Array<{
    slot_key: string;
    stage: string;
    date: string;
    dispatched_at: string;
    delivered_count?: number;
    failed_count?: number;
  }>;
};

export async function fetchAlertsPreview(project: string = 'ALL', stage: string = 'AUTO'): Promise<AlertsPreviewResponse> {
  const qs = new URLSearchParams({ project, stage });
  const res = await fetchWithRetry(getApiUrl(`/api/work-management/alerts/preview?${qs.toString()}`));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function dispatchAlerts(options: AlertsDispatchOptions = {}): Promise<AlertsDispatchResponse> {
  const res = await fetchWithRetry(getApiUrl('/api/work-management/alerts/dispatch'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(options),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function fetchAlertSchedulerStatus(): Promise<AlertSchedulerStatusResponse> {
  const res = await fetchWithRetry(getApiUrl('/api/work-management/alerts/scheduler-status'));
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}

export async function toggleAlertScheduler(enabled: boolean): Promise<AlertSchedulerStatusResponse> {
  const res = await fetchWithRetry(getApiUrl('/api/work-management/alerts/scheduler-toggle'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
  if (!res.ok) throw new Error(await getErrorMessage(res));
  return res.json();
}
