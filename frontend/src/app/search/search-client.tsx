"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { MeetingPageHeading, ResultsLoading } from "@/components/meeting-page-feedback";
import { useMeetingPageDraft } from "@/lib/use-meeting-page-draft";
import LocalDateTime from "@/components/local-date-time";
import { ApiError, searchSavedMeetings } from "@/lib/api";
import type { MeetingSearchResult } from "@/lib/types";

const initialDraft = { keyword: "" };

export default function SearchClient({ accessToken, userKey }: { accessToken: string; userKey?: string }) {
  const [draft, setDraft] = useMeetingPageDraft("search", userKey, initialDraft);
  const keyword = draft.keyword;
  const [submitted, setSubmitted] = useState("");
  const [rows, setRows] = useState<MeetingSearchResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  async function search(query = keyword.trim()) {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setRows(null);
    setError("");
    setSubmitted(query);
    setLoading(Boolean(query));
    if (!query) return;
    try {
      const result = await searchSavedMeetings(accessToken, query, controller.signal);
      if (!controller.signal.aborted) setRows(result);
    } catch (failure) {
      if (!controller.signal.aborted) setError(failure instanceof ApiError && [401, 403].includes(failure.status)
        ? failure.responseBody : "Search could not be completed. Please try again.");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  return <main className="mx-auto min-w-0 max-w-5xl px-4 py-8 sm:px-6">
    <MeetingPageHeading page="search" />
    <form aria-label="Search saved meeting content" className="mt-5 flex flex-wrap items-end gap-3" onSubmit={event => { event.preventDefault(); void search(); }}>
      <label className="flex min-w-0 flex-1 flex-col gap-1 text-sm font-medium">Keyword
        <input type="search" maxLength={255} value={keyword} onChange={event => setDraft({ keyword: event.target.value })} className="min-w-0 rounded-md border border-gray-300 px-3 py-2" />
      </label>
      <button type="submit" className="rounded-md bg-[#003366] px-4 py-2 text-sm font-semibold text-white">Search</button>
    </form>
    <section aria-label="Search results" aria-busy={loading} className="mt-6 min-h-64 min-w-0 break-words">
      {loading && <ResultsLoading page="search" />}
      {error && <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-red-800"><p>{error}</p>
        <button className="mt-3 rounded-md border border-red-300 bg-white px-3 py-2 text-sm font-semibold" onClick={() => void search(submitted)}>Try again</button>
      </div>}
      {!loading && !error && rows === null && <p className="rounded-lg border bg-white p-6 text-sm text-gray-600">Enter a keyword to search saved meeting content.</p>}
      {rows !== null && <>
        <p role="status" className="mb-3 text-sm text-gray-600">{rows.length ? `Showing ${rows.length} matching meetings for “${submitted}” (maximum 50).` : "No matching saved meetings."}</p>
        <ul className="space-y-3">{rows.map(row => <li key={row.id} className="rounded-lg border p-4">
          <Link href={`/meetings/${encodeURIComponent(row.id)}`} className="font-semibold text-[#003366] underline">{row.title?.trim() || "Untitled meeting"}</Link>
          <p className="mt-1 text-sm text-gray-600">{row.recorded_at ? <LocalDateTime value={row.recorded_at} /> : "Meeting time unavailable"}</p>
          <p className="mt-1 text-sm">Matched: {[row.matched_summary && "summary", row.matched_action_items && "action items", row.matched_decisions && "decisions"].filter(Boolean).join(" and ")}</p>
        </li>)}</ul>
      </>}
    </section>
  </main>;
}
