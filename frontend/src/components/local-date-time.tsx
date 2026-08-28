"use client";
import { useSyncExternalStore } from "react";
import { formatDateTime, resolveTimeZone } from "@/lib/time";

const subscribe = () => () => {};
const snapshot = () => resolveTimeZone(null, Intl.DateTimeFormat().resolvedOptions().timeZone);
const serverSnapshot = () => null;

export function useUserTimeZone() {
  // No reliable mailbox/profile zone is currently persisted. Browser IANA zone
  // is the user's local zone; don't use the Vercel server's zone during SSR.
  return useSyncExternalStore(subscribe, snapshot, serverSnapshot);
}

export default function LocalDateTime({ value }: { value?: string | null }) {
  const zone = useUserTimeZone();
  return <span>{zone ? formatDateTime(value, zone) : "—"}</span>;
}
