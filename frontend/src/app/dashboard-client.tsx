"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Calendar, Users, ChevronRight, Upload, Mic, Video, Share2, History, Lock, Power } from "lucide-react";
import StateBadge from "@/components/state-badge";
import LocalDateTime, { useUserTimeZone } from "@/components/local-date-time";
import RecordingJobs from "@/components/recording-jobs";
import { formatEventTime } from "@/lib/time";
import ImportModal from "@/components/import-modal";
import { getAllMeetings, requestHistoricalAccess, shareMeeting, unsubscribeCurrentUser } from "@/lib/api";
import type { MeetingOut, ProcessingState, CalendarEvent, SyncState } from "@/lib/types";

/** Convert a UPN like "jane.doe@taxconsulting.co.za" to a display name "Jane Doe". */
function formatUpn(upn: string | null | undefined): string {
  if (!upn) return "";
  return upn.split("@")[0].split(".").map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
}

const PIPELINE_STATES: ProcessingState[] = ["queued", "downloading", "transcribing", "extracting"];

interface Props {
  meetings: MeetingOut[];
  upcoming: CalendarEvent[];
  historical: MeetingOut[];
  upn: string;
  accessToken: string;
  isSubscribed: boolean;
  syncStates: SyncState[];
  loadErrors: string[];
}

type Tab = "upcoming" | "in_progress" | "review" | "old_meetings" | "historical" | "cancelled";

function conciseMicrosoftError(error: string): string {
  const lower = error.toLowerCase();
  const source = lower.includes("onedrive") || lower.includes("/drive")
    ? "OneDrive"
    : lower.includes("calendar")
      ? "Calendar"
      : "Microsoft data";

  if (lower.includes("403") || lower.includes("forbidden")) {
    return `${source} permission is unavailable (Microsoft Graph returned 403).`;
  }
  if (lower.includes("401") || lower.includes("unauthorized")) {
    return `${source} authorization is unavailable (Microsoft Graph returned 401).`;
  }
  if (lower.includes("404") || lower.includes("not found")) {
    return `${source} could not be found (Microsoft Graph returned 404).`;
  }
  return error.length > 180 ? `${error.slice(0, 177)}...` : error;
}

export default function DashboardClient({ meetings: initialMeetings, upcoming, historical: initialHistorical, upn, accessToken, isSubscribed, syncStates, loadErrors }: Props) {
  const router = useRouter();
  const [meetings, setMeetings] = useState(initialMeetings);
  useEffect(() => {
    const timer = setInterval(() => { void getAllMeetings(accessToken).then(setMeetings).catch(() => {}); }, 10000);
    return () => clearInterval(timer);
  }, [accessToken]);
  const [tab, setTab] = useState<Tab>("upcoming");
  const [showImport, setShowImport] = useState(false);
  const [historical, setHistorical] = useState<MeetingOut[]>(initialHistorical);
  const [shareModal, setShareModal] = useState<{ meetingId: string; title: string } | null>(null);
  const [unsubscribing, setUnsubscribing] = useState(false);

  async function handleOptOut() {
    if (!confirm("Turn off future Calendar and OneDrive processing? Existing meeting records will remain available.")) return;
    setUnsubscribing(true);
    try {
      await unsubscribeCurrentUser(accessToken);
      router.refresh();
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Could not turn off processing");
    } finally {
      setUnsubscribing(false);
    }
  }

  const upcomingEvents  = upcoming.filter((e) => e.status === "upcoming");
  const inProgressEvents = upcoming.filter((e) => e.status === "in_progress");
  const pipelineActive  = meetings.filter((m) => PIPELINE_STATES.includes(m.state));
  const pendingReview   = meetings.filter((m) => m.state === "awaiting_review");
  const oldMeetings     = meetings.filter((m) => m.state === "approved" || m.state === "sent");
  const cancelled       = meetings.filter((m) => m.state === "failed" || m.state === "cancelled");
  const persistedSyncErrors = syncStates
    .filter((state) => state.status === "failed")
    .map((state) => `${state.source === "onedrive" ? "OneDrive" : "Calendar"}: ${state.last_error ?? "Last sync failed"}`);
  // Prefer errors from this page load. Stored sync failures are a fallback and
  // must not duplicate the same Microsoft failure in the warning panel.
  const microsoftErrors = Array.from(new Set(
    (loadErrors.length > 0 ? loadErrors : persistedSyncErrors).map(conciseMicrosoftError),
  ));

  async function handleRequestAccess(meetingId: string) {
    try {
      await requestHistoricalAccess(meetingId, accessToken);
      setHistorical((prev) => prev.filter((m) => m.id !== meetingId));
      alert("Access granted — the meeting will now appear in your Old Meetings tab.");
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Could not grant access");
    }
  }

  const stats: { icon: string; num: number; label: string; color: string; tab: Tab }[] = [
    { icon: "📅", num: upcomingEvents.length,                  label: "Upcoming",         color: "bg-blue-50",   tab: "upcoming"     },
    { icon: "⚙️", num: inProgressEvents.length + pipelineActive.length, label: "In Progress", color: "bg-indigo-50", tab: "in_progress"  },
    { icon: "📋", num: pendingReview.length,                   label: "Awaiting Review",  color: "bg-amber-50",  tab: "review"       },
    { icon: "✅", num: oldMeetings.length,                     label: "Completed",        color: "bg-green-50",  tab: "old_meetings" },
  ];

  return (
    <main className="max-w-5xl mx-auto px-6 py-7">
      {microsoftErrors.length > 0 && (
        <div role="alert" className="mb-5 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <p className="font-semibold">Microsoft data is temporarily unavailable</p>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-xs">
            {microsoftErrors.map((error) => <li key={error}>{error}</li>)}
          </ul>
          <p className="mt-2 text-xs">No meetings are hidden as an empty result; try again after the permission or service issue is resolved.</p>
        </div>
      )}
      <div className="mb-6 flex items-start justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-bold text-[#003366]">Meeting Intelligence</h1>
          <p className="text-[#6b7280] text-[13.5px] mt-0.5">
            Review and approve AI-extracted meeting notes before they are emailed to participants.
          </p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          {isSubscribed && (
            <button
              type="button"
              onClick={handleOptOut}
              disabled={unsubscribing}
              title="Stop future Calendar and OneDrive processing; keep existing records"
              className="inline-flex items-center gap-2 rounded-md border border-[#003366] bg-white px-3 py-2 text-[13px] font-semibold text-[#003366] transition-colors hover:bg-blue-50 disabled:opacity-50"
            >
              <Power size={14} /> {unsubscribing ? "Turning off..." : "Opt out"}
            </button>
          )}
          <button
            type="button"
            onClick={() => isSubscribed && setShowImport(true)}
            disabled={!isSubscribed}
            title={isSubscribed ? "Process a past OneDrive recording" : "Opt in to process Calendar and OneDrive recordings"}
            className="inline-flex items-center gap-2 rounded-md bg-[#003366] px-4 py-2 text-[13px] font-semibold text-white transition-colors hover:bg-[#0a4a8c] disabled:cursor-not-allowed disabled:opacity-45"
          >
            <Upload size={15} /> {isSubscribed ? "Process Past Recording" : "Opt in to process recordings"}
          </button>
        </div>
      </div>

      {showImport && <ImportModal upn={accessToken} onClose={() => setShowImport(false)} />}

      <RecordingJobs token={accessToken} onChanged={async () => setMeetings(await getAllMeetings(accessToken))} />

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-7">
        {stats.map((s) => (
          <button
            key={s.label}
            type="button"
            onClick={() => setTab(s.tab)}
            className={`bg-white rounded-lg border shadow-sm p-4 flex items-center gap-3 text-left transition-all hover:shadow-md hover:-translate-y-0.5 ${
              tab === s.tab ? "border-[#003366]" : "border-[#dde1e8] hover:border-[#003366]"
            }`}
          >
            <div className={`w-10 h-10 ${s.color} rounded-lg flex items-center justify-center text-lg shrink-0`}>
              {s.icon}
            </div>
            <div>
              <div className="text-[22px] font-bold text-[#003366] leading-none">{s.num}</div>
              <div className="text-[12px] text-[#6b7280] mt-0.5">{s.label}</div>
            </div>
          </button>
        ))}
      </div>

      {/* Tabs */}
      <div className="flex flex-wrap border-b-2 border-[#dde1e8] mb-6 gap-0">
        {([
          { id: "upcoming"    as Tab, label: "Upcoming Meetings",         count: upcomingEvents.length                          },
          { id: "in_progress" as Tab, label: "In Progress",               count: inProgressEvents.length + pipelineActive.length },
          { id: "review"      as Tab, label: "Awaiting Review",           count: pendingReview.length                           },
          { id: "old_meetings"as Tab, label: "Old Meetings",               count: null                                          },
          { id: "historical"  as Tab, label: "Historical Access",         count: historical.length || null                     },
          { id: "cancelled"   as Tab, label: "Failed / Cancelled",                 count: cancelled.length || null                      },
        ]).map(({ id, label, count }) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`px-4 py-2.5 text-[13px] font-medium border-b-2 -mb-0.5 transition-colors whitespace-nowrap ${
              tab === id
                ? "text-[#003366] border-[#C9A52C] font-semibold"
                : "text-[#6b7280] border-transparent hover:text-[#003366]"
            }`}
          >
            {label}
            {count !== null && count > 0 && (
              <span className="ml-1.5 bg-[#C9A52C] text-[#003366] text-[11px] font-bold px-1.5 py-0.5 rounded-full">
                {count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Upcoming Meetings */}
      {tab === "upcoming" && (
        upcomingEvents.length === 0
          ? <EmptyState
              icon="📅"
              title={isSubscribed ? "No upcoming meetings" : "Calendar processing is off"}
              sub={isSubscribed
                ? "No Teams meetings scheduled in the next 7 days."
                : "Opt in above to let Meeting Intelligence check your Outlook calendar and OneDrive recordings."}
            />
          : <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {upcomingEvents.map((ev) => <CalendarCard key={ev.event_id} event={ev} />)}
            </div>
      )}

      {/* In Progress */}
      {tab === "in_progress" && (
        inProgressEvents.length === 0 && pipelineActive.length === 0
          ? <EmptyState icon="⚙️" title="Nothing in progress" sub="Meetings currently happening or being processed will appear here." />
          : <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {inProgressEvents.map((ev) => <CalendarCard key={ev.event_id} event={ev} inProgress />)}
              {pipelineActive.map((m) => <MeetingCard key={m.id} meeting={m} />)}
            </div>
      )}

      {/* Awaiting Review */}
      {tab === "review" && (
        pendingReview.length === 0
          ? <EmptyState icon="📭" title="All caught up" sub="No meetings are awaiting your review." />
          : <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {pendingReview.map((m) => <MeetingCard key={m.id} meeting={m} />)}
            </div>
      )}

      {/* Old Meetings */}
      {tab === "old_meetings" && (
        oldMeetings.length === 0
          ? <EmptyState icon="📂" title="No completed meetings yet" sub="Approved and sent meetings will appear here." />
          : <div className="bg-white rounded-lg border border-[#dde1e8] shadow-sm overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr>
                    {["Meeting", "Date", "Organiser", "Participants", "Status", ""].map((h) => (
                      <th key={h} className="bg-[#003366] text-white text-xs font-semibold px-4 py-2.5 text-left border border-white/10">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {oldMeetings.map((m, i) => (
                    <tr key={m.id} className={`${i % 2 === 1 ? "bg-[#f8fafc]" : ""} hover:bg-blue-50/30 transition-colors`}>
                      <td className="px-4 py-2.5 border border-[#dde1e8] font-medium">
                        <Link href={`/meetings/${m.id}`} className="hover:text-[#003366] hover:underline">
                          {m.title ?? "Untitled Meeting"}
                        </Link>
                      </td>
                      <td className="px-4 py-2.5 border border-[#dde1e8] text-[#6b7280] text-[12.5px] whitespace-nowrap">
                        {<LocalDateTime value={m.recorded_at ?? m.extracted_json?.meeting_time} />}
                      </td>
                      <td className="px-4 py-2.5 border border-[#dde1e8] text-[#6b7280] text-[12.5px]">
                        {formatUpn(m.organizer_upn) || "—"}
                      </td>
                      <td className="px-4 py-2.5 border border-[#dde1e8] text-[#6b7280] text-[12.5px] text-center">
                        {m.extracted_json?.attendees?.length ?? "—"}
                      </td>
                      <td className="px-4 py-2.5 border border-[#dde1e8]">
                        <StateBadge state={m.state} />
                      </td>
                      <td className="px-4 py-2.5 border border-[#dde1e8]">
                        <div className="flex items-center gap-3 whitespace-nowrap">
                          <Link
                            href={`/meetings/${m.id}`}
                            className="text-[11.5px] font-semibold text-[#003366] hover:text-[#C9A52C] hover:underline"
                          >
                            View notes
                          </Link>
                          {m.organizer_upn === upn && (
                            <button
                              type="button"
                              onClick={() => setShareModal({ meetingId: m.id, title: m.title ?? "Untitled Meeting" })}
                              className="inline-flex items-center gap-1 text-[11.5px] text-[#003366] hover:text-[#C9A52C] transition-colors"
                              title="Share transcript"
                            >
                              <Share2 size={13} /> Share
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
      )}

      {/* Historical Access */}
      {tab === "historical" && (
        historical.length === 0
          ? <EmptyState icon="🔓" title="No historical meetings found" sub="Meetings you attended before registering will appear here. Once you request access, they move to Old Meetings." />
          : <div className="bg-white rounded-lg border border-[#dde1e8] shadow-sm overflow-hidden">
              <div className="bg-amber-50 border-b border-amber-200 px-4 py-2.5 flex items-center gap-2 text-[12.5px] text-amber-700">
                <History size={13} />
                These meetings were processed before you registered. Click <strong>Request Access</strong> to unlock any you attended.
              </div>
              <table className="w-full text-sm">
                <thead>
                  <tr>
                    {["Meeting", "Date", "Organiser", "Action"].map((h) => (
                      <th key={h} className="bg-[#003366] text-white text-xs font-semibold px-4 py-2.5 text-left border border-white/10">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {historical.map((m, i) => (
                    <tr key={m.id} className={`${i % 2 === 1 ? "bg-[#f8fafc]" : ""} hover:bg-blue-50/30 transition-colors`}>
                      <td className="px-4 py-2.5 border border-[#dde1e8] font-medium text-[13px]">
                        <span className="flex items-center gap-1.5 text-[#6b7280]">
                          <Lock size={11} className="shrink-0" />
                          {m.title ?? "Untitled Meeting"}
                        </span>
                      </td>
                      <td className="px-4 py-2.5 border border-[#dde1e8] text-[#6b7280] text-[12.5px] whitespace-nowrap">
                        {<LocalDateTime value={m.recorded_at ?? m.extracted_json?.meeting_time} />}
                      </td>
                      <td className="px-4 py-2.5 border border-[#dde1e8] text-[#6b7280] text-[12.5px]">
                        {formatUpn(m.organizer_upn) || "—"}
                      </td>
                      <td className="px-4 py-2.5 border border-[#dde1e8]">
                        <button
                          type="button"
                          onClick={() => handleRequestAccess(m.id)}
                          className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-[#003366] bg-blue-50 hover:bg-blue-100 px-3 py-1 rounded-md transition-colors"
                        >
                          <History size={12} /> Request Access
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
      )}

      {/* Cancelled */}
      {tab === "cancelled" && (
        cancelled.length === 0
          ? <EmptyState icon="🚫" title="No failed or cancelled recordings" sub="Failed and explicitly cancelled recordings appear here." />
          : <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {cancelled.map((m) => <MeetingCard key={m.id} meeting={m} />)}
            </div>
      )}

      {/* Share modal */}
      {shareModal && (
        <ShareModal
          meetingId={shareModal.meetingId}
          meetingTitle={shareModal.title}
          callerUpn={accessToken}
          onClose={() => setShareModal(null)}
        />
      )}
    </main>
  );
}

/** Card component for a meeting that has been imported into the processing pipeline. */
function MeetingCard({ meeting: m }: { meeting: MeetingOut }) {
  const isProcessing = PIPELINE_STATES.includes(m.state);
  return (
    <Link href={`/meetings/${m.id}`} className="group block bg-white rounded-lg border border-[#dde1e8] shadow-sm hover:border-[#003366] hover:shadow-md transition-all overflow-hidden">
      <div className="bg-[#003366] border-b-[3px] border-[#C9A52C] px-4 py-3.5">
        <p className="text-white text-[13.5px] font-semibold leading-snug line-clamp-2">
          {m.title ?? "Untitled Meeting"}
        </p>
      </div>
      <div className="px-4 py-3.5">
        <div className="flex flex-col gap-1.5 mb-3">
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            <span className="flex items-center gap-1 text-[#6b7280] text-[12.5px]">
              <Calendar size={12} className="shrink-0" /> {<LocalDateTime value={m.recorded_at ?? m.extracted_json?.meeting_time} />}
            </span>
            <span className="flex items-center gap-1 text-[#6b7280] text-[12.5px]">
              <Users size={12} className="shrink-0" /> {m.extracted_json?.attendees?.length ?? 0} participants
            </span>
          </div>
          {m.organizer_upn && (
            <span className="flex items-center gap-1 text-[#6b7280] text-[12.5px]">
              <Mic size={12} className="shrink-0" /> Organised by: {formatUpn(m.organizer_upn)}
            </span>
          )}
        </div>
        <div className="flex items-center justify-between pt-2.5 border-t border-[#dde1e8]">
          <StateBadge state={m.state} />
          <span className="text-[#003366] text-[12.5px] font-semibold flex items-center gap-0.5 group-hover:gap-1.5 transition-all">
            {isProcessing ? "View Progress" : m.state === "failed" ? "View Error" : "Review"} <ChevronRight size={14} />
          </span>
        </div>
      </div>
    </Link>
  );
}

/** Card component for a calendar event not yet recorded/imported.
 *  Shows a pulsing "Live" badge when the meeting is currently in progress. */
function CalendarCard({ event: ev, inProgress }: { event: CalendarEvent; inProgress?: boolean }) {
  const zone = useUserTimeZone();
  const { dateLabel, timeRange, duration } = zone ? formatEventTime(ev.start, ev.end, zone) : { dateLabel: "—", timeRange: "—", duration: "" };
  return (
    <div className={`bg-white rounded-lg border shadow-sm overflow-hidden hover:shadow-md transition-all ${inProgress ? "border-indigo-300 hover:border-indigo-500" : "border-[#dde1e8] hover:border-[#003366]"}`}>
      <div className={`border-b-[3px] border-[#C9A52C] px-4 py-3.5 flex items-start justify-between gap-2 ${inProgress ? "bg-indigo-700" : "bg-[#003366]"}`}>
        <p className="text-white text-[13.5px] font-semibold leading-snug line-clamp-2 flex-1">
          {ev.subject}
        </p>
        <span className={`shrink-0 text-[10.5px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wide ${inProgress ? "bg-green-400 text-green-900 animate-pulse" : "bg-[#C9A52C] text-[#003366]"}`}>
          {inProgress ? "Live" : dateLabel}
        </span>
      </div>
      <div className="px-4 py-3.5">
        <div className="flex flex-col gap-1.5 mb-3">
          <span className="flex items-center gap-1.5 text-[#6b7280] text-[12.5px]">
            <Calendar size={12} className="shrink-0" />
            {dateLabel} · {timeRange}
            {duration && <span className="text-[#9ca3af] ml-1">({duration})</span>}
          </span>
          <span className="flex items-center gap-1.5 text-[#6b7280] text-[12.5px]">
            <Users size={12} className="shrink-0" />
            {ev.attendee_count} participant{ev.attendee_count !== 1 ? "s" : ""}
          </span>
          {ev.organizer_name && (
            <span className="flex items-center gap-1.5 text-[#6b7280] text-[12.5px]">
              <Mic size={12} className="shrink-0" /> Organised by: {ev.organizer_name}
            </span>
          )}
        </div>
        <div className="flex items-center justify-between pt-2.5 border-t border-[#dde1e8]">
          <span className="inline-flex items-center gap-1.5 bg-blue-50 text-blue-700 text-[11.5px] font-semibold px-2.5 py-0.5 rounded-full">
            <Video size={11} /> Teams
          </span>
          <span className="text-[#9ca3af] text-[11.5px]">{inProgress ? "Meeting in progress" : "Recording pending"}</span>
        </div>
      </div>
    </div>
  );
}

/** Full-tab empty state placeholder shown when a tab has no items to display. */
function EmptyState({ icon, title, sub }: { icon: string; title: string; sub: string }) {
  return (
    <div className="text-center py-16 text-[#6b7280]">
      <div className="text-4xl mb-3">{icon}</div>
      <h3 className="text-[15px] font-semibold text-[#1a1a2e] mb-1">{title}</h3>
      <p className="text-[13.5px]">{sub}</p>
    </div>
  );
}

/** Share dialog — organiser can share a transcript with any @taxconsulting.co.za address. */
function ShareModal({
  meetingId,
  meetingTitle,
  callerUpn,
  onClose,
}: {
  meetingId: string;
  meetingTitle: string;
  callerUpn: string;
  onClose: () => void;
}) {
  const [recipient, setRecipient] = useState("");
  const [status, setStatus] = useState<"idle" | "loading" | "success" | "error">("idle");
  const [message, setMessage] = useState("");

  async function handleShare() {
    if (!recipient.endsWith("@taxconsulting.co.za")) {
      setStatus("error");
      setMessage("Only @taxconsulting.co.za addresses are allowed.");
      return;
    }
    setStatus("loading");
    try {
      const res = await shareMeeting(meetingId, recipient, callerUpn);
      setStatus("success");
      setMessage(res.message);
    } catch (e: unknown) {
      setStatus("error");
      setMessage(e instanceof Error ? e.message : "Share failed");
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md overflow-hidden">
        <div className="bg-[#003366] border-b-4 border-[#C9A52C] px-6 py-4">
          <h2 className="text-white font-semibold text-[15px] flex items-center gap-2">
            <Share2 size={16} /> Share Transcript
          </h2>
          <p className="text-white/60 text-[12px] mt-0.5 truncate">{meetingTitle}</p>
        </div>
        <div className="px-6 py-5 flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label className="text-[12.5px] font-medium text-[#374151]">Recipient email</label>
            <input
              type="email"
              placeholder="colleague@taxconsulting.co.za"
              value={recipient}
              onChange={(e) => setRecipient(e.target.value)}
              className="w-full border border-[#dde1e8] rounded-md px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-[#003366]"
            />
            <p className="text-[11.5px] text-[#9ca3af]">Only @taxconsulting.co.za addresses are accepted.</p>
          </div>
          {status === "error" && (
            <p className="text-[12.5px] text-red-600 bg-red-50 border border-red-200 rounded-md px-3 py-2">{message}</p>
          )}
          {status === "success" && (
            <p className="text-[12.5px] text-green-700 bg-green-50 border border-green-200 rounded-md px-3 py-2">{message}</p>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className="px-4 py-2 text-[13px] text-[#6b7280] hover:text-[#1a1a2e]">
              {status === "success" ? "Close" : "Cancel"}
            </button>
            {status !== "success" && (
              <button
                type="button"
                onClick={handleShare}
                disabled={!recipient || status === "loading"}
                className="px-4 py-2 text-[13px] font-semibold bg-[#003366] text-white rounded-md hover:bg-[#0a4a8c] disabled:opacity-50"
              >
                {status === "loading" ? "Sharing…" : "Share"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
