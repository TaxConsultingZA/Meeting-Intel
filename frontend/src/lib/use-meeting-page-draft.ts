"use client";

import { useMemo, useState, useSyncExternalStore } from "react";

const subscribe = (notify: () => void) => {
  window.addEventListener("storage", notify);
  return () => window.removeEventListener("storage", notify);
};
const serverSnapshot = () => "";

/** Keep only input drafts, never meeting results or credentials, across route unmounts. */
export function useMeetingPageDraft<T extends Record<string, string>>(page: string, userKey: string | undefined, initial: T) {
  const [edited, setEdited] = useState<T | null>(null);
  const key = userKey ? `meeting-intel:draft:${page}:${userKey}` : undefined;
  const stored = useSyncExternalStore(subscribe, () => {
    try { return key ? sessionStorage.getItem(key) ?? "" : ""; } catch { return ""; }
  }, serverSnapshot);
  const restored = useMemo(() => {
    try {
      const value: unknown = JSON.parse(stored || "null");
      if (value && typeof value === "object" && Object.keys(initial).every(field => typeof (value as Record<string, unknown>)[field] === "string")) {
        return Object.fromEntries(Object.keys(initial).map(field => [field, (value as Record<string, string>)[field].slice(0, 255)])) as T;
      }
    } catch { /* Ignore malformed or unavailable browser storage. */ }
    return initial;
  }, [stored, initial]);
  function update(value: T) {
    setEdited(value);
    if (key) {
      try { sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* Inputs still work in memory. */ }
    }
  }
  return [edited ?? restored, update] as const;
}
