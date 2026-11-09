"use client";

import { useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { CalendarDays } from "lucide-react";
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from "@/components/ui/dialog";

const english = "en-ZA";
const monthNames = Array.from({ length: 12 }, (_, month) =>
  new Intl.DateTimeFormat(english, { month: "long", timeZone: "UTC" }).format(new Date(Date.UTC(2024, month, 1))));
const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const dayLabel = new Intl.DateTimeFormat(english, { dateStyle: "full", timeZone: "UTC" });
const shortLabel = new Intl.DateTimeFormat(english, { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" });
const todayInJohannesburg = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Africa/Johannesburg", year: "numeric", month: "2-digit", day: "2-digit",
});
const button = "rounded border border-gray-400 bg-white px-2 py-2 text-sm text-[#003366] focus-visible:outline-2 focus-visible:outline-[#003366] disabled:opacity-50";

function dateAt(year: number, month: number, day: number) {
  // UTC is a calendar arithmetic workspace. Only YYYY-MM-DD leaves this control.
  const date = new Date(0);
  date.setUTCFullYear(year, month, day);
  return date;
}

function iso(date: Date) {
  return date.toISOString().slice(0, 10);
}

export function calendarDateError(value: string, required = false): string | undefined {
  if (!value) return required ? "Select a decision date." : undefined;
  const date = new Date(`${value}T00:00:00Z`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000") ||
      Number.isNaN(date.getTime()) || iso(date) !== value) {
    return "Enter a valid date or choose one from the calendar.";
  }
}

function selectedDay(value: string) {
  if (value && !calendarDateError(value)) return new Date(`${value}T00:00:00Z`);
  const parts = todayInJohannesburg.formatToParts();
  return dateAt(Number(parts.find(part => part.type === "year")?.value),
    Number(parts.find(part => part.type === "month")?.value) - 1,
    Number(parts.find(part => part.type === "day")?.value));
}

export default function CalendarDateField({ id, label, value, onChange, required = false, error, disabled }: {
  id: string; label: string; value: string; onChange: (value: string) => void;
  required?: boolean; error?: string; disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(() => selectedDay(value));
  const [yearText, setYearText] = useState("");
  const activeButton = useRef<HTMLButtonElement>(null);
  const moveFocus = useRef(false);
  const year = active.getUTCFullYear();
  const month = active.getUTCMonth();
  const offset = (dateAt(year, month, 1).getUTCDay() + 6) % 7;
  const dayCount = dateAt(year, month + 1, 0).getUTCDate();

  useLayoutEffect(() => {
    if (open && moveFocus.current) {
      moveFocus.current = false;
      activeButton.current?.focus();
    }
  }, [active, open]);

  function move(next: Date, focus = false) {
    if (next.getUTCFullYear() < 1 || next.getUTCFullYear() > 9999) return;
    moveFocus.current = focus;
    setActive(next);
    setYearText(String(next.getUTCFullYear()));
  }

  function commitYear() {
    const nextYear = Number(yearText);
    if (/^\d{1,4}$/.test(yearText) && nextYear >= 1 && nextYear <= 9999) {
      if (nextYear !== year) move(dateAt(nextYear, month, 1));
      else setYearText(String(year));
    } else {
      setYearText(String(year));
    }
  }

  function navigate(event: KeyboardEvent<HTMLButtonElement>) {
    const day = active.getUTCDate();
    const offsets: Record<string, number> = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 };
    const weekDay = (active.getUTCDay() + 6) % 7;
    const delta = offsets[event.key] ?? (event.key === "Home" ? -weekDay : event.key === "End" ? 6 - weekDay : undefined);
    if (delta === undefined) return;
    event.preventDefault();
    move(dateAt(year, month, day + delta), true);
  }

  function choose(date: Date) {
    onChange(iso(date));
    setOpen(false);
  }

  return <div className="min-w-0 space-y-1">
    <label htmlFor={id} className="text-sm font-medium">{label}</label>
    <div className="flex min-w-0 flex-wrap gap-2">
      <input id={id} type="text" value={value} placeholder="YYYY-MM-DD" required={required}
        disabled={disabled} aria-invalid={Boolean(error)} aria-describedby={`${id}-help${error ? ` ${id}-error` : ""}`}
        className="min-w-0 flex-1 rounded border border-gray-400 bg-white p-2 text-sm"
        onChange={event => onChange(event.target.value)} />
      <Dialog open={open} onOpenChange={next => {
        if (next) move(selectedDay(value));
        setOpen(next);
      }}>
        <DialogTrigger type="button" disabled={disabled} className={button} title="Open calendar" aria-label={`Open calendar for ${label}`}>
          <CalendarDays className="size-5" aria-hidden="true" />
        </DialogTrigger>
        {open && <DialogContent className="max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-xs overflow-y-auto"
          initialFocus={activeButton}>
          <DialogTitle>Choose a date</DialogTitle>
          <DialogDescription>Use the arrow keys to move between days. Press Enter to select.</DialogDescription>
          <div className="flex items-end gap-1">
            <button type="button" className={button} aria-label="Previous month" disabled={year === 1 && month === 0}
              onClick={() => move(dateAt(year, month - 1, 1))}>‹</button>
            <label className="min-w-0 flex-1 text-xs">Month
              <select aria-label="Month" className="block w-full rounded border p-2" value={month}
                onChange={event => move(dateAt(year, Number(event.target.value), 1))}>
                {monthNames.map((name, index) => <option key={name} value={index}>{name}</option>)}
              </select>
            </label>
            <label className="w-14 text-xs">Year
              <input className="block w-full rounded border p-2" inputMode="numeric" maxLength={4} value={yearText}
                onChange={event => setYearText(event.target.value)} onBlur={commitYear}
                onKeyDown={event => { if (event.key === "Enter") { event.preventDefault(); commitYear(); } }} />
            </label>
            <button type="button" className={button} aria-label="Next month" disabled={year === 9999 && month === 11}
              onClick={() => move(dateAt(year, month + 1, 1))}>›</button>
          </div>
          <div className="grid grid-cols-7 gap-1 text-center" role="group" aria-label={`${monthNames[month]} ${year}`}>
            {weekdays.map(day => <span key={day} className="py-1 text-xs font-medium">{day}</span>)}
            {Array.from({ length: offset }, (_, index) => <span key={`blank-${index}`} />)}
            {Array.from({ length: dayCount }, (_, index) => {
              const day = index + 1;
              const date = dateAt(year, month, day);
              const current = day === active.getUTCDate();
              const selected = iso(date) === value;
              return <button key={day} ref={current ? activeButton : undefined} type="button"
                tabIndex={current ? 0 : -1} aria-label={dayLabel.format(date)} aria-pressed={selected}
                className={`min-h-9 rounded text-sm hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-[#003366] ${selected ? "bg-blue-100 font-semibold" : ""}`}
                onKeyDown={navigate} onClick={() => choose(date)}>{day}</button>;
            })}
          </div>
        </DialogContent>}
      </Dialog>
      {!required && value && <button type="button" className={button} disabled={disabled}
        onClick={() => { onChange(""); document.getElementById(id)?.focus(); }}>Clear date</button>}
    </div>
    <p id={`${id}-help`} className="text-xs text-gray-600">
      {required ? "Required. " : "Optional. "}{value && !calendarDateError(value)
        ? shortLabel.format(selectedDay(value))
        : "Choose from the calendar or enter YYYY-MM-DD."}
    </p>
    {error && <p id={`${id}-error`} role="alert" className="text-xs text-red-800">{error}</p>}
  </div>;
}
