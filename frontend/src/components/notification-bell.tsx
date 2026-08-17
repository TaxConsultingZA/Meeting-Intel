"use client";
import { useState, useEffect, useRef, useCallback } from "react";
import Link from "next/link";
import { Bell, CheckCircle2, AlertCircle, Clock, Send } from "lucide-react";
import { getNotifications } from "@/lib/api";
import type { AppNotification } from "@/lib/types";

const SEEN_KEY = "mi_seen_notifications";
const POLL_MS  = 30_000;

const TYPE_ICON: Record<AppNotification["type"], React.ReactNode> = {
  ready_for_review: <CheckCircle2 size={14} className="text-amber-500 shrink-0 mt-0.5" />,
  notes_sent:       <Send size={14} className="text-green-500 shrink-0 mt-0.5" />,
  failed:           <AlertCircle size={14} className="text-red-500 shrink-0 mt-0.5" />,
  processing:       <Clock size={14} className="text-blue-500 shrink-0 mt-0.5" />,
};

/** Read the set of already-seen notification IDs from localStorage. */
function getSeenIds(): Set<string> {
  try { return new Set(JSON.parse(localStorage.getItem(SEEN_KEY) ?? "[]")); }
  catch { return new Set(); }
}

/** Add notification IDs to the seen set in localStorage, capping at 100 entries. */
function markSeen(ids: string[]) {
  try {
    const existing = getSeenIds();
    ids.forEach((id) => existing.add(id));
    localStorage.setItem(SEEN_KEY, JSON.stringify([...existing].slice(-100)));
  } catch {}
}

/** Convert an ISO timestamp to a human-readable relative string ("5m ago", "2h ago"). */
function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export default function NotificationBell({ upn }: { upn: string }) {
  const [notifications, setNotifications] = useState<AppNotification[]>([]);
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const ref = useRef<HTMLDivElement>(null);

  const fetchAndDiff = useCallback(async () => {
    try {
      const data = await getNotifications(upn);
      setNotifications(data);
      const seen = getSeenIds();
      setUnread(data.filter((n) => !seen.has(n.id)).length);
    } catch {}
  }, [upn]);

  useEffect(() => {
    const initial = window.setTimeout(() => void fetchAndDiff(), 0);
    const interval = setInterval(fetchAndDiff, POLL_MS);
    return () => {
      window.clearTimeout(initial);
      clearInterval(interval);
    };
  }, [fetchAndDiff]);

  // Close on outside click
  useEffect(() => {
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  function handleOpen() {
    setOpen((o) => !o);
    if (!open) {
      markSeen(notifications.map((n) => n.id));
      setUnread(0);
    }
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={handleOpen}
        className="relative text-white/60 hover:text-white transition-colors p-1"
        aria-label="Notifications"
      >
        <Bell size={18} />
        {unread > 0 && (
          <span className="absolute -top-1 -right-1 w-4 h-4 bg-[#C9A52C] text-[#003366] text-[9px] font-bold rounded-full flex items-center justify-center">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-9 w-80 bg-white rounded-lg shadow-xl border border-[#dde1e8] z-50 overflow-hidden">
          <div className="bg-[#003366] border-b-[3px] border-[#C9A52C] px-4 py-3 flex items-center justify-between">
            <span className="text-white font-semibold text-[13.5px]">Notifications</span>
            {notifications.length > 0 && (
              <span className="text-white/60 text-[11px]">{notifications.length} recent</span>
            )}
          </div>

          <div className="max-h-80 overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="py-10 text-center text-[#9ca3af] text-[13px]">
                <Bell size={28} className="mx-auto mb-2 opacity-30" />
                No notifications yet
              </div>
            ) : (
              notifications.map((n) => {
                const inner = (
                  <div className="flex gap-2.5 px-4 py-3 border-b border-[#f3f4f6] hover:bg-[#f8fafc] transition-colors">
                    {TYPE_ICON[n.type]}
                    <div className="flex-1 min-w-0">
                      <p className="text-[12.5px] font-semibold text-[#1a1a2e] truncate">{n.title}</p>
                      <p className="text-[11.5px] text-[#6b7280] mt-0.5">{n.message}</p>
                      <p className="text-[11px] text-[#9ca3af] mt-0.5">{timeAgo(n.time)}</p>
                    </div>
                  </div>
                );
                return n.link ? (
                  <Link key={n.id} href={n.link} onClick={() => setOpen(false)}>
                    {inner}
                  </Link>
                ) : (
                  <div key={n.id}>{inner}</div>
                );
              })
            )}
          </div>
        </div>
      )}
    </div>
  );
}
