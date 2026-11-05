import { expect, it } from "vitest";
import { getActionItemReminders } from "../action-item-reminders";
import type { ApprovedActionItem } from "../types";

const base: ApprovedActionItem = {
  id: "a", meeting_id: "m", meeting_title: "Meeting", task: "Task", owner: "alice@example.test",
  deadline_iso: null, deadline_text: null, source_quote: null,
};

it("uses local calendar days and includes today through the seventh day", () => {
  const now = new Date(2026, 9, 20, 23, 30);
  const items = [
    { ...base, id: "yesterday", deadline_iso: "2026-10-19" },
    { ...base, id: "today", deadline_iso: "2026-10-20" },
    { ...base, id: "day7", deadline_iso: "2026-10-27" },
    { ...base, id: "day8", deadline_iso: "2026-10-28" },
  ];
  const result = getActionItemReminders(items, "ALICE@example.test", now);
  expect(result.overdue.map(item => item.id)).toEqual(["yesterday"]);
  expect(result.dueSoon.map(item => item.id)).toEqual(["today", "day7"]);
});

it("anchors a late UTC instant to the browser's local calendar day", () => {
  const now = new Date("2026-10-20T23:30:00-07:00");
  const localToday = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  const result = getActionItemReminders([{ ...base, deadline_iso: localToday }], "alice@example.test", now);
  expect(result.dueSoon).toHaveLength(1);
  expect(result.overdue).toHaveLength(0);
});

it("ignores invalid or implicit dates, completed tasks and nonmatching owners", () => {
  const result = getActionItemReminders([
    { ...base, id: "invalid", deadline_iso: "2026-02-30", deadline_text: "next week" },
    { ...base, id: "text-only", deadline_text: "next week" },
    { ...base, id: "complete", deadline_iso: "2026-10-19", completed_at: "2026-10-20T01:00:00Z" },
    { ...base, id: "name", owner: "Alice", deadline_iso: "2026-10-19" },
    { ...base, id: "other", owner: "bob@example.test", deadline_iso: "2026-10-19" },
  ], "alice@example.test", new Date(2026, 9, 20, 12));
  expect(result).toEqual({ overdue: [], dueSoon: [] });
});
