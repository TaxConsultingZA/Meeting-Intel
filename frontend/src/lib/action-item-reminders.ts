import type { ApprovedActionItem } from "./types";

export type ActionItemReminderGroups = {
  overdue: ApprovedActionItem[];
  dueSoon: ApprovedActionItem[];
};

function localCalendarDate(now: Date): string {
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function calendarDay(value: string): number | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const timestamp = Date.parse(`${value}T00:00:00Z`);
  if (!Number.isFinite(timestamp) || new Date(timestamp).toISOString().slice(0, 10) !== value) return null;
  return timestamp / 86_400_000;
}

export function getActionItemReminders(
  items: ApprovedActionItem[],
  viewerUpn: string,
  now = new Date(),
): ActionItemReminderGroups {
  const today = calendarDay(localCalendarDate(now));
  if (today === null || !viewerUpn.trim()) return { overdue: [], dueSoon: [] };

  const overdue: ApprovedActionItem[] = [];
  const dueSoon: ApprovedActionItem[] = [];
  for (const item of items) {
    if (item.completed_at || !item.owner?.trim() || item.owner.trim().toLowerCase() !== viewerUpn.trim().toLowerCase()) continue;
    if (!item.deadline_iso) continue;
    const due = calendarDay(item.deadline_iso);
    if (due === null) continue;
    if (due < today) overdue.push(item);
    else if (due <= today + 7) dueSoon.push(item);
  }
  return { overdue, dueSoon };
}
