import type { MeetingOut } from "./types";

export const UNVERIFIED_RECORDING_ASSOCIATION = "Calendar association unverified. Existing results are preserved.";

type MeetingIdentity = Pick<MeetingOut, "title" | "recording_display">;

export function meetingDisplayTitle(meeting: MeetingIdentity): string {
  if (meeting.recording_display?.association_status === "needs_review") {
    return meeting.recording_display.filename?.trim() || "Recording identity unverified";
  }
  return meeting.title ?? "Untitled Meeting";
}

export function meetingIdentityNotice(meeting: MeetingIdentity): string | null {
  return meeting.recording_display?.association_status === "needs_review"
    ? UNVERIFIED_RECORDING_ASSOCIATION : null;
}
