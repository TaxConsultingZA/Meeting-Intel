const WINDOWS_ZONES: Record<string, string> = {
  "South Africa Standard Time": "Africa/Johannesburg",
  "China Standard Time": "Asia/Shanghai",
  "GMT Standard Time": "Europe/London",
  UTC: "UTC",
};

export function resolveTimeZone(profileZone?: string | null, browserZone?: string | null): string {
  for (const candidate of [profileZone, browserZone, "Africa/Johannesburg"]) {
    if (!candidate) continue;
    const zone = WINDOWS_ZONES[candidate] ?? candidate;
    try { new Intl.DateTimeFormat("en", { timeZone: zone }); return zone; } catch { /* Next reliable source */ }
  }
  return "UTC";
}

export function parseInstant(value: string | null | undefined): Date | null {
  if (!value || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(value)) return null;
  // API dates are UTC ISO strings. Legacy naive UTC strings get Z exactly once;
  // explicit Z/offset strings are never shifted by appending another offset.
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value: string | null | undefined, zone: string): string {
  const date = parseInstant(value);
  if (!date) return value || "—"; // Preserve descriptive/unknown old meeting dates.
  return new Intl.DateTimeFormat("en-ZA", {
    timeZone: zone, day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).format(date);
}

function dayKey(date: Date, zone: string) {
  const parts = new Intl.DateTimeFormat("en", { timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(date);
  const part = (name: string) => parts.find(p => p.type === name)?.value;
  return `${part("year")}-${part("month")}-${part("day")}`;
}

export function formatEventTime(start: string | null, end: string | null, zone: string, now = new Date()) {
  const s = parseInstant(start), e = parseInstant(end);
  if (!s) return { dateLabel: "—", timeRange: "—", duration: "" };
  const today = dayKey(now, zone);
  const tomorrow = new Date(`${today}T00:00:00Z`);
  tomorrow.setUTCDate(tomorrow.getUTCDate() + 1);
  const shortDate = (d: Date) => new Intl.DateTimeFormat("en-ZA", { timeZone: zone, day: "2-digit", month: "short" }).format(d);
  const time = (d: Date) => new Intl.DateTimeFormat("en-ZA", { timeZone: zone, hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(d);
  const dateLabel = dayKey(s, zone) === today ? "Today" : dayKey(s, zone) === tomorrow.toISOString().slice(0, 10) ? "Tomorrow" : shortDate(s);
  const endLabel = e ? `${dayKey(e, zone) !== dayKey(s, zone) ? shortDate(e) + " " : ""}${time(e)}` : "";
  return { dateLabel, timeRange: `${time(s)}${e ? ` – ${endLabel}` : ""}`, duration: e ? `${Math.round((e.getTime() - s.getTime()) / 60000)} min` : "" };
}
