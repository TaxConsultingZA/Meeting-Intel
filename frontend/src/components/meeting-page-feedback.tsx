import Link from "next/link";

export type MeetingPage = "actions" | "search";
export const meetingPages = {
  actions: {
    title: "Action Items",
    description: "Approved action items from meetings you can access. Task completion is separate from meeting-note approval. Approved wording remains locked.",
    width: "max-w-7xl",
  },
  search: {
    title: "Search saved meetings",
    description: "Search saved summaries, action item descriptions and recorded decisions in meetings you can view. Results show up to 50 matching meetings, newest first. Transcripts are excluded.",
    width: "max-w-5xl",
  },
};

/** Public navigation only: no account data or extra requests before authentication. */
export function MeetingPageNavigation({ page }: { page: MeetingPage }) {
  return <nav aria-label="Main navigation" className="sticky top-0 z-50 flex min-h-14 flex-wrap items-center gap-x-4 gap-y-2 bg-[#003366] px-4 py-2 shadow-md lg:gap-x-8 lg:px-6">
    <Link href="/" className="flex shrink-0 items-center gap-2.5">
      <span className="flex h-8 w-8 items-center justify-center rounded-md bg-[#C9A52C] text-sm font-extrabold text-[#003366]">MI</span>
      <span className="text-[15px] font-semibold text-white">Tax<span className="text-[#C9A52C]">Consulting</span> SA</span>
    </Link>
    <div className="order-last flex w-full flex-wrap gap-1 lg:order-none lg:ml-2 lg:w-auto">
      {[["/", "Dashboard"], ["/action-items", "Action Items"], ["/search", "Search saved meetings"]].map(([href, label]) => {
        const active = href === (page === "actions" ? "/action-items" : "/search");
        return <Link key={href} href={href} aria-current={active ? "page" : undefined} className={`whitespace-nowrap rounded-md px-3.5 py-1.5 text-[13.5px] ${active ? "bg-white/10 text-[#C9A52C]" : "text-white/70 hover:bg-white/10 hover:text-white"}`}>{label}</Link>;
      })}
    </div>
    <span aria-hidden="true" className="ml-auto h-8 w-8 shrink-0 rounded-full bg-white/20" />
  </nav>;
}

export function MeetingPageHeading({ page }: { page: MeetingPage }) {
  const { title, description } = meetingPages[page];
  return <div><h1 className="text-2xl font-bold text-[#003366]">{title}</h1>
    <p className={`mt-2 text-sm text-gray-600 ${page === "actions" ? "max-w-2xl" : ""}`}>{description}</p></div>;
}

export function ResultsLoading({ page, route = false }: { page: MeetingPage; route?: boolean }) {
  return <div role="status" aria-label={page === "actions" ? "Action items loading" : "Search loading"} className="min-h-64 rounded-lg border border-[#dde1e8] bg-white p-4">
    <p className="mb-4 text-sm text-[#003366]">{page === "actions" ? "Loading action items…" : route ? "Loading search…" : "Searching saved meetings…"}</p>
    <div aria-hidden="true" className="space-y-3 motion-safe:animate-pulse">
      {[0, 1, 2].map(row => <div key={row} className="h-12 rounded bg-[#eef1f6]" />)}
    </div>
  </div>;
}

export function MeetingPageLoading({ page }: { page: MeetingPage }) {
  return <><MeetingPageNavigation page={page} />
    <main aria-busy="true" className={`mx-auto min-w-0 ${meetingPages[page].width} px-4 py-8 sm:px-6`}>
      <MeetingPageHeading page={page} />
      <p role="status" className="mt-5 text-sm text-[#003366]">Loading {meetingPages[page].title}…</p>
      <div aria-hidden="true" className={`mt-3 grid gap-3 rounded-lg border bg-gray-50 p-4 ${page === "actions" ? "sm:grid-cols-3" : "sm:grid-cols-[1fr_6rem]"}`}>
        {(page === "actions" ? ["Meeting", "Owner", "Due date"] : ["Keyword"]).map(label => <div key={label} className="text-sm font-medium text-gray-700">{label}<div className="mt-1 h-10 rounded-md border border-gray-300 bg-white" /></div>)}
        <div className="h-9 w-28 self-end rounded-md bg-[#dde1e8]" />
      </div>
      <div className="mt-6"><ResultsLoading page={page} route /></div>
    </main>
  </>;
}
