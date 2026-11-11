"use client";
import "./admin-workspace.css";
import AccessRequestsPanel from "./access-requests-panel";
import { parseInstant } from "@/lib/time";
import AdminWorkbench from "./admin-workbench";
import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import LoadingSpinner from "@/components/loading-spinner";
import Link from "next/link";
import { UserPlus, Trash2, Shield, Pencil, ChevronDown, Loader2, History, ArrowRight, BarChart3 } from "lucide-react";
import { createBusinessUnit, getAdminAccessRequests, cleanupAdminJob, decideMeetingEditAccess, decideRecordingProcessing, getAdminUserSyncStatus, getBusinessUnits, getRecordingJobs, getRegisteredUsers, registerUser, removeUser, reprocessRecordingJob, revokeAdminMeetingAccess, updateUser } from "@/lib/api";
import type { UpdateUserPayload } from "@/lib/api";
import type { RegisteredUser, BusinessUnit, RecordingJobOut, AdminAccessRequest, AdminMeetingOut, SyncState } from "@/lib/types";
import { JobControls } from "@/components/recording-jobs";
import { toast } from "sonner";
import { recordingStatusMessage } from "@/components/recording-jobs";
import StateBadge from "@/components/state-badge";

interface Props {
  initialRequests: AdminAccessRequest[];
  callerUpn: string;
  accessToken: string;
  deferInitialRequests?: boolean;
}

export default function AdminClient({ initialRequests, callerUpn, accessToken, deferInitialRequests = false }: Props) {
  const [buFilter, setBuFilter] = useState("");
  const [groupUsers, setGroupUsers] = useState(false);
  const [usersLoadAttempt, setUsersLoadAttempt] = useState(0);
  useEffect(() => {
    const refreshUsers = () => setUsersLoadAttempt(current => current + 1);
    window.addEventListener("business-unit-updated", refreshUsers);
    return () => window.removeEventListener("business-unit-updated", refreshUsers);
  }, []);
  const [usersError, setUsersError] = useState("");
  const [users, setUsers] = useState<RegisteredUser[]>([]);
  const visibleUsers = users.filter(u => !buFilter || (buFilter === "unassigned" ? u.business_unit_id == null : String(u.business_unit_id) === buFilter)).sort((a,b) => groupUsers ? (a.business_unit_name || "Unassigned").localeCompare(b.business_unit_name || "Unassigned") || a.upn.localeCompare(b.upn) : 0);
  const [catalog, setCatalog] = useState<BusinessUnit[]>([]);
  const businessUnits = catalog.filter(unit => unit.is_selectable);
  const [unitName, setUnitName] = useState("");
  const [unitError, setUnitError] = useState("");
  const [unitSaved, setUnitSaved] = useState("");
  const [unitSaving, setUnitSaving] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const [editUser, setEditUser] = useState<RegisteredUser | null>(null);
  const [savingUser, setSavingUser] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<RecordingJobOut[]>([]);
  const [meetings, setMeetings] = useState<AdminMeetingOut[]>([]);
  const [requests, setRequests] = useState(initialRequests);
  const [loaded, setLoaded] = useState({ meetings: false, jobs: false, users: false });
  const [loading, setLoading] = useState({ meetings: false, jobs: false, users: false });
  const sectionsInFlight = useRef(new Set<string>());
  const [requestsLoading, setRequestsLoading] = useState(deferInitialRequests);
  const [requestActionError, setRequestActionError] = useState("");
  const [requestsError, setRequestsError] = useState("");
  const [syncOpen, setSyncOpen] = useState<string | null>(null);
  const [syncByUser, setSyncByUser] = useState<Record<string, SyncState[]>>({});
  const [syncLoading, setSyncLoading] = useState<string | null>(null);
  const [syncErrors, setSyncErrors] = useState<Record<string, string>>({});
  const [busyJob, setBusyJob] = useState<{ id: string; action: "reprocess" | "cleanup" } | null>(null);
  const jobsInFlight = useRef(new Set<string>());
  const failedJobs = jobs.filter((job) => job.status === "failed");
  const jobCounts = [
    ["Queued", jobs.filter((job) => job.status === "pending").length],
    ["Processing / Transcribing", jobs.filter((job) => job.status === "processing").length],
    ["Completed", jobs.filter((job) => job.status === "completed").length],
    ["Failed", failedJobs.length],
    ["Cancelled", jobs.filter((job) => job.status === "cancelled").length],
  ] as const;

  const refreshRequests = useCallback(async (active: () => boolean = () => true) => {
    setRequestsLoading(true);
    try {
      const rows = await getAdminAccessRequests(accessToken);
      if (active()) { setRequests(rows); setRequestsError(""); }
    } catch {
      if (active()) setRequestsError("Access requests could not be loaded.");
    } finally {
      if (active()) setRequestsLoading(false);
    }
  }, [accessToken]);

  useEffect(() => {
    if (!deferInitialRequests) return;
    let active = true;
    void refreshRequests(() => active);
    return () => { active = false; };
  }, [deferInitialRequests, refreshRequests]);

  useEffect(() => {
    let active = true;
    setUsersError("");
    setLoaded(current => ({ ...current, users: false }));
    setLoading(current => ({ ...current, users: true }));
    void Promise.all([getRegisteredUsers(accessToken), getBusinessUnits(accessToken, true)])
      .then(([nextUsers, nextUnits]) => {
        if (!active) return;
        setUsers(nextUsers);
        setCatalog(nextUnits);
        setLoaded(current => ({ ...current, users: true }));
      })
      .catch(() => {
        if (active) setUsersError("Users could not be loaded. Please retry.");
      })
      .finally(() => {
        if (active) setLoading(current => ({ ...current, users: false }));
      });
    return () => { active = false; };
  }, [accessToken, usersLoadAttempt]);

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
    setRequestActionError("");
    if (!request.meeting_id || !request.requester_upn) return;
    if (!confirm(`${approved ? "Approve" : "Reject"} ${request.request_type} access for ${request.requester_upn}?`)) return;
    setError(null);
    try {
      await decideMeetingEditAccess(request.meeting_id, request.requester_upn, approved, accessToken);
      void refreshRequests();
      setRequests((current) => current.map((entry) => entry.id === request.id
        ? { ...entry, status: approved ? "approved" : "denied" }
        : entry));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to decide access request");
      setRequestActionError(e instanceof Error ? e.message : "Failed to decide access request");
    }
  }

  async function handleProcessingDecision(request: AdminAccessRequest, approved: boolean) {
    setRequestActionError("");
    if (!confirm(`${approved ? "Approve" : "Reject"} processing request for ${request.meeting}?`)) return;
    setError(null);
    try {
      await decideRecordingProcessing(request.id, approved, accessToken);
      void refreshRequests();
      setRequests((current) => current.map((entry) => entry.id === request.id
        ? { ...entry, status: approved ? "approved" : "denied", can_approve: false }
        : entry));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : `Failed to ${approved ? "approve" : "reject"} processing request`);
      setRequestActionError(e instanceof Error ? e.message : "Processing request could not be decided");
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
    sectionsInFlight.current.add("jobs");
    setLoaded((current) => ({ ...current, jobs: false }));
    setLoading((current) => ({ ...current, jobs: true }));
    setError(null);
    try {
      setJobs(await getRecordingJobs(accessToken, undefined, 200));
      setLoaded((current) => ({ ...current, jobs: true }));
    } catch {
      const message = "Recording jobs could not be loaded. Close and reopen Processing Jobs to try again.";
      setError(message);
      throw new Error(message);
    } finally {
      sectionsInFlight.current.delete("jobs");
      setLoading((current) => ({ ...current, jobs: false }));
    }
  }

  async function handleReprocess(job: RecordingJobOut) {
    if (jobsInFlight.current.has(job.job_id)) return;
    jobsInFlight.current.add(job.job_id);
    setBusyJob({ id: job.job_id, action: "reprocess" });
    setError(null);
    try {
      await reprocessRecordingJob(job.job_id, accessToken);
      toast.success("Recording queued for reprocessing. Saved results remain available until replacement succeeds.");
      try { await refreshJobs(); }
      catch { setError("Reprocessing was queued, but the latest status could not be loaded. Reload the page before taking another action."); }
    } catch {
      setError("We could not confirm the reprocess request. Reload the page to check the status before trying again.");
    } finally {
      jobsInFlight.current.delete(job.job_id);
      setBusyJob((current) => current?.id === job.job_id ? null : current);
    }
  }

  async function handleCleanup(job: RecordingJobOut, refresh: () => Promise<void>) {
    if (jobsInFlight.current.has(job.job_id)) return;
    if (!confirm(`Remove this ${job.status} operational job record? Saved meeting content will be kept.`)) return;
    jobsInFlight.current.add(job.job_id);
    setBusyJob({ id: job.job_id, action: "cleanup" });
    setError(null);
    try {
      await cleanupAdminJob(job.job_id, accessToken);
      await refresh();
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

  async function handleCreateUnit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!unitName.trim() || unitSaving) return;
    setUnitSaving(true);
    setUnitError("");
    setUnitSaved("");
    try {
      const unit = await createBusinessUnit(accessToken, unitName);
      setCatalog(current => [...current, unit].sort((a, b) => a.name.localeCompare(b.name)));
      window.dispatchEvent(new Event("business-unit-updated"));
      setUnitName("");
      setUnitSaved(`Added ${unit.name}.`);
    } catch (failure) {
      setUnitError(failure instanceof Error ? failure.message : "Could not add Business Unit.");
    } finally {
      setUnitSaving(false);
    }
  }

  async function handleUpdate(targetUpn: string, payload: UpdateUserPayload) {
    if (savingUser) return;
    setError(null);
    setSavingUser(true);
    try {
      const updated = await updateUser(targetUpn, payload, accessToken);
      setUsers((prev) => prev.map((u) => (u.upn === targetUpn ? updated : u)));
      setEditUser(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to update user");
    } finally {
      setSavingUser(false);
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
    <main className="admin-workspace max-w-6xl mx-auto px-4 sm:px-6 py-5">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[22px] font-bold text-[#003366]">Admin workspace</h1>
          <p className="text-[#6b7280] text-[13.5px] mt-0.5">
            Manage meetings, processing, access, and registered users.
          </p>
        </div>
        <Link href="/admin/usage-metrics" className="admin-metrics-link"><BarChart3 size={16} aria-hidden="true" /> Usage Metrics</Link>
      </div>

      <AdminWorkbench pendingRequests={!requestsLoading && !requestsError ? requests.filter(r => r.status === "pending").length : undefined} accessToken={accessToken} callerUpn={callerUpn} renderControls={(meeting, linkedJobs, refresh, area) => <div tabIndex={0} aria-label="Access and processing controls" className="space-y-3 max-h-[28rem] overflow-y-auto">
        {area === "access" ? <><h3>Meeting access</h3><AccessList meeting={meeting} onRevoke={async (id, upn, type) => { await handleRevoke(id, upn, type); await refresh(); }} />
        <h3>Access requests for this meeting</h3>
        {requests.filter(r => r.meeting_id === meeting.id).map(r => <div key={r.id} className="border p-2"><p>{r.requester_name || r.requester_upn} · {r.request_type} · {r.status} · {formatSyncTime(r.requested_at)}</p><p>Decision by: {r.decided_by || "No reliable record"} · Decision time: {r.decided_at ? formatSyncTime(r.decided_at) : "No reliable record"}</p>{r.status === "pending" && <div className="flex gap-4">{(r.request_type !== "processing" || r.can_approve) && <button onClick={() => void (r.request_type === "processing" ? handleProcessingDecision(r, true) : handleAccessDecision(r, true))}>Approve</button>}<button onClick={() => void (r.request_type === "processing" ? handleProcessingDecision(r, false) : handleAccessDecision(r, false))}>Reject</button></div>}</div>)}
        {!requests.some(r => r.meeting_id === meeting.id) && <p>{requestsLoading ? "Loading access requests…" : requestsError || "No linked requests in the returned records."}</p>}</> : <>
        {linkedJobs.map(job => <div key={job.job_id}><fieldset><JobControls job={job} token={accessToken} onChanged={refresh} /></fieldset>
          {job.can_reprocess && <button disabled={!!busyJob} onClick={async () => { await handleReprocess(job); await refresh(); }}>Reprocess</button>}
          {(job.status === "failed" || job.status === "cancelled") && <button disabled={!!busyJob} onClick={() => void handleCleanup(job, refresh)}>Clean up</button>}
        </div>)}</>}
      </div>} />
      <AccessRequestsPanel requests={requests} loading={requestsLoading} error={requestsError || requestActionError} retry={() => { setRequestActionError(""); void refreshRequests(); }} disabled={false} decide={(r,approved) => r.request_type === "processing" ? handleProcessingDecision(r,approved) : handleAccessDecision(r,approved)} />
      {error && !editUser && (
        <div className="mb-4 bg-red-50 border border-red-200 text-red-700 text-[13px] px-4 py-3 rounded-lg">
          {error}
        </div>
      )}

      <section className="group bg-white rounded-lg border border-[#dde1e8] shadow-sm overflow-hidden">
        <header className="flex flex-wrap items-center justify-between gap-3 bg-[#003366] p-4">
          <h2 className="font-semibold text-white">Users {loaded.users ? `(${users.length})` : ""}</h2>
          <button type="button" onClick={() => setShowAdd(true)} disabled={!loaded.users}
            className="inline-flex items-center gap-2 rounded-md border border-white bg-white px-4 py-2 text-[13px] font-semibold text-[#003366] hover:bg-slate-100 disabled:opacity-50">
            <UserPlus size={15} /> Register User
          </button>
        </header>
        <div id="admin-users-content">
        {usersError && <div role="alert" className="px-4 pb-3">{usersError} <button disabled={loading.users} onClick={() => setUsersLoadAttempt(attempt => attempt + 1)}>Retry users</button></div>}
        {loaded.users && <form className="grid items-end gap-3 px-4 pt-4 sm:max-w-xl sm:grid-cols-[minmax(0,1fr)_auto]" onSubmit={handleCreateUnit}>
          <label className="grid min-w-0 gap-1.5 text-xs font-medium text-slate-700">
            New Business Unit name
            <input className="h-10 w-full min-w-0 rounded-md border border-[#dde1e8] px-3 text-sm disabled:bg-slate-100" required maxLength={100} value={unitName} disabled={unitSaving} onChange={event => setUnitName(event.target.value)} />
          </label>
          <button type="submit" className="admin-primary h-10 w-full sm:w-auto" disabled={unitSaving || !unitName.trim()}>{unitSaving ? "Adding..." : "Add Business Unit"}</button>
          {unitError && <p className="break-words text-red-700 sm:col-span-2" role="alert">{unitError}</p>}
          {unitSaved && <p className="break-words text-emerald-700 sm:col-span-2" role="status">{unitSaved}</p>}
        </form>}
        <div className="admin-filter-grid"><label>Business Unit<select aria-label="Filter users by Business Unit" value={buFilter} onChange={e=>setBuFilter(e.target.value)}><option value="">All business units</option>{catalog.map(unit => <option key={unit.id} value={unit.id}>{unit.name}{unit.is_selectable ? "" : " (historical)"}</option>)}<option value="unassigned">Unassigned</option></select></label><label>View<select aria-label="User display mode" value={groupUsers ? "grouped" : "list"} onChange={e=>setGroupUsers(e.target.value==="grouped")}><option value="list">User list</option><option value="grouped">Grouped by Business Unit</option></select></label></div><p className="admin-help">{visibleUsers.length} of {users.length} users · Historical Business Units are available for filtering. BU does not grant login or meeting access.</p>
        {loading.users && <LoadingSpinner label="Users loading" />}
        {loaded.users && <div tabIndex={0} className="admin-users-scroll max-h-[28rem] overflow-y-auto overflow-x-hidden [&_table]:max-sm:block [&_thead]:max-sm:hidden [&_tbody]:max-sm:block [&_tr]:max-sm:block [&_td]:max-sm:block [&_td]:max-sm:whitespace-normal [&_td]:max-sm:break-words">
        <table className="admin-users-table w-full text-sm">
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
            {visibleUsers.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-[#9ca3af] text-[13px]">
                  No users match this Business Unit.
                </td>
              </tr>
            )}
            {visibleUsers.map((u, i) => (
              <Fragment key={u.upn}>
              {groupUsers && (i === 0 || (visibleUsers[i-1].business_unit_name || "Unassigned") !== (u.business_unit_name || "Unassigned")) && <tr className="admin-bu-group"><td colSpan={6}>{u.business_unit_name || "Unassigned"}</td></tr>}
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
                  {(parseInstant(u.registered_at) ?? new Date(NaN)).toLocaleDateString("en-ZA", { day: "2-digit", month: "short", year: "numeric", timeZone: "Africa/Johannesburg" })}
                </td>
                <td className="px-4 py-2.5 border border-[#dde1e8]">
                  <div className="flex flex-wrap items-center gap-3">
                    <button type="button" onClick={() => void toggleSyncDiagnostics(u.upn)}
                      aria-expanded={syncOpen === u.upn}
                      className="text-[11px] font-semibold text-[#003366] hover:underline">
                      Sync
                    </button>
                    <button
                      type="button"
                      onClick={() => { setError(null); setEditUser(u); }}
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
                      ? <LoadingSpinner label="Sync diagnostics loading" />
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
      </div>
      </section>

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
          error={error}
          saving={savingUser}
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
  return value ? (parseInstant(value) ?? new Date(NaN)).toLocaleString("en-ZA", { timeZone: "Africa/Johannesburg" }) : "Unavailable";
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
  error,
  saving,
  onSave,
  onClose,
}: {
  user: RegisteredUser;
  businessUnits: BusinessUnit[];
  error: string | null;
  saving: boolean;
  onSave: (payload: UpdateUserPayload) => void;
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
            aria-label="Correct Business Unit"
            onChange={(e) => setBuId(e.target.value ? Number(e.target.value) : null)}
            className="w-full border border-[#dde1e8] rounded-md px-3 py-2 text-[13px] focus:outline-none focus:ring-2 focus:ring-[#003366]"
          >
            <option value="">Unassigned</option>
            {user.business_unit_id != null && !businessUnits.some(unit => unit.id === user.business_unit_id) && (
              <option value={user.business_unit_id} disabled>{user.business_unit_name} (historical)</option>
            )}
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
        {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
        <div className="flex justify-end gap-2 mt-2">
          <button type="button" disabled={saving} onClick={onClose} className="px-4 py-2 text-[13px] text-[#6b7280] hover:text-[#1a1a2e]">Cancel</button>
          <button
            type="button"
            disabled={saving}
            onClick={() => onSave({
              display_name: displayName || undefined,
              is_admin: isAdmin,
              ...(buId === user.business_unit_id ? {} : {
                business_unit_id: buId,
                business_unit_version: user.business_unit_version,
              }),
            })}
            className="px-4 py-2 text-[13px] font-semibold bg-[#003366] text-white rounded-md hover:bg-[#0a4a8c]"
          >
            {saving ? "Saving..." : "Save Changes"}
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
