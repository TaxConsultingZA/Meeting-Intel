"use client";

import { useRef, useState } from "react";
import { ApiError, setTaskCompletion } from "@/lib/api";
import type { TaskCompletion } from "@/lib/types";
import LocalDateTime from "./local-date-time";

export default function TaskCompletionControl({ item, token, onUpdate }: {
  item: TaskCompletion & { id: string; task: string }; token: string;
  onUpdate: (value: TaskCompletion) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  async function save() {
    if (inFlight.current || !item.can_complete) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      onUpdate(await setTaskCompletion(item.id, !item.completed_at, token));
    } catch (failure) {
      setError(failure instanceof ApiError && failure.status === 403
        ? "You no longer have permission to update this task. Refresh to check access."
        : "Could not confirm task status. Refresh to check the saved status, then try again.");
    } finally { inFlight.current = false; setBusy(false); }
  }
  return <div className="min-w-36 space-y-2" aria-busy={busy}>
    <p className={`text-xs font-semibold ${item.completed_at ? "text-green-800" : "text-[#003366]"}`}>{item.completed_at ? "Completed" : "Open"}</p>
    {item.completed_at && <p className="text-xs text-gray-500">Completed at <LocalDateTime value={item.completed_at} /></p>}
    {item.can_complete && <button type="button" disabled={busy} onClick={() => void save()}
      aria-label={`${item.completed_at ? "Reopen" : "Mark complete"}: ${item.task}`}
      className="rounded border border-[#dde1e8] px-3 py-1.5 text-xs font-semibold text-[#003366] hover:bg-blue-50 disabled:opacity-50">
      {busy ? "Saving…" : item.completed_at ? "Reopen" : "Mark complete"}
    </button>}
    {error && <p role="alert" className="max-w-xs text-xs text-red-700">{error}</p>}
  </div>;
}
