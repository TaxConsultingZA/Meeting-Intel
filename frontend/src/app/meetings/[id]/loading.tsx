import Link from "next/link";

function LoadingCard({ title, lines = 3 }: { title: string; lines?: number }) {
  return <section aria-label={`${title} loading`} className="overflow-hidden rounded-lg border border-[#dde1e8] bg-white">
    <h2 className="border-b border-[#dde1e8] bg-[#fafbfc] px-4 py-3 text-sm font-semibold text-[#003366]">{title}</h2>
    <div aria-hidden="true" className="space-y-3 p-4 motion-safe:animate-pulse">
      {Array.from({ length: lines }, (_, index) => <div key={index} className={`h-3 rounded bg-[#e5eaf2] ${index === lines - 1 ? "w-2/3" : "w-full"}`} />)}
    </div>
  </section>;
}

export default function MeetingDetailLoading({ showNavigation = true }: { showNavigation?: boolean }) {
  return <>
    {showNavigation && <nav aria-label="Main navigation" className="sticky top-0 z-50 flex min-h-14 flex-wrap items-center gap-x-4 gap-y-2 bg-[#003366] px-4 py-2 text-white shadow-md lg:gap-x-8 lg:px-6">
      <Link href="/" className="flex shrink-0 items-center gap-2.5">
        <span className="flex h-8 w-8 items-center justify-center rounded-md bg-[#C9A52C] text-sm font-extrabold text-[#003366]">MI</span>
        <span className="text-[15px] font-semibold">Tax<span className="text-[#C9A52C]">Consulting</span> SA</span>
      </Link>
      <div className="order-last flex w-full flex-wrap gap-1 lg:order-none lg:w-auto lg:ml-2">
        {[{ href: "/", label: "Dashboard" }, { href: "/action-items", label: "Action Items" }, { href: "/search", label: "Search saved meetings" }].map(link =>
          <Link key={link.href} href={link.href} className="rounded-md px-3.5 py-1.5 text-[13.5px] text-white/70 hover:bg-white/10 hover:text-white">{link.label}</Link>)}
      </div>
    </nav>}
    <main aria-label="Meeting detail loading" aria-busy="true" className="mx-auto max-w-6xl px-6 py-7">
      <Link href="/" className="mb-4 inline-flex text-[13px] text-[#6b7280] hover:text-[#003366]">Back to Dashboard</Link>
      <h1 className="text-xl font-semibold text-[#003366]">Meeting details</h1>
      <p role="status" className="mt-2 text-sm text-[#6b7280]">Loading meeting details…</p>
      <div className="mt-5 grid items-start gap-5 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div className="min-w-0 space-y-4"><LoadingCard title="Meeting information" lines={6} /><LoadingCard title="Recording processing" lines={2} /></div>
        <div className="min-w-0 space-y-4"><LoadingCard title="Decisions" lines={2} /><LoadingCard title="Summary" /><LoadingCard title="Action items" /></div>
      </div>
    </main>
  </>;
}
