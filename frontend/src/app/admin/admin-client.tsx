"use client";
import { Fragment, useRef, useState } from "react";
import Link from "next/link";
import { UserPlus, Trash2, Shield, Pencil, ChevronDown, Loader2 } from "lucide-react";
import { cleanupAdminJob, decideMeetingEditAccess, decideRecordingProcessing, getAdminMeetings, getAdminUserSyncStatus, getBusinessUnits, getRecordingJobs, getRegisteredUsers, registerUser, removeUser, reprocessRecordingJob, revokeAdminMeetingAccess, updateUser } from "@/lib/api";
import type { RegisteredUser, BusinessUnit, RecordingJobOut, AdminAccessRequest, AdminMeetingOut, SyncState } from "@/lib/types";
import { JobControls } from "@/components/recording-jobs";
import StateBadge from "@/components/state-badge";

interface Props {
  initialRequests: AdminAccessRequest[];
  callerUpn: string;
  accessToken: string;
}

export default function AdminClient({ initialRequests, callerUpn, accessToken }: Props) {
  const [users, setUsers] = useState<RegisteredUser[]>([]);
  const [businessUnits, setBusinessUnits] = useState<BusinessUnit[]>([]);
  const [showAdd, setShowAdd] = useState(false);
  const [editUser, setEditUser] = useState<RegisteredUser | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<RecordingJobOut[]>([]);
  const [meetings, setMeetings] = useState<AdminMeetingOut[]>([]);
  const [requests, setRequests] = useState(initialRequests);
  const [loaded, setLoaded] = useState({ meetings: false, jobs: false, users: false });
  const [loading, setLoading] = useState<string | null>(null);
  const [syncOpen, setSyncOpen] = useState<string | null>(null);
  const [syncByUser, setSyncByUser] = useState<Record<string, SyncState[]>>({});
  const [syncLoading, setSyncLoading] = useState<string | null>(null);
  const [syncErrors, setSyncErrors] = useState<Record<string, string>>({});
  const [busyJob, setBusyJob] = useState<{ id: string; action: "reprocess" | "cleanup" } | null>(null);
  const jobsInFlight = useRef(new Set<string>());

  async function loadSection(section: "meetings" | "jobs" | "users") {
    if (loaded[section]) return;
    setLoading(section);
    setError(null);
    try {
      if (section === "meetings") setMeetings(await getAdminMeetings(accessToken));
      if (section === "jobs") setJobs(await getRecordingJobs(accessToken));
      if (section === "users") {
        const [nextUsers, nextUnits] = await Promise.all([
          getRegisteredUsers(accessToken), getBusinessUnits(accessToken),
        ]);
        setUsers(nextUsers);
        setBusinessUnits(nextUnits);
      }
      setLoaded((current) => ({ ...current, [section]: true }));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : `Failed to load ${section}`);
    } finally {
      setLoading((current) => current === section ? null : current);
    }
  }

  async function toggleSyncDiagnostics(upn: string) {
    if (syncOpen === upn) {
      setSyncOpen(null);
      return;
    }
    setSyncOpen(upn);
    if (syncByUser[upn]) return;
    setSyncLoading(upn);
    setSyncErrors((current) => ({ ...current, [upn]: "" }));
    try {
      const states = await getAdminUserSyncStatus(upn, accessToken);
      setSyncByUser((current) => ({ ...current, [upn]: states }));
    } catch (e: unknown) {
      setSyncErrors((current) => ({
        ...current, [upn]: e instanceof Error ? e.message : "Sync diagnostics unavailable",
      }));
    } finally {
      setSyncLoading((current) => current === upn ? null : current);
    }
  }

  async function handleAccessDecision(request: AdminAccessRequest, approved: boolean) {
    if (!request.meeting_id || !request.requester_upn) return;
    if (!confirm(`${approved ? "Approve" : "Reject"} ${request.request_type} access for ${request.requester_upn}?`)) return;
    setError(null);
    try {
      await decideMeetingEditAccess(request.meeting_id, request.requester_upn, approved, accessToken);
      setRequests((current) => current.map((entry) => entry.id === request.id
        ? { ...entry, status: approved ? "approved" : "denied" }
        : entry));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to decide access request");
    }
  }

  async function handleProcessingDecision(request: AdminAccessRequest, approved: boolean) {
    if (!confirm(`${approved ? "Approve" : "Reject"} processing request for ${request.meeting}?`)) return;
    setError(null);
    try {
      await decideRecordingProcessing(request.id, approved, accessToken);
      setRequests((current) => current.map((entry) => entry.id === request.id
        ? { ...entry, status: approved ? "approved" : "denied", can_approve: false }
        : entry));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : `Failed to ${approved ? "approve" : "reject"} processing request`);
    }
  }

  async function handleRevoke(meetingId: string, userUpn: string, accessType: "view" | "edit") {
    if (!confirm(`Revoke ${accessType} access for ${userUpn}?`)) return;
    setError(null);
    try {
      await revokeAdminMeetingAccess(meetingId, userUpn, accessType, accessToken);
      setMeetings((current) => current.map((meeting) => meeting.id !== meetingId ? meeting : {
        ...meeting,
        access: accessType === "view"
          ? meeting.access.filter((entry) => entry.user_upn !== userUpn)
          : meeting.access.map((entry) => entry.user_upn === userUpn ? { ...entry, edit_access: false } : entry),
      }));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : `Failed to revoke ${accessType} access`);
    }
  }

  async function refreshJobs() {
    setJobs(await getRecordingJobs(accessToken));
  }

  async function handleReprocess(job: RecordingJobOut) {
    if (jobsInFlight.current.has(job.job_id)) return;
    jobsInFlight.current.add(job.job_id);
    setBusyJob({ id: job.job_id, action: "reprocess" });
    setError(null);
    try {
      await reprocessRecordingJob(job.job_id, accessToken);
      await refreshJobs();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to reprocess recording");
    } finally {
      jobsInFlight.current.delete(job.job_id);
      setBusyJob((current) => current?.id === job.job_id ? null : current);
    }
  }

  async function handleCleanup(job: RecordingJobOut) {
    if (jobsInFlight.current.has(job.job_id)) return;
    if (!confirm(`Remove this ${job.status} operational job record? Saved meeting content will be kept.`)) return;
    jobsInFlight.current.add(job.job_id);
    setBusyJob({ id: job.job_id, action: "cleanup" });
    setError(null);
    try {
      await cleanupAdminJob(job.job_id, accessToken);
      await refreshJobs();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to clean up job record");
    } finally {
      jobsInFlight.current.delete(job.job_id);
      setBusyJob((current) => current?.id === job.job_id ? null : current);
    }
  }

  async function handleAdd(form: AddUserForm) {
    setError(null);
    try {
      const created = await registerUser(
        form.upn,
        {
          upn: form.upn,
          display_name: form.display_name || undefined,
          business_unit_id: form.business_unit_id ?? undefined,
          is_admin: form.is_admin,
        },
        accessToken,
      );
      setUsers((prev) => [...prev, created]);
      setShowAdd(false);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to register user");
    }
  }

  async function handleUpdate(targetUpn: string, payload: { display_name?: string; business_unit_id?: number; is_admin?: boolean }) {
    setError(null);
    try {
      const updated = await updateUser(targetUpn, payload, accessToken);
      setUsers((prev) => prev.map((u) => (u.upn === targetUpn ? updated : u)));
      setEditUser(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to update user");
    }
  }

  async function handleRemove(targetUpn: string) {
    if (!confirm(`Remove ${targetUpn} from the platform?`)) return;
    setError(null);
    try {
      await removeUser(targetUpn, accessToken);
      setUsers((prev) => prev.filter((u) => u.upn !== targetUpn));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to remove user");
    }
  }

  return (
    <main className="max-w-5xl mx-auto px-6 py-7">
      <div className="mb-6">
        <div>
          <h1 className="text-[22px] font-bold text-[#003366]">Administration</h1>
          <p className="text-[#6b7280] text-[13.5px] mt-0.5">
            Manage meetings, processing, access, and registered users.
          </p>
        </div>
      </div>

      <details onToggle={(event) => event.currentTarget.open && void loadSection("meetings")} className="group mb-3 bg-white rounded-lg border border-[#dde1e8] shadow-sm overflow-hidden">
        <SectionHeader id="admin-meetings" label="Meetings" count={loaded.meetings ? meetings.length : undefined} />
        <div className="px-4 pb-3"><p className="text-xs text-[#6b7280]">Operational metadata and Admin meeting-content access across users.</p></div>
        {loading === "meetings" && <Loading />}
        {loaded.meetings && <>
        <div className="overflow-x-auto"><table className="w-full text-xs"><thead><tr>{["Meeting", "Organizer / owner", "Recording", "Meeting", "Job", "Request"].map((label) => <th key={label} className="bg-[#003366] text-white px-3 py-2 text-left">{label}</th>)}</tr></thead>
          <tbody>{meetings.map((meeting) => <tr key={meeting.id} className="border-t align-top"><td className="px-3 py-2 font-medium"><Link href={`/meetings/${meeting.id}`} className="text-[#003366] underline-offset-2 hover:underline">{meeting.title ?? "Untitled meeting"}</Link></td><td className="px-3 py-2">{meeting.organizer_upn ?? "Unknown"}{meeting.owner_upn && meeting.owner_upn !== meeting.organizer_upn ? ` / ${meeting.owner_upn}` : ""}<AccessList meeting={meeting} onRevoke={handleRevoke} /></td><td className="px-3 py-2">{meeting.recording_status}</td><td className="px-3 py-2"><StatusText value={meeting.meeting_status} /></td><td className="px-3 py-2">{meeting.job_status ? <StatusText value={meeting.job_status} /> : "—"}</td><td className="px-3 py-2">{meeting.request_status ? <StatusText value={meeting.request_status} /> : "—"}</td></tr>)}</tbody>
        </table></div>
        {meetings.length === 0 && <p className="p-4 text-sm text-[#9ca3af]">No meetings.</p>}
        </>}
      </details>

      <details onToggle={(event) => event.currentTarget.open && void loadSection("jobs")} className="group mb-3 bg-white rounded-lg border border-[#dde1e8] shadow-sm overflow-hidden">
        <SectionHeader id="admin-jobs" label="Processing Jobs" count={loaded.jobs ? jobs.length : undefined} />
        <div className="px-4 pb-4">
        <p className="text-xs text-[#6b7280] mb-3">Jobs across all registered users.</p>
        {loading === "jobs" && <Loading />}
        {loaded.jobs && <>
        {jobs.length === 0 && <p className="text-sm text-[#9ca3af]">No processing jobs.</p>}
        {jobs.map((job) => (
          <div key={job.job_id} className="border-t py-3 text-sm space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-medium">{job.title}</span>
              <StateBadge state={job.processing_status} />
            </div>
            <p className="text-xs text-[#6b7280]">Owner: {job.owner_upn ?? "Unknown"}</p>
            {job.is_stuck && <p className="text-xs font-semibold text-amber-800">Worker lease appears stuck.</p>}
            {job.error && <p className="text-xs text-red-700">{job.error}</p>}
            <div className="flex items-center gap-3">
              <JobControls job={job} token={accessToken} onChanged={refreshJobs} />
              {job.can_reprocess && <button type="button" disabled={busyJob?.id === job.job_id} onClick={() => handleReprocess(job)} className="inline-flex items-center gap-1 text-xs font-semibold text-blue-800 disabled:cursor-not-allowed disabled:opacity-50">{busyJob?.id === job.job_id && busyJob.action === "reprocess" && <Loader2 size={12} className="animate-spin" />}{busyJob?.id === job.job_id && busyJob.action === "reprocess" ? "Reprocessing…" : "Reprocess"}</button>}
              {(job.status === "failed" || job.status === "cancelled") && (
                <button type="button" disabled={busyJob?.id === job.job_id} onClick={() => void handleCleanup(job)} className="inline-flex items-center gap-1 text-xs font-semibold text-red-700 disabled:cursor-not-allowed disabled:opacity-50">{busyJob?.id === job.job_id && busyJob.action === "cleanup" && <Loader2 size={12} className="animate-spin" />}{busyJob?.id === job.job_id && busyJob.action === "cleanup" ? "Cleaning up…" : "Clean up"}</button>
              )}
            </div>
          </div>
        ))}
        </>}
        </div>
      </details>

      <details open className="group mb-3 bg-white rounded-lg border border-[#dde1e8] shadow-sm overflow-hidden">
        <SectionHeader id="admin-requests" label="Access Requests" count={requests.length} />
        <div className="px-4 pb-4">
        <p className="text-xs text-[#6b7280] mb-3">Processing, view, and edit requests across all users. Admins have full-control authority through the available approval workflows.</p>
        {requests.length === 0 && <p className="text-sm text-[#9ca3af]">No access requests.</p>}
        {requests.map((request) => (
          <div key={request.id} className="border-t py-3 text-sm">
            <div className="flex flex-wrap items-center gap-2"><span className="font-medium">{request.meeting}</span><StatusText value={request.status} /></div>
            <p className="text-xs text-[#6b7280]">{request.request_type.replace(/^./, (letter) => letter.toUpperCase())} · Requested by {request.requester_name ?? request.requester_upn ?? "Former user"} · Owner / organizer: {request.owner_upn ?? request.organizer_upn ?? "Unknown"}</p>
            {request.request_type === "processing" && request.status === "pending" && (
              <div className="mt-2 flex gap-3">
                {request.can_approve && <button type="button" onClick={() => handleProcessingDecision(request, true)} className="text-xs font-semibold text-emerald-700">Approve</button>}
                <button type="button" onClick={() => handleProcessingDecision(request, false)} className="text-xs font-semibold text-red-700">Reject</button>
              </div>
            )}
            {request.status === "pending" && request.request_type !== "processing" && request.meeting_id && request.requester_upn && (
              <div className="mt-2 flex gap-3">
                <button type="button" onClick={() => handleAccessDecision(request, true)} className="text-xs font-semibold text-emerald-700">Approve</button>
                <button type="button" onClick={() => handleAccessDecision(request, false)} className="text-xs font-semibold text-red-700">Reject</button>
              </div>
            )}
          </div>
        ))}
        </div>
      </details>

      {error && (
        <div className="mb-4 bg-red-50 border border-red-200 text-red-700 text-[13px] px-4 py-3 rounded-lg">
          {error}
        </div>
      )}

      <details onToggle={(event) => event.currentTarget.open && void loadSection("users")} className="group bg-white rounded-lg border border-[#dde1e8] shadow-sm overflow-hidden">
        <SectionHeader id="admin-users" label="Users" count={loaded.users ? users.length : undefined} />
        <div className="px-4 pb-3 flex justify-end">
          <button type="button" onClick={() => setShowAdd(true)} disabled={!loaded.users}
            className="inline-flex items-center gap-2 bg-[#003366] hover:bg-[#0a4a8c] disabled:opacity-50 text-white text-[13px] font-semibold px-4 py-2 rounded-md transition-colors">
            <UserPlus size={15} /> Register User
          </button>
        </div>
        {loading === "users" && <Loading />}
        {loaded.users && <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr>
              {["Name / Email", "Business Unit", "Role", "Subscribed", "Registered", "Actions"].map((h) => (
                <th key={h} className="bg-[#003366] text-white text-xs font-semibold px-4 py-2.5 text-left border border-white/10">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {users.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-[#9ca3af] text-[13px]">
                  No users registered yet. Add one using the button above.
                </td>
              </tr>
            )}
            {users.map((u, i) => (
              <Fragment key={u.upn}>
              <tr className={`${i % 2 === 1 ? "bg-[#f8fafc]" : ""} hover:bg-blue-50/30 transition-colors`}>
                <td className="px-4 py-2.5 border border-[#dde1e8]">
                  <div className="font-medium text-[#1a1a2e] text-[13px]">
                    {u.display_name ?? formatUpn(u.upn)}
                  </div>
                  <div className="text-[11.5px] text-[#6b7280]">{u.upn}</div>
                </td>
                <td className="px-4 py-2.5 border border-[#dde1e8] text-[#6b7280] text-[12.5px]">
                  {u.business_unit_name ?? <span className="text-[#d1d5db] italic">Unassigned</span>}
                </td>
                <td className="px-4 py-2.5 border border-[#dde1e8]">
                  {u.is_admin ? (
                    <span className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full">
                      <Shield size={11} /> Admin
                    </span>
                  ) : (
                    <span className="text-[12px] text-[#6b7280]">Member</span>
                  )}
                </td>
                <td className="px-4 py-2.5 border border-[#dde1e8] text-[12px]">
                  <span className={u.is_subscribed ? "text-emerald-700" : "text-[#6b7280]"}>
                    {u.is_subscribed ? "Subscribed" : "Not subscribed"}
                  </span>
                </td>
                <td className="px-4 py-2.5 border border-[#dde1e8] text-[#6b7280] text-[12px] whitespace-nowrap">
                  {new Date(u.registered_at).toLocaleDateString("en-ZA", { day: "2-digit", month: "short", year: "numeric" })}
                </td>
                <td className="px-4 py-2.5 border border-[#dde1e8]">
                  <div className="flex items-center gap-2">
                    <button type="button" onClick={() => void toggleSyncDiagnostics(u.upn)}
                      aria-expanded={syncOpen === u.upn}
                      className="text-[11px] font-semibold text-[#003366] hover:underline">
                      Sync
                    </button>
                    <button
                      type="button"
                      onClick={() => setEditUser(u)}
                      className="text-[#6b7280] hover:text-[#003366] transition-colors"
                      title="Edit"
                    >
                      <Pencil size={14} />
                    </button>
                    {u.upn !== callerUpn && (
                      <button
                        type="button"
                        onClick={() => handleRemove(u.upn)}
                        className="text-[#6b7280] hover:text-red-600 transition-colors"
                        title="Remove"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
              {syncOpen === u.upn && (
                <tr>
                  <td colSpan={6} className="border border-[#dde1e8] bg-slate-50 px-4 py-3">
                    {syncLoading === u.upn
                      ? <p role="status" className="text-xs text-[#6b7280]">Loading sync diagnostics…</p>
                      : syncErrors[u.upn]
                        ? <p className="text-xs text-red-700">{syncErrors[u.upn]}</p>
                        : <SyncDiagnostics states={syncByUser[u.upn] ?? []} />}
                  </td>
                </tr>
              )}
              </Fragment>
            ))}
          </tbody>
        </table>
        </div>}
      </details>

      {/* Add User dialog */}
      {showAdd && (
        <AddUserDialog
          businessUnits={businessUnits}
          onSave={handleAdd}
          onClose={() => setShowAdd(false)}
        />
      )}

      {/* Edit User dialog */}
      {editUser && (
        <EditUserDialog
          user={editUser}
          businessUnits={businessUnits}
          onSave={(payload) => handleUpdate(editUser.upn, payload)}
          onClose={() => setEditUser(null)}
        />
      )}
    </main>
  );
}

function SectionHeader({ id, label, count }: { id: string; label: string; count?: number }) {
  return (
    <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 [&::-webkit-details-marker]:hidden">
      <h2 id={id} className="text-sm font-semibold text-[#003366]">
        {label}{count !== undefined && <span className="ml-2 font-normal text-[#6b7280]">({count})</span>}
      </h2>
      <ChevronDown size={16} aria-hidden="true" className="text-[#6b7280] transition-transform group-open:rotate-180" />
    </summary>
  );
}

function Loading() {
  return <p role="status" className="px-4 pb-4 text-sm text-[#6b7280]">Loading…</p>;
}

function SyncDiagnostics({ states }: { states: SyncState[] }) {
  const bySource = new Map(states.map((state) => [state.source, state]));
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {["calendar", "onedrive"].map((source) => {
        const state = bySource.get(source);
        return (
          <div key={source} className="rounded border border-[#dde1e8] bg-white p-3 text-xs">
            <div className="flex items-center justify-between gap-2">
              <span className="font-semibold text-[#003366]">{source === "calendar" ? "Calendar" : "OneDrive"}</span>
              <StatusText value={state?.status ?? "unavailable"} />
            </div>
            <p className="mt-2 text-[#6b7280]">Last success: {formatSyncTime(state?.last_succeeded_at)}</p>
            <p className="text-[#6b7280]">Last attempt: {formatSyncTime(state?.last_attempted_at)}</p>
            {state?.last_error && <p className="mt-1 break-words text-red-700">Last error: {state.last_error}</p>}
          </div>
        );
      })}
    </div>
  );
}

function formatSyncTime(value: string | null | undefined) {
  return value ? new Date(value).toLocaleString("en-ZA") : "Unavailable";
}

function StatusText({ value }: { value: string }) {
  return <span className="inline-flex rounded-full bg-slate-100 px-2 py-0.5 font-medium text-slate-700">{value.replaceAll("_", " ")}</span>;
}

function AccessList({ meeting, onRevoke }: {
  meeting: AdminMeetingOut;
  onRevoke: (meetingId: string, userUpn: string, accessType: "view" | "edit") => void;
}) {
  return (
    <div className="mt-2 space-y-1 border-t pt-2">
      {meeting.access.length === 0 && <span className="text-[#9ca3af]">No current access</span>}
      {meeting.access.map((entry) => (
        <div key={entry.user_upn} className="flex flex-wrap items-center gap-1">
          <span className="mr-1 text-[11px]">{entry.user_upn}</span>
          <span className="rounded bg-blue-50 px-1 text-[10px] text-blue-800">View</span>
          {entry.edit_access && <span className="rounded bg-amber-50 px-1 text-[10px] text-amber-800">Edit</span>}
          {!entry.is_organizer && entry.edit_access && <button type="button" onClick={() => onRevoke(meeting.id, entry.user_upn, "edit")} className="text-[10px] font-semibold text-red-700">Revoke edit</button>}
          {!entry.is_organizer && <button type="button" onClick={() => onRevoke(meeting.id, entry.user_upn, "view")} className="text-[10px] font-semibold text-red-700">Revoke view</button>}
          {entry.is_organizer && <span className="text-[10px] text-[#6b7280]">Organizer</span>}
        </div>
      ))}
    </div>
  );
}

function formatUpn(upn: string): string {
  return upn.split("@")[0].split(".").map((p) => p.charAt(0).toUpperCase() + p.slice(1)).join(" ");
}

interface AddUserForm {
  upn: string;
  display_name: string;
  business_unit_id: number | null;
  is_admin: boolean;
}

function AddUserDialog({
  businessUnits,
  onSave,
  onClose,
}: {
  businessUnits: BusinessUnit[];
  onSave: (form: AddUserForm) => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState<AddUserForm>({ upn: "", display_name: "", business_unit_id: null, is_admin: false });

  return (
    <Dialog title="Register New User" onClose={onClose}>
      <div className="flex flex-col gap-4">
        <Field label="Work Email (@taxconsulting.co.za)" required>
          <input
            type="email"
            placeholder="firstname.lastname@taxconsulting.co.za"
            value={form.upn}
            onChange={(e) => setForm({ ...form, upn: e.target.value })}
            className="w-full border border-[#dde1e8] rounded-md px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-[#003366]"
          />
        </Field>
        <Field label="Display Name">
          <input
            type="text"
            placeholder="Full Name (optional)"
            value={form.display_name}
            onChange={(e) => setForm({ ...form, display_name: e.target.value })}
            className="w-full border border-[#dde1e8] rounded-md px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-[#003366]"
          />
        </Field>
        <Field label="Business Unit" required>
          <select
            value={form.business_unit_id ?? ""}
            onChange={(e) => setForm({ ...form, business_unit_id: e.target.value ? Number(e.target.value) : null })}
            className="w-full border border-[#dde1e8] rounded-md px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-[#003366]"
          >
            <option value="">Select business unit...</option>
            {businessUnits.map((bu) => (
              <option key={bu.id} value={bu.id}>{bu.name}</option>
            ))}
          </select>
        </Field>
        <label className="flex items-center gap-2 text-[13px] text-[#374151] cursor-pointer">
          <input
            type="checkbox"
            checked={form.is_admin}
            onChange={(e) => setForm({ ...form, is_admin: e.target.checked })}
            className="rounded border-[#dde1e8]"
          />
          Grant admin access (can manage users)
        </label>
        <div className="flex justify-end gap-2 mt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-[13px] text-[#6b7280] hover:text-[#1a1a2e]">Cancel</button>
          <button
            type="button"
            onClick={() => onSave(form)}
            disabled={!form.upn || !form.business_unit_id}
            className="px-4 py-2 text-[13px] font-semibold bg-[#003366] text-white rounded-md hover:bg-[#0a4a8c] disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Register
          </button>
        </div>
      </div>
    </Dialog>
  );
}

function EditUserDialog({
  user,
  businessUnits,
  onSave,
  onClose,
}: {
  user: RegisteredUser;
  businessUnits: BusinessUnit[];
  onSave: (payload: { display_name?: string; business_unit_id?: number; is_admin?: boolean }) => void;
  onClose: () => void;
}) {
  const [displayName, setDisplayName] = useState(user.display_name ?? "");
  const [buId, setBuId] = useState<number | null>(user.business_unit_id);
  const [isAdmin, setIsAdmin] = useState(user.is_admin);

  return (
    <Dialog title={`Edit — ${user.display_name ?? user.upn}`} onClose={onClose}>
      <div className="flex flex-col gap-4">
        <Field label="Display Name">
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="w-full border border-[#dde1e8] rounded-md px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-[#003366]"
          />
        </Field>
        <Field label="Business Unit">
          <select
            value={buId ?? ""}
            onChange={(e) => setBuId(e.target.value ? Number(e.target.value) : null)}
            className="w-full border border-[#dde1e8] rounded-md px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-[#003366]"
          >
            <option value="">Select business unit...</option>
            {businessUnits.map((bu) => (
              <option key={bu.id} value={bu.id}>{bu.name}</option>
            ))}
          </select>
        </Field>
        <label className="flex items-center gap-2 text-[13px] text-[#374151] cursor-pointer">
          <input
            type="checkbox"
            checked={isAdmin}
            onChange={(e) => setIsAdmin(e.target.checked)}
            className="rounded border-[#dde1e8]"
          />
          Admin access
        </label>
        <div className="flex justify-end gap-2 mt-2">
          <button type="button" onClick={onClose} className="px-4 py-2 text-[13px] text-[#6b7280] hover:text-[#1a1a2e]">Cancel</button>
          <button
            type="button"
            onClick={() => onSave({ display_name: displayName || undefined, business_unit_id: buId ?? undefined, is_admin: isAdmin })}
            className="px-4 py-2 text-[13px] font-semibold bg-[#003366] text-white rounded-md hover:bg-[#0a4a8c]"
          >
            Save Changes
          </button>
        </div>
      </div>
    </Dialog>
  );
}

function Dialog({ title, children }: { title: string; children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl w-full max-w-md">
        <div className="bg-[#003366] border-b-4 border-[#C9A52C] px-6 py-4 rounded-t-xl">
          <h2 className="text-white font-semibold text-[15px]">{title}</h2>
        </div>
        <div className="px-6 py-5">{children}</div>
      </div>
    </div>
  );
}

function Field({ label, required, children }: { label: string; required?: boolean; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-[12.5px] font-medium text-[#374151]">
        {label}{required && <span className="text-red-500 ml-0.5">*</span>}
      </label>
      {children}
    </div>
  );
}
