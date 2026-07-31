import type { ActionItemEdit, MeetingOut, AvailableRecording, CalendarEvent, AppNotification, RegisteredUser, BusinessUnit } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/**
 * Base fetch wrapper for all backend API calls.
 * Attaches the Microsoft Entra bearer token, throws on non-2xx responses,
 * and handles 204 No Content by returning undefined.
 */
async function apiFetch<T>(
  path: string,
  accessToken: string,
  init?: RequestInit,
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${accessToken}`,
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

/** Fetch only meetings currently awaiting organiser review. */
export async function getPendingMeetings(upn: string): Promise<MeetingOut[]> {
  return apiFetch<MeetingOut[]>("/reviews/pending", upn);
}

/** Fetch all meetings the user is a participant of, across all pipeline states. */
export async function getAllMeetings(upn: string): Promise<MeetingOut[]> {
  return apiFetch<MeetingOut[]>("/reviews/all", upn);
}

/** Fetch a single meeting by ID. Throws if the user is not a participant. */
export async function getMeeting(id: string, upn: string): Promise<MeetingOut> {
  return apiFetch<MeetingOut>(`/reviews/${id}`, upn);
}

/** Partially update an action item's fields (task, owner, deadline, confidence). */
export async function editActionItem(
  itemId: string,
  edit: ActionItemEdit,
  upn: string,
): Promise<void> {
  await apiFetch<void>(`/reviews/action-items/${itemId}`, upn, {
    method: "PATCH",
    body: JSON.stringify(edit),
  });
}

/** Approve a meeting's notes, triggering the final email send to all participants. */
export async function approveMeeting(
  meetingId: string,
  accessToken: string,
  recipients: string[],
): Promise<{ ok: boolean; state: string }> {
  return apiFetch(`/reviews/${meetingId}/approve`, accessToken, {
    method: "POST",
    body: JSON.stringify({ recipients }),
  });
}

/** Fetch the 30 most recent activity notifications for the current user. */
export async function getNotifications(upn: string): Promise<AppNotification[]> {
  return apiFetch<AppNotification[]>("/notifications", upn);
}

/** Fetch the user's upcoming and in-progress Teams calendar events (next 7 days). */
export async function getUpcomingMeetings(upn: string): Promise<CalendarEvent[]> {
  return apiFetch<CalendarEvent[]>("/calendar/upcoming", upn);
}

/** List MP4 files in the user's OneDrive Recordings folder with their current import status. */
export async function getAvailableRecordings(upn: string): Promise<AvailableRecording[]> {
  return apiFetch<AvailableRecording[]>("/recordings/available", upn);
}

/** Trigger the full pipeline for a new recording. Returns 409 if already imported. */
export async function importRecording(
  driveItemId: string,
  driveId: string,
  upn: string,
): Promise<{ ok: boolean }> {
  return apiFetch("/recordings/import", upn, {
    method: "POST",
    body: JSON.stringify({ drive_item_id: driveItemId, drive_id: driveId }),
  });
}

/** Re-trigger the pipeline for a previously failed recording. */
export async function reprocessRecording(
  driveItemId: string,
  driveId: string,
  upn: string,
): Promise<{ ok: boolean }> {
  return apiFetch("/recordings/reprocess", upn, {
    method: "POST",
    body: JSON.stringify({ drive_item_id: driveItemId, drive_id: driveId }),
  });
}

// ── Registration / Admin ──────────────────────────────────────────────────────

/** Check if the current user is registered on the platform. Returns null if not registered (404). */
export async function getMe(upn: string): Promise<RegisteredUser | null> {
  try {
    return await apiFetch<RegisteredUser>("/users/me", upn);
  } catch (e: unknown) {
    if (e instanceof Error && e.message.startsWith("404")) return null;
    throw e;
  }
}

/** Explicitly opt the current user into automatic Calendar/OneDrive processing. */
export async function subscribeCurrentUser(
  accessToken: string,
): Promise<{ is_subscribed: boolean; subscribed_at: string | null }> {
  return apiFetch("/users/me/subscription", accessToken, { method: "POST" });
}

/** Stop future automatic processing without deleting historical meeting data. */
export async function unsubscribeCurrentUser(
  accessToken: string,
): Promise<{ is_subscribed: boolean; subscribed_at: string | null }> {
  return apiFetch("/users/me/subscription", accessToken, { method: "DELETE" });
}

/** Fetch all available business units (any authenticated domain user can call this). */
export async function getBusinessUnits(upn: string): Promise<BusinessUnit[]> {
  return apiFetch<BusinessUnit[]>("/admin/business-units", upn);
}

/** Fetch all registered platform users (admin only). */
export async function getRegisteredUsers(upn: string): Promise<RegisteredUser[]> {
  return apiFetch<RegisteredUser[]>("/admin/users", upn);
}

/** Register a new user (admin only). */
export async function registerUser(
  upn: string,
  payload: { upn: string; display_name?: string; business_unit_id?: number; is_admin?: boolean },
  callerUpn: string,
): Promise<RegisteredUser> {
  return apiFetch<RegisteredUser>("/admin/users", callerUpn, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** Update a registered user's details (admin only). */
export async function updateUser(
  targetUpn: string,
  payload: { display_name?: string; business_unit_id?: number; is_admin?: boolean },
  callerUpn: string,
): Promise<RegisteredUser> {
  return apiFetch<RegisteredUser>(`/admin/users/${encodeURIComponent(targetUpn)}`, callerUpn, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

/** Remove a registered user (admin only). */
export async function removeUser(targetUpn: string, callerUpn: string): Promise<void> {
  await apiFetch<void>(`/admin/users/${encodeURIComponent(targetUpn)}`, callerUpn, {
    method: "DELETE",
  });
}

/** Share a meeting transcript with a @taxconsulting.co.za colleague. */
export async function shareMeeting(
  meetingId: string,
  recipientUpn: string,
  callerUpn: string,
): Promise<{ ok: boolean; message: string }> {
  return apiFetch(`/reviews/${meetingId}/share`, callerUpn, {
    method: "POST",
    body: JSON.stringify({ recipient_upn: recipientUpn }),
  });
}

/** Fetch meetings the user attended before registering (no current access). */
export async function getHistoricalMeetings(upn: string): Promise<MeetingOut[]> {
  return apiFetch<MeetingOut[]>("/reviews/historical", upn);
}

/** Auto-request access to a historical meeting (granted instantly if UPN is in attendees). */
export async function requestHistoricalAccess(
  meetingId: string,
  upn: string,
): Promise<{ ok: boolean; message: string }> {
  return apiFetch(`/reviews/${meetingId}/request-access`, upn, { method: "POST" });
}
