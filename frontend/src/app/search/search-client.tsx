"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import LoadingSpinner from "@/components/loading-spinner";
import LocalDateTime from "@/components/local-date-time";
import { searchSavedMeetings } from "@/lib/api";
import type { MeetingSearchResult } from "@/lib/types";

export default function SearchClient({ accessToken }: { accessToken: string }) {
  const [keyword, setKeyword] = useState("");
  const [submitted, setSubmitted] = useState("");
  const [rows, setRows] = useState<MeetingSearchResult[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);

  async function search() {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    const query = keyword.trim();
    setRows(null);
    setError("");
    setSubmitted(query);
    setLoading(Boolean(query));
    if (!query) return;
    try {
      const result = await searchSavedMeetings(accessToken, query, controller.signal);
      if (!controller.signal.aborted) setRows(result);
    } catch {
      if (!controller.signal.aborted) setError("Search could not be completed. Please try again.");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  return <main className="mx-auto max-w-5xl px-6 py-8">
    <h1 className="text-2xl font-bold text-[#003366]">Search saved meetings</h1>
    <p className="mt-2 text-sm text-gray-600">Search saved summaries, action item descriptions and recorded decisions in meetings you can view. Results show up to 50 matching meetings, newest first. Transcripts are excluded.</p>
    <form aria-label="Search saved meeting content" className="mt-5 flex flex-wrap items-end gap-3" onSubmit={event => { event.preventDefault(); void search(); }}>
      <label className="flex flex-1 flex-col gap-1 text-sm font-medium">Keyword
        <input type="search" maxLength={255} value={keyword} onChange={event => setKeyword(event.target.value)} className="rounded-md border border-gray-300 px-3 py-2" />
      </label>
      <button type="submit" className="rounded-md bg-[#003366] px-4 py-2 text-sm font-semibold text-white">Search</button>
    </form>
    <section aria-label="Search results" aria-busy={loading} className="mt-6 min-w-0 break-words">
      {loading && <LoadingSpinner label="Search loading" />}
      {error && <p role="alert" className="text-red-800">{error}</p>}
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
