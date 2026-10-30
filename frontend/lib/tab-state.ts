'use client';

import { useState, useCallback, useRef } from 'react';

// In-memory cache for fast retrieval and storing live runtime objects
const memoryCache = new Map<string, any>();
let workspaceGeneration = 0;

/**
 * Retrieve cached tab state. Checks memoryCache first, then sessionStorage.
 */
export function getTabState<T>(key: string, defaultValue: T): T {
  if (memoryCache.has(key)) {
    const val = memoryCache.get(key);
    // If defaultValue is a Set but memory cached an Array, convert
    if (defaultValue instanceof Set && Array.isArray(val)) {
      return new Set(val) as unknown as T;
    }
    return val as T;
  }
  if (typeof window !== 'undefined') {
    try {
      const stored = sessionStorage.getItem(`karix_tab:${key}`);
      if (stored !== null) {
        const parsed = JSON.parse(stored);
        if (defaultValue instanceof Set && Array.isArray(parsed)) {
          const s = new Set(parsed);
          memoryCache.set(key, s);
          return s as unknown as T;
        }
        memoryCache.set(key, parsed);
        return parsed as T;
      }
    } catch {
      // Ignore storage errors
    }
  }
  return defaultValue;
}

/**
 * Save tab state to memoryCache and mirror to sessionStorage.
 */
export function setTabState<T>(key: string, value: T): void {
  memoryCache.set(key, value);
  if (typeof window !== 'undefined') {
    try {
      if (value instanceof Set) {
        sessionStorage.setItem(`karix_tab:${key}`, JSON.stringify(Array.from(value)));
      } else {
        sessionStorage.setItem(`karix_tab:${key}`, JSON.stringify(value));
      }
    } catch {
      // Ignore non-serializable objects (preserved in memoryCache)
    }
  }
}

/**
 * Clear cached tab state, optionally matching a key prefix.
 */
export function clearTabState(prefix?: string): void {
  if (!prefix) {
    workspaceGeneration += 1;
    memoryCache.clear();
    if (typeof window !== 'undefined') {
      try {
        const keysToRemove: string[] = [];
        for (let i = 0; i < sessionStorage.length; i++) {
          const k = sessionStorage.key(i);
          if (k && k.startsWith('karix_tab:')) {
            keysToRemove.push(k);
          }
        }
        keysToRemove.forEach((k) => sessionStorage.removeItem(k));
      } catch {}
    }
    return;
  }

  for (const k of Array.from(memoryCache.keys())) {
    if (k.startsWith(prefix)) {
      memoryCache.delete(k);
    }
  }
  if (typeof window !== 'undefined') {
    try {
      const target = `karix_tab:${prefix}`;
      const keysToRemove: string[] = [];
      for (let i = 0; i < sessionStorage.length; i++) {
        const k = sessionStorage.key(i);
        if (k && k.startsWith(target)) {
          keysToRemove.push(k);
        }
      }
      keysToRemove.forEach((k) => sessionStorage.removeItem(k));
    } catch {}
  }
}

/** Only actual work, not filters or navigation, needs a destination-change warning. */
export function hasWorkspaceDrafts(): boolean {
  const submission = getTabState<{ step?: string } | null>('submit_state', null);
  if (submission?.step && submission.step !== 'idle') return true;
  if (getTabState<unknown[] | null>('submit_sms_dlt_source', null)?.length) return true;
  if (getTabState('submit_sms_dlt_identification', null)) return true;
  if (getTabState<unknown[] | null>('submit_sms_dlt_brief_selected', null)?.length) return true;
  if (getTabState('submit_identify_report', null)) return true;
  for (const key of ['briefs_wa_templates', 'briefs_rcs_templates', 'briefs_sms_templates']) {
    if (getTabState<unknown[]>(key, []).length > 0) return true;
  }
  return ['settings_unsaved', 'moe_unsaved_preview', 'moe_single_name', 'moe_single_subject',
    'moe_single_html', 'moe_single_push_title', 'moe_single_push_message']
    .some((key) => Boolean(getTabState<unknown>(key, null)));
}

/**
 * React hook that mirrors useState but persists values across tab/route switches
 * and browser tab reloads.
 */
export function useTabState<T>(
  key: string,
  defaultValue: T
): [T, (val: T | ((prev: T) => T)) => void, () => void] {
  const [state, setStateInternal] = useState<T>(() => getTabState(key, defaultValue));
  const keyRef = useRef(key);
  keyRef.current = key;
  const generation = workspaceGeneration;

  const setState = useCallback((action: T | ((prev: T) => T)) => {
    if (generation !== workspaceGeneration) return;
    setStateInternal((current) => {
      if (generation !== workspaceGeneration) return current;
      const next = typeof action === 'function' ? (action as (prev: T) => T)(current) : action;
      setTabState(keyRef.current, next);
      return next;
    });
  }, [generation]);

  const resetState = useCallback(() => {
    if (generation !== workspaceGeneration) return;
    memoryCache.delete(keyRef.current);
    if (typeof window !== 'undefined') {
      try {
        sessionStorage.removeItem(`karix_tab:${keyRef.current}`);
      } catch {}
    }
    setStateInternal(defaultValue);
  }, [defaultValue, generation]);

  return [state, setState, resetState];
}
