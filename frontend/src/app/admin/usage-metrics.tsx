"use client";

import { useEffect, useMemo, useState } from "react";
import { getUsageMetrics } from "@/lib/api";
import type { UsageMetricKind, UsageMetrics } from "@/lib/types";

export type Bucket = { start: string; end: string; label: string; fullLabel: string };
type Metric = { key: UsageMetricKind; label: string; axis: string; totalNoun: string; hint: string; empty: string };
export type AppliedFilters = { from: string; to: string; group: string };
const METRICS: Metric[] = [
  { key: "action_items", label: "Action items completed", axis: "Action items", totalNoun: "action items", hint: "Completion date in Johannesburg · confirming user’s current BU.", empty: "No completed action items in this range." },
  { key: "meetings", label: "Meetings created", axis: "Meetings", totalNoun: "meetings", hint: "Creation date in Johannesburg · organizer’s current BU.", empty: "No meetings were created in this range." },
];
const UNAVAILABLE = [
  { label: "API usage", reason: "Unavailable: a metered provider record with model and BU attribution is required." },
  { label: "Emails sent", reason: "Unavailable: a reliable external delivery result is required." },
  { label: "API quota", reason: "Unavailable: an authorized provider quota source is required." },
];
const DAY = 86_400_000;
const asDate = (value: string) => new Date(`${value}T00:00:00Z`);
const iso = (value: Date) => value.toISOString().slice(0, 10);
const parts = (value: string) => new Intl.DateTimeFormat("en", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).formatToParts(asDate(value));
const part = (value: string, type: Intl.DateTimeFormatPartTypes) => parts(value).find(item => item.type === type)?.value ?? "";

export function bucketLabel(start: string, end: string) {
  const sd = part(start, "day"), sm = part(start, "month"), sy = part(start, "year");
  const ed = part(end, "day"), em = part(end, "month"), ey = part(end, "year");
  if (start === end) return `${sd} ${sm}${sy !== ey ? ` ${sy}` : ""}`;
  if (sy === ey && sm === em) return `${sd}–${ed} ${sm}`;
  if (sy === ey) return `${sd} ${sm}–${ed} ${em}`;
  return `${sd} ${sm} ${sy}–${ed} ${em} ${ey}`;
}
export function makeBuckets(start: string, end: string, targetBuckets = 12): Bucket[] {
  const first = asDate(start), last = asDate(end);
  const days = Math.floor((last.getTime() - first.getTime()) / DAY) + 1;
  const width = days <= 15 ? 1 : days <= 105 ? Math.max(7, Math.ceil(days / targetBuckets)) : Math.ceil(days / targetBuckets);
  const result: Bucket[] = [];
  for (let cursor = first; cursor <= last;) {
    const finish = new Date(Math.min(last.getTime(), cursor.getTime() + (width - 1) * DAY));
    const bucketStart = iso(cursor), bucketEnd = iso(finish);
    result.push({ start: bucketStart, end: bucketEnd, label: bucketLabel(bucketStart, bucketEnd), fullLabel: `${bucketStart} to ${bucketEnd}` });
    cursor = new Date(finish.getTime() + DAY);
  }
  return result;
}
export function niceTicks(max: number): number[] {
  if (max <= 0) return [0];
  if (max <= 2) return [0, 1, 2];
  const target = max / 4, magnitude = 10 ** Math.floor(Math.log10(Math.max(target, 1)));
  const scaled = target / magnitude, step = (scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 5 ? 5 : 10) * magnitude;
  const ceiling = Math.ceil(max / step) * step;
  return Array.from({ length: ceiling / step + 1 }, (_, index) => index * step);
}
function todayJohannesburg() {
  const value = new Intl.DateTimeFormat("en", { timeZone: "Africa/Johannesburg", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(new Date());
  const pick = (type: string) => value.find(item => item.type === type)?.value ?? "";
  return `${pick("year")}-${pick("month")}-${pick("day")}`;
}
function minusDays(value: string, days: number) { const date = asDate(value); date.setUTCDate(date.getUTCDate() - days); return iso(date); }
export function rangeLabel(filters: AppliedFilters, groups: UsageMetrics["groups"]) {
  const name = filters.group === "all" ? "All Business Units" : groups.find(group => group.key === filters.group)?.name ?? "Unassigned";
  const sameYear = part(filters.from, "year") === part(filters.to, "year");
  return `${bucketLabel(filters.from, filters.to)}${sameYear ? ` ${part(filters.to, "year")}` : ""} · ${name}`;
}

export default function UsageMetricsChart({ token }: { token: string }) {
  const today = todayJohannesburg();
  const initial = { from: minusDays(today, 89), to: today, group: "all" };
  const [draft, setDraft] = useState<AppliedFilters>(initial);
  const [applied, setApplied] = useState<AppliedFilters>(initial);
  const [metric, setMetric] = useState<UsageMetricKind>("action_items");
  const [data, setData] = useState<UsageMetrics | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(false);
  const [narrow, setNarrow] = useState(false);
  const selected = METRICS.find(item => item.key === metric) ?? METRICS[0];
  useEffect(() => {
    let cancelled = false;
    if (applied.from > applied.to) { setError("Choose an end date on or after the start date."); return; }
    setLoading(true); setError("");
    void getUsageMetrics(token, applied.from, applied.to, metric).then(result => { if (!cancelled) setData(result); }).catch(() => { if (!cancelled) setError("Usage metrics could not be loaded."); }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [applied, metric, token]);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 600px)");
    const update = () => setNarrow(media.matches);
    update(); media.addEventListener("change", update); return () => media.removeEventListener("change", update);
  }, []);
  const groups = data?.groups ?? [], allMode = applied.group === "all";
  const buckets = useMemo(() => makeBuckets(applied.from, applied.to, narrow ? 9 : 12), [applied, narrow]);
  const bars = useMemo(() => {
    if (!data) return [] as { label: string; fullLabel: string; value: number }[];
    if (allMode) return groups.map(item => ({ label: item.name, fullLabel: item.name, value: data.days.reduce((total, day) => total + (day.counts[item.key] ?? 0), 0) }));
    return buckets.map(bucket => ({ label: bucket.label, fullLabel: bucket.fullLabel, value: data.days.filter(day => day.date >= bucket.start && day.date <= bucket.end).reduce((total, day) => total + (day.counts[applied.group] ?? 0), 0) }));
  }, [allMode, applied.group, buckets, data, groups]);
  const total = bars.reduce((sum, bar) => sum + bar.value, 0), ticks = niceTicks(Math.max(0, ...bars.map(bar => bar.value))), ceiling = ticks.at(-1) ?? 0;
  const apply = () => { if (draft.from > draft.to) { setError("Choose an end date on or after the start date."); return; } setApplied({ ...draft }); };
  const showChart = Boolean(data) && !loading && (!allMode ? total > 0 : true);
  return <section className="usage-card" aria-label="Usage Metrics chart">
    <div className="usage-filters" role="group" aria-label="Usage metric filters">
      <label>From<input aria-label="Usage metrics start date" type="date" value={draft.from} max={draft.to} onChange={event => setDraft(value => ({ ...value, from: event.target.value }))} /></label>
      <label>To<input aria-label="Usage metrics end date" type="date" value={draft.to} min={draft.from} onChange={event => setDraft(value => ({ ...value, to: event.target.value }))} /></label>
      <label>Business Unit<select aria-label="Usage metrics Business Unit" value={draft.group} onChange={event => setDraft(value => ({ ...value, group: event.target.value }))}><option value="all">All Business Units</option>{groups.filter(item => item.key !== "unassigned").map(item => <option key={item.key} value={item.key}>{item.name}{item.is_selectable ? "" : " (historical)"}</option>)}<option value="unassigned">Unassigned</option></select></label>
      <button type="button" className="usage-apply" onClick={apply} disabled={loading}>{loading ? "Applying…" : "Apply filters"}</button>
    </div>
    <div className="usage-metric-tabs" aria-label="Metric selection">
      {METRICS.map(item => <button type="button" key={item.key} className={metric === item.key ? "active" : ""} aria-pressed={metric === item.key} onClick={() => { setMetric(item.key); setNotice(""); }}>{item.label}</button>)}
      {UNAVAILABLE.map(item => <button type="button" key={item.label} className="unavailable" onClick={() => setNotice(item.reason)}>{item.label}<span>Unavailable</span></button>)}
    </div>
    {notice && <p className="usage-notice" role="status">{notice}</p>}
    <div className="usage-chart-head"><div><h2>{selected.label}</h2><p>{selected.hint}</p><p className="usage-applied">{rangeLabel(applied, groups)}</p></div><strong className="usage-total">Total: {total} {selected.totalNoun}</strong></div>
    {error ? <p role="alert" className="usage-empty">{error}</p> : !data || loading ? <p className="usage-empty">Loading chart…</p> : !showChart ? <p className="usage-empty">{selected.empty}<span>Total: 0 {selected.totalNoun}</span></p> : <><div className={allMode ? "usage-scroll" : "usage-fit"}><div className="usage-chart" style={{ ["--bar-count" as string]: Math.max(bars.length, 1) }}>
      <div className="usage-axis">{[...ticks].reverse().map(tick => <span key={tick} style={{ bottom: `calc(${(tick / Math.max(ceiling, 1)) * 75}% + 52px)` }}>{tick}</span>)}</div>
      <div className="usage-plot">{ticks.map(tick => <i key={tick} style={{ bottom: `calc(${(tick / Math.max(ceiling, 1)) * 75}% + 52px)` }} />)}{bars.map((bar, index) => <div className="usage-bar-wrap" key={`${bar.fullLabel}-${index}`}><span className="usage-value" hidden={bar.value === 0} style={{ bottom: `calc(${(bar.value / Math.max(ceiling, 1)) * 75}% + 57px)` }}>{bar.value}</span><div className="usage-bar" tabIndex={0} role="img" title={`${bar.fullLabel}: ${bar.value}`} aria-label={`${bar.fullLabel}: ${bar.value}`} style={{ height: `${(bar.value / Math.max(ceiling, 1)) * 75}%` }} /><span className="usage-label" title={bar.fullLabel} tabIndex={0} aria-label={bar.fullLabel}>{bar.label}</span></div>)}</div>
    </div></div></>}
  </section>;
}
