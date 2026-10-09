"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, getApprovedActionItems } from "@/lib/api";
import type { ActionItemFilters, ApprovedActionItemsPage } from "@/lib/types";

const initial: ActionItemFilters = { view: "all", meeting: "", owner: "", deadline: "", offset: 0 };
const controlBase = "rounded-md border px-3 py-2 text-sm focus-visible:outline-2 focus-visible:outline-[#003366]";
const control = `${controlBase} border-gray-300 bg-white`;

export default function ActionItemsClient({ accessToken }: { accessToken: string }) {
  const [filters, setFilters] = useState(initial);
  const [draft, setDraft] = useState({ meeting: "", owner: "", deadline: "" });
  const [result, setResult] = useState<ApprovedActionItemsPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    async function load() {
      setLoading(true);
      setResult(null);
      setError("");
      try {
        const page = await getApprovedActionItems(accessToken, filters, controller.signal);
        if (active) setResult(page);
      } catch (failure) {
        if (active) setError(failure instanceof ApiError ? failure.responseBody : "Unable to load action items. Please try again.");
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => { active = false; controller.abort(); };
  }, [accessToken, filters, refresh]);

  // Hide previous results immediately when navigation/filter/refresh requests change.
  function change(next: ActionItemFilters) { setResult(null); setLoading(true); setFilters(next); }

  const hasAppliedFilters = [filters.meeting, filters.owner, filters.deadline].some(value => value.trim());
  const emptyTitle = filters.offset > 0
    ? "No actions on this page"
    : hasAppliedFilters
    ? "No matching action items"
    : "No approved action items yet";
  const emptyDescription = filters.offset > 0
    ? "This page has no results. Return to the first page to reload this view."
    : hasAppliedFilters
    ? "No approved action items from meetings you can access match your applied filters. Try changing or clearing the filters above."
    : "There are no approved action items from meetings you can access yet. Action items appear here after meeting notes containing extracted action items are approved.";

  return <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div><h1 className="text-2xl font-bold text-[#003366]">Action Items</h1>
        <p className="mt-2 max-w-2xl text-sm text-gray-600">Approved action items from meetings you can access. Review and edit extracted action items in Meeting Detail before approval.</p></div>
      <button className={control} disabled={loading} onClick={() => { setResult(null); setLoading(true); setRefresh(value => value + 1); }}>Refresh</button>
    </div>
    <form aria-label="Filter action items" className="mt-5 grid gap-3 rounded-lg border bg-gray-50 p-4 sm:grid-cols-3" onSubmit={event => { event.preventDefault(); change({ ...filters, ...draft, offset: 0 }); }}>
      {([ ["meeting", "Meeting", "Search meeting title"], ["owner", "Person mentioned in meeting", "Search name or email mentioned"], ["deadline", "Deadline mentioned", "Date or spoken deadline"] ] as const).map(([key, label, placeholder]) =>
        <label key={key} className="flex flex-col gap-1 text-sm font-medium text-gray-700">{label}
          <input className={control} maxLength={255} placeholder={placeholder} value={draft[key]} onChange={event => setDraft({ ...draft, [key]: event.target.value })} />
        </label>)}
      <p className="text-xs text-gray-600 sm:col-span-3">Filters match text, ignoring case. Deadline searches both the date and original spoken deadline.</p>
      <div className="flex gap-2 sm:col-span-3"><button type="submit" className={`${control} font-semibold text-[#003366]`}>Apply filters</button>
        <button type="button" className={control} onClick={() => { setDraft({ meeting: "", owner: "", deadline: "" }); change({ ...initial }); }}>Clear filters</button></div>
    </form>
    <section className="mt-6" aria-label="Approved action items" aria-busy={loading}>
      {loading && <p role="status" className="p-6 text-gray-600">Loading action items…</p>}
      {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800">{error}</div>}
      {result && !result.items.length && <div className="rounded-lg border bg-white px-6 py-10 text-center">
        <div role="status">
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="mx-auto mb-4 h-10 w-10 text-[#003366]">
            <rect x="5" y="4" width="14" height="17" rx="2" />
            <path d="M9 4V2h6v2M8 10l1 1 2-2M13 10h3M8 15l1 1 2-2M13 15h3" />
          </svg>
          <h2 className="text-lg font-semibold text-[#003366]">{emptyTitle}</h2>
          <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-gray-600">{emptyDescription}</p>
        </div>
        {filters.offset > 0
          ? <button className={`${control} mt-4`} onClick={() => change({ ...filters, offset: 0 })}>Return to first page</button>
          : !hasAppliedFilters && <Link className="mt-4 inline-block text-sm font-semibold text-[#003366] underline" href="/">View meetings on Dashboard</Link>}
      </div>}
      {result && result.items.length > 0 && <>
        <p role="status" className="mb-3 text-sm text-gray-600">Showing {filters.offset + 1}–{filters.offset + result.items.length}</p>
        <div className="overflow-x-auto rounded-lg border"><table className="w-full min-w-[760px] text-left text-sm">
          <caption className="sr-only">Approved action items and source evidence</caption>
          <thead className="bg-[#003366] text-white"><tr>{["Task", "Meeting", "Person mentioned in meeting", "Deadline mentioned", "Source evidence"].map(label => <th scope="col" key={label} className="px-4 py-3">{label}</th>)}</tr></thead>
          <tbody>{result.items.map(item => <tr key={item.id} className="border-t even:bg-gray-50">
            <td className="max-w-sm whitespace-pre-wrap break-words px-4 py-4 align-top font-medium">{item.task}</td>
            <td className="px-4 py-4 align-top"><Link className="text-[#003366] underline" href={`/meetings/${encodeURIComponent(item.meeting_id)}`}>{item.meeting_title?.trim() || "Untitled meeting"}</Link></td>
            <td className="px-4 py-4 align-top">{item.owner?.trim() || "Unspecified"}</td>
            <td className="px-4 py-4 align-top">{item.deadline_iso || item.deadline_text?.trim() || "Unspecified"}
              {item.deadline_iso && item.deadline_text && <p className="mt-1 text-xs text-gray-500">As spoken: {item.deadline_text}</p>}</td>
            <td className="max-w-sm px-4 py-4 align-top">{item.source_quote?.trim() ? <details><summary className="cursor-pointer text-[#003366]">View source evidence</summary><blockquote className="mt-2 whitespace-pre-wrap break-words border-l-2 border-[#C9A52C] pl-3">{item.source_quote}</blockquote></details> : "No source evidence provided."}</td>
          </tr>)}</tbody>
        </table></div>
      </>}
      {result && result.items.length > 0 && <div className="mt-4 flex gap-2" aria-label="Pagination">
        <button className={control} disabled={filters.offset === 0} onClick={() => change({ ...filters, offset: Math.max(0, filters.offset - 50) })}>Previous</button>
        <button className={control} disabled={!result.has_more} onClick={() => change({ ...filters, offset: filters.offset + 50 })}>Next</button>
      </div>}
    </section>
  </main>;
}
