export type Account = "bajaj" | "tata";
export type Channel = "whatsapp" | "rcs";

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
  updated_at?: string | null;
  provider_response?: Record<string, unknown> | null;
  client?: string;
  channel?: string;
  // RCS-specific fields
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
  sender_ids?: string[];
  template_message_type?: string;
  template_message?: string;
  entity_id?: string;
};

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function fetchStats(
  account: Account = "bajaj",
  channel: Channel = "whatsapp"
): Promise<Stats> {
  const url = new URL(`${API}/api/stats`);
  url.searchParams.set("account", account);
  url.searchParams.set("channel", channel);
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function fetchTemplates(params?: {
  account?: Account;
  channel?: Channel;
  status?: string;
  search?: string;
}): Promise<Template[]> {
  const url = new URL(`${API}/api/templates`);
  url.searchParams.set("account", params?.account || "bajaj");
  url.searchParams.set("channel", params?.channel || "whatsapp");
  if (params?.status) url.searchParams.set("status", params.status);
  if (params?.search) url.searchParams.set("search", params.search);
  const res = await fetch(url.toString());
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function previewFile(
  file: File,
  account: Account = "bajaj",
  channel: Channel = "whatsapp"
): Promise<TemplatePreview[]> {
  const form = new FormData();
  form.append("file", file);
  const url = new URL(`${API}/api/preview`);
  url.searchParams.set("account", account);
  url.searchParams.set("channel", channel);
  const res = await fetch(url.toString(), {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function submitFile(
  file: File,
  account: Account = "bajaj",
  channel: Channel = "whatsapp"
): Promise<{ submitted: number; results: Template[] }> {
  const form = new FormData();
  form.append("file", file);
  const url = new URL(`${API}/api/submit`);
  url.searchParams.set("account", account);
  url.searchParams.set("channel", channel);
  const res = await fetch(url.toString(), {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function pollPending(
  account: Account = "bajaj",
  channel: Channel = "whatsapp"
): Promise<{ checked: number }> {
  const url = new URL(`${API}/api/poll`);
  url.searchParams.set("account", account);
  url.searchParams.set("channel", channel);
  const res = await fetch(url.toString(), { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
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
  entity_id?: string;
  lounge_cookie?: string;
}): Promise<{ ok: boolean }> {
  const res = await fetch(`${API}/api/credentials`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(creds),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function testCredentials(
  account: Account = "bajaj",
  channel: Channel = "whatsapp"
): Promise<{
  ok: boolean;
  message: string;
}> {
  const url = new URL(`${API}/api/test-credentials`);
  url.searchParams.set("account", account);
  url.searchParams.set("channel", channel);
  const res = await fetch(url.toString(), { method: "POST" });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function getSampleCsvUrl(channel: Channel = "whatsapp"): string {
  return `${API}/api/sample-csv?channel=${channel}`;
}
