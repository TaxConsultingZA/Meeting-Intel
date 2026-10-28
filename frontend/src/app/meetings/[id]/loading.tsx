export default function MeetingDetailLoading() {
  return (
    <main aria-label="Meeting detail loading" aria-busy="true" className="mx-auto max-w-6xl px-6 py-7">
      <p role="status" className="text-sm text-[#6b7280]">Loading meeting details…</p>
      <div aria-hidden="true" className="mt-5 grid gap-4 lg:grid-cols-[280px_minmax(0,1fr)]">
        <div className="h-64 rounded-lg bg-[#e5eaf2] motion-safe:animate-pulse" />
        <div className="h-96 rounded-lg bg-[#e5eaf2] motion-safe:animate-pulse" />
      </div>
    </main>
  );
}
