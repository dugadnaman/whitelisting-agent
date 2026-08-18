/**
 * Shared formatting helpers for the Karix dashboard.
 */

export function formatError(err: unknown): string {
  if (!err) return '';
  if (typeof err === 'string') {
    const s = err.trim();
    if (s.startsWith('HTTP ') && s.includes(':')) {
      const rest = s.split(':').slice(1).join(':').trim();
      const cleaned = formatError(rest);
      if (cleaned && cleaned !== rest) return cleaned;
    }
    const matchUser = s.match(/"error_user_msg"\s*:\s*"([^"]+)"/);
    if (matchUser) return matchUser[1];
    const matchMsg = s.match(/"message"\s*:\s*"([^"]+)"/);
    if (matchMsg && !matchMsg[1].includes('Invalid parameter')) return matchMsg[1];
    return s;
  }
  if (typeof err === 'object') {
    const anyErr = err as Record<string, unknown>;
    if (anyErr.error_user_msg) return String(anyErr.error_user_msg);
    if (anyErr.errorMessage) return formatError(anyErr.errorMessage);
    if (anyErr.error && typeof anyErr.error === 'object') {
      const nested = anyErr.error as Record<string, unknown>;
      return String(nested.error_user_msg || nested.message || JSON.stringify(nested));
    }
    if (anyErr.error) return formatError(anyErr.error);
    if (anyErr.message) return String(anyErr.message);
    if (anyErr.reason) return formatError(anyErr.reason);
    try {
      return JSON.stringify(err);
    } catch {
      return String(err);
    }
  }
  return String(err);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
    });
  } catch {
    return iso;
  }
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    const diffSec = Math.floor((Date.now() - d.getTime()) / 1000);
    if (diffSec < 60) return 'just now';
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
    return `${Math.floor(diffSec / 86400)}d ago`;
  } catch {
    return iso;
  }
}

export function truncate(s: string | null | undefined, n: number): string {
  if (!s) return '—';
  return s.length > n ? `${s.slice(0, n - 1)}…` : s;
}
