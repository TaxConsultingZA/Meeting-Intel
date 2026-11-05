import type { MeetingOut } from "@/lib/types";
import { formatDateTime, parseInstant } from "@/lib/time";

export default function MeetingCardDate({ meeting }: { meeting: Pick<MeetingOut, "card_date"> }) {
  const date = meeting.card_date;
  // Older API responses have no provenance. Avoid presenting ambiguous dates as meeting starts.
  const value = date?.value;
  const source = date?.date_source ?? date?.source;
  const calendarDay = value?.slice(0, 10);
  const realDay = calendarDay && !Number.isNaN(Date.parse(`${calendarDay}T00:00:00Z`)) && new Date(`${calendarDay}T00:00:00Z`).toISOString().slice(0, 10) === calendarDay;
  const valid = realDay && value && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/i.test(value) && parseInstant(value);
  if (!valid || !["meeting", "recording"].includes(source || "")) return <span title={date?.reason || "Missing or invalid date timestamp or provenance."}>Date not available</span>;
  return <span title={date?.reason || "Verified calendar meeting start"}>
    {source === "recording" ? "Recording time: " : ""}{formatDateTime(value!, "Africa/Johannesburg")} SAST
  </span>;
}
