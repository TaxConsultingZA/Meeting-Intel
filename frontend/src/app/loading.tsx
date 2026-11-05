export default function Loading() {
  return (
    <div aria-label="Dashboard loading" aria-busy="true">
      <p role="status" className="sr-only">Loading Dashboard</p>
      <div aria-hidden="true" className="flex min-h-14 items-center gap-4 bg-[#003366] px-4 py-2 lg:gap-8 lg:px-6">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[#C9A52C] text-sm font-extrabold text-[#003366]">MI</div>
          <span className="font-semibold text-white">Tax<span className="text-[#C9A52C]">Consulting</span> SA</span>
        </div>
        <div className="hidden h-8 w-44 rounded bg-white/10 motion-safe:animate-pulse sm:block" />
        <div className="ml-auto h-8 w-8 rounded-full bg-white/20 motion-safe:animate-pulse" />
      </div>
      <main className="mx-auto max-w-5xl px-6 py-7">
        <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-[22px] font-bold text-[#003366]">Meeting Intelligence</h1>
            <p className="mt-0.5 text-[13.5px] text-[#6b7280]">Review and approve AI-extracted meeting notes before they are emailed to participants.</p>
          </div>
          <div aria-hidden="true" className="h-10 w-44 rounded-md bg-[#dde1e8] motion-safe:animate-pulse" />
        </div>
        <div aria-hidden="true" className="mb-7 grid grid-cols-2 gap-4 sm:grid-cols-4">
          {["Upcoming", "In Progress", "Awaiting Review", "Completed"].map((label) => (
            <div key={label} className="flex items-center gap-3 rounded-lg border border-[#dde1e8] bg-white p-4 shadow-sm">
              <div className="h-10 w-10 shrink-0 rounded-lg bg-[#eef1f6] motion-safe:animate-pulse" />
              <div className="min-w-0">
                <div className="mb-2 h-5 w-10 rounded bg-[#e5eaf2] motion-safe:animate-pulse" />
                <div className="text-xs text-[#6b7280]">{label}</div>
              </div>
            </div>
          ))}
        </div>
        <div aria-hidden="true" className="mb-6 flex flex-wrap border-b-2 border-[#dde1e8]">
          {["Meetings", "Upcoming Meetings", "In Progress", "Awaiting Review", "Old Meetings", "Failed / Cancelled"].map((label) => (
            <span key={label} className={`px-4 py-2.5 text-[13px] font-medium ${label === "Upcoming Meetings" ? "border-b-2 border-[#C9A52C] text-[#003366]" : "text-[#6b7280]"}`}>{label}</span>
          ))}
        </div>
        <div aria-label="Meeting cards loading" className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[0, 1, 2].map((card) => (
            <div key={card} aria-hidden="true" className="min-h-48 overflow-hidden rounded-lg border border-[#dde1e8] bg-white shadow-sm motion-safe:animate-pulse">
              <div className="border-b-[3px] border-[#C9A52C] bg-[#003366] px-4 py-4"><div className="h-4 w-3/4 rounded bg-white/25" /></div>
              <div className="space-y-3 p-4">
                <div className="h-3 w-2/3 rounded bg-[#e5eaf2]" />
                <div className="h-3 w-1/2 rounded bg-[#eef1f6]" />
                <div className="h-3 w-full rounded bg-[#eef1f6]" />
                <div className="h-8 w-24 rounded bg-[#e5eaf2]" />
              </div>
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}
